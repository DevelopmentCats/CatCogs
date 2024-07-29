from .RobustEvents import RobustEventsCog

async def setup(bot):
    cog = RobustEventsCog(bot)
    await bot.add_cog(cog)
