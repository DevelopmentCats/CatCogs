from typing import Dict, List, Tuple, Optional
from .game import Cat
import random
from dataclasses import dataclass
import math
import json
import requests
from transformers import pipeline
import os
import asyncio

class HuggingFaceAPI:
    """Wrapper for Hugging Face API calls"""
    
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {os.getenv('HUGGINGFACE_API_KEY')}"
        }
        self.pipelines = {
            "text-generation": pipeline("text-generation"),
            "text-classification": pipeline("text-classification")
        }
    
    async def generate_text(self, model: str, prompt: str, temperature: float, max_length: int) -> str:
        """Generate text using specified model"""
        try:
            generator = self.pipelines["text-generation"]
            result = generator(
                prompt,
                model=model,
                temperature=temperature,
                max_length=max_length
            )
            return result[0]["generated_text"]
        except Exception as e:
            print(f"Error generating text: {e}")
            return ""
    
    async def classify_text(self, text: str) -> Dict[str, float]:
        """Classify text sentiment"""
        try:
            classifier = self.pipelines["text-classification"]
            result = classifier(text)
            return {r["label"]: r["score"] for r in result}
        except Exception as e:
            print(f"Error classifying text: {e}")
            return {}

# Constants for Hugging Face
HUGGINGFACE_API_URL = "https://api-inference.huggingface.co/models/"

# Models specialized for different aspects of decision making
MODELS = {
    "primary": {
        "name": "gpt2-medium",  # Good for general text generation and decision making
        "temp": 0.7,
        "max_length": 150
    },
    "tactical": {
        "name": "microsoft/DialoGPT-medium",  # Good for contextual understanding
        "temp": 0.5,
        "max_length": 100
    },
    "personality": {
        "name": "EleutherAI/gpt-neo-1.3B",  # Good for role-playing and personality
        "temp": 0.8,
        "max_length": 200
    },
    "fallback": {
        "name": "distilgpt2",  # Lightweight fallback
        "temp": 0.7,
        "max_length": 100
    }
}

@dataclass
class BattleState:
    """Current state of the battle for AI decision making"""
    active_cat: 'Cat'  # The cat whose turn it is
    allies: List['Cat']  # Other cats on same team
    enemies: List['Cat']  # Enemy cats
    turn_number: int
    battle_log: List[str]

    def to_context(self) -> str:
        """Convert battle state to a context string for AI"""
        context = f"""
        Active Cat: {self.active_cat.name} ({self.active_cat.affinity}) - HP: {self.active_cat.current_hp}/{self.active_cat.current_stats.hp}
        Allies: {', '.join(f'{cat.name} (HP: {cat.current_hp}/{cat.current_stats.hp})' for cat in self.allies)}
        Enemies: {', '.join(f'{cat.name} (HP: {cat.current_hp}/{cat.current_stats.hp})' for cat in self.enemies)}
        Turn: {self.turn_number}
        Recent Actions: {'; '.join(self.battle_log[-3:] if self.battle_log else [])}
        """
        return context

@dataclass
class ActionScore:
    """Score and reasoning for a potential action"""
    action: Dict
    score: float
    reasoning: List[str]

class PersonalityProfile:
    def __init__(self, personality_type: str, battle_style: str):
        self.type = personality_type
        self.battle_style = battle_style
        
        # Base weights for different action types
        self.weights = {
            "aggressive": {
                "damage": 1.5,
                "support": 0.7,
                "defensive": 0.5
            },
            "defensive": {
                "damage": 0.7,
                "support": 1.0,
                "defensive": 1.5
            },
            "strategic": {
                "damage": 1.0,
                "support": 1.2,
                "defensive": 1.0
            },
            "supportive": {
                "damage": 0.6,
                "support": 1.5,
                "defensive": 1.2
            }
        }[battle_style]
        
        self.modifiers = self._get_personality_modifiers(personality_type)

    def _get_personality_modifiers(self, personality_type: str) -> Dict:
        """Get personality-specific decision modifiers"""
        modifiers = {
            "curious": {
                "try_new_moves": 1.2,
                "risk_taking": 1.1
            },
            "mysterious": {
                "stealth_moves": 1.3,
                "status_effects": 1.2
            },
            "noble": {
                "team_support": 1.2,
                "finishing_moves": 1.1
            }
        }
        return modifiers.get(personality_type, {})

    def to_prompt(self) -> str:
        """Convert personality to prompt context"""
        return f"""
        Personality: {self.type}
        Battle Style: {self.battle_style}
        Tendencies:
        - {'Aggressive' if self.weights['damage'] > 1.0 else 'Defensive'} combat approach
        - {'Supportive' if self.weights['support'] > 1.0 else 'Independent'} team play
        - {'Risk-taking' if 'risk_taking' in self.modifiers else 'Cautious'} decision making
        """

