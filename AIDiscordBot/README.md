# 🤖 Gemini AI Discord Bot

A powerful Discord bot powered by Google's Gemini-Pro AI model, featuring intelligent conversation, web search capabilities, and dynamic personality customization.

## ✨ Features

- 🧠 **Advanced AI Conversations**: Powered by Google's Gemini-Pro model
- 🔍 **Web Search Integration**: Real-time information from the web
- 🎭 **Customizable Personality**: Adapt the bot's personality per channel
- 📚 **Conversation Memory**: Maintains context for natural discussions
- ⚡ **Rate Limiting**: Smart message handling to prevent spam

## 🚀 Installation

1. **Install the Cog**
   ```
   [p]cog install catcogs AIDiscordBot
   [p]load AIDiscordBot
   ```

2. **Configure API Keys (Required)**
   ```
   [p]chatbot setapikey <your_gemini_api_key>
   ```

3. **Set Up Web Search (Optional)**
   ```
   [p]chatbot searchkey <your_search_api_key>
   [p]chatbot searchid <your_search_engine_id>
   [p]chatbot togglesearch
   ```

## 💬 Usage

### Basic Interaction
Simply mention the bot (@BotName) to start chatting!
```
@BotName Hello! How are you today?
```

### Available Commands

#### Configuration
- `[p]chatbot setapikey <key>` - Set Gemini API key (Admin only)
- `[p]chatbot toggle` - Enable/disable bot
- `[p]chatbot personality [text]` - View/set bot personality
- `[p]chatbot reset` - Reset conversation history
- `[p]chatbot clearrate` - Clear rate limits

#### Search Configuration
- `[p]chatbot searchkey <key>` - Set Search API key (Admin only)
- `[p]chatbot searchid <id>` - Set Search Engine ID (Admin only)
- `[p]chatbot togglesearch` - Enable/disable search

#### Status Commands
- `[p]chatbot status` - Check bot status
- `[p]chatbot settings` - View current settings

## 📝 Getting API Keys

### Gemini API Key
1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create or select a project
3. Enable the Gemini API
4. Create API credentials

### Google Custom Search (Optional)
1. Visit [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project and enable Custom Search API
3. Create API credentials
4. Create a [Custom Search Engine](https://programmablesearchengine.google.com/)
