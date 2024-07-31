import asyncio
import calendar
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional

import discord
import humanize
import pytz
from discord.ext import commands, tasks
from discord.ui import Modal, TextInput, View
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n

_ = Translator("RobustEvents", __file__)

class RepeatType(Enum):
    NONE = 'none'
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'

class BasicEventModal(Modal):
    def __init__(self, cog, guild: discord.Guild, original_message: discord.Message):
        super().__init__(title=_("Create New Event - Basic Info"))
        self.cog = cog
        self.guild = guild
        self.original_message = original_message

        self.name = TextInput(label=_("Event Name"), placeholder=_("Enter event name"), max_length=100)
        self.datetime1 = TextInput(label=_("First Time (HH:MM)"), placeholder=_("14:30"))
        self.datetime2 = TextInput(label=_("Second Time (Optional, HH:MM)"), placeholder=_("18:30"), required=False)
        self.description = TextInput(label=_("Description"), style=discord.TextStyle.paragraph, max_length=1000)

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

class AdvancedEventModal(Modal):
    def __init__(self, cog, guild: discord.Guild, original_message: discord.Message):
        super().__init__(title=_("Create New Event - Advanced Options"))
        self.cog = cog
        self.guild = guild
        self.original_message = original_message

        self.notifications = TextInput(label=_("Notification Times (minutes)"), placeholder=_("10,30,60"))
        self.repeat = TextInput(label=_("Repeat (none/daily/weekly/monthly/yearly)"), placeholder=_("none"))
        self.role_name = TextInput(label=_("Event Role Name"), placeholder=_("Event Attendees"))
        self.channel = TextInput(label=_("Channel"), placeholder=_("#events"))

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

        await self.original_message.delete()

class AdvancedOptionsView(View):
    def __init__(self, cog, original_message: discord.Message):
        super().__init__()
        self.cog = cog
        self.original_message = original_message

    @discord.ui.button(label=_("Set Advanced Options"), style=discord.ButtonStyle.primary)
    async def advanced_options_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        advanced_modal = AdvancedEventModal(self.cog, interaction.guild, self.original_message)
        await interaction.response.send_modal(advanced_modal)
        self.stop()

class EventCreationView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.message = None

    @discord.ui.button(label=_("Create Event"), style=discord.ButtonStyle.primary, emoji="➕")
    async def create_event_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        basic_modal = BasicEventModal(self.cog, self.guild, self.message)
        await interaction.response.send_modal(basic_modal)

