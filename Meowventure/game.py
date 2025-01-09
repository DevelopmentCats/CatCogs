# Visual Style Guide
COLOR_PRIMARY = 0x1abc9c  # Teal
COLOR_SECONDARY = 0x3498db  # Blue
COLOR_SUCCESS = 0x2ecc71  # Green
COLOR_DANGER = 0xe74c3c  # Red
COLOR_WARNING = 0xf1c40f  # Yellow
COLOR_INFO = 0x9b59b6  # Purple

EMBED_TITLE = "Meowventure Red"
EMBED_FOOTER = "🐾 Adventure awaits! 🐾"
EMBED_THUMBNAIL = "https://i.imgur.com/meowventure.png"

from typing import Dict, List, Optional, Union
import random
import math
import asyncio
from dataclasses import dataclass
from .ai import BattleAI, BattleState, PersonalityProfile, battle_ai

@dataclass
class PlayerReputation:
    level: int = 1
    xp: int = 0
    login_streak: int = 0
    last_login_date: str = ""
    total_spent: Dict[str, int] = {"fish": 0, "gems": 0}

    def calculate_level(self) -> None:
        """Calculate reputation level based on XP"""
        levels = [
            {"level": 1, "xp_required": 0},
            {"level": 2, "xp_required": 100},
            {"level": 3, "xp_required": 500},
            {"level": 4, "xp_required": 2000},
            {"level": 5, "xp_required": 10000}
        ]
        
        for level_data in reversed(levels):
            if self.xp >= level_data["xp_required"]:
                self.level = level_data["level"]
                break

    def add_xp(self, amount: int) -> None:
        """Add XP and recalculate level"""
        self.xp += amount
        self.calculate_level()

    def update_login_streak(self, current_date: str) -> Dict[str, int]:
        """Update login streak based on current date and return rewards"""
        rewards = {"fish": 0, "gems": 0}
        
        if self.last_login_date != current_date:
            if self.last_login_date and (current_date - self.last_login_date).days == 1:
                self.login_streak = min(self.login_streak + 1, 7)
            else:
                self.login_streak = 1
            self.last_login_date = current_date
            
            # Calculate daily rewards based on streak
            base_fish = 50
            base_gems = 5
            streak_bonus = min(self.login_streak, 7)  # Max 7x bonus
            
            rewards["fish"] = base_fish * streak_bonus
            rewards["gems"] = base_gems * streak_bonus
            
            # Special bonus for 7-day streak
            if self.login_streak == 7:
                rewards["fish"] += 100
                rewards["gems"] += 10
                
        return rewards

    def get_shop_bonuses(self) -> Dict[str, float]:
        """Calculate shop bonuses based on reputation level"""
        bonuses = {
            "price_reduction": min(0.05 * self.level, 0.2),  # Up to 20% price reduction
            "discount_increase": min(0.1 * self.level, 0.6),  # Up to 60% better discounts
            "additional_items": min(0.1 * self.level, 0.2),  # Up to 20% more items in shop
            "bonus_gems": min(0.05 * self.level, 0.15),  # Up to 15% bonus gems from purchases
            "bonus_fish": min(0.1 * self.level, 0.3),  # Up to 30% bonus fish from purchases
            "daily_deals": min(0.05 * self.level, 0.15)  # Up to 15% better daily deals
        }
        return bonuses

@dataclass
class Stats:
    hp: int
    attack: int
    defense: int
    speed: int
    crit_rate: float
    crit_damage: float

    def apply_modifier(self, modifier: Dict[str, float]) -> None:
        """Apply stat modifiers from buffs/equipment"""
        if "all_stats" in modifier:
            self.hp = int(self.hp * modifier["all_stats"])
            self.attack = int(self.attack * modifier["all_stats"])
            self.defense = int(self.defense * modifier["all_stats"])
            self.speed = int(self.speed * modifier["all_stats"])
        else:
            for stat, value in modifier.items():
                if hasattr(self, stat):
                    setattr(self, stat, int(getattr(self, stat) * value))

