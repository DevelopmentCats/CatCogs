from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
import discord
import aiohttp
import json
import logging
from typing import Dict, List, Optional
from .utils.gemini_client import GeminiClient
from .utils.server_analyzer import ServerAnalyzer

log = logging.getLogger("red.serversage")

class ServerSage(commands.Cog):
    """ AI-Powered Discord Server Enhancement - Your Mystical Server Guide"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=867530999,
            force_registration=True
        )
        
        default_global = {
            "gemini_api_key": None,
            "max_suggestions": 10,
            "auto_apply": False,
            "suggestion_style": "friendly",
            "confirmation_required": True
        }
        
        default_guild = {
            "last_analysis": None,
            "pending_suggestions": [],
            "applied_changes": [],
            "ignored_channels": [],
            "ignored_categories": [],
            "custom_preferences": {}
        }
        
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        self.gemini_client = None
        self._init_gemini_client()
    
    async def _init_gemini_client(self):
        """Initialize the Gemini AI client with stored API key"""
        api_key = await self.config.gemini_api_key()
        if api_key:
            self.gemini_client = GeminiClient(api_key)
    
    @commands.group(name="serversage", aliases=["sage"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def _serversage(self, ctx: commands.Context):
        """ Let me guide you in enhancing your server!"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title=" ServerSage - Your Mystical Server Guide",
                description="Hello! I'm here to help enhance your server with AI-powered wisdom!",
                color=discord.Color.purple()
            )
            embed.add_field(
                name=" Available Commands",
                value=(
                    "`analyze` - Scan your server for enhancement opportunities\n"
                    "`suggest` - View pending magical improvements\n"
                    "`apply` - Transform your server with suggested changes\n"
                    "`config` - Customize how I work\n"
                    "`help` - Show detailed help for each command"
                ),
                inline=False
            )
            embed.set_footer(text="Type [p]help serversage <command> for more details!")
            await ctx.send(embed=embed)

    @_serversage.command(name="analyze")
    async def analyze_server(self, ctx: commands.Context, *, style_prompt: str = None):
        """ Analyze your server and suggest improvements
        
        Parameters
        ----------
        style_prompt : str, optional
            Describe how you want your server to be styled (e.g., "gaming focused", "professional community", "anime server")
        """
        if not self.gemini_client:
            await ctx.send(" Please set up your Gemini API key first with `[p]serversage config setkey <your-key>`")
            return
            
        # If no style provided, ask for it
        if not style_prompt:
            prompt_msg = await ctx.send(
                embed=discord.Embed(
                    title=" Server Style",
                    description=(
                        "What kind of server would you like this to be? Some examples:\n"
                        "• A professional community for developers\n"
                        "• A fun gaming server focused on Minecraft\n"
                        "• An anime discussion community\n"
                        "• A study group server\n"
                        "• A content creator community\n\n"
                        "Reply to this message with your desired style, or say 'skip' to use default style."
                    ),
                    color=discord.Color.blue()
                )
            )
            
            try:
                response = await self.bot.wait_for(
                    "message",
                    check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
                    timeout=30.0
                )
                style_prompt = response.content if response.content.lower() != "skip" else None
                
                # Clean up the prompt message
                await prompt_msg.delete()
                try:
                    await response.delete()
                except:
                    pass
            except asyncio.TimeoutError:
                await prompt_msg.delete()
                style_prompt = None
            
        async with ctx.typing():
            progress_msg = await ctx.send(" *Consulting the mystical AI forces...*")
            
            try:
                # Gather server info
                await progress_msg.edit(content=" *Examining your server's current state...*")
                server_info = await ServerAnalyzer.gather_server_info(ctx.guild)
                
                # Get AI analysis
                await progress_msg.edit(content=" *Pondering improvements...*")
                style = await self.config.suggestion_style()
                analysis = await self.gemini_client.analyze_server(
                    server_info,
                    style=style,
                    style_prompt=style_prompt
                )
                
                # Store suggestions
                await self.config.guild(ctx.guild).pending_suggestions.set(analysis["suggestions"])
                await self.config.guild(ctx.guild).last_analysis.set(analysis["summary"])
                
                # Create response embed
                embed = discord.Embed(
                    title=" Server Analysis Complete!",
                    description=analysis["summary"],
                    color=discord.Color.purple()
                )
                
                if style_prompt:
                    embed.add_field(
                        name=" Requested Style",
                        value=f"```{style_prompt}```",
                        inline=False
                    )
                
                suggestion_count = len(analysis["suggestions"])
                embed.add_field(
                    name=" Suggestions Found",
                    value=f"I've discovered {suggestion_count} potential improvements!",
                    inline=False
                )
                
                embed.add_field(
                    name=" Next Steps",
                    value="Use `[p]serversage suggest` to view my recommendations!",
                    inline=False
                )
                
                await progress_msg.edit(content=None, embed=embed)
                
            except Exception as e:
                log.error(f"Error during server analysis: {str(e)}")
                await progress_msg.edit(
                    content=" Oops! Something went wrong during the analysis. Please try again later."
                )

    @_serversage.command(name="suggest")
    async def show_suggestions(self, ctx: commands.Context):
        """ View the mystical suggestions for your server"""
        suggestions = await self.config.guild(ctx.guild).pending_suggestions()
        
        if not suggestions:
            await ctx.send(" No suggestions available! Use `[p]serversage analyze` to get started!")
            return
            
        pages = []
        for i, suggestion in enumerate(suggestions, 1):
            embed = discord.Embed(
                title=f" Suggestion {i}/{len(suggestions)}",
                description=suggestion["description"],
                color=discord.Color.purple()
            )
            embed.add_field(
                name="Priority",
                value=f"{'' if suggestion['priority'] == 'High' else '' if suggestion['priority'] == 'Medium' else ''} {suggestion['priority']}",
                inline=True
            )
            embed.add_field(
                name="Type",
                value=suggestion["type"].replace("_", " ").title(),
                inline=True
            )
            pages.append(embed)
            
        # TODO: Implement proper pagination
        await ctx.send(embed=pages[0])

    @_serversage.command(name="apply")
    async def apply_changes(self, ctx: commands.Context):
        """ Transform your server with suggested changes"""
        suggestions = await self.config.guild(ctx.guild).pending_suggestions()
        
        if not suggestions:
            await ctx.send(" No changes to apply! Use `[p]serversage analyze` first!")
            return
            
        changes = ServerAnalyzer.create_change_plan(suggestions)
        
        # First show what will be changed
        preview = await ServerAnalyzer.apply_changes(ctx.guild, changes, dry_run=True)
        preview_text = "\n".join(preview[:5])
        if len(preview) > 5:
            preview_text += f"\n...and {len(preview) - 5} more changes"
            
        embed = discord.Embed(
            title=" Ready to Transform Your Server!",
            description="Here's what I'm going to do:",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="Planned Changes",
            value=f"```\n{preview_text}\n```",
            inline=False
        )
        embed.add_field(
            name=" Confirmation",
            value="React with to apply these changes, or to cancel.",
            inline=False
        )
        
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("")
        await msg.add_reaction("")

        # TODO: Add reaction handling logic

    @_serversage.group(name="config")
    async def configure_cog(self, ctx: commands.Context):
        """ Customize how ServerSage works"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title=" ServerSage Settings",
                description="Customize how I enhance your server!",
                color=discord.Color.purple()
            )
            embed.add_field(
                name="Available Settings",
                value=(
                    "`setkey` - Set your Gemini API key\n"
                    "`style` - Change suggestion style\n"
                    "`maxsuggestions` - Set maximum suggestions\n"
                    "`ignore` - Set channels/categories to ignore"
                ),
                inline=False
            )
            await ctx.send(embed=embed)
    
    @configure_cog.command(name="setkey")
    async def set_api_key(self, ctx: commands.Context, api_key: str):
        """Set your Gemini API key"""
        # Delete the message to protect the API key
        try:
            await ctx.message.delete()
        except:
            pass
            
        await self.config.gemini_api_key.set(api_key)
        await self._init_gemini_client()
        await ctx.send(" API key set successfully!", delete_after=5)
    
    @configure_cog.command(name="style")
    async def set_style(self, ctx: commands.Context, style: str):
        """Set the suggestion style (friendly/professional/concise)"""
        if style not in ["friendly", "professional", "concise"]:
            await ctx.send(" Style must be one of: friendly, professional, concise")
            return
            
        await self.config.suggestion_style.set(style)
        await ctx.send(f" Suggestion style set to: {style}")

async def setup(bot: Red):
    await bot.add_cog(ServerSage(bot))
