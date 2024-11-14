from typing import Optional, Dict, Any, List
from discord import TextChannel, Guild, Member, Role, ChannelType
from . import AIResponderTool, ToolRegistry
from ..utils.errors import ToolError
from datetime import datetime
import json

@ToolRegistry.register
class ServerInfo(AIResponderTool):
    """Tool for retrieving Discord server information."""
    
    name = "server_info"
    description = "Get detailed information about the current Discord server"
    
    def __init__(self, bot=None):
        super().__init__(bot)
        
    async def initialize(self) -> None:
        """Initialize server info tool."""
        pass

    def _run(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError("This tool only supports async operation")
        
    async def _arun(self, guild_id: str) -> str:
        if not self.bot:
            raise ToolError(self.name, "Bot instance required")
            
        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return "Server not found or not accessible"
                
            # Collect server statistics
            text_channels = len([c for c in guild.channels if isinstance(c, TextChannel)])
            voice_channels = len([c for c in guild.channels if c.type == ChannelType.voice])
            categories = len([c for c in guild.channels if c.type == ChannelType.category])
            
            # Get verification level
            verification = str(guild.verification_level).capitalize()
            
            # Format creation date
            created_at = guild.created_at.strftime("%Y-%m-%d")
            
            # Build response
            info = [
                "**Server Information:**",
                f"📝 Name: {guild.name}",
                f"👥 Members: {guild.member_count}",
                f"📅 Created: {created_at}",
                f"🔒 Verification Level: {verification}",
                "",
                "**Channels:**",
                f"💬 Text Channels: {text_channels}",
                f"🔊 Voice Channels: {voice_channels}",
                f"📁 Categories: {categories}",
                "",
                f"👑 Roles: {len(guild.roles)}",
                f"😀 Emojis: {len(guild.emojis)}",
                f"🚀 Boost Level: {guild.premium_tier}"
            ]
            
            if guild.description:
                info.insert(2, f"ℹ️ Description: {guild.description}")
                
            return "\n".join(info)
            
        except Exception as e:
            raise ToolError(self.name, f"Error retrieving server info: {str(e)}")

@ToolRegistry.register
class ChannelHistory(AIResponderTool):
    """Tool for retrieving channel message history."""
    
    name = "channel_history"
    description = "Get recent message history from a Discord channel"
    
    def __init__(self, bot=None):
        super().__init__(bot)
        
    async def initialize(self) -> None:
        """Initialize channel history tool."""
        pass

    def _run(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError("This tool only supports async operation")
        
    async def _arun(self, channel_id: str, limit: int = 5) -> str:
        if not self.bot:
            raise ToolError(self.name, "Bot instance required")
            
        try:
            # Validate input
            if not 1 <= limit <= 50:
                return "Invalid limit: Must be between 1 and 50 messages"
                
            channel = self.bot.get_channel(int(channel_id))
            if not isinstance(channel, TextChannel):
                return "Channel not found or not accessible"
                
            messages = []
            async for message in channel.history(limit=100):  # Fetch extra to account for bot messages
                if len(messages) >= limit:
                    break
                    
                if not message.author.bot:  # Skip bot messages
                    timestamp = message.created_at.strftime("%Y-%m-%d %H:%M")
                    content = message.content or "[No content]"
                    
                    # Handle attachments
                    if message.attachments:
                        content += f" [+{len(message.attachments)} attachment(s)]"
                        
                    # Format message
                    messages.append(
                        f"[{timestamp}] {message.author.display_name}: {content}"
                    )
                    
            if not messages:
                return "No recent messages found in this channel"
                
            return "**Recent Messages:**\n" + "\n".join(messages)
            
        except Exception as e:
            raise ToolError(self.name, f"Error retrieving channel history: {str(e)}")
