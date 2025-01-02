"""
 ServerSage - Your Mystical Server Guide
Created by DevelopmentCats with EXTREME FELINE PRECISION 
"""

import discord
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box
from typing import Optional
import logging
from .utils import GeminiClient, ServerAnalyzer, SuggestionManager

log = logging.getLogger("red.serversage")

class ServerSage(commands.Cog):
    """ The PURRFECT Discord Server Enhancement Companion!"""
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=260120231747)
        self.config.register_global(api_key=None)
        
        # Initialize our components
        self.gemini = GeminiClient(self._get_api_key())
        self.analyzer = ServerAnalyzer(self.bot)
        
    async def _get_api_key(self) -> Optional[str]:
        """Gets the Gemini API key with the stealth of a ninja cat"""
        return await self.config.api_key()
        
    @commands.group(aliases=["sage"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def serversage(self, ctx: commands.Context):
        """ Unleash the POWER of ServerSage!"""
        if not ctx.invoked_subcommand:
            cmd_list = (
                "** Available Commands:**\n"
                "`analyze` - Begin the Great Server Hunt!\n"
                "`suggest` - View pending suggestions\n"
                "`apply` - Execute approved changes\n"
                "`config` - Adjust your hunting preferences"
            )
            embed = discord.Embed(
                title=" ServerSage Commands",
                description=cmd_list,
                color=discord.Color.purple()
            )
            await ctx.send(embed=embed)
            
    @serversage.command()
    async def analyze(self, ctx: commands.Context, *, style: Optional[str] = None):
        """ Begin the Great Server Hunt!
        
        Example:
        `[p]sage analyze professional and modern`
        `[p]sage analyze gaming community focused on Minecraft`
        """
        async with ctx.typing():
            await self.analyzer.analyze_server(ctx, style_prompt=style)
            
    @serversage.command()
    async def suggest(self, ctx: commands.Context):
        """ View and manage pending suggestions"""
        if not self.analyzer.suggestion_manager.pending_suggestions:
            await ctx.send("No pending suggestions! Time for a new hunt? ")
            return
            
        await self.analyzer.suggestion_manager.display_suggestions(ctx)
        
    @serversage.command()
    async def apply(self, ctx: commands.Context):
        """ Execute approved changes with FELINE GRACE"""
        await self.analyzer.apply_suggestions(ctx)
        
    @serversage.group()
    async def config(self, ctx: commands.Context):
        """ Adjust your hunting preferences"""
        if not ctx.invoked_subcommand:
            current_key = await self._get_api_key()
            status = "" if current_key else ""
            
            embed = discord.Embed(
                title=" ServerSage Configuration",
                description=(
                    "**Current Settings:**\n"
                    f"API Key: {status}\n\n"
                    "**Available Commands:**\n"
                    "`setkey` - Set your Gemini API key\n"
                    "`clearkey` - Clear your API key"
                ),
                color=discord.Color.purple()
            )
            await ctx.send(embed=embed)
            
    @config.command()
    async def setkey(self, ctx: commands.Context, api_key: str):
        """ Set your Gemini API key"""
        # Delete message to protect API key
        try:
            await ctx.message.delete()
        except:
            pass
            
        await self.config.api_key.set(api_key)
        self.gemini = GeminiClient(api_key)  # Reinitialize with new key
        
        embed = discord.Embed(
            title=" API Key Updated",
            description="Your API key has been securely stored! Ready to hunt! ",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
        
    @config.command()
    async def clearkey(self, ctx: commands.Context):
        """ Clear your API key"""
        await self.config.api_key.set(None)
        self.gemini = GeminiClient(None)
        
        embed = discord.Embed(
            title=" API Key Cleared",
            description="Your API key has been removed! Set a new one to continue hunting! ",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)
        
    async def cog_unload(self):
        """Cleanup when the cog is unloaded"""
        # Any cleanup code here
        pass

async def setup(bot: Red):
    await bot.add_cog(ServerSage(bot))
