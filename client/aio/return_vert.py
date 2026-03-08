#!/usr/bin/env python3

import sys
import subprocess
import os
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton

from win_common import AIO_ROOT

LOADING_SCRIPT = AIO_ROOT / "kiosk" / "loading_vert.py"
CURRENT_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "current_pid.txt"


class VerticalReturnOverlay(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        screen = QApplication.primaryScreen().geometry()
        screen_w = screen.width()
        screen_h = screen.height()

        height = int(screen_h * 0.40)
        y = screen_h - height

        self.setGeometry(0, y, screen_w, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        self.return_btn = QPushButton("Return to Platform Selection", self)
        self.return_btn.setFixedHeight(60)
        self.return_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                font-size: 20px;
                font-weight: bold;
                border-radius: 30px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        layout.addWidget(self.return_btn, alignment=Qt.AlignLeft | Qt.AlignTop)

        self.return_btn.clicked.connect(self._on_return)

    def _on_return(self):
        pid_arg = sys.argv[1] if len(sys.argv) > 1 else None

        if LOADING_SCRIPT.exists():
            cmd = [sys.executable, str(LOADING_SCRIPT), "return"]
            if pid_arg:
                cmd.append(pid_arg)
            subprocess.Popen(cmd)

        def relaunch():
            script_path = AIO_ROOT / "kiosk" / "multi_vert_win.py"
            subprocess.Popen([sys.executable, str(script_path)], cwd=str(script_path.parent))

            try:
                if CURRENT_PID_FILE.exists():
                    CURRENT_PID_FILE.unlink()
            except Exception:
                pass

            app = QApplication.instance()
            if app:
                app.quit()

        QTimer.singleShot(2500, relaunch)


def main():
    app = QApplication(sys.argv)
    overlay = VerticalReturnOverlay()
    overlay.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()