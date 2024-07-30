import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Select
from redbot.core import Config, commands
from redbot.core.bot import Red
from datetime import datetime, timedelta
import pytz
from typing import Optional, List, Dict
import asyncio
from collections import defaultdict
import logging
from discord.ext import tasks
import humanize
import calendar

class BasicEventModal(Modal):
    def __init__(self, cog, timezone: pytz.timezone, original_message: discord.Message):
        super().__init__(title="Create New Event - Basic Info")
        self.cog = cog
        self.timezone = timezone
        self.original_message = original_message

        self.name = TextInput(label="Event Name", placeholder="Enter event name", max_length=100)
        self.datetime1 = TextInput(label="First Time (HH:MM)", placeholder="14:30")
        self.datetime2 = TextInput(label="Second Time (Optional, HH:MM)", placeholder="18:30", required=False)
        self.description = TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000)

        self.add_item(self.name)
        self.add_item(self.datetime1)
        self.add_item(self.datetime2)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            now = datetime.now(self.timezone)
            
            # Validate time format
            def validate_time(time_str):
                try:
                    return datetime.strptime(time_str, "%H:%M").time()
                except ValueError:
                    raise ValueError(f"Invalid time format: {time_str}. Please use HH:MM format.")

            time1 = validate_time(self.datetime1.value)
            event_time1 = self.timezone.localize(datetime.combine(now.date(), time1)).astimezone(pytz.UTC)
            if event_time1 <= now:
                event_time1 += timedelta(days=1)

            if self.datetime2.value:
                time2 = validate_time(self.datetime2.value)
                event_time2 = self.timezone.localize(datetime.combine(now.date(), time2)).astimezone(pytz.UTC)
                if event_time2 <= now:
                    event_time2 += timedelta(days=1)
            else:
                event_time2 = None

        except ValueError as e:
            await interaction.response.send_message(embed=self.cog.error_embed(str(e)), ephemeral=True)
            return

        # Store the basic event information temporarily
        self.cog.temp_event_data = {
            'name': self.name.value,
            'time1': event_time1.isoformat(),
            'time2': event_time2.isoformat() if event_time2 else None,
            'description': self.description.value,
        }

        # Send a message with a button to open the advanced options
        view = AdvancedOptionsView(self.cog, self.timezone, self.original_message)
        await interaction.response.send_message("Basic information saved. Click the button below to set advanced options:", view=view, ephemeral=True)

class AdvancedEventModal(Modal):
    def __init__(self, cog, timezone: pytz.timezone, original_message: discord.Message):
        super().__init__(title="Create New Event - Advanced Options")
        self.cog = cog
        self.timezone = timezone
        self.original_message = original_message

        self.notifications = TextInput(label="Notification Times (minutes)", placeholder="10,30,60")
        self.repeat = TextInput(label="Repeat (none/daily/weekly/monthly/yearly)", placeholder="none")
        self.role_name = TextInput(label="Event Role Name", placeholder="Event Attendees")  # Made mandatory
        self.channel = TextInput(label="Channel", placeholder="#events")

        self.add_item(self.notifications)
        self.add_item(self.repeat)
        self.add_item(self.role_name)
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            notifications = [int(n.strip()) for n in self.notifications.value.split(',')]
        except ValueError:
            await interaction.response.send_message(embed=self.cog.error_embed("Invalid notification times."), ephemeral=True)
            return

        repeat = self.repeat.value.lower()
        if repeat not in ['none', 'daily', 'weekly', 'monthly', 'yearly']:
            await interaction.response.send_message(embed=self.cog.error_embed("Invalid repeat option."), ephemeral=True)
            return

        role_name = self.role_name.value.strip()
        if not role_name:
            await interaction.response.send_message(embed=self.cog.error_embed("Event role name is required."), ephemeral=True)
            return

        channel_name = self.channel.value.lstrip('#')
        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Channel #{channel_name} not found."), ephemeral=True)
            return

        # Get the basic event data
        basic_data = self.cog.temp_event_data
        if not basic_data:
            await interaction.response.send_message(embed=self.cog.error_embed("Error: Event data not found."), ephemeral=True)
            return

        # Create the event with all the information
        await self.cog.create_event(
            interaction.guild,
            basic_data['name'],
            datetime.fromisoformat(basic_data['time1']),
            basic_data['description'],
            notifications,
            repeat,
            role_name,
            channel,
            datetime.fromisoformat(basic_data['time2']) if basic_data['time2'] else None
        )

        await interaction.response.send_message(embed=self.cog.success_embed("Event created successfully!"), ephemeral=True)

        # Clear the temporary event data
        self.cog.temp_event_data = None

        # Delete the original message with the button
        await self.original_message.delete()

