import time
import subprocess
import sys
import json
from pathlib import Path
import psutil
import os

PROGRAMDATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio"
CONFIG_DIR = PROGRAMDATA / "config"
ALLOW_EXIT_FLAG = CONFIG_DIR / "allow_exit.flag"
CURRENT_PID_FILE = CONFIG_DIR / "current_pid.txt"

# Resolve AIO root
if getattr(sys, "frozen", False):
    AIO_ROOT = Path(sys.executable).parent.parent
else:
    AIO_ROOT = Path(__file__).resolve().parents[2]

KIOSK_DIR = AIO_ROOT / "kiosk"

PYTHON = Path(r"C:\Program Files\Python314\python.exe")
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

GRACE_SECONDS = 3  # debounce window


def pid_running(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception:
        return False


def get_last_pid():
    try:
        if CURRENT_PID_FILE.exists():
            return int(CURRENT_PID_FILE.read_text().strip())
    except Exception:
        pass
    return None


def get_terminal_type():
    activation = CONFIG_DIR / "activation.json"
    if not activation.exists():
        return None
    try:
        data = json.loads(activation.read_text(encoding="utf-8"))
        return data.get("terminal_type")
    except Exception:
        return None


def relaunch():
    launcher = AIO_ROOT / "launcher" / "launcher.exe"

    # Relaunch the shell first (correct recovery path)
    if launcher.exists():
        subprocess.Popen([str(launcher)])
        return

    # Fallback: relaunch kiosk directly if launcher is missing
    term = get_terminal_type()

    if term == "single":
        target = KIOSK_DIR / "single_win.py"

    elif term == "multi_vert":
        target = KIOSK_DIR / "multi_vert_win.py"

    else:
        target = KIOSK_DIR / "multi_win.py"

    if target.exists():
        subprocess.Popen([str(PYTHON), str(target)], cwd=str(target.parent))


def admin_exit_active() -> bool:
    if not ALLOW_EXIT_FLAG.exists():
        return False

    try:
        age = time.time() - ALLOW_EXIT_FLAG.stat().st_mtime
        if age < 10:
            return True
        # Expired: remove flag
        ALLOW_EXIT_FLAG.unlink(missing_ok=True)
    except Exception:
        pass

    return False


def main():
    last_seen_alive = time.time()

    while True:
        time.sleep(1)

        if admin_exit_active():
            continue

        pid = get_last_pid()
        if pid is None:
            # No PID registered; if not an admin exit, recover the shell
            if not admin_exit_active():
                relaunch()
            continue

        if pid_running(pid):
            last_seen_alive = time.time()
            continue

        # PID missing — wait for grace window
        if time.time() - last_seen_alive < GRACE_SECONDS:
            continue

        relaunch()
        # Clear admin flag after acting so watchdog resumes enforcement
        try:
            ALLOW_EXIT_FLAG.unlink(missing_ok=True)
        except Exception:
            pass
        last_seen_alive = time.time()


if __name__ == "__main__":
    main()