from redbot.core.bot import Red
from .RobustEvents import RobustEventsCog  # Import the cog class from RobustEvents.py

async def setup(bot: Red):
    cog = RobustEventsCog(bot)
    await bot.add_cog(cog)