class Cat:
    def __init__(self, cat_data: Dict):
        self.id: str = cat_data["id"]
        self.name: str = cat_data["name"]
        self.title: str = cat_data["title"]
        self.rarity: str = cat_data["rarity"]
        self.affinity: str = cat_data["affinity"]
        self.level: int = 1
        self.exp: int = 0
        self.evolution_stage: int = 1
        
        # Initialize base stats
        self.base_stats = Stats(**cat_data["base_stats"])
        self.current_stats = Stats(**cat_data["base_stats"])
        self.growth_rates = cat_data["growth_rates"]
        
        # Combat related
        self.abilities: List[str] = cat_data["abilities"]
        self.passive: str = cat_data["passive"]
        self.current_hp: int = self.current_stats.hp
        self.energy: int = 100
        self.status_effects: List[Dict] = []
        
        # Add personality data
        self.personality_type = cat_data.get("personality_type", "mysterious")
        self.battle_style = cat_data.get("battle_style", "strategic")
        self.personality = PersonalityProfile(self.personality_type, self.battle_style)

    def calculate_stats(self) -> None:
        """Calculate current stats based on level, evolution, and equipment"""
        for stat in ["hp", "attack", "defense", "speed"]:
            base = getattr(self.base_stats, stat)
            growth = self.growth_rates[stat]
            level_bonus = math.floor(base * (growth * (self.level - 1) / 100))
            evolution_bonus = base * ((self.evolution_stage - 1) * 0.2)
            final = base + level_bonus + evolution_bonus
            setattr(self.current_stats, stat, int(final))
        
        self.current_hp = self.current_stats.hp

    def gain_exp(self, amount: int) -> Dict[str, Union[int, bool]]:
        """Grant experience to the cat and handle level ups"""
        self.exp += amount
        old_level = self.level
        
        # Calculate new level
        exp_needed = lambda lvl: int(100 * (lvl ** 1.5))
        while self.exp >= exp_needed(self.level):
            self.level += 1
        
        if old_level != self.level:
            self.calculate_stats()
            return {
                "levels_gained": self.level - old_level,
                "new_level": self.level,
                "leveled_up": True
            }
        
        return {"leveled_up": False}

    def can_evolve(self, required_items: List[str], player_items: Dict[str, int]) -> bool:
        """Check if cat can evolve based on requirements"""
        if self.level < 20:
            return False
        
        for item in required_items:
            if item not in player_items or player_items[item] < 1:
                return False
        
        return True

    def evolve(self) -> None:
        """Evolve the cat to next stage"""
        self.evolution_stage += 1
        self.calculate_stats()

