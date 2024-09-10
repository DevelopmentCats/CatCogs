from redbot.core import commands, Config
import discord
from datetime import datetime
import asyncio

class UserTracker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "tracked_users": [],
            "log_channel": None
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
                    print(f"Log channel for guild {guild.name} was not found. Setting cleared.")

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
            await ctx.send(f"✅ Log channel for this server set to {channel.mention}")

    async def log_activity(self, user, activity_type, details):
        for guild in self.bot.guilds:
            try:
                tracked_users = await self.config.guild(guild).tracked_users()
                if user.id in tracked_users:
                    log_channel_id = await self.config.guild(guild).log_channel()
                    if log_channel_id:
                        log_channel = guild.get_channel(log_channel_id)
                        if log_channel:
                            embed = discord.Embed(
                                title=f"{activity_type} - {user.name} (ID: {user.id})",
                                color=discord.Color.blue(),
                                timestamp=datetime.utcnow()
                            )
                            embed.add_field(name="Details", value=details[:1024], inline=False)
                            await log_channel.send(embed=embed)
            except Exception as e:
                print(f"Error logging activity for user {user.id} in guild {guild.id}: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        try:
            content = message.content if message.content else "[No text content]"
            await self.log_activity(
                message.author,
                "Message Sent",
                f"Server: {message.guild.name}\nChannel: {message.channel.mention}\nContent: {content[:900]}{'...' if len(content) > 900 else ''}"
            )
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

                await self.log_activity(member, "Voice Activity", f"Server: {member.guild.name}\n{action}")
            except Exception as e:
                print(f"Error in on_voice_state_update for user {member.id}: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            if before.status != after.status:
                await self.log_activity(after, "Status Change", f"Server: {after.guild.name}\nNew status: {after.status}")

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
                    await self.log_activity(after, "Activity Change", f"Server: {after.guild.name}\n{details}")
        except Exception as e:
            print(f"Error in on_member_update for user {after.id}: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        try:
            log_channel_id = await self.config.guild(channel.guild).log_channel()
            if channel.id == log_channel_id:
                await self.config.guild(channel.guild).log_channel.set(None)
                print(f"Log channel {channel.name} was deleted in guild {channel.guild.name}. Log channel setting has been cleared.")
        except Exception as e:
            print(f"Error in on_guild_channel_delete for guild {channel.guild.id}: {e}")
