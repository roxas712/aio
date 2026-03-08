"""Set display resolution to 1080x1920 portrait (without rotation)."""
import ctypes
from ctypes import wintypes, byref, sizeof


class DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", ctypes.c_long),
        ("dmPositionY", ctypes.c_long),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
    ]


DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000

dm = DEVMODE()
dm.dmSize = sizeof(DEVMODE)
ctypes.windll.user32.EnumDisplaySettingsW(None, -1, byref(dm))
print(f"Current: {dm.dmPelsWidth}x{dm.dmPelsHeight}")

dm.dmPelsWidth = 1080
dm.dmPelsHeight = 1920
dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT

result = ctypes.windll.user32.ChangeDisplaySettingsW(byref(dm), 0)
codes = {0: "SUCCESS", -1: "RESTART_REQUIRED", -2: "FAILED", -3: "BAD_MODE", -4: "NOT_UPDATED", -5: "BAD_FLAGS", -6: "BAD_PARAM"}
print(f"Set 1080x1920: {codes.get(result, result)}")
