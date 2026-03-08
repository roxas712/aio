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

from PyQt5.QtCore import Qt, QTimer, QSize, QUrl
from PyQt5.QtGui import QIcon, QPainter, QColor, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QApplication, QSizePolicy,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaPlaylist, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget

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
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet("background-color: black;")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Video player is created lazily — only when we have videos to play.
        # This avoids DirectShow/Mesa crashes on VMs with no audio/video hardware.
        self.video_widget = None
        self.player = None
        self.playlist = None
        self._fallback_label = None
        self._volume = 100

    def _init_player(self):
        """Create the video player on demand. Returns True on success."""
        if self.player is not None:
            return True
        try:
            self.video_widget = QVideoWidget(self)
            self._layout.addWidget(self.video_widget)

            self.player = QMediaPlayer(self)
            self.playlist = QMediaPlaylist(self)
            self.player.setVideoOutput(self.video_widget)
            self.player.setPlaylist(self.playlist)
            self.playlist.setPlaybackMode(QMediaPlaylist.Loop)
            self.player.setVolume(self._volume)
            self.player.error.connect(self._on_player_error)
            return True
        except Exception as e:
            log_debug(f"[AD] Failed to init video player: {e}")
            return False

    def load_ads(self, folder_path: Path):
        # Create folder if missing
        folder_path.mkdir(parents=True, exist_ok=True)

        # Collect video files
        videos = list(sorted(folder_path.glob("*.mp4")))

        # Fallback: try bundled videos
        if not videos:
            fallback_paths = [
                AIO_ROOT / "kiosk" / "vids" / "AIO_upper-loop.mp4",
                PROGRAMDATA_ROOT / "vids" / "AIO_upper-loop.mp4",
            ]
            for fb in fallback_paths:
                if fb.exists():
                    videos = [fb]
                    break

        if videos:
            # Store paths and defer ALL player creation + playback to after event loop
            self._pending_videos = videos
            log_debug(f"[AD] {len(videos)} video(s) found, deferring player init")
            QTimer.singleShot(1000, self._deferred_init_and_play)
        else:
            log_debug("[AD] No videos found, showing static fallback")
            self._show_static_fallback()

    def _deferred_init_and_play(self):
        """Create video player and start playback after event loop is running."""
        videos = getattr(self, '_pending_videos', None)
        if not videos:
            self._show_static_fallback()
            return

        if not self._init_player():
            self._show_static_fallback()
            return

        log_debug("[AD] Player initialized, starting playback")
        self.playlist.clear()
        for v in videos:
            self.playlist.addMedia(QMediaContent(QUrl.fromLocalFile(str(v))))
        try:
            self.player.play()
        except Exception as e:
            log_debug(f"[AD] Playback failed: {e}")
            self._show_static_fallback()

    def _show_static_fallback(self):
        """Show branded image when no videos are available or playback fails."""
        if self._fallback_label:
            return  # Already showing fallback

        # Disconnect error signal before stopping to prevent recursion
        if self.player:
            try:
                self.player.error.disconnect(self._on_player_error)
            except Exception:
                pass
            try:
                self.player.stop()
            except Exception:
                pass
        if self.video_widget:
            self.video_widget.hide()

        self._fallback_label = QLabel(self)
        self._fallback_label.setAlignment(Qt.AlignCenter)

        logo_path = AIO_ROOT / "kiosk" / "img" / "admin_bg.jpg"
        if logo_path.exists():
            pix = QPixmap(str(logo_path).replace("\\", "/"))
            self._fallback_label.setPixmap(pix.scaled(
                self.width() or 1080, self.height() or 1152,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            ))
            self._fallback_label.setScaledContents(True)
        else:
            self._fallback_label.setText("AIO")
            self._fallback_label.setStyleSheet(
                "color: #FFD700; font-size: 72px; font-weight: bold; background-color: black;"
            )

        self._layout.addWidget(self._fallback_label)

    def _on_player_error(self, error):
        """Handle media player errors without crashing the app."""
        if getattr(self, '_handling_error', False):
            return  # Prevent re-entry (stop() can re-trigger error signal)
        self._handling_error = True
        log_debug(f"[AD] Media player error {error}: {self.player.errorString()}")
        try:
            self.player.error.disconnect(self._on_player_error)
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        self._show_static_fallback()

    def set_volume(self, vol):
        self._volume = vol
        if self.player:
            self.player.setVolume(vol)

    def pause(self):
        if self.player:
            self.player.pause()

    def resume(self):
        if self.player:
            self.player.play()


