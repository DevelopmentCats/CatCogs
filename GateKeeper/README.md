# 🔒 GateKeeper - Discord Security Cog

A PURRFECT security system that guards your Discord server like a vigilant cat! 😺

## 🐱 Features

- 🛡️ **Advanced Verification System**
  - New members start in the Welcome Center
  - Trusted members vouch for newcomers
  - Customizable verification requirements
  - Auto-removal of inactive unverified members

- 🏰 **Welcome Center**
  - Dedicated verification desk
  - Friendly welcome lounge
  - Clear instructions and rules
  - Comprehensive logging

- 🎨 **Beautiful Embedded Messages**
  - Themed welcome messages
  - Status updates and notifications
  - Progress tracking
  - Detailed statistics

- ⚙️ **Easy Setup**
  - One-command setup wizard
  - Customizable settings
  - Automatic channel creation
  - Role management

## 📚 Commands

### Admin Commands
- `[p]gatekeeper setup` - Run the setup wizard
- `[p]gk settings` - View current settings
- `[p]gk setvouch <amount>` - Set required vouches
- `[p]gk setwelcomemsg <message>` - Customize welcome message
- `[p]gk timeout <hours>` - Set verification timeout
- `[p]supervouch <member> [reason]` - Instantly verify someone
- `[p]gk massverify <members...>` - Verify multiple members
- `[p]gk stats` - View verification statistics
- `[p]gk blacklist <member>` - Ban from verification

### Moderator Commands
- `[p]vouch <member>` - Vouch for a new member
- `[p]unvouch <member>` - Remove your vouch
- `[p]vouchinfo [member]` - Check verification status

### Member Commands
- `[p]vouchinfo` - Check your verification progress

## 🚀 Installation

1. Make sure you have Red-DiscordBot v3.5+ installed
2. Add this repository:
   ```
   [p]repo add gatekeeper <repository_url>
   ```
3. Install the cog:
   ```
   [p]cog install gatekeeper
   ```
4. Load the cog:
   ```
   [p]load gatekeeper
   ```

## ⚙️ Initial Setup

1. Run the setup wizard:
   ```
   [p]gatekeeper setup
   ```
2. The wizard will:
   - Create necessary roles
   - Set up the Welcome Center
   - Configure logging
   - Enable protection

3. Customize settings (optional):
   - Welcome message: `[p]gk setwelcomemsg`
   - Required vouches: `[p]gk setvouch`
   - Verification timeout: `[p]gk timeout`

## 🔒 Security Features

- Role-based access control
- Automatic unverified member cleanup
- Blacklist system
- Comprehensive logging
- Verification timeout
- Anti-spam protection

## 📝 Support

Need help? Found a bug? Have a suggestion? Open an issue on our GitHub repository!

---

*Made with 😺 by DevelopmentCats - Keeping your server as safe as a cat guards its territory!*
