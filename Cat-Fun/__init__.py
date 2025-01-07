from redbot.core.bot import Red
from .meowfun import MeowFun

async def setup(bot: Red) -> None:
    await bot.add_cog(MeowFun(bot)) 