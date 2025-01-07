# MJDiscord - MidJourney API Integration for Red Discord Bot

<div align="center">

![MJDiscord Banner](https://raw.githubusercontent.com/DeveloperCats/mjdiscord/main/assets/banner.png)

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org)
[![Red-DiscordBot](https://img.shields.io/badge/Red--DiscordBot-3.5+-red.svg)](https://github.com/Cog-Creators/Red-DiscordBot)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

*A powerful [Red Discord Bot](https://github.com/Cog-Creators/Red-DiscordBot) cog that provides seamless integration with MidJourney's API for stunning AI image generation.*

[Installation](#installation) • [Setup Guide](#setup) • [Commands](#commands) • [Examples](#examples) • [Support](#support)

</div>

## ✨ Features

- 🚀 **Direct API Integration** - Reliable and fast communication with MidJourney
- ⚡ **Latest Features** - Support for all MidJourney models and parameters
- 🔄 **Real-time Updates** - Live progress tracking via WebSocket
- 📊 **Job Management** - Detailed tracking and control of image generation
- 🔒 **Secure & Private** - Safe API key handling and role-based access
- 👥 **Multi-User Support** - Concurrent job processing and user quotas
- ⚙️ **Fully Configurable** - Customize every aspect of the integration

## 📥 Installation

1. Install the cog repository:
```bash
[p]repo add mjdiscord https://github.com/DeveloperCats/mjdiscord
```

2. Install the MJDiscord cog:
```bash
[p]cog install mjdiscord mjdiscord
```

3. Load the cog:
```bash
[p]load mjdiscord
```

4. Enable application commands in your server:
   - Use `/applications` in your server
   - Find your bot in the list
   - Enable the "Use Application Commands" permission

> 💡 **Tip**: Slash commands will appear after a few minutes. If they don't, try restarting your Discord client.

## 🛠️ Setup

### 1. MidJourney API Key

To obtain your MidJourney API key:

1. Visit [MidJourney's API Documentation](https://docs.midjourney.com/v1/reference/authentication)
2. Log in to your MidJourney account
3. Navigate to the API Settings or Developer Portal
4. Generate a new API key (Note: Keep this key secure and never share it publicly)
5. Configure the cog with your API key:
```bash
[p]mjset apikey YOUR_API_KEY
```

> ⚠️ **Security Note**: The API key command should be used in a private channel or DM. The bot will automatically delete the message containing your key.

### 2. Webhook URL (Optional but Recommended)

Setting up a webhook enables faster job updates and better progress tracking:

1. Create a Discord Webhook:
   - Go to your server settings
   - Select "Integrations"
   - Click "Create Webhook"
   - Choose a channel for job updates
   - Copy the webhook URL

2. Configure the webhook in the cog:
```bash
[p]mjset webhook YOUR_WEBHOOK_URL
```

> 💡 **Tip**: Create a dedicated channel for MidJourney updates to keep your server organized.

To disable webhook updates:
```bash
[p]mjset webhook
```

### 3. Additional Configuration

1. Configure allowed roles:
```bash
[p]mjset roles
```
> 💡 **Tip**: You can mention multiple roles in one message, or type 'everyone' to allow all users.

2. Set your preferred default model:
```bash
[p]mjset model 5.2
```

## 🎨 Command Usage

This cog supports both traditional prefix commands and slash commands. You can use whichever style you prefer!

### Slash Commands
Just type `/` in your Discord client and select from the MJDiscord commands:
- `/imagine` - Generate images
- `/mjstatus` - Check system status
- `/mjhelp` - View command help
- `/favorites` - View saved images
- `/mjset` - Configure settings (admin only)

### Prefix Commands
Use your bot's prefix (default: `[p]`) followed by the command:
- `[p]imagine` - Generate images
- `[p]mjstatus` - Check system status
- `[p]mjhelp` - View command help
- `[p]favorites` - View saved images
- `[p]mjset` - Configure settings (admin only)

> 💡 **Tip**: Slash commands provide better parameter hints and validation right in Discord!

## 🎨 Usage Examples

### Using Slash Commands
```
/imagine prompt: a magical forest with glowing mushrooms
/imagine prompt: cyberpunk city at night aspect: 16:9 quality: 1 version: 5.2 stylize: 800
/imagine prompt: cute cat version: turbo
```

### Using Prefix Commands
```
[p]imagine a magical forest with glowing mushrooms
[p]imagine cyberpunk city at night --ar 16:9 --quality 1 --version 5.2 --stylize 800
[p]imagine cute cat --version turbo
```

## 🎮 Image Controls

After an image is generated, you can use reaction controls to modify or interact with it:

### Basic Controls
| Reaction | Action | Description |
|----------|--------|-------------|
| 🔄 | Rerun | Generate the image again with the same parameters |
| ⬆️ | Upscale | Open upscale options menu |
| 🎲 | Vary | Open variation options menu |
| 💾 | Save | Save the image to your favorites |
| ❌ | Delete | Remove the message |

### Upscale Options
When you click the upscale (⬆️) reaction:
- 2️⃣ - 2x Upscale
- 4️⃣ - 4x Upscale
- ❌ - Cancel

### Variation Options
When you click the vary (🎲) reaction:
- 🔵 - Subtle Variations (30%)
- 🟢 - Moderate Variations (50%)
- 🟡 - Strong Variations (70%)
- ❌ - Cancel

### Quick Variations
Use number reactions to create specific variations:
- 1️⃣ - Create Variation 1
- 2️⃣ - Create Variation 2
- 3️⃣ - Create Variation 3
- 4️⃣ - Create Variation 4

### Favorites System
- Use 💾 to save images you like
- View your saved images with `[p]favorites`
- Browse through your favorites with pagination controls

> 💡 **Tip**: Reactions are only available to the user who generated the image

## 🎮 Commands

### Image Generation
Command: `[p]imagine <prompt> [parameters]`

Available Parameters:
| Parameter | Description | Values | Example |
|-----------|-------------|---------|---------|
| `aspect` | Image aspect ratio | 1:1, 16:9, 2:3, etc. | `--ar 16:9` |
| `stylize` | Style strength | 0-1000 | `--stylize 800` |
| `chaos` | Variation amount | 0-100 | `--chaos 50` |
| `quality` | Image quality | .25, .5, 1 | `--quality 1` |
| `seed` | Reproducible results | Any number | `--seed 12345` |
| `version` | MJ model version | 5.0, 5.1, 5.2, niji, turbo | `--version 5.2` |
| `no_style` | Disable base style | true/false | `--no_style` |

### Management Commands
| Command | Description |
|---------|-------------|
| `[p]mjset apikey <key>` | Set MidJourney API key |
| `[p]mjset webhook [url]` | Configure webhook updates |
| `[p]mjset roles` | Set allowed roles |
| `[p]mjset model <version>` | Set default model |
| `[p]mjstatus` | Check system status |
| `[p]mjhelp` | View detailed help |

## 🚀 Available Models

| Model | Description | Best For |
|-------|-------------|----------|
| `5.0` | Base V5 model | General purpose |
| `5.1` | Enhanced details | Realistic images |
| `5.2` | Latest version | Best quality |
| `niji` | Anime style | Illustrations |
| `turbo` | Fast generation | Quick results |

## ⚙️ Configuration Options

- **API Key Management**: Secure storage and handling
- **Webhook Integration**: Real-time job updates
- **Role-based Access**: Control who can use commands
- **Model Selection**: Default version setting
- **Job Limits**: 1-5 concurrent jobs per user
- **Cooldowns**: Rate limiting for fair usage

## 📋 Requirements

- Python 3.8 or higher
- Red-DiscordBot V3.5+
- Required packages:
  ```
  aiohttp>=3.8.0
  websockets>=10.0
  pillow>=9.0.0
  python-dotenv>=0.19.0
  ```

## 🆘 Support

Need help? Found a bug? Have a suggestion?

- Open an issue in the [mjdiscord repository](https://github.com/DeveloperCats/mjdiscord)
- Join our [Support Server](https://discord.gg/mjdiscord)
- Check the [FAQ](https://github.com/DeveloperCats/mjdiscord/wiki/FAQ)

## 👏 Credits

- Created by [DeveloperCats](https://github.com/DeveloperCats)
- MidJourney for their amazing AI image generation API
- Red Discord Bot team for the bot framework

## 📄 License

This cog is released under the MIT License. See the [LICENSE](LICENSE) file for details. 