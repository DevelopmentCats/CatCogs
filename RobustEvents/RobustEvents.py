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
from redbot.core import Config, Commands
from redbot.core.bot import Red

class RepeatType(Enum):
    NONE = 'none'
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    YEARLY = 'yearly'

class BasicEventModal(Modal):
    def __init__(self, cog, guild: discord.Guild, original_message: discord.Message):
        super().__init__(title="Create New Event - Basic Info")
        self.cog = cog
        self.guild = guild
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
        await interaction.response.send_message("Basic information saved. Click the button below to set advanced options:", view=view, ephemeral=True)

class AdvancedEventModal(Modal):
    def __init__(self, cog, guild: discord.Guild, original_message: discord.Message):
        super().__init__(title="Create New Event - Advanced Options")
        self.cog = cog
        self.guild = guild
        self.original_message = original_message

        self.notifications = TextInput(label="Notification Times (minutes)", placeholder="10,30,60")
        self.repeat = TextInput(label="Repeat (none/daily/weekly/monthly/yearly)", placeholder="none")
        self.role_name = TextInput(label="Event Role Name", placeholder="Event Attendees")
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
        if repeat not in RepeatType._value2member_map_:
            await interaction.response.send_message(embed=self.cog.error_embed("Invalid repeat option."), ephemeral=True)
            return

        role_name = self.role_name.value.strip()
        if not role_name:
            await interaction.response.send_message(embed=self.cog.error_embed("Event role name is required."), ephemeral=True)
            return

        channel_name = self.channel.value.lstrip('#')
        channel = discord.utils.get(self.guild.text_channels, name=channel_name)
        if not channel:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Channel #{channel_name} not found."), ephemeral=True)
            return

        basic_data = self.cog.temp_event_data.pop(interaction.user.id, None)
        if not basic_data:
            await interaction.response.send_message(embed=self.cog.error_embed("Error: Event data not found."), ephemeral=True)
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

        await interaction.response.send_message(embed=self.cog.success_embed(f"Event created successfully! Event ID: {event_id}"), ephemeral=True)

        await self.original_message.delete()

class AdvancedOptionsView(View):
    def __init__(self, cog, original_message: discord.Message):
        super().__init__()
        self.cog = cog
        self.original_message = original_message

    @discord.ui.button(label="Set Advanced Options", style=discord.ButtonStyle.primary)
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

    @discord.ui.button(label="Create Event", style=discord.ButtonStyle.primary, emoji="➕")
    async def create_event_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        basic_modal = BasicEventModal(self.cog, self.guild, self.message)
        await interaction.response.send_modal(basic_modal)