# ------------------------------------------------------
# Compact Manager Page for Vertical Mode
# ------------------------------------------------------

class VerticalManagerPage(QWidget):
    def __init__(self, parent=None, advanced=False):
        super().__init__(parent)
        self.setObjectName("VerticalManagerPage")
        self.setStyleSheet("background-color: #1a1a2e;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(8)

        # Title
        title = QLabel("Manager", self)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        layout.addWidget(title)

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
        try:
            if VERSION_FILE.exists():
                with VERSION_FILE.open("r", encoding="utf-8") as vf:
                    version = json.load(vf).get("version", "N/A")
        except Exception:
            pass
        ver_label = QLabel(f"Version: {version}", self)
        ver_label.setAlignment(Qt.AlignCenter)
        ver_label.setStyleSheet(info_style)
        layout.addWidget(ver_label)

        hw_id = get_client_uuid() or "N/A"
        hw_label = QLabel(f"HW ID: {hw_id[:24]}..." if len(hw_id) > 24 else f"HW ID: {hw_id}", self)
        hw_label.setAlignment(Qt.AlignCenter)
        hw_label.setStyleSheet(info_style)
        layout.addWidget(hw_label)

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

        # Store reference to original multi UI root
        self._multi_root = self.centralWidget()
        self._multi_root.setParent(self)
        self._multi_root.raise_()

        # Re-apply fullscreen after a short delay (handles display rotation settling)
        QTimer.singleShot(500, self._reapply_fullscreen)

        # Force terminal type
        self.terminal_type = "multi_vert"

        # Create Ad Overlay
        self.ad_overlay = AdLoopWidget(self)
        self._update_ad_geometry()

        ads_folder = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "ads"
        self.ad_overlay.load_ads(ads_folder)
        self.ad_overlay.raise_()

        # Volume control button (upper-right of ad area)
        self._volume_btn = VolumeButton(
            on_volume_changed=self._on_volume_changed,
            parent=self
        )
        self._position_volume_button()
        self._volume_btn.raise_()

        # Replace carousel with vertical-sized version
        self._replace_carousel_for_vertical()

        # Shrink "Get Started" button for vertical
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

        # Tighten grid menu margins for vertical
        if hasattr(self, 'grid_menu'):
            grid_layout = self.grid_menu.layout()
            if grid_layout:
                grid_layout.setContentsMargins(20, 20, 20, 20)
                grid_layout.setSpacing(15)

        # Enforce layout whenever stacked content changes
        try:
            if hasattr(self, 'stack'):
                self.stack.currentChanged.connect(self._enforce_bottom_layout)
        except Exception:
            pass

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

        new_carousel = CarouselWidget(
            games=self.games,
            on_select=self.main_menu._game_selected,
            parent=self.main_menu,
            center_size=QSize(240, 360),
            side_size=QSize(180, 270),
            container_size=QSize(1000, 420),
            num_visible=3,
        )
        self.main_menu.carousel = new_carousel
        # Insert after the top stretch (index 1)
        self.main_menu.layout().insertWidget(1, new_carousel, alignment=Qt.AlignHCenter)

    def _on_volume_changed(self, vol):
        if self.ad_overlay:
            self.ad_overlay.set_volume(vol)

    def _position_volume_button(self):
        """Position volume button in upper-right of ad area."""
        if not hasattr(self, '_volume_btn') or not self._volume_btn:
            return
        screen_w = self.width() or 1080
        ad_height = int((self.height() or 1920) * AD_RATIO)
        self._volume_btn.move(screen_w - 80, ad_height - 80)

    def _reapply_fullscreen(self):
        screen = self.screen().geometry()
        self.setGeometry(screen)
        self.showFullScreen()
        self._update_ad_geometry()
        self._enforce_bottom_layout()
        self._position_volume_button()

    # --------------------------------------------------
    # Geometry Handling
    # --------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_ad_geometry()
        self._position_volume_button()

        # Move secret tap zone to game area (not behind ad overlay)
        if hasattr(self, '_secret_btn'):
            screen_h = self.height()
            game_y = screen_h - int(screen_h * GAME_RATIO)
            self._secret_btn.move(0, game_y)
            self._secret_btn.raise_()

    def _update_ad_geometry(self):
        if not self.ad_overlay or not self._multi_root:
            return

        screen_w = self.width()
        screen_h = self.height()

        ad_height = int(screen_h * AD_RATIO)
        game_area_height = int(screen_h * GAME_RATIO)
        game_y = screen_h - game_area_height

        self.ad_overlay.setGeometry(0, 0, screen_w, ad_height)
        self.ad_overlay.raise_()

        self._multi_root.setGeometry(0, game_y, screen_w, game_area_height)
        self._multi_root.setFixedSize(screen_w, game_area_height)

    def _enforce_bottom_layout(self):
        screen_w = self.width()
        screen_h = self.height()

        game_area_height = int(screen_h * GAME_RATIO)
        game_y = screen_h - game_area_height

        if hasattr(self, '_multi_root') and self._multi_root:
            self._multi_root.setGeometry(0, game_y, screen_w, game_area_height)
            self._multi_root.setFixedSize(screen_w, game_area_height)

    # --------------------------------------------------
    # Admin Menu Override
    # --------------------------------------------------

    def open_manager_page(self, advanced=False):
        if self.manager_page:
            self.stack.removeWidget(self.manager_page)
            self.manager_page.deleteLater()
            self.manager_page = None

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

        try:
            send_status_to_server("in_play")
        except Exception:
            pass

        # Show internal loading screen
        if hasattr(self, 'stack') and hasattr(self, 'loading_screen'):
            try:
                self.stack.setCurrentWidget(self.loading_screen)
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
            proc = win_launch_game(game)
            if proc:
                self._store_game_pid(proc.pid, title)

                if is_full_vertical:
                    if self.ad_overlay:
                        self.ad_overlay.hide()
                    self._show_fullscreen_return_button()
                else:
                    # Constrain landscape EXE to bottom 40%
                    QTimer.singleShot(
                        2000,
                        lambda p=proc.pid: self._constrain_landscape_window(p)
                    )
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

    def _constrain_landscape_window(self, pid, retries=5):
        """
        Constrain launched platform window into bottom 40% of portrait screen.
        Uses PID-based matching with retry logic and border removal.
        """
        if self.ad_overlay:
            self.ad_overlay.show()

        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)

        game_height = int(screen_h * GAME_RATIO)
        y_offset = screen_h - game_height

        # Get all PIDs in the process tree
        try:
            parent = psutil.Process(pid)
            pids = {pid} | {c.pid for c in parent.children(recursive=True)}
        except Exception:
            pids = {pid}

        found = False

        def enum_handler(hwnd, _):
            nonlocal found
            if not win32gui.IsWindowVisible(hwnd):
                return

            try:
                _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return

            if win_pid not in pids:
                return

            found = True
            title = win32gui.GetWindowText(hwnd)

            # Restore if minimized
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass

            # Remove window borders
            try:
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
                style &= ~(
                    win32con.WS_CAPTION | win32con.WS_THICKFRAME
                    | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX
                    | win32con.WS_SYSMENU
                )
                win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
            except Exception:
                pass

            # Remove extended style borders
            try:
                ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                ex_style &= ~(
                    win32con.WS_EX_DLGMODALFRAME
                    | win32con.WS_EX_CLIENTEDGE
                    | win32con.WS_EX_STATICEDGE
                )
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
            except Exception:
                pass

            # Position into bottom 40%
            win32gui.SetWindowPos(
                hwnd, None,
                0, y_offset, screen_w, game_height,
                win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW
            )
            log_debug(f"[VERT] Constrained hwnd={hwnd} title='{title}' to (0,{y_offset},{screen_w},{game_height})")

        try:
            win32gui.EnumWindows(enum_handler, None)
        except Exception:
            pass

        if found:
            self._show_landscape_return_button()
        elif retries > 0:
            QTimer.singleShot(
                800,
                lambda: self._constrain_landscape_window(pid, retries=retries - 1)
            )
        else:
            log_debug(f"[VERT] Failed to find window for PID {pid} after all retries")
            self._show_landscape_return_button()

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

        screen_h = self.height()
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

        game_y = self.height() - int(self.height() * GAME_RATIO)
        btn.move(30, game_y + 30)
        btn.raise_()
        btn.show()
        btn.clicked.connect(self.return_to_main)
        self._vertical_return_btn = btn

    # --------------------------------------------------
    # Vertical Return Override
    # --------------------------------------------------

    def return_to_main(self):
        """Vertical-safe return: kill running platform and restore bottom UI."""
        log_debug("[VERT] Return requested")

        # Remove return buttons
        for attr in ("_vertical_return_btn", "_landscape_return_btn"):
            try:
                btn = getattr(self, attr, None)
                if btn:
                    btn.deleteLater()
            except Exception:
                pass

        # Kill game process
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

        # Re-enforce bottom layout geometry
        QTimer.singleShot(100, self._enforce_bottom_layout)


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
