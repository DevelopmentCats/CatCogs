from typing import Dict, List, Optional
import discord
from discord.ext import commands
import logging
from .suggestion_manager import SuggestionManager
from .gemini_client import GeminiClient

log = logging.getLogger("red.serversage.analyzer")

class ServerAnalyzer:
    """🔍 Analyzes Discord server structure and creates info for AI processing"""
    
    def __init__(self, bot):
        self.bot = bot
        self.suggestion_manager = SuggestionManager()
        
    async def initialize(self):
        """Initialize the analyzer with API key"""
        self.gemini = await GeminiClient(self.bot.get_api_key())
        
    @staticmethod
    async def gather_server_info(guild: discord.Guild) -> Dict:
        """Gather comprehensive information about the server"""
        
        # Get channel activity data
        channel_activity = {}
        for channel in guild.text_channels:
            try:
                messages = [msg async for msg in channel.history(limit=100)]
                channel_activity[channel.id] = len(messages)
            except:
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

    async def create_change_plan(self, suggestions: List[Dict]) -> List[Dict]:
        """Convert AI suggestions into actionable changes"""
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

    async def analyze_server(self, ctx, style_prompt: Optional[str] = None) -> None:
        """Analyzes the server and presents interactive suggestions"""
        if not hasattr(self, 'gemini'):
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

    async def apply_suggestions(self, ctx) -> None:
        """Applies all approved suggestions"""
        changes = self.suggestion_manager.get_suggestions(ctx.guild.id)
        if not changes:
            await ctx.send("No pending suggestions to apply!")
            return
            
        results = await self.apply_changes(ctx.guild, changes)
        await ctx.send("✨ Changes Applied:\n" + "\n".join(results))
        
        # Clear applied suggestions
        self.suggestion_manager.clear_suggestions(ctx.guild.id)

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
                
            except discord.Forbidden:
                results.append(f"❌ Missing permissions for {change['action']}")
            except Exception as e:
                log.error(f"Error applying change {change}: {str(e)}")
                results.append(f"❌ Failed to {change['action']}: {str(e)}")
        
        return results

    def _format_change(self, change: Dict) -> str:
        """Format a change for display"""
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
