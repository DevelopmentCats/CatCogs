import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View
from redbot.core import Config, commands
from redbot.core.bot import Red
from datetime import datetime, timedelta
import pytz
from typing import Optional, List
import asyncio

class BasicEventModal(Modal):
    def __init__(self, cog, timezone: pytz.timezone):
        super().__init__(title="Create New Event - Basic Info")
        self.cog = cog
        self.timezone = timezone

        self.name = TextInput(label="Event Name", placeholder="Enter event name", max_length=100)
        self.datetime1 = TextInput(label="First Date and Time (YYYY-MM-DD HH:MM)", placeholder="2024-01-01 14:30")
        self.datetime2 = TextInput(label="Second Date and Time (Optional)", placeholder="2024-01-01 18:30", required=False)
        self.description = TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000)

        self.add_item(self.name)
        self.add_item(self.datetime1)
        self.add_item(self.datetime2)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            local_time1 = datetime.strptime(self.datetime1.value, "%Y-%m-%d %H:%M")
            event_time1 = self.timezone.localize(local_time1).astimezone(pytz.UTC)
            if event_time1 <= datetime.now(pytz.UTC):
                await interaction.response.send_message(embed=self.cog.error_embed("First event time must be in the future."), ephemeral=True)
                return

            if self.datetime2.value:
                local_time2 = datetime.strptime(self.datetime2.value, "%Y-%m-%d %H:%M")
                event_time2 = self.timezone.localize(local_time2).astimezone(pytz.UTC)
                if event_time2 <= datetime.now(pytz.UTC):
                    await interaction.response.send_message(embed=self.cog.error_embed("Second event time must be in the future."), ephemeral=True)
                    return
            else:
                event_time2 = None

        except ValueError as e:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Invalid date or time format: {e}"), ephemeral=True)
            return

        # Store basic info temporarily
        self.cog.temp_event_data = {
            "basic": {
                "name": self.name.value,
                "time1": event_time1,
                "time2": event_time2,
                "description": self.description.value
            }
        }

        # Show the advanced options modal
        advanced_modal = AdvancedEventModal(self.cog)
        await interaction.response.send_modal(advanced_modal)

class AdvancedEventModal(Modal):
    def __init__(self, cog):
        super().__init__(title="Create New Event - Advanced Options")
        self.cog = cog

        self.notifications = TextInput(label="Notification Times (minutes)", placeholder="10,30,60")
        self.repeat = TextInput(label="Repeat (none/daily/weekly/monthly)", placeholder="none")
        self.create_role = TextInput(label="Create Role? (yes/no)", placeholder="no")
        self.channel = TextInput(label="Channel", placeholder="#events")

        self.add_item(self.notifications)
        self.add_item(self.repeat)
        self.add_item(self.create_role)
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            notifications = [int(n.strip()) for n in self.notifications.value.split(',')]
        except ValueError:
            await interaction.response.send_message(embed=self.cog.error_embed("Invalid notification times."), ephemeral=True)
            return

        repeat = self.repeat.value.lower()
        if repeat not in ['none', 'daily', 'weekly', 'monthly']:
            await interaction.response.send_message(embed=self.cog.error_embed("Invalid repeat option."), ephemeral=True)
            return

        create_role = self.create_role.value.lower() == 'yes'
        channel_name = self.channel.value.lstrip('#')

        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Channel #{channel_name} not found."), ephemeral=True)
            return

        # Update temp_event_data with advanced info
        self.cog.temp_event_data["advanced"] = {
            "notifications": notifications,
            "repeat": repeat,
            "create_role": create_role,
            "channel": channel
        }

        # Show the event creation button
        await interaction.response.send_message("Please click the 'Create Event' button to create the event.", view=EventCreationView(self.cog))