class Battle:
    def __init__(self, team1: List[Cat], team2: List[Cat], is_auto: bool = False):
        self.team1 = team1
        self.team2 = team2
        self.turn_order: List[Cat] = []
        self.current_turn: int = 0
        self.battle_log: List[str] = []
        self.is_active: bool = True
        self.is_auto = is_auto  # Whether battle runs automatically
        
        # Initialize battle state
        self.state = BattleState(
            active_cat=None,  # Will be set in initialize_battle
            allies=[],  # Will be set based on current turn
            enemies=[],  # Will be set based on current turn
            turn_number=0,
            battle_log=[]
        )

    def initialize_battle(self) -> None:
        """Set up the initial battle state"""
        # Combine teams and sort by speed for turn order
        all_cats = self.team1 + self.team2
        self.turn_order = sorted(all_cats, key=lambda cat: cat.current_stats.speed, reverse=True)
        
        # Reset all cats to battle-ready state
        for cat in all_cats:
            cat.current_hp = cat.current_stats.hp
            cat.energy = 100
            cat.status_effects = []
        
        # Set initial battle state
        self.state.active_cat = self.turn_order[0]
        self._update_battle_state()

    def _update_battle_state(self) -> None:
        """Update the battle state for AI decision making"""
        current_cat = self.get_current_cat()
        
        # Determine allies and enemies based on current cat's team
        if current_cat in self.team1:
            self.state.allies = [cat for cat in self.team1 if cat != current_cat and cat.current_hp > 0]
            self.state.enemies = [cat for cat in self.team2 if cat.current_hp > 0]
        else:
            self.state.allies = [cat for cat in self.team2 if cat != current_cat and cat.current_hp > 0]
            self.state.enemies = [cat for cat in self.team1 if cat.current_hp > 0]
        
        self.state.active_cat = current_cat
        self.state.turn_number = self.current_turn
        self.state.battle_log = self.battle_log[-5:]  # Keep last 5 actions for context

    async def process_turn(self, action: Optional[Dict] = None) -> Dict:
        """Process a single turn of battle"""
        current_cat = self.get_current_cat()
        
        # Process status effects
        self._process_status_effects(current_cat)
        
        # Get action - either from AI or provided action
        if action is None:
            if self.is_auto or current_cat in self.team2:  # AI controls team2 and auto battles
                action = await self._get_ai_action(current_cat)
            else:
                raise ValueError("Action required for player-controlled cat")
        
        # Process the action if cat can act
        if not self._is_stunned(current_cat):
            result = await self._process_action(current_cat, action)
            self.battle_log.append(result["log"])
            
            # Update AI learning based on action success
            if current_cat in self.team2:  # Only learn from AI-controlled cats
                battle_ai.update_learning(action, result["success"], self.state)
        
        # Move to next turn
        self.current_turn += 1
        self._update_battle_state()
        
        # Check for battle end
        if self._check_battle_end():
            self.is_active = False
            
        return {
            "log": self.battle_log[-1],
            "battle_active": self.is_active,
            "next_cat": self.get_current_cat(),
            "state": self.state
        }

    async def _get_ai_action(self, cat: Cat) -> Dict:
        """Get AI decision for a cat's turn"""
        return await battle_ai.get_action(self.state, cat.personality)

    async def _process_action(self, cat: Cat, action: Dict) -> Dict:
        """Process a battle action"""
        try:
            if action["type"] == "basic_attack":
                return await self._process_basic_attack(cat, action)
            elif action["type"] == "ability":
                return await self._process_ability(cat, action)
            else:
                raise ValueError(f"Unknown action type: {action['type']}")
        except Exception as e:
            print(f"Error processing action: {e}")
            return {
                "log": f"{cat.name}'s action failed",
                "success": False
            }

    async def _process_basic_attack(self, cat: Cat, action: Dict) -> Dict:
        """Process a basic attack action"""
        # Select target (for now, just pick first alive enemy)
        target = next((enemy for enemy in self.state.enemies if enemy.current_hp > 0), None)
        if not target:
            return {"log": "No valid target", "success": False}
        
        # Calculate damage
        damage = self._calculate_damage(cat, target, action)
        
        # Apply damage
        target.current_hp = max(0, target.current_hp - damage)
        
        return {
            "log": f"{cat.name} attacks {target.name} for {damage} damage!",
            "success": True
        }

    async def _process_ability(self, cat: Cat, action: Dict) -> Dict:
        """Process an ability action"""
        # This would be expanded based on actual ability effects
        # For now, just a basic implementation
        ability_id = action["id"]
        
        # Check energy cost
        if cat.energy < action.get("energy_cost", 0):
            return {
                "log": f"{cat.name} doesn't have enough energy for {ability_id}",
                "success": False
            }
        
        # Deduct energy
        cat.energy -= action.get("energy_cost", 0)
        
        # Basic ability effect (placeholder)
        target = next((enemy for enemy in self.state.enemies if enemy.current_hp > 0), None)
        if target:
            damage = self._calculate_damage(cat, target, action) * 1.5  # Abilities do 50% more damage
            target.current_hp = max(0, target.current_hp - damage)
            return {
                "log": f"{cat.name} uses {ability_id} on {target.name} for {damage} damage!",
                "success": True
            }
        
        return {"log": "No valid target", "success": False}

    def _calculate_damage(self, attacker: Cat, defender: Cat, action: Dict) -> int:
        """Calculate damage for an attack"""
        # Base damage calculation with defense scaling
        defense_factor = max(0.2, 1 - (defender.current_stats.defense / 100))
        base_damage = attacker.current_stats.attack * defense_factor
        
        # Apply random variance (±10%)
        variance = random.uniform(0.9, 1.1)
        
        # Apply critical hit
        is_crit = random.random() < attacker.current_stats.crit_rate
        crit_mult = attacker.current_stats.crit_damage if is_crit else 1.0
        
        # Apply type effectiveness if specified in action
        effectiveness = action.get("effectiveness", 1.0)
        
        # Calculate final damage with minimum of 1
        final_damage = max(1, int(base_damage * variance * crit_mult * effectiveness))
        
        return final_damage

    def get_current_cat(self) -> Cat:
        """Get the cat whose turn it currently is"""
        return self.turn_order[self.current_turn % len(self.turn_order)]

    def _process_status_effects(self, cat: Cat) -> None:
        """Process all active status effects on a cat"""
        for effect in cat.status_effects[:]:  # Copy list to allow removal during iteration
            if effect["type"] == "damage_over_time":
                # Calculate damage based on attacker's stats if available
                attacker_stats = effect.get("attacker_stats", None)
                if attacker_stats:
                    base_damage = attacker_stats.get("attack", 0) * 0.2  # 20% of attacker's attack
                    defense_factor = max(0.2, 1 - (cat.current_stats.defense / 100))
                    damage = int(base_damage * defense_factor)
                else:
                    damage = effect["damage_per_tick"]
                
                damage = max(1, damage)  # Minimum 1 damage
                cat.current_hp -= damage
                self.battle_log.append(f"{cat.name} took {damage} damage from {effect['name']}")
            
            # Process stat modifications
            if effect["type"] == "stat_modifier":
                for stat, value in effect["modifiers"].items():
                    if hasattr(cat.current_stats, stat):
                        current_value = getattr(cat.current_stats, stat)
                        setattr(cat.current_stats, stat, int(current_value * value))
            
            effect["duration"] -= 1
            if effect["duration"] <= 0:
                # Remove effect and restore stats if needed
                if effect["type"] == "stat_modifier":
                    for stat, value in effect["modifiers"].items():
                        if hasattr(cat.current_stats, stat):
                            current_value = getattr(cat.current_stats, stat)
                            setattr(cat.current_stats, stat, int(current_value / value))
                cat.status_effects.remove(effect)

    def _is_stunned(self, cat: Cat) -> bool:
        """Check if a cat is stunned"""
        return any(effect["effect"] == "stun" for effect in cat.status_effects)

    def _check_battle_end(self) -> bool:
        """Check if the battle has ended"""
        team1_alive = any(cat.current_hp > 0 for cat in self.team1)
        team2_alive = any(cat.current_hp > 0 for cat in self.team2)
        return not (team1_alive and team2_alive)

