# Meowventure - A Red-DiscordBot Cat Collection Game

<div align="center">

![Meowventure Logo](assets/logo.png)

A feature-rich Discord cat collection game where users can collect unique cats, battle with them, and earn rewards! Built as a cog for Red Discord Bot.

[![Red-DiscordBot](https://img.shields.io/badge/Red--DiscordBot-V3.5+-red.svg)](https://github.com/Cog-Creators/Red-DiscordBot)
[![Discord](https://img.shields.io/discord/YOUR_DISCORD_ID)](https://discord.gg/YOUR_INVITE)
[![GitHub license](https://img.shields.io/github/license/Developer-Cats/catcogs)](https://github.com/Developer-Cats/catcogs/blob/master/LICENSE)

</div>

## About

Meowventure is an engaging cat collection game where users can:
- 🐱 Collect unique cats with different personalities and abilities
- ⚔️ Battle other players' cats in epic duels
- 🌿 Earn catnip through chatting and daily rewards
- 🏆 Participate in tournaments
- 🎭 Customize cats with equipment and items
- 📈 Level up cats and unlock new abilities

## Features

### Cat Collection
- Over 50 unique cats to collect
- Different rarities: Common, Uncommon, Rare, Epic, and Legendary
- Unique personalities affecting battle stats
- Special abilities and combat moves
- Customizable nicknames for cats

### Battle System
- Turn-based combat with strategic elements
- Special abilities and status effects
- Equipment and item system
- Tournament mode for competitive play
- Battle rewards and rankings

### Economy
- Earn catnip through various activities
- Daily rewards with streak bonuses
- Shop system with rotating inventory
- Premium and regular summoning systems
- Trading system (coming soon)

### Progression
- Level up system for cats
- Unlock new abilities as cats grow stronger
- Achievement system
- Leaderboards and rankings
- Collection completion tracking

## Commands

### Basic Commands
- `[p]meow` - Main command group
- `[p]meow profile [user]` - View your or another user's profile
- `[p]meow daily` - Claim your daily catnip reward
- `[p]meow cats` - View your cat collection

### Cat Management
- `[p]meow adopt <cat_id>` - Adopt a cat from the shop
- `[p]meow nickname <cat_id> <name>` - Give a nickname to your cat
- `[p]meow pet <cat_id>` - Pet your cat to increase happiness
- `[p]meow favorite <cat_id>` - Set your favorite cat

### Battle Commands
- `[p]meow battle challenge <user> <cat_id>` - Challenge another user to a battle
- `[p]meow battle accept <challenger_id> <cat_id>` - Accept a battle challenge
- `[p]meow battle decline <challenger_id>` - Decline a battle challenge

### Shop Commands
- `[p]meow shop` - View the cat shop
- `[p]meow item shop` - View the item shop
- `[p]meow item buy <item_id>` - Buy an item
- `[p]meow item inventory` - View your inventory

### Summoning Commands
- `[p]meow summon regular` - Perform a regular summon (300 catnip)
- `[p]meow summon premium` - Perform a premium summon (1000 catnip)
- `[p]meow summon multi` - Perform a 10x premium summon (9000 catnip)

### Tournament Commands
- `[p]meow tournament start` - Start a tournament (Admin only)
- `[p]meow tournament join <cat_id>` - Join an active tournament

## Installation

1. Make sure you have [Red-DiscordBot V3.5+](https://github.com/Cog-Creators/Red-DiscordBot) installed
2. Install required dependencies:
```bash
[p]pip install discord.py>=2.0.0
```
3. Add the repository:
```bash
[p]repo add catcogs https://github.com/Developer-Cats/catcogs
```
4. Install the cog:
```bash
[p]cog install catcogs meowventure
```
5. Load the cog:
```bash
[p]load meowventure
```

## Configuration

Use the following commands to configure the cog:
```bash
[p]meowset catnipchance <chance>  # Set chance of earning catnip from chat (0-1)
[p]meowset catnipamount <min> <max>  # Set min/max catnip earned from chat
```

## Contributing

We welcome contributions to Meowventure! Here's how you can help:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

Please read our [Contributing Guidelines](CONTRIBUTING.md) for details.

## Support

Join our [Discord server](https://discord.gg/YOUR_INVITE) for support, feature requests, and community discussions.

## Credits

- Developer: Developer Cats
- Special thanks to the Red-DiscordBot community
- Cat artwork and designs by various artists (see [CREDITS.md](CREDITS.md))

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
