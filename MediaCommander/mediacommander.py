"""
🎬 MediaCommander - Your ULTIMATE Media Management Companion!
Created by DevelopmentCats with EXTREME FELINE PRECISION 🐱

A comprehensive Red-DiscordBot cog that integrates with the full Arr stack:
Plex, Sonarr, Radarr, Lidarr, Tautulli, Overseerr, and more!
"""

import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu, start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate
from typing import Optional, Dict, Any, List
import logging
import asyncio
from datetime import datetime, timedelta

from .utils import (
    PlexClient, SonarrClient, RadarrClient, LidarrClient, 
    TautulliClient, OverseerrClient, MediaEmbedHelper, PermissionHelper
)

log = logging.getLogger("red.mediacommander")

class MediaCommander(commands.Cog):
    """🎬 The ULTIMATE Media Management Companion for Discord!"""
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=260120231748)
        
        # Default configuration structure
        default_global = {
            "services": {
                "plex": {
                    "enabled": False,
                    "url": "",
                    "token": "",
                    "admin_roles": [],
                    "user_roles": []
                },
                "sonarr": {
                    "enabled": False,
                    "url": "",
                    "api_key": "",
                    "admin_roles": [],
                    "user_roles": []
                },
                "radarr": {
                    "enabled": False,
                    "url": "",
                    "api_key": "",
                    "admin_roles": [],
                    "user_roles": []
                },
                "lidarr": {
                    "enabled": False,
                    "url": "",
                    "api_key": "",
                    "admin_roles": [],
                    "user_roles": []
                },
                "tautulli": {
                    "enabled": False,
                    "url": "",
                    "api_key": "",
                    "admin_roles": [],
                    "user_roles": []
                },
                "overseerr": {
                    "enabled": False,
                    "url": "",
                    "api_key": "",
                    "admin_roles": [],
                    "user_roles": []
                }
            }
        }
        
        self.config.register_global(**default_global)
        
        # Initialize API clients as None
        self.clients = {
            'plex': None,
            'sonarr': None,
            'radarr': None,
            'lidarr': None,
            'tautulli': None,
            'overseerr': None
        }

    async def _get_client(self, service: str):
        """Get or create API client for a service"""
        if self.clients[service] is None:
            config_data = await self.config.services()
            service_config = config_data.get(service, {})
            
            if not service_config.get('enabled', False):
                return None
                
            url = service_config.get('url', '')
            api_key = service_config.get('api_key', '')
            token = service_config.get('token', '')
            
            if not url:
                return None
            
            try:
                if service == 'plex' and token:
                    self.clients[service] = PlexClient(url, token)
                elif service in ['sonarr', 'radarr', 'lidarr', 'tautulli', 'overseerr'] and api_key:
                    if service == 'sonarr':
                        self.clients[service] = SonarrClient(url, api_key)
                    elif service == 'radarr':
                        self.clients[service] = RadarrClient(url, api_key)
                    elif service == 'lidarr':
                        self.clients[service] = LidarrClient(url, api_key)
                    elif service == 'tautulli':
                        self.clients[service] = TautulliClient(url, api_key)
                    elif service == 'overseerr':
                        self.clients[service] = OverseerrClient(url, api_key)
            except Exception as e:
                log.error(f"Failed to create {service} client: {e}")
                return None
                
        return self.clients[service]

    async def _check_service_permission(self, ctx: commands.Context, service: str, admin_required: bool = False) -> bool:
        """Check if user has permission to use a service"""
        config_data = await self.config.services()
        
        # Check if service is enabled
        service_config = config_data.get(service, {})
        if not service_config.get('enabled', False):
            await ctx.send(f"❌ {service.title()} is not enabled on this server.")
            return False
        
        # Owner can always access
        if await self.bot.is_owner(ctx.author):
            return True
        
        # Check admin permissions if required
        if admin_required:
            admin_roles = service_config.get('admin_roles', [])
            if not PermissionHelper.has_media_admin_role(ctx.author, admin_roles):
                await ctx.send(f"❌ You need admin permissions to use {service.title()} management commands.")
                return False
        else:
            # Check user permissions
            if not PermissionHelper.can_use_service(ctx.author, service, config_data):
                await ctx.send(f"❌ You don't have permission to use {service.title()}.")
                return False
        
        return True

    # Main command group
    @commands.group(name="mediacommander", aliases=["mc"])
    @commands.guild_only()
    async def mediacommander(self, ctx: commands.Context):
        """🎬 MediaCommander - Your Ultimate Media Management Companion"""
        pass

    # Configuration commands
    @mediacommander.group(name="config")
    @commands.is_owner()
    async def config_group(self, ctx: commands.Context):
        """⚙️ Configuration commands for MediaCommander"""
        pass

    @config_group.command(name="setup")
    async def setup_service(self, ctx: commands.Context, service: str, url: str, key: str):
        """Setup a service configuration
        
        Usage:
        `[p]mc config setup plex https://plex.example.com YOUR_PLEX_TOKEN`
        `[p]mc config setup sonarr https://sonarr.example.com YOUR_API_KEY`
        """
        valid_services = ['plex', 'sonarr', 'radarr', 'lidarr', 'tautulli', 'overseerr']
        
        if service not in valid_services:
            await ctx.send(f"❌ Invalid service. Valid services: {', '.join(valid_services)}")
            return
        
        try:
            async with self.config.services() as services:
                services[service]['url'] = url
                if service == 'plex':
                    services[service]['token'] = key
                else:
                    services[service]['api_key'] = key
                services[service]['enabled'] = True
            
            # Clear the client to force recreation
            self.clients[service] = None
            
            await ctx.send(f"✅ {service.title()} configured successfully!")
            
            # Delete the message for security
            try:
                await ctx.message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
                
        except Exception as e:
            log.error(f"Error setting up {service}: {e}")
            await ctx.send(f"❌ Failed to setup {service}: {str(e)}")

    @config_group.command(name="roles")
    async def set_roles(self, ctx: commands.Context, service: str, role_type: str, *roles: discord.Role):
        """Set roles for a service
        
        Usage:
        `[p]mc config roles plex admin @PlexAdmin @ServerMod`
        `[p]mc config roles sonarr user @PlexUser @Member`
        """
        valid_services = ['plex', 'sonarr', 'radarr', 'lidarr', 'tautulli', 'overseerr']
        valid_types = ['admin', 'user']
        
        if service not in valid_services:
            await ctx.send(f"❌ Invalid service. Valid services: {', '.join(valid_services)}")
            return
            
        if role_type not in valid_types:
            await ctx.send(f"❌ Invalid role type. Valid types: {', '.join(valid_types)}")
            return
        
        try:
            role_ids = [role.id for role in roles]
            async with self.config.services() as services:
                services[service][f'{role_type}_roles'] = role_ids
            
            role_mentions = [role.mention for role in roles]
            await ctx.send(f"✅ Set {service.title()} {role_type} roles to: {', '.join(role_mentions)}")
            
        except Exception as e:
            log.error(f"Error setting roles for {service}: {e}")
            await ctx.send(f"❌ Failed to set roles: {str(e)}")

    @config_group.command(name="status")
    async def config_status(self, ctx: commands.Context):
        """Show current configuration status"""
        config_data = await self.config.services()
        
        embed = discord.Embed(
            title="🎬 MediaCommander Configuration Status",
            color=0x5865F2
        )
        
        for service, config in config_data.items():
            status = "✅ Enabled" if config.get('enabled', False) else "❌ Disabled"
            url = config.get('url', 'Not set')
            has_key = "✅ Set" if (config.get('api_key') or config.get('token')) else "❌ Missing"
            
            admin_roles = len(config.get('admin_roles', []))
            user_roles = len(config.get('user_roles', []))
            
            field_value = f"**Status:** {status}\n"
            field_value += f"**URL:** {url}\n"
            field_value += f"**API Key:** {has_key}\n"
            field_value += f"**Admin Roles:** {admin_roles}\n"
            field_value += f"**User Roles:** {user_roles}"
            
            embed.add_field(
                name=f"🔧 {service.title()}",
                value=field_value,
                inline=True
            )
        
        await ctx.send(embed=embed)

    # User info command
    @mediacommander.command(name="permissions", aliases=["perms"])
    async def check_permissions(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Check your or another user's MediaCommander permissions"""
        target = member or ctx.author
        config_data = await self.config.services()
        permissions = PermissionHelper.get_user_permissions(target, config_data)
        
        embed = PermissionHelper.format_permissions_embed(target, permissions)
        await ctx.send(embed=embed)

    @mediacommander.command(name="dashboard", aliases=["overview", "status"])
    async def dashboard(self, ctx: commands.Context):
        """📊 Show MediaCommander dashboard with all services status"""
        config_data = await self.config.services()
        
        embed = discord.Embed(
            title="🎬 MediaCommander Dashboard",
            description="Your complete media management overview",
            color=0x5865F2
        )
        
        # Add service status fields
        enabled_services = []
        disabled_services = []
        
        for service, config in config_data.items():
            service_emoji = {
                'plex': '🎭',
                'sonarr': '📺', 
                'radarr': '🎬',
                'lidarr': '🎵',
                'tautulli': '📊',
                'overseerr': '🎫'
            }.get(service, '🔧')
            
            if config.get('enabled', False):
                enabled_services.append(f"{service_emoji} {service.title()}")
            else:
                disabled_services.append(f"{service_emoji} {service.title()}")
        
        if enabled_services:
            embed.add_field(
                name="✅ Enabled Services",
                value='\n'.join(enabled_services),
                inline=True
            )
        
        if disabled_services:
            embed.add_field(
                name="❌ Disabled Services", 
                value='\n'.join(disabled_services),
                inline=True
            )
        
        # Add user permissions
        permissions = PermissionHelper.get_user_permissions(ctx.author, config_data)
        user_access = []
        admin_access = []
        
        for service, level in permissions.items():
            service_emoji = {
                'plex': '🎭',
                'sonarr': '📺',
                'radarr': '🎬', 
                'lidarr': '🎵',
                'tautulli': '📊',
                'overseerr': '🎫'
            }.get(service, '🔧')
            
            if level == 'admin':
                admin_access.append(f"{service_emoji} {service.title()}")
            elif level == 'user':
                user_access.append(f"{service_emoji} {service.title()}")
        
        if admin_access:
            embed.add_field(
                name="🛡️ Your Admin Access",
                value='\n'.join(admin_access),
                inline=False
            )
        
        if user_access:
            embed.add_field(
                name="👤 Your User Access",
                value='\n'.join(user_access),
                inline=False
            )
        
        # Add quick help
        embed.add_field(
            name="🚀 Quick Commands",
            value="`[p]mc plex activity` - Current streams\n"
                  "`[p]mc sonarr search <show>` - Find TV shows\n"
                  "`[p]mc radarr search <movie>` - Find movies\n"
                  "`[p]mc overseerr request movie <title>` - Request media\n"
                  "`[p]help MediaCommander` - Full command list",
            inline=False
        )
        
        embed.set_footer(text="🐱 Made with extreme feline precision by DevelopmentCats")
        
        await ctx.send(embed=embed)

    @mediacommander.command(name="help", aliases=["commands"])
    async def media_help(self, ctx: commands.Context):
        """📖 Show detailed MediaCommander help and command list"""
        embed = discord.Embed(
            title="🎬 MediaCommander - Command Reference",
            description="Your Ultimate Media Management Companion",
            color=0x5865F2
        )
        
        # Configuration commands
        embed.add_field(
            name="⚙️ Configuration (Owner Only)",
            value="`[p]mc config setup <service> <url> <key>` - Setup service\n"
                  "`[p]mc config roles <service> <type> <roles>` - Set roles\n"
                  "`[p]mc config status` - Show configuration",
            inline=False
        )
        
        # Plex commands
        embed.add_field(
            name="🎭 Plex Commands",
            value="`[p]mc plex status` - Server status\n"
                  "`[p]mc plex search <query>` - Search media\n"
                  "`[p]mc plex activity` - Current streams\n"
                  "`[p]mc plex libraries` - Show libraries\n"
                  "`[p]mc plex users` - Show users (Admin)\n"
                  "`[p]mc plex invite @user` - Secure DM invite (Admin)\n"
                  "`[p]mc plex invite email <email>` - Direct invite with redaction (Admin)",
            inline=False
        )
        
        # Sonarr commands
        embed.add_field(
            name="📺 Sonarr Commands",
            value="`[p]mc sonarr search <show>` - Search TV shows\n"
                  "`[p]mc sonarr add <show>` - Add series (Admin)\n"
                  "`[p]mc sonarr queue` - Download queue\n"
                  "`[p]mc sonarr calendar` - Upcoming episodes\n"
                  "`[p]mc sonarr missing` - Search missing (Admin)",
            inline=False
        )
        
        # Radarr commands
        embed.add_field(
            name="🎬 Radarr Commands", 
            value="`[p]mc radarr search <movie>` - Search movies\n"
                  "`[p]mc radarr add <movie>` - Add movie (Admin)\n"
                  "`[p]mc radarr queue` - Download queue\n"
                  "`[p]mc radarr calendar` - Upcoming releases\n"
                  "`[p]mc radarr missing` - Search missing (Admin)",
            inline=False
        )
        
        # Lidarr commands
        embed.add_field(
            name="🎵 Lidarr Commands",
            value="`[p]mc lidarr search artist <name>` - Search artists\n"
                  "`[p]mc lidarr search album <name>` - Search albums\n"
                  "`[p]mc lidarr add <artist>` - Add artist (Admin)\n"
                  "`[p]mc lidarr artists` - Show monitored artists",
            inline=False
        )
        
        # Overseerr commands
        embed.add_field(
            name="🎫 Overseerr Commands",
            value="`[p]mc overseerr request movie <title>` - Request movie\n"
                  "`[p]mc overseerr request tv <title>` - Request TV show\n"
                  "`[p]mc overseerr pending` - Pending requests (Admin)\n"
                  "`[p]mc overseerr approve <id>` - Approve request (Admin)\n"
                  "`[p]mc overseerr decline <id>` - Decline request (Admin)",
            inline=False
        )
        
        # Tautulli commands
        embed.add_field(
            name="📊 Tautulli Commands",
            value="`[p]mc tautulli stats` - Server statistics\n"
                  "`[p]mc tautulli activity` - Current activity\n"
                  "`[p]mc tautulli users` - User stats (Admin)",
            inline=False
        )
        
        # General commands
        embed.add_field(
            name="🔧 General Commands",
            value="`[p]mc dashboard` - Service overview\n"
                  "`[p]mc permissions [@user]` - Check permissions\n"
                  "`[p]mc help` - This help message",
            inline=False
        )
        
        embed.set_footer(text="Use '[p]help <command>' for detailed help on specific commands")
        
        await ctx.send(embed=embed)

    # Plex commands
    @mediacommander.group(name="plex")
    @commands.guild_only()
    async def plex_group(self, ctx: commands.Context):
        """📺 Plex Media Server commands"""
        pass

    @plex_group.command(name="status")
    async def plex_status(self, ctx: commands.Context):
        """Check Plex server status and information"""
        if not await self._check_service_permission(ctx, 'plex'):
            return
        
        client = await self._get_client('plex')
        if not client:
            await ctx.send("❌ Plex client not configured properly.")
            return
        
        try:
            server_info = await client.get_server_info()
            
            # Extract useful information from server response
            server_name = server_info.get('friendlyName', 'Unknown Server')
            version = server_info.get('version', 'Unknown')
            platform = server_info.get('platform', 'Unknown')
            platform_version = server_info.get('platformVersion', '')
            
            # MyPlex/Remote Access status
            myplex_state = server_info.get('myPlexMappingState', 'unknown')
            myplex_signin = server_info.get('myPlexSigninState', 'unknown') 
            myplex_subscription = server_info.get('myPlexSubscription', '0') == '1'
            myplex_username = server_info.get('myPlexUsername', 'Not configured')
            
            # Server capabilities
            allow_sync = server_info.get('allowSync', '0') == '1'
            allow_sharing = server_info.get('allowSharing', '0') == '1'
            allow_camera_upload = server_info.get('allowCameraUpload', '0') == '1'
            
            # Transcoding info
            active_transcodes = server_info.get('transcoderActiveVideoSessions', '0')
            transcoder_video = server_info.get('transcoderVideo', '0') == '1'
            transcoder_audio = server_info.get('transcoderAudio', '0') == '1'
            
            # Country and update info
            country_code = server_info.get('countryCode', 'unknown').upper()
            updated_at = server_info.get('updatedAt', '')
            
            # Create status embed
            embed = discord.Embed(
                title=f"🎭 {server_name}",
                description="Plex Media Server Status",
                color=0xE5A00D
            )
            
            # Server Information
            embed.add_field(
                name="🖥️ Server Info",
                value=f"**Version:** {version}\n**Platform:** {platform} {platform_version}\n**Country:** {country_code}",
                inline=True
            )
            
            # MyPlex Status
            myplex_status = "✅ Connected" if myplex_state == "mapped" and myplex_signin == "ok" else "❌ Disconnected"
            plex_pass = "✅ Plex Pass" if myplex_subscription else "❌ No Plex Pass"
            
            # Redact the MyPlex username (email) for privacy
            if myplex_username and myplex_username != 'Not configured':
                redacted_username = self._redact_email(myplex_username)
            else:
                redacted_username = myplex_username
            
            embed.add_field(
                name="🌐 MyPlex Status", 
                value=f"**Status:** {myplex_status}\n**Account:** {redacted_username}\n**Subscription:** {plex_pass}",
                inline=True
            )
            
            # Server Capabilities
            sync_status = "✅" if allow_sync else "❌"
            sharing_status = "✅" if allow_sharing else "❌" 
            camera_status = "✅" if allow_camera_upload else "❌"
            
            embed.add_field(
                name="⚙️ Capabilities",
                value=f"**Sync:** {sync_status}\n**Sharing:** {sharing_status}\n**Camera Upload:** {camera_status}",
                inline=True
            )
            
            # Transcoding Status
            video_transcoding = "✅ Available" if transcoder_video else "❌ Unavailable"
            audio_transcoding = "✅ Available" if transcoder_audio else "❌ Unavailable"
            
            embed.add_field(
                name="🎬 Transcoding",
                value=f"**Video:** {video_transcoding}\n**Audio:** {audio_transcoding}\n**Active Sessions:** {active_transcodes}",
                inline=True
            )
            
            # Add machine identifier for debugging
            machine_id = server_info.get('machineIdentifier', 'Unknown')
            embed.add_field(
                name="🔧 Technical",
                value=f"**Machine ID:** `{machine_id[:16]}...`",
                inline=True
            )
            
            # Add timestamp if available
            if updated_at:
                try:
                    from datetime import datetime
                    timestamp = datetime.fromtimestamp(int(updated_at))
                    embed.add_field(
                        name="⏰ Last Update",
                        value=timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        inline=True
                    )
                except:
                    pass
            
            embed.set_footer(text="🐱 MediaCommander • Server status retrieved successfully")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Plex status error: {e}")
            await ctx.send(f"❌ Error getting Plex status: {str(e)}")

    @plex_group.command(name="search")
    async def plex_search(self, ctx: commands.Context, *, query: str):
        """Search Plex media"""
        if not await self._check_service_permission(ctx, 'plex'):
            return
        
        client = await self._get_client('plex')
        if not client:
            await ctx.send("❌ Plex client not configured properly.")
            return
        
        try:
            results = await client.search_media(query)
            if not results:
                await ctx.send(f"🔍 No results found for '{query}'")
                return
            
            embeds = []
            for item in results[:5]:  # Limit to 5 results
                media_type = item.get('type', 'unknown')
                if media_type == 'movie':
                    embed = MediaEmbedHelper.create_media_embed(item, 'plex', 'movie')
                elif media_type in ['show', 'series']:
                    embed = MediaEmbedHelper.create_media_embed(item, 'plex', 'series')
                else:
                    embed = MediaEmbedHelper.create_media_embed(item, 'plex', 'info')
                embeds.append(embed)
            
            if embeds:
                if len(embeds) == 1:
                    await ctx.send(embed=embeds[0])
                else:
                    # Use proper pagination with reaction removal
                    current_page = 0
                    
                    # Add page indicator to embed footer
                    for i, embed in enumerate(embeds):
                        embed.set_footer(text=f"Page {i+1} of {len(embeds)} • 🐱 MediaCommander")
                    
                    message = await ctx.send(embed=embeds[current_page])
                    
                    if len(embeds) > 1:
                        # Add reactions for navigation (left, close, right)
                        await start_adding_reactions(message, ["⬅️", "❌", "➡️"])
                        
                        def check(reaction, user):
                            return (
                                user == ctx.author 
                                and reaction.message.id == message.id 
                                and str(reaction.emoji) in ["⬅️", "❌", "➡️"]
                            )
                        
                        try:
                            while True:
                                reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                                
                                if str(reaction.emoji) == "➡️" and current_page < len(embeds) - 1:
                                    current_page += 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "⬅️" and current_page > 0:
                                    current_page -= 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "❌":
                                    try:
                                        await message.delete()
                                    except discord.Forbidden:
                                        await message.clear_reactions()
                                    return
                                
                                # Remove user's reaction
                                try:
                                    await message.remove_reaction(reaction.emoji, user)
                                except discord.Forbidden:
                                    pass  # Bot doesn't have manage messages permission
                                    
                        except asyncio.TimeoutError:
                            pass
                        
                        # Clean up reactions
                        try:
                            await message.clear_reactions()
                        except discord.Forbidden:
                            pass
                
        except Exception as e:
            log.error(f"Plex search error: {e}")
            await ctx.send(f"❌ Error searching Plex: {str(e)}")

    @plex_group.command(name="activity")
    async def plex_activity(self, ctx: commands.Context):
        """Show current Plex activity"""
        if not await self._check_service_permission(ctx, 'plex'):
            return
        
        client = await self._get_client('plex')
        if not client:
            await ctx.send("❌ Plex client not configured properly.")
            return
        
        try:
            sessions = await client.get_sessions()
            activity_data = {'sessions': sessions}
            embed = MediaEmbedHelper.create_media_embed(activity_data, 'plex', 'activity')
            await ctx.send(embed=embed)
        except Exception as e:
            log.error(f"Plex activity error: {e}")
            await ctx.send(f"❌ Error getting Plex activity: {str(e)}")

    @plex_group.command(name="libraries")
    async def plex_libraries(self, ctx: commands.Context):
        """Show Plex libraries with detailed information"""
        if not await self._check_service_permission(ctx, 'plex'):
            return
        
        client = await self._get_client('plex')
        if not client:
            await ctx.send("❌ Plex client not configured properly.")
            return
        
        try:
            libraries = await client.get_libraries()
            if not libraries:
                await ctx.send("📚 No libraries found!")
                return
            
            embed = discord.Embed(
                title=f"📚 Plex Libraries ({len(libraries)} total)",
                color=0xE5A00D
            )
            
            for lib in libraries[:12]:  # Limit to 12 libraries for clean display
                name = lib.get('title', 'Unknown Library')
                lib_type = lib.get('type', 'unknown')
                refreshing = lib.get('refreshing', '0') == '1'
                
                # Get last scan information
                scanned_at = lib.get('scannedAt', '')
                updated_at = lib.get('updatedAt', '')
                
                # Format library type for display
                type_display = {
                    'movie': 'Movies',
                    'show': 'TV Shows', 
                    'artist': 'Music',
                    'photo': 'Photos'
                }.get(lib_type, lib_type.title())
                
                # Choose appropriate emoji
                type_emoji = {
                    'movie': '🎬',
                    'show': '📺', 
                    'artist': '🎵',
                    'photo': '📸'
                }.get(lib_type, '📁')
                
                # Format scan status
                if refreshing:
                    scan_status = "🔄 Scanning..."
                elif scanned_at:
                    try:
                        from datetime import datetime
                        scan_time = datetime.fromtimestamp(int(scanned_at))
                        scan_status = f"✅ Last scan: {scan_time.strftime('%m/%d/%y')}"
                    except:
                        scan_status = "✅ Scanned"
                else:
                    scan_status = "❓ Not scanned"
                
                # Get folder path if available
                locations = lib.get('Location', [])
                if isinstance(locations, dict):
                    locations = [locations]
                
                folder_info = ""
                if locations:
                    folder_path = locations[0].get('path', '') if locations else ''
                    if folder_path:
                        # Show just the folder name, not full path
                        folder_name = folder_path.split('/')[-1] if '/' in folder_path else folder_path
                        folder_info = f"\n📁 {folder_name}"
                
                embed.add_field(
                    name=f"{type_emoji} {name}",
                    value=f"**Type:** {type_display}\n{scan_status}{folder_info}",
                    inline=True
                )
            
            # Add helpful footer
            embed.set_footer(text="Libraries can be refreshed from Plex Settings → Manage → Libraries")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Plex libraries error: {e}")
            await ctx.send(f"❌ Error getting Plex libraries: {str(e)}")

    @plex_group.command(name="users")
    async def plex_users(self, ctx: commands.Context):
        """Show Plex users (Admin only)"""
        if not await self._check_service_permission(ctx, 'plex', admin_required=True):
            return
        
        client = await self._get_client('plex')
        if not client:
            await ctx.send("❌ Plex client not configured properly.")
            return
        
        try:
            users = await client.get_users()
            if not users:
                await ctx.send("👥 No users found!")
                return
            
            # Create paginated embeds for users
            embeds = []
            users_per_page = 12  # 12 users per page (3 columns x 4 rows looks good)
            total_users = len(users)
            
            for page_start in range(0, total_users, users_per_page):
                page_users = users[page_start:page_start + users_per_page]
                page_num = (page_start // users_per_page) + 1
                total_pages = (total_users + users_per_page - 1) // users_per_page
                
                embed = discord.Embed(
                    title=f"👥 Plex Users ({total_users} total) - Page {page_num}/{total_pages}",
                    color=0xE5A00D
                )
                
                for user in page_users:
                    # Extract user information from plex.tv API
                    display_name = user.get('title', user.get('username', 'Unknown User'))
                    email = user.get('email', '')
                    user_id = user.get('id', 'N/A')
                    restricted = user.get('restricted', '0') == '1'
                    home = user.get('home', '0') == '1'
                    all_libraries = user.get('allLibraries', '0') == '1'
                    num_libraries = user.get('numLibraries', '0')
                    
                    # Redact email for privacy
                    if email:
                        redacted_email = self._redact_email(email)
                    else:
                        redacted_email = 'No email available'
                    
                    # Determine access level based on plex.tv data
                    if home and restricted:
                        access_level = "🏠 Home User (Restricted)"
                    elif home:
                        access_level = "🏠 Home User (Full Access)"
                    elif all_libraries:
                        access_level = "✅ Full Library Access"
                    elif num_libraries and num_libraries != '0':
                        access_level = f"🔒 Partial Access ({num_libraries} libraries)"
                    elif restricted:
                        access_level = "🔒 Restricted Access"
                    else:
                        access_level = "👤 Shared User"
                    
                    embed.add_field(
                        name=f"👤 {display_name}",
                        value=f"Email: {redacted_email}\nAccess: {access_level}",
                        inline=True
                    )
                
                embeds.append(embed)
            
            # Send paginated embeds
            if len(embeds) == 1:
                await ctx.send(embed=embeds[0])
            else:
                # Add page indicators to embed footers
                for i, embed in enumerate(embeds):
                    embed.set_footer(text=f"Page {i+1} of {len(embeds)} • 🐱 MediaCommander")
                
                # Use proper pagination with reaction removal
                current_page = 0
                message = await ctx.send(embed=embeds[current_page])
                
                # Add reactions for navigation (left, close, right)
                await start_adding_reactions(message, ["⬅️", "❌", "➡️"])
                
                def check(reaction, user):
                    return (
                        user == ctx.author 
                        and reaction.message.id == message.id 
                        and str(reaction.emoji) in ["⬅️", "❌", "➡️"]
                    )
                
                try:
                    while True:
                        reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                        
                        if str(reaction.emoji) == "➡️" and current_page < len(embeds) - 1:
                            current_page += 1
                            await message.edit(embed=embeds[current_page])
                        elif str(reaction.emoji) == "⬅️" and current_page > 0:
                            current_page -= 1
                            await message.edit(embed=embeds[current_page])
                        elif str(reaction.emoji) == "❌":
                            try:
                                await message.delete()
                            except discord.Forbidden:
                                await message.clear_reactions()
                            return
                        
                        # Remove user's reaction
                        try:
                            await message.remove_reaction(reaction.emoji, user)
                        except discord.Forbidden:
                            pass  # Bot doesn't have manage messages permission
                            
                except asyncio.TimeoutError:
                    pass
                
                # Clean up reactions
                try:
                    await message.clear_reactions()
                except discord.Forbidden:
                    pass
            
        except Exception as e:
            log.error(f"Plex users error: {e}")
            await ctx.send(f"❌ Error getting Plex users: {str(e)}")

    @plex_group.command(name="invite")
    async def plex_invite(self, ctx: commands.Context, target: str = None):
        """Invite user to Plex with interactive library selection (Admin only)
        
        Auto-detects input type:
        `[p]mc plex invite @user` - Bot DMs user for email privately
        `[p]mc plex invite user@email.com` - Direct email invitation
        """
        if not await self._check_service_permission(ctx, 'plex', admin_required=True):
            return
        
        client = await self._get_client('plex')
        if not client:
            await ctx.send("❌ Plex client not configured properly.")
            return
        
        try:
            # Get all libraries first
            libraries = await client.get_libraries()
            if not libraries:
                await ctx.send("❌ No Plex libraries found!")
                return
            
            if not target:
                # Show help if no arguments provided
                embed = discord.Embed(
                    title="🎭 Plex Invite Help",
                    description="Auto-detects input type - no keywords needed!",
                    color=0xE5A00D
                )
                
                embed.add_field(
                    name="🔒 Secure Method (Recommended)",
                    value="`[p]mc plex invite @username`\nBot privately DMs user for email",
                    inline=False
                )
                
                embed.add_field(
                    name="📧 Direct Method",
                    value="`[p]mc plex invite user@email.com`\nDirect invitation with email redaction (use in private channels)",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                return
            
            # Auto-detect input type
            import re
            
            # Check if it's an email address (contains @ and basic email pattern)
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if '@' in target and re.match(email_pattern, target):
                # Direct email invitation
                await self._direct_email_invite(ctx, client, target, libraries)
                return
            
            # Check if it's a mention (starts with <@)
            if target.startswith('<@'):
                # Extract user ID from mention
                user_id = target.strip('<@!>')
                try:
                    user = ctx.guild.get_member(int(user_id))
                    if not user:
                        await ctx.send("❌ User not found in this server!")
                        return
                    
                    await self._secure_user_invite(ctx, client, user, libraries)
                    return
                except ValueError:
                    await ctx.send("❌ Invalid user mention format!")
                    return
            
            # Try to parse as username/nickname/ID
            try:
                # Try to convert target to a member
                converter = commands.MemberConverter()
                user = await converter.convert(ctx, target)
                await self._secure_user_invite(ctx, client, user, libraries)
                return
            except commands.BadArgument:
                # If it's not a valid member and not an email, show error
                await ctx.send(f"❌ '{target}' is not a valid user mention, username, or email address!")
                return
            
        except Exception as e:
            log.error(f"Plex invite error: {e}")
            await ctx.send(f"❌ Error with invite command: {str(e)}")

    async def _secure_user_invite(self, ctx: commands.Context, client, user: discord.Member, libraries: List[Dict[str, Any]]):
        """Handle secure user invitation via DM"""
        # Create library selection embed
        library_embed = await self._create_library_selection_embed(libraries)
        
        # Send library selection to admin
        library_msg = await ctx.send(embed=library_embed)
        
        # Add reactions for library selection
        number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
        select_all_emoji = '✅'
        confirm_emoji = '✅'  # Use same emoji for clarity
        
        for i, lib in enumerate(libraries[:10]):  # Limit to 10 libraries
            await library_msg.add_reaction(number_emojis[i])
        
        await library_msg.add_reaction(select_all_emoji)
        
        # Track selected libraries
        selected_indices = set()
        
        # Enhanced selection embed
        async def update_selection_embed():
            embed = discord.Embed(
                title="📚 Library Selection",
                description="Select libraries to share with the user:",
                color=0xE5A00D
            )
            
            # Show available libraries with selection status
            library_list = []
            for i, lib in enumerate(libraries[:10]):
                name = lib.get('title', 'Unknown Library')
                lib_type = lib.get('type', 'unknown')
                count = lib.get('count', 'N/A')
                
                type_emoji = {
                    'movie': '🎬',
                    'show': '📺', 
                    'music': '🎵',
                    'photo': '📸'
                }.get(lib_type, '📁')
                
                status = "✅" if i in selected_indices else "⬜"
                library_list.append(f"{number_emojis[i]} {status} {type_emoji} **{name}** ({count} items)")
            
            embed.add_field(
                name="Available Libraries",
                value='\n'.join(library_list),
                inline=False
            )
            
            if selected_indices:
                selected_names = [libraries[i].get('title', 'Unknown') for i in selected_indices]
                embed.add_field(
                    name="Currently Selected",
                    value='\n'.join([f"🎬 {name}" for name in selected_names]),
                    inline=False
                )
            
            embed.add_field(
                name="Instructions",
                value="1️⃣-🔟 Toggle individual libraries\n✅ **Select ALL and CONFIRM**",
                inline=False
            )
            
            return embed
        
        # Wait for admin's library selection
        def check_library_reaction(reaction, reaction_user):
            return (reaction_user == ctx.author and 
                   reaction.message.id == library_msg.id and
                   str(reaction.emoji) in number_emojis[:len(libraries)] + [select_all_emoji])
        
        try:
            while True:
                reaction, _ = await self.bot.wait_for('reaction_add', check=check_library_reaction, timeout=120.0)
                
                if str(reaction.emoji) == select_all_emoji:
                    # If nothing selected, select all. If something selected, confirm.
                    if not selected_indices:
                        # Select all libraries
                        selected_indices = set(range(len(libraries)))
                        await library_msg.edit(embed=await update_selection_embed())
                    else:
                        # Confirm selection
                        selected_libraries = [libraries[i] for i in selected_indices]
                        selected_names = [libraries[i].get('title', 'Unknown') for i in selected_indices]
                        await library_msg.delete()
                        break
                    
                else:
                    # Toggle individual library
                    emoji_index = number_emojis.index(str(reaction.emoji))
                    if emoji_index in selected_indices:
                        selected_indices.remove(emoji_index)
                    else:
                        selected_indices.add(emoji_index)
                    
                    # Update the embed to show current selection
                    try:
                        await library_msg.edit(embed=await update_selection_embed())
                    except discord.NotFound:
                        # Message was deleted, break out of loop
                        return
                
                # Remove the user's reaction to allow re-selection
                try:
                    await library_msg.remove_reaction(reaction.emoji, ctx.author)
                except discord.NotFound:
                    pass
            
            # Send DM to user for email
            dm_embed = discord.Embed(
                title="📧 Plex Invitation Request",
                description=f"**{ctx.author.display_name}** wants to invite you to their Plex server!",
                color=0xE5A00D
            )
            
            dm_embed.add_field(
                name="📚 Libraries You'll Access",
                value='\n'.join([f"🎬 {name}" for name in selected_names]),
                inline=False
            )
            
            dm_embed.add_field(
                name="📧 Please Reply",
                value="Reply with your email address to receive the invitation.",
                inline=False
            )
            
            dm_embed.set_footer(text="This request will expire in 5 minutes")
            
            try:
                dm_msg = await user.send(embed=dm_embed)
                
                # Notify admin that DM was sent
                await ctx.send(f"✅ DM sent to **{user.display_name}** requesting their email address.")
                
                # Wait for user's email response
                def check_dm_response(message):
                    return (message.author == user and 
                           isinstance(message.channel, discord.DMChannel) and
                           '@' in message.content)
                
                email_msg = await self.bot.wait_for('message', check=check_dm_response, timeout=300.0)
                user_email = email_msg.content.strip()
                
                # Validate email format (basic check)
                if '@' not in user_email or '.' not in user_email.split('@')[1]:
                    await user.send("❌ Please provide a valid email address.")
                    return
                
                # Send the invitation
                library_ids = [str(lib.get('key', '')) for lib in selected_libraries]
                result = await client.invite_user(user_email, library_ids)
                
                # Handle the response from the enhanced invite_user method
                if result.get('success'):
                    # Confirm to user
                    success_embed = discord.Embed(
                        title="🎉 Plex Invitation Sent!",
                        description=f"An invitation has been sent to **{user_email}**",
                        color=0x00FF00
                    )
                    
                    # Use sections_shared from result if available, otherwise fall back to selected_names
                    shared_sections = result.get('sections_shared', selected_names)
                    success_embed.add_field(
                        name="📚 Libraries",
                        value='\n'.join([f"🎬 {name}" for name in shared_sections]),
                        inline=False
                    )
                    

                    
                    await user.send(embed=success_embed)
                    
                    # Confirm to admin (with redacted email for security)
                    redacted_email = self._redact_email(user_email)
                    admin_embed = discord.Embed(
                        title="✅ Invitation Completed",
                        description=f"Successfully invited **{user.display_name}** ({redacted_email}) to Plex",
                        color=0x00FF00
                    )
                    admin_embed.add_field(
                        name="📚 Libraries",
                        value=', '.join(shared_sections),
                        inline=False
                    )
                    admin_embed.add_field(
                        name="🔒 Secure Process",
                        value="Email was collected privately via DM and is now redacted for security",
                        inline=False
                    )
                    admin_embed.add_field(
                        name="📋 Details",
                        value=result.get('message', 'Invitation sent successfully'),
                        inline=False
                    )
                    await ctx.send(embed=admin_embed)
                else:
                    # Handle invitation error
                    error_message = result.get('error', 'Unknown error occurred')
                    
                    # Notify user of error
                    error_embed = discord.Embed(
                        title="❌ Invitation Failed",
                        description="There was an error sending your Plex invitation.",
                        color=0xFF0000
                    )
                    error_embed.add_field(
                        name="Error Details",
                        value=error_message,
                        inline=False
                    )
                    await user.send(embed=error_embed)
                    
                    # Notify admin of error
                    admin_error_embed = discord.Embed(
                        title="❌ Invitation Failed",
                        description=f"Failed to invite **{user.display_name}**",
                        color=0xFF0000
                    )
                    admin_error_embed.add_field(
                        name="Error Details",
                        value=error_message,
                        inline=False
                    )
                    await ctx.send(embed=admin_error_embed)
                
            except discord.Forbidden:
                await ctx.send(f"❌ Cannot send DM to **{user.display_name}**. They may have DMs disabled.")
            
        except asyncio.TimeoutError:
            await library_msg.delete()
            await ctx.send("⏰ Library selection timed out.")
        except asyncio.TimeoutError:
            await ctx.send("⏰ User did not respond with their email in time.")

    async def _direct_email_invite(self, ctx: commands.Context, client, email: str, libraries: List[Dict[str, Any]]):
        """Handle direct email invitation with library selection"""
        # Create library selection embed
        library_embed = await self._create_library_selection_embed(libraries)
        
        # Send library selection
        library_msg = await ctx.send(embed=library_embed)
        
        # Add reactions for library selection
        number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
        select_all_emoji = '✅'
        
        for i, lib in enumerate(libraries[:10]):  # Limit to 10 libraries
            await library_msg.add_reaction(number_emojis[i])
        
        await library_msg.add_reaction(select_all_emoji)
        
        # Track selected libraries
        selected_indices = set()
        
        # Enhanced selection embed
        async def update_selection_embed():
            embed = discord.Embed(
                title="📚 Library Selection",
                description="Select libraries to share with the user:",
                color=0xE5A00D
            )
            
            # Show available libraries with selection status
            library_list = []
            for i, lib in enumerate(libraries[:10]):
                name = lib.get('title', 'Unknown Library')
                lib_type = lib.get('type', 'unknown')
                count = lib.get('count', 'N/A')
                
                type_emoji = {
                    'movie': '🎬',
                    'show': '📺', 
                    'music': '🎵',
                    'photo': '📸'
                }.get(lib_type, '📁')
                
                status = "✅" if i in selected_indices else "⬜"
                library_list.append(f"{number_emojis[i]} {status} {type_emoji} **{name}** ({count} items)")
            
            embed.add_field(
                name="Available Libraries",
                value='\n'.join(library_list),
                inline=False
            )
            
            if selected_indices:
                selected_names = [libraries[i].get('title', 'Unknown') for i in selected_indices]
                embed.add_field(
                    name="Currently Selected",
                    value='\n'.join([f"🎬 {name}" for name in selected_names]),
                    inline=False
                )
            
            embed.add_field(
                name="Instructions",
                value="1️⃣-🔟 Toggle individual libraries\n✅ **Select ALL and CONFIRM**",
                inline=False
            )
            
            return embed
        
        # Wait for admin's library selection
        def check_library_reaction(reaction, user):
            return (user == ctx.author and 
                   reaction.message.id == library_msg.id and
                   str(reaction.emoji) in number_emojis[:len(libraries)] + [select_all_emoji])
        
        try:
            while True:
                reaction, _ = await self.bot.wait_for('reaction_add', check=check_library_reaction, timeout=120.0)
                
                if str(reaction.emoji) == select_all_emoji:
                    # If nothing selected, select all. If something selected, confirm.
                    if not selected_indices:
                        # Select all libraries
                        selected_indices = set(range(len(libraries)))
                        await library_msg.edit(embed=await update_selection_embed())
                    else:
                        # Confirm selection
                        selected_libraries = [libraries[i] for i in selected_indices]
                        selected_names = [libraries[i].get('title', 'Unknown') for i in selected_indices]
                        await library_msg.delete()
                        break
                    
                else:
                    # Toggle individual library
                    emoji_index = number_emojis.index(str(reaction.emoji))
                    if emoji_index in selected_indices:
                        selected_indices.remove(emoji_index)
                    else:
                        selected_indices.add(emoji_index)
                    
                    # Update the embed to show current selection
                    try:
                        await library_msg.edit(embed=await update_selection_embed())
                    except discord.NotFound:
                        # Message was deleted, break out of loop
                        return
                
                # Remove the user's reaction to allow re-selection
                try:
                    await library_msg.remove_reaction(reaction.emoji, ctx.author)
                except discord.NotFound:
                    pass
            
            # Send the invitation
            library_ids = [str(lib.get('key', '')) for lib in selected_libraries]
            result = await client.invite_user(email, library_ids)
            
            # Redact email for privacy protection
            redacted_email = self._redact_email(email)
            
            # Handle the response from the enhanced invite_user method
            if result.get('success'):
                # Use sections_shared from result if available, otherwise fall back to selected_names
                shared_sections = result.get('sections_shared', selected_names)
                
                embed = discord.Embed(
                    title="✅ Plex Invitation Sent",
                    description=f"Successfully invited **{redacted_email}** to Plex",
                    color=0x00FF00
                )
                
                embed.add_field(
                    name="📚 Selected Libraries",
                    value=', '.join(shared_sections),
                    inline=False
                )
                
                embed.add_field(
                    name="🔒 Privacy Protection",
                    value="Email address has been redacted for security",
                    inline=False
                )
                

                
                embed.add_field(
                    name="📋 Details",
                    value=result.get('message', 'Invitation sent successfully'),
                    inline=False
                )
                
                await ctx.send(embed=embed)
            else:
                # Handle invitation error
                error_message = result.get('error', 'Unknown error occurred')
                
                embed = discord.Embed(
                    title="❌ Plex Invitation Failed",
                    description=f"Failed to invite **{redacted_email}** to Plex",
                    color=0xFF0000
                )
                
                embed.add_field(
                    name="Error Details",
                    value=error_message,
                    inline=False
                )
                
                embed.add_field(
                    name="🔒 Privacy Protection",
                    value="Email address has been redacted for security",
                    inline=False
                )
                
                await ctx.send(embed=embed)
            
        except asyncio.TimeoutError:
            await library_msg.delete()
            await ctx.send("⏰ Library selection timed out.")

    def _redact_email(self, email: str) -> str:
        """Redact an email address for privacy protection"""
        try:
            if '@' not in email:
                return email
            
            username, domain = email.split('@', 1)
            
            # Redact username part
            if len(username) <= 2:
                redacted_username = '*' * len(username)
            else:
                redacted_username = username[0] + '*' * (len(username) - 2) + username[-1]
            
            # Redact domain part (but keep extension visible)
            if '.' in domain:
                domain_parts = domain.split('.')
                domain_name = domain_parts[0]
                domain_ext = '.'.join(domain_parts[1:])
                
                if len(domain_name) <= 2:
                    redacted_domain = '*' * len(domain_name)
                else:
                    redacted_domain = domain_name[0] + '*' * (len(domain_name) - 2) + domain_name[-1]
                
                redacted_email = f"{redacted_username}@{redacted_domain}.{domain_ext}"
            else:
                # No extension, just redact domain
                if len(domain) <= 2:
                    redacted_domain = '*' * len(domain)
                else:
                    redacted_domain = domain[0] + '*' * (len(domain) - 2) + domain[-1]
                
                redacted_email = f"{redacted_username}@{redacted_domain}"
            
            return redacted_email
            
        except Exception:
            # If redaction fails for any reason, return a generic redacted format
            return "***@***.***"

    async def _create_library_selection_embed(self, libraries: List[Dict[str, Any]]) -> discord.Embed:
        """Create an embed for library selection"""
        embed = discord.Embed(
            title="📚 Select Plex Libraries",
            description="React with the numbers to select libraries for the invitation:",
            color=0xE5A00D
        )
        
        number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
        
        library_list = []
        for i, lib in enumerate(libraries[:10]):  # Limit to 10 libraries
            name = lib.get('title', 'Unknown Library')
            lib_type = lib.get('type', 'unknown')
            count = lib.get('count', 'N/A')
            
            type_emoji = {
                'movie': '🎬',
                'show': '📺', 
                'music': '🎵',
                'photo': '📸'
            }.get(lib_type, '📁')
            
            library_list.append(f"{number_emojis[i]} {type_emoji} **{name}** ({count} items)")
        
        embed.add_field(
            name="Available Libraries",
            value='\n'.join(library_list),
            inline=False
        )
        
        embed.add_field(
            name="✅ Select All Libraries",
            value="React with ✅ to grant access to all libraries",
            inline=False
        )
        
        embed.set_footer(text="You have 60 seconds to make your selection")
        
        return embed

    # Sonarr commands
    @mediacommander.group(name="sonarr")
    @commands.guild_only()
    async def sonarr_group(self, ctx: commands.Context):
        """📺 Sonarr TV Series commands"""
        pass

    @sonarr_group.command(name="search")
    async def sonarr_search(self, ctx: commands.Context, *, query: str):
        """Search for TV series"""
        if not await self._check_service_permission(ctx, 'sonarr'):
            return
        
        client = await self._get_client('sonarr')
        if not client:
            await ctx.send("❌ Sonarr client not configured properly.")
            return
        
        try:
            results = await client.search_series(query)
            if not results:
                await ctx.send(f"🔍 No series found for '{query}'")
                return
            
            embeds = []
            for series in results[:5]:  # Limit to 5 results
                embed = MediaEmbedHelper.create_media_embed(series, 'sonarr', 'series')
                embeds.append(embed)
            
            if embeds:
                if len(embeds) == 1:
                    await ctx.send(embed=embeds[0])
                else:
                    # Use proper pagination with reaction removal
                    current_page = 0
                    
                    # Add page indicator to embed footer
                    for i, embed in enumerate(embeds):
                        embed.set_footer(text=f"Page {i+1} of {len(embeds)} • 🐱 MediaCommander")
                    
                    message = await ctx.send(embed=embeds[current_page])
                    
                    if len(embeds) > 1:
                        # Add reactions for navigation (left, close, right)
                        await start_adding_reactions(message, ["⬅️", "❌", "➡️"])
                        
                        def check(reaction, user):
                            return (
                                user == ctx.author 
                                and reaction.message.id == message.id 
                                and str(reaction.emoji) in ["⬅️", "❌", "➡️"]
                            )
                        
                        try:
                            while True:
                                reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                                
                                if str(reaction.emoji) == "➡️" and current_page < len(embeds) - 1:
                                    current_page += 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "⬅️" and current_page > 0:
                                    current_page -= 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "❌":
                                    try:
                                        await message.delete()
                                    except discord.Forbidden:
                                        await message.clear_reactions()
                                    return
                                
                                # Remove user's reaction
                                try:
                                    await message.remove_reaction(reaction.emoji, user)
                                except discord.Forbidden:
                                    pass  # Bot doesn't have manage messages permission
                                    
                        except asyncio.TimeoutError:
                            pass
                        
                        # Clean up reactions
                        try:
                            await message.clear_reactions()
                        except discord.Forbidden:
                            pass
                
        except Exception as e:
            log.error(f"Sonarr search error: {e}")
            await ctx.send(f"❌ Error searching Sonarr: {str(e)}")

    @sonarr_group.command(name="queue")
    async def sonarr_queue(self, ctx: commands.Context):
        """Show Sonarr download queue"""
        if not await self._check_service_permission(ctx, 'sonarr'):
            return
        
        client = await self._get_client('sonarr')
        if not client:
            await ctx.send("❌ Sonarr client not configured properly.")
            return
        
        try:
            queue = await client.get_queue()
            if not queue:
                await ctx.send("📥 Download queue is empty!")
                return
            
            embed = discord.Embed(
                title="📥 Sonarr Download Queue",
                color=0x35C5F4
            )
            
            for item in queue[:10]:  # Limit to 10 items
                title = item.get('title', 'Unknown')
                status = item.get('status', 'Unknown')
                progress = item.get('sizeleft', 0)
                
                embed.add_field(
                    name=title[:50],
                    value=f"Status: {status}\nProgress: {progress}%",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Sonarr queue error: {e}")
            await ctx.send(f"❌ Error getting Sonarr queue: {str(e)}")

    @sonarr_group.command(name="add")
    async def sonarr_add(self, ctx: commands.Context, *, series_name: str):
        """Add a TV series to Sonarr (Admin only)"""
        if not await self._check_service_permission(ctx, 'sonarr', admin_required=True):
            return
        
        client = await self._get_client('sonarr')
        if not client:
            await ctx.send("❌ Sonarr client not configured properly.")
            return
        
        async with ctx.typing():
            try:
                # Search for the series first
                results = await client.search_series(series_name)
                if not results:
                    await ctx.send(f"🔍 No series found for '{series_name}'")
                    return
                
                # Use the first result
                series = results[0]
                
                # Add required fields for adding series
                series_data = {
                    'title': series.get('title'),
                    'titleSlug': series.get('titleSlug'),
                    'tvdbId': series.get('tvdbId'),
                    'qualityProfileId': 1,  # Default quality profile
                    'rootFolderPath': '/tv/',  # Default root folder
                    'monitored': True,
                    'addOptions': {
                        'monitor': 'all',
                        'searchForMissingEpisodes': True
                    }
                }
                
                result = await client.add_series(series_data)
                
                embed = discord.Embed(
                    title="📺 Series Added to Sonarr",
                    description=f"**{series.get('title')}** has been added!",
                    color=0x35C5F4
                )
                
                if series.get('overview'):
                    embed.add_field(
                        name="Overview",
                        value=series['overview'][:200] + ('...' if len(series['overview']) > 200 else ''),
                        inline=False
                    )
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                log.error(f"Sonarr add error: {e}")
                await ctx.send(f"❌ Error adding series: {str(e)}")

    @sonarr_group.command(name="calendar")
    async def sonarr_calendar(self, ctx: commands.Context, days: int = 7):
        """Show upcoming episodes (next 7 days by default)"""
        if not await self._check_service_permission(ctx, 'sonarr'):
            return
        
        client = await self._get_client('sonarr')
        if not client:
            await ctx.send("❌ Sonarr client not configured properly.")
            return
        
        try:
            from datetime import datetime, timedelta
            start_date = datetime.now().strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            
            episodes = await client.get_calendar(start_date, end_date)
            if not episodes:
                await ctx.send(f"📅 No episodes scheduled for the next {days} days!")
                return
            
            embed = discord.Embed(
                title=f"📅 Upcoming Episodes ({days} days)",
                color=0x35C5F4
            )
            
            for episode in episodes[:10]:  # Limit to 10 episodes
                series_title = episode.get('series', {}).get('title', 'Unknown Series')
                episode_title = episode.get('title', 'Unknown Episode')
                season = episode.get('seasonNumber', 'N/A')
                episode_num = episode.get('episodeNumber', 'N/A')
                air_date = episode.get('airDate', 'Unknown')
                
                embed.add_field(
                    name=f"{series_title} S{season}E{episode_num}",
                    value=f"**{episode_title}**\nAirs: {air_date}",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Sonarr calendar error: {e}")
            await ctx.send(f"❌ Error getting calendar: {str(e)}")

    @sonarr_group.command(name="missing")
    async def sonarr_missing(self, ctx: commands.Context):
        """Search for missing episodes (Admin only)"""
        if not await self._check_service_permission(ctx, 'sonarr', admin_required=True):
            return
        
        client = await self._get_client('sonarr')
        if not client:
            await ctx.send("❌ Sonarr client not configured properly.")
            return
        
        async with ctx.typing():
            try:
                result = await client.search_missing()
                await ctx.send("🔍 **Search for missing episodes started!**\nThis may take a while to complete.")
                
            except Exception as e:
                log.error(f"Sonarr missing search error: {e}")
                await ctx.send(f"❌ Error starting missing search: {str(e)}")

    # Radarr commands
    @mediacommander.group(name="radarr")
    @commands.guild_only()
    async def radarr_group(self, ctx: commands.Context):
        """🎬 Radarr Movie commands"""
        pass

    @radarr_group.command(name="search")
    async def radarr_search(self, ctx: commands.Context, *, query: str):
        """Search for movies"""
        if not await self._check_service_permission(ctx, 'radarr'):
            return
        
        client = await self._get_client('radarr')
        if not client:
            await ctx.send("❌ Radarr client not configured properly.")
            return
        
        try:
            results = await client.search_movies(query)
            if not results:
                await ctx.send(f"🔍 No movies found for '{query}'")
                return
            
            embeds = []
            for movie in results[:5]:  # Limit to 5 results
                embed = MediaEmbedHelper.create_media_embed(movie, 'radarr', 'movie')
                embeds.append(embed)
            
            if embeds:
                if len(embeds) == 1:
                    await ctx.send(embed=embeds[0])
                else:
                    # Use proper pagination with reaction removal
                    current_page = 0
                    
                    # Add page indicator to embed footer
                    for i, embed in enumerate(embeds):
                        embed.set_footer(text=f"Page {i+1} of {len(embeds)} • 🐱 MediaCommander")
                    
                    message = await ctx.send(embed=embeds[current_page])
                    
                    if len(embeds) > 1:
                        # Add reactions for navigation (left, close, right)
                        await start_adding_reactions(message, ["⬅️", "❌", "➡️"])
                        
                        def check(reaction, user):
                            return (
                                user == ctx.author 
                                and reaction.message.id == message.id 
                                and str(reaction.emoji) in ["⬅️", "❌", "➡️"]
                            )
                        
                        try:
                            while True:
                                reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                                
                                if str(reaction.emoji) == "➡️" and current_page < len(embeds) - 1:
                                    current_page += 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "⬅️" and current_page > 0:
                                    current_page -= 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "❌":
                                    try:
                                        await message.delete()
                                    except discord.Forbidden:
                                        await message.clear_reactions()
                                    return
                                
                                # Remove user's reaction
                                try:
                                    await message.remove_reaction(reaction.emoji, user)
                                except discord.Forbidden:
                                    pass  # Bot doesn't have manage messages permission
                                    
                        except asyncio.TimeoutError:
                            pass
                        
                        # Clean up reactions
                        try:
                            await message.clear_reactions()
                        except discord.Forbidden:
                            pass
                
        except Exception as e:
            log.error(f"Radarr search error: {e}")
            await ctx.send(f"❌ Error searching Radarr: {str(e)}")

    @radarr_group.command(name="add")
    async def radarr_add(self, ctx: commands.Context, *, movie_title: str):
        """Add a movie to Radarr (Admin only)"""
        if not await self._check_service_permission(ctx, 'radarr', admin_required=True):
            return
        
        client = await self._get_client('radarr')
        if not client:
            await ctx.send("❌ Radarr client not configured properly.")
            return
        
        async with ctx.typing():
            try:
                # Search for the movie first
                results = await client.search_movies(movie_title)
                if not results:
                    await ctx.send(f"🔍 No movies found for '{movie_title}'")
                    return
                
                # Use the first result
                movie = results[0]
                
                # Add required fields for adding movie
                movie_data = {
                    'title': movie.get('title'),
                    'titleSlug': movie.get('titleSlug'),
                    'tmdbId': movie.get('tmdbId'),
                    'qualityProfileId': 1,  # Default quality profile
                    'rootFolderPath': '/movies/',  # Default root folder
                    'monitored': True,
                    'addOptions': {
                        'monitor': 'movieOnly',
                        'searchForMovie': True
                    }
                }
                
                result = await client.add_movie(movie_data)
                
                embed = discord.Embed(
                    title="🎬 Movie Added to Radarr",
                    description=f"**{movie.get('title')}** has been added!",
                    color=0xFFC230
                )
                
                if movie.get('overview'):
                    embed.add_field(
                        name="Overview",
                        value=movie['overview'][:200] + ('...' if len(movie['overview']) > 200 else ''),
                        inline=False
                    )
                
                if movie.get('year'):
                    embed.add_field(name="Year", value=movie['year'], inline=True)
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                log.error(f"Radarr add error: {e}")
                await ctx.send(f"❌ Error adding movie: {str(e)}")

    @radarr_group.command(name="queue")
    async def radarr_queue(self, ctx: commands.Context):
        """Show Radarr download queue"""
        if not await self._check_service_permission(ctx, 'radarr'):
            return
        
        client = await self._get_client('radarr')
        if not client:
            await ctx.send("❌ Radarr client not configured properly.")
            return
        
        try:
            queue = await client.get_queue()
            if not queue:
                await ctx.send("📥 Download queue is empty!")
                return
            
            embed = discord.Embed(
                title="📥 Radarr Download Queue",
                color=0xFFC230
            )
            
            for item in queue[:10]:  # Limit to 10 items
                title = item.get('title', 'Unknown')
                status = item.get('status', 'Unknown')
                progress = item.get('sizeleft', 0)
                
                embed.add_field(
                    name=title[:50],
                    value=f"Status: {status}\nProgress: {progress}%",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Radarr queue error: {e}")
            await ctx.send(f"❌ Error getting Radarr queue: {str(e)}")

    @radarr_group.command(name="calendar")
    async def radarr_calendar(self, ctx: commands.Context, days: int = 30):
        """Show upcoming movie releases (next 30 days by default)"""
        if not await self._check_service_permission(ctx, 'radarr'):
            return
        
        client = await self._get_client('radarr')
        if not client:
            await ctx.send("❌ Radarr client not configured properly.")
            return
        
        try:
            from datetime import datetime, timedelta
            start_date = datetime.now().strftime('%Y-%m-%d')
            end_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
            
            movies = await client.get_calendar(start_date, end_date)
            if not movies:
                await ctx.send(f"📅 No movies scheduled for the next {days} days!")
                return
            
            embed = discord.Embed(
                title=f"📅 Upcoming Movie Releases ({days} days)",
                color=0xFFC230
            )
            
            for movie in movies[:10]:  # Limit to 10 movies
                title = movie.get('title', 'Unknown Movie')
                release_date = movie.get('physicalRelease', movie.get('digitalRelease', 'Unknown'))
                year = movie.get('year', 'N/A')
                
                embed.add_field(
                    name=f"{title} ({year})",
                    value=f"Release: {release_date}",
                    inline=False
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Radarr calendar error: {e}")
            await ctx.send(f"❌ Error getting calendar: {str(e)}")

    @radarr_group.command(name="missing")
    async def radarr_missing(self, ctx: commands.Context):
        """Search for missing movies (Admin only)"""
        if not await self._check_service_permission(ctx, 'radarr', admin_required=True):
            return
        
        client = await self._get_client('radarr')
        if not client:
            await ctx.send("❌ Radarr client not configured properly.")
            return
        
        async with ctx.typing():
            try:
                result = await client.search_missing()
                await ctx.send("🔍 **Search for missing movies started!**\nThis may take a while to complete.")
                
            except Exception as e:
                log.error(f"Radarr missing search error: {e}")
                await ctx.send(f"❌ Error starting missing search: {str(e)}")

    # Overseerr commands
    @mediacommander.group(name="overseerr", aliases=["requests"])
    @commands.guild_only()
    async def overseerr_group(self, ctx: commands.Context):
        """🎫 Overseerr Request Management commands"""
        pass

    @overseerr_group.command(name="pending")
    async def overseerr_pending(self, ctx: commands.Context):
        """Show pending requests"""
        if not await self._check_service_permission(ctx, 'overseerr', admin_required=True):
            return
        
        client = await self._get_client('overseerr')
        if not client:
            await ctx.send("❌ Overseerr client not configured properly.")
            return
        
        try:
            response = await client.get_pending_requests()
            requests = response.get('results', [])
            
            if not requests:
                await ctx.send("📋 No pending requests!")
                return
            
            embeds = []
            for request in requests[:10]:  # Limit to 10 requests
                embed = MediaEmbedHelper.create_media_embed(request, 'overseerr', 'request')
                embeds.append(embed)
            
            if embeds:
                if len(embeds) == 1:
                    await ctx.send(embed=embeds[0])
                else:
                    # Use proper pagination with reaction removal
                    current_page = 0
                    
                    # Add page indicator to embed footer
                    for i, embed in enumerate(embeds):
                        embed.set_footer(text=f"Page {i+1} of {len(embeds)} • 🐱 MediaCommander")
                    
                    message = await ctx.send(embed=embeds[current_page])
                    
                    if len(embeds) > 1:
                        # Add reactions for navigation (left, close, right)
                        await start_adding_reactions(message, ["⬅️", "❌", "➡️"])
                        
                        def check(reaction, user):
                            return (
                                user == ctx.author 
                                and reaction.message.id == message.id 
                                and str(reaction.emoji) in ["⬅️", "❌", "➡️"]
                            )
                        
                        try:
                            while True:
                                reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                                
                                if str(reaction.emoji) == "➡️" and current_page < len(embeds) - 1:
                                    current_page += 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "⬅️" and current_page > 0:
                                    current_page -= 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "❌":
                                    try:
                                        await message.delete()
                                    except discord.Forbidden:
                                        await message.clear_reactions()
                                    return
                                
                                # Remove user's reaction
                                try:
                                    await message.remove_reaction(reaction.emoji, user)
                                except discord.Forbidden:
                                    pass  # Bot doesn't have manage messages permission
                                    
                        except asyncio.TimeoutError:
                            pass
                        
                        # Clean up reactions
                        try:
                            await message.clear_reactions()
                        except discord.Forbidden:
                            pass
                
        except Exception as e:
            log.error(f"Overseerr pending requests error: {e}")
            await ctx.send(f"❌ Error getting pending requests: {str(e)}")

    @overseerr_group.command(name="approve")
    async def overseerr_approve(self, ctx: commands.Context, request_id: int):
        """Approve a media request (Admin only)"""
        if not await self._check_service_permission(ctx, 'overseerr', admin_required=True):
            return
        
        client = await self._get_client('overseerr')
        if not client:
            await ctx.send("❌ Overseerr client not configured properly.")
            return
        
        try:
            result = await client.approve_request(request_id)
            
            embed = discord.Embed(
                title="✅ Request Approved",
                description=f"Request #{request_id} has been approved!",
                color=0x00FF00
            )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Overseerr approve error: {e}")
            await ctx.send(f"❌ Error approving request: {str(e)}")

    @overseerr_group.command(name="decline")
    async def overseerr_decline(self, ctx: commands.Context, request_id: int, *, reason: str = None):
        """Decline a media request (Admin only)"""
        if not await self._check_service_permission(ctx, 'overseerr', admin_required=True):
            return
        
        client = await self._get_client('overseerr')
        if not client:
            await ctx.send("❌ Overseerr client not configured properly.")
            return
        
        try:
            result = await client.decline_request(request_id, reason)
            
            embed = discord.Embed(
                title="❌ Request Declined",
                description=f"Request #{request_id} has been declined.",
                color=0xFF0000
            )
            
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Overseerr decline error: {e}")
            await ctx.send(f"❌ Error declining request: {str(e)}")

    @overseerr_group.command(name="request")
    async def overseerr_request(self, ctx: commands.Context, media_type: str, *, title: str):
        """Submit a media request
        
        Usage: `[p]mc overseerr request movie "Inception"`
               `[p]mc overseerr request tv "Breaking Bad"`
        """
        if not await self._check_service_permission(ctx, 'overseerr'):
            return
        
        if media_type.lower() not in ['movie', 'tv', 'show']:
            await ctx.send("❌ Media type must be 'movie' or 'tv'/'show'")
            return
        
        client = await self._get_client('overseerr')
        if not client:
            await ctx.send("❌ Overseerr client not configured properly.")
            return
        
        async with ctx.typing():
            try:
                # Search for the media first
                if media_type.lower() == 'movie':
                    results = await client.search_movies(title)
                else:
                    results = await client.search_tv(title)
                
                if not results or not results.get('results'):
                    await ctx.send(f"🔍 No {media_type} found for '{title}'")
                    return
                
                # Use the first result
                media = results['results'][0]
                media_id = media.get('id')
                
                if media_type.lower() == 'movie':
                    result = await client.request_movie(media_id)
                else:
                    result = await client.request_tv(media_id)
                
                embed = discord.Embed(
                    title="🎫 Request Submitted",
                    description=f"Your request for **{media.get('title', media.get('name'))}** has been submitted!",
                    color=0x5865F2
                )
                
                embed.add_field(name="Type", value=media_type.title(), inline=True)
                embed.add_field(name="Status", value="Pending Approval", inline=True)
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                log.error(f"Overseerr request error: {e}")
                await ctx.send(f"❌ Error submitting request: {str(e)}")

    # Lidarr commands
    @mediacommander.group(name="lidarr")
    @commands.guild_only()
    async def lidarr_group(self, ctx: commands.Context):
        """🎵 Lidarr Music Management commands"""
        pass

    @lidarr_group.command(name="search")
    async def lidarr_search(self, ctx: commands.Context, search_type: str, *, query: str):
        """Search for artists or albums
        
        Usage: `[p]mc lidarr search artist "The Beatles"`
               `[p]mc lidarr search album "Abbey Road"`
        """
        if not await self._check_service_permission(ctx, 'lidarr'):
            return
        
        if search_type.lower() not in ['artist', 'album']:
            await ctx.send("❌ Search type must be 'artist' or 'album'")
            return
        
        client = await self._get_client('lidarr')
        if not client:
            await ctx.send("❌ Lidarr client not configured properly.")
            return
        
        try:
            if search_type.lower() == 'artist':
                results = await client.search_artists(query)
                embed_type = 'artist'
            else:
                results = await client.search_albums(query)
                embed_type = 'album'
            
            if not results:
                await ctx.send(f"🔍 No {search_type}s found for '{query}'")
                return
            
            embeds = []
            for item in results[:5]:  # Limit to 5 results
                embed = MediaEmbedHelper.create_media_embed(item, 'lidarr', embed_type)
                embeds.append(embed)
            
            if embeds:
                if len(embeds) == 1:
                    await ctx.send(embed=embeds[0])
                else:
                    # Use proper pagination with reaction removal
                    current_page = 0
                    
                    # Add page indicator to embed footer
                    for i, embed in enumerate(embeds):
                        embed.set_footer(text=f"Page {i+1} of {len(embeds)} • 🐱 MediaCommander")
                    
                    message = await ctx.send(embed=embeds[current_page])
                    
                    if len(embeds) > 1:
                        # Add reactions for navigation (left, close, right)
                        await start_adding_reactions(message, ["⬅️", "❌", "➡️"])
                        
                        def check(reaction, user):
                            return (
                                user == ctx.author 
                                and reaction.message.id == message.id 
                                and str(reaction.emoji) in ["⬅️", "❌", "➡️"]
                            )
                        
                        try:
                            while True:
                                reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60.0)
                                
                                if str(reaction.emoji) == "➡️" and current_page < len(embeds) - 1:
                                    current_page += 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "⬅️" and current_page > 0:
                                    current_page -= 1
                                    await message.edit(embed=embeds[current_page])
                                elif str(reaction.emoji) == "❌":
                                    try:
                                        await message.delete()
                                    except discord.Forbidden:
                                        await message.clear_reactions()
                                    return
                                
                                # Remove user's reaction
                                try:
                                    await message.remove_reaction(reaction.emoji, user)
                                except discord.Forbidden:
                                    pass  # Bot doesn't have manage messages permission
                                    
                        except asyncio.TimeoutError:
                            pass
                        
                        # Clean up reactions
                        try:
                            await message.clear_reactions()
                        except discord.Forbidden:
                            pass
                
        except Exception as e:
            log.error(f"Lidarr search error: {e}")
            await ctx.send(f"❌ Error searching Lidarr: {str(e)}")

    @lidarr_group.command(name="add")
    async def lidarr_add(self, ctx: commands.Context, *, artist_name: str):
        """Add an artist to Lidarr (Admin only)"""
        if not await self._check_service_permission(ctx, 'lidarr', admin_required=True):
            return
        
        client = await self._get_client('lidarr')
        if not client:
            await ctx.send("❌ Lidarr client not configured properly.")
            return
        
        async with ctx.typing():
            try:
                # Search for the artist first
                results = await client.search_artists(artist_name)
                if not results:
                    await ctx.send(f"🔍 No artists found for '{artist_name}'")
                    return
                
                # Use the first result
                artist = results[0]
                
                # Add required fields for adding artist
                artist_data = {
                    'artistName': artist.get('artistName'),
                    'nameSlug': artist.get('nameSlug'),
                    'foreignArtistId': artist.get('foreignArtistId'),
                    'qualityProfileId': 1,  # Default quality profile
                    'rootFolderPath': '/music/',  # Default root folder
                    'monitored': True,
                    'addOptions': {
                        'monitor': 'all',
                        'searchForMissingAlbums': True
                    }
                }
                
                result = await client.add_artist(artist_data)
                
                embed = discord.Embed(
                    title="🎵 Artist Added to Lidarr",
                    description=f"**{artist.get('artistName')}** has been added!",
                    color=0xE7318A
                )
                
                if artist.get('overview'):
                    embed.add_field(
                        name="Overview",
                        value=artist['overview'][:200] + ('...' if len(artist['overview']) > 200 else ''),
                        inline=False
                    )
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                log.error(f"Lidarr add error: {e}")
                await ctx.send(f"❌ Error adding artist: {str(e)}")

    @lidarr_group.command(name="artists")
    async def lidarr_artists(self, ctx: commands.Context):
        """Show monitored artists"""
        if not await self._check_service_permission(ctx, 'lidarr'):
            return
        
        client = await self._get_client('lidarr')
        if not client:
            await ctx.send("❌ Lidarr client not configured properly.")
            return
        
        try:
            artists = await client.get_artists()
            if not artists:
                await ctx.send("🎵 No artists found!")
                return
            
            embed = discord.Embed(
                title="🎵 Monitored Artists",
                color=0xE7318A
            )
            
            for artist in artists[:15]:  # Limit to 15 artists
                name = artist.get('artistName', 'Unknown Artist')
                album_count = artist.get('albumCount', 0)
                monitored = artist.get('monitored', False)
                
                status = "📻 Monitored" if monitored else "⏸️ Unmonitored"
                
                embed.add_field(
                    name=f"🎤 {name}",
                    value=f"Albums: {album_count}\nStatus: {status}",
                    inline=True
                )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Lidarr artists error: {e}")
            await ctx.send(f"❌ Error getting artists: {str(e)}")

    # Tautulli commands
    @mediacommander.group(name="tautulli", aliases=["stats"])
    @commands.guild_only()
    async def tautulli_group(self, ctx: commands.Context):
        """📊 Tautulli Analytics and Statistics commands"""
        pass

    @tautulli_group.command(name="stats")
    async def tautulli_stats(self, ctx: commands.Context):
        """Show Plex server statistics"""
        if not await self._check_service_permission(ctx, 'tautulli'):
            return
        
        client = await self._get_client('tautulli')
        if not client:
            await ctx.send("❌ Tautulli client not configured properly.")
            return
        
        try:
            stats = await client.get_home_stats()
            
            embed = discord.Embed(
                title="📊 Plex Server Statistics",
                color=0xDDA22B
            )
            
            # Add various stats fields based on response
            if stats and 'response' in stats and 'data' in stats['response']:
                data = stats['response']['data']
                for stat in data:
                    stat_id = stat.get('stat_id', '')
                    count = stat.get('count', 0)
                    
                    if stat_id == 'top_movies':
                        embed.add_field(name="🎬 Movies", value=count, inline=True)
                    elif stat_id == 'top_tv':
                        embed.add_field(name="📺 TV Shows", value=count, inline=True)
                    elif stat_id == 'top_music':
                        embed.add_field(name="🎵 Music", value=count, inline=True)
                    elif stat_id == 'top_users':
                        embed.add_field(name="👥 Active Users", value=count, inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Tautulli stats error: {e}")
            await ctx.send(f"❌ Error getting statistics: {str(e)}")

    @tautulli_group.command(name="activity")
    async def tautulli_activity(self, ctx: commands.Context):
        """Show current Plex activity via Tautulli"""
        if not await self._check_service_permission(ctx, 'tautulli'):
            return
        
        client = await self._get_client('tautulli')
        if not client:
            await ctx.send("❌ Tautulli client not configured properly.")
            return
        
        try:
            activity = await client.get_activity()
            
            if activity and 'response' in activity and 'data' in activity['response']:
                activity_data = activity['response']['data']
                sessions = activity_data.get('sessions', [])
                
                embed = MediaEmbedHelper.create_media_embed(
                    {'sessions': sessions}, 'tautulli', 'activity'
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send("📊 No activity data available!")
            
        except Exception as e:
            log.error(f"Tautulli activity error: {e}")
            await ctx.send(f"❌ Error getting activity: {str(e)}")

    @tautulli_group.command(name="users")
    async def tautulli_users(self, ctx: commands.Context):
        """Show user statistics (Admin only)"""
        if not await self._check_service_permission(ctx, 'tautulli', admin_required=True):
            return
        
        client = await self._get_client('tautulli')
        if not client:
            await ctx.send("❌ Tautulli client not configured properly.")
            return
        
        try:
            users_data = await client.get_users()
            
            if users_data and 'response' in users_data and 'data' in users_data['response']:
                users = users_data['response']['data']
                
                embed = discord.Embed(
                    title="👥 User Statistics",
                    color=0xDDA22B
                )
                
                for user in users: 
                    username = user.get('friendly_name', user.get('username', 'Unknown'))
                    plays = user.get('plays', 0)
                    last_seen = user.get('last_seen', 'Never')
                    
                    embed.add_field(
                        name=f"👤 {username}",
                        value=f"Plays: {plays}\nLast Seen: {last_seen}",
                        inline=True
                    )
                
                await ctx.send(embed=embed)
            else:
                await ctx.send("👥 No user data available!")
            
        except Exception as e:
            log.error(f"Tautulli users error: {e}")
            await ctx.send(f"❌ Error getting users: {str(e)}")

    async def cog_unload(self):
        """Clean up when cog is unloaded"""
        for client in self.clients.values():
            if client:
                try:
                    await client.close()
                except:
                    pass 