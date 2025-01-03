"""
😼 ServerSage - Your PURRFECTLY CHAOTIC Discord Companion!
Created by DevelopmentCats with EXTREME FELINE PRECISION 🐱

A Red-DiscordBot cog that POUNCES on server organization problems!
"""

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement
from pathlib import Path
from .serversage import ServerSage

__author__ = 'DevelopmentCats'
__version__ = '1.0.0'

async def setup(bot: Red) -> None:
    """This function is called by Red when loading the cog"""
    cog = ServerSage(bot)
    # This is the key part that tells Red about our requirements
    if hasattr(cog, "requirements"):
        requirements_file = Path(__file__).parent / "requirements.txt"
        if requirements_file.exists():
            cog.requirements = requirements_file.read_text().splitlines()
    await bot.add_cog(cog)
