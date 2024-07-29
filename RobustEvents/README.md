
# Events Cog

[![Red-DiscordBot](https://img.shields.io/badge/Red--DiscordBot-V3-red.svg)](https://github.com/Cog-Creators/Red-DiscordBot)
[![Discord.py](https://img.shields.io/badge/Discord.py-rewrite-blue.svg)](https://github.com/Rapptz/discord.py/tree/rewrite)
[![License](https://img.shields.io/badge/License-MIT-blue)](https://github.com/DevelopmentCats/CatCogs/blob/main/LICENSE)
[![GitHub Repo stars](https://img.shields.io/github/stars/DevelopmentCats/CatCogs?style=plastic&color=%23696969)](https://github.com/DevelopmentCats/CatCogs/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/DevelopmentCats/CatCogs?style=plastic&color=%23696969)](https://github.com/DevelopmentCats/CatCogs/forks)

## About

The Events Cog is a robust tool designed for the [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot). It allows server administrators to create, manage, and notify users about upcoming events with ease. This cog includes features like event creation, reminders, notifications, and management tools to keep your community informed and engaged.

## Features

- **Create Events:** Easily create new events with a name, date, time, and description.
- **Set Reminders:** Configure reminders to notify users before the event starts.
- **Notifications:** Automatically notify users about upcoming events.
- **Manage Events:** Edit or delete existing events as needed.
- **Role Creation:** Optionally create roles for specific events.

## Installation

To install the Events Cog, follow these steps:

1. Ensure you have the downloader cog loaded.
2. Add the CatCogs repository:
    ```py
    [p]repo add catcogs https://github.com/DevelopmentCats/CatCogs
    ```
3. Install the Events Cog:
    ```py
    [p]cog install catcogs events
    ```
4. Load the Events Cog:
    ```py
    [p]load events
    ```

## Usage

### Creating an Event

Use the following command to create a new event:

```py
[p]event create
```

You will be prompted to enter the event name, date, time, and description.

### Setting a Reminder

Set a reminder for an event with the following command:

```py
[p]event reminder <event_id> <time_before_event>
```

Example:

```py
[p]event reminder 1 1h
```

This sets a reminder for event ID 1, one hour before the event starts.

### Notifying Users

Notify users about an upcoming event with:

```py
[p]event notify <event_id>
```

### Managing Events

To edit an event:

```py
[p]event edit <event_id>
```

To delete an event:

```py
[p]event delete <event_id>
```

### Creating Roles for Events

When creating an event, you can specify if a role should be created for the event. This can be useful for managing permissions and notifications specific to the event.

## Commands

Here is a list of available commands and their descriptions:

- **Event Creation:** `event create` - Create a new event.
- **Set Reminder:** `event reminder <event_id> <time_before_event>` - Set a reminder for an event.
- **Notify Users:** `event notify <event_id>` - Notify users about an upcoming event.
- **Edit Event:** `event edit <event_id>` - Edit an existing event.
- **Delete Event:** `event delete <event_id>` - Delete an existing event.

## Contributing

Feel free to contribute to this project by submitting issues or pull requests. Your feedback and contributions are greatly appreciated!

## Credits

Thank you to everyone in the official [Red server](https://discord.gg/red) for always being supportive and helpful.

---

[GitHub Repository](https://github.com/DevelopmentCats/CatCogs)
