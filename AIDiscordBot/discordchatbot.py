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

        # Constants for message limits
        self.DISCORD_MESSAGE_LIMIT = 2000  # Discord's message length limit
        self.GEMINI_MAX_INPUT = 30720     # Gemini's input token limit (approximate in characters)
        self.GEMINI_MAX_OUTPUT = 2048     # Keep responses reasonable

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
        history = self.active_conversations.get(channel_id, [])
        
        # If history is too old, clear it
        if history:
            now = datetime.now()
            oldest_allowed = now - timedelta(hours=24)  # Clear history older than 24 hours
            
            if datetime.fromisoformat(history[0].get('timestamp', now.isoformat())) < oldest_allowed:
                history = []
                self.active_conversations[channel_id] = history
        
        return history

    async def add_to_history(self, channel_id: int, role: str, content: str, user_name: str = None):
        """Add a message to the conversation history"""
        if channel_id not in self.active_conversations:
            self.active_conversations[channel_id] = []
        
        history = self.active_conversations[channel_id]
        
        # Clean up the content if it contains repeated name prefixes
        if content and ":" in content:
            # Split by ":" and take the last part to remove any name prefixes
            parts = content.split(":")
            if len(parts) > 1:
                content = parts[-1].strip()
        
        # Format the message in Gemini's expected structure with metadata
        entry = {
            "parts": [{
                "text": content  # Store just the message content
            }],
            "role": "user" if role.lower() == "user" else "model",
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "user_name": user_name if user_name else self.bot.user.display_name,
                "channel_id": str(channel_id)
            }
        }
            
        history.append(entry)
        
        # Keep only the last N messages, but try to keep conversation pairs together
        guild = self.bot.get_channel(channel_id).guild
        max_history = await self.config.guild(guild).max_history()
        
        if len(history) > max_history:
            # Ensure we don't break up a conversation pair
            if len(history) % 2 == 1:
                max_history += 1
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
            "You are a witty and slightly sarcastic Discord bot with a great sense of humor. "
            "While always helpful, you enjoy adding playful banter and clever jokes to your responses. "
            "You're confident but not arrogant, and you love making references to internet culture and memes when appropriate. "
            "Your responses should be a mix of helpfulness and entertainment - think of yourself as a knowledgeable friend "
            "who can't help but crack jokes while helping out. "
            "Only use emojis when they're directly relevant to the conversation or add meaningful context - "
            "prefer wit and wordplay over emoji reactions."
        )

    async def get_bot_personality(self, guild: discord.Guild, channel: discord.TextChannel, user_name: str) -> str:
        """Get the bot's personality and context information"""
        return (
            "You are a helpful and slightly sarcastic Discord bot. "
            "Keep responses concise and entertaining while remaining helpful. "
            "Use emojis sparingly and only when they add value to the conversation. "
            f"You are currently speaking with {user_name} in "
            f"Server: {guild.name}\n"
            f"Channel: #{channel.name}\n"
            f"Channel category: {channel.category.name if channel.category else 'No category'}"
        )

    async def get_channel_info(self, channel: discord.TextChannel) -> str:
        """Get information about the current channel"""
        return (
            f"You are chatting in #{channel.name}\n"
            f"Channel topic: {channel.topic if channel.topic else 'No topic set'}\n"
            f"Channel category: {channel.category.name if channel.category else 'No category'}"
        )

    def _handle_safety_error(self, error_message: str, channel_id: int = None) -> str:
        """Handle safety-related errors from Gemini in a user-friendly way"""
        if "finish_reason: SAFETY" not in error_message:
            return None
            
        # Extract safety ratings
        safety_levels = {
            "NEGLIGIBLE": 0,
            "LOW": 1,
            "MEDIUM": 2,
            "HIGH": 3
        }
        
        highest_category = None
        highest_level = -1
        
        for line in error_message.split('\n'):
            if "category: HARM_CATEGORY_" in line:
                category = line.split("HARM_CATEGORY_")[1].strip()
            elif "probability:" in line:
                level = line.split("probability:")[1].strip()
                level_value = safety_levels.get(level, 0)
                
                if level_value > highest_level:
                    highest_level = level_value
                    highest_category = category

        # If this was a high-risk safety error, clear recent history
        if highest_level >= 2 and channel_id is not None:  # MEDIUM or HIGH risk
            if channel_id in self.active_conversations:
                # Keep only the first few messages to maintain some context
                self.active_conversations[channel_id] = self.active_conversations[channel_id][:2]
        
        if highest_category:
            friendly_category = highest_category.replace("_", " ").title()
            messages = {
                "SEXUALLY_EXPLICIT": "I can't respond to that as it may involve inappropriate content.",
                "HATE_SPEECH": "I can't engage with content that could promote hate or discrimination.",
                "HARASSMENT": "I aim to maintain a respectful environment and can't engage with potentially harmful content.",
                "DANGEROUS_CONTENT": "I can't assist with potentially dangerous or harmful content.",
            }
            return messages.get(highest_category, f"I can't respond to that due to safety concerns regarding {friendly_category}.")
            
        return "I can't respond to that due to safety concerns. Let's keep the conversation friendly and appropriate!"

    def _truncate_message(self, message: str, limit: int) -> str:
        """Truncate message to stay within limits while keeping it readable"""
        if len(message) <= limit:
            return message
            
        # Try to truncate at a sentence boundary
        truncated = message[:limit-4]  # Leave room for ellipsis
        last_sentence = max(
            truncated.rfind('.'),
            truncated.rfind('!'),
            truncated.rfind('?')
        )
        
        if last_sentence > limit * 0.7:  # If we can get a decent amount of content
            return truncated[:last_sentence+1] + "..."
        return truncated + "..."

    def _prepare_prompt(self, message: str, context: str, history: List[dict], current_user: str) -> str:
        """Prepare prompt while respecting Gemini's input limits"""
        # Start with essential components and clear user identification
        prompt_template = (
            "=== Current Message ===\n"
            "Current speaking user: {current_user}\n"
            "User message: {message}\n\n"
            
            "=== Response Guidelines ===\n"
            "1. You are responding directly to {current_user}\n"
            "2. Focus primarily on responding to the current message\n"
            "3. Use conversation history only for maintaining context\n"
            "4. Only reference server/channel/time details if directly relevant\n"
            "5. Keep responses natural and avoid unnecessary references to context\n"
            "6. Never repeat user names or 'meow' multiple times\n"
            "7. Respond directly to {current_user}'s message content\n"
            "8. Keep responses appropriate and friendly\n"
            "9. If unsure about content safety, give a generic response\n"
            "10. Keep responses under {response_limit} characters\n"
            "11. Address {current_user} naturally without constantly repeating their name\n\n"
        )
        
        # Calculate available space
        base_prompt = prompt_template.format(
            message=message,
            current_user=current_user,
            response_limit=self.DISCORD_MESSAGE_LIMIT
        )
        remaining_space = self.GEMINI_MAX_INPUT - len(base_prompt)
        
        # Add context and history if space permits
        if remaining_space > 100:  # Ensure minimum useful space
            history_summary = self._summarize_history(history, current_user)
            context_section = f"=== Background Information ===\n{context}"
            
            # If everything fits, use it all
            if len(history_summary) + len(context_section) <= remaining_space:
                base_prompt = (
                    base_prompt +
                    f"=== Conversation Context ===\n{history_summary}\n\n" +
                    context_section
                )
            else:
                # Prioritize recent context over full history
                if len(context_section) < remaining_space * 0.7:
                    # Use more space for context, less for history
                    context_space = len(context_section)
                    history_space = remaining_space - context_space - 10
                    base_prompt = (
                        base_prompt +
                        f"=== Conversation Context ===\n{self._truncate_message(history_summary, history_space)}\n\n" +
                        context_section
                    )
                else:
                    # Use all space for essential context
                    base_prompt = (
                        base_prompt +
                        f"=== Background Information ===\n{self._truncate_message(context, remaining_space)}"
                    )
        
        return base_prompt

    def _summarize_history(self, history: List[dict], current_user: str = None) -> str:
        """Create a brief summary of the conversation history"""
        if not history:
            return f"This is the start of our conversation with {current_user}."
        
        # Count messages per user
        user_messages = {}
        for entry in history:
            if 'metadata' in entry and 'user_name' in entry['metadata']:
                user = entry['metadata']['user_name']
                user_messages[user] = user_messages.get(user, 0) + 1
        
        # Create summary with emphasis on current user
        summary_parts = []
        for user, count in user_messages.items():
            if user == current_user:
                summary_parts.insert(0, f"{user} (current speaker, {count} messages)")
            else:
                summary_parts.append(f"{user} ({count} messages)")
        
        time_span = ""
        if len(history) >= 2:
            try:
                first_time = datetime.fromisoformat(history[0].get('timestamp', ''))
                last_time = datetime.fromisoformat(history[-1].get('timestamp', ''))
                duration = last_time - first_time
                if duration.total_seconds() < 3600:  # Less than an hour
                    time_span = f"over {int(duration.total_seconds() / 60)} minutes"
                else:
                    time_span = f"over {int(duration.total_seconds() / 3600)} hours"
            except (ValueError, TypeError):
                time_span = ""
        
        topics = self._extract_conversation_topics(history[-5:], current_user)
        
        return (
            f"Ongoing conversation with {', '.join(summary_parts)} {time_span}. "
            f"{topics if topics else ''}"
        )

    def _extract_conversation_topics(self, recent_history: List[dict], current_user: str = None) -> str:
        """Extract main topics from recent messages to maintain context without being too specific"""
        if not recent_history:
            return ""
            
        topics = []
        for entry in recent_history:
            if 'parts' in entry and entry['parts']:
                message = entry['parts'][0].get('text', '')
                user = entry['metadata'].get('user_name', '')
                
                # Extract key nouns or phrases that might be important for context
                if len(message.split()) > 3:  # Only consider substantial messages
                    # Clean the message to avoid any problematic content
                    cleaned_message = message.split(':')[-1].strip()
                    if len(cleaned_message) > 50:
                        cleaned_message = cleaned_message[:50] + "..."
                    
                    # Add user context to the topic
                    if user == current_user:
                        topics.append(f"your previous message: {cleaned_message}")
                    else:
                        topics.append(f"previous topic from {user}: {cleaned_message}")
                    
        if topics:
            return f"Recent topics: {topics[-1]}"
        return ""

    async def process_message(self, message: str, context: str, history: List[dict], channel_id: int = None, user_name: str = None, user_mention: str = None) -> str:
        """Process a single message through Gemini"""
        try:
            # Format history for better context
            formatted_history = []
            for entry in history[-5:]:  # Only use last 5 messages for context
                if 'parts' in entry and entry['parts']:
                    message_text = entry['parts'][0].get('text', '')
                    entry_user = entry['metadata'].get('user_name', '')
                    # Make it clear when we're referencing the current user's messages
                    if entry_user == user_name:
                        formatted_text = f"You ({user_name}): {message_text}"
                    else:
                        formatted_text = f"{entry_user}: {message_text}"
                    
                    formatted_history.append({
                        "role": entry["role"],
                        "parts": [{"text": formatted_text}]
                    })
            
            chat = self.model.start_chat(history=formatted_history)
            
            # Prepare prompt with length limits and user context
            prompt = self._prepare_prompt(message, context, history, user_name)
            
            try:
                response = chat.send_message(prompt)
                # Ensure response fits Discord limits and properly mentions user
                response_text = self._truncate_message(response.text, self.DISCORD_MESSAGE_LIMIT)
                # Replace the first occurrence of the user's name with their mention
                if user_name in response_text and user_mention:
                    response_text = response_text.replace(user_name, user_mention, 1)
                return response_text
            except Exception as e:
                error_str = str(e)
                friendly_error = self._handle_safety_error(error_str, channel_id)
                if friendly_error:
                    return friendly_error
                    
                if "blocked" in error_str.lower():
                    return f"I can't process that message, {user_mention}. Let's keep our conversation friendly!"
                elif "quota" in error_str.lower():
                    return f"I've hit my rate limit. Please try again in a moment, {user_mention}!"
                else:
                    print(f"Gemini Error: {error_str}")
                    return f"I encountered an issue processing your message, {user_mention}. Could you try rephrasing it?"
                    
        except Exception as e:
            print(f"Unexpected Error: {str(e)}")
            return f"I ran into an unexpected problem, {user_mention}. Please try again!"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for messages that mention the bot"""
        if message.author.bot or not message.guild:
            return

        # Check if the bot is mentioned
        if self.bot.user in message.mentions:
            typing_task = None
            try:
                # Add to typing channels before starting the task
                self.typing_channels.add(message.channel.id)
                typing_task = asyncio.create_task(self.maintain_typing(message.channel))
                
                # Get user's display name (nickname if set, otherwise display name)
                user_name = message.author.nick or message.author.display_name
                # Store the mention format for proper Discord mentions
                user_mention = message.author.mention

                # Check if API is configured
                if not self.model:
                    if not await self.initialize():
                        await message.reply(f"Please ask an admin to set up my API key using the `[p]chatbot setapikey` command, {user_mention}")
                        return

                # Check if bot is enabled in this guild
                enabled = await self.config.guild(message.guild).enabled()
                if not enabled:
                    await message.reply(f"Sorry {user_mention}, I'm currently disabled in this server.")
                    return

                # Check rate limit
                if await self.check_rate_limit(message.channel.id):
                    await message.reply(f"I'm receiving too many messages! Please wait a moment before trying again, {user_mention}")
                    return

                # Remove bot mention and split into questions
                user_message = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
                questions = self.split_into_questions(user_message)

                # Get conversation history and personality with time context
                history = await self.get_conversation_history(message.channel.id)
                personality = await self.get_bot_personality(message.guild, message.channel, user_name)

                # Process each question
                responses = []
                for question in questions:
                    response = await self.process_message(
                        message=question,
                        context=personality,
                        history=history,
                        channel_id=message.channel.id,
                        user_name=user_name,
                        user_mention=user_mention
                    )
                    if "safety concerns" in response.lower():
                        continue
                    responses.append(response)
                    
                    # Add to history only if it wasn't a safety error
                    await self.add_to_history(message.channel.id, "user", question, user_name)
                    await self.add_to_history(message.channel.id, "assistant", response, self.bot.user.display_name)

                # Combine responses intelligently
                final_response = "\n\n".join(responses) if responses else f"I can't process that message, {user_mention}. Let's try a different topic!"

                # Update rate limit
                if message.channel.id not in self.rate_limits:
                    self.rate_limits[message.channel.id] = []
                self.rate_limits[message.channel.id].append(datetime.now().isoformat())

                # Send response
                await message.reply(final_response)

            except Exception as e:
                error_msg = f"An unexpected error occurred: {str(e)}"
                await message.reply(f"{error_msg}, {user_mention}")
            
            finally:
                # Clean up typing indicator
                if message.channel.id in self.typing_channels:
                    self.typing_channels.remove(message.channel.id)
                if typing_task and not typing_task.done():
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass

    async def maintain_typing(self, channel: discord.TextChannel):
        """Maintain typing indicator while processing"""
        try:
            while channel.id in self.typing_channels:
                async with channel.typing():
                    await asyncio.sleep(1)  # Shorter sleep time for more responsive typing
        except Exception as e:
            print(f"Error in typing indicator: {e}")
        finally:
            if channel.id in self.typing_channels:
                self.typing_channels.remove(channel.id)

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
