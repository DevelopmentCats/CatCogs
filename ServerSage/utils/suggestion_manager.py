"""
😼 SuggestionManager - Handling suggestions with FELINE GRACE!
"""

import discord
from typing import Dict, List, Optional, Union
import json
from datetime import datetime
import asyncio

class SuggestionManager:
    """Manages server improvement suggestions with the precision of a cat stalking its prey"""
    
    def __init__(self):
        self.pending_suggestions: Dict[str, Dict] = {}  # suggestion_id -> suggestion
        self.modified_suggestions: Dict[str, Dict] = {}  # suggestion_id -> modified_suggestion
        self.approved_suggestions: List[str] = []  # List of approved suggestion_ids
        self.denied_suggestions: List[str] = []  # List of denied suggestion_ids
        
    async def create_suggestion_embed(self, suggestion: Dict, is_modified: bool = False) -> discord.Embed:
        """Creates a PURRFECT embed for displaying a suggestion"""
        embed = discord.Embed(
            title="🐱 Server Improvement Suggestion",
            color=discord.Color.purple() if not is_modified else discord.Color.green()
        )
        
        # Add suggestion details
        embed.add_field(
            name="📋 Description",
            value=suggestion["description"],
            inline=False
        )
        embed.add_field(
            name="💭 Reason",
            value=suggestion["reason"],
            inline=False
        )
        embed.add_field(
            name="⚡ Priority",
            value=suggestion["priority"],
            inline=True
        )
        embed.add_field(
            name="🎯 Type",
            value=suggestion["type"],
            inline=True
        )
        
        # Add impact scores
        impact = suggestion["impact"]
        embed.add_field(
            name="📊 Impact Scores",
            value=f"Organization: {impact['organization']}/10\n"
                  f"Engagement: {impact['engagement']}/10\n"
                  f"Growth: {impact['growth']}/10",
            inline=False
        )
        
        # Add action details
        action = suggestion["action"]
        action_details = "\n".join(f"{k}: {v}" for k, v in action.items())
        embed.add_field(
            name="⚙️ Action Details",
            value=f"```{action_details}```",
            inline=False
        )
        
        if is_modified:
            embed.set_footer(text="✏️ This suggestion has been modified!")
        
        return embed
        
    async def display_suggestions(self, ctx) -> None:
        """Displays all pending suggestions with interactive buttons"""
        for suggestion_id, suggestion in self.pending_suggestions.items():
            embed = await self.create_suggestion_embed(suggestion)
            
            # Create action buttons
            view = SuggestionView(self, suggestion_id)
            await ctx.send(embed=embed, view=view)
            
    async def modify_suggestion(self, suggestion_id: str, field: str, value: str) -> bool:
        """Modifies a specific field of a suggestion"""
        if suggestion_id not in self.pending_suggestions:
            return False
            
        # Create modified version if it doesn't exist
        if suggestion_id not in self.modified_suggestions:
            self.modified_suggestions[suggestion_id] = self.pending_suggestions[suggestion_id].copy()
            
        suggestion = self.modified_suggestions[suggestion_id]
        
        # Handle nested fields (e.g., "action.name")
        if "." in field:
            main_field, sub_field = field.split(".")
            if main_field in suggestion and isinstance(suggestion[main_field], dict):
                suggestion[main_field][sub_field] = value
        else:
            suggestion[field] = value
            
        return True
        
    async def approve_suggestion(self, suggestion_id: str) -> bool:
        """Approves a suggestion for implementation"""
        if suggestion_id in self.pending_suggestions:
            self.approved_suggestions.append(suggestion_id)
            return True
        return False
        
    async def deny_suggestion(self, suggestion_id: str) -> bool:
        """Denies a suggestion"""
        if suggestion_id in self.pending_suggestions:
            self.denied_suggestions.append(suggestion_id)
            return True
        return False
        
    def get_approved_suggestions(self) -> List[Dict]:
        """Returns all approved suggestions in their final form"""
        approved = []
        for suggestion_id in self.approved_suggestions:
            if suggestion_id in self.modified_suggestions:
                approved.append(self.modified_suggestions[suggestion_id])
            else:
                approved.append(self.pending_suggestions[suggestion_id])
        return approved
        
class SuggestionView(discord.ui.View):
    """Interactive view for managing suggestions"""
    
    def __init__(self, manager: SuggestionManager, suggestion_id: str):
        super().__init__(timeout=None)
        self.manager = manager
        self.suggestion_id = suggestion_id
        
    @discord.ui.button(label="✏️ Modify", style=discord.ButtonStyle.primary)
    async def modify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Opens a modal for modifying the suggestion"""
        modal = ModifySuggestionModal(self.manager, self.suggestion_id)
        await interaction.response.send_modal(modal)
        
    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Approves the suggestion"""
        await self.manager.approve_suggestion(self.suggestion_id)
        await interaction.response.send_message("Suggestion approved! 😸", ephemeral=True)
        
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Denies the suggestion"""
        await self.manager.deny_suggestion(self.suggestion_id)
        await interaction.response.send_message("Suggestion denied! 😿", ephemeral=True)
        
    @discord.ui.button(label="👀 Preview", style=discord.ButtonStyle.secondary)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Shows a preview of the suggestion's effects"""
        suggestion = self.manager.modified_suggestions.get(
            self.suggestion_id,
            self.manager.pending_suggestions[self.suggestion_id]
        )
        embed = await self.manager.create_suggestion_embed(suggestion, is_modified=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
class ModifySuggestionModal(discord.ui.Modal):
    """Modal for modifying suggestion details"""
    
    def __init__(self, manager: SuggestionManager, suggestion_id: str):
        super().__init__(title="🐱 Modify Suggestion")
        self.manager = manager
        self.suggestion_id = suggestion_id
        
        # Get current suggestion
        suggestion = manager.modified_suggestions.get(
            suggestion_id,
            manager.pending_suggestions[suggestion_id]
        )
        
        # Add fields based on suggestion type
        self.field_inputs = {}
        for field, value in suggestion["action"].items():
            self.field_inputs[field] = discord.ui.TextInput(
                label=field.capitalize(),
                default=str(value),
                required=True
            )
            self.add_item(self.field_inputs[field])
            
    async def on_submit(self, interaction: discord.Interaction):
        """Handles the submission of modified values"""
        modified = False
        for field, input_field in self.field_inputs.items():
            if await self.manager.modify_suggestion(
                self.suggestion_id,
                f"action.{field}",
                input_field.value
            ):
                modified = True
                
        if modified:
            await interaction.response.send_message(
                "Suggestion modified! Use the Preview button to see changes! 😸",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "No changes were made! 😿",
                ephemeral=True
            )
