import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, Button, View, Select
from redbot.core import Config, commands
from redbot.core.bot import Red
from datetime import datetime, timedelta
import pytz
from typing import Optional, List
import asyncio

# ... (previous code remains the same)

class RobustEventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(events={}, timezone="UTC")
        self.event_tasks = {}
        self.temp_event_data = None
        self.emoji = {
            "calendar": "📅",
            "clock": "🕒",
            "bell": "🔔",
            "repeat": "🔁",
            "description": "📝",
            "channel": "📢",
            "role": "👥",
            "success": "✅",
            "error": "❌",
            "warning": "⚠️"
        }

    def format_time(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    def get_event_color(self, event_time: datetime) -> discord.Color:
        now = datetime.now(pytz.UTC)
        time_until_event = event_time - now
        if time_until_event <= timedelta(hours=1):
            return discord.Color.red()
        elif time_until_event <= timedelta(days=1):
            return discord.Color.gold()
        else:
            return discord.Color.green()

    def create_event_embed(self, name: str, event_data: dict) -> discord.Embed:
        event_time = datetime.fromisoformat(event_data['time'])
        color = self.get_event_color(event_time)
        embed = discord.Embed(title=f"{self.emoji['calendar']} Event: {name}", color=color)
        embed.add_field(name=f"{self.emoji['clock']} Time", value=self.format_time(event_time), inline=False)
        if event_data.get('second_time'):
            second_time = datetime.combine(event_time.date(), datetime.fromisoformat(event_data['second_time']).time())
            embed.add_field(name=f"{self.emoji['clock']} Second Time", value=self.format_time(second_time), inline=False)
        embed.add_field(name=f"{self.emoji['description']} Description", value=event_data['description'], inline=False)
        embed.add_field(name=f"{self.emoji['bell']} Notifications", value=", ".join(map(str, event_data['notifications'])) + " minutes before", inline=False)
        embed.add_field(name=f"{self.emoji['repeat']} Repeat", value=event_data['repeat'].capitalize(), inline=True)
        embed.add_field(name=f"{self.emoji['channel']} Channel", value=f"<#{event_data['channel']}>", inline=True)
        embed.add_field(name=f"{self.emoji['role']} Create Role", value="Yes" if event_data['create_role'] else "No", inline=True)
        return embed

    @commands.command()
    async def list_events(self, ctx):
        """List all scheduled events."""
        events = await self.config.guild(ctx.guild).events()
        if not events:
            await ctx.send(embed=self.error_embed("No events scheduled."))
            return
        
        embeds = []
        for name, data in events.items():
            embeds.append(self.create_event_embed(name, data))
        
        if len(embeds) == 1:
            await ctx.send(embed=embeds[0])
        else:
            await self.send_paginated_embeds(ctx, embeds)

    async def send_paginated_embeds(self, ctx, embeds: List[discord.Embed]):
        current_page = 0

        view = discord.ui.View()
        
        async def update_message(interaction: discord.Interaction):
            embed = embeds[current_page]
            embed.set_footer(text=f"Page {current_page + 1}/{len(embeds)}")
            await interaction.response.edit_message(embed=embed, view=view)

        @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray)
        async def previous_button(interaction: discord.Interaction, button: discord.ui.Button):
            nonlocal current_page
            current_page = (current_page - 1) % len(embeds)
            await update_message(interaction)

        @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
        async def next_button(interaction: discord.Interaction, button: discord.ui.Button):
            nonlocal current_page
            current_page = (current_page + 1) % len(embeds)
            await update_message(interaction)

        view.add_item(previous_button)
        view.add_item(next_button)

        embeds[0].set_footer(text=f"Page 1/{len(embeds)}")
        await ctx.send(embed=embeds[0], view=view)

    @commands.command()
    async def event_info(self, ctx, name: str):
        """Display detailed information about a specific event."""
        events = await self.config.guild(ctx.guild).events()
        if name not in events:
            await ctx.send(embed=self.error_embed(f"No event found with the name '{name}'."))
            return
        
        embed = self.create_event_embed(name, events[name])
        await ctx.send(embed=embed)

    def error_embed(self, message: str) -> discord.Embed:
        """Create an error embed."""
        return discord.Embed(title=f"{self.emoji['error']} Error", description=message, color=discord.Color.red())

    def success_embed(self, message: str) -> discord.Embed:
        """Create a success embed."""
        return discord.Embed(title=f"{self.emoji['success']} Success", description=message, color=discord.Color.green())

    def warning_embed(self, message: str) -> discord.Embed:
        """Create a warning embed."""
        return discord.Embed(title=f"{self.emoji['warning']} Warning", description=message, color=discord.Color.gold())

    async def send_notification(self, guild: discord.Guild, event_name: str, notification_time: int):
        """Send a notification for the event."""
        event_data = await self.config.guild(guild).events()
        event = event_data.get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            embed = discord.Embed(
                title=f"{self.emoji['bell']} Event Reminder",
                description=f"The event '{event_name}' is starting in {notification_time} minutes!",
                color=discord.Color.blue()
            )
            embed.add_field(name="Description", value=event['description'], inline=False)
            embed.add_field(name="Time", value=self.format_time(datetime.fromisoformat(event['time'])), inline=False)
            await channel.send(embed=embed)

    async def send_event_start_message(self, guild: discord.Guild, event_name: str):
        """Send a message when the event starts."""
        event_data = await self.config.guild(guild).events()
        event = event_data.get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            embed = discord.Embed(
                title=f"{self.emoji['calendar']} Event Starting Now!",
                description=f"The event '{event_name}' is starting now!",
                color=discord.Color.green()
            )
            embed.add_field(name="Description", value=event['description'], inline=False)
            await channel.send(embed=embed)

    # ... (rest of the code remains the same)

async def setup(bot: Red):
    cog = RobustEventsCog(bot)
    await bot.add_cog(cog)
    print(f"{cog.emoji['success']} RobustEventsCog has been loaded and is ready.")