class EventInfoView(discord.ui.View):
    def __init__(self, cog, event_id: str, role_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event_id
        self.role_id = role_id

    @discord.ui.button(label=_("Join Event"), style=discord.ButtonStyle.primary, emoji="✅")
    async def join_event(self, interaction: discord.Interaction, button: discord.ui.Button):
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
            except discord.Forbidden:
                await interaction.response.send_message(_("I don't have permission to assign roles."), ephemeral=True)

    @discord.ui.button(label=_("Set Reminder"), style=discord.ButtonStyle.secondary, emoji="⏰")
    async def set_reminder(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = self.cog.guild_events[interaction.guild.id].get(self.event_id)
        if not event:
            await interaction.response.send_message(_("Error: Event not found."), ephemeral=True)
            return

        guild_tz = await self.cog.get_guild_timezone(interaction.guild)
        event_time = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        view = ReminderSelectView(self.cog, interaction.user.id, self.event_id, event_time)
        await interaction.response.send_message(_("Select when you'd like to be reminded:"), view=view, ephemeral=True)

class EventReminderView(discord.ui.View):
    def __init__(self, cog, guild_id: int, event_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.event_id = event_id

    @discord.ui.button(label=_("View Event Details"), style=discord.ButtonStyle.primary, emoji="📅")
    async def view_event_details(self, interaction: discord.Interaction, button: discord.ui.Button):
        event = self.cog.guild_events[self.guild_id].get(self.event_id)
        if not event:
            await interaction.response.send_message(_("This event no longer exists."), ephemeral=True)
            return

        embed = await self.cog.create_event_info_embed(interaction.guild, self.event_id, event)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label=_("Snooze Reminder"), style=discord.ButtonStyle.secondary, emoji="⏰")
    async def snooze_reminder(self, interaction: discord.Interaction, button: discord.ui.Button):
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

        select = discord.ui.Select(placeholder=_("Select snooze duration"), options=snooze_options)

        async def snooze_callback(interaction: discord.Interaction):
            minutes = int(select.values[0])
            new_reminder_time = now + timedelta(minutes=minutes)
            if new_reminder_time >= event_time:
                await interaction.response.send_message(_("Cannot snooze past the event start time."), ephemeral=True)
                return

            await self.cog.set_personal_reminder(self.guild_id, interaction.user.id, self.event_id, new_reminder_time)
            await interaction.response.send_message(_("Reminder snoozed for {minutes} minutes.").format(minutes=minutes), ephemeral=True)

        select.callback = snooze_callback
        view = discord.ui.View()
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
        self.logger = logging.getLogger('red.RobustEvents')
        self.bot.loop.create_task(self.initialize_events())
        self.cleanup_expired_events.start()
        self.sync_event_cache.start()
        self.guild_timezone_cache = {}
        self.guild_events = defaultdict(dict)
        self.temp_event_data = defaultdict(dict)
        self.event_info_messages = {}
        self.update_event_embeds.start()
        self.config.register_guild(event_info_messages={})
        self.event_info_messages = {}
        self.bot.loop.create_task(self.initialize_event_info_messages())
        self.cleanup_event_info_messages.start()

    def cog_unload(self):
        self.cleanup_expired_events.cancel()
        self.sync_event_cache.cancel()
        self.update_event_embeds.cancel()
        for task in self.event_tasks.values():
            task.cancel()
        for task in self.personal_reminder_tasks.values():
            task.cancel()
        self.cleanup_event_info_messages.cancel()

    @tasks.loop(hours=24)
    async def cleanup_expired_events(self):
        for guild in self.bot.guilds:
            async with self.config.guild(guild).events() as events:
                current_time = datetime.now(pytz.UTC)
                to_remove = []
                for event_id, event in events.items():
                    event_time = max(datetime.fromisoformat(event['time1']), datetime.fromisoformat(event['time2'] or event['time1']))
                    if event['repeat'] == RepeatType.NONE.value and event_time < current_time:
                        to_remove.append(event_id)
                for event_id in to_remove:
                    del events[event_id]
                    if event_id in self.event_tasks:
                        self.event_tasks[event_id].cancel()
                        del self.event_tasks[event_id]

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
        if event_id in self.event_tasks:
            self.event_tasks[event_id].cancel()
        self.event_tasks[event_id] = self.bot.loop.create_task(self.event_loop(guild, event_id))

    async def schedule_personal_reminder(self, guild_id: int, user_id: int, event_id: str, reminder_time: datetime):
        task_key = f"{guild_id}:{user_id}:{event_id}"
        if task_key in self.personal_reminder_tasks:
            self.personal_reminder_tasks[task_key].cancel()
        self.personal_reminder_tasks[task_key] = self.bot.loop.create_task(self.personal_reminder_loop(guild_id, user_id, event_id, reminder_time))

    async def event_loop(self, guild: discord.Guild, event_id: str):
        while True:
            try:
                event = self.guild_events[guild.id].get(event_id)
                if not event:
                    return

                guild_tz = await self.get_guild_timezone(guild)
                now = datetime.now(guild_tz)
                time1 = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
                time2 = datetime.fromisoformat(event['time2']).astimezone(guild_tz) if event.get('time2') else None

                times = [time for time in [time1, time2] if time]
                next_time = min(times)

                if next_time <= now:
                    await self.update_event_times(guild, event_id)
                    continue

                time_until_event = next_time - now

                for notification_time in sorted(event['notifications'], reverse=True):
                    notification_delta = timedelta(minutes=notification_time)
                    if time_until_event > notification_delta:
                        await asyncio.sleep((time_until_event - notification_delta).total_seconds())
                        await self.queue_notification(guild, event_id, notification_time, next_time)
                        time_until_event = notification_delta

                await discord.utils.sleep_until(next_time)
                await self.send_event_start_message(guild, event_id, next_time)

                if time2 and next_time == time1:
                    await discord.utils.sleep_until(time2)
                    await self.send_event_start_message(guild, event_id, time2)

                await self.update_event_times(guild, event_id)

                # After updating event times, trigger an update of the event info embed
                await self.update_event_times(guild, event_id)

            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"Error in event loop for {event_id}: {e}")
                await asyncio.sleep(60)

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
            return

        notification_event = asyncio.Event()
        self.notification_queue[queue_key] = [notification_event]
        
        try:
            await self.send_notification(guild, event_id, notification_time, event_time)
        finally:
            self.notification_queue[queue_key].clear()

    async def send_notification(self, guild: discord.Guild, event_id: str, notification_time: int, event_time: datetime):
        guild_tz = await self.get_guild_timezone(guild)
        event = self.guild_events[guild.id].get(event_id)
        if not event:
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

    @commands.guild_only()
    @commands.command(name="eventcreate")
    @commands.has_permissions(manage_events=True)
    async def event_create(self, ctx):
        """
        Start the process of creating a new event using an interactive modal.

        This command will open an interactive form for creating a new event.
        You must have the Manage Events permission to use this command.
        """
        view = EventCreationView(self, ctx.guild)
        embed = discord.Embed(title=_("📅 Create New Event"), 
                              description=_("Click the button below to start creating a new event."), 
                              color=discord.Color.blue())
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @commands.guild_only()
    @commands.command(name="eventlist")
    async def event_list(self, ctx):
        """
        Display a list of all scheduled events.

        This command shows a list of all upcoming events with their details.
        """
        guild_tz = await self.cog.get_guild_timezone(ctx.guild)
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

    async def get_event_id_from_name(self, guild: discord.Guild, event_name: str) -> Optional[str]:
        events = await self.config.guild(guild).events()
        return next((id for id, event in events.items() if event['name'].lower() == event_name.lower()), None)

    @commands.guild_only()
    @commands.command(name="eventdelete")
    @commands.has_permissions(manage_events=True)
    async def event_delete(self, ctx, *, event_name: str):
        """
        Delete a specific event by its name.

        This command will delete an event and notify all participants.
        You must have the Manage Events permission to use this command.
        """
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if event_id:
            success = await self.delete_event(ctx.guild, event_id)
            if success:
                await ctx.send(embed=self.success_embed(_("Event '{event_name}' deleted.").format(event_name=event_name)))
            else:
                await ctx.send(embed=self.error_embed(_("Failed to delete event '{event_name}'.").format(event_name=event_name)))

    async def delete_event(self, guild: discord.Guild, event_id: str):
        async with self.config.guild(guild).events() as events:
            if event_id not in events:
                return False
            
            event = events.pop(event_id)

        if guild.id in self.guild_events and event_id in self.guild_events[guild.id]:
            del self.guild_events[guild.id][event_id]
        
        if event_id in self.event_tasks:
            self.event_tasks[event_id].cancel()
            del self.event_tasks[event_id]

        if event['role_id']:
            role = guild.get_role(event['role_id'])
            if role:
                try:
                    await role.delete()
                except discord.Forbidden:
                    self.logger.error(_("Couldn't delete the event role for '{event_name}' due to lack of permissions.").format(event_name=event['name']))

        async for member_id, member_data in self.config.all_members(guild):
            async with self.config.member_from_ids(guild.id, member_id).personal_reminders() as reminders:
                if event_id in reminders:
                    del reminders[event_id]
            task_key = f"{guild.id}:{member_id}:{event_id}"
            if task_key in self.personal_reminder_tasks:
                self.personal_reminder_tasks[task_key].cancel()
                del self.personal_reminder_tasks[task_key]

        for key in list(self.notification_queue.keys()):
            if key.startswith(f"{guild.id}:{event_id}:"):
                for notification_event in self.notification_queue[key]:
                    notification_event.set()
                del self.notification_queue[key]

        # Remove the event info message reference when deleting an event
        await self.remove_event_info_message(guild.id, event_id)

        return True

    @commands.guild_only()
    @commands.command(name="eventupdate")
    @commands.has_permissions(manage_events=True)
    async def event_update(self, ctx, *, event_name: str):
        """
        Update details of an existing event.

        This command allows updating the details of an event.
        You must have the Manage Events permission to use this command.
        """
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.").format(event_name=event_name)))
        else:
            event = self.guild_events[ctx.guild.id][event_id]
            view = EventEditView(self, ctx.guild, event_id, event)
            await ctx.send(embed=self.success_embed(_("Click the button below to edit the event '{event_name}'.").format(event_name=event_name)), view=view)

    async def create_event(self, guild: discord.Guild, name: str, event_time1: datetime, description: str, notifications: List[int], repeat: str, role_name: Optional[str], channel: Optional[discord.TextChannel], event_time2: Optional[datetime] = None) -> str:
        guild_tz = await self.get_guild_timezone(guild)
        event_time1 = event_time1.astimezone(guild_tz)
        if event_time2:
            event_time2 = event_time2.astimezone(guild_tz)
        try:
            event_role = await self.create_or_get_event_role(guild, role_name) if role_name else None

            event_id = str(uuid.uuid4())

            event_data = {
                "id": event_id,
                "name": name,
                "time1": event_time1.astimezone(guild_tz).isoformat(),
                "description": description,
                "notifications": sorted(notifications),
                "repeat": repeat,
                "role_name": role_name,
                "role_id": event_role.id if event_role else None,
                "channel": channel.id if channel else None,
                "time2": event_time2.astimezone(guild_tz).isoformat() if event_time2 else None
            }

            async with self.config.guild(guild).events() as events:
                events[event_id] = event_data
            self.guild_events[guild.id][event_id] = event_data
            await self.update_event_times(guild, event_id)
            await self.schedule_event(guild, event_id)
            return event_id
        except Exception as e:
            self.logger.error(f"Error creating event: {e}")
            raise

    async def update_event(self, guild: discord.Guild, event_id: str, new_data: dict) -> bool:
        try:
            async with self.config.guild(guild).events() as events:
                if event_id not in events:
                    return False

                events[event_id].update(new_data)
                self.guild_events[guild.id][event_id].update(new_data)
                await self.config.guild(guild).events.set(events)  # Ensure config changes are saved

            await self.schedule_event(guild, event_id)
            return True
        except Exception as e:
            self.logger.error(f"Error updating event {event_id}: {e}")
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
            self.logger.error(_("Bot doesn't have permission to create roles in guild {guild_name}").format(guild_name=guild.name))
            return None

    @commands.guild_only()
    @commands.command(name="settimezone")
    @commands.has_permissions(manage_events=True)
    async def set_timezone(self, ctx, timezone_str: str):
        """
        Set the timezone for the guild. Requires 'Manage Events' permission.

        Usage: [p]settimezone <timezone>
        Example: [p]settimezone US/Pacific
        """
        try:
            timezone = pytz.timezone(timezone_str)
            await self.config.guild(ctx.guild).timezone.set(timezone_str)
            self.guild_timezone_cache[ctx.guild.id] = timezone
            await ctx.send(embed=self.success_embed(_("Timezone set to {timezone_str}").format(timezone_str=timezone_str)))
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(embed=self.error_embed(_("Unknown timezone: {timezone_str}. Please use a valid timezone from the IANA Time Zone Database.").format(timezone_str=timezone_str)))

    @commands.guild_only()
    @commands.command(name="eventinfo")
    async def event_info(self, ctx, *, event_name: str):
        """
        Display detailed information about a specific event.

        This command shows detailed information about an upcoming event.
        """
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.")), ephemeral=True)
            return

        event = self.guild_events[ctx.guild.id].get(event_id)
        if not event:
            await ctx.send(embed=self.error_embed(_("Event data not found for '{event_name}'.")), ephemeral=True)
            return

        embed = await self.create_event_info_embed(ctx.guild, event_id, event)
        message = await ctx.send(embed=embed)
        
        # Store the message ID for future updates
        if ctx.guild.id not in self.event_info_messages:
            self.event_info_messages[ctx.guild.id] = {}
        self.event_info_messages[ctx.guild.id][event_id] = (ctx.channel.id, message.id)
        await self.config.guild(ctx.guild).event_info_messages.set(self.event_info_messages[ctx.guild.id])

    async def create_event_info_embed(self, guild: discord.Guild, event_id: str, event: dict):
        guild_tz = await self.get_guild_timezone(guild)
        time1 = datetime.fromisoformat(event['time1']).astimezone(guild_tz)
        time2 = datetime.fromisoformat(event['time2']).astimezone(guild_tz) if event.get('time2') else None

        embed = discord.Embed(title=f"📅 {event['name']}", color=discord.Color.blue())
        
        # Event description
        embed.description = f"```{event['description']}```"

        # Event times
        time_field = f"🕒 Start: <t:{int(time1.timestamp())}:F>"
        if time2:
            time_field += f"\n🕒 End: <t:{int(time2.timestamp())}:F>"
        embed.add_field(name=_("Event Time"), value=time_field, inline=False)

        # Countdown
        now = datetime.now(guild_tz)
        time_until = time1 - now
        if time_until.total_seconds() > 0:
            countdown = _("⏳ Starts <t:{timestamp}:R>").format(timestamp=int(time1.timestamp()))
            embed.add_field(name=_("Countdown"), value=countdown, inline=True)

        # Repeat information
        repeat_emoji = {
            'none': '🚫', 'daily': '📆', 'weekly': '🗓️', 'monthly': '📅', 'yearly': '🎊'
        }
        repeat_value = f"{repeat_emoji.get(event['repeat'], '🔄')} {event['repeat'].capitalize()}"
        embed.add_field(name=_("Repeat"), value=repeat_value, inline=True)

        # Channel information
        channel = guild.get_channel(event['channel'])
        channel_value = f"📢 {channel.mention}" if channel else _("Channel not found")
        embed.add_field(name=_("Channel"), value=channel_value, inline=True)

        # Role information
        role = guild.get_role(event['role_id'])
        role_value = f"👥 {role.mention}" if role else _("No specific role")
        embed.add_field(name=_("Event Role"), value=role_value, inline=True)

        # Notifications
        if event['notifications']:
            notif_value = ", ".join(f"{n}m" for n in sorted(event['notifications']))
            embed.add_field(name=_("🔔 Reminders"), value=notif_value, inline=True)

        # Participants count (if role exists)
        if role:
            participant_count = len(role.members)
            embed.add_field(name=_("👥 Participants"), value=f"{participant_count} joined", inline=True)

        # Footer with event ID
        embed.set_footer(text=_("Event ID: {event_id}").format(event_id=event_id))

        return embed

    async def set_personal_reminder(self, guild_id: int, user_id: int, event_id: str, reminder_time: datetime):
        async with self.config.member_from_ids(guild_id, user_id).personal_reminders() as reminders:
            reminders[event_id] = reminder_time.isoformat()
        await self.schedule_personal_reminder(guild_id, user_id, event_id, reminder_time)

    @commands.guild_only()
    @commands.command(name="eventedit")
    @commands.has_permissions(manage_events=True)
    async def event_edit(self, ctx, *, event_name: str):
        """
        Edit an existing event using an interactive modal.

        This command will open an interactive form for editing an event.
        You must have the Manage Events permission to use this command.
        """
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.").format(event_name=event_name)))
        else:
            event = self.guild_events[ctx.guild.id][event_id]
            view = EventEditView(self, ctx.guild, event_name, event)
            await ctx.send(embed=self.success_embed(_("Click the button below to edit the event '{event_name}'.").format(event_name=event_name)), view=view)

    @commands.guild_only()
    @commands.command(name="eventcancel")
    @commands.has_permissions(manage_events=True)
    async def event_cancel(self, ctx, *, event_name: str):
        """
        Cancel an event and notify all participants.

        This command will cancel an event and notify all participants.
        You must have the Manage Events permission to use this command.
        """
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed=self.error_embed(_("No event found with the name '{event_name}'.").format(event_name=event_name)))

    async def cancel_event(self, guild: discord.Guild, event_id: str):
        try:
            event = self.guild_events[guild.id].get(event_id)
            if not event:
                return

            await self.delete_event(guild, event_id)

            channel = guild.get_channel(event['channel'])
            if channel:
                await channel.send(_("The event '{event_name}' has been cancelled.").format(event_name=event['name']))

        except Exception as e:
            self.logger.error(f"Error cancelling event {event_id}: {e}")

    def error_embed(self, message: str) -> discord.Embed:
        return discord.Embed(title=_("❌ Error"), description=message, color=discord.Color.red())

    def success_embed(self, message: str) -> discord.Embed:
        return discord.Embed(title=_("✅ Success"), description=message, color=discord.Color.green())

    @commands.command(name="eventhelp", aliases=["event"])
    async def event_help(self, ctx):
        """
        Display a list of all available event-related commands.

        This command shows a list of all commands for managing and participating in events.
        """
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

    @tasks.loop(hours=1)
    async def sync_event_cache(self):
        for guild in self.bot.guilds:
            events = await self.config.guild(guild).events()
            self.guild_events[guild.id] = events

    @commands.guild_only()
    @commands.command(name="eventpurge")
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

    async def get_guild_timezone(self, guild: discord.Guild) -> pytz.timezone:
        if guild.id not in self.guild_timezone_cache:
            timezone_str = await self.config.guild(guild).timezone()
            self.guild_timezone_cache[guild.id] = pytz.timezone(timezone_str)
        return self.guild_timezone_cache[guild.id]

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

    async def initialize_event_info_messages(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            self.event_info_messages[guild.id] = await self.config.guild(guild).event_info_messages()

    async def remove_event_info_message(self, guild_id: int, event_id: str):
        if guild_id in self.event_info_messages and event_id in self.event_info_messages[guild_id]:
            del self.event_info_messages[guild_id][event_id]
            await self.config.guild_from_id(guild_id).event_info_messages.set(self.event_info_messages[guild_id])

    @tasks.loop(hours=24)
    async def cleanup_event_info_messages(self):
        for guild in self.bot.guilds:
            for event_id in list(self.event_info_messages.get(guild.id, {}).keys()):
                if event_id not in self.guild_events[guild.id]:
                    await self.remove_event_info_message(guild.id, event_id)

class ReminderSelectView(discord.ui.View):
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
        await interaction.response.send_message(embed=self.cog.success_embed(_("I'll remind you about '{event_id}' {minutes} minutes before it starts.").format(event_id=self.event_id, minutes=minutes)), ephemeral=True)

class ReminderSelect(discord.ui.Select):
    def __init__(self, callback):
        options = [
            discord.SelectOption(label=_("5 minutes"), value="5", emoji="⏱️"),
            discord.SelectOption(label=_("15 minutes"), value="15", emoji="⏱️"),
            discord.SelectOption(label=_("30 minutes"), value="30", emoji="⏱️"),
            discord.SelectOption(label=_("1 hour"), value="60", emoji="⏰"),
            discord.SelectOption(label=_("2 hours"), value="120", emoji="⏰"),
        ]
        super().__init__(placeholder=_("Select reminder time"), options=options)
        self.callback_function = callback

    async def callback(self, interaction: discord.Interaction):
        await self.callback_function(interaction, int(self.values[0]))

class ConfirmPurgeView(discord.ui.View):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    @discord.ui.button(label=_("Confirm Purge"), style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.purge_all_data()
        embed = discord.Embed(
            title=_("✅ Data Purged"),
            description=_("All event data has been purged successfully."),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label=_("Cancel"), style=discord.ButtonStyle.secondary, emoji="🚫")
    async def cancel_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title=_("❌ Purge Cancelled"),
            description=_("The purge operation has been cancelled. No data was deleted."),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

class BasicEventEditModal(discord.ui.Modal, title=_("Edit Event - Basic Info")):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data
        self.timezone = pytz.timezone(self.cog.config.guild(guild).timezone())

        self.name = TextInput(label=_("Event Name"), default=event_name, max_length=100)
        self.datetime1 = TextInput(label=_("First Time (HH:MM)"), default=datetime.fromisoformat(event_data['time1']).astimezone(self.timezone).strftime("%H:%M"))
        self.datetime2 = TextInput(label=_("Second Time (Optional, HH:MM)"), default=datetime.fromisoformat(event_data['time2']).astimezone(self.timezone).strftime("%H:%M") if event_data.get('time2') else "", required=False)
        self.description = TextInput(label=_("Description"), style=discord.TextStyle.paragraph, max_length=1000, default=event_data['description'])

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

class AdvancedEventEditModal(discord.ui.Modal, title=_("Edit Event - Advanced Options")):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

        self.notifications = TextInput(label=_("Notification Times (minutes)"), default=",".join(map(str, event_data['notifications'])))
        self.repeat = TextInput(label=_("Repeat (none/daily/weekly/monthly/yearly)"), default=event_data['repeat'])
        self.role_name = TextInput(label=_("Event Role Name"), default=event_data['role_name'])
        self.channel = TextInput(label=_("Channel"), default=f"#{self.guild.get_channel(event_data['channel']).name}")

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

        success = await self.cog.update_event(self.guild, self.event_name, new_data)
        if success:
            await interaction.response.send_message(embed=self.cog.success_embed(_("Event '{event_name}' has been updated successfully.").format(event_name=self.event_name)), ephemeral=True)
        else:
            await interaction.response.send_message(embed=self.cog.error_embed(_("Failed to update event '{event_name}'.").format(event_name=self.event_name)), ephemeral=True)

        self.cog.temp_edit_data.pop(interaction.user.id, None)

class EventEditView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    @discord.ui.button(label=_("Edit Event"), style=discord.ButtonStyle.primary, emoji="✏️")
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

    @discord.ui.button(label=_("Edit Advanced Options"), style=discord.ButtonStyle.primary, emoji="⚙️")
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

    @discord.ui.button(label=_("Confirm Cancel"), style=discord.ButtonStyle.danger, emoji="🚫")
    async def confirm_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.cancel_event(self.guild, self.event_name)
        await interaction.response.send_message(embed=self.cog.success_embed(_("The event '{event_name}' has been cancelled and participants have been notified.").format(event_name=self.event_name)))

    @discord.ui.button(label=_("Keep Event"), style=discord.ButtonStyle.secondary, emoji="🔙")
    async def keep_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=self.cog.success_embed(_("The event '{event_name}' has not been cancelled.").format(event_name=self.event_name)))

async def setup(bot: Red):
    await bot.add_cog(RobustEventsCog(bot))
