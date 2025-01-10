# 🐾 GateKeeper - The Purrfect Security System 🛡️

```
  _____________________________
 /                             \
|    ____    ____    ____    ____|
|   |    |  |    |  |    |  |    |
|   |    |  |    |  |    |  |    |
|   |____|  |____|  |____|  |____|
|   __________________________   |
|  |                          |  |
|  |   🐱 GateKeeper 🛡️      |  |
|  |__________________________|  |
 \_____________________________/
```

> "A security system so reliable, even cats would trust it!" 🐱

---

## 🎯 Features

### 🛡️ **Advanced Verification System**
- 🐾 Trusted members vouch for newcomers
- 🎚️ Customizable vouch requirements
- 🕒 Auto-removal of inactive unverified members
- 📜 Comprehensive verification logging

### 🏰 **Welcome Center**
- 🖥️ Dedicated verification desk with clear instructions
- 🛋️ Public welcome lounge for newcomer introductions
- 🗂️ Organized under a clean category structure
- 🔑 Automatic permission management

### 🔐 **Permission Management**
- ⚙️ Automatic channel permission setup
- 🟢 Verified users get full channel access
- 🔴 Unverified users are restricted appropriately
- ⚖️ Preserves existing special permissions

### 📊 **Comprehensive Logging**
- 📝 Tracks all verification attempts
- 👥 Monitors vouch activity
- ⚙️ Logs configuration changes
- 🔒 Private logging channel

---

## 🚀 Installation

```bash
[p]repo add catcogs https://github.com/DevelopmentCats/CatCogs
[p]cog install catcogs gatekeeper
[p]load gatekeeper
```

---

## 🎮 Commands

### 🛠️ Admin Commands
- `[p]gatekeeper setup` - Run the setup wizard
- `[p]gk settings` - View current settings
- `[p]gk setvouch <amount>` - Set required vouches
- `[p]gk setwelcomemsg <message>` - Customize welcome message
- `[p]gk timeout <hours>` - Set verification timeout
- `[p]supervouch <member> [reason]` - Instantly verify someone
- `[p]gk massverify <members...>` - Verify multiple members
- `[p]gk stats` - View verification statistics
- `[p]gk blacklist <member>` - Ban from verification

### 🛡️ Moderator Commands
- `[p]vouch <member>` - Vouch for a new member
- `[p]unvouch <member>` - Remove your vouch
- `[p]vouchinfo [member]` - Check verification status

### 👤 Member Commands
- `[p]vouchinfo` - Check your verification progress

---

## 🎨 Visual Structure

### Welcome Center Layout
```
📁 Welcome Center
├── 📝 verification-desk
├── 💬 welcome-lounge
└── 🔒 gatekeeper-logs
```

---

## 🛡️ Security Features

- 🔒 Role-based access control
- 🧹 Automatic unverified member cleanup
- 🚫 Blacklist system
- 📜 Comprehensive logging
- ⏳ Verification timeout
- 🚨 Anti-spam protection

---

## 📝 Support

🐛 Found a bug?  
💡 Have a suggestion?  
🐾 Need help?  

Open an issue on our [GitHub repository](https://github.com/DevelopmentCats/CatCogs)!

---

*Made with ❤️ by DevelopmentCats - Keeping your server as safe as a cat guards its territory!*
