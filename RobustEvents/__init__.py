from redbot.core.bot import Red
from .RobustEvents import RobustEventsCog  # Import the cog class from RobustEvents.py

async def setup(bot: Red):
    try:
        cog = RobustEventsCog(bot)
        await bot.add_cog(cog)
        print("RobustEvents has been loaded and is ready.")
    except Exception as e:
        print(f"Failed to load RobustEvents: {e}")
