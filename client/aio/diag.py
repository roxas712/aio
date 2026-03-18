#!/usr/bin/env python3
"""AIO Diagnostic Script — run on terminal to gather display/system info.

Usage:  py -3.14 diag.py
"""

import os
import sys
import json
import ctypes
from ctypes import wintypes
from pathlib import Path

PROGRAMDATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio"
DIAG_FILE = PROGRAMDATA / "logs" / "diag.txt"

lines = []

def log(msg):
    print(msg)
    lines.append(msg)


def main():
    log("=" * 60)
    log("  AIO Terminal Diagnostics")
    log("=" * 60)

    # --- Screen info via ctypes ---
    user32 = ctypes.windll.user32
    sm_w = user32.GetSystemMetrics(0)
    sm_h = user32.GetSystemMetrics(1)
    log(f"\nGetSystemMetrics:  {sm_w} x {sm_h}")

    # --- DEVMODE display settings ---
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        from win_common import _get_display_orientation
        d = _get_display_orientation()
        if d:
            log(f"DEVMODE PelsWidth:  {d.dmPelsWidth}")
            log(f"DEVMODE PelsHeight: {d.dmPelsHeight}")
            log(f"DEVMODE Orientation: {d.dmDisplayOrientation}")
            log(f"DEVMODE Frequency:  {d.dmDisplayFrequency} Hz")
        else:
            log("DEVMODE: failed to read")
    except Exception as e:
        log(f"DEVMODE error: {e}")

    # --- Qt screen geometry ---
    try:
        os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
        os.environ.setdefault("QT_SCALE_FACTOR", "1")
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
        app = QApplication(sys.argv)
        screen = app.primaryScreen()
        geo = screen.geometry()
        log(f"\nQt primaryScreen:  {geo.width()} x {geo.height()}")
        log(f"Qt devicePixelRatio: {screen.devicePixelRatio()}")
        log(f"Qt physicalSize:   {screen.physicalSize().width():.0f} x {screen.physicalSize().height():.0f} mm")
        log(f"Qt logicalDpi:     {screen.logicalDotsPerInch():.1f}")
        avail = screen.availableGeometry()
        log(f"Qt availableGeo:   {avail.width()} x {avail.height()}")
        app.quit()
    except Exception as e:
        log(f"Qt error: {e}")

    # --- NVIDIA driver ---
    try:
        import subprocess
        r = subprocess.run(["nvidia-smi", "--query-gpu=driver_version,name",
                           "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            log(f"\nNVIDIA GPU: {r.stdout.strip()}")
        else:
            log("\nNVIDIA: nvidia-smi failed")
    except Exception:
        log("\nNVIDIA: nvidia-smi not found")

    # --- Config files ---
    log("\n--- Config Files ---")
    for name in ("activation.json", "version.json", "games.json"):
        p = PROGRAMDATA / "config" / name
        if p.exists():
            try:
                with p.open("r") as f:
                    data = json.load(f)
                if name == "games.json":
                    log(f"{name}: {len(data)} games")
                else:
                    log(f"{name}: {json.dumps(data, indent=2)}")
            except Exception as e:
                log(f"{name}: error reading: {e}")
        else:
            log(f"{name}: NOT FOUND")

    # --- Kiosk video files ---
    vids_dir = Path(r"C:\Program Files\aio\kiosk\vids")
    if vids_dir.exists():
        vids = list(vids_dir.iterdir())
        log(f"\nVideos ({len(vids)}):")
        for v in vids:
            sz = v.stat().st_size
            log(f"  {v.name}: {sz:,} bytes ({sz // 1_000_000} MB)")
    else:
        log(f"\nVideos dir not found: {vids_dir}")

    # --- Recent logs ---
    log("\n--- Recent updater.log ---")
    updater_log = PROGRAMDATA / "logs" / "updater.log"
    if updater_log.exists():
        try:
            text = updater_log.read_text(encoding="utf-8", errors="replace")
            for line in text.strip().split("\n")[-15:]:
                log(f"  {line}")
        except Exception:
            log("  (error reading)")
    else:
        log("  NOT FOUND")

    log("\n--- Recent multi_vert_debug.log ---")
    vert_log = PROGRAMDATA / "logs" / "multi_vert_debug.log"
    if vert_log.exists():
        try:
            text = vert_log.read_text(encoding="utf-8", errors="replace")
            for line in text.strip().split("\n")[-20:]:
                log(f"  {line}")
        except Exception:
            log("  (error reading)")
    else:
        log("  NOT FOUND")

    # --- Save to file ---
    try:
        DIAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        DIAG_FILE.write_text("\n".join(lines), encoding="utf-8")
        log(f"\nDiag saved to: {DIAG_FILE}")
    except Exception as e:
        log(f"\nFailed to save diag: {e}")

    log("\nDone. Please screenshot or copy the output above.")


if __name__ == "__main__":
    main()
