def is_allowed_url(url: str) -> bool:
    allowed_hosts = [
        "playgd.city",
        "goldendragoncity.com",
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
    return any(h in (url or "").lower() for h in allowed_hosts)
#!/usr/bin/env python3
# single_win.py

import os
import sys
import json
import subprocess
from functools import partial
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, QTimer, QSize, QEvent
from PyQt5.QtGui import QMovie, QPixmap, QPainter, QPainterPath, QPen, QFont
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
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEngineProfile, QWebEnginePage

from win_common import (
    PROGRAMDATA_ROOT,
    KIOSK_DIR,
    AIO_ROOT,
    VERSION_FILE,
    get_local_ip,
    send_click_to_server,
    send_status_to_server,
    log_activity_local,
    launch_game,
    sync_config_from_server,
    persist_synced_config,
)

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------

MANAGER_PIN = "8888"
ADVANCED_PIN = "1225"

SINGLE_GAME_FILE = PROGRAMDATA_ROOT / "config" / "single_game.json"

# Chrome profile directory for single mode
CHROME_PROFILE_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "chrome_profile_single"


# ------------------------------------------------------------------------------
# Golden Dragon Facebook guard (browser mode)
# ------------------------------------------------------------------------------
class GoldenDragonPage(QWebEnginePage):
    """
    Blocks navigation to unauthorized domains and bounces back to Golden Dragon.
    """

    def acceptNavigationRequest(self, url, nav_type, isMainFrame):
        target = url.toString().lower()
        if not is_allowed_url(target):
            return False
        return super().acceptNavigationRequest(url, nav_type, isMainFrame)


def inject_golden_dragon_fix(webview: QWebEngineView, game_url: str):
    """
    Install a Golden Dragon guard that disables/rewires any Facebook links.
    """
    if "goldendragoncity.com" not in (game_url or "").lower():
        return

    webview.setPage(GoldenDragonPage(webview))

    js = r"""
    (function () {
      function installGuards() {
        try {
          // Intercept anchor clicks to facebook.*
          document.querySelectorAll('a[href*="facebook.com"]').forEach(function (a) {
            if (a.__gdPatched) return;
            a.__gdPatched = true;
            a.addEventListener('click', function (e) {
              e.preventDefault();
              e.stopImmediatePropagation();
              try {
                if (history.length > 1) { history.back(); }
                else { window.location.href = "https://www.goldendragoncity.com/"; }
              } catch (err) {
                window.location.href = "https://www.goldendragoncity.com/";
              }
              return false;
            }, { capture: true, passive: false });
          });

          // Intercept any buttons likely used for "Facebook" routes
          document.querySelectorAll('button, div[role="button"]').forEach(function (btn) {
            if (btn.__gdPatched) return;

            var txt = (btn.innerText || btn.textContent || "").toLowerCase();
            var aria = (btn.getAttribute("aria-label") || "").toLowerCase();

            if (
              txt.includes("facebook") || aria.includes("facebook") ||
              btn.className.toLowerCase().includes("facebook")
            ) {
              btn.__gdPatched = true;
              btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopImmediatePropagation();
                try {
                  if (history.length > 1) { history.back(); }
                  else { window.location.href = "https://www.goldendragoncity.com/"; }
                } catch (err) {
                  window.location.href = "https://www.goldendragoncity.com/";
                }
                return false;
              }, { capture: true, passive: false });
            }
          });
        } catch (e) {
          // swallow
        }
      }

      // Initial pass
      installGuards();

      // Keep reapplying as the DOM changes
      var mo = new MutationObserver(function () {
        installGuards();
      });
      mo.observe(document.documentElement, { subtree: true, childList: true });
    })();
    """
    webview.page().runJavaScript(js)
    webview.loadFinished.connect(lambda ok: webview.page().runJavaScript(js))


# ------------------------------------------------------------------------------
# Numeric Keypad Dialogs
# ------------------------------------------------------------------------------
class NumericKeypadDialog(QDialog):
    def __init__(self, title="Enter Pin", parent=None):
        super().__init__(parent)
        self._prompt_text = title
        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        pinpad_img = (KIOSK_DIR / "img" / "pinpad.jpg")
        pinpad_path = str(pinpad_img).replace("\\", "/")
        self.setStyleSheet(f"""
            QDialog {{
                background-image: url("{pinpad_path}");
                background-repeat: no-repeat;
                background-position: center;
                background-color: transparent;
                border-radius: 15px;
            }}
        """)
        self._entered_text = ""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.setLayout(layout)

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
                background-color: rgba(255, 255, 255, 0.8);
                color: black;
                border: 1px solid gray;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        layout.addWidget(self.display, alignment=Qt.AlignCenter)

        center_layout = QHBoxLayout()
        center_layout.setAlignment(Qt.AlignCenter)
        layout.addLayout(center_layout)

        grid = QGridLayout()
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)
        grid.setContentsMargins(35, 10, 10, 10)
        center_layout.addLayout(grid)

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

        spacer = QWidget()
        spacer.setFixedHeight(20)
        grid.addWidget(spacer, 4, 0, 1, 3)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(80, 40)
        cancel_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                background-color: red;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: darkred;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        grid.addWidget(cancel_btn, 5, 0, 1, 2)

        ok_btn = QPushButton("OK")
        ok_btn.setFixedSize(80, 40)
        ok_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px;
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
        ok_btn.clicked.connect(self.accept)
        grid.addWidget(ok_btn, 5, 2)

        self.setFixedSize(250, 400)

    def _append_digit(self, digit: str):
        self._entered_text += digit
        self.display.setText(self._entered_text)

    def get_code(self) -> str:
        return self._entered_text

    def keyPressEvent(self, event):
        if event.key() in (
            Qt.Key_0, Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4,
            Qt.Key_5, Qt.Key_6, Qt.Key_7, Qt.Key_8, Qt.Key_9
        ):
            self._append_digit(event.text())
            return

        if event.key() == Qt.Key_Backspace:
            self._entered_text = self._entered_text[:-1]
            self.display.setText(self._entered_text)
            return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return

        if event.key() == Qt.Key_Escape:
            self.reject()
            return

        super().keyPressEvent(event)


