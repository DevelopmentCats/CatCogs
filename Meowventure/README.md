# Meowventure - A Discord Adventure Game

![Meowventure Logo](https://placekitten.com/200/200) *Logo coming soon*

Meowventure is a text-based adventure game cog for Red Discord Bot where players can explore, battle, and collect cats!

## Project Structure
```
meowventure/
├── __init__.py       # Cog initialization
├── game.py           # Main game logic
├── commands.py       # Command implementations
├── data.py           # Data models and storage
├── helpers.py        # Utility functions
├── info.json         # Cog metadata
├── README.md         # Documentation
└── data/             # Game data files
    ├── abilities.json
    ├── cats.json
    ├── effects.json
    ├── items.json
    └── shop.json
```

## Installation
1. Add the repo: `[p]repo add meowventure <repo_url>`
2. Install the cog: `[p]cog install meowventure meowventure`
3. Load the cog: `[p]load meowventure`
4. Start playing: `[p]meowventure start`

## Development Setup
1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Run tests:
```bash
python -m pytest tests/
```

## Commands

### Game Commands
- `[p]meowventure start` - Start your adventure
- `[p]meowventure profile` - View your profile
- `[p]meowventure explore` - Explore new areas
- `[p]meowventure shop` - Visit the item shop
- `[p]meowventure battle @user` - Battle another player
- `[p]meowventure inventory` - View your items
- `[p]meowventure cats` - View your cat collection
- `[p]meowventure daily` - Claim daily rewards

### Admin Commands
- `[p]meowventureset currency <name>` - Set currency name
- `[p]meowventureset daily <amount>` - Set daily reward amount
- `[p]meowventureset toggle` - Enable/disable the game

## Data Files
The game uses JSON files in the `data/` directory:
- `abilities.json` - Cat abilities and effects
- `cats.json` - Cat types and stats
- `effects.json` - Status effects
- `items.json` - Shop items and equipment
- `shop.json` - Shop configuration

## Contributing
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## License
MIT License

## Author
**DeveloperCats** - [GitHub](https://github.com/DeveloperCats)
