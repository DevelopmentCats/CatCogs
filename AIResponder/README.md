
# AIResponder Cog for Red-DiscordBot

A powerful AI assistant cog for Red-DiscordBot using LangChain V3 and state-of-the-art language models.

## Features

- 🤖 Advanced AI conversation capabilities
- 🔧 Modular tool integration system
- 💾 Intelligent memory management
- 🔄 State machine architecture
- 🛠️ Comprehensive error handling
- ⚡ Streaming responses
- 📊 Built-in analytics

## Installation

1. Install required dependencies:
```bash
python -m pip install langchain langchain-openai openai aiohttp sympy
```

2. Load the cog:
```bash
[p]load airesponder
```

3. Configure the cog:
```bash
[p]aiconfig set api_key YOUR_API_KEY
[p]aiconfig set model gpt-3.5-turbo
```

## Configuration

### Basic Settings
- `api_key`: Your API key
- `model`: Model to use (e.g., "gpt-3.5-turbo")
- `temperature`: Response creativity (0.0-2.0)
- `max_tokens`: Maximum response length

### Memory Settings
- `max_history_items`: Number of conversation turns to remember
- `context_window`: Messages to include for context
- `max_token_limit`: Maximum memory token limit

### Tool Settings
- Enable/disable specific tools
- Configure tool permissions
- Set tool-specific rate limits

## Commands

### User Commands
- `[p]ai <query>`: Interact with the AI assistant
- `[p]aihelp`: View AI assistant capabilities
- `[p]aistatus`: Check AI system status

### Admin Commands
- `[p]aiconfig view`: View current configuration
- `[p]aiconfig set <setting> <value>`: Update settings
- `[p]aireload`: Reload AI components
- `[p]errorstats`: View error statistics

## Tools

### Built-in Tools
1. Calculator
   - Perform mathematical calculations
   - Supports complex expressions

2. Search
   - Web search functionality
   - Real-time information retrieval

3. Discord Info
   - Server information
   - Channel history access

4. Time/Date
   - Current time in various formats
   - Date calculations

## Error Handling

The cog includes comprehensive error handling:
- Automatic recovery mechanisms
- Error rate monitoring
- Admin notifications
- Detailed logging
- Performance metrics

## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License

MIT License - See LICENSE file for details
