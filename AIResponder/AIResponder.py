import aiohttp
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from typing import Dict, List, Tuple
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
            "api_timeout": 300,
            "db_path": "airesponder.db",
            "personalities": {},
        }
        self.config.register_global(**default_global)
        self.user_cooldowns: Dict[int, Tuple[datetime, int]] = {}
        self.request_queue: Queue = Queue()
        self.processing_lock = asyncio.Lock()
        asyncio.create_task(self.setup_database())

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

                full_prompt = (
                    f"System: You are {self.bot.user.name}, an AI assistant in a Discord server. "
                    f"Respond naturally and conversationally, as if you're chatting with a friend. "
                    f"Do not mention or acknowledge that you're an AI or that this is a prompt. "
                    f"Do not use commands or explain your thought process. Just respond directly to the user's message.\n\n"
                    f"Context:\n{context_str}\n"
                    f"Current time (UTC): {current_time}\n\n"
                    f"Instructions:\n"
                    f"1. Analyze the user's message and provide a relevant, helpful response.\n"
                    f"2. Use Discord formatting when appropriate: **bold**, *italic*, __underline__, ~~strikethrough~~, `code`, ```code blocks```.\n"
                    f"3. Use emojis sparingly to convey emotion when appropriate.\n"
                    f"4. Keep responses concise, under 2000 characters.\n"
                    f"5. Base your personality on this description: {custom_personality}\n"
                    f"6. Use the conversation history to maintain context and continuity.\n\n"
                    f"Human: {content}\n\n"
                    f"Assistant: Certainly! I'll analyze the message and respond accordingly, taking into account our conversation history."
                )

                api_timeout = await self.config.api_timeout()
                response = await asyncio.wait_for(self.get_ai_response(full_prompt), timeout=api_timeout)

                # Remove any user mentions from the AI's response
                response = re.sub(r'<@!?\d+>', '', response).strip()

                # Add the user mention to the beginning of the response
                response = f"<@{message.author.id}> {response}"

                await self.update_user_conversation_history(message.author.id, content, response)

                if len(response) > 2000:
                    for page in pagify(response, delims=["\n", " "], page_length=1990):
                        await message.channel.send(page)
                else:
                    await message.channel.send(response)

            except asyncio.TimeoutError:
                error_message = f"Response timed out after {api_timeout} seconds."
                await self.log_error(error_message)
                await message.channel.send(f"<@{message.author.id}> {error_message} Please try again later or contact an administrator.")
            except Exception as e:
                error_message = "An unexpected error occurred while processing your request."
                await self.log_error(error_message, e)
                await message.channel.send(f"<@{message.author.id}> {error_message} Please try again later.")

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

    async def get_ai_response(self, prompt: str) -> str:
        api_url = await self.config.api_url()
        model = await self.config.model()
        max_tokens = await self.config.max_tokens()
        api_timeout = await self.config.api_timeout()

        prompt_tokens = self.count_tokens(prompt)
        available_tokens = 100000 - prompt_tokens  # Assuming 100k token context window

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "max_tokens": min(max_tokens, available_tokens)
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

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    bot.add_listener(cog.on_message)
