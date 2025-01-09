"""
Meowventure - A fun text-based adventure game for Discord! 🐱
"""
import json
from pathlib import Path

from .game import Meowventure

with open(Path(__file__).parent / "info.json") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]

async def setup(bot):
    await bot.add_cog(Meowventure(bot))
