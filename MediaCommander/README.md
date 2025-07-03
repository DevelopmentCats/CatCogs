# 🎬 MediaCommander - Ultimate Media Management for Discord

> **Your PURRFECTLY CHAOTIC Media Companion!**  
> Created by DevelopmentCats with EXTREME FELINE PRECISION 🐱

MediaCommander is a comprehensive Red Discord Bot cog that integrates with the full Arr stack and related media services, providing both server owners and users with powerful media management capabilities directly from Discord.

## 🌟 Features

### 🔧 Supported Services

- **🎭 Plex Media Server** - Stream management, user access, library browsing
- **📺 Sonarr** - TV series management, search, and automation  
- **🎬 Radarr** - Movie management, search, and automation
- **🎵 Lidarr** - Music management, artist and album handling
- **📊 Tautulli** - Plex analytics and monitoring
- **🎫 Overseerr** - Media request management and approval

### 🎯 Key Capabilities

- **Role-Based Permissions** - Separate admin and user access levels
- **Rich Discord Embeds** - Beautiful media displays with posters and metadata
- **Real-Time Monitoring** - Current activity tracking and queue management
- **Search & Discovery** - Find media across all integrated services
- **Request Management** - Handle media requests through Overseerr
- **Secure Configuration** - API keys and tokens stored securely
- **Admin Media Management** - Add series/movies, invite users, approve requests
- **Interactive Dashboard** - Comprehensive overview of all services and permissions
- **Comprehensive Analytics** - Detailed statistics via Tautulli integration
- **Music Management** - Full Lidarr support for artist and album management
- **Secure User Invitations** - Private DM-based Plex invites with interactive library selection and email redaction

## 🚀 Installation

1. **Add the cog to your Red instance:**
   ```bash
   [p]repo add catcogs https://github.com/DevelopmentCats/CatCogs
   [p]cog install catcogs MediaCommander
   [p]load MediaCommander
   ```

2. **Verify installation:**
   ```bash
   [p]mc config status
   ```

## 🚀 Quick Start Examples

Once configured, try these commands to get started:

```bash
# Check your dashboard
[p]mc dashboard

# Search for media
[p]mc plex search "The Office"
[p]mc sonarr search "Breaking Bad"
[p]mc radarr search "Inception"

# Request new media
[p]mc overseerr request movie "Dune"
[p]mc overseerr request tv "The Mandalorian"

# Check server activity
[p]mc plex activity
[p]mc tautulli stats

# Admin: Add media
[p]mc sonarr add "Stranger Things"
[p]mc radarr add "Spider-Man"

# Admin: Invite users securely
[p]mc plex invite @username
```

## ⚙️ Configuration

### Initial Setup

Configure each service you want to use:

```bash
# Plex Media Server
[p]mc config setup plex https://plex.yourdomain.com YOUR_PLEX_TOKEN

# Sonarr
[p]mc config setup sonarr https://sonarr.yourdomain.com YOUR_SONARR_API_KEY

# Radarr  
[p]mc config setup radarr https://radarr.yourdomain.com YOUR_RADARR_API_KEY

# Lidarr
[p]mc config setup lidarr https://lidarr.yourdomain.com YOUR_LIDARR_API_KEY

# Tautulli
[p]mc config setup tautulli https://tautulli.yourdomain.com YOUR_TAUTULLI_API_KEY

# Overseerr
[p]mc config setup overseerr https://overseerr.yourdomain.com YOUR_OVERSEERR_API_KEY
```

### Role Configuration

Set up role-based permissions:

```bash
# Admin roles (full management access)
[p]mc config roles plex admin @PlexAdmin @ServerMod

# User roles (limited access)
[p]mc config roles plex user @PlexUser @Member @Everyone

# Apply to other services
[p]mc config roles sonarr admin @MediaAdmin
[p]mc config roles sonarr user @PlexUser @Member
```

### Check Configuration

```bash
[p]mc config status
```

## 📚 Command Reference

### 🎛️ Configuration Commands (Owner Only)

| Command | Description |
|---------|-------------|
| `[p]mc config setup <service> <url> <key>` | Configure a service |
| `[p]mc config roles <service> <type> <roles>` | Set admin/user roles |
| `[p]mc config status` | Show configuration status |

### 🔧 General Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `[p]mc dashboard` | Show service overview and status | User |
| `[p]mc help` | Show detailed command reference | User |
| `[p]mc permissions [@user]` | Check media permissions | User |

### 🎭 Plex Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `[p]mc plex status` | Check server status | User |
| `[p]mc plex search <query>` | Search media library | User |
| `[p]mc plex activity` | Show current streams | User |
| `[p]mc plex libraries` | Show all libraries | User |
| `[p]mc plex users` | Show all users | Admin |
| `[p]mc plex invite @user` | Secure user invite (DM for email) | Admin |
| `[p]mc plex invite email <email>` | Direct email invite | Admin |

### 📺 Sonarr Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `[p]mc sonarr search <query>` | Search for TV series | User |
| `[p]mc sonarr add <series>` | Add series to Sonarr | Admin |
| `[p]mc sonarr queue` | Show download queue | User |
| `[p]mc sonarr calendar [days]` | Show upcoming episodes | User |
| `[p]mc sonarr missing` | Search for missing episodes | Admin |

