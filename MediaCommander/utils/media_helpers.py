"""
Helper classes for MediaCommander
Handles Discord embeds, permissions, and media formatting
"""

import discord
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
import logging

log = logging.getLogger("red.mediacommander.media_helpers")

class MediaEmbedHelper:
    """Helper class for creating rich Discord embeds for media content"""
    
    @staticmethod
    def create_media_embed(media_data: Dict[str, Any], service: str, embed_type: str = "info") -> discord.Embed:
        """Create a rich embed for media content"""
        
        # Color scheme based on service
        colors = {
            'plex': 0xE5A00D,
            'sonarr': 0x35C5F4,
            'radarr': 0xFFC230,
            'lidarr': 0xE7318A,
            'tautulli': 0xDDA22B,
            'overseerr': 0x5865F2
        }
        
        color = colors.get(service.lower(), 0x99AAB5)
        
        if embed_type == "movie":
            return MediaEmbedHelper._create_movie_embed(media_data, color)
        elif embed_type == "series":
            return MediaEmbedHelper._create_series_embed(media_data, color)
        elif embed_type == "artist":
            return MediaEmbedHelper._create_artist_embed(media_data, color)
        elif embed_type == "album":
            return MediaEmbedHelper._create_album_embed(media_data, color)
        elif embed_type == "activity":
            return MediaEmbedHelper._create_activity_embed(media_data, color)
        elif embed_type == "request":
            return MediaEmbedHelper._create_request_embed(media_data, color)
        else:
            return MediaEmbedHelper._create_generic_embed(media_data, service, color)
    
    @staticmethod
    def _create_movie_embed(movie_data: Dict[str, Any], color: int) -> discord.Embed:
        """Create embed for movie information"""
        title = movie_data.get('title', 'Unknown Movie')
        year = movie_data.get('year', '')
        if year:
            title += f" ({year})"
            
        embed = discord.Embed(
            title=f"🎬 {title}",
            color=color
        )
        
        # Add description
        overview = movie_data.get('overview', movie_data.get('summary', ''))
        if overview:
            embed.description = overview[:500] + ('...' if len(overview) > 500 else '')
        
        # Add fields
        if 'runtime' in movie_data:
            embed.add_field(name="Runtime", value=f"{movie_data['runtime']} min", inline=True)
        
        if 'studio' in movie_data:
            embed.add_field(name="Studio", value=movie_data['studio'], inline=True)
        
        if 'rating' in movie_data:
            embed.add_field(name="Rating", value=movie_data['rating'], inline=True)
        
        if 'genres' in movie_data and movie_data['genres']:
            genres = ', '.join(movie_data['genres'][:3])
            embed.add_field(name="Genres", value=genres, inline=True)
        
        # Add poster if available
        if 'poster' in movie_data or 'thumb' in movie_data:
            poster_url = movie_data.get('poster', movie_data.get('thumb'))
            if poster_url and poster_url.startswith('http'):
                embed.set_thumbnail(url=poster_url)
        
        return embed
    
    @staticmethod
    def _create_series_embed(series_data: Dict[str, Any], color: int) -> discord.Embed:
        """Create embed for TV series information"""
        title = series_data.get('title', series_data.get('seriesName', 'Unknown Series'))
        year = series_data.get('year', series_data.get('firstAired', ''))
        if year and str(year)[:4]:
            title += f" ({str(year)[:4]})"
            
        embed = discord.Embed(
            title=f"📺 {title}",
            color=color
        )
        
        # Add description
        overview = series_data.get('overview', series_data.get('summary', ''))
        if overview:
            embed.description = overview[:500] + ('...' if len(overview) > 500 else '')
        
        # Add fields
        if 'network' in series_data:
            embed.add_field(name="Network", value=series_data['network'], inline=True)
        
        if 'status' in series_data:
            embed.add_field(name="Status", value=series_data['status'], inline=True)
        
        if 'seasonCount' in series_data:
            embed.add_field(name="Seasons", value=series_data['seasonCount'], inline=True)
        
        if 'episodeCount' in series_data:
            embed.add_field(name="Episodes", value=series_data['episodeCount'], inline=True)
        
        if 'genres' in series_data and series_data['genres']:
            genres = ', '.join(series_data['genres'][:3])
            embed.add_field(name="Genres", value=genres, inline=True)
        
        # Add poster if available
        if 'poster' in series_data or 'banner' in series_data:
            poster_url = series_data.get('poster', series_data.get('banner'))
            if poster_url and poster_url.startswith('http'):
                embed.set_thumbnail(url=poster_url)
        
        return embed
    
    @staticmethod
    def _create_artist_embed(artist_data: Dict[str, Any], color: int) -> discord.Embed:
        """Create embed for artist information"""
        name = artist_data.get('artistName', artist_data.get('name', 'Unknown Artist'))
        
        embed = discord.Embed(
            title=f"🎵 {name}",
            color=color
        )
        
        # Add description
        biography = artist_data.get('biography', artist_data.get('overview', ''))
        if biography:
            embed.description = biography[:500] + ('...' if len(biography) > 500 else '')
        
        # Add fields
        if 'albumCount' in artist_data:
            embed.add_field(name="Albums", value=artist_data['albumCount'], inline=True)
        
        if 'trackCount' in artist_data:
            embed.add_field(name="Tracks", value=artist_data['trackCount'], inline=True)
        
        if 'genres' in artist_data and artist_data['genres']:
            genres = ', '.join(g.get('name', g) for g in artist_data['genres'][:3])
            embed.add_field(name="Genres", value=genres, inline=True)
        
        # Add image if available
        if 'images' in artist_data and artist_data['images']:
            image_url = artist_data['images'][0].get('url')
            if image_url and image_url.startswith('http'):
                embed.set_thumbnail(url=image_url)
        
        return embed
    
    @staticmethod
    def _create_album_embed(album_data: Dict[str, Any], color: int) -> discord.Embed:
        """Create embed for album information"""
        title = album_data.get('title', album_data.get('albumName', 'Unknown Album'))
        artist = album_data.get('artist', {}).get('artistName', album_data.get('artistName', ''))
        
        embed_title = f"💿 {title}"
        if artist:
            embed_title += f" - {artist}"
            
        embed = discord.Embed(
            title=embed_title,
            color=color
        )
        
        # Add fields
        if 'releaseDate' in album_data:
            embed.add_field(name="Release Date", value=album_data['releaseDate'], inline=True)
        
        if 'trackCount' in album_data:
            embed.add_field(name="Tracks", value=album_data['trackCount'], inline=True)
        
        if 'genres' in album_data and album_data['genres']:
            genres = ', '.join(g.get('name', g) for g in album_data['genres'][:3])
            embed.add_field(name="Genres", value=genres, inline=True)
        
        # Add cover if available
        if 'images' in album_data and album_data['images']:
            image_url = album_data['images'][0].get('url')
            if image_url and image_url.startswith('http'):
                embed.set_thumbnail(url=image_url)
        
        return embed
    
    @staticmethod
    def _create_activity_embed(activity_data: Dict[str, Any], color: int) -> discord.Embed:
        """Create embed for current activity/sessions"""
        sessions = activity_data.get('sessions', [])
        stream_count = len(sessions)
        
        embed = discord.Embed(
            title=f"📊 Current Activity ({stream_count} streams)",
            color=color
        )
        
        if not sessions:
            embed.description = "No active streams"
            return embed
        
        for i, session in enumerate(sessions[:5]):  # Limit to 5 sessions
            user = session.get('user', 'Unknown User')
            title = session.get('title', 'Unknown')
            player = session.get('player', 'Unknown Device')
            state = session.get('state', 'unknown')
            
            field_name = f"👤 {user}"
            field_value = f"**{title}**\n📱 {player} ({state})"
            
            if 'progress_percent' in session:
                progress = session['progress_percent']
                field_value += f"\n⏳ {progress}% complete"
            
            embed.add_field(name=field_name, value=field_value, inline=False)
        
        if len(sessions) > 5:
            embed.add_field(name="...", value=f"And {len(sessions) - 5} more sessions", inline=False)
        
        return embed
    
    @staticmethod
    def _create_request_embed(request_data: Dict[str, Any], color: int) -> discord.Embed:
        """Create embed for media requests"""
        media = request_data.get('media', {})
        title = media.get('title', 'Unknown Request')
        media_type = request_data.get('type', 'unknown')
        status = request_data.get('status', 'pending')
        
        # Status emoji mapping
        status_emojis = {
            'pending': '⏳',
            'approved': '✅',
            'declined': '❌',
            'available': '📼'
        }
        
        status_emoji = status_emojis.get(status, '❓')
        type_emoji = '🎬' if media_type == 'movie' else '📺' if media_type == 'tv' else '🎵'
        
        embed = discord.Embed(
            title=f"{type_emoji} {title}",
            color=color
        )
        
        embed.add_field(name="Status", value=f"{status_emoji} {status.title()}", inline=True)
        embed.add_field(name="Type", value=media_type.title(), inline=True)
        
        if 'requestedBy' in request_data:
            embed.add_field(name="Requested By", value=request_data['requestedBy']['displayName'], inline=True)
        
        if 'createdAt' in request_data:
            created_date = datetime.fromisoformat(request_data['createdAt'].replace('Z', '+00:00'))
            embed.add_field(name="Requested", value=created_date.strftime('%Y-%m-%d %H:%M'), inline=True)
        
        # Add poster if available
        if media.get('posterPath'):
            poster_url = f"https://image.tmdb.org/t/p/w500{media['posterPath']}"
            embed.set_thumbnail(url=poster_url)
        
        return embed
    
    @staticmethod
    def _create_generic_embed(data: Dict[str, Any], service: str, color: int) -> discord.Embed:
        """Create a generic embed for any data"""
        title = data.get('title', data.get('name', f"{service.title()} Data"))
        
        embed = discord.Embed(
            title=f"📋 {title}",
            color=color
        )
        
        # Add description if available
        desc = data.get('description', data.get('overview', data.get('summary', '')))
        if desc:
            embed.description = desc[:500] + ('...' if len(desc) > 500 else '')
        
        # Add up to 5 fields from the data
        field_count = 0
        for key, value in data.items():
            if field_count >= 5:
                break
            if key not in ['title', 'name', 'description', 'overview', 'summary'] and value:
                embed.add_field(name=key.title(), value=str(value)[:100], inline=True)
                field_count += 1
        
        return embed