class BattleAI:
    def __init__(self, difficulty: str = "normal"):
        self.difficulty = difficulty
        self.difficulty_modifiers = {
            "easy": 0.8,
            "normal": 1.0,
            "hard": 1.2,
            "expert": 1.5
        }
        
        # Initialize HuggingFace API
        self.ai_api = HuggingFaceAPI()
        
        # Learning components
        self.move_success_rate: Dict[str, Dict] = {}
        self.opponent_patterns: Dict[str, List] = {}
        self.strategy_memory: Dict[str, Dict] = {}

    async def get_action(self, state: BattleState, personality: PersonalityProfile) -> Dict:
        """Get AI decision based on battle state and personality"""
        # Get possible actions
        actions = self._get_possible_actions(state.active_cat)
        
        # Score each action based on multiple factors
        scored_actions = []
        for action in actions:
            score = self._evaluate_action(action, state, personality)
            scored_actions.append(score)
        
        # Sort by score and select best action
        scored_actions.sort(key=lambda x: x.score, reverse=True)
        
        # Apply difficulty-based randomness
        if random.random() > self.difficulty_modifiers[self.difficulty]:
            # Sometimes choose a random action from top 3
            return random.choice(scored_actions[:3]).action
            
        return scored_actions[0].action

    def _get_possible_actions(self, cat: 'Cat') -> List[Dict]:
        """Get all possible actions for a cat"""
        actions = []
        
        # Basic attack is always available
        actions.append({
            "type": "basic_attack",
            "name": "Basic Attack",
            "energy_cost": 0
        })
        
        # Add available abilities
        for ability_id in cat.abilities:
            if self._can_use_ability(cat, ability_id):
                actions.append({
                    "type": "ability",
                    "id": ability_id,
                    "name": ability_id  # This would be replaced with actual ability name
                })
        
        return actions

    def _can_use_ability(self, cat: 'Cat', ability_id: str) -> bool:
        """Check if an ability can be used"""
        # This would check energy costs, cooldowns, etc.
        return True  # Placeholder

    def _evaluate_action(self, action: Dict, state: BattleState, personality: PersonalityProfile) -> ActionScore:
        """Evaluate an action's potential value"""
        base_score = 0.0
        reasoning = []

        # Get base score based on action type
        if action["type"] == "basic_attack":
            base_score = self._evaluate_attack(state)
        elif action["type"] == "ability":
            base_score = self._evaluate_ability(action, state)

        # Apply personality modifiers
        score = self._apply_personality_modifiers(base_score, action, personality, reasoning)
        
        # Consider tactical factors
        score = self._apply_tactical_modifiers(score, action, state, reasoning)
        
        # Apply learning from past battles
        score = self._apply_learned_knowledge(score, action, state, reasoning)

        return ActionScore(action=action, score=score, reasoning=reasoning)

    def _evaluate_attack(self, state: BattleState) -> float:
        """Evaluate basic attack value"""
        score = 50.0  # Base score for attacks
        
        # Consider target HP percentages
        lowest_hp_percent = min(cat.current_hp / cat.current_stats.hp for cat in state.enemies)
        if lowest_hp_percent < 0.3:
            score += 20  # Prioritize finishing off weak enemies
            
        return score

    def _evaluate_ability(self, action: Dict, state: BattleState) -> float:
        """Evaluate ability value"""
        score = 70.0  # Abilities generally better than basic attacks
        
        # This would be expanded based on actual ability effects
        # For now, just a basic implementation
        return score

    def _apply_personality_modifiers(self, base_score: float, action: Dict, 
                                   personality: PersonalityProfile, reasoning: List[str]) -> float:
        """Apply personality-based modifiers to action score"""
        score = base_score
        
        # Apply battle style weights
        if action["type"] == "basic_attack":
            score *= personality.weights["damage"]
            reasoning.append(f"Applied {personality.battle_style} battle style modifier")
            
        # Apply personality-specific modifiers
        for modifier, value in personality.modifiers.items():
            if self._is_modifier_applicable(modifier, action):
                score *= value
                reasoning.append(f"Applied {modifier} personality modifier")
                
        return score

    def _apply_tactical_modifiers(self, base_score: float, action: Dict, 
                                state: BattleState, reasoning: List[str]) -> float:
        """Apply tactical situation modifiers"""
        score = base_score
        
        # Consider team HP
        ally_hp_percent = sum(cat.current_hp for cat in state.allies) / sum(cat.current_stats.hp for cat in state.allies)
        if ally_hp_percent < 0.5:
            score *= 1.2  # Prioritize defensive/healing actions
            reasoning.append("Team HP low, prioritizing defensive actions")
            
        # Consider type advantages
        if self._has_type_advantage(state.active_cat, state.enemies):
            score *= 1.3
            reasoning.append("Has type advantage")
            
        return score

    def _apply_learned_knowledge(self, base_score: float, action: Dict, 
                               state: BattleState, reasoning: List[str]) -> float:
        """Apply knowledge from past battles"""
        score = base_score
        
        # Consider past success rate
        if action["type"] == "ability" and action["id"] in self.move_success_rate:
            success_rate = self.move_success_rate[action["id"]]["success_rate"]
            score *= (0.5 + success_rate)  # Scale based on past success
            reasoning.append(f"Adjusted for {success_rate:.2f} past success rate")
            
        return score

    def _is_modifier_applicable(self, modifier: str, action: Dict) -> bool:
        """Check if a personality modifier applies to an action"""
        # This would be expanded based on actual modifier types
        return True  # Placeholder

    def _has_type_advantage(self, cat: 'Cat', enemies: List['Cat']) -> bool:
        """Check for type advantage"""
        # This would check affinity advantages
        return False  # Placeholder

    def update_learning(self, action: Dict, success: bool, battle_state: BattleState) -> None:
        """Update AI learning based on action results"""
        if action["type"] == "ability":
            ability_id = action["id"]
            if ability_id not in self.move_success_rate:
                self.move_success_rate[ability_id] = {"uses": 0, "successes": 0}
            
            self.move_success_rate[ability_id]["uses"] += 1
            if success:
                self.move_success_rate[ability_id]["successes"] += 1
            
            # Calculate success rate
            uses = self.move_success_rate[ability_id]["uses"]
            successes = self.move_success_rate[ability_id]["successes"]
            self.move_success_rate[ability_id]["success_rate"] = successes / uses

# Initialize global AI instance
battle_ai = BattleAI()
