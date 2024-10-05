import aiohttp
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from typing import Dict, List, Tuple, Any, Union
import asyncio
from datetime import datetime, timedelta
import json
from asyncio import Queue
import logging
import pytz
import re
import sqlite3
import os
from contextlib import closing
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from aiohttp import ClientError

# Langchain imports
from langchain_community.llms import Ollama
from langchain.prompts import PromptTemplate
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory, ConversationTokenBufferMemory
from langchain.agents import Tool, AgentExecutor, LLMSingleActionAgent
from langchain.schema import AgentAction, AgentFinish, OutputParserException
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.callbacks import AsyncIteratorCallbackHandler

MAX_RETRIES = 3
RETRY_DELAY = 2

class AIResponder(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_global = {
            "api_url": "http://localhost:11434",
            "model": "llama3.2:latest",
            "max_tokens": 300,
            "enabled_channels": [],
            "custom_personality": "You are a helpful AI assistant.",
            "api_timeout": 300,
            "db_path": "airesponder.db",
            "personalities": {},
        }
        self.config.register_global(**default_global)
        self.user_cooldowns: Dict[int, Tuple[datetime, int]] = {}
        self.request_queue: Queue = Queue()
        self.processing_lock = asyncio.Lock()
        
        # Initialize Langchain components
        self.llm = None
        self.conversation_chain = None
        self.agent_executor = None
        
        # Use create_task for asynchronous setup
        asyncio.create_task(self.async_init())

    async def async_init(self):
        await self.setup_database()
        await self.setup_langchain()

    async def setup_database(self):
        db_path = await self.config.db_path()
        with closing(sqlite3.connect(db_path)) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS conversation_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        message TEXT,
                        response TEXT,
                        relevance FLOAT DEFAULT 1.0,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()

    async def setup_langchain(self):
        api_url = await self.config.api_url()
        model = await self.config.model()
        
        self.llm = Ollama(base_url=api_url, model=model)
        
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            input_key="human_input",
            return_messages=True
        )
        
        custom_personality = await self.config.custom_personality()
        
        prompt = PromptTemplate(
            input_variables=["personality", "context", "current_time", "chat_history", "human_input"],
            template="""
            System: You are an AI assistant with the following personality: {personality}
            You are in a Discord server, responding to user messages.
            Respond naturally and conversationally, as if you're chatting with a friend.
            Do not mention that you're an AI or that this is a prompt.

            Context:
            {context}
            Current time (UTC): {current_time}

            Chat History:
            {chat_history}

            Human: {human_input}

            Assistant: """
        )
        
        self.conversation_chain = ConversationChain(
            llm=self.llm,
            memory=memory,
            prompt=prompt,
            verbose=True
        )
        
        tools = self.setup_tools()
        
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=LLMSingleActionAgent(
                llm_chain=self.conversation_chain,
                output_parser=self.CustomOutputParser(),
                stop=["\nObservation:"],
                allowed_tools=[tool.name for tool in tools]
            ),
            tools=tools,
            memory=memory,
            verbose=True
        )

    def setup_tools(self):
        return [
            Tool(
                name="web_search",
                func=self.web_search,
                description="Search the web for current information. Use this when you need to find up-to-date information about a topic."
            ),
            Tool(
                name="calculator",
                func=self.calculate,
                description="Perform mathematical calculations. Use this when you need to compute numerical results."
            ),
            Tool(
                name="weather",
                func=self.get_weather,
                description="Get current weather information for a location. Use this when asked about weather conditions in a specific place."
            ),
            Tool(
                name="datetime",
                func=self.get_datetime_info,
                description="Get current date and time information. Use this when asked about the current date, time, or both."
            ),
            Tool(
                name="server_info",
                func=self.get_server_info,
                description="Get Discord server information. Use this when asked about the current server's name, member count, channels, or roles."
            )
        ]

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
                relevant_context = await self.get_relevant_context(message, content)
                
                current_time = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S %Z")
                
                context_str = "\n".join([f"{k}: {v}" for k, v in relevant_context.items()])
                
                input_dict = {
                    "personality": custom_personality,
                    "context": context_str,
                    "current_time": current_time,
                    "human_input": content
                }
                
                thinking_emoji = "🤔"
                response_message = await message.channel.send(f"{thinking_emoji} Thinking...")
                
                full_response = ""
                async for response_chunk in self.stream_agent_response(input_dict):
                    full_response += response_chunk
                    if len(full_response) > 1900:
                        await response_message.edit(content=full_response[:1900])
                        full_response = full_response[1900:]
                        response_message = await message.channel.send(full_response)
                    else:
                        await response_message.edit(content=full_response)
                
                if full_response:
                    await response_message.edit(content=full_response)
                
                await self.update_user_conversation_history(message.author.id, content, full_response)
                
            except Exception as e:
                error_message = "An unexpected error occurred while processing your request."
                await self.log_error(error_message, e)
                await message.channel.send(f"<@{message.author.id}> {error_message} Please try again later.")

    async def stream_agent_response(self, input_dict):
        full_response = ""
        async for chunk in self.agent_executor.astream(input_dict):
            if 'output' in chunk:
                full_response += chunk['output']
                yield full_response

    async def check_rate_limit(self, user_id: int) -> bool:
        if await self.bot.is_owner(discord.Object(id=user_id)):
            return True
        
        now = datetime.now()
        if user_id in self.user_cooldowns:
            last_use, use_count = self.user_cooldowns[user_id]
            if now - last_use < timedelta(minutes=1):
                if use_count >= 5:
                    return False
                self.user_cooldowns[user_id] = (last_use, use_count + 1)
            else:
                self.user_cooldowns[user_id] = (now, 1)
        else:
            self.user_cooldowns[user_id] = (now, 1)
        return True

    async def process_queue(self):
        if self.processing_lock.locked():
            return

        async with self.processing_lock:
            while not self.request_queue.empty():
                message = await self.request_queue.get()
                await self.respond_to_mention(message)

    async def log_error(self, error_message: str, error: Exception = None):
        logging.error(f"AIResponder Error: {error_message}")
        if error:
            logging.error(f"Exception details: {str(error)}")
        
        # You can add additional error reporting here, such as sending to a Discord channel
        error_channel_id = await self.config.error_channel_id()
        if error_channel_id:
            channel = self.bot.get_channel(error_channel_id)
            if channel:
                await channel.send(f"AIResponder Error: {error_message}")

    async def get_relevant_context(self, message: discord.Message, content: str) -> dict:
        context = {}
        
        # Always include basic user and channel info
        context['user_id'] = message.author.id
        context['channel_id'] = message.channel.id
        
        # Get conversation history using semantic similarity
        context['conversation_history'] = await self.get_user_conversation_history(message.author.id, content)
        
        # Include recent messages if the query seems to reference them
        if any(word in content.lower() for word in ['earlier', 'before', 'previous', 'last message']):
            context['recent_messages'] = await self.get_recent_messages(message.channel, message)
        
        # Include server info if the query is about the server or roles
        if any(word in content.lower() for word in ['server', 'channel', 'role', 'permission']):
            context['server_info'] = self.get_compressed_server_info(message.guild)
        
        return context

    def get_compressed_server_info(self, guild: discord.Guild) -> str:
        channels = f"Channels: {', '.join([c.name for c in guild.channels[:10]])}"
        roles = f"Roles: {', '.join([r.name for r in guild.roles[:10]])}"
        return f"{guild.name} | Members: {guild.member_count} | {channels} | {roles}"

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    async def web_search(self, query: str) -> str:
        try:
            # DuckDuckGo Search
            async with aiohttp.ClientSession() as session:
                ddg_url = f"https://api.duckduckgo.com/?q={query}&format=json"
                async with session.get(ddg_url) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        if data.get("Abstract") or data.get("RelatedTopics"):
                            summary = data.get("Abstract", "")
                            topics = "\n".join([topic.get("Text", "") for topic in data.get("RelatedTopics", [])[:3]])
                            return f"Web search results for '{query}':\n\n{summary}\n\nRelated topics:\n{topics}"

            # Wikipedia fallback
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={query}&format=json"
            async with aiohttp.ClientSession() as session:
                async with session.get(wiki_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        search_results = data.get("query", {}).get("search", [])
                        if search_results:
                            top_result = search_results[0]
                            title = top_result.get("title", "")
                            snippet = top_result.get("snippet", "")
                            return f"Wikipedia search results for '{query}':\n\nTitle: {title}\nSummary: {snippet}"

            return f"No results found for '{query}'."

        except Exception as e:
            return f"An error occurred during web search: {str(e)}"

    def calculate(self, expression: str) -> str:
        try:
            result = eval(expression)
            return f"The result of {expression} is {result}"
        except Exception as e:
            return f"Error in calculation: {str(e)}"

    async def get_weather(self, location: str) -> str:
        try:
            # Keep your existing implementation
            search_url = f"https://www.metaweather.com/api/location/search/?query={location}"
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url) as response:
                    if response.status == 200:
                        locations = await response.json()
                        if not locations:
                            return f"No weather information found for '{location}'."
                        
                        location_id = locations[0]['woeid']
                        
                        weather_url = f"https://www.metaweather.com/api/location/{location_id}/"
                        async with session.get(weather_url) as weather_response:
                            if weather_response.status == 200:
                                weather_data = await weather_response.json()
                                current_weather = weather_data['consolidated_weather'][0]
                                
                                state = current_weather['weather_state_name']
                                temp = round(current_weather['the_temp'], 1)
                                humidity = current_weather['humidity']
                                wind_speed = round(current_weather['wind_speed'], 1)
                                
                                return f"Weather in {location}:\nState: {state}\nTemperature: {temp}°C\nHumidity: {humidity}%\nWind Speed: {wind_speed} mph"
                            else:
                                return f"Error fetching weather data for '{location}'."
                    else:
                        return f"Error searching for location '{location}'."
        except Exception as e:
            return f"An error occurred while fetching weather information: {str(e)}"

    def get_datetime_info(self, query: str) -> str:
        now = datetime.now()
        if query == "now":
            return f"Current date and time: {now.strftime('%Y-%m-%d %H:%M:%S')}"
        elif query == "date":
            return f"Current date: {now.strftime('%Y-%m-%d')}"
        elif query == "time":
            return f"Current time: {now.strftime('%H:%M:%S')}"
        else:
            return f"Invalid datetime query: {query}"

    def get_server_info(self, info_type: str) -> str:
        if not self.bot.guilds:
            return "Bot is not in any servers"
        guild = self.bot.guilds[0]  # Get info from the first server the bot is in
        if info_type == "name":
            return f"Server name: {guild.name}"
        elif info_type == "member_count":
            return f"Number of members: {guild.member_count}"
        elif info == "channels":
            channels = ", ".join([channel.name for channel in guild.channels[:10]])
            return f"Channels: {channels}"
        elif info_type == "roles":
            roles = ", ".join([role.name for role in guild.roles[:10]])
            return f"Roles: {roles}"
        else:
            return f"Invalid server info type: {info_type}"

    async def get_recent_messages(self, channel: discord.TextChannel, current_message: discord.Message, limit: int = 5) -> str:
        messages = []
        async for msg in channel.history(limit=limit + 1):  # +1 to account for the current message
            if msg.id != current_message.id:  # Exclude the current message
                if msg.author == self.bot.user:
                    messages.append(f"Bot: {msg.content}")
                else:
                    messages.append(f"{msg.author.name}: {msg.content}")
            if len(messages) == limit:
                break
        return "\n".join(reversed(messages))

    async def get_user_conversation_history(self, user_id: int, current_message: str) -> str:
        db_path = await self.config.db_path()
        with closing(sqlite3.connect(db_path)) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute('''
                    SELECT message, response, relevance FROM conversation_history
                    WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10
                ''', (user_id,))
                rows = cursor.fetchall()
        
        if not rows:
            return "No previous conversation with this user."
        
        # Calculate semantic similarity
        vectorizer = TfidfVectorizer().fit_transform([current_message] + [row[0] for row in rows])
        cosine_similarities = cosine_similarity(vectorizer[0:1], vectorizer[1:]).flatten()
        
        # Combine semantic similarity with existing relevance scores
        combined_scores = [sim * row[2] for sim, row in zip(cosine_similarities, rows)]
        
        # Sort by combined score and select top 3
        sorted_history = sorted(zip(combined_scores, rows), key=lambda x: x[0], reverse=True)[:3]
        
        history = "\n".join([f"User: {row[1][0]}\nBot: {row[1][1]}" for row in sorted_history])
        return f"Previous relevant conversations with this user:\n{history}"

    async def update_user_conversation_history(self, user_id: int, user_message: str, ai_response: str):
        db_path = await self.config.db_path()
        with closing(sqlite3.connect(db_path)) as conn:
            with closing(conn.cursor()) as cursor:
                # Insert new conversation entry
                cursor.execute('''
                    INSERT INTO conversation_history (user_id, message, response, relevance)
                    VALUES (?, ?, ?, 1.0)
                ''', (user_id, user_message, ai_response))
                
                # Apply relevance decay to existing entries
                cursor.execute('''
                    UPDATE conversation_history
                    SET relevance = relevance * 0.9
                    WHERE user_id = ? AND id != last_insert_rowid()
                ''', (user_id,))
                
                conn.commit()

    class CustomOutputParser:
        def parse(self, llm_output: str) -> Union[AgentAction, AgentFinish]:
            if "Final Answer:" in llm_output:
                return AgentFinish(
                    return_values={"output": llm_output.split("Final Answer:")[-1].strip()},
                    log=llm_output,
                )
            
            action_match = re.search(r"Action: (.*?)[\n]*Action Input: (.*)", llm_output, re.DOTALL)
            if action_match:
                action = action_match.group(1).strip()
                action_input = action_match.group(2).strip()
                return AgentAction(tool=action, tool_input=action_input, log=llm_output)
            
            return AgentFinish(
                return_values={"output": llm_output.strip()},
                log=llm_output,
            )

    @commands.group(name="air", invoke_without_command=True)
    async def air(self, ctx: commands.Context):
        """AIResponder commands for managing AI interactions."""
        await self.air_help(ctx)

    @air.command(name="help")
    async def air_help(self, ctx: commands.Context):
        """Get help on how to use the AI responder."""
        help_text = (
            "**AIResponder Help**\n\n"
            "The AIResponder cog allows you to interact with an AI assistant.\n\n"
            "**General Usage:**\n"
            f"- To chat with the AI, mention the bot or use `{ctx.prefix}air chat <your message>`\n\n"
            f"**Available Commands:**\n"
            f"`{ctx.prefix}air config` - Configure the AIResponder (Bot Owner only)\n"
            f"`{ctx.prefix}air chat` - Chat with the AI\n"
            f"`{ctx.prefix}air help` - Show this help message\n\n"
            f"Use `{ctx.prefix}help air <command>` for more information on a specific command."
        )
        await ctx.send(help_text)

    @air.group(name="config")
    @commands.is_owner()
    async def air_config(self, ctx: commands.Context):
        """Configure the AIResponder cog (Bot Owner only)."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @air_config.command(name="setapiurl")
    @commands.is_owner()
    async def air_setapiurl(self, ctx: commands.Context, url: str):
        """Set the Ollama API URL."""
        if not url.startswith(("http://", "https://")):
            await ctx.send("Invalid URL. Please provide a valid HTTP or HTTPS URL.")
            return
        await self.config.api_url.set(url)
        await self.update_langchain_components()
        await ctx.send(f"Ollama API URL set to: {url}")

    @air_config.command(name="setmodel")
    @commands.is_owner()
    async def air_setmodel(self, ctx: commands.Context, model: str = None):
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
                            await self.update_langchain_components()
                            await ctx.send(f"AI model set to: {model}")
                        else:
                            await ctx.send(f"Model '{model}' not found. Available models: {', '.join(available_models)}")
                    else:
                        await ctx.send(f"Failed to fetch available models. Status: {resp.status}")
            except Exception as e:
                await ctx.send(f"Error fetching models: {str(e)}")

    @air_config.command(name="setmaxtokens")
    @commands.is_owner()
    async def air_setmaxtokens(self, ctx: commands.Context, max_tokens: int):
        """Set the maximum number of tokens for the AI response."""
        if max_tokens < 1 or max_tokens > 2048:
            await ctx.send("Invalid token count. Please choose a number between 1 and 2048.")
            return
        await self.config.max_tokens.set(max_tokens)
        await ctx.send(f"Maximum tokens set to: {max_tokens}")

    @air_config.command(name="enable")
    @commands.is_owner()
    async def air_enable(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Enable the AI responder in a specific channel or the current channel."""
        channel = channel or ctx.channel
        async with self.config.enabled_channels() as channels:
            if channel.id not in channels:
                channels.append(channel.id)
        await ctx.send(f"AI responder enabled in {channel.mention}")

    @air_config.command(name="disable")
    @commands.is_owner()
    async def air_disable(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Disable the AI responder in a specific channel or the current channel."""
        channel = channel or ctx.channel
        async with self.config.enabled_channels() as channels:
            if channel.id in channels:
                channels.remove(channel.id)
        await ctx.send(f"AI responder disabled in {channel.mention}")

    @air_config.command(name="settings")
    @commands.is_owner()
    async def air_settings(self, ctx: commands.Context):
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

    @air_config.command(name="testapi")
    @commands.is_owner()
    async def air_testapi(self, ctx: commands.Context):
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

    @air_config.command(name="setpersonality")
    @commands.is_owner()
    async def air_setpersonality(self, ctx: commands.Context, *, personality: str):
        """Set a custom AI personality/prompt."""
        await self.config.custom_personality.set(personality)
        await ctx.send(f"Custom AI personality set to: {personality}")

    @air_config.command(name="savepersonality")
    @commands.is_owner()
    async def air_savepersonality(self, ctx: commands.Context, name: str):
        """Save the current AI personality with a given name."""
        current_personality = await self.config.custom_personality()
        async with self.config.personalities() as personalities:
            personalities[name] = current_personality
        await ctx.send(f"Personality '{name}' saved successfully.")

    @air_config.command(name="loadpersonality")
    @commands.is_owner()
    async def air_loadpersonality(self, ctx: commands.Context, name: str):
        """Load a saved AI personality by name."""
        async with self.config.personalities() as personalities:
            if name in personalities:
                await self.config.custom_personality.set(personalities[name])
                await ctx.send(f"Personality '{name}' loaded successfully.")
            else:
                await ctx.send(f"Personality '{name}' not found.")

    @air_config.command(name="listpersonalities")
    @commands.is_owner()
    async def air_listpersonalities(self, ctx: commands.Context):
        """List all saved AI personalities."""
        personalities = await self.config.personalities()
        if personalities:
            personality_list = "\n".join(personalities.keys())
            await ctx.send(f"Saved personalities:\n{personality_list}")
        else:
            await ctx.send("No saved personalities found.")

    @air_config.command(name="settimeout")
    @commands.is_owner()
    async def air_settimeout(self, ctx: commands.Context, timeout: int):
        """Set the API timeout in seconds."""
        if timeout < 60 or timeout > 600:
            await ctx.send("Invalid timeout. Please choose a number between 60 and 600 seconds.")
            return
        await self.config.api_timeout.set(timeout)
        await ctx.send(f"API timeout set to: {timeout} seconds")

    @air.command(name="chat")
    async def air_chat(self, ctx: commands.Context, *, message: str):
        """Chat with the AI without mentioning the bot."""
        fake_message = ctx.message
        fake_message.content = f"{self.bot.user.mention} {message}"
        await self.respond_to_mention(fake_message)

    @air.command(name="clearhistory")
    async def air_clearhistory(self, ctx: commands.Context, user: discord.Member = None):
        """Clear conversation history for a user or yourself."""
        user = user or ctx.author
        if user != ctx.author and not await self.bot.is_owner(ctx.author):
            await ctx.send("You can only clear your own conversation history.")
            return

        db_path = await self.config.db_path()
        with closing(sqlite3.connect(db_path)) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute('DELETE FROM conversation_history WHERE user_id = ?', (user.id,))
                conn.commit()

        await ctx.send(f"Conversation history cleared for {user.display_name}.")

    @air.command(name="history")
    async def air_history(self, ctx: commands.Context, user: discord.Member = None, limit: int = 5):
        """View recent conversation history for a user or yourself."""
        user = user or ctx.author
        if user != ctx.author and not await self.bot.is_owner(ctx.author):
            await ctx.send("You can only view your own conversation history.")
            return

        db_path = await self.config.db_path()
        with closing(sqlite3.connect(db_path)) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute('''
                    SELECT message, response, timestamp
                    FROM conversation_history
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (user.id, limit))
                rows = cursor.fetchall()

        if not rows:
            await ctx.send(f"No conversation history found for {user.display_name}.")
            return

        history = []
        for msg, resp, timestamp in rows:
            history.append(f"**{timestamp}**")
            history.append(f"User: {msg}")
            history.append(f"Bot: {resp}")
            history.append("")

        for page in pagify("\n".join(history), delims=["\n\n"], page_length=1900):
            await ctx.send(page)

    async def update_langchain_components(self):
        api_url = await self.config.api_url()
        model = await self.config.model()
        
        self.llm = Ollama(base_url=api_url, model=model)
        
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            input_key="human_input",
            return_messages=True
        )
        
        custom_personality = await self.config.custom_personality()
        
        prompt = PromptTemplate(
            input_variables=["personality", "context", "current_time", "chat_history", "human_input"],
            template="""
            System: You are an AI assistant with the following personality: {personality}
            You are in a Discord server, responding to user messages.
            Respond naturally and conversationally, as if you're chatting with a friend.
            Do not mention that you're an AI or that this is a prompt.

            Context:
            {context}
            Current time (UTC): {current_time}

            Chat History:
            {chat_history}

            Human: {human_input}

            Assistant: """
        )
        
        self.conversation_chain = ConversationChain(
            llm=self.llm,
            memory=memory,
            prompt=prompt,
            verbose=True
        )
        
        tools = self.setup_tools()
        
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=LLMSingleActionAgent(
                llm_chain=self.conversation_chain,
                output_parser=self.CustomOutputParser(),
                stop=["\nObservation:"],
                allowed_tools=[tool.name for tool in tools]
            ),
            tools=tools,
            memory=memory,
            verbose=True
        )

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    bot.add_listener(cog.on_message)
