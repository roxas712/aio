#!/usr/bin/env python3

"""
Windows Vertical Multi Mode
---------------------------------
Architecture:
- Qt app remains fullscreen on 1080x1920 portrait display
- Top 60% (1080x1152) = Ad loop widget (Qt layer)
- Bottom 40% (1080x768) = Game selection UI (carousel + grid)
- Landscape games are constrained to bottom 40%
- Vertical games take full screen (ads hidden)
"""

import sys
import os
import json
import subprocess
from pathlib import Path

# --- Logging setup ---
import logging
import psutil

LOG_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(LOG_DIR / "multi_vert_debug.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def log_debug(message: str):
    print(message)
    logging.info(message)

# --- Required for stable minimized-launch model ---
import win32gui
import win32con
import win32process

from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import (
    QIcon, QImage, QPainter, QColor, QPixmap,
    QLinearGradient, QRadialGradient, QFont, QPen, QBrush,
)
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QApplication, QSizePolicy, QSpacerItem,
)

import ctypes


# Reuse existing multi implementation
from multi_win import MainWindow, CarouselWidget, CURRENT_PID_FILE
from win_common import (
    AIO_ROOT, PROGRAMDATA_ROOT, VERSION_FILE,
    launch_game as win_launch_game,
    get_local_ip, get_client_uuid, get_terminal_name, send_status_to_server,
    clear_pending_restart, force_portrait,
)

# --- Game PID file for vertical mode ---
GAME_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "game_pid.txt"
CHROME_PROFILE_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "chrome_profile"
FIREFOX_PROFILE_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "firefox_profile"

# Ad/game split ratio
AD_RATIO = 0.60
GAME_RATIO = 0.40


# ------------------------------------------------------
# Neon Divider
# ------------------------------------------------------

class NeonDivider(QWidget):
    """Glowing cyan neon line used as a visual separator."""

    TOTAL_H = 14  # total widget height (glow region)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid_y = h / 2.0

        # Black background to cut cleanly between ad and game
        p.fillRect(0, 0, w, h, QColor(0, 0, 0))

        # Soft outer glow layers
        for i, alpha in enumerate([30, 50, 70]):
            inset = (3 - i)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 200, 255, alpha))
            p.drawRect(0, int(mid_y) - inset, w, inset * 2)

        # Bright core line
        p.setPen(QPen(QColor(0, 240, 255, 255), 2))
        p.drawLine(0, int(mid_y), w, int(mid_y))
        p.end()


# ------------------------------------------------------
# Loading Overlay
# ------------------------------------------------------

class LoadingOverlay(QWidget):
    """Dark overlay with centered text and animated neon loading bar."""

    _BG = QColor(10, 10, 30)          # dark navy
    _BAR_CYAN = QColor(0, 200, 255)   # neon cyan for bar
    _BAR_PINK = QColor(255, 50, 150)  # neon pink accent

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.hide()

        self._text = "Loading..."
        self._bar_pos = 0.0   # 0.0 – 1.0, sweeps back and forth
        self._bar_dir = 0.02  # step per tick

        # Animation timer
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(30)
        self._anim_timer.timeout.connect(self._animate)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.fillRect(self.rect(), self._BG)

        # Scale font size to overlay height (baseline: 1536px game area)
        font_sz = max(28, int(h * 0.04))
        font = QFont("Arial", font_sz, QFont.Bold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))

        # --- Centered text + bar at vertical center of overlay ---
        text_rect_h = int(h * 0.15)
        center_y = int(h * 0.45)
        text_y = center_y - text_rect_h
        p.drawText(0, text_y, w, text_rect_h, Qt.AlignHCenter | Qt.AlignVCenter, self._text)

        # --- Loading bar ---
        bar_w = int(w * 0.70)
        bar_h = max(6, int(h * 0.008))
        bar_x = (w - bar_w) // 2
        bar_y = center_y + int(h * 0.02)

        # Track background (dark grey rounded rect)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(40, 40, 60))
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 4, 4)

        # Glowing sweep indicator (slides back and forth)
        sweep_w = int(bar_w * 0.30)
        sweep_x = bar_x + int(self._bar_pos * (bar_w - sweep_w))

        # Glow behind the sweep
        glow_grad = QLinearGradient(sweep_x - 10, 0, sweep_x + sweep_w + 10, 0)
        glow_grad.setColorAt(0.0, QColor(0, 200, 255, 0))
        glow_grad.setColorAt(0.3, QColor(0, 200, 255, 40))
        glow_grad.setColorAt(0.5, QColor(0, 200, 255, 80))
        glow_grad.setColorAt(0.7, QColor(0, 200, 255, 40))
        glow_grad.setColorAt(1.0, QColor(0, 200, 255, 0))
        p.setBrush(QBrush(glow_grad))
        p.drawRoundedRect(sweep_x - 10, bar_y - 6, sweep_w + 20, bar_h + 12, 6, 6)

        # Sweep bar (gradient from pink to cyan)
        bar_grad = QLinearGradient(sweep_x, 0, sweep_x + sweep_w, 0)
        bar_grad.setColorAt(0.0, self._BAR_PINK)
        bar_grad.setColorAt(1.0, self._BAR_CYAN)
        p.setBrush(QBrush(bar_grad))
        p.drawRoundedRect(sweep_x, bar_y, sweep_w, bar_h, 4, 4)

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

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def show_loading(self, text="Loading..."):
        self._text = text
        self._bar_pos = 0.0
        self._bar_dir = 0.02
        self.raise_()
        self.show()
        self._anim_timer.start()

    def hide_loading(self):
        self._anim_timer.stop()
        self.hide()


# ------------------------------------------------------
# Volume Button (ported from V1.17 vert.py)
# ------------------------------------------------------

class VolumeButton(QPushButton):
    VOLUME_LEVELS = [
        (0, "vol_mute.png"),
        (25, "vol_25.png"),
        (60, "vol_60.png"),
        (100, "vol_100.png"),
    ]

    def __init__(self, on_volume_changed=None, parent=None):
        super().__init__(parent)
        self._on_volume_changed = on_volume_changed
        self._volume_index = 3  # Default to 100%
        self.setFixedSize(60, 60)
        self.setFlat(True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._update_icon()
        self.clicked.connect(self._cycle_volume)
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        self.setFixedSize(70, 70)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        self.setFixedSize(60, 60)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        size = self.size()
        diameter = min(size.width(), size.height()) - 4
        color = QColor("#a7a7a7") if self._hovered else QColor("#888888")
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(
            (size.width() - diameter) // 2,
            (size.height() - diameter) // 2,
            diameter, diameter
        )
        super().paintEvent(event)

    def _cycle_volume(self):
        self._volume_index = (self._volume_index + 1) % len(self.VOLUME_LEVELS)
        self._update_icon()
        if self._on_volume_changed:
            self._on_volume_changed(self.current_volume())

    def _update_icon(self):
        _, icon_file = self.VOLUME_LEVELS[self._volume_index]
        icon_path = AIO_ROOT / "kiosk" / "img" / icon_file
        if icon_path.exists():
            self.setIcon(QIcon(str(icon_path).replace("\\", "/")))
            self.setIconSize(QSize(50, 50))

    def current_volume(self):
        return self.VOLUME_LEVELS[self._volume_index][0]


# ------------------------------------------------------
# Ad Loop Widget (Top 60%)
# ------------------------------------------------------

class AdLoopWidget(QWidget):
    """Ad loop widget for the top 60% of vertical display.

    Plays .mp4 videos via OpenCV (FFmpeg backend — no DirectShow) and
    also supports .jpg/.png/.bmp image ads. Videos loop continuously;
    multiple media files rotate in sequence.
    Falls back to branded image if no ads are found or cv2 is unavailable.
    """

    IMAGE_SLIDE_MS = 8000  # 8 seconds per image slide

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: black;")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._layout.addWidget(self._label)

        self._media_files = []   # list of Paths (.mp4, .jpg, etc.)
        self._current_idx = 0
        self._cap = None         # cv2.VideoCapture (or None)
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._read_frame)
        self._slide_timer = QTimer(self)
        self._slide_timer.timeout.connect(self._next_media)
        self._volume = 100
        self._paused = False
        self._cv2 = None  # lazy import

    def _try_import_cv2(self):
        if self._cv2 is not None:
            return True
        try:
            import cv2
            self._cv2 = cv2
            log_debug("[AD] OpenCV loaded successfully")
            return True
        except ImportError:
            log_debug("[AD] OpenCV (cv2) not available — video playback disabled")
            return False

    def load_ads(self, folder_path: Path):
        """Scan folder for videos and images to use as ad rotation."""
        folder_path.mkdir(parents=True, exist_ok=True)

        has_cv2 = self._try_import_cv2()

        # Collect all supported media files
        media = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp"):
            media.extend(folder_path.glob(ext))
        if has_cv2:
            for ext in ("*.mp4", "*.mov", "*.avi", "*.mkv"):
                media.extend(folder_path.glob(ext))
        # If both .mp4 and .mov exist for the same name, drop the .mp4
        mov_stems = {m.stem for m in media if m.suffix == '.mov'}
        media = [m for m in media if not (m.suffix == '.mp4' and m.stem in mov_stems)]
        media = list(sorted(media))

        if media:
            self._media_files = media
            self._current_idx = 0
            vid_exts = {'.mp4', '.mov', '.avi', '.mkv'}
            log_debug(f"[AD] {len(media)} ad(s) found ({sum(1 for m in media if m.suffix in vid_exts)} video): {[m.name for m in media]}")
            # Defer playback start so fullscreen geometry settles first
            QTimer.singleShot(1000, self._play_current)
        else:
            log_debug("[AD] No ads found, showing branded fallback")
            self._show_branded_fallback()

    def _play_current(self):
        """Start playing the current media item."""
        self._frame_timer.stop()
        self._slide_timer.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        path = self._media_files[self._current_idx]

        if path.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv"):
            self._play_video(path)
        else:
            self._show_image(path)

    def _play_video(self, path: Path):
        """Open video with OpenCV and start frame timer."""
        cv2 = self._cv2
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            log_debug(f"[AD] Failed to open video: {path.name}")
            self._next_media()
            return

        self._cap = cap
        vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        self._frame_timer.start(int(1000 / fps))
        log_debug(f"[AD] Playing video: {path.name} ({vid_w}x{vid_h} @ {fps:.0f} fps)")
        log_debug(f"[AD] Widget size: {self.width()}x{self.height()}, "
                  f"label size: {self._label.width()}x{self._label.height()}")
        self._frame_count = 0

    def _read_frame(self):
        """Read one frame from the video, resize to widget, and display."""
        if self._cap is None or self._paused:
            return

        ret, frame = self._cap.read()
        if not ret:
            # Video ended — loop or advance to next media
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            if len(self._media_files) > 1:
                self._next_media()
                return
            else:
                # Single video — loop it
                ret, frame = self._cap.read()
                if not ret:
                    return

        # Use screen geometry for target size — self.width() can return
        # DPI-scaled values (e.g. 2360 instead of 1080) on Windows
        screen = self.window().screen() if self.window() else None
        if screen:
            sg = screen.geometry()
            target_w = sg.width()
            target_h = int(sg.height() * AD_RATIO)
        else:
            target_w = self.width()
            target_h = self.height()

        # Log first frame dimensions for debugging
        self._frame_count = getattr(self, '_frame_count', 0) + 1
        if self._frame_count == 1:
            log_debug(f"[AD] First frame: video={frame.shape[1]}x{frame.shape[0]}, "
                      f"target={target_w}x{target_h}, "
                      f"widget={self.width()}x{self.height()}")

        if target_w > 0 and target_h > 0:
            frame = self._cv2.resize(frame, (target_w, target_h),
                                     interpolation=self._cv2.INTER_AREA)

        h, w, ch = frame.shape
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        # Use strides for correct byte alignment; .copy() ensures data ownership
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        self._label.setPixmap(pix)
        # Mirror to TOPMOST ad overlay if active (for EXE game overlay)
        mirror = getattr(self, '_topmost_mirror_label', None)
        if mirror:
            try:
                mirror.setPixmap(pix)
            except Exception:
                pass

    def _show_image(self, path: Path):
        """Display a static image ad."""
        pix = QPixmap(str(path).replace("\\", "/"))
        if pix.isNull():
            log_debug(f"[AD] Failed to load image: {path.name}")
            self._next_media()
            return
        self._label.setPixmap(pix)
        # Auto-advance after interval if there are multiple media files
        if len(self._media_files) > 1:
            self._slide_timer.start(self.IMAGE_SLIDE_MS)

    def _next_media(self):
        """Advance to the next media file in rotation."""
        if not self._media_files:
            return
        self._current_idx = (self._current_idx + 1) % len(self._media_files)
        self._play_current()

    def _show_branded_fallback(self):
        """Show admin_bg.jpg or gold text when no ads are available."""
        logo_path = AIO_ROOT / "kiosk" / "img" / "admin_bg.jpg"
        if logo_path.exists():
            pix = QPixmap(str(logo_path).replace("\\", "/"))
            self._label.setPixmap(pix)
        else:
            self._label.setText("AIO")
            self._label.setStyleSheet(
                "color: #FFD700; font-size: 72px; font-weight: bold; background-color: black;"
            )

    # --- Public API (called by VerticalMultiWindow) ---

    def set_volume(self, vol):
        self._volume = vol
        # OpenCV video is silent — audio can be added later via separate lib

    def pause(self):
        self._paused = True
        self._frame_timer.stop()
        self._slide_timer.stop()

    def resume(self):
        self._paused = False
        if self._cap is not None:
            fps = self._cap.get(self._cv2.CAP_PROP_FPS) or 30
            self._frame_timer.start(int(1000 / fps))
        elif len(self._media_files) > 1:
            self._slide_timer.start(self.IMAGE_SLIDE_MS)


