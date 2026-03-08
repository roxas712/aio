#!/usr/bin/env python3
# loading.py

import sys
import os
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PyQt5.QtGui import QFont

from win_common import AIO_ROOT

RETURN_SCRIPT = AIO_ROOT / "kiosk" / "return.py"
CURRENT_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "current_pid.txt"

class LoadingWindow(QWidget):
    def __init__(self, mode: str = "launch"):
        super().__init__()
        self.mode = mode
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        # Use an opaque background to fully hide the desktop behind the loading screen
        self.setStyleSheet("background-color: black;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignCenter)

        label = QLabel(self)
        font = label.font()
        font.setPointSize(36)
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180); "
            "padding: 20px; border-radius: 12px;"
        )

        if mode == "return":
            label.setText("RETURNING TO PLATFORM MENU...")
        else:
            label.setText("LOADING YOUR SELECTION...")

        layout.addWidget(label)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "launch"
    target_pid = None
    if len(sys.argv) > 2:
        try:
            target_pid = int(sys.argv[2])
        except ValueError:
            target_pid = None

    app = QApplication(sys.argv)
    win = LoadingWindow(mode)
    win.showFullScreen()

    if mode == "launch":
        # After ~20 seconds, close the loading UI and spawn the Return overlay (if configured)
        def finish_launch():
            pid_arg = None

            # Prefer PID written by multi_win.py
            try:
                if CURRENT_PID_FILE.exists():
                    pid_text = CURRENT_PID_FILE.read_text(encoding="utf-8").strip()
                    if pid_text:
                        pid_arg = pid_text
            except Exception:
                pid_arg = None

            # Fallback: PID passed via argv
            if pid_arg is None and target_pid is not None:
                pid_arg = str(target_pid)

            if RETURN_SCRIPT.exists():
                cmd = [sys.executable, str(RETURN_SCRIPT)]
                if pid_arg:
                    cmd.append(pid_arg)
                try:
                    subprocess.Popen(cmd)
                except Exception as e:
                    print(f"[WARN] Failed to launch return overlay: {e}")

            app.quit()

        QTimer.singleShot(20000, finish_launch)
    elif mode == "return":
        def do_return_cleanup():
            # Prefer PID from file; fall back to argv
            pid_to_kill = None
            try:
                if CURRENT_PID_FILE.exists():
                    pid_text = CURRENT_PID_FILE.read_text(encoding="utf-8").strip()
                    if pid_text:
                        pid_to_kill = pid_text
            except Exception:
                pid_to_kill = None

            if pid_to_kill is None and target_pid is not None:
                pid_to_kill = str(target_pid)

            # Attempt to kill the specific PID if provided
            if pid_to_kill:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid_to_kill), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    print(f"[WARN] Failed to taskkill PID {pid_to_kill}: {e}")

            # As an extra safety measure, kill known game process image names
            for image_name in (
                "playgd.exe",
                "chrome.exe",
                "playorca.mobi.exe",
                "playorca.mobi",
                "FirePhoenix.exe",
                "Orca.exe",
                "gShell.exe",
                "firefox.exe",
            ):
                try:
                    subprocess.run(
                        ["taskkill", "/IM", image_name, "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    print(f"[WARN] Failed to taskkill image {image_name}: {e}")

            # After a brief pause to allow the platform to close, close the loading UI
            QTimer.singleShot(1500, app.quit)

        # Give the returning overlay time to appear before killing the platform
        QTimer.singleShot(2000, do_return_cleanup)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()