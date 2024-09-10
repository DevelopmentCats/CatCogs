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

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def usertracker(self, ctx):
        """Commands for the User Tracker cog"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @usertracker.command()
    async def add(self, ctx, user: discord.Member):
        """Add a user to track"""
        async with self.lock:
            async with self.config.guild(ctx.guild).tracked_users() as tracked_users:
                if user.id not in tracked_users:
                    tracked_users.append(user.id)
                    await ctx.send(f"{user.name} has been added to the tracking list.")
                else:
                    await ctx.send(f"{user.name} is already being tracked.")

    @usertracker.command()
    async def remove(self, ctx, user: discord.Member):
        """Remove a user from tracking"""
        async with self.lock:
            async with self.config.guild(ctx.guild).tracked_users() as tracked_users:
                if user.id in tracked_users:
                    tracked_users.remove(user.id)
                    await ctx.send(f"{user.name} has been removed from the tracking list.")
                else:
                    await ctx.send(f"{user.name} is not being tracked.")

    @usertracker.command()
    async def list(self, ctx):
        """List all tracked users"""
        tracked_users = await self.config.guild(ctx.guild).tracked_users()
        if tracked_users:
            user_list = []
            for user_id in tracked_users:
                user = ctx.guild.get_member(user_id)
                if user:
                    user_list.append(f"{user.name} (ID: {user.id})")
                else:
                    user_list.append(f"Unknown User (ID: {user_id})")
            await ctx.send("Currently tracked users:\n" + "\n".join(user_list))
        else:
            await ctx.send("No users are currently being tracked.")

    @usertracker.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel for logging tracked user activities"""
        if not channel.permissions_for(ctx.guild.me).send_messages:
            await ctx.send(f"I don't have permission to send messages in {channel.mention}. Please choose a different channel or adjust my permissions.")
            return
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Log channel set to {channel.mention}")

    async def log_activity(self, guild, user, activity_type, details):
        try:
            log_channel_id = await self.config.guild(guild).log_channel()
            if not log_channel_id:
                return

            log_channel = guild.get_channel(log_channel_id)
            if not log_channel:
                return

            embed = discord.Embed(
                title=f"{activity_type} - {user.name}",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Details", value=details[:1024], inline=False)
            await log_channel.send(embed=embed)
        except discord.errors.HTTPException as e:
            print(f"Error sending log message: {e}")
        except Exception as e:
            print(f"Unexpected error in log_activity: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.author.bot:
            return

        try:
            tracked_users = await self.config.guild(message.guild).tracked_users()
            if message.author.id in tracked_users:
                content = message.content if message.content else "[No text content]"
                await self.log_activity(
                    message.guild,
                    message.author,
                    "Message Sent",
                    f"Channel: {message.channel.mention}\nContent: {content[:900]}{'...' if len(content) > 900 else ''}"
                )
        except Exception as e:
            print(f"Error in on_message: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        try:
            tracked_users = await self.config.guild(member.guild).tracked_users()
            if member.id not in tracked_users:
                return

            if before.channel != after.channel:
                if after.channel:
                    action = f"Joined voice channel {after.channel.name}"
                elif before.channel:
                    action = f"Left voice channel {before.channel.name}"
                else:
                    return

                await self.log_activity(member.guild, member, "Voice Activity", action)
        except Exception as e:
            print(f"Error in on_voice_state_update: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            tracked_users = await self.config.guild(after.guild).tracked_users()
            if after.id not in tracked_users:
                return

            if before.status != after.status:
                await self.log_activity(after.guild, after, "Status Change", f"New status: {after.status}")

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
                    await self.log_activity(after.guild, after, "Activity Change", details)
        except Exception as e:
            print(f"Error in on_member_update: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        try:
            log_channel_id = await self.config.guild(channel.guild).log_channel()
            if channel.id == log_channel_id:
                await self.config.guild(channel.guild).log_channel.set(None)
                print(f"Log channel {channel.name} was deleted in guild {channel.guild.name}. Log channel setting has been cleared.")
        except Exception as e:
            print(f"Error in on_guild_channel_delete: {e}")

    def cog_unload(self):
        # Cleanup code here if needed
        pass
