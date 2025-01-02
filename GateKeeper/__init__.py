"""
GateKeeper - A sophisticated security system for protecting your Discord server! 🔒
"""
import json
from pathlib import Path

from .gatekeeper import GateKeeper

with open(Path(__file__).parent / "info.json") as fp:
    __red_end_user_data_statement__ = json.load(fp)["end_user_data_statement"]

async def setup(bot):
    await bot.add_cog(GateKeeper(bot))
