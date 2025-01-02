from typing import Dict, List, Optional
import discord
from discord.ext import commands
import logging
from .suggestion_manager import SuggestionManager

log = logging.getLogger("red.serversage.analyzer")

class ServerAnalyzer:
    """🔍 Analyzes Discord server structure and creates info for AI processing"""
    
    def __init__(self, bot):
        self.bot = bot
        self.gemini = GeminiClient(bot.get_api_key())
        self.suggestion_manager = SuggestionManager()
        
    @staticmethod
    async def gather_server_info(guild: discord.Guild) -> Dict:
        """Gather comprehensive information about the server"""
        
        # Get channel activity data
        channel_activity = {}
        for channel in guild.text_channels:
            try:
                messages = await channel.history(limit=100).flatten()
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
                    "permissions": [
                        perm[0] for perm in role.permissions if perm[1]
                    ],
                    "member_count": len(role.members)
                }

        # Get server features and settings
        server_features = {
            "features": list(guild.features),
            "verification_level": str(guild.verification_level),
            "explicit_content_filter": str(guild.explicit_content_filter),
            "afk_timeout": guild.afk_timeout,
            "has_boost": guild.premium_tier > 0,
            "boost_level": guild.premium_tier,
            "boost_count": guild.premium_subscription_count,
            "has_vanity_url": "VANITY_URL" in guild.features,
            "has_community_features": "COMMUNITY" in guild.features
        }

        return {
            "name": guild.name,
            "member_count": guild.member_count,
            "owner": str(guild.owner),
            "created_at": guild.created_at.isoformat(),
            "categories": [
                {
                    "name": category.name,
                    "position": category.position,
                    "channels": [
                        {
                            "name": channel.name,
                            "type": str(channel.type),
                            "position": channel.position,
                            "permissions_synced": channel.permissions_synced,
                            "nsfw": getattr(channel, "nsfw", False),
                            "topic": getattr(channel, "topic", None),
                            "slowmode_delay": getattr(channel, "slowmode_delay", 0),
                            "activity_level": channel_activity.get(channel.id, 0),
                            "is_news": isinstance(channel, discord.TextChannel) and channel.is_news(),
                            "has_threads": isinstance(channel, discord.TextChannel) and len(await channel.threads()) > 0
                        }
                        for channel in category.channels
                    ]
                }
                for category in guild.categories
            ],
            "roles": role_analysis,
            "server_features": server_features,
            "emojis": [
                {
                    "name": emoji.name,
                    "animated": emoji.animated,
                    "available": emoji.available
                }
                for emoji in guild.emojis
            ],
            "stickers": [
                {
                    "name": sticker.name,
                    "description": sticker.description
                }
                for sticker in guild.stickers
            ],
            "uncategorized_channels": [
                {
                    "name": channel.name,
                    "type": str(channel.type),
                    "activity_level": channel_activity.get(channel.id, 0)
                }
                for channel in guild.channels
                if not channel.category
            ],
            "thread_usage": any(
                isinstance(channel, discord.TextChannel) and len(await channel.threads()) > 0
                for channel in guild.text_channels
            ),
            "integration_count": len(await guild.integrations()),
            "has_welcome_screen": guild.welcome_screen is not None
        }
    
    @staticmethod
    def create_change_plan(suggestions: List[Dict]) -> List[Dict]:
        """Convert AI suggestions into actionable changes"""
        changes = []
        for suggestion in suggestions:
            try:
                if suggestion.get("type") == "create_channel":
                    changes.append({
                        "action": "create_channel",
                        "name": suggestion["name"],
                        "category": suggestion.get("category"),
                        "type": suggestion.get("channel_type", "text"),
                        "topic": suggestion.get("topic", ""),
                        "position": suggestion.get("position"),
                        "slowmode": suggestion.get("slowmode", 0),
                        "nsfw": suggestion.get("nsfw", False)
                    })
                elif suggestion.get("type") == "rename_channel":
                    changes.append({
                        "action": "rename_channel",
                        "old_name": suggestion["old_name"],
                        "new_name": suggestion["new_name"],
                        "update_topic": suggestion.get("update_topic", False),
                        "new_topic": suggestion.get("new_topic", "")
                    })
                elif suggestion.get("type") == "move_channel":
                    changes.append({
                        "action": "move_channel",
                        "channel_name": suggestion["channel_name"],
                        "category": suggestion["category"],
                        "position": suggestion.get("position"),
                        "sync_permissions": suggestion.get("sync_permissions", True)
                    })
                elif suggestion.get("type") == "create_category":
                    changes.append({
                        "action": "create_category",
                        "name": suggestion["name"],
                        "position": suggestion.get("position")
                    })
                elif suggestion.get("type") == "update_permissions":
                    changes.append({
                        "action": "update_permissions",
                        "target": suggestion["target"],
                        "target_type": suggestion["target_type"],  # channel, category, or role
                        "permissions": suggestion["permissions"]
                    })
            except KeyError as e:
                log.error(f"Missing required field in suggestion: {e}")
                continue
                
        return changes
    
    async def analyze_server(self, ctx, style_prompt: Optional[str] = None) -> None:
        """Analyzes the server and presents interactive suggestions"""
        try:
            # Get server info
            server_info = await self._gather_server_info(ctx.guild)
            
            # Get AI analysis
            analysis = await self.gemini.analyze_server(server_info, style_prompt=style_prompt)
            
            # Store suggestions in manager
            for i, suggestion in enumerate(analysis["suggestions"]):
                self.suggestion_manager.pending_suggestions[f"s{i}"] = suggestion
                
            # Display summary embed
            summary_embed = discord.Embed(
                title="😸 Server Analysis Complete!",
                description=analysis["summary"],
                color=discord.Color.purple()
            )
            
            # Add health metrics
            health = analysis["server_health"]
            summary_embed.add_field(
                name="📊 Server Health",
                value=f"Organization: {health['organization_score']}/100\n"
                      f"Engagement: {health['engagement_score']}/100\n"
                      f"Growth Potential: {health['growth_potential']}/100",
                inline=False
            )
            
            # Add style analysis if provided
            if "style_analysis" in analysis:
                summary_embed.add_field(
                    name="🎨 Style Analysis",
                    value=analysis["style_analysis"],
                    inline=False
                )
                
            await ctx.send(embed=summary_embed)
            
            # Display interactive suggestions
            await self.suggestion_manager.display_suggestions(ctx)
            
        except Exception as e:
            error_embed = discord.Embed(
                title="😿 Oops! The cat knocked something over!",
                description=f"An error occurred during analysis: {str(e)}",
                color=discord.Color.red()
            )
            await ctx.send(embed=error_embed)
            
    async def apply_suggestions(self, ctx) -> None:
        """Applies all approved suggestions"""
        approved = self.suggestion_manager.get_approved_suggestions()
        
        if not approved:
            await ctx.send("No approved suggestions to apply! 😿")
            return
            
        progress_embed = discord.Embed(
            title="🐱 Applying Suggestions",
            description="Watch me work my MAGIC!",
            color=discord.Color.green()
        )
        progress_msg = await ctx.send(embed=progress_embed)
        
        try:
            for suggestion in approved:
                # Update progress
                progress_embed.description = f"Applying: {suggestion['description']}"
                await progress_msg.edit(embed=progress_embed)
                
                # Apply the suggestion
                await self._apply_suggestion(ctx.guild, suggestion)
                
                # Add success checkmark
                progress_embed.add_field(
                    name="✅ Success!",
                    value=suggestion['description'],
                    inline=False
                )
                await progress_msg.edit(embed=progress_embed)
                
            progress_embed.description = "All suggestions have been applied! PURRFECT! 😸"
            await progress_msg.edit(embed=progress_embed)
            
        except Exception as e:
            progress_embed.description = f"😿 Oops! Something went wrong: {str(e)}"
            progress_embed.color = discord.Color.red()
            await progress_msg.edit(embed=progress_embed)
    
    @staticmethod
    async def apply_changes(
        guild: discord.Guild,
        changes: List[Dict],
        dry_run: bool = True
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
                    
                    channel_type = {
                        "text": discord.ChannelType.text,
                        "voice": discord.ChannelType.voice,
                        "news": discord.ChannelType.news
                    }.get(change["type"], discord.ChannelType.text)
                    
                    channel = await guild.create_text_channel(
                        name=change["name"],
                        category=category,
                        topic=change.get("topic", ""),
                        slowmode_delay=change.get("slowmode", 0),
                        nsfw=change.get("nsfw", False),
                        type=channel_type
                    )
                    results.append(f"✨ Created channel: {channel.name}")
                
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
    
    async def _apply_suggestion(self, guild: discord.Guild, suggestion: Dict) -> None:
        """Apply a single suggestion"""
        changes = self.create_change_plan([suggestion])
        await self.apply_changes(guild, changes, dry_run=False)