class CraftingRecipe:
    def __init__(self, recipe_data: Dict):
        self.id: str = recipe_data["id"]
        self.name: str = recipe_data["name"]
        self.category: str = recipe_data["category"]
        self.materials: Dict[str, int] = recipe_data["materials"]
        self.time: int = recipe_data["time"]
        self.success_rate: float = recipe_data["success_rate"]
        self.visuals: Dict = recipe_data["visuals"]
        
    def can_craft(self, player_materials: Dict[str, int]) -> bool:
        """Check if player has required materials"""
        for material, quantity in self.materials.items():
            if player_materials.get(material, 0) < quantity:
                return False
        return True

class CraftingSystem:
    def __init__(self):
        self.active_crafts: Dict[str, Dict] = {}  # player_id: {recipe_id: completion_time}
        self.recipes: Dict[str, CraftingRecipe] = {}
        
    def load_recipes(self, recipes_data: Dict) -> None:
        """Load crafting recipes from data"""
        for recipe_id, recipe_data in recipes_data.items():
            self.recipes[recipe_id] = CraftingRecipe(recipe_data)
            
    def start_craft(self, player_id: str, recipe_id: str) -> bool:
        """Start a crafting process if player has materials"""
        if recipe_id not in self.recipes:
            return False
            
        recipe = self.recipes[recipe_id]
        if player_id not in self.active_crafts:
            self.active_crafts[player_id] = {}
            
        # Check if already crafting this item
        if recipe_id in self.active_crafts[player_id]:
            return False
            
        self.active_crafts[player_id][recipe_id] = {
            "start_time": asyncio.get_event_loop().time(),
            "completion_time": recipe.time
        }
        return True
        
    def check_craft_completion(self, player_id: str) -> List[Dict]:
        """Check for completed crafts and return results"""
        completed = []
        if player_id in self.active_crafts:
            current_time = asyncio.get_event_loop().time()
            for recipe_id, craft_data in list(self.active_crafts[player_id].items()):
                if current_time >= craft_data["start_time"] + craft_data["completion_time"]:
                    recipe = self.recipes[recipe_id]
                    
                    # Calculate success chance with reputation bonus
                    reputation = game_state.get_player_reputation(player_id)
                    bonuses = reputation.get_shop_bonuses()
                    success_rate = min(1.0, recipe.success_rate * (1 + bonuses["daily_deals"]))
                    
                    # Determine if craft was successful
                    success = random.random() <= success_rate
                    
                    # Add bonus items on success
                    bonus_items = {}
                    if success:
                        # Chance for bonus items based on reputation
                        if random.random() < bonuses["additional_items"]:
                            bonus_items = {
                                "fish": random.randint(10, 50),
                                "gems": random.randint(1, 5)
                            }
                    
                    completed.append({
                        "recipe_id": recipe_id,
                        "success": success,
                        "bonus_items": bonus_items
                    })
                    del self.active_crafts[player_id][recipe_id]
        return completed

