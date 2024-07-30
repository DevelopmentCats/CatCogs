from redbot.core.bot import Red
from .RobustEvents import RobustEventsCog  # Import the cog class from RobustEvents.py

__red_end_user_data_statement__ = "This cog does not persistently store data about users."

async def setup(bot: Red):
    try:
        cog = RobustEventsCog(bot)
        await bot.add_cog(cog)
        bot.log.info("RobustEvents has been loaded and is ready.")
    except Exception as e:
        bot.log.exception(f"Failed to load RobustEvents: {e}")
