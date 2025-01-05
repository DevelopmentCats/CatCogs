import asyncio
from typing import Dict, List, Optional
import google.generativeai as genai
from redbot.core import commands, Config
from discord.ext import commands as dpy_commands
import discord
import re
from datetime import datetime, timedelta
import pytz

class DiscordChatBot(commands.Cog):
    """A sophisticated chat bot using Google's Gemini AI"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        
        default_global = {
            "api_key": None  # Gemini API key
        }
        
        default_guild = {
            "max_history": 10,  # Maximum number of messages to keep in history
            "enabled": True,  # Toggle for enabling/disabling the bot
            "rate_limit": 5,  # Messages per minute
            "max_response_time": 30,  # Maximum seconds to wait for response
            "timezone": 'America/Chicago'  # Default timezone
        }

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

        # Store active conversations and rate limiting
        self.active_conversations: Dict[int, List[dict]] = {}
        self.rate_limits: Dict[int, List[datetime]] = {}
        self.typing_channels: set = set()
        self.model = None

        # Discord markdown formatting guide for the AI
        self.discord_formatting = """
Discord Text Formatting Guide:
- Bold: **text**
- Italic: *text* or _text_
- Bold Italic: ***text***
- Underline: __text__
- Strikethrough: ~~text~~
- Code block: ```language
code
```
- Inline code: `text`
- Quote: > text
- Spoiler: ||text||
- Bullet points: • text
- Numbered list: 1. text
- Emoji: Use Discord emoji format :emoji_name:
- User mention: Just use their display name, no special formatting needed
- Channel mention: #channel-name
"""

    async def initialize(self):
        """Initialize the Gemini API with the stored key"""
        api_key = await self.config.api_key()
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-pro')
            return True
        return False

    def split_into_questions(self, text: str) -> List[str]:
        """Split a message into multiple questions/statements"""
        # Split by question marks, periods, or exclamation marks followed by space
        splits = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s for s in splits if s]

    async def get_conversation_history(self, channel_id: int) -> List[dict]:
        """Get conversation history for a channel"""
        return self.active_conversations.get(channel_id, [])

    async def add_to_history(self, channel_id: int, role: str, content: str, user_name: str = None):
        """Add a message to the conversation history"""
        if channel_id not in self.active_conversations:
            self.active_conversations[channel_id] = []
        
        history = self.active_conversations[channel_id]
        entry = {
            "role": role, 
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        if user_name:
            entry["user_name"] = user_name
            
        history.append(entry)
        
        # Keep only the last N messages
        guild = self.bot.get_channel(channel_id).guild
        max_history = await self.config.guild(guild).max_history()
        if len(history) > max_history:
            history = history[-max_history:]
        
        self.active_conversations[channel_id] = history

    async def check_rate_limit(self, channel_id: int) -> bool:
        """Check if the channel has hit rate limit"""
        now = datetime.now()
        if channel_id not in self.rate_limits:
            self.rate_limits[channel_id] = []

        # Remove old timestamps
        self.rate_limits[channel_id] = [
            t for t in self.rate_limits[channel_id] 
            if now - datetime.fromisoformat(t) < timedelta(minutes=1)
        ]

        guild = self.bot.get_channel(channel_id).guild
        rate_limit = await self.config.guild(guild).rate_limit()
        return len(self.rate_limits[channel_id]) >= rate_limit

    async def get_current_time_info(self, guild_id: int) -> str:
        """Get formatted time information based on guild's timezone"""
        guild = self.bot.get_guild(guild_id)
        timezone = await self.config.guild(guild).timezone()
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)
        
        return (
            f"Current time: {now.strftime('%Y-%m-%d %I:%M %p %Z')}\n"
            f"Day of week: {now.strftime('%A')}\n"
            f"Date: {now.strftime('%B %d, %Y')}"
        )

    def get_bot_info(self) -> str:
        """Get information about the bot itself"""
        return (
            f"Your name is {self.bot.user.display_name}. "
            f"You are a Discord bot with the ID {self.bot.user.id}. "
            "You should refer to yourself by your display name when relevant. "
            "You are helpful, friendly, and knowledgeable about Discord formatting. "
            "You can use Discord markdown to format your messages for better readability."
        )

    async def get_channel_info(self, channel: discord.TextChannel) -> str:
        """Get information about the current channel"""
        return (
            f"You are chatting in #{channel.name}\n"
            f"Channel topic: {channel.topic if channel.topic else 'No topic set'}\n"
            f"Channel category: {channel.category.name if channel.category else 'No category'}"
        )

    async def get_bot_personality(self, guild: discord.Guild, channel: discord.TextChannel, user_name: str) -> str:
        """Generate bot personality based on server context and current time"""
        server_info = (
            f"Server name: {guild.name}\n"
            f"Member count: {guild.member_count}\n"
            f"Server description: {guild.description if guild.description else 'No description'}\n"
        )
        
        time_info = await self.get_current_time_info(guild.id)
        channel_info = await self.get_channel_info(channel)
        bot_info = self.get_bot_info()
        
        return (
            f"{bot_info}\n\n"
            f"You are currently talking to {user_name}. Always refer to them by this name.\n\n"
            f"Time Context:\n{time_info}\n\n"
            f"Server Context:\n{server_info}\n"
            f"Channel Context:\n{channel_info}\n\n"
            f"Formatting Guide:\n{self.discord_formatting}\n\n"
            "Remember to:\n"
            "1. Use appropriate Discord formatting in your responses\n"
            "2. Keep responses friendly and conversational\n"
            "3. Use appropriate emoji occasionally\n"
            "4. Reference the current time when relevant\n"
            "5. Always refer to users by their display name\n"
            "6. Format code blocks with the appropriate language syntax highlighting"
        )

    async def process_message(self, message: str, context: str, history: List[dict]) -> str:
        """Process a single message through Gemini"""
        try:
            chat = self.model.start_chat(history=history)
            response = chat.send_message(
                f"{context}\n\nUser message: {message}"
            )
            return response.text
        except Exception as e:
            return f"I encountered an error processing your message: {str(e)}"

    async def maintain_typing(self, channel: discord.TextChannel):
        """Maintain typing indicator while processing"""
        while channel.id in self.typing_channels:
            try:
                async with channel.typing():
                    await asyncio.sleep(5)
            except:
                break

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages that mention the bot"""
        if message.author.bot or not message.guild:
            return

        # Check if the bot is mentioned
        if self.bot.user in message.mentions:
            # Check if API is configured
            if not self.model:
                if not await self.initialize():
                    await message.reply("Please ask an admin to set up my API key using the `[p]chatbot setapikey` command.")
                    return

            # Check if bot is enabled in this guild
            enabled = await self.config.guild(message.guild).enabled()
            if not enabled:
                await message.reply("Sorry, I'm currently disabled in this server.")
                return

            # Check rate limit
            if await self.check_rate_limit(message.channel.id):
                await message.reply("I'm receiving too many messages! Please wait a moment before trying again.")
                return

            # Start typing indicator
            self.typing_channels.add(message.channel.id)
            typing_task = asyncio.create_task(self.maintain_typing(message.channel))

            try:
                # Get user's display name (nickname if set, otherwise display name)
                user_name = message.author.nick or message.author.display_name

                # Remove bot mention and split into questions
                user_message = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
                questions = self.split_into_questions(user_message)

                # Get conversation history and personality with time context
                history = await self.get_conversation_history(message.channel.id)
                personality = await self.get_bot_personality(message.guild, message.channel, user_name)

                # Process each question
                responses = []
                for question in questions:
                    response = await self.process_message(question, personality, history)
                    responses.append(response)
                    
                    # Add to history
                    await self.add_to_history(message.channel.id, "user", question, user_name)
                    await self.add_to_history(message.channel.id, "assistant", response, self.bot.user.display_name)

                # Combine responses intelligently
                final_response = "\n\n".join(responses) if len(responses) > 1 else responses[0]

                # Update rate limit
                self.rate_limits[message.channel.id].append(datetime.now().isoformat())

                # Send response
                await message.reply(final_response)

            except Exception as e:
                await message.reply(f"I encountered an unexpected error: {str(e)}")
            
            finally:
                # Stop typing indicator
                self.typing_channels.remove(message.channel.id)
                typing_task.cancel()

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def chatbot(self, ctx: commands.Context):
        """Commands to manage the chat bot"""
        pass

    @chatbot.command()
    @commands.is_owner()
    async def setapikey(self, ctx: commands.Context, api_key: str):
        """Set the Gemini API key (owner only)
        
        Get your API key from: https://makersuite.google.com/app/apikey"""
        # Delete the message to hide the API key
        try:
            await ctx.message.delete()
        except:
            pass

        await self.config.api_key.set(api_key)
        if await self.initialize():
            await ctx.send("API key set and validated successfully! I'm ready to chat.")
        else:
            await ctx.send("Failed to initialize with the provided API key. Please check if it's valid.")

    @chatbot.command()
    async def maxhistory(self, ctx: commands.Context, amount: int):
        """Set the maximum number of messages to keep in conversation history"""
        if amount < 1 or amount > 50:
            await ctx.send("Please choose a number between 1 and 50")
            return
            
        await self.config.guild(ctx.guild).max_history.set(amount)
        await ctx.send(f"Maximum conversation history set to {amount} messages")

    @chatbot.command()
    async def ratelimit(self, ctx: commands.Context, messages_per_minute: int):
        """Set the rate limit (messages per minute)"""
        if messages_per_minute < 1 or messages_per_minute > 60:
            await ctx.send("Please choose a number between 1 and 60")
            return
            
        await self.config.guild(ctx.guild).rate_limit.set(messages_per_minute)
        await ctx.send(f"Rate limit set to {messages_per_minute} messages per minute")

    @chatbot.command()
    async def timezone(self, ctx: commands.Context, timezone_name: str):
        """Set the timezone for the server (e.g., 'America/New_York')"""
        try:
            pytz.timezone(timezone_name)
            await self.config.guild(ctx.guild).timezone.set(timezone_name)
            time_info = await self.get_current_time_info(ctx.guild.id)
            await ctx.send(f"Timezone set to {timezone_name}\n\n{time_info}")
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(f"Invalid timezone. Please use a valid timezone name (e.g., 'America/New_York', 'Europe/London')")

    @chatbot.command()
    async def toggle(self, ctx: commands.Context):
        """Toggle the chat bot on/off"""
        current = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not current)
        state = "enabled" if not current else "disabled"
        await ctx.send(f"Chat bot is now {state}")

    @chatbot.command()
    async def clearhistory(self, ctx: commands.Context):
        """Clear conversation history for this server"""
        if ctx.channel.id in self.active_conversations:
            del self.active_conversations[ctx.channel.id]
        await ctx.send("Conversation history cleared!")

async def setup(bot):
    cog = DiscordChatBot(bot)
    await bot.add_cog(cog)
    await cog.initialize()
