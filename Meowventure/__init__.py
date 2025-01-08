"""
Meowventure - A cat collection and battle game for Discord
Copyright (C) 2023 DeveloperCats
"""
import json
from pathlib import Path

from redbot.core.bot import Red
from redbot.core.errors import CogLoadError

from .meowventure import Meowventure

async def setup(bot: Red) -> None:
    """Load Meowventure cog."""
    # Check for required data files
    required_files = ["cats.json", "items.json", "abilities.json", "shop.json"]
    data_path = Path(__file__).parent / "data"
    
    missing_files = []
    for file in required_files:
        if not (data_path / file).exists():
            missing_files.append(file)
    
    if missing_files:
        raise CogLoadError(
            f"Meowventure is missing required data files: {', '.join(missing_files)}\n"
            f"Please ensure all required files are in the /data directory."
        )
    
    # Validate JSON files
    try:
        for file in required_files:
            with open(data_path / file, "r", encoding='utf-8') as f:
                json.load(f)
    except json.JSONDecodeError as e:
        raise CogLoadError(
            f"Invalid JSON in data files: {str(e)}\n"
            f"Please ensure all JSON files are properly formatted."
        )
    
    cog = Meowventure(bot)
    await bot.add_cog(cog) 