# MJDiscord - MidJourney Integration for Red Discord Bot

A [Red Discord Bot](https://github.com/Cog-Creators/Red-DiscordBot) cog that provides seamless integration with MidJourney's image generation capabilities directly through your Red Bot.

## Installation

To install the cog, run the following commands in Discord:

```
[p]repo add catcogs https://github.com/DeveloperCats/catcogs
[p]cog install catcogs mjdiscord
[p]load mjdiscord
```

## Setup

1. Make sure you have the MidJourney bot in your server
2. Run the setup command:
```
[p]mjset setup
```
3. Follow the interactive setup process:
   - Specify the channel where MidJourney bot is active
   - Configure allowed roles (or type 'everyone' to allow all users)
   - Configure optional settings like auto-reactions and job limits

## Commands

### Image Generation
- `[p]imagine <prompt> [parameters]` - Generate an image using MidJourney
  
  Optional Parameters:
  - `aspect` - Aspect ratio (e.g., '1:1', '16:9', '2:3')
  - `stylize` - Stylization value (0-1000)
  - `chaos` - Chaos value (0-100)
  - `quality` - Quality value (.25, .5, or 1)
  - `seed` - Seed number for reproducible results
  - `version` - MidJourney model version (5.1, 5.2, or niji)
  - `no_style` - Disable MJ's base stylization

  Example:
  ```
  [p]imagine a magical forest with glowing mushrooms --ar 16:9 --quality 1
  ```

### Management Commands
- `[p]mjset setup` - Interactive setup for MidJourney integration
- `[p]mjset reactions <true/false>` - Toggle automatic reaction controls
- `[p]mjstatus` - Check MidJourney integration status
- `[p]mjhelp` - Show detailed help for commands and parameters

## Features

- 🎨 Generate images using MidJourney through Discord commands
- ✨ Support for all MidJourney parameters (aspect ratio, quality, style, etc.)
- 🔄 Interactive image controls through reactions
- ⚙️ Configurable user permissions and job limits
- 📊 Progress tracking and status updates
- 💬 Detailed error messages and user feedback

## Reaction Controls

After an image is generated, you can use reactions to:
- 1️⃣-4️⃣ - Upscale the corresponding image variation
- 🔄 - Create variations of the image

## Configuration Options

- Channel Configuration
- Role-based Access Control
- Concurrent Job Limits (1-5 per user)
- Automatic Reaction Controls
- Command Cooldowns

## Support

For support, bug reports, or feature requests, please open an issue in the [catcogs repository](https://github.com/DeveloperCats/catcogs).

## Credits

- Created by [DeveloperCats](https://github.com/DeveloperCats)
- MidJourney for their amazing AI image generation
- Red Discord Bot team for the bot framework

## License

This cog is released under the MIT License. See the LICENSE file for details. 