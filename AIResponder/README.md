
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
```

Now let's create a migration guide:

```markdown:MIGRATION.md
# Migration Guide: AIResponder V2 to V3

## Major Changes

### 1. State Machine Architecture
- Replaced chain-of-thought with state machine
- New planning and execution states
- Better error recovery

### 2. Memory System
- New conversation memory interface
- Enhanced context management
- Better cleanup mechanisms

### 3. Tool System
- New tool definitions
- Async tool support
- Enhanced error handling

### 4. Configuration
- New configuration schema
- Enhanced validation
- Migration support

## Migration Steps

1. Configuration Updates
```python
# Old format
await self.config.api_key.set("key")

# New format
await self.config.set({
    "api_key": "key",
    "schema_version": 2,
    "provider": "openai"
})
```

2. Tool Updates
```python
# Old format
@tool
def my_tool():
    pass

# New format
class MyTool(BaseCogTool):
    name: str = "My Tool"
    description: str = "Tool description"
    
    async def _arun(self, input: str) -> str:
        pass
```

3. Memory Updates
```python
# Old format
self.memory = ConversationBufferWindowMemory()

# New format
self.memory = DiscordConversationMemory(
    logger=self.logger,
    max_token_limit=2000,
    max_history_items=50
)
```

4. Error Handling Updates
```python
# Old format
try:
    result = await self.agent(query)
except Exception as e:
    await self.handle_error(e)

# New format
with self.error_handler.error_context({"query": query}):
    result = await self.agent_executor.ainvoke(state)
```

## Breaking Changes

1. Response Format
- Streaming responses now use new callback system
- Different message chunking format

2. Tool Execution
- Tools must be async-compatible
- New error handling requirements

3. Configuration
- New schema version
- Stricter validation

4. Memory System
- New memory interfaces
- Different context format

## Compatibility

The V3 update includes automatic migration for:
- Existing configurations
- Stored conversations
- Tool definitions
- Custom prompts

## Support

For migration assistance:
1. Check error logs
2. Review documentation
3. Submit issues on GitHub
