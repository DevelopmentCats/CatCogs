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

    async def initialize(self) -> bool:
        """Initialize the Gemini API client"""
        try:
            api_key = await self.config.api_key()
            if not api_key:
                print("No API key configured")
                return False
                
            genai.configure(api_key=api_key)
            
            # Configure model with enhanced capabilities
            generation_config = {
                "temperature": 0.9,
                "top_p": 1,
                "top_k": 1,
                "max_output_tokens": 2048,
            }
            
            safety_settings = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE"
                },
            ]
            
            # Use Gemini-Pro model with math capabilities
            self.model = genai.GenerativeModel(
                model_name="gemini-pro",
                generation_config=generation_config,
                safety_settings=safety_settings
            )
            
            print("Successfully initialized Gemini API")
            return True
            
        except Exception as e:
            print(f"Error initializing Gemini API: {str(e)}")
            return False

    def split_into_questions(self, text: str) -> List[str]:
        """Split a message into multiple questions/statements"""
        # Split by question marks, periods, or exclamation marks followed by space
        splits = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s for s in splits if s]

    async def get_conversation_history(self, channel_id: int, current_user: str = None) -> List[dict]:
        """Get conversation history with proper user context"""
        if channel_id not in self.active_conversations:
            return []
            
        history = self.active_conversations[channel_id]
        
        # Filter out old messages (older than 24 hours)
        current_time = datetime.now()
        history = [
            msg for msg in history
            if (current_time - datetime.fromisoformat(msg['metadata']['timestamp'])).total_seconds() < 86400
        ]
        
        # Only include messages from the current conversation context
        if current_user:
            filtered_history = []
            for msg in history[-10:]:  # Look at last 10 messages
                msg_user = msg['metadata'].get('user_name', '')
                
                # Include messages if they're from the current user or responses to them
                if msg_user == current_user or (
                    filtered_history and 
                    filtered_history[-1]['metadata'].get('user_name') == current_user
                ):
                    filtered_history.append(msg)
            history = filtered_history[-5:]  # Keep last 5 relevant messages
        else:
            history = history[-5:]  # Keep last 5 messages if no specific user
            
        return history

    def _clean_message(self, message: str) -> str:
        """Clean message content by removing unwanted prefixes and formatting"""
        if not message:
            return ""
        # Fix regex flag positioning - move (?i) to start
        message = re.sub(r'(?i)^meow:\s*', '', message.strip())
        return message.strip()

    async def add_to_history(self, channel_id: int, role: str, message: str, user_name: str = None) -> None:
        """Add a message to the conversation history"""
        if channel_id not in self.active_conversations:
            self.active_conversations[channel_id] = []
            
        # Clean the message before storing
        clean_message = self._clean_message(message)
            
        # Map role to valid Gemini roles
        gemini_role = "user" if role.lower() == "user" else "model"
            
        # Add metadata to help with context
        entry = {
            "role": gemini_role,  # Only use "user" or "model" for Gemini
            "parts": [{"text": clean_message}],
            "metadata": {
                "user_name": user_name,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        self.active_conversations[channel_id].append(entry)
        
        # Cleanup old messages (older than 24 hours)
        current_time = datetime.now()
        self.active_conversations[channel_id] = [
            msg for msg in self.active_conversations[channel_id]
            if (current_time - datetime.fromisoformat(msg['metadata']['timestamp'])).total_seconds() < 86400
        ]

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

    def _prepare_prompt(self, message: str, context: str, history: List[dict], current_user: str) -> str:
        """Prepare prompt while respecting Gemini's input limits"""
        # Start with essential components and clear user identification
        prompt_template = (
            "=== Current User ===\n"
            "You are talking to: {current_user}\n"
            "IMPORTANT: Only mention and respond to the current user above.\n\n"
            
            "=== Your Capabilities ===\n"
            "You are powered by Google's Gemini-Pro AI model and can:\n\n"
            
            "1. Mathematical & Scientific Abilities:\n"
            "   - Perform complex calculations and mathematical reasoning\n"
            "   - Solve equations and mathematical problems\n"
            "   - Explain scientific concepts and theories\n"
            "   - Work with statistics and data analysis\n\n"
            
            "2. Programming & Technical:\n"
            "   - Write, explain, and debug code in multiple languages\n"
            "   - Provide technical explanations and documentation\n"
            "   - Help with software architecture and design\n"
            "   - Explain technical concepts clearly\n\n"
            
            "3. Language & Communication:\n"
            "   - Engage in natural conversations\n"
            "   - Help with writing and editing\n"
            "   - Explain complex topics simply\n"
            "   - Assist with language learning\n\n"
            
            "4. Analysis & Problem Solving:\n"
            "   - Break down complex problems\n"
            "   - Provide step-by-step explanations\n"
            "   - Offer multiple perspectives\n"
            "   - Help with decision-making\n\n"
            
            "5. Knowledge & Information:\n"
            "   - Share knowledge about various topics\n"
            "   - Explain historical events and concepts\n"
            "   - Discuss current affairs (up to training cutoff)\n"
            "   - Provide educational assistance\n\n"
            
            "When responding:\n"
            "- Show detailed work for calculations\n"
            "- Provide clear explanations\n"
            "- Use appropriate formatting\n"
            "- Double-check accuracy\n"
            "- Stay within ethical boundaries\n\n"
            
            "=== Response Length Requirements ===\n"
            "CRITICAL: Your response MUST be less than {response_limit} characters. Do not exceed this limit.\n"
            "If you need to provide a long explanation:\n"
            "1. Focus on the most important points\n"
            "2. Be concise and clear\n"
            "3. Break into multiple messages if necessary\n"
            "4. Never truncate mid-sentence\n\n"
            
            "=== Current Message ===\n"
            "User message: {message}\n\n"
            
            "=== Response Guidelines ===\n"
            "1. You are ONLY responding to {current_user}\n"
            "2. Focus on the current message\n"
            "3. Keep responses natural and conversational\n"
            "4. Never mention other users from history\n"
            "5. Keep responses appropriate and friendly\n"
            "6. If unsure about content safety, give a generic response\n"
            "7. IMPORTANT: Keep your response under {response_limit} characters\n\n"
        )
        
        # Calculate available space
        base_prompt = prompt_template.format(
            message=message,
            current_user=current_user,
            response_limit=self.DISCORD_MESSAGE_LIMIT
        )
        
        return base_prompt

    async def process_message(self, message: str, context: str, history: List[dict], channel_id: int = None, user_name: str = None, user_mention: str = None) -> str:
        """Process a single message through Gemini"""
        try:
            # Get history specific to current user
            user_history = await self.get_conversation_history(channel_id, user_name)
            
            # Format history for better context
            formatted_history = []
            for entry in user_history:  # Only use user-specific history
                if 'parts' in entry and entry['parts']:
                    message_text = entry['parts'][0].get('text', '')
                    entry_user = entry['metadata'].get('user_name', '')
                    
                    # Clean the message text
                    message_text = self._clean_message(message_text)
                    
                    # Format message based on who sent it
                    if entry_user == user_name:
                        formatted_text = f"You: {message_text}"
                    else:
                        formatted_text = f"Assistant: {message_text}"
                    
                    formatted_history.append({
                        "role": entry.get("role", "user"),  # Ensure valid role
                        "parts": [{"text": formatted_text}]
                    })
            
            try:
                chat = self.model.start_chat(history=formatted_history)
            except Exception as e:
                print(f"Error starting chat: {str(e)}")
                chat = self.model.start_chat(history=[])  # Start fresh if history causes issues
            
            # Clean the current message
            clean_message = self._clean_message(message)
            
            # Prepare prompt with length limits and user context
            prompt = self._prepare_prompt(clean_message, context, user_history, user_name)
            
            try:
                response = chat.send_message(prompt)
                response_text = self._clean_message(response.text)
                
                # Check if response exceeds Discord limit
                if len(response_text) >= self.DISCORD_MESSAGE_LIMIT:
                    print(f"Warning: Response exceeded length limit ({len(response_text)} chars)")
                    return f"I generated a response that was too long ({len(response_text)} characters). Let me try again with a more concise answer, {user_mention}."
                
                # Replace the first occurrence of the user's name with their mention
                if user_name in response_text and user_mention:
                    response_text = response_text.replace(user_name, user_mention, 1)
                return response_text
                
            except Exception as e:
                error_str = str(e)
                print(f"Gemini Error: {error_str}")
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

                # Remove bot mention and clean the message
                user_message = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
                user_message = self._clean_message(user_message)

                # Get conversation history and personality with time context
                history = await self.get_conversation_history(message.channel.id)
                personality = await self.get_bot_personality(message.guild, message.channel, user_name)

                # Process the entire message as one query
                response = await self.process_message(
                    message=user_message,
                    context=personality,
                    history=history,
                    channel_id=message.channel.id,
                    user_name=user_name,
                    user_mention=user_mention
                )
                
                if "safety concerns" not in response.lower():
                    # Add to history only if it wasn't a safety error
                    await self.add_to_history(message.channel.id, "user", user_message, user_name)
                    await self.add_to_history(message.channel.id, "assistant", response, self.bot.user.display_name)

                    # Update rate limit
                    if message.channel.id not in self.rate_limits:
                        self.rate_limits[message.channel.id] = []
                    self.rate_limits[message.channel.id].append(datetime.now().isoformat())

                    # Clean and send response
                    final_response = self._clean_message(response)
                    await message.reply(final_response)
                else:
                    await message.reply(f"I can't process that message, {user_mention}. Let's try a different topic!")

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
