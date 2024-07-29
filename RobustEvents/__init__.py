from .events import RobustEvents

async def setup(bot):
    cog = RobustEvents(bot)
    await bot.add_cog(cog)
