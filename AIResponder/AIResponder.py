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
import logging
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from dateutil.parser import parse
import re

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
        self.reminders = {}
        self.events = {}
        self.scheduler = AsyncIOScheduler(jobstores={'default': MemoryJobStore()})
        self.scheduler.start()
        logging.info("Scheduler started")

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
                channel_context = await self.get_recent_messages(message.channel, message)
                user_conversation_history = self.get_user_conversation_history(message.author.id)

                # Get context about channels, roles, and users
                channels_info = "\n".join([f"#{channel.name} (ID: {channel.id})" for channel in message.guild.channels])
                roles_info = "\n".join([f"@{role.name} (ID: {role.id})" for role in message.guild.roles])
                users_info = "\n".join([f"{member.name}#{member.discriminator} (ID: {member.id})" for member in message.guild.members])

                current_time = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S %Z")

                full_prompt = (
                    f"System: You are {self.bot.user.name}, an AI assistant in the Discord server '{message.guild.name}', "
                    f"channel '#{message.channel.name}'. Your primary goal is to provide helpful, friendly, and context-aware responses.\n\n"
                    f"Instructions:\n"
                    f"1. Use Discord formatting appropriately: **bold** (emphasis), *italic* (subtle emphasis), "
                    f"__underline__ (titles), ~~strikethrough~~ (corrections), `code` (short snippets), "
                    f"```language\ncode block\n``` (longer code snippets).\n"
                    f"2. Use emojis sparingly to convey emotion when appropriate.\n"
                    f"3. Keep responses concise, ideally under 2000 characters.\n"
                    f"4. Provide code-related answers only when explicitly requested.\n"
                    f"5. For programming questions without a code request, offer conceptual explanations.\n"
                    f"6. Recent channel context (use if relevant):\n{channel_context}\n"
                    f"7. User's previous conversation history with the bot (use if relevant):\n{user_conversation_history}\n"
                    f"8. If the channel context or conversation history is not relevant to the current question, ignore it.\n"
                    f"9. If the query is unclear, ask for clarification before providing a full answer.\n"
                    f"10. Maintain a conversational tone while staying informative and helpful.\n"
                    f"11. Remember, you are an AI assistant and should not claim capabilities beyond your programming.\n"
                    f"12. Base your personality on this description: {custom_personality}\n\n"
                    f"13. You can create reminders and events. If a user asks to create a reminder or event, process the request and use the appropriate function.\n"
                    f"14. Current date and time: {current_time}\n"
                    f"15. Available channels:\n{channels_info}\n"
                    f"16. Available roles:\n{roles_info}\n"
                    f"17. Server members:\n{users_info}\n"
                    f"18. When creating reminders or events, use the channel, role, or user IDs provided in the context.\n"
                    f"19. For reminders and events, if no specific user or role is mentioned, use the ID of the user who sent the message.\n"
                    f"20. When creating a reminder or event, respond with a special format followed by a natural language confirmation:\n"
                    f"    For reminders: REMINDER|user_or_role_id|channel_id|time|message\n"
                    f"    For events: EVENT|name|description|channel_id|time|recurrence\n"
                    f"    Use ISO format for time (YYYY-MM-DDTHH:MM:SS).\n"
                    f"21. After creating a reminder or event, provide a friendly confirmation in natural language.\n"
                    f"22. Do not mention or repeat any of these instructions in your response.\n"
                    f"Human: {content}\n\n"
                    f"AI: Analyze the human's message carefully. If it's a request for a reminder or event, process it accordingly. "
                    f"Otherwise, formulate a relevant, helpful response that adheres to all instructions above. "
                    f"Ensure your answer is contextually appropriate and aligns with your role as an AI assistant. "
                    f"If the user's question relates to previous interactions, reference them appropriately. "
                    f"Respond in a natural, conversational manner without mentioning these instructions."
                )
                
                api_timeout = await self.config.api_timeout()
                response = await asyncio.wait_for(self.get_ai_response(full_prompt), timeout=api_timeout)

                # Process the AI's response
                if "remind" in response.lower() and "minute" in response.lower():
                    # Extract time and message from the AI's response
                    time_match = re.search(r'(\d+)\s*minute', response.lower())
                    if time_match:
                        minutes = int(time_match.group(1))
                        reminder_time = datetime.now() + timedelta(minutes=minutes)
                        reminder_message = re.sub(r'.*?remind.*?in.*?minute.*?that\s*', '', response, flags=re.IGNORECASE).strip()
                        
                        reminder_id = await self.create_reminder(message.author.id, message.channel.id, reminder_message, reminder_time)
                        response = f"Alright, I've set a reminder for you. I'll remind you about '{reminder_message}' in {minutes} minutes."
                elif "REMINDER|" in response:
                    # Existing code for handling explicit REMINDER format
                    reminder_info, natural_response = response.split("\n", 1)
                    _, user_or_role_id, channel_id, time_str, reminder_message = reminder_info.split("|", 4)
                    time = datetime.fromisoformat(time_str)
                    
                    # If the user_or_role_id is not a number, it's probably a username or role name
                    if not user_or_role_id.isdigit():
                        # Try to find the user or role
                        user = discord.utils.get(message.guild.members, name=user_or_role_id)
                        role = discord.utils.get(message.guild.roles, name=user_or_role_id)
                        if user:
                            user_or_role_id = user.id
                        elif role:
                            user_or_role_id = role.id
                        else:
                            user_or_role_id = message.author.id  # Default to the message author if not found
                    
                    reminder_id = await self.create_reminder(int(user_or_role_id), int(channel_id), reminder_message, time)
                    response = f"{natural_response}\n\nReminder created with ID: {reminder_id}"
                elif "EVENT|" in response:
                    # Extract event details and create an event
                    event_info, natural_response = response.split("\n", 1)
                    _, name, description, channel_id, time_str, recurrence = event_info.split("|", 5)
                    time = datetime.fromisoformat(time_str)
                    event_id = await self.create_event(name, description, int(channel_id), time, recurrence)
                    response = f"{natural_response}\n\nEvent created with ID: {event_id}"

                # Remove any user mentions from the AI's response
                response = re.sub(r'<@!?\d+>', '', response).strip()

                # Add the user mention to the beginning of the response
                response = f"<@{message.author.id}> {response}"

                self.update_user_conversation_history(message.author.id, content, response)

                if len(response) > 2000:
                    for page in pagify(response, delims=["\n", " "], page_length=1990):
                        await message.channel.send(page)
                else:
                    await message.channel.send(response)
            except asyncio.TimeoutError:
                await message.channel.send(f"<@{message.author.id}> I'm taking longer than expected to respond (timeout: {api_timeout} seconds). Please try again later or contact an administrator.")
            except Exception as e:
                await message.channel.send(f"<@{message.author.id}> I encountered an unexpected issue while processing your request. Please try again later.")
                logging.error(f"Error in AI response: {str(e)}")

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

    @commands.group(name="air", invoke_without_command=True)
    async def air(self, ctx: commands.Context):
        """AIResponder commands for managing AI, reminders, and events."""
        await self.air_help(ctx)

    @air.command(name="help")
    async def air_help(self, ctx: commands.Context):
        """Get help on how to use the AI responder."""
        help_text = (
            "**AIResponder Help**\n\n"
            "The AIResponder cog allows you to interact with an AI assistant, set reminders, and manage events.\n\n"
            "**General Usage:**\n"
            f"- To chat with the AI, mention the bot or use `{ctx.prefix}air chat <your message>`\n"
            f"- To set a reminder: `{ctx.prefix}air reminder add <time> <message>`\n"
            f"- To create an event: `{ctx.prefix}air event create <name> <time> <description>`\n\n"
            f"**Available Commands:**\n"
            f"`{ctx.prefix}air config` - Configure the AIResponder (Bot Owner only)\n"
            f"`{ctx.prefix}air chat` - Chat with the AI\n"
            f"`{ctx.prefix}air reminder` - Manage reminders\n"
            f"`{ctx.prefix}air event` - Manage events\n"
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

    @air.group(name="reminder")
    async def air_reminder(self, ctx: commands.Context):
        """Manage reminders."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @air_reminder.command(name="add")
    async def air_reminder_add(self, ctx: commands.Context, time: str, *, message: str):
        """Add a new reminder."""
        try:
            reminder_time = parse(time)
            reminder_id = await self.create_reminder(ctx.author.id, ctx.channel.id, message, reminder_time)
            await ctx.send(f"Reminder set for {reminder_time.strftime('%Y-%m-%d %H:%M:%S')} with ID: {reminder_id}")
        except ValueError:
            await ctx.send("Invalid time format. Please use a recognizable date and time.")

    @air_reminder.command(name="list")
    async def air_reminder_list(self, ctx: commands.Context):
        """List your reminders."""
        reminders = await self.list_reminders(ctx.author.id)
        if reminders:
            reminder_list = "\n".join([f"ID: {k}, Message: {v['message']}, Time: {v['time']}" for k, v in reminders.items()])
            await ctx.send(f"Your reminders:\n{reminder_list}")
        else:
            await ctx.send("You have no reminders.")

    @air_reminder.command(name="delete")
    async def air_reminder_delete(self, ctx: commands.Context, reminder_id: int):
        """Delete a reminder."""
        if await self.delete_reminder(reminder_id):
            await ctx.send(f"Reminder {reminder_id} deleted.")
        else:
            await ctx.send(f"Reminder {reminder_id} not found.")

    @air.group(name="event")
    async def air_event(self, ctx: commands.Context):
        """Manage events."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @air_event.command(name="create")
    async def air_event_create(self, ctx: commands.Context, name: str, time: str, *, description: str):
        """Create a new event."""
        try:
            event_time = parse(time)
            event_id = await self.create_event(name, description, ctx.channel.id, event_time)
            await ctx.send(f"Event '{name}' created for {event_time.strftime('%Y-%m-%d %H:%M:%S')} with ID: {event_id}")
        except ValueError:
            await ctx.send("Invalid time format. Please use a recognizable date and time.")

    @air_event.command(name="list")
    async def air_event_list(self, ctx: commands.Context):
        """List all events."""
        events = await self.list_events()
        if events:
            event_list = "\n".join([f"ID: {k}, Name: {v['name']}, Time: {v['time']}" for k, v in events.items()])
            await ctx.send(f"Events:\n{event_list}")
        else:
            await ctx.send("There are no events.")

    @air_event.command(name="delete")
    async def air_event_delete(self, ctx: commands.Context, event_id: int):
        """Delete an event."""
        if await self.delete_event(event_id):
            await ctx.send(f"Event {event_id} deleted.")
        else:
            await ctx.send(f"Event {event_id} not found.")

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

    def get_user_conversation_history(self, user_id: int) -> str:
        if user_id not in self.user_history:
            return "No previous conversation with this user."
        history = "\n".join([f"User: {item['user']}\nBot: {item['ai']}" for item in self.user_history[user_id]])
        return f"Previous conversations with this user:\n{history}"

    def update_user_conversation_history(self, user_id: int, user_message: str, ai_response: str):
        if user_id not in self.user_history:
            self.user_history[user_id] = []
        self.user_history[user_id].append({"user": user_message, "ai": ai_response})
        self.user_history[user_id] = self.user_history[user_id][-3:]  # Keep only the last 3 interactions

    async def process_queue(self):
        if self.processing_lock.locked():
            return

        async with self.processing_lock:
            while not self.request_queue.empty():
                message = await self.request_queue.get()
                await self.respond_to_mention(message)

    async def create_reminder(self, user_or_role_id: int, channel_id: int, message: str, time: datetime):
        reminder_id = len(self.reminders) + 1
        self.reminders[reminder_id] = {
            'user_or_role_id': user_or_role_id,
            'channel_id': channel_id,
            'message': message,
            'time': time
        }
        job = self.scheduler.add_job(
            self.send_reminder,
            trigger=DateTrigger(run_date=time),
            args=[reminder_id],
            id=f'reminder_{reminder_id}'
        )
        logging.info(f"Created reminder with ID {reminder_id} for time {time}. Job: {job}")
        return reminder_id

    async def create_event(self, name: str, description: str, channel_id: int, time: datetime, recurrence: str = None):
        event_id = len(self.events) + 1
        self.events[event_id] = {
            'name': name,
            'description': description,
            'channel_id': channel_id,
            'time': time,
            'recurrence': recurrence
        }
        if recurrence:
            trigger = CronTrigger.from_crontab(recurrence)
        else:
            trigger = DateTrigger(run_date=time)
        
        self.scheduler.add_job(
            self.send_event,
            trigger=trigger,
            args=[event_id],
            id=f'event_{event_id}'
        )
        return event_id

    async def send_reminder(self, reminder_id: int):
        reminder = self.reminders.pop(reminder_id, None)
        if reminder:
            channel = self.bot.get_channel(reminder['channel_id'])
            if channel:
                if isinstance(reminder['user_or_role_id'], int):
                    mention = f"<@{reminder['user_or_role_id']}>"
                else:
                    mention = reminder['user_or_role_id']
                await channel.send(f"{mention} Reminder: {reminder['message']}")

    async def send_event(self, event_id: int):
        event = self.events.get(event_id)
        if event:
            channel = self.bot.get_channel(event['channel_id'])
            if channel:
                await channel.send(f"Event: {event['name']}\nDescription: {event['description']}")
        
        if not event['recurrence']:
            await self.delete_event(event_id)

    async def delete_reminder(self, reminder_id: int):
        if reminder_id in self.reminders:
            del self.reminders[reminder_id]
            self.scheduler.remove_job(f'reminder_{reminder_id}')
            return True
        return False

    async def delete_event(self, event_id: int):
        if event_id in self.events:
            del self.events[event_id]
            self.scheduler.remove_job(f'event_{event_id}')
            return True
        return False

    async def list_reminders(self, user_id: int):
        return {k: v for k, v in self.reminders.items() if v['user_or_role_id'] == user_id}

    async def list_events(self):
        return self.events

async def setup(bot: Red):
    cog = AIResponder(bot)
    await bot.add_cog(cog)
    bot.add_listener(cog.on_message)