class EventCreationView(View):
    def __init__(self, cog, timezone: pytz.timezone):
        super().__init__()
        self.cog = cog
        self.timezone = timezone
        self.basic_info_filled = False
        self.advanced_info_filled = False

    @discord.ui.button(label="Basic Info", style=discord.ButtonStyle.primary)
    async def basic_info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BasicEventModal(self.cog, self.timezone)
        await interaction.response.send_modal(modal)
        self.basic_info_filled = True
        await self.update_buttons(interaction)

    @discord.ui.button(label="Advanced Options", style=discord.ButtonStyle.secondary)
    async def advanced_options_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.basic_info_filled:
            await interaction.response.send_message("Please fill out the Basic Info first.", ephemeral=True)
            return
        modal = AdvancedEventModal(self.cog)
        await interaction.response.send_modal(modal)
        self.advanced_info_filled = True
        await self.update_buttons(interaction)

    @discord.ui.button(label="Create Event", style=discord.ButtonStyle.success, disabled=True)
    async def create_event_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not (self.basic_info_filled and self.advanced_info_filled):
            await interaction.response.send_message("Please fill out both Basic Info and Advanced Options first.", ephemeral=True)
            return
        
        # Create the event using the stored temporary data
        await self.cog.create_event_from_temp_data(interaction.guild)
        await interaction.response.send_message(embed=self.cog.success_embed("Event created successfully!"), ephemeral=True)
        self.stop()

    async def update_buttons(self, interaction: discord.Interaction):
        self.create_event_button.disabled = not (self.basic_info_filled and self.advanced_info_filled)
        await interaction.message.edit(view=self)

class RobustEventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(events={}, timezone="UTC")
        self.event_tasks = {}
        self.temp_event_data = None  # Add this line to store temporary event data

    @commands.command()
    async def eventcreate(self, ctx):
        """Start the custom modal for creating a new event."""
        guild_timezone = await self.config.guild(ctx.guild).timezone()
        timezone = pytz.timezone(guild_timezone) if guild_timezone else pytz.UTC
        view = EventCreationView(self, timezone)
        await ctx.send("Use the buttons below to create a new event:", view=view)

    @commands.command()
    async def list_events(self, ctx):
        """List all scheduled events."""
        events = await self.config.guild(ctx.guild).events()
        if not events:
            await ctx.send(embed=self.error_embed("No events scheduled."))
            return
        event_list = "\n".join([f"{name}: {data['time1']}" for name, data in events.items()])
        await ctx.send(embed=discord.Embed(title="Scheduled Events", description=event_list, color=discord.Color.blue()))

    @commands.command()
    async def delete_event(self, ctx, name: Optional[str] = None):
        """Delete an event."""
        if not name:
            await ctx.send("Usage: `!delete_event <name>`")
            return

        async with self.config.guild(ctx.guild).events() as events:
            if name in events:
                del events[name]
                await ctx.send(embed=self.success_embed(f"Event '{name}' deleted."))
                if name in self.event_tasks:
                    self.event_tasks[name].cancel()
                    del self.event_tasks[name]
            else:
                await ctx.send(embed=self.error_embed(f"No event found with the name '{name}'."))

    @commands.command()
    async def update_event(self, ctx, name: Optional[str] = None, date: Optional[str] = None, time: Optional[str] = None, description: Optional[str] = None, notifications: Optional[str] = None, repeat: Optional[str] = None):
        """Update an existing event."""
        if not name:
            await ctx.send("Usage: `!update_event <name> [date] [time] [description] [notifications] [repeat]`\nExample: `!update_event \"Event Name\" date=2024-02-01 time=16:00 description=\"New description\" notifications=\"15,45,90\" repeat=\"weekly\"`")
            return

        async with self.config.guild(ctx.guild).events() as events:
            if name not in events:
                await ctx.send(embed=self.error_embed(f"No event found with the name '{name}'.")) 
                return

            if date and time:
                try:
                    event_time = datetime.strptime(f"{date}T{time}", "%Y-%m-%dT%H:%M").replace(tzinfo=pytz.UTC)
                    if event_time <= datetime.now(pytz.UTC):
                        await ctx.send(embed=self.error_embed("Event time must be in the future."))
                        return
                    events[name]['time1'] = event_time.isoformat()
                except ValueError:
                    await ctx.send(embed=self.error_embed("Invalid date or time format."))
                    return

            if description:
                events[name]['description'] = description

            if notifications:
                try:
                    notification_times = [int(n.strip()) for n in notifications.split(',')]
                    events[name]['notifications'] = notification_times
                except ValueError:
                    await ctx.send(embed=self.error_embed("Invalid notification times."))
                    return

            if repeat:
                events[name]['repeat'] = repeat.lower()

            await ctx.send(embed=self.success_embed(f"Event '{name}' updated."))
            if name in self.event_tasks:
                self.event_tasks[name].cancel()
                del self.event_tasks[name]
            self.schedule_event(ctx.guild, name, datetime.fromisoformat(events[name]['time1']))

    async def create_event(self, guild: discord.Guild, name: str, event_time1: datetime, description: str, notifications: List[int], repeat: str, create_role: bool, channel: discord.TextChannel, event_time2: Optional[datetime] = None):
        """Create an event and store it."""
        await self.config.guild(guild).events.set_raw(name, value={
            "time1": event_time1.isoformat(),
            "description": description,
            "notifications": notifications,
            "repeat": repeat,
            "create_role": create_role,
            "channel": channel.id,
            "time2": event_time2.isoformat() if event_time2 else None
        })
        self.schedule_event(guild, name, event_time1)
        if event_time2:
            self.schedule_event(guild, name, event_time2)

    async def schedule_event(self, guild: discord.Guild, name: str, event_time: datetime):
        async def event_task():
            while True:
                event_data = await self.config.guild(guild).events()
                event = event_data.get(name)
                if not event:
                    return

                now = datetime.now(pytz.UTC)
                time_until_event = event_time - now

                for notification_time in event['notifications']:
                    notification_delta = timedelta(minutes=notification_time)
                    if time_until_event > notification_delta:
                        await asyncio.sleep((time_until_event - notification_delta).total_seconds())
                        await self.send_notification(guild, name, notification_time)

                await discord.utils.sleep_until(event_time)
                await self.send_event_start_message(guild, name)

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
                    event_time += timedelta(weeks=4)
                else:
                    return

                await self.config.guild(guild).events.set_raw(name, value={
                    "time1": event_time.isoformat(),
                    "description": event['description'],
                    "notifications": event['notifications'],
                    "repeat": event['repeat'],
                    "create_role": event['create_role'],
                    "channel": event['channel'],
                    "time2": event.get('time2')
                })
                self.schedule_event(guild, name, event_time)

        self.event_tasks[name] = self.bot.loop.create_task(event_task())

    async def send_notification(self, guild: discord.Guild, event_name: str, notification_time: int):
        """Send a notification for the event."""
        event_data = await self.config.guild(guild).events()
        event = event_data.get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            await channel.send(f"Reminder: The event '{event_name}' is starting in {notification_time} minutes!")

    async def send_event_start_message(self, guild: discord.Guild, event_name: str):
        """Send a message when the event starts."""
        event_data = await self.config.guild(guild).events()
        event = event_data.get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            await channel.send(f"The event '{event_name}' is starting now!\n{event['description']}")

    def error_embed(self, message: str) -> discord.Embed:
        """Create an error embed."""
        return discord.Embed(title="Error", description=message, color=discord.Color.red())

    def success_embed(self, message: str) -> discord.Embed:
        """Create a success embed."""
        return discord.Embed(title="Success", description=message, color=discord.Color.green())

    async def create_event_from_temp_data(self, guild: discord.Guild):
        """Create an event using the stored temporary data."""
        basic_info = self.temp_event_data['basic']
        advanced_info = self.temp_event_data['advanced']

        await self.create_event(
            guild,
            basic_info["name"],
            basic_info["time1"],
            basic_info["description"],
            advanced_info["notifications"],
            advanced_info["repeat"],
            advanced_info["create_role"],
            advanced_info["channel"],
            basic_info["time2"]
        )

        # Clear temporary data
        self.temp_event_data = None

    @commands.command()
    async def set_timezone(self, ctx, timezone_str: str):
        """Set the timezone for the guild."""
        try:
            timezone = pytz.timezone(timezone_str)
            await self.config.guild(ctx.guild).timezone.set(timezone_str)
            await ctx.send(embed=self.success_embed(f"Timezone set to {timezone_str}"))
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(embed=self.error_embed(f"Unknown timezone: {timezone_str}. Please use a valid timezone from the IANA Time Zone Database."))

async def setup(bot: Red):
    cog = RobustEventsCog(bot)
    await bot.add_cog(cog)
    print("RobustEventsCog has been loaded and is ready.")
