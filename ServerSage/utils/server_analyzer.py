from typing import Dict, List, Optional
import discord
from discord.ext import commands
import logging
from redbot.core import Config
from .suggestion_manager import SuggestionManager
from .gemini_client import GeminiClient

log = logging.getLogger("red.serversage.analyzer")

class ServerAnalyzer:
    """🔍 Analyzes Discord server structure and creates info for AI processing"""
    
    def __init__(self, bot, config: Config):
        self.bot = bot
        self.config = config
        self.suggestion_manager = SuggestionManager()
        self.gemini = None
        
    async def initialize(self):
        """Initialize the analyzer with API key"""
        try:
            api_key = await self.config.api_key()
            if not api_key:
                raise ValueError("API key not set")
            self.gemini = GeminiClient(api_key)
        except Exception as e:
            log.error(f"Failed to initialize GeminiClient: {str(e)}")
            raise
        
    @staticmethod
    async def gather_server_info(guild: discord.Guild) -> Dict:
        """Gather comprehensive information about the server"""
        try:
            # Get channel activity data
            channel_activity = {}
            for channel in guild.text_channels:
                try:
                    messages = [msg async for msg in channel.history(limit=100)]
                    channel_activity[channel.id] = len(messages)
                except (discord.Forbidden, discord.HTTPException) as e:
                    log.warning(f"Could not fetch history for channel {channel.name}: {str(e)}")
                    channel_activity[channel.id] = 0
                except Exception as e:
                    log.error(f"Unexpected error fetching channel history: {str(e)}")
                    channel_activity[channel.id] = 0

            # Analyze roles and permissions
            role_analysis = {}
            for role in guild.roles:
                if not role.is_default():
                    role_analysis[role.id] = {
                        "name": role.name,
                        "position": role.position,
                        "color": str(role.color),
                        "mentionable": role.mentionable,
                        "hoisted": role.hoist,
                        "permissions": [perm[0] for perm in role.permissions if perm[1]]
                    }

            # Get channel information
            channels_info = {}
            for channel in guild.channels:
                channels_info[channel.id] = {
                    "name": channel.name,
                    "type": str(channel.type),
                    "position": channel.position,
                    "category": channel.category.name if channel.category else None,
                    "activity": channel_activity.get(channel.id, 0) if isinstance(channel, discord.TextChannel) else None
                }

            return {
                "server_name": guild.name,
                "member_count": guild.member_count,
                "channels": channels_info,
                "roles": role_analysis,
                "channel_activity": channel_activity
            }
        except Exception as e:
            log.error(f"Error gathering server info: {str(e)}")
            raise

    async def create_change_plan(self, suggestions: List[Dict]) -> List[Dict]:
        """Convert AI suggestions into actionable changes"""
        try:
            changes = []
            for suggestion in suggestions:
                if suggestion["type"] == "create_channel":
                    changes.append({
                        "action": "create_channel",
                        "name": suggestion["name"],
                        "category": suggestion.get("category"),
                        "topic": suggestion.get("topic"),
                        "type": suggestion.get("channel_type", "text")
                    })
                elif suggestion["type"] == "delete_channel":
                    changes.append({
                        "action": "delete_channel",
                        "name": suggestion["name"]
                    })
                elif suggestion["type"] == "rename_channel":
                    changes.append({
                        "action": "rename_channel",
                        "old_name": suggestion["old_name"],
                        "new_name": suggestion["new_name"],
                        "update_topic": suggestion.get("update_topic", False),
                        "new_topic": suggestion.get("new_topic")
                    })
                elif suggestion["type"] == "create_category":
                    changes.append({
                        "action": "create_category",
                        "name": suggestion["name"],
                        "position": suggestion.get("position")
                    })
                elif suggestion["type"] == "move_channel":
                    changes.append({
                        "action": "move_channel",
                        "channel_name": suggestion["channel"],
                        "category": suggestion["category"],
                        "position": suggestion.get("position"),
                        "sync_permissions": suggestion.get("sync_permissions", True)
                    })
                elif suggestion["type"] == "update_permissions":
                    changes.append({
                        "action": "update_permissions",
                        "target_type": suggestion["target_type"],
                        "target": suggestion["target"],
                        "permissions": suggestion["permissions"]
                    })
            return changes
        except Exception as e:
            log.error(f"Error creating change plan: {str(e)}")
            raise

    async def analyze_server(self, ctx, style_prompt: Optional[str] = None) -> None:
        """Analyzes the server and presents interactive suggestions"""
        try:
            if not self.gemini:
                await self.initialize()
            
            server_info = await self.gather_server_info(ctx.guild)
            suggestions = await self.gemini.analyze_server(server_info, style_prompt)
            changes = await self.create_change_plan(suggestions)
            
            # Store suggestions for later approval
            self.suggestion_manager.store_suggestions(ctx.guild.id, changes)
            
            # Present suggestions to user
            await ctx.send("🔍 Server Analysis Complete! Here are my suggestions:")
            for i, change in enumerate(changes, 1):
                await ctx.send(f"{i}. {self._format_change(change)}")
            
            await ctx.send("Use `]serversage apply` to implement these changes!")
        except ValueError as e:
            await ctx.send(f"❌ Configuration error: {str(e)}")
        except Exception as e:
            log.error(f"Error during server analysis: {str(e)}")
            await ctx.send(f"❌ An error occurred during analysis: {str(e)}")

    async def apply_suggestions(self, ctx) -> None:
        """Applies all approved suggestions"""
        try:
            changes = self.suggestion_manager.get_suggestions(ctx.guild.id)
            if not changes:
                await ctx.send("No pending suggestions to apply!")
                return
                
            results = await self.apply_changes(ctx.guild, changes)
            await ctx.send("✨ Changes Applied:\n" + "\n".join(results))
            
            # Clear applied suggestions
            self.suggestion_manager.clear_suggestions(ctx.guild.id)
        except Exception as e:
            log.error(f"Error applying suggestions: {str(e)}")
            raise

    @staticmethod
    async def apply_changes(
            guild: discord.Guild,
            changes: List[Dict],
            dry_run: bool = False
        ) -> List[str]:
        """Apply the changes to the server"""
        results = []
        
        for change in changes:
            try:
                if dry_run:
                    results.append(f"Would {change['action']}: {change}")
                    continue
                    
                if change["action"] == "create_channel":
                    category = None
                    if change.get("category"):
                        category = discord.utils.get(
                            guild.categories,
                            name=change["category"]
                        )
                    
                    channel = await guild.create_text_channel(
                        name=change["name"],
                        category=category,
                        topic=change.get("topic")
                    )
                    results.append(f"✨ Created channel: {channel.name}")
                
                elif change["action"] == "delete_channel":
                    channel = discord.utils.get(
                        guild.channels,
                        name=change["name"]
                    )
                    if channel:
                        await channel.delete()
                        results.append(f"✨ Deleted channel: {change['name']}")
                    else:
                        results.append(f"⚠️ Channel not found: {change['name']}")
                
                elif change["action"] == "rename_channel":
                    channel = discord.utils.get(
                        guild.channels,
                        name=change["old_name"]
                    )
                    if channel:
                        await channel.edit(
                            name=change["new_name"],
                            topic=change.get("new_topic", channel.topic) if change.get("update_topic") else channel.topic
                        )
                        results.append(
                            f"✨ Renamed channel: {change['old_name']} -> {change['new_name']}"
                        )
                    else:
                        results.append(f"⚠️ Channel not found: {change['old_name']}")
                
                elif change["action"] == "create_category":
                    category = await guild.create_category(
                        name=change["name"],
                        position=change.get("position")
                    )
                    results.append(f"✨ Created category: {category.name}")
                
                elif change["action"] == "move_channel":
                    channel = discord.utils.get(
                        guild.channels,
                        name=change["channel_name"]
                    )
                    category = discord.utils.get(
                        guild.categories,
                        name=change["category"]
                    )
                    if channel and category:
                        await channel.edit(
                            category=category,
                            position=change.get("position", channel.position),
                            sync_permissions=change.get("sync_permissions", True)
                        )
                        results.append(f"✨ Moved channel: {channel.name} to {category.name}")
                    else:
                        if not channel:
                            results.append(f"⚠️ Channel not found: {change['channel_name']}")
                        if not category:
                            results.append(f"⚠️ Category not found: {change['category']}")
                
                elif change["action"] == "update_permissions":
                    target = None
                    if change["target_type"] == "channel":
                        target = discord.utils.get(guild.channels, name=change["target"])
                    elif change["target_type"] == "category":
                        target = discord.utils.get(guild.categories, name=change["target"])
                    elif change["target_type"] == "role":
                        target = discord.utils.get(guild.roles, name=change["target"])
                        
                    if target:
                        await target.edit(permissions=discord.Permissions(**change["permissions"]))
                        results.append(f"✨ Updated permissions for {change['target']}")
                    else:
                        results.append(f"⚠️ Target not found: {change['target']} ({change['target_type']})")
                
            except discord.Forbidden:
                results.append(f"❌ Missing permissions for {change['action']}")
            except discord.HTTPException as e:
                results.append(f"❌ Discord API error for {change['action']}: {str(e)}")
            except Exception as e:
                log.error(f"Error applying change {change}: {str(e)}")
                results.append(f"❌ Failed to {change['action']}: {str(e)}")
        
        return results

    def _format_change(self, change: Dict) -> str:
        """Format a change for display"""
        try:
            if change["action"] == "create_channel":
                return f"Create new channel `{change['name']}`" + (f" in category `{change['category']}`" if change.get("category") else "")
            elif change["action"] == "delete_channel":
                return f"Delete channel `{change['name']}`"
            elif change["action"] == "rename_channel":
                return f"Rename channel `{change['old_name']}` to `{change['new_name']}`"
            elif change["action"] == "create_category":
                return f"Create new category `{change['name']}`"
            elif change["action"] == "move_channel":
                return f"Move channel `{change['channel_name']}` to category `{change['category']}`"
            elif change["action"] == "update_permissions":
                return f"Update permissions for {change['target_type']} `{change['target']}`"
            return str(change)
        except Exception as e:
            log.error(f"Error formatting change: {str(e)}")
            return "❌ Error formatting change"
