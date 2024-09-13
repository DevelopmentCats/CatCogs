from redbot.core import commands, Config
import discord
from datetime import datetime, timedelta
import asyncio
import logging
from functools import lru_cache
import time
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import os
from collections import defaultdict
import matplotlib.pyplot as plt
import io
from wordcloud import WordCloud
import numpy as np
from PIL import Image
import aiohttp
import matplotlib.animation as animation
import plotly.graph_objects as go

ACTIVITY_SUMMARY_LENGTH = 50

class UserTrackerError(Exception):
    pass

class RateLimiter:
    def __init__(self, calls, period):
        self.calls = calls
        self.period = period
        self.timestamps = []

    async def __aenter__(self):
        now = datetime.now()
        self.timestamps = [ts for ts in self.timestamps if now - ts <= self.period]
        if len(self.timestamps) >= self.calls:
            sleep_time = (self.timestamps[0] + self.period - now).total_seconds()
            await asyncio.sleep(max(0, sleep_time))
        self.timestamps.append(now)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class UserTracker(commands.Cog):
    """
    Track and log activities of specified users in real-time.

    This cog allows you to monitor messages, voice state changes, status updates, and image attachments of tracked users.
    It uses threads for individual user logs and maintains a main message with links to these threads.
    """
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "tracked_users": [],
            "log_channel": None,
            "user_threads": {},
            "main_message_id": None,
            "authorized_users": [],
            "user_themes": {},
            "last_logged_activities": {}
        }
        self.config.register_guild(**default_guild)
        self.lock = asyncio.Lock()
        self.task = bot.loop.create_task(self.initialize())
        self.logger = logging.getLogger('UserTracker')
        self.rate_limiter = RateLimiter(calls=5, period=timedelta(seconds=5))
        self.last_activity = defaultdict(dict)
        self.inactivity_threshold = timedelta(days=7)
        self.check_inactivity_task = bot.loop.create_task(self.check_inactivity())
        self.fill_missed_activities_task = bot.loop.create_task(self.check_and_fill_missed_activities())

    async def initialize(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            log_channel_id = await self.config.guild(guild).log_channel()
            if log_channel_id:
                channel = guild.get_channel(log_channel_id)
                if not channel:
                    await self.config.guild(guild).log_channel.set(None)
                    await self.config.guild(guild).user_threads.set({})
                    await self.config.guild(guild).main_message_id.set(None)
                    print(f"Log channel for guild {guild.name} was not found. Settings cleared.")
                else:
                    await self.ensure_main_message(guild)

    def cog_unload(self):
        if hasattr(self, 'task'):
            self.task.cancel()
        if hasattr(self, 'check_inactivity_task'):
            self.check_inactivity_task.cancel()
        if hasattr(self, 'fill_missed_activities_task'):
            self.fill_missed_activities_task.cancel()

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    async def track(self, ctx):
        """
        User tracking commands.

        Use subcommands to manage tracked users, log channels, and user authorizations.
        Only authorized users can use these commands.

        Subcommands:
        - add: Add a user to track
        - remove: Remove a user from tracking
        - list: List all tracked users
        - channel: Set or view the log channel
        - authorize: Authorize a user to use UserTracker commands (Bot Owner only)
        - deauthorize: Remove authorization for a user (Bot Owner only)
        - analyze: Analyze the sentiment and toxicity of a user's recent messages
        - heatmap: Generate a 24-hour circular heatmap of user activity
        - wordcloud: Generate a word cloud of the user's most used words and phrases
        - theme: Set a custom color theme for a tracked user's embeds
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
        await ctx.send_help(ctx.command)

    @track.command(name="add")
    async def track_add(self, ctx, user: discord.User):
        """
        Add a user to track in this server.

        This will create a new thread for logging the user's activities.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
        async with self.lock:
            async with self.config.guild(ctx.guild).tracked_users() as tracked_users:
                if user.id not in tracked_users:
                    tracked_users.append(user.id)
                    await self.create_user_thread(ctx.guild, user)
                    await self.ensure_main_message(ctx.guild)
                    await ctx.send(f"✅ User {user.name} (ID: {user.id}) has been added to the tracking list for this server.")
                else:
                    await ctx.send(f"ℹ️ User {user.name} (ID: {user.id}) is already being tracked in this server.")

    @track.command(name="remove")
    async def track_remove(self, ctx, user: discord.User):
        """
        Remove a user from tracking in this server.

        This will delete the user's log thread.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
        async with self.lock:
            async with self.config.guild(ctx.guild).tracked_users() as tracked_users:
                if user.id in tracked_users:
                    tracked_users.remove(user.id)
                    await self.remove_user_thread(ctx.guild, user)
                    await self.ensure_main_message(ctx.guild)
                    await ctx.send(f"✅ User {user.name} (ID: {user.id}) has been removed from the tracking list for this server.")
                else:
                    await ctx.send(f"ℹ️ User {user.name} (ID: {user.id}) is not being tracked in this server.")

    @track.command(name="list")
    async def track_list(self, ctx):
        """
        List all tracked users in this server.

        Displays a list of tracked users with their IDs.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
        tracked_users = await self.config.guild(ctx.guild).tracked_users()
        if tracked_users:
            user_list = []
            for user_id in tracked_users:
                user = self.bot.get_user(user_id)
                if user:
                    user_list.append(f"{user.name} (ID: {user.id})")
                else:
                    user_list.append(f"Unknown User (ID: {user_id})")
            
            embed = discord.Embed(title=f"Tracked Users in {ctx.guild.name}", color=discord.Color.blue())
            embed.description = "\n".join(user_list)
            await ctx.send(embed=embed)
        else:
            await ctx.send("ℹ️ No users are currently being tracked in this server.")

    @track.command(name="channel")
    async def track_channel(self, ctx, channel: discord.TextChannel = None):
        """
        Set or view the channel for logging tracked user activities in this server.

        If no channel is specified, it will display the current log channel.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
        if channel is None:
            current_channel_id = await self.config.guild(ctx.guild).log_channel()
            if current_channel_id:
                current_channel = ctx.guild.get_channel(current_channel_id)
                if current_channel:
                    await ctx.send(f"Current log channel for this server: {current_channel.mention}")
                else:
                    await ctx.send("ℹ️ The previously set log channel in this server no longer exists.")
            else:
                await ctx.send("ℹ️ No log channel is currently set for this server.")
        else:
            if not channel.permissions_for(ctx.guild.me).send_messages:
                await ctx.send(f"❌ I don't have permission to send messages in {channel.mention}. Please choose a different channel or adjust my permissions.")
                return
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            await self.config.guild(ctx.guild).user_threads.set({})
            await self.config.guild(ctx.guild).main_message_id.set(None)
            await self.setup_log_channel(ctx.guild, channel)
            await ctx.send(f"✅ Log channel for this server set to {channel.mention}")

    async def setup_log_channel(self, guild, channel):
        tracked_users = await self.config.guild(guild).tracked_users()
        user_threads = await self.config.guild(guild).user_threads()
        
        for user_id in tracked_users:
            user = self.bot.get_user(user_id)
            if user:
                if str(user_id) not in user_threads:
                    await self.create_user_thread(guild, user)
                else:
                    thread_id = user_threads[str(user_id)]
                    thread = guild.get_thread(thread_id)
                    if not thread:
                        await self.create_user_thread(guild, user)
        
        await self.ensure_main_message(guild)

    async def ensure_main_message(self, guild):
        log_channel_id = await self.config.guild(guild).log_channel()
        main_message_id = await self.config.guild(guild).main_message_id()
        if not log_channel_id:
            return

        channel = guild.get_channel(log_channel_id)
        if not channel:
            return

        if main_message_id:
            try:
                message = await channel.fetch_message(main_message_id)
                await self.update_main_message(guild)
            except discord.NotFound:
                await self.create_main_message(guild, channel)
        else:
            await self.create_main_message(guild, channel)

        # Double-check to ensure the message was created
        main_message_id = await self.config.guild(guild).main_message_id()
        if not main_message_id:
            await self.create_main_message(guild, channel)

    async def create_main_message(self, guild, channel):
        embed = await self.get_thread_list_embed(guild)
        try:
            message = await channel.send(embed=embed)
            await self.config.guild(guild).main_message_id.set(message.id)
        except discord.errors.Forbidden:
            print(f"Error: Bot doesn't have permission to send messages in the log channel for guild {guild.id}")
        except Exception as e:
            print(f"Error creating main message in guild {guild.id}: {e}")

    async def update_main_message(self, guild):
        log_channel_id = await self.config.guild(guild).log_channel()
        main_message_id = await self.config.guild(guild).main_message_id()
        if not log_channel_id or not main_message_id:
            return

        channel = guild.get_channel(log_channel_id)
        if not channel:
            return

        try:
            message = await channel.fetch_message(main_message_id)
            embed = await self.get_thread_list_embed(guild)
            await message.edit(embed=embed)
        except discord.NotFound:
            await self.create_main_message(guild, channel)

    async def get_thread_list_embed(self, guild):
        embed = discord.Embed(title="🕵️ User Log Threads 🕵️", color=discord.Color.dark_purple())
        embed.description = "Behold, the chronicles of our subjects! Click the links below to dive into the rabbit hole of user logs:"

        user_threads = await self.config.guild(guild).user_threads()
        tasks = []
        for user_id, thread_id in user_threads.items():
            tasks.append(self.get_user_field(guild, user_id, thread_id))
        
        fields = await asyncio.gather(*tasks)
        for field in fields:
            if field:
                embed.add_field(**field)

        if not user_threads:
            embed.add_field(name="🦗 Crickets...", value="The void echoes... Use the `track add` command to start tracking users and breathe life into this desolate space!")

        embed.set_footer(text="Last updated | May the logs be ever in your favor")
        embed.timestamp = datetime.utcnow()
        return embed

    async def get_user_field(self, guild, user_id, thread_id):
        user = self.bot.get_user(int(user_id))
        thread = guild.get_thread(thread_id)
        if user and thread:
            try:
                last_activity = await self.get_last_message(thread)
            except Exception as e:
                last_activity = f"Error retrieving activity: {str(e)}"
            
            return {
                "name": f"{user.name} (ID: {user.id})",
                "value": f"[View Logs]({thread.jump_url})\nLast activity: {last_activity}",
                "inline": False
            }
        elif user:
            return {
                "name": f"{user.name} (ID: {user.id})",
                "value": "Thread not found. It may have been deleted.",
                "inline": False
            }
        return None

    @lru_cache(maxsize=128)
    def get_last_message_cached(self, thread_id):
        async def _get_last_message():
            thread = self.bot.get_channel(thread_id)
            if not thread:
                return "Thread not found"
            
            async for message in thread.history(limit=1):
                if message.author == self.bot.user and message.embeds:
                    embed = message.embeds[0]
                    activity_type = embed.title
                    details = embed.fields[0].value
                    if activity_type == "Message Sent":
                        content = details.split("**Content:** ")[-1]
                        summary = f"Message: {content[:ACTIVITY_SUMMARY_LENGTH]}..."
                        if embed.image:
                            summary += " [Image]"
                        return summary
                    else:
                        return f"{activity_type}: {details[:ACTIVITY_SUMMARY_LENGTH]}..."
                elif message.author != self.bot.user:
                    summary = f"User message: {message.content[:ACTIVITY_SUMMARY_LENGTH]}..."
                    if message.attachments:
                        summary += " [Image]"
                    return summary
            return "No activity logged yet"
        
        return asyncio.create_task(_get_last_message())

    async def get_last_message(self, thread):
        return await self.get_last_message_cached(thread.id)

    async def create_user_thread(self, guild, user):
        log_channel_id = await self.config.guild(guild).log_channel()
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return

        thread_name = f"Logs for {user.name} ({user.id})"
        
        async with self.config.guild(guild).user_threads() as user_threads:
            if str(user.id) in user_threads:
                thread = guild.get_thread(user_threads[str(user.id)])
                if thread:
                    return thread
                # If thread doesn't exist, remove it from user_threads
                del user_threads[str(user.id)]
            
            # Check for existing threads with the same name
            for thread in log_channel.threads:
                if thread.name == thread_name:
                    user_threads[str(user.id)] = thread.id
                    return thread
            
            # Create a new thread only if one doesn't exist
            thread = await log_channel.create_thread(name=thread_name, auto_archive_duration=10080)
            user_threads[str(user.id)] = thread.id

        await self.update_main_message(guild)
        return thread

    async def remove_user_thread(self, guild, user):
        async with self.config.guild(guild).user_threads() as user_threads:
            thread_id = user_threads.pop(str(user.id), None)
        if thread_id:
            thread = guild.get_thread(thread_id)
            if thread:
                await thread.delete()
        await self.update_main_message(guild)

    async def get_user_thread(self, guild, user):
        user_threads = await self.config.guild(guild).user_threads()
        thread_id = user_threads.get(str(user.id))
        if thread_id:
            return guild.get_thread(thread_id)
        return None

    def create_embed(self, user, activity_type, details):
        emoji_map = {
            "Message Sent": "💬",
            "Voice Activity": "🎙️",
            "Status Change": "🔄",
            "Activity Change": "🎮",
            "Message Edited": "✏️",
            "Message Deleted": "🗑️"
        }
        emoji = emoji_map.get(activity_type, "ℹ️")
        
        user_themes = self.config.guild(user.guild).user_themes()
        color = discord.Color(user_themes.get(str(user.id), discord.Color.random().value))
        
        embed = discord.Embed(
            title=f"{emoji} {activity_type}",
            color=color,
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=f"{user.name} (ID: {user.id})", icon_url=user.display_avatar.url)
        embed.add_field(name="Details", value=details, inline=False)
        return embed

    async def log_activity(self, user, activity_type, details, image_urls=None):
        async with self.rate_limiter:
            for guild in self.bot.guilds:
                if user not in guild.members:
                    continue
                try:
                    tracked_users = await self.config.guild(guild).tracked_users()
                    if user.id in tracked_users:
                        thread = await self.get_user_thread(guild, user)
                        if thread:
                            embed = self.create_embed(user, activity_type, details)
                            
                            if activity_type == "Message Sent":
                                content = details.split("**Content:** ")[-1]
                                analysis = await self.analyze_text(content)
                                embed.add_field(name="Sentiment", value=f"{analysis['sentiment']:.2f}", inline=True)
                                embed.add_field(name="Positive", value=f"{analysis['positive']:.2f}", inline=True)
                                embed.add_field(name="Neutral", value=f"{analysis['neutral']:.2f}", inline=True)
                                embed.add_field(name="Negative", value=f"{analysis['negative']:.2f}", inline=True)
                                embed.add_field(name="Toxicity", value="Detected" if analysis['toxicity'] else "Not Detected", inline=True)
                            
                            if image_urls:
                                embed.set_image(url=image_urls[0])
                            await thread.send(embed=embed)
                            
                            for url in image_urls[1:]:
                                await thread.send(url)
                            
                            self.get_last_message_cached.cache_clear()
                            await self.update_main_message(guild)
                            self.last_activity[user.id][guild.id] = datetime.utcnow()
                            
                            # Update the last logged activity timestamp
                            async with self.config.guild(guild).last_logged_activities() as last_logged_activities:
                                last_logged_activities[str(user.id)] = datetime.utcnow().isoformat()
                except Exception as e:
                    self.logger.error(f"Error logging activity for user {user.id} in guild {guild.id}: {e}", exc_info=True)
                    raise UserTrackerError(f"Failed to log activity: {str(e)}")

    async def bot_in_guild(self, guild_id):
        return self.bot.get_guild(guild_id) is not None

    async def analyze_text(self, text):
        try:
            analyzer = SentimentIntensityAnalyzer()
            sentiment_scores = analyzer.polarity_scores(text)
            return {
                'sentiment': sentiment_scores['compound'],
                'positive': sentiment_scores['pos'],
                'neutral': sentiment_scores['neu'],
                'negative': sentiment_scores['neg'],
                'toxicity': sentiment_scores['compound'] < -0.5
            }
        except Exception as e:
            self.logger.error(f"Error in analyze_text: {e}", exc_info=True)
            return {'sentiment': 0, 'positive': 0, 'neutral': 0, 'negative': 0, 'toxicity': False}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not await self.bot_in_guild(message.guild.id):
            return

        try:
            content = message.content if message.content else "[No text content]"
            details = (f"**Server:** {message.guild.name}\n"
                       f"**Channel:** {message.channel.mention}\n"
                       f"**Content:** {content[:1900]}{'...' if len(content) > 1900 else ''}")

            image_urls = [attachment.url for attachment in message.attachments if attachment.content_type.startswith('image')]

            await self.log_activity(message.author, "Message Sent", details, image_urls)
        except Exception as e:
            self.logger.error(f"Error in on_message for user {message.author.id}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel != after.channel:
            try:
                if after.channel:
                    action = f"Joined voice channel {after.channel.name}"
                elif before.channel:
                    action = f"Left voice channel {before.channel.name}"
                else:
                    return

                details = f"**Server:** {member.guild.name}\n**Action:** {action}"
                await self.log_activity(member, "Voice Activity", details)
            except Exception as e:
                self.logger.error(f"Error in on_voice_state_update for user {member.id}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            if before.status != after.status:
                details = f"**Server:** {after.guild.name}\n**New status:** {after.status}"
                await self.log_activity(after, "Status Change", details)

            if before.activity != after.activity:
                activity = after.activity
                if activity:
                    if isinstance(activity, discord.Game):
                        details = f"Playing {activity.name}"
                    elif isinstance(activity, discord.Streaming):
                        details = f"Streaming {activity.name}"
                    elif isinstance(activity, discord.Spotify):
                        details = f"Listening to {activity.title} by {activity.artist}"
                    else:
                        details = str(activity)
                    details = f"**Server:** {after.guild.name}\n**Activity:** {details[:ACTIVITY_SUMMARY_LENGTH]}{'...' if len(details) > ACTIVITY_SUMMARY_LENGTH else ''}"
                    await self.log_activity(after, "Activity Change", details)
        except Exception as e:
            self.logger.error(f"Error in on_member_update for user {after.id}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.author.bot or not await self.bot_in_guild(after.guild.id):
            return
        try:
            details = (f"**Server:** {after.guild.name}\n"
                       f"**Channel:** {after.channel.mention}\n"
                       f"**Before:** {before.content[:900]}{'...' if len(before.content) > 900 else ''}\n"
                       f"**After:** {after.content[:900]}{'...' if len(after.content) > 900 else ''}")
            await self.log_activity(after.author, "Message Edited", details)
        except Exception as e:
            self.logger.error(f"Error in on_message_edit for user {after.author.id}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not await self.bot_in_guild(message.guild.id):
            return
        try:
            details = (f"**Server:** {message.guild.name}\n"
                       f"**Channel:** {message.channel.mention}\n"
                       f"**Content:** {message.content[:1900]}{'...' if len(message.content) > 1900 else ''}")
            await self.log_activity(message.author, "Message Deleted", details)
        except Exception as e:
            self.logger.error(f"Error in on_message_delete for user {message.author.id}: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        try:
            log_channel_id = await self.config.guild(channel.guild).log_channel()
            if channel.id == log_channel_id:
                await self.config.guild(channel.guild).log_channel.set(None)
                await self.config.guild(channel.guild).user_threads.set({})
                await self.config.guild(channel.guild).main_message_id.set(None)
                print(f"Log channel {channel.name} was deleted in guild {channel.guild.name}. Log channel and thread settings have been cleared.")
        except Exception as e:
            self.logger.error(f"Error in on_guild_channel_delete for guild {channel.guild.id}: {e}", exc_info=True)

    @track.command(name="analyze")
    async def track_analyze(self, ctx, user: discord.User):
        """
        Analyze the sentiment and toxicity of a user's recent messages.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
    
        thread = await self.get_user_thread(ctx.guild, user)
        if not thread:
            await ctx.send(f"No log thread found for user {user.name}.")
            return
    
        messages = []
        async for message in thread.history(limit=100):
            if message.author == self.bot.user and message.embeds:
                embed = message.embeds[0]
                if embed.title == "Message Sent":
                    content = embed.fields[0].value.split("**Content:** ")[-1]
                    messages.append(content)
    
        if not messages:
            await ctx.send(f"No recent messages found for user {user.name}.")
            return
    
        combined_text = " ".join(messages)
        analysis = await self.analyze_text(combined_text)
    
        embed = discord.Embed(title=f"Sentiment Analysis for {user.name}", color=discord.Color.blue())
        embed.add_field(name="Overall Sentiment", value=f"{analysis['sentiment']:.2f}", inline=False)
        embed.add_field(name="Positive", value=f"{analysis['positive']:.2f}", inline=True)
        embed.add_field(name="Neutral", value=f"{analysis['neutral']:.2f}", inline=True)
        embed.add_field(name="Negative", value=f"{analysis['negative']:.2f}", inline=True)
        embed.add_field(name="Toxicity", value="Detected" if analysis['toxicity'] else "Not Detected", inline=False)
        
        sentiment_description = "Very Negative"
        if analysis['sentiment'] > -0.5:
            sentiment_description = "Somewhat Negative"
        if analysis['sentiment'] > -0.2:
            sentiment_description = "Neutral"
        if analysis['sentiment'] > 0.2:
            sentiment_description = "Somewhat Positive"
        if analysis['sentiment'] > 0.5:
            sentiment_description = "Very Positive"
        
        embed.add_field(name="Interpretation", value=sentiment_description, inline=False)

        await ctx.send(embed=embed)

    @track.command(name="authorize")
    @commands.is_owner()
    async def track_authorize(self, ctx, user: discord.User):
        """
        Authorize a user to use UserTracker commands (Bot Owner only).

        This allows the specified user to use all UserTracker commands in this server.
        """
        async with self.config.guild(ctx.guild).authorized_users() as authorized_users:
            if user.id not in authorized_users:
                authorized_users.append(user.id)
                await ctx.send(f"✅ User {user.name} (ID: {user.id}) has been authorized to use UserTracker commands in this server.")
            else:
                await ctx.send(f"ℹ️ User {user.name} (ID: {user.id}) is already authorized to use UserTracker commands in this server.")

    @track.command(name="deauthorize")
    @commands.is_owner()
    async def track_deauthorize(self, ctx, user: discord.User):
        """
        Remove authorization for a user to use UserTracker commands (Bot Owner only).

        This prevents the specified user from using UserTracker commands in this server.
        """
        async with self.config.guild(ctx.guild).authorized_users() as authorized_users:
            if user.id in authorized_users:
                authorized_users.remove(user.id)
                await ctx.send(f"✅ User {user.name} (ID: {user.id}) has been deauthorized from using UserTracker commands in this server.")
            else:
                await ctx.send(f"ℹ️ User {user.name} (ID: {user.id}) was not authorized to use UserTracker commands in this server.")

    async def is_authorized(self, ctx):
        if await self.bot.is_owner(ctx.author):
            return True
        authorized_users = await self.config.guild(ctx.guild).authorized_users()
        return ctx.author.id in authorized_users

    async def check_inactivity(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild in self.bot.guilds:
                tracked_users = await self.config.guild(guild).tracked_users()
                for user_id in tracked_users:
                    user = self.bot.get_user(user_id)
                    if user and guild.id in self.last_activity.get(user_id, {}):
                        last_active = self.last_activity[user_id][guild.id]
                        if datetime.utcnow() - last_active > self.inactivity_threshold:
                            await self.send_inactivity_notification(guild, user)
            await asyncio.sleep(86400)  # Check once a day

    async def send_inactivity_notification(self, guild, user):
        log_channel_id = await self.config.guild(guild).log_channel()
        if not log_channel_id:
            return
        channel = guild.get_channel(log_channel_id)
        if channel:
            days_inactive = (datetime.utcnow() - self.last_activity[user.id][guild.id]).days
            message = f"👻 Ghostbuster Alert! 👻\n{user.name} hasn't been seen for {days_inactive} days. " \
                      f"Did they fall into a black hole, or just discover outdoor activities?"
            await channel.send(message)

    async def check_and_fill_missed_activities(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild in self.bot.guilds:
                tracked_users = await self.config.guild(guild).tracked_users()
                last_logged_activities = await self.config.guild(guild).last_logged_activities()
                for user_id in tracked_users:
                    user = self.bot.get_user(user_id)
                    if user:
                        last_logged_str = last_logged_activities.get(str(user_id), datetime.min.isoformat())
                        last_logged = datetime.fromisoformat(last_logged_str)
                        await self.fill_missed_activities(guild, user, last_logged)
            await asyncio.sleep(3600)  # Run every hour

    async def fill_missed_activities(self, guild, user, last_logged):
        # Check messages
        for channel in guild.text_channels:
            async for message in channel.history(after=last_logged, limit=None):
                if message.author.id == user.id:
                    await self.log_activity(user, "Message Sent", f"**Server:** {guild.name}\n**Channel:** {channel.mention}\n**Content:** {message.content[:1900]}")

        # Check voice state
        voice_state = user.voice
        if voice_state and voice_state.channel:
            await self.log_activity(user, "Voice Activity", f"**Server:** {guild.name}\n**Action:** Joined voice channel {voice_state.channel.name}")

        # Check status and activity
        member = guild.get_member(user.id)
        if member:
            await self.log_activity(user, "Status Change", f"**Server:** {guild.name}\n**New status:** {member.status}")
            if member.activity:
                activity_details = str(member.activity)
                await self.log_activity(user, "Activity Change", f"**Server:** {guild.name}\n**Activity:** {activity_details[:ACTIVITY_SUMMARY_LENGTH]}")

        # Update the last logged activity timestamp
        async with self.config.guild(guild).last_logged_activities() as last_logged_activities:
            last_logged_activities[str(user.id)] = datetime.utcnow().isoformat()

    @track.command(name="heatmap")
    async def track_heatmap(self, ctx, user: discord.User):
        """
        Generate a 24-hour circular heatmap of user activity.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return

        thread = await self.get_user_thread(ctx.guild, user)
        if not thread:
            await ctx.send(f"No log thread found for user {user.name}.")
            return

        activity_data = await self.get_user_activity_data(thread)
        heatmap = self.generate_circular_heatmap(activity_data)

        with io.BytesIO() as image_binary:
            heatmap.save(image_binary, 'PNG')
            image_binary.seek(0)
            await ctx.send(f"Behold, the temporal tapestry of {user.name}'s existence!",
                           file=discord.File(fp=image_binary, filename='time_lord_heatmap.png'))

    async def get_user_activity_data(self, thread):
        activity_data = [0] * 24
        async for message in thread.history(limit=None):
            if message.author == self.bot.user and message.embeds:
                hour = message.created_at.hour
                activity_data[hour] += 1
        return activity_data

    def generate_circular_heatmap(self, activity_data):
        fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
        theta = np.linspace(0, 2*np.pi, 24, endpoint=False)
        radii = np.array(activity_data)
        width = 2*np.pi / 24

        bars = ax.bar(theta, radii, width=width, bottom=0.0)
        
        # Color the bars
        norm = plt.Normalize(np.min(radii), np.max(radii))
        for r, bar in zip(radii, bars):
            bar.set_facecolor(plt.cm.viridis(norm(r)))
        
        ax.set_xticks(theta)
        ax.set_xticklabels([f"{h:02d}:00" for h in range(24)])
        ax.set_ylim(0, max(radii) * 1.1)
        ax.set_title("The Circular Chronicles of Time", va='bottom')

        plt.tight_layout()
        
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png')
        img_buf.seek(0)
        
        return Image.open(img_buf)

    @track.command(name="wordcloud")
    async def track_wordcloud(self, ctx, user: discord.User):
        """
        Generate a word cloud of the user's most used words and phrases.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return

        thread = await self.get_user_thread(ctx.guild, user)
        if not thread:
            await ctx.send(f"No log thread found for user {user.name}.")
            return

        text = await self.get_user_messages(thread)
        if not text:
            await ctx.send(f"No messages found for user {user.name}.")
            return

        wordcloud = await self.generate_wordcloud(user, text)

        await ctx.send(f"Behold, the lexical universe of {user.name}!",
                       file=wordcloud)

    async def get_user_messages(self, thread):
        messages = []
        async for message in thread.history(limit=None):
            if message.author == self.bot.user and message.embeds:
                embed = message.embeds[0]
                if embed.title == "Message Sent":
                    content = embed.fields[0].value.split("**Content:** ")[-1]
                    messages.append(content)
        return " ".join(messages)

    async def generate_wordcloud(self, user, text):
        avatar_url = str(user.display_avatar.url)
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url) as resp:
                avatar_data = await resp.read()
    
        avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
        mask = Image.new("RGB", avatar.size, (255,255,255))
        mask.paste(avatar, (0,0), avatar)
        mask = np.array(mask)

        wordcloud = WordCloud(width=800, height=800, background_color='white', mask=mask).generate(text)
    
        plt.figure(figsize=(10,10), facecolor=None)
        plt.imshow(wordcloud)
        plt.axis("off")
        plt.tight_layout(pad=0)
    
        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png')
        img_buf.seek(0)
    
        return discord.File(fp=img_buf, filename='lexicon_o_matic.png')

    @track.command(name="theme")
    async def track_theme(self, ctx, user: discord.User, color: discord.Color):
        """Set a custom color theme for a tracked user's embeds."""
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
        
        async with self.config.guild(ctx.guild).user_themes() as user_themes:
            user_themes[str(user.id)] = color.value
        
        await ctx.send(f"Color theme for {user.name} set to {color}")


    @track.command(name="sentimentgraph")
    async def track_sentimentgraph(self, ctx, user: discord.User):
        """
        Generate an interactive sentiment graph for a user's recent messages.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return
    
        thread = await self.get_user_thread(ctx.guild, user)
        if not thread:
            await ctx.send(f"No log thread found for user {user.name}.")
            return
    
        sentiment_graph = await self.generate_sentiment_graph(thread)

        await ctx.send(f"Behold, the emotional journey of {user.name}!",
                       file=sentiment_graph)

    async def generate_sentiment_graph(self, thread):
        messages = []
        sentiments = []
        async for message in thread.history(limit=100):
            if message.author == self.bot.user and message.embeds:
                embed = message.embeds[0]
                if embed.title == "Message Sent":
                    content = embed.fields[0].value.split("**Content:** ")[-1]
                    analysis = await self.analyze_text(content)
                    messages.append(content[:50] + "...")
                    sentiments.append(analysis['sentiment'])
    
        fig = go.Figure(data=go.Scatter(
            x=list(range(len(messages))),
            y=sentiments,
            mode='lines+markers',
            text=messages,
            hoverinfo='text+y'
        ))
    
        fig.update_layout(
            title="Sentiment Over Time",
            xaxis_title="Message Number",
            yaxis_title="Sentiment Score"
        )
    
        img_bytes = fig.to_image(format="png")
        return discord.File(io.BytesIO(img_bytes), filename='sentiment_graph.png')

    @track.command(name="animatedheatmap")
    async def track_animatedheatmap(self, ctx, user: discord.User):
        """
        Generate an animated GIF heatmap of user activity over the past week.
        """
        if not await self.is_authorized(ctx):
            await ctx.send("You are not authorized to use UserTracker commands.")
            return

        thread = await self.get_user_thread(ctx.guild, user)
        if not thread:
            await ctx.send(f"No log thread found for user {user.name}.")
            return

        animated_heatmap = await self.generate_animated_heatmap(thread)

        await ctx.send(f"Behold, the temporal tapestry of {user.name}'s existence!",
                       file=animated_heatmap)

    async def generate_animated_heatmap(self, thread):
        activity_data = [await self.get_user_activity_data(thread) for _ in range(7)]
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        def update(frame):
            ax.clear()
            data = activity_data[frame]
            sns.heatmap(np.array(data).reshape(1, -1), ax=ax, cmap='viridis', cbar=False)
            ax.set_xticks(np.arange(0.5, 24.5))
            ax.set_xticklabels([f"{h:02d}:00" for h in range(24)])
            ax.set_yticks([])
            ax.set_title(f"Activity Heatmap - Day {frame + 1}")
        
        anim = animation.FuncAnimation(fig, update, frames=7, interval=1000)
        
        with io.BytesIO() as image_binary:
            anim.save(image_binary, writer='pillow', format='gif')
            image_binary.seek(0)
            return discord.File(fp=image_binary, filename='activity_heatmap.gif')
