from redbot.core import commands, Config
import discord
from datetime import datetime, timedelta
import asyncio

class UserTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "tracked_users": [],
            "log_channel": None,
            "user_threads": {},
            "main_message_id": None
        }
        self.config.register_guild(**default_guild)
        self.lock = asyncio.Lock()
        self.task = bot.loop.create_task(self.initialize())

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

    @commands.group(invoke_without_command=True)
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def track(self, ctx):
        """User tracking commands"""
        await ctx.send_help(ctx.command)

    @track.command(name="add")
    async def track_add(self, ctx, user: discord.User):
        """Add a user to track in this server"""
        async with self.lock:
            async with self.config.guild(ctx.guild).tracked_users() as tracked_users:
                if user.id not in tracked_users:
                    tracked_users.append(user.id)
                    await self.create_user_thread(ctx.guild, user)
                    await self.update_main_message(ctx.guild)
                    await ctx.send(f"✅ User {user.name} (ID: {user.id}) has been added to the tracking list for this server.")
                else:
                    await ctx.send(f"ℹ️ User {user.name} (ID: {user.id}) is already being tracked in this server.")

    @track.command(name="remove")
    async def track_remove(self, ctx, user: discord.User):
        """Remove a user from tracking in this server"""
        async with self.lock:
            async with self.config.guild(ctx.guild).tracked_users() as tracked_users:
                if user.id in tracked_users:
                    tracked_users.remove(user.id)
                    await self.remove_user_thread(ctx.guild, user)
                    await self.update_main_message(ctx.guild)
                    await ctx.send(f"✅ User {user.name} (ID: {user.id}) has been removed from the tracking list for this server.")
                else:
                    await ctx.send(f"ℹ️ User {user.name} (ID: {user.id}) is not being tracked in this server.")

    @track.command(name="list")
    async def track_list(self, ctx):
        """List all tracked users in this server"""
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
        """Set or view the channel for logging tracked user activities in this server"""
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
        for user_id in tracked_users:
            user = self.bot.get_user(user_id)
            if user:
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

    async def create_main_message(self, guild, channel):
        embed = await self.get_thread_list_embed(guild)
        message = await channel.send(embed=embed)
        await self.config.guild(guild).main_message_id.set(message.id)

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
        embed = discord.Embed(title="User Log Threads", color=discord.Color.blue())
        embed.description = "Click on the links below to view individual user logs:"

        user_threads = await self.config.guild(guild).user_threads()
        for user_id, thread_id in user_threads.items():
            user = self.bot.get_user(int(user_id))
            thread = guild.get_thread(thread_id)
            if user and thread:
                last_message = await self.get_last_message(thread)
                last_activity = last_message.content if last_message else "No activity logged yet"
                embed.add_field(
                    name=f"{user.name} (ID: {user.id})",
                    value=f"[View Logs]({thread.jump_url})\nLast activity: {last_activity[:100]}{'...' if len(last_activity) > 100 else ''}",
                    inline=False
                )

        if not user_threads:
            embed.add_field(name="No tracked users", value="Use the `track add` command to start tracking users.")

        embed.set_footer(text="Last updated")
        embed.timestamp = datetime.utcnow()
        return embed

    async def get_last_message(self, thread):
        messages = await thread.history(limit=1).flatten()
        return messages[0] if messages else None

    async def create_user_thread(self, guild, user):
        log_channel_id = await self.config.guild(guild).log_channel()
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return

        thread_name = f"Logs for {user.name} ({user.id})"
        thread = await log_channel.create_thread(name=thread_name, auto_archive_duration=10080)
        async with self.config.guild(guild).user_threads() as user_threads:
            user_threads[str(user.id)] = thread.id
        await self.update_main_message(guild)

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
        embed = discord.Embed(
            title=f"{activity_type}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=f"{user.name} (ID: {user.id})", icon_url=user.display_avatar.url)
        embed.add_field(name="Details", value=details, inline=False)
        return embed

    async def log_activity(self, user, activity_type, details):
        for guild in self.bot.guilds:
            try:
                tracked_users = await self.config.guild(guild).tracked_users()
                if user.id in tracked_users:
                    thread = await self.get_user_thread(guild, user)
                    if thread:
                        embed = self.create_embed(user, activity_type, details)
                        await thread.send(embed=embed)
                        await self.update_main_message(guild)
            except Exception as e:
                print(f"Error logging activity for user {user.id} in guild {guild.id}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        try:
            content = message.content if message.content else "[No text content]"
            details = (f"**Server:** {message.guild.name}\n"
                       f"**Channel:** {message.channel.mention}\n"
                       f"**Content:** {content[:1900]}{'...' if len(content) > 1900 else ''}")
            await self.log_activity(message.author, "Message Sent", details)
        except Exception as e:
            print(f"Error in on_message for user {message.author.id}: {e}")

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
                print(f"Error in on_voice_state_update for user {member.id}: {e}")

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
                    details = f"**Server:** {after.guild.name}\n**Activity:** {details}"
                    await self.log_activity(after, "Activity Change", details)
        except Exception as e:
            print(f"Error in on_member_update for user {after.id}: {e}")

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
            print(f"Error in on_guild_channel_delete for guild {channel.guild.id}: {e}")
