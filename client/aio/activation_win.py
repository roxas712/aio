def touch_allow_exit_flag():
    try:
        flag = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "allow_exit.flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    except Exception:
        pass
#!/usr/bin/env python3
# activation_win.py

import os
import sys
import json
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import subprocess
import uuid
import winreg

import requests
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPixmap, QPainter
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QHBoxLayout,
    QDialog,
)

from win_common import (
    AIO_ROOT,
    get_server_base_url,
    get_client_uuid,
    get_game_library,
    save_games,
)


# ------------------------------
# Paths & constants
# ------------------------------

PROGRAMDATA_ROOT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio"
KIOSK_DIR = Path(__file__).resolve().parent
ACTIVATION_FILE = PROGRAMDATA_ROOT / "config" / "activation.json"
SINGLE_GAME_FILE = PROGRAMDATA_ROOT / "config" / "single_game.json"
LOG_FILE = PROGRAMDATA_ROOT / "logs" / "activation.log"
UPDATE_BG = KIOSK_DIR / "img" / "update.jpg"
OVERLAY_KIOSK_DIR = PROGRAMDATA_ROOT / "overlay" / "kiosk"

CHECK_REGISTRATION_URL = "/client/check_registration"
CHECK_CONFIG_URL = "/client/check_config"
APP_VERSION_FILE = KIOSK_DIR / "version.json"


# ------------------------------
# Logging
# ------------------------------

def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ------------------------------
# Helpers
# ------------------------------

def get_local_version() -> str:
    default = "V1.0.0"
    if APP_VERSION_FILE.exists():
        try:
            with APP_VERSION_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("version", default)
        except Exception:
            return default
    try:
        APP_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with APP_VERSION_FILE.open("w", encoding="utf-8") as f:
            json.dump({"version": default}, f)
    except Exception as e:
        log(f"[ERROR] Could not create version file: {e}")
    return default


def write_activation_file(data: Dict[str, Any]) -> None:
    try:
        ACTIVATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with ACTIVATION_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log(f"[INFO] Wrote activation.json to {ACTIVATION_FILE}")
    except Exception as e:
        log(f"[ERROR] Failed to write activation.json: {e}")


def get_base_url() -> str:
    return get_server_base_url()


# ------------------------------
# Machine ID (Registry-based)
# ------------------------------

