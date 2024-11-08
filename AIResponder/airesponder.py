from redbot.core import commands, Config
from redbot.core.bot import Red
from typing import Optional
import logging
import asyncio

from .core.deep_infra import DeepInfraModel
from .utils.config import ConfigManager
from .utils.errors import AIResponderError, ConfigError
from .memory.conversation import ConversationManager
from .agents.manager import AgentManager
from .tools.manager import ToolManager
from .responses import ResponseFormatter, ResponseValidator, RateLimiter, ResponseChunker

log = logging.getLogger("red.airesponder")

class AIResponder(commands.Cog):
    """AI Assistant cog for Red Discord bot."""
    
    def __init__(self, bot: Red):
        """Initialize the cog."""
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=987654321,
            force_registration=True,
            cog_name="AIResponder"
        )
        
        # Register global defaults first
        defaults = {
            "api_key": None,
            "model_name": "meta-llama/Llama-3.2-11B-Vision-Instruct",
            "max_history": 10,
            "history_expiry_hours": 24,
            "disabled_channels": [],
            "disabled_servers": [],
            "rate_limit_requests": 5,
            "rate_limit_burst": 2,
            "rate_limit_cooldown": 30,
            "max_response_chunks": 5,
            "tool_configs": {}
        }
        self.config.register_global(**defaults)
        
        # Now create config manager with initialized config
        self.config_manager = ConfigManager(self.config)
        self.model: Optional[DeepInfraModel] = None
        self.conversation_manager: Optional[ConversationManager] = None
        self.tool_manager: Optional[ToolManager] = None
        self.agent_manager: Optional[AgentManager] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.formatter = ResponseFormatter()
        self.validator = ResponseValidator()
        self.rate_limiter = RateLimiter()
        self.chunker = ResponseChunker()
        
    async def initialize(self) -> None:
        """Initialize the cog."""
        await self.config_manager.initialize()
        api_key = await self.config_manager.get_api_key()
        max_history = await self.config_manager.get_max_history()
        
        if not api_key:
            log.warning("No API key configured for AIResponder")
            return
            
        try:
            self.model = DeepInfraModel(api_key)
            await self.model.initialize()
            
            self.conversation_manager = ConversationManager(max_history=max_history)
            self.tool_manager = ToolManager(self.bot)
            await self.tool_manager.initialize_tools()
            
            self.agent_manager = AgentManager(self.model, self.tool_manager)
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        except Exception as e:
            log.error(f"Failed to initialize: {e}")
            self.model = None

    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired conversations."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run cleanup every hour
                if self.conversation_manager:
                    await self.conversation_manager.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in cleanup loop: {e}")

    async def cog_unload(self) -> None:
        """Called when the cog is unloaded."""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        if self.tool_manager:
            await self.tool_manager.cleanup_tools()
        if self.model:
            await self.model.cleanup()

    @commands.group(name="air")
    @commands.admin_or_permissions(administrator=True)
    async def air(self, ctx: commands.Context):
        """AI Responder configuration commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @air.command(name="setkey")
    async def air_setkey(self, ctx: commands.Context, api_key: str):
        """Set the API key for the AI model."""
        try:
            await self.config_manager.set_api_key(api_key)
            await ctx.send("API key updated successfully.")
            await self.initialize()
        except ConfigError as e:
            await ctx.send(f"Error setting API key: {str(e)}")

    @air.command(name="clearhistory")
    async def air_clearhistory(self, ctx: commands.Context):
        """Clear your conversation history with the bot."""
        if self.conversation_manager:
            await self.conversation_manager.clear_conversation(
                ctx.author.id,
                ctx.channel.id
            )
            await ctx.send("Your conversation history has been cleared.")
        else:
            await ctx.send("Conversation manager is not initialized.")

    @air.command(name="togglechannel")
    async def air_togglechannel(self, ctx: commands.Context):
        """Toggle AI responses in the current channel."""
        try:
            is_disabled = await self.config_manager.toggle_channel(ctx.channel.id)
            status = "disabled" if is_disabled else "enabled"
            await ctx.send(f"AI responses are now {status} in this channel.")
        except ConfigError as e:
            await ctx.send(f"Error toggling channel: {str(e)}")

    @air.command(name="setmodel")
    async def air_setmodel(self, ctx: commands.Context, model_name: str):
        """Set the AI model to use."""
        try:
            await self.config_manager.set_model_name(model_name)
            await ctx.send(f"Model updated to: {model_name}")
            await self.initialize()
        except ConfigError as e:
            await ctx.send(f"Error setting model: {str(e)}")

    @air.command(name="status")
    async def air_status(self, ctx: commands.Context):
        """Show the current status of the AI responder."""
        model_name = await self.config_manager.get_model_name()
        rate_limits = await self.config_manager.get_rate_limit_config()
        
        status = [
            "**AI Responder Status**",
            f"Model: {model_name}",
            f"Initialized: {self.model is not None}",
            f"Rate Limits: {rate_limits['requests']}/min (burst: {rate_limits['burst']})",
            f"Tools Loaded: {len(self.tool_manager.get_all_tools()) if self.tool_manager else 0}"
        ]
        
        await ctx.send("\n".join(status))

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle mentions in messages."""
        if message.author.bot:
            return
            
        if self.bot.user not in message.mentions:
            return
            
        if await self.config_manager.is_channel_disabled(message.channel.id):
            return
            
        if not self.model or not self.conversation_manager:
            await message.channel.send("AI responder is not properly configured.")
            return
            
        if not await self.rate_limiter.acquire(message.author.id):
            retry_after = await self.rate_limiter.get_retry_after(message.author.id)
            await message.channel.send(
                f"You're sending messages too quickly! Please wait {retry_after:.1f} seconds."
            )
            return
            
        try:
            await self.conversation_manager.add_message(
                message.author.id,
                message.channel.id,
                message.content,
                "user"
            )
            
            history = await self.conversation_manager.get_conversation_history(
                message.author.id,
                message.channel.id
            )
            
            current_response = ""
            async for response_chunk in self.agent_manager.process_message(
                message.content,
                history
            ):
                current_response += response_chunk
                
            is_valid, error_message = await self.validator.validate(current_response)
            if not is_valid:
                await message.channel.send(f"Error: {error_message}")
                return
                
            formatted_response = self.formatter.format_response(current_response)
            
            async for chunk in self.chunker.chunk_response(formatted_response):
                await message.channel.send(chunk)
                
            await self.conversation_manager.add_message(
                message.author.id,
                message.channel.id,
                current_response,
                "assistant"
            )
            
        except AIResponderError as e:
            await message.channel.send(f"Error: {str(e)}")
            log.error(f"AIResponder error: {e}")
        except Exception as e:
            await message.channel.send("An unexpected error occurred.")
            log.error(f"Unexpected error in AIResponder: {e}")
