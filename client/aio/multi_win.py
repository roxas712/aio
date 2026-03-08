import PyQt5.QtGui as QtGui
#!/usr/bin/env python3
#multi_win.py

import sys
import os
import subprocess
import json
from functools import partial
from typing import Dict, Any
from pathlib import Path
import time
# Ensure QWidget is defined before use, even if execution happens before imports settle
from PyQt5.QtWidgets import QWidget

from PyQt5.QtCore import Qt, QSize, QEvent, QTimer, QEasingCurve, QRectF
from PyQt5.QtWidgets import QToolButton
from PyQt5.QtCore import QPropertyAnimation, QPoint
from PyQt5.QtGui import QPixmap, QPainter, QPainterPath, QPen, QFont, QMovie, QColor
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLineEdit,
    QPushButton,
    QWidget,
    QLabel,
    QSizePolicy,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QGraphicsBlurEffect,
)

# ------------------------------
# AdOverlay for Portrait Mode
# ------------------------------

class AdOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background-color: black;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("AD SPACE", self)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: white; font-size: 36px;")
        layout.addWidget(label)
CAROUSEL_ANIM_MS = 280
CAROUSEL_COMMIT_MS = 180
CAROUSEL_IDLE_ROTATE_MS = 1500
CAROUSEL_IDLE_DELAY_MS = 10000
CENTER_SIZE = QSize(400, 600)   # Tall center card
SIDE_SIZE = QSize(320, 480)     # Tall side cards


# Safe top padding so cards never clip at the top
CAROUSEL_TOP_PADDING = 2

# Spacing tuned per depth level

SIDE_OPACITY = 0.65

CAROUSEL_CENTER_OFFSET = 0

# Accent colors per game (fallback = gold)
GAME_ACCENT_COLORS = {
    "Golden Dragon City": "#FFD700",
    "Orca": "#2EC4FF",
    "River Sweeps": "#3CB371",
    "Fire Phoenix": "#FF4500",
    "Fire Kirin": "#E60026",
    "Great Balls of Fire": "#FF8C00",
}

GLOW_PULSE_MIN = 0.6
GLOW_PULSE_MAX = 1.0
GLOW_PULSE_MS = 1400

BREATH_SCALE_MIN = 0.98
BREATH_SCALE_MAX = 1.02
BREATH_ANIM_MS = 2200

# ------------------------------
# Carousel Widget (FIXED)
# ------------------------------

