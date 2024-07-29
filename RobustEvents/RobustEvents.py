import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
import pytz

import discord
from discord import app_commands
from discord.ui import Modal, TextInput, Select, View, Button
from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_timedelta, box

class EventCreationModal(Modal):
    def __init__(self, cog, timezone):
        super().__init__(title="Create New Event")
        self.cog = cog
        self.timezone = timezone
        self.name = TextInput(label="Event Name", placeholder="Enter event name", max_length=100)
        self.date = TextInput(label="Date (YYYY-MM-DD)", placeholder="2024-01-01")
        self.time = TextInput(label="Time (HH:MM)", placeholder="14:30")
        self.description = TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000)
        self.create_role = TextInput(label="Create Role? (yes/no)", placeholder="yes or no", max_length=3)
        self.add_item(self.name)
        self.add_item(self.date)
        self.add_item(self.time)
        self.add_item(self.description)
        self.add_item(self.create_role)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            local_time = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y-%m-%d %H:%M")
            event_time = self.timezone.localize(local_time).astimezone(pytz.UTC)
            if event_time <= datetime.now(pytz.UTC):
                await interaction.response.send_message(embed=self.cog.error_embed("Event time must be in the future."), ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message(embed=self.cog.error_embed("Invalid date or time format."), ephemeral=True)
            return

        await self.cog.create_event(
            interaction.guild,
            self.name.value,
            event_time,
            self.description.value,
            self.create_role.value.lower() == "yes",
        )
        await interaction.response.send_message(embed=self.cog.success_embed("Event created successfully!"), ephemeral=True)

class RobustEventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.event_tasks = {}

    @commands.command()
    async def create_event(self, ctx, name: str, event_time: datetime, description: str, create_role: bool):
        """Command to create a new event."""
        await ctx.send(f"Event '{name}' created for {event_time}.")

    def success_embed(self, message: str) -> discord.Embed:
        return discord.Embed(description=message, color=discord.Color.green())

    def error_embed(self, message: str) -> discord.Embed:
        return discord.Embed(description=message, color=discord.Color.red())

    async def schedule_event(self, guild: discord.Guild, name: str, event_time: datetime):
        async def event_task():
            while True:
                event_data = await self.config.guild(guild).events()
                event = event_data.get(name)
                if not event:
                    return

                now = datetime.now(pytz.UTC)
                time_until_event = event_time - now

                # Schedule notifications
                for notification_time in event['notifications']:
                    notification_delta = timedelta(minutes=notification_time)
                    if time_until_event > notification_delta:
                        await asyncio.sleep((time_until_event - notification_delta).total_seconds())
                        await self.send_notification(guild, name, notification_time)

                # Wait for the event time
                await discord.utils.sleep_until(event_time)

                # Send event start message
                await self.send_event_start_message(guild, name)

                # Handle repeating events
                repeat_type = event['repeat']
                if repeat_type == 'none':
                    async with self.config.guild(guild).events() as events:
                        del events[name]
                    return
                elif repeat_type == 'daily':
                    event_time += timedelta(days=1)
                elif repeat_type == 'weekly':
                    event_time += timedelta(weeks=1)
                elif repeat_type == 'monthly':
                    event_time = event_time.replace(month=event_time.month % 12 + 1)
                    if event_time.month == 1:
                        event_time = event_time.replace(year=event_time.year + 1)

                async with self.config.guild(guild).events() as events:
                    events[name]['time'] = event_time.isoformat()

        task = asyncio.create_task(event_task())
        self.event_tasks[name] = task

    async def send_notification(self, guild: discord.Guild, event_name: str, minutes_before: int):
        """Send a notification for an event."""
        channel = discord.utils.get(guild.channels, name="event-notifications")
        if channel:
            await channel.send(f"Reminder: Event '{event_name}' is starting in {minutes_before} minutes!")

    async def send_event_start_message(self, guild: discord.Guild, event_name: str):
        """Send a message when an event starts."""
        channel = discord.utils.get(guild.channels, name="event-notifications")
        if channel:
            await channel.send(f"The event '{event_name}' is starting now!")

    @commands.Cog.listener()
    async def on_ready(self):
        """Schedule events when the bot is ready."""
        for guild in self.bot.guilds:
            events = await self.config.guild(guild).events()
            for name, data in events.items():
                event_time = datetime.fromisoformat(data['time'])
                self.schedule_event(guild, name, event_time)
