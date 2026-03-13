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
from PyQt5.QtCore import QPropertyAnimation, QPoint, QRect
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

# ------------------------------------------------------
# Loading Overlay (animated neon bar)
# ------------------------------------------------------

class LoadingOverlay(QWidget):
    """Dark overlay with centered text and animated neon loading bar."""

    _BG = QColor(10, 10, 30)
    _BAR_CYAN = QColor(0, 200, 255)
    _BAR_PINK = QColor(255, 50, 150)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self._text = "Loading…"
        self._bar_pos = 0.0
        self._bar_dir = 0.02

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._animate)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(0, 0, w, h, self._BG)

        # Centered text
        p.setPen(QColor(255, 255, 255))
        font = QFont("Arial", 32, QFont.Bold)
        p.setFont(font)
        p.drawText(QRectF(0, h * 0.25, w, h * 0.3), Qt.AlignCenter, self._text)

        # Loading bar
        bar_w = int(w * 0.70)
        bar_h = 8
        bar_x = (w - bar_w) // 2
        bar_y = int(h * 0.60)
        radius = bar_h // 2

        # Track
        p.setBrush(QColor(40, 40, 60))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, radius, radius)

        # Sweep indicator
        sweep_w = int(bar_w * 0.30)
        sweep_x = bar_x + int((bar_w - sweep_w) * self._bar_pos)

        # Glow behind sweep
        glow_grad = QtGui.QLinearGradient(sweep_x - 10, 0, sweep_x + sweep_w + 10, 0)
        glow_grad.setColorAt(0.0, QColor(0, 200, 255, 0))
        glow_grad.setColorAt(0.3, QColor(0, 200, 255, 80))
        glow_grad.setColorAt(0.7, QColor(255, 50, 150, 80))
        glow_grad.setColorAt(1.0, QColor(255, 50, 150, 0))
        p.setBrush(glow_grad)
        p.drawRoundedRect(sweep_x - 10, bar_y - 4, sweep_w + 20, bar_h + 8, radius + 2, radius + 2)

        # Main bar gradient
        bar_grad = QtGui.QLinearGradient(sweep_x, 0, sweep_x + sweep_w, 0)
        bar_grad.setColorAt(0.0, self._BAR_PINK)
        bar_grad.setColorAt(1.0, self._BAR_CYAN)
        p.setBrush(bar_grad)
        p.drawRoundedRect(sweep_x, bar_y, sweep_w, bar_h, radius, radius)

        p.end()

    def _animate(self):
        self._bar_pos += self._bar_dir
        if self._bar_pos >= 1.0:
            self._bar_pos = 1.0
            self._bar_dir = -abs(self._bar_dir)
        elif self._bar_pos <= 0.0:
            self._bar_pos = 0.0
            self._bar_dir = abs(self._bar_dir)
        self.update()

    def show_loading(self, text="Loading…"):
        self._text = text
        self._bar_pos = 0.0
        self._bar_dir = 0.02
        self.raise_()
        self.show()
        self._timer.start()

    def hide_loading(self):
        self._timer.stop()
        self.hide()


