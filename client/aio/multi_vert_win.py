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
from PyQt5.QtGui import QIcon, QImage, QPainter, QColor, QPixmap
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
    get_local_ip, get_client_uuid, send_status_to_server,
    force_portrait,
)

# --- Game PID file for vertical mode ---
GAME_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "game_pid.txt"

# Ad/game split ratio
AD_RATIO = 0.60
GAME_RATIO = 0.40


# ------------------------------------------------------
# Loading Overlay
# ------------------------------------------------------

class LoadingOverlay(QWidget):
    """Opaque dark overlay with centered text for loading/returning transitions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(0, 0, 0))
        self.setPalette(pal)
        self.hide()

        self._label = QLabel("Loading...", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("""
            color: white;
            font-size: 36px;
            font-weight: bold;
            background: black;
        """)

    def resizeEvent(self, event):
        self._label.setGeometry(self.rect())
        super().resizeEvent(event)

    def show_loading(self, text="Loading..."):
        self._label.setText(text)
        self.raise_()
        self.show()

    def hide_loading(self):
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
        self._label.setPixmap(QPixmap.fromImage(qimg))

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

        # Shrink "Get Started" button for vertical and re-center it
        if hasattr(self.main_menu, 'start_btn'):
            mm_layout.setAlignment(self.main_menu.start_btn, Qt.AlignHCenter)
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

        screen_w, _ = self._screen_size()
        new_carousel = CarouselWidget(
            games=self.games,
            on_select=self.main_menu._game_selected,
            parent=self.main_menu,
            center_size=QSize(300, 420),
            side_size=QSize(240, 340),
            container_size=QSize(screen_w, 480),
            num_visible=5,
            gap=-55,
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

    def launch_game(self, game: dict):
        """
        Override multi_win launch_game behavior for vertical mode.
        Keep Qt app running, constrain browser/EXE into bottom 40%.
        """
        title = game.get("title") or "Unknown"
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

        # Show loading overlay
        if hasattr(self, '_loading_overlay'):
            self._loading_overlay.show_loading("Loading...")

        # Reset constrain phase for new game launch
        self._constrain_phase = 0

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

                if is_full_vertical:
                    if self.ad_overlay:
                        self.ad_overlay.hide()
                    if hasattr(self, '_loading_overlay'):
                        self._loading_overlay.hide_loading()
                    self._show_fullscreen_return_button()
                else:
                    # Constrain landscape EXE to bottom 40%
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
                try:
                    if is_full_vertical:
                        proc = subprocess.Popen([firefox_path, "-kiosk", target])
                        if self.ad_overlay:
                            self.ad_overlay.hide()
                        self._show_fullscreen_return_button()
                    else:
                        proc = subprocess.Popen([firefox_path, target])
                    self._store_game_pid(proc.pid, title)
                    if not is_full_vertical:
                        QTimer.singleShot(
                            1500,
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
            if is_full_vertical:
                proc = subprocess.Popen([
                    chrome_path,
                    "--kiosk",
                    "--no-first-run",
                    "--disable-infobars",
                    "--disable-session-crashed-bubble",
                    target,
                ])
                if self.ad_overlay:
                    self.ad_overlay.hide()
                self._store_game_pid(proc.pid, title)
                self._show_fullscreen_return_button()
            else:
                proc = subprocess.Popen([
                    chrome_path,
                    "--new-window",
                    "--start-minimized",
                    "--no-first-run",
                    "--disable-infobars",
                    "--disable-session-crashed-bubble",
                    "--disable-features=DesktopPWAs,WebAppInstall",
                    "--disable-extensions",
                    target,
                ])
                self._store_game_pid(proc.pid, title)
                QTimer.singleShot(
                    1500,
                    lambda p=proc.pid: self._constrain_landscape_window(p)
                )
        except Exception:
            pass

    # --------------------------------------------------
    # Window Constraint (PID-based with retry)
    # --------------------------------------------------

    def _constrain_window(self, hwnd, y_offset, screen_w, game_height):
        """Break D3D fullscreen and position window into the bottom game region.

        Strategy:
        Phase 1 (first call): Send real Alt+Enter via SendInput to break D3D
                              exclusive fullscreen, then return to let game process it.
        Phase 2 (second call): Minimize window to force D3D mode switch if
                               Alt+Enter didn't work, then return.
        Phase 3+: Strip styles and reposition into bottom 40%.
        """
        title = win32gui.GetWindowText(hwnd)
        phase = getattr(self, '_constrain_phase', 0)

        try:
            rect = win32gui.GetWindowRect(hwnd)
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        except Exception:
            rect = (0, 0, 0, 0)
            style = 0

        log_debug(f"[VERT] _constrain phase={phase} '{title}' rect={rect} style=0x{style:08X}")

        # Phase 1: Send real Alt+Enter via SendInput (OS-level keyboard simulation)
        if phase == 0:
            self._constrain_phase = 1
            log_debug(f"[VERT] Phase 0: Sending Alt+Enter via SendInput")
            try:
                import ctypes
                from ctypes import wintypes

                # SendInput structures
                INPUT_KEYBOARD = 1
                KEYEVENTF_KEYUP = 0x0002
                VK_MENU = 0x12    # Alt key
                VK_RETURN = 0x0D  # Enter key

                class KEYBDINPUT(ctypes.Structure):
                    _fields_ = [
                        ("wVk", wintypes.WORD),
                        ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                    ]

                class INPUT(ctypes.Structure):
                    class _INPUT(ctypes.Union):
                        _fields_ = [("ki", KEYBDINPUT)]
                    _fields_ = [
                        ("type", wintypes.DWORD),
                        ("_input", _INPUT),
                    ]

                def make_key_input(vk, flags=0):
                    inp = INPUT()
                    inp.type = INPUT_KEYBOARD
                    inp._input.ki.wVk = vk
                    inp._input.ki.dwFlags = flags
                    inp._input.ki.time = 0
                    inp._input.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
                    return inp

                # Bring game window to foreground first
                win32gui.SetForegroundWindow(hwnd)

                # Build input sequence: Alt down, Enter down, Enter up, Alt up
                inputs = (INPUT * 4)(
                    make_key_input(VK_MENU),                          # Alt down
                    make_key_input(VK_RETURN),                        # Enter down
                    make_key_input(VK_RETURN, KEYEVENTF_KEYUP),       # Enter up
                    make_key_input(VK_MENU, KEYEVENTF_KEYUP),         # Alt up
                )
                ctypes.windll.user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
                log_debug(f"[VERT] SendInput Alt+Enter sent successfully")
            except Exception as e:
                log_debug(f"[VERT] SendInput Alt+Enter failed: {e}")
            return  # Let game process the keystroke

        # Phase 2: If still fullscreen, try minimize+restore to break D3D
        if phase == 1:
            self._constrain_phase = 2
            # Check if Alt+Enter worked (rect should have changed)
            still_fullscreen = (rect[0] == 0 and rect[1] == 0 and
                                rect[2] >= screen_w - 10 and rect[3] >= y_offset + game_height)
            if still_fullscreen:
                log_debug(f"[VERT] Phase 1: Alt+Enter didn't work, trying minimize+restore")
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                except Exception as e:
                    log_debug(f"[VERT] Minimize failed: {e}")
                return  # Let minimize take effect, restore on next call
            else:
                log_debug(f"[VERT] Phase 1: Alt+Enter worked! rect={rect}")
                # Fall through to repositioning

        # Phase 3: Restore from minimize if needed, strip styles, reposition
        if phase == 2:
            self._constrain_phase = 3
            try:
                # Check if minimized
                if win32gui.IsIconic(hwnd):
                    log_debug(f"[VERT] Phase 2: Restoring from minimize")
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    return  # Let restore take effect
            except Exception:
                pass

        # Strip window styles for borderless
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            new_style = style & ~(
                win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_THICKFRAME
                | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX
                | win32con.WS_SYSMENU | win32con.WS_OVERLAPPEDWINDOW
            )
            new_style |= win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS
            win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, new_style)
        except Exception:
            pass

        # Remove extended style bits
        try:
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex_style &= ~(win32con.WS_EX_TOPMOST | win32con.WS_EX_DLGMODALFRAME
                          | win32con.WS_EX_CLIENTEDGE | win32con.WS_EX_STATICEDGE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
        except Exception:
            pass

        # Position into bottom game region
        try:
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_NOTOPMOST,
                0, y_offset, screen_w, game_height,
                win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW
            )
        except Exception:
            pass

        try:
            win32gui.MoveWindow(hwnd, 0, y_offset, screen_w, game_height, True)
        except Exception:
            pass

        # Verify
        try:
            rect = win32gui.GetWindowRect(hwnd)
            log_debug(f"[VERT] AFTER reposition: rect={rect} (target: 0,{y_offset},{screen_w},{y_offset + game_height})")
        except Exception:
            pass

    def _constrain_landscape_window(self, pid, retries=10):
        """
        Constrain launched platform window into bottom 40% of portrait screen.
        Strategy: PID match → exe-name match → new-window detection (snapshot diff).
        """
        if self.ad_overlay:
            self.ad_overlay.show()

        # Get physical screen size via DPI-aware API
        user32 = ctypes.windll.user32
        try:
            # Make this thread DPI-aware so GetSystemMetrics returns physical pixels
            user32.SetProcessDPIAware()
        except Exception:
            pass
        phys_w = user32.GetSystemMetrics(0)
        phys_h = user32.GetSystemMetrics(1)

        # Also get Qt logical size
        qt_w, qt_h = self._screen_size()

        # SetWindowPos needs physical pixels — use GetSystemMetrics values
        screen_w = phys_w
        screen_h = phys_h

        game_height = int(screen_h * GAME_RATIO)
        y_offset = screen_h - game_height
        log_debug(f"[VERT] Constrain target: phys={phys_w}x{phys_h} qt={qt_w}x{qt_h} "
                  f"using={screen_w}x{screen_h} y={y_offset} h={game_height}")

        # Build set of PIDs to match: original + children + exe-name siblings
        exe_name = getattr(self, '_game_exe_name', None)
        try:
            parent = psutil.Process(pid)
            pids = {pid} | {c.pid for c in parent.children(recursive=True)}
        except Exception:
            pids = {pid}

        # Fallback: find all PIDs matching the exe name
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

            # Skip tiny windows
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

            # Match by PID or by "new window" (not in pre-launch snapshot)
            pid_match = win_pid in pids
            new_window = hwnd not in pre_launch and len(pre_launch) > 0

            if not pid_match and not new_window:
                return

            match_reason = "pid" if pid_match else "new_window"
            found = True
            self._game_hwnd = hwnd
            self._constrain_window(hwnd, y_offset, screen_w, game_height)
            log_debug(f"[VERT] Match reason={match_reason} win_pid={win_pid}")

        try:
            win32gui.EnumWindows(enum_handler, None)
        except Exception:
            pass

        if found:
            # Game window found — hide loading, show return button
            if hasattr(self, '_loading_overlay'):
                self._loading_overlay.hide_loading()
            self._show_landscape_return_button()
            # Keep re-constraining for a few seconds (game may reposition itself)
            self._constrain_count = 0
            self._constrain_params = (y_offset, screen_w, game_height)
            self._reconstrain_timer = QTimer(self)
            self._reconstrain_timer.setInterval(500)
            self._reconstrain_timer.timeout.connect(self._reconstrain_game)
            self._reconstrain_timer.start()
        elif retries > 0:
            QTimer.singleShot(
                1000,
                lambda: self._constrain_landscape_window(pid, retries=retries - 1)
            )
        else:
            log_debug(f"[VERT] Failed to find window for PID {pid} (exe={exe_name}) after all retries")
            log_debug(f"[VERT] Searched PIDs: {pids}")
            # Hide loading even if window wasn't found — show return button so user isn't stuck
            if hasattr(self, '_loading_overlay'):
                self._loading_overlay.hide_loading()
            self._show_landscape_return_button()

    def _reconstrain_game(self):
        """Periodically re-constrain game window (games may reposition themselves)."""
        self._constrain_count += 1
        if self._constrain_count > 20:  # Stop after 10 seconds (20 * 500ms)
            self._reconstrain_timer.stop()
            return

        hwnd = getattr(self, '_game_hwnd', None)
        if not hwnd:
            self._reconstrain_timer.stop()
            return

        try:
            if not win32gui.IsWindow(hwnd):
                self._reconstrain_timer.stop()
                return
            y_offset, screen_w, game_height = self._constrain_params
            self._constrain_window(hwnd, y_offset, screen_w, game_height)
        except Exception:
            self._reconstrain_timer.stop()

    # --------------------------------------------------
    # Return Buttons
    # --------------------------------------------------

    def _show_landscape_return_button(self):
        """Show return button for landscape games (bottom 40% region)."""
        if hasattr(self, "_landscape_return_btn"):
            try:
                self._landscape_return_btn.deleteLater()
            except Exception:
                pass

        btn = QPushButton("Return to Platform Selection", self)
        btn.setFixedSize(360, 70)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                font-size: 20px;
                font-weight: bold;
                border-radius: 35px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)

        _, screen_h = self._screen_size()
        game_y = screen_h - int(screen_h * GAME_RATIO)

        btn.move(30, game_y + 30)
        btn.raise_()
        btn.show()
        btn.clicked.connect(self.return_to_main)
        self._landscape_return_btn = btn

    def _show_fullscreen_return_button(self):
        """Show return button for full-vertical games."""
        if hasattr(self, "_vertical_return_btn"):
            try:
                self._vertical_return_btn.deleteLater()
            except Exception:
                pass

        btn = QPushButton("Return to Platform Selection", self)
        btn.setFixedSize(360, 70)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                font-size: 20px;
                font-weight: bold;
                border-radius: 35px;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)

        _, screen_h = self._screen_size()
        game_y = screen_h - int(screen_h * GAME_RATIO)
        btn.move(30, game_y + 30)
        btn.raise_()
        btn.show()
        btn.clicked.connect(self.return_to_main)
        self._vertical_return_btn = btn

    # --------------------------------------------------
    # Vertical Return Override
    # --------------------------------------------------

    def return_to_main(self):
        """Vertical-safe return: show returning overlay, kill game, restore UI."""
        log_debug("[VERT] Return requested")

        # Stop re-constrain timer
        if hasattr(self, '_reconstrain_timer'):
            self._reconstrain_timer.stop()
        self._game_hwnd = None

        # Remove return buttons immediately
        for attr in ("_vertical_return_btn", "_landscape_return_btn"):
            try:
                btn = getattr(self, attr, None)
                if btn:
                    btn.deleteLater()
            except Exception:
                pass

        # Show "Returning To Menu..." overlay
        if hasattr(self, '_loading_overlay'):
            self._loading_overlay.show_loading("Returning To Menu...")

        # Do the actual cleanup after a short delay so the overlay is visible
        QTimer.singleShot(200, self._finish_return_to_main)

    def _finish_return_to_main(self):
        """Perform the actual cleanup after the returning overlay is shown."""
        # Kill game process by PID
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

        # Also kill by exe name (handles launcher-spawned processes)
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

        # Restore ads
        if self.ad_overlay:
            self.ad_overlay.show()
            self.ad_overlay.resume()

        try:
            send_status_to_server("menu")
        except Exception:
            pass

        # Restore multi UI inside bottom region
        if hasattr(self, 'stack') and hasattr(self, 'main_menu'):
            try:
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


# ------------------------------------------------------
# Entry
# ------------------------------------------------------

if __name__ == "__main__":
    # Enable native crash diagnostics (segfault stack traces)
    import faulthandler
    faulthandler.enable()

    # Force portrait BEFORE Qt starts so QApplication sees correct geometry
    try:
        force_portrait()
    except Exception:
        pass

    import time
    time.sleep(1)  # Let display settle after rotation

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

    window = VerticalMultiWindow()
    window.showFullScreen()
    log_debug("[APP] Event loop starting")
    exit_code = app.exec_()
    log_debug(f"[APP] Event loop exited with code {exit_code}")
    sys.exit(exit_code)
