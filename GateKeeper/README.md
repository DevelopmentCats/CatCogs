# 🔒 GateKeeper - Discord Security Cog

A POWERFUL and user-friendly security cog for Red Discord Bot that helps protect your server from unwanted visitors! 

## 😺 Features

- 🛡️ **Automatic Role Management**
  - New members are assigned an unverified role
  - Gain access through member vouching
  - Customizable verification requirements

- 🎨 **Beautiful Embedded Messages**
  - Welcome messages for new members
  - Verification status updates
  - Progress tracking for vouches

- ⚙️ **Easy Setup**
  - Interactive setup wizard
  - Customizable settings
  - Role creation and management

## 📚 Commands

### Admin Commands
- `[p]gatekeeper setup` - Run the interactive setup wizard
- `[p]gatekeeper settings` - View and modify settings
- `[p]supervouch <member> [reason]` - Instantly verify a member
- `[p]gk massverify <members...>` - Verify multiple members at once
- `[p]gk stats` - View verification statistics

### Member Commands
- `[p]vouch <member>` - Vouch for a new member
- `[p]vouchinfo [member]` - Check verification status

## 🚀 Installation

1. Make sure you have Red-DiscordBot v3 installed
2. Add this repository to your bot:
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

1. Run `[p]gatekeeper setup` to start the interactive setup
2. The cog will create necessary roles and channels
3. Customize settings using `[p]gatekeeper settings`

## 🐾 Contributing

Feel free to submit issues and pull requests! All contributions are welcome!

## 📜 License

This project is licensed under the MIT License - see the LICENSE file for details.

---
Made with 😺 by DevelopmentCats - Keeping your Discord server as safe as a cat guarding its territory!
