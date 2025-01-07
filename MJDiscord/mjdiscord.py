from typing import Optional, Literal, Dict, Any
import discord
import asyncio
import json
import re
import logging
from datetime import datetime, timedelta
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, pagify
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS

# Set up logging
log = logging.getLogger("red.mjdiscord")

# Emoji reactions for different actions
UPSCALE_REACTIONS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
VARIATION_REACTIONS = ["🔄"]
CUSTOM_ZOOM_REACTIONS = ["🔍"]
BETA_REACTIONS = ["🅱️"]
ASPECT_RATIOS = ["1:1", "16:9", "2:3", "4:3", "3:2", "2:1", "1:2"]  # Available aspect ratios
STYLE_VALUES = range(0, 1001)  # 0-1000 for --stylize
CHAOS_VALUES = range(0, 101)   # 0-100 for --chaos
QUALITY_VALUES = [".25", ".5", "1"]  # Quality values for --quality
VERSION_VALUES = ["5.1", "5.2", "niji"]  # MJ model versions
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
    "channel": "📺",
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

# Progress bar for visual feedback
def get_progress_bar(percent: int) -> str:
    filled = "█" * (percent // 10)
    empty = "░" * (10 - (percent // 10))
    return f"{filled}{empty} {percent}%"

class MJDiscord(commands.Cog):
    """MidJourney integration for Red-DiscordBot"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=897234789,
            force_registration=True
        )
        
        default_global = {
            "mj_channel_id": None,     # Channel where MidJourney bot is active
            "mj_server_id": None,      # Server where MidJourney bot is active
            "mj_bot_id": None,         # MidJourney bot's ID
            "allowed_roles": [],       # Roles allowed to use the cog
            "is_configured": False,    # Whether the cog is configured
            "auto_reactions": True,    # Whether to automatically add reactions
            "max_jobs_per_user": 3,    # Maximum concurrent jobs per user
            "cooldown_minutes": 1      # Cooldown between commands
        }
        
        self.config.register_global(**default_global)
        
        # Store active imagine requests and their original channels
        self.active_requests: Dict[int, Dict[str, Any]] = {}  # user_id -> {message, channel, type}
        self.message_cache: Dict[str, Dict[str, Any]] = {}    # message_id -> {user_id, type, original_msg}

        # Start background tasks
        try:
            self.cleanup_task = self.bot.loop.create_task(self.cleanup_old_requests())
            self.cache_cleanup_task = self.bot.loop.create_task(self.cleanup_message_cache())
        except Exception as e:
            log.error(f"Error starting cleanup tasks: {e}")
            raise
        
        # Register message listener
        self.bot.add_listener(self.on_message, "on_message")
        self.bot.add_listener(self.on_reaction_add, "on_reaction_add")

    def cog_unload(self):
        """Cleanup when cog is unloaded"""
        self.cleanup_task.cancel()
        self.cache_cleanup_task.cancel()

    async def cleanup_message_cache(self):
        """Background task to clean up old message cache entries"""
        while True:
            try:
                current_time = datetime.now()
                # Clean up cache entries older than 2 hours
                self.message_cache = {
                    msg_id: data
                    for msg_id, data in self.message_cache.items()
                    if current_time - data.get("timestamp", current_time) < timedelta(hours=2)
                }
                await asyncio.sleep(300)  # Run every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in message cache cleanup task: {e}")
                await asyncio.sleep(300)

    async def cleanup_old_requests(self):
        """Background task to clean up old requests"""
        while True:
            try:
                current_time = datetime.now()
                # Clean up requests older than 1 hour
                self.active_requests = {
                    user_id: data
                    for user_id, data in self.active_requests.items()
                    if current_time - data.get("timestamp", current_time) < timedelta(hours=1)
                }
                await asyncio.sleep(300)  # Run every 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(300)

    async def on_message(self, message: discord.Message):
        """Handle MidJourney bot responses"""
        if not message.author.bot or not message.embeds:
            return

        settings = await self.config.all()
        if not settings["is_configured"] or message.author.id != settings["mj_bot_id"]:
            return

        # Check if this is a response to one of our requests
        for user_id, request_data in self.active_requests.items():
            if not request_data.get("waiting_response"):
                continue

            # Check if this is a MidJourney response
            if len(message.embeds) > 0 and message.embeds[0].title and "Job ID:" in message.embeds[0].title:
                original_msg = request_data.get("message")
                original_channel = request_data.get("channel")

                if not original_msg or not original_channel:
                    continue

                # Update the original message with the results
                try:
                    image_url = message.embeds[0].image.url if message.embeds[0].image else None
                    if image_url:
                        embed = discord.Embed(
                            title=f"{EMOJIS['art']} Image Generated Successfully!",
                            color=COLORS["success"]
                        )
                        embed.set_image(url=image_url)
                        
                        # Add prompt with proper formatting
                        prompt_value = request_data.get("prompt", "Unknown prompt")
                        if len(prompt_value) > 1024:
                            prompt_value = prompt_value[:1021] + "..."
                        embed.add_field(
                            name=f"{EMOJIS['wand']} Prompt",
                            value=box(prompt_value),
                            inline=False
                        )
                        
                        # Add controls explanation
                        embed.add_field(
                            name=f"{EMOJIS['info']} Available Actions",
                            value=(
                                "**Upscale Image:** Click 1️⃣-4️⃣\n"
                                "**Create Variations:** Click 🔄\n"
                            ),
                            inline=False
                        )
                        
                        # Add footer with job completion time
                        embed.set_footer(
                            text=f"Generated in {(datetime.now() - request_data.get('timestamp', datetime.now())).seconds} seconds"
                        )

                        await original_msg.edit(content=None, embed=embed)
                        
                        # Cache the message for reaction handling
                        self.message_cache[message.id] = {
                            "user_id": user_id,
                            "type": "imagine",
                            "original_msg": original_msg,
                            "timestamp": datetime.now()
                        }
                        
                        # Add reaction controls if enabled
                        if settings["auto_reactions"]:
                            try:
                                for reaction in UPSCALE_REACTIONS + VARIATION_REACTIONS:
                                    await message.add_reaction(reaction)
                            except discord.Forbidden:
                                log.warning(f"Missing permissions to add reactions in channel {message.channel.id}")
                            except discord.HTTPException as e:
                                log.error(f"Error adding reactions: {e}")
                        
                        # Mark request as completed
                        request_data["waiting_response"] = False
                        
                except discord.NotFound:
                    # Original message was deleted
                    log.debug(f"Original message {original_msg.id} was deleted")
                    pass
                except discord.Forbidden:
                    log.error(f"Missing permissions to edit message in channel {original_channel.id}")
                except Exception as e:
                    log.error(f"Error handling MidJourney response: {e}")
                    try:
                        await original_channel.send(f"❌ Error processing image: {str(e)}")
                    except:
                        pass

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Handle reactions on MidJourney images"""
        if user.bot:
            return

        message = reaction.message
        settings = await self.config.all()
        
        # Check if this is a cached message
        cached_data = self.message_cache.get(message.id)
        if not cached_data or cached_data["user_id"] != user.id:
            return

        # Handle different reaction types
        try:
            if str(reaction.emoji) in UPSCALE_REACTIONS:
                number = UPSCALE_REACTIONS.index(str(reaction.emoji)) + 1
                await self.handle_upscale(message, number, user, cached_data["original_msg"])
            
            elif str(reaction.emoji) in VARIATION_REACTIONS:
                await self.handle_variation(message, user, cached_data["original_msg"])
            
            # Remove the user's reaction
            await reaction.remove(user)
            
        except Exception as e:
            print(f"Error handling reaction: {e}")

    async def handle_upscale(self, message: discord.Message, number: int, user: discord.User, original_msg: discord.Message):
        """Handle upscale reaction"""
        settings = await self.config.all()
        mj_channel = self.bot.get_channel(settings["mj_channel_id"])
        
        if not mj_channel:
            return
        
        try:
            # Send the upscale command
            await mj_channel.send(f"/upscale {number}")
            
            # Update the original message
            embed = original_msg.embeds[0]
            embed.set_field_at(1, name="Status", value="Upscaling image... Please wait!")
            await original_msg.edit(embed=embed)
            
            # Store the new request
            self.active_requests[user.id] = {
                "message": original_msg,
                "channel": original_msg.channel,
                "type": "upscale",
                "waiting_response": True,
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            await original_msg.channel.send(f"❌ Error upscaling image: {str(e)}")

    async def handle_variation(self, message: discord.Message, user: discord.User, original_msg: discord.Message):
        """Handle variation reaction"""
        settings = await self.config.all()
        mj_channel = self.bot.get_channel(settings["mj_channel_id"])
        
        if not mj_channel:
            return
        
        try:
            # Send the variation command
            await mj_channel.send(f"/variation")
            
            # Update the original message
            embed = original_msg.embeds[0]
            embed.set_field_at(1, name="Status", value="Creating variations... Please wait!")
            await original_msg.edit(embed=embed)
            
            # Store the new request
            self.active_requests[user.id] = {
                "message": original_msg,
                "channel": original_msg.channel,
                "type": "variation",
                "waiting_response": True,
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            await original_msg.channel.send(f"❌ Error creating variations: {str(e)}")

    @commands.group()
    @commands.admin_or_permissions(administrator=True)
    async def mjset(self, ctx: commands.Context):
        """Configure MidJourney integration settings"""
        pass

    @mjset.command(name="setup")
    async def setup(self, ctx: commands.Context):
        """
        Interactive setup for MidJourney integration
        
        This will guide you through:
        1. Setting up the MidJourney channel
        2. Configuring allowed roles
        3. Verifying the setup
        """
        try:
            # Step 1: Get MidJourney Channel
            await ctx.send("Please mention or enter the ID of the channel where the MidJourney bot is active:")
            
            def channel_check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            
            msg = await self.bot.wait_for('message', check=channel_check, timeout=60)
            
            # Handle channel mention or ID
            if msg.channel_mentions:
                channel = msg.channel_mentions[0]
            else:
                try:
                    channel = ctx.guild.get_channel(int(msg.content))
                    if not channel:
                        await ctx.send("❌ Invalid channel. Setup cancelled.")
                        return
                except ValueError:
                    await ctx.send("❌ Invalid channel ID. Setup cancelled.")
                    return
            
            # Step 2: Verify MidJourney bot in channel
            mj_bot = None
            for member in channel.members:
                if member.bot and "midjourney" in member.name.lower():
                    mj_bot = member
                    break
            
            if not mj_bot:
                await ctx.send("❌ MidJourney bot not found in the specified channel. Make sure the bot is added to the channel.")
                return
            
            # Step 3: Get allowed roles
            await ctx.send("Please mention the roles that should be allowed to use MidJourney commands (mention multiple roles in one message, or type 'everyone' to allow all users):")
            
            msg = await self.bot.wait_for('message', check=channel_check, timeout=60)
            
            allowed_roles = []
            if msg.content.lower() != "everyone":
                if not msg.role_mentions:
                    await ctx.send("❌ No roles mentioned. Setup cancelled.")
                    return
                allowed_roles = [role.id for role in msg.role_mentions]
            
            # Step 4: Configure additional settings
            await ctx.send("Would you like to configure additional settings? (yes/no)")
            msg = await self.bot.wait_for('message', check=channel_check, timeout=60)
            
            if msg.content.lower().startswith('y'):
                # Configure auto reactions
                await ctx.send("Enable automatic reaction controls? (yes/no)")
                msg = await self.bot.wait_for('message', check=channel_check, timeout=60)
                auto_reactions = msg.content.lower().startswith('y')
                
                # Configure job limits
                await ctx.send("How many concurrent jobs should users be allowed? (1-5)")
                msg = await self.bot.wait_for('message', check=channel_check, timeout=60)
                try:
                    max_jobs = max(1, min(5, int(msg.content)))
                except ValueError:
                    max_jobs = 3
            else:
                auto_reactions = True
                max_jobs = 3
            
            # Save configuration
            async with self.config.all() as settings:
                settings["mj_channel_id"] = channel.id
                settings["mj_server_id"] = ctx.guild.id
                settings["mj_bot_id"] = mj_bot.id
                settings["allowed_roles"] = allowed_roles
                settings["auto_reactions"] = auto_reactions
                settings["max_jobs_per_user"] = max_jobs
                settings["is_configured"] = True
            
            await ctx.send("✅ MidJourney integration configured successfully!")
            
        except asyncio.TimeoutError:
            await ctx.send("Setup timed out. Please try again.")

    @mjset.command(name="reactions")
    @commands.admin_or_permissions(administrator=True)
    async def toggle_reactions(self, ctx: commands.Context, enabled: bool = None):
        """Toggle automatic reaction controls"""
        if enabled is None:
            current = await self.config.auto_reactions()
            await ctx.send(f"Automatic reactions are currently {'enabled' if current else 'disabled'}")
            return
            
        await self.config.auto_reactions.set(enabled)
        await ctx.send(f"✅ Automatic reactions {'enabled' if enabled else 'disabled'}")

    @commands.hybrid_command()
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
        """
        Generate an image using MidJourney
        
        Parameters
        ----------
        prompt: str
            The prompt to generate an image from
        aspect: Optional[str]
            Aspect ratio (e.g., '1:1', '16:9', '2:3')
        stylize: Optional[int]
            Stylization value (0-1000)
        chaos: Optional[int]
            Chaos value (0-100)
        quality: Optional[str]
            Quality value (.25, .5, or 1)
        seed: Optional[str]
            Seed number for reproducible results
        version: Optional[str]
            MidJourney model version (5.1, 5.2, or niji)
        no_style: Optional[bool]
            Whether to disable MJ's base stylization
        """
        # Apply cooldown from config
        bucket = commands.CooldownMapping.from_cooldown(
            1, await self.config.cooldown_minutes() * 60, commands.BucketType.user
        )
        if retry_after := bucket.get_bucket(ctx.message).update_rate_limit():
            raise commands.CommandOnCooldown(bucket, retry_after, commands.BucketType.user)

        settings = await self.config.all()
        
        if not settings["is_configured"]:
            await ctx.send("❌ MidJourney integration not configured. Ask an admin to run `mjset setup`")
            return
        
        # Check if user has permission
        if settings["allowed_roles"] and not any(role.id in settings["allowed_roles"] for role in ctx.author.roles):
            await ctx.send("❌ You don't have permission to use MidJourney commands.")
            return
        
        # Check concurrent jobs limit
        active_jobs = len([req for req in self.active_requests.values() 
                         if req.get("user_id") == ctx.author.id and req.get("waiting_response")])
        if active_jobs >= settings["max_jobs_per_user"]:
            await ctx.send(f"❌ You have too many active jobs. Please wait for them to complete (max: {settings['max_jobs_per_user']}).")
            return

        # Get the MidJourney channel
        mj_channel = self.bot.get_channel(settings["mj_channel_id"])
        if not mj_channel:
            await ctx.send("❌ MidJourney channel not found. Please ask an admin to reconfigure.")
            return

        # Validate and build parameters
        params = []
        
        # Validate aspect ratio
        if aspect:
            if aspect not in ASPECT_RATIOS:
                await ctx.send(f"❌ Invalid aspect ratio. Available options: {', '.join(ASPECT_RATIOS)}")
                return
            params.append(f"--ar {aspect}")
        
        # Validate stylize
        if stylize is not None:
            if stylize not in STYLE_VALUES:
                await ctx.send("❌ Stylize value must be between 0 and 1000.")
                return
            params.append(f"--stylize {stylize}")
        
        # Validate chaos
        if chaos is not None:
            if chaos not in CHAOS_VALUES:
                await ctx.send("❌ Chaos value must be between 0 and 100.")
                return
            params.append(f"--chaos {chaos}")
        
        # Validate quality
        if quality:
            if quality not in QUALITY_VALUES:
                await ctx.send("❌ Quality must be .25, .5, or 1")
                return
            params.append(f"--quality {quality}")
        
        # Validate seed
        if seed:
            if not SEED_PATTERN.match(seed):
                await ctx.send("❌ Invalid seed number. Must be a number between 0-9999999999.")
                return
            params.append(f"--seed {seed}")
        
        # Validate version
        if version:
            if version not in VERSION_VALUES:
                await ctx.send(f"❌ Invalid version. Available options: {', '.join(VERSION_VALUES)}")
                return
            params.append(f"--v {version}")
        
        # Add no-style parameter
        if no_style:
            params.append("--no style")
        
        # Build the final prompt
        final_prompt = f"{prompt} {' '.join(params)}"
        
        # Send the imagine command
        try:
            # Create embed for tracking
            embed = discord.Embed(
                title=f"{EMOJIS['art']} Processing Image Generation",
                description=get_progress_bar(10),
                color=COLORS["processing"]
            )
            
            # Format prompt nicely
            formatted_prompt = box(prompt)
            embed.add_field(
                name=f"{EMOJIS['wand']} Prompt",
                value=formatted_prompt if len(formatted_prompt) <= 1024 else f"{formatted_prompt[:1021]}...",
                inline=False
            )
            
            # Add parameters in a clean format
            if params:
                param_list = []
                for param in params:
                    if "--ar" in param:
                        param_list.append(f"{EMOJIS['aspect']} {param}")
                    elif "--stylize" in param:
                        param_list.append(f"{EMOJIS['style']} {param}")
                    elif "--chaos" in param:
                        param_list.append(f"{EMOJIS['chaos']} {param}")
                    elif "--quality" in param:
                        param_list.append(f"{EMOJIS['quality']} {param}")
                    elif "--seed" in param:
                        param_list.append(f"{EMOJIS['seed']} {param}")
                    elif "--v" in param:
                        param_list.append(f"{EMOJIS['version']} {param}")
                    else:
                        param_list.append(param)
                
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
            
            embed.set_footer(text="This may take a few minutes...")
            
            # Send progress message in the original channel
            progress_msg = await ctx.send(embed=embed)
            
            # Send the actual command to MidJourney's channel
            mj_msg = await mj_channel.send(f"/imagine prompt: {final_prompt}")
            
            # Store the request for tracking
            self.active_requests[ctx.author.id] = {
                "message": progress_msg,
                "channel": ctx.channel,
                "type": "imagine",
                "prompt": final_prompt,
                "waiting_response": True,
                "timestamp": datetime.now()
            }
            
            # Update progress message
            embed.set_field_at(-1, name="Status", value="Request sent! Waiting for MidJourney...")
            await progress_msg.edit(embed=embed)
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send messages in the MidJourney channel.")
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {str(e)}")
        
    @commands.hybrid_command()
    async def mjstatus(self, ctx: commands.Context):
        """Check MidJourney integration status"""
        settings = await self.config.all()
        
        if not settings["is_configured"]:
            await ctx.send("❌ MidJourney integration not configured.")
            return
        
        mj_channel = self.bot.get_channel(settings["mj_channel_id"])
        if not mj_channel:
            await ctx.send("❌ MidJourney channel not found. Please ask an admin to reconfigure.")
            return
        
        # Check if user has permission
        if settings["allowed_roles"] and not any(role.id in settings["allowed_roles"] for role in ctx.author.roles):
            allowed_roles = [ctx.guild.get_role(role_id).name for role_id in settings["allowed_roles"] if ctx.guild.get_role(role_id)]
            await ctx.send(f"ℹ️ MidJourney is configured but restricted to these roles: {', '.join(allowed_roles)}")
            return
        
        # Count active jobs
        user_jobs = len([req for req in self.active_requests.values() 
                        if req.get("user_id") == ctx.author.id and req.get("waiting_response")])
        
        embed = discord.Embed(
            title=f"{EMOJIS['info']} MidJourney Status",
            color=COLORS["brand"]
        )
        
        # Add server status
        embed.add_field(
            name=f"{EMOJIS['channel']} Active Channel",
            value=mj_channel.mention
        )
        
        # Add job status with progress bar
        max_jobs = settings['max_jobs_per_user']
        progress = (user_jobs / max_jobs) * 100
        embed.add_field(
            name=f"{EMOJIS['jobs']} Active Jobs",
            value=f"{get_progress_bar(int(progress))}\n{user_jobs}/{max_jobs} slots used",
            inline=False
        )
        
        # Add feature status
        features = []
        features.append(f"{EMOJIS['success' if settings['auto_reactions'] else 'error']} Reaction Controls")
        
        embed.add_field(
            name="Features",
            value="\n".join(features),
            inline=False
        )
        
        # Add footer with refresh hint
        embed.set_footer(text="Use /mjstatus again to refresh")

        await ctx.send(embed=embed) 

    @commands.hybrid_command()
    async def mjhelp(self, ctx: commands.Context):
        """Show detailed help for MidJourney commands and parameters"""
        embed = discord.Embed(
            title=f"{EMOJIS['help']} MidJourney Command Guide",
            description=(
                f"{EMOJIS['info']} Generate amazing images using simple commands!\n"
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
            
            f"{EMOJIS['version']} **Version** (--v)\n"
            f"Options: {', '.join(VERSION_VALUES)}\n"
            "Example: `--v niji`\n"
        ]
        
        embed.add_field(
            name="Parameters",
            value="\n".join(parameters),
            inline=False
        )
        
        # Quick examples
        examples = [
            "🖼️ **Landscape:** `/imagine beautiful sunset over mountains --ar 16:9 --quality 1`",
            "👤 **Portrait:** `/imagine professional headshot --ar 2:3 --v 5.2`",
            "🎨 **Artistic:** `/imagine abstract art --stylize 1000 --chaos 100`",
            "📺 **Anime:** `/imagine cute anime character --v niji --stylize 800`"
        ]
        
        embed.add_field(
            name="Example Commands",
            value="\n".join(examples),
            inline=False
        )
        
        # Reaction controls with better formatting
        controls = [
            "1️⃣-4️⃣ - Upscale image to high resolution",
            "🔄 - Create variations of the image"
        ]
        
        embed.add_field(
            name=f"{EMOJIS['info']} Reaction Controls",
            value="\n".join(controls),
            inline=False
        )
        
        # Add tips in footer
        embed.set_footer(text="💡 Tip: Use --quality 1 for best results, but note it uses more of your MidJourney quota")

        await ctx.send(embed=embed) 