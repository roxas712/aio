#!/usr/bin/env python3

"""
Windows Vertical Multi Mode
---------------------------------
Architecture:
- Qt app remains fullscreen
- Top 40% = Ad loop widget (Qt layer)
- Bottom 60% = Existing Multi UI
- Landscape games are constrained to bottom 60%
- Vertical games take full screen (ads hidden)
"""

import sys
import os
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
import win32api

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtMultimedia import QMediaPlayer, QMediaPlaylist, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl

import ctypes
from ctypes import wintypes


def force_windows_portrait():
    """Force primary display into portrait orientation (rotated left)."""
    user32 = ctypes.WinDLL('user32', use_last_error=True)

    ENUM_CURRENT_SETTINGS = -1
    DM_DISPLAYORIENTATION = 0x00000080
    DM_PELSWIDTH = 0x00080000
    DM_PELSHEIGHT = 0x00100000

    class DEVMODE(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG),
            ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", wintypes.SHORT),
            ("dmDuplex", wintypes.SHORT),
            ("dmYResolution", wintypes.SHORT),
            ("dmTTOption", wintypes.SHORT),
            ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    devmode = DEVMODE()
    devmode.dmSize = ctypes.sizeof(DEVMODE)

    if not user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
        return

    # Rotate left (1 = 90 degrees)
    if devmode.dmDisplayOrientation != 1:
        devmode.dmFields = DM_DISPLAYORIENTATION | DM_PELSWIDTH | DM_PELSHEIGHT
        devmode.dmDisplayOrientation = 1

        # Swap width and height
        devmode.dmPelsWidth, devmode.dmPelsHeight = devmode.dmPelsHeight, devmode.dmPelsWidth

        user32.ChangeDisplaySettingsW(ctypes.byref(devmode), 0)

# Reuse existing multi implementation

from multi_win import MainWindow
from win_common import AIO_ROOT
from PyQt5.QtWidgets import QApplication
import subprocess

from win_common import launch_game as win_launch_game
from multi_win import CURRENT_PID_FILE
import webbrowser

# --- Game PID file for vertical mode ---
GAME_PID_FILE = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "game_pid.txt"


# ------------------------------------------------------
# Ad Loop Widget (Top 40%)
# ------------------------------------------------------

class AdLoopWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet("background-color: black;")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.video_widget = QVideoWidget(self)
        self.layout.addWidget(self.video_widget)

        self.player = QMediaPlayer(self)
        self.playlist = QMediaPlaylist(self)
        self.player.setVideoOutput(self.video_widget)
        self.player.setPlaylist(self.playlist)
        self.playlist.setPlaybackMode(QMediaPlaylist.Loop)

    def load_ads(self, folder_path: Path):
        if not folder_path.exists():
            return

        self.playlist.clear()

        for file in sorted(folder_path.glob("*.mp4")):
            self.playlist.addMedia(QMediaContent(QUrl.fromLocalFile(str(file))))

        if self.playlist.mediaCount() > 0:
            self.player.play()

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.play()


# ------------------------------------------------------
# Vertical Multi Window
# ------------------------------------------------------