class EventInfoView(discord.ui.View):
    def __init__(self, cog, event_name: str, role_id: int):
        super().__init__(timeout=None)
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
        self.logger = logging.getLogger('red.RobustEvents')
        self.bot.loop.create_task(self.initialize_events())
        self.cleanup_expired_events.start()
        self.sync_event_cache.start()
        self.guild_timezone_cache = {}
        self.guild_events = defaultdict(dict)
        self.temp_event_data = defaultdict(dict)

    def cog_unload(self):
        self.cleanup_expired_events.cancel()
        self.sync_event_cache.cancel()
        for task in self.event_tasks.values():
            task.cancel()
        for task in self.personal_reminder_tasks.values():
            task.cancel()

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
                title=f"🔔 Event Reminder: {event['name']}",
                description=f"{role_mention}\n\nThe event '{event['name']}' is starting in {notification_time} minutes!",
                color=discord.Color.blue()
            )
            embed.add_field(name="Description", value=event['description'], inline=False)
            embed.add_field(name="Start Time", value=f"<t:{int(event_time.astimezone(guild_tz).timestamp())}:F>", inline=False)
            embed.set_footer(text="This message will be automatically deleted in 30 minutes.")
            
            message = await channel.send(embed=embed)
            
            self.bot.loop.create_task(self.delete_message_after(message, delay=1800))

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
                title=f"🎉 Event Starting Now: {event['name']}",
                description=f"{role_mention}\n\nThe event '{event['name']}' is starting now!",
                color=discord.Color.green()
            )
            embed.add_field(name="Description", value=event['description'], inline=False)
            embed.add_field(name="Start Time", value=f"<t:{int(event_time.astimezone(guild_tz).timestamp())}:F>", inline=False)
            
            await channel.send(embed=embed)

    @commands.command(name="eventcreate")
    @commands.has_permissions(manage_events=True)
    async def event_create(self, ctx):
        view = EventCreationView(self, ctx.guild)
        embed = discord.Embed(title="📅 Create New Event", 
                              description="Click the button below to start creating a new event.", 
                              color=discord.Color.blue())
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @commands.command(name="eventlist")
    async def event_list(self, ctx):
        guild_tz = await self.get_guild_timezone(ctx.guild)
        events = await self.config.guild(ctx.guild).events()
        if not events:
            await ctx.send(embed=self.error_embed("No events scheduled."))
            return
        
        embed = discord.Embed(title="📅 Scheduled Events", color=discord.Color.blue())
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

    @commands.command(name="eventdelete")
    @commands.has_permissions(manage_events=True)
    async def event_delete(self, ctx, *, event_name: str):
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if event_id:
            success = await self.delete_event(ctx.guild, event_id)
            if success:
                await ctx.send(embed=self.success_embed(f"Event '{event_name}' deleted."))
            else:
                await ctx.send(embed=self.error_embed(f"Failed to delete event '{event_name}'."))

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
                    self.logger.error(f"Couldn't delete the event role for '{event['name']}' due to lack of permissions.")

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

        return True

    @commands.command(name="eventupdate")
    @commands.has_permissions(manage_events=True)
    async def event_update(self, ctx, *, event_name: str):
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed(self.error_embed(f"No event found with the name '{event_name}'.")))

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
            self.logger.error(f"Bot doesn't have permission to create roles in guild {guild.name}")
            return None

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
            await ctx.send(embed=self.success_embed(f"Timezone set to {timezone_str}"))
        except pytz.exceptions.UnknownTimeZoneError:
            await ctx.send(embed(self.error_embed(f"Unknown timezone: {timezone_str}. Please use a valid timezone from the IANA Time Zone Database.")))

    @commands.command(name="eventinfo")
    async def event_info(self, ctx, *, event_name: str):
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed(self.error_embed(f"No event found with the name '{event_name}'.")))

    async def set_personal_reminder(self, guild_id: int, user_id: int, event_id: str, reminder_time: datetime):
        async with self.config.member_from_ids(guild_id, user_id).personal_reminders() as reminders:
            reminders[event_id] = reminder_time.isoformat()
        await self.schedule_personal_reminder(guild_id, user_id, event_id, reminder_time)

    @commands.command(name="eventedit")
    @commands.has_permissions(manage_events=True)
    async def event_edit(self, ctx, *, event_name: str):
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed(self.error_embed(f"No event found with the name '{event_name}'.")))

    @commands.command(name="eventcancel")
    @commands.has_permissions(manage_events=True)
    async def event_cancel(self, ctx, *, event_name: str):
        event_id = await self.get_event_id_from_name(ctx.guild, event_name)
        
        if not event_id:
            await ctx.send(embed(self.error_embed(f"No event found with the name '{event_name}'.")))

    async def cancel_event(self, guild: discord.Guild, event_id: str):
        try:
            event = self.guild_events[guild.id].get(event_id)
            if not event:
                return

            await self.delete_event(guild, event_id)

            channel = guild.get_channel(event['channel'])
            if channel:
                await channel.send(f"The event '{event['name']}' has been cancelled.")

        except Exception as e:
            self.logger.error(f"Error cancelling event {event_id}: {e}")

    def error_embed(self, message: str) -> discord.Embed:
        return discord.Embed(title="❌ Error", description=message, color=discord.Color.red())

    def success_embed(self, message: str) -> discord.Embed:
        return discord.Embed(title="✅ Success", description=message, color=discord.Color.green())

    @commands.command(name="eventhelp", aliases=["event"])
    async def event_help(self, ctx):
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

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        embed.add_field(name="🎫 Event Participation Commands", value="Commands for event participants:", inline=False)
        for command, description in event_commands:
            embed.add_field(name=f"`{prefix}{command}`", value=description, inline=False)

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        embed.add_field(name="ℹ️ Help Command", value=f"For help with specific commands, use `{prefix}help <command>`.", inline=False)
        embed.set_footer(text=f"Current prefix: {prefix}")
        await ctx.send(embed=embed)

    @tasks.loop(hours=1)
    async def sync_event_cache(self):
        for guild in self.bot.guilds:
            events = await self.config.guild(guild).events()
            self.guild_events[guild.id] = events

    @commands.command(name="eventpurge")
    @commands.has_permissions(administrator=True)
    async def event_purge(self, ctx):
        """Purge all event data. Use with caution!"""
        view = ConfirmPurgeView(self)
        embed = discord.Embed(
            title="⚠️ Purge All Event Data",
            description="Are you sure you want to purge all event data? This action cannot be undone!",
            color=discord.Color.red()
        )
        embed.add_field(name="Warning", value="This should only be used when updates to the cog break compatibility with current events.")
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
            await interaction.response.send_message(embed(self.cog.error_embed("This reminder time has already passed.")), ephemeral=True)
            return

        await self.cog.set_personal_reminder(interaction.guild_id, self.user_id, self.event_id, reminder_time)
        await interaction.response.send_message(embed(self.cog.success_embed(f"I'll remind you about '{self.event_id}' {minutes} minutes before it starts.")), ephemeral=True)

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