class AdvancedOptionsView(View):
    def __init__(self, cog, timezone: pytz.timezone, original_message: discord.Message):
        super().__init__()
        self.cog = cog
        self.timezone = timezone
        self.original_message = original_message

    @discord.ui.button(label="Set Advanced Options", style=discord.ButtonStyle.primary)
    async def advanced_options_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        advanced_modal = AdvancedEventModal(self.cog, self.timezone, self.original_message)
        await interaction.response.send_modal(advanced_modal)
        self.stop()  # Stop the view after opening the modal

class EventCreationView(discord.ui.View):
    def __init__(self, cog, timezone: pytz.timezone):
        super().__init__()
        self.cog = cog
        self.timezone = timezone
        self.message = None  # Will be set after the message is sent

    @discord.ui.button(label="Create Event", style=discord.ButtonStyle.primary, emoji="➕")
    async def create_event_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        basic_modal = BasicEventModal(self.cog, self.timezone, self.message)
        await interaction.response.send_modal(basic_modal)

class EventInfoView(discord.ui.View):
    def __init__(self, cog, event_name: str, role_id: int):
        super().__init__(timeout=None)  # Set timeout to None for persistent view
        self.cog = cog
        self.event_name = event_name
        self.role_id = role_id

    @discord.ui.button(label="Join Event", style=discord.ButtonStyle.primary, emoji="✅", custom_id="join_event")
    async def join_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("Error: Event role not found.", ephemeral=True)
            return
        
        if role in interaction.user.roles:
            await interaction.response.send_message("You're already signed up for this event!", ephemeral=True)
        else:
            try:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"You've been added to the {self.event_name} event!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to assign roles.", ephemeral=True)

