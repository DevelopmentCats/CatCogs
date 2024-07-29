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

class EventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "events": {},
            "timezone": "UTC"
        }
        self.config.register_guild(**default_guild)
        self.event_tasks = {}

    @event.command(name="create")
    @app_commands.describe(
        name="The name of the event",
        time="The time of the event (YYYY-MM-DD HH:MM)",
        description="A description of the event"
    )
    async def event_create(self, ctx: commands.Context, name: str = None, time: str = None, *, description: str = None):
        """Create a new event"""
        if not all([name, time, description]):
            # Display help information if any required argument is missing
            embed = discord.Embed(title="Create Event", color=discord.Color.blue())
            embed.add_field(name="Usage", value="!event create <name> <time> <description>")
            embed.add_field(name="Example", value="!event create 'Game Night' '2024-08-01 20:00' Join us for a fun game night!")
            embed.set_footer(text="Time format: YYYY-MM-DD HH:MM (in server's timezone)")
            await ctx.send(embed=embed)
            return

        timezone_str = await self.config.guild(ctx.guild).timezone()
        timezone = pytz.timezone(timezone_str)

        modal = EventCreationModal(self, timezone)
        modal.name.default = name
        modal.description.default = description
        if " " in time:
            date, time = time.split(" ")
            modal.date.default = date
            modal.time.default = time
        await ctx.interaction.response.send_modal(modal)

    @event.command(name="list")
    async def event_list(self, ctx: commands.Context):
        """List all scheduled events"""
        events = await self.config.guild(ctx.guild).events()
        timezone_str = await self.config.guild(ctx.guild).timezone()
        timezone = pytz.timezone(timezone_str)

        if not events:
            await ctx.send(embed=discord.Embed(title="No Events", description="No events are currently scheduled.", color=discord.Color.orange()))
            return

        # Create and send embeds for each event
        embeds = []
        for name, event in events.items():
            event_time = datetime.fromisoformat(event['time']).replace(tzinfo=pytz.UTC)
            local_time = event_time.astimezone(timezone)
            time_until = event_time - datetime.now(pytz.UTC)
            roles = [ctx.guild.get_role(role_id).mention for role_id in event['roles'] if ctx.guild.get_role(role_id)]
            notifications = [f"{n} minutes before" for n in event['notifications']]
            
            embed = discord.Embed(title=f"Event: {name}", color=discord.Color.blue())
            embed.add_field(name="Time", value=local_time.strftime('%Y-%m-%d %H:%M %Z'), inline=False)
            embed.add_field(name="Time until", value=humanize_timedelta(timedelta=time_until), inline=False)
            embed.add_field(name="Description", value=event['description'], inline=False)
            embed.add_field(name="Roles", value=', '.join(roles) if roles else "None", inline=False)
            embed.add_field(name="Notifications", value=', '.join(notifications) if notifications else "None", inline=False)
            embed.add_field(name="Repeat", value=event['repeat'] if event['repeat'] else "None", inline=False)
            
            embeds.append(embed)

        await ctx.send(embeds=embeds)

    @event.command(name="settimezone")
    @app_commands.describe(timezone="The timezone to set for the server (e.g., 'US/Pacific', 'Europe/London')")
    async def event_settimezone(self, ctx: commands.Context, timezone: str = None):
        """Set the timezone for the server"""
        if not timezone:
            current_timezone = await self.config.guild(ctx.guild).timezone()
            embed = discord.Embed(title="Set Server Timezone", color=discord.Color.blue())
            embed.add_field(name="Current Timezone", value=current_timezone)
            embed.add_field(name="Usage", value="!event settimezone <timezone>")
            embed.add_field(name="Example", value="!event settimezone US/Pacific")
            embed.set_footer(text="For a list of valid timezones, visit: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
            await ctx.send(embed=embed)
            return

        try:
            pytz.timezone(timezone)
            await self.config.guild(ctx.guild).timezone.set(timezone)
            embed = discord.Embed(title="Timezone Set", description=f"Server timezone has been set to {timezone}.", color=discord.Color.green())
            await ctx.send(embed=embed)
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(embed=self.error_embed(f"Invalid timezone: {timezone}. Please use a valid timezone identifier."))

    def schedule_event(self, guild: discord.Guild, name: str, event_time: datetime):
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
      
