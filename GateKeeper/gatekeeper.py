from typing import Optional, List
import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from datetime import datetime, timedelta
import asyncio
import logging

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

    @commands.group(name="gatekeeper", aliases=["gk"])
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
        conf = self.config.guild(ctx.guild)
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
    async def set_vouches_required(self, ctx: commands.Context, amount: int):
        """Set the number of vouches required for verification"""
        if amount < 1:
            return await ctx.send("The number of required vouches must be at least 1! 😾")

        await self.config.guild(ctx.guild).vouchers_required.set(amount)
        await ctx.send(f"✅ Members now need {amount} vouches to be verified!")

    @_gatekeeper.command(name="setwelcome")
    async def set_welcome_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for welcome messages"""
        await self.config.guild(ctx.guild).welcome_channel_id.set(channel.id)
        await ctx.send(f"✅ Welcome channel set to {channel.mention}!")

    @_gatekeeper.command(name="setlog")
    async def set_log_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for logging GateKeeper actions"""
        await self.config.guild(ctx.guild).log_channel_id.set(channel.id)
        await ctx.send(f"✅ Log channel set to {channel.mention}!")

    @_gatekeeper.command(name="setverificationchannel")
    async def set_verification_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for verification"""
        await self.config.guild(ctx.guild).verification_channel_id.set(channel.id)
        await ctx.send(f"✅ Verification channel set to {channel.mention}!")

    @_gatekeeper.command(name="timeout")
    async def set_verification_timeout(self, ctx: commands.Context, hours: int):
        """Set how long verification requests remain active"""
        if hours < 1:
            return await ctx.send("Timeout must be at least 1 hour! 😾")

        await self.config.guild(ctx.guild).verification_timeout_hours.set(hours)
        await ctx.send(f"✅ Verification requests will now expire after {hours} hours!")

    @_gatekeeper.command(name="autoremove")
    async def set_auto_remove(self, ctx: commands.Context, days: int):
        """Set how many days before unverified members are removed"""
        if days < 0:
            return await ctx.send("Days must be 0 or positive! (0 disables auto-remove) 😾")

        await self.config.guild(ctx.guild).auto_remove_unverified_days.set(days)
        if days == 0:
            await ctx.send("✅ Auto-remove has been disabled!")
        else:
            await ctx.send(f"✅ Unverified members will be removed after {days} days!")

    @_gatekeeper.command(name="blacklist")
    async def blacklist_user(self, ctx: commands.Context, user: discord.User):
        """Prevent a user from being verified"""
        async with self.config.guild(ctx.guild).blacklisted_users() as blacklist:
            if user.id in blacklist:
                return await ctx.send("That user is already blacklisted! 😾")
            blacklist.append(user.id)

        await ctx.send(f"✅ {user.mention} has been blacklisted from verification!")
        await self._log_action(ctx.guild, f"{user} ({user.id}) was blacklisted by {ctx.author}")

    @_gatekeeper.command(name="unblacklist")
    async def unblacklist_user(self, ctx: commands.Context, user: discord.User):
        """Remove a user from the blacklist"""
        async with self.config.guild(ctx.guild).blacklisted_users() as blacklist:
            if user.id not in blacklist:
                return await ctx.send("That user is not blacklisted! 😾")
            blacklist.remove(user.id)

        await ctx.send(f"✅ {user.mention} has been removed from the blacklist!")
        await self._log_action(ctx.guild, f"{user} ({user.id}) was unblacklisted by {ctx.author}")

    @_gatekeeper.command(name="stats")
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

    @_gatekeeper.command(name="massverify")
    @checks.admin_or_permissions(administrator=True)
    async def mass_verify(self, ctx: commands.Context, *members: discord.Member):
        """⚡ Verify multiple members at once
        
        This is an admin-only command that will instantly verify multiple members.
        """
        if not ctx.guild or not members:
            return await ctx.send("Please specify at least one member to verify! 😾")

        conf = self.config.guild(ctx.guild)
        if not await conf.enabled():
            return await ctx.send("GateKeeper is not enabled on this server! 😿")

        success = []
        failed = []

        for member in members:
            try:
                # Skip bots and blacklisted users
                if member.bot or member.id in await conf.blacklisted_users():
                    failed.append(f"{member} (Bot or Blacklisted)")
                    continue

                # Skip already verified members
                verified_role_id = await conf.verified_role_id()
                if verified_role_id:
                    verified_role = ctx.guild.get_role(verified_role_id)
                    if verified_role in member.roles:
                        failed.append(f"{member} (Already Verified)")
                        continue

                # Verify the member
                await self._verify_member(ctx.guild, member, [ctx.author.id])
                success.append(member.name)

            except Exception as e:
                failed.append(f"{member} (Error: {str(e)})")

        # Create response embed
        embed = discord.Embed(
            title="⚡ Mass Verification Results",
            color=discord.Color.gold() if success else discord.Color.red()
        )

        if success:
            embed.add_field(
                name="✅ Successfully Verified",
                value="\n".join(success) or "None",
                inline=False
            )

        if failed:
            embed.add_field(
                name="❌ Failed to Verify",
                value="\n".join(failed) or "None",
                inline=False
            )

        embed.set_footer(text=f"Processed by {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command()
    @commands.guild_only()
    async def vouch(self, ctx: commands.Context, member: discord.Member):
        """Vouch for a member to give them access to the server"""
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
            if voucher_role not in ctx.author.roles:
                return await ctx.send("You don't have permission to vouch for others! 🙀")

        # Check if member is already verified
        verified_role_id = await conf.verified_role_id()
        if verified_role_id:
            verified_role = ctx.guild.get_role(verified_role_id)
            if verified_role in member.roles:
                return await ctx.send("This member is already verified! 😸")

        async with conf.pending_verifications() as pending:
            if str(member.id) not in pending:
                pending[str(member.id)] = []
                
            if ctx.author.id in pending[str(member.id)]:
                return await ctx.send("You've already vouched for this member! 😸")
                
            pending[str(member.id)].append(ctx.author.id)
            vouches_needed = await conf.vouchers_required()
            current_vouches = len(pending[str(member.id)])

        # Create fancy progress bar
        progress = int((current_vouches / vouches_needed) * 10)
        progress_bar = "█" * progress + "░" * (10 - progress)

        embed = discord.Embed(
            title="✨ Vouch Recorded!",
            description=f"{ctx.author.mention} has vouched for {member.mention}!\n\n"
                      f"Progress: [{progress_bar}] {current_vouches}/{vouches_needed}",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

        # Log the vouch
        await self._log_action(
            ctx.guild,
            f"{ctx.author} ({ctx.author.id}) vouched for {member} ({member.id})"
        )

        # Check if member has enough vouches
        if current_vouches >= vouches_needed:
            await self._verify_member(ctx.guild, member, pending[str(member.id)])

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def supervouch(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """🌟 Immediately verify a member, bypassing the normal vouch requirements
        
        This is an admin-only command that will instantly verify a member.
        You can optionally provide a reason that will be logged.
        """
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
        if verified_role_id:
            verified_role = ctx.guild.get_role(verified_role_id)
            if verified_role in member.roles:
                return await ctx.send("This member is already verified! 😸")

        # Store in verification history with special flag
        async with conf.verification_history() as history:
            history[str(member.id)] = {
                "verified_at": datetime.utcnow().isoformat(),
                "vouched_by": [ctx.author.id],
                "supervouch": True,
                "reason": reason
            }

        # Remove from pending verifications if exists
        async with conf.pending_verifications() as pending:
            if str(member.id) in pending:
                del pending[str(member.id)]

        # Add verified role and remove unverified role
        verified_role_id = await conf.verified_role_id()
        unverified_role_id = await conf.unverified_role_id()
        
        if verified_role_id and unverified_role_id:
            verified_role = ctx.guild.get_role(verified_role_id)
            unverified_role = ctx.guild.get_role(unverified_role_id)
            
            if verified_role and unverified_role:
                try:
                    await member.add_roles(verified_role, reason=f"GateKeeper: Supervouch by {ctx.author}")
                    await member.remove_roles(unverified_role, reason=f"GateKeeper: Supervouch by {ctx.author}")

                    # Create a fancy embed for the response
                    embed = discord.Embed(
                        title="⭐ Super Vouch Successful!",
                        description=f"{member.mention} has been instantly verified by {ctx.author.mention}!",
                        color=discord.Color.gold()
                    )
                    if reason:
                        embed.add_field(name="Reason", value=reason)
                    embed.set_footer(text="With great power comes great responsibility... 🐱")
                    await ctx.send(embed=embed)

                    # Log the supervouch
                    log_message = f"{ctx.author} ({ctx.author.id}) super-vouched {member} ({member.id})"
                    if reason:
                        log_message += f"\nReason: {reason}"
                    await self._log_action(ctx.guild, log_message)

                except discord.HTTPException as e:
                    log.error(f"Error super-vouching member {member.id}: {e}")
                    await ctx.send("There was an error while trying to verify the member! 😿")

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

    @commands.command()
    @commands.guild_only()
    async def vouchinfo(self, ctx: commands.Context, member: discord.Member = None):
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
            status = "✅ Verified"
            if isinstance(member_history, dict):
                verified_at = datetime.fromisoformat(member_history.get('verified_at', ''))
                vouched_by = member_history.get('vouched_by', [])
                vouchers = []
                for voucher_id in vouched_by:
                    voucher = ctx.guild.get_member(voucher_id)
                    if voucher:
                        vouchers.append(voucher.name)

                embed.add_field(
                    name="Verification Details",
                    value=f"📅 Verified At: {verified_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
                          f"👥 Vouched By: {', '.join(vouchers) or 'Unknown'}\n"
                          f"⭐ Super Vouch: {'Yes' if member_history.get('supervouch') else 'No'}",
                    inline=False
                )

                if member_history.get('reason'):
                    embed.add_field(
                        name="Reason",
                        value=member_history['reason'],
                        inline=False
                    )
        else:
            status = "❌ Not Verified"
            # Check if pending verification
            pending = await conf.pending_verifications()
            if str(member.id) in pending:
                current_vouches = len(pending[str(member.id)])
                needed_vouches = await conf.vouchers_required()
                
                # Create progress bar
                progress = int((current_vouches / needed_vouches) * 10)
                progress_bar = "█" * progress + "░" * (10 - progress)
                
                embed.add_field(
                    name="Pending Verification",
                    value=f"Progress: [{progress_bar}] {current_vouches}/{needed_vouches} vouches",
                    inline=False
                )

                # List current vouchers
                vouchers = []
                for voucher_id in pending[str(member.id)]:
                    voucher = ctx.guild.get_member(voucher_id)
                    if voucher:
                        vouchers.append(voucher.name)
                
                if vouchers:
                    embed.add_field(
                        name="Current Vouchers",
                        value="\n".join(vouchers),
                        inline=False
                    )

        embed.description = f"**Current Status**: {status}"
        
        # Add join date
        if member.joined_at:
            embed.add_field(
                name="Server Join Date",
                value=member.joined_at.strftime("%Y-%m-%d %H:%M UTC"),
                inline=False
            )

        await ctx.send(embed=embed)

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

    @_gatekeeper.command(name="setup")
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def setup_gatekeeper(self, ctx: commands.Context):
        """🔧 Interactive setup wizard for GateKeeper"""
        if not ctx.guild:
            return await ctx.send("This command can only be used in a server! 😾")

        # Check bot permissions first
        required_permissions = discord.Permissions(
            manage_roles=True,
            manage_channels=True,
            read_messages=True,
            send_messages=True,
            manage_messages=True,
            embed_links=True,
            add_reactions=True,
            manage_threads=True
        )

        if not ctx.guild.me.guild_permissions.is_superset(required_permissions):
            missing_perms = [perm[0] for perm in required_permissions if not getattr(ctx.guild.me.guild_permissions, perm[0])]
            return await ctx.send(
                f"❌ I'm missing required permissions: {', '.join(missing_perms)}\n"
                "Please give me the necessary permissions and try again! 😿"
            )

        # Initial setup message
        setup_embed = discord.Embed(
            title="🔧 GateKeeper Setup Wizard",
            description="Let's set up GateKeeper to protect your server! I'll guide you through each step.",
            color=discord.Color.blue()
        )
        setup_msg = await ctx.send(embed=setup_embed)

        try:
            # Step 1: Create roles
            setup_embed.description = "📑 Step 1/4: Creating roles..."
            await setup_msg.edit(embed=setup_embed)
            
            unverified_role, verified_role, voucher_role = await self._setup_roles(ctx.guild)
            if not all([unverified_role, verified_role, voucher_role]):
                return await setup_msg.edit(content="❌ Failed to create necessary roles! Please check my permissions and try again.")

            # Step 2: Create verification channels
            setup_embed.description = "📑 Step 2/4: Creating channels..."
            await setup_msg.edit(embed=setup_embed)
            
            verify_channel, welcome_channel, category = await self._create_verification_channels(ctx.guild, unverified_role, verified_role)
            if not all([verify_channel, welcome_channel, category]):
                return await setup_msg.edit(content="❌ Failed to create verification channels! Please check my permissions and try again.")
            
            # Create log channel in the same category
            log_channel = await self._create_log_channel(ctx.guild, category)
            if not log_channel:
                return await setup_msg.edit(content="❌ Failed to create log channel! Please check my permissions and try again.")

            # Step 3: Update existing channel permissions
            setup_embed.description = "📑 Step 3/4: Updating channel permissions..."
            await setup_msg.edit(embed=setup_embed)
            
            ignore_channels = [verify_channel.id, welcome_channel.id, log_channel.id]
            await self._update_all_channels(ctx.guild, verified_role, unverified_role, ignore_channels)

            # Step 4: Save configuration
            setup_embed.description = "📑 Step 4/4: Saving configuration..."
            await setup_msg.edit(embed=setup_embed)
            
            conf = self.config.guild(ctx.guild)
            await conf.enabled.set(True)
            await conf.unverified_role_id.set(unverified_role.id)
            await conf.verified_role_id.set(verified_role.id)
            await conf.voucher_role_id.set(voucher_role.id)
            await conf.welcome_channel_id.set(welcome_channel.id)
            await conf.verification_channel_id.set(verify_channel.id)
            await conf.log_channel_id.set(log_channel.id)

            # Final success message
            success_embed = discord.Embed(
                title="✨ Setup Complete!",
                description=(
                    "GateKeeper is now protecting your server!\n\n"
                    f"📑 **Roles Created/Updated:**\n"
                    f"• Unverified: {unverified_role.mention}\n"
                    f"• Verified: {verified_role.mention}\n"
                    f"• Voucher: {voucher_role.mention}\n\n"
                    f"📝 **Channels Created/Updated:**\n"
                    f"• Category: {category.name}\n"
                    f"• Verification Desk: {verify_channel.mention}\n"
                    f"• Welcome Lounge: {welcome_channel.mention}\n"
                    f"• Logs: {log_channel.mention}\n\n"
                    "🔧 **Next Steps:**\n"
                    "1. Assign the Voucher role to trusted members\n"
                    "2. Use `[p]gatekeeper settings` to customize settings\n"
                    "3. Test the system with a new member!\n\n"
                    "Need help? Use `[p]help GateKeeper` for a list of commands!"
                ),
                color=discord.Color.green()
            )
            await setup_msg.edit(embed=success_embed)

            # Log the setup
            await self._log_action(
                ctx.guild,
                f"GateKeeper setup completed by {ctx.author} ({ctx.author.id})"
            )

        except discord.HTTPException as e:
            log.error(f"Error during setup: {e}")
            error_embed = discord.Embed(
                title="❌ Setup Failed",
                description=(
                    "There was an error during setup! Make sure I have these permissions:\n"
                    "• Manage Roles\n"
                    "• Manage Channels\n"
                    "• Read Messages\n"
                    "• Send Messages\n"
                    "• Manage Messages\n"
                    "• Embed Links\n"
                    "• Add Reactions\n"
                    "• Manage Threads"
                ),
                color=discord.Color.red()
            )
            await setup_msg.edit(embed=error_embed)

def setup(bot: Red):
    bot.add_cog(GateKeeper(bot))
