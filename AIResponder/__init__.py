from .airesponder import AIResponder

async def setup(bot):
    await bot.add_cog(AIResponder(bot))
