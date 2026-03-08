#win_common.py

from __future__ import annotations

import json
import os
import socket
import datetime
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    import winreg  # type: ignore[attr-defined]
except Exception:
    winreg = None  # On non-Windows or when winreg is not available

AIO_ROOT = Path(r"C:\Program Files\aio")  # Code + static assets

# Writable data lives under ProgramData\aio
PROGRAMDATA_ROOT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio"
CONFIG_DIR = PROGRAMDATA_ROOT / "config"
LOGS_DIR = PROGRAMDATA_ROOT / "logs"
GAMES_DIR = PROGRAMDATA_ROOT / "games"
KIOSK_DIR = AIO_ROOT / "kiosk"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
GAMES_DIR.mkdir(parents=True, exist_ok=True)
KIOSK_DIR.mkdir(parents=True, exist_ok=True)

# Agent/client config is still in Program Files\aio\config so the agent can write/read it
CLIENT_CONFIG_FILE = (AIO_ROOT / "config" / "client.json")  # agent/client config (uuid, server_url, etc.)

# Kiosk-specific config/logs live under ProgramData\aio
KIOSK_CONFIG_FILE = CONFIG_DIR / "kiosk.json"              # future kiosk-specific config
ACTIVITY_LOG_FILE = LOGS_DIR / "kiosk_activity.json"       # local click log
GAMES_FILE = CONFIG_DIR / "games.json"                     # per-terminal game list for multi mode
VERSION_FILE = CONFIG_DIR / "version.json"                 # app version metadata for Windows client
ACTIVATION_FILE = CONFIG_DIR / "activation.json"           # activation info for this terminal


def get_registry_machine_id() -> str:
    """
    Try to read a persistent MachineId from the Windows registry.

    Looks for:
    - HKLM\SOFTWARE\PGOC\AIO\MachineId
    - HKCU\SOFTWARE\PGOC\AIO\MachineId

    Returns the first non-empty value found, or an empty string if not available.
    """
    if winreg is None:
        return ""

    key_path = r"SOFTWARE\PGOC\AIO"
    value_name = "MachineId"

    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, key_path) as hkey:
                value, _ = winreg.QueryValueEx(hkey, value_name)
                if value:
                    return str(value)
        except OSError:
            continue

    return ""


# ------------------------------
# Server info
# ------------------------------

def load_client_config() -> Dict[str, Any]:
    """Load client.json written/used by the AIO agent."""
    if not CLIENT_CONFIG_FILE.exists():
        return {}
    try:
        with CLIENT_CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_server_base_url() -> str:
    cfg = load_client_config()
    # We now use https://pgoc.ai as the canonical base (agent does this too)
    return cfg.get("server_url", "https://pgoc.ai").rstrip("/")


def get_client_uuid() -> str:
    """
    Resolve a stable Windows client UUID / hardware ID for display and reporting.

    Preference order:
    1. Registry MachineId from SOFTWARE\PGOC\AIO\MachineId
    2. PROGRAMFILES\aio\config\client.json["uuid"]
    3. PROGRAMDATA\aio\config\activation.json["hardware_id"] or ["uuid"] or ["terminal_uuid"]
    4. Fallback constant "unknown-win-client"
    """
    # 1) Try registry MachineId (written by activation_win / agent)
    reg_id = get_registry_machine_id()
    if reg_id:
        return reg_id

    # 2) Try client.json (written/used by agent) in Program Files\aio\config
    try:
        if CLIENT_CONFIG_FILE.exists():
            with CLIENT_CONFIG_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            uid = data.get("uuid")
            if uid:
                return str(uid)
    except Exception:
        pass

    # 3) Try activation.json (written by activation_win)
    try:
        if ACTIVATION_FILE.exists():
            with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
                act = json.load(f)
            for key in ("hardware_id", "uuid", "terminal_uuid"):
                val = act.get(key)
                if val:
                    return str(val)
    except Exception:
        pass

    # 4) Fallback
    cfg = load_client_config()
    return cfg.get("uuid") or "unknown-win-client"


# ------------------------------
# Game list
# ------------------------------

