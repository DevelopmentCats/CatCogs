# Welcome to CatCogs

[![Red-DiscordBot](https://img.shields.io/badge/Red--DiscordBot-V3-red.svg)](https://github.com/Cog-Creators/Red-DiscordBot)
[![Discord.py](https://img.shields.io/badge/Discord.py-rewrite-blue.svg)](https://github.com/Rapptz/discord.py/tree/rewrite)
[![License](https://img.shields.io/badge/License-MIT-blue)](https://github.com/DevelopmentCats/CatCogs/blob/main/LICENSE)
[![GitHub Repo stars](https://img.shields.io/github/stars/DevelopmentCats/CatCogs?style=plastic&color=%23696969)](https://github.com/DevelopmentCats/CatCogs/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/DevelopmentCats/CatCogs?style=plastic&color=%23696969)](https://github.com/DevelopmentCats/CatCogs/forks)

## About

Welcome to CatCogs, a collection of custom cogs for the [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot/). These cogs are designed to add new features and enhance your Discord server experience.

## Installation

> Ensure you have the downloader cog loaded.

```py
[p]load downloader
[p]repo add catcogs https://github.com/DevelopmentCats/CatCogs
[p]cog install catcogs RobustEvents
[p]load RobustEvents
```

## Available Cogs

Currently, the following cog is available in this repository:

### RobustEvents

**Version:** 1.0.0

**Description:** Schedule and manage events in your Discord server with ease. Create events, set reminders, and notify users about upcoming activities.

#### Features:
- **Create New Events:** Use a modal to enter event details including name, date, time, description, notifications, repeat options, role name, and channel.
- **List Events:** Display a list of all scheduled events with their details.
- **Edit Events:** Update existing events using a modal with new details.
- **Delete Events:** Remove events from the schedule.
- **Cancel Events:** Cancel events and notify participants.
- **Set Reminders:** Users can set personal reminders for events.
- **Notification System:** Automatic notifications for upcoming events.
- **Repeating Events:** Support for daily, weekly, and monthly repeating events.
- **Time Zone Support:** Events respect the server's set time zone.
- **Role Management:** Automatically create and manage roles for event participants.

#### Usage:

- **Create Event:**
  ```py
  [p]eventcreate
  ```
  Opens a modal to input basic event information and advanced options.

- **List Events:**
  ```py
  [p]eventlist
  ```
  Displays all scheduled events in the server.

- **Edit Event:**
  ```py
  [p]eventedit <event_name>
  ```
  Opens a modal to edit the details of the specified event.

- **Delete Event:**
  ```py
  [p]eventdelete <event_name>
  ```
  Deletes the specified event from the schedule.

- **Cancel Event:**
  ```py
  [p]eventcancel <event_name>
  ```
  Cancels the specified event and notifies participants.

- **Set Reminder:**
  ```py
  [p]eventremind <event_name>
  ```
  Opens a view for the user to set a personal reminder for the specified event.

- **Set Time Zone:**
  ```py
  [p]settimezone <timezone>
  ```
  Sets the server's time zone for scheduling events.

For detailed documentation and command usage, refer to the [Events Cog Documentation](https://github.com/DevelopmentCats/CatCogs/wiki/RobustEvents-Cog).

## Credits

Thank you to everyone in the official [Red server](https://discord.gg/red) for always being nice and helpful.

---

Feel free to contribute to this repository by submitting issues or pull requests. Your feedback and contributions are greatly appreciated!

---

[GitHub Repository](https://github.com/DevelopmentCats/CatCogs)
