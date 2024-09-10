from .UserTracker import UserActivityLogger

async def setup(bot):
    await bot.add_cog(UserActivityLogger(bot))