# ------------------------------------------------------------------------------
# GUI Helper Classes
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# Pending configuration overlay
# ------------------------------------------------------------------------------
class PendingConfigPage(QWidget):
    """
    Simple overlay shown when no single-game selection has been configured.
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
        self.advanced_mode = advanced
        self.setObjectName("ManagerPageScreen")

        self.bg_label = QLabel(self)
        admin_bg = (KIOSK_DIR / "img" / "admin_bg.jpg")
        admin_bg_path = str(admin_bg).replace("\\", "/")
        self.bg_label.setPixmap(QPixmap(admin_bg_path))
        self.bg_label.setScaledContents(True)
        self.bg_label.setGeometry(0, 0, self.width(), self.height())
        self.bg_label.lower()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(20)
        self.setLayout(main_layout)

        title = QLabel("Manager Page", self)
        title_font = title.font()
        title_font.setPointSize(42)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; background-color: transparent;")
        main_layout.addWidget(title)

        ip = get_local_ip()
        ip_label = QLabel(f"Local IP: {ip}", self)
        ip_label.setAlignment(Qt.AlignCenter)
        ip_label.setStyleSheet("color: white; font-size: 30px; background-color: black; border-radius: 10px;")
        main_layout.addWidget(ip_label)

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
            version = "N/A"

        ver_text = f"Application Version: {version}"
        if commit_sha:
            ver_text += f"  ({commit_sha})"
        version_label = QLabel(ver_text, self)
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: white; font-size: 24px; background-color: black; border-radius: 10px;")
        main_layout.addWidget(version_label)

        # --------------------------------------------------
        # ADVANCED DISPLAY CONTROLS
        # --------------------------------------------------
        if self.advanced_mode:
            import win32api
            import win32con

            current = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)

            self._original_w = current.PelsWidth
            self._original_h = current.PelsHeight
            self._original_orientation = current.DisplayOrientation
            self._pending_orientation = self._original_orientation
            self._pending_resolution = (self._original_w, self._original_h)

            orientation_label = QLabel("Screen Orientation", self)
            orientation_label.setAlignment(Qt.AlignCenter)
            orientation_label.setStyleSheet("color: yellow; font-size: 22px;")
            main_layout.addWidget(orientation_label)

            orient_row = QHBoxLayout()

            def make_orient_btn(text, mode):
                btn = QPushButton(text, self)
                btn.setStyleSheet("""
                    QPushButton {
                        font-size: 16px;
                        padding: 8px 14px;
                        background-color: #333;
                        color: white;
                        border-radius: 8px;
                    }
                    QPushButton:hover { background-color: #555; }
                """)
                btn.clicked.connect(lambda: self._rotate_screen(mode))
                return btn

            orient_row.addWidget(make_orient_btn("Landscape", 0))
            orient_row.addWidget(make_orient_btn("Portrait", 1))
            orient_row.addWidget(make_orient_btn("Landscape (Flipped)", 2))
            orient_row.addWidget(make_orient_btn("Portrait (Flipped)", 3))

            main_layout.addLayout(orient_row)

            resolution_label = QLabel("Resolution", self)
            resolution_label.setAlignment(Qt.AlignCenter)
            resolution_label.setStyleSheet("color: yellow; font-size: 22px;")
            main_layout.addWidget(resolution_label)

            is_portrait = self._original_h > self._original_w

            if is_portrait:
                base_w, base_h = 1080, 1920
            else:
                base_w, base_h = 1920, 1080

            resolutions = [
                (base_w - 160, base_h - 90),
                (base_w, base_h),
                (base_w + 160, base_h + 90),
            ]

            res_row = QHBoxLayout()

            def make_res_btn(w, h):
                btn = QPushButton(f"{w} x {h}", self)
                btn.setStyleSheet("""
                    QPushButton {
                        font-size: 16px;
                        padding: 8px 14px;
                        background-color: #222;
                        color: white;
                        border-radius: 8px;
                    }
                    QPushButton:hover { background-color: #444; }
                """)
                btn.clicked.connect(lambda: self._set_pending_resolution(w, h))
                return btn

            for w, h in resolutions:
                res_row.addWidget(make_res_btn(w, h))

            main_layout.addLayout(res_row)

            save_btn = QPushButton("Save Display Settings", self)
            save_btn.setStyleSheet("""
                QPushButton {
                    font-size: 18px;
                    padding: 10px 20px;
                    background-color: gold;
                    color: black;
                    border-radius: 10px;
                }
            """)
            save_btn.clicked.connect(self._confirm_display_changes)
            main_layout.addWidget(save_btn, alignment=Qt.AlignCenter)

        # Buttons row
        button_layout = QHBoxLayout()
        shutdown_btn = QPushButton("Shutdown", self)
        restart_btn = QPushButton("Restart", self)
        relaunch_btn = QPushButton("Relaunch App", self)
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
        shutdown_btn.setStyleSheet(btn_style)
        restart_btn.setStyleSheet(btn_style)
        relaunch_btn.setStyleSheet(btn_style)
        shutdown_btn.clicked.connect(self.shutdown_system)
        restart_btn.clicked.connect(self.restart_system)
        relaunch_btn.clicked.connect(self.relaunch_app)
        button_layout.addWidget(shutdown_btn)
        button_layout.addWidget(restart_btn)
        button_layout.addWidget(relaunch_btn)
        main_layout.addLayout(button_layout)

        remote_support_btn = QPushButton("Remote Support", self)
        remote_support_btn.setStyleSheet("""
            QPushButton {
                font-size: 20px;
                font-weight: bold;
                padding: 10px 20px;
                background-color: #228B22;
                color: white;
                border-radius: 10px;
            }
            QPushButton:hover { background-color: #196619; }
        """)
        remote_support_btn.clicked.connect(self._remote_support)
        main_layout.addWidget(remote_support_btn, alignment=Qt.AlignCenter)

        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(30)
        return_btn = QPushButton("Return to Game", self)
        return_btn.setStyleSheet(btn_style)
        return_btn.clicked.connect(lambda: self.window().return_to_main())
        nav_layout.addWidget(return_btn)
        main_layout.addLayout(nav_layout)

        self._bg_label = self.bg_label

    def resizeEvent(self, event):
        if self._bg_label is not None:
            self._bg_label.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(event)

    def shutdown_system(self):
        os.system("shutdown /s /t 5")

    def restart_system(self):
        os.system("shutdown /r /t 0 /f")

    def relaunch_app(self):
        from PyQt5.QtWidgets import QApplication
        script_path = KIOSK_DIR / "single_win.py"
        try:
            subprocess.Popen([sys.executable, str(script_path)])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to relaunch app:\n{e}")
            return
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _rotate_screen(self, orientation):
        # Do NOT immediately apply.
        # Just store pending orientation.
        self._pending_orientation = orientation

    def _set_pending_resolution(self, w, h):
        self._pending_resolution = (w, h)

    def _confirm_display_changes(self):
        reply = QMessageBox.question(
            self,
            "Confirm Restart",
            "Changing these settings requires a restart of the Terminal.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.Cancel,
        )

        if reply == QMessageBox.Cancel:
            # Reset pending values back to original
            self._pending_orientation = self._original_orientation
            self._pending_resolution = (self._original_w, self._original_h)
            return

        try:
            import win32api
            import win32con

            devmode = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)

            # Apply orientation first
            if hasattr(self, "_pending_orientation"):
                orientation = self._pending_orientation
                if orientation in (1, 3):
                    devmode.PelsWidth, devmode.PelsHeight = devmode.PelsHeight, devmode.PelsWidth
                devmode.DisplayOrientation = orientation

            # Apply resolution
            if hasattr(self, "_pending_resolution"):
                w, h = self._pending_resolution
                devmode.PelsWidth = w
                devmode.PelsHeight = h

            win32api.ChangeDisplaySettings(devmode, 0)

            os.system("shutdown /r /t 0 /f")

        except Exception as e:
            QMessageBox.critical(self, "Display Error", str(e))

    def _remote_support(self):
        """
        Launch the Bomgar remote support client dropped by the installer into Public Documents\aio.
        """
        exe_name = "bomgar-scc-w0eec30jzfffee5wi1eizdy65hf5yg7jf5zgfyjc40hc90.exe"
        # Public Documents is typically C:\Users\Public\Documents
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


# ------------------------------------------------------------------------------
# GameView & LoadingScreen (single mode)
# ------------------------------------------------------------------------------
class GameView(QWidget):
    def __init__(self, on_return, parent=None):
        super().__init__(parent)
        self.on_return = on_return

        # Ensure Chrome profile directory exists before use
        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        self.webview = QWebEngineView(self)
        # Force WebEngine profile isolation (important)
        profile = QWebEngineProfile("single_kiosk", self.webview)
        profile.setPersistentStoragePath(str(CHROME_PROFILE_DIR))
        profile.setCachePath(str(CHROME_PROFILE_DIR / "cache"))
        profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        self.webview.setPage(GoldenDragonPage(profile))

        # Disable PWA / install features explicitly
        profile.settings().setAttribute(QWebEngineSettings.PluginsEnabled, True)
        profile.settings().setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        profile.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        profile.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled, False)
        profile.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.webview)
        self.setLayout(layout)

    def load_url_game(self, url: str):
        self.webview.settings().setAttribute(QWebEngineSettings.PluginsEnabled, True)
        self.webview.settings().setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        self.webview.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        try:
            inject_golden_dragon_fix(self.webview, url)
        except Exception:
            pass
        self.webview.setUrl(QUrl(url))


class LoadingScreen(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoadingScreen")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.loading_label = QLabel(self)
        self.loading_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.loading_label, alignment=Qt.AlignCenter)
        loading_gif = (KIOSK_DIR / "img" / "loading.gif")
        loading_path = str(loading_gif).replace("\\", "/")
        self.movie = QMovie(loading_path)
        self.loading_label.setMovie(self.movie)

    def restartAnimation(self):
        self.movie.stop()
        self.movie.jumpToFrame(0)
        self.movie.start()


# ------------------------------------------------------------------------------
# MainWindow Class (single mode)
# ------------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, selected_game: dict):
        super().__init__()
        # Register this single-mode kiosk process with the watchdog
        try:
            pid_file = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "current_pid.txt"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
        self.selected_game = selected_game

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.bg_label = QLabel()
        self.bg_label.setScaledContents(True)
        self.bg_label.setStyleSheet("background-color: black;")
        admin_bg = (KIOSK_DIR / "img" / "admin_bg.jpg")
        admin_bg_path = str(admin_bg).replace("\\", "/")
        self.movie = QMovie(admin_bg_path)
        if self.movie.isValid():
            self.movie.start()
            self.bg_label.setMovie(self.movie)
        else:
            self.bg_label.setPixmap(QPixmap(admin_bg_path))

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.setStyleSheet("background-color: rgba(0,0,0,0);")
        self.stack.setAttribute(Qt.WA_TranslucentBackground)

        central_widget = QWidget()
        central_widget.setAttribute(Qt.WA_TranslucentBackground)
        central_widget.setStyleSheet("background-color: transparent;")
        container_layout = QGridLayout(central_widget)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self.bg_label, 0, 0)
        container_layout.addWidget(self.stack, 0, 0)
        self.setCentralWidget(central_widget)

        self.showFullScreen()
        self.installEventFilter(self)

        self.manager_page = None
        self.home_page = None

        # Load based on type (url vs exe); if invalid, show pending configuration overlay
        gtype = (self.selected_game.get("type") or "").lower().strip()
        target = self.selected_game.get("target") or ""
        title = self.selected_game.get("title") or "Unknown"

        if gtype == "url" and target:
            self.game_view = GameView(self.return_to_main)
            self.stack.addWidget(self.game_view)

            log_activity_local(title)
            send_click_to_server(title)
            try:
                send_status_to_server("in_play")
            except Exception:
                pass
            self.game_view.load_url_game(target)
            self.stack.setCurrentWidget(self.game_view)
            self.home_page = self.game_view

        elif gtype == "exe" and target:
            log_activity_local(title)
            send_click_to_server(title)
            try:
                send_status_to_server("in_play")
            except Exception:
                pass

            # Launch the EXE (no in-UI Exit control for single-mode)
            launch_game(self.selected_game)

            # Show a simple informational screen behind the game window
            wrapper = QWidget()
            vbox = QVBoxLayout(wrapper)
            vbox.setContentsMargins(40, 40, 40, 40)
            vbox.setSpacing(20)

            info = QLabel(
                f"{title} has been launched.\n\n"
                f"Use the game window to play.\n\n"
                f"Press the Manager shortcut (Shift+F7) if you need to access the kiosk controls."
            )
            info.setAlignment(Qt.AlignCenter)
            info.setStyleSheet(
                "color: white; font-size: 24px; "
                "background-color: black; border-radius: 10px; padding: 20px;"
            )

            vbox.addStretch()
            vbox.addWidget(info, alignment=Qt.AlignCenter)
            vbox.addStretch()

            self.stack.addWidget(wrapper)
            self.stack.setCurrentWidget(wrapper)
            self.home_page = wrapper
        else:
            # Pending configuration: no valid single-game selection
            pending = PendingConfigPage(self)
            self.stack.addWidget(pending)
            self.stack.setCurrentWidget(pending)
            try:
                send_status_to_server("idle")
            except Exception:
                pass
            self.home_page = pending
            self.selected_game = {}

        # Periodic config sync — polls server every 60s for game/config changes
        self._config_sync_timer = QTimer(self)
        self._config_sync_timer.setInterval(60_000)
        self._config_sync_timer.timeout.connect(self._on_config_sync)
        self._config_sync_timer.start()
        self._sync_worker = None

    # --------------------------------------------------
    # Periodic config sync
    # --------------------------------------------------

    def _on_config_sync(self):
        """Start background config sync (runs HTTP request off main thread)."""
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return

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
        """Process config sync result — any change triggers full kiosk restart."""
        if not result:
            return

        if result.get("changed_terminal_type") or result.get("changed_games"):
            persist_synced_config(result)
            self._restart_kiosk()

    def _restart_kiosk(self):
        """Restart kiosk pipeline via activation_win.py."""
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

    def _manager_login(self):
        dialog = NumericKeypadDialog("Manager Login", self)
        if dialog.exec_() == QDialog.Accepted:
            pw = dialog.get_code()
            if pw == MANAGER_PIN:
                self._open_manager_page()
            else:
                QMessageBox.warning(self, "Access Denied", "Invalid password!", QMessageBox.Ok)

    def _open_manager_page(self, advanced=False):
        if not self.manager_page:
            self.manager_page = ManagerPage(self, advanced=advanced)
            self.stack.addWidget(self.manager_page)
        self.stack.setCurrentWidget(self.manager_page)

    def return_to_main(self):
        try:
            send_status_to_server("idle")
        except Exception:
            pass
        if hasattr(self, "home_page") and self.home_page is not None:
            self.stack.setCurrentWidget(self.home_page)


    def resizeEvent(self, event):
        self.bg_label.setGeometry(0, 0, self.width(), self.height())
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        # Block Alt-based shortcuts (Alt+F4, Alt+Tab, etc.)
        if event.modifiers() & Qt.AltModifier:
            event.ignore()
            return

        # Block Windows (Super) key
        if event.key() in (Qt.Key_Meta, Qt.Key_Super_L, Qt.Key_Super_R):
            event.ignore()
            return

        # Block Escape
        if event.key() == Qt.Key_Escape:
            event.ignore()
            return

        # Manager / Admin shortcut
        if event.key() == Qt.Key_F7 and (event.modifiers() & Qt.ShiftModifier):
            dlg = NumericKeypadDialog("Manager / Admin Login", self)
            if dlg.exec_() == QDialog.Accepted:
                code = dlg.get_code()
                if code == "12251225":
                    try:
                        from pathlib import Path
                        import os
                        import subprocess

                        # Suppress watchdog relaunch
                        flag = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "allow_exit.flag"
                        flag.parent.mkdir(parents=True, exist_ok=True)
                        flag.touch()

                        # Launch Windows Explorer for admin desktop access
                        subprocess.Popen(["explorer.exe"])
                    except Exception:
                        pass

                    app = QApplication.instance()
                    if app is not None:
                        app.quit()
                elif code == ADVANCED_PIN:
                    self._open_manager_page(advanced=True)
                elif code == MANAGER_PIN:
                    self._open_manager_page(advanced=False)
                else:
                    QMessageBox.warning(self, "Access Denied", "Invalid Pin!", QMessageBox.Ok)
            return

        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.MouseButtonPress, QEvent.KeyPress, QEvent.MouseMove):
            # Single mode: treat any interaction as activity; send a click ping
            if self.selected_game.get("target"):
                send_click_to_server(self.selected_game.get("title") or "Unknown")
        return super().eventFilter(obj, event)


# ------------------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------------------
def main():
    # Basic DPI sanity for Windows
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    os.environ["QT_DEVICE_PIXEL_RATIO"] = "1"
    from PyQt5.QtCore import Qt as _Qt
    QApplication.setAttribute(_Qt.AA_DisableHighDpiScaling, True)

    app = QApplication(sys.argv)

    # Load selected single game from ProgramData; if missing/invalid, show pending configuration UI
    selected = {}
    if SINGLE_GAME_FILE.exists():
        try:
            with SINGLE_GAME_FILE.open("r", encoding="utf-8") as f:
                selected = json.load(f)
        except Exception:
            selected = {}

    window = MainWindow(selected)

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()