class CarouselWidget(QWidget):
    def __init__(self, games, on_select, parent=None):
        super().__init__(parent)
        # Carousel should not consume the whole screen height
        self.setMinimumHeight(720)
        self.games = games
        self.on_select = on_select
        self.index = 0

        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        # Remove vertical margins so cards are not clipped by layout
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        # Remove layout-based centering; we'll center manually

        self.card_container = QWidget(self)
        existing_layout = self.card_container.layout()
        if existing_layout is not None:
            existing_layout.deleteLater()
        # Container height must fit cards but leave room for the button
        self.card_container.setFixedSize(2200, 700)

        layout.addWidget(self.card_container)

        self._cards_initialized = False

        QTimer.singleShot(0, lambda: self._build_cards(animate=False))

        self.start_attract_rotation()

        # Prevent attribute errors from optional timers
        self.idle_timer = QTimer(self)
        self.user_activity_timer = QTimer(self)

    def _build_cards(self, animate=False):
        # Guard against empty game list (prevent silent failure)
        if not self.games:
            return

        # Final safety: clear buttons list before rebuilding
        self.buttons = []

        # Strong cleanup: remove all previous widgets, not just findChildren
        for child in self.card_container.findChildren(QWidget):
            child.hide()
            child.setParent(None)
            child.deleteLater()

        # Edge‑based spacing (center ↔ side ↔ outer)
        cx = self.card_container.width() // 2
        GAP = 20
        inner = (CENTER_SIZE.width() // 2) + (SIDE_SIZE.width() // 2) + GAP
        outer_card_w = int(SIDE_SIZE.width() * 0.75)
        outer = inner + (SIDE_SIZE.width() // 2) + (outer_card_w // 2) + GAP
        X_OFFSETS = {
            -2: -outer,
            -1: -inner,
             0:    0,
             1:  inner,
             2:  outer,
        }
        # Anchor cards to container center only (no external lift)
        cy_visual_center = self.card_container.height() // 2

        for i in range(5):
            offset = i - 2
            idx = (self.index + offset) % len(self.games)
            game = self.games[idx]

            btn = BlurImageButton(
                title=game["title"],
                img_path=game.get("img") or "",
                parent=self.card_container
            )
            btn.enable_hover = False
            btn._callback = None
            # No click or hover in attract mode

            if offset == CAROUSEL_CENTER_OFFSET:
                size = CENTER_SIZE
                opacity = 1.0
                btn.setGraphicsEffect(None)  # ensure no effect masks rounding
                # No accent, no glow, no breathing, no click
            elif abs(offset - CAROUSEL_CENTER_OFFSET) == 1:
                size = SIDE_SIZE
                opacity = SIDE_OPACITY
            else:
                size = QSize(int(SIDE_SIZE.width()*0.75), int(SIDE_SIZE.height()*0.75))
                opacity = 0.35

            btn.resize(size)
            btn.setWindowOpacity(opacity)

            # Edge-based X position
            x = cx + X_OFFSETS[offset] - size.width() // 2
            # Anchor Y to container center only (no clamp)
            y = cy_visual_center - size.height() // 2
            btn.move(int(x), int(y))
            btn.show()
            if offset == 0:
                btn.raise_()
            self.buttons.append(btn)

        if animate:
            self._animate_cards()

        self._cards_initialized = True

    def _animate_cards(self):
        # Edge‑based spacing (center ↔ side ↔ outer)
        cx = self.card_container.width() // 2
        GAP = 20
        inner = (CENTER_SIZE.width() // 2) + (SIDE_SIZE.width() // 2) + GAP
        outer_card_w = int(SIDE_SIZE.width() * 0.75)
        outer = inner + (SIDE_SIZE.width() // 2) + (outer_card_w // 2) + GAP
        X_OFFSETS = {
            -2: -outer,
            -1: -inner,
             0:    0,
             1:  inner,
             2:  outer,
        }
        # Anchor cards to container center only (no external lift)
        cy_visual_center = self.card_container.height() // 2

        for i, btn in enumerate(self.buttons):
            offset = i - 2  # center index = 2

            if offset == 0:
                size = CENTER_SIZE
                opacity = 1.0
            elif abs(offset) == 1:
                size = SIDE_SIZE
                opacity = SIDE_OPACITY
            else:
                size = QSize(int(SIDE_SIZE.width() * 0.75), int(SIDE_SIZE.height() * 0.75))
                opacity = 0.35

            # Edge-based X position
            target_x = cx + X_OFFSETS[offset] - size.width() // 2
            # Anchor Y to container center only (no clamp)
            target_y = cy_visual_center - size.height() // 2

            pos_anim = QPropertyAnimation(btn, b"pos", self)
            pos_anim.setDuration(CAROUSEL_ANIM_MS)
            pos_anim.setEndValue(QPoint(int(target_x), int(target_y)))
            pos_anim.setEasingCurve(QEasingCurve.OutCubic)
            pos_anim.start()

            # Only animate opacity for non-center cards; direct set for center
            if offset != 0:
                fade = QPropertyAnimation(btn, b"windowOpacity", self)
                fade.setDuration(CAROUSEL_ANIM_MS)
                fade.setEndValue(opacity)
                fade.start()
            else:
                btn.setWindowOpacity(1.0)
            if offset == 0:
                btn.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # Hard-center the carousel container in the widget (horizontal only)
        parent_w = self.width()
        cont_w = self.card_container.width()
        x = int((parent_w - cont_w) / 2)
        # Let the layout control vertical placement
        self.card_container.move(x, 0)
    def start_attract_rotation(self):
        self.attract_timer = QTimer(self)
        self.attract_timer.setInterval(2200)
        self.attract_timer.timeout.connect(self._rotate_once)
        self.attract_timer.start()

    def _rotate_once(self):
        self.index = (self.index + 1) % len(self.games)
        self._build_cards(animate=True)

    def _start_center_glow(self, btn, color):
        self._glow_anim = QPropertyAnimation(btn, b"windowOpacity", self)
        self._glow_anim.setDuration(GLOW_PULSE_MS)
        self._glow_anim.setStartValue(GLOW_PULSE_MIN)
        self._glow_anim.setEndValue(GLOW_PULSE_MAX)
        self._glow_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._glow_anim.setLoopCount(-1)
        self._glow_anim.start()

        btn.setStyleSheet(
            f"border: 6px solid {color};"
        )

    def _start_breathing(self, btn):
        geo = btn.geometry()

        dx = int(geo.width() * (BREATH_SCALE_MAX - 1) / 2)
        dy = int(geo.height() * (BREATH_SCALE_MAX - 1) / 2)

        grow = QPropertyAnimation(btn, b"geometry", self)
        grow.setDuration(BREATH_ANIM_MS)
        grow.setStartValue(geo)
        grow.setEndValue(
            geo.adjusted(
                -dx,
                -dy,
                dx,
                dy,
            )
        )
        grow.setEasingCurve(QEasingCurve.InOutSine)
        grow.setLoopCount(-1)
        grow.start()

        self._breath_anim = grow

    def _commit_selection(self, game):
        try:
            if hasattr(self, "_glow_anim"):
                self._glow_anim.stop()
            if hasattr(self, "_breath_anim"):
                self._breath_anim.stop()
        except Exception:
            pass
        self.idle_timer.stop()
        # Find the visually centered button (index 2)
        if len(self.buttons) >= 3:
            center = self.buttons[2]
        else:
            center = self.buttons[0]

        start = center.pos()
        end = QPoint(start.x(), start.y() - 20)

        anim = QPropertyAnimation(center, b"pos", self)
        anim.setDuration(CAROUSEL_COMMIT_MS)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()

        QTimer.singleShot(CAROUSEL_COMMIT_MS, lambda g=game: self.on_select(g))

    def next_game(self):
        self.idle_timer.stop()
        self.user_activity_timer.start()
        self.index = (self.index + 1) % len(self.games)
        self._build_cards(animate=True)

    def prev_game(self):
        self.idle_timer.stop()
        self.user_activity_timer.start()
        self.index = (self.index - 1) % len(self.games)
        self._build_cards(animate=True)

from win_common import (
    load_games,
    log_activity_local,
    send_click_to_server,
    send_status_to_server,
    get_local_ip,
    VERSION_FILE,
    AIO_ROOT,
    launch_game as win_launch_game,
    get_client_uuid,
    GAMES_FILE,
    ACTIVATION_FILE,
)

LOADING_SCRIPT = AIO_ROOT / "kiosk" / "loading.py"

# PID propagation file for launched game/browser
CURRENT_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "current_pid.txt"

# Hardened Chrome profile directory (for PWA suppression)
CHROME_PROFILE_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "chrome_profile"


MANAGER_PIN = "8888"
ADVANCED_PIN = "1225"


# ------------------------------
# Small UI helpers
# ------------------------------

class NumericKeypadDialog(QDialog):
    def __init__(self, title="Enter Pin", parent=None):
        super().__init__(parent)
        self._prompt_text = title
        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setStyleSheet("""
            QDialog {
                background-color: #222;
                border-radius: 15px;
            }
        """)
        self._entered_text = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        prompt_label = QLabel(self._prompt_text, self)
        prompt_label.setAlignment(Qt.AlignCenter)
        prompt_label.setStyleSheet("font-size: 18px; color: white;")
        layout.addWidget(prompt_label, alignment=Qt.AlignCenter)

        self.display = QLineEdit(self)
        self.display.setFixedHeight(40)
        self.display.setAlignment(Qt.AlignCenter)
        self.display.setEchoMode(QLineEdit.Password)
        self.display.setReadOnly(True)
        self.display.setStyleSheet("""
            QLineEdit {
                font-size: 16px;
                background-color: rgba(255,255,255,0.8);
                color: black;
                border: 1px solid gray;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        layout.addWidget(self.display, alignment=Qt.AlignCenter)

        grid = QGridLayout()
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)
        buttons = [
            ("1", 0, 0), ("2", 0, 1), ("3", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("7", 2, 0), ("8", 2, 1), ("9", 2, 2),
            ("0", 3, 1),
        ]
        for text, row, col in buttons:
            btn = QPushButton(text)
            btn.setFixedSize(50, 50)
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 18px;
                    font-weight: bold;
                    background-color: white;
                    color: black;
                    border: 1px solid gray;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: lightgray;
                }
            """)
            btn.clicked.connect(lambda checked, t=text: self._append_digit(t))
            grid.addWidget(btn, row, col)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(80, 40)
        cancel_btn.setStyleSheet("background-color: red; color: white;")
        cancel_btn.clicked.connect(self.reject)
        grid.addWidget(cancel_btn, 4, 0, 1, 2)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedSize(80, 40)
        ok_btn.setStyleSheet("background-color: white; color: black;")
        ok_btn.clicked.connect(self.accept)
        grid.addWidget(ok_btn, 4, 2)

        layout.addLayout(grid)
        self.setFixedSize(260, 360)

    def _append_digit(self, digit: str) -> None:
        self._entered_text += digit
        self.display.setText(self._entered_text)

    def get_code(self) -> str:
        return self._entered_text

    def keyPressEvent(self, event):
        # Allow numeric keyboard input
        if event.key() in (
            Qt.Key_0, Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4,
            Qt.Key_5, Qt.Key_6, Qt.Key_7, Qt.Key_8, Qt.Key_9
        ):
            digit = event.text()
            self._append_digit(digit)
            return

        # Backspace support
        if event.key() == Qt.Key_Backspace:
            self._entered_text = self._entered_text[:-1]
            self.display.setText(self._entered_text)
            return

        # Enter = Accept
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return

        # Escape = Cancel
        if event.key() == Qt.Key_Escape:
            self.reject()
            return

        super().keyPressEvent(event)


class OutlinedLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        fm = self.fontMetrics()
        text_width = fm.horizontalAdvance(self.text())
        text_height = fm.height()
        x = (self.width() - text_width) / 2
        y = (self.height() + text_height) / 2 - fm.descent()
        path.addText(x, y, self.font(), self.text())
        pen = QPen(Qt.black, 2)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), self.alignment(), self.text())


class BlurImageButton(QWidget):
    def __init__(self, title: str, img_path: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(220, 160)

        # Normalize path for Qt (use forward slashes)
        safe_img = (img_path or "").replace("\\", "/")
        self._pixmap = QPixmap(safe_img)
        self._callback = None
        self._hovered = False


        # Title label overlay; hidden by default, shown on hover
        self.label = OutlinedLabel(title, self)
        self.label.setAlignment(Qt.AlignCenter)
        font = self.label.font()
        font.setPointSize(18)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setStyleSheet("color: white; background: transparent;")
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.label.setVisible(False)

    def setClickedCallback(self, func):
        self._callback = func

    def enterEvent(self, event):
        if not getattr(self, "enable_hover", True):
            return
        # On hover: show the title text
        self.label.setVisible(True)
        self.label.raise_()
        self._hovered = True
        self.update()
        self.setStyleSheet("border: 3px solid rgba(255, 215, 0, 180);")
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not getattr(self, "enable_hover", True):
            return
        # On leave: hide the title text
        self.label.setVisible(False)
        self._hovered = False
        self.update()
        self.setStyleSheet("")
        super().leaveEvent(event)

    def resizeEvent(self, event):
        self.label.setGeometry(self.rect())
        super().resizeEvent(event)

    def sizeHint(self):
        return QSize(220, 160)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Outer rect (full widget)
        outer_rect = QRectF(0, 0, self.width(), self.height())

        # Extra headroom so glow never clips (top/bottom safe)
        inset_x = 6
        inset_y = 10
        inner_rect = QRectF(
            inset_x,
            inset_y,
            self.width() - inset_x * 2,
            self.height() - inset_y * 2
        )

        radius = 26.0

        # Clip image to inner rounded rect
        clip_path = QPainterPath()
        clip_path.addRoundedRect(inner_rect, radius, radius)
        painter.setClipPath(clip_path)

        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            x_offset = int((self.width() - scaled.width()) / 2)
            y_offset = int((self.height() - scaled.height()) / 2)
            painter.drawPixmap(x_offset, y_offset, scaled)

        painter.setClipping(False)

        # --- Subtle dark overlay on hover (image only) ---
        if getattr(self, "_hovered", False):
            overlay_color = QColor(0, 0, 0, 120)  # semi-transparent black
            painter.setBrush(overlay_color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(inner_rect, radius, radius)

        # --- Neon glow border (drawn INSIDE widget bounds) ---
        glow_path = QPainterPath()
        glow_path.addRoundedRect(inner_rect, radius, radius)

        # Soft outer glow
        glow_pen = QPen(QtGui.QColor(200, 0, 255, 160))
        glow_pen.setWidth(8)
        glow_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(glow_pen)
        painter.drawPath(glow_path)

        # Sharp neon edge
        edge_pen = QPen(QtGui.QColor(255, 0, 255))
        edge_pen.setWidth(4)
        edge_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(edge_pen)
        painter.drawPath(glow_path)

    def mousePressEvent(self, event):
        if self._callback:
            self._callback()




# ------------------------------
# Manager page (simple Windows version)
# ------------------------------


# ------------------------------
# Overlay pages
# ------------------------------

class PendingConfigPage(QWidget):
    """
    Simple overlay shown when no games have been configured for this terminal.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PendingConfigPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("TERMINAL PENDING CONFIGURATION", self)
        font = title.font()
        font.setPointSize(40)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180); "
            "padding: 20px; border-radius: 12px;"
        )
        layout.addWidget(title)

        subtitle = QLabel(
            "This terminal has not yet been configured.\n"
            "Please wait...",
            self,
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: white; font-size: 18px; background-color: transparent;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)



class ManagerPage(QWidget):
    def __init__(self, parent=None, advanced=False):
        super().__init__(parent)
        self.setObjectName("ManagerPageScreen")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        self.advanced_mode = advanced

        # Background image (admin_bg.jpg)
        bg_label = QLabel(self)
        admin_bg = (AIO_ROOT / "kiosk" / "img" / "admin_bg.jpg")
        admin_bg_path = str(admin_bg).replace("\\", "/")
        pix = QPixmap(admin_bg_path)
        bg_label.setPixmap(pix)
        bg_label.setScaledContents(True)
        bg_label.setGeometry(0, 0, self.width(), self.height())
        bg_label.lower()
        self._bg_label = bg_label

        # Title
        title = QLabel("Manager Page", self)
        title_font = title.font()
        title_font.setPointSize(42)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; background-color: transparent;")
        layout.addWidget(title)

        # Local IP
        ip_label = QLabel(f"Local IP: {get_local_ip()}", self)
        ip_label.setAlignment(Qt.AlignCenter)
        ip_label.setStyleSheet("color: white; font-size: 30px; background-color: black; border-radius: 10px;")
        layout.addWidget(ip_label)

        # Application version
        version = "N/A"
        try:
            if VERSION_FILE.exists():
                with VERSION_FILE.open("r", encoding="utf-8") as vf:
                    version_data = json.load(vf)
                    version = version_data.get("version", "N/A")
        except Exception:
            pass
        version_label = QLabel(f"Application Version: {version}", self)
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: white; font-size: 24px; background-color: black; border-radius: 10px;")
        layout.addWidget(version_label)

        # Hardware ID (from win_common.get_client_uuid)
        try:
            hardware_id = get_client_uuid()
        except Exception:
            hardware_id = "N/A"
        uuid_label = QLabel(f"Hardware ID: {hardware_id}", self)
        uuid_label.setAlignment(Qt.AlignCenter)
        uuid_label.setStyleSheet("color: white; font-size: 24px; background-color: black; border-radius: 10px;")
        layout.addWidget(uuid_label)

        # ------------------------------
        # Advanced Mode Visual Section
        # ------------------------------
        if self.advanced_mode:
            advanced_banner = QLabel("⚠ ADVANCED OPTIONS ENABLED ⚠", self)
            banner_font = advanced_banner.font()
            banner_font.setPointSize(24)
            banner_font.setBold(True)
            advanced_banner.setFont(banner_font)
            advanced_banner.setAlignment(Qt.AlignCenter)
            advanced_banner.setStyleSheet(
                "color: black; "
                "background-color: #FFD700; "
                "padding: 12px; "
                "border-radius: 12px;"
            )
            layout.addWidget(advanced_banner)

            advanced_note = QLabel(
                "This terminal is running in Advanced Manager Mode.\n"
                "Use caution when modifying system settings.",
                self,
            )
            advanced_note.setAlignment(Qt.AlignCenter)
            advanced_note.setStyleSheet(
                "color: white; "
                "background-color: rgba(0,0,0,180); "
                "padding: 10px; "
                "border-radius: 10px;"
            )
            advanced_note.setWordWrap(True)
            layout.addWidget(advanced_note)

            # ------------------------------
            # Orientation + Resolution Row
            # ------------------------------
            import win32api
            import win32con
            current = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
            current_w = current.PelsWidth
            current_h = current.PelsHeight
            current_orientation = current.DisplayOrientation

            self._original_w = current_w
            self._original_h = current_h
            self._original_orientation = current_orientation

            # Initialize pending values to current
            self._pending_orientation = current_orientation
            self._pending_resolution = (current_w, current_h)

            from PyQt5.QtWidgets import QComboBox

            dropdown_row = QHBoxLayout()
            dropdown_row.setSpacing(80)

            # Orientation Column
            orientation_col = QVBoxLayout()

            orientation_label = QLabel("Screen Orientation", self)
            orientation_label.setAlignment(Qt.AlignCenter)
            orientation_label.setStyleSheet("color: white; font-size: 20px;")
            orientation_col.addWidget(orientation_label)

            self.orientation_combo = QComboBox(self)
            self.orientation_combo.setFixedWidth(260)
            self.orientation_combo.setStyleSheet("""
                QComboBox {
                    font-size: 18px;
                    padding: 6px;
                    background-color: #333;
                    color: white;
                    border-radius: 6px;
                }
            """)

            orientation_options = [
                ("Landscape", 0),
                ("Portrait", 1),
                ("Landscape (Flipped)", 2),
                ("Portrait (Flipped)", 3),
            ]

            for text, mode in orientation_options:
                self.orientation_combo.addItem(text, mode)

            self.orientation_combo.setCurrentIndex(current_orientation)
            self.orientation_combo.currentIndexChanged.connect(
                lambda i: setattr(self, "_pending_orientation",
                                  self.orientation_combo.itemData(i))
            )

            orientation_col.addWidget(self.orientation_combo, alignment=Qt.AlignCenter)

            # Resolution Column
            resolution_col = QVBoxLayout()

            resolution_label = QLabel("Resolution", self)
            resolution_label.setAlignment(Qt.AlignCenter)
            resolution_label.setStyleSheet("color: white; font-size: 20px;")
            resolution_col.addWidget(resolution_label)

            self.resolution_combo = QComboBox(self)
            self.resolution_combo.setFixedWidth(260)
            self.resolution_combo.setStyleSheet("""
                QComboBox {
                    font-size: 18px;
                    padding: 6px;
                    background-color: #333;
                    color: white;
                    border-radius: 6px;
                }
            """)

            if current_h > current_w:
                resolution_options = [
                    (720, 1280),
                    (1080, 1920),
                    (2160, 3840),
                ]
            else:
                resolution_options = [
                    (1280, 720),
                    (1920, 1080),
                    (3840, 2160),
                ]

            for w, h in resolution_options:
                self.resolution_combo.addItem(f"{w} x {h}", (w, h))

            self.resolution_combo.currentIndexChanged.connect(
                lambda i: setattr(self, "_pending_resolution",
                                  self.resolution_combo.itemData(i))
            )

            resolution_col.addWidget(self.resolution_combo, alignment=Qt.AlignCenter)

            dropdown_row.addLayout(orientation_col)
            dropdown_row.addLayout(resolution_col)

            layout.addLayout(dropdown_row)

            save_btn = QPushButton("Save Display Settings", self)
            save_btn.setStyleSheet("""
                QPushButton {
                    font-size: 18px;
                    padding: 10px 20px;
                    background-color: #FFD700;
                    color: black;
                    border-radius: 10px;
                }
                QPushButton:hover {
                    background-color: #FFEA80;
                }
            """)
            save_btn.clicked.connect(self._confirm_display_changes)
            layout.addWidget(save_btn, alignment=Qt.AlignCenter)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_style = """
            QPushButton {
                font-size: 20px;
                font-weight: bold;
                padding: 10px 20px;
                background-color: #555;
                color: white;
                border-radius: 10px;
            }
            QPushButton:hover { background-color: #777; }
        """

        shutdown_btn = QPushButton("Shutdown", self)
        restart_btn = QPushButton("Restart", self)
        relaunch_btn = QPushButton("Relaunch App", self)
        shutdown_btn.setStyleSheet(btn_style)
        restart_btn.setStyleSheet(btn_style)
        relaunch_btn.setStyleSheet(btn_style)
        shutdown_btn.clicked.connect(self.shutdown_system)
        restart_btn.clicked.connect(self.restart_system)
        relaunch_btn.clicked.connect(self.relaunch_app)

        btn_row.addWidget(shutdown_btn)
        btn_row.addWidget(restart_btn)
        btn_row.addWidget(relaunch_btn)
        layout.addLayout(btn_row)

        # Remote Support button (launch Bomgar client)
        remote_btn = QPushButton("Remote Support", self)
        remote_btn.setStyleSheet("""
            QPushButton {
                font-size: 20px;
                font-weight: bold;
                padding: 10px 20px;
                background-color: #228B22;
                color: white;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #196619;
            }
        """)
        remote_btn.clicked.connect(self._remote_support)
        layout.addWidget(remote_btn, alignment=Qt.AlignCenter)

        # Back button
        back_btn = QPushButton("Return to Game Selection", self)
        back_btn.setStyleSheet(btn_style)
        back_btn.clicked.connect(lambda: self.window().stack.setCurrentWidget(self.window().main_menu))
        layout.addWidget(back_btn, alignment=Qt.AlignCenter)
    def _set_pending_resolution(self, w, h):
        self._pending_resolution = (w, h)

    def _confirm_display_changes(self):
        dialog = QMessageBox(None)
        dialog.setWindowTitle("Confirm Restart")
        dialog.setText(
            "Changing these settings requires a restart of the Terminal.\n\nContinue?"
        )
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dialog.setDefaultButton(QMessageBox.Cancel)

        dialog.setWindowFlags(
            Qt.Dialog |
            Qt.WindowStaysOnTopHint |
            Qt.MSWindowsFixedSizeDialogHint
        )

        dialog.setWindowModality(Qt.ApplicationModal)

        reply = dialog.exec_()

        if reply == QMessageBox.Cancel:
            self._pending_orientation = self._original_orientation
            self._pending_resolution = (self._original_w, self._original_h)
            return

        try:
            import win32api
            import win32con

            devmode = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)

            if hasattr(self, "_pending_orientation"):
                orientation = self._pending_orientation
                if orientation in (1, 3):
                    devmode.PelsWidth, devmode.PelsHeight = devmode.PelsHeight, devmode.PelsWidth
                devmode.DisplayOrientation = orientation

            if hasattr(self, "_pending_resolution"):
                w, h = self._pending_resolution
                devmode.PelsWidth = w
                devmode.PelsHeight = h

            win32api.ChangeDisplaySettings(devmode, 0)

            os.system("shutdown /r /t 0 /f")

        except Exception as e:
            QMessageBox.critical(None, "Display Error", f"Failed to apply display settings:\n{e}")

    def resizeEvent(self, event):
        if hasattr(self, "_bg_label") and self._bg_label is not None:
            self._bg_label.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(event)

    def shutdown_system(self):
        # Windows-friendly shutdown (requires appropriate permissions)
        os.system("shutdown /s /t 5")

    def restart_system(self):
        # Immediate reboot: no delay, force close apps
        os.system("shutdown /r /t 0 /f")

    def relaunch_app(self):
        """
        Relaunch the kiosk via the launcher shell.
        This avoids black screens and respects watchdog + shell replacement.
        """
        try:
            from pathlib import Path
            import os
            import subprocess
            from PyQt5.QtWidgets import QApplication

            # Suppress watchdog relaunch (intentional exit)
            flag = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "allow_exit.flag"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.touch()

            # Launch the launcher (system shell)
            launcher = AIO_ROOT / "launcher" / "launcher.exe"
            if launcher.exists():
                subprocess.Popen([str(launcher)])
            else:
                # Fallback: relaunch multi directly if launcher is missing
                subprocess.Popen([sys.executable, str(AIO_ROOT / "kiosk" / "multi_win.py")])

            # Exit current app cleanly
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to relaunch app:\n{e}")

    def _rotate_screen(self, orientation):
        # Store pending orientation only (do NOT apply immediately)
        self._pending_orientation = orientation

    def _remote_support(self):
        """
        Launch the Bomgar remote support client dropped by the installer into Public Documents\aio.
        """
        exe_name = "bomgar-scc-w0eec30jzfffee5wi1eizdy65hf5yg7jf5zgfyjc40hc90.exe"
        public_root = os.environ.get("PUBLIC", r"C:\Users\Public")
        bomgar_path = Path(public_root) / "Documents" / "aio" / exe_name

        if not bomgar_path.exists():
            QMessageBox.warning(
                self,
                "Remote Support",
                f"Remote support tool not found at:\n{bomgar_path}"
            )
            return

        try:
            subprocess.Popen([str(bomgar_path)], cwd=str(bomgar_path.parent))
            QMessageBox.information(
                self,
                "Remote Support",
                "Remote support tool launched successfully."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Remote Support",
                f"Failed to launch support tool:\n{e}"
            )


# ------------------------------
# Main menu + main window
# ------------------------------


# --- GridMenu page ---
class GridMenu(QWidget):
    def __init__(self, on_game_selected, games, parent=None):
        super().__init__(parent)
        self.on_game_selected = on_game_selected

        layout = QGridLayout(self)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(40)

        cols = 4
        for i, game in enumerate(games):
            btn = BlurImageButton(
                title=game["title"],
                img_path=game.get("img") or "",
                parent=self
            )
            btn.enable_hover = True
            btn.setClickedCallback(lambda g=game: self.on_game_selected(g))
            r = i // cols
            c = i % cols
            layout.addWidget(btn, r, c)


class MainMenu(QWidget):
    def __init__(self, on_game_selected, games_info, parent=None):
        super().__init__(parent)
        self.on_game_selected = on_game_selected
        self.games_info = games_info
        self.setObjectName("MainMenuPage")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 0, 40, 40)
        layout.setSpacing(30)

        # Top stretch (heavier weight to push content further downward)
        layout.addStretch(3)

        self.carousel = CarouselWidget(
            games=self.games_info,
            on_select=self._game_selected,
            parent=self
        )

        layout.addWidget(self.carousel, alignment=Qt.AlignHCenter)

        self.start_btn = QPushButton("Get Started", self)
        self.start_btn.setFixedSize(320, 80)
        self.start_btn.setStyleSheet("""
QPushButton {
    font-size: 28px;
    font-weight: bold;
    background-color: #FFD700;
    color: black;
    border-radius: 14px;
}
QPushButton:hover {
    background-color: #FFEA80;
}
""")
        self.start_btn.clicked.connect(self._go_to_grid)
        layout.addWidget(self.start_btn, alignment=Qt.AlignHCenter)

        # Bottom stretch (lighter weight)
        layout.addStretch(1)

    def _game_selected(self, game: Dict[str, Any]):
        title = game.get("title") or "Unknown"
        log_activity_local(title)
        send_click_to_server(title)
        self.on_game_selected(game)

    def _go_to_grid(self):
        self.window().show_grid_menu()


def is_allowed_url(url: str) -> bool:
    allowed_hosts = [
        "playgd.city",
        "orionstars-vip.com",
        "river777.net",
        "firekirin",
        "pandamaster",
        "ultrapanda",
        "cgweb.app",
        "vblink",
        "playbdd.com",
        "fpplay.mobi",
    ]
    return any(h in url.lower() for h in allowed_hosts)

class MainWindow(QMainWindow):
    def _get_terminal_type(self):
        try:
            if ACTIVATION_FILE.exists():
                with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("terminal_type", "multi")
        except Exception:
            pass
        return "multi"

    def _constrain_window_portrait(self, window_title_hint: str):
        """
        Constrain a launched window to bottom section of portrait display.
        Only used when terminal_type == multi_vert and game is landscape.
        """
        try:
            import win32gui
            import win32con
            import ctypes
            import time

            time.sleep(2)

            user32 = ctypes.windll.user32
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)

            # Only constrain if screen is portrait
            if screen_h <= screen_w:
                return

            game_height = int(screen_h * 0.60)
            y_offset = screen_h - game_height

            def enum_handler(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if window_title_hint.lower() in title.lower():
                        win32gui.SetWindowPos(
                            hwnd,
                            None,
                            0,
                            y_offset,
                            screen_w,
                            game_height,
                            win32con.SWP_NOZORDER
                        )

            win32gui.EnumWindows(enum_handler, None)

        except Exception:
            pass

    def _launch_game_after_delay(self, game: Dict[str, Any]) -> None:
        """
        Actual platform launch logic, called after a short delay so that
        loading.py has time to appear and cover the desktop.
        """
        title = game.get("title") or "Unknown"
        gtype = (game.get("type") or "url").lower().strip()
        target = game.get("target") or ""
        orientation = game.get("orientation", "landscape")

        # EXE-based platforms (Orca, Fire Phoenix, River Sweeps, Tower Link, GDC, etc.)
        if gtype == "exe":
            # Launch native EXE using win_common (already does path + cwd check)
            proc = win_launch_game(game)
            if proc is None:
                QMessageBox.warning(self, "Error", f"Failed to launch {title}.")
                return

            try:
                CURRENT_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                CURRENT_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
            except Exception:
                pass

            if self.terminal_type == "multi_vert" and orientation == "landscape":
                try:
                    self._constrain_window_portrait(title)
                except Exception:
                    pass

            # Exit the multi selection app so only the game + loading UI remain
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return

        # URL-based platforms → launch in external browser full-screen
        url = target
        browser_cmd = None
        title_lower = title.lower()

        # Classic Online: requires Firefox
        if title_lower == "classic online":
            firefox_candidates = [
                r"C:\\Program Files\\Mozilla Firefox\\firefox.exe",
                r"C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
            ]
            for path in firefox_candidates:
                if os.path.exists(path):
                    # Firefox kiosk mode
                    browser_cmd = [path, "-kiosk", url]
                    break
        else:
            # All other URL games → Chrome
            chrome_candidates = [
                r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            ]
            for path in chrome_candidates:
                if os.path.exists(path):
                    # Chrome kiosk mode with PWA install dialog permanently disabled, disposable profile
                    browser_cmd = [
                        path,
                        "--kiosk",
                        f"--user-data-dir={str(CHROME_PROFILE_DIR)}",
                        "--disable-features=DesktopPWAs,WebAppInstall,WebAppIdentityProxy",
                        "--disable-pwa-install",
                        "--disable-infobars",
                        "--disable-extensions",
                        "--disable-pinch",
                        "--disable-save-password-bubble",
                        "--disable-session-crashed-bubble",
                        "--disable-downloads",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-component-update",
                        "--disable-background-networking",
                        "--disable-sync",
                        "--disable-notifications",
                        "--disable-popup-blocking",
                        url,
                    ]
                    break

        if browser_cmd is None:
            # Fallback: if we can't find the browser path, just use default browser without overlay
            win_launch_game(game)
            return

        # Launch the browser in kiosk mode
        try:
            try:
                CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            proc = subprocess.Popen(browser_cmd)
            try:
                CURRENT_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                CURRENT_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
            except Exception:
                pass
            if self.terminal_type == "multi_vert" and orientation == "landscape":
                try:
                    self._constrain_window_portrait(title)
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to launch browser for {title}:\n{e}")
            return

        app = QApplication.instance()
        if app is not None:
            app.quit()
    def __init__(self):
        super().__init__()
        # Register this kiosk menu process with the watchdog
        try:
            pid_file = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "current_pid.txt"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

        self.setWindowTitle("AIO v2 – Multi")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Background GIF
        self.bg_label = QLabel()
        self.bg_label.setScaledContents(True)
        self.bg_label.setStyleSheet("background-color: black;")
        bg_gif = (AIO_ROOT / "kiosk" / "img" / "bg.gif")
        bg_path = str(bg_gif).replace("\\", "/")
        movie = QMovie(bg_path)
        if movie.isValid():
            movie.start()
            self.bg_label.setMovie(movie)
            self._bg_movie = movie
        else:
            self.bg_label.setPixmap(QPixmap(bg_path))

        # Stacked content overlay
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.setStyleSheet("background-color: rgba(0,0,0,0);")
        self.stack.setAttribute(Qt.WA_TranslucentBackground)

        central_widget = QWidget()
        central_widget.setAttribute(Qt.WA_TranslucentBackground)
        layout = QGridLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.bg_label, 0, 0)
        layout.addWidget(self.stack, 0, 0)
        self.setCentralWidget(central_widget)

        # Ad overlay for portrait mode (multi_vert)
        self.ad_overlay = None
        self.terminal_type = self._get_terminal_type()
        if self.terminal_type == "multi_vert":
            self.ad_overlay = AdOverlay(central_widget)
            self.ad_overlay.setGeometry(
                0,
                0,
                self.width(),
                int(self.height() * 0.40)
            )
            self.ad_overlay.raise_()

        # Secret manager tap zone (top-left)
        self._secret_clicks = 0
        from PyQt5.QtCore import QTimer
        self._secret_reset_timer = QTimer(self)
        self._secret_reset_timer.setInterval(10000)
        self._secret_reset_timer.setSingleShot(True)
        self._secret_reset_timer.timeout.connect(self._reset_secret_counter)

        self._secret_btn = QPushButton(central_widget)
        self._secret_btn.setObjectName("SecretManagerTapZone")
        self._secret_btn.setFixedSize(100, 100)
        self._secret_btn.move(0, 0)
        self._secret_btn.setFlat(True)
        self._secret_btn.setFocusPolicy(Qt.NoFocus)
        self._secret_btn.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._secret_btn.clicked.connect(self._on_secret_click)
        self._secret_btn.raise_()

        # Show/hide secret tap zone based on current page
        self.stack.currentChanged.connect(lambda _ix: self._sync_tap_zone_visibility())

        # Inactivity timer: 5 minutes
        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.setInterval(300_000)
        self.inactivity_timer.timeout.connect(self.return_to_main)
        self.inactivity_timer.start()

        # Grid idle timer (10 seconds on grid view)
        self.grid_idle_timer = QTimer(self)
        self.grid_idle_timer.setInterval(10_000)  # 10 seconds
        self.grid_idle_timer.setSingleShot(True)
        self.grid_idle_timer.timeout.connect(self._grid_idle_return)

        # ------------- Initialization block moved from _grid_idle_return -------------
        self.manager_page = None

        self.installEventFilter(self)

        # Games + pages
        if GAMES_FILE.exists():
            self.games = load_games()
        else:
            self.games = []

        if self.games:
            self.main_menu = MainMenu(self.launch_game, self.games, self)
            self.grid_menu = GridMenu(self.launch_game, self.games, self)
            self.stack.addWidget(self.main_menu)
            self.stack.addWidget(self.grid_menu)
        else:
            self.main_menu = PendingConfigPage(self)
            self.stack.addWidget(self.main_menu)

        try:
            send_status_to_server("menu")
        except Exception:
            pass

        # Window size and fullscreen setup
        import ctypes
        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)

        self.setFixedSize(screen_w, screen_h)
        self.move(0, 0)
        self.showFullScreen()
        self._sync_tap_zone_visibility()
    def _grid_idle_return(self):
        # Only return if we are currently on the grid view
        if hasattr(self, "grid_menu") and self.stack.currentWidget() is self.grid_menu:
            self.return_to_main()

    def resizeEvent(self, event):
        self.bg_label.setGeometry(0, 0, self.width(), self.height())
        if hasattr(self, "_secret_btn"):
            self._secret_btn.move(0, 0)
            self._secret_btn.raise_()
        if self.ad_overlay:
            self.ad_overlay.setGeometry(
                0,
                0,
                self.width(),
                int(self.height() * 0.40)
            )
            self.ad_overlay.raise_()
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.KeyPress):
            self.inactivity_timer.start(300_000)

            # Reset grid idle timer if we are on grid view
            if hasattr(self, "grid_menu") and self.stack.currentWidget() is self.grid_menu:
                self.grid_idle_timer.start()

            # Safely handle carousel timers only if they exist
            try:
                if hasattr(self.main_menu, "carousel"):
                    carousel = self.main_menu.carousel
                    if hasattr(carousel, "user_activity_timer"):
                        carousel.user_activity_timer.start()
            except Exception:
                pass

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        # Shift + F7 → Admin access
        if event.key() == Qt.Key_F7 and (event.modifiers() & Qt.ShiftModifier):
            dlg = NumericKeypadDialog("Manager / Admin Login", self)
            if dlg.exec_() == QDialog.Accepted:
                code = dlg.get_code()

                # Full exit to Windows Explorer
                if code == "12251225":
                    try:
                        flag = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "allow_exit.flag"
                        flag.parent.mkdir(parents=True, exist_ok=True)
                        flag.touch()
                        subprocess.Popen(["explorer.exe"])
                        app = QApplication.instance()
                        if app:
                            app.quit()
                    except Exception:
                        pass
                    return

                # Advanced Manager
                elif code == ADVANCED_PIN:
                    self.open_manager_page(advanced=True)
                    return

                # Normal Manager
                elif code == MANAGER_PIN:
                    self.open_manager_page(advanced=False)
                    return

                else:
                    QMessageBox.warning(self, "Access Denied", "Invalid Pin!", QMessageBox.Ok)
            return

        super().keyPressEvent(event)


    def _reset_secret_counter(self):
        self._secret_clicks = 0

    def _on_secret_click(self):
        self._secret_clicks += 1
        self._secret_reset_timer.start()
        if self._secret_clicks >= 6:
            self._secret_reset_timer.stop()
            self._secret_clicks = 0
            dlg = NumericKeypadDialog("Enter Manager Pin", self)
            if dlg.exec_() == QDialog.Accepted and dlg.get_code() == MANAGER_PIN:
                self.open_manager_page()
            else:
                QMessageBox.warning(self, "Access Denied", "Invalid Manager Pin!", QMessageBox.Ok)

    def _sync_tap_zone_visibility(self):
        try:
            on_main = (self.stack.currentWidget() is self.main_menu)
        except Exception:
            on_main = False
        if hasattr(self, "_secret_btn"):
            self._secret_btn.setVisible(bool(on_main))

    def open_manager_page(self, advanced=False):
        if self.manager_page:
            self.stack.removeWidget(self.manager_page)
            self.manager_page.deleteLater()
            self.manager_page = None

        self.manager_page = ManagerPage(self, advanced=advanced)
        self.stack.addWidget(self.manager_page)
        self.stack.setCurrentWidget(self.manager_page)
        self._sync_tap_zone_visibility()

    def return_to_main(self):
        if hasattr(self, "grid_idle_timer"):
            self.grid_idle_timer.stop()
        try:
            send_status_to_server("menu")
        except Exception:
            pass
        self.stack.setCurrentWidget(self.main_menu)
        self._sync_tap_zone_visibility()

    def show_grid_menu(self):
        if hasattr(self, "grid_menu"):
            self.stack.setCurrentWidget(self.grid_menu)
            self.grid_idle_timer.start()
        self._sync_tap_zone_visibility()

    def launch_game(self, game: Dict[str, Any]):
        """
        Launch a game from the multi-game menu.

        Flow:
        - Start loading.py in "launch" mode so it can cover the desktop.
        - Wait a short delay (2.5s) to allow loading UI to appear.
        - Then actually launch the platform and quit multi_win.py.
        """
        title = game.get("title") or "Unknown"
        target = game.get("target") or ""

        try:
            send_status_to_server("in_play")
        except Exception:
            pass

        if not target:
            QMessageBox.warning(self, "Error", f"No target configured for {title}.")
            return

        # Start loading.py in "launch" mode first so it can cover the desktop
        if LOADING_SCRIPT.exists():
            try:
                subprocess.Popen([sys.executable, str(LOADING_SCRIPT), "launch"])
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to launch Loading overlay:\n{e}")
                # We still let the game run even if loading UI fails

        # Use a short delay to ensure the loading UI has time to appear
        delay_ms = 2500  # 2.5 seconds
        QTimer.singleShot(delay_ms, lambda g=game: self._launch_game_after_delay(g))

    # closeEvent override for EXE cleanup is no longer needed and removed.


def main():
    # Basic DPI sanity for Windows
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_DEVICE_PIXEL_RATIO", "1")

    from PyQt5.QtCore import Qt as _Qt
    QApplication.setAttribute(_Qt.AA_DisableHighDpiScaling, True)

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()