class ConfirmPurgeView(discord.ui.View):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    @discord.ui.button(label="Confirm Purge", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.purge_all_data()
        embed = discord.Embed(
            title="✅ Data Purged",
            description="All event data has been purged successfully.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="🚫")
    async def cancel_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="❌ Purge Cancelled",
            description="The purge operation has been cancelled. No data was deleted.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

class BasicEventEditModal(discord.ui.Modal, title="Edit Event - Basic Info"):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data
        self.timezone = pytz.timezone(self.cog.config.guild(guild).timezone())

        self.name = TextInput(label="Event Name", default=event_name, max_length=100)
        self.datetime1 = TextInput(label="First Time (HH:MM)", default=datetime.fromisoformat(event_data['time1']).astimezone(self.timezone).strftime("%H:%M"))
        self.datetime2 = TextInput(label="Second Time (Optional, HH:MM)", default=datetime.fromisoformat(event_data['time2']).astimezone(self.timezone).strftime("%H:%M") if event_data.get('time2') else "", required=False)
        self.description = TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=1000, default=event_data['description'])

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
            await interaction.response.send_message(embed(self.cog.error_embed(str(e))), ephemeral=True)
            return

        self.cog.temp_edit_data[interaction.user.id] = {
            'name': self.name.value,
            'time1': event_time1.isoformat(),
            'time2': event_time2.isoformat() if event_time2 else None,
            'description': self.description.value,
        }

        view = AdvancedEditOptionsView(self.cog, self.guild, self.event_name, self.event_data)
        await interaction.response.send_message("Basic information updated. Click the button below to edit advanced options:", view=view, ephemeral=True)

class AdvancedEventEditModal(discord.ui.Modal, title="Edit Event - Advanced Options"):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

        self.notifications = TextInput(label="Notification Times (minutes)", default=",".join(map(str, event_data['notifications'])))
        self.repeat = TextInput(label="Repeat (none/daily/weekly/monthly/yearly)", default=event_data['repeat'])
        self.role_name = TextInput(label="Event Role Name", default=event_data['role_name'])
        self.channel = TextInput(label="Channel", default=f"#{self.guild.get_channel(event_data['channel']).name}")

        self.add_item(self.notifications)
        self.add_item(self.repeat)
        self.add_item(self.role_name)
        self.add_item(self.channel)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            notifications = [int(n.strip()) for n in self.notifications.value.split(',')]
        except ValueError:
            await interaction.response.send_message(embed(self.cog.error_embed("Invalid notification times.")), ephemeral=True)
            return

        repeat = self.repeat.value.lower()
        if repeat not in RepeatType._value2member_map_:
            await interaction.response.send_message(embed(self.cog.error_embed("Invalid repeat option.")), ephemeral=True)
            return

        role_name = self.role_name.value.strip()
        if not role_name:
            await interaction.response.send_message(embed(self.cog.error_embed("Event role name is required.")), ephemeral=True)
            return

        channel_name = self.channel.value.lstrip('#')
        channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
        if not channel:
            await interaction.response.send_message(embed(self.cog.error_embed(f"Channel #{channel_name} not found.")), ephemeral=True)
            return

        basic_data = self.cog.temp_edit_data.pop(interaction.user.id, None)
        if not basic_data:
            await interaction.response.send_message(embed(self.cog.error_embed("Error: Event data not found.")), ephemeral=True)
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
            await interaction.response.send_message(embed(self.cog.success_embed(f"Event '{self.event_name}' has been updated successfully.")), ephemeral=True)
        else:
            await interaction.response.send_message(embed(self.cog.error_embed(f"Failed to update event '{self.event_name}'.")), ephemeral=True)

        self.cog.temp_edit_data.pop(interaction.user.id, None)

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
        await interaction.response.send_message(embed(self.cog.success_embed(f"The event '{self.event_name}' has been cancelled and participants have been notified.")))

    @discord.ui.button(label="Keep Event", style=discord.ButtonStyle.secondary, emoji="🔙")
    async def keep_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed(self.cog.success_embed(f"The event '{self.event_name}' has not been cancelled.")))

async def setup(bot: Red):
    await bot.add_cog(RobustEventsCog(bot))
