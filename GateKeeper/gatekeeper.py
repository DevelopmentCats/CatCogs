from typing import Optional, List
import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from datetime import datetime, timedelta
import asyncio
import logging
from discord import app_commands

log = logging.getLogger("red.gatekeeper")

class GateKeeper(commands.Cog):
    """🔒 Security system for protecting your Discord server

    GateKeeper provides an advanced verification system that requires new members 
    to be vouched for before gaining access. Use `[p]gatekeeper setup` to get started!
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=2025010201, force_registration=True
        )
        
        default_guild = {
            "enabled": False,
            "welcome_channel_id": None,
            "verified_role_id": None,
            "unverified_role_id": None,
            "vouchers_required": 2,
            "voucher_role_id": None,
            "log_channel_id": None,
            "verification_channel_id": None,
            "pending_verifications": {},  # {user_id: [voucher_ids]}
            "welcome_message": "Welcome {user_mention} to {server_name}! 🎉\nTo gain access to the server, you need to be vouched for by {vouches_needed} trusted members.",
            "auto_remove_unverified_days": 7,  # Remove unverified members after X days
            "verification_timeout_hours": 48,  # Reset verification progress after X hours
            "blacklisted_users": [],  # Users who can't be verified
            "verification_history": {},  # {user_id: {"verified_at": timestamp, "vouched_by": [user_ids]}}
            "restricted_channels": [],  # Channels that verified users still need extra permissions for
            "custom_commands_enabled": True,  # Allow custom verification commands
            "custom_commands": {},  # {command_name: response_message}
        }
        
        self.config.register_guild(**default_guild)
        
        # Start background task for cleanup
        self.cleanup_task = self.bot.loop.create_task(self.periodic_cleanup())

    def cog_unload(self):
        """Cleanup on cog unload"""
        if self.cleanup_task:
            self.cleanup_task.cancel()

    async def periodic_cleanup(self):
        """Background task to clean up unverified members and expired verification requests"""
        while True:
            try:
                await self._cleanup_unverified_members()
                await self._cleanup_expired_verifications()
                await asyncio.sleep(3600)  # Check every hour
            except Exception as e:
                log.error(f"Error in periodic cleanup: {e}", exc_info=True)
                await asyncio.sleep(300)  # Wait 5 minutes on error

    async def _cleanup_unverified_members(self):
        """Remove unverified members who have been in the server too long"""
        for guild in self.bot.guilds:
            conf = self.config.guild(guild)
            if not await conf.enabled():
                continue

            days = await conf.auto_remove_unverified_days()
            if days <= 0:
                continue

            unverified_role_id = await conf.unverified_role_id()
            if not unverified_role_id:
                continue

            unverified_role = guild.get_role(unverified_role_id)
            if not unverified_role:
                continue

            cutoff = datetime.utcnow() - timedelta(days=days)
            for member in unverified_role.members:
                if member.joined_at and member.joined_at < cutoff:
                    try:
                        await member.kick(reason=f"Unverified for {days} days")
                        await self._log_action(
                            guild,
                            f"Kicked {member} ({member.id}) - Unverified for {days} days"
                        )
                    except discord.HTTPException:
                        continue

    async def _cleanup_expired_verifications(self):
        """Clean up expired verification requests"""
        for guild in self.bot.guilds:
            conf = self.config.guild(guild)
            if not await conf.enabled():
                continue

            timeout_hours = await conf.verification_timeout_hours()
            if timeout_hours <= 0:
                continue

            async with conf.pending_verifications() as pending:
                expired = []
                for user_id, vouchers in pending.items():
                    if not vouchers:  # Skip if no vouchers
                        continue
                    
                    member = guild.get_member(int(user_id))
                    if not member:  # Member left
                        expired.append(user_id)
                        continue

                    # Check if first vouch is too old
                    first_vouch_time = await self._get_first_vouch_time(guild, int(user_id))
                    if first_vouch_time and (datetime.utcnow() - first_vouch_time).total_seconds() > timeout_hours * 3600:
                        expired.append(user_id)
                        await self._log_action(
                            guild,
                            f"Expired verification request for {member} ({user_id}) - Timed out after {timeout_hours} hours"
                        )

                for user_id in expired:
                    del pending[user_id]

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Automatically assign unverified role to new members"""
        guild = member.guild
        conf = self.config.guild(guild)
        
        if not await conf.enabled():
            return
            
        unverified_role_id = await conf.unverified_role_id()
        if not unverified_role_id:
            return
            
        unverified_role = guild.get_role(unverified_role_id)
        if not unverified_role:
            return
            
        try:
            await member.add_roles(unverified_role, reason="GateKeeper: New member auto-role")
            
            # Send welcome message if configured
            welcome_channel_id = await conf.welcome_channel_id()
            if welcome_channel_id:
                welcome_channel = guild.get_channel(welcome_channel_id)
                if welcome_channel:
                    welcome_message = await conf.welcome_message()
                    vouches_needed = await conf.vouchers_required()
                    formatted_message = welcome_message.format(
                        user_mention=member.mention,
                        server_name=guild.name,
                        vouches_needed=vouches_needed
                    )
                    await welcome_channel.send(formatted_message)
                    
            await self._log_action(
                guild,
                f"Automatically assigned unverified role to new member {member} ({member.id})"
            )
        except discord.HTTPException as e:
            log.error(f"Failed to assign unverified role to {member} in {guild}: {e}")

    @commands.hybrid_group(name="gatekeeper", aliases=["gk"])
    @commands.guild_only()
    async def _gatekeeper(self, ctx: commands.Context):
        """🔒 Security system for protecting your Discord server

        GateKeeper provides an advanced verification system that requires new members 
        to be vouched for before gaining access. Use `[p]gatekeeper setup` to get started!
        """
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @_gatekeeper.command(name="settings")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def show_settings(self, ctx: commands.Context):
        """😺 Show current GateKeeper settings"""
        if not ctx.guild:
            return
            
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        settings = {
            "Enabled": await conf.enabled(),
            "Welcome Channel": ctx.guild.get_channel(await conf.welcome_channel_id()),
            "Verification Channel": ctx.guild.get_channel(await conf.verification_channel_id()),
            "Log Channel": ctx.guild.get_channel(await conf.log_channel_id()),
            "Verified Role": ctx.guild.get_role(await conf.verified_role_id()),
            "Unverified Role": ctx.guild.get_role(await conf.unverified_role_id()),
            "Voucher Role": ctx.guild.get_role(await conf.voucher_role_id()),
            "Vouches Required": await conf.vouchers_required(),
            "Welcome Message": await conf.welcome_message(),
            "Auto-Remove Days": await conf.auto_remove_unverified_days(),
            "Verification Timeout (hours)": await conf.verification_timeout_hours()
        }

        embed = discord.Embed(
            title="🔧 GateKeeper Settings",
            color=discord.Color.blue()
        )

        for key, value in settings.items():
            if isinstance(value, (discord.TextChannel, discord.Role)):
                value = value.mention if value else "Not Set ❌"
            elif isinstance(value, bool):
                value = "Enabled ✅" if value else "Disabled ❌"
            embed.add_field(name=key, value=str(value), inline=False)

        await ctx.send(embed=embed)

    @_gatekeeper.command(name="setwelcomemsg")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def set_welcome_message(self, ctx: commands.Context, *, message: str):
        """😺 Set the welcome message for new members
        
        Available placeholders:
        {user_mention} - Mentions the new member
        {server_name} - Server name
        {vouches_needed} - Number of vouches required
        """
        await self.config.guild(ctx.guild).welcome_message.set(message)
        embed = discord.Embed(
            title="✨ Welcome Message Updated",
            description=f"New message:\n{message}",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @_gatekeeper.command(name="setvouch")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(
        amount="Number of vouches required for verification (1-10)"
    )
    async def set_vouches_required(self, ctx: commands.Context, amount: app_commands.Range[int, 1, 10]):
        """Set the number of vouches required for verification"""
        if not ctx.guild:
            return
            
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        await conf.vouchers_required.set(amount)
        await ctx.send(f"✅ Members now need {amount} vouches to be verified!")
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) set required vouches to {amount}"
        )

    @_gatekeeper.command(name="setwelcome")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(
        channel="The channel for welcome messages"
    )
    async def set_welcome_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for welcome messages"""
        if not ctx.guild:
            return
            
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        await conf.welcome_channel_id.set(channel.id)
        await ctx.send(f"✅ Welcome channel set to {channel.mention}!")
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) set welcome channel to {channel.name} ({channel.id})"
        )

    @_gatekeeper.command(name="setlog")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(
        channel="The channel for logging GateKeeper actions"
    )
    async def set_log_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for logging GateKeeper actions"""
        if not ctx.guild:
            return
            
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        await conf.log_channel_id.set(channel.id)
        await ctx.send(f"✅ Log channel set to {channel.mention}!")
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) set log channel to {channel.name} ({channel.id})"
        )

    @_gatekeeper.command(name="setverify")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(
        channel="The channel for verification"
    )
    async def set_verification_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for verification"""
        if not ctx.guild:
            return
            
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        await conf.verification_channel_id.set(channel.id)
        await ctx.send(f"✅ Verification channel set to {channel.mention}!")
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) set verification channel to {channel.name} ({channel.id})"
        )

    @_gatekeeper.command(name="timeout")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(
        hours="Hours before verification requests expire (1-168)"
    )
    async def set_verification_timeout(self, ctx: commands.Context, hours: app_commands.Range[int, 1, 168]):
        """Set how long verification requests remain active"""
        if not ctx.guild:
            return
            
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        await conf.verification_timeout_hours.set(hours)
        await ctx.send(f"✅ Verification requests will now expire after {hours} hours!")
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) set verification timeout to {hours} hours"
        )

    @_gatekeeper.command(name="autoremove")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    @app_commands.describe(
        days="Days before unverified members are removed (0 to disable)"
    )
    async def set_auto_remove(self, ctx: commands.Context, days: app_commands.Range[int, 0, 30]):
        """Set how many days before unverified members are removed"""
        if not ctx.guild:
            return
            
        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        await conf.auto_remove_unverified_days.set(days)
        if days == 0:
            await ctx.send("✅ Auto-remove has been disabled!")
        else:
            await ctx.send(f"✅ Unverified members will be removed after {days} days!")
        
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) set auto-remove days to {days}"
        )

    @commands.hybrid_command(name="blacklist")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        user="The user to blacklist from verification"
    )
    async def blacklist_user(self, ctx: commands.Context, user: discord.User):
        """🚫 Prevent a user from being verified"""
        if not ctx.guild:
            return

        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        # Check if member is blacklisted
        blacklist = await conf.blacklisted_users()
        if user.id in blacklist:
            return await ctx.send("This user is already blacklisted! 😾")

        # Add to blacklist
        async with conf.blacklisted_users() as blacklist:
            blacklist.append(user.id)

        # If they're verified, remove their verified role
        if isinstance(user, discord.Member):
            verified_role_id = await conf.verified_role_id()
            if verified_role_id:
                verified_role = ctx.guild.get_role(verified_role_id)
                if verified_role and verified_role in user.roles:
                    try:
                        await user.remove_roles(verified_role, reason="User blacklisted")
                    except discord.HTTPException:
                        await ctx.send(f"⚠️ Failed to remove verified role from {user.mention}")

        # Remove from pending verifications if present
        async with conf.pending_verifications() as pending:
            if str(user.id) in pending:
                del pending[str(user.id)]

        await ctx.send(f"🚫 {user.mention} has been blacklisted from verification")
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) blacklisted {user} ({user.id})"
        )

    @commands.hybrid_command(name="unblacklist")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        user="The user to remove from the blacklist"
    )
    async def unblacklist_user(self, ctx: commands.Context, user: discord.User):
        """✅ Remove a user from the blacklist"""
        if not ctx.guild:
            return

        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        # Check if member is blacklisted
        blacklist = await conf.blacklisted_users()
        if user.id not in blacklist:
            return await ctx.send("This user is not blacklisted! 😺")

        # Remove from blacklist
        async with conf.blacklisted_users() as blacklist:
            blacklist.remove(user.id)

        await ctx.send(f"✅ {user.mention} has been removed from the blacklist")
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) unblacklisted {user} ({user.id})"
        )

    @commands.hybrid_command(name="stats")
    @commands.guild_only()
    async def show_stats(self, ctx: commands.Context):
        """📊 Show verification statistics for the server"""
        if not ctx.guild:
            return

        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        # Gather statistics
        verification_history = await conf.verification_history()
        pending_verifications = await conf.pending_verifications()
        unverified_role_id = await conf.unverified_role_id()
        unverified_role = ctx.guild.get_role(unverified_role_id) if unverified_role_id else None

        total_verified = len(verification_history)
        total_pending = len(pending_verifications)
        total_unverified = len(unverified_role.members) if unverified_role else 0
        
        # Count supervouches
        supervouches = sum(1 for data in verification_history.values() 
                         if isinstance(data, dict) and data.get('supervouch', False))

        # Calculate average time to verification (excluding supervouches)
        verification_times = []
        for data in verification_history.values():
            if isinstance(data, dict) and not data.get('supervouch', False):
                try:
                    verified_at = datetime.fromisoformat(data['verified_at'])
                    # Assuming join_time is when they started getting vouches
                    member = ctx.guild.get_member(int(data.get('user_id', 0)))
                    if member and member.joined_at:
                        time_to_verify = (verified_at - member.joined_at).total_seconds() / 3600  # hours
                        verification_times.append(time_to_verify)
                except (KeyError, ValueError):
                    continue

        avg_time = sum(verification_times) / len(verification_times) if verification_times else 0

        embed = discord.Embed(
            title="📊 GateKeeper Statistics",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )

        # General Stats
        embed.add_field(
            name="Current Status",
            value=f"🔓 Verified Members: {total_verified}\n"
                  f"⏳ Pending Verification: {total_pending}\n"
                  f"🔒 Unverified Members: {total_unverified}\n"
                  f"⭐ Super Vouches: {supervouches}",
            inline=False
        )

        # Time Stats
        embed.add_field(
            name="Timing",
            value=f"⏱️ Average Time to Verify: {avg_time:.1f} hours\n"
                  f"🕐 Timeout Period: {await conf.verification_timeout_hours()} hours\n"
                  f"📅 Auto-remove After: {await conf.auto_remove_unverified_days()} days",
            inline=False
        )

        # Requirements
        embed.add_field(
            name="Requirements",
            value=f"✨ Vouches Needed: {await conf.vouchers_required()}\n"
                  f"👥 Blacklisted Users: {len(await conf.blacklisted_users())}",
            inline=False
        )

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="vouch")
    @commands.guild_only()
    @app_commands.describe(
        member="The member you want to vouch for"
    )
    async def vouch(self, ctx: commands.Context, member: discord.Member):
        """🤝 Vouch for a member to give them access to the server"""
        if not ctx.guild:
            return

        # Various checks
        if member == ctx.author:
            return await ctx.send("You can't vouch for yourself! 😾")

        if member.bot:
            return await ctx.send("You can't vouch for bots! 🤖")

        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        # Check if member is blacklisted
        blacklist = await conf.blacklisted_users()
        if member.id in blacklist:
            return await ctx.send("This user is blacklisted and cannot be verified! 😾")

        # Check if voucher has permission
        voucher_role_id = await conf.voucher_role_id()
        if voucher_role_id:
            voucher_role = ctx.guild.get_role(voucher_role_id)
            if not voucher_role or voucher_role not in ctx.author.roles:
                return await ctx.send("You don't have permission to vouch for members! 😿")

        # Check if member is already verified
        verified_role_id = await conf.verified_role_id()
        if not verified_role_id:
            return await ctx.send("Verified role not configured! Please contact an admin. 😿")

        verified_role = ctx.guild.get_role(verified_role_id)
        if not verified_role:
            return await ctx.send("Verified role not found! Please contact an admin. 😿")

        if verified_role in member.roles:
            return await ctx.send(f"{member.mention} is already verified! 😺")

        # Get pending verifications
        pending = await conf.pending_verifications()
        if str(member.id) not in pending:
            pending[str(member.id)] = []

        # Check if this person already vouched
        if ctx.author.id in pending[str(member.id)]:
            return await ctx.send("You've already vouched for this member! 😺")

        # Add vouch and check if enough vouches
        pending[str(member.id)].append(ctx.author.id)
        await conf.pending_verifications.set(pending)

        vouches_required = await conf.vouchers_required()
        current_vouches = len(pending[str(member.id)])

        if current_vouches >= vouches_required:
            # Member has enough vouches, verify them
            await self._verify_member(ctx.guild, member, pending[str(member.id)])
            del pending[str(member.id)]
            await conf.pending_verifications.set(pending)
            await ctx.send(f"🎉 {member.mention} has been verified! Welcome!")
        else:
            await ctx.send(
                f"✅ Vouch recorded for {member.mention}! "
                f"They need {vouches_required - current_vouches} more "
                f"vouch{'es' if vouches_required - current_vouches != 1 else ''} "
                f"to be verified."
            )

    @commands.hybrid_command(name="vouchinfo")
    @commands.guild_only()
    @app_commands.describe(
        member="The member to check verification status for (defaults to yourself)"
    )
    async def vouchinfo(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """🔍 Check verification status and history of a member"""
        if not ctx.guild:
            return

        member = member or ctx.author
        conf = self.config.guild(ctx.guild)

        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        embed = discord.Embed(
            title=f"🔍 Verification Info for {member}",
            color=discord.Color.blue()
        )

        # Check current status
        verified_role_id = await conf.verified_role_id()
        verified_role = ctx.guild.get_role(verified_role_id) if verified_role_id else None
        is_verified = verified_role in member.roles if verified_role else False

        # Get verification history
        history = await conf.verification_history()
        member_history = history.get(str(member.id), {})

        if is_verified:
            embed.add_field(
                name="Status",
                value="✅ Verified",
                inline=False
            )
            if isinstance(member_history, dict):
                verified_at = member_history.get("verified_at")
                if verified_at:
                    embed.add_field(
                        name="Verified On",
                        value=f"<t:{verified_at}:F>",
                        inline=True
                    )
                vouched_by = member_history.get("vouched_by", [])
                if vouched_by:
                    vouchers = []
                    for voucher_id in vouched_by:
                        voucher = ctx.guild.get_member(voucher_id)
                        if voucher:
                            vouchers.append(voucher.mention)
                    if vouchers:
                        embed.add_field(
                            name="Vouched By",
                            value="\n".join(vouchers),
                            inline=True
                        )
        else:
            embed.add_field(
                name="Status",
                value="❌ Not Verified",
                inline=False
            )
            # Check pending vouches
            pending = await conf.pending_verifications()
            if str(member.id) in pending:
                current_vouches = len(pending[str(member.id)])
                vouches_required = await conf.vouchers_required()
                vouchers = []
                for voucher_id in pending[str(member.id)]:
                    voucher = ctx.guild.get_member(voucher_id)
                    if voucher:
                        vouchers.append(voucher.mention)
                embed.add_field(
                    name="Current Vouches",
                    value=f"{current_vouches}/{vouches_required}\n" + "\n".join(vouchers),
                    inline=False
                )

        # Check if blacklisted
        blacklist = await conf.blacklisted_users()
        if member.id in blacklist:
            embed.add_field(
                name="⚠️ Notice",
                value="This user is blacklisted and cannot be verified",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="supervouch")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        member="The member to instantly verify",
        reason="Optional reason for the verification"
    )
    async def supervouch(self, ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = None):
        """🌟 Immediately verify a member, bypassing the normal vouch requirements"""
        if not ctx.guild:
            return

        if member.bot:
            return await ctx.send("You can't verify bots! 🤖")

        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        # Check if member is blacklisted
        blacklist = await conf.blacklisted_users()
        if member.id in blacklist:
            return await ctx.send("This user is blacklisted! Remove them from the blacklist first! 😾")

        # Check if already verified
        verified_role_id = await conf.verified_role_id()
        if not verified_role_id:
            return await ctx.send("Verified role not configured! Please contact an admin. 😿")

        verified_role = ctx.guild.get_role(verified_role_id)
        if not verified_role:
            return await ctx.send("Verified role not found! Please contact an admin. 😿")

        if verified_role in member.roles:
            return await ctx.send(f"{member.mention} is already verified! 😺")

        # Remove from pending verifications if present
        async with conf.pending_verifications() as pending:
            if str(member.id) in pending:
                del pending[str(member.id)]

        # Add to verification history
        async with conf.verification_history() as history:
            history[str(member.id)] = {
                "verified_at": int(datetime.utcnow().timestamp()),
                "vouched_by": [ctx.author.id],
                "supervouch": True,
                "reason": reason
            }

        # Add verified role and remove unverified role
        try:
            await member.add_roles(verified_role, reason=f"Supervouch by {ctx.author}")
            
            unverified_role_id = await conf.unverified_role_id()
            if unverified_role_id:
                unverified_role = ctx.guild.get_role(unverified_role_id)
                if unverified_role and unverified_role in member.roles:
                    await member.remove_roles(unverified_role)

            await ctx.send(f"🌟 {member.mention} has been instantly verified by {ctx.author.mention}!")
            await self._log_action(
                ctx.guild,
                f"{ctx.author} ({ctx.author.id}) super-vouched for {member} ({member.id})"
                + (f" with reason: {reason}" if reason else "")
            )
        except discord.HTTPException as e:
            await ctx.send(f"Failed to verify member: {e}")

    @commands.hybrid_command(name="massverify")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        members="The members to verify (mention multiple members)"
    )
    async def mass_verify(self, ctx: commands.Context, *members: discord.Member):
        """⚡ Verify multiple members at once (Admin only)"""
        if not ctx.guild or not members:
            return await ctx.send("Please mention at least one member to verify!")

        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        verified_role_id = await conf.verified_role_id()
        if not verified_role_id:
            return await ctx.send("Verified role not configured! Please contact an admin. 😿")

        verified_role = ctx.guild.get_role(verified_role_id)
        if not verified_role:
            return await ctx.send("Verified role not found! Please contact an admin. 😿")

        success = []
        failed = []

        for member in members:
            if member.bot:
                failed.append(f"{member} (Bot)")
                continue

            if member.id in (await conf.blacklisted_users()):
                failed.append(f"{member} (Blacklisted)")
                continue

            if verified_role in member.roles:
                failed.append(f"{member} (Already verified)")
                continue

            try:
                # Remove from pending verifications if present
                async with conf.pending_verifications() as pending:
                    if str(member.id) in pending:
                        del pending[str(member.id)]

                # Add to verification history
                async with conf.verification_history() as history:
                    history[str(member.id)] = {
                        "verified_at": int(datetime.utcnow().timestamp()),
                        "vouched_by": [ctx.author.id],
                        "supervouch": True,
                        "reason": "Mass verification"
                    }

                await member.add_roles(verified_role, reason=f"Mass verification by {ctx.author}")
                
                unverified_role_id = await conf.unverified_role_id()
                if unverified_role_id:
                    unverified_role = ctx.guild.get_role(unverified_role_id)
                    if unverified_role and unverified_role in member.roles:
                        await member.remove_roles(unverified_role)

                success.append(member.mention)
            except Exception as e:
                failed.append(f"{member} (Error: {str(e)})")

        # Create response embed
        embed = discord.Embed(
            title="⚡ Mass Verification Results",
            color=discord.Color.blue() if success else discord.Color.red()
        )

        if success:
            embed.add_field(
                name="✅ Successfully Verified",
                value="\n".join(success) if len(success) <= 10 else 
                      f"{len(success)} members verified successfully",
                inline=False
            )

        if failed:
            embed.add_field(
                name="❌ Failed to Verify",
                value="\n".join(failed),
                inline=False
            )

        await ctx.send(embed=embed)
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) mass-verified {len(success)} members"
        )

    async def _verify_member(self, guild: discord.Guild, member: discord.Member, voucher_ids: List[int]):
        """Handle member verification"""
        conf = self.config.guild(guild)
        
        verified_role_id = await conf.verified_role_id()
        unverified_role_id = await conf.unverified_role_id()
        
        if verified_role_id and unverified_role_id:
            verified_role = guild.get_role(verified_role_id)
            unverified_role = guild.get_role(unverified_role_id)
            
            if verified_role and unverified_role:
                try:
                    await member.add_roles(verified_role, reason="GateKeeper: Member verified")
                    await member.remove_roles(unverified_role, reason="GateKeeper: Member verified")
                    
                    # Store verification history
                    async with conf.verification_history() as history:
                        history[str(member.id)] = {
                            "verified_at": datetime.utcnow().isoformat(),
                            "vouched_by": voucher_ids
                        }
                    
                    # Remove from pending verifications
                    async with conf.pending_verifications() as pending:
                        if str(member.id) in pending:
                            del pending[str(member.id)]
                    
                    # Send success message
                    welcome_channel_id = await conf.welcome_channel_id()
                    if welcome_channel_id:
                        channel = guild.get_channel(welcome_channel_id)
                        if channel:
                            embed = discord.Embed(
                                title="🎉 New Member Verified!",
                                description=f"{member.mention} has been verified and now has full access to the server!",
                                color=discord.Color.gold()
                            )
                            await channel.send(embed=embed)
                    
                    # Log verification
                    await self._log_action(
                        guild,
                        f"{member} ({member.id}) was verified with {len(voucher_ids)} vouches"
                    )
                
                except discord.HTTPException as e:
                    log.error(f"Error verifying member {member.id}: {e}")

    async def _log_action(self, guild: discord.Guild, message: str):
        """Log an action to the designated log channel"""
        conf = self.config.guild(guild)
        log_channel_id = await conf.log_channel_id()
        if not log_channel_id:
            return

        channel = guild.get_channel(log_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            description=f"🔒 {message}",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="GateKeeper Log")
        
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _get_first_vouch_time(self, guild: discord.Guild, user_id: int) -> Optional[datetime]:
        """Get the timestamp of the first vouch for a user"""
        conf = self.config.guild(guild)
        async with conf.verification_history() as history:
            if str(user_id) in history:
                try:
                    return datetime.fromisoformat(history[str(user_id)]["verified_at"])
                except (KeyError, ValueError):
                    return None
        return None

    async def _create_verification_channels(self, guild: discord.Guild, unverified_role: discord.Role, verified_role: discord.Role) -> tuple[Optional[discord.TextChannel], Optional[discord.TextChannel], Optional[discord.CategoryChannel]]:
        """Create and set up the verification channels"""
        try:
            # First try to find existing channels
            category = discord.utils.get(guild.categories, name="Welcome Center")
            verify_channel = discord.utils.get(guild.text_channels, name="verification-desk")
            welcome_channel = discord.utils.get(guild.text_channels, name="welcome-lounge")

            # Set up base overwrites for category
            category_overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    read_message_history=True
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                    manage_channels=True,
                    add_reactions=True,
                    embed_links=True,
                    attach_files=True,
                    manage_threads=True
                )
            }

            # Create or update category
            if not category:
                category = await guild.create_category(
                    "Welcome Center",
                    overwrites=category_overwrites,
                    reason="GateKeeper: Created welcome center category"
                )
            else:
                await category.edit(overwrites=category_overwrites)

            # Set up verification desk overwrites - no one can chat except bot
            verify_overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    read_message_history=True
                ),
                unverified_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    read_message_history=True
                ),
                verified_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=False,
                    read_message_history=True
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                    manage_channels=True,
                    add_reactions=True,
                    embed_links=True,
                    attach_files=True,
                    manage_threads=True
                )
            }

            # Create or update verification desk
            if not verify_channel:
                verify_channel = await guild.create_text_channel(
                    "verification-desk",
                    category=category,
                    overwrites=verify_overwrites,
                    reason="GateKeeper: Created verification instructions channel",
                    topic="Get verified to access the server! Read the instructions and wait for trusted members to vouch for you. 🔒"
                )
            else:
                await verify_channel.edit(
                    category=category,
                    overwrites=verify_overwrites,
                    topic="Get verified to access the server! Read the instructions and wait for trusted members to vouch for you. 🔒"
                )
                # Clear channel and resend welcome message
                await verify_channel.purge(limit=None)

            rules_embed = discord.Embed(
                title="🔒 Welcome to the Verification Desk!",
                description=(
                    "Welcome to the server! To gain access, you need to be vouched for by trusted members.\n\n"
                    "**How Verification Works:**\n"
                    "1. Head over to the 👋 `welcome-lounge` channel\n"
                    "2. Introduce yourself and chat with our community\n"
                    "3. Wait for trusted members to vouch for you\n"
                    "4. Once you have enough vouches, you'll automatically get access!\n\n"
                    "**Rules:**\n"
                    "• Be patient and respectful\n"
                    "• Don't spam or ping members for vouches\n"
                    "• One account per person\n"
                    "• Follow server rules\n\n"
                    f"Required Vouches: {guild.name} requires multiple trusted members to vouch for you.\n"
                    "Use `[p]vouchinfo` to check your progress! 😺"
                ),
                color=discord.Color.blue()
            )
            rules_embed.set_footer(text="GateKeeper - Keeping your server safe! 😺")
            await verify_channel.send(embed=rules_embed)

            # Set up welcome lounge overwrites - everyone can chat
            welcome_overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    read_message_history=True,
                    add_reactions=True,
                    embed_links=True,
                    attach_files=True,
                    create_instant_invite=False,
                    mention_everyone=False
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                    manage_channels=True,
                    add_reactions=True,
                    embed_links=True,
                    attach_files=True,
                    manage_threads=True
                )
            }

            # Create or update welcome lounge
            if not welcome_channel:
                welcome_channel = await guild.create_text_channel(
                    "welcome-lounge",
                    category=category,
                    overwrites=welcome_overwrites,
                    reason="GateKeeper: Created welcome lounge channel",
                    topic="Welcome! Introduce yourself and chat while waiting for verification. Be patient and friendly! 😊"
                )
            else:
                await welcome_channel.edit(
                    category=category,
                    overwrites=welcome_overwrites,
                    topic="Welcome! Introduce yourself and chat while waiting for verification. Be patient and friendly! 😊"
                )
                # Clear channel and resend welcome message
                await welcome_channel.purge(limit=None)

            welcome_embed = discord.Embed(
                title="👋 Welcome to the Lounge!",
                description=(
                    "This is a space for new members to chat while waiting for verification!\n\n"
                    "**What to do here:**\n"
                    "• Introduce yourself to the community\n"
                    "• Chat with other members\n"
                    "• Ask questions about the server\n"
                    "• Be patient while waiting for verification\n\n"
                    "Remember to be friendly and follow the server rules! 😺"
                ),
                color=discord.Color.green()
            )
            await welcome_channel.send(embed=welcome_embed)

            return verify_channel, welcome_channel, category
        except discord.HTTPException as e:
            log.error(f"Error creating verification channels: {e}")
            return None, None, None

    async def _create_log_channel(self, guild: discord.Guild, category: discord.CategoryChannel) -> Optional[discord.TextChannel]:
        """Create the log channel"""
        try:
            log_channel = discord.utils.get(guild.text_channels, name="gatekeeper-logs")
            if not log_channel:
                log_channel = await guild.create_text_channel(
                    "gatekeeper-logs",
                    category=category,
                    reason="GateKeeper: Created log channel"
                )
                await log_channel.set_permissions(
                    guild.default_role,
                    read_messages=False,
                    send_messages=False,
                    read_message_history=False
                )
            return log_channel
        except discord.HTTPException as e:
            log.error(f"Error creating log channel: {e}")
            return None

    async def _setup_roles(self, guild: discord.Guild) -> tuple[Optional[discord.Role], Optional[discord.Role], Optional[discord.Role]]:
        """Create and set up all necessary roles"""
        try:
            # Find or create unverified role
            unverified_role = discord.utils.get(guild.roles, name="Unverified")
            if not unverified_role:
                unverified_role = await guild.create_role(
                    name="Unverified",
                    color=discord.Color.dark_grey(),
                    reason="GateKeeper: Created unverified role",
                    permissions=discord.Permissions(
                        read_messages=True,
                        send_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                        embed_links=True,
                        attach_files=True,
                        create_instant_invite=False,
                        change_nickname=True
                    )
                )

            # Find or create verified role
            verified_role = discord.utils.get(guild.roles, name="Verified")
            if not verified_role:
                verified_role = await guild.create_role(
                    name="Verified",
                    color=discord.Color.green(),
                    reason="GateKeeper: Created verified role",
                    permissions=discord.Permissions(
                        read_messages=True,
                        send_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                        attach_files=True,
                        embed_links=True,
                        external_emojis=True,
                        change_nickname=True,
                        create_instant_invite=True,
                        connect=True,
                        speak=True
                    )
                )

            # Find or create voucher role
            voucher_role = discord.utils.get(guild.roles, name="Voucher")
            if not voucher_role:
                voucher_role = await guild.create_role(
                    name="Voucher",
                    color=discord.Color.blue(),
                    reason="GateKeeper: Created voucher role",
                    permissions=discord.Permissions(
                        read_messages=True,
                        send_messages=True,
                        read_message_history=True,
                        add_reactions=True,
                        change_nickname=True
                    )
                )

            # Ensure role hierarchy
            positions = {
                verified_role: guild.me.top_role.position - 3,
                voucher_role: guild.me.top_role.position - 2,
                unverified_role: guild.me.top_role.position - 1
            }
            await guild.edit_role_positions(positions=positions)

            return unverified_role, verified_role, voucher_role
        except discord.HTTPException as e:
            log.error(f"Error creating roles: {e}")
            return None, None, None

    async def _update_all_channels(self, guild: discord.Guild, verified_role: discord.Role, unverified_role: discord.Role, ignore_channels: list[int]):
        """Update permissions for all channels"""
        try:
            for channel in guild.channels:
                if channel.id not in ignore_channels:
                    try:
                        # Get existing overwrites
                        overwrites = channel.overwrites

                        # Set comprehensive permissions for verified users
                        verified_permissions = discord.PermissionOverwrite(
                            # Basic channel access
                            read_messages=True,
                            send_messages=True,
                            read_message_history=True,
                            
                            # Message management
                            add_reactions=True,
                            embed_links=True,
                            attach_files=True,
                            use_external_emojis=True,
                            use_external_stickers=True,
                            
                            # Voice permissions (if voice channel)
                            connect=True if isinstance(channel, discord.VoiceChannel) else None,
                            speak=True if isinstance(channel, discord.VoiceChannel) else None,
                            stream=True if isinstance(channel, discord.VoiceChannel) else None,
                            use_voice_activation=True if isinstance(channel, discord.VoiceChannel) else None,
                            
                            # General permissions
                            request_to_speak=True,
                            use_application_commands=True,
                            change_nickname=True
                        )

                        # Set restrictive permissions for unverified users
                        unverified_permissions = discord.PermissionOverwrite(
                            read_messages=False,
                            send_messages=False,
                            read_message_history=False,
                            add_reactions=False,
                            connect=False,
                            speak=False
                        )

                        # Update the overwrites
                        overwrites[verified_role] = verified_permissions
                        overwrites[unverified_role] = unverified_permissions

                        await channel.edit(
                            overwrites=overwrites,
                            reason="GateKeeper: Updated channel permissions for verified/unverified roles"
                        )
                        
                        log.info(f"Updated permissions for channel: {channel.name}")
                        
                    except discord.HTTPException as e:
                        log.error(f"Error updating permissions for channel {channel.name}: {e}")
                        continue
                    except Exception as e:
                        log.error(f"Unexpected error updating channel {channel.name}: {e}")
                        continue
                else:
                    log.info(f"Skipping permission update for managed channel: {channel.name}")
            
            log.info("Finished updating all channel permissions")
            
        except Exception as e:
            log.error(f"Error updating channel permissions: {e}")

    @commands.hybrid_command(name="setup")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def setup_gatekeeper(self, ctx: commands.Context):
        """🔧 Interactive setup wizard for GateKeeper"""
        if not ctx.guild:
            return

        conf = self.config.guild(ctx.guild)

        # Create embed for initial setup message
        embed = discord.Embed(
            title="🔧 GateKeeper Setup Wizard",
            description=(
                "Welcome to the GateKeeper setup wizard! I'll help you configure the verification system.\n\n"
                "**What will be set up:**\n"
                "• Verified and Unverified roles\n"
                "• Welcome and verification channels\n"
                "• Log channel for tracking actions\n"
                "• Basic settings and permissions\n\n"
                "**Do you want to proceed?** (yes/no)"
            ),
            color=discord.Color.blue()
        )
        setup_msg = await ctx.send(embed=embed)

        try:
            msg = await ctx.bot.wait_for(
                "message",
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ["yes", "no", "y", "n"],
                timeout=30.0
            )
        except asyncio.TimeoutError:
            await setup_msg.edit(content="Setup wizard timed out! Run the command again to restart.", embed=None)
            return

        if not msg.content.lower().startswith("y"):
            await setup_msg.edit(content="Setup cancelled!", embed=None)
            return

        # Step 1: Create roles
        status_msg = await ctx.send("📋 Creating roles...")
        verified_role, unverified_role = await self._setup_roles(ctx.guild)
        if not verified_role or not unverified_role:
            await status_msg.edit(content="❌ Failed to create roles! Please check my permissions and try again.")
            return

        await conf.verified_role_id.set(verified_role.id)
        await conf.unverified_role_id.set(unverified_role.id)

        # Step 2: Create channels
        await status_msg.edit(content="📋 Creating channels...")
        verify_channel, welcome_channel, category = await self._create_verification_channels(
            ctx.guild, unverified_role, verified_role
        )
        
        if not verify_channel or not welcome_channel:
            await status_msg.edit(content="❌ Failed to create channels! Please check my permissions and try again.")
            return

        await conf.verification_channel_id.set(verify_channel.id)
        await conf.welcome_channel_id.set(welcome_channel.id)

        # Step 3: Create log channel
        await status_msg.edit(content="📋 Creating log channel...")
        log_channel = await self._create_log_channel(ctx.guild, category)
        if log_channel:
            await conf.log_channel_id.set(log_channel.id)

        # Step 4: Set up voucher role
        await status_msg.edit(content="Who should be able to vouch for new members? Reply with:\n1️⃣ Everyone\n2️⃣ Specific role")
        try:
            msg = await ctx.bot.wait_for(
                "message",
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel and m.content in ["1", "2"],
                timeout=30.0
            )
        except asyncio.TimeoutError:
            await status_msg.edit(content="No response received, defaulting to everyone can vouch.")
        else:
            if msg.content == "2":
                try:
                    voucher_role = await ctx.guild.create_role(
                        name="Trusted Voucher",
                        color=discord.Color.green(),
                        reason="GateKeeper: Created voucher role"
                    )
                    await conf.voucher_role_id.set(voucher_role.id)
                    await ctx.send(f"✅ Created {voucher_role.mention} role! Assign this to members who can vouch for others.")
                except discord.HTTPException:
                    await ctx.send("❌ Failed to create voucher role! Please create it manually.")

        # Step 5: Configure basic settings
        await conf.enabled.set(True)
        await conf.vouchers_required.set(2)
        await conf.verification_timeout_hours.set(24)
        await conf.auto_remove_unverified_days.set(7)

        # Final setup message
        embed = discord.Embed(
            title="✅ GateKeeper Setup Complete!",
            description=(
                "The verification system is now set up and running! Here's what was configured:\n\n"
                f"• Created roles: {verified_role.mention} and {unverified_role.mention}\n"
                f"• Created channels: {verify_channel.mention} and {welcome_channel.mention}\n"
                f"• Created log channel: {log_channel.mention if log_channel else '❌ Failed'}\n"
                "• Enabled basic settings\n\n"
                "**Next Steps:**\n"
                "1. Use `/gatekeeper settings` to view current configuration\n"
                "2. Use `/gatekeeper setvouch` to change required vouches (default: 2)\n"
                "3. Use `/gatekeeper setwelcomemsg` to customize the welcome message\n"
                "4. Use `/gatekeeper autoremove` to change auto-remove days (default: 7)\n\n"
                "Need help? Use `/help GateKeeper` to see all available commands!"
            ),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) completed the setup wizard"
        )

def setup(bot: Red):
    bot.add_cog(GateKeeper(bot))
