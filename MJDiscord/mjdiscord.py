from typing import Optional, Literal, Dict, Any
import discord
import aiohttp
import asyncio
import json
import re
import logging
import websockets
import base64
from datetime import datetime, timedelta
from io import BytesIO
from PIL import Image
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from discord import app_commands

# Set up logging
log = logging.getLogger("red.mjdiscord")

# Constants for MidJourney API
API_VERSION = "v1"
API_BASE_URL = "https://api.midjourney.com"
WS_URL = "wss://api.midjourney.com/ws"

# Available model versions and parameters
MODEL_VERSIONS = {
    "5.0": "MJ_V5",
    "5.1": "MJ_V5.1",
    "5.2": "MJ_V5.2",
    "niji": "NIJI_V5",
    "turbo": "MJ_TURBO"
}

# Reaction controls for image manipulation
CONTROL_REACTIONS = {
    "🔄": "rerun",      # Rerun the same prompt
    "⬆️": "upscale",    # Upscale the image
    "🎲": "vary",       # Create variations
    "💾": "save",       # Save to favorites
    "❌": "delete",     # Delete the message
    "1️⃣": "vary_1",    # Variation options
    "2️⃣": "vary_2",
    "3️⃣": "vary_3",
    "4️⃣": "vary_4"
}

# Upscale options
UPSCALE_REACTIONS = {
    "2️⃣": "2x",
    "4️⃣": "4x"
}

# Variation strength options
VARIATION_STRENGTH = {
    "🔵": 0.3,  # Subtle variations
    "🟢": 0.5,  # Moderate variations
    "🟡": 0.7   # Strong variations
}

ASPECT_RATIOS = ["1:1", "16:9", "2:3", "4:3", "3:2", "2:1", "1:2"]
STYLE_VALUES = range(0, 1001)  # 0-1000 for --stylize
CHAOS_VALUES = range(0, 101)   # 0-100 for --chaos
QUALITY_VALUES = [".25", ".5", "1"]  # Quality values for --quality
SEED_PATTERN = re.compile(r'^\d{1,10}$')  # Seed validation pattern

# Emoji indicators for different states and features
EMOJIS = {
    "loading": "⏳",
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "art": "🎨",
    "wand": "✨",
    "star": "⭐",
    "settings": "⚙️",
    "link": "🔗",
    "time": "⏰",
    "roles": "👥",
    "api": "🔌",
    "jobs": "📋",
    "quality": "💎",
    "style": "🖌️",
    "version": "📦",
    "aspect": "📐",
    "chaos": "🌀",
    "seed": "🎲",
    "help": "❓"
}

# Color scheme for embeds
COLORS = {
    "brand": discord.Color.from_rgb(139, 0, 139),  # Deep purple for brand color
    "success": discord.Color.from_rgb(67, 181, 129),
    "error": discord.Color.from_rgb(240, 71, 71),
    "warning": discord.Color.from_rgb(250, 166, 26),
    "info": discord.Color.from_rgb(114, 137, 218),
    "processing": discord.Color.from_rgb(59, 165, 93)
}