class PermissionHelper:
    """Helper class for managing role-based permissions"""
    
    @staticmethod
    def has_media_admin_role(member: discord.Member, admin_roles: List[int]) -> bool:
        """Check if member has any of the configured admin roles"""
        if not admin_roles:
            return False
        return any(role.id in admin_roles for role in member.roles)
    
    @staticmethod
    def has_media_user_role(member: discord.Member, user_roles: List[int]) -> bool:
        """Check if member has any of the configured user roles"""
        if not user_roles:
            return True  # If no roles configured, everyone has access
        return any(role.id in user_roles for role in member.roles)
    
    @staticmethod
    def can_use_service(member: discord.Member, service: str, config_data: Dict[str, Any]) -> bool:
        """Check if member can use a specific service"""
        service_config = config_data.get(f"{service}_config", {})
        
        # Check if service is enabled
        if not service_config.get('enabled', False):
            return False
        
        # Check admin permissions
        admin_roles = service_config.get('admin_roles', [])
        if PermissionHelper.has_media_admin_role(member, admin_roles):
            return True
        
        # Check user permissions
        user_roles = service_config.get('user_roles', [])
        return PermissionHelper.has_media_user_role(member, user_roles)
    
    @staticmethod
    def get_user_permissions(member: discord.Member, config_data: Dict[str, Any]) -> Dict[str, str]:
        """Get user's permission level for each service"""
        permissions = {}
        services = ['plex', 'sonarr', 'radarr', 'lidarr', 'tautulli', 'overseerr']
        
        for service in services:
            service_config = config_data.get(f"{service}_config", {})
            
            if not service_config.get('enabled', False):
                permissions[service] = 'disabled'
                continue
            
            admin_roles = service_config.get('admin_roles', [])
            user_roles = service_config.get('user_roles', [])
            
            if PermissionHelper.has_media_admin_role(member, admin_roles):
                permissions[service] = 'admin'
            elif PermissionHelper.has_media_user_role(member, user_roles):
                permissions[service] = 'user'
            else:
                permissions[service] = 'none'
        
        return permissions
    
    @staticmethod
    def format_permissions_embed(member: discord.Member, permissions: Dict[str, str]) -> discord.Embed:
        """Create an embed showing user's permissions"""
        embed = discord.Embed(
            title=f"🔒 Media Permissions for {member.display_name}",
            color=0x5865F2
        )
        
        # Group permissions by level
        admin_services = []
        user_services = []
        disabled_services = []
        no_access_services = []
        
        for service, level in permissions.items():
            if level == 'admin':
                admin_services.append(service.title())
            elif level == 'user':
                user_services.append(service.title())
            elif level == 'disabled':
                disabled_services.append(service.title())
            else:
                no_access_services.append(service.title())
        
        if admin_services:
            embed.add_field(
                name="🛡️ Admin Access",
                value=', '.join(admin_services),
                inline=False
            )
        
        if user_services:
            embed.add_field(
                name="👤 User Access",
                value=', '.join(user_services),
                inline=False
            )
        
        if disabled_services:
            embed.add_field(
                name="🚫 Disabled Services",
                value=', '.join(disabled_services),
                inline=False
            )
        
        if no_access_services:
            embed.add_field(
                name="❌ No Access",
                value=', '.join(no_access_services),
                inline=False
            )
        
        return embed 