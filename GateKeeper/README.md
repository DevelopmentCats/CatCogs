# 🔒 GateKeeper - Discord Security Cog

A PURRFECT security system that guards your Discord server like a vigilant cat! 😺

## 🐱 Features

- 🛡️ **Advanced Verification System**
  - Trusted members vouch for newcomers
  - Customizable vouch requirements
  - Auto-removal of inactive unverified members
  - Comprehensive verification logging

- 🏰 **Welcome Center**
  - Dedicated verification desk with clear instructions
  - Public welcome lounge for newcomer introductions
  - Organized under a clean category structure
  - Automatic permission management

- 🔐 **Permission Management**
  - Automatic channel permission setup
  - Verified users get full channel access
  - Unverified users are restricted appropriately
  - Preserves existing special permissions

- 📊 **Comprehensive Logging**
  - Tracks all verification attempts
  - Monitors vouch activity
  - Logs configuration changes
  - Private logging channel

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
   - Create/update necessary roles (Unverified, Verified, Voucher)
   - Set up the Welcome Center category
   - Create/update verification channels
   - Configure logging
   - Set up channel permissions

3. Customize settings (optional):
   - Welcome message: `[p]gk setwelcomemsg`
   - Required vouches: `[p]gk setvouch`
   - Verification timeout: `[p]gk timeout`

## 🔒 Channel Structure

### Welcome Center Category
- **verification-desk**: Read-only channel with verification instructions
- **welcome-lounge**: Public chat for new members and introductions
- **gatekeeper-logs**: Private channel for verification activity

### Channel Permissions
- **Verified Users Get**:
  - Channel visibility and access
  - Message sending and history
  - Reactions and file attachments
  - Voice channel access
  - External emoji usage
  - Basic user permissions

- **Unverified Users**:
  - Can only see welcome channels
  - Can chat in welcome-lounge
  - All other channels hidden

## 🛡️ Security Features

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