CAROUSEL_ANIM_MS = 180
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
    def __init__(self, games, on_select, parent=None, *,
                 center_size=None, side_size=None,
                 container_size=None, num_visible=5, gap=20):
        super().__init__(parent)
        self.center_size = center_size or CENTER_SIZE
        self.side_size = side_size or SIDE_SIZE
        self.num_visible = num_visible  # 3 or 5
        self.gap = gap
        cont = container_size or QSize(2200, 700)

        self.setMinimumHeight(cont.height() + 20)
        self.games = games
        self.on_select = on_select
        self.index = 0

        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        self.card_container = QWidget(self)
        existing_layout = self.card_container.layout()
        if existing_layout is not None:
            existing_layout.deleteLater()
        self.card_container.setFixedSize(cont)

        layout.addWidget(self.card_container)

        self._cards_initialized = False

        QTimer.singleShot(0, lambda: self._build_cards(animate=False))

        self.start_attract_rotation()

        # Prevent attribute errors from optional timers
        self.idle_timer = QTimer(self)
        self.user_activity_timer = QTimer(self)

    def _calc_x_offsets(self):
        """Calculate X offset positions for each carousel slot."""
        cx = self.card_container.width() // 2
        GAP = self.gap
        half = self.num_visible // 2
        inner = (self.center_size.width() // 2) + (self.side_size.width() // 2) + GAP

        offsets = {0: 0, -1: -inner, 1: inner}
        if self.num_visible >= 5:
            outer_card_w = int(self.side_size.width() * 0.75)
            outer = inner + (self.side_size.width() // 2) + (outer_card_w // 2) + GAP
            offsets[-2] = -outer
            offsets[2] = outer
            # Off-screen positions for slide animation entry/exit
            offscreen = outer + outer_card_w + abs(GAP)
            offsets[-3] = -offscreen
            offsets[3] = offscreen
        else:
            offscreen = inner + self.side_size.width() + abs(GAP)
            offsets[-2] = -offscreen
            offsets[2] = offscreen
        return offsets

    def _size_for_offset(self, offset):
        """Return (QSize, opacity) for a given carousel slot offset."""
        if offset == CAROUSEL_CENTER_OFFSET:
            return self.center_size, 1.0
        elif abs(offset - CAROUSEL_CENTER_OFFSET) == 1:
            return self.side_size, SIDE_OPACITY
        else:
            return QSize(int(self.side_size.width() * 0.75),
                         int(self.side_size.height() * 0.75)), 0.35

    def _build_cards(self, animate=False, direction=0):
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

        cx = self.card_container.width() // 2
        X_OFFSETS = self._calc_x_offsets()
        half = self.num_visible // 2

        # Anchor cards to container center only (no external lift)
        cy_visual_center = self.card_container.height() // 2

        for i in range(self.num_visible):
            offset = i - half
            idx = (self.index + offset) % len(self.games)
            game = self.games[idx]

            btn = BlurImageButton(
                title=game["title"],
                img_path=game.get("img") or "",
                parent=self.card_container
            )
            btn.enable_hover = False
            btn._callback = None

            size, opacity = self._size_for_offset(offset)
            btn.resize(size)

            if animate and direction != 0:
                # Place at previous position (shifted by direction) for slide-in
                start_slot = offset + direction
                start_size, start_opacity = self._size_for_offset(start_slot)
                btn.resize(start_size)
                btn.setWindowOpacity(start_opacity)
                start_x = cx + X_OFFSETS.get(start_slot, X_OFFSETS.get(
                    3 if start_slot > 0 else -3, 0)) - start_size.width() // 2
                start_y = cy_visual_center - start_size.height() // 2
                btn.move(int(start_x), int(start_y))
            else:
                btn.setWindowOpacity(opacity)
                x = cx + X_OFFSETS[offset] - size.width() // 2
                y = cy_visual_center - size.height() // 2
                btn.move(int(x), int(y))

            btn.show()
            self.buttons.append(btn)

        # Z-order: raise from outermost to center so center is on top
        for i in sorted(range(len(self.buttons)), key=lambda i: -abs(i - half)):
            self.buttons[i].raise_()

        if animate and direction != 0:
            self._animate_cards()

        self._cards_initialized = True

    def _animate_cards(self):
        cx = self.card_container.width() // 2
        X_OFFSETS = self._calc_x_offsets()
        half = self.num_visible // 2
        cy_visual_center = self.card_container.height() // 2

        for i, btn in enumerate(self.buttons):
            offset = i - half
            size, opacity = self._size_for_offset(offset)

            target_x = cx + X_OFFSETS[offset] - size.width() // 2
            target_y = cy_visual_center - size.height() // 2

            # Animate position + size together via geometry
            geo_anim = QPropertyAnimation(btn, b"geometry", self)
            geo_anim.setDuration(CAROUSEL_ANIM_MS)
            geo_anim.setEndValue(
                QRect(int(target_x), int(target_y), size.width(), size.height())
            )
            geo_anim.setEasingCurve(QEasingCurve.OutCubic)
            geo_anim.start()

            # Animate opacity
            if offset != 0:
                fade = QPropertyAnimation(btn, b"windowOpacity", self)
                fade.setDuration(CAROUSEL_ANIM_MS)
                fade.setEndValue(opacity)
                fade.start()
            else:
                btn.setWindowOpacity(1.0)

        # Z-order: raise from outermost to center so center is on top
        for i in sorted(range(len(self.buttons)), key=lambda i: -abs(i - half)):
            self.buttons[i].raise_()

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
        self._build_cards(animate=True, direction=1)

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
        # Find the visually centered button
        half = self.num_visible // 2
        if len(self.buttons) > half:
            center = self.buttons[half]
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
        self._build_cards(animate=True, direction=1)

    def prev_game(self):
        self.idle_timer.stop()
        self.user_activity_timer.start()
        self.index = (self.index - 1) % len(self.games)
        self._build_cards(animate=True, direction=-1)

from win_common import (
    load_games,
    save_games,
    sync_config_from_server,
    persist_synced_config,
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
        self.setWordWrap(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fm = self.fontMetrics()
        flags = int(self.alignment()) | Qt.TextWordWrap
        text_rect = painter.boundingRect(self.rect(), flags, self.text())

        # Centre the text block vertically
        dy = (self.height() - text_rect.height()) / 2 - text_rect.y()
        painter.translate(0, dy)

        # Black outline via QPainterPath per line
        path = QPainterPath()
        line_y = text_rect.y()
        for line in self.text().split('\n') if '\n' in self.text() else [None]:
            # Let Qt do the word-wrap layout; draw outline for each wrapped line
            pass

        # Simpler approach: draw text offset in 8 directions for outline
        pen = QPen(Qt.black, 2)
        painter.setPen(pen)
        for dx in (-2, 0, 2):
            for dy2 in (-2, 0, 2):
                if dx == 0 and dy2 == 0:
                    continue
                painter.drawText(self.rect().adjusted(dx, dy2, dx, dy2), flags, self.text())

        # Foreground text
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), flags, self.text())


class BlurImageButton(QWidget):
    def __init__(self, title: str, img_path: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(100, 140)

        # Normalize path for Qt (use forward slashes)
        safe_img = (img_path or "").replace("\\", "/")
        self._pixmap = QPixmap(safe_img)
        self._callback = None
        self._hovered = False


        # Title label overlay; hidden by default, shown on hover
        self.label = OutlinedLabel(title, self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
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
        # Inset label so long names word-wrap inside the button
        pad = 10
        self.label.setGeometry(pad, pad, self.width() - pad * 2, self.height() - pad * 2)
        super().resizeEvent(event)

    def sizeHint(self):
        return QSize(220, 220)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        # Keep cards roughly 4:3 aspect ratio so logos don't look smooshed
        return int(w * 3 / 4)

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

        # Dark background fill so no empty space shows around fitted logos
        painter.save()
        painter.setBrush(QColor(15, 10, 30))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(inner_rect, radius, radius)
        painter.restore()

        if not self._pixmap.isNull():
            target_size = QSize(
                max(1, int(inner_rect.width())),
                max(1, int(inner_rect.height()))
            )
            scaled = self._pixmap.scaled(
                target_size,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            )
            painter.drawPixmap(int(inner_rect.x()), int(inner_rect.y()), scaled)

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
        commit_sha = ""
        try:
            if VERSION_FILE.exists():
                with VERSION_FILE.open("r", encoding="utf-8") as vf:
                    version_data = json.load(vf)
                    version = version_data.get("version", "N/A")
                    sha = version_data.get("commit_sha", "")
                    if sha:
                        commit_sha = sha[:7]
        except Exception:
            pass
        ver_text = f"Application Version: {version}"
        if commit_sha:
            ver_text += f"  ({commit_sha})"
        version_label = QLabel(ver_text, self)
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
    GAMES_PER_PAGE = 12
    COLS = 4

    def __init__(self, on_game_selected, games, parent=None):
        super().__init__(parent)
        self.on_game_selected = on_game_selected
        self.games = games
        self.current_page = 0
        self.total_pages = max(1, -(-len(games) // self.GAMES_PER_PAGE))  # ceil div

        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(10)

        # Pre-build all pages in a stacked widget
        self.page_stack = QStackedWidget(self)
        self.page_stack.setAttribute(Qt.WA_TranslucentBackground)
        for page_idx in range(self.total_pages):
            page_widget = QWidget(self.page_stack)
            page_widget.setAttribute(Qt.WA_TranslucentBackground)
            grid = QGridLayout(page_widget)
            grid.setContentsMargins(30, 20, 30, 10)
            grid.setSpacing(16)

            start = page_idx * self.GAMES_PER_PAGE
            page_games = self.games[start:start + self.GAMES_PER_PAGE]
            for i, game in enumerate(page_games):
                btn = BlurImageButton(
                    title=game["title"],
                    img_path=game.get("img") or "",
                    parent=page_widget
                )
                btn.enable_hover = True
                btn.setClickedCallback(lambda g=game: self.on_game_selected(g))
                grid.addWidget(btn, i // self.COLS, i % self.COLS)

            # Give each used row equal stretch; push remainder to bottom
            rows_used = (len(page_games) + self.COLS - 1) // self.COLS
            for r in range(rows_used):
                grid.setRowStretch(r, 1)
            if rows_used < 4:
                grid.setRowStretch(rows_used, 0)  # don't stretch empty row

            self.page_stack.addWidget(page_widget)

        outer.addWidget(self.page_stack, 1)

        # Navigation row
        if self.total_pages > 1:
            nav_row = QHBoxLayout()
            nav_row.setSpacing(20)

            arrow_style = """
                QPushButton {
                    font-size: 22px; font-weight: bold; padding: 10px 24px;
                    background-color: rgba(255, 215, 0, 200); color: black;
                    border-radius: 12px; min-width: 80px;
                }
                QPushButton:hover { background-color: #FFEA80; }
                QPushButton:disabled { background-color: rgba(100, 100, 100, 150); color: #666; }
            """

            self.prev_btn = QPushButton("\u25C0  Prev", self)
            self.prev_btn.setStyleSheet(arrow_style)
            self.prev_btn.clicked.connect(self._prev_page)

            self.page_label = QLabel("", self)
            self.page_label.setAlignment(Qt.AlignCenter)
            self.page_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")

            self.next_btn = QPushButton("Next  \u25B6", self)
            self.next_btn.setStyleSheet(arrow_style)
            self.next_btn.clicked.connect(self._next_page)

            nav_row.addStretch()
            nav_row.addWidget(self.prev_btn)
            nav_row.addWidget(self.page_label)
            nav_row.addWidget(self.next_btn)
            nav_row.addStretch()
            outer.addLayout(nav_row)

        self._update_nav()

    def _update_nav(self):
        self.page_stack.setCurrentIndex(self.current_page)
        if self.total_pages > 1:
            self.page_label.setText(f"{self.current_page + 1} / {self.total_pages}")

    def _prev_page(self):
        self.current_page = (self.current_page - 1) % self.total_pages
        self._update_nav()

    def _next_page(self):
        self.current_page = (self.current_page + 1) % self.total_pages
        self._update_nav()


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
        Actual platform launch logic, called after the loading overlay appears.
        Hides the Qt window and waits for the game process to exit, then
        returns to the main menu.
        """
        title = game.get("title") or "Unknown"
        gtype = (game.get("type") or "url").lower().strip()
        target = game.get("target") or ""
        orientation = game.get("orientation", "landscape")

        proc = None

        # EXE-based platforms
        if gtype == "exe":
            proc = win_launch_game(game)
            if proc is None:
                self._loading_overlay.hide_loading()
                self.stack.show()
                QMessageBox.warning(self, "Error", f"Failed to launch {title}.")
                return

        else:
            # URL-based platforms → launch in external browser full-screen
            url = target
            browser_cmd = None
            title_lower = title.lower()

            if title_lower == "classic online":
                firefox_candidates = [
                    r"C:\Program Files\Mozilla Firefox\firefox.exe",
                    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
                ]
                for path in firefox_candidates:
                    if os.path.exists(path):
                        browser_cmd = [path, "-kiosk", url]
                        break
            else:
                chrome_candidates = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                ]
                for path in chrome_candidates:
                    if os.path.exists(path):
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
                win_launch_game(game)
                self._loading_overlay.hide_loading()
                self.stack.show()
                return

            try:
                try:
                    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                proc = subprocess.Popen(browser_cmd)
            except Exception as e:
                self._loading_overlay.hide_loading()
                self.stack.show()
                QMessageBox.critical(self, "Error", f"Failed to launch browser for {title}:\n{e}")
                return

        # Save PID for watchdog
        if proc:
            try:
                CURRENT_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                CURRENT_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
            except Exception:
                pass

        # Hide loading + Qt window; game takes over the screen
        self._loading_overlay.hide_loading()
        self.hide()

        # Show floating TOPMOST return button over the game
        self._show_game_return_button()

        # Poll for game exit, then return to menu
        self._game_proc = proc
        self._game_poll_timer = QTimer(self)
        self._game_poll_timer.setInterval(2000)
        self._game_poll_timer.timeout.connect(self._check_game_exited)
        self._game_poll_timer.start()

    def _show_game_return_button(self):
        """Show a floating TOPMOST return button over the fullscreen game."""
        old = getattr(self, '_game_return_win', None)
        if old:
            try:
                old.deleteLater()
            except Exception:
                pass

        btn_win = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        btn_win.setAttribute(Qt.WA_TranslucentBackground)
        btn_win.setGeometry(10, 10, 500, 80)

        btn = QPushButton("Return", btn_win)
        btn.setFixedSize(160, 60)
        btn.move(10, 10)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                font-size: 18px;
                font-weight: bold;
                border-radius: 30px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        btn.enterEvent = lambda e, b=btn: (
            b.setText("Return to Platform Selection"),
            b.setFixedSize(380, 60),
        )
        btn.leaveEvent = lambda e, b=btn: (
            b.setText("Return"),
            b.setFixedSize(160, 60),
        )
        btn.clicked.connect(self._kill_game_and_return)

        btn_win.show()
        self._game_return_win = btn_win
        self._raise_return_topmost()

        # Re-assert TOPMOST every 500ms (D3D fullscreen games steal Z-order)
        self._return_raise_timer = QTimer(self)
        self._return_raise_timer.setInterval(500)
        self._return_raise_timer.timeout.connect(self._raise_return_topmost)
        self._return_raise_timer.start()

    def _raise_return_topmost(self):
        """Push the return-button window above all others (including D3D)."""
        btn_win = getattr(self, '_game_return_win', None)
        if not btn_win:
            return
        try:
            import win32gui
            import win32con
            hwnd = int(btn_win.winId())
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
                | win32con.SWP_SHOWWINDOW
            )
        except Exception:
            pass

    def _hide_game_return_button(self):
        """Remove the floating return button and stop its raise timer."""
        timer = getattr(self, '_return_raise_timer', None)
        if timer:
            timer.stop()
            self._return_raise_timer = None

        btn_win = getattr(self, '_game_return_win', None)
        if btn_win:
            try:
                btn_win.hide()
                btn_win.deleteLater()
            except Exception:
                pass
            self._game_return_win = None

    def _kill_game_and_return(self):
        """Kill the running game process and return to the menu."""
        proc = getattr(self, '_game_proc', None)
        if proc:
            # Kill entire process tree (Chrome/Firefox have many children)
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:
                pass
            self._game_proc = None

        # Also kill any lingering browser/game processes by name
        for exe in ("chrome.exe", "firefox.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/IM", exe, "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

        # Brief pause so windows actually close before we show the menu
        QTimer.singleShot(500, self._return_to_menu)

    def _check_game_exited(self):
        """Poll whether the launched game process has exited."""
        proc = getattr(self, '_game_proc', None)
        if proc is None or proc.poll() is not None:
            self._game_proc = None
            self._return_to_menu()

    def _return_to_menu(self):
        """Common logic: stop polling, hide return button, show menu."""
        if hasattr(self, '_game_poll_timer'):
            self._game_poll_timer.stop()

        self._hide_game_return_button()

        try:
            send_status_to_server("menu")
        except Exception:
            pass

        # Show menu again
        self.stack.show()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
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
        self.grid_idle_timer.setInterval(30_000)  # 30 seconds
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

        # --- Config sync timer (check server every 60 seconds) ---
        self._config_sync_timer = QTimer(self)
        self._config_sync_timer.setInterval(60_000)
        self._config_sync_timer.timeout.connect(self._on_config_sync)
        self._config_sync_timer.start()
        self._sync_worker = None

        # Window size and fullscreen setup
        import ctypes
        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)

        # Loading overlay (covers entire screen for horizontal mode)
        central = self.centralWidget()
        self._loading_overlay = LoadingOverlay(central)
        self._loading_overlay.setFixedSize(screen_w, screen_h)
        self._loading_overlay.move(0, 0)
        self._loading_overlay.hide()

        self.setFixedSize(screen_w, screen_h)
        self.move(0, 0)
        self.showFullScreen()
        self._sync_tap_zone_visibility()

    # --------------------------------------------------
    # Periodic config sync
    # --------------------------------------------------

    def _on_config_sync(self):
        """Start background config sync (runs HTTP request off main thread)."""
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return  # Previous sync still in progress

        from PyQt5.QtCore import QThread, pyqtSignal

        class _Worker(QThread):
            sync_complete = pyqtSignal(dict)
            def run(self_worker):
                try:
                    result = sync_config_from_server()
                    self_worker.sync_complete.emit(result or {})
                except Exception:
                    self_worker.sync_complete.emit({})

        self._sync_worker = _Worker(self)
        self._sync_worker.sync_complete.connect(self._handle_sync_result)
        self._sync_worker.start()

    def _handle_sync_result(self, result: dict):
        """Process config sync result on the main thread."""
        if not result:
            return

        # Terminal type changed → restart through activation_win.py
        if result.get("changed_terminal_type"):
            persist_synced_config(result)
            self._restart_kiosk()
            return

        # Games changed → persist and rebuild UI
        if result.get("changed_games"):
            persist_synced_config(result)
            self._apply_new_games(result.get("games") or [])

    def _apply_new_games(self, new_games: list):
        """Rebuild MainMenu and GridMenu with a new game list."""
        # Remove old widgets from stack
        if hasattr(self, 'grid_menu'):
            self.stack.removeWidget(self.grid_menu)
            self.grid_menu.deleteLater()
            del self.grid_menu
        self.stack.removeWidget(self.main_menu)
        self.main_menu.deleteLater()

        self.games = new_games

        if self.games:
            self.main_menu = MainMenu(self.launch_game, self.games, self)
            self.grid_menu = GridMenu(self.launch_game, self.games, self)
            self.stack.addWidget(self.main_menu)
            self.stack.addWidget(self.grid_menu)
            self.stack.setCurrentWidget(self.main_menu)
        else:
            self.main_menu = PendingConfigPage(self)
            self.stack.addWidget(self.main_menu)
            self.stack.setCurrentWidget(self.main_menu)

        self._sync_tap_zone_visibility()

    def _restart_kiosk(self):
        """Restart kiosk pipeline via activation_win.py (e.g. terminal_type changed)."""
        activation_script = AIO_ROOT / "kiosk" / "activation_win.py"
        try:
            flag = Path(os.environ.get("PROGRAMDATA", r"C:\\ProgramData")) / "aio" / "config" / "allow_exit.flag"
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.touch()
            subprocess.Popen([sys.executable, str(activation_script)])
            app = QApplication.instance()
            if app:
                app.quit()
        except Exception:
            pass

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
        - Show built-in loading overlay with animated neon bar.
        - Hide the game selection UI.
        - Wait a short delay, then launch the platform.
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

        # Hide selection UI, show loading overlay
        self.stack.hide()
        self._loading_overlay.show_loading(f"Loading {title}…")

        # Short delay then launch
        QTimer.singleShot(1500, lambda g=game: self._launch_game_after_delay(g))

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