import asyncio
import calendar
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Set

import discord
import humanize
import pytz
import traceback
from discord.ext import commands, tasks
from discord import ui, TextInput
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n
from discord import app_commands

_ = Translator("RobustEvents", __file__)

MIN_NOTIFICATION_INTERVAL = timedelta(minutes=5)  # Minimum interval between notifications

class RepeatType(Enum):
    NONE = 'none'
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'

class BasicEventModal(ui.Modal, title=_("Create New Event - Basic Info")):
    def __init__(self, cog, guild: discord.Guild, original_message: discord.Message):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.original_message = original_message

        self.name = ui.TextInput(label=_("Event Name"), placeholder=_("Enter event name"), max_length=100)
        self.datetime1 = ui.TextInput(label=_("First Time (HH:MM)"), placeholder=_("14:30"))
        self.datetime2 = ui.TextInput(label=_("Second Time (Optional, HH:MM)"), placeholder=_("18:30"), required=False)
        self.description = ui.TextInput(label=_("Description"), style=discord.TextStyle.paragraph, max_length=1000)

        self.add_item(self.name)
        self.add_item(self.datetime1)
        self.add_item(self.datetime2)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        guild_tz = await self.cog.get_guild_timezone(self.guild)
        try:
            now = datetime.now(guild_tz)

            def validate_time(time_str):
                try:
                    return datetime.strptime(time_str, "%H:%M").time()
                except ValueError:
                    raise ValueError(f"Invalid time format: {time_str}. Please use HH:MM format.")

            time1 = validate_time(self.datetime1.value)
            event_time1 = guild_tz.localize(datetime.combine(now.date(), time1))

            if self.datetime2.value:
                time2 = validate_time(self.datetime2.value)
                event_time2 = guild_tz.localize(datetime.combine(now.date(), time2))
            else:
                event_time2 = None

        except ValueError as e:
            await interaction.response.send_message(embed=self.cog.error_embed(str(e)), ephemeral=True)
            return

        self.cog.temp_event_data[interaction.user.id] = {
            'name': self.name.value,
            'time1': event_time1.isoformat(),
            'time2': event_time2.isoformat() if event_time2 else None,
            'description': self.description.value,
        }

        view = AdvancedOptionsView(self.cog, self.original_message)
        await interaction.response.send_message(_("Basic information saved. Click the button below to set advanced options:"), view=view, ephemeral=True)
        await self.original_message.delete()

class AdvancedEventModal(ui.Modal, title=_("Create New Event - Advanced Options")):
    def __init__(self, cog, guild: discord.Guild, original_message: discord.Message):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.original_message = original_message

        self.notifications = ui.TextInput(label=_("Notification Times (minutes)"), placeholder=_("10,30,60"))
        self.repeat = ui.TextInput(label=_("Repeat (none/daily/weekly/monthly/yearly)"), placeholder=_("none"))
        self.role_name = ui.TextInput(label=_("Event Role Name"), placeholder=_("Event Attendees"))
        self.channel = ui.TextInput(label=_("Channel"), placeholder=_("#events"))

        self.add_item(self.notifications)
        self.add_item(self.repeat)
        self.add_item(self.role_name)
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            notifications = [int(n.strip()) for n in self.notifications.value.split(',')]
        except ValueError:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Invalid notification times.")), ephemeral=True)
            return

        repeat = self.repeat.value.lower()
        if repeat not in RepeatType._value2member_map_:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Invalid repeat option.")), ephemeral=True)
            return

        role_name = self.role_name.value.strip()
        if not role_name:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Event role name is required.")), ephemeral=True)
            return

        channel_name = self.channel.value.lstrip('#')
        channel = discord.utils.get(self.guild.text_channels, name=channel_name)
        if not channel:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Channel #{channel_name} not found.").format(channel_name=channel_name)), ephemeral=True)
            return

        basic_data = self.cog.temp_event_data.pop(interaction.user.id, None)
        if not basic_data:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Error: Event data not found.")), ephemeral=True)
            return

        try:
            event_id = await self.cog.create_event(
                self.guild,
                basic_data['name'],
                datetime.fromisoformat(basic_data['time1']),
                basic_data['description'],
                notifications,
                repeat,
                role_name,
                channel,
                datetime.fromisoformat(basic_data['time2']) if basic_data['time2'] else None
            )

            await interaction.response.send_message(embed=self.cog.success_embed(_("Event created successfully! Event ID: {event_id}").format(event_id=event_id)), ephemeral=True)

            if self.original_message:
                await self.original_message.delete()
        except Exception as e:
            self.cog.logger.error(f"Error creating event: {e}", exc_info=True)
            await interaction.response.send_message(_("An error occurred while creating the event. Please try again."), ephemeral=True)

class AdvancedOptionsView(ui.View):
    def __init__(self, cog, original_message: discord.Message):
        super().__init__()
        self.cog = cog
        self.original_message = original_message

    @ui.button(label=_("Set Advanced Options"), style=discord.ButtonStyle.primary)
    async def advanced_options_button(self, interaction: discord.Interaction, button: ui.Button):
        advanced_modal = AdvancedEventModal(self.cog, interaction.guild, self.original_message)
        await interaction.response.send_modal(advanced_modal)
        self.stop()