class RobustEventsCog(commands.Cog):
    """Cog for managing and scheduling events"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "events": {},
            "timezone": "UTC"
        }
        default_member = {
            "personal_reminders": {}
        }
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)
        self.event_tasks: Dict[str, asyncio.Task] = {}
        self.personal_reminder_tasks: Dict[str, asyncio.Task] = {}
        self.notification_queue: Dict[str, List[asyncio.Event]] = defaultdict(list)
        self.event_cache: Dict[int, Dict[str, dict]] = defaultdict(dict)
        self.logger = logging.getLogger('red.RobustEvents')
        self.bot.loop.create_task(self.initialize_events())
        self.cleanup_expired_events.start()
        self.sync_event_cache.start()
        self.bot.add_view(EventInfoView(self, "", 0))

    def cog_unload(self):
        self.cleanup_expired_events.cancel()
        self.sync_event_cache.cancel()
        for task in self.event_tasks.values():
            task.cancel()
        for task in self.personal_reminder_tasks.values():
            task.cancel()

    @tasks.loop(hours=24)
    async def cleanup_expired_events(self):
        """Automatically clean up expired non-repeating events."""
        for guild in self.bot.guilds:
            async with self.config.guild(guild).events() as events:
                current_time = datetime.now(pytz.UTC)
                to_remove = []
                for name, event in events.items():
                    event_time = max(datetime.fromisoformat(event['time1']), datetime.fromisoformat(event['time2'] or event['time1']))
                    if event['repeat'] == 'none' and event_time < current_time:
                        to_remove.append(name)
                for name in to_remove:
                    await self.delete_event(guild, name)

    async def initialize_events(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self.load_guild_events(guild)
        await self.load_personal_reminders()

    async def load_guild_events(self, guild: discord.Guild):
        events = await self.config.guild(guild).events()
        for name, event in events.items():
            self.event_cache[guild.id][name] = event
            await self.schedule_event(guild, name)

    async def load_personal_reminders(self):
        for guild in self.bot.guilds:
            async for member_id, member_data in self.config.all_members(guild):
                for event_name, reminder_time in member_data.get('personal_reminders', {}).items():
                    await self.schedule_personal_reminder(guild.id, member_id, event_name, datetime.fromisoformat(reminder_time))

    async def schedule_event(self, guild: discord.Guild, name: str):
        if name in self.event_tasks:
            self.event_tasks[name].cancel()
        self.event_tasks[name] = self.bot.loop.create_task(self.event_loop(guild, name))

    async def schedule_personal_reminder(self, guild_id: int, user_id: int, event_name: str, reminder_time: datetime):
        task_key = f"{guild_id}:{user_id}:{event_name}"
        if task_key in self.personal_reminder_tasks:
            self.personal_reminder_tasks[task_key].cancel()
        self.personal_reminder_tasks[task_key] = self.bot.loop.create_task(self.personal_reminder_loop(guild_id, user_id, event_name, reminder_time))

    async def event_loop(self, guild: discord.Guild, name: str):
        while True:
            try:
                event = self.event_cache[guild.id].get(name)
                if not event:
                    return

                now = datetime.now(pytz.UTC)
                time1 = datetime.fromisoformat(event['time1'])
                time2 = datetime.fromisoformat(event['time2']) if event.get('time2') else None

                times = [time for time in [time1, time2] if time and time > now]
                if not times:
                    await self.update_event_times(guild, name)
                    continue

                next_time = min(times)
                time_until_event = next_time - now

                for notification_time in sorted(event['notifications'], reverse=True):
                    notification_delta = timedelta(minutes=notification_time)
                    if time_until_event > notification_delta:
                        await asyncio.sleep((time_until_event - notification_delta).total_seconds())
                        await self.queue_notification(guild, name, notification_time, next_time)
                        time_until_event = notification_delta

                await discord.utils.sleep_until(next_time)
                await self.send_event_start_message(guild, name, next_time)

                if time2 and next_time == time1:
                    await discord.utils.sleep_until(time2)
                    await self.send_event_start_message(guild, name, time2)

                await self.update_event_times(guild, name)

            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"Error in event loop for {name}: {e}")
                await asyncio.sleep(60)

    async def update_event_times(self, guild: discord.Guild, name: str):
        event = self.event_cache[guild.id].get(name)
        if not event:
            return

        time1 = datetime.fromisoformat(event['time1'])
        time2 = datetime.fromisoformat(event['time2']) if event.get('time2') else None

        if event['repeat'] == 'daily':
            delta = timedelta(days=1)
        elif event['repeat'] == 'weekly':
            delta = timedelta(weeks=1)
        elif event['repeat'] == 'monthly':
            # Move to the same day next month, handling edge cases
            next_month = time1.replace(day=1) + timedelta(days=32)
            next_month = next_month.replace(day=min(time1.day, calendar.monthrange(next_month.year, next_month.month)[1]))
            delta = next_month - time1
        elif event['repeat'] == 'yearly':
            # Move to the same date next year, handling leap years
            next_year = time1.replace(year=time1.year + 1)
            if time1.month == 2 and time1.day == 29:
                next_year = next_year.replace(day=28)
            delta = next_year - time1
        else:
            # Non-repeating event, delete it
            await self.delete_event(guild, name)
            return

        event['time1'] = (time1 + delta).isoformat()
        if time2:
            event['time2'] = (time2 + delta).isoformat()

        await self.config.guild(guild).events.set_raw(name, value=event)
        self.event_cache[guild.id][name] = event

    async def queue_notification(self, guild: discord.Guild, event_name: str, notification_time: int, event_time: datetime):
        queue_key = f"{guild.id}:{event_name}:{notification_time}"
        notification_event = asyncio.Event()
        self.notification_queue[queue_key].append(notification_event)
        
        if len(self.notification_queue[queue_key]) == 1:
            await self.send_notification(guild, event_name, notification_time, event_time)
        
        await notification_event.wait()
        self.notification_queue[queue_key].remove(notification_event)

    async def send_notification(self, guild: discord.Guild, event_name: str, notification_time: int, event_time: datetime):
        event = self.event_cache[guild.id].get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            role = guild.get_role(event['role_id']) if event['role_id'] else None
            role_mention = role.mention if role else "@everyone"
            
            embed = discord.Embed(
                title=f"🔔 Event Reminder: {event_name}",
                description=f"{role_mention}\n\nThe event '{event_name}' is starting in {notification_time} minutes!",
                color=discord.Color.blue()
            )
            embed.add_field(name="Description", value=event['description'], inline=False)
            embed.add_field(name="Start Time", value=f"<t:{int(event_time.timestamp())}:F>", inline=False)
            embed.set_footer(text="This message will be automatically deleted in 30 minutes.")
            
            message = await channel.send(embed=embed)
            
            self.bot.loop.create_task(self.delete_message_after(message, delay=1800))  # 1800 seconds = 30 minutes

        queue_key = f"{guild.id}:{event_name}:{notification_time}"
        for notification_event in self.notification_queue[queue_key]:
            notification_event.set()

    async def delete_message_after(self, message: discord.Message, delay: int):
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    async def send_event_start_message(self, guild: discord.Guild, event_name: str, event_time: datetime):
        event = self.event_cache[guild.id].get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            role = guild.get_role(event['role_id']) if event['role_id'] else None
            role_mention = role.mention if role else "@everyone"
            
            embed = discord.Embed(
                title=f"🎉 Event Starting Now: {event_name}",
                description=f"{role_mention}\n\nThe event '{event_name}' is starting now!",
                color=discord.Color.green()
            )
            embed.add_field(name="Description", value=event['description'], inline=False)
            embed.add_field(name="Start Time", value=f"<t:{int(event_time.timestamp())}:F>", inline=False)
            
            await channel.send(embed=embed)

    @commands.command(name="eventcreate")
    @commands.has_permissions(manage_events=True)
    async def event_create(self, ctx):
        """Start the custom modal for creating a new event."""
        guild_timezone = await self.config.guild(ctx.guild).timezone()
        timezone = pytz.timezone(guild_timezone) if guild_timezone else pytz.UTC
        view = EventCreationView(self, timezone)
        embed = discord.Embed(title="📅 Create New Event", 
                              description="Click the button below to start creating a new event.", 
                              color=discord.Color.blue())
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @commands.command(name="eventlist")
    async def event_list(self, ctx):
        """List all scheduled events."""
        events = await self.config.guild(ctx.guild).events()
        if not events:
            await ctx.send(embed=self.error_embed("No events scheduled."))
            return
        
        embed = discord.Embed(title="📅 Scheduled Events", color=discord.Color.blue())
        for name, data in events.items():
            event_time = datetime.fromisoformat(data['time1'])
            time_until = humanize.naturaltime(event_time, when=datetime.now(pytz.UTC))
            embed.add_field(
                name=name,
                value=f"🕒 {event_time.strftime('%Y-%m-%d %H:%M')} UTC\n⏳ {time_until}\n📍 <#{data['channel']}>",
                inline=False
            )
        await ctx.send(embed=embed)

    @commands.command(name="eventdelete")
    @commands.has_permissions(manage_events=True)
    async def event_delete(self, ctx, name: Optional[str] = None):
        """Delete an event.

        Usage: [p]eventdelete <name>
        """
        if not name:
            await ctx.send("Usage: `[p]eventdelete <name>`")
            return

        events = await self.config.guild(ctx.guild).events()
        if name in events:
            await self.delete_event(ctx.guild, name)
            await ctx.send(embed=self.success_embed(f"Event '{name}' deleted."))
        else:
            await ctx.send(embed=self.error_embed(f"No event found with the name '{name}'."))

    async def delete_event(self, guild: discord.Guild, name: str):
        await self.config.guild(guild).events.clear_raw(name)
        if guild.id in self.event_cache and name in self.event_cache[guild.id]:
            del self.event_cache[guild.id][name]
        if name in self.event_tasks:
            self.event_tasks[name].cancel()
            del self.event_tasks[name]

        # Delete the event role if it exists
        event = self.event_cache[guild.id].get(name)
        if event and event['role_id']:
            role = guild.get_role(event['role_id'])
            if role:
                try:
                    await role.delete()
                except discord.Forbidden:
                    self.logger.error(f"Couldn't delete the event role for '{name}' due to lack of permissions.")

        # Remove personal reminders for this event
        async for member_id, member_data in self.config.all_members(guild):
            async with self.config.member_from_ids(guild.id, member_id).personal_reminders() as reminders:
                if name in reminders:
                    del reminders[name]
            task_key = f"{guild.id}:{member_id}:{name}"
            if task_key in self.personal_reminder_tasks:
                self.personal_reminder_tasks[task_key].cancel()
                del self.personal_reminder_tasks[task_key]

        # Clear any queued notifications for this event
        for key in list(self.notification_queue.keys()):
            if key.startswith(f"{guild.id}:{name}:"):
                for notification_event in self.notification_queue[key]:
                    notification_event.set()
                del self.notification_queue[key]

    @commands.command(name="eventupdate")
    @commands.has_permissions(manage_events=True)
    async def event_update(self, ctx, name: Optional[str] = None, date: Optional[str] = None, time: Optional[str] = None, description: Optional[str] = None, notifications: Optional[str] = None, repeat: Optional[str] = None):
        """Update an existing event.

        Usage: [p]eventupdate <name> [date] [time] [description] [notifications] [repeat]
        Example: [p]eventupdate "Event Name" date=2024-02-01 time=16:00 description="New description" notifications="15,45,90" repeat="weekly"
        """
        if not name:
            await ctx.send("Usage: `[p]eventupdate <name> [date] [time] [description] [notifications] [repeat]`\nExample: `[p]eventupdate \"Event Name\" date=2024-02-01 time=16:00 description=\"New description\" notifications=\"15,45,90\" repeat=\"weekly\"`")
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
            await self.schedule_event(ctx.guild, name)

    async def create_event(self, guild: discord.Guild, name: str, event_time1: datetime, description: str, notifications: List[int], repeat: str, role_name: Optional[str], channel: Optional[discord.TextChannel], event_time2: Optional[datetime] = None):
        try:
            event_role = await self.create_or_get_event_role(guild, role_name) if role_name else None

            event_data = {
                "time1": event_time1.isoformat(),
                "description": description,
                "notifications": sorted(notifications),  # Sort notifications in ascending order
                "repeat": repeat,
                "role_name": role_name,
                "role_id": event_role.id if event_role else None,
                "channel": channel.id if channel else None,
                "time2": event_time2.isoformat() if event_time2 else None
            }

            await self.config.guild(guild).events.set_raw(name, value=event_data)
            self.event_cache[guild.id][name] = event_data
            await self.schedule_event(guild, name)
        except Exception as e:
            self.logger.error(f"Error creating event: {e}")
            raise

    async def update_event(self, guild: discord.Guild, event_name: str, new_data: dict):
        try:
            async with self.config.guild(guild).events() as events:
                if event_name not in events:
                    return False

                events[event_name].update(new_data)
                self.event_cache[guild.id][event_name].update(new_data)

            await self.schedule_event(guild, event_name)
            return True
        except Exception as e:
            self.logger.error(f"Error updating event {event_name}: {e}")
            return False

    async def create_or_get_event_role(self, guild: discord.Guild, role_name: str) -> Optional[discord.Role]:
        if not role_name:
            return None
        existing_role = discord.utils.get(guild.roles, name=role_name)
        if existing_role:
            return existing_role
        try:
            return await guild.create_role(name=role_name, mentionable=True)
        except discord.Forbidden:
            self.logger.error(f"Bot doesn't have permission to create roles in guild {guild.name}")
            return None

    def get_next_event_time(self, current_time: datetime, repeat_type: str) -> datetime:
        if repeat_type == 'daily':
            return current_time + timedelta(days=1)
        elif repeat_type == 'weekly':
            return current_time + timedelta(weeks=1)
        elif repeat_type == 'monthly':
            return current_time + timedelta(weeks=4)
        else:
            return current_time

    @commands.command(name="settimezone")
    @commands.has_permissions(manage_events=True)
    async def set_timezone(self, ctx, timezone_str: str):
        """Set the timezone for the guild.

        Usage: [p]settimezone <timezone>
        """
        try:
            timezone = pytz.timezone(timezone_str)
            await self.config.guild(ctx.guild).timezone.set(timezone_str)
            await ctx.send(embed=self.success_embed(f"Timezone set to {timezone_str}"))
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(embed=self.error_embed(f"Unknown timezone: {timezone_str}. Please use a valid timezone from the IANA Time Zone Database."))

    @commands.command(name="eventinfo")
    async def event_info(self, ctx, *, event_name: str):
        """Display information about a specific event."""
        events = await self.config.guild(ctx.guild).events()
        event = events.get(event_name)
        
        if not event:
            await ctx.send(embed=self.error_embed(f"No event found with the name '{event_name}'."))
            return

        embed = discord.Embed(title=f"📅 {event_name}", description=event['description'], color=discord.Color.blue())
        
        start_time1 = datetime.fromisoformat(event['time1'])
        embed.add_field(name="🕒 First Time", value=f"<t:{int(start_time1.timestamp())}:t>", inline=False)
        
        if event.get('time2'):
            start_time2 = datetime.fromisoformat(event['time2'])
            embed.add_field(name="🕒 Second Time", value=f"<t:{int(start_time2.timestamp())}:t>", inline=False)
        
        embed.add_field(name="🔁 Repeat", value=event['repeat'].capitalize(), inline=True)
        embed.add_field(name="🔔 Notifications", value=", ".join(f"{n} minutes" for n in event['notifications']), inline=True)
        
        channel = ctx.guild.get_channel(event['channel'])
        if channel:
            embed.add_field(name="📍 Channel", value=channel.mention, inline=True)

        next_occurrence = min(start_time1, start_time2) if event.get('time2') else start_time1
        if next_occurrence < datetime.now(pytz.UTC):
            next_occurrence += timedelta(days=1)
        
        time_until = humanize.naturaltime(next_occurrence, when=datetime.now(pytz.UTC))
        embed.set_footer(text=f"Next occurrence {time_until}")

        view = EventInfoView(self, event_name, event['role_id'])
        await ctx.send(embed=embed, view=view)

    @commands.command(name="eventremind")
    async def event_remind(self, ctx, *, event_name: str):
        """Set a personal reminder for an event."""
        event = self.event_cache[ctx.guild.id].get(event_name)
        if not event:
            await ctx.send(embed=self.error_embed(f"No event found with the name '{event_name}'."))
            return

        event_time = datetime.fromisoformat(event['time1'])
        now = datetime.now(pytz.UTC)
        if event_time <= now:
            await ctx.send(embed=self.error_embed("This event has already started or passed."))
            return

        view = ReminderSelectView(self, ctx.author.id, event_name, event_time)
        embed = discord.Embed(title=f"⏰ Set Reminder for {event_name}", 
                              description="Select when you'd like to be reminded:", 
                              color=discord.Color.blue())
        await ctx.send(embed=embed, view=view)

    async def set_personal_reminder(self, guild_id: int, user_id: int, event_name: str, reminder_time: datetime):
        async with self.config.member_from_ids(guild_id, user_id).personal_reminders() as reminders:
            reminders[event_name] = reminder_time.isoformat()
        await self.schedule_personal_reminder(guild_id, user_id, event_name, reminder_time)

    @commands.command(name="eventedit")
    @commands.has_permissions(manage_events=True)
    async def event_edit(self, ctx, *, event_name: str):
        """Edit an existing event using a modal."""
        event = self.event_cache[ctx.guild.id].get(event_name)
        if not event:
            await ctx.send(embed=self.error_embed(f"No event found with the name '{event_name}'."))
            return

        view = EventEditView(self, ctx.guild, event_name, event)
        embed = discord.Embed(title=f"✏️ Edit Event: {event_name}", 
                              description="Click the button below to edit the event details.", 
                              color=discord.Color.blue())
        await ctx.send(embed=embed, view=view)

    @commands.command(name="eventcancel")
    @commands.has_permissions(manage_events=True)
    async def event_cancel(self, ctx, *, event_name: str):
        """Cancel an event and notify participants.

        Usage: [p]eventcancel <event_name>
        """
        event = self.event_cache[ctx.guild.id].get(event_name)
        if not event:
            await ctx.send(embed=self.error_embed(f"No event found with the name '{event_name}'."))
            return

        view = ConfirmCancelView(self, ctx.guild, event_name, event)
        await ctx.send(f"Are you sure you want to cancel the event '{event_name}'?", view=view)

    async def cancel_event(self, guild: discord.Guild, event_name: str):
        try:
            event = self.event_cache[guild.id].get(event_name)
            if not event:
                return

            # Cancel the event
            await self.delete_event(guild, event_name)

            # Notify participants
            channel = guild.get_channel(event['channel'])
            if channel:
                await channel.send(f"The event '{event_name}' has been cancelled.")

        except Exception as e:
            self.logger.error(f"Error cancelling event {event_name}: {e}")

    def error_embed(self, message: str) -> discord.Embed:
        """Create an error embed."""
        return discord.Embed(title="❌ Error", description=message, color=discord.Color.red())

    def success_embed(self, message: str) -> discord.Embed:
        """Create a success embed."""
        return discord.Embed(title="✅ Success", description=message, color=discord.Color.green())

    @commands.command(name="eventhelp", aliases=["event"])
    async def event_help(self, ctx):
        """Display categorized help information for all event-related commands."""
        # Get the bot's command prefix for this guild
        prefix = ctx.clean_prefix

        embed = discord.Embed(
            title="📅 Event Management System Help",
            description="Here's a list of all available event-related commands:",
            color=discord.Color.blue()
        )

        management_commands = [
            ("eventcreate", "Start the process of creating a new event using an interactive modal."),
            ("eventdelete <name>", "Delete a specific event by its name."),
            ("eventupdate <name> [options]", "Update details of an existing event."),
            ("settimezone <timezone>", "Set the timezone for the guild (e.g., 'US/Pacific', 'Europe/London')."),
            ("eventedit <name>", "Edit an existing event using an interactive modal."),
            ("eventcancel <name>", "Cancel an event and notify all participants."),
        ]

        event_commands = [
            ("eventlist", "Display a list of all scheduled events."),
            ("eventinfo <name>", "Display detailed information about a specific event."),
            ("eventremind <name>", "Set a personal reminder for an event."),
        ]

        embed.add_field(name="🛠️ Management Commands", value="Commands for creating and managing events (requires Manage Events permission):", inline=False)
        for command, description in management_commands:
            embed.add_field(name=f"`{prefix}{command}`", value=description, inline=False)

        embed.add_field(name="\u200b", value="\u200b", inline=False)  # Empty field for spacing

        embed.add_field(name="🎫 Event Participation Commands", value="Commands for event participants:", inline=False)
        for command, description in event_commands:
            embed.add_field(name=f"`{prefix}{command}`", value=description, inline=False)

        embed.add_field(name="\u200b", value="\u200b", inline=False)  # Empty field for spacing

        embed.add_field(name="ℹ️ Help Command", value=f"`{prefix}eventhelp` or `{prefix}event`: Display this help message with all available commands.", inline=False)

        embed.set_footer(text=f"Current prefix: {prefix}")
        await ctx.send(embed=embed)

    @tasks.loop(hours=1)
    async def sync_event_cache(self):
        for guild in self.bot.guilds:
            events = await self.config.guild(guild).events()
            self.event_cache[guild.id] = events

class ReminderSelectView(discord.ui.View):
    def __init__(self, cog, user_id: int, event_name: str, event_time: datetime):
        super().__init__()
        self.cog = cog
        self.user_id = user_id
        self.event_name = event_name
        self.event_time = event_time

        self.add_item(ReminderSelect(self.set_reminder))

    async def set_reminder(self, interaction: discord.Interaction, minutes: int):
        reminder_time = self.event_time - timedelta(minutes=minutes)
        now = datetime.now(pytz.UTC)
        if reminder_time <= now:
            await interaction.response.send_message(embed=self.cog.error_embed("This reminder time has already passed."), ephemeral=True)
            return

        await self.cog.set_personal_reminder(interaction.guild_id, self.user_id, self.event_name, reminder_time)
        await interaction.response.send_message(embed=self.cog.success_embed(f"I'll remind you about '{self.event_name}' {minutes} minutes before it starts."), ephemeral=True)

class ReminderSelect(discord.ui.Select):
    def __init__(self, callback):
        options = [
            discord.SelectOption(label="5 minutes", value="5", emoji="⏱️"),
            discord.SelectOption(label="15 minutes", value="15", emoji="⏱️"),
            discord.SelectOption(label="30 minutes", value="30", emoji="⏱️"),
            discord.SelectOption(label="1 hour", value="60", emoji="⏰"),
            discord.SelectOption(label="2 hours", value="120", emoji="⏰"),
        ]
        super().__init__(placeholder="Select reminder time", options=options)
        self.callback_function = callback

    async def callback(self, interaction: discord.Interaction):
        await self.callback_function(interaction, int(self.values[0]))

class BasicEventEditModal(discord.ui.Modal, title="Edit Event - Basic Info"):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

        self.new_name = discord.ui.TextInput(
            label="Event Name",
            default=event_name,
            required=True
        )
        self.new_datetime = discord.ui.TextInput(
            label="Date and Time (YYYY-MM-DD HH:MM)",
            default=datetime.fromisoformat(event_data['time1']).strftime("%Y-%m-%d %H:%M"),
            required=True
        )
        self.new_description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            default=event_data['description'],
            required=True
        )

        self.add_item(self.new_name)
        self.add_item(self.new_datetime)
        self.add_item(self.new_description)

    async def on_submit(self, interaction: discord.Interaction):
        new_data = {}
        new_data['name'] = self.new_name.value

        try:
            new_time = datetime.strptime(self.new_datetime.value, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.UTC)
            new_data['time1'] = new_time.isoformat()
        except ValueError:
            await interaction.response.send_message("Invalid date format. Please use YYYY-MM-DD HH:MM", ephemeral=True)
            return

        new_data['description'] = self.new_description.value

        # Store the basic event information temporarily
        self.cog.temp_edit_data = new_data

        # Send a message with a button to open the advanced options
        view = AdvancedEditOptionsView(self.cog, self.guild, self.event_name, self.event_data)
        await interaction.response.send_message("Basic information updated. Click the button below to edit advanced options:", view=view, ephemeral=True)

class AdvancedEventEditModal(discord.ui.Modal, title="Edit Event - Advanced Options"):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

        self.new_notifications = discord.ui.TextInput(
            label="Notification Times (minutes)",
            default=",".join(map(str, event_data['notifications'])),
            required=True
        )
        self.new_repeat = discord.ui.TextInput(
            label="Repeat (none/daily/weekly/monthly/yearly)",
            default=event_data['repeat'],
            required=True
        )

        self.add_item(self.new_notifications)
        self.add_item(self.new_repeat)

    async def on_submit(self, interaction: discord.Interaction):
        new_data = self.cog.temp_edit_data

        try:
            new_notifications = [int(n.strip()) for n in self.new_notifications.value.split(',')]
            new_data['notifications'] = new_notifications
        except ValueError:
            await interaction.response.send_message("Invalid notification format. Please use comma-separated numbers.", ephemeral=True)
            return

        if self.new_repeat.value not in ['none', 'daily', 'weekly', 'monthly', 'yearly']:
            await interaction.response.send_message("Invalid repeat option. Please use none, daily, weekly, monthly, or yearly.", ephemeral=True)
            return
        new_data['repeat'] = self.new_repeat.value

        success = await self.cog.update_event(self.guild, self.event_name, new_data)
        if success:
            await interaction.response.send_message(embed=self.cog.success_embed(f"Event '{self.event_name}' has been updated successfully."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Failed to update event '{self.event_name}'."), ephemeral=True)

        # Clear the temporary edit data
        self.cog.temp_edit_data = None

class EventEditView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_event_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = BasicEventEditModal(self.cog, self.guild, self.event_name, self.event_data)
        await interaction.response.send_modal(modal)

class AdvancedEditOptionsView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    @discord.ui.button(label="Edit Advanced Options", style=discord.ButtonStyle.primary, emoji="⚙️")
    async def advanced_options_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AdvancedEventEditModal(self.cog, self.guild, self.event_name, self.event_data)
        await interaction.response.send_modal(modal)

class ConfirmCancelView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    @discord.ui.button(label="Confirm Cancel", style=discord.ButtonStyle.danger, emoji="🚫")
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cancel_event(self.guild, self.event_name)
        await interaction.response.send_message(embed=self.cog.success_embed(f"The event '{self.event_name}' has been cancelled and participants have been notified."))

    @discord.ui.button(label="Keep Event", style=discord.ButtonStyle.secondary, emoji="🔙")
    async def keep_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=self.cog.success_embed(f"The event '{self.event_name}' has not been cancelled."))

async def setup(bot: Red):
    await bot.add_cog(RobustEventsCog(bot))
