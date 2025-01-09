from typing import Dict, List, Optional, Union
import random
import math
import asyncio
from dataclasses import dataclass
from .ai import BattleAI, BattleState, PersonalityProfile

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
        # Base damage calculation
        base_damage = attacker.current_stats.attack - (defender.current_stats.defense * 0.5)
        
        # Apply random variance (±10%)
        variance = random.uniform(0.9, 1.1)
        
        # Apply critical hit
        is_crit = random.random() < attacker.current_stats.crit_rate
        crit_mult = attacker.current_stats.crit_damage if is_crit else 1.0
        
        # Calculate final damage
        final_damage = max(1, int(base_damage * variance * crit_mult))
        
        return final_damage

    def get_current_cat(self) -> Cat:
        """Get the cat whose turn it currently is"""
        return self.turn_order[self.current_turn % len(self.turn_order)]

    def _process_status_effects(self, cat: Cat) -> None:
        """Process all active status effects on a cat"""
        for effect in cat.status_effects[:]:  # Copy list to allow removal during iteration
            if effect["type"] == "damage_over_time":
                damage = effect["damage_per_tick"]
                cat.current_hp -= damage
                self.battle_log.append(f"{cat.name} took {damage} damage from {effect['name']}")
            
            effect["duration"] -= 1
            if effect["duration"] <= 0:
                cat.status_effects.remove(effect)

    def _is_stunned(self, cat: Cat) -> bool:
        """Check if a cat is stunned"""
        return any(effect["effect"] == "stun" for effect in cat.status_effects)

    def _check_battle_end(self) -> bool:
        """Check if the battle has ended"""
        team1_alive = any(cat.current_hp > 0 for cat in self.team1)
        team2_alive = any(cat.current_hp > 0 for cat in self.team2)
        return not (team1_alive and team2_alive)

class GameState:
    def __init__(self):
        self.active_battles: Dict[str, Battle] = {}
        self.cat_cache: Dict[str, Dict] = {}
        
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

# Initialize global game state
game_state = GameState()
