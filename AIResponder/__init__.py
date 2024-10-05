from .AIResponder import AIResponder

async def setup(bot):
    cog = AIResponder(bot)
    await cog.setup_database()
    await bot.add_cog(cog)
