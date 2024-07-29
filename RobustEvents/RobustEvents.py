import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, Button, View, Select
from redbot.core import Config, commands
from redbot.core.bot import Red
from datetime import datetime, timedelta
import pytz
from typing import Optional, List

class EventCreationModal(Modal):
    def __init__(self, cog, timezone, channels: List[discord.SelectOption]):
        super().__init__(title="Create New Event")
        self.cog = cog
        self.timezone = timezone

        self.name = TextInput(label="Event Name", placeholder="Enter event name", max_length=100)
        self.date = TextInput(label="Date (YYYY-MM-DD)", placeholder="2024-01-01")
        self.time = TextInput(label="Time (HH:MM)", placeholder="14:30")
        self.description = TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000)
        self.notifications = TextInput(label="Notification Times (minutes before, comma-separated)", placeholder="10,30,60")
        self.repeat = TextInput(label="Repeat (none, daily, weekly, monthly)", placeholder="none")
        self.create_role = TextInput(label="Create Role? (yes/no)", placeholder="yes or no", max_length=3)

        # Add items to the modal
        self.add_item(self.name)
        self.add_item(self.date)
        self.add_item(self.time)
        self.add_item(self.description)
        self.add_item(self.notifications)
        self.add_item(self.repeat)
        self.add_item(self.create_role)

        # Channel selection dropdown
        self.channel_select = Select(placeholder="Select a channel...", options=channels)
        self.add_item(self.channel_select)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            local_time = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y-%m-%d %H:%M")
            event_time = self.timezone.localize(local_time).astimezone(pytz.UTC)
            if event_time <= datetime.now(pytz.UTC):
                await interaction.response.send_message(embed=self.cog.error_embed("Event time must be in the future."), ephemeral=True)
                return
        except ValueError as e:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Invalid date or time format: {e}"), ephemeral=True)
            return

        try:
            notifications = [int(n.strip()) for n in self.notifications.value.split(',')]
        except ValueError:
            await interaction.response.send_message(embed=self.cog.error_embed("Invalid notification times."), ephemeral=True)
            return

        # Handle channel selection
        channel_id = int(self.channel_select.values[0])
        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            await interaction.response.send_message(embed=self.cog.error_embed("Selected channel not found."), ephemeral=True)
            return

        await self.cog.create_event(
            interaction.guild,
            self.name.value,
            event_time,
            self.description.value,
            notifications,
            self.repeat.value.lower(),
            self.create_role.value.lower() == "yes",
            channel
        )
        await interaction.response.send_message(embed=self.cog.success_embed("Event created successfully!"), ephemeral=True)

class EventCreationButton(Button):
    def __init__(self, cog):
        super().__init__(label="Create Event", style=discord.ButtonStyle.primary)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        channels = [discord.SelectOption(label=channel.name, value=str(channel.id)) for channel in interaction.guild.text_channels]
        modal = EventCreationModal(self.cog, pytz.timezone("UTC"), channels)
        await interaction.response.send_message("Opening event creation modal...", ephemeral=True)
        await interaction.response.send_modal(modal)

class RobustEventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(events={})
        self.event_tasks = {}

    @commands.command()
    async def eventcreate(self, ctx):
        """Start the custom modal for creating a new event."""
        view = View()
        view.add_item(EventCreationButton(self))
        await ctx.send("Click the button below to create a new event:", view=view)

    @commands.command()
    async def list_events(self, ctx):
        """List all scheduled events."""
        events = await self.config.guild(ctx.guild).events()
        if not events:
            await ctx.send(embed=self.error_embed("No events scheduled."))
            return
        event_list = "\n".join([f"{name}: {data['time']}" for name, data in events.items()])
        await ctx.send(embed=discord.Embed(title="Scheduled Events", description=box(event_list, lang="yaml"), color=discord.Color.blue()))

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
                    events[name]['time'] = event_time.isoformat()
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
            self.schedule_event(ctx.guild, name, datetime.fromisoformat(events[name]['time']))

    async def create_event(self, guild: discord.Guild, name: str, event_time: datetime, description: str, notifications: list, repeat: str, create_role: bool, channel: discord.TextChannel):
        """Create an event and store it."""
        await self.config.guild(guild).events.set_raw(name, value={
            "time": event_time.isoformat(),
            "description": description,
            "notifications": notifications,
            "repeat": repeat,
            "create_role": create_role,
            "channel": channel.id
        })
        self.schedule_event(guild, name, event_time)

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
                    event_time += timedelta(weeks=4)
                else:
                    break

                await self.schedule_event(guild, name, event_time)

        self.event_tasks[name] = self.bot.loop.create_task(event_task())

    async def send_notification(self, guild: discord.Guild, event_name: str, notification_time: int):
        """Send a notification message to the specified channel."""
        event_data = await self.config.guild(guild).events()
        event = event_data.get(event_name)
        if not event:
            return

        channel_id = event.get('channel')
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(f"Reminder: {event_name} is coming up in {notification_time} minutes!")

    async def send_event_start_message(self, guild: discord.Guild, event_name: str):
        """Send a message when the event starts."""
        event_data = await self.config.guild(guild).events()
        event = event_data.get(event_name)
        if not event:
            return

        channel_id = event.get('channel')
        channel = guild.get_channel(channel_id)
        if channel:
            await channel.send(f"The event '{event_name}' has started!")

    def error_embed(self, message: str) -> discord.Embed:
        return discord.Embed(title="Error", description=message, color=discord.Color.red())

    def success_embed(self, message: str) -> discord.Embed:
        return discord.Embed(title="Success", description=message, color=discord.Color.green())

async def setup(bot: Red):
    cog = RobustEventsCog(bot)
    await bot.add_cog(cog)
    print("RobustEventsCog has been loaded and is ready.")