class ShopItem:
    def __init__(self, item_data: Dict):
        self.id: str = item_data["id"]
        self.name: str = item_data["name"]
        self.category: str = item_data["category"]
        self.base_price: Dict[str, int] = item_data["price"]
        self.stock: int = item_data.get("stock", -1)  # -1 means unlimited
        self.requirements: Dict = item_data.get("requirements", {})
        self.bundle_size: int = item_data.get("bundle_size", 1)
        self.bundle_discount: float = item_data.get("bundle_discount", 0.0)
        
    def get_price(self, player_reputation: PlayerReputation) -> Dict[str, int]:
        """Calculate final price with reputation bonuses"""
        price = {}
        bonuses = player_reputation.get_shop_bonuses()
        
        for currency, amount in self.base_price.items():
            # Apply reputation-based price reduction
            base_price = int(amount * (1 - bonuses["price_reduction"]))
            
            # Apply bundle discount if buying multiple
            if self.bundle_size > 1:
                # Enhanced bundle discount with reputation bonus
                enhanced_discount = self.bundle_discount * (1 + bonuses["discount_increase"])
                base_price = int(base_price * (1 - min(enhanced_discount, 0.9)))  # Cap at 90% discount
                
            # Apply daily deals bonus if this is a discounted item
            if self.bundle_discount > 0:
                base_price = int(base_price * (1 - bonuses["daily_deals"]))
                
            price[currency] = max(1, base_price)  # Ensure price is at least 1
            
        return price