class EventCreationView(ui.View):
    def __init__(self, cog, guild: discord.Guild, author: discord.Member):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.cog = cog
        self.guild = guild
        self.author = author
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(_("Only the command initiator can use these buttons."), ephemeral=True)
            return False
        return True

    @ui.button(label=_("Create Event"), style=discord.ButtonStyle.primary, emoji="➕")
    async def create_event_button(self, interaction: discord.Interaction, button: ui.Button):
        basic_modal = BasicEventModal(self.cog, self.guild, self.message)
        await interaction.response.send_modal(basic_modal)
        self.stop()

    @ui.button(label=_("Cancel"), style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.message.delete()
        self.stop()

    async def on_timeout(self):
        if self.message:
            await self.message.delete()

class EventInfoView(ui.View):
    def __init__(self, cog, event_id: str, role_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event_id
        self.role_id = role_id

    @ui.button(label=_("Join Event"), style=discord.ButtonStyle.primary, emoji="✅")
    async def join_event(self, interaction: discord.Interaction, button: ui.Button):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(_("Error: Event role not found."), ephemeral=True)
            return
        
        if role in interaction.user.roles:
            await interaction.response.send_message(_("You're already signed up for this event!"), ephemeral=True)
        else:
            try:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(_("You've been added to the event!"), ephemeral=True)
                
                # Update the embed
                event = self.cog.guild_events[interaction.guild.id].get(self.event_id)
                if event:
                    new_embed = await self.cog.create_event_info_embed(interaction.guild, self.event_id, event)
                    await interaction.message.edit(embed=new_embed)
            except discord.Forbidden:
                await interaction.response.send_message(_("I don't have permission to assign roles."), ephemeral=True)

    @ui.button(label=_("Set Reminder"), style=discord.ButtonStyle.secondary, emoji="⏰")
    async def set_reminder(self, interaction: discord.Interaction, button: ui.Button):
        event = self.cog.guild_events[interaction.guild.id].get(self.event_id)
        if not event:
            await interaction.response.send_message(_("Error: Event not found."), ephemeral=True)
            return

        guild_tz = await self.cog.get_guild_timezone(interaction.guild)
        event_time = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        view = ReminderSelectView(self.cog, interaction.user.id, self.event_id, event_time)
        await interaction.response.send_message(_("Select when you'd like to be reminded via direct message:"), view=view, ephemeral=True)

class EventReminderView(ui.View):
    def __init__(self, cog, guild_id: int, event_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.event_id = event_id

    @ui.button(label=_("View Event Details"), style=discord.ButtonStyle.primary, emoji="📅")
    async def view_event_details(self, interaction: discord.Interaction, button: ui.Button):
        event = self.cog.guild_events[self.guild_id].get(self.event_id)
        if not event:
            await interaction.response.send_message(_("This event no longer exists."), ephemeral=True)
            return

        embed = await self.cog.create_event_info_embed(interaction.guild, self.event_id, event)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label=_("Snooze Reminder"), style=discord.ButtonStyle.secondary, emoji="⏰")
    async def snooze_reminder(self, interaction: discord.Interaction, button: ui.Button):
        event = self.cog.guild_events[self.guild_id].get(self.event_id)
        if not event:
            await interaction.response.send_message(_("This event no longer exists."), ephemeral=True)
            return

        guild_tz = await self.cog.get_guild_timezone(interaction.guild)
        event_time = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        now = datetime.now(guild_tz)

        if event_time <= now:
            await interaction.response.send_message(_("This event has already started or passed."), ephemeral=True)
            return

        snooze_options = [
            discord.SelectOption(label=_("5 minutes"), value="5"),
            discord.SelectOption(label=_("15 minutes"), value="15"),
            discord.SelectOption(label=_("30 minutes"), value="30"),
            discord.SelectOption(label=_("1 hour"), value="60")
        ]

        select = ui.Select(placeholder=_("Select snooze duration"), options=snooze_options)

        async def snooze_callback(interaction: discord.Interaction, select: ui.Select):
            minutes = int(select.values[0])
            new_reminder_time = now + timedelta(minutes=minutes)
            if new_reminder_time >= event_time:
                await interaction.response.send_message(_("Cannot snooze past the event start time."), ephemeral=True)
                return

            await self.cog.set_personal_reminder(self.guild_id, interaction.user.id, self.event_id, new_reminder_time)
            await interaction.response.send_message(_("Reminder snoozed for {minutes} minutes.").format(minutes=minutes), ephemeral=True)

        select.callback = snooze_callback
        view = ui.View()
        view.add_item(select)
        await interaction.response.send_message(_("Choose how long to snooze the reminder:"), view=view, ephemeral=True)

@cog_i18n(_)
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
        self.last_notification_time: Dict[str, datetime] = {}  # Track last notification time
        self.logger = logging.getLogger('red.RobustEvents')
        
        self.guild_timezone_cache = {}
        self.guild_events = defaultdict(dict)
        self.temp_event_data = defaultdict(dict)
        self.temp_edit_data = defaultdict(dict)
        self.event_info_messages = defaultdict(dict)

        self.bot.loop.create_task(self.initialize_cog())

        self.cleanup_expired_events.start()
        self.sync_event_cache.start()
        self.update_event_embeds.start()
        self.cleanup_event_info_messages.start()
        self.sent_notifications: Set[str] = set()
        self.failed_notifications = []
        self.retry_failed_notifications.start()
        self.cleanup_notifications.start()

        # Replace existing notification tracking with simpler system
        self.active_events: Dict[str, asyncio.Task] = {}

    @tasks.loop(hours=1)
    async def cleanup_notifications(self):
        now = datetime.now(pytz.UTC)
        for guild in self.bot.guilds:
            guild_tz = await self.get_guild_timezone(guild)
            for event_id, event in self.guild_events.get(guild.id, {}).items():
                event_time = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
                if event_time < now:
                    notification_keys = [f"{guild.id}:{event_id}:{n}" for n in event['notifications']]
                    self.sent_notifications -= set(notification_keys)
            self.logger.debug("Cleaned up old notifications")

    async def initialize_cog(self):
        try:
            self.logger.info("Starting RobustEvents cog initialization...")
            await self.bot.wait_until_ready()
            self.logger.info("Bot is ready, initializing events...")
            await self.initialize_events()
            self.logger.info("Events initialized, setting up event info messages...")
            await self.initialize_event_info_messages()
            self.logger.info("Event info messages set up, performing initial cleanup...")
            await self.cleanup_notifications()
            self.logger.info("Initial cleanup completed.")
            self.logger.info("RobustEvents cog initialization completed successfully.")
        except Exception as e:
            self.logger.error(f"Error initializing cog: {e}", exc_info=True)
            await self.notify_admin_of_initialization_failure(e)

    async def notify_admin_of_initialization_failure(self, error: Exception):
        for guild in self.bot.guilds:
            owner = guild.owner
            if owner:
                try:
                    await owner.send(f"RobustEvents cog initialization failed. Error: {error}")
                except discord.HTTPException:
                    pass

    def cog_unload(self):
        self.cleanup_expired_events.cancel()
        self.update_event_embeds.cancel()
        for task in self.event_tasks.values():
            task.cancel()
        for task in self.personal_reminder_tasks.values():
            task.cancel()
        self.cleanup_event_info_messages.cancel()
        self.temp_event_data.clear()
        self.temp_edit_data.clear()
        self.notification_queue.clear()
        self.last_notification_time.clear()
        self.event_info_messages.clear()
        asyncio.create_task(self.cleanup_notifications())
        if hasattr(self, 'refresh_timezone_cache'):
            self.refresh_timezone_cache.cancel()

    @tasks.loop(hours=24)
    async def cleanup_event_info_messages(self):
        for guild in self.bot.guilds:
            guild_events = self.event_info_messages.get(guild.id, {})
            if guild_events:
                for event_id in list(guild_events.keys()):
                    if event_id not in self.guild_events.get(guild.id, {}):
                        del guild_events[event_id]
                self.event_info_messages[guild.id] = guild_events
                await self.config.guild(guild).event_info_messages.set(guild_events)

    @tasks.loop(hours=24)
    async def cleanup_expired_events(self):
        """Simplified cleanup of expired events and notifications"""
        now = datetime.now(pytz.UTC)
        for guild in self.bot.guilds:
            async with self.config.guild(guild).events() as events:
                for event_id in list(events.keys()):
                    event = events[event_id]
                    event_time = datetime.fromisoformat(event['time1'])
                    
                    if event['repeat'] == RepeatType.NONE.value and event_time < now:
                        del events[event_id]
                        if event_id in self.active_events:
                            self.active_events[event_id].cancel()
                            del self.active_events[event_id]
                        
                        # Clean up related notifications
                        self.sent_notifications = {
                            key for key in self.sent_notifications 
                            if not key.startswith(f"{guild.id}:{event_id}:")
                        }

    @tasks.loop(minutes=15)
    async def retry_failed_notifications(self):
        for guild_id, event_id, notification_time, event_time in self.failed_notifications[:]:
            guild = self.bot.get_guild(guild_id)
            if guild:
                try:
                    await self.send_notification(guild, event_id, notification_time, event_time)
                    self.failed_notifications.remove((guild_id, event_id, notification_time, event_time))
                except Exception as e:
                    self.logger.error(f"Failed to retry notification for event {event_id}: {e}")

    async def initialize_events(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self.load_guild_events(guild)
        await self.load_personal_reminders()

    async def load_guild_events(self, guild: discord.Guild):
        events = await self.config.guild(guild).events()
        self.guild_events[guild.id] = events
        for event_id, event in events.items():
            await self.schedule_event(guild, event_id)

    async def load_personal_reminders(self):
        for guild in self.bot.guilds:
            members = await self.config.all_members(guild)
            for member_id, member_data in members.items():
                for event_id, reminder_time in member_data.get('personal_reminders', {}).items():
                    await self.schedule_personal_reminder(guild.id, member_id, event_id, datetime.fromisoformat(reminder_time))

    async def schedule_event(self, guild: discord.Guild, event_id: str):
        """Simplified event scheduling"""
        if event_id in self.active_events:
            self.active_events[event_id].cancel()
        
        self.active_events[event_id] = asyncio.create_task(self.event_loop(guild, event_id))
        self.logger.debug(f"Scheduled event task for event {event_id} in guild {guild.id}")

    async def schedule_personal_reminder(self, guild_id: int, user_id: int, event_id: str, reminder_time: datetime):
        task_key = f"{guild_id}:{user_id}:{event_id}"
        if task_key in self.personal_reminder_tasks:
            self.logger.debug(f"Cancelling existing personal reminder task for event {event_id} for user {user_id} in guild {guild_id}")
            self.personal_reminder_tasks[task_key].cancel()
        self.personal_reminder_tasks[task_key] = self.bot.loop.create_task(self.personal_reminder_loop(guild_id, user_id, event_id, reminder_time))
        self.logger.debug(f"Scheduled personal reminder task for event {event_id} for user {user_id} in guild {guild_id}")

    async def personal_reminder_loop(self, guild_id: int, user_id: int, event_id: str, reminder_time: datetime):
        now = datetime.now(pytz.UTC)
        sleep_duration = (reminder_time - now).total_seconds()
        if sleep_duration > 0:
            await asyncio.sleep(sleep_duration)
        event = self.guild_events[guild_id].get(event_id)
        if not event:
            return
        user = self.bot.get_user(user_id)
        if not user:
            self.logger.warning(f"User {user_id} not found for personal reminder of event {event_id}")
            return
        guild = self.bot.get_guild(guild_id)
        if not guild:
            self.logger.warning(f"Guild {guild_id} not found for personal reminder of event {event_id}")
            return
        guild_tz = await self.get_guild_timezone(guild)
        event_time = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        try:
            await user.send(
                _("🔔 Reminder: The event '{event_name}' is starting at {event_time}.").format(
                    event_name=event['name'],
                    event_time=event_time.strftime('%Y-%m-%d %H:%M %Z')
                )
            )
        except discord.Forbidden:
            self.logger.warning(f"Couldn't send reminder DM to user {user_id} for event {event_id} due to permissions")
        except discord.HTTPException as e:
            self.logger.error(f"Failed to send reminder DM to user {user_id} for event {event_id}: {e}")

    async def event_loop(self, guild: discord.Guild, event_id: str):
        """Simplified event loop that handles both notifications and event execution"""
        while True:
            try:
                event = self.guild_events[guild.id].get(event_id)
                if not event:
                    self.logger.info(f"Event {event_id} not found, stopping loop")
                    return

                guild_tz = await self.get_guild_timezone(guild)
                now = datetime.now(pytz.UTC)
                event_time = datetime.fromisoformat(event['time1'])
                
                # Calculate next notification or event time
                next_times = []
                
                # Add event start time
                next_times.append((event_time, "event"))
                
                # Add notification times
                for minutes in event['notifications']:
                    notif_time = event_time - timedelta(minutes=minutes)
                    notification_key = f"{guild.id}:{event_id}:{minutes}"
                    if notif_time > now and notification_key not in self.sent_notifications:
                        next_times.append((notif_time, f"notification_{minutes}"))

                if not next_times:
                    await self.update_event_times(guild, event_id)
                    continue

                # Get the next occurring time
                next_time, action_type = min(next_times, key=lambda x: x[0])
                
                # Calculate sleep duration
                sleep_duration = (next_time - now).total_seconds()
                if sleep_duration > 0:
                    await asyncio.sleep(sleep_duration)

                # Handle the action
                if action_type == "event":
                    await self.send_event_start_message(guild, event_id, next_time)
                    await self.update_event_times(guild, event_id)
                elif action_type.startswith("notification_"):
                    minutes = int(action_type.split("_")[1])
                    notification_key = f"{guild.id}:{event_id}:{minutes}"
                    if notification_key not in self.sent_notifications:
                        await self.send_notification(guild, event_id, minutes, event_time)
                        self.sent_notifications.add(notification_key)

            except asyncio.CancelledError:
                self.logger.info(f"Event loop for {event_id} cancelled")
                return
            except Exception as e:
                self.logger.error(f"Error in event loop for {event_id}: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait before retrying

    async def update_event_times(self, guild: discord.Guild, event_id: str):
        guild_tz = await self.get_guild_timezone(guild)
        event = self.guild_events[guild.id].get(event_id)
        if not event:
            return

        time1 = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        time2 = datetime.fromisoformat(event['time2']).astimezone(guild_tz) if event.get('time2') else None
        now = datetime.now(guild_tz)

        if event['repeat'] == RepeatType.DAILY.value:
            next_time1 = now.replace(hour=time1.hour, minute=time1.minute, second=0, microsecond=0)
            if next_time1 <= now:
                next_time1 += timedelta(days=1)
            
            if time2:
                next_time2 = now.replace(hour=time2.hour, minute=time2.minute, second=0, microsecond=0)
                if next_time2 <= now:
                    next_time2 += timedelta(days=1)
            else:
                next_time2 = None
        elif event['repeat'] == RepeatType.WEEKLY.value:
            days_ahead = time1.weekday() - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            next_time1 = now + timedelta(days=days_ahead)
            next_time1 = next_time1.replace(hour=time1.hour, minute=time1.minute, second=0, microsecond=0)
            
            if time2:
                next_time2 = next_time1.replace(hour=time2.hour, minute=time2.minute)
            else:
                next_time2 = None
        elif event['repeat'] == RepeatType.MONTHLY.value:
            next_month = now.replace(day=1) + timedelta(days=32)
            next_time1 = next_month.replace(day=min(time1.day, calendar.monthrange(next_month.year, next_month.month)[1]),
                                            hour=time1.hour, minute=time1.minute, second=0, microsecond=0)
            if time2:
                next_time2 = next_time1.replace(hour=time2.hour, minute=time2.minute)
            else:
                next_time2 = None
        elif event['repeat'] == RepeatType.YEARLY.value:
            next_year = now.replace(year=now.year + 1, month=time1.month, day=time1.day,
                                    hour=time1.hour, minute=time1.minute, second=0, microsecond=0)
            if time1.month == 2 and time1.day == 29 and not calendar.isleap(next_year.year):
                next_year = next_year.replace(day=28)
            next_time1 = next_year
            
            if time2:
                next_time2 = next_time1.replace(hour=time2.hour, minute=time2.minute)
            else:
                next_time2 = None
        else:
            return

        event['time1'] = next_time1.isoformat()
        if next_time2:
            event['time2'] = next_time2.isoformat()

        async with self.config.guild(guild).events() as events:
            events[event_id] = event
        self.guild_events[guild.id][event_id] = event

        # After updating the event times, update the event info embed
        if event_id in self.event_info_messages:
            channel_id, message_id = self.event_info_messages[event_id]
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    message = await channel.fetch_message(message_id)
                    new_embed = await self.create_event_info_embed(guild, event_id, event)
                    await message.edit(embed=new_embed)
                except (discord.NotFound, discord.Forbidden):
                    del self.event_info_messages[event_id]

    async def queue_notification(self, guild: discord.Guild, event_id: str, notification_time: int, event_time: datetime):
        guild_tz = await self.get_guild_timezone(guild)
        queue_key = f"{guild.id}:{event_id}:{notification_time}"
        
        if queue_key in self.notification_queue and self.notification_queue[queue_key]:
            self.logger.debug(f"Notification for event {event_id} at {notification_time} minutes already queued.")
            return

        # Check last notification time
        last_notification = self.last_notification_time.get(queue_key)
        now = datetime.now(guild_tz)
        if last_notification and now - last_notification < MIN_NOTIFICATION_INTERVAL:
            self.logger.debug(f"Skipping notification for event {event_id} at {notification_time} minutes due to minimum interval.")
            return

        notification_event = asyncio.Event()
        self.notification_queue[queue_key].append(notification_event)
        
        try:
            await self.send_notification(guild, event_id, notification_time, event_time)
            self.last_notification_time[queue_key] = now
        except Exception as e:
            self.logger.error(f"Failed to send notification for event {event_id}: {e}")
            # Store failed notifications for retry
            self.failed_notifications.append((guild.id, event_id, notification_time, event_time))

        self.notification_queue[queue_key].remove(notification_event)
        if not self.notification_queue[queue_key]:
            del self.notification_queue[queue_key]

    async def send_notification_with_retry(self, guild: discord.Guild, event_id: str, notification_time: int, event_time: datetime):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self.send_notification(guild, event_id, notification_time, event_time)
                return
            except discord.HTTPException as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"Failed to send notification after {max_retries} attempts: {e}")
                else:
                    retry_delay = (2 ** attempt) * 5  # Exponential backoff
                    self.logger.warning(f"Attempt {attempt + 1} failed, retrying in {retry_delay} seconds: {e}")
                    await asyncio.sleep(retry_delay)
            except Exception as e:
                self.logger.error(f"Unexpected error sending notification: {e}")
                return

    async def send_notification(self, guild: discord.Guild, event_id: str, notification_time: int, event_time: datetime):
        self.logger.debug(f"Sending notification for event {event_id} at {notification_time} minutes before the event.")
        guild_tz = await self.get_guild_timezone(guild)
        event = self.guild_events[guild.id].get(event_id)
        if not event:
            self.logger.error(f"Event {event_id} not found in guild {guild.id} during notification.")
            return

        channel = guild.get_channel(event['channel'])
        if not channel:
            self.logger.error(f"Channel not found for event {event_id} in guild {guild.id}.")
            return

        role = guild.get_role(event['role_id']) if event.get('role_id') else None
        role_mention = role.mention if role else "@everyone"
    
        embed = discord.Embed(
            title=f"🔔 Event Reminder: {event['name']}",
            description=_("The event '{event_name}' is starting in {minutes} minutes!").format(event_name=event['name'], minutes=notification_time),
            color=discord.Color.blue()
        )
        embed.add_field(name=_("Description"), value=event['description'], inline=False)
        embed.add_field(name=_("Start Time"), value=f"<t:{int(event_time.astimezone(guild_tz).timestamp())}:F>", inline=False)
        embed.set_footer(text=_("This message will be automatically deleted in 30 minutes."))
    
        try:
            message = await channel.send(content=role_mention, embed=embed)
            self.bot.loop.create_task(self.delete_message_after(message, delay=1800))
        except discord.HTTPException as e:
            self.logger.error(f"Failed to send notification message: {e}")
            try:
                await channel.send(_("An error occurred while sending the notification message. Please try again later."))
            except discord.HTTPException:
                self.logger.error(f"Failed to send error message to channel {channel.id} in guild {guild.id}")

    async def delete_message_after(self, message: discord.Message, delay: int):
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    async def send_event_start_message(self, guild: discord.Guild, event_id: str, event_time: datetime):
        guild_tz = await self.get_guild_timezone(guild)
        event = self.guild_events[guild.id].get(event_id)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            role = guild.get_role(event['role_id']) if event['role_id'] else None
            role_mention = role.mention if role else "@everyone"
            
            embed = discord.Embed(
                title=f"🎉 {role_mention} Event Starting Now: {event['name']}",
                description=_("The event '{event_name}' is starting now!").format(event_name=event['name']),
                color=discord.Color.green()
            )
            embed.add_field(name=_("Description"), value=event['description'], inline=False)
            embed.add_field(name=_("Start Time"), value=f"<t:{int(event_time.astimezone(guild_tz).timestamp())}:F>", inline=False)
            
            try:
                await channel.send(embed=embed)
            except discord.HTTPException as e:
                self.logger.error(f"Failed to send event start message: {e}")
                await channel.send(_("An error occurred while sending the event start message. Please try again later."))

    @commands.hybrid_group(name="event", invoke_without_command=True)
    async def event(self, ctx):
        """Manage and participate in events."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @event.command(name="create")
    @app_commands.describe(
        name="Name of the event",
        start_time="Start time of the event (HH:MM)",
        end_time="End time of the event (HH:MM, optional)",
        date="Date of the event (YYYY-MM-DD)",
        description="Description of the event",
        channel="Channel to post event notifications in",
        repeat="Repeat frequency (none/daily/weekly/monthly/yearly)",
        notifications="Minutes before event to send notifications (comma-separated)",
        role="Role to mention for the event"
    )
    @commands.has_permissions(manage_events=True)
    async def event_create(
        self, 
        ctx: commands.Context,
        name: str,
        start_time: str,
        date: str,
        description: str,
        channel: discord.TextChannel,
        end_time: str = None,
        repeat: str = "none",
        notifications: str = "30",
        role: discord.Role = None
    ):
        """Create a new event with the specified details."""
        try:
            # Validate time format
            try:
                event_time = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
            except ValueError:
                await ctx.send(embed=self.error_embed(_("Invalid date/time format. Use YYYY-MM-DD HH:MM")))
                return

            # Validate repeat option
            repeat = repeat.lower()
            if repeat not in RepeatType._value2member_map_:
                await ctx.send(embed=self.error_embed(_("Invalid repeat option. Use: none/daily/weekly/monthly/yearly")))
                return

            # Parse notifications
            try:
                notification_times = [int(n.strip()) for n in notifications.split(',')]
            except ValueError:
                await ctx.send(embed=self.error_embed(_("Invalid notification format. Use comma-separated numbers (e.g., '10,30,60')")))
                return

            # Create event role if specified
            if role:
                role = await self.create_or_get_event_role(ctx.guild, role)
                if not role:
                    await ctx.send(embed=self.error_embed(_("Failed to create event role")))
                    return
            else:
                role = None

            # Create the event
            guild_tz = await self.get_guild_timezone(ctx.guild)
            event_time = guild_tz.localize(event_time)
            
            success, event_id = await self.create_event(
                ctx.guild,
                name,
                event_time,
                description,
                notification_times,
                repeat,
                role_name,
                channel
            )

            if success:
                embed = await self.create_event_info_embed(ctx.guild, event_id, self.guild_events[ctx.guild.id][event_id])
                view = EventInfoView(self, event_id, role.id if role else None)
                message = await ctx.send(
                    embed=self.success_embed(_("Event created successfully! Here are the details:")),
                    view=view
                )
                
                # Store message for updates
                if ctx.guild.id not in self.event_info_messages:
                    self.event_info_messages[ctx.guild.id] = {}
                self.event_info_messages[ctx.guild.id][event_id] = (ctx.channel.id, message.id)
            else:
                await ctx.send(embed=self.error_embed(_("Failed to create event. Please try again.")))

        except Exception as e:
            await self.handle_command_error(ctx, e)

    @event.command(name="delete")
    @app_commands.describe(name="Name of the event to delete")
    @commands.has_permissions(manage_events=True)
    async def event_delete(self, ctx, *, name: str):
        """Delete an event by its name."""
        event_id = await self.get_event_id_from_name(ctx.guild, name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.")))
            return

        view = ConfirmView(self, ctx, name)
        embed = discord.Embed(
            title=_("🗑️ Delete Event"),
            description=_("Are you sure you want to delete the event '{event_name}'?").format(event_name=name),
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, view=view)

    @event.command(name="edit")
    @app_commands.describe(
        name="Name of the event to edit",
        new_name="New name for the event",
        start_time="New start time (HH:MM)",
        end_time="New end time (HH:MM, optional)",
        date="New date (YYYY-MM-DD)",
        description="New description",
        channel="New channel for notifications",
        repeat="New repeat frequency (none/daily/weekly/monthly/yearly)",
        notifications="New notification times (comma-separated minutes)",
        role="New role to mention"
    )
    @commands.has_permissions(manage_events=True)
    async def event_edit(
        self,
        ctx: commands.Context,
        name: str,
        new_name: str = None,
        start_time: str = None,
        end_time: str = None,
        date: str = None,
        description: str = None,
        channel: discord.TextChannel = None,
        repeat: str = None,
        notifications: str = None,
        role: discord.Role = None
    ):
        """Edit an existing event's details."""
        event_id = await self.get_event_id_from_name(ctx.guild, name)
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.")))
            return

        current_event = self.guild_events[ctx.guild.id][event_id]
        guild_tz = await self.get_guild_timezone(ctx.guild)

        # Build update data
        update_data = {}
        
        if new_name:
            update_data['name'] = new_name
            
        if start_time and date:
            try:
                new_time = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
                new_time = guild_tz.localize(new_time)
                update_data['time1'] = new_time.isoformat()
            except ValueError:
                await ctx.send(embed=self.error_embed(_("Invalid date/time format. Use YYYY-MM-DD HH:MM")))
                return
                
        if description:
            update_data['description'] = description
            
        if channel:
            update_data['channel'] = channel.id
            
        if repeat:
            repeat = repeat.lower()
            if repeat not in RepeatType._value2member_map_:
                await ctx.send(embed=self.error_embed(_("Invalid repeat option")))
                return
            update_data['repeat'] = repeat
            
        if notifications:
            try:
                notif_times = [int(n.strip()) for n in notifications.split(',')]
                update_data['notifications'] = notif_times
            except ValueError:
                await ctx.send(embed=self.error_embed(_("Invalid notification format")))
                return
                
        if role:
            role = await self.create_or_get_event_role(ctx.guild, role)
            if role:
                update_data['role_name'] = role_name
                update_data['role_id'] = role.id
            else:
                await ctx.send(embed=self.error_embed(_("Failed to create/update role")))
                return

        if not update_data:
            await ctx.send(embed=self.error_embed(_("No changes specified")))
            return

        success = await self.update_event(ctx.guild, event_id, update_data)
        if success:
            embed = await self.create_event_info_embed(ctx.guild, event_id, self.guild_events[ctx.guild.id][event_id])
            await ctx.send(
                embed=self.success_embed(_("Event updated successfully! Here are the new details:")),
                view=EventInfoView(self, event_id, role.id if role else None)
            )
        else:
            await ctx.send(embed=self.error_embed(_("Failed to update event")))

    @event.command(name="list")
    async def event_list(self, ctx):
        """List all scheduled events."""
        guild_tz = await self.get_guild_timezone(ctx.guild)
        events = await self.config.guild(ctx.guild).events()
        if not events:
            await ctx.send(embed=self.error_embed(_("No events scheduled.")))
            return
        
        embed = discord.Embed(title=_("📅 Scheduled Events"), color=discord.Color.blue())
        for event_id, data in events.items():
            event_time = datetime.fromisoformat(data['time1']).astimezone(guild_tz)
            time_until = humanize.naturaltime(event_time, when=datetime.now(guild_tz))
            embed.add_field(
                name=data['name'],
                value=f"🕒 {event_time.strftime('%Y-%m-%d %H:%M')} {guild_tz}\n⏳ {time_until}\n📍 <#{data['channel']}>",
                inline=False
            )
        await ctx.send(embed=embed)

    @event.command(name="info")
    @app_commands.describe(name="Name of the event")
    async def event_info(self, ctx, *, name: str):
        """Show detailed information about an event."""
        event_id = await self.get_event_id_from_name(ctx.guild, name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.")), ephemeral=True)
            return

        event = self.guild_events.get(ctx.guild.id, {}).get(event_id)
        if not event:
            await ctx.send(embed=self.error_embed(_("Event data not found for '{event_name}'.")), ephemeral=True)
            return

        embed = await self.create_event_info_embed(ctx.guild, event_id, event)
        role_id = event.get('role_id')
        view = EventInfoView(self, event_id, role_id)
        message = await ctx.send(embed=embed, view=view)
        
        if ctx.guild.id not in self.event_info_messages:
            self.event_info_messages[ctx.guild.id] = {}
        self.event_info_messages[ctx.guild.id][event_id] = (ctx.channel.id, message.id)
        await self.config.guild(ctx.guild).event_info_messages.set(self.event_info_messages[ctx.guild.id])

    @event.command(name="cancel")
    @app_commands.describe(name="Name of the event to cancel")
    @commands.has_permissions(manage_events=True)
    async def event_cancel(self, ctx, *, name: str):
        """Cancel an event and notify participants."""
        event_id = await self.get_event_id_from_name(ctx.guild, name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.")), ephemeral=True)
            return

        event = self.guild_events[ctx.guild.id][event_id]
        guild_tz = await self.get_guild_timezone(ctx.guild)
        event_time = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        now = datetime.now(guild_tz)

        if event_time <= now:
            await ctx.send(embed=self.error_embed(_("This event has already started or passed.")), ephemeral=True)
            return

        await self.cancel_event(ctx.guild, name)
        await ctx.send(embed=self.success_embed(_("The event '{event_name}' has been cancelled and participants have been notified.").format(event_name=name)))

    @event.command(name="remind")
    @app_commands.describe(
        name="Name of the event",
        minutes="Minutes before the event to be reminded"
    )
    async def event_remind(self, ctx, name: str, minutes: int):
        """Set a personal reminder for an event."""
        event_id = await self.get_event_id_from_name(ctx.guild, name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.")), ephemeral=True)
            return

        event = self.guild_events[ctx.guild.id][event_id]
        guild_tz = await self.get_guild_timezone(ctx.guild)
        event_time = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        now = datetime.now(guild_tz)

        if event_time <= now:
            await ctx.send(embed=self.error_embed(_("This event has already started or passed.")), ephemeral=True)
            return

        await self.set_personal_reminder(ctx.guild, ctx.author.id, event_id, event_time - timedelta(minutes=minutes))
        await ctx.send(embed=self.success_embed(_("I'll remind you about '{event_id}' {minutes} minutes before it starts via direct message.").format(event_id=event_id, minutes=minutes)))

    @commands.hybrid_command(name="timezone")
    @app_commands.describe(timezone="Timezone to set (e.g., 'US/Pacific', 'Europe/London')")
    @commands.has_permissions(manage_guild=True)
    async def set_timezone(self, ctx: commands.Context, *, timezone: str):
        """Set the timezone for the guild."""
        try:
            await self.update_guild_timezone(ctx.guild, timezone)
            await ctx.send(embed=self.success_embed(_("Timezone set to {timezone_str}").format(timezone_str=timezone)))
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(embed=self.error_embed(_("Unknown timezone: {timezone_str}. Please use a valid timezone from the IANA Time Zone Database.").format(timezone_str=timezone)))
        except Exception as e:
            await self.handle_command_error(ctx, e)

    async def update_guild_timezone(self, guild: discord.Guild, new_timezone: str):
        old_tz = await self.get_guild_timezone(guild)
        new_tz = pytz.timezone(new_timezone)
        
        async with self.config.guild(guild).events() as events:
            for event in events.values():
                event['time1'] = datetime.fromisoformat(event['time1']).astimezone(old_tz).astimezone(new_tz).isoformat()
                if event.get('time2'):
                    event['time2'] = datetime.fromisoformat(event['time2']).astimezone(old_tz).astimezone(new_tz).isoformat()
        
        await self.config.guild(guild).timezone.set(new_timezone)
        self.guild_timezone_cache[guild.id] = new_tz
        await self.update_event_cache(guild)
        self.logger.info(f"Updated timezone for guild {guild.id} to {new_timezone}")

    async def update_event_cache(self, guild: discord.Guild, event_id: str = None):
        if event_id:
            event = await self.config.guild(guild).events.get_raw(event_id)
            if event:
                self.guild_events[guild.id][event_id] = event
            else:
                self.guild_events[guild.id].pop(event_id, None)
        else:
            events = await self.config.guild(guild).events()
            self.guild_events[guild.id] = events
        self.logger.debug(f"Event cache updated for guild {guild.id}")

    async def log_and_notify_error(self, guild: discord.Guild, message: str, error: Exception):
        self.logger.error(f"{message}: {error}", exc_info=True)
        owner = guild.owner
        if owner:
            try:
                await owner.send(f"An error occurred in the event system: {message}\n```{error}```")
            except discord.HTTPException:
                pass

    async def send_notification_with_retry(self, guild: discord.Guild, event_id: str, notification_time: int, event_time: datetime):
        self.logger.debug(f"Sending notification for event {event_id} at {notification_time} minutes before the event.")
        guild_tz = await self.get_guild_timezone(guild)
        event = self.guild_events[guild.id].get(event_id)
        if not event:
            self.logger.error(f"Event {event_id} not found in guild {guild.id} during notification.")
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            role = guild.get_role(event['role_id']) if event['role_id'] else None
            role_mention = role.mention if role else "@everyone"
            
            embed = discord.Embed(
                title=f"🔔 {role_mention} Event Reminder: {event['name']}",
                description=_("The event '{event_name}' is starting in {minutes} minutes!").format(event_name=event['name'], minutes=notification_time),
                color=discord.Color.blue()
            )
            embed.add_field(name=_("Description"), value=event['description'], inline=False)
            embed.add_field(name=_("Start Time"), value=f"<t:{int(event_time.astimezone(guild_tz).timestamp())}:F>", inline=False)
            embed.set_footer(text=_("This message will be automatically deleted in 30 minutes."))
            
            try:
                message = await channel.send(embed=embed)
                self.bot.loop.create_task(self.delete_message_after(message, delay=1800))
            except discord.HTTPException as e:
                self.logger.error(f"Failed to send notification message: {e}")
                await channel.send(_("An error occurred while sending the notification message. Please try again later."))

    @tasks.loop(minutes=15)
    async def sync_event_cache(self):
        changes_made = False
        for guild in self.bot.guilds:
            events = await self.config.guild(guild).events()
            if self.guild_events.get(guild.id) != events:
                self.guild_events[guild.id] = events
                changes_made = True
        if changes_made:
            self.logger.info("Event cache synced with changes")

    @tasks.loop(minutes=5)
    async def update_event_embeds(self):
        for guild in self.bot.guilds:
            guild_tz = await self.get_guild_timezone(guild)
            now = datetime.now(guild_tz)
            for event_id, event in self.guild_events[guild.id].items():
                if event_id in self.event_info_messages:
                    channel_id, message_id = self.event_info_messages[event_id]
                    channel = guild.get_channel(channel_id)
                    if channel:
                        try:
                            message = await channel.fetch_message(message_id)
                            new_embed = await self.create_event_info_embed(guild, event_id, event)
                            await message.edit(embed=new_embed)
                        except (discord.NotFound, discord.Forbidden):
                            del self.event_info_messages[event_id]

    async def update_single_event_embed(self, guild: discord.Guild, event_id: str):
        if event_id in self.event_info_messages:
            channel_id, message_id = self.event_info_messages[event_id]
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    message = await channel.fetch_message(message_id)
                    event = self.guild_events[guild.id].get(event_id)
                    if event:
                        new_embed = await self.create_event_info_embed(guild, event_id, event)
                        await message.edit(embed=new_embed)
                except (discord.NotFound, discord.Forbidden):
                    del self.event_info_messages[event_id]

    async def handle_command_error(self, ctx: commands.Context, error: Exception):
        self.logger.error(f"Error in command {ctx.command}: {error}", exc_info=True)
        await ctx.send(embed=self.error_embed(_("An error occurred while processing the command. Please try again later.")))

    async def get_guild_config(self, guild: discord.Guild):
        return await self.config.guild(guild).all()

    async def set_guild_config(self, guild: discord.Guild, config: dict):
        await self.config.guild(guild).set(config)

    async def sync_config(self, guild: discord.Guild):
        config = await self.get_guild_config(guild)
        self.guild_events[guild.id] = config.get("events", {})
        self.guild_timezone_cache[guild.id] = pytz.timezone(config.get("timezone", "UTC"))

    @commands.hybrid_command(name="eventhelp", aliases=["event"])
    async def event_help(self, ctx):
        """Display a list of all available event-related commands."""
        prefix = ctx.clean_prefix

        embed = discord.Embed(
            title=_("📅 Event Management System Help"),
            description=_("Here's a list of all available event-related commands:"),
            color=discord.Color.blue()
        )

        management_commands = [
            ("eventcreate", _("Start the process of creating a new event using an interactive modal.")),
            ("eventdelete <name>", _("Delete a specific event by its name.")),
            ("eventupdate <name> [options]", _("Update details of an existing event.")),
            ("settimezone <timezone>", _("Set the timezone for the guild (e.g., 'US/Pacific', 'Europe/London').")),
            ("eventedit <name>", _("Edit an existing event using an interactive modal.")),
            ("eventcancel <name>", _("Cancel an event and notify all participants.")),
        ]

        event_commands = [
            ("eventlist", _("Display a list of all scheduled events.")),
            ("eventinfo <name>", _("Display detailed information about a specific event.")),
            ("eventremind <name>", _("Set a personal reminder for an event.")),
        ]

        embed.add_field(name=_("🛠️ Management Commands"), value=_("Commands for creating and managing events (requires Manage Events permission):"), inline=False)
        for command, description in management_commands:
            embed.add_field(name=f"`{prefix}{command}`", value=description, inline=False)

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        embed.add_field(name=_("🎫 Event Participation Commands"), value=_("Commands for event participants:"), inline=False)
        for command, description in event_commands:
            embed.add_field(name=f"`{prefix}{command}`", value=description, inline=False)

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        embed.add_field(name=_("ℹ️ Help Command"), value=_("For help with specific commands, use `{prefix}help <command>`.").format(prefix=prefix), inline=False)
        embed.set_footer(text=_("Current prefix: {prefix}").format(prefix=prefix))
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="eventpurge")
    @commands.has_permissions(administrator=True)
    async def event_purge(self, ctx):
        """
        Purge all event data. Use with caution!

        This command will purge all event data. Use it only when necessary.
        """
        view = ConfirmPurgeView(self)
        embed = discord.Embed(
            title=_("⚠️ Purge All Event Data"),
            description=_("Are you sure you want to purge all event data?"),
            color=discord.Color.red()
        )
        embed.add_field(name=_("Warning"), value=_("This should only be used when updates to the cog break compatibility with current events."))
        await ctx.send(embed=embed, view=view)

    async def purge_all_data(self):
        await self.config.clear_all()
        self.event_tasks.clear()
        self.personal_reminder_tasks.clear()
        self.notification_queue.clear()
        self.temp_event_data.clear()
        self.last_notification_time.clear()

    async def get_guild_timezone(self, guild: discord.Guild) -> pytz.timezone:
        if guild.id not in self.guild_timezone_cache:
            timezone_str = await self.config.guild(guild).timezone()
            self.guild_timezone_cache[guild.id] = pytz.timezone(timezone_str)
        return self.guild_timezone_cache[guild.id]

    async def initialize_event_info_messages(self):
        await self.bot.wait_until_ready()
        self.event_info_messages = {}
        for guild in self.bot.guilds:
            guild_messages = await self.config.guild(guild).event_info_messages()
            self.event_info_messages[guild.id] = guild_messages or {}
        self.logger.info("Event info messages initialized")

    async def log_and_notify_error(self, guild: discord.Guild, message: str, error: Exception):
        error_details = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        self.logger.error(f"{message}: {error_details}")
        owner = guild.owner
        if owner:
            try:
                await owner.send(f"An error occurred in the event system: {message}\n```{error_details[:1900]}```")
            except discord.HTTPException:
                pass

class ReminderSelectView(ui.View):
    def __init__(self, cog, user_id: int, event_id: str, event_time: datetime):
        super().__init__()
        self.cog = cog
        self.user_id = user_id
        self.event_id = event_id
        self.event_time = event_time

        self.add_item(ReminderSelect(self.set_reminder))

    async def set_reminder(self, interaction: discord.Interaction, minutes: int):
        guild_tz = await self.cog.get_guild_timezone(interaction.guild)
        reminder_time = self.event_time - timedelta(minutes=minutes)
        now = datetime.now(guild_tz)
        if reminder_time <= now:
            await interaction.response.send_message(embed=self.cog.error_embed(_("This reminder time has already passed.")), ephemeral=True)
            return

        await self.cog.set_personal_reminder(interaction.guild_id, self.user_id, self.event_id, reminder_time)
        await interaction.response.send_message(embed=self.cog.success_embed(_("I'll remind you about '{event_id}' {minutes} minutes before it starts via direct message.").format(event_id=self.event_id, minutes=minutes)), ephemeral=True)

class ReminderSelect(ui.Select):
    def __init__(self, callback):
        options = [
            discord.SelectOption(label=_("5 minutes"), value="5", emoji="⏱️"),
            discord.SelectOption(label=_("15 minutes"), value="15", emoji="⏱️"),
            discord.SelectOption(label=_("30 minutes"), value="30", emoji="⏱️"),
            discord.SelectOption(label=_("1 hour"), value="60", emoji="⏰"),
            discord.SelectOption(label=_("2 hours"), value="120", emoji="⏰"),
        ]
        super().__init__(placeholder=_("Select reminder time before the event"), options=options)
        self.callback_function = callback

    async def callback(self, interaction: discord.Interaction):
        await self.callback_function(interaction, int(self.values[0]))

class ConfirmView(ui.View):
    def __init__(self, cog, ctx, event_name):
        super().__init__(timeout=60)  # 1 minute timeout
        self.cog = cog
        self.ctx = ctx
        self.event_name = event_name
        self.value = None

    @ui.button(label=_("Confirm"), style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        event_id = await self.cog.get_event_id_from_name(self.ctx.guild, self.event_name)
        if event_id:
            success = await self.cog.delete_event(self.ctx.guild, event_id)
            if success:
                await interaction.response.send_message(_("Event '{event_name}' has been deleted.").format(event_name=self.event_name))
            else:
                await interaction.response.send_message(_("Failed to delete event '{event_name}'. Please try again later.").format(event_name=self.event_name))
        else:
            await interaction.response.send_message(_("Event '{event_name}' not found.").format(event_name=self.event_name))
        self.value = True
        self.stop()

    @ui.button(label=_("Cancel"), style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(_("Event deletion cancelled."))
        self.value = False
        self.stop()

    async def on_timeout(self):
        await self.ctx.send(_("Event deletion timed out."))
        self.stop()


class ConfirmPurgeView(ui.View):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    @ui.button(label=_("Confirm Purge"), style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_purge(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.purge_all_data()
        embed = discord.Embed(
            title=_("✅ Data Purged"),
            description=_("All event data has been purged successfully."),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @ui.button(label=_("Cancel"), style=discord.ButtonStyle.secondary, emoji="🚫")
    async def cancel_purge(self, interaction: discord.Interaction, button: ui.Button):
        embed = discord.Embed(
            title=_("❌ Purge Cancelled"),
            description=_("The purge operation has been cancelled. No data was deleted."),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

class BasicEventEditModal(ui.Modal, title=_("Edit Event - Basic Info")):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict, timezone: pytz.timezone):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data
        self.timezone = timezone

        self.name = ui.TextInput(label=_("Event Name"), default=event_name, max_length=100)
        self.datetime1 = ui.TextInput(label=_("First Time (HH:MM)"), default=datetime.fromisoformat(event_data['time1']).astimezone(self.timezone).strftime("%H:%M"))
        self.datetime2 = ui.TextInput(label=_("Second Time (Optional, HH:MM)"), default=datetime.fromisoformat(event_data['time2']).astimezone(self.timezone).strftime("%H:%M") if event_data.get('time2') else "", required=False)
        self.description = ui.TextInput(label=_("Description"), style=discord.TextStyle.paragraph, max_length=1000, default=event_data['description'])

        self.add_item(self.name)
        self.add_item(self.datetime1)
        self.add_item(self.datetime2)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            now = datetime.now(self.timezone)
            
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

        self.cog.temp_edit_data[interaction.user.id] = {
            'name': self.name.value,
            'time1': event_time1.isoformat(),
            'time2': event_time2.isoformat() if event_time2 else None,
            'description': self.description.value,
        }

        view = AdvancedEditOptionsView(self.cog, self.guild, self.event_name, self.event_data)
        await interaction.response.send_message(_("Basic information updated. Click the button below to edit advanced options:"), view=view, ephemeral=True)
        await self.original_message.delete()

class AdvancedEventEditModal(ui.Modal, title=_("Edit Event - Advanced Options")):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict, timezone: pytz.timezone):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data
        self.timezone = timezone

        self.notifications = ui.TextInput(label=_("Notification Times (minutes)"), default=",".join(map(str, event_data['notifications'])))
        self.repeat = ui.TextInput(label=_("Repeat (none/daily/weekly/monthly/yearly)"), default=event_data['repeat'])
        self.role_name = ui.TextInput(label=_("Event Role Name"), default=event_data['role_name'])
        self.channel = ui.TextInput(label=_("Channel"), default=f"#{self.guild.get_channel(event_data['channel']).name}")

        self.add_item(self.notifications)
        self.add_item(self.repeat)
        self.add_item(self.role_name)
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            notifications = [int(n.strip()) for n in self.notifications.value.split(',')]
        except ValueError:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Invalid notification times.")), ephemeral=True)
            return

        repeat = self.repeat.value.lower()
        if repeat not in RepeatType._value2member_map_:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Invalid repeat option.")), ephemeral=True)
            return

        role_name = self.role_name.value.strip()
        if not role_name:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Event role name is required.")), ephemeral=True)
            return

        channel_name = self.channel.value.lstrip('#')
        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Channel #{channel_name} not found.").format(channel_name=channel_name)), ephemeral=True)
            return

        basic_data = self.cog.temp_edit_data.pop(interaction.user.id, None)
        if not basic_data:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Error: Event data not found.")), ephemeral=True)
            return

        new_data = {
            'name': basic_data['name'],
            'time1': basic_data['time1'],
            'time2': basic_data['time2'],
            'description': basic_data['description'],
            'notifications': notifications,
            'repeat': repeat,
            'role_name': role_name,
            'channel': channel.id,
        }

        event_id = await self.cog.get_event_id_from_name(self.guild, self.event_name)
        if event_id:
            success = await self.cog.update_event(self.guild, event_id, new_data)
            if success:
                await interaction.response.send_message(embed=self.cog.success_embed(_("Event '{event_name}' has been updated successfully.").format(event_name=self.event_name)), ephemeral=True)
            else:
                await interaction.response.send_message(embed=self.cog.error_embed(_("Failed to update event '{event_name}'.")), ephemeral=True)
        else:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Event '{event_name}' not found.")), ephemeral=True)

class EventEditView(ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    async def on_timeout(self):
        await self.message.delete()

    @ui.button(label=_("Edit Event"), style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_event_button(self, interaction: discord.Interaction, button: ui.Button):
        timezone = await self.cog.get_guild_timezone(self.guild)
        modal = BasicEventEditModal(self.cog, self.guild, self.event_name, self.event_data, timezone)
        await interaction.response.send_modal(modal)

class AdvancedEditOptionsView(ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    @ui.button(label=_("Edit Advanced Options"), style=discord.ButtonStyle.primary, emoji="⚙️")
    async def advanced_options_button(self, interaction: discord.Interaction, button: ui.Button):
        timezone = await self.cog.get_guild_timezone(self.guild)
        modal = AdvancedEventEditModal(self.cog, self.guild, self.event_name, self.event_data, timezone)
        await interaction.response.send_modal(modal)

class ConfirmCancelView(ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    @ui.button(label=_("Confirm Cancel"), style=discord.ButtonStyle.danger, emoji="🚫")
    async def confirm_cancel(self, interaction: discord.Interaction, button: ui.Button):
        await self.cog.cancel_event(self.guild, self.event_name)
        await interaction.response.send_message(embed=self.cog.success_embed(_("The event '{event_name}' has been cancelled and participants have been notified.").format(event_name=self.event_name)))
        await self.message.delete()
        self.stop()

    @ui.button(label=_("Keep Event"), style=discord.ButtonStyle.secondary, emoji="🔙")
    async def keep_event(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(embed=self.cog.success_embed(_("The event '{event_name}' has not been cancelled.").format(event_name=self.event_name)))
        await self.message.delete()
        self.stop()

async def setup(bot: Red):
    await bot.add_cog(RobustEventsCog(bot))
