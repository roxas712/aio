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
# Terminal name sync
# ------------------------------

def get_terminal_name() -> str:
    """Read terminal name from activation.json."""
    try:
        if ACTIVATION_FILE.exists():
            with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
                return json.load(f).get("terminal", "")
    except Exception:
        pass
    return ""


def _sync_terminal_name(server_name: str) -> None:
    """Update activation.json if the server-assigned terminal name changed."""
    try:
        data = {}
        if ACTIVATION_FILE.exists():
            with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
        current = data.get("terminal", "")
        if current != server_name:
            data["terminal"] = server_name
            ACTIVATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            with ACTIVATION_FILE.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
    except Exception:
        pass


# ------------------------------
# Version info
# ------------------------------

def _get_app_version() -> str:
    """Read app version from version.json, default V1.0.0."""
    try:
        if VERSION_FILE.exists():
            with VERSION_FILE.open("r", encoding="utf-8") as f:
                return json.load(f).get("version", "V1.0.0")
    except Exception:
        pass
    return "V1.0.0"


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
        "target": "https://cgweb.app/home/",
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
        "type": "url",
        "target": "https://fpc-mob.com",
        "img": str(KIOSK_DIR / "img" / "firephoenix.png"),
        "orientation": "landscape",
    },
    {
        "title": "Fortune 2 Go",
        "type": "url",
        "target": "https://www.fortune2go20.com/",
        "img": str(KIOSK_DIR / "img" / "fortune2go.png"),
        "orientation": "vertical",
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
        "type": "url",
        "target": "https://playgd.city",
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

_startup_restart_cleared = False


def clear_pending_restart():
    """Clear any stale restart flag on the server without rebooting.

    Call this once at app startup so a manual reboot doesn't trigger
    a second reboot from a leftover restart_flag.
    """
    global _startup_restart_cleared
    if _startup_restart_cleared:
        return
    _startup_restart_cleared = True
    try:
        base = get_server_base_url()
        cfg = load_client_config()
        ack_url = f"{base}/client/ack_restart"
        requests.post(ack_url, json={
            "uuid": get_client_uuid(),
            "activation_key": cfg.get("activation_key", ""),
            "terminal": cfg.get("terminal_name", ""),
        }, timeout=3)
    except Exception:
        pass


def send_status_to_server(status: str) -> dict:
    """
    Report runtime status to the server and return server commands.

    Valid values:
      - idle
      - menu
      - in_play

    Returns the server response dict (with 'commands' key) or empty dict.
    """
    try:
        base = get_server_base_url()
        url = f"{base}/client/ping"

        payload = {
            "uuid": get_client_uuid(),
            "status": status,
            "app_version": _get_app_version(),
        }

        resp = requests.post(url, json=payload, timeout=3)
        if resp.ok:
            data = resp.json()
            # Sync terminal_name from server if changed
            config = data.get("config", {})
            server_name = config.get("terminal_name")
            if server_name:
                _sync_terminal_name(server_name)
            # Handle restart command from server
            commands = data.get("commands", {})
            if commands.get("restart"):
                _handle_server_restart(base)
            return data
    except Exception:
        # Never allow status reporting to break kiosk flow
        pass
    return {}


def _handle_server_restart(base_url: str) -> None:
    """Acknowledge restart and reboot the machine."""
    import os
    try:
        cfg = load_client_config()
        # Acknowledge the restart so flag is cleared server-side
        ack_url = f"{base_url}/client/ack_restart"
        requests.post(ack_url, json={
            "uuid": get_client_uuid(),
            "activation_key": cfg.get("activation_key", ""),
            "terminal": cfg.get("terminal_name", ""),
        }, timeout=3)
    except Exception:
        pass
    # Force reboot
    os.system("shutdown /r /t 5 /f")


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


def _get_primary_device_name() -> str:
    """Get the device name of the primary display (e.g. '\\\\.\\DISPLAY1')."""
    import ctypes
    from ctypes import wintypes

    class DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    DISPLAY_DEVICE_PRIMARY = 0x00000004

    dev = DISPLAY_DEVICE()
    dev.cb = ctypes.sizeof(DISPLAY_DEVICE)

    idx = 0
    while user32.EnumDisplayDevicesW(None, idx, ctypes.byref(dev), 0):
        if dev.StateFlags & DISPLAY_DEVICE_PRIMARY:
            name = dev.DeviceName
            print(f"[INFO] Primary display device: {name} ({dev.DeviceString.strip()})")
            return name
        idx += 1

    return ""


def force_display_orientation(target_orientation: int):
    """
    Set display orientation.
    0 = landscape (default), 1 = portrait (rotated left),
    2 = inverted landscape, 3 = portrait (rotated right).

    Uses device-specific ChangeDisplaySettingsExW which is more reliable
    than ChangeDisplaySettingsW(NULL) on NVIDIA drivers.
    """
    import ctypes
    from ctypes import wintypes
    import time

    DM_DISPLAYORIENTATION = 0x00000080
    DM_PELSWIDTH = 0x00080000
    DM_PELSHEIGHT = 0x00100000

    devmode = _get_display_orientation()
    if devmode is None:
        print("[WARN] force_display_orientation: failed to read current display settings")
        return False

    current = devmode.dmDisplayOrientation
    cur_w = devmode.dmPelsWidth
    cur_h = devmode.dmPelsHeight
    want_portrait = target_orientation in (1, 3)
    is_portrait = cur_h > cur_w

    print(f"[INFO] Display: {cur_w}x{cur_h}, orientation={current}, "
          f"target={target_orientation}, want_portrait={want_portrait}, "
          f"is_portrait={is_portrait}")

    # Check both orientation flag AND actual pixel dimensions
    if current == target_orientation and want_portrait == is_portrait:
        print(f"[INFO] Display already at orientation {target_orientation}")
        return True

    # Get the actual display device name (NVIDIA requires it)
    device_name = _get_primary_device_name()

    user32 = ctypes.WinDLL('user32', use_last_error=True)

    # Try each portrait orientation (1 and 3) since physical mounting varies
    orientations_to_try = [target_orientation]
    if want_portrait:
        alt = 3 if target_orientation == 1 else 1
        orientations_to_try.append(alt)

    for try_orientation in orientations_to_try:
        print(f"[INFO] Attempting orientation {try_orientation}...")

        # Re-read current state for each attempt
        dm = _get_display_orientation()
        if dm is None:
            continue

        dm.dmFields = DM_DISPLAYORIENTATION | DM_PELSWIDTH | DM_PELSHEIGHT
        dm.dmDisplayOrientation = try_orientation

        # Swap width/height if needed
        cur_is_portrait = dm.dmPelsHeight > dm.dmPelsWidth
        if want_portrait and not cur_is_portrait:
            dm.dmPelsWidth, dm.dmPelsHeight = dm.dmPelsHeight, dm.dmPelsWidth
        elif not want_portrait and cur_is_portrait:
            dm.dmPelsWidth, dm.dmPelsHeight = dm.dmPelsHeight, dm.dmPelsWidth

        # --- Method 1: ChangeDisplaySettingsExW with device name ---
        # CDS_UPDATEREGISTRY (1) makes the change persistent in the registry
        # so NVIDIA driver can't revert it on next mode-set.
        CDS_UPDATEREGISTRY = 1
        if device_name:
            result = user32.ChangeDisplaySettingsExW(
                device_name,
                ctypes.byref(dm),
                None,   # hwnd
                CDS_UPDATEREGISTRY,
                None,   # lParam
            )
            print(f"[INFO] ChangeDisplaySettingsExW({device_name}, orient={try_orientation}) "
                  f"returned {result}")
        else:
            result = user32.ChangeDisplaySettingsW(ctypes.byref(dm), CDS_UPDATEREGISTRY)
            print(f"[INFO] ChangeDisplaySettingsW(orient={try_orientation}) "
                  f"returned {result}")

        if result == 0:
            time.sleep(1.0)
            verify = _get_display_orientation()
            if verify:
                vw, vh = verify.dmPelsWidth, verify.dmPelsHeight
                actual_portrait = vh > vw
                if want_portrait == actual_portrait:
                    print(f"[INFO] Verified: {vw}x{vh} — rotation successful")
                    return True
                else:
                    print(f"[WARN] Rotation reported success but pixels={vw}x{vh}")
            else:
                return True

    # --- Fallback: PowerShell/C# ChangeDisplaySettingsEx ---
    print("[INFO] Trying PowerShell/C# fallback...")
    for try_orientation in orientations_to_try:
        if _try_nvidia_rotation(try_orientation):
            time.sleep(1.0)
            verify = _get_display_orientation()
            if verify:
                vw, vh = verify.dmPelsWidth, verify.dmPelsHeight
                actual_portrait = vh > vw
                if want_portrait == actual_portrait:
                    print(f"[INFO] PowerShell rotation verified: {vw}x{vh}")
                    return True
            else:
                return True

    # --- Last resort: use PowerShell Set-DisplayOrientation ---
    print("[INFO] Trying display.exe / PowerShell last resort...")
    try:
        import subprocess
        # Try using PowerShell to directly set via WMI/CIM
        ps_cmd = f'''
$orientation = {target_orientation}
# Try using the display CPL approach
$sig = @'
[DllImport("user32.dll")]
public static extern int ChangeDisplaySettingsEx(
    string lpszDeviceName, ref DEVMODE lpDevMode, IntPtr hwnd,
    uint dwflags, IntPtr lParam);
[DllImport("user32.dll")]
public static extern bool EnumDisplayDevices(
    string lpDevice, uint iDevNum, ref DISPLAY_DEVICE lpDisplayDevice, uint dwFlags);
[DllImport("user32.dll")]
public static extern bool EnumDisplaySettings(
    string deviceName, int modeNum, ref DEVMODE devMode);

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
public struct DISPLAY_DEVICE {{
    public int cb;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
    public string DeviceName;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
    public string DeviceString;
    public int StateFlags;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
    public string DeviceID;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
    public string DeviceKey;
}}

[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
public struct DEVMODE {{
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
    public string dmDeviceName;
    public short dmSpecVersion;
    public short dmDriverVersion;
    public short dmSize;
    public short dmDriverExtra;
    public int dmFields;
    public int dmPositionX;
    public int dmPositionY;
    public int dmDisplayOrientation;
    public int dmDisplayFixedOutput;
    public short dmColor;
    public short dmDuplex;
    public short dmYResolution;
    public short dmTTOption;
    public short dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
    public string dmFormName;
    public short dmLogPixels;
    public int dmBitsPerPel;
    public int dmPelsWidth;
    public int dmPelsHeight;
    public int dmDisplayFlags;
    public int dmDisplayFrequency;
}}
'@
Add-Type -MemberDefinition $sig -Name NativeDisplay -Namespace Win32

# Find primary display
$dev = New-Object Win32.NativeDisplay+DISPLAY_DEVICE
$dev.cb = [System.Runtime.InteropServices.Marshal]::SizeOf($dev)
$idx = 0
$primaryName = ""
while ([Win32.NativeDisplay]::EnumDisplayDevices($null, $idx, [ref]$dev, 0)) {{
    if ($dev.StateFlags -band 4) {{ $primaryName = $dev.DeviceName; break }}
    $idx++
}}
if (-not $primaryName) {{ Write-Host "No primary display found"; exit 1 }}
Write-Host "Primary: $primaryName"

$dm = New-Object Win32.NativeDisplay+DEVMODE
$dm.dmSize = [System.Runtime.InteropServices.Marshal]::SizeOf($dm)
[Win32.NativeDisplay]::EnumDisplaySettings($primaryName, -1, [ref]$dm) | Out-Null

$oldW = $dm.dmPelsWidth
$oldH = $dm.dmPelsHeight
$wantPortrait = ($orientation -eq 1) -or ($orientation -eq 3)
$isLandscape = $oldW -gt $oldH

if ($wantPortrait -and $isLandscape) {{
    $dm.dmPelsWidth = $oldH
    $dm.dmPelsHeight = $oldW
}} elseif (-not $wantPortrait -and -not $isLandscape) {{
    $dm.dmPelsWidth = $oldH
    $dm.dmPelsHeight = $oldW
}}
$dm.dmDisplayOrientation = $orientation
$dm.dmFields = 0x00000080 -bor 0x00080000 -bor 0x00100000

# Use CDS_UPDATEREGISTRY (1) to make it persistent
$r = [Win32.NativeDisplay]::ChangeDisplaySettingsEx($primaryName, [ref]$dm, [IntPtr]::Zero, 1, [IntPtr]::Zero)
Write-Host "Result: $r"
'''
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=20,
        )
        print(f"[INFO] PowerShell last-resort output: {result.stdout.strip()}")
        if result.returncode == 0 and "Result: 0" in result.stdout:
            time.sleep(1.0)
            verify = _get_display_orientation()
            if verify:
                vw, vh = verify.dmPelsWidth, verify.dmPelsHeight
                if want_portrait == (vh > vw):
                    print(f"[INFO] Last-resort rotation verified: {vw}x{vh}")
                    return True
    except Exception as e:
        print(f"[WARN] Last-resort rotation failed: {e}")

    print(f"[WARN] All rotation methods failed")
    return False


