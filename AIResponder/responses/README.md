# AIResponder Cog for Red-DiscordBot

A powerful AI assistant cog for Red-DiscordBot using Deep Infra and state-of-the-art language models.

## Features

- 🤖 Advanced AI conversation capabilities
- 🔧 Modular tool integration system
- 💾 Intelligent memory management
- 🔄 Streaming responses
- 🛠️ Comprehensive error handling
- ⚡ Rate limiting and burst control
- 📊 Built-in analytics

## Installation

1. Install required dependencies:
```bash
python -m pip install langchain numexpr aiohttp python-dateutil
```

2. Load the cog:
```bash
[p]load airesponder
```

3. Configure the cog:
```bash
[p]air setkey YOUR_API_KEY
[p]air setmodel meta-llama/Llama-3.2-11B-Vision-Instruct
```

## Commands

### User Commands
- `[p]air help` - View AI assistant capabilities
- `[p]air clearhistory` - Clear your conversation history
- `[p]air status` - Check AI system status

### Admin Commands
- `[p]air setkey <api_key>` - Set the API key
- `[p]air setmodel <model>` - Set the AI model
- `[p]air togglechannel` - Enable/disable AI in current channel

## Configuration

### Basic Settings
- `api_key`: Your Deep Infra API key
- `model_name`: Model to use (default: meta-llama/Llama-3.2-11B-Vision-Instruct)
- `max_history`: Number of conversation turns to remember
- `history_expiry_hours`: Hours before conversation history expires

### Rate Limiting
- `rate_limit_requests`: Maximum requests per minute
- `rate_limit_burst`: Maximum burst requests
- `rate_limit_cooldown`: Cooldown period in seconds

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

## Error Handling

The cog includes comprehensive error handling:
- Automatic recovery mechanisms
- Rate limit monitoring
- Admin notifications
- Detailed logging
- Performance metrics

## Usage Examples

1. Basic Conversation:
```
@BotName What is the weather like?
```

2. Using Tools:
```
@BotName Calculate 2 * (3 + 4)
@BotName Search for latest news about AI
```

3. Server Information:
```
@BotName Tell me about this server
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## Support

For support:
1. Check the command help: `[p]help air`
2. Visit our support server
3. Open an issue on GitHub

## License

MIT License - See LICENSE file for details

## Credits

- Built for Red-DiscordBot
- Uses Deep Infra's AI models
- Special thanks to all contributors