import json
import random
import asyncio
from typing import Optional
from pathlib import Path
from datetime import datetime, timedelta
import time

import discord
from redbot.core import commands, bank, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list
from redbot.core.data_manager import bundled_data_path


class Meowventure(commands.Cog):
    """A fun cat collecting and catnip earning adventure!"""

    # Cat personality traits based on cats.json
    PERSONALITIES = {
        "mysterious": {"dodge": 15, "crit_chance": 10},
        "royal": {"defense": 10, "special_move_chance": 15},
        "genius": {"accuracy": 20, "special_move_chance": 10},
        "adventurous": {"attack": 10, "speed": 10},
        "wise": {"special_move_chance": 20, "defense": 5},
        "creative": {"special_move_chance": 15, "dodge": 10},
        "noble": {"defense": 20, "attack": -5},
        "otherworldly": {"special_move_chance": 20, "dodge": 15},
        "charismatic": {"attack": 15, "accuracy": 10},
        "legendary": {"all_stats": 10},
        "perpetually annoyed": {"attack": 20, "speed": -10},
        "musical genius": {"special_move_chance": 25},
        "cosmic": {"dodge": 20, "special_move_chance": 15},
        "entrepreneur": {"catnip_bonus": 20},
        "eldritch": {"special_move_chance": 25, "fear_chance": 15},
        "yeasty": {"defense": 25, "speed": -15},
        "paranoid": {"dodge": 25, "accuracy": -10},
        "professional": {"accuracy": 15},
        "chaotic": {"speed": 25, "accuracy": -15},
        "competitive": {"attack": 15, "crit_chance": 15},
        "cosmic horror": {"special_move_chance": 30, "fear_chance": 20},
        "cardboard enthusiast": {"defense": 30, "speed": -20},
        "chaotic_memer": {"special_move_chance": 25, "confusion_chance": 20},
        "astronomical": {"dodge": 20, "accuracy": 15},
        "pixelated": {"accuracy": 20, "glitch_chance": 15},
        "caffeinated": {"speed": 30, "accuracy": -10},
        "musical": {"special_move_chance": 20, "stun_chance": 15},
        "honorable": {"attack": 15, "defense": 15},
        "helpful": {"support_bonus": 20},
        "italian": {"attack": 10, "speed": 10},
        "warrior": {"attack": 20, "defense": 10},
        "magical": {"special_move_chance": 25, "magic_bonus": 15},
        "calculated": {"accuracy": 25, "crit_chance": 15},
        "creative": {"special_move_chance": 20},
        "chill": {"defense": 15, "dodge": 15},
        "ethereal": {"dodge": 30, "special_move_chance": 20},
        "eccentric": {"special_move_chance": 30, "confusion_chance": 25}
    }

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=260120231746)
        self.cats_path = bundled_data_path(self) / "cats.json"
        self.items_path = bundled_data_path(self) / "items.json"
        self.abilities_path = bundled_data_path(self) / "abilities.json"
        self.shop_path = bundled_data_path(self) / "shop.json"
        self.battles = {}  # Store ongoing battles
        
        # NPC battle configurations
        self.npc_difficulties = {
            "easy": {
                "level_range": (1, 5),
                "stat_multiplier": 0.8,
                "ability_chance": 0.1,
                "catnip_multiplier": 0.7,
                "xp_multiplier": 1.0
            },
            "medium": {
                "level_range": (5, 15),
                "stat_multiplier": 1.0,
                "ability_chance": 0.15,
                "catnip_multiplier": 1.0,
                "xp_multiplier": 1.2
            },
            "hard": {
                "level_range": (15, 30),
                "stat_multiplier": 1.2,
                "ability_chance": 0.2,
                "catnip_multiplier": 1.5,
                "xp_multiplier": 1.5
            }
        }
        
        default_guild = {
            "catnip_chance": 0.1,  # 10% chance to get catnip from chatting
            "catnip_amount_range": (1, 5),  # Min and max catnip from chatting
            "shop_refresh_time": None,
            "shop_cats": [],  # List of cats currently available in shop
            "tournament_active": False,
            "tournament_participants": [],
            "tournament_rounds": [],
            "item_shop_refresh": None,
            "item_shop_inventory": []
        }
        
        default_user = {
            "cats": [],  # List of cat IDs owned by user
            "catnip": 0,
            "last_daily": None,
            "daily_streak": 0,
            "cat_nicknames": {},  # Dictionary of cat_id: nickname
            "favorite_cat": None,
            "last_pet": {},  # Dictionary of cat_id: last_pet_time
            "cat_happiness": {},  # Dictionary of cat_id: happiness_level (0-100)
            "cat_levels": {},  # Dictionary of cat_id: {level, xp}
            "battles_won": 0,
            "battles_lost": 0,
            "tournament_wins": 0,
            "inventory": {
                "equipment": {},  # cat_id: {slot: item_id}
                "battle_items": {},  # item_id: quantity
                "consumables": {}  # item_id: quantity
            },
            "achievements": {
                "battles_won": 0,
                "tournaments_won": 0,
                "cats_collected": 0,
                "max_level_cats": 0,
                "rare_items_found": 0
            },
            "patrol_team": [],  # List of cat IDs for patrol team (max 2)
            "patrol_cooldowns": {},  # Track when each cat was last on patrol
            "pity_counter": 0
        }
        
        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)
        
        with open(self.cats_path, "r", encoding='utf-8') as f:
            self.available_cats = json.load(f)
        with open(self.items_path, "r", encoding='utf-8') as f:
            self.available_items = json.load(f)
        with open(self.abilities_path, "r", encoding='utf-8') as f:
            self.available_abilities = json.load(f)
        with open(self.shop_path, "r", encoding='utf-8') as f:
            self.shop_data = json.load(f)
        
        self.cat_images = {
            cat["id"]: f"{cat['id']}_cat.png" 
            for cat in self.available_cats["cats"]
        }

        # Load status effects from abilities.json
        with open(self.abilities_path, "r", encoding='utf-8') as f:
            abilities_data = json.load(f)
            self.status_effects = abilities_data["status_effects"]

    @commands.group(name="meow")
    async def meow(self, ctx: commands.Context):
        """Main command group for Meowventure"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()
    
    @meow.command(name="profile")
    async def show_profile(self, ctx: commands.Context, member: discord.Member = None):
        """Show your or another user's cat profile"""
        target = member or ctx.author
        user_data = await self.config.user(target).all()
        
        embed = discord.Embed(
            title=f"🐱 {target.display_name}'s Cat Profile",
            color=discord.Color.blue()
        )
        
        # Battle stats
        embed.add_field(
            name="Battle Stats",
            value=f"Battles Won: {user_data['battles_won']}\n"
                  f"Battles Lost: {user_data['battles_lost']}\n"
                  f"Tournament Wins: {user_data['tournament_wins']}\n"
                  f"Win Rate: {(user_data['battles_won'] / (user_data['battles_won'] + user_data['battles_lost']) * 100):.1f}% if user_data['battles_won'] + user_data['battles_lost'] > 0 else '0.0%'",
            inline=False
        )
        
        # Cat collection
        total_cats = len(self.available_cats["cats"])
        owned_cats = len(user_data["cats"])
        embed.add_field(
            name="Cat Collection",
            value=f"Cats Owned: {owned_cats}/{total_cats}\n"
                  f"Collection Rate: {(owned_cats/total_cats*100):.1f}%",
            inline=False
        )
        
        # Favorite cat stats
        if user_data["favorite_cat"]:
            fav_cat = next(c for c in self.available_cats["cats"] if c["id"] == user_data["favorite_cat"])
            fav_cat_level = user_data.get("cat_levels", {}).get(user_data["favorite_cat"], {"level": 1})["level"]
            embed.add_field(
                name="Favorite Cat",
                value=f"Name: {fav_cat['name']}\n"
                      f"Level: {fav_cat_level}\n"
                      f"Happiness: {user_data['cat_happiness'].get(user_data['favorite_cat'], 50)}%",
                inline=False
            )
        
        # Achievements
        achievements = []
        if user_data["battles_won"] >= 100:
            achievements.append("🏆 Battle Master")
        if user_data["tournament_wins"] >= 10:
            achievements.append("👑 Tournament Champion")
        if owned_cats >= total_cats * 0.8:
            achievements.append("📚 Cat Collector")
        if any(level_data["level"] >= 20 for level_data in user_data.get("cat_levels", {}).values()):
            achievements.append("⭐ Cat Trainer")
        
        if achievements:
            embed.add_field(
                name="Achievements",
                value="\n".join(achievements),
                inline=False
            )
        
        # Economy
        embed.add_field(
            name="Economy",
            value=f"Catnip: {user_data['catnip']}\n"
                  f"Items Owned: {sum(len(category) for category in user_data['inventory'].values())}",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @meow.command(name="cats")
    async def meow_cats(self, ctx: commands.Context):
        """View your cat collection"""
        data = await self.config.user(ctx.author).all()
        
        if not data["cats"]:
            await ctx.send("You don't have any cats yet! Use `meow shop` to adopt one.")
            return
        
        embed = discord.Embed(
            title=f"🐱 {ctx.author.display_name}'s Cats",
            color=discord.Color.blue()
        )
        
        for cat_id in data["cats"]:
            cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
            if cat_data:
                nickname = data["cat_nicknames"].get(cat_id, cat_data["name"])
                happiness = data["cat_happiness"].get(cat_id, 50)
                mood = self.get_mood_emoji(happiness)
                level = data.get("cat_levels", {}).get(cat_id, {"level": 1})["level"]
                
                embed.add_field(
                    name=f"{mood} {nickname} (Level {level})",
                    value=f"Type: {cat_data['name']}\n"
                          f"Rarity: {cat_data['rarity'].title()}\n"
                          f"Happiness: {happiness}/100",
                    inline=True
                )
        
        await ctx.send(embed=embed)
    
    @meow.command(name="shop")
    async def meow_shop(self, ctx: commands.Context):
        """Browse cats available for adoption"""
        guild_data = await self.config.guild(ctx.guild).all()
        current_time = ctx.message.created_at.timestamp()
        
        # Refresh shop if needed
        if not guild_data["shop_refresh_time"] or \
           current_time - guild_data["shop_refresh_time"] > 86400:  # 24 hours
            available_cats = random.sample(self.available_cats["cats"], k=4)
            async with self.config.guild(ctx.guild).all() as guild_data:
                guild_data["shop_cats"] = [c["id"] for c in available_cats]
                guild_data["shop_refresh_time"] = current_time
        else:
            available_cats = [
                c for c in self.available_cats["cats"]
                if c["id"] in guild_data["shop_cats"]
            ]
        
        embed = discord.Embed(
            title="🏪 Cat Adoption Shop",
            description="Use `meow adopt <cat_id>` to adopt a cat!",
            color=discord.Color.gold()
        )
        
        for cat in available_cats:
            embed.add_field(
                name=f"{cat['name']} (ID: {cat['id']})",
                value=f"Price: 🌿 {cat['price']}\n"
                      f"Rarity: {cat['rarity'].title()}\n"
                      f"Description: {cat['description']}",
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @meow.command(name="adopt")
    async def meow_adopt(self, ctx: commands.Context, cat_id: str):
        """Adopt a cat from the shop"""
        guild_data = await self.config.guild(ctx.guild).all()
        user_data = await self.config.user(ctx.author).all()
        
        if cat_id not in guild_data["shop_cats"]:
            await ctx.send("That cat isn't available in the shop right now!")
            return
        
        cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
        if not cat_data:
            await ctx.send("Invalid cat ID!")
            return
        
        if cat_id in user_data["cats"]:
            await ctx.send("You already have this cat!")
            return
        
        if user_data["catnip"] < cat_data["price"]:
            await ctx.send(f"You need 🌿 {cat_data['price']} catnip to adopt this cat!")
            return
        
        async with self.config.user(ctx.author).all() as user_data:
            user_data["catnip"] -= cat_data["price"]
            user_data["cats"].append(cat_id)
            user_data["cat_happiness"][cat_id] = 50  # Starting happiness
            user_data["cat_levels"][cat_id] = {"level": 1, "xp": 0}  # Starting level
        
        await ctx.send(
            f"🎉 Congratulations! You've adopted {cat_data['name']}! "
            f"Use `meow nickname {cat_id} <nickname>` to give them a special name!"
        )
    
    @meow.command(name="nickname")
    async def meow_nickname(self, ctx: commands.Context, cat_id: str, *, nickname: str):
        """Give a nickname to your cat"""
        user_data = await self.config.user(ctx.author).all()
        
        if cat_id not in user_data["cats"]:
            await ctx.send("You don't own this cat!")
            return
        
        if len(nickname) > 32:
            await ctx.send("Nickname must be 32 characters or less!")
            return
        
        async with self.config.user(ctx.author).all() as user_data:
            user_data["cat_nicknames"][cat_id] = nickname
        
        await ctx.send(f"Your cat's nickname has been set to: {nickname}")
    
    @meow.command(name="pet")
    async def meow_pet(self, ctx: commands.Context, cat_id: str):
        """Pet one of your cats to make them happy"""
        user_data = await self.config.user(ctx.author).all()
        
        if cat_id not in user_data["cats"]:
            await ctx.send("You don't own this cat!")
            return
        
        last_pet = user_data["last_pet"].get(cat_id, 0)
        if ctx.message.created_at.timestamp() - last_pet < 3600:  # 1 hour cooldown
            await ctx.send("This cat needs some alone time! Try again later.")
            return
        
        happiness_increase = random.randint(5, 15)
        current_happiness = user_data["cat_happiness"].get(cat_id, 50)
        new_happiness = min(100, current_happiness + happiness_increase)
        
        async with self.config.user(ctx.author).all() as user_data:
            user_data["last_pet"][cat_id] = ctx.message.created_at.timestamp()
            user_data["cat_happiness"][cat_id] = new_happiness
        
        cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
        nickname = user_data["cat_nicknames"].get(cat_id, cat_data["name"])
        
        responses = [
            f"{nickname} purrs contentedly! (+{happiness_increase} happiness)",
            f"{nickname} rubs against your leg! (+{happiness_increase} happiness)",
            f"{nickname} rolls over for belly rubs! (+{happiness_increase} happiness)",
            f"{nickname} looks at you with adorable eyes! (+{happiness_increase} happiness)"
        ]
        
        await ctx.send(random.choice(responses))
    
    @meow.command(name="favorite")
    async def meow_favorite(self, ctx: commands.Context, cat_id: str):
        """Set your favorite cat"""
        user_data = await self.config.user(ctx.author).all()
        
        if cat_id not in user_data["cats"]:
            await ctx.send("You don't own this cat!")
            return
        
        async with self.config.user(ctx.author).all() as user_data:
            user_data["favorite_cat"] = cat_id
        
        cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
        nickname = user_data["cat_nicknames"].get(cat_id, cat_data["name"])
        
        await ctx.send(f"💝 {nickname} is now your favorite cat!")
    
    @meow.command(name="daily")
    async def claim_daily(self, ctx: commands.Context):
        """Claim your daily reward"""
        user_data = await self.config.user(ctx.author).all()
        current_time = datetime.datetime.now()
        
        # Check if already claimed today
        if user_data["last_daily"]:
            last_daily = datetime.datetime.fromisoformat(user_data["last_daily"])
            if current_time.date() == last_daily.date():
                time_until_next = datetime.datetime.combine(current_time.date() + datetime.timedelta(days=1), 
                                                         datetime.time.min)
                time_left = time_until_next - current_time
                await ctx.send(f"You've already claimed your daily reward! Come back in {time_left.hours}h {time_left.minutes}m")
                return
            
            # Check if streak continues
            if current_time.date() == last_daily.date() + datetime.timedelta(days=1):
                user_data["daily_streak"] += 1
            else:
                user_data["daily_streak"] = 1
        else:
            user_data["daily_streak"] = 1
        
        # Get rewards for current streak
        streak = str(user_data["daily_streak"])
        if streak in self.shop_data["daily_rewards"]["consecutive_days"]:
            rewards = self.shop_data["daily_rewards"]["consecutive_days"][streak]
        else:
            rewards = self.shop_data["daily_rewards"]["consecutive_days"]["1"]
        
        # Apply rewards
        user_data["catnip"] += rewards["catnip"]
        if "items" in rewards:
            for item_id in rewards["items"]:
                if item_id not in user_data["inventory"]["consumables"]:
                    user_data["inventory"]["consumables"][item_id] = 0
                user_data["inventory"]["consumables"][item_id] += 1
        
        # Update last claim time
        user_data["last_daily"] = current_time.isoformat()
        
        await self.config.user(ctx.author).set(user_data)
        
        # Create reward message
        embed = discord.Embed(
            title="🎁 Daily Rewards!",
            description=f"Day {user_data['daily_streak']} Streak!",
            color=discord.Color.green()
        )
        
        rewards_text = f"**{rewards['catnip']}** catnip\n"
        if "items" in rewards:
            for item_id in rewards["items"]:
                item = self.shop_data["regular_items"].get(item_id) or \
                       self.shop_data["daily_rotation"]["possible_items"].get(item_id)
                rewards_text += f"**{item['name']}** x1\n"
        
        embed.add_field(name="Rewards", value=rewards_text)
        embed.set_footer(text=f"Come back tomorrow to continue your streak!")
        
        await ctx.send(embed=embed)

    @meow.group(name="shop")
    async def meow_shop(self, ctx: commands.Context):
        """Shop commands for Meowventure"""
        pass

    @meow_shop.command(name="view")
    async def shop_view(self, ctx: commands.Context):
        """View the shop's current inventory"""
        embed = discord.Embed(
            title="🏪 Meowventure Shop",
            description="Welcome to the shop! Here's what we have in stock:",
            color=discord.Color.gold()
        )
        
        # Regular items
        regular_items = ""
        for item_id, item in self.shop_data["regular_items"].items():
            regular_items += f"**{item['name']}** - {item['price']} catnip\n"
            regular_items += f"*{item['description']}*\n\n"
        
        embed.add_field(
            name="📦 Regular Items",
            value=regular_items or "No items available",
            inline=False
        )
        
        # Daily rotation items
        rotation_items = await self._get_daily_rotation(ctx.guild.id)
        daily_items = ""
        for item in rotation_items:
            daily_items += f"**{item['name']}** - {item['price']} catnip\n"
            daily_items += f"*{item['description']}* ({item['rarity'].upper()})\n\n"
        
        embed.add_field(
            name="✨ Daily Special Items",
            value=daily_items or "No special items today",
            inline=False
        )
        
        # Show user's catnip
        user_data = await self.config.user(ctx.author).all()
        embed.set_footer(text=f"Your catnip: {user_data['catnip']}")
        
        await ctx.send(embed=embed)

    @meow_shop.command(name="buy")
    async def shop_buy(self, ctx: commands.Context, item_id: str):
        """Buy an item from the shop"""
        user_data = await self.config.user(ctx.author).all()
        
        # Find item in regular items
        item = self.shop_data["regular_items"].get(item_id)
        if not item:
            # Check daily rotation
            rotation_items = await self._get_daily_rotation(ctx.guild.id)
            item = next((i for i in rotation_items if i["id"] == item_id), None)
        
        if not item:
            await ctx.send("That item doesn't exist or isn't available!")
            return
        
        # Check if user has enough catnip
        if user_data["catnip"] < item["price"]:
            await ctx.send("You don't have enough catnip to buy this item!")
            return
        
        # Add item to inventory based on category
        if item["category"] == "consumable":
            if "consumables" not in user_data["inventory"]:
                user_data["inventory"]["consumables"] = {}
            if item_id not in user_data["inventory"]["consumables"]:
                user_data["inventory"]["consumables"][item_id] = 0
            user_data["inventory"]["consumables"][item_id] += 1
        else:
            if "battle_items" not in user_data["inventory"]:
                user_data["inventory"]["battle_items"] = {}
            if item_id not in user_data["inventory"]["battle_items"]:
                user_data["inventory"]["battle_items"][item_id] = 0
            user_data["inventory"]["battle_items"][item_id] += 1
        
        # Deduct catnip
        user_data["catnip"] -= item["price"]
        
        await self.config.user(ctx.author).set(user_data)
        await ctx.send(f"You bought a {item['name']}!")

    async def _get_daily_rotation(self, guild_id: int) -> list:
        """Get the current daily rotation of special items"""
        # Use guild ID and current date as seed for consistent daily rotation
        current_date = datetime.datetime.now().date()
        seed = f"{guild_id}{current_date.isoformat()}"
        random.seed(seed)
        
        # Select random items
        possible_items = list(self.shop_data["daily_rotation"]["possible_items"].items())
        num_items = min(self.shop_data["daily_rotation"]["slots"], len(possible_items))
        selected_items = random.sample(possible_items, num_items)
        
        # Format items
        rotation_items = []
        for item_id, item in selected_items:
            item_copy = item.copy()
            item_copy["id"] = item_id
            rotation_items.append(item_copy)
        
        return rotation_items

    @meow.group(name="item")
    async def meow_item(self, ctx: commands.Context):
        """Item commands for Meowventure"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @meow_item.command(name="shop")
    async def item_shop(self, ctx: commands.Context, category: str = None):
        """Browse the item shop"""
        categories = ["equipment", "battle_items"]
        if category and category.lower() not in categories:
            await ctx.send(f"Invalid category! Choose from: {', '.join(categories)}")
            return

        guild_data = await self.config.guild(ctx.guild).all()
        current_time = ctx.message.created_at.timestamp()

        # Refresh shop if needed
        if not guild_data["item_shop_refresh"] or \
           current_time - guild_data["item_shop_refresh"] > 86400:  # 24 hours
            async with self.config.guild(ctx.guild).all() as g_data:
                g_data["item_shop_inventory"] = self._generate_shop_inventory()
                g_data["item_shop_refresh"] = current_time

        embed = discord.Embed(
            title="🏪 Item Shop",
            description="Use `meow item buy <item_id>` to purchase items!",
            color=discord.Color.gold()
        )

        for item_type, items in self.available_items.items():
            if category and item_type != category:
                continue
            
            for item_id, item in items.items():
                if item_id in guild_data["item_shop_inventory"]:
                    embed.add_field(
                        name=f"{item['name']} (ID: {item_id})",
                        value=f"Price: 🌿 {item['price']}\n"
                              f"Rarity: {item['rarity'].title()}\n"
                              f"Description: {item['description']}",
                        inline=False
                    )

        await ctx.send(embed=embed)

    @meow_item.command(name="buy")
    async def item_buy(self, ctx: commands.Context, item_id: str):
        """Buy an item from the shop"""
        guild_data = await self.config.guild(ctx.guild).all()
        if item_id not in guild_data["item_shop_inventory"]:
            await ctx.send("That item isn't available in the shop right now!")
            return

        # Find item in available items
        item = None
        item_type = None
        for itype, items in self.available_items.items():
            if item_id in items:
                item = items[item_id]
                item_type = itype
                break

        if not item:
            await ctx.send("Invalid item ID!")
            return

        user_data = await self.config.user(ctx.author).all()
        if user_data["catnip"] < item["price"]:
            await ctx.send(f"You need 🌿 {item['price']} catnip to buy this item!")
            return

        async with self.config.user(ctx.author).all() as u_data:
            u_data["catnip"] -= item["price"]
            if item_type == "equipment":
                if item_id not in u_data["inventory"]["equipment"]:
                    u_data["inventory"]["equipment"][item_id] = 1
                else:
                    u_data["inventory"]["equipment"][item_id] += 1
            else:
                if item_id not in u_data["inventory"]["battle_items"]:
                    u_data["inventory"]["battle_items"][item_id] = 1
                else:
                    u_data["inventory"]["battle_items"][item_id] += 1

        await ctx.send(f"You bought {item['name']}!")

    @meow_item.command(name="inventory")
    async def item_inventory(self, ctx: commands.Context):
        """View your item inventory"""
        user_data = await self.config.user(ctx.author).all()
        
        embed = discord.Embed(
            title=f"🎒 {ctx.author.display_name}'s Inventory",
            color=discord.Color.blue()
        )

        # Equipment
        equipment_text = ""
        for item_id, quantity in user_data["inventory"]["equipment"].items():
            for category, items in self.available_items["equipment"].items():
                if item_id in items:
                    item = items[item_id]
                    equipment_text += f"{item['name']} x{quantity}\n"
                    break
        
        embed.add_field(
            name="Equipment",
            value=equipment_text or "No equipment",
            inline=False
        )

        # Battle Items
        battle_items_text = ""
        for item_id, quantity in user_data["inventory"]["battle_items"].items():
            for category, items in self.available_items["battle_items"].items():
                if item_id in items:
                    item = items[item_id]
                    battle_items_text += f"{item['name']} x{quantity}\n"
                    break

        embed.add_field(
            name="Battle Items",
            value=battle_items_text or "No battle items",
            inline=False
        )

        await ctx.send(embed=embed)

    @meow_item.command(name="equip")
    async def item_equip(self, ctx: commands.Context, cat_id: str, item_id: str):
        """Equip an item to a cat"""
        user_data = await self.config.user(ctx.author).all()
        
        if cat_id not in user_data["cats"]:
            await ctx.send("You don't own this cat!")
            return

        if item_id not in user_data["inventory"]["equipment"]:
            await ctx.send("You don't own this item!")
            return

        # Find item in equipment
        item = None
        for category, items in self.available_items["equipment"].items():
            if item_id in items:
                item = items[item_id]
                break

        if not item:
            await ctx.send("Invalid equipment item!")
            return

        async with self.config.user(ctx.author).all() as u_data:
            if cat_id not in u_data["inventory"]["equipment"]:
                u_data["inventory"]["equipment"][cat_id] = {}
            
            # Remove any existing item in the same slot
            for equipped_item_id in u_data["inventory"]["equipment"][cat_id].values():
                if equipped_item_id == item_id:
                    await ctx.send("This item is already equipped!")
                    return

            u_data["inventory"]["equipment"][cat_id][item["slot"]] = item_id

        await ctx.send(f"Equipped {item['name']} to your cat!")

    @meow_item.command(name="unequip")
    async def item_unequip(self, ctx: commands.Context, cat_id: str, slot: str):
        """Unequip an item from a cat"""
        user_data = await self.config.user(ctx.author).all()
        
        if cat_id not in user_data["cats"]:
            await ctx.send("You don't own this cat!")
            return

        if cat_id not in user_data["inventory"]["equipment"] or \
           slot not in user_data["inventory"]["equipment"][cat_id]:
            await ctx.send("No item equipped in that slot!")
            return

        async with self.config.user(ctx.author).all() as u_data:
            item_id = u_data["inventory"]["equipment"][cat_id][slot]
            del u_data["inventory"]["equipment"][cat_id][slot]

        # Find item name
        item_name = "the item"
        for category, items in self.available_items["equipment"].items():
            if item_id in items:
                item_name = items[item_id]["name"]
                break

        await ctx.send(f"Unequipped {item_name} from your cat!")

    def _generate_shop_inventory(self):
        """Generate a random selection of items for the shop"""
        inventory = []
        
        # Add some equipment
        for category in self.available_items["equipment"]:
            items = list(self.available_items["equipment"][category].keys())
            inventory.extend(random.sample(items, min(2, len(items))))
        
        # Add some battle items
        for category in self.available_items["battle_items"]:
            items = list(self.available_items["battle_items"][category].keys())
            inventory.extend(random.sample(items, min(2, len(items))))
        
        return inventory

    async def _calculate_cat_stats(self, cat_id: str, user_data: dict) -> dict:
        """Calculate a cat's stats including level bonuses and equipment"""
        cat = next(c for c in self.available_cats["cats"] if c["id"] == cat_id)
        base_stats = cat["base_stats"].copy()
        
        # Rebalanced level scaling
        if cat_id in user_data.get("cat_levels", {}):
            level_data = user_data["cat_levels"][cat_id]
            level = level_data["level"]
            # Reduced level multiplier for better balance
            level_multiplier = 1 + (level * 0.03)  # Changed from 0.05 to 0.03
            for stat in base_stats:
                base_stats[stat] = int(base_stats[stat] * level_multiplier)
        
        # Rebalanced equipment bonuses
        if cat_id in user_data["inventory"]["equipment"]:
            for slot, item_id in user_data["inventory"]["equipment"][cat_id].items():
                item = next(i for i in self.available_items["items"] if i["id"] == item_id)
                if "stat_boosts" in item:
                    for stat, boost in item["stat_boosts"].items():
                        if stat in base_stats:
                            # Cap equipment bonuses
                            max_boost = {
                                "attack": 25,
                                "defense": 30,
                                "speed": 20,
                                "hp": 40
                            }.get(stat, 20)
                            base_stats[stat] += min(boost, max_boost)
        
        # Rebalanced happiness bonus (reduced maximum impact)
        happiness = user_data.get("cat_happiness", {}).get(cat_id, 50)
        happiness_multiplier = 1 + (happiness * 0.0005)  # Changed from 0.001 to 0.0005
        for stat in base_stats:
            base_stats[stat] = int(base_stats[stat] * happiness_multiplier)
        
        return base_stats

    @meow.group(name="battle")
    async def meow_battle(self, ctx: commands.Context):
        """Battle commands for Meowventure"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()
    
    @meow_battle.command(name="challenge")
    async def battle_challenge(self, ctx: commands.Context, opponent: discord.Member, cat_id: str):
        """Challenge another player to a cat battle"""
        if opponent.bot:
            await ctx.send("You can't challenge a bot!")
            return
        
        if opponent == ctx.author:
            await ctx.send("You can't challenge yourself!")
            return
        
        challenger_data = await self.config.user(ctx.author).all()
        if cat_id not in challenger_data["cats"]:
            await ctx.send("You don't own this cat!")
            return
        
        battle_id = f"{ctx.author.id}-{opponent.id}"
        if battle_id in self.battles:
            await ctx.send("You already have a pending battle!")
            return
        
        cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
        self.battles[battle_id] = {
            "challenger": ctx.author,
            "opponent": opponent,
            "challenger_cat": cat_id,
            "opponent_cat": None,
            "status": "pending"
        }
        
        embed = discord.Embed(
            title="🐱 Cat Battle Challenge!",
            description=f"{ctx.author.mention} challenges you with their {cat_data['name']}!",
            color=discord.Color.red()
        )
        embed.add_field(
            name="To Accept",
            value=f"Use `meow battle accept {ctx.author.id} <your_cat_id>`"
        )
        embed.add_field(
            name="To Decline",
            value=f"Use `meow battle decline {ctx.author.id}`"
        )
        
        await ctx.send(opponent.mention, embed=embed)
    
    @meow_battle.command(name="accept")
    async def battle_accept(self, ctx: commands.Context, challenger_id: int, cat_id: str):
        """Accept a battle challenge"""
        battle_id = f"{challenger_id}-{ctx.author.id}"
        if battle_id not in self.battles:
            await ctx.send("No pending battle found!")
            return
        
        battle = self.battles[battle_id]
        if battle["status"] != "pending":
            await ctx.send("This battle has already started!")
            return
        
        defender_data = await self.config.user(ctx.author).all()
        if cat_id not in defender_data["cats"]:
            await ctx.send("You don't own this cat!")
            return
        
        battle["opponent_cat"] = cat_id
        battle["status"] = "active"
        
        await self._do_battle(ctx, battle_id)
    
    @meow_battle.command(name="decline")
    async def battle_decline(self, ctx: commands.Context, challenger_id: int):
        """Decline a battle challenge"""
        battle_id = f"{challenger_id}-{ctx.author.id}"
        if battle_id not in self.battles:
            await ctx.send("No pending battle found!")
            return
        
        battle = self.battles[battle_id]
        if battle["status"] != "pending":
            await ctx.send("This battle has already started!")
            return
        
        del self.battles[battle_id]
        await ctx.send(f"{ctx.author.mention} has declined the battle challenge!")
    
    @meow_battle.command(name="npc")
    async def battle_npc(self, ctx: commands.Context, cat_id: str, difficulty: str = "medium"):
        """Battle against an NPC cat
        
        Difficulty options: easy, medium, hard"""
        if difficulty not in self.npc_difficulties:
            await ctx.send("Invalid difficulty! Choose from: easy, medium, hard")
            return
        
        user_data = await self.config.user(ctx.author).all()
        if cat_id not in user_data["cats"]:
            await ctx.send("You don't own this cat!")
            return
        
        # Generate NPC cat
        npc_cat = await self._generate_npc_cat(difficulty)
        
        battle_id = f"{ctx.author.id}-npc-{int(time.time())}"
        self.battles[battle_id] = {
            "challenger": ctx.author,
            "opponent": None,  # NPC opponent
            "challenger_cat": cat_id,
            "opponent_cat": npc_cat["id"],
            "status": "active",
            "is_npc": True,
            "difficulty": difficulty,
            "npc_data": npc_cat
        }
        
        # Start battle immediately
        await self._do_battle(ctx, battle_id)

    @meow_battle.group(name="team")
    async def patrol_team(self, ctx: commands.Context):
        """Manage your patrol team"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @patrol_team.command(name="set")
    async def team_set(self, ctx: commands.Context, *cat_ids: str):
        """Set your patrol team (up to 2 cats)
        
        Example:
        [p]meow battle team set cat_1 cat_2"""
        if not cat_ids:
            await ctx.send("Please provide at least one cat ID!")
            return
            
        if len(cat_ids) > 2:  # Changed from 3 to 2
            await ctx.send("You can only have up to 2 cats in your patrol team!")
            return
            
        user_data = await self.config.user(ctx.author).all()
        
        # Verify all cats exist and are owned by the user
        invalid_cats = [cat_id for cat_id in cat_ids if cat_id not in user_data["cats"]]
        if invalid_cats:
            await ctx.send(f"You don't own the following cats: {', '.join(invalid_cats)}")
            return
            
        # Set the patrol team
        async with self.config.user(ctx.author).all() as u_data:
            u_data["patrol_team"] = list(cat_ids)
            
        # Get cat names for confirmation message
        cat_names = []
        for cat_id in cat_ids:
            cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
            if cat_data:
                cat_names.append(f"{cat_data['emoji']} {cat_data['name']}")
        
        embed = discord.Embed(
            title="🐾 Patrol Team Set!",
            description=f"Your new patrol partners:\n" + "\n".join(cat_names),
            color=discord.Color.green()
        )
        
        # Add tip if only one cat is set
        if len(cat_ids) == 1:
            embed.add_field(
                name="💡 Tip",
                value="You can add a second cat to your patrol team for better chances of success!",
                inline=False
            )
            
        await ctx.send(embed=embed)

    @patrol_team.command(name="show")
    async def team_show(self, ctx: commands.Context):
        """Show your current patrol team"""
        user_data = await self.config.user(ctx.author).all()
        team = user_data.get("patrol_team", [])
        
        if not team:
            await ctx.send("You haven't set up a patrol team yet! Use `meow battle team set` to create one.")
            return
            
        embed = discord.Embed(
            title="🐾 Your Patrol Partners",
            color=discord.Color.blue()
        )
        
        for cat_id in team:
            cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
            if cat_data:
                level = user_data.get("cat_levels", {}).get(cat_id, {"level": 1})["level"]
                happiness = user_data.get("cat_happiness", {}).get(cat_id, 50)
                cooldown = user_data.get("patrol_cooldowns", {}).get(cat_id, 0)
                
                # Check if cat is on cooldown
                current_time = int(time.time())
                cooldown_remaining = max(0, cooldown - current_time)
                status = "Ready for patrol!" if cooldown_remaining <= 0 else f"Resting for {cooldown_remaining//60} minutes"
                
                embed.add_field(
                    name=f"{cat_data['emoji']} {cat_data['name']} (Level {level})",
                    value=f"Happiness: {self.get_mood_emoji(happiness)} {happiness}%\n"
                          f"Status: {status}",
                    inline=False
                )
        
        # Add tip if team isn't full
        if len(team) < 2:
            embed.add_field(
                name="💡 Tip",
                value="You can have up to 2 cats in your patrol team!",
                inline=False
            )
        
        await ctx.send(embed=embed)

    @patrol_team.command(name="remove")
    async def team_remove(self, ctx: commands.Context, cat_id: str):
        """Remove a cat from your patrol team"""
        async with self.config.user(ctx.author).all() as user_data:
            if cat_id not in user_data.get("patrol_team", []):
                await ctx.send("This cat isn't in your patrol team!")
                return
                
            user_data["patrol_team"].remove(cat_id)
            
        cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
        if cat_data:
            await ctx.send(f"{cat_data['emoji']} {cat_data['name']} has been removed from your patrol team!")

    @meow_battle.command(name="patrol")
    async def battle_patrol(self, ctx: commands.Context):
        """Send your patrol team to explore and battle neighborhood cats!"""
        user_data = await self.config.user(ctx.author).all()
        team = user_data.get("patrol_team", [])
        
        if not team:
            await ctx.send("You need to set up a patrol team first! Use `meow battle team set` to create one.")
            return
            
        # Check for available cats (not on cooldown)
        current_time = int(time.time())
        available_cats = []
        cooldown_cats = []
        
        for cat_id in team:
            cooldown = user_data.get("patrol_cooldowns", {}).get(cat_id, 0)
            if current_time >= cooldown:
                cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
                if cat_data:
                    available_cats.append((cat_id, cat_data))
            else:
                cooldown_cats.append((cat_id, (cooldown - current_time) // 60))
        
        if not available_cats:
            cooldown_msg = "\n".join([f"- {next((c['name'] for c in self.available_cats['cats'] if c['id'] == cat_id), 'Unknown')}: {mins} minutes" 
                                    for cat_id, mins in cooldown_cats])
            await ctx.send(f"Your patrol cats are resting!\nRemaining cooldowns:\n{cooldown_msg}")
            return
            
        # Select a random available cat for the patrol
        patrol_cat_id, patrol_cat = random.choice(available_cats)
        
        # Get cat's level for encounter scaling
        cat_level_data = user_data.get("cat_levels", {}).get(patrol_cat_id, {"level": 1})
        cat_level = cat_level_data["level"]
        
        # Set cooldown for the selected cat (20 minutes instead of 30, since we have smaller teams)
        async with self.config.user(ctx.author).all() as u_data:
            if "patrol_cooldowns" not in u_data:
                u_data["patrol_cooldowns"] = {}
            u_data["patrol_cooldowns"][patrol_cat_id] = current_time + (20 * 60)  # Changed from 30 to 20 minutes
        
        # Create initial patrol message
        embed = discord.Embed(
            title="🐾 Patrol Time!",
            description=f"{patrol_cat['name']} has gone out to patrol their territory...",
            color=discord.Color.blue()
        )
        patrol_msg = await ctx.send(embed=embed)
        await asyncio.sleep(2)  # Build suspense
        
        # Determine encounter type based on level and randomness
        encounter_roll = random.random()
        time_of_day = datetime.datetime.now().hour
        is_night = 20 <= time_of_day or time_of_day <= 5  # Night encounters are tougher
        
        if cat_level < 5:
            # Low level encounters
            if encounter_roll < 0.85:  # 85% chance
                difficulty = "easy"
                encounter_type = random.choice([
                    "a curious stray kitten",
                    "a playful house cat",
                    "a friendly neighborhood cat"
                ])
            else:  # 15% chance
                difficulty = "medium"
                encounter_type = random.choice([
                    "an experienced alley cat",
                    "a territorial tabby",
                    "a street-smart feline"
                ])
        elif cat_level < 15:
            # Mid level encounters
            if encounter_roll < 0.6:  # 60% chance
                difficulty = "easy" if not is_night else "medium"
                encounter_type = random.choice([
                    "a friendly rival",
                    "a neighborhood champion",
                    "a skilled hunter"
                ])
            elif encounter_roll < 0.9:  # 30% chance
                difficulty = "medium"
                encounter_type = random.choice([
                    "a mysterious wanderer",
                    "a territorial defender",
                    "a seasoned street fighter"
                ])
            else:  # 10% chance
                difficulty = "hard"
                encounter_type = random.choice([
                    "a shadow stalker",
                    "a legendary alley king",
                    "a mysterious guardian"
                ])
        else:
            # High level encounters
            if encounter_roll < 0.4:  # 40% chance
                difficulty = "medium"
                encounter_type = random.choice([
                    "a respected street veteran",
                    "a skilled territory defender",
                    "an experienced challenger"
                ])
            elif encounter_roll < 0.8:  # 40% chance
                difficulty = "hard"
                encounter_type = random.choice([
                    "a notorious alley boss",
                    "a legendary street king",
                    "a mysterious shadow master"
                ])
            else:  # 20% chance
                difficulty = "hard"
                encounter_type = random.choice([
                    "the legendary neighborhood champion",
                    "a mythical territory guardian",
                    "the shadow lord of the alleys"
                ])
        
        # Add time of day flavor
        time_flavor = "in the dark alley" if is_night else "in the neighborhood"
        
        # Update encounter message
        embed.description = f"While patrolling {time_flavor}, {patrol_cat['name']} encountered {encounter_type}!"
        if is_night:
            embed.description += "\n*The night makes the encounter more challenging...*"
        await patrol_msg.edit(embed=embed)
        
        # Generate NPC cat
        npc_cat = await self._generate_npc_cat(difficulty)
        npc_cat["name"] = f"{encounter_type.title()}"
        
        battle_id = f"{ctx.author.id}-patrol-{int(time.time())}"
        self.battles[battle_id] = {
            "challenger": ctx.author,
            "opponent": None,  # NPC opponent
            "challenger_cat": cat_id,
            "opponent_cat": npc_cat["id"],
            "status": "active",
            "is_npc": True,
            "difficulty": difficulty,
            "npc_data": npc_cat,
            "encounter_type": encounter_type,
            "is_night": is_night
        }
        
        await asyncio.sleep(1)  # Brief pause before battle
        await self._do_battle(ctx, battle_id)

    async def _select_patrol_cat(self, user_data: dict) -> Optional[dict]:
        """Select the most appropriate cat for patrol based on various factors"""
        available_cats = []
        
        for cat_id in user_data.get("cats", {}):
            cat_data = next((c for c in self.available_cats["cats"] if c["id"] == cat_id), None)
            if not cat_data:
                continue
                
            # Get cat's stats and condition
            happiness = user_data.get("cat_happiness", {}).get(cat_id, 50)
            level_data = user_data.get("cat_levels", {}).get(cat_id, {"level": 1, "xp": 0})
            
            # Calculate patrol readiness score
            score = 0
            score += happiness * 0.5  # Happier cats are more likely to patrol
            score += level_data["level"] * 2  # Higher level cats are more experienced
            score += random.randint(1, 20)  # Add some randomness
            
            # Cats with very low happiness are less likely to patrol
            if happiness < 20:
                score *= 0.5
            
            available_cats.append((cat_data, score))
        
        if not available_cats:
            return None
            
        # Sort by score and pick from top 3 (if available)
        available_cats.sort(key=lambda x: x[1], reverse=True)
        selection_pool = available_cats[:min(3, len(available_cats))]
        return random.choice(selection_pool)[0]

    async def _generate_npc_cat(self, difficulty: str) -> dict:
        """Generate a balanced NPC cat based on difficulty"""
        diff_config = self.npc_difficulties[difficulty]
        
        # Select a random cat as base
        base_cat = random.choice([c for c in self.available_cats["cats"] 
                                if c["rarity"] in ["common", "uncommon", "rare"]])
        
        # Create NPC version with adjusted stats
        npc_cat = base_cat.copy()
        npc_cat["id"] = f"npc_{base_cat['id']}_{int(time.time())}"
        npc_cat["name"] = f"NPC {base_cat['name']}"
        
        # Adjust stats based on difficulty
        for stat in npc_cat["stats"]:
            base_value = npc_cat["stats"][stat]
            level_bonus = random.randint(*diff_config["level_range"]) * 3
            difficulty_bonus = base_value * (diff_config["stat_multiplier"] - 1)
            npc_cat["stats"][stat] = int(base_value + level_bonus + difficulty_bonus)
        
        # Add some random abilities based on difficulty
        available_abilities = [ability for ability in self.available_abilities["abilities"]]
        num_abilities = {
            "easy": 2,
            "medium": 3,
            "hard": 4
        }[difficulty]
        npc_cat["abilities"] = random.sample(available_abilities, num_abilities)
        
        return npc_cat
    
    async def _do_battle(self, ctx: commands.Context, battle_id: str):
        """Execute a battle between two cats"""
        battle = self.battles[battle_id]
        is_npc_battle = battle.get("is_npc", False)
        
        # Get cat data and stats
        challenger_cat = next(c for c in self.available_cats["cats"] if c["id"] == battle["challenger_cat"])
        opponent_cat = battle["npc_data"] if is_npc_battle else next(c for c in self.available_cats["cats"] if c["id"] == battle["opponent_cat"])
        
        # Initialize battle state with personality effects and stats
        challenger_stats = await self._calculate_cat_stats(battle["challenger_cat"], 
                                                         await self.config.user(battle["challenger"]).all())
        if is_npc_battle:
            opponent_stats = opponent_cat["stats"]
        else:
            opponent_stats = await self._calculate_cat_stats(battle["opponent_cat"], 
                                                           await self.config.user(battle["opponent"]).all())
        
        # Initialize AI for both cats
        challenger_ai = await self._initialize_cat_ai(challenger_cat, challenger_stats)
        opponent_ai = await self._initialize_cat_ai(opponent_cat, opponent_stats)
        
        # Battle state tracking with AI components
        battle_state = {
            "challenger": {
                "hp": 100 + (challenger_stats["defense"] // 4),
                "status": [], 
                "combo": 0,
                "last_moves": [],
                "ability_cooldowns": {},
                "stats": challenger_stats,
                "ai": challenger_ai,
                "is_player": True,  # Challenger is always a player
                "cat": challenger_cat
            },
            "opponent": {
                "hp": 100 + (opponent_stats["defense"] // 4),
                "status": [], 
                "combo": 0,
                "last_moves": [],
                "ability_cooldowns": {},
                "stats": opponent_stats,
                "ai": opponent_ai,
                "is_player": not is_npc_battle,  # Opponent might be NPC or player
                "cat": opponent_cat
            }
        }
        
        # Create battle embed
        embed = discord.Embed(
            title="🐱 Epic Cat Battle! 🐱",
            description=f"{challenger_cat['name']} vs {opponent_cat['name']}",
            color=discord.Color.gold()
        )
        battle_msg = await ctx.send(embed=embed)
        
        # Battle loop
        round_num = 1
        max_rounds = 15
        
        while battle_state["challenger"]["hp"] > 0 and battle_state["opponent"]["hp"] > 0 and round_num <= max_rounds:
            # Process status effects
            for side in ["challenger", "opponent"]:
                for status in battle_state[side]["status"]:
                    await self._apply_status_effect(battle_state, side, status)
            
            # Determine turn order based on speed and AI traits
            turn_order = await self._determine_turn_order(battle_state)
            
            # Process each turn
            for attacker_side, defender_side in turn_order:
                if battle_state["challenger"]["hp"] <= 0 or battle_state["opponent"]["hp"] <= 0:
                    break
                
                attacker = battle_state[attacker_side]
                defender = battle_state[defender_side]
                
                # Get action decision (AI for NPCs, or AI suggestion for players)
                action = await self._get_battle_action(battle_state, attacker_side, defender_side)
                
                # If it's a player's turn in PvP, we could add player input here
                if attacker["is_player"] and not is_npc_battle:
                    # For now, use AI decision, but could be expanded for player input
                    pass
                
                # Execute the action
                await self._execute_battle_action(ctx, battle_state, action, attacker_side, defender_side, embed)
                
                # Record the move for AI learning
                attacker["last_moves"].append(action)
                if len(attacker["last_moves"]) > 3:  # Keep last 3 moves
                    attacker["last_moves"].pop(0)
            
            # Update battle display
            await self._update_battle_display(battle_msg, embed, battle_state, round_num)
            await asyncio.sleep(2)
            round_num += 1

        # Handle battle conclusion
        winner = battle["challenger"] if battle_state["challenger"]["hp"] > battle_state["opponent"]["hp"] else battle["opponent"]
        
        # Calculate rewards with difficulty multiplier for NPC battles
        if is_npc_battle:
            difficulty_config = self.npc_difficulties[battle["difficulty"]]
            base_reward = self._calculate_battle_rewards(battle_state, round_num, max_rounds)
            catnip_reward = int(base_reward * difficulty_config["catnip_multiplier"])
            xp_reward = int(100 * difficulty_config["xp_multiplier"])  # Base XP for NPC battles
            
            if winner == battle["challenger"]:
                async with self.config.user(winner).all() as user_data:
                    user_data["catnip"] += catnip_reward
                    user_data["battles_won"] += 1
                    
                    # Award XP to the cat
                    cat_id = battle["challenger_cat"]
                    if cat_id not in user_data["cat_levels"]:
                        user_data["cat_levels"][cat_id] = {"level": 1, "xp": 0}
                    user_data["cat_levels"][cat_id]["xp"] += xp_reward
                    
                    # Check for level up
                    while user_data["cat_levels"][cat_id]["xp"] >= self._get_xp_for_level(user_data["cat_levels"][cat_id]["level"]):
                        user_data["cat_levels"][cat_id]["level"] += 1
                        await ctx.send(f"🎉 Your {challenger_cat['name']} reached level {user_data['cat_levels'][cat_id]['level']}!")
                    
                    # Update happiness
                    if cat_id not in user_data["cat_happiness"]:
                        user_data["cat_happiness"][cat_id] = 50
                    user_data["cat_happiness"][cat_id] = min(100, user_data["cat_happiness"][cat_id] + 5)
            
            # Show battle results
            embed = discord.Embed(
                title="🏆 Battle Complete!",
                description=f"{'You are' if winner == battle['challenger'] else 'NPC is'} victorious!\n\n"
                           f"Rewards:\n"
                           f"🌿 {catnip_reward} catnip\n"
                           f"📈 {xp_reward} XP\n"
                           f"💝 +5 happiness",
                color=discord.Color.green()
            )
        else:
            # Handle regular PvP battle rewards
            catnip_reward = self._calculate_battle_rewards(battle_state, round_num, max_rounds)
            
        async with self.config.user(winner).all() as user_data:
            user_data["catnip"] += catnip_reward
            user_data["battles_won"] += 1
            
            cat_id = battle[f"{winner.id}_cat"]
            if cat_id not in user_data["cat_happiness"]:
                user_data["cat_happiness"][cat_id] = 50
                user_data["cat_happiness"][cat_id] = min(100, user_data["cat_happiness"][cat_id] + 5)

        embed = discord.Embed(
            title="🏆 Battle Complete!",
            description=f"{winner.mention}'s cat is victorious!\n\n"
                       f"Rewards:\n"
                       f"🌿 {catnip_reward} catnip\n"
                       f"💝 +5 happiness\n",
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)

    async def _get_battle_action(self, battle_state: dict, attacker_side: str, defender_side: str) -> dict:
        """Get the next battle action for any cat (player or NPC)"""
        attacker = battle_state[attacker_side]
        defender = battle_state[defender_side]
        
        # Get AI suggestion regardless of player/NPC status
        action = await self._get_ai_action(battle_state, attacker_side, defender_side, attacker["cat"])
        
        # Add battle context to the action
        action["context"] = {
            "hp_ratio": attacker["hp"] / (100 + (attacker["stats"]["defense"] // 4)),
            "opponent_hp_ratio": defender["hp"] / (100 + (defender["stats"]["defense"] // 4)),
            "combo": attacker["combo"],
            "last_moves": attacker["last_moves"],
            "available_abilities": [
                ability_id for ability_id in attacker["cat"].get("abilities", [])
                if ability_id not in attacker["ability_cooldowns"]
            ]
        }
        
        return action

    async def _execute_battle_action(self, ctx: commands.Context, battle_state: dict, action: dict,
                                   attacker_side: str, defender_side: str, embed: discord.Embed):
        """Execute a battle action with personality and style"""
        attacker = battle_state[attacker_side]
        defender = battle_state[defender_side]
        cat = attacker["cat"]
        
        # Get personality-based flavor text
        personality = cat.get("personality", "mysterious")
        
        if action["type"] == "ability":
            await self._execute_ability_action(ctx, battle_state, action, attacker, defender, cat, embed)
        else:  # Normal attack
            await self._execute_attack_action(battle_state, action, attacker, defender, cat, embed)
    
    async def _execute_ability_action(self, ctx, battle_state, action, attacker, defender, cat, embed):
        """Execute an ability action"""
        available_abilities = action["context"]["available_abilities"]
        if not available_abilities:
            # Fallback to normal attack if no abilities available
            action["type"] = "attack"
            action["style"] = "normal"
            await self._execute_attack_action(battle_state, action, attacker, defender, cat, embed)
            return
            
        ability_id = self._select_best_ability(available_abilities, action["priority"], 
                                             attacker["stats"], defender["stats"])
        ability = self.available_abilities["abilities"][ability_id]
        
        # Apply ability effects
        for side, participant in [("attacker", attacker), ("defender", defender)]:
            if side == "attacker":
                damage, effects = await self._execute_special_move(ctx, battle_state, 
                                                                 side, "defender",
                                                                 ability)
                
                # Add ability to cooldown
                participant["ability_cooldowns"][ability_id] = 3  # Standard 3-turn cooldown
                
                # Update combo based on ability success
                if damage > 0 or effects:
                    participant["combo"] += 1
                
                # Add flavor text based on personality
                personality_flavor = self._get_personality_flavor(cat["personality"], "ability")
                if personality_flavor:
                    embed.add_field(
                        name="😺 Personality",
                        value=personality_flavor,
                        inline=False
                    )

    async def _execute_attack_action(self, battle_state, action, attacker, defender, cat, embed):
        """Execute a normal attack action"""
        base_damage = self._calculate_damage(attacker["stats"], defender["stats"])
        
        # Modify damage based on attack style
        if action["style"] == "aggressive":
            damage = int(base_damage * 1.2)
            accuracy = 0.8
        elif action["style"] == "cautious":
            damage = int(base_damage * 0.8)
            accuracy = 1.0
        elif action["style"] == "quick":
            damage = int(base_damage * 0.9)
            accuracy = 0.9
        else:  # normal
            damage = base_damage
            accuracy = 0.9
        
        # Check if attack hits
        if random.random() <= accuracy:
            defender["hp"] -= damage
            attacker["combo"] += 1
            
            # Add attack flavor text
            style_flavor = {
                "aggressive": "launches a fierce attack",
                "cautious": "strikes with precision",
                "quick": "darts in with lightning speed",
                "normal": "attacks"
            }[action["style"]]
            
            embed.add_field(
                name="⚔️ Attack",
                value=f"{cat['name']} {style_flavor} for {damage} damage!",
                inline=False
            )
        else:
            attacker["combo"] = 0
            embed.add_field(
                name="💨 Miss",
                value=f"{cat['name']}'s attack missed!",
                inline=False
            )

    def _select_best_ability(self, available_abilities: list, priority: str, 
                           attacker_stats: dict, defender_stats: dict) -> str:
        """Select the most appropriate ability based on the situation"""
        scored_abilities = []
        
        for ability_id in available_abilities:
            ability = self.available_abilities["abilities"][ability_id]
            score = 0
            
            # Score based on priority
            if priority == "offensive" and "damage_multiplier" in ability:
                score += 3
            elif priority == "defensive" and "defense_boost" in ability:
                score += 3
            elif priority == "combo" and "combo_bonus" in ability:
                score += 3
            elif priority == "utility":
                score += 1
            
            # Additional scoring based on stats and ability effects
            if "damage_multiplier" in ability and attacker_stats["attack"] > defender_stats["defense"]:
                score += 2
            if "defense_boost" in ability and attacker_stats["defense"] < defender_stats["attack"]:
                score += 2
            
            scored_abilities.append((ability_id, score))
        
        # Add some randomness to prevent predictability
        scored_abilities.sort(key=lambda x: x[1] + random.random() * 2, reverse=True)
        return scored_abilities[0][0]

    async def _initialize_cat_ai(self, cat: dict, stats: dict) -> dict:
        """Initialize AI behavior patterns based on cat's personality and stats"""
        personality = cat.get("personality", "mysterious")
        
        # Base AI traits
        ai_traits = {
            "aggressive": {
                "attack_chance": 0.7,
                "ability_chance": 0.4,
                "combo_focus": 0.6,
                "defensive_threshold": 0.3
            },
            "cautious": {
                "attack_chance": 0.5,
                "ability_chance": 0.3,
                "combo_focus": 0.3,
                "defensive_threshold": 0.5
            },
            "balanced": {
                "attack_chance": 0.6,
                "ability_chance": 0.35,
                "combo_focus": 0.4,
                "defensive_threshold": 0.4
            },
            "strategic": {
                "attack_chance": 0.55,
                "ability_chance": 0.45,
                "combo_focus": 0.5,
                "defensive_threshold": 0.45
            }
        }
        
        # Determine AI style based on personality and stats
        if personality in ["fierce", "bold"]:
            base_style = "aggressive"
        elif personality in ["shy", "careful"]:
            base_style = "cautious"
        elif personality in ["clever", "wise"]:
            base_style = "strategic"
        else:
            base_style = "balanced"
        
        # Adjust traits based on stats
        traits = ai_traits[base_style].copy()
        
        # High attack stat encourages aggressive play
        if stats["attack"] > stats["defense"] * 1.2:
            traits["attack_chance"] += 0.1
            traits["combo_focus"] += 0.1
        
        # High defense encourages strategic play
        if stats["defense"] > stats["attack"] * 1.2:
            traits["defensive_threshold"] += 0.1
            traits["ability_chance"] += 0.1
        
        # High speed encourages combo-focused play
        if stats["speed"] > (stats["attack"] + stats["defense"]) / 2:
            traits["combo_focus"] += 0.15
            traits["ability_chance"] += 0.05
        
        return {
            "style": base_style,
            "traits": traits,
            "personality": personality,
            "strategy_cooldown": 0,  # Prevents rapid strategy switching
            "last_strategy": None
        }
    
    async def _get_ai_action(self, battle_state: dict, attacker_side: str, defender_side: str, cat: dict) -> dict:
        """Determine the best action for the AI to take based on current battle state"""
        state = battle_state[attacker_side]
        opponent_state = battle_state[defender_side]
        ai = state["ai"]
        
        # Calculate detailed battle metrics
        hp_ratio = state["hp"] / (100 + (state["stats"]["defense"] // 4))
        opponent_hp_ratio = opponent_state["hp"] / (100 + (opponent_state["stats"]["defense"] // 4))
        
        # Calculate stat ratios for better decision making
        attack_ratio = state["stats"]["attack"] / max(1, opponent_state["stats"]["defense"])
        defense_ratio = state["stats"]["defense"] / max(1, opponent_state["stats"]["attack"])
        speed_ratio = state["stats"]["speed"] / max(1, opponent_state["stats"]["speed"])
        
        # Analyze status effects
        has_positive_status = any(status in self.status_effects and 
                                self.status_effects[status].get("type") == "buff"
                                for status in state["status"])
        has_negative_status = any(status in self.status_effects and 
                                self.status_effects[status].get("type") == "debuff"
                                for status in state["status"])
        opponent_has_buffs = any(status in self.status_effects and 
                               self.status_effects[status].get("type") == "buff"
                               for status in opponent_state["status"])
        
        # Calculate threat level (0-1) with status effects consideration
        threat_level = (
            (1 - hp_ratio) * 0.3 +  # Lower HP increases threat
            (opponent_hp_ratio) * 0.2 +  # Higher opponent HP increases threat
            (1 if opponent_has_buffs else 0) * 0.1 +  # Opponent buffs increase threat
            (has_negative_status * 0.2) +  # Having debuffs increases threat
            (max(0, 1 - defense_ratio) * 0.2)  # Lower defense ratio increases threat
        )
        
        # Calculate opportunity score (0-1) with enhanced metrics
        opportunity_score = (
            hp_ratio * 0.2 +  # Higher HP increases opportunities
            (attack_ratio - 1) * 0.2 +  # Higher attack ratio increases opportunities
            (speed_ratio - 1) * 0.15 +  # Higher speed ratio increases opportunities
            (has_positive_status * 0.15) +  # Having buffs increases opportunities
            (state["combo"] >= 2) * 0.2 +  # Having a combo increases opportunities
            (not opponent_has_buffs * 0.1)  # Opponent lacking buffs increases opportunities
        )
        
        # Get available abilities with cooldown check
        available_abilities = [
            ability_id for ability_id in cat.get("abilities", [])
            if ability_id not in state["ability_cooldowns"]
        ]
        
        # Categorize available abilities
        ability_types = {
            "offensive": [],
            "defensive": [],
            "utility": [],
            "combo": []
        }
        
        for ability_id in available_abilities:
            ability = self.available_abilities["abilities"][ability_id]
            
            # Categorize based on ability effects
            if "damage_multiplier" in ability:
                ability_types["offensive"].append(ability_id)
            if "defense_boost" in ability or "healing" in ability:
                ability_types["defensive"].append(ability_id)
            if "status_effect" in ability:
                if ability["status_effect"].get("type") == "buff":
                    ability_types["utility"].append(ability_id)
                elif ability["status_effect"].get("type") == "debuff":
                    ability_types["offensive"].append(ability_id)
            if "combo_bonus" in ability or "chain" in ability:
                ability_types["combo"].append(ability_id)
        
        # Adjust strategy based on personality and available abilities
        personality = cat.get("personality", "mysterious")
        if personality == "fierce":
            opportunity_score *= 1.2
            threat_level *= 0.8
        elif personality == "shy":
            threat_level *= 1.2
            opportunity_score *= 0.8
        elif personality == "clever":
            # Clever cats try to counter the opponent's state
            if opponent_has_buffs and ability_types["utility"]:
                opportunity_score *= 1.2  # Encourage utility moves to counter buffs
            if has_negative_status and ability_types["defensive"]:
                threat_level *= 1.2  # Encourage defensive moves when debuffed
        
        # Select strategy based on situation
        if threat_level > 0.6 and ability_types["defensive"]:
            # Defensive strategy when threatened
            if random.random() < ai["traits"]["ability_chance"] * 1.3:
                return {
                    "type": "ability",
                    "priority": "defensive",
                    "available": ability_types["defensive"]
                }
            return {"type": "attack", "style": "cautious"}
            
        elif opportunity_score > 0.6:
            # Offensive strategy when advantaged
            if state["combo"] >= 2 and ability_types["combo"]:
                # Prioritize combo abilities when on a streak
                if random.random() < ai["traits"]["combo_focus"]:
                    return {
                        "type": "ability",
                        "priority": "combo",
                        "available": ability_types["combo"]
                    }
            elif ability_types["offensive"]:
                if random.random() < ai["traits"]["ability_chance"]:
                    return {
                        "type": "ability",
                        "priority": "offensive",
                        "available": ability_types["offensive"]
                    }
            return {"type": "attack", "style": "aggressive"}
            
        else:
            # Balanced approach
            if has_negative_status and ability_types["utility"]:
                # Try to remove debuffs
                if random.random() < ai["traits"]["ability_chance"]:
                    return {
                        "type": "ability",
                        "priority": "utility",
                        "available": ability_types["utility"]
                    }
            
            # Default to a mix of normal attacks and abilities
            if random.random() < ai["traits"]["ability_chance"] and any(ability_types.values()):
                # Choose ability type based on situation
                priorities = []
                if threat_level > 0.4:
                    if ability_types["defensive"]:
                        priorities.append(("defensive", 60))
                    if ability_types["utility"]:
                        priorities.append(("utility", 40))
                if opportunity_score > 0.4:
                    if ability_types["offensive"]:
                        priorities.append(("offensive", 50))
                    if ability_types["combo"]:
                        priorities.append(("combo", 30))
                
                if priorities:
                    selected_priority = random.choices(
                        [p[0] for p in priorities],
                        weights=[p[1] for p in priorities]
                    )[0]
                    return {
                        "type": "ability",
                        "priority": selected_priority,
                        "available": ability_types[selected_priority]
                    }
            
            # Default attack style based on situation
            if speed_ratio > 1.2:
                return {"type": "attack", "style": "quick"}
            elif defense_ratio > 1.2:
                return {"type": "attack", "style": "cautious"}
            else:
                return {"type": "attack", "style": "normal"}
    
    async def _execute_ai_action(self, ctx: commands.Context, battle_state: dict, action: dict,
                               attacker_side: str, defender_side: str, cat: dict, embed: discord.Embed):
        """Execute the AI-chosen action"""
        state = battle_state[attacker_side]
        opponent_state = battle_state[defender_side]
        
        if action["type"] == "ability":
            # Filter abilities based on priority
            available_abilities = []
            for ability_id in cat.get("abilities", []):
                if ability_id not in state["ability_cooldowns"]:
                    ability = self.available_abilities["abilities"][ability_id]
                    if action["priority"] == "offensive" and "damage_multiplier" in ability:
                        available_abilities.append(ability_id)
                    elif action["priority"] == "defensive" and "defense_boost" in ability:
                        available_abilities.append(ability_id)
                    elif action["priority"] == "combo" and "combo_bonus" in ability:
                        available_abilities.append(ability_id)
                    elif action["priority"] == "utility":
                        available_abilities.append(ability_id)
            
            if available_abilities:
                ability_id = random.choice(available_abilities)
                ability = self.available_abilities["abilities"][ability_id]
                
                # Apply ability effects
                damage, effects = await self._execute_special_move(ctx, battle_state, 
                                                                 attacker_side, defender_side,
                                                                 ability)
                
                # Add ability to cooldown
                state["ability_cooldowns"][ability_id] = 3  # Standard 3-turn cooldown
                
                # Update combo based on ability success
                if damage > 0 or effects:
                    state["combo"] += 1
                
                # Add flavor text based on personality
                personality_flavor = self._get_personality_flavor(cat["personality"], "ability")
                if personality_flavor:
                    embed.add_field(
                        name="😺 Personality",
                        value=personality_flavor,
                        inline=False
                    )

        else:  # Normal attack
            base_damage = self._calculate_damage(state["stats"], opponent_state["stats"])
            
            # Modify damage based on attack style
            if action["style"] == "aggressive":
                damage = int(base_damage * 1.2)
                accuracy = 0.8
            elif action["style"] == "cautious":
                damage = int(base_damage * 0.8)
                accuracy = 1.0
            elif action["style"] == "quick":
                damage = int(base_damage * 0.9)
                accuracy = 0.9
            else:  # normal
                damage = base_damage
                accuracy = 0.9
            
            # Check if attack hits
            if random.random() <= accuracy:
                opponent_state["hp"] -= damage
                state["combo"] += 1
                
                # Add attack flavor text
                style_flavor = {
                    "aggressive": "launches a fierce attack",
                    "cautious": "strikes with precision",
                    "quick": "darts in with lightning speed",
                    "normal": "attacks"
                }[action["style"]]
                
                embed.add_field(
                    name="⚔️ Attack",
                    value=f"{cat['name']} {style_flavor} for {damage} damage!",
                    inline=False
                )
            else:
                state["combo"] = 0
                embed.add_field(
                    name="💨 Miss",
                    value=f"{cat['name']}'s attack missed!",
                    inline=False
                )

    def _get_personality_flavor(self, personality: str, action_type: str) -> str:
        """Get flavor text based on personality and action type"""
        flavor_text = {
            "fierce": {
                "ability": "unleashes their power with a mighty roar!",
                "attack": "strikes with unbridled ferocity!",
                "dodge": "refuses to back down!"
            },
            "shy": {
                "ability": "musters their courage for a special move!",
                "attack": "strikes when the moment is right!",
                "dodge": "carefully evades the attack!"
            },
            "clever": {
                "ability": "executes their strategy perfectly!",
                "attack": "finds the perfect opening!",
                "dodge": "outsmarts their opponent!"
            },
            "mysterious": {
                "ability": "channels an enigmatic power!",
                "attack": "strikes from the shadows!",
                "dodge": "vanishes like mist!"
            }
        }
        
        return flavor_text.get(personality, {}).get(action_type, None)
    
    async def _determine_turn_order(self, battle_state: dict) -> list:
        """Determine turn order based on speed and AI traits"""
        challenger_speed = battle_state["challenger"]["stats"]["speed"]
        opponent_speed = battle_state["opponent"]["stats"]["speed"]
        
        # Add some randomness based on AI aggression
        challenger_initiative = challenger_speed * (1 + random.random() * 0.2)
        opponent_initiative = opponent_speed * (1 + random.random() * 0.2)
        
        # Aggressive AI traits can boost initiative
        if battle_state["challenger"]["ai"]["style"] == "aggressive":
            challenger_initiative *= 1.1
        if battle_state["opponent"]["ai"]["style"] == "aggressive":
            opponent_initiative *= 1.1
        
        if challenger_initiative > opponent_initiative:
            return [("challenger", "opponent"), ("opponent", "challenger")]
        else:
            return [("opponent", "challenger"), ("challenger", "opponent")]

    def _get_xp_for_level(self, current_level: int) -> int:
        """Calculate XP needed for next level"""
        return int(100 * (current_level ** 1.5))  # Exponential XP curve

    async def _update_battle_display(self, message, embed, battle_state, challenger_cat, opponent_cat, round_num):
        """Update the battle display with current state"""
        embed.clear_fields()

        embed.add_field(
            name=f"Round {round_num}",
            value="🐱 Battle in Progress! 🐱",
            inline=False
        )

        for side, cat in [("challenger", challenger_cat), ("opponent", opponent_cat)]:
            state = battle_state[side]
            # Get status effects from abilities.json
            status_text = []
            for status in state["status"]:
                if status in self.status_effects:
                    effect = self.status_effects[status]
                    status_text.append(f"{effect['name']}")
            status_display = " | ".join(status_text) if status_text else "Normal"
            
            personality = cat.get("personality", "mysterious")
            personality_effects = self.PERSONALITIES.get(personality, {})
            personality_text = ", ".join(f"{k}: {v:+d}%" for k, v in personality_effects.items())

            embed.add_field(
                name=f"{cat['emoji']} {cat['name']}",
                value=f"```\nHP: {'█' * int(state['hp']/10)}{'░' * (10-int(state['hp']/10))} {state['hp']}/100\n"
                      f"ATK: {state['stats']['attack']} | DEF: {state['stats']['defense']} | SPD: {state['stats']['speed']}\n```\n"
                      f"**Status:** {status_display}\n"
                      f"**Personality:** {personality} ({personality_text})",
                inline=False
            )

        await message.edit(embed=embed)

    def get_mood_emoji(self, happiness: int) -> str:
        """Get mood emoji based on happiness level"""
        if happiness >= 80:
            return "😺"
        elif happiness >= 60:
            return "😸"
        elif happiness >= 40:
            return "😺"
        elif happiness >= 20:
            return "😿"
        else:
            return "🙀"
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle random catnip drops from chatting"""
        if message.author.bot or not message.guild:
            return
            
        guild_data = await self.config.guild(message.guild).all()
        if random.random() < guild_data["catnip_chance"]:
            min_catnip, max_catnip = guild_data["catnip_amount_range"]
            earned = random.randint(min_catnip, max_catnip)
            
            async with self.config.user(message.author).all() as user_data:
                user_data["catnip"] += earned
            
            await message.channel.send(
                f"🌿 {message.author.mention} found {earned} catnip while chatting!"
            )

    @meow.group(name="summon")
    async def meow_summon(self, ctx: commands.Context):
        """Summon new cats using magical catnip!"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🌟 Cat Summoning",
                description="Use magical catnip to summon new cats!\n\n"
                          "**Commands:**\n"
                          "`summon regular` - Regular summon (300 catnip)\n"
                          "`summon premium` - Premium summon (1000 catnip)\n"
                          "`summon multi` - 10x Premium summon with guaranteed rare+ (9000 catnip)\n"
                          "`summon pity` - Check your pity counter\n\n"
                          "**Rates:**\n"
                          "Regular: Common (60%), Uncommon (35%), Rare (5%)\n"
                          "Premium: Uncommon (60%), Rare (35%), Epic (4%), Legendary (1%)",
                color=discord.Color.gold()
            )
            await ctx.send(embed=embed)

    @meow_summon.command(name="regular")
    async def summon_regular(self, ctx: commands.Context):
        """Perform a regular cat summon"""
        cost = 300
        async with self.config.user(ctx.author).all() as user_data:
            if user_data["catnip"] < cost:
                await ctx.send("You need 300 catnip to perform a regular summon!")
                return

            # Get summon result
            rarity = self._get_summon_rarity("regular")
            cat = self._get_random_cat(rarity)
            
            # Update user data
            user_data["catnip"] -= cost
            if cat["id"] not in user_data["cats"]:
                user_data["cats"].append(cat["id"])
                user_data["cat_levels"][cat["id"]] = {"level": 1, "xp": 0}
                is_new = True
            else:
                # Convert duplicate to cat fragments and XP
                fragments = {"common": 1, "uncommon": 2, "rare": 5}[rarity]
                xp = {"common": 100, "uncommon": 300, "rare": 1000}[rarity]
                if "cat_fragments" not in user_data:
                    user_data["cat_fragments"] = {}
                if cat["id"] not in user_data["cat_fragments"]:
                    user_data["cat_fragments"][cat["id"]] = 0
                user_data["cat_fragments"][cat["id"]] += fragments
                user_data["cat_levels"][cat["id"]]["xp"] += xp
                is_new = False

            # Create summon animation
            embed = discord.Embed(
                title="✨ Summoning Circle Activated!",
                description="The magical catnip draws a cat from another dimension...",
                color=discord.Color.blue()
            )
            msg = await ctx.send(embed=embed)
            
            await asyncio.sleep(2)
            
            # Update with result
            star_rating = {"common": "⭐", "uncommon": "⭐⭐", "rare": "⭐⭐⭐"}[rarity]
            embed.title = f"🌟 Summoned: {cat['name']} {star_rating}"
            embed.description = f"**Rarity:** {rarity.title()}\n"
            if is_new:
                embed.description += "**NEW!** Added to your collection! 📚"
            else:
                embed.description += f"Duplicate! Converted to {fragments} fragments and {xp} XP 🔄"
            
            embed.set_thumbnail(url=f"attachment://{cat['id']}_cat.png")
            await msg.edit(embed=embed)

    @meow_summon.command(name="premium")
    async def summon_premium(self, ctx: commands.Context):
        """Perform a premium cat summon"""
        cost = 1000
        async with self.config.user(ctx.author).all() as user_data:
            if user_data["catnip"] < cost:
                await ctx.send("You need 1000 catnip to perform a premium summon!")
                return

            if "pity_counter" not in user_data:
                user_data["pity_counter"] = 0
            
            # Get summon result
            rarity = self._get_summon_rarity("premium", user_data["pity_counter"])
            cat = self._get_random_cat(rarity)
            
            # Update pity counter
            if rarity in ["epic", "legendary"]:
                user_data["pity_counter"] = 0
            else:
                user_data["pity_counter"] += 1
            
            # Update user data
            user_data["catnip"] -= cost
            if cat["id"] not in user_data["cats"]:
                user_data["cats"].append(cat["id"])
                user_data["cat_levels"][cat["id"]] = {"level": 1, "xp": 0}
                is_new = True
            else:
                # Convert duplicate to cat fragments and XP
                fragments = {"uncommon": 2, "rare": 5, "epic": 10, "legendary": 20}[rarity]
                xp = {"uncommon": 300, "rare": 1000, "epic": 3000, "legendary": 10000}[rarity]
                if "cat_fragments" not in user_data:
                    user_data["cat_fragments"] = {}
                if cat["id"] not in user_data["cat_fragments"]:
                    user_data["cat_fragments"][cat["id"]] = 0
                user_data["cat_fragments"][cat["id"]] += fragments
                user_data["cat_levels"][cat["id"]]["xp"] += xp
                is_new = False

            # Create summon animation
            embed = discord.Embed(
                title="🌠 Premium Summoning Circle Activated!",
                description="The premium catnip creates a powerful dimensional rift...",
                color=discord.Color.purple()
            )
            msg = await ctx.send(embed=embed)
            
            await asyncio.sleep(2)
            
            # Update with result
            star_rating = {
                "uncommon": "⭐⭐",
                "rare": "⭐⭐⭐",
                "epic": "⭐⭐⭐⭐",
                "legendary": "⭐⭐⭐⭐⭐"
            }[rarity]
            
            embed.title = f"🌟 Summoned: {cat['name']} {star_rating}"
            embed.description = f"**Rarity:** {rarity.title()}\n"
            if is_new:
                embed.description += "**NEW!** Added to your collection! 📚"
            else:
                embed.description += f"Duplicate! Converted to {fragments} fragments and {xp} XP 🔄"
            
            embed.set_thumbnail(url=f"attachment://{cat['id']}_cat.png")
            await msg.edit(embed=embed)

    @meow_summon.command(name="multi")
    async def summon_multi(self, ctx: commands.Context):
        """Perform a 10x premium summon with guaranteed rare+"""
        cost = 9000  # 10% discount for bulk
        async with self.config.user(ctx.author).all() as user_data:
            if user_data["catnip"] < cost:
                await ctx.send("You need 9000 catnip to perform a 10x premium summon!")
                return

            if "pity_counter" not in user_data:
                user_data["pity_counter"] = 0
            
            # Create initial animation
            embed = discord.Embed(
                title="🌌 10x Premium Summoning Circle Activated!",
                description="A massive dimensional rift opens...",
                color=discord.Color.purple()
            )
            msg = await ctx.send(embed=embed)
            
            # Perform 10 summons
            results = []
            for i in range(10):
                # Last summon guaranteed rare+ if no rare+ yet
                if i == 9 and not any(r["rarity"] in ["rare", "epic", "legendary"] for r in results):
                    rarity = random.choice(["rare", "epic", "legendary"])
                else:
                    rarity = self._get_summon_rarity("premium", user_data["pity_counter"])
                
                cat = self._get_random_cat(rarity)
                results.append({"cat": cat, "rarity": rarity})
                
                # Update pity counter
                if rarity in ["epic", "legendary"]:
                    user_data["pity_counter"] = 0
                else:
                    user_data["pity_counter"] += 1
                
                # Process the summon
                if cat["id"] not in user_data["cats"]:
                    user_data["cats"].append(cat["id"])
                    user_data["cat_levels"][cat["id"]] = {"level": 1, "xp": 0}
                    results[-1]["is_new"] = True
                else:
                    fragments = {"uncommon": 2, "rare": 5, "epic": 10, "legendary": 20}[rarity]
                    xp = {"uncommon": 300, "rare": 1000, "epic": 3000, "legendary": 10000}[rarity]
                    if "cat_fragments" not in user_data:
                        user_data["cat_fragments"] = {}
                    if cat["id"] not in user_data["cat_fragments"]:
                        user_data["cat_fragments"][cat["id"]] = 0
                    user_data["cat_fragments"][cat["id"]] += fragments
                    user_data["cat_levels"][cat["id"]]["xp"] += xp
                    results[-1]["fragments"] = fragments
                    results[-1]["xp"] = xp
                    results[-1]["is_new"] = False
                
                # Update animation
                star_rating = {
                    "uncommon": "⭐⭐",
                    "rare": "⭐⭐⭐",
                    "epic": "⭐⭐⭐⭐",
                    "legendary": "⭐⭐⭐⭐⭐"
                }[rarity]
                
                summon_list = ""
                for r in results:
                    stars = {
                        "uncommon": "⭐⭐",
                        "rare": "⭐⭐⭐",
                        "epic": "⭐⭐⭐⭐",
                        "legendary": "⭐⭐⭐⭐⭐"
                    }[r["rarity"]]
                    new_tag = "NEW!" if r["is_new"] else ""
                    summon_list += f"{stars} {r['cat']['name']} {new_tag}\n"
                
                embed.description = f"Summoning in progress... ({i+1}/10)\n\n{summon_list}"
                await msg.edit(embed=embed)
                await asyncio.sleep(1)
            
            # Deduct cost
            user_data["catnip"] -= cost
            
            # Final summary
            rarities = [r["rarity"] for r in results]
            summary = (
                f"**Summon Complete!**\n\n"
                f"🎯 Results:\n"
                f"Uncommon: {rarities.count('uncommon')}\n"
                f"Rare: {rarities.count('rare')}\n"
                f"Epic: {rarities.count('epic')}\n"
                f"Legendary: {rarities.count('legendary')}\n\n"
                f"New Cats: {sum(1 for r in results if r['is_new'])}"
            )
            
            embed.title = "🌟 10x Summon Results"
            embed.description = summary
            await msg.edit(embed=embed)

    @meow_summon.command(name="pity")
    async def check_pity(self, ctx: commands.Context):
        """Check your pity counter for premium summons"""
        user_data = await self.config.user(ctx.author).all()
        pity = user_data.get("pity_counter", 0)
        
        embed = discord.Embed(
            title="🎯 Pity Counter",
            description=f"Your current pity counter is: {pity}\n\n"
                      f"Every premium summon without an Epic or Legendary increases your pity counter.\n"
                      f"At 50 pity, you're guaranteed an Epic or Legendary!\n\n"
                      f"Current Epic/Legendary chance: {min(5 + pity * 0.2, 100)}%",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    def _get_summon_rarity(self, summon_type: str, pity: int = 0) -> str:
        """Get a random rarity based on summon type and pity"""
        if summon_type == "regular":
            # Adjusted regular summon rates
            roll = random.random() * 100
            if roll < 65:  # Increased slightly for better common drops
                return "common"
            elif roll < 90:  # Reduced slightly
                return "uncommon"
            else:
                return "rare"
        else:  # premium
            # Rebalanced premium rates with better pity system
            base_epic_chance = 4
            base_legendary_chance = 1
            pity_bonus = min(pity * 0.5, 40)  # More gradual pity increase, max 40%
            
            roll = random.random() * 100
            
            if roll < (base_legendary_chance + pity_bonus * 0.2) or pity >= 89:  # Guaranteed at 90 pity
                return "legendary"
            elif roll < (base_epic_chance + base_legendary_chance + pity_bonus) or pity >= 79:  # Guaranteed epic at 80
                return "epic"
            elif roll < 55:  # Adjusted for better balance
                return "rare"
            else:
                return "uncommon"

    def _get_random_cat(self, rarity: str) -> dict:
        """Get a random cat of the specified rarity"""
        possible_cats = [cat for cat in self.available_cats["cats"] if cat["rarity"] == rarity]
        return random.choice(possible_cats)

    async def _update_battle_display(self, message, embed, battle_state, challenger_cat, opponent_cat, round_num):
        """Update the battle display with current state"""
        embed.clear_fields()
        
        embed.add_field(
            name=f"Round {round_num}",
            value="🐱 Battle in Progress! 🐱",
            inline=False
        )

        for side, cat in [("challenger", challenger_cat), ("opponent", opponent_cat)]:
            state = battle_state[side]
            # Get status effects from abilities.json
            status_text = []
            for status in state["status"]:
                if status in self.status_effects:
                    effect = self.status_effects[status]
                    status_text.append(f"{effect['name']}")
            status_display = " | ".join(status_text) if status_text else "Normal"
            
            personality = cat.get("personality", "mysterious")
            personality_effects = self.PERSONALITIES.get(personality, {})
            personality_text = ", ".join(f"{k}: {v:+d}%" for k, v in personality_effects.items())

            embed.add_field(
                name=f"{cat['emoji']} {cat['name']}",
                value=f"```\nHP: {'█' * int(state['hp']/10)}{'░' * (10-int(state['hp']/10))} {state['hp']}/100\n"
                      f"ATK: {state['stats']['attack']} | DEF: {state['stats']['defense']} | SPD: {state['stats']['speed']}\n```\n"
                      f"**Status:** {status_display}\n"
                      f"**Personality:** {personality} ({personality_text})",
                inline=False
            )

        await message.edit(embed=embed)

def setup(bot: Red):
    bot.add_cog(Meowventure(bot))
