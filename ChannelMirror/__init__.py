from .ChannelMirror import ChannelMirror

async def setup(bot):
    await bot.add_cog(ChannelMirror(bot))
