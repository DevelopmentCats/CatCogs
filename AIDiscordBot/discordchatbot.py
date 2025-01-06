import discord
from discord.ext import commands
from redbot.core import commands as red_commands
from redbot.core import Config
import google.generativeai as genai
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta
import pytz
import asyncio
from typing import Dict, List, Optional, Tuple
import re
import logging

class DiscordChatBot(red_commands.Cog):
    """A Discord chatbot powered by Google's Gemini AI"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.typing_channels = set()
        self.rate_limits = {}
        self.model = None
        self.search_service = None
        self.log = logging.getLogger("red.aibot.search")  # Use standard logging
        
        # Constants
        self.DISCORD_MESSAGE_LIMIT = 2000
        self.RATE_LIMIT_MAX = 50  # Maximum messages per time window
        self.RATE_LIMIT_MINUTES = 15  # Time window in minutes
        self.GEMINI_MAX_INPUT = 30720     # Gemini's input token limit (approximate in characters)
        self.GEMINI_MAX_OUTPUT = 2048     # Keep responses reasonable
        self.DEFAULT_TIMEZONE = 'America/Chicago'  # Default timezone
        
        default_guild = {
            "enabled": True,
            "max_history": 10,
            "rate_limit": 25,
            "timezone": self.DEFAULT_TIMEZONE,  # Use the constant
            "search_enabled": False,
            "api_key": None
        }
        
        default_channel = {
            "history": [],
            "personality": ""
        }
        
        default_global = {
            "search_api_key": None,  # Search API key is global
            "search_engine_id": None  # Search Engine ID is global
        }
        
        self.config.register_guild(**default_guild)
        self.config.register_channel(**default_channel)
        self.config.register_global(**default_global)

        # Store active conversations
        self.active_conversations: Dict[int, List[dict]] = {}

    async def initialize(self) -> bool:
        """Initialize the Gemini API client"""
        try:
            api_key = await self.config.api_key()
            if not api_key:
                print("No API key configured")
                return False

            genai.configure(api_key=api_key)
            
            # Initialize model with safety settings
            generation_config = {
                "temperature": 0.9,
                "top_p": 1,
                "top_k": 1,
                "max_output_tokens": 2048,
            }
            
            safety_settings = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ]
            
            self.model = genai.GenerativeModel(
                model_name="gemini-pro",
                generation_config=generation_config,
                safety_settings=safety_settings
            )
            
            # Initialize search service if keys are available
            search_api_key = await self.config.search_api_key()
            if search_api_key:
                self.search_service = build('customsearch', 'v1', developerKey=search_api_key)
            
            return True
            
        except Exception as e:
            print(f"Error initializing Gemini API: {str(e)}")
            return False

    async def get_gemini_response(self, prompt: str) -> Optional[str]:
        """Get a response from Gemini with proper error handling"""
        try:
            if not self.model:
                if not await self.initialize():
                    return "I'm not properly configured yet. Please ask an admin to set up my API key."

            chat = self.model.start_chat(history=[])
            response = await asyncio.to_thread(
                lambda: chat.send_message(prompt).text
            )
            
            # Ensure response doesn't exceed Discord's limit
            if len(response) > self.DISCORD_MESSAGE_LIMIT:
                response = response[:self.DISCORD_MESSAGE_LIMIT-100] + "..."
            
            return response

        except Exception as e:
            print(f"Error getting Gemini response: {str(e)}")
            return None

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

    async def _check_rate_limit(self, channel_id: int, message: discord.Message) -> bool:
        """Check if the channel has hit its rate limit"""
        now = datetime.now(timezone.utc)
        
        # Initialize rate limits for this channel if needed
        if channel_id not in self.rate_limits:
            self.rate_limits[channel_id] = []
        
        # Remove old timestamps
        self.rate_limits[channel_id] = [
            t for t in self.rate_limits[channel_id] 
            if now - datetime.fromisoformat(t) < timedelta(minutes=self.RATE_LIMIT_MINUTES)
        ]
        
        # Check if we're over the limit
        if len(self.rate_limits[channel_id]) >= self.RATE_LIMIT_MAX:
            return False
        
        # Add new timestamp
        self.rate_limits[channel_id].append(now.isoformat())
        return True

    def format_discord_message(self, text: str) -> str:
        """Format message for Discord, ensuring proper markdown and length limits"""
        if not text:
            return ""
            
        # Ensure code blocks are properly closed
        open_blocks = text.count("```")
        if open_blocks % 2 != 0:
            text += "\n```"
            
        # Ensure all formatting is properly closed
        for char in ["*", "_", "~", "|"]:
            count = text.count(char)
            if count % 2 != 0:
                text += char
                
        # Truncate if too long
        if len(text) > self.DISCORD_MESSAGE_LIMIT:
            text = text[:self.DISCORD_MESSAGE_LIMIT-100] + "..."
            
        return text

    async def get_current_time_info(self, guild_id: int = None) -> str:
        """Get formatted time information based on guild's timezone"""
        try:
            # Get timezone setting, default to America/Chicago if not set
            if guild_id:
                guild_timezone = await self.config.guild_from_id(guild_id).timezone()
            else:
                guild_timezone = self.DEFAULT_TIMEZONE

            # Get current time in UTC
            utc_now = datetime.now(timezone.utc)
            
            # Convert to guild's timezone
            local_tz = pytz.timezone(guild_timezone)
            local_time = utc_now.astimezone(local_tz)
            
            return f"Current time: {local_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            
        except Exception as e:
            print(f"Error getting time info: {str(e)}")
            return f"Current time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"

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

    async def should_perform_search(self, message: str) -> tuple[bool, str]:
        """
        Ask Gemini if a web search would be helpful for this message and get the search query
        Returns a tuple of (should_search: bool, search_query: str)
        """
        try:
            prompt = f"""Analyze if this message requires current or factual information that would benefit from a web search.
If a search is needed, generate a precise and focused search query that would best find the relevant information.

ONLY recommend a search for questions about:
1. Current events, news, or trending topics
2. Facts that may change over time (prices, statistics, rankings)
3. Product information, reviews, or comparisons
4. Technical documentation or specifications
5. Recent developments in any field
6. Location-specific information
7. Time-sensitive information

DO NOT recommend a search for:
1. Basic facts or general knowledge
2. Hypothetical scenarios
3. Personal opinions or advice
4. Mathematical calculations
5. Code explanations
6. Grammar or language questions
7. Simple definitions

Message: {message}

Respond in this exact format:
SEARCH_NEEDED: true/false
SEARCH_QUERY: <only if search is needed, create a focused and specific search query that will yield relevant results>

Example good responses:
SEARCH_NEEDED: true
SEARCH_QUERY: iPhone 15 Pro Max price and specifications 2024

SEARCH_NEEDED: false
SEARCH_QUERY:

Example bad responses:
SEARCH_NEEDED: true
SEARCH_QUERY: what is python programming (too general, not time-sensitive)

SEARCH_NEEDED: true
SEARCH_QUERY: how to bake cookies (not requiring current information)"""

            response = await self.get_gemini_response(prompt)
            if not response:
                return False, ""

            # Parse the response
            lines = response.strip().split('\n')
            if len(lines) < 2:
                return False, ""

            search_needed = lines[0].split(': ')[1].lower() == 'true'
            search_query = lines[1].split(': ')[1] if len(lines[1].split(': ')) > 1 else ""

            # Additional validation of the search query
            if search_needed and not search_query.strip():
                self.log.debug("Search was recommended but no query was generated")
                return False, ""  # Don't search if query is empty
            if len(search_query) > 128:
                self.log.debug(f"Search query truncated from {len(search_query)} characters to 128")
                search_query = search_query[:128]  # Limit query length

            if search_needed:
                self.log.info(f"Search recommended for message: '{message}' with query: '{search_query}'")
            else:
                self.log.debug(f"Search not recommended for message: '{message}'")

            return search_needed, search_query

        except Exception as e:
            self.log.error(f"Error in should_perform_search: {str(e)}")
            return False, ""

    async def process_message(self, message: discord.Message, user_mention: str, clean_content: str) -> str:
        """Process a single message through Gemini"""
        try:
            # Get conversation history
            history = await self.get_conversation_history(message.channel.id)
            
            # Check if search might be helpful
            search_context = ""
            if message.guild:
                search_enabled = await self.config.guild(message.guild).search_enabled()
                if search_enabled:
                    should_search, search_query = await self.should_perform_search(clean_content)
                    if should_search and search_query:
                        search_results = await self.perform_web_search(search_query, message)
                        if search_results:
                            search_context = f"Here is some relevant information I found:\n{search_results}\n\n"
                            print(f"Search performed with query: {search_query}")
            
            # Format history for better context
            formatted_history = []
            for entry in history:  
                if 'parts' in entry and entry['parts']:
                    message_text = entry['parts'][0].get('text', '')
                    
                    # Clean the message text
                    message_text = self._clean_message(message_text)
                    
                    # Format message based on who sent it
                    if entry['metadata'].get('user_name') == message.author.display_name:
                        formatted_text = f"You: {message_text}"
                    else:
                        formatted_text = f"Assistant: {message_text}"
                    
                    formatted_history.append({
                        "role": entry.get("role", "user"),  
                        "parts": [{"text": formatted_text}]
                    })
            
            try:
                chat = self.model.start_chat(history=formatted_history)
            except Exception as e:
                print(f"Error starting chat: {str(e)}")
                chat = self.model.start_chat(history=[])  
            
            # Prepare prompt using the original template with search results
            prompt = self._prepare_prompt(
                message=clean_content,
                context=self.get_bot_personality(message.guild, message.channel, message.author.display_name),
                history=history,
                current_user=message.author.display_name,
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
                if message.author.display_name in response_text:
                    response_text = response_text.replace(message.author.display_name, user_mention, 1)
                return response_text
                
            except Exception as e:
                error_str = str(e)
                print(f"Gemini Error: {error_str}")
                friendly_error = self._handle_safety_error(error_str, message.channel.id)
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

    async def perform_web_search(self, query: str, ctx) -> str:
        """Perform a web search using Google Custom Search API"""
        try:
            search_api_key = await self.config.search_api_key()
            search_engine_id = await self.config.search_engine_id()
            
            if not search_api_key or not search_engine_id:
                self.log.warning("Search attempted but API key or engine ID not configured")
                return "Web search is not configured. Please ask the bot owner to set up the search API."
            
            if not self.search_service:
                self.search_service = build('customsearch', 'v1', developerKey=search_api_key)
            
            # Log the search with context awareness
            if ctx:
                guild_name = ctx.guild.name if ctx.guild else "DM"
                channel_name = ctx.channel.name if hasattr(ctx.channel, 'name') else "DM"
                user_name = str(ctx.author)
                self.log.info(f"Search performed - Guild: {guild_name}, Channel: {channel_name}, User: {user_name}, Query: {query}")
            else:
                self.log.info(f"Internal search performed - Query: {query}")
            
            # Perform the search with improved parameters
            result = self.search_service.cse().list(
                q=query,
                cx=search_engine_id,
                num=3,  # Get top 3 results
                dateRestrict='m6',  # Restrict to last 6 months for freshness
                safe='active'  # Enable safe search
            ).execute()
            
            if 'items' not in result:
                self.log.info(f"No search results found for query: {query}")
                return "No relevant results found for your query."
            
            search_results = []
            result_count = 0
            for item in result['items']:
                title = item.get('title', 'No title')
                snippet = item.get('snippet', 'No description')
                link = item.get('link', '')
                date = item.get('pagemap', {}).get('metatags', [{}])[0].get('article:published_time', '')
                
                # Clean and format the snippet
                snippet = snippet.replace('\n', ' ').strip()
                if len(snippet) > 200:
                    snippet = snippet[:197] + "..."
                
                # Format date if available
                date_str = ""
                if date:
                    try:
                        from datetime import datetime
                        date_obj = datetime.fromisoformat(date.replace('Z', '+00:00'))
                        date_str = f" (Published: {date_obj.strftime('%Y-%m-%d')})"
                    except Exception as e:
                        self.log.debug(f"Error parsing date for search result: {str(e)}")
                
                search_results.append(f"**{title}**{date_str}\n{snippet}\n{link}\n")
                result_count += 1
            
            if not search_results:
                self.log.warning(f"Search returned items but no valid results could be formatted for query: {query}")
                return "No relevant results found for your query."
                
            self.log.info(f"Search completed successfully - Query: {query}, Results: {result_count}")
            return "\n\n".join(search_results)
            
        except Exception as e:
            error_msg = str(e)
            self.log.error(f"Search error - Query: {query}, Error: {error_msg}")
            if "quota" in error_msg.lower():
                return "Search quota exceeded. Please try again later or contact the bot owner."
            elif "invalid" in error_msg.lower() and "key" in error_msg.lower():
                return "Search API configuration error. Please contact the bot owner."
            else:
                return "An error occurred while performing the web search. Please try again later."

    @commands.group()
    @commands.guild_only()
    async def chatbot(self, ctx: commands.Context):
        """Gemini AI Chatbot Commands"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @chatbot.command()
    @red_commands.is_owner()
    async def searchkey(self, ctx: commands.Context, key: str):
        """
        Set the Google Custom Search API key (Bot Owner Only)
        
        This key will be used for all servers where search is enabled.
        """
        await self.config.search_api_key.set(key)
        await ctx.send("Search API key has been set. Use `searchid` to set the search engine ID.")
        # Delete the command message for security
        try:
            await ctx.message.delete()
        except:
            pass

    @chatbot.command()
    @red_commands.is_owner()
    async def searchid(self, ctx: commands.Context, engine_id: str):
        """
        Set the Google Custom Search Engine ID (Bot Owner Only)
        
        This ID will be used for all servers where search is enabled.
        """
        await self.config.search_engine_id.set(engine_id)
        await ctx.send("Search engine ID has been set. Use `togglesearch` to enable search in this server.")

    @chatbot.command()
    @red_commands.admin_or_permissions(administrator=True)
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
        await ctx.send(f"Web search has been {status} for this server!")

    @chatbot.command()
    @red_commands.admin_or_permissions(administrator=True)
    async def toggle(self, ctx: commands.Context):
        """
        Toggle the bot on/off for this server
        
        Usage: [p]chatbot toggle
        
        This will enable/disable the bot's response to mentions in this server.
        """
        current = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not current)
        status = "enabled" if not current else "disabled"
        await ctx.send(f"I have been {status} for this server!")

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
                await ctx.send("I'm currently using my default personality!")
            else:
                await ctx.send(f"My current personality is: {current}")
        else:
            await self.config.channel(ctx.channel).personality.set(new_personality)
            await ctx.send("My personality has been updated!")

    @chatbot.command()
    async def reset(self, ctx: commands.Context):
        """
        Reset the conversation history for this channel
        
        Usage: [p]chatbot reset
        
        This will clear all stored message history for this channel.
        """
        await self.config.channel(ctx.channel).history.set([])
        await ctx.send("Conversation history has been reset!")

    @chatbot.command()
    @red_commands.admin_or_permissions(administrator=True)
    async def clearrate(self, ctx: commands.Context):
        """
        Clear rate limit counters for this channel (Admin only)
        
        Usage: [p]chatbot clearrate
        
        This will reset the rate limit counters, useful if the bot gets stuck.
        """
        if ctx.channel.id in self.rate_limits:
            del self.rate_limits[ctx.channel.id]
        await ctx.send("Rate limit counters have been cleared!")

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
        # Ignore messages from bots
        if message.author.bot:
            return

        # Check if message mentions the bot
        if not self.bot.user in message.mentions:
            return

        # Get guild settings
        if message.guild:
            enabled = await self.config.guild(message.guild).enabled()
            if not enabled:
                return
        
        # Start typing indicator
        self.typing_channels.add(message.channel.id)
        async with message.channel.typing():
            try:
                # Clean the message content
                clean_content = message.clean_content.replace(f'@{self.bot.user.display_name}', '').strip()
                user_mention = message.author.mention

                # Check rate limits
                if not await self._check_rate_limit(message.channel.id, message):
                    await message.channel.send(
                        f"Sorry {user_mention}, you're sending messages too quickly. Please wait a moment."
                    )
                    return

                # Process the message
                response = await self.process_message(message, user_mention, clean_content)
                
                if response:
                    # Split response if it's too long
                    if len(response) > self.DISCORD_MESSAGE_LIMIT:
                        chunks = [response[i:i + self.DISCORD_MESSAGE_LIMIT] 
                                for i in range(0, len(response), self.DISCORD_MESSAGE_LIMIT)]
                        for chunk in chunks:
                            await message.channel.send(chunk)
                    else:
                        await message.channel.send(response)
                else:
                    await message.channel.send(
                        f"Sorry {user_mention}, I couldn't generate a response. Please try again."
                    )

            except Exception as e:
                print(f"Unexpected Error: {str(e)}")
                await message.channel.send(
                    f"Sorry {user_mention}, something went wrong. Please try again later."
                )
            finally:
                # Remove typing indicator
                self.typing_channels.discard(message.channel.id)

async def setup(bot):
    cog = DiscordChatBot(bot)
    await bot.add_cog(cog)
    await cog.initialize()
