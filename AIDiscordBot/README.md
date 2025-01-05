# DiscordChatBot - Gemini AI Powered Discord Bot

A sophisticated Red-DiscordBot cog that creates an intelligent chat bot using Google's Gemini AI. This bot can engage in natural conversations while maintaining context awareness of both the server and time.

## 🌟 Features

- 🤖 Intelligent conversations using Google's Gemini AI
- 💭 Multi-question handling in single messages
- 🧠 Conversation memory with configurable history
- 🌍 Server context awareness
- ⏰ Time zone support with accurate time references
- ⚡ Real-time typing indicators
- 🛡️ Rate limiting and safety features
- 🎯 Precise mention-based activation
- 📝 Discord-native formatting
- 👤 User nickname awareness

## 📋 Prerequisites

- Red-DiscordBot instance (v3.5.0+)
- Google Gemini API key (get it from https://makersuite.google.com/app/apikey)

## 🚀 Installation

1. Add the repository to your bot:
   ```
   [p]repo add discordchatbot <repository_url>
   ```

2. Install the cog:
   ```
   [p]cog install discordchatbot
   ```

3. Load the cog:
   ```
   [p]load discordchatbot
   ```

4. Set your Gemini API key (bot owner only):
   ```
   [p]chatbot setapikey <your_api_key>
   ```

## ⚙️ Configuration Commands

All configuration commands start with `[p]chatbot` and require administrator permissions unless noted.

### Essential Setup

| Command | Description | Example | Permission |
|---------|-------------|---------|------------|
| `setapikey <key>` | Set Gemini API key | `[p]chatbot setapikey your_key_here` | Bot Owner |
| `timezone <timezone>` | Set server timezone | `[p]chatbot timezone America/Chicago` | Admin |
| `toggle` | Enable/disable the bot | `[p]chatbot toggle` | Admin |

### Advanced Settings

| Command | Description | Parameters | Example |
|---------|-------------|------------|---------|
| `maxhistory <amount>` | Set max conversation history | `amount`: 1-50 messages | `[p]chatbot maxhistory 20` |
| `ratelimit <amount>` | Set rate limit | `amount`: 1-60 messages per minute | `[p]chatbot ratelimit 10` |
| `clearhistory` | Clear conversation history | None | `[p]chatbot clearhistory` |

## 💬 Usage

### Starting a Conversation

To chat with the bot, simply mention it in any channel:
```
@BotName How are you today?
```

### Multi-Question Messages

You can ask multiple questions in one message:
```
@BotName What time is it? How's the weather? What's new?
```

### Discord Formatting

The bot understands and uses Discord's native formatting:
- **Bold** text using `**text**`
- *Italic* text using `*text*`
- `Code blocks` for code snippets
- > Quotes for references
- Bullet points for lists
- Emojis for expression

## 🎯 Features in Detail

### Time Awareness
- Maintains accurate time information
- Responds with time-appropriate context
- Supports all standard timezone formats
- Remembers server-specific timezone settings

### Conversation Memory
- Maintains context across messages
- Configurable history length (1-50 messages)
- Privacy-focused with easy clearing
- Stores user nicknames for personalized interaction

### Server Context
- Aware of server name and details
- Maintains server-specific settings
- Adapts responses to server context
- Channel-aware responses

### Safety Features
- Configurable rate limiting
- Proper error handling
- Resource cleanup
- Memory management
- Administrator-only configuration

## 🔒 Privacy & Data

- No permanent data storage
- Conversation history stored temporarily in memory
- Easily clearable with `[p]chatbot clearhistory`
- No personal information retained
- Compliant with Discord's privacy guidelines

## 👥 Support & Community

- For issues: Open an issue in the repository
- For questions: Join our Discord support server
- For updates: Watch the repository

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👨‍💻 Author

**DeveloperCats**

## 📝 Changelog

### Version 1.0.0
- Initial release
- Full Gemini AI integration
- Discord-native formatting
- Time awareness
- Multi-question handling