def _try_nvidia_rotation(target_orientation: int) -> bool:
    """Try rotating display using NVIDIA command-line tools."""
    import subprocess

    # Map orientation to NVIDIA rotation degrees
    # 0=landscape(0°), 1=portrait left(90°), 2=inverted(180°), 3=portrait right(270°)
    nvidia_rotation = {0: "0", 1: "90", 2: "180", 3: "270"}
    degrees = nvidia_rotation.get(target_orientation, "90")

    # Try nvidia-smi display rotation (works on some driver versions)
    try:
        # Use NVIDIA's nvcpl command line if available
        nvcpl = r"C:\Program Files\NVIDIA Corporation\Control Panel Client\nvcplui.exe"
        import os
        if os.path.exists(nvcpl):
            print(f"[INFO] NVIDIA Control Panel found at {nvcpl}")
    except Exception:
        pass

    # Try using PowerShell with .NET to set rotation via WMI
    try:
        ps_cmd = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class DisplayRotation {{
    [DllImport("user32.dll")]
    public static extern int ChangeDisplaySettingsEx(
        string deviceName, ref DEVMODE devMode, IntPtr hwnd,
        uint flags, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool EnumDisplaySettings(
        string deviceName, int modeNum, ref DEVMODE devMode);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    public struct DEVMODE {{
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string dmDeviceName;
        public short dmSpecVersion;
        public short dmDriverVersion;
        public short dmSize;
        public short dmDriverExtra;
        public int dmFields;
        public int dmPositionX;
        public int dmPositionY;
        public int dmDisplayOrientation;
        public int dmDisplayFixedOutput;
        public short dmColor;
        public short dmDuplex;
        public short dmYResolution;
        public short dmTTOption;
        public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel;
        public int dmPelsWidth;
        public int dmPelsHeight;
        public int dmDisplayFlags;
        public int dmDisplayFrequency;
    }}

    public static void Rotate(int orientation) {{
        DEVMODE dm = new DEVMODE();
        dm.dmSize = (short)Marshal.SizeOf(dm);
        EnumDisplaySettings(null, -1, ref dm);
        int oldW = dm.dmPelsWidth;
        int oldH = dm.dmPelsHeight;
        bool isLandscape = oldW > oldH;
        bool wantPortrait = (orientation == 1 || orientation == 3);
        if (isLandscape == wantPortrait) {{
            dm.dmPelsWidth = oldH;
            dm.dmPelsHeight = oldW;
        }}
        dm.dmDisplayOrientation = orientation;
        dm.dmFields = 0x00000080 | 0x00080000 | 0x00100000;
        ChangeDisplaySettingsEx(null, ref dm, IntPtr.Zero, 0, IntPtr.Zero);
    }}
}}
"@
[DisplayRotation]::Rotate({target_orientation})
'''
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            print(f"[INFO] NVIDIA/PowerShell rotation applied (orientation {target_orientation})")
            return True
        else:
            print(f"[WARN] PowerShell rotation failed: {result.stderr.strip()[:200]}")
    except Exception as e:
        print(f"[WARN] PowerShell rotation fallback failed: {e}")

    return False


def force_portrait():
    """Force primary display into portrait orientation.

    Tries orientation 1 (rotated left) first, then 3 (rotated right).
    Retries up to 3 times with increasing delays to handle NVIDIA driver
    settling after boot.
    """
    import time

    for attempt in range(3):
        if attempt > 0:
            wait = attempt * 2
            print(f"[INFO] force_portrait: retry {attempt}, waiting {wait}s...")
            time.sleep(wait)

        result = force_display_orientation(1)
        if result:
            return True

        # Verify if it actually worked despite returning False
        dm = _get_display_orientation()
        if dm and dm.dmPelsHeight > dm.dmPelsWidth:
            print(f"[INFO] force_portrait: pixels are portrait despite return=False")
            return True

    print("[WARN] force_portrait: all attempts failed")
    return False


def force_landscape():
    """Force primary display into landscape orientation (default)."""
    return force_display_orientation(0)


def configure_touch_as_mouse():
    """No-op — touch settings reverted to Windows defaults.

    All games now launch in the browser, so native Windows touch
    handling works correctly without registry overrides.
    """
    pass


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


# ------------------------------
# Periodic config sync
# ------------------------------

SINGLE_GAME_FILE = CONFIG_DIR / "single_game.json"
CHECK_CONFIG_PATH = "/client/check_config"


def sync_config_from_server() -> Dict[str, Any]:
    """
    Fetch latest config from server using activation data.

    Returns dict with:
        terminal_type: str
        games: list | None          (multi/multi_vert modes)
        single_game: dict | None    (single mode)
        changed_games: bool
        changed_terminal_type: bool

    Returns {} on any failure (network, missing activation, etc.).
    """
    if not ACTIVATION_FILE.exists():
        return {}

    try:
        with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
            act = json.load(f)
    except Exception:
        return {}

    activation_key = act.get("activation_key")
    terminal = act.get("terminal")
    if not activation_key or not terminal:
        return {}

    old_terminal_type = act.get("terminal_type", "multi")

    base = get_server_base_url()
    cfg_url = f"{base}{CHECK_CONFIG_PATH}"
    try:
        resp = requests.get(
            cfg_url,
            params={"activation_key": activation_key, "terminal": terminal},
            timeout=8,
        )
        if resp.status_code != 200:
            return {}
        cfg = resp.json() or {}
    except Exception:
        return {}

    # Resolve terminal type
    tt = (cfg.get("terminal_type") or cfg.get("desired_terminal")
          or act.get("terminal_type") or "multi")
    tt = str(tt).strip().lower() if tt else "multi"
    if tt not in ("single", "multi", "multi_vert", "lock"):
        tt = "multi"

    result = {
        "terminal_type": tt,
        "changed_terminal_type": (tt != old_terminal_type),
        "games": None,
        "single_game": None,
        "changed_games": False,
    }

    if tt in ("multi", "multi_vert"):
        selected = cfg.get("selected_games") or []
        if selected:
            all_games = get_game_library()
            filtered = []
            for sg in selected:
                raw_title = (sg.get("title") or "").strip()
                if not raw_title:
                    continue
                title_l = raw_title.lower()
                match = next(
                    (g for g in all_games if (g.get("title") or "").strip().lower() == title_l),
                    None,
                )
                if match:
                    entry = dict(match)
                    # Let server URL override if DEFAULT_GAMES has empty target
                    if sg.get("url") and not entry.get("target"):
                        entry["target"] = sg["url"]
                    filtered.append(entry)
                else:
                    # Try to find local image by sanitized title
                    sanitized = raw_title.lower().replace(" ", "")
                    local_img = KIOSK_DIR / "img" / f"{sanitized}.png"
                    filtered.append({
                        "title": sg.get("title") or "Unknown",
                        "type": "url",
                        "target": sg.get("url") or "",
                        "img": str(local_img) if local_img.exists() else (sg.get("img") or ""),
                    })
            if filtered:
                result["games"] = filtered
                current = load_games()
                current_titles = sorted((g.get("title") or "").lower() for g in current)
                new_titles = sorted((g.get("title") or "").lower() for g in filtered)
                # Also compare targets so stale URLs on disk get refreshed
                current_targets = sorted((g.get("target") or "") for g in current)
                new_targets = sorted((g.get("target") or "") for g in filtered)
                result["changed_games"] = (
                    current_titles != new_titles or current_targets != new_targets
                )

    elif tt == "single":
        sg = cfg.get("selected_game") or {}
        title = (sg.get("title") or "").strip()
        if title:
            all_games = get_game_library()
            chosen = next(
                (g for g in all_games if (g.get("title") or "").strip().lower() == title.lower()),
                None,
            )
            if not chosen:
                chosen = {
                    "title": sg.get("title") or "Unknown",
                    "type": "url",
                    "target": sg.get("url") or "",
                    "img": sg.get("img") or "",
                }
            result["single_game"] = chosen
            current_single = {}
            if SINGLE_GAME_FILE.exists():
                try:
                    with SINGLE_GAME_FILE.open("r", encoding="utf-8") as f:
                        current_single = json.load(f)
                except Exception:
                    pass
            result["changed_games"] = (
                (current_single.get("title") or "").lower() != title.lower()
            )

    return result


def persist_synced_config(sync_result: Dict[str, Any]) -> None:
    """Write synced config to disk (games.json / single_game.json / activation.json)."""
    tt = sync_result.get("terminal_type", "multi")

    if tt in ("multi", "multi_vert") and sync_result.get("games"):
        save_games(sync_result["games"])

    elif tt == "single" and sync_result.get("single_game"):
        try:
            SINGLE_GAME_FILE.parent.mkdir(parents=True, exist_ok=True)
            with SINGLE_GAME_FILE.open("w", encoding="utf-8") as f:
                json.dump(sync_result["single_game"], f, indent=2)
        except Exception:
            pass

    # Update terminal_type in activation.json
    if ACTIVATION_FILE.exists():
        try:
            with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
                act = json.load(f)
            act["terminal_type"] = tt
            with ACTIVATION_FILE.open("w", encoding="utf-8") as f:
                json.dump(act, f, indent=2)
        except Exception:
            pass