def get_persistent_machine_id() -> str:
    r"""Return a stable, per-machine ID for Windows kiosks.

    Strategy:
    - Try to read MachineId from HKLM\SOFTWARE\PGOC\AIO.
    - If missing, try HKCU\SOFTWARE\PGOC\AIO.
    - If still missing, compute from WMIC csproduct UUID.
    - If WMIC fails or is bogus, fall back to uuid4().
    - Cache back to HKLM (or HKCU if HKLM not writable).
    """
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\\PGOC\\AIO"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\\PGOC\\AIO"),
    ]

    # 1) Try to read existing MachineId from registry
    for root, subkey in reg_paths:
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                val, _ = winreg.QueryValueEx(key, "MachineId")
                val = (val or "").strip()
                if val:
                    return val
        except FileNotFoundError:
            continue
        except Exception:
            continue

    # 2) Compute a new MachineId from WMIC if possible
    mid = None
    try:
        out = subprocess.check_output(
            ["wmic", "csproduct", "get", "uuid"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if len(lines) >= 2:
            candidate = lines[1]
            if candidate and candidate.upper() != "UUID":
                stripped = candidate.replace("-", "").upper()
                # Filter out all-0 or all-F junk
                if not (set(stripped) <= {"0"} or set(stripped) <= {"F"}):
                    mid = candidate
    except Exception:
        mid = None

    # 3) Fallback to random uuid4 if WMIC didn't give us a good value
    if not mid:
        mid = str(uuid.uuid4())

    # 4) Try to write it back to registry (HKLM first, HKCU fallback)
    for root, subkey in reg_paths:
        try:
            key = winreg.CreateKeyEx(
                root,
                subkey,
                0,
                winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
            )
            with key:
                winreg.SetValueEx(key, "MachineId", 0, winreg.REG_SZ, mid)
            break
        except PermissionError:
            # Can't write here; try next root
            continue
        except Exception:
            continue

    return mid


# ------------------------------
# Computer Name Helper
# ------------------------------

def apply_computer_name_from_terminal(reg_data: Dict[str, Any]) -> None:
    """Best-effort: set the Windows computer name to AIOGT-x where x is the terminal number.

    This does not force a reboot; Windows may require a reboot for the change to fully apply.
    """
    term = reg_data.get("terminal")
    if not term:
        return
    try:
        term_str = str(term).strip()
        if not term_str:
            return
        new_name = f"AIOGT-{term_str}"
        current_name = os.environ.get("COMPUTERNAME") or ""
        if not current_name:
            log("[WARN] COMPUTERNAME environment variable is empty; skipping rename.")
            return
        if current_name.upper() == new_name.upper():
            log(f"[INFO] Computer name already set to {new_name}")
            return

        # Use WMIC to request a rename; this typically requires admin rights and a reboot to take full effect.
        cmd = f'wmic computersystem where name="{current_name}" call rename name="{new_name}"'
        log(f"[INFO] Attempting to set computer name to {new_name} via WMIC")
        subprocess.run(cmd, shell=True, check=True)
        log(f"[INFO] Computer name rename command issued successfully (reboot may be required).")
    except Exception as e:
        log(f"[WARN] Failed to rename computer to AIOGT-{term}: {e}")


# ------------------------------
# Pending Activation Window
# ------------------------------

def apply_server_config_and_persist(reg_data: Dict[str, Any]) -> str:
    """
    Given activation reg_data (must include activation_key and terminal),
    fetch /client/check_config and persist the server config locally:
      - For multi: write games.json via save_games(filtered)
      - For single: write single_game.json
    Returns the resolved terminal_type (defaults to reg_data['terminal_type'] or 'multi').
    """
    base = get_base_url()
    cfg_url = f"{base}{CHECK_CONFIG_URL}"
    cfg: Dict[str, Any] = {}
    try:
        resp = requests.get(
            cfg_url,
            params={
                "activation_key": reg_data.get("activation_key"),
                "terminal": reg_data.get("terminal"),
            },
            timeout=8,
        )
        if resp.status_code == 200:
            cfg = resp.json() or {}
        log(f"[DEBUG] /client/check_config response: {cfg}")
    except Exception as e:
        log(f"[WARN] Failed to fetch config: {e}")
        cfg = {}

    tt = (cfg.get("terminal_type") or cfg.get("desired_terminal") or reg_data.get("terminal_type") or "multi")
    tt = str(tt).strip().lower() if tt else "multi"
    if tt not in ("single", "multi", "multi_vert", "lock"):
        tt = "multi"
    reg_data["terminal_type"] = tt

    # Persist server-selected games
    try:
        if tt in ("multi", "multi_vert"):
            selected_games_cfg = cfg.get("selected_games") or []
            if selected_games_cfg:
                all_games = get_game_library()
                filtered = []
                for sg in selected_games_cfg:
                    raw_title = (sg.get("title") or "").strip()
                    if not raw_title:
                        continue
                    title_l = raw_title.lower()

                    match = None
                    for g in all_games:
                        if (g.get("title") or "").strip().lower() == title_l:
                            match = g
                            break
                    if match:
                        filtered.append(match)
                    else:
                        filtered.append({
                            "title": sg.get("title") or "Unknown",
                            "type": "url",
                            "target": sg.get("url") or "",
                            "img": sg.get("img") or "",
                        })
                if filtered:
                    save_games(filtered)
                    log(f"[INFO] Saved {len(filtered)} selected games for {tt} mode via save_games().")
        elif tt == "single":
            sg = cfg.get("selected_game") or {}
            title = (sg.get("title") or "").strip()
            if title:
                all_games = get_game_library()
                chosen = None
                for g in all_games:
                    if (g.get("title") or "").strip().lower() == title.lower():
                        chosen = g
                        break
                if not chosen:
                    chosen = {
                        "title": sg.get("title") or "Unknown",
                        "type": "url",
                        "target": sg.get("url") or "",
                        "img": sg.get("img") or "",
                    }
                SINGLE_GAME_FILE.parent.mkdir(parents=True, exist_ok=True)
                with SINGLE_GAME_FILE.open("w", encoding="utf-8") as f:
                    json.dump(chosen, f, indent=2)
                log(f"[INFO] Saved single_game.json for single mode: {chosen.get('title')}")
    except Exception as e:
        log(f"[WARN] Error while applying server game config: {e}")

    # Persist activation info
    try:
        write_activation_file(reg_data)
    except Exception:
        pass

    return tt


class PendingActivationWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("PendingActivationWindow")
        self.setWindowTitle("Pending Activation")

        # Fullscreen
        self.showFullScreen()
        screen = QApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())

        # Background image
        self._bg_pix = QPixmap(str(UPDATE_BG))

        self.uuid = get_persistent_machine_id()
        log(f"[INFO] PendingActivationWindow started with uuid={self.uuid}")

        self._registration_sent = False
        self.poll_ms = 5000  # start at 5s

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_assignment)
        self.timer.start(self.poll_ms)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._bg_pix)
        super().paintEvent(event)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(20)

        title_label = QLabel("Terminal Is Pending Activation", self)
        title_font = QFont("Arial", 36, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: white;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        uuid_label = QLabel(f"Machine-ID: {self.uuid}", self)
        uuid_label.setFont(QFont("Arial", 20))
        uuid_label.setStyleSheet("color: white;")
        uuid_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(uuid_label)

        btn_layout = QHBoxLayout()

        support_btn = QPushButton("Remote Support", self)
        support_btn.setFont(QFont("Arial", 20))
        support_btn.clicked.connect(self._remote_support)
        btn_layout.addWidget(support_btn)

        restart_btn = QPushButton("Restart", self)
        restart_btn.setFont(QFont("Arial", 20))
        restart_btn.clicked.connect(self.restart_computer)
        btn_layout.addWidget(restart_btn)

        shutdown_btn = QPushButton("Shutdown", self)
        shutdown_btn.setFont(QFont("Arial", 20))
        shutdown_btn.clicked.connect(self.shutdown_computer)
        btn_layout.addWidget(shutdown_btn)

        layout.addLayout(btn_layout)

    # ---- Buttons ----

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

    def restart_computer(self):
        os.system("shutdown /r /t 5")

    def shutdown_computer(self):
        os.system("shutdown /s /t 5")

    # ---- Polling ----

    def check_assignment(self):
        base = get_base_url()
        url = f"{base}{CHECK_REGISTRATION_URL}"
        try:
            params = {"uuid": self.uuid}
            headers = {}

            if not self._registration_sent:
                log(f"[INFO] First registration poll to {url} with uuid={self.uuid}")
                resp = requests.get(url, params=params, timeout=5)
                self._registration_sent = True
            else:
                headers = {"X-Status-Only": "1"}
                params["status"] = "1"
                resp = requests.get(url, params=params, headers=headers, timeout=5)

            data = resp.json() if resp.status_code == 200 else {}
            log(f"[DEBUG] /client/check_registration response: {data}")

            if data.get("activated"):
                self._handle_activated(data)
                return

            # Not activated yet – back off poll interval
            self._backoff()

        except Exception as e:
            log(f"[WARN] check_assignment exception: {e}\n{traceback.format_exc()}")
            self._backoff()

    def _backoff(self):
        self.poll_ms = min(int(self.poll_ms * 2), 60000)
        jitter = random.randint(0, 2000)
        next_interval = self.poll_ms + jitter
        try:
            self.timer.stop()
            self.timer.start(next_interval)
            log(f"[INFO] Not activated yet; next poll in {next_interval} ms")
        except Exception:
            pass

    def _handle_activated(self, reg_data: Dict[str, Any]):
        log(f"[INFO] Terminal activated: {reg_data}")
        # Apply Windows computer name based on assigned terminal number (AIOGT-x)
        apply_computer_name_from_terminal(reg_data)

        # Fetch server config, persist local selections, and get resolved terminal_type
        tt = apply_server_config_and_persist(reg_data)

        # Stop polling and launch kiosk
        self.timer.stop()
        self.close()
        self._launch_kiosk(tt, {})


    def _launch_kiosk(self, terminal_type: str, cfg: Dict[str, Any]):
        """
        Launch the appropriate kiosk UI based on terminal_type.

        - 'multi'  -> multi_win.py
        - 'single' -> single_win.py
        (Additional types like 'multi_vert' can be added later.)
        """
        log(f"[INFO] Launching kiosk for terminal_type={terminal_type}")
        try:
            # Decide which script to launch
            if terminal_type == "single":
                script_name = "single_win.py"
            else:
                script_name = "multi_win.py"

            # Prefer an overlay version of the script if present in ProgramData
            overlay_script = OVERLAY_KIOSK_DIR / script_name
            if overlay_script.exists():
                kiosk_script = overlay_script
            else:
                kiosk_script = KIOSK_DIR / script_name

            touch_allow_exit_flag()
            subprocess.Popen([sys.executable, str(kiosk_script)])
            # Terminate the activation process once kiosk is launched
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as e:
            log(f"[FATAL] Failed to launch kiosk: {e}\n{traceback.format_exc()}")
            self._show_fatal_error(str(e))


    def _show_fatal_error(self, message: str):
        app = QApplication.instance() or QApplication(sys.argv)
        dlg = QDialog()
        dlg.setWindowFlags(Qt.FramelessWindowHint)
        dlg.showFullScreen()
        layout = QVBoxLayout(dlg)
        layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel(f"<b>Critical Error</b><br>Could not launch kiosk.<br><br>{message}")
        lbl.setStyleSheet("font-size: 32px; color: red; background: black;")
        lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl)
        dlg.show()
        app.exec_()


def main():
    log("activation_win.py: Starting up")

    app = QApplication(sys.argv)

    # If there's already an activation.json, ALWAYS refresh from server config before launching
    if ACTIVATION_FILE.exists():
        try:
            with ACTIVATION_FILE.open("r", encoding="utf-8") as f:
                act = json.load(f)
            log(f"activation_win.py: Existing activation.json: {act}")

            # Refresh terminal_type + selections from server and persist
            resolved_type = apply_server_config_and_persist(act)

            # Launch correct kiosk UI based on server-authoritative type
            if resolved_type == "single":
                script_name = "single_win.py"
            else:
                script_name = "multi_win.py"

            overlay_script = OVERLAY_KIOSK_DIR / script_name
            if overlay_script.exists():
                kiosk_script = overlay_script
            else:
                kiosk_script = KIOSK_DIR / script_name

            touch_allow_exit_flag()
            subprocess.Popen([sys.executable, str(kiosk_script)])
            return
        except Exception as e:
            log(f"[WARN] Existing activation.json present but refresh/launch failed: {e}")

    # Otherwise, show pending activation
    window = PendingActivationWindow()
    window.showFullScreen()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()