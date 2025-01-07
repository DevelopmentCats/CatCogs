from .mjdiscord import MJDiscord

async def setup(bot):
    await bot.add_cog(MJDiscord(bot)) 