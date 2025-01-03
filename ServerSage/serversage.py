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
    """The PURRFECT Discord Server Enhancement Companion!"""
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=260120231747)
        default_global = {
            "api_key": None
        }
        self.config.register_global(**default_global)
        self.analyzer = ServerAnalyzer(bot, self.config)
        
    @commands.group(name="serversage")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def serversage(self, ctx: commands.Context):
        """🔮 ServerSage - Your Mystical Server Guide"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()
            
    @serversage.command(name="setkey")
    @commands.is_owner()
    async def set_api_key(self, ctx: commands.Context, api_key: str):
        """Set the Google Gemini API key"""
        try:
            await self.config.api_key.set(api_key)
            await ctx.send("✨ API key set successfully!")
            # Delete the message containing the API key for security
            try:
                await ctx.message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
        except Exception as e:
            log.error(f"Error setting API key: {str(e)}")
            await ctx.send("❌ Failed to set API key. Please check logs for details.")

    @serversage.command(name="analyze")
    async def analyze(self, ctx: commands.Context, *, style: Optional[str] = None):
        """🔍 Analyze your server and get AI-powered suggestions
        
        Example:
        `[p]serversage analyze` - Basic analysis
        `[p]serversage analyze gaming focused` - Analysis with gaming focus
        """
        async with ctx.typing():
            try:
                api_key = await self.config.api_key()
                if not api_key:
                    await ctx.send("❌ API key not set! Please ask the bot owner to set it using `[p]serversage setkey`")
                    return
                    
                await self.analyzer.analyze_server(ctx, style_prompt=style)
            except Exception as e:
                log.error(f"Error during server analysis: {str(e)}")
                await ctx.send(f"❌ An error occurred during analysis: {str(e)}\nPlease try again or contact support if the issue persists.")

    @serversage.command(name="apply")
    async def apply(self, ctx: commands.Context):
        """✨ Apply the suggested changes to your server"""
        async with ctx.typing():
            try:
                await self.analyzer.apply_suggestions(ctx)
            except discord.Forbidden:
                await ctx.send("❌ I don't have the required permissions to make these changes!")
            except Exception as e:
                log.error(f"Error applying suggestions: {str(e)}")
                await ctx.send(f"❌ An error occurred while applying changes: {str(e)}")

    @serversage.command(name="preview")
    async def preview(self, ctx: commands.Context):
        """👀 Preview pending changes without applying them"""
        try:
            changes = self.analyzer.suggestion_manager.get_suggestions(ctx.guild.id)
            if not changes:
                await ctx.send("No pending suggestions found!")
                return
                
            preview = ["📋 Pending Changes:"]
            for i, change in enumerate(changes, 1):
                preview.append(f"{i}. {self.analyzer._format_change(change)}")
            
            await ctx.send("\n".join(preview))
        except Exception as e:
            log.error(f"Error previewing changes: {str(e)}")
            await ctx.send(f"❌ An error occurred while previewing changes: {str(e)}")

    @serversage.command(name="clear")
    async def clear(self, ctx: commands.Context):
        """🧹 Clear all pending suggestions"""
        try:
            self.analyzer.suggestion_manager.clear_suggestions(ctx.guild.id)
            await ctx.send("✨ All pending suggestions have been cleared!")
        except Exception as e:
            log.error(f"Error clearing suggestions: {str(e)}")
            await ctx.send(f"❌ An error occurred while clearing suggestions: {str(e)}")
