from .UserTracker import UserTracker

async def setup(bot):
    await bot.add_cog(UserTracker(bot))
