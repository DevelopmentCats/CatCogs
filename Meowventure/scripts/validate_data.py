import json
from typing import Dict, Set, List, Tuple
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher

class DataValidator:
    def __init__(self):
        # Get the project root directory (parent of scripts folder)
        self.root_path = Path(__file__).parent.parent
        self.data_path = self.root_path / "data"
        self.results_path = self.root_path / "validation_results"
        self.cats_file = self.data_path / "cats.json"
        self.abilities_file = self.data_path / "abilities.json"
        
        # Create results directory if it doesn't exist
        self.results_path.mkdir(exist_ok=True)
        
        # Load data
        self.cats_data = self._load_json(self.cats_file)
        self.abilities_data = self._load_json(self.abilities_file)

    def _load_json(self, file_path: Path) -> dict:
        """Load and parse JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Error: File not found at {file_path}")
            return {}
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {file_path}: {e}")
            return {}
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            return {}

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity ratio between two strings."""
        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()

    def find_duplicate_cats(self) -> List[Dict[str, List[str]]]:
        """Find duplicate and similar cats."""
        duplicates = []
        cats = self.cats_data.get("cats", [])
        
        # Check for exact ID duplicates
        id_counts = {}
        for cat in cats:
            cat_id = cat.get("id")
            if cat_id in id_counts:
                id_counts[cat_id].append(cat.get("name"))
            else:
                id_counts[cat_id] = [cat.get("name")]
        
        exact_duplicates = {id_: names for id_, names in id_counts.items() if len(names) > 1}
        if exact_duplicates:
            duplicates.append({"type": "exact", "duplicates": exact_duplicates})

        # Check for similar names/descriptions
        similar_cats = []
        for i, cat1 in enumerate(cats):
            for cat2 in cats[i+1:]:
                name_similarity = self._calculate_similarity(cat1.get("name", ""), cat2.get("name", ""))
                desc_similarity = self._calculate_similarity(cat1.get("description", ""), cat2.get("description", ""))
                
                if name_similarity > 0.8 or desc_similarity > 0.8:
                    similar_cats.append({
                        "cat1": f"{cat1.get('id')} ({cat1.get('name')})",
                        "cat2": f"{cat2.get('id')} ({cat2.get('name')})",
                        "name_similarity": f"{name_similarity:.2%}",
                        "desc_similarity": f"{desc_similarity:.2%}"
                    })
        
        if similar_cats:
            duplicates.append({"type": "similar", "duplicates": similar_cats})
        
        return duplicates

    def find_duplicate_abilities(self) -> List[Dict[str, List[str]]]:
        """Find exact duplicate abilities by comparing effects."""
        duplicates = []
        abilities = self.abilities_data.get("abilities", {})
        
        # Create dictionary to store ability signatures
        ability_signatures = {}
        
        for ability_id, ability in abilities.items():
            # Create a signature from the ability's core properties
            signature = json.dumps({
                "damage_multiplier": ability.get("damage_multiplier"),
                "effect": ability.get("effect"),
                "duration": ability.get("duration"),
                "cooldown": ability.get("cooldown")
            }, sort_keys=True)
            
            if signature in ability_signatures:
                ability_signatures[signature].append(ability_id)
            else:
                ability_signatures[signature] = [ability_id]
        
        # Find abilities with identical signatures
        duplicate_abilities = {
            abilities[ids[0]]["name"]: ids 
            for signature, ids in ability_signatures.items() 
            if len(ids) > 1
        }
        
        if duplicate_abilities:
            duplicates.append({"type": "exact", "duplicates": duplicate_abilities})
        
        return duplicates

    def save_validation_results(self, results: Dict) -> Path:
        """Save validation results to a numbered file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Find the next available number
        number = 1
        while True:
            filename = f"validation_results_{timestamp}_{number}.json"
            file_path = self.results_path / filename
            if not file_path.exists():
                break
            number += 1
            
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)
            
        return file_path

    def run_full_validation(self) -> Tuple[bool, Dict]:
        """Run all validations and return results."""
        results = {
            "missing_abilities": list(self.find_missing_ability_definitions()),
            "unused_abilities": list(self.find_unused_abilities()),
            "ability_structure_errors": self.validate_ability_structure(),
            "cat_validation_errors": self.validate_cats(),
            "duplicate_cats": self.find_duplicate_cats(),
            "duplicate_abilities": self.find_duplicate_abilities(),
            "status_effect_errors": self.validate_status_effects()
        }
        
        is_valid = all(
            not errors for errors in results.values() 
            if not isinstance(errors, list) or not errors
        )
        return is_valid, results

    def get_cat_abilities(self) -> Set[str]:
        """Get all abilities referenced in cats.json."""
        abilities = set()
        for cat in self.cats_data.get("cats", []):
            cat_abilities = cat.get("abilities", [])
            abilities.update(cat_abilities)
        return abilities

    def get_defined_abilities(self) -> Set[str]:
        """Get all abilities defined in abilities.json."""
        return set(self.abilities_data.get("abilities", {}).keys())

    def find_missing_ability_definitions(self) -> Set[str]:
        """Find abilities used by cats but not defined in abilities.json."""
        cat_abilities = self.get_cat_abilities()
        defined_abilities = self.get_defined_abilities()
        return cat_abilities - defined_abilities

    def find_unused_abilities(self) -> Set[str]:
        """Find abilities defined but not used by any cats."""
        cat_abilities = self.get_cat_abilities()
        defined_abilities = self.get_defined_abilities()
        return defined_abilities - cat_abilities

    def validate_ability_structure(self) -> List[str]:
        """Validate the structure of each ability definition."""
        errors = []
        required_fields = {"name", "description", "effect"}
        
        for ability_id, ability in self.abilities_data.get("abilities", {}).items():
            missing_fields = required_fields - set(ability.keys())
            if missing_fields:
                errors.append(f"Ability '{ability_id}' missing required fields: {missing_fields}")
            
            # Check for valid animation format (if present)
            if "animation" in ability:
                anim = ability["animation"]
                if not isinstance(anim, str) or anim.count("→") != 2:
                    errors.append(f"Ability '{ability_id}' has invalid animation format")
        
        return errors

    def validate_cats(self) -> List[str]:
        """Validate cat definitions."""
        errors = []
        required_fields = {"id", "name", "rarity", "description", "personality", "abilities", "stats", "role", "emoji"}
        valid_rarities = {"common", "uncommon", "rare", "epic", "legendary"}
        
        for cat in self.cats_data.get("cats", []):
            # Check required fields
            missing_fields = required_fields - set(cat.keys())
            if missing_fields:
                errors.append(f"Cat '{cat.get('id', 'UNKNOWN')}' missing required fields: {missing_fields}")
            
            # Check rarity
            if cat.get("rarity") not in valid_rarities:
                errors.append(f"Cat '{cat.get('id')}' has invalid rarity: {cat.get('rarity')}")
            
            # Check stats structure
            stats = cat.get("stats", {})
            if not all(stat in stats for stat in ["attack", "defense", "speed"]):
                errors.append(f"Cat '{cat.get('id')}' has invalid stats structure")

        return errors

    def validate_status_effects(self) -> List[str]:
        """Validate status effects and their references in abilities."""
        errors = []
        required_status_fields = {"name", "description", "effects", "duration"}
        defined_status_effects = set(self.abilities_data.get("status_effects", {}).keys())
        referenced_status_effects = set()

        # Collect all status effects referenced in abilities
        for ability_id, ability in self.abilities_data.get("abilities", {}).items():
            effect = ability.get("effect", {})
            # Check direct status references
            if "status" in effect:
                referenced_status_effects.add(effect["status"])
            
            # Check for status-related effects
            for key in effect.keys():
                if "status" in key.lower() and isinstance(effect[key], str):
                    referenced_status_effects.add(effect[key])

        # Check for missing status effect definitions
        missing_status_effects = referenced_status_effects - defined_status_effects
        if missing_status_effects:
            errors.append(f"Missing status effect definitions: {sorted(missing_status_effects)}")

        # Validate structure of defined status effects
        status_effects = self.abilities_data.get("status_effects", {})
        for status_id, status in status_effects.items():
            # Check required fields
            missing_fields = required_status_fields - set(status.keys())
            if missing_fields:
                errors.append(f"Status effect '{status_id}' missing required fields: {missing_fields}")
            
            # Validate effects field contains actual effects
            if "effects" in status and not status["effects"]:
                errors.append(f"Status effect '{status_id}' has empty effects")
            
            # Validate duration is a positive number
            if "duration" in status and not isinstance(status["duration"], (int, float)) or status.get("duration", 0) <= 0:
                errors.append(f"Status effect '{status_id}' has invalid duration")

        return errors

def main():
    try:
        validator = DataValidator()
        is_valid, results = validator.run_full_validation()
        
        # Save results
        results_file = validator.save_validation_results(results)
        
        print("\n=== Data Validation Results ===\n")
        print(f"Data Path: {validator.data_path}")
        print(f"Results saved to: {results_file}\n")
        
        if results["missing_abilities"]:
            print("❌ Missing Ability Definitions:")
            for ability in sorted(results["missing_abilities"]):
                print(f"  - {ability}")
        else:
            print("✅ All cat abilities are properly defined")
        
        if results["unused_abilities"]:
            print("\n❌ Unused Ability Definitions:")
            for ability in sorted(results["unused_abilities"]):
                print(f"  - {ability}")
        else:
            print("✅ All defined abilities are used by cats")
        
        if results["ability_structure_errors"]:
            print("\n❌ Ability Structure Errors:")
            for error in results["ability_structure_errors"]:
                print(f"  - {error}")
        else:
            print("✅ All ability definitions are properly structured")
        
        if results["cat_validation_errors"]:
            print("\n❌ Cat Validation Errors:")
            for error in results["cat_validation_errors"]:
                print(f"  - {error}")
        else:
            print("✅ All cat definitions are properly structured")
        
        if results["duplicate_cats"]:
            print("\n❌ Duplicate/Similar Cats Found:")
            for dup_type in results["duplicate_cats"]:
                if dup_type["type"] == "exact":
                    for cat_id, names in dup_type["duplicates"].items():
                        print(f"  - Exact duplicate ID '{cat_id}' used by: {', '.join(names)}")
                else:
                    for pair in dup_type["duplicates"]:
                        print(f"  - Similar cats: {pair['cat1']} and {pair['cat2']}")
                        print(f"    Name similarity: {pair['name_similarity']}")
                        print(f"    Description similarity: {pair['desc_similarity']}")
        else:
            print("✅ No duplicate cats found")
            
        if results["duplicate_abilities"]:
            print("\n❌ Similar Abilities Found:")
            for dup_type in results["duplicate_abilities"]:
                for pair in dup_type["duplicates"]:
                    print(f"  - Similar abilities: {pair['ability1']} and {pair['ability2']}")
                    print(f"    Description similarity: {pair['desc_similarity']}")
                    print(f"    Effect similarity: {pair['effect_similarity']}")
        else:
            print("✅ No similar abilities found")
        
        if results["status_effect_errors"]:
            print("\n❌ Status Effect Validation Errors:")
            for error in results["status_effect_errors"]:
                print(f"  - {error}")
        else:
            print("✅ All status effects are properly defined and referenced")
        
        print(f"\nOverall Validation: {'✅ PASSED' if is_valid else '❌ FAILED'}")
        
    except Exception as e:
        print(f"Error during validation: {e}")
        return 1
    
    return 0 if is_valid else 1

if __name__ == "__main__":
    exit(main()) 