# Default library – you can adjust titles/paths/urls as needed.
# "type": "exe" means launch a native .exe, "url" means open in embedded browser (future) or default browser.
DEFAULT_GAMES: List[Dict[str, Any]] = [
    {
        "title": "100 Plus",
        "type": "url",
        "target": "https://99.100plus.me/",
        "img": str(KIOSK_DIR / "img" / "100plus.png"),
        "orientation": "landscape",
    },
    {
        "title": "AceBook",
        "type": "url",
        "target": "https://www.playacebook.mobi/",
        "img": str(KIOSK_DIR / "img" / "acebook.png"),
        "orientation": "landscape",
    },
    {
        "title": "Big Daddy Dragon",
        "type": "url",
        "target": "https://www.playbdd.com/",
        "img": str(KIOSK_DIR / "img" / "bigdaddydragon.png"),
        "orientation": "landscape",
    },
    {
        "title": "Classic Online",
        "type": "url",
        "target": "https://cgweb.app/games/",
        "img": str(KIOSK_DIR / "img" / "classic.png"),
        "orientation": "landscape",
    },
    {
        "title": "Fire Kirin",
        "type": "url",
        "target": "http://play.firekirin.in/web_mobile/firekirin_pc/",
        "img": str(KIOSK_DIR / "img" / "firekirin.png"),
        "orientation": "landscape",
    },
    {
        "title": "Fire Phoenix",
        "type": "exe",
        "target": r"C:\Program Files (x86)\FirePhoenix\FirePhoenix.exe",
        "img": str(KIOSK_DIR / "img" / "firephoenix.png"),
        "orientation": "landscape",
    },
    {
        "title": "Golden Dragon",
        "type": "url",
        "target": "https://www.goldendragoncity.com/",
        "img": str(KIOSK_DIR / "img" / "goldendragon.png"),
        "orientation": "landscape",
    },
    {
        "title": "Golden Dragon City",
        "type": "exe",
        "target": r"C:\Program Files (x86)\PlayGD\playgd.exe",
        "img": str(KIOSK_DIR / "img" / "goldendragoncity.png"),
        "orientation": "landscape",
    },
    {
        "title": "Great Balls of Fire",
        "type": "url",
        "target": "http://firelinkplus.com",
        "img": str(KIOSK_DIR / "img" / "greatballs.png"),
        "orientation": "vertical",
    },
    {
        "title": "Magic City",
        "type": "url",
        "target": "https://www.magiccity777.com/SSLobby/m4880.0/web-mobile/index.html",
        "img": str(KIOSK_DIR / "img" / "magiccity.png"),
        "orientation": "landscape",
    },
    {
        "title": "Orca",
        "type": "exe",
        "target": r"C:\Program Files (x86)\Orca\Orca.exe",
        "img": str(KIOSK_DIR / "img" / "orca.png"),
        "orientation": "vertical",
    },
    {
        "title": "Orion Stars",
        "type": "url",
        "target": "https://orionstars-vip.com/",
        "img": str(KIOSK_DIR / "img" / "orionstars.png"),
        "orientation": "landscape",
    },
    {
        "title": "Panda Master",
        "type": "url",
        "target": "http://mobile.pandamaster.vip/web_game/pandamaster_pc/",
        "img": str(KIOSK_DIR / "img" / "pandamaster.png"),
        "orientation": "landscape",
    },
    {
        "title": "River Sweeps",
        "type": "url",
        "target": "https://river777.net/",
        "img": str(KIOSK_DIR / "img" / "riversweeps.png"),
        "orientation": "landscape",
    },
    {
        "title": "Tower Link",
        "type": "exe",
        "target": r"C:\TowerLink\bin\launcher.exe",
        "img": str(KIOSK_DIR / "img" / "towerlink.png"),
        "orientation": "landscape",
    },
    {
        "title": "Ultra Panda",
        "type": "url",
        "target": "https://www.ultrapanda.mobi/",
        "img": str(KIOSK_DIR / "img" / "ultrapanda.png"),
        "orientation": "landscape",
    },
    {
        "title": "vBlink",
        "type": "url",
        "target": "https://www.vblink777.club/",
        "img": str(KIOSK_DIR / "img" / "vblink.png"),
        "orientation": "landscape",
    },
]


def get_game_library() -> List[Dict[str, Any]]:
    """Return the canonical full game library (all supported platforms)."""
    return DEFAULT_GAMES


def load_games() -> List[Dict[str, Any]]:
    """ 
    Load the per-terminal enabled game list from ProgramData\aio\config\games.json.

    IMPORTANT:
    - If games.json is missing or empty/invalid, return [] so the kiosk can show
      the "TERMINAL PENDING CONFIGURATION" screen.
    - DEFAULT_GAMES remains the canonical library used for matching titles when
      activation_win applies server selections.
    """
    if not GAMES_FILE.exists():
        return []

    try:
        with GAMES_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
        return []
    except Exception as e:
        print(f"[WARN] Failed to load {GAMES_FILE}: {e}")
        return []