def get_progress_bar(percent: int) -> str:
    """Generate a visual progress bar"""
    filled = "█" * (percent // 10)
    empty = "░" * (10 - (percent // 10))
    return f"{filled}{empty} {percent}%"

class MJDiscord(commands.Cog):
    """MidJourney API integration for Red-DiscordBot"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=897234789,
            force_registration=True
        )
        
        default_global = {
            "api_key": None,
            "webhook_url": None,
            "allowed_roles": [],
            "is_configured": False,
            "auto_reactions": True,
            "max_jobs_per_user": 3,
            "cooldown_minutes": 1,
            "default_model": "5.2"
        }
        
        self.config.register_global(**default_global)
        
        # Store active jobs and their status
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.user_jobs: Dict[int, set[str]] = {}
        self.active_controls: Dict[int, Dict[str, Any]] = {}
        
        # API session
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        
        # Start background tasks
        self.bg_tasks = []
        self.start_background_tasks()

    async def cog_load(self) -> None:
        """Register app commands when the cog loads."""
        await self.bot.tree.sync()

    async def cog_unload(self) -> None:
        """Cleanup when cog is unloaded"""
        for task in self.bg_tasks:
            task.cancel()
        
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())
        
        if self.ws and not self.ws.closed:
            asyncio.create_task(self.ws.close())

    def start_background_tasks(self):
        """Start all background tasks"""
        try:
            self.bg_tasks.extend([
                self.bot.loop.create_task(self.init_api_session()),
                self.bot.loop.create_task(self.cleanup_old_jobs()),
                self.bot.loop.create_task(self.ws_handler())
            ])
        except Exception as e:
            log.error(f"Error starting background tasks: {e}")
            raise

    async def init_api_session(self):
        """Initialize API session and websocket connection"""
        if self.session and not self.session.closed:
            await self.session.close()
        
        settings = await self.config.all()
        if not settings["api_key"]:
            return
        
        self.session = aiohttp.ClientSession(
            base_url=API_BASE_URL,
            headers={
                "Authorization": f"Bearer {settings['api_key']}",
                "Content-Type": "application/json"
            }
        )

    async def ws_handler(self):
        """Handle WebSocket connection for real-time updates"""
        while True:
            try:
                settings = await self.config.all()
                if not settings["api_key"]:
                    await asyncio.sleep(60)
                    continue
                
                async with websockets.connect(
                    WS_URL,
                    extra_headers={"Authorization": f"Bearer {settings['api_key']}"}
                ) as ws:
                    self.ws = ws
                    async for message in ws:
                        await self.handle_ws_message(json.loads(message))
                        
            except websockets.exceptions.ConnectionClosed:
                log.warning("WebSocket connection closed. Reconnecting...")
                await asyncio.sleep(5)
            except Exception as e:
                log.error(f"WebSocket error: {e}")
                await asyncio.sleep(5)

    async def handle_ws_message(self, data: Dict[str, Any]):
        """Handle incoming WebSocket messages"""
        job_id = data.get("job_id")
        if not job_id or job_id not in self.active_jobs:
            return
        
        job = self.active_jobs[job_id]
        status = data.get("status", "unknown")
        progress = data.get("progress", 0)
        
        try:
            # Update progress message
            embed = discord.Embed(
                title=f"{EMOJIS['art']} Image Generation in Progress",
                description=get_progress_bar(progress),
                color=COLORS["processing"]
            )
            
            embed.add_field(
                name=f"{EMOJIS['info']} Status",
                value=f"{EMOJIS['loading']} {status.title()}...",
                inline=False
            )
            
            await job["message"].edit(embed=embed)
            
            # Handle completion
            if status == "completed" and (image_url := data.get("image_url")):
                await self.handle_job_completion(job_id, image_url)
            
            # Handle failure
            elif status == "failed":
                await self.handle_job_failure(job_id, data.get("error", "Unknown error"))
                
        except Exception as e:
            log.error(f"Error handling WebSocket message: {e}")

    async def handle_job_completion(self, job_id: str, image_url: str):
        """Handle successful job completion"""
        job = self.active_jobs[job_id]
        
        embed = discord.Embed(
            title=f"{EMOJIS['success']} Image Generated Successfully!",
            color=COLORS["success"]
        )
        
        embed.set_image(url=image_url)
        
        # Add prompt with proper formatting
        prompt_value = job.get("prompt", "Unknown prompt")
        if len(prompt_value) > 1024:
            prompt_value = prompt_value[:1021] + "..."
        embed.add_field(
            name=f"{EMOJIS['wand']} Prompt",
            value=box(prompt_value),
            inline=False
        )
        
        # Add completion time
        duration = (datetime.now() - job["timestamp"]).seconds
        embed.set_footer(text=f"Generated in {duration} seconds • React with controls below to modify")
        
        # Store the original parameters for reuse
        embed.add_field(
            name="Job ID",
            value=job_id,
            inline=False
        )
        
        message = await job["message"].edit(embed=embed)
        
        # Add reaction controls
        for reaction in CONTROL_REACTIONS.keys():
            await message.add_reaction(reaction)
        
        # Store message info for reaction handling
        self.active_controls[message.id] = {
            "job_id": job_id,
            "prompt": prompt_value,
            "parameters": job.get("parameters", {}),
            "image_url": image_url,
            "user_id": job["user_id"]
        }
        
        # Cleanup job but keep control info
        self.active_jobs.pop(job_id)
        if job["user_id"] in self.user_jobs:
            self.user_jobs[job["user_id"]].remove(job_id)

    async def handle_job_failure(self, job_id: str, error: str):
        """Handle job failure"""
        job = self.active_jobs[job_id]
        
        embed = discord.Embed(
            title=f"{EMOJIS['error']} Image Generation Failed",
            description=f"Error: {error}",
            color=COLORS["error"]
        )
        
        await job["message"].edit(embed=embed)
        
        # Cleanup
        self.active_jobs.pop(job_id)
        if job["user_id"] in self.user_jobs:
            self.user_jobs[job["user_id"]].remove(job_id)

    async def cleanup_old_jobs(self):
        """Background task to clean up old jobs"""
        while True:
            try:
                current_time = datetime.now()
                # Clean up jobs older than 1 hour
                expired_jobs = [
                    job_id for job_id, job in self.active_jobs.items()
                    if current_time - job["timestamp"] > timedelta(hours=1)
                ]
                
                for job_id in expired_jobs:
                    job = self.active_jobs.pop(job_id)
                    if job["user_id"] in self.user_jobs:
                        self.user_jobs[job["user_id"]].remove(job_id)
                
                await asyncio.sleep(300)  # Run every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(300)

    @commands.hybrid_group(name="mjset")
    @commands.admin_or_permissions(administrator=True)
    async def mjset(self, ctx: commands.Context):
        """Configure MidJourney API integration settings."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @mjset.command(name="apikey")
    @app_commands.describe(api_key="Your MidJourney API key")
    async def set_api_key(self, ctx: commands.Context, api_key: str):
        """Set your MidJourney API key."""
        # Delete the message containing the API key
        try:
            await ctx.message.delete()
        except:
            pass
        
        async with self.config.all() as settings:
            settings["api_key"] = api_key
            settings["is_configured"] = True
        
        # Reinitialize API session
        await self.init_api_session()
        
        await ctx.send(f"{EMOJIS['success']} API key configured successfully!")

    @mjset.command(name="webhook")
    @app_commands.describe(webhook_url="Discord webhook URL for updates (leave empty to disable)")
    async def set_webhook(self, ctx: commands.Context, webhook_url: Optional[str] = None):
        """Set a webhook URL for faster job updates (optional)."""
        async with self.config.all() as settings:
            settings["webhook_url"] = webhook_url
        
        if webhook_url:
            await ctx.send(f"{EMOJIS['success']} Webhook URL configured successfully!")
        else:
            await ctx.send(f"{EMOJIS['info']} Webhook updates disabled.")

    @mjset.command(name="roles")
    async def set_roles(self, ctx: commands.Context):
        """Configure which roles can use MidJourney commands."""
        await ctx.send("Please mention the roles that should be allowed to use MidJourney commands (mention multiple roles in one message, or type 'everyone' to allow all users):")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            
            if msg.content.lower() == "everyone":
                async with self.config.all() as settings:
                    settings["allowed_roles"] = []
                await ctx.send(f"{EMOJIS['success']} All users can now use MidJourney commands!")
            else:
                if not msg.role_mentions:
                    await ctx.send(f"{EMOJIS['error']} No roles mentioned. Configuration unchanged.")
                    return
                
                async with self.config.all() as settings:
                    settings["allowed_roles"] = [role.id for role in msg.role_mentions]
                
                role_list = ", ".join(role.name for role in msg.role_mentions)
                await ctx.send(f"{EMOJIS['success']} MidJourney commands restricted to these roles: {role_list}")
        
        except asyncio.TimeoutError:
            await ctx.send("Setup timed out. Please try again.")

    @mjset.command(name="model")
    @app_commands.describe(version="Model version (5.0, 5.1, 5.2, niji, turbo)")
    async def set_default_model(self, ctx: commands.Context, version: str):
        """Set the default model version."""
        if version not in MODEL_VERSIONS:
            await ctx.send(f"{EMOJIS['error']} Invalid version. Available options: {', '.join(MODEL_VERSIONS.keys())}")
            return
        
        async with self.config.all() as settings:
            settings["default_model"] = version
        
        await ctx.send(f"{EMOJIS['success']} Default model set to {version}!")

    @commands.hybrid_command(name="imagine")
    @app_commands.describe(
        prompt="The prompt to generate an image from",
        aspect="Aspect ratio (e.g., '1:1', '16:9', '2:3')",
        stylize="Stylization value (0-1000)",
        chaos="Chaos value (0-100)",
        quality="Quality value (.25, .5, or 1)",
        seed="Seed number for reproducible results",
        version="MidJourney model version (5.0, 5.1, 5.2, niji, turbo)",
        no_style="Whether to disable MJ's base stylization"
    )
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def imagine(
        self, 
        ctx: commands.Context, 
        prompt: str,
        aspect: Optional[str] = None,
        stylize: Optional[int] = None,
        chaos: Optional[int] = None,
        quality: Optional[str] = None,
        seed: Optional[str] = None,
        version: Optional[str] = None,
        no_style: Optional[bool] = False
    ):
        """Generate an image using MidJourney."""
        settings = await self.config.all()
        
        if not settings["is_configured"]:
            await ctx.send(f"{EMOJIS['error']} MidJourney API not configured. Ask an admin to run `mjset apikey`")
            return
        
        # Check if user has permission
        if settings["allowed_roles"] and not any(role.id in settings["allowed_roles"] for role in ctx.author.roles):
            await ctx.send(f"{EMOJIS['error']} You don't have permission to use MidJourney commands.")
            return
        
        # Check concurrent jobs limit
        user_job_count = len(self.user_jobs.get(ctx.author.id, set()))
        if user_job_count >= settings["max_jobs_per_user"]:
            await ctx.send(f"{EMOJIS['error']} You have too many active jobs. Please wait for them to complete (max: {settings['max_jobs_per_user']}).")
            return
        
        # Validate parameters
        params = {}
        
        # Validate aspect ratio
        if aspect:
            if aspect not in ASPECT_RATIOS:
                await ctx.send(f"{EMOJIS['error']} Invalid aspect ratio. Available options: {', '.join(ASPECT_RATIOS)}")
                return
            params["aspect_ratio"] = aspect
        
        # Validate stylize
        if stylize is not None:
            if stylize not in STYLE_VALUES:
                await ctx.send(f"{EMOJIS['error']} Stylize value must be between 0 and 1000.")
                return
            params["stylize"] = stylize
        
        # Validate chaos
        if chaos is not None:
            if chaos not in CHAOS_VALUES:
                await ctx.send(f"{EMOJIS['error']} Chaos value must be between 0 and 100.")
                return
            params["chaos"] = chaos
        
        # Validate quality
        if quality:
            if quality not in QUALITY_VALUES:
                await ctx.send(f"{EMOJIS['error']} Quality must be .25, .5, or 1")
                return
            params["quality"] = float(quality)
        
        # Validate seed
        if seed:
            if not SEED_PATTERN.match(seed):
                await ctx.send(f"{EMOJIS['error']} Invalid seed number. Must be a number between 0-9999999999.")
                return
            params["seed"] = int(seed)
        
        # Validate version
        version = version or settings["default_model"]
        if version not in MODEL_VERSIONS:
            await ctx.send(f"{EMOJIS['error']} Invalid version. Available options: {', '.join(MODEL_VERSIONS.keys())}")
            return
        params["model"] = MODEL_VERSIONS[version]
        
        # Add no-style parameter
        if no_style:
            params["no_style"] = True
        
        # Create progress message
        embed = discord.Embed(
            title=f"{EMOJIS['art']} Processing Image Generation",
            description=get_progress_bar(0),
            color=COLORS["processing"]
        )
        
        # Format prompt nicely
        formatted_prompt = box(prompt)
        embed.add_field(
            name=f"{EMOJIS['wand']} Prompt",
            value=formatted_prompt if len(formatted_prompt) <= 1024 else f"{formatted_prompt[:1021]}...",
            inline=False
        )
        
        # Add parameters field if any
        if params:
            param_list = []
            for key, value in params.items():
                if key == "aspect_ratio":
                    param_list.append(f"{EMOJIS['aspect']} Aspect: {value}")
                elif key == "stylize":
                    param_list.append(f"{EMOJIS['style']} Style: {value}")
                elif key == "chaos":
                    param_list.append(f"{EMOJIS['chaos']} Chaos: {value}")
                elif key == "quality":
                    param_list.append(f"{EMOJIS['quality']} Quality: {value}")
                elif key == "seed":
                    param_list.append(f"{EMOJIS['seed']} Seed: {value}")
                elif key == "model":
                    param_list.append(f"{EMOJIS['version']} Model: {value}")
            
            if param_list:
                embed.add_field(
                    name="Parameters",
                    value="\n".join(param_list),
                    inline=False
                )
        
        embed.add_field(
            name=f"{EMOJIS['info']} Status",
            value=f"{EMOJIS['loading']} Initializing request...",
            inline=False
        )
        
        progress_msg = await ctx.send(embed=embed)
        
        # Send API request
        try:
            async with self.session.post("/imagine", json={
                "prompt": prompt,
                **params,
                "webhook_url": settings.get("webhook_url")
            }) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    await progress_msg.edit(
                        embed=discord.Embed(
                            title=f"{EMOJIS['error']} API Error",
                            description=f"Error: {error}",
                            color=COLORS["error"]
                        )
                    )
                    return
                
                data = await resp.json()
                job_id = data["job_id"]
                
                # Store job information
                self.active_jobs[job_id] = {
                    "user_id": ctx.author.id,
                    "message": progress_msg,
                    "channel": ctx.channel,
                    "type": "imagine",
                    "prompt": prompt,
                    "timestamp": datetime.now()
                }
                
                if ctx.author.id not in self.user_jobs:
                    self.user_jobs[ctx.author.id] = set()
                self.user_jobs[ctx.author.id].add(job_id)
                
                # Update progress message
                embed.set_field_at(
                    -1,
                    name=f"{EMOJIS['info']} Status",
                    value=f"{EMOJIS['loading']} Request sent! Processing...",
                    inline=False
                )
                await progress_msg.edit(embed=embed)
        
        except Exception as e:
            log.error(f"Error sending imagine request: {e}")
            await progress_msg.edit(
                embed=discord.Embed(
                    title=f"{EMOJIS['error']} Error",
                    description=f"An error occurred: {str(e)}",
                    color=COLORS["error"]
                )
            )

    @commands.hybrid_command(name="mjstatus")
    @app_commands.describe()
    async def mjstatus(self, ctx: commands.Context):
        """Check MidJourney integration status."""
        settings = await self.config.all()
        
        if not settings["is_configured"]:
            await ctx.send(f"{EMOJIS['error']} MidJourney API not configured.")
            return
        
        # Check if user has permission
        if settings["allowed_roles"] and not any(role.id in settings["allowed_roles"] for role in ctx.author.roles):
            allowed_roles = [ctx.guild.get_role(role_id).name for role_id in settings["allowed_roles"] if ctx.guild.get_role(role_id)]
            await ctx.send(f"ℹ️ MidJourney is configured but restricted to these roles: {', '.join(allowed_roles)}")
            return
        
        # Count active jobs
        user_jobs = len(self.user_jobs.get(ctx.author.id, set()))
        
        embed = discord.Embed(
            title=f"{EMOJIS['info']} MidJourney Status",
            color=COLORS["brand"]
        )
        
        # Add API status
        embed.add_field(
            name=f"{EMOJIS['api']} API Status",
            value=f"{EMOJIS['success']} Connected" if self.session and not self.session.closed else f"{EMOJIS['error']} Disconnected"
        )
        
        # Add WebSocket status
        embed.add_field(
            name=f"{EMOJIS['link']} WebSocket",
            value=f"{EMOJIS['success']} Connected" if self.ws and not self.ws.closed else f"{EMOJIS['error']} Disconnected"
        )
        
        # Add job status with progress bar
        max_jobs = settings['max_jobs_per_user']
        progress = (user_jobs / max_jobs) * 100
        embed.add_field(
            name=f"{EMOJIS['jobs']} Active Jobs",
            value=f"{get_progress_bar(int(progress))}\n{user_jobs}/{max_jobs} slots used",
            inline=False
        )
        
        # Add current model
        embed.add_field(
            name=f"{EMOJIS['version']} Default Model",
            value=settings["default_model"],
            inline=False
        )
        
        # Add footer with refresh hint
        embed.set_footer(text="Use /mjstatus again to refresh")
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="mjhelp")
    @app_commands.describe()
    async def mjhelp(self, ctx: commands.Context):
        """Show detailed help for MidJourney commands and parameters."""
        embed = discord.Embed(
            title=f"{EMOJIS['help']} MidJourney Command Guide",
            description=(
                f"{EMOJIS['info']} Generate amazing images using MidJourney's API!\n"
                f"{EMOJIS['wand']} All parameters are optional - just start with a prompt!"
            ),
            color=COLORS["brand"]
        )
        
        # Basic usage with example
        embed.add_field(
            name="Quick Start",
            value=(
                "```/imagine your prompt here```\n"
                "Example: `/imagine a magical forest with glowing mushrooms`"
            ),
            inline=False
        )
        
        # Parameters with icons and better formatting
        parameters = [
            f"{EMOJIS['aspect']} **Aspect Ratio** (--ar)\n"
            f"Available: {', '.join(ASPECT_RATIOS)}\n"
            "Example: `--ar 16:9`\n",
            
            f"{EMOJIS['style']} **Style Strength** (--stylize)\n"
            "Range: 0-1000 (higher = more stylized)\n"
            "Example: `--stylize 600`\n",
            
            f"{EMOJIS['chaos']} **Chaos** (--chaos)\n"
            "Range: 0-100 (higher = more varied)\n"
            "Example: `--chaos 50`\n",
            
            f"{EMOJIS['quality']} **Quality** (--quality)\n"
            "Options: .25, .5, 1 (higher = better)\n"
            "Example: `--quality 1`\n",
            
            f"{EMOJIS['seed']} **Seed** (--seed)\n"
            "Any number for consistent results\n"
            "Example: `--seed 123456`\n",
            
            f"{EMOJIS['version']} **Version** (--version)\n"
            f"Options: {', '.join(MODEL_VERSIONS.keys())}\n"
            "Example: `--version turbo`\n"
        ]
        
        embed.add_field(
            name="Parameters",
            value="\n".join(parameters),
            inline=False
        )
        
        # Quick examples
        examples = [
            "🖼️ **Landscape:** `/imagine beautiful sunset over mountains --ar 16:9 --quality 1`",
            "👤 **Portrait:** `/imagine professional headshot --ar 2:3 --version 5.2`",
            "🎨 **Artistic:** `/imagine abstract art --stylize 1000 --chaos 100`",
            "⚡ **Quick:** `/imagine cute anime character --version turbo`"
        ]
        
        embed.add_field(
            name="Example Commands",
            value="\n".join(examples),
            inline=False
        )
        
        # Add tips in footer
        embed.set_footer(text="💡 Tip: Use the turbo model for faster results, or quality 1 for best results")
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="favorites")
    @app_commands.describe()
    async def favorites(self, ctx: commands.Context):
        """View your saved favorite images."""
        async with self.config.user(ctx.author).favorites() as favorites:
            if not favorites:
                await ctx.send(f"{EMOJIS['info']} You haven't saved any favorites yet!")
                return
            
            # Create embed pages for favorites
            pages = []
            for i, fav in enumerate(favorites, 1):
                embed = discord.Embed(
                    title=f"Favorite #{i}",
                    color=COLORS["brand"]
                )
                embed.set_image(url=fav["image_url"])
                embed.add_field(
                    name="Prompt",
                    value=box(fav["prompt"]),
                    inline=False
                )
                if fav.get("parameters"):
                    params = "\n".join(f"{k}: {v}" for k, v in fav["parameters"].items())
                    embed.add_field(
                        name="Parameters",
                        value=box(params),
                        inline=False
                    )
                embed.set_footer(text=f"Saved on {datetime.fromisoformat(fav['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}")
                pages.append(embed)
            
            # Show paginated favorites
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Handle reaction controls for image manipulation"""
        if user.bot:
            return
            
        message = reaction.message
        if message.id not in self.active_controls:
            return
            
        control_info = self.active_controls[message.id]
        if user.id != control_info["user_id"]:
            return
            
        emoji = str(reaction.emoji)
        if emoji not in CONTROL_REACTIONS:
            return
            
        # Remove user's reaction
        await reaction.remove(user)
        
        action = CONTROL_REACTIONS[emoji]
        
        if action == "rerun":
            await self.handle_rerun(message, control_info)
        elif action == "upscale":
            await self.handle_upscale_menu(message, control_info)
        elif action == "vary":
            await self.handle_variation_menu(message, control_info)
        elif action == "save":
            await self.handle_save(message, control_info)
        elif action == "delete":
            await message.delete()
            self.active_controls.pop(message.id)
        elif action.startswith("vary_"):
            variation_num = int(action[-1])
            await self.handle_specific_variation(message, control_info, variation_num)

    async def handle_rerun(self, message: discord.Message, control_info: dict):
        """Rerun the same prompt with the same parameters"""
        embed = message.embeds[0]
        embed.title = f"{EMOJIS['loading']} Rerunning Generation..."
        await message.edit(embed=embed)
        
        # Create new job with same parameters
        await self.create_image_job(
            message.channel,
            control_info["prompt"],
            message,
            control_info["user_id"],
            control_info.get("parameters", {})
        )

    async def handle_upscale_menu(self, message: discord.Message, control_info: dict):
        """Show upscale options menu"""
        embed = message.embeds[0]
        embed.title = f"{EMOJIS['quality']} Select Upscale Factor"
        embed.description = "2️⃣ - 2x Upscale\n4️⃣ - 4x Upscale"
        await message.edit(embed=embed)
        
        # Clear existing reactions and add upscale options
        await message.clear_reactions()
        for reaction in UPSCALE_REACTIONS.keys():
            await message.add_reaction(reaction)
        await message.add_reaction("❌")  # Cancel option

    async def handle_variation_menu(self, message: discord.Message, control_info: dict):
        """Show variation options menu"""
        embed = message.embeds[0]
        embed.title = f"{EMOJIS['chaos']} Select Variation Strength"
        embed.description = (
            "🔵 - Subtle Variations (30%)\n"
            "🟢 - Moderate Variations (50%)\n"
            "🟡 - Strong Variations (70%)"
        )
        await message.edit(embed=embed)
        
        # Clear existing reactions and add variation options
        await message.clear_reactions()
        for reaction in VARIATION_STRENGTH.keys():
            await message.add_reaction(reaction)
        await message.add_reaction("❌")  # Cancel option

    async def handle_specific_variation(self, message: discord.Message, control_info: dict, variation_num: int):
        """Handle creating a specific variation of the image"""
        embed = message.embeds[0]
        embed.title = f"{EMOJIS['loading']} Creating Variation {variation_num}..."
        await message.edit(embed=embed)
        
        # Add variation parameters
        params = control_info.get("parameters", {}).copy()
        params["variation_index"] = variation_num
        params["variation_strength"] = 0.5  # Default to moderate variation
        
        # Create new job with variation parameters
        await self.create_image_job(
            message.channel,
            control_info["prompt"],
            message,
            control_info["user_id"],
            params
        )

    async def handle_save(self, message: discord.Message, control_info: dict):
        """Save the image to user's favorites"""
        # Create favorites if not exists
        async with self.config.user_from_id(control_info["user_id"]).favorites() as favorites:
            favorites.append({
                "prompt": control_info["prompt"],
                "image_url": control_info["image_url"],
                "parameters": control_info.get("parameters", {}),
                "timestamp": datetime.now().isoformat()
            })
        
        # Confirm save
        embed = message.embeds[0]
        original_title = embed.title
        embed.title = f"{EMOJIS['success']} Saved to Favorites!"
        await message.edit(embed=embed)
        
        # Revert title after 2 seconds
        await asyncio.sleep(2)
        embed.title = original_title
        await message.edit(embed=embed)

    async def create_image_job(
        self,
        channel: discord.TextChannel,
        prompt: str,
        message: discord.Message,
        user_id: int,
        params: Dict[str, Any]
    ) -> None:
        """Create and manage a new image generation job."""
        settings = await self.config.all()
        
        try:
            async with self.session.post("/imagine", json={
                "prompt": prompt,
                **params,
                "webhook_url": settings.get("webhook_url")
            }) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    await message.edit(
                        embed=discord.Embed(
                            title=f"{EMOJIS['error']} API Error",
                            description=f"Error: {error}",
                            color=COLORS["error"]
                        )
                    )
                    return
                
                data = await resp.json()
                job_id = data["job_id"]
                
                # Store job information
                self.active_jobs[job_id] = {
                    "user_id": user_id,
                    "message": message,
                    "channel": channel,
                    "type": "imagine",
                    "prompt": prompt,
                    "parameters": params,
                    "timestamp": datetime.now()
                }
                
                if user_id not in self.user_jobs:
                    self.user_jobs[user_id] = set()
                self.user_jobs[user_id].add(job_id)
                
        except Exception as e:
            log.error(f"Error creating image job: {e}")
            await message.edit(
                embed=discord.Embed(
                    title=f"{EMOJIS['error']} Error",
                    description=f"An error occurred: {str(e)}",
                    color=COLORS["error"]
                )
            ) 