# ------------------------------------------------------
# Compact Manager Page for Vertical Mode
# ------------------------------------------------------

class VerticalManagerPage(QWidget):
    def __init__(self, parent=None, advanced=False):
        super().__init__(parent)
        self.setObjectName("VerticalManagerPage")

        # Load admin_bg.jpg for paintEvent background
        bg_path = AIO_ROOT / "kiosk" / "img" / "admin_bg.jpg"
        self._bg_pixmap = None
        if bg_path.exists():
            self._bg_pixmap = QPixmap(str(bg_path).replace("\\", "/"))
        else:
            self.setStyleSheet("background-color: #1a1a2e;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 15)
        layout.setSpacing(8)

        # Spacer to push content below the ad overlay area
        win = parent if parent else self.window()
        if hasattr(win, '_screen_size'):
            _sw, _sh = win._screen_size()
        else:
            _sh = 1920
        ad_h = int(_sh * AD_RATIO)
        layout.addSpacerItem(QSpacerItem(0, ad_h, QSizePolicy.Minimum, QSizePolicy.Fixed))

        # Title
        title = QLabel("Manager", self)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

        self.advanced_mode = advanced

        if advanced:
            warn = QLabel("ADVANCED OPTIONS ENABLED", self)
            warn.setAlignment(Qt.AlignCenter)
            warn.setStyleSheet(
                "color: yellow; font-size: 12px; font-weight: bold; "
                "background-color: rgba(255,165,0,50); padding: 4px; border-radius: 4px;"
            )
            layout.addWidget(warn)

        # Info section
        info_style = (
            "color: white; font-size: 13px; "
            "background-color: rgba(0,0,0,150); padding: 6px; border-radius: 6px;"
        )

        ip_label = QLabel(f"IP: {get_local_ip()}", self)
        ip_label.setAlignment(Qt.AlignCenter)
        ip_label.setStyleSheet(info_style)
        layout.addWidget(ip_label)

        t_name = get_terminal_name() or "N/A"
        self._admin_terminal_label = QLabel(f"Terminal: {t_name}", self)
        self._admin_terminal_label.setAlignment(Qt.AlignCenter)
        self._admin_terminal_label.setStyleSheet(info_style)
        layout.addWidget(self._admin_terminal_label)

        version = "N/A"
        commit_sha = ""
        try:
            if VERSION_FILE.exists():
                with VERSION_FILE.open("r", encoding="utf-8") as vf:
                    vdata = json.load(vf)
                    version = vdata.get("version", "N/A")
                    sha = vdata.get("commit_sha", "")
                    if sha:
                        commit_sha = sha[:7]
        except Exception:
            pass
        ver_text = f"Version: {version}"
        if commit_sha:
            ver_text += f" ({commit_sha})"
        ver_label = QLabel(ver_text, self)
        ver_label.setAlignment(Qt.AlignCenter)
        ver_label.setStyleSheet(info_style)
        layout.addWidget(ver_label)

        hw_id = get_client_uuid() or "N/A"
        hw_label = QLabel(f"HW ID: {hw_id}", self)
        hw_label.setWordWrap(True)
        hw_label.setAlignment(Qt.AlignCenter)
        hw_label.setStyleSheet(info_style)
        layout.addWidget(hw_label)

        # Advanced: Orientation + Resolution controls
        if self.advanced_mode:
            import win32api
            import win32con
            from PyQt5.QtWidgets import QComboBox

            current = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
            current_w = current.PelsWidth
            current_h = current.PelsHeight
            current_orientation = current.DisplayOrientation

            self._original_w = current_w
            self._original_h = current_h
            self._original_orientation = current_orientation
            self._pending_orientation = current_orientation
            self._pending_resolution = (current_w, current_h)

            combo_style = """
                QComboBox {
                    font-size: 14px; padding: 8px 12px;
                    background-color: rgba(0, 0, 0, 180);
                    color: #FFD700;
                    border: 2px solid #FFD700;
                    border-radius: 8px;
                    font-weight: bold;
                }
                QComboBox:hover {
                    border-color: #FFEA80;
                    background-color: rgba(255, 215, 0, 30);
                }
                QComboBox::drop-down {
                    border: none;
                    width: 30px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 6px solid #FFD700;
                    margin-right: 8px;
                }
                QComboBox QAbstractItemView {
                    background-color: #1a1a2e;
                    color: #FFD700;
                    border: 2px solid #FFD700;
                    border-radius: 4px;
                    selection-background-color: rgba(255, 215, 0, 80);
                    selection-color: white;
                    padding: 4px;
                }
            """
            label_style = "color: #FFD700; font-size: 14px; font-weight: bold;"

            dropdown_row = QHBoxLayout()
            dropdown_row.setSpacing(20)

            # Orientation
            orientation_col = QVBoxLayout()
            orientation_label = QLabel("Orientation", self)
            orientation_label.setAlignment(Qt.AlignCenter)
            orientation_label.setStyleSheet(label_style)
            orientation_col.addWidget(orientation_label)

            self.orientation_combo = QComboBox(self)
            self.orientation_combo.setFixedWidth(200)
            self.orientation_combo.setStyleSheet(combo_style)
            for text, mode in [("Landscape", 0), ("Portrait", 1),
                               ("Landscape (Flip)", 2), ("Portrait (Flip)", 3)]:
                self.orientation_combo.addItem(text, mode)
            self.orientation_combo.setCurrentIndex(current_orientation)
            self.orientation_combo.currentIndexChanged.connect(
                lambda i: setattr(self, "_pending_orientation",
                                  self.orientation_combo.itemData(i))
            )
            orientation_col.addWidget(self.orientation_combo, alignment=Qt.AlignCenter)

            # Resolution
            resolution_col = QVBoxLayout()
            resolution_label = QLabel("Resolution", self)
            resolution_label.setAlignment(Qt.AlignCenter)
            resolution_label.setStyleSheet(label_style)
            resolution_col.addWidget(resolution_label)

            self.resolution_combo = QComboBox(self)
            self.resolution_combo.setFixedWidth(200)
            self.resolution_combo.setStyleSheet(combo_style)
            if current_h > current_w:
                res_options = [(720, 1280), (1080, 1920), (2160, 3840)]
            else:
                res_options = [(1280, 720), (1920, 1080), (3840, 2160)]
            for w, h in res_options:
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
            save_btn.setStyleSheet(
                "QPushButton { font-size: 13px; font-weight: bold; padding: 6px 14px; "
                "background-color: #FFD700; color: black; border-radius: 6px; } "
                "QPushButton:hover { background-color: #FFEA80; }"
            )
            save_btn.clicked.connect(self._confirm_display_changes)
            layout.addWidget(save_btn, alignment=Qt.AlignCenter)

        layout.addStretch(1)

        # System control buttons
        btn_style = """
            QPushButton {
                font-size: 14px; font-weight: bold; padding: 8px 16px;
                background-color: #555; color: white; border-radius: 8px;
            }
            QPushButton:hover { background-color: #777; }
        """

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        shutdown_btn = QPushButton("Shutdown", self)
        shutdown_btn.setStyleSheet(btn_style)
        shutdown_btn.clicked.connect(lambda: os.system("shutdown /s /t 5"))
        btn_row.addWidget(shutdown_btn)

        restart_btn = QPushButton("Restart", self)
        restart_btn.setStyleSheet(btn_style)
        restart_btn.clicked.connect(lambda: os.system("shutdown /r /t 0 /f"))
        btn_row.addWidget(restart_btn)

        relaunch_btn = QPushButton("Relaunch", self)
        relaunch_btn.setStyleSheet(btn_style)
        relaunch_btn.clicked.connect(self._relaunch)
        btn_row.addWidget(relaunch_btn)

        layout.addLayout(btn_row)

        # Return button
        back_btn = QPushButton("Return to Games", self)
        back_btn.setFixedHeight(40)
        back_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px; font-weight: bold;
                background-color: #dc3545; color: white; border-radius: 8px;
            }
            QPushButton:hover { background-color: #c82333; }
        """)
        back_btn.clicked.connect(self._return_to_menu)
        layout.addWidget(back_btn)

    def paintEvent(self, event):
        if self._bg_pixmap:
            painter = QPainter(self)
            scaled = self._bg_pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
        else:
            super().paintEvent(event)

    def _confirm_display_changes(self):
        from PyQt5.QtWidgets import QMessageBox
        dialog = QMessageBox(None)
        dialog.setWindowTitle("Confirm Restart")
        dialog.setText("Changing these settings requires a restart.\n\nContinue?")
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        dialog.setDefaultButton(QMessageBox.Cancel)
        dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
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
            from PyQt5.QtWidgets import QMessageBox as MB
            MB.critical(None, "Display Error", f"Failed to apply settings:\n{e}")

    def _relaunch(self):
        try:
            launcher = Path(r"C:\Program Files\aio\launcher.exe")
            if launcher.exists():
                subprocess.Popen([str(launcher)])
            else:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
            app = QApplication.instance()
            if app:
                app.quit()
        except Exception:
            pass

    def _return_to_menu(self):
        win = self.window()
        if hasattr(win, 'stack') and hasattr(win, 'main_menu'):
            # Resume ad loop
            if hasattr(win, 'ad_overlay') and win.ad_overlay:
                win.ad_overlay._label.setText("")
                win.ad_overlay._label.setStyleSheet("")
                win.ad_overlay.resume()
            win.stack.setCurrentWidget(win.main_menu)
            if hasattr(win, '_sync_tap_zone_visibility'):
                win._sync_tap_zone_visibility()


# ------------------------------------------------------
# Vertical Multi Window
# ------------------------------------------------------

class VerticalMultiWindow(MainWindow):
    def __init__(self):
        self.ad_overlay = None
        self._game_pid = None
        self._game_is_exe_landscape = False
        self._volume_btn = None
        self._multi_root = None
        super().__init__()

        # Register vertical shell PID for watchdog
        try:
            CURRENT_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            CURRENT_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
            log_debug(f"[VERT] Registered shell PID {os.getpid()}")
        except Exception:
            pass

        # Remove the fixed size constraint set by MainWindow.__init__
        # so the window can properly resize for portrait display
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX

        # Keep central widget in QMainWindow's layout (do NOT reparent).
        # Use a top margin to push game content to the bottom 40%.
        self._multi_root = self.centralWidget()

        # Remove MainWindow's simple "AD SPACE" placeholder overlay.
        if self.ad_overlay is not None:
            self.ad_overlay.hide()
            self.ad_overlay.setParent(None)
            self.ad_overlay.deleteLater()
            self.ad_overlay = None

        # Re-apply fullscreen after a short delay (handles display rotation settling)
        QTimer.singleShot(500, self._reapply_fullscreen)

        # Force terminal type
        self.terminal_type = "multi_vert"

        # Use actual screen geometry for initial sizing (self.height() may
        # return DPI-scaled or primary-monitor values before fullscreen settles)
        _screen = self.screen().geometry()
        _init_w, _init_h = _screen.width(), _screen.height()

        # Ad overlay uses physical screen coordinates
        ad_phys = int(_init_h * AD_RATIO)

        # Zero out central widget margins — stack fills the full window;
        # game content is pushed down via a fixed spacer inside MainMenu.
        if self._multi_root.layout():
            self._multi_root.layout().setContentsMargins(0, 0, 0, 0)

        # Pull bg_label out of the grid layout and position it to cover
        # only the bottom 40% (game area).  The original 1920x1080 bg.gif
        # would stretch badly if scaled to the full 1080x1920 portrait screen.
        central_layout = self._multi_root.layout()
        if central_layout:
            central_layout.removeWidget(self.bg_label)
        self.bg_label.setParent(self._multi_root)
        game_h = _init_h - ad_phys
        self.bg_label.setGeometry(0, ad_phys, _init_w, game_h)
        self.bg_label.lower()  # behind stack and ad overlay

        # Create Ad Overlay as child of central widget (covers top 60%)
        self.ad_overlay = AdLoopWidget(self._multi_root)
        self.ad_overlay.setGeometry(0, 0, _init_w, ad_phys)
        self.ad_overlay.show()
        self.ad_overlay.raise_()

        self.ad_overlay.load_ads(AIO_ROOT / "kiosk" / "vids")

        # Glowing neon divider between ad area and game area
        self._neon_divider = NeonDivider(self._multi_root)
        divider_h = NeonDivider.TOTAL_H
        self._neon_divider.setGeometry(0, ad_phys - divider_h // 2, _init_w, divider_h)
        self._neon_divider.show()
        self._neon_divider.raise_()

        log_debug(f"[VERT] Window size: {self.width()}x{self.height()}, ad_phys={ad_phys}")

        # Volume control button (upper-right of ad area)
        self._volume_btn = VolumeButton(
            on_volume_changed=self._on_volume_changed,
            parent=self._multi_root
        )
        self._position_volume_button()
        self._volume_btn.raise_()

        # Replace carousel with vertical-sized version
        self._replace_carousel_for_vertical()

        # Push game content into the bottom 40% of the screen.
        # MainMenu fills the full window.  We replace the top stretch with a
        # fixed-height spacer equal to the ad area so content sits just below it.
        mm_layout = self.main_menu.layout()
        if mm_layout:
            # Remove all existing stretch items
            for i in range(mm_layout.count() - 1, -1, -1):
                item = mm_layout.itemAt(i)
                if item and item.spacerItem():
                    mm_layout.removeItem(item)
            # Fixed spacer matching the ad area height

            self._ad_spacer = QSpacerItem(0, ad_phys, QSizePolicy.Minimum, QSizePolicy.Fixed)
            mm_layout.insertItem(0, self._ad_spacer)
            mm_layout.insertStretch(1, 1)   # top padding in game area
            mm_layout.addStretch(1)          # bottom padding in game area
            mm_layout.setSpacing(15)
            mm_layout.setContentsMargins(0, 0, 0, 10)

        # Scale "Get Started" button for vertical and re-center it
        if hasattr(self.main_menu, 'start_btn'):
            mm_layout.setAlignment(self.main_menu.start_btn, Qt.AlignHCenter)
            btn_w = max(260, int(_init_w * 0.35))
            btn_h = max(55, int(game_h * 0.09))
            font_sz = max(20, int(btn_h * 0.42))
            radius = btn_h // 4
            self.main_menu.start_btn.setFixedSize(btn_w, btn_h)
            self.main_menu.start_btn.setStyleSheet(f"""
QPushButton {{
    font-size: {font_sz}px;
    font-weight: bold;
    background-color: #FFD700;
    color: black;
    border-radius: {radius}px;
}}
QPushButton:hover {{
    background-color: #FFEA80;
}}
""")

        # Grid menu also needs an ad spacer to push content below the ad area
        if hasattr(self, 'grid_menu'):
            grid_layout = self.grid_menu.layout()
            if grid_layout:
                grid_layout.setContentsMargins(20, 0, 20, 20)
                grid_layout.setSpacing(15)
    
                self._grid_ad_spacer = QSpacerItem(0, ad_phys, QSizePolicy.Minimum, QSizePolicy.Fixed)
                grid_layout.insertItem(0, self._grid_ad_spacer)

        # Enforce layout whenever stacked content changes
        try:
            if hasattr(self, 'stack'):
                self.stack.currentChanged.connect(self._enforce_bottom_layout)
        except Exception:
            pass

        # Loading overlay for game launch/return transitions
        screen_w, screen_h = self._screen_size()
        game_height = int(screen_h * GAME_RATIO)
        self._loading_overlay = LoadingOverlay(self)
        self._loading_overlay.setFixedSize(screen_w, game_height)
        self._loading_overlay.move(0, screen_h - game_height)
        self._loading_overlay.hide()

        # Periodic heartbeat — pings the server every 60s and syncs
        # terminal name / commands.
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(60_000)
        self._heartbeat_timer.timeout.connect(self._heartbeat_ping)
        self._heartbeat_timer.start()

        # Background portrait re-assertion — NVIDIA drivers may revert the
        # rotation several seconds after boot.  Keep re-applying portrait
        # orientation for the first 30 seconds to catch any reversions.
        self._portrait_checks_remaining = 15  # 15 × 2s = 30s
        self._portrait_timer = QTimer(self)
        self._portrait_timer.setInterval(2000)
        self._portrait_timer.timeout.connect(self._reassert_portrait)
        self._portrait_timer.start()

        log_debug(f"[VERT] __init__ complete. games={len(self.games) if self.games else 0}, "
                  f"has_carousel={hasattr(self.main_menu, 'carousel')}")

        # Deferred diagnostic — fires after layout settles
        def _diag():
            mm = self.main_menu
            c = getattr(mm, 'carousel', None)
            b = getattr(mm, 'start_btn', None)
            sw, sh = self._screen_size()
            log_debug(f"[DIAG] window={self.width()}x{self.height()} screen={sw}x{sh} extra_right={max(0, self.width()-sw)}")
            log_debug(f"[DIAG] stack vis={self.stack.isVisible()} geo={self.stack.geometry()}")
            log_debug(f"[DIAG] mainmenu vis={mm.isVisible()} geo={mm.geometry()}")
            if c:
                log_debug(f"[DIAG] carousel vis={c.isVisible()} geo={c.geometry()} "
                          f"container={c.card_container.geometry() if hasattr(c, 'card_container') else '?'}")
                cards = c.card_container.findChildren(QPushButton) if hasattr(c, 'card_container') else []
                log_debug(f"[DIAG] carousel cards={len(cards)}")
                # Log each card's actual position for centering debug
                from PyQt5.QtWidgets import QWidget as _QW
                card_widgets = c.card_container.findChildren(_QW)
                card_geos = [(w.objectName() or w.__class__.__name__, w.geometry()) for w in card_widgets if w.parent() is c.card_container]
                for name, geo in card_geos:
                    log_debug(f"[DIAG]   card {name}: x={geo.x()} y={geo.y()} w={geo.width()} h={geo.height()}")
                # Also log carousel's position in screen coords
                cpos = c.mapToGlobal(c.rect().topLeft())
                log_debug(f"[DIAG] carousel global_pos=({cpos.x()},{cpos.y()}) container_w={c.card_container.width()}")
            if b:
                log_debug(f"[DIAG] start_btn vis={b.isVisible()} geo={b.geometry()}")
            # Check layout items
            ml = mm.layout()
            if ml:
                items = []
                for i in range(ml.count()):
                    it = ml.itemAt(i)
                    if it.widget():
                        w = it.widget()
                        items.append(f"W:{w.__class__.__name__}({w.geometry()})")
                    elif it.spacerItem():
                        sp = it.spacerItem()
                        items.append(f"S:{sp.sizeHint()}")
                log_debug(f"[DIAG] mm_layout items={items}")
                log_debug(f"[DIAG] mm_margins={ml.contentsMargins().left()},{ml.contentsMargins().top()},{ml.contentsMargins().right()},{ml.contentsMargins().bottom()}")
        QTimer.singleShot(2000, _diag)

    def _apply_new_games(self, new_games: list):
        """Override: rebuild game UI then re-apply vertical-specific adjustments."""
        super()._apply_new_games(new_games)

        # Re-apply vertical carousel sizing
        if self.games:
            self._replace_carousel_for_vertical()

        # Re-enforce margin-based layout
        self._enforce_bottom_layout()

        # Re-apply vertical styling tweaks
        if hasattr(self.main_menu, 'start_btn'):
            self.main_menu.start_btn.setFixedSize(260, 55)
            self.main_menu.start_btn.setStyleSheet("""
QPushButton {
    font-size: 20px;
    font-weight: bold;
    background-color: #FFD700;
    color: black;
    border-radius: 12px;
}
QPushButton:hover {
    background-color: #FFEA80;
}
""")

        if hasattr(self, 'grid_menu'):
            grid_layout = self.grid_menu.layout()
            if grid_layout:
                grid_layout.setContentsMargins(20, 0, 20, 20)
                grid_layout.setSpacing(15)
                # Add ad spacer so game grid sits below the ad overlay
    
                screen_w, screen_h = self._screen_size()
                ad_phys = int(screen_h * AD_RATIO)
                self._grid_ad_spacer = QSpacerItem(0, ad_phys, QSizePolicy.Minimum, QSizePolicy.Fixed)
                grid_layout.insertItem(0, self._grid_ad_spacer)

    def closeEvent(self, event):
        """Block unexpected window closure. Exit only via explicit app.quit()."""
        app = QApplication.instance()
        if app and not app.closingDown():
            log_debug("[VERT] closeEvent blocked (unexpected close)")
            event.ignore()
            return
        super().closeEvent(event)

    def _replace_carousel_for_vertical(self):
        """Replace the inherited landscape carousel with a vertical-sized one."""
        if not hasattr(self.main_menu, 'carousel') or not self.games:
            return

        old_carousel = self.main_menu.carousel
        old_carousel.setParent(None)
        old_carousel.deleteLater()

        # Clear parent-class margins BEFORE inserting new carousel
        mm_layout = self.main_menu.layout()
        if mm_layout:
            mm_layout.setContentsMargins(0, 0, 0, 0)

        screen_w, screen_h = self._screen_size()
        game_h = int(screen_h * GAME_RATIO)

        # Scale card sizes to the game area height so they look correct
        # on any resolution (1080x1920, 2160x3840 4K, etc.)
        center_h = int(game_h * 0.55)
        center_w = int(center_h * 0.72)
        side_h = int(center_h * 0.80)
        side_w = int(side_h * 0.72)
        container_h = int(game_h * 0.65)
        card_gap = int(-center_w * 0.18)

        log_debug(f"[VERT] Carousel sizing: screen={screen_w}x{screen_h} "
                  f"game_h={game_h} center={center_w}x{center_h} "
                  f"side={side_w}x{side_h} container_h={container_h}")

        new_carousel = CarouselWidget(
            games=self.games,
            on_select=self.main_menu._game_selected,
            parent=self.main_menu,
            center_size=QSize(center_w, center_h),
            side_size=QSize(side_w, side_h),
            container_size=QSize(screen_w, container_h),
            num_visible=5,
            gap=card_gap,
        )
        # Fill full width — zero all padding so container sits at x=0
        new_carousel.layout().setContentsMargins(0, 0, 0, 0)
        new_carousel.layout().setSpacing(0)
        new_carousel.setFixedWidth(screen_w)
        self.main_menu.carousel = new_carousel
        # alignment=0 ensures no AlignHCenter is applied to this widget item
        mm_layout.insertWidget(1, new_carousel, 0, Qt.Alignment(0))

    def _on_volume_changed(self, vol):
        if self.ad_overlay:
            self.ad_overlay.set_volume(vol)

    def _screen_size(self):
        """Return (width, height) from the actual screen geometry.

        self.width()/height() return DPI-scaled values on Windows which
        don't match the physical display (e.g. 1920 instead of 1080 on a
        rotated portrait screen).  screen().geometry() always returns the
        correct post-rotation dimensions.
        """
        sg = self.screen().geometry()
        return sg.width(), sg.height()

    def _position_volume_button(self):
        """Position volume button in upper-right of ad area."""
        if not hasattr(self, '_volume_btn') or not self._volume_btn:
            return
        sw, sh = self._screen_size()
        ad_height = int(sh * AD_RATIO)
        self._volume_btn.move(sw - 80, ad_height - 80)

    def _reapply_fullscreen(self):
        screen = self.screen().geometry()
        screen_w, screen_h = screen.width(), screen.height()
        log_debug(f"[VERT] _reapply_fullscreen screen={screen_w}x{screen_h}")
        self.setGeometry(screen)
        self.showFullScreen()

        # The window's logical width may exceed the physical screen width
        # (DPI scaling).  Constrain the stack to the physical screen size so
        # Qt layouts center content within the visible area.
        self.stack.setFixedSize(screen_w, screen_h)

        # Left-align stack so it starts at x=0 (the visible left edge)
        central_layout = self._multi_root.layout()
        if central_layout:
            central_layout.setAlignment(self.stack, Qt.AlignLeft | Qt.AlignTop)

        # Position bg_label to cover only the bottom 40% (game area)
        ad_phys = int(screen_h * AD_RATIO)
        game_h = screen_h - ad_phys
        self.bg_label.setGeometry(0, ad_phys, screen_w, game_h)

        self._position_volume_button()

    # --------------------------------------------------
    # Geometry Handling
    # --------------------------------------------------

    def resizeEvent(self, event):
        # Skip MainWindow.resizeEvent — it assumes landscape layout and
        # sets bg_label/ad_overlay geometry incorrectly for vertical mode.
        # We handle everything via margin + manual ad positioning instead.
        event.accept()
        self._update_ad_geometry()
        self._position_volume_button()

        # Move secret tap zone to top of game area (below ad)
        if hasattr(self, '_secret_btn'):
            screen_w, screen_h = self._screen_size()
            ad_height = int(screen_h * AD_RATIO)
            self._secret_btn.move(0, ad_height)
            self._secret_btn.raise_()

    def _update_ad_geometry(self):
        if not self.ad_overlay or not self._multi_root:
            return

        # Ad overlay uses physical screen pixels
        screen_w, screen_h = self._screen_size()
        ad_phys = int(screen_h * AD_RATIO)
        self.ad_overlay.setGeometry(0, 0, screen_w, ad_phys)
        self.ad_overlay.raise_()

        # Update the fixed spacers in MainMenu and GridMenu to match ad height
        if hasattr(self, '_ad_spacer'):
            self._ad_spacer.changeSize(0, ad_phys, QSizePolicy.Minimum, QSizePolicy.Fixed)
            if self.main_menu.layout():
                self.main_menu.layout().invalidate()
        if hasattr(self, '_grid_ad_spacer'):
            self._grid_ad_spacer.changeSize(0, ad_phys, QSizePolicy.Minimum, QSizePolicy.Fixed)
            if hasattr(self, 'grid_menu') and self.grid_menu.layout():
                self.grid_menu.layout().invalidate()

        # Re-constrain stack to physical screen; bg covers game area only
        self.stack.setFixedSize(screen_w, screen_h)
        game_h = screen_h - ad_phys
        self.bg_label.setGeometry(0, ad_phys, screen_w, game_h)

    def _enforce_bottom_layout(self):
        """Re-apply the ad spacer height in case it drifted."""
        self._update_ad_geometry()

    # --------------------------------------------------
    # Admin Menu Override
    # --------------------------------------------------

    def open_manager_page(self, advanced=False):
        if self.manager_page:
            self.stack.removeWidget(self.manager_page)
            self.manager_page.deleteLater()
            self.manager_page = None

        # Pause ad loop and show placeholder
        if self.ad_overlay:
            self.ad_overlay.pause()
            self.ad_overlay._label.clear()  # remove video/image pixmap
            self.ad_overlay._label.setText("Ad Space")
            self.ad_overlay._label.setAlignment(Qt.AlignCenter)
            self.ad_overlay._label.setStyleSheet(
                "color: white; font-size: 36px; font-weight: bold; background-color: black;"
            )

        self.manager_page = VerticalManagerPage(self, advanced=advanced)
        self.stack.addWidget(self.manager_page)
        self.stack.setCurrentWidget(self.manager_page)
        self._sync_tap_zone_visibility()

    # --------------------------------------------------
    # Vertical Launch Override
    # --------------------------------------------------

    # Map of EXE platforms that should be launched as browser URLs instead.
    # Stale games.json on terminals may still list these as "exe" type.
    _EXE_TO_URL = {
        "fire phoenix": "https://fpc-mob.com",
        "golden dragon city": "https://playgd.city",
    }

    def launch_game(self, game: dict):
        """
        Override multi_win launch_game behavior for vertical mode.
        Keep Qt app running, constrain browser/EXE into bottom 40%.
        """
        title = game.get("title") or "Unknown"

        # Force-convert known EXE platforms to browser URL
        override_url = self._EXE_TO_URL.get(title.lower())
        if override_url and (game.get("type") or "url").lower().strip() == "exe":
            log_debug(f"[VERT] Converting EXE '{title}' → browser URL: {override_url}")
            game = dict(game)  # copy to avoid mutating original
            game["type"] = "url"
            game["target"] = override_url

        log_debug(f"[VERT] Launch requested: {title}")

        # Stop idle timers so they don't return to main while a game is running
        if hasattr(self, 'grid_idle_timer'):
            self.grid_idle_timer.stop()
        if hasattr(self, 'inactivity_timer'):
            self.inactivity_timer.stop()

        try:
            send_status_to_server("in_play")
        except Exception:
            pass

        # Hide the entire game selection UI so nothing shows behind the game
        if hasattr(self, 'stack'):
            self.stack.hide()
        if hasattr(self, 'bg_label'):
            self.bg_label.hide()

        # Show loading overlay
        if hasattr(self, '_loading_overlay'):
            self._loading_overlay.show_loading("Loading...")

        # Snapshot existing windows so we can find new ones after launch
        self._pre_launch_hwnds = set()
        try:
            import win32gui as _wg
            def _collect(hwnd, _):
                if _wg.IsWindowVisible(hwnd):
                    self._pre_launch_hwnds.add(hwnd)
            _wg.EnumWindows(_collect, None)
        except Exception:
            pass

        QTimer.singleShot(1500, lambda g=game: self._vertical_launch_after_delay(g))

    def _store_game_pid(self, pid, title):
        """Store game PID for tracking and cleanup."""
        self._game_pid = pid
        try:
            GAME_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            GAME_PID_FILE.write_text(str(pid), encoding="utf-8")
            log_debug(f"[VERT] Stored PID {pid} for {title}")
        except Exception:
            pass

    def _vertical_launch_after_delay(self, game: dict):
        """Launch platform WITHOUT quitting the vertical Qt app."""
        title = game.get("title") or "Unknown"
        gtype = (game.get("type") or "url").lower().strip()
        target = game.get("target") or ""
        orientation = game.get("orientation", "landscape")

        # Determine if this is a full vertical game
        full_vertical_titles = [
            "great balls of fire",
            "fortune 2 go",
            "orca",
        ]
        is_full_vertical = (
            orientation == "vertical"
            or title.lower() in full_vertical_titles
        )

        # EXE-based platforms
        if gtype == "exe":
            log_debug(f"[VERT] Launching EXE: {target}")
            proc = None
            if os.path.exists(target):
                try:
                    exe_dir = os.path.dirname(target)
                    proc = subprocess.Popen(
                        [target],
                        cwd=exe_dir or None,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    log_debug(f"[VERT] EXE launched, PID={proc.pid}")
                except Exception as e:
                    log_debug(f"[VERT] EXE Popen exception: {e}")
            else:
                log_debug(f"[VERT] EXE not found at: {target}")

            if proc:
                self._store_game_pid(proc.pid, title)
                # Store exe name for fallback window matching
                self._game_exe_name = os.path.basename(target)
                self._game_is_browser = False

                if is_full_vertical:
                    if self.ad_overlay:
                        self.ad_overlay.hide()
                    if hasattr(self, '_loading_overlay'):
                        self._loading_overlay.hide_loading()
                    self._show_fullscreen_return_button()
                else:
                    # EXE games don't scale content when windowed.
                    # Position the game window to fill the FULL screen
                    # (0,0 at full resolution) so it renders correctly,
                    # then cover the top 60% with TOPMOST ad overlay.
                    self._game_is_exe_landscape = True
                    QTimer.singleShot(
                        2000,
                        lambda p=proc.pid: self._constrain_landscape_window(p)
                    )
            else:
                log_debug(f"[VERT] EXE launch FAILED for {title} (target={target})")
                # Return to main since game didn't start
                self.return_to_main()
            return

        # URL-based platforms
        if not target:
            log_debug(f"[VERT] No URL target for {title}, returning to main")
            self.return_to_main()
            return

        # Classic Online → Firefox
        if title.lower() == "classic online":
            firefox_candidates = [
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            ]
            firefox_path = None
            for path in firefox_candidates:
                if os.path.exists(path):
                    firefox_path = path
                    break

            if firefox_path:
                # Kill ALL leftover Firefox so a fresh instance applies our flags
                try:
                    subprocess.run(
                        ["taskkill", "/IM", "firefox.exe", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    import time; time.sleep(1.5)
                except Exception:
                    pass

                # Set Firefox policy to block JS Fullscreen API for landscape
                if not is_full_vertical:
                    self._set_firefox_fullscreen_policy(False)
                else:
                    self._set_firefox_fullscreen_policy(True)

                # Classic Online always uses this URL regardless of games.json
                target = "https://cgweb.app/home/"

                # Create a clean Firefox profile.  Only write user.js (Firefox
                # reads it on every launch as overrides; prefs.js is Firefox's
                # own saved state — overwriting it resets first-run flags).
                try:
                    FIREFOX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
                    (FIREFOX_PROFILE_DIR / "user.js").write_text(
                        '// AIO kiosk overrides – rewritten each launch\n'
                        'user_pref("browser.sessionstore.resume_from_crash", false);\n'
                        'user_pref("browser.sessionstore.resume_session_once", false);\n'
                        'user_pref("browser.startup.homepage_override.mstone", "ignore");\n'
                        'user_pref("browser.startup.page", 0);\n'
                        'user_pref("browser.startup.homepage", "about:blank");\n'
                        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                        'user_pref("browser.tabs.warnOnClose", false);\n'
                        # Suppress first-run / welcome page
                        'user_pref("browser.aboutwelcome.enabled", false);\n'
                        'user_pref("trailhead.firstrun.didSeeAboutWelcome", true);\n'
                        'user_pref("browser.startup.firstrunSkipsHomepage", true);\n'
                        'user_pref("startup.homepage_welcome_url", "");\n'
                        'user_pref("startup.homepage_welcome_url.additional", "");\n'
                        # Suppress telemetry / rights / data-reporting prompts
                        'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
                        'user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);\n'
                        'user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);\n'
                        'user_pref("browser.rights.3.shown", true);\n'
                        'user_pref("browser.disableResetPrompt", true);\n'
                        'user_pref("browser.messaging-system.whatsNewPanel.enabled", false);\n',
                        encoding="utf-8",
                    )
                except Exception:
                    pass

                # Nuke stale session-restore data so Firefox won't reopen
                # previously-crashed tabs alongside our target URL.
                import shutil
                for sf in ("sessionstore.jsonlz4", "sessionstore-backups"):
                    sp = FIREFOX_PROFILE_DIR / sf
                    try:
                        if sp.is_file():
                            sp.unlink()
                        elif sp.is_dir():
                            shutil.rmtree(sp, ignore_errors=True)
                    except Exception:
                        pass

                try:
                    if is_full_vertical:
                        proc = subprocess.Popen([firefox_path, "-kiosk", target])
                        if self.ad_overlay:
                            self.ad_overlay.hide()
                        self._store_game_pid(proc.pid, title)
                        self._show_fullscreen_return_button()
                    else:
                        screen_w, screen_h = self._screen_size()
                        ad_h = int(screen_h * AD_RATIO)
                        game_h = screen_h - ad_h
                        # Launch with -no-remote (isolated instance) and our
                        # clean profile.  No -new-window flag — it can cause
                        # a second tab when combined with session restore.
                        proc = subprocess.Popen([
                            firefox_path,
                            "-no-remote",
                            "-profile", str(FIREFOX_PROFILE_DIR),
                            f"-width", str(screen_w),
                            f"-height", str(game_h),
                            target,
                        ])
                        self._store_game_pid(proc.pid, title)
                        self._game_exe_name = "firefox.exe"
                        self._game_is_browser = True
                        QTimer.singleShot(
                            3000,
                            lambda p=proc.pid: self._constrain_landscape_window(p)
                        )
                except Exception:
                    pass
            return

        # All other browser games → Chrome
        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        chrome_path = None
        for path in chrome_candidates:
            if os.path.exists(path):
                chrome_path = path
                break

        if not chrome_path:
            return

        try:
            CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Kill any leftover Chrome using our profile so flags are applied fresh
        try:
            subprocess.run(
                ["taskkill", "/IM", "chrome.exe", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            import time; time.sleep(0.5)
        except Exception:
            pass

        # Path to extension that disables the JS Fullscreen API
        nofs_ext = str(Path(__file__).resolve().parent / "chrome_ext_nofs")

        # Set Chrome policy to block JS Fullscreen API for landscape games
        if not is_full_vertical:
            self._set_chrome_fullscreen_policy(False)
        else:
            self._set_chrome_fullscreen_policy(True)

        # Common flags for a clean, chromeless browser session
        common_flags = [
            f"--user-data-dir={str(CHROME_PROFILE_DIR)}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--disable-features=DesktopPWAs,WebAppInstall,WebAppInstallation,"
            "PwaInstall,PwaInstallIcon,WebAppIdentityProxy",
            "--disable-pwa-install",
            "--disable-save-password-bubble",
            "--disable-sync",
            "--disable-notifications",
            "--disable-extensions",
        ]

        try:
            if is_full_vertical:
                # Full vertical: kiosk mode, no fullscreen-blocking extension
                proc = subprocess.Popen([
                    chrome_path,
                    "--kiosk",
                    "--disable-extensions",
                    *common_flags,
                    target,
                ])
                if self.ad_overlay:
                    self.ad_overlay.hide()
                self._store_game_pid(proc.pid, title)
                self._show_fullscreen_return_button()
            else:
                # Use --app= mode so Chrome has no tabs/address bar.
                # Position directly in the bottom 40% so the game renders
                # at the correct viewport size (1080x768).
                # A low-level keyboard hook blocks Ctrl+W/T/N while active.
                screen_w, screen_h = self._screen_size()
                ad_h = int(screen_h * AD_RATIO)
                game_h = screen_h - ad_h
                proc = subprocess.Popen([
                    chrome_path,
                    f"--app={target}",
                    *common_flags,
                    f"--window-size={screen_w},{game_h}",
                    f"--window-position=0,{ad_h}",
                ])
                self._store_game_pid(proc.pid, title)
                self._game_exe_name = "chrome.exe"
                self._game_is_browser = True
                QTimer.singleShot(
                    3000,
                    lambda p=proc.pid: self._constrain_landscape_window(p)
                )
        except Exception:
            pass

    # --------------------------------------------------
    # Window Constraint (PID-based with retry)
    # --------------------------------------------------

    def _make_overlay_topmost(self, widget):
        """Make a Qt widget's native window always-on-top via Win32 API."""
        try:
            hwnd = int(widget.winId())
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
            )
            log_debug(f"[VERT] Made widget TOPMOST hwnd=0x{hwnd:08X}")
        except Exception as e:
            log_debug(f"[VERT] Failed to make TOPMOST: {e}")

    def _constrain_landscape_window(self, pid, retries=10):
        """
        Detect launched game window, then overlay ads on top of it.

        D3D games resist all Win32 repositioning — instead we let the game
        run fullscreen and place our ad overlay + return button on top via
        HWND_TOPMOST.  The user sees ads covering the top 60%, game visible
        in the bottom 40%.
        """
        screen_w, screen_h = self._screen_size()
        ad_height = int(screen_h * AD_RATIO)
        log_debug(f"[VERT] Waiting for game window (pid={pid}, retry={10-retries})")

        # Build set of PIDs to match: original + children + exe-name siblings
        exe_name = getattr(self, '_game_exe_name', None)
        try:
            parent = psutil.Process(pid)
            pids = {pid} | {c.pid for c in parent.children(recursive=True)}
        except Exception:
            pids = {pid}

        if exe_name:
            try:
                for p in psutil.process_iter(['pid', 'name']):
                    if p.info['name'] and p.info['name'].lower() == exe_name.lower():
                        pids.add(p.info['pid'])
            except Exception:
                pass

        found = False
        our_pid = os.getpid()
        pre_launch = getattr(self, '_pre_launch_hwnds', set())

        def enum_handler(hwnd, _):
            nonlocal found
            if not win32gui.IsWindowVisible(hwnd):
                return
            rect = win32gui.GetWindowRect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w < 200 or h < 200:
                return
            try:
                _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return
            if win_pid == our_pid:
                return
            pid_match = win_pid in pids
            new_window = hwnd not in pre_launch and len(pre_launch) > 0
            if not pid_match and not new_window:
                return
            match_reason = "pid" if pid_match else "new_window"
            found = True
            self._game_hwnd = hwnd
            log_debug(f"[VERT] Game window found! hwnd=0x{hwnd:08X} "
                      f"reason={match_reason} pid={win_pid} rect={rect}")

        try:
            win32gui.EnumWindows(enum_handler, None)
        except Exception:
            pass

        if found:
            # Game is running — raise our ad overlay ON TOP of the fullscreen game
            log_debug(f"[VERT] Raising ad overlay as TOPMOST over game")
            self._raise_overlays_over_game(screen_w, ad_height)
        elif retries > 0:
            QTimer.singleShot(
                1000,
                lambda: self._constrain_landscape_window(pid, retries=retries - 1)
            )
        else:
            log_debug(f"[VERT] Failed to find window for PID {pid} after all retries")
            if hasattr(self, '_loading_overlay'):
                self._loading_overlay.hide_loading()
            self._show_landscape_return_button()

    def _raise_overlays_over_game(self, screen_w, ad_height):
        """Position game in bottom 40% and overlay ads on top.

        Two strategies depending on game type:
        - EXE (D3D) games: Reparent as child of Qt window to break exclusive
          fullscreen, then use Qt ad overlay on top.
        - Browser games: Leave kiosk fullscreen intact (preserves shortcut
          blocking & native input), overlay ads as a TOPMOST window.
        """
        game_hwnd = getattr(self, '_game_hwnd', None)
        screen_w2, screen_h = self._screen_size()
        game_height = screen_h - ad_height
        is_browser = getattr(self, '_game_is_browser', False)

        # Store the game window's actual PID for kill later
        if game_hwnd:
            try:
                _, game_win_pid = win32process.GetWindowThreadProcessId(game_hwnd)
                self._game_window_pid = game_win_pid
                log_debug(f"[VERT] Game window PID={game_win_pid}")
            except Exception:
                pass

        if is_browser:
            # --- Browser path: no reparenting (breaks Chrome input) ---
            # Use SetWinEventHook for instant detection when Chrome tries to
            # resize/move (e.g. JS fullscreen), and snap it back immediately.
            log_debug(f"[VERT] Browser game — positioning + WinEvent hook")

            if game_hwnd:
                try:
                    self._strip_chrome_frame(game_hwnd)
                    # Position in bottom 40%
                    win32gui.SetWindowPos(
                        game_hwnd, None,
                        0, ad_height, screen_w, game_height,
                        win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
                    )
                    log_debug(f"[VERT] Browser positioned at 0,{ad_height} "
                              f"size {screen_w}x{game_height}")
                except Exception as e:
                    log_debug(f"[VERT] Browser positioning failed: {e}")

            # Show the regular Qt ad overlay
            if self.ad_overlay:
                self.ad_overlay.show()
                self.ad_overlay.raise_()
                self.ad_overlay.resume()

            # Raise the neon divider above the game
            if hasattr(self, '_neon_divider') and self._neon_divider:
                self._neon_divider.raise_()

            # Hide loading overlay
            if hasattr(self, '_loading_overlay'):
                self._loading_overlay.hide_loading()

            # Return button as TOPMOST window
            self._show_landscape_return_button_topmost(screen_w, ad_height)

            # Cover Chrome's title bar with a TOPMOST overlay strip
            self._show_titlebar_cover(screen_w, ad_height)

            # Install WinEvent hook for instant fullscreen/resize detection
            self._browser_target_rect = (0, ad_height, screen_w, game_height)
            self._install_winevent_hook(game_hwnd)

            # Install keyboard hook to block Ctrl+W/T/N (closing/opening windows)
            self._install_keyboard_hook()

            # Keep stripping title bar (Chrome re-adds it on page load/navigation)
            self._reparent_count = 0
            self._reparent_params = (game_hwnd, ad_height, screen_w, game_height)
            self._reparent_timer = QTimer(self)
            self._reparent_timer.setInterval(500)
            self._reparent_timer.timeout.connect(self._reassert_browser_position)
            self._reparent_timer.start()

        else:
            # --- EXE path: NO reparenting (breaks input permanently) ---
            # EXE/D3D games run fullscreen at native resolution. We do NOT
            # resize or reparent — just let the game be.  Our TOPMOST ad
            # overlay covers the top 60%, so the user sees the bottom 40%
            # of the game and can interact with it (touch/mouse work because
            # the game is a normal top-level window).
            log_debug(f"[VERT] EXE game — fullscreen + TOPMOST ad overlay (no reparent)")

            if game_hwnd:
                # Give focus to the game window
                try:
                    win32gui.SetForegroundWindow(game_hwnd)
                except Exception:
                    pass

            # Hide our Qt window so it doesn't sit between game and user
            self.hide()

            # Create TOPMOST ad overlay window covering top 60%
            self._show_topmost_ad_overlay(screen_w, ad_height)

            # Hide loading overlay
            if hasattr(self, '_loading_overlay'):
                self._loading_overlay.hide_loading()

            # Return button as TOPMOST window
            self._show_landscape_return_button_topmost(screen_w, ad_height)

            # Keep re-asserting TOPMOST on overlays
            self._reparent_count = 0
            self._reparent_params = (game_hwnd, ad_height, screen_w, game_height)
            self._reparent_timer = QTimer(self)
            self._reparent_timer.setInterval(500)
            self._reparent_timer.timeout.connect(self._reassert_exe_topmost)
            self._reparent_timer.start()

    def _reassert_reparent(self):
        """Keep repositioning the reparented game window."""
        self._reparent_count += 1
        if self._reparent_count > 20:  # 10 seconds
            self._reparent_timer.stop()
            return

        game_hwnd, ad_height, screen_w, game_height = self._reparent_params
        if not game_hwnd:
            self._reparent_timer.stop()
            return

        try:
            if not win32gui.IsWindow(game_hwnd):
                self._reparent_timer.stop()
                return

            our_hwnd = int(self.winId())
            parent = ctypes.windll.user32.GetParent(game_hwnd)

            # Re-reparent if game escaped
            if parent != our_hwnd:
                log_debug(f"[VERT] Game escaped parent, re-reparenting")
                ctypes.windll.user32.SetParent(game_hwnd, our_hwnd)
                style = win32gui.GetWindowLong(game_hwnd, win32con.GWL_STYLE)
                style = style & ~(win32con.WS_POPUP | win32con.WS_CAPTION)
                style = style | win32con.WS_CHILD | win32con.WS_VISIBLE
                win32gui.SetWindowLong(game_hwnd, win32con.GWL_STYLE, style)

            # Re-position
            win32gui.MoveWindow(game_hwnd, 0, ad_height, screen_w, game_height, True)

            if self.ad_overlay:
                self.ad_overlay.raise_()
        except Exception:
            pass

    def _show_topmost_ad_overlay(self, screen_w, ad_height):
        """Create a separate TOPMOST window for ads that covers the top 60%.

        Used for EXE games where the game runs as a top-level window.
        The ad overlay must be a separate TOPMOST window to sit above the game.
        """
        # Clean up previous
        old = getattr(self, '_topmost_ad', None)
        if old:
            try:
                old.hide()
                old.deleteLater()
            except Exception:
                pass

        ad_win = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        ad_win.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        ad_win.setStyleSheet("background-color: black;")
        ad_win.setGeometry(0, 0, screen_w, ad_height)

        # Create an ad loop inside the TOPMOST window
        from PyQt5.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(ad_win)
        layout.setContentsMargins(0, 0, 0, 0)

        ad_label = QLabel(ad_win)
        ad_label.setAlignment(Qt.AlignCenter)
        ad_label.setStyleSheet("background-color: black;")
        layout.addWidget(ad_label)

        ad_win.show()
        self._topmost_ad = ad_win
        self._make_overlay_topmost(ad_win)

        # Mirror the main ad overlay's video frames into this TOPMOST window
        if self.ad_overlay and hasattr(self.ad_overlay, '_label'):
            self.ad_overlay._topmost_mirror_label = ad_label
            self.ad_overlay.resume()

        log_debug(f"[VERT] TOPMOST ad overlay created: {screen_w}x{ad_height}")

    def _reassert_exe_topmost(self):
        """Keep TOPMOST ad overlay and return button above fullscreen EXE game."""
        self._reparent_count += 1
        if self._reparent_count > 120:  # 60 seconds then stop polling
            self._reparent_timer.stop()
            return

        game_hwnd = self._reparent_params[0] if self._reparent_params else None
        if game_hwnd:
            try:
                if not win32gui.IsWindow(game_hwnd):
                    self._reparent_timer.stop()
                    return
            except Exception:
                pass

        try:
            # Re-assert TOPMOST on ad overlay
            topmost_ad = getattr(self, '_topmost_ad', None)
            if topmost_ad:
                self._make_overlay_topmost(topmost_ad)

            # Re-assert TOPMOST on return button
            topmost_btn = getattr(self, '_topmost_return_btn', None)
            if topmost_btn:
                self._make_overlay_topmost(topmost_btn)
        except Exception:
            pass

    @staticmethod
    def _strip_chrome_frame(hwnd):
        """Force Chrome window to have zero frame/title bar."""
        # Set style to bare popup — no caption, no frame, no system menu
        target_style = win32con.WS_POPUP | win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, target_style)
        # Remove all extended decorations
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, 0)

    def _reassert_browser_position(self):
        """Keep stripping title bar and repositioning browser window."""
        game_hwnd, ad_height, screen_w, game_height = self._reparent_params
        if not game_hwnd:
            self._reparent_timer.stop()
            return

        try:
            if not win32gui.IsWindow(game_hwnd):
                self._reparent_timer.stop()
                return

            # Always strip frame (Chrome likes to re-add its title bar)
            style = win32gui.GetWindowLong(game_hwnd, win32con.GWL_STYLE)
            if style & win32con.WS_CAPTION:
                self._strip_chrome_frame(game_hwnd)
                win32gui.SetWindowPos(
                    game_hwnd, None,
                    0, ad_height, screen_w, game_height,
                    win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
                )

            # Check if window has moved or resized
            rect = win32gui.GetWindowRect(game_hwnd)
            cur_x, cur_y, cur_r, cur_b = rect
            cur_w = cur_r - cur_x
            cur_h = cur_b - cur_y
            if cur_x != 0 or cur_y != ad_height or cur_w != screen_w or cur_h != game_height:
                win32gui.SetWindowPos(
                    game_hwnd, None,
                    0, ad_height, screen_w, game_height,
                    win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
                )
        except Exception:
            pass

    # --------------------------------------------------
    # Keyboard Hook (block Chrome shortcuts while game is active)
    # --------------------------------------------------

    def _install_keyboard_hook(self):
        """Install a low-level keyboard hook to block only Ctrl+W/T/N."""
        if getattr(self, '_kb_hook', None):
            return  # already installed

        import ctypes
        from ctypes import wintypes

        # Only block the 3 most dangerous Chrome shortcuts
        BLOCKED_CTRL = {0x57, 0x54, 0x4E}  # W, T, N

        # Use correct pointer-sized return type (LRESULT) for 64-bit compat
        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.CFUNCTYPE(
            LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        user32 = ctypes.windll.user32
        user32.CallNextHookEx.restype = LRESULT
        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        ]

        WM_KEYDOWN = 0x0100
        WM_SYSKEYDOWN = 0x0104
        VK_CONTROL = 0x11

        def hook_proc(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode in BLOCKED_CTRL:
                    # Use GetAsyncKeyState for physical key state
                    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
                        return LRESULT(1)
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        self._hook_proc_ref = HOOKPROC(hook_proc)  # prevent GC
        self._kb_hook = user32.SetWindowsHookExW(13, self._hook_proc_ref, None, 0)
        log_debug(f"[VERT] Keyboard hook installed: {self._kb_hook}")

    def _remove_keyboard_hook(self):
        """Remove the low-level keyboard hook."""
        hook = getattr(self, '_kb_hook', None)
        if hook:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(hook)
                log_debug("[VERT] Keyboard hook removed")
            except Exception:
                pass
            self._kb_hook = None
            self._hook_proc_ref = None

    # --------------------------------------------------
    # WinEvent Hook (instant fullscreen detection for browser games)
    # --------------------------------------------------

    def _install_winevent_hook(self, game_hwnd):
        """Install SetWinEventHook to detect window move/resize instantly."""
        if getattr(self, '_winevent_hook', None):
            return

        import ctypes
        from ctypes import wintypes

        EVENT_OBJECT_LOCATIONCHANGE = 0x800B
        WINEVENT_OUTOFCONTEXT = 0x0000

        # Get thread ID of the Chrome window
        try:
            thread_id, proc_id = win32process.GetWindowThreadProcessId(game_hwnd)
        except Exception:
            thread_id = 0
            proc_id = 0

        target_hwnd = game_hwnd
        target_rect = self._browser_target_rect  # (x, y, w, h)

        WINEVENTPROC = ctypes.CFUNCTYPE(
            None,
            wintypes.HANDLE,   # hWinEventHook
            wintypes.DWORD,    # event
            wintypes.HWND,     # hwnd
            ctypes.c_long,     # idObject
            ctypes.c_long,     # idChild
            wintypes.DWORD,    # idEventThread
            wintypes.DWORD,    # dwmsEventTime
        )

        def winevent_proc(hHook, event, hwnd, idObject, idChild, dwThread, dwTime):
            if hwnd != target_hwnd:
                return
            try:
                rect = win32gui.GetWindowRect(hwnd)
                cur_x, cur_y, cur_r, cur_b = rect
                cur_w = cur_r - cur_x
                cur_h = cur_b - cur_y
                tx, ty, tw, th = target_rect
                if cur_x != tx or cur_y != ty or cur_w != tw or cur_h != th:
                    # Chrome tried to escape — force popup style and snap back
                    target_style = (win32con.WS_POPUP | win32con.WS_VISIBLE |
                                    win32con.WS_CLIPSIBLINGS)
                    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, target_style)
                    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, 0)
                    win32gui.SetWindowPos(
                        hwnd, None, tx, ty, tw, th,
                        win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED
                    )
            except Exception:
                pass

        self._winevent_proc_ref = WINEVENTPROC(winevent_proc)
        self._winevent_hook = ctypes.windll.user32.SetWinEventHook(
            EVENT_OBJECT_LOCATIONCHANGE,  # eventMin
            EVENT_OBJECT_LOCATIONCHANGE,  # eventMax
            None,                         # hmodWinEventProc
            self._winevent_proc_ref,      # pfnWinEventProc
            proc_id,                      # idProcess (0 = all)
            0,                            # idThread (0 = all threads)
            WINEVENT_OUTOFCONTEXT,        # dwFlags
        )
        log_debug(f"[VERT] WinEvent hook installed: {self._winevent_hook} "
                  f"pid={proc_id} hwnd=0x{game_hwnd:08X}")

    def _remove_winevent_hook(self):
        """Remove the WinEvent hook."""
        hook = getattr(self, '_winevent_hook', None)
        if hook:
            try:
                ctypes.windll.user32.UnhookWinEvent(hook)
                log_debug("[VERT] WinEvent hook removed")
            except Exception:
                pass
            self._winevent_hook = None
            self._winevent_proc_ref = None

    # --------------------------------------------------
    # Chrome Fullscreen Policy
    # --------------------------------------------------

    @staticmethod
    def _set_chrome_fullscreen_policy(allowed: bool):
        """Set Chrome enterprise policy to allow/block JS Fullscreen API.

        Sets HKCU\\SOFTWARE\\Policies\\Google\\Chrome\\FullscreenAllowed.
        This makes Chrome itself reject requestFullscreen() calls.
        Kiosk mode (--kiosk) is unaffected — it uses a different mechanism.
        """
        import winreg
        key_path = r"SOFTWARE\Policies\Google\Chrome"
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "FullscreenAllowed", 0, winreg.REG_DWORD,
                              1 if allowed else 0)
            winreg.CloseKey(key)
            log_debug(f"[VERT] Chrome FullscreenAllowed policy set to {allowed}")
        except Exception as e:
            log_debug(f"[VERT] Failed to set Chrome policy: {e}")

    @staticmethod
    def _set_firefox_fullscreen_policy(allowed: bool):
        """Set Firefox enterprise policy to allow/block JS Fullscreen API.

        Sets HKCU\\SOFTWARE\\Policies\\Mozilla\\Firefox\\Permissions\\Fullscreen.
        BlockNewRequests = true prevents requestFullscreen() calls.
        """
        import winreg
        key_path = r"SOFTWARE\Policies\Mozilla\Firefox\Permissions\Fullscreen"
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "BlockNewRequests", 0, winreg.REG_DWORD,
                              0 if allowed else 1)
            winreg.CloseKey(key)
            log_debug(f"[VERT] Firefox Fullscreen BlockNewRequests set to {not allowed}")
        except Exception as e:
            log_debug(f"[VERT] Failed to set Firefox policy: {e}")

    # --------------------------------------------------
    # Title Bar Cover (hides Chrome's min/max/close)
    # --------------------------------------------------

    def _show_titlebar_cover(self, screen_w, ad_height, cover_h=None):
        """Place a TOPMOST click-through black strip over the browser title bar."""
        old = getattr(self, '_titlebar_cover', None)
        if old:
            try:
                old.deleteLater()
            except Exception:
                pass

        # Firefox shows full nav bar (~75px), Chrome --app shows only ~32px
        exe = getattr(self, '_game_exe_name', '') or ''
        if cover_h is None:
            TITLEBAR_H = 75 if 'firefox' in exe.lower() else 32
        else:
            TITLEBAR_H = cover_h

        cover = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        cover.setAutoFillBackground(True)
        pal = cover.palette()
        pal.setColor(cover.backgroundRole(), QColor(0, 0, 0))
        cover.setPalette(pal)
        cover.setGeometry(0, ad_height, screen_w, TITLEBAR_H)
        cover.show()
        self._titlebar_cover = cover

        # Make TOPMOST + click-through (WS_EX_TRANSPARENT | WS_EX_LAYERED)
        hwnd = int(cover.winId())
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST,
            0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
        )
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED | 0x08000000  # WS_EX_NOACTIVATE
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)

    # --------------------------------------------------
    # Return Buttons
    # --------------------------------------------------

    def _show_landscape_return_button(self):
        """Show return button for landscape games (child of main window, non-topmost)."""
        if hasattr(self, "_landscape_return_btn"):
            try:
                self._landscape_return_btn.deleteLater()
            except Exception:
                pass

        s = self._btn_scale()
        btn_w, btn_h = int(110 * s), int(50 * s)

        btn = QPushButton("Return", self)
        btn.setFixedSize(btn_w, btn_h)
        btn.setStyleSheet(self._return_btn_style())
        btn.enterEvent = lambda e, b=btn: self._expand_return_btn(b)
        btn.leaveEvent = lambda e, b=btn: self._collapse_return_btn(b)
        btn.clicked.connect(self.return_to_main)

        _, screen_h = self._screen_size()
        ad_height = int(screen_h * AD_RATIO)

        btn.move(int(20 * s), ad_height - btn_h - int(10 * s))
        btn.raise_()
        btn.show()
        self._landscape_return_btn = btn

    def _show_landscape_return_button_topmost(self, screen_w, ad_height):
        """Show return button as a separate TOPMOST window over the game."""
        if hasattr(self, "_topmost_return_btn") and self._topmost_return_btn:
            try:
                self._topmost_return_btn.deleteLater()
            except Exception:
                pass

        s = self._btn_scale()
        btn_w, btn_h = int(110 * s), int(50 * s)
        container_w, container_h = int(350 * s), int(70 * s)

        btn_win = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        btn_win.setAttribute(Qt.WA_TranslucentBackground)
        btn_win.setGeometry(0, ad_height - container_h, container_w, container_h)

        btn = QPushButton("Return", btn_win)
        btn.setFixedSize(btn_w, btn_h)
        btn.move(int(20 * s), int(10 * s))
        btn.setStyleSheet(self._return_btn_style())
        btn.enterEvent = lambda e, b=btn, w=btn_win: self._expand_return_btn(b, w)
        btn.leaveEvent = lambda e, b=btn, w=btn_win: self._collapse_return_btn(b, w)
        btn.clicked.connect(self.return_to_main)

        btn_win.show()
        self._topmost_return_btn = btn_win
        self._make_overlay_topmost(btn_win)

    def _show_fullscreen_return_button(self):
        """Show return button for full-vertical games as a TOPMOST window.

        Full-vertical games cover the entire screen, so a Qt child widget
        can't render above them.  Use a separate frameless TOPMOST window.
        """
        # Clean up any previous button
        for attr in ("_vertical_return_btn", "_topmost_return_btn"):
            old = getattr(self, attr, None)
            if old:
                try:
                    old.deleteLater()
                except Exception:
                    pass
                setattr(self, attr, None)

        s = self._btn_scale()
        btn_w, btn_h = int(110 * s), int(50 * s)
        container_w, container_h = int(350 * s), int(70 * s)

        btn_win = QWidget(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        btn_win.setAttribute(Qt.WA_TranslucentBackground)
        btn_win.setGeometry(0, 0, container_w, container_h)

        btn = QPushButton("Return", btn_win)
        btn.setFixedSize(btn_w, btn_h)
        btn.move(int(20 * s), int(10 * s))
        btn.setStyleSheet(self._return_btn_style())
        btn.enterEvent = lambda e, b=btn, w=btn_win: self._expand_return_btn(b, w)
        btn.leaveEvent = lambda e, b=btn, w=btn_win: self._collapse_return_btn(b, w)
        btn.clicked.connect(self.return_to_main)

        btn_win.show()
        self._topmost_return_btn = btn_win
        self._vertical_return_btn = btn_win
        self._make_overlay_topmost(btn_win)

    # --------------------------------------------------
    # Vertical Return Override
    # --- Return button helpers -------------------------------------------

    def _btn_scale(self):
        """Return a scale factor for button sizing based on screen width.
        Baseline is 1080px wide.  On wider screens buttons stay proportional."""
        w, _ = self._screen_size()
        return max(0.5, min(1.5, w / 1080.0))

    def _return_btn_style(self):
        s = self._btn_scale()
        fs = max(12, int(16 * s))
        r = max(15, int(25 * s))
        return f"""
            QPushButton {{
                background-color: #dc3545;
                color: white;
                font-size: {fs}px;
                font-weight: bold;
                border-radius: {r}px;
            }}
            QPushButton:hover {{
                background-color: #c82333;
            }}
        """

    def _expand_return_btn(self, btn, container=None):
        s = self._btn_scale()
        btn.setText("Return to Platform Selection")
        btn.setFixedSize(int(280 * s), int(50 * s))
        if container:
            container.setFixedWidth(int(350 * s))

    def _collapse_return_btn(self, btn, container=None):
        s = self._btn_scale()
        btn.setText("Return")
        btn.setFixedSize(int(110 * s), int(50 * s))
        if container:
            container.setFixedWidth(int(180 * s))

    # --------------------------------------------------

    def return_to_main(self):
        """Vertical-safe return: kill game immediately, show overlay, restore UI after delay."""
        log_debug("[VERT] Return requested")

        # Stop reparent timer and remove keyboard hook
        if hasattr(self, '_reparent_timer'):
            self._reparent_timer.stop()
        self._remove_keyboard_hook()
        self._remove_winevent_hook()
        self._set_chrome_fullscreen_policy(True)   # restore for kiosk games
        self._set_firefox_fullscreen_policy(True)  # restore for kiosk games

        # Un-reparent and hide the game window immediately
        game_hwnd = getattr(self, '_game_hwnd', None)
        if game_hwnd:
            try:
                if win32gui.IsWindow(game_hwnd):
                    ctypes.windll.user32.SetParent(game_hwnd, 0)
                    win32gui.ShowWindow(game_hwnd, win32con.SW_HIDE)
            except Exception:
                pass
        self._game_hwnd = None

        # Remove return buttons, title bar cover, and TOPMOST overlays
        for attr in ("_vertical_return_btn", "_landscape_return_btn",
                      "_topmost_return_btn", "_topmost_ad", "_topmost_ad_widget",
                      "_titlebar_cover"):
            try:
                w = getattr(self, attr, None)
                if w:
                    w.hide()
                    w.deleteLater()
                    setattr(self, attr, None)
            except Exception:
                pass

        # Clear TOPMOST mirror label reference
        if self.ad_overlay and hasattr(self.ad_overlay, '_topmost_mirror_label'):
            self.ad_overlay._topmost_mirror_label = None

        # Kill game processes immediately (so game doesn't re-appear)
        self._kill_game_processes()
        self._game_is_browser = False
        self._game_is_exe_landscape = False

        # Re-show Qt window if it was hidden for EXE game
        if not self.isVisible():
            self.show()
            self.showFullScreen()
            self._reapply_fullscreen()

        # Show "Returning To Menu..." overlay (game is gone, overlay is visible)
        if hasattr(self, '_loading_overlay'):
            self._loading_overlay.show_loading("Returning To Menu...")
            self._loading_overlay.raise_()

        # Restore UI after a visible delay
        QTimer.singleShot(1500, self._finish_return_to_main)

    def _kill_game_processes(self):
        """Kill all game-related processes."""
        # Kill by launcher PID
        try:
            if GAME_PID_FILE.exists():
                pid = GAME_PID_FILE.read_text().strip()
                if pid:
                    log_debug(f"[VERT] Killing game PID {pid}")
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                GAME_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        # Kill by the actual game window PID
        game_win_pid = getattr(self, '_game_window_pid', None)
        if game_win_pid:
            try:
                log_debug(f"[VERT] Killing game window PID {game_win_pid}")
                subprocess.run(
                    ["taskkill", "/PID", str(game_win_pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            self._game_window_pid = None

        # Kill by exe name
        exe_name = getattr(self, '_game_exe_name', None)
        if exe_name:
            try:
                log_debug(f"[VERT] Killing by exe name: {exe_name}")
                subprocess.run(
                    ["taskkill", "/IM", exe_name, "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            self._game_exe_name = None

        self._game_pid = None

    def _finish_return_to_main(self):
        """Restore UI after the returning overlay has been visible."""
        # Restore ads
        if self.ad_overlay:
            self.ad_overlay.show()
            self.ad_overlay.resume()

        try:
            send_status_to_server("menu")
        except Exception:
            pass

        # Restore multi UI inside bottom region
        if hasattr(self, 'bg_label'):
            self.bg_label.show()
        if hasattr(self, 'stack') and hasattr(self, 'main_menu'):
            try:
                self.stack.show()
                self.stack.setCurrentWidget(self.main_menu)
            except Exception:
                pass

        # Restart idle timers
        if hasattr(self, 'inactivity_timer'):
            self.inactivity_timer.start()

        # Re-enforce bottom layout, then hide the overlay
        QTimer.singleShot(100, self._enforce_bottom_layout)
        QTimer.singleShot(500, self._hide_loading_overlay)

    def _hide_loading_overlay(self):
        if hasattr(self, '_loading_overlay'):
            self._loading_overlay.hide_loading()

    # -- Portrait re-assertion (fights NVIDIA driver revert) ----------
    def _reassert_portrait(self):
        """Re-check display orientation and force portrait if NVIDIA reverted it."""
        self._portrait_checks_remaining -= 1
        if self._portrait_checks_remaining <= 0:
            self._portrait_timer.stop()
            log_debug("[VERT] Portrait assertion period ended")
            return

        try:
            from win_common import _get_display_orientation, force_portrait as _fp
            dm = _get_display_orientation()
            if dm and dm.dmPelsWidth > dm.dmPelsHeight:
                log_debug(f"[VERT] Display reverted to landscape ({dm.dmPelsWidth}x{dm.dmPelsHeight}) "
                          f"— re-forcing portrait")
                _fp()
                # After rotation, re-apply fullscreen and layout
                QTimer.singleShot(1500, self._reapply_fullscreen)
            elif dm:
                log_debug(f"[VERT] Portrait OK: {dm.dmPelsWidth}x{dm.dmPelsHeight}")
        except Exception as e:
            log_debug(f"[VERT] Portrait check error: {e}")

    # -- Periodic heartbeat -----------------------------------------
    def _heartbeat_ping(self):
        """Send a status ping and refresh the terminal name label."""
        try:
            status = "in_play" if self._game_pid else "menu"
            send_status_to_server(status)
        except Exception:
            pass
        # Refresh terminal name label in admin panel (if open)
        try:
            mp = getattr(self, 'manager_page', None)
            if mp and hasattr(mp, '_admin_terminal_label'):
                t_name = get_terminal_name() or "N/A"
                mp._admin_terminal_label.setText(f"Terminal: {t_name}")
        except Exception:
            pass


# ------------------------------------------------------
# Entry
# ------------------------------------------------------

if __name__ == "__main__":
    # Enable native crash diagnostics (segfault stack traces)
    import faulthandler
    faulthandler.enable()

    # Force portrait BEFORE Qt starts so QApplication sees correct geometry
    import time
    try:
        success = force_portrait()
        if not success:
            log_debug("[STARTUP] force_portrait failed — display may be sideways")
            # Extra wait + one more attempt after NVIDIA driver settles
            time.sleep(3)
            force_portrait()
    except Exception as e:
        log_debug(f"[STARTUP] force_portrait exception: {e}")

    time.sleep(1)  # Let display settle after rotation

    # Final check: log actual display state before Qt starts
    try:
        from win_common import _get_display_orientation
        dm = _get_display_orientation()
        if dm:
            log_debug(f"[STARTUP] Pre-Qt display: {dm.dmPelsWidth}x{dm.dmPelsHeight} "
                      f"orient={dm.dmDisplayOrientation}")
            if dm.dmPelsWidth > dm.dmPelsHeight:
                log_debug("[STARTUP] WARNING: Display is still landscape!")
    except Exception:
        pass

    # Basic DPI sanity for Windows
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_DEVICE_PIXEL_RATIO", "1")

    from PyQt5.QtCore import Qt as _Qt
    QApplication.setAttribute(_Qt.AA_DisableHighDpiScaling, True)

    app = QApplication(sys.argv)
    # Do NOT quit when the window is briefly hidden during init/resize.
    # Exit is handled explicitly via PIN code or relaunch button.
    app.setQuitOnLastWindowClosed(False)

    # Log whenever the app is about to quit so we can trace unexpected exits
    app.aboutToQuit.connect(lambda: log_debug("[APP] aboutToQuit signal fired"))

    # Clear any stale restart flag so a manual reboot doesn't re-trigger
    clear_pending_restart()

    window = VerticalMultiWindow()
    window.showFullScreen()
    log_debug("[APP] Event loop starting")
    exit_code = app.exec_()
    log_debug(f"[APP] Event loop exited with code {exit_code}")
    sys.exit(exit_code)