class ShopSystem:
    def __init__(self):
        self.items: Dict[str, ShopItem] = {}
        self.daily_reset_time: int = 0  # Timestamp for next reset
        
    def load_items(self, items_data: Dict) -> None:
        """Load shop items from data"""
        for item_id, item_data in items_data.items():
            self.items[item_id] = ShopItem(item_data)
            
    def reset_daily_deals(self) -> None:
        """Reset daily deals and special offers"""
        # Reset stock for limited items
        for item in self.items.values():
            if item.stock > 0:  # Only reset items with limited stock
                # Base stock based on item rarity
                base_stock = {
                    "common": 5,
                    "uncommon": 3,
                    "rare": 2,
                    "epic": 1
                }.get(item.category, 1)
                
                # Apply random variation
                item.stock = max(1, base_stock + random.randint(-1, 1))
                
        # Apply random discounts to 3-5 random items
        num_discounts = random.randint(3, min(5, len(self.items)))
        discounted_items = random.sample(list(self.items.values()), num_discounts)
        
        for item in discounted_items:
            # Base discount based on item rarity
            base_discount = {
                "common": 0.1,
                "uncommon": 0.2,
                "rare": 0.3,
                "epic": 0.4
            }.get(item.category, 0.1)
            
            # Apply random variation
            discount = round(base_discount + random.uniform(-0.05, 0.05), 2)
            item.bundle_discount = min(max(0.1, discount), 0.5)  # Keep between 10-50%
            
            # Set bundle size based on rarity
            item.bundle_size = {
                "common": random.randint(3, 5),
                "uncommon": random.randint(2, 4),
                "rare": random.randint(1, 3),
                "epic": 1
            }.get(item.category, 1)
            
    def get_available_items(self, player_id: str) -> Dict[str, Dict]:
        """Get items available to a player based on reputation"""
        reputation = game_state.get_player_reputation(player_id)
        available_items = {}
        
        for item_id, item in self.items.items():
            # Check stock
            if item.stock == 0:
                continue
                
            # Check requirements
            if "reputation_level" in item.requirements:
                if reputation.level < item.requirements["reputation_level"]:
                    continue
                    
            # Calculate final price
            price = item.get_price(reputation)
            
            available_items[item_id] = {
                "name": item.name,
                "category": item.category,
                "price": price,
                "stock": item.stock,
                "bundle_size": item.bundle_size,
                "bundle_discount": item.bundle_discount
            }
            
        return available_items
        
    def purchase_item(self, player_id: str, item_id: str, quantity: int = 1) -> Dict[str, Union[bool, Dict[str, int]]]:
        """Process an item purchase and return success status with bonus rewards"""
        if item_id not in self.items:
            return {"success": False, "bonuses": {}}
            
        item = self.items[item_id]
        reputation = game_state.get_player_reputation(player_id)
        
        # Check stock
        if item.stock > 0 and quantity > item.stock:
            return {"success": False, "bonuses": {}}
            
        # Check requirements
        if "reputation_level" in item.requirements:
            if reputation.level < item.requirements["reputation_level"]:
                return {"success": False, "bonuses": {}}
                
        # Calculate total price
        price = item.get_price(reputation)
        total_price = {currency: amount * quantity for currency, amount in price.items()}
        
        # Deduct currency
        player_currency = game_state.get_player_currency(player_id)
        for currency, amount in total_price.items():
            if not player_currency.deduct(currency, amount):
                return {"success": False, "bonuses": {}}
                
        # Update stock
        if item.stock > 0:
            item.stock -= quantity
            
        # Update reputation
        game_state.update_player_reputation(player_id, total_price)
        
        # Calculate bonus rewards
        bonuses = reputation.get_shop_bonuses()
        bonus_rewards = {
            "fish": int(total_price.get("fish", 0) * bonuses["bonus_fish"]),
            "gems": int(total_price.get("gems", 0) * bonuses["bonus_gems"])
        }
        
        # Add bonus rewards to player's currency
        if bonus_rewards["fish"] > 0:
            player_currency.add("fish", bonus_rewards["fish"])
        if bonus_rewards["gems"] > 0:
            player_currency.add("gems", bonus_rewards["gems"])
            
        return {
            "success": True,
            "bonuses": bonus_rewards
        }

    def get_time_until_reset(self) -> int:
        """Get seconds remaining until next shop reset"""
        current_time = asyncio.get_event_loop().time()
        if current_time >= self.daily_reset_time:
            return 0
        return int(self.daily_reset_time - current_time)
        
    def format_time_until_reset(self) -> str:
        """Format time remaining until next shop reset in human-readable format"""
        seconds = self.get_time_until_reset()
        if seconds == 0:
            return "New deals available!"
            
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
        if seconds > 0 and hours == 0:  # Only show seconds if less than 1 hour
            parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
            
        return "New deals in " + ", ".join(parts)
        
    def get_current_deals(self) -> Dict[str, Dict]:
        """Get current discounted items and their deal information"""
        deals = {}
        for item in self.items.values():
            if item.bundle_discount > 0:
                deals[item.id] = {
                    "name": item.name,
                    "discount": item.bundle_discount,
                    "bundle_size": item.bundle_size,
                    "stock": item.stock
                }
        return deals

