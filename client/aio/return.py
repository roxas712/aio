#!/usr/bin/env python3

import sys
import subprocess
import os
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QPushButton,
)

from win_common import AIO_ROOT

LOADING_SCRIPT = AIO_ROOT / "kiosk" / "loading.py"
CURRENT_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\\ProgramData")) / "aio" / "config" / "current_pid.txt"


class ReturnButton(QPushButton):
    """
    A pill-shaped button that shows 'Return' collapsed, and expands to
    'Return to Platform Selection' on hover.
    """
    def __init__(self, parent=None):
        super().__init__("Return", parent)
        self._collapsed_width = 140
        self._expanded_width = 320
        self._height = 60
        self.setFixedSize(self._collapsed_width, self._height)
        self.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 30px;
                padding-left: 20px;
                padding-right: 20px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)

    def enterEvent(self, event):
        self.setFixedWidth(self._expanded_width)
        self.setText("Return to Platform Selection")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setFixedWidth(self._collapsed_width)
        self.setText("Return")
        super().leaveEvent(event)


class ReturnOverlay(QWidget):
    """
    Fullscreen, always-on-top overlay with a bottom-left Return button.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.showFullScreen()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)

        self.return_btn = ReturnButton(self)
        layout.addWidget(self.return_btn, alignment=Qt.AlignLeft | Qt.AlignTop)
        self.return_btn.clicked.connect(self._on_return)

    def _on_return(self):
        """
        Return flow:
        - Launch loading.py in 'return' mode so the returning UI covers the desktop.
        - After a short delay, relaunch multi_win.py.
        NOTE: loading.py is responsible for terminating the running platform.
        """
        pid_arg = sys.argv[1] if len(sys.argv) > 1 else None

        # Launch loading.py in return mode (pass PID if we have one)
        if LOADING_SCRIPT.exists():
            cmd = [sys.executable, str(LOADING_SCRIPT), "return"]
            if pid_arg is not None:
                cmd.append(pid_arg)
            try:
                subprocess.Popen(cmd)
            except Exception as e:
                print(f"[ERROR] Failed to launch loading.py in return mode: {e}")
        else:
            print(f"[ERROR] loading.py not found at {LOADING_SCRIPT}")

        def relaunch_multi_and_exit():
            # Relaunch multi_win.py (single source of truth for starting the menu)
            script_path = AIO_ROOT / "kiosk" / "multi_win.py"
            try:
                subprocess.Popen([sys.executable, str(script_path)], cwd=str(script_path.parent))
            except Exception as e:
                print(f"[ERROR] Failed to relaunch multi_win.py: {e}")

            # Clear PID file so we don't reuse stale PIDs
            try:
                if CURRENT_PID_FILE.exists():
                    CURRENT_PID_FILE.unlink()
            except Exception:
                pass

            # Quit this overlay
            app = QApplication.instance()
            if app:
                app.quit()

        # Give loading.py time to appear before we relaunch the menu
        QTimer.singleShot(2500, relaunch_multi_and_exit)


def main():
    app = QApplication(sys.argv)
    overlay = ReturnOverlay()
    overlay.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()