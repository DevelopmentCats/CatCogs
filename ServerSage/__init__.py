"""
😼 ServerSage - Your PURRFECTLY CHAOTIC Discord Companion!
Created by DevelopmentCats with EXTREME FELINE PRECISION 🐱

A Red-DiscordBot cog that POUNCES on server organization problems!
"""

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement

__author__ = 'DevelopmentCats'
__version__ = '1.0.0'

# This is the key part - defining requirements as a module-level variable
requirements = ["google-generativeai>=0.3.0", "typing-extensions>=4.0.0", 
               "aiohttp>=3.8.0", "python-dotenv>=0.19.0"]

from .serversage import ServerSage

async def setup(bot: Red) -> None:
    """This function is called by Red when loading the cog"""
    cog = ServerSage(bot)
    await bot.add_cog(cog)
