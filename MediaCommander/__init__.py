"""
🎬 MediaCommander - Your ULTIMATE Media Management Companion!
Created by DevelopmentCats with EXTREME FELINE PRECISION 🐱

A comprehensive Red-DiscordBot cog that integrates with the full Arr stack:
Plex, Sonarr, Radarr, Lidarr, Tautulli, Overseerr, and more!
"""

from redbot.core.bot import Red
from redbot.core.utils import get_end_user_data_statement

__author__ = 'DevelopmentCats'
__version__ = '1.0.0'

# Define requirements for the cog
requirements = [
    "aiohttp>=3.8.0", 
    "python-dateutil>=2.8.2", 
    "requests>=2.28.0"
]

from .mediacommander import MediaCommander

async def setup(bot: Red) -> None:
    """This function is called by Red when loading the cog"""
    cog = MediaCommander(bot)
    await bot.add_cog(cog)

def __red_end_user_data_statement__():
    return get_end_user_data_statement(__file__) 