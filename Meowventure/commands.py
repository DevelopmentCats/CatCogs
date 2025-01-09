from typing import Optional, List
import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify
import asyncio
import random
from datetime import datetime, timedelta

from .game import GameState, Cat, Battle, game_state
from .ai import BattleAI, PersonalityProfile

class Meowventure(commands.Cog):
    """A quirky cat collection and battle game!"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=260288776360820736)
        
        # Default settings
        default_global = {
            "maintenance_mode": False,
            "last_reset": None,
            "shop_rotation": None
        }
        
        default_guild = {
            "enabled": True,
            "battle_channels": [],
            "leaderboard": {}
        }
        
        default_user = {
            "cats": {},  # Cat collection
            "active_team": [],  # Current battle team
            "inventory": {},  # Items
            "currency": {
                "fish": 0,
                "gems": 0
            },
            "stats": {
                "battles_won": 0,
                "battles_lost": 0,
                "cats_collected": 0,
                "daily_streak": 0,
                "last_daily": None
            }
        }
        
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)

    @commands.hybrid_group(name="meow")
    async def meow(self, ctx: commands.Context):
        """Main command group for Meowventure"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    # Core Game Commands
    @meow.command(name="start")
    @app_commands.describe(
        starter_cat="Choose your starter cat type (nature, shadow, light)"
    )
    async def meow_start(self, ctx: commands.Context, starter_cat: str = "random"):
        """Start your Meowventure journey with a starter cat!"""
        # Check if user already has data
        user_data = await self.config.user(ctx.author).all()
        if user_data["cats"]:
            return await ctx.send("You've already started your journey! Use `/meow profile` to see your progress.")
        
        # Validate starter cat choice
        valid_starters = ["nature", "shadow", "light"]
        if starter_cat == "random":
            starter_cat = random.choice(valid_starters)
        elif starter_cat.lower() not in valid_starters:
            return await ctx.send(f"Invalid starter cat! Choose from: {humanize_list(valid_starters)}")
        
        # Create starter cat data
        starter_cats = {
            "nature": {
                "id": "starter_nature",
                "name": "Leafwhisker",
                "title": "Sprout Guardian",
                "rarity": "rare",
                "affinity": "nature",
                "base_stats": {
                    "hp": 100,
                    "attack": 15,
                    "defense": 10,
                    "speed": 12,
                    "crit_rate": 0.05,
                    "crit_damage": 1.5
                },
                "growth_rates": {
                    "hp": 10,
                    "attack": 5,
                    "defense": 4,
                    "speed": 3
                },
                "abilities": ["nature_surge", "healing_breeze"],
                "passive": "nature_empowerment",
                "personality_type": "noble",
                "battle_style": "supportive"
            },
            "shadow": {
                "id": "starter_shadow",
                "name": "Nightprowl",
                "title": "Shadow Walker",
                "rarity": "rare",
                "affinity": "shadow",
                "base_stats": {
                    "hp": 90,
                    "attack": 18,
                    "defense": 8,
                    "speed": 14,
                    "crit_rate": 0.08,
                    "crit_damage": 1.6
                },
                "growth_rates": {
                    "hp": 8,
                    "attack": 6,
                    "defense": 3,
                    "speed": 4
                },
                "abilities": ["shadow_strike", "stealth_pounce"],
                "passive": "shadow_affinity",
                "personality_type": "mysterious",
                "battle_style": "aggressive"
            },
            "light": {
                "id": "starter_light",
                "name": "Dawnwhisper",
                "title": "Light Bringer",
                "rarity": "rare",
                "affinity": "light",
                "base_stats": {
                    "hp": 95,
                    "attack": 16,
                    "defense": 12,
                    "speed": 10,
                    "crit_rate": 0.06,
                    "crit_damage": 1.5
                },
                "growth_rates": {
                    "hp": 9,
                    "attack": 5,
                    "defense": 5,
                    "speed": 3
                },
                "abilities": ["radiant_beam", "blessing_light"],
                "passive": "light_resonance",
                "personality_type": "noble",
                "battle_style": "strategic"
            }
        }
        
        # Initialize user data
        starter_cat_data = starter_cats[starter_cat]
        async with self.config.user(ctx.author).all() as user_data:
            user_data["cats"][starter_cat_data["id"]] = starter_cat_data
            user_data["active_team"] = [starter_cat_data["id"]]
            user_data["currency"]["fish"] = 100  # Starting currency
            user_data["stats"]["cats_collected"] = 1
        
        # Create welcome embed
        embed = discord.Embed(
            title="🌟 Welcome to Meowventure! 🌟",
            description=f"Your journey begins with {starter_cat_data['name']}, the {starter_cat_data['title']}!",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Your Starter Cat",
            value=f"**Name:** {starter_cat_data['name']}\n"
                  f"**Title:** {starter_cat_data['title']}\n"
                  f"**Affinity:** {starter_cat_data['affinity'].title()}\n"
                  f"**Rarity:** {starter_cat_data['rarity'].title()}",
            inline=False
        )
        embed.add_field(
            name="Getting Started",
            value="• Use `/meow help` to see all commands\n"
                  "• Start a patrol with `/meow patrol`\n"
                  "• Check your profile with `/meow profile`\n"
                  "• Visit the shop with `/meow shop`",
            inline=False
        )
        embed.set_footer(text="Your adventure awaits!")
        
        await ctx.send(embed=embed)

    @meow.command(name="profile")
    @app_commands.describe(user="View another user's profile (optional)")
    async def meow_profile(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """View your Meowventure profile and stats"""
        target = user or ctx.author
        user_data = await self.config.user(target).all()
        
        if not user_data["cats"]:
            if target == ctx.author:
                return await ctx.send("You haven't started your journey yet! Use `/meow start` to begin.")
            return await ctx.send(f"{target.display_name} hasn't started their Meowventure journey yet!")
        
        # Create profile embed
        embed = discord.Embed(
            title=f"🐱 {target.display_name}'s Meowventure Profile",
            color=discord.Color.blue()
        )
        
        # Collection stats
        embed.add_field(
            name="Collection",
            value=f"Cats: {len(user_data['cats'])}\n"
                  f"Active Team: {len(user_data['active_team'])}/4",
            inline=True
        )
        
        # Currency
        embed.add_field(
            name="Currency",
            value=f"🐟 Fish: {user_data['currency']['fish']}\n"
                  f"💎 Gems: {user_data['currency']['gems']}",
            inline=True
        )
        
        # Battle stats
        total_battles = user_data["stats"]["battles_won"] + user_data["stats"]["battles_lost"]
        win_rate = (user_data["stats"]["battles_won"] / total_battles * 100) if total_battles > 0 else 0
        embed.add_field(
            name="Battle Stats",
            value=f"Battles Won: {user_data['stats']['battles_won']}\n"
                  f"Win Rate: {win_rate:.1f}%",
            inline=True
        )
        
        # Active team
        if user_data["active_team"]:
            team_cats = []
            for cat_id in user_data["active_team"]:
                cat = user_data["cats"].get(cat_id, {})
                if cat:
                    team_cats.append(f"• {cat['name']} ({cat.get('level', 1)})")
            
            embed.add_field(
                name="Active Team",
                value="\n".join(team_cats) if team_cats else "No active team set",
                inline=False
            )
        
        # Daily streak
        last_daily = user_data["stats"]["last_daily"]
        if last_daily:
            last_daily = datetime.fromisoformat(last_daily)
            streak_text = f"🔥 Daily Streak: {user_data['stats']['daily_streak']}"
            if datetime.utcnow() - last_daily < timedelta(days=1):
                streak_text += "\n✅ Daily reward claimed"
            embed.add_field(name="Daily Status", value=streak_text, inline=False)
        
        await ctx.send(embed=embed)

    @meow.command(name="help")
    @app_commands.describe(command="Get help for a specific command")
    async def meow_help(self, ctx: commands.Context, command: Optional[str] = None):
        """Get help with Meowventure commands"""
        if command is None:
            # Create main help embed
            embed = discord.Embed(
                title="🐱 Meowventure Help",
                description="A quirky cat collection and battle game!",
                color=discord.Color.blue()
            )
            
            # Add command categories
            categories = {
                "Core Commands": [
                    "`/meow start` - Begin your journey",
                    "`/meow profile` - View your profile",
                    "`/meow help` - Show this help message"
                ],
                "Cat Management": [
                    "`/meow cats` - View your cat collection",
                    "`/meow team` - Manage your active team",
                    "`/meow rename` - Rename a cat"
                ],
                "Battle System": [
                    "`/meow patrol` - Go on a patrol",
                    "`/meow challenge` - Challenge another player",
                    "`/meow train` - Train your cats"
                ],
                "Economy": [
                    "`/meow shop` - Visit the shop",
                    "`/meow daily` - Claim daily rewards",
                    "`/meow inventory` - View your items"
                ]
            }
            
            for category, commands_list in categories.items():
                embed.add_field(
                    name=category,
                    value="\n".join(commands_list),
                    inline=False
                )
            
            embed.set_footer(text="Use /meow help <command> for detailed information")
            
        else:
            # Get help for specific command
            cmd = self.bot.get_command(f"meow {command}")
            if not cmd:
                return await ctx.send(f"Command `{command}` not found.")
            
            embed = discord.Embed(
                title=f"Help: {cmd.qualified_name}",
                description=cmd.help or "No description available.",
                color=discord.Color.blue()
            )
            
            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join(cmd.aliases), inline=False)
            
            usage = cmd.usage or cmd.signature
            if usage:
                embed.add_field(name="Usage", value=f"`/meow {command} {usage}`", inline=False)
        
        await ctx.send(embed=embed)

    # More command groups will be added here...

async def setup(bot: Red):
    await bot.add_cog(Meowventure(bot))