class VerticalMultiWindow(MainWindow):
    def __init__(self):
        self.ad_overlay = None
        super().__init__()

        # Register vertical shell PID for watchdog
        try:
            CURRENT_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
            CURRENT_PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
            log_debug(f"[VERT] Registered shell PID {os.getpid()}")
        except Exception:
            pass

        # Store reference to original multi UI root
        self._multi_root = self.centralWidget()
        self._multi_root.setParent(self)
        self._multi_root.raise_()

        # Force portrait orientation on launch
        try:
            force_windows_portrait()
        except Exception:
            pass

        # After rotation, re-apply fullscreen + geometry correction
        QTimer.singleShot(500, self._reapply_fullscreen)

        # Force terminal type
        self.terminal_type = "multi_vert"

        # Create Ad Overlay
        self.ad_overlay = AdLoopWidget(self)
        self._update_ad_geometry()

        ads_folder = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "ads"
        self.ad_overlay.load_ads(ads_folder)
        self.ad_overlay.raise_()

        # Enforce layout whenever stacked content changes (loading/game/menu)
        try:
            if hasattr(self, 'content_stack'):
                self.content_stack.currentChanged.connect(self._enforce_bottom_layout)
        except Exception:
            pass

    def _reapply_fullscreen(self):
        screen = self.screen().geometry()
        self.setGeometry(screen)
        self.showFullScreen()
        self._update_ad_geometry()
        self._enforce_bottom_layout()

    # --------------------------------------------------
    # Geometry Handling
    # --------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_ad_geometry()

    def _update_ad_geometry(self):
        if not self.ad_overlay:
            return

        screen_w = self.width()
        screen_h = self.height()

        # Top = 60% (ads)
        ad_height = int(screen_h * 0.60)

        # Bottom = 40% (game UI)
        game_area_height = int(screen_h * 0.40)
        game_y = screen_h - game_area_height

        self.ad_overlay.setGeometry(
            0,
            0,
            screen_w,
            ad_height
        )
        self.ad_overlay.raise_()

        self._multi_root.setGeometry(
            0,
            game_y,
            screen_w,
            game_area_height
        )
        self._multi_root.setFixedSize(screen_w, game_area_height)

    def _enforce_bottom_layout(self):
        screen_w = self.width()
        screen_h = self.height()

        game_area_height = int(screen_h * 0.40)
        game_y = screen_h - game_area_height

        if hasattr(self, '_multi_root') and self._multi_root:
            self._multi_root.setGeometry(0, game_y, screen_w, game_area_height)
            self._multi_root.setFixedSize(screen_w, game_area_height)

        if hasattr(self, 'loading_screen') and self.loading_screen:
            self.loading_screen.setParent(self._multi_root)
            self.loading_screen.setGeometry(0, 0, screen_w, game_area_height)
            self.loading_screen.setFixedSize(screen_w, game_area_height)

        if hasattr(self, 'game_view') and self.game_view:
            self.game_view.setParent(self._multi_root)
            self.game_view.setGeometry(0, 0, screen_w, game_area_height)
            self.game_view.setFixedSize(screen_w, game_area_height)

            if hasattr(self.game_view, 'home_btn'):
                self.game_view.home_btn.move(20, 20)


    # --------------------------------------------------
    # Vertical Launch Override
    # --------------------------------------------------

    def launch_game(self, game: dict):
        """
        Override multi_win launch_game behavior for vertical mode.
        We DO NOT quit the Qt app for landscape games.
        Instead, we keep the Qt app running and constrain browser/EXE
        into the bottom 40% area.
        """

        title = game.get("title") or "Unknown"
        orientation = game.get("orientation", "landscape")

        log_debug(f"[VERT] Launch requested: {title}")

        # Show internal loading screen instead of spawning loading_vert.py
        if hasattr(self, 'stack') and hasattr(self, 'loading_screen'):
            try:
                self.stack.setCurrentWidget(self.loading_screen)
            except Exception:
                pass

        # small delay so loading message is visible
        QTimer.singleShot(1500, lambda g=game: self._vertical_launch_after_delay(g))

    def _vertical_launch_after_delay(self, game: dict):
        """
        Launch platform WITHOUT quitting the vertical Qt app.
        """

        title = game.get("title") or "Unknown"
        gtype = (game.get("type") or "url").lower().strip()
        target = game.get("target") or ""
        orientation = game.get("orientation", "landscape")

        # EXE-based platforms
        if gtype == "exe":
            proc = win_launch_game(game)
            if proc:
                try:
                    GAME_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                    GAME_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
                    log_debug(f"[VERT] Spawned PID {proc.pid} for {title}")
                except Exception:
                    pass

                # PID health check after 3s
                def check_pid_alive():
                    try:
                        alive = psutil.pid_exists(proc.pid)
                        log_debug(f"[VERT] PID {proc.pid} alive={alive}")
                    except Exception:
                        pass
                QTimer.singleShot(3000, check_pid_alive)

            # Handle vertical full-screen EXE titles
            if orientation == "vertical":
                if self.ad_overlay:
                    self.ad_overlay.hide()
            # No other ad_overlay show/hide here for EXE

        # URL-based platforms
        else:
            title_lower = title.lower()

            # Determine if this is a full vertical game
            full_vertical_titles = [
                "great balls of fire",
                "fortune 2 go",
                "orca",
            ]

            is_full_vertical = title_lower in full_vertical_titles

            # Classic Online → Firefox
            if title_lower == "classic online":
                firefox_candidates = [
                    r"C:\\Program Files\\Mozilla Firefox\\firefox.exe",
                    r"C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
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
                            # Hide ads for full vertical
                            if self.ad_overlay:
                                self.ad_overlay.hide()
                        else:
                            proc = subprocess.Popen([firefox_path, target])
                            # Constrain window AFTER it appears
                            QTimer.singleShot(
                                1200,
                                lambda t=title: self._constrain_landscape_window(t)
                            )
                        try:
                            GAME_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                            GAME_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
                            log_debug(f"[VERT] Spawned PID {proc.pid} for {title}")
                        except Exception:
                            pass

                        # PID health check after 3s
                        def check_pid_alive():
                            try:
                                alive = psutil.pid_exists(proc.pid)
                                log_debug(f"[VERT] PID {proc.pid} alive={alive}")
                            except Exception:
                                pass
                        QTimer.singleShot(3000, check_pid_alive)
                    except Exception:
                        pass
                return

            # All other browser games → Chrome
            chrome_candidates = [
                r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            ]

            chrome_path = None
            for path in chrome_candidates:
                if os.path.exists(path):
                    chrome_path = path
                    break

            if chrome_path:
                try:
                    if is_full_vertical:
                        # Full vertical browser games (kiosk mode)
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

                        # Store PID
                        try:
                            GAME_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                            GAME_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
                            log_debug(f"[VERT] Spawned PID {proc.pid} for {title}")
                        except Exception:
                            pass

                        # PID health check after 3s
                        def check_pid_alive():
                            try:
                                alive = psutil.pid_exists(proc.pid)
                                log_debug(f"[VERT] PID {proc.pid} alive={alive}")
                            except Exception:
                                pass
                        QTimer.singleShot(3000, check_pid_alive)

                        # Add internal return button for full vertical mode
                        self._show_fullscreen_return_button()

                    else:
                        # Landscape browser games → launch minimized first
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

                        try:
                            GAME_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
                            GAME_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
                            log_debug(f"[VERT] Spawned PID {proc.pid} for {title}")
                        except Exception:
                            pass

                        # PID health check after 3s
                        def check_pid_alive():
                            try:
                                alive = psutil.pid_exists(proc.pid)
                                log_debug(f"[VERT] PID {proc.pid} alive={alive}")
                            except Exception:
                                pass
                        QTimer.singleShot(3000, check_pid_alive)

                        # Configure window after spawn
                        QTimer.singleShot(
                            1200,
                            lambda t=title: self._constrain_landscape_window(t)
                        )
                except Exception:
                    pass
    def _show_landscape_return_button(self):
        """
        Show return button for landscape games (bottom 40% region).
        """
        if hasattr(self, "_landscape_return_btn"):
            try:
                self._landscape_return_btn.deleteLater()
            except Exception:
                pass

        from PyQt5.QtWidgets import QPushButton

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
        game_area_height = int(screen_h * 0.40)
        game_y = screen_h - game_area_height

        btn.move(30, game_y + 30)
        btn.raise_()
        btn.show()

        btn.clicked.connect(self.return_to_main)

        self._landscape_return_btn = btn

    def _constrain_landscape_window(self, window_title_hint: str):
        """
        Constrain launched platform window into bottom 40% of portrait screen.
        """

        if self.ad_overlay:
            self.ad_overlay.show()

        try:
            log_debug(f"[VERT] Attempting constraint for title: {window_title_hint}")
            import win32gui
            import win32con
            import ctypes
            # slight delay handled by QTimer before calling this method

            user32 = ctypes.windll.user32
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)

            game_height = int(screen_h * 0.40)
            y_offset = screen_h - game_height

            def enum_handler(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return

                title = win32gui.GetWindowText(hwnd)
                if window_title_hint.lower() not in title.lower():
                    return

                # Restore in case it auto-maximized
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                except Exception:
                    pass

                # Log before constraining window
                log_debug(f"[VERT] Constraining window handle {hwnd} for {title}")

                # Force into bottom 40% region
                win32gui.SetWindowPos(
                    hwnd,
                    None,
                    0,
                    y_offset,
                    screen_w,
                    game_height,
                    win32con.SWP_NOZORDER | win32con.SWP_SHOWWINDOW
                )

            win32gui.EnumWindows(enum_handler, None)

            if self.ad_overlay:
                self.ad_overlay.show()

            self._show_landscape_return_button()

        except Exception:
            pass


    def _show_fullscreen_return_button(self):
        """
        Show an internal return button for full-vertical games.
        """
        if hasattr(self, "_vertical_return_btn"):
            try:
                self._vertical_return_btn.deleteLater()
            except Exception:
                pass

        from PyQt5.QtWidgets import QPushButton

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

        btn.move(30, self.height() - int(self.height() * 0.40) + 30)
        btn.raise_()
        btn.show()

        btn.clicked.connect(self.return_to_main)

        self._vertical_return_btn = btn

    # --------------------------------------------------
    # Vertical Return Override
    # --------------------------------------------------

    def return_to_main(self):
        """
        Vertical-safe return: kill running platform and restore bottom UI.
        """
        log_debug("[VERT] Return requested")
        # Remove fullscreen return button if present
        try:
            if hasattr(self, "_vertical_return_btn"):
                self._vertical_return_btn.deleteLater()
        except Exception:
            pass

        try:
            if hasattr(self, "_landscape_return_btn"):
                self._landscape_return_btn.deleteLater()
        except Exception:
            pass

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
                try:
                    GAME_PID_FILE.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        # Restore ads
        if self.ad_overlay:
            self.ad_overlay.show()

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
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = VerticalMultiWindow()
    window.showFullScreen()
    sys.exit(app.exec_())