### 🎬 Radarr Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `[p]mc radarr search <query>` | Search for movies | User |
| `[p]mc radarr add <movie>` | Add movie to Radarr | Admin |
| `[p]mc radarr queue` | Show download queue | User |
| `[p]mc radarr calendar [days]` | Show upcoming releases | User |
| `[p]mc radarr missing` | Search for missing movies | Admin |

### 🎵 Lidarr Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `[p]mc lidarr search artist <name>` | Search for artists | User |
| `[p]mc lidarr search album <name>` | Search for albums | User |
| `[p]mc lidarr add <artist>` | Add artist to Lidarr | Admin |
| `[p]mc lidarr artists` | Show monitored artists | User |

### 📊 Tautulli Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `[p]mc tautulli stats` | Show server statistics | User |
| `[p]mc tautulli activity` | Show current activity | User |
| `[p]mc tautulli users` | Show user statistics | Admin |

### 🎫 Overseerr Commands

| Command | Description | Permissions |
|---------|-------------|-------------|
| `[p]mc overseerr request movie <title>` | Request a movie | User |
| `[p]mc overseerr request tv <title>` | Request a TV show | User |
| `[p]mc overseerr pending` | Show pending requests | Admin |
| `[p]mc overseerr approve <id>` | Approve a request | Admin |
| `[p]mc overseerr decline <id> [reason]` | Decline a request | Admin |

## 🔑 API Key Setup

### Plex Token
1. Visit [plex.tv/claim](https://plex.tv/claim)
2. Copy the claim token
3. Use in setup command

### Sonarr/Radarr/Lidarr API Keys
1. Go to Settings → General in your *arr app
2. Copy the API Key
3. Use in setup command

### Tautulli API Key
1. Go to Settings → Web Interface
2. Show Advanced → API
3. Copy the API Key

### Overseerr API Key
1. Go to Settings → General
2. Copy the API Key from the API section

## 🛡️ Permission System

MediaCommander uses a flexible role-based permission system:

### Permission Levels

- **Owner** - Full access to all commands and configuration
- **Admin** - Management commands, request approval, user management
- **User** - Search, personal requests, viewing permissions
- **None** - No access to the service

### Service-Specific Roles

Each service can have different admin and user roles configured independently, allowing fine-grained control over who can access what functionality.

## 🔒 Secure Plex Invitations

MediaCommander features a unique **secure invitation system** for Plex:

### 🛡️ Secure Method (Recommended)
```bash
[p]mc plex invite @username
```
1. **Admin tags a Discord user** in the server
2. **Bot sends interactive library selection** with emoji reactions
3. **User receives private DM** requesting their email
4. **Email stays completely private** - never exposed in server
5. **Automatic invitation** sent with selected libraries

### 📧 Direct Method (Private Channels)
```bash
[p]mc plex invite email user@email.com
```
- For use in private channels or DMs
- Still includes interactive library selection
- **Email address redacted** in confirmation messages
- Direct email invitation with privacy protection

### ✨ Interactive Library Selection
- **Visual library browser** with media counts
- **Emoji-based selection** (1️⃣, 2️⃣, etc.)
- **Select all option** with ✅
- **Library type indicators** (🎬 Movies, 📺 TV, 🎵 Music)

## 🎨 Rich Embeds

MediaCommander creates beautiful Discord embeds for:

- **Movie Information** - Posters, runtime, genres, ratings
- **TV Series Details** - Seasons, episodes, network, status  
- **Artist Profiles** - Biography, album count, genres
- **Album Information** - Release dates, track counts, cover art
- **Activity Monitoring** - Current streams with progress
- **Request Status** - Pending, approved, declined states
- **Interactive Library Selection** - Visual library management

## 🔧 Troubleshooting

### Common Issues

**Service not responding:**
```bash
# Check configuration
[p]mc config status

# Verify URLs are accessible
# Confirm API keys are correct
```

**Permission denied:**
```bash
# Check your roles
[p]mc permissions

# Ask admin to add you to appropriate roles
[p]mc config roles <service> user @YourRole
```

**No results found:**
- Verify the service is properly configured
- Check if media exists in the service
- Ensure your query is specific enough

### Debug Information

- All errors are logged to Red's logging system
- Check bot logs for detailed error messages
- API responses are logged for troubleshooting

## 🤝 Contributing

Found a bug or want to add a feature? 

1. Report issues on our [GitHub repository](https://github.com/DevelopmentCats/CatCogs)
2. Submit pull requests with improvements
3. Join our Discord community for support

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.

## 🙏 Acknowledgments

- **Red Discord Bot** - The amazing framework that makes this possible
- **Plex Inc.** - For their robust media server platform
- **The *Arr Community** - For their incredible automation tools
- **Overseerr Team** - For their beautiful request management system

---

*🐱 Made with extreme feline precision by DevelopmentCats*

**Support the project:** ⭐ Star us on GitHub | �� Join our Discord 