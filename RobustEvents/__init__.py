from .events import EventsCog

async def setup(bot):
    cog = EventsCog(bot)
    await bot.add_cog(cog)
