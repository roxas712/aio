# AIO Game Terminal

All-In-One gaming terminal client for the Blue Steel Kiosk ecosystem.

## Structure

```
client/
├── aio/                  # Main application
│   ├── activation_win.py # Terminal activation & registration
│   ├── single_win.py     # Single-game kiosk mode
│   ├── multi_win.py      # Multi-game selection mode
│   ├── multi_vert_win.py # Multi-game vertical orientation
│   ├── win_common.py     # Shared utilities & configuration
│   ├── updater_win.py    # Auto-update mechanism
│   ├── loading.py        # Loading screen UI
│   ├── loading_vert.py   # Loading screen (vertical)
│   ├── return.py         # Return-to-menu button
│   ├── return_vert.py    # Return button (vertical)
│   ├── img/              # Game logos & UI assets
│   └── vids/             # Video assets
├── installer/            # Windows installer (Inno Setup)
│   ├── installer.iss     # Full installer script
│   ├── update.iss        # Update package script
│   └── agent.py          # Heartbeat agent daemon
└── watchdog.py           # Process monitoring service
```

## Terminal Modes

- **Single Mode** - Launches a single configured game on startup
- **Multi Mode** - Game selection carousel (landscape)
- **Multi Vertical Mode** - Game selection for portrait displays

## Requirements

- Windows 10 LTSC
- Python 3.14
- PyQt5 + QtWebEngine

## Server

The backend API server is maintained separately at [pgoc](https://github.com/roxas712/pgoc).
