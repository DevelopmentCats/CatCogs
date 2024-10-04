import aiohttp
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from typing import Dict, List
import asyncio
from datetime import datetime, timedelta
import json
from asyncio import Queue

class AIResponder(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_global = {
            "api_url": "http://localhost:11434/api/generate",
            "model": "llama2",
            "max_tokens": 300,
            "enabled_channels": [],
            "custom_personality": "You are a helpful AI assistant.",
            "api_timeout": 300,  # Increased default timeout to 5 minutes
        }
        self.config.register_global(**default_global)
        self.user_cooldowns: Dict[int, datetime] = {}
        self.user_history: Dict[int, List[Dict[str, str]]] = {}
        self.request_queue: Queue = Queue()
        self.processing_lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.mentions:
            return

        if self.bot.user in message.mentions:
            enabled_channels = await self.config.enabled_channels()
            if not enabled_channels or message.channel.id in enabled_channels:
                await self.request_queue.put(message)
                await self.process_queue()

    @commands.cooldown(1, 30, commands.BucketType.user)
    async def respond_to_mention(self, message: discord.Message):
        if not await self.check_rate_limit(message.author.id):
            await message.channel.send("You're using the AI too frequently. Please wait a moment before trying again.")
            return

        content = message.content.replace(self.bot.user.mention, "").strip()
        if not content:
            await message.channel.send("You mentioned me, but didn't ask anything. How can I help you?")
            return

        async with message.channel.typing():
            try:
                custom_personality = await self.config.custom_personality()
                recent_messages = await self.get_recent_messages(message.channel)
                user_history = self.get_user_history(message.author.id)

                full_prompt = (
                    f"System: You are {self.bot.user.name}, an AI assistant in the Discord server '{message.guild.name}', "
                    f"channel '#{message.channel.name}'. Respond to users in a helpful, friendly, and context-aware manner.\n\n"
                    f"Instructions:\n"
                    f"1. Use Discord formatting: **bold** for emphasis, *italic* for subtle emphasis, "
                    f"__underline__ for titles, ~~strikethrough~~ for corrections, `code` for short snippets, "
                    f"and ```language\ncode block\n``` for longer code snippets.\n"
                    f"2. Use emojis sparingly to convey emotion when appropriate.\n"
                    f"3. To mention the user you're responding to, use: <@{message.author.id}>\n"
                    f"4. Keep responses concise and under 2000 characters when possible.\n"
                    f"5. Always start your response by mentioning the user who asked the question.\n"
                    f"6. Do not provide code-related answers unless specifically requested in the user's question.\n"
                    f"7. If asked about coding or programming without a specific request for code, provide conceptual explanations instead.\n\n"
                    f"Recent conversation context:\n{recent_messages}\n\n"
                    f"User conversation history:\n{user_history}\n\n"
                    f"Custom personality: {custom_personality}\n\n"
                    f"Human: {content}\n\n"
                    f"AI: Respond to the human's message, addressing them directly using their mention tag. "
                    f"Take into account the context and instructions provided above, especially regarding code-related responses."
                )
                
                api_timeout = await self.config.api_timeout()
                response = await asyncio.wait_for(self.get_ai_response(full_prompt), timeout=api_timeout)

                self.update_user_history(message.author.id, content, response)

                if len(response) > 2000:
                    pages = [page for page in pagify(response, delims=["\n", " "], page_length=1990)]
                    await menu(message.channel, pages, DEFAULT_CONTROLS)
                else:
                    await message.channel.send(response)
            except asyncio.TimeoutError:
                await message.channel.send(f"I'm taking longer than expected to respond (timeout: {api_timeout} seconds). Please try again later or contact an administrator.")
            except Exception as e:
                await message.channel.send("I encountered an unexpected issue while processing your request. Please try again later.")
                self.bot.logger.error(f"Error in AI response: {str(e)}")

    async def check_rate_limit(self, user_id: int) -> bool:
        if await self.bot.is_owner(discord.Object(id=user_id)):
            return True
        
        now = datetime.now()
        if user_id in self.user_cooldowns:
            if now - self.user_cooldowns[user_id] < timedelta(seconds=10):
                return False
        self.user_cooldowns[user_id] = now
        return True

    async def get_ai_response(self, prompt: str) -> str:
        api_url = await self.config.api_url()
        model = await self.config.model()
        max_tokens = await self.config.max_tokens()
        api_timeout = await self.config.api_timeout()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                }, timeout=api_timeout) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise Exception(f"API request failed with status {resp.status}. Error: {error_text}")
                
                    response = ""
                    async for line in resp.content:
                        if line:
                            data = json.loads(line)
                            if 'response' in data:
                                response += data['response']
                
                    return response.strip() or "I apologize, but I couldn't generate a response to that."
        except asyncio.TimeoutError:
            raise Exception(f"I'm taking longer than expected to respond (timeout: {api_timeout} seconds). Please try again later.")
        except aiohttp.ClientError as e:
            self.bot.logger.error(f"Error connecting to Ollama API: {str(e)}")
            raise Exception(f"I'm having trouble connecting to my knowledge base. Please try again later.")

    @commands.group()
    @commands.is_owner()
    async def airesponder(self, ctx: commands.Context):
        """Configure the AI Responder cog."""
        pass

    @airesponder.command()
    async def setapiurl(self, ctx: commands.Context, url: str):
        """Set the Ollama API URL."""
        if not url.startswith(("http://", "https://")):
            await ctx.send("Invalid URL. Please provide a valid HTTP or HTTPS URL.")
            return
        await self.config.api_url.set(url)
        await ctx.send(f"Ollama API URL set to: {url}")

    @airesponder.command()
    async def setmodel(self, ctx: commands.Context, model: str = None):
        """Set the AI model to use or list available models."""
        api_url = await self.config.api_url()
        models_url = f"{api_url.rsplit('/', 2)[0]}/api/tags"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(models_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        available_models = [m['name'] for m in data['models']]
                        
                        if not model:
                            await ctx.send(f"Available models: {', '.join(available_models)}")
                            return
                        
                        if model in available_models:
                            await self.config.model.set(model)
                            await ctx.send(f"AI model set to: {model}")
                        else:
                            await ctx.send(f"Model '{model}' not found. Available models: {', '.join(available_models)}")
                    else:
                        await ctx.send(f"Failed to fetch available models. Status: {resp.status}")
            except Exception as e:
                await ctx.send(f"Error fetching models: {str(e)}")

    @airesponder.command()
    async def setmaxtokens(self, ctx: commands.Context, max_tokens: int):
        """Set the maximum number of tokens for the AI response."""
        if max_tokens < 1 or max_tokens > 2048:
            await ctx.send("Invalid token count. Please choose a number between 1 and 2048.")
            return
        await self.config.max_tokens.set(max_tokens)
        await ctx.send(f"Maximum tokens set to: {max_tokens}")

    @airesponder.command()
    async def enable(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Enable the AI responder in a specific channel or the current channel."""
        channel = channel or ctx.channel
        async with self.config.enabled_channels() as channels:
            if channel.id not in channels:
                channels.append(channel.id)
        await ctx.send(f"AI responder enabled in {channel.mention}")

    @airesponder.command()
    async def disable(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Disable the AI responder in a specific channel or the current channel."""
        channel = channel or ctx.channel
        async with self.config.enabled_channels() as channels:
            if channel.id in channels:
                channels.remove(channel.id)
        await ctx.send(f"AI responder disabled in {channel.mention}")

    @airesponder.command()
    async def settings(self, ctx: commands.Context):
        """Display current AI responder settings."""
        api_url = await self.config.api_url()
        model = await self.config.model()
        max_tokens = await self.config.max_tokens()
        enabled_channels = await self.config.enabled_channels()
        api_timeout = await self.config.api_timeout()
        custom_personality = await self.config.custom_personality()

        embed = discord.Embed(title="AI Responder Settings", color=discord.Color.blue())
        embed.add_field(name="API URL", value=api_url, inline=False)
        embed.add_field(name="Model", value=model, inline=False)
        embed.add_field(name="Max Tokens", value=max_tokens, inline=False)
        embed.add_field(name="API Timeout", value=f"{api_timeout} seconds", inline=False)
        embed.add_field(name="Enabled Channels", value=", ".join([f"<#{c}>" for c in enabled_channels]) or "None", inline=False)
        embed.add_field(name="Custom Personality", value=custom_personality, inline=False)

        await ctx.send(embed=embed)

    @airesponder.command()
    async def testapi(self, ctx: commands.Context):
        """Test the connection to the Ollama API."""
        try:
            api_url = await self.config.api_url()
            model = await self.config.model()
            
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json={
                    "model": model,
                    "prompt": "Hello, this is a test.",
                    "stream": False,
                }) as resp:
                    if resp.status == 200:
                        response = ""
                        async for line in resp.content:
                            if line:
                                data = json.loads(line)
                                if 'response' in data:
                                    response += data['response']
                        await ctx.send(f"API test successful. Response: {box(response.strip())}")
                    else:
                        error_text = await resp.text()
                        await ctx.send(f"API test failed. Status: {resp.status}, Error: {error_text}")
        except Exception as e:
            await ctx.send(f"API test failed: {str(e)}")

    @airesponder.command()
    async def setpersonality(self, ctx: commands.Context, *, personality: str):
        """Set a custom AI personality/prompt."""
        await self.config.custom_personality.set(personality)
        await ctx.send(f"Custom AI personality set to: {personality}")

    @commands.command()
    async def aihelp(self, ctx: commands.Context):
        """Get help on how to use the AI responder."""
        help_text = (
            "**AI Responder Help**\n\n"
            "To use the AI responder, simply mention the bot and ask your question. For example:\n"
            f"{self.bot.user.mention} What is the capital of France?\n\n"
            "The AI will then respond to your question.\n\n"
            "**Additional Information:**\n"
            "- The AI responder may be enabled only in specific channels. Ask an admin if you're unsure where it can be used.\n"
            "- There's a cooldown period between uses to prevent spam.\n"
            "- Admins can configure various aspects of the AI responder using the `airesponder` command group.\n\n"
            "For more information, contact a server administrator."
        )
        await ctx.send(help_text)

    @airesponder.command()
    async def settimeout(self, ctx: commands.Context, timeout: int):
        """Set the API timeout in seconds."""
        if timeout < 60 or timeout > 600:
            await ctx.send("Invalid timeout. Please choose a number between 60 and 600 seconds.")
            return
        await self.config.api_timeout.set(timeout)
        await ctx.send(f"API timeout set to: {timeout} seconds")

    async def get_recent_messages(self, channel: discord.TextChannel, limit: int = 5) -> str:
        messages = []
        async for msg in channel.history(limit=limit):
            if msg.author == self.bot.user:
                messages.append(f"Bot: {msg.content}")
            else:
                messages.append(f"{msg.author.name}: {msg.content}")
        return "\n".join(reversed(messages))

    def get_user_history(self, user_id: int) -> str:
        if user_id not in self.user_history:
            return "No previous conversation."
        return "\n".join([f"User: {item['user']}\nAI: {item['ai']}" for item in self.user_history[user_id]])

    def update_user_history(self, user_id: int, user_message: str, ai_response: str):
        if user_id not in self.user_history:
            self.user_history[user_id] = []
        self.user_history[user_id].append({"user": user_message, "ai": ai_response})
        self.user_history[user_id] = self.user_history[user_id][-3:]  # Keep only the last 3 interactions

    @commands.command()
    async def ai(self, ctx: commands.Context, *, question: str):
        """Ask the AI a question without mentioning the bot."""
        message = ctx.message
        message.content = f"{self.bot.user.mention} {question}"
        await self.respond_to_mention(message)

    @commands.command()
    async def aicontext(self, ctx: commands.Context):
        """Display the current AI context for the user."""
        user_history = self.get_user_history(ctx.author.id)
        recent_messages = await self.get_recent_messages(ctx.channel)
        
        embed = discord.Embed(title="AI Context", color=discord.Color.blue())
        embed.add_field(name="Recent Channel Messages", value=recent_messages[:1000] + "..." if len(recent_messages) > 1000 else recent_messages, inline=False)
        embed.add_field(name="Your Conversation History", value=user_history[:1000] + "..." if len(user_history) > 1000 else user_history, inline=False)
        
        await ctx.send(embed=embed)

    @commands.command()
    async def aiclear(self, ctx: commands.Context):
        """Clear your AI conversation history."""
        if ctx.author.id in self.user_history:
            del self.user_history[ctx.author.id]
        await ctx.send("Your AI conversation history has been cleared.")

    async def process_queue(self):
        if self.processing_lock.locked():
            return

        async with self.processing_lock:
            while not self.request_queue.empty():
                message = await self.request_queue.get()
                await self.respond_to_mention(message)

async def setup(bot: Red):
    await bot.add_cog(AIResponder(bot))
