"""
😼 ServerSage - Your PURRFECTLY CHAOTIC Discord Companion!
Created by DevelopmentCats with EXTREME FELINE PRECISION 🐱

A Red-DiscordBot cog that POUNCES on server organization problems!
"""

from redbot.core.bot import Red
from .serversage import ServerSage

__author__ = 'DevelopmentCats'
__version__ = '1.0.0'

async def setup(bot: Red) -> None:
    """This function is called by Red when loading the cog"""
    await bot.add_cog(ServerSage(bot))
