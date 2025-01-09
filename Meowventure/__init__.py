import discord
from redbot.core import commands

class Meowventure(commands.Cog):
    """Meowventure - A fun adventure game for Discord!"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def meow(self, ctx):
        """Says meow!"""
        await ctx.send("Meow! 🐱")

def setup(bot):
    bot.add_cog(Meowventure(bot))