class PlayerCurrency:
    def __init__(self):
        self.fish: int = 0
        self.gems: int = 0
        
    def add(self, currency: str, amount: int) -> bool:
        """Add currency to player's balance"""
        if currency not in ["fish", "gems"]:
            return False
            
        setattr(self, currency, getattr(self, currency) + amount)
        return True
        
    def deduct(self, currency: str, amount: int) -> bool:
        """Deduct currency from player's balance"""
        if currency not in ["fish", "gems"]:
            return False
            
        current = getattr(self, currency)
        if current < amount:
            return False
            
        setattr(self, currency, current - amount)
        return True
        
    def get_balance(self) -> Dict[str, int]:
        """Get current currency balances"""
        return {
            "fish": self.fish,
            "gems": self.gems
        }

class GameState:
    def __init__(self):
        self.active_battles: Dict[str, Battle] = {}
        self.cat_cache: Dict[str, Dict] = {}
        self.player_reputations: Dict[str, PlayerReputation] = {}
        self.player_currencies: Dict[str, PlayerCurrency] = {}
        self.crafting_system = CraftingSystem()
        self.shop_system = ShopSystem()
        
    def get_player_currency(self, player_id: str) -> PlayerCurrency:
        """Get or create a player's currency balance"""
        if player_id not in self.player_currencies:
            self.player_currencies[player_id] = PlayerCurrency()
        return self.player_currencies[player_id]
        
    async def create_battle(self, battle_id: str, team1: List[Cat], team2: List[Cat], 
                          is_auto: bool = False) -> Battle:
        """Create and initialize a new battle"""
        battle = Battle(team1, team2, is_auto)
        battle.initialize_battle()
        self.active_battles[battle_id] = battle
        return battle
    
    def get_battle(self, battle_id: str) -> Optional[Battle]:
        """Get an active battle by ID"""
        return self.active_battles.get(battle_id)
    
    def end_battle(self, battle_id: str) -> None:
        """Clean up a finished battle"""
        if battle_id in self.active_battles:
            del self.active_battles[battle_id]

    def get_player_reputation(self, player_id: str) -> PlayerReputation:
        """Get or create a player's reputation"""
        if player_id not in self.player_reputations:
            self.player_reputations[player_id] = PlayerReputation()
        return self.player_reputations[player_id]

    def update_player_reputation(self, player_id: str, purchase_data: Dict) -> None:
        """Update player reputation after a purchase"""
        reputation = self.get_player_reputation(player_id)
        
        # Add XP based on purchase
        xp = 0
        if "fish" in purchase_data:
            xp += purchase_data["fish"] * 0.01
            reputation.total_spent["fish"] += purchase_data["fish"]
        if "gems" in purchase_data:
            xp += purchase_data["gems"] * 0.1
            reputation.total_spent["gems"] += purchase_data["gems"]
        
        reputation.add_xp(int(xp))

    def process_daily_login(self, player_id: str, current_date: str) -> Dict[str, int]:
        """Process daily login and return rewards"""
        reputation = self.get_player_reputation(player_id)
        rewards = reputation.update_login_streak(current_date)
        
        # Add rewards to player's currency
        player_currency = self.get_player_currency(player_id)
        if rewards["fish"] > 0:
            player_currency.add("fish", rewards["fish"])
        if rewards["gems"] > 0:
            player_currency.add("gems", rewards["gems"])
            
        # Check if shop needs reset
        current_time = asyncio.get_event_loop().time()
        if current_time >= self.shop_system.daily_reset_time:
            self.shop_system.reset_daily_deals()
            # Set next reset time to 24 hours from now
            self.shop_system.daily_reset_time = current_time + (24 * 60 * 60)
            
        return rewards

# Initialize global game state
game_state = GameState()
