async def setup(bot: Red):
    cog = RobustEventsCog(bot)
    await bot.add_cog(cog)
