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
from PIL import Image
import io

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
        self.max_history_length = 10
        
        default_guild = {
            "enabled": True,
            "max_history": 10,
            "rate_limit": 25,
            "timezone": self.DEFAULT_TIMEZONE,
            "search_enabled": False,
            "personality": ""  # Add personality to guild settings
        }
        
        default_channel = {
            "history": []
        }
        
        default_global = {
            "api_key": None,  # Gemini API key is global
            "search_api_key": None,  # Search API key is global
            "search_engine_id": None  # Search Engine ID is global
        }
        
        self.config.register_guild(**default_guild)
        self.config.register_channel(**default_channel)
        self.config.register_global(**default_global)

        # Store active conversations
        self.conversation_history: Dict[int, List[dict]] = {}

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
            
            # Use a single model for both text and images
            self.model = genai.GenerativeModel(
                model_name="gemini-2.0-flash-exp",  # Updated to use the flash model
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

    async def get_gemini_response(self, prompt: str, images: List[dict] = None) -> Optional[str]:
        """Get a response from Gemini with proper error handling"""
        try:
            if not self.model:
                if not await self.initialize():
                    return "I'm not properly configured yet. Please ask an admin to set up my API key."

            # Create chat instance
            chat = self.model.start_chat(history=[])
            
            # Prepare message parts
            parts = [{'text': prompt}]
            if images:
                parts.extend(images)  # Add any images to the parts list
            
            # Send message and get response
            response = await asyncio.to_thread(
                lambda: chat.send_message(parts).text
            )
            
            # Ensure response doesn't exceed Discord's limit
            if len(response) > self.DISCORD_MESSAGE_LIMIT:
                response = response[:self.DISCORD_MESSAGE_LIMIT-100] + "..."
            
            return response

        except Exception as e:
            self.log.error(f"Error getting Gemini response: {str(e)}")
            self.log.error(f"Full error context: {e.__class__.__name__}: {str(e)}")
            return None

    def split_into_questions(self, text: str) -> List[str]:
        """Split a message into multiple questions/statements"""
        # Split by question marks, periods, or exclamation marks followed by space
        splits = re.split(r'(?<=[.!?])\s+', text.strip())
        return [s for s in splits if s]

    async def get_conversation_history(self, channel_id: int, user_name: str = None) -> List[Dict]:
        """Get conversation history for a channel"""
        if channel_id not in self.conversation_history:
            self.conversation_history[channel_id] = []
        
        # Return the last few messages from history
        history = self.conversation_history[channel_id][-self.max_history_length:]
        return [
            {
                'role': entry.get('role', 'user'),
                'content': entry.get('content', ''),
                'name': entry.get('user_name', user_name) if entry.get('role') == 'user' else None
            }
            for entry in history
        ]

    def _clean_message(self, message: str) -> str:
        """Clean message content by removing unwanted prefixes and formatting"""
        if not message:
            return ""
        # Fix regex flag positioning - move (?i) to start
        message = re.sub(r'(?i)^meow:\s*', '', message.strip())
        return message.strip()

    async def add_to_history(self, channel_id: int, role: str, message: str, user_name: str = None) -> None:
        """Add a message to the conversation history"""
        if channel_id not in self.conversation_history:
            self.conversation_history[channel_id] = []
            
        # Clean the message before storing
        clean_message = self._clean_message(message)
            
        # Map role to valid Gemini roles
        gemini_role = "user" if role.lower() == "user" else "model"
            
        # Add metadata to help with context
        entry = {
            "role": gemini_role,  # Only use "user" or "model" for Gemini
            "content": clean_message,
            "user_name": user_name,
            "timestamp": datetime.now().isoformat()
        }
        
        self.conversation_history[channel_id].append(entry)
        
        # Cleanup old messages (older than 24 hours)
        current_time = datetime.now()
        self.conversation_history[channel_id] = [
            msg for msg in self.conversation_history[channel_id]
            if (current_time - datetime.fromisoformat(msg['timestamp'])).total_seconds() < 86400
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
            "You are a witty and sarcastic Discord bot with a great sense of humor. "
            "While always helpful and accurate, you enjoy adding playful banter and clever jokes to your responses. "
            "You're confident but not arrogant, and you love making references to internet culture and memes when appropriate. "
            "Your responses should be a mix of helpfulness and entertainment - think of yourself as a knowledgeable friend "
            "who can't help but crack jokes while helping out. "
            "You excel at witty comebacks and clever wordplay, but never at the expense of being helpful. "
            "When analyzing images, maintain your witty personality while providing accurate descriptions. "
            "Only use emojis when they're directly relevant to the conversation or add meaningful context - "
            "prefer wit and wordplay over emoji reactions."
        )

    def get_default_personality(self) -> str:
        """Get the default personality traits"""
        return (
            "witty and sarcastic with a great sense of humor. "
            "Enjoys adding playful banter and clever jokes while staying helpful. "
            "Makes references to internet culture and memes when appropriate. "
            "Confident but not arrogant, with excellent wordplay skills."
        )

    async def get_bot_personality(self, guild: discord.Guild, channel: discord.TextChannel, user_name: str) -> str:
        """Get the bot's personality and context information"""
        # Get guild personality or use default
        guild_personality = await self.config.guild(guild).personality()
        personality = guild_personality if guild_personality else self.get_default_personality()
        
        # Build the personality prompt
        personality_prompt = (
            f"You are {self.bot.user.display_name}, a Discord bot with the following personality:\n"
            f"{personality}\n\n"
            f"Current context:\n"
            f"- Speaking with: {user_name}\n"
            f"- Server: {guild.name}\n"
            f"- Channel: #{channel.name}\n"
            f"- Category: {channel.category.name if channel.category else 'No category'}\n"
            f"- Channel topic: {channel.topic if channel.topic else 'No topic set'}\n"
        )
        
        return personality_prompt

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
            if channel_id in self.conversation_history:
                # Keep only the first few messages to maintain some context
                self.conversation_history[channel_id] = self.conversation_history[channel_id][:2]
        
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

    async def process_message(self, message: discord.Message, user_mention: str, clean_content: str) -> str:
        """Process a single message through Gemini"""
        try:
            # Process images if any
            images = []
            image_context = ""
            has_images = False
            try:
                images, image_context = await self._process_images(message)
                has_images = bool(images)
            except Exception as e:
                self.log.error(f"Error processing images: {str(e)}")
            
            # Get conversation history
            history = await self.get_conversation_history(message.channel.id, message.author.display_name)
            
            # Format history for Gemini
            formatted_history = []
            try:
                for entry in history:
                    if entry['role'] == 'user':
                        formatted_history.append({
                            'role': 'user',
                            'parts': [{'text': f"{entry['name']}: {entry['content']}"}]
                        })
                    else:
                        formatted_history.append({
                            'role': 'model',
                            'parts': [{'text': entry['content']}]
                        })
            except Exception as e:
                self.log.error(f"Error formatting history: {str(e)}")
                formatted_history = []
            
            # Check if we should perform a web search - only if no images
            search_context = ""
            if not has_images and message.guild and await self.config.guild(message.guild).search_enabled():
                try:
                    should_search, query = await self.should_perform_search(clean_content)
                    if should_search:
                        search_results = await self.perform_web_search(query, message)
                        if search_results:
                            search_context = f"\nRelevant search results:\n{search_results}\n"
                except Exception as e:
                    self.log.error(f"Error during web search: {str(e)}")
            
            # Prepare prompt using the original template with search results and image context
            try:
                prompt = self._prepare_prompt(
                    message=clean_content,
                    context=await self.get_bot_personality(message.guild, message.channel, message.author.display_name),
                    history=history,
                    current_user=message.author.display_name,
                    search_results=search_context
                )
            except Exception as e:
                self.log.error(f"Error preparing prompt: {str(e)}")
                prompt = clean_content

            # Get response from Gemini
            try:
                response = await self.get_gemini_response(prompt, images)
                
                if not response:
                    return f"I'm having trouble understanding that, {user_mention}. Could you try rephrasing?"
                
                response_text = self._clean_message(response)
                
                # Add to conversation history - include note about images but not the image data
                message_to_save = clean_content
                if has_images:
                    message_to_save += f"\n[Shared {len(images)} image(s)]"
                
                await self.add_to_history(
                    message.channel.id,
                    "user",
                    message_to_save,
                    message.author.display_name
                )
                await self.add_to_history(
                    message.channel.id,
                    "assistant",
                    response_text
                )
                
                return response_text
                
            except Exception as e:
                error_str = str(e)
                self.log.error(f"Error getting Gemini response: {error_str}")
                self.log.error(f"Full error context: {e.__class__.__name__}: {str(e)}")
                
                if "safety" in error_str.lower() or "blocked" in error_str.lower():
                    return f"I can't process that message due to content safety restrictions, {user_mention}. Let's keep our conversation friendly!"
                elif "quota" in error_str.lower() or "rate" in error_str.lower():
                    return f"I've hit my rate limit, {user_mention}. Please try again in a moment!"
                elif "image" in error_str.lower():
                    return f"I had trouble processing the image(s), {user_mention}. Please make sure they're in a supported format (JPEG, PNG, WEBP)."
                else:
                    return f"I encountered an issue processing your message, {user_mention}. Could you try rephrasing it?"
            
        except Exception as e:
            self.log.error(f"Unexpected error in process_message: {str(e)}")
            self.log.error(f"Full error context: {e.__class__.__name__}: {str(e)}")
            return f"I ran into an unexpected problem, {user_mention}. Please try again!"

    def _prepare_prompt(self, message: str, context: str, history: List[Dict], current_user: str, search_results: str = "") -> str:
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
            "  - Maintain your conversational style\n\n"
            
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

    async def _process_images(self, message: discord.Message) -> Tuple[List[dict], str]:
        """Process images from the message or referenced message"""
        images = []
        image_context = ""
        
        # Function to download and convert image
        async def download_image(attachment):
            try:
                data = await attachment.read()
                image = Image.open(io.BytesIO(data))
                
                # Convert to bytes in memory
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format=image.format or 'PNG')
                img_byte_arr = img_byte_arr.getvalue()
                
                # Format for flash-exp model
                return {
                    'inline_data': {
                        'mime_type': attachment.content_type or 'image/png',
                        'data': img_byte_arr
                    }
                }
            except Exception as e:
                self.log.error(f"Error downloading/processing image: {str(e)}")
                return None

        # Check for images in the current message
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    image_data = await download_image(attachment)
                    if image_data:
                        images.append(image_data)  # Don't wrap in 'image' key
                        image_context += f"[Image from {message.author.display_name}] "

        # Check for images in referenced message
        if message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            if ref_msg.attachments:
                for attachment in ref_msg.attachments:
                    if attachment.content_type and attachment.content_type.startswith('image/'):
                        image_data = await download_image(attachment)
                        if image_data:
                            images.append(image_data)  # Don't wrap in 'image' key
                            image_context += f"[Referenced image from {ref_msg.author.display_name}] "

        return images, image_context

    @red_commands.group()
    @red_commands.guild_only()
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
    @red_commands.admin_or_permissions(administrator=True)
    async def personality(self, ctx: commands.Context, *, personality: str = None):
        """
        View or set the bot's personality for this server

        Examples:
        - [p]chatbot personality
        - [p]chatbot personality friendly and helpful assistant that loves explaining tech
        - [p]chatbot personality professional business consultant focused on formal communication
        
        Note: This completely replaces the default personality for this server.
        Use [p]chatbot resetpersonality to restore the default personality.
        """
        if personality is None:
            # Show current personality
            current = await self.config.guild(ctx.guild).personality()
            personality_text = current if current else self.get_default_personality()
            
            embed = discord.Embed(
                title="🤖 Bot Personality",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Current Personality",
                value=personality_text,
                inline=False
            )
            if not current:
                embed.add_field(
                    name="Note",
                    value="Using default personality. Use this command with a description to set a custom personality.",
                    inline=False
                )
            await ctx.send(embed=embed)
        else:
            # Set new personality
            await self.config.guild(ctx.guild).personality.set(personality)
            await ctx.send(f"✅ Bot personality has been updated for this server!")

    @chatbot.command()
    @red_commands.admin_or_permissions(administrator=True)
    async def resetpersonality(self, ctx: commands.Context):
        """
        Reset the bot's personality to default for this server
        
        This will restore the default witty and sarcastic personality.
        """
        await self.config.guild(ctx.guild).personality.set("")
        await ctx.send("✅ Bot personality has been reset to default!")

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
        personality = await self.config.guild(ctx.guild).personality()
        
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

    @red_commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
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
                self.log.error(f"Error processing message: {str(e)}")
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