def save_games(games: List[Dict[str, Any]]) -> None:
    try:
        GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with GAMES_FILE.open("w", encoding="utf-8") as f:
            json.dump(games, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to save {GAMES_FILE}: {e}")


# ------------------------------
# IP + click logging
# ------------------------------

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def log_activity_local(game_title: str) -> None:
    evt = {
        "game": game_title,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }
    try:
        if ACTIVITY_LOG_FILE.exists():
            with ACTIVITY_LOG_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        else:
            data = []
    except Exception:
        data = []

    data.append(evt)
    try:
        ACTIVITY_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with ACTIVITY_LOG_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to write {ACTIVITY_LOG_FILE}: {e}")


def send_click_to_server(game_title: str) -> None:
    """
    Click logging to server.

    Uses activation.json from ProgramData to populate activation_key and terminal,
    and the client uuid as hardware_id.
    """
    base = get_server_base_url()
    url = f"{base}/activity/click"

    activation_key = None
    terminal_name = None

    # Try to load activation info from ProgramData
    try:
        if ACTIVATION_FILE.exists():
            with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
                act = json.load(f)
            activation_key = act.get("activation_key")
            terminal_name = act.get("terminal")
    except Exception as e:
        print(f"[WARN] send_click_to_server: failed to read activation.json: {e}")

    if not activation_key or not terminal_name:
        # Without these, /activity/click will 400; avoid spamming the server.
        print("[WARN] send_click_to_server: missing activation_key or terminal; skipping server log.")
        return

    payload = {
        "activation_key": activation_key,
        "terminal": str(terminal_name),
        "hardware_id": get_client_uuid(),
        "title": game_title,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }
    try:
        resp = requests.post(url, json=payload, timeout=3)
        if resp.status_code != 200:
            print(f"[WARN] send_click_to_server: HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[WARN] send_click_to_server failed: {e}")


# ------------------------------
# Status reporting helper
# ------------------------------

def send_status_to_server(status: str) -> None:
    """
    Report runtime status to the server.

    Valid values:
      - idle
      - menu
      - in_play
    """
    try:
        base = get_server_base_url()
        url = f"{base}/client/ping"

        payload = {
            "uuid": get_client_uuid(),
            "status": status,
        }

        requests.post(url, json=payload, timeout=3)
    except Exception:
        # Never allow status reporting to break kiosk flow
        pass


# ------------------------------
# Display orientation helpers
# ------------------------------

def _get_display_orientation():
    """
    Get current display orientation using Win32 API.
    Returns (orientation, width, height) or None on failure.
    Orientation: 0=landscape, 1=portrait(left), 2=inverted, 3=portrait(right)
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    ENUM_CURRENT_SETTINGS = -1

    class DEVMODE(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG),
            ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", wintypes.SHORT),
            ("dmDuplex", wintypes.SHORT),
            ("dmYResolution", wintypes.SHORT),
            ("dmTTOption", wintypes.SHORT),
            ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    devmode = DEVMODE()
    devmode.dmSize = ctypes.sizeof(DEVMODE)

    if not user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
        return None

    return devmode


def force_display_orientation(target_orientation: int):
    """
    Set display orientation.
    0 = landscape (default), 1 = portrait (rotated left),
    2 = inverted landscape, 3 = portrait (rotated right).
    """
    import ctypes
    from ctypes import wintypes

    DM_DISPLAYORIENTATION = 0x00000080
    DM_PELSWIDTH = 0x00080000
    DM_PELSHEIGHT = 0x00100000

    devmode = _get_display_orientation()
    if devmode is None:
        print("[WARN] force_display_orientation: failed to read current display settings")
        return False

    current = devmode.dmDisplayOrientation
    if current == target_orientation:
        print(f"[INFO] Display already at orientation {target_orientation}")
        return True

    devmode.dmFields = DM_DISPLAYORIENTATION | DM_PELSWIDTH | DM_PELSHEIGHT
    devmode.dmDisplayOrientation = target_orientation

    # Swap width/height when changing between landscape and portrait
    needs_swap = (current in (0, 2)) != (target_orientation in (0, 2))
    if needs_swap:
        devmode.dmPelsWidth, devmode.dmPelsHeight = devmode.dmPelsHeight, devmode.dmPelsWidth

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    result = user32.ChangeDisplaySettingsW(ctypes.byref(devmode), 0)
    if result == 0:  # DISP_CHANGE_SUCCESSFUL
        print(f"[INFO] Display rotated to orientation {target_orientation}")
        return True
    else:
        print(f"[WARN] Display rotation failed with code {result}")
        return False


def force_portrait():
    """Force primary display into portrait orientation (rotated left)."""
    return force_display_orientation(1)


def force_landscape():
    """Force primary display into landscape orientation (default)."""
    return force_display_orientation(0)


# ------------------------------
# Game launching helpers
# ------------------------------

def launch_game(game: Dict[str, Any]) -> Optional[subprocess.Popen]:
    """
    Launch either a native .exe or a URL based on the game dict.

    Returns:
        - subprocess.Popen object for exe games
        - None for URL games
    """
    gtype = (game.get("type") or "url").lower().strip()
    target = game.get("target") or ""

    if not target:
        print(f"[WARN] launch_game: missing target for {game.get('title')}")
        return None

    if gtype == "exe":
        # Ensure the target exists before attempting to launch
        if not os.path.exists(target):
            print(f"[ERROR] launch_game: target not found for '{game.get('title') or 'Unknown'}': {target}")
            return None
        try:
            exe_dir = os.path.dirname(target)
            # Use shell=True so .lnk and .exe resolve via Windows shell, and set cwd to the EXE's directory
            proc = subprocess.Popen(target, shell=True, cwd=exe_dir or None)
            return proc
        except Exception as e:
            print(f"[ERROR] Failed to launch exe '{target}': {e}")
            return None
    else:
        # URL – for now, open in default browser.
        # Later we can embed a QWebEngineView if you want a browser-style kiosk.
        try:
            import webbrowser
            webbrowser.open(target)
        except Exception as e:
            print(f"[ERROR] Failed to open URL '{target}': {e}")
        return None