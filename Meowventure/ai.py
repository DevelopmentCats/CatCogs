from typing import Dict, List, Tuple, Optional
import random
from dataclasses import dataclass
import math
import json
import requests
from transformers import pipeline
import os
import asyncio

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

class HuggingFaceAPI:
    def __init__(self, api_key: Optional[str] = None):
        """Initialize HuggingFace API connection"""
        self.api_key = api_key or os.getenv("HUGGINGFACE_API_KEY")
        if not self.api_key:
            raise ValueError("HuggingFace API key not found. Set HUGGINGFACE_API_KEY environment variable.")
        
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        
        # Initialize local pipeline for fallback
        try:
            self.local_model = pipeline(
                "text-generation",
                model=MODELS["fallback"]["name"],
                device=-1  # Use CPU
            )
        except Exception as e:
            print(f"Warning: Could not initialize local model: {e}")
            self.local_model = None

    async def get_decision(self, prompt: str, context_type: str = "primary") -> Dict:
        """Get AI decision from HuggingFace"""
        model_config = MODELS.get(context_type, MODELS["primary"])
        
        try:
            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_length": model_config["max_length"],
                    "temperature": model_config["temp"],
                    "top_p": 0.9,
                    "return_full_text": False,
                    "do_sample": True
                }
            }
            
            response = requests.post(
                f"{HUGGINGFACE_API_URL}{model_config['name']}",
                headers=self.headers,
                json=payload
            )
            
            if response.status_code == 200:
                return self._parse_response(response.json(), context_type)
            else:
                return self._fallback_decision(prompt, context_type)
                
        except Exception as e:
            print(f"HuggingFace API error: {e}")
            return self._fallback_decision(prompt, context_type)

    def _parse_response(self, response: List[Dict], context_type: str) -> Dict:
        """Parse and validate model response"""
        try:
            # Extract the generated text
            generated_text = response[0]["generated_text"]
            
            # Try to find and parse JSON object in response
            import re
            json_match = re.search(r'\{.*\}', generated_text, re.DOTALL)
            if json_match:
                decision_data = json.loads(json_match.group())
                return {
                    "action_choice": decision_data.get("action_choice", ""),
                    "reasoning": decision_data.get("reasoning", []),
                    "confidence": decision_data.get("confidence", 0.8),
                    "model_type": context_type
                }
        except Exception as e:
            print(f"Response parsing error: {e}")
        
        return self._fallback_decision("", context_type)

    def _fallback_decision(self, prompt: str, context_type: str) -> Dict:
        """Use local model as fallback"""
        if self.local_model:
            try:
                result = self.local_model(prompt)
                return {
                    "decision": result[0]["generated_text"],
                    "confidence": 0.5,
                    "fallback": True,
                    "model_type": context_type
                }
            except Exception as e:
                print(f"Local model error: {e}")
        
        # Ultimate fallback: random decision
        return {
            "decision": "random",
            "confidence": 0.5,
            "fallback": True,
            "model_type": context_type
        }

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

    def _create_decision_prompt(self, state: BattleState, personality: PersonalityProfile, 
                              actions: List[Dict]) -> Dict[str, str]:
        """Create specialized prompts for different aspects of decision making"""
        
        # Base battle situation prompt
        battle_context = f"""
        [Battle State Analysis]
        Turn: {state.turn_number}
        
        Active Cat:
        - Name: {state.active_cat.name}
        - Type: {state.active_cat.affinity}
        - Health: {state.active_cat.current_hp}/{state.active_cat.current_stats.hp}
        - Energy: {state.active_cat.energy}/100
        - Status Effects: {', '.join(effect['name'] for effect in state.active_cat.status_effects) or 'None'}
        
        Team Status:
        Allies: {', '.join(f'{cat.name} ({int(cat.current_hp/cat.current_stats.hp * 100)}% HP)' for cat in state.allies)}
        Enemies: {', '.join(f'{cat.name} ({int(cat.current_hp/cat.current_stats.hp * 100)}% HP)' for cat in state.enemies)}
        
        Recent Actions:
        {chr(10).join(f'- {action}' for action in state.battle_log[-3:] if state.battle_log)}
        """

        # Personality-focused prompt
        personality_context = f"""
        [Character Analysis]
        Personality: {personality.type}
        Battle Style: {personality.battle_style}
        
        Key Traits:
        - Combat Style: {'Aggressive' if personality.weights['damage'] > 1.0 else 'Defensive'}
        - Team Role: {'Support-focused' if personality.weights['support'] > 1.0 else 'Damage-focused'}
        - Risk Profile: {'Risk-taker' if 'risk_taking' in personality.modifiers else 'Cautious'}
        
        Personality Quirks:
        {chr(10).join(f'- {key}: {value}' for key, value in personality.modifiers.items())}
        """

        # Tactical analysis prompt
        tactical_context = f"""
        [Tactical Analysis]
        Available Actions:
        {chr(10).join(f'''- {action['name']}:
           Type: {action['type']}
           Energy Cost: {action['energy_cost']}
           {'Ability ID: ' + action['id'] if 'id' in action else ''}''' for action in actions)}
        
        Strategic Considerations:
        - Team HP Average: {int(sum(cat.current_hp/cat.current_stats.hp * 100 for cat in state.allies)/len(state.allies))}%
        - Enemy HP Average: {int(sum(cat.current_hp/cat.current_stats.hp * 100 for cat in state.enemies)/len(state.enemies))}%
        - Turn Position: {'Early' if state.turn_number < 3 else 'Mid' if state.turn_number < 7 else 'Late'} game
        """

        # Decision request prompt
        decision_prompt = f"""
        Based on the above analysis, select the optimal action that best fits the character's personality
        and tactical situation. Consider:
        1. Personality alignment with action type
        2. Current battle state and team needs
        3. Energy efficiency and strategic value
        4. Status effect synergies
        5. Team composition and role fulfillment
        
        Respond with a JSON object in the following format:
        {{
            "action_choice": "name_of_chosen_action",
            "reasoning": [
                "Primary strategic reason",
                "Personality consideration",
                "Tactical advantage"
            ],
            "confidence": 0.0-1.0,
            "alternative_considerations": [
                "Other action that was considered",
                "Why it wasn't chosen"
            ]
        }}
        """

        return {
            "primary": f"{battle_context}\n\n{tactical_context}\n\n{decision_prompt}",
            "personality": f"{personality_context}\n\n{battle_context}\n\n{decision_prompt}",
            "tactical": f"{tactical_context}\n\n{battle_context}\n\n{decision_prompt}"
        }

    async def get_action(self, battle_state: BattleState, personality: PersonalityProfile) -> Dict:
        """Determine the best action using specialized AI models"""
        possible_actions = self._get_possible_actions(battle_state.active_cat)
        
        # Get specialized prompts
        prompts = self._create_decision_prompt(battle_state, personality, possible_actions)
        
        # Get decisions from different models
        decisions = await asyncio.gather(
            self.ai_api.get_decision(prompts["primary"], "primary"),
            self.ai_api.get_decision(prompts["personality"], "personality"),
            self.ai_api.get_decision(prompts["tactical"], "tactical")
        )
        
        # Combine and process decisions
        scored_actions = self._process_multiple_decisions(
            decisions, possible_actions, battle_state, personality
        )
        
        # Return final decision
        return self._select_action(scored_actions)

    def _process_multiple_decisions(self, decisions: List[Dict], possible_actions: List[Dict],
                                  state: BattleState, personality: PersonalityProfile) -> List[ActionScore]:
        """Process and combine decisions from multiple models"""
        scored_actions = []
        
        # Weight for each model type
        model_weights = {
            "primary": 1.0,
            "personality": 0.8,
            "tactical": 0.9
        }
        
        # Process each decision
        for decision in decisions:
            model_type = decision.get("model_type", "primary")
            weight = model_weights[model_type]
            
            # Find matching action
            chosen_action = next(
                (a for a in possible_actions if a["name"] == decision["action_choice"]),
                possible_actions[0]
            )
            
            # Calculate base score
            base_score = self._evaluate_action(chosen_action, state, personality)
            confidence = decision.get("confidence", 0.8)
            
            # Apply model-specific weight
            final_score = base_score * confidence * weight
            
            scored_actions.append(ActionScore(
                action=chosen_action,
                score=final_score,
                reasoning=[f"[{model_type.title()}] {reason}" for reason in decision.get("reasoning", [])]
            ))
        
        return scored_actions

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

    def _select_action(self, scored_actions: List[ActionScore]) -> Dict:
        """Select final action based on scores and difficulty"""
        scored_actions.sort(key=lambda x: x.score, reverse=True)
        
        # Apply difficulty-based randomness
        if random.random() > self.difficulty_modifiers[self.difficulty]:
            return random.choice(scored_actions[:3]).action
            
        return scored_actions[0].action

# Initialize global AI instance
battle_ai = BattleAI()
