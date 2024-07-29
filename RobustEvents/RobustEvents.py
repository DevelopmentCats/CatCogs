import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, Button, View
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box
from datetime import datetime, timedelta
import pytz
import asyncio

class EventCreationModal(Modal):
    def __init__(self, cog):
        super().__init__(title="Create New Event")
        self.cog = cog
        
        self.name = TextInput(label="Event Name", placeholder="Enter event name", max_length=100)
        self.date = TextInput(label="Date (YYYY-MM-DD)", placeholder="2024-01-01")
        self.time = TextInput(label="Time (HH:MM)", placeholder="14:30")
        self.description = TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000)
        self.notifications = TextInput(label="Notification Times (minutes before, comma-separated)", placeholder="10,30,60")
        self.repeat = TextInput(label="Repeat (none, daily, weekly, monthly)", placeholder="none")
        self.create_role = TextInput(label="Create Role? (yes/no)", placeholder="yes or no", max_length=3)
        
        self.add_item(self.name)
        self.add_item(self.date)
        self.add_item(self.time)
        self.add_item(self.description)
        self.add_item(self.notifications)
        self.add_item(self.repeat)
        self.add_item(self.create_role)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            local_time = datetime.strptime(f"{self.date.value} {self.time.value}", "%Y-%m-%d %H:%M")
            event_time = self.cog.default_timezone.localize(local_time).astimezone(pytz.UTC)
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

        await self.cog.create_event(
            interaction.guild,
            self.name.value,
            event_time,
            self.description.value,
            notifications,
            self.repeat.value.lower(),
            self.create_role.value.lower() == "yes",
        )
        await interaction.response.send_message(embed=self.cog.success_embed("Event created successfully!"), ephemeral=True)

class EventCreationButton(Button):
    def __init__(self, cog):
        super().__init__(label="Create Event", style=discord.ButtonStyle.primary, custom_id="create_event_button")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Opening event creation modal...", ephemeral=True)
        modal = EventCreationModal(self.cog)
        await interaction.response.send_modal(modal)

class RobustEventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(events={})
        self.event_tasks = {}
        self.default_timezone = pytz.UTC  # Change this to your preferred default timezone

    @commands.command(name="eventcreate")
    async def eventcreate(self, ctx: commands.Context):
        """Send a message with a button to start the event creation process."""
        view = View()
        view.add_item(EventCreationButton(self))
        await ctx.send("Click the button below to start creating an event.", view=view)

    @commands.command(name="list_events")
    async def list_events(self, ctx: commands.Context):
        """List all scheduled events."""
        events = await self.config.guild(ctx.guild).events()
        if not events:
            await ctx.send(embed=self.error_embed("No events scheduled."))
            return
        event_list = "\n".join([f"{name}: {data['time']}" for name, data in events.items()])
        await ctx.send(embed=discord.Embed(title="Scheduled Events", description=box(event_list, lang="yaml"), color=discord.Color.blue()))

    @commands.command(name="delete_event")
    async def delete_event(self, ctx: commands.Context, name: str = None):
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

    @commands.command(name="update_event")
    async def update_event(self, ctx: commands.Context, name: str = None, date: str = None, time: str = None, description: str = None, notifications: str = None, repeat: str = None):
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

    async def create_event(self, guild: discord.Guild, name: str, event_time: datetime, description: str, notifications: list, repeat: str, create_role: bool):
        """Create a new event and store it."""
        await self.config.guild(guild).events.set_raw(name, value={
            "time": event_time.isoformat(),
            "description": description,
            "notifications": notifications,
            "repeat": repeat.lower(),
            "create_role": create_role
        })
        self.schedule_event(guild, name, event_time)
        await self.bot.get_channel(your_channel_id).send(embed=self.success_embed(f"Event '{name}' created for {event_time}."))

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
                    try:
                        event_time = event_time.replace(month=event_time.month % 12 + 1)
                        if event_time.month == 1:
                            event_time = event_time.replace(year=event_time.year + 1)
                    except ValueError:
                        event_time += timedelta(days=31)
                else:
                    async with self.config.guild(guild).events() as events:
                        del events[name]
                    return

                self.schedule_event(guild, name, event_time)

        self.event_tasks[name] = asyncio.create_task(event_task())

    async def send_notification(self, guild: discord.Guild, event_name: str, notification_time: int):
        channel = self.bot.get_channel(your_channel_id)  # Replace with your channel ID
        await channel.send(embed=discord.Embed(title=f"Reminder: {event_name}", description=f"The event '{event_name}' is starting in {notification_time} minutes.", color=discord.Color.orange()))

    async def send_event_start_message(self, guild: discord.Guild, event_name: str):
        channel = self.bot.get_channel(your_channel_id)  # Replace with your channel ID
        await channel.send(embed=discord.Embed(title=f"Event Started: {event_name}", description=f"The event '{event_name}' has just started.", color=discord.Color.green()))

    def success_embed(self, message: str) -> discord.Embed:
        return discord.Embed(description=message, color=discord.Color.green())

    def error_embed(self, message: str) -> discord.Embed:
        return discord.Embed(description=message, color=discord.Color.red())

    @commands.Cog.listener()
    async def on_ready(self):
        """Schedule events when the bot is ready."""
        for guild in self.bot.guilds:
            events = await self.config.guild(guild).events()
            for name, data in events.items():
                event_time = datetime.fromisoformat(data['time'])
                self.schedule_event(guild, name, event_time)

async def setup(bot: Red):
    cog = RobustEventsCog(bot)
    await bot.add_cog(cog)
    print("RobustEventsCog has been loaded and is ready.")
