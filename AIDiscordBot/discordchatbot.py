import asyncio
from typing import Dict, List, Optional
import google.generativeai as genai
from redbot.core import commands, Config
from discord.ext import commands as dpy_commands
import discord
import re
from datetime import datetime, timezone, timedelta
import pytz
from googleapiclient.discovery import build

class DiscordChatBot(commands.Cog):
    """A sophisticated chat bot using Google's Gemini AI"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        
        default_global = {
            "api_key": None,         # Gemini API key
            "search_api_key": None,  # Google Custom Search API key
            "search_engine_id": None # Custom Search Engine ID
        }
        
        default_guild = {
            "max_history": 10,      # Maximum number of messages to keep in history
            "enabled": True,        # Toggle for enabling/disabling the bot
            "rate_limit": 5,        # Messages per minute
            "max_response_time": 30, # Maximum seconds to wait for response
            "timezone": 'America/Chicago', # Default timezone
            "search_enabled": True  # Toggle for web search capability
        }

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

        # Store active conversations and rate limiting
        self.active_conversations: Dict[int, List[dict]] = {}
        self.rate_limits: Dict[int, List[datetime]] = {}
        self.typing_channels: set = set()
        self.model = None
        self.search_service = None
        
        # Constants
        self.DISCORD_MESSAGE_LIMIT = 2000
        self.RATE_LIMIT_MAX = 25  # Maximum messages per time window
        self.RATE_LIMIT_MINUTES = 5  # Time window in minutes
        self.GEMINI_MAX_INPUT = 30720     # Gemini's input token limit (approximate in characters)
        self.GEMINI_MAX_OUTPUT = 2048     # Keep responses reasonable

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

    async def initialize(self) -> bool:
        """Initialize the Gemini API client"""
        try:
            api_key = await self.config.api_key()
            if not api_key:
                print("No API key configured")
                return False
                
            genai.configure(api_key=api_key)
            
            # Initialize search service if credentials are available
            search_api_key = await self.config.search_api_key()
            if search_api_key:
                self.search_service = build("customsearch", "v1", developerKey=search_api_key)
            
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
            if now - datetime.fromisoformat(t) < timedelta(minutes=self.RATE_LIMIT_MINUTES)
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

    async def should_perform_search(self, message: str) -> bool:
        """Determine if a message might benefit from web search using Gemini's analysis"""
        try:
            analysis_prompt = f"""
            You are an AI assistant analyzing if a message requires current or factual information from the web.
            
            Message to analyze: "{message}"
            
            Analyze ONLY if this message would significantly benefit from current web information.
            Consider:
            1. Need for current events, prices, or real-time data
            2. Request for facts that may be outdated in training data
            3. Questions about recent changes, updates, or trends
            4. Need for current comparisons or statistics
            5. Queries about ongoing events or developments
            
            IMPORTANT:
            - Only return 'true' if web data would SIGNIFICANTLY improve the response
            - Return 'false' for general knowledge, opinions, or conversational queries
            - Respond with ONLY 'true' or 'false', nothing else
            """

            chat = self.model.start_chat(history=[])
            response = await asyncio.to_thread(
                lambda: chat.send_message(analysis_prompt).text.strip().lower()
            )
            
            return response == 'true'

        except Exception as e:
            print(f"Error in search analysis: {str(e)}")
            return False

    def _prepare_prompt(self, message: str, context: str, history: List[dict], current_user: str, search_results: str = "") -> str:
        """Prepare prompt while respecting Gemini's input limits"""
        # Get current time in both UTC and local time
        current_utc = datetime.now(timezone.utc)
        current_local = datetime.now()
        
        # Start with essential components and clear user identification
        prompt_template = (
            "=== Current Date and Time ===\n"
            "IMPORTANT - Current Time Information:\n"
            "UTC: {utc_time}\n"
            "Local: {local_time}\n"
            "You MUST be aware of this time context when responding.\n\n"
            
            "=== Current User ===\n"
            "You are talking to: {current_user}\n"
            "IMPORTANT: Only mention and respond to the current user above.\n\n"
            
            "{web_search}"
            
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
            "- Stay within ethical boundaries\n"
            "- Consider the current time when discussing events\n"
            "- If web search results are provided:\n"
            "  * Use them to enhance but not dominate your response\n"
            "  * Blend them naturally with your knowledge\n"
            "  * Maintain your conversational style\n\n"
            
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
            "7. IMPORTANT: Keep your response under {response_limit} characters\n"
            "8. ALWAYS consider the current date/time when discussing time-sensitive topics\n\n"
        )
        
        # Add web search section if results exist
        web_search_section = ""
        if search_results:
            web_search_section = (
                "=== Current Web Information ===\n"
                "Use this current information to enhance your response while maintaining your conversational style:\n"
                f"{search_results}\n\n"
            )
        
        # Format times as ISO format with timezone info
        utc_time_str = current_utc.isoformat()
        local_time_str = current_local.isoformat()
        
        # Calculate available space
        base_prompt = prompt_template.format(
            message=message,
            current_user=current_user,
            response_limit=self.DISCORD_MESSAGE_LIMIT,
            web_search=web_search_section,
            utc_time=utc_time_str,
            local_time=local_time_str
        )
        
        return base_prompt

    async def process_message(self, message: str, context: str, history: List[dict], channel_id: int = None, user_name: str = None, user_mention: str = None) -> str:
        """Process a single message through Gemini"""
        try:
            # Get history specific to current user
            user_history = await self.get_conversation_history(channel_id, user_name)
            
            # Check if search might be helpful
            search_context = ""
            if channel_id:
                guild = self.bot.get_channel(channel_id).guild
                search_enabled = await self.config.guild(guild).search_enabled()
                if search_enabled and await self.should_perform_search(message):
                    search_results = await self.perform_web_search(message)
                    if search_results:
                        search_context = search_results
            
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
            
            # Prepare prompt using the original template with search results
            prompt = self._prepare_prompt(
                message=clean_message,
                context=context,
                history=user_history,
                current_user=user_name,
                search_results=search_context
            )
            
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

    async def perform_web_search(self, query: str, num_results: int = 3) -> str:
        """Perform a web search and return formatted results"""
        try:
            if not self.search_service:
                return ""

            search_engine_id = await self.config.search_engine_id()
            if not search_engine_id:
                return ""

            result = self.search_service.cse().list(
                q=query,
                cx=search_engine_id,
                num=num_results
            ).execute()

            search_results = []
            for item in result.get('items', []):
                search_results.append({
                    'title': item['title'],
                    'snippet': item['snippet'],
                    'link': item['link']
                })

            if search_results:
                formatted_results = "Here's relevant information from the web:\n\n"
                for res in search_results:
                    formatted_results += f"Source: {res['title']}\n"
                    formatted_results += f"Summary: {res['snippet']}\n"
                    formatted_results += f"URL: {res['link']}\n\n"
                return formatted_results
            return ""

        except Exception as e:
            print(f"Search error: {str(e)}")
            return ""

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

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def chatbot(self, ctx: commands.Context):
        """
        Gemini AI Chatbot Commands
        
        This is a powerful AI chatbot powered by Google's Gemini-Pro model.
        Simply mention the bot (@BotName) to start chatting!
        
        Configuration Commands:
        - setapikey: Set the Gemini API key (Admin only)
        - toggle: Enable/disable the bot
        - personality: View or set the bot's personality
        - reset: Reset conversation history
        - clearrate: Clear rate limit counters
        
        Search Configuration:
        - searchkey: Set Google Custom Search API key (Admin only)
        - searchid: Set Google Custom Search Engine ID (Admin only)
        - togglesearch: Enable/disable web search capability
        
        Status Commands:
        - status: Check bot's current status
        - settings: View current settings
        """
        # Only send help if no subcommand was invoked
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🤖 Gemini AI Chatbot Help",
                description="Here are all available commands:",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="📝 Basic Usage",
                value="Simply mention the bot (@BotName) to start chatting!",
                inline=False
            )
            
            embed.add_field(
                name="⚙️ Configuration Commands",
                value="`setapikey` - Set Gemini API key (Admin)\n"
                      "`toggle` - Enable/disable bot\n"
                      "`personality` - Set bot personality\n"
                      "`reset` - Reset conversation\n"
                      "`clearrate` - Clear rate limits",
                inline=False
            )
            
            embed.add_field(
                name="🔍 Search Configuration",
                value="`searchkey` - Set Search API key (Admin)\n"
                      "`searchid` - Set Search Engine ID (Admin)\n"
                      "`togglesearch` - Enable/disable search",
                inline=False
            )
            
            embed.add_field(
                name="📊 Status Commands",
                value="`status` - Check bot status\n"
                      "`settings` - View current settings",
                inline=False
            )
            
            embed.add_field(
                name="ℹ️ Detailed Help",
                value="Use `~chatbot <command>` for detailed help on each command\n"
                      "Example: `~chatbot personality`",
                inline=False
            )
            
            await ctx.send(embed=embed)

    @chatbot.command()
    @commands.is_owner()
    async def setapikey(self, ctx: commands.Context, api_key: str):
        """
        Set the Gemini API key (Admin only)
        
        Usage: [p]chatbot setapikey <your_api_key>
        Example: [p]chatbot setapikey AIzaSyXXXXXXXXXXXXXXXXXXXXXX
        
        Get your API key from: https://makersuite.google.com/app/apikey
        """
        # Delete the message to hide the API key
        try:
            await ctx.message.delete()
        except:
            pass
        
        await self.config.api_key.set(api_key)
        await self.initialize()  # Reinitialize with new key
        await ctx.send("API key has been set! I'm ready to chat. 🤖")

    @chatbot.command()
    @commands.admin_or_permissions(administrator=True)
    async def searchkey(self, ctx: commands.Context, api_key: str):
        """
        Set the Google Custom Search API key (Admin only)
        
        Usage: [p]chatbot searchkey <your_api_key>
        Example: [p]chatbot searchkey AIzaSyXXXXXXXXXXXXXXXXXXXXXX
        
        Get your API key from: https://console.cloud.google.com/apis/credentials
        """
        try:
            await ctx.message.delete()
        except:
            pass
        
        await self.config.search_api_key.set(api_key)
        await ctx.send("Search API key has been set! 🔍")

    @chatbot.command()
    @commands.admin_or_permissions(administrator=True)
    async def searchid(self, ctx: commands.Context, engine_id: str):
        """
        Set the Google Custom Search Engine ID (Admin only)
        
        Usage: [p]chatbot searchid <your_engine_id>
        Example: [p]chatbot searchid 123456789:abcdefghijk
        
        Get your Search Engine ID from: https://programmablesearchengine.google.com/
        """
        await self.config.search_engine_id.set(engine_id)
        await ctx.send("Search Engine ID has been set! 🔍")

    @chatbot.command()
    @commands.admin_or_permissions(administrator=True)
    async def togglesearch(self, ctx: commands.Context):
        """
        Toggle web search capability for this server
        
        Usage: [p]chatbot togglesearch
        
        This will enable/disable the bot's ability to search the web for current information.
        Requires both Search API key and Engine ID to be set.
        """
        current = await self.config.guild(ctx.guild).search_enabled()
        await self.config.guild(ctx.guild).search_enabled.set(not current)
        status = "enabled" if not current else "disabled"
        await ctx.send(f"Web search has been {status} for this server! 🔍")

    @chatbot.command()
    @commands.admin_or_permissions(administrator=True)
    async def toggle(self, ctx: commands.Context):
        """
        Toggle the bot on/off for this server
        
        Usage: [p]chatbot toggle
        
        This will enable/disable the bot's response to mentions in this server.
        """
        current = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not current)
        status = "enabled" if not current else "disabled"
        await ctx.send(f"I have been {status} for this server! 🤖")

    @chatbot.command()
    async def personality(self, ctx: commands.Context, *, new_personality: str = None):
        """
        View or set the bot's personality for this channel
        
        Usage: 
        - View current: [p]chatbot personality
        - Set new: [p]chatbot personality <description>
        
        Example: [p]chatbot personality You are a helpful and friendly AI assistant
        """
        if new_personality is None:
            current = await self.config.channel(ctx.channel).personality()
            if not current:
                await ctx.send("I'm currently using my default personality! 😊")
            else:
                await ctx.send(f"My current personality is: {current}")
        else:
            await self.config.channel(ctx.channel).personality.set(new_personality)
            await ctx.send("My personality has been updated! 😊")

    @chatbot.command()
    async def reset(self, ctx: commands.Context):
        """
        Reset the conversation history for this channel
        
        Usage: [p]chatbot reset
        
        This will clear all stored message history for this channel.
        """
        await self.config.channel(ctx.channel).history.set([])
        await ctx.send("Conversation history has been reset! 🔄")

    @chatbot.command()
    @commands.admin_or_permissions(administrator=True)
    async def clearrate(self, ctx: commands.Context):
        """
        Clear rate limit counters for this channel (Admin only)
        
        Usage: [p]chatbot clearrate
        
        This will reset the rate limit counters, useful if the bot gets stuck.
        """
        if ctx.channel.id in self.rate_limits:
            del self.rate_limits[ctx.channel.id]
        await ctx.send("Rate limit counters have been cleared! ⚡")

    @chatbot.command()
    async def status(self, ctx: commands.Context):
        """
        Check the bot's current status
        
        Usage: [p]chatbot status
        
        Shows:
        - API connection status
        - Search capability status
        - Current rate limits
        - Bot enabled/disabled state
        """
        # Check API status
        api_key = await self.config.api_key()
        api_status = "✅ Connected" if (self.model and api_key) else "❌ Not connected"
        
        # Check search status
        search_key = await self.config.search_api_key()
        search_id = await self.config.search_engine_id()
        search_enabled = await self.config.guild(ctx.guild).search_enabled()
        search_status = "✅ Ready" if (search_key and search_id and search_enabled) else "❌ Not configured"
        
        # Check bot status
        enabled = await self.config.guild(ctx.guild).enabled()
        bot_status = "✅ Enabled" if enabled else "❌ Disabled"
        
        # Get rate limit info
        rate_count = len(self.rate_limits.get(ctx.channel.id, [])) if ctx.channel.id in self.rate_limits else 0
        
        status_embed = discord.Embed(
            title="🤖 Bot Status",
            color=discord.Color.blue()
        )
        
        # Add API key info if admin
        if await self.bot.is_owner(ctx.author):
            api_key_truncated = f"{api_key[:6]}...{api_key[-4:]}" if api_key else "Not Set"
            status_embed.add_field(
                name="🔑 API Key",
                value=f"`{api_key_truncated}`",
                inline=True
            )
        
        status_embed.add_field(name="🤖 Bot State", value=bot_status, inline=True)
        status_embed.add_field(name="🔌 API Status", value=api_status, inline=True)
        status_embed.add_field(name="🔍 Search Status", value=search_status, inline=True)
        status_embed.add_field(
            name="⚡ Rate Limits", 
            value=f"{rate_count}/{self.RATE_LIMIT_MAX} messages in {self.RATE_LIMIT_MINUTES}min window", 
            inline=True
        )
        
        await ctx.send(embed=status_embed)

    @chatbot.command()
    async def settings(self, ctx: commands.Context):
        """
        View current settings for this server/channel
        
        Usage: [p]chatbot settings
        
        Shows:
        - Bot enabled/disabled state
        - Search enabled/disabled state
        - Current personality
        - Rate limit settings
        """
        # Get current settings
        enabled = await self.config.guild(ctx.guild).enabled()
        search_enabled = await self.config.guild(ctx.guild).search_enabled()
        personality = await self.config.channel(ctx.channel).personality()
        
        settings_embed = discord.Embed(
            title="⚙️ Current Settings",
            color=discord.Color.green()
        )
        settings_embed.add_field(
            name="Bot Status",
            value="✅ Enabled" if enabled else "❌ Disabled",
            inline=True
        )
        settings_embed.add_field(
            name="Web Search",
            value="✅ Enabled" if search_enabled else "❌ Disabled",
            inline=True
        )
        settings_embed.add_field(
            name="Personality",
            value=personality if personality else "Default",
            inline=False
        )
        settings_embed.add_field(
            name="Rate Limits",
            value=f"Max {self.RATE_LIMIT_MAX} messages per {self.RATE_LIMIT_MINUTES} minutes",
            inline=True
        )
        
        await ctx.send(embed=settings_embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle incoming messages"""
        if message.author.bot or not message.guild:
            return

        # Get the bot's user
        bot_user = self.bot.user
        if not bot_user:
            return

        # Check if bot was mentioned
        was_mentioned = bot_user.mentioned_in(message)
        bot_mention = f'<@{bot_user.id}>'
        starts_with_mention = message.content.startswith(bot_mention)

        # Only respond to mentions
        if not (was_mentioned or starts_with_mention):
            return

        # Get clean message content
        clean_content = message.clean_content.replace(f'@{bot_user.display_name}', '').strip()
        if not clean_content:
            return

        # Check if API is configured
        if not self.model:
            if not await self.initialize():
                await message.reply(f"Please ask an admin to set up my API key using the `[p]chatbot setapikey` command, {message.author.mention}")
                return

        # Check if bot is enabled in this guild
        enabled = await self.config.guild(message.guild).enabled()
        if not enabled:
            await message.reply(f"Sorry {message.author.mention}, I'm currently disabled in this server.")
            return

        # Check rate limit
        if await self.check_rate_limit(message.channel.id):
            await message.reply(f"I'm receiving too many messages! Please wait a moment before trying again, {message.author.mention}")
            return

        async with message.channel.typing():
            try:
                # Get user's display name and mention
                user_name = message.author.display_name
                user_mention = message.author.mention

                # Get conversation history and personality
                history = await self.get_conversation_history(message.channel.id)
                personality = await self.get_bot_personality(message.guild, message.channel, user_name)

                # Check if search is needed and get search results
                search_context = ""
                if await self.config.guild(message.guild).search_enabled():
                    if await self.should_perform_search(clean_content):
                        search_results = await self.perform_web_search(clean_content)
                        if search_results:
                            search_context = search_results
                            print(f"Search performed for query: {clean_content}")
                            print(f"Search results found: {bool(search_results)}")

                # Process the message with all context
                response = await self.process_message(
                    message=clean_content,
                    context=personality,
                    history=history,
                    channel_id=message.channel.id,
                    user_name=user_name,
                    user_mention=user_mention
                )

                # Update history if not a safety response
                if "safety concerns" not in response.lower():
                    await self.add_to_history(message.channel.id, "user", clean_content, user_name)
                    await self.add_to_history(message.channel.id, "assistant", response, bot_user.display_name)

                    # Update rate limit
                    if message.channel.id not in self.rate_limits:
                        self.rate_limits[message.channel.id] = []
                    self.rate_limits[message.channel.id].append(datetime.now().isoformat())

                # Send response in chunks if needed
                if len(response) > 2000:
                    chunks = [response[i:i + 1900] for i in range(0, len(response), 1900)]
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response)

            except Exception as e:
                print(f"Error processing message: {str(e)}")
                error_msg = f"Sorry {message.author.mention}, I encountered an error: {str(e)}"
                await message.reply(error_msg)

async def setup(bot):
    cog = DiscordChatBot(bot)
    await bot.add_cog(cog)
    await cog.initialize()
