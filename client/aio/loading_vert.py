#!/usr/bin/env python3

import sys
import os
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel

CURRENT_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "current_pid.txt"


class VerticalLoadingWindow(QWidget):
    def __init__(self, mode="launch"):
        super().__init__()
        self.mode = mode

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setStyleSheet("background-color: black;")

        screen = QApplication.primaryScreen().geometry()
        screen_w = screen.width()
        screen_h = screen.height()

        # Bottom 40% only
        height = int(screen_h * 0.40)
        y = screen_h - height

        self.setGeometry(0, y, screen_w, height)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        label = QLabel(self)
        font = label.font()
        font.setPointSize(36)
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: white;")

        if mode == "return":
            label.setText("RETURNING TO PLATFORM MENU...")
        else:
            label.setText("LOADING YOUR SELECTION...")

        layout.addWidget(label)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "launch"
    target_pid = sys.argv[2] if len(sys.argv) > 2 else None

    app = QApplication(sys.argv)
    win = VerticalLoadingWindow(mode)
    win.show()

    if mode == "launch":
        QTimer.singleShot(20000, app.quit)

    elif mode == "return":
        def cleanup():
            if target_pid:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(target_pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            QTimer.singleShot(1500, app.quit)

        QTimer.singleShot(2000, cleanup)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()