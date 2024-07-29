import asyncio
from datetime import datetime, timedelta
from typing import Optional
import pytz

import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, Button, View
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

class EventCreationModal(Modal):
    def __init__(self, cog, timezone):
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

class SignupButton(Button):
    def __init__(self, cog, role: discord.Role):
        super().__init__(label="Sign Up for Notifications", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.role = role

    async def callback(self, interaction: discord.Interaction):
        if self.role not in interaction.user.roles:
            await interaction.user.add_roles(self.role)
            await interaction.response.send_message(f"You have been signed up for notifications with the role {self.role.mention}!", ephemeral=True)
        else:
            await interaction.response.send_message(f"You are already signed up for notifications with the role {self.role.mention}.", ephemeral=True)

class RobustEventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(events={})
        self.event_tasks = {}

    @commands.command()
    async def create_event(self, ctx, name: Optional[str] = None, event_time: Optional[str] = None, description: Optional[str] = None, notifications: Optional[str] = None, repeat: Optional[str] = None, create_role: Optional[str] = None, timezone: Optional[str] = "UTC"):
        """Command to create a new event."""
        if not (name and event_time and description and notifications and repeat and create_role):
            await ctx.send("Usage: `!create_event <name> <YYYY-MM-DDTHH:MM> <description> <notifications> <repeat> <create_role> [timezone]`\nExample: `!create_event \"Event Name\" 2024-01-01T14:30 \"Description\" \"10,30,60\" \"daily\" \"yes\" [timezone]`")
            return

        try:
            tz = pytz.timezone(timezone)
            event_time = datetime.strptime(event_time, "%Y-%m-%dT%H:%M").replace(tzinfo=tz)
            if event_time <= datetime.now(tz):
                await ctx.send(embed=self.error_embed("Event time must be in the future."))
                return
        except (ValueError, pytz.UnknownTimeZoneError) as e:
            await ctx.send(embed=self.error_embed(f"Invalid date, time, or timezone format: {e}"))
            return

        try:
            notification_times = [int(n.strip()) for n in notifications.split(',')]
        except ValueError:
            await ctx.send(embed=self.error_embed("Invalid notification times."))
            return

        create_role_bool = create_role.lower() == "yes"

        await self.config.guild(ctx.guild).events.set_raw(name, value={
            "time": event_time.isoformat(),
            "description": description,
            "notifications": notification_times,
            "repeat": repeat.lower(),
            "create_role": create_role_bool
        })
        self.schedule_event(ctx.guild, name, event_time)
        await ctx.send(embed=self.success_embed(f"Event '{name}' created for {event_time}."))

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

    @commands.command()
    async def createevent(self, ctx):
        """Start the custom modal for creating a new event."""
        timezone = pytz.timezone("UTC")  # Adjust this to use the appropriate timezone
        await ctx.send("Opening event creation modal...", delete_after=5)
        await ctx.send_modal(EventCreationModal(self, timezone))

    @commands.command()
    async def signup_event(self, ctx, role: discord.Role):
        """Post an embed for users to sign up for event notifications."""
        embed = discord.Embed(title="Event Notifications Signup", description=f"Click the button below to sign up for event notifications with the role {role.mention}.", color=discord.Color.green())
        view = View()
        view.add_item(SignupButton(self, role))
        await ctx.send(embed=embed, view=view)

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
                    try:
                        event_time = event_time.replace(month=event_time.month % 12 + 1)
                        if event_time.month == 1:
                            event_time = event_time.replace(year=event_time.year + 1)
                    except ValueError:
                        event_time = event_time.replace(day=1, month=(event_time.month % 12) + 1)

                async with self.config.guild(guild).events() as events:
                    events[name]['time'] = event_time.isoformat()

        task = asyncio.create_task(event_task())
        self.event_tasks[name] = task

    async def send_notification(self, guild: discord.Guild, event_name: str, minutes_before: int):
        """Send a notification for an event."""
        channel = discord.utils.get(guild.channels, name="event-notifications")
        if channel:
            await channel.send(f"🔔 Reminder: Event **'{event_name}'** is starting in **{minutes_before} minutes**!")

    async def send_event_start_message(self, guild: discord.Guild, event_name: str):
        """Send a message when an event starts."""
        channel = discord.utils.get(guild.channels, name="event-notifications")
        if channel:
            await channel.send(f"🎉 The event **'{event_name}'** is starting now!")

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
