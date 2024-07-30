import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Select
from redbot.core import Config, commands
from redbot.core.bot import Red
from datetime import datetime, timedelta
import pytz
from typing import Optional, List
import asyncio
from collections import defaultdict
import logging
from discord.ext import tasks
import humanize

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
            time1 = datetime.strptime(self.datetime1.value, "%H:%M").time()
            event_time1 = self.timezone.localize(datetime.combine(now.date(), time1)).astimezone(pytz.UTC)
            if event_time1 <= now:
                event_time1 += timedelta(days=1)

            if self.datetime2.value:
                time2 = datetime.strptime(self.datetime2.value, "%H:%M").time()
                event_time2 = self.timezone.localize(datetime.combine(now.date(), time2)).astimezone(pytz.UTC)
                if event_time2 <= now:
                    event_time2 += timedelta(days=1)
            else:
                event_time2 = None

        except ValueError as e:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Invalid time format: {e}"), ephemeral=True)
            return

        # Check for existing events
        async with self.cog.config.guild(interaction.guild).events() as events:
            if self.name.value in events:
                await interaction.response.send_message(embed=self.cog.error_embed("An event with this name already exists."), ephemeral=True)
                return

        # Update this part to use the new create_event method
        await self.cog.create_event(
            interaction.guild,
            self.name.value,
            event_time1,
            self.description.value,
            [],  # Empty notifications list, will be filled in AdvancedEventModal
            "none",  # Default repeat value
            None,  # Role name will be set in AdvancedEventModal
            None,  # Channel will be set in AdvancedEventModal
            event_time2
        )

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
        self.repeat = TextInput(label="Repeat (none/daily/weekly/monthly)", placeholder="none")
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
        if repeat not in ['none', 'daily', 'weekly', 'monthly']:
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

        # Check for existing events
        async with self.cog.config.guild(interaction.guild).events() as events:
            if self.cog.temp_event_data['basic']['name'] in events:
                await interaction.response.send_message(embed=self.cog.error_embed("An event with this name already exists."), ephemeral=True)
                return

        # Update the event with advanced options
        event_name = self.cog.temp_event_data['basic']['name']
        await self.cog.update_event(interaction.guild, event_name, {
            "notifications": notifications,
            "repeat": repeat,
            "role_name": role_name,
            "channel": channel.id
        })

        await interaction.response.send_message(embed=self.cog.success_embed("Event created successfully!"), ephemeral=True)

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
        self.event_tasks = {}
        self.personal_reminder_tasks = {}
        self.temp_event_data = None
        self.event_cache = defaultdict(dict)
        self.logger = logging.getLogger('red.RobustEvents')
        self.bot.loop.create_task(self.initialize_events())
        self.cleanup_expired_events.start()
        self.bot.add_view(EventInfoView(self, "", 0))  # Add this line

    def cog_unload(self):
        self.cleanup_expired_events.cancel()

    @tasks.loop(hours=24)
    async def cleanup_expired_events(self):
        """Automatically clean up expired non-repeating events."""
        for guild in self.bot.guilds:
            async with self.config.guild(guild).events() as events:
                current_time = datetime.now(pytz.UTC)
                to_remove = []
                for name, event in events.items():
                    event_time = datetime.fromisoformat(event['time1'])
                    if event['repeat'] == 'none' and event_time < current_time:
                        to_remove.append(name)
                for name in to_remove:
                    del events[name]
                    if name in self.event_tasks:
                        self.event_tasks[name].cancel()
                        del self.event_tasks[name]

    async def initialize_events(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self.load_guild_events(guild)
        await self.load_personal_reminders()

    async def load_guild_events(self, guild: discord.Guild):
        events = await self.config.guild(guild).events()
        for name, event in events.items():
            self.event_cache[guild.id][name] = event
            await self.schedule_event(guild, name, datetime.fromisoformat(event['time1']))

    async def load_personal_reminders(self):
        for guild in self.bot.guilds:
            async for member_id, member_data in self.config.all_members(guild):
                for event_name, reminder_time in member_data.get('personal_reminders', {}).items():
                    await self.schedule_personal_reminder(guild.id, member_id, event_name, datetime.fromisoformat(reminder_time))

    async def schedule_event(self, guild: discord.Guild, name: str, event_time: datetime):
        if name in self.event_tasks:
            self.event_tasks[name].cancel()
        self.event_tasks[name] = self.bot.loop.create_task(self.event_loop(guild, name, event_time))

    async def schedule_personal_reminder(self, guild_id: int, user_id: int, event_name: str, reminder_time: datetime):
        task_key = f"{guild_id}:{user_id}:{event_name}"
        if task_key in self.personal_reminder_tasks:
            self.personal_reminder_tasks[task_key].cancel()
        self.personal_reminder_tasks[task_key] = self.bot.loop.create_task(self.personal_reminder_loop(guild_id, user_id, event_name, reminder_time))

    async def event_loop(self, guild: discord.Guild, name: str, event_time: datetime):
        while True:
            try:
                event = self.event_cache[guild.id].get(name)
                if not event:
                    return

                now = datetime.now(pytz.UTC)
                time1 = datetime.fromisoformat(event['time1'])
                time2 = datetime.fromisoformat(event['time2']) if event.get('time2') else None

                # Determine the next occurrence
                if time2:
                    next_time = min(time1, time2) if min(time1, time2) > now else max(time1, time2)
                    if next_time <= now:
                        next_time += timedelta(days=1)
                else:
                    next_time = time1 if time1 > now else time1 + timedelta(days=1)

                time_until_event = next_time - now

                for notification_time in event['notifications']:
                    notification_delta = timedelta(minutes=notification_time)
                    if time_until_event > notification_delta:
                        await asyncio.sleep((time_until_event - notification_delta).total_seconds())
                        await self.send_notification(guild, name, notification_time)

                await discord.utils.sleep_until(next_time)
                await self.send_event_start_message(guild, name)

                # Update times for the next occurrence
                event['time1'] = (time1 + timedelta(days=1)).isoformat()
                if time2:
                    event['time2'] = (time2 + timedelta(days=1)).isoformat()
                await self.config.guild(guild).events.set_raw(name, value=event)
                self.event_cache[guild.id][name] = event

            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error(f"Error in event loop for {name}: {e}")
                await asyncio.sleep(60)

    async def personal_reminder_loop(self, guild_id: int, user_id: int, event_name: str, reminder_time: datetime):
        try:
            await discord.utils.sleep_until(reminder_time)
            guild = self.bot.get_guild(guild_id)
            user = guild.get_member(user_id) if guild else None
            if user:
                event = self.event_cache[guild_id].get(event_name)
                if event:
                    event_time = datetime.fromisoformat(event['time1'])
                    time_until_event = event_time - datetime.now(pytz.UTC)
                    minutes_until_event = int(time_until_event.total_seconds() / 60)
                    await user.send(f"Reminder: The event '{event_name}' is starting in {minutes_until_event} minutes!")
                else:
                    await user.send(f"Reminder: You had a reminder set for the event '{event_name}', but it seems the event no longer exists.")
            
            # Remove the personal reminder from the config
            async with self.config.member_from_ids(guild_id, user_id).personal_reminders() as reminders:
                reminders.pop(event_name, None)
        except asyncio.CancelledError:
            return
        except Exception as e:
            self.logger.error(f"Error in personal reminder loop for user {user_id}, event {event_name}: {e}")

    async def send_notification(self, guild: discord.Guild, event_name: str, notification_time: int):
        """Send a notification for the event."""
        event = self.event_cache[guild.id].get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            await channel.send(f"Reminder: The event '{event_name}' is starting in {notification_time} minutes!")

    async def send_event_start_message(self, guild: discord.Guild, event_name: str):
        """Send a message when the event starts."""
        event = self.event_cache[guild.id].get(event_name)
        if not event:
            return

        channel = guild.get_channel(event['channel'])
        if channel:
            await channel.send(f"The event '{event_name}' is starting now!\n{event['description']}")

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
    async def event_delete(self, ctx, name: Optional[str] = None):
        """Delete an event.

        Usage: [p]eventdelete <name>
        """
        if not name:
            await ctx.send("Usage: `[p]eventdelete <name>`")
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

    @commands.command(name="eventupdate")
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
            if name in self.event_tasks:
                self.event_tasks[name].cancel()
                del self.event_tasks[name]
            self.schedule_event(ctx.guild, name, datetime.fromisoformat(events[name]['time1']))

    async def create_event(self, guild: discord.Guild, name: str, event_time1: datetime, description: str, notifications: List[int], repeat: str, role_name: Optional[str], channel: Optional[discord.TextChannel], event_time2: Optional[datetime] = None):
        """Create an event and store it."""
        try:
            event_role = await self.create_or_get_event_role(guild, role_name) if role_name else None

            event_data = {
                "time1": event_time1.isoformat(),
                "description": description,
                "notifications": notifications,
                "repeat": repeat,
                "role_name": role_name,
                "role_id": event_role.id if event_role else None,
                "channel": channel.id if channel else None,
                "time2": event_time2.isoformat() if event_time2 else None
            }

            await self.config.guild(guild).events.set_raw(name, value=event_data)
            self.event_cache[guild.id][name] = event_data
            await self.schedule_event(guild, name, event_time1)
            if event_time2:
                await self.schedule_event(guild, name, event_time2)
        except Exception as e:
            self.logger.error(f"Error creating event: {e}")
            raise

    async def update_event(self, guild: discord.Guild, event_name: str, new_data: dict):
        """Update an existing event with new data."""
        try:
            async with self.config.guild(guild).events() as events:
                if event_name not in events:
                    return False

                events[event_name].update(new_data)
                self.event_cache[guild.id][event_name].update(new_data)

            # Reschedule the event
            await self.schedule_event(guild, event_name, datetime.fromisoformat(new_data.get('time1', events[event_name]['time1'])))
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

    async def delete_event(self, guild: discord.Guild, name: str):
        await self.config.guild(guild).events.clear_raw(name)
        del self.event_cache[guild.id][name]

    @commands.command(name="settimezone")
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
            await self.config.guild(guild).events.clear_raw(event_name)
            del self.event_cache[guild.id][event_name]

            if event_name in self.event_tasks:
                self.event_tasks[event_name].cancel()
                del self.event_tasks[event_name]

            # Notify participants
            channel = guild.get_channel(event['channel'])
            if channel:
                await channel.send(f"The event '{event_name}' has been cancelled.")

            # Delete the event role if it exists
            if event['role_id']:
                role = guild.get_role(event['role_id'])
                if role:
                    try:
                        await role.delete()
                    except discord.Forbidden:
                        self.logger.error(f"Couldn't delete the event role for '{event_name}' due to lack of permissions.")
        except Exception as e:
            self.logger.error(f"Error cancelling event {event_name}: {e}")

    def error_embed(self, message: str) -> discord.Embed:
        """Create an error embed."""
        return discord.Embed(title="❌ Error", description=message, color=discord.Color.red())

    def success_embed(self, message: str) -> discord.Embed:
        """Create a success embed."""
        return discord.Embed(title="✅ Success", description=message, color=discord.Color.green())

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
        self.callback = callback

    async def callback(self, interaction: discord.Interaction):
        await self.callback(interaction, int(self.values[0]))

class EventEditView(discord.ui.View):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_event_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EventEditModal(self.cog, self.guild, self.event_name, self.event_data)
        await interaction.response.send_modal(modal)

class EventEditModal(discord.ui.Modal):
    def __init__(self, cog, guild: discord.Guild, event_name: str, event_data: dict):
        super().__init__(title=f"Edit Event: {event_name}")
        self.cog = cog
        self.guild = guild
        self.event_name = event_name
        self.event_data = event_data

        self.add_item(discord.ui.InputText(label="New Event Name", placeholder="Leave blank to keep current name", required=False))
        self.add_item(discord.ui.InputText(label="New Date and Time (YYYY-MM-DD HH:MM)", placeholder="Leave blank to keep current time", required=False))
        self.add_item(discord.ui.InputText(label="New Description", style=discord.InputTextStyle.long, placeholder="Leave blank to keep current description", required=False))
        self.add_item(discord.ui.InputText(label="New Notification Times (minutes)", placeholder="e.g., 10,30,60", required=False))

    async def callback(self, interaction: discord.Interaction):
        new_data = {}
        if self.children[0].value:
            new_data['name'] = self.children[0].value
        if self.children[1].value:
            try:
                new_time = datetime.strptime(self.children[1].value, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.UTC)
                new_data['time1'] = new_time.isoformat()
            except ValueError:
                await interaction.response.send_message("Invalid date format. Please use YYYY-MM-DD HH:MM", ephemeral=True)
                return
        if self.children[2].value:
            new_data['description'] = self.children[2].value
        if self.children[3].value:
            try:
                new_notifications = [int(n.strip()) for n in self.children[3].value.split(',')]
                new_data['notifications'] = new_notifications
            except ValueError:
                await interaction.response.send_message("Invalid notification format. Please use comma-separated numbers.", ephemeral=True)
                return

        success = await self.cog.update_event(self.guild, self.event_name, new_data)
        if success:
            await interaction.response.send_message(embed=self.cog.success_embed(f"Event '{self.event_name}' has been updated successfully."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=self.cog.error_embed(f"Failed to update event '{self.event_name}'."), ephemeral=True)

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
