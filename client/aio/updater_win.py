#!/usr/bin/env python3
# updater_win.py -- GitHub-based auto-updater for AIO kiosk terminal
#
# Boot chain: launcher.exe → updater_win.py → activation_win.py → kiosk
#
# On every boot:
#   1. Check GitHub API for latest commit SHA on main branch
#   2. Compare with locally stored SHA in version.json
#   3. If different: download repo ZIP, extract, deploy files, update deps
#   4. Launch activation_win.py (always, even if update fails or is skipped)

import os
import sys
import json
import shutil
import subprocess
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

AIO_ROOT = Path(r"C:\Program Files\aio")
KIOSK_DIR = AIO_ROOT / "kiosk"
AGENT_DIR = AIO_ROOT / "agent"

PROGRAMDATA_ROOT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio"
STAGING_DIR = PROGRAMDATA_ROOT / "repo"
ZIP_PATH = PROGRAMDATA_ROOT / "aio-latest.zip"
TMP_EXTRACT_DIR = PROGRAMDATA_ROOT / "tmp_extract"

VERSION_FILE = PROGRAMDATA_ROOT / "config" / "version.json"
LOG_FILE = PROGRAMDATA_ROOT / "logs" / "updater.log"

PYTHON = Path(r"C:\Program Files\Python314\python.exe")
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

REPO_OWNER = "roxas712"
REPO_NAME = "aio"
BRANCH = "main"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/commits/{BRANCH}"
ARCHIVE_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/{BRANCH}.zip"

# PAT is stored on-disk (not in source) to avoid push protection blocks.
# Deployed by the installer to C:\Program Files\aio\config\github_token.txt
GITHUB_TOKEN_FILE = AIO_ROOT / "config" / "github_token.txt"


def _get_github_headers() -> dict:
    """Build GitHub API headers with auth token if available."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        if GITHUB_TOKEN_FILE.exists():
            token = GITHUB_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                headers["Authorization"] = f"token {token}"
    except Exception:
        pass
    return headers

# ---------------------------------------------------------------------------
# Services & Dependencies
# ---------------------------------------------------------------------------

SERVICES = ["AIOWatchdog", "AIOAgent"]
PIP_PACKAGES = ["PyQt5", "PyQtWebEngine", "psutil", "requests", "websockets", "pywin32", "opencv-python"]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Watchdog flag
# ---------------------------------------------------------------------------

def touch_allow_exit_flag():
    try:
        flag = PROGRAMDATA_ROOT / "config" / "allow_exit.flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Version tracking
# ---------------------------------------------------------------------------

def get_local_commit_sha() -> str:
    if not VERSION_FILE.exists():
        return ""
    try:
        with VERSION_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("commit_sha", "")
    except Exception:
        return ""


def get_remote_commit_sha() -> str:
    try:
        log("[INFO] Querying GitHub API for latest commit SHA...")
        resp = requests.get(
            GITHUB_API_URL,
            headers=_get_github_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            sha = resp.json().get("sha", "")
            log(f"[INFO] Remote commit SHA: {sha[:12]}")
            return sha
        else:
            log(f"[WARN] GitHub API returned HTTP {resp.status_code}")
            return ""
    except requests.exceptions.ConnectionError as e:
        log(f"[WARN] ConnectionError reaching GitHub API: {e}")
        return ""
    except requests.exceptions.Timeout:
        log("[WARN] GitHub API request timed out")
        return ""
    except Exception as e:
        log(f"[WARN] Failed to query GitHub API: {e}")
        return ""


def write_version_file(commit_sha: str) -> None:
    data = {}
    if VERSION_FILE.exists():
        try:
            with VERSION_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    data["commit_sha"] = commit_sha
    data.setdefault("version", "V2.0")
    data["last_updated"] = datetime.now().isoformat()

    try:
        VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with VERSION_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log(f"[INFO] Updated version.json: commit_sha={commit_sha[:12]}")
    except Exception as e:
        log(f"[WARN] Failed to write version.json: {e}")


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def stop_services() -> None:
    for svc in SERVICES:
        try:
            result = subprocess.run(
                ["sc", "query", svc],
                capture_output=True, text=True, timeout=10,
            )
            if "RUNNING" in result.stdout:
                log(f"[INFO] Stopping service: {svc}")
                subprocess.run(
                    ["sc", "stop", svc],
                    capture_output=True, text=True, timeout=30,
                )
                for _ in range(10):
                    time.sleep(1)
                    check = subprocess.run(
                        ["sc", "query", svc],
                        capture_output=True, text=True, timeout=10,
                    )
                    if "STOPPED" in check.stdout:
                        log(f"[INFO] Service {svc} stopped.")
                        break
            else:
                log(f"[INFO] Service {svc} not running (skipping).")
        except Exception as e:
            log(f"[WARN] Error stopping {svc}: {e}")


def start_services() -> None:
    for svc in ["AIOAgent", "AIOWatchdog"]:
        try:
            result = subprocess.run(
                ["sc", "query", svc],
                capture_output=True, text=True, timeout=10,
            )
            if "STOPPED" in result.stdout:
                log(f"[INFO] Starting service: {svc}")
                subprocess.run(
                    ["sc", "start", svc],
                    capture_output=True, text=True, timeout=30,
                )
        except Exception as e:
            log(f"[WARN] Error starting {svc}: {e}")


# ---------------------------------------------------------------------------
# Download & extract
# ---------------------------------------------------------------------------

def download_repo_zip(max_retries: int = 3) -> bool:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    delays = [10, 30, 60]  # seconds between retries

    for attempt in range(1, max_retries + 1):
        try:
            log(f"[INFO] Downloading repo archive (attempt {attempt}/{max_retries})...")
            resp = requests.get(ARCHIVE_URL, headers=_get_github_headers(), stream=True, timeout=180)
            resp.raise_for_status()

            with ZIP_PATH.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            log(f"[INFO] Downloaded archive ({ZIP_PATH.stat().st_size} bytes)")
            return True
        except Exception as e:
            log(f"[ERROR] Download attempt {attempt} failed: {e}")
            if attempt < max_retries:
                wait = delays[attempt - 1] if attempt - 1 < len(delays) else delays[-1]
                log(f"[INFO] Retrying in {wait}s...")
                time.sleep(wait)

    log("[ERROR] All download attempts failed.")
    return False


def extract_repo_zip() -> bool:
    try:
        if STAGING_DIR.exists():
            shutil.rmtree(STAGING_DIR, ignore_errors=True)
        if TMP_EXTRACT_DIR.exists():
            shutil.rmtree(TMP_EXTRACT_DIR, ignore_errors=True)

        log("[INFO] Extracting archive...")
        TMP_EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(str(ZIP_PATH), "r") as zf:
            zf.extractall(str(TMP_EXTRACT_DIR))

        # GitHub zips contain a top-level folder like "aio-main/"
        subdirs = [d for d in TMP_EXTRACT_DIR.iterdir() if d.is_dir()]
        if len(subdirs) == 1:
            subdirs[0].rename(STAGING_DIR)
        else:
            TMP_EXTRACT_DIR.rename(STAGING_DIR)

        if TMP_EXTRACT_DIR.exists():
            shutil.rmtree(TMP_EXTRACT_DIR, ignore_errors=True)
        if ZIP_PATH.exists():
            ZIP_PATH.unlink(missing_ok=True)

        log(f"[INFO] Extracted to {STAGING_DIR}")
        return True
    except Exception as e:
        log(f"[ERROR] Failed to extract archive: {e}")
        return False


# ---------------------------------------------------------------------------
# File deployment (mirrors deploy.ps1)
# ---------------------------------------------------------------------------

def deploy_files() -> bool:
    try:
        kiosk_src = STAGING_DIR / "client" / "aio"
        watchdog_src = STAGING_DIR / "client" / "watchdog.py"

        if not kiosk_src.exists():
            log(f"[ERROR] Source kiosk dir not found: {kiosk_src}")
            return False

        KIOSK_DIR.mkdir(parents=True, exist_ok=True)
        AGENT_DIR.mkdir(parents=True, exist_ok=True)

        # Copy all .py files to kiosk dir
        for py_file in kiosk_src.glob("*.py"):
            dest = KIOSK_DIR / py_file.name
            shutil.copy2(str(py_file), str(dest))
            log(f"[INFO]   -> kiosk\\{py_file.name}")

        # Copy images
        img_src = kiosk_src / "img"
        img_dst = KIOSK_DIR / "img"
        if img_src.exists():
            img_dst.mkdir(parents=True, exist_ok=True)
            for item in img_src.iterdir():
                if item.name == ".DS_Store":
                    continue
                dest = img_dst / item.name
                if item.is_file():
                    shutil.copy2(str(item), str(dest))
                elif item.is_dir():
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(item), str(dest))
            log("[INFO]   -> kiosk\\img\\ (all assets)")

        # Copy videos
        vids_src = kiosk_src / "vids"
        vids_dst = KIOSK_DIR / "vids"
        if vids_src.exists():
            vids_dst.mkdir(parents=True, exist_ok=True)
            for item in vids_src.iterdir():
                if item.name == ".DS_Store":
                    continue
                dest = vids_dst / item.name
                if item.is_file():
                    shutil.copy2(str(item), str(dest))
                elif item.is_dir():
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(item), str(dest))
            log("[INFO]   -> kiosk\\vids\\ (all videos)")

        # Copy watchdog
        if watchdog_src.exists():
            shutil.copy2(str(watchdog_src), str(AGENT_DIR / "watchdog.py"))
            log("[INFO]   -> agent\\watchdog.py")

        # Copy deploy.ps1 to AIO_ROOT if present
        deploy_src = STAGING_DIR / "deploy.ps1"
        if deploy_src.exists():
            shutil.copy2(str(deploy_src), str(AIO_ROOT / "deploy.ps1"))
            log("[INFO]   -> deploy.ps1")

        return True
    except Exception as e:
        log(f"[ERROR] Failed to deploy files: {e}")
        log(traceback.format_exc())
        return False


# ---------------------------------------------------------------------------
# Pip dependencies
# ---------------------------------------------------------------------------

def update_pip_dependencies() -> None:
    if not PYTHON.exists():
        log(f"[WARN] Python not found at {PYTHON}, skipping pip update")
        return
    try:
        log("[INFO] Updating pip dependencies...")
        cmd = [str(PYTHON), "-m", "pip", "install", "--upgrade"] + PIP_PACKAGES + ["--quiet"]
        subprocess.run(cmd, capture_output=True, timeout=300)
        log("[INFO] Dependencies updated.")
    except Exception as e:
        log(f"[WARN] pip install failed (non-fatal): {e}")


# LFS video files to download directly from GitHub raw content
# Format: (repo_path, local_dest)
LFS_VIDEO_FILES = [
    ("client/aio/vids/AIO_upper-loop.mov", KIOSK_DIR / "vids" / "AIO_upper-loop.mov"),
]

RAW_CONTENT_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/raw/refs/heads/{BRANCH}"


def download_lfs_videos() -> None:
    """Download LFS-tracked video files directly from GitHub raw content."""
    for repo_path, local_dest in LFS_VIDEO_FILES:
        try:
            # Skip if file already exists and is > 1MB (not a pointer)
            if local_dest.exists() and local_dest.stat().st_size > 1_000_000:
                log(f"[INFO] LFS video already present: {local_dest.name} "
                    f"({local_dest.stat().st_size // 1_000_000}MB)")
                continue

            # Check if deployed file is an LFS pointer (< 1KB text)
            if local_dest.exists() and local_dest.stat().st_size < 1024:
                log(f"[INFO] Found LFS pointer for {local_dest.name}, downloading actual file...")

            url = f"{RAW_CONTENT_URL}/{repo_path}"
            log(f"[INFO] Downloading LFS video: {repo_path}...")

            local_dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_dest = local_dest.with_suffix(".tmp")

            resp = requests.get(url, headers=_get_github_headers(), stream=True, timeout=600)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with tmp_dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=262144):  # 256KB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            if downloaded > 1_000_000:
                tmp_dest.rename(local_dest)
                log(f"[INFO] Downloaded {local_dest.name} ({downloaded // 1_000_000}MB)")
            else:
                log(f"[WARN] Downloaded file too small ({downloaded} bytes), may be LFS pointer")
                tmp_dest.unlink(missing_ok=True)

        except Exception as e:
            log(f"[WARN] Failed to download LFS video {repo_path}: {e}")


def configure_system() -> None:
    """Apply one-time system configuration for kiosk terminals.

    - Touch-to-mouse: disable HID touch visual feedback, force cursor visible
    - Git LFS: install if not present (for large video files)
    """
    import winreg

    log("[INFO] Applying system configuration...")

    # --- Touch-to-mouse: disable touch visual feedback & force mouse mode ---
    touch_settings = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Wisp\Touch",
         [("TouchGate", 0)]),  # 0 = force touch through mouse pipeline
        (winreg.HKEY_CURRENT_USER,
         r"Control Panel\Cursors",
         [("ContactVisualization", 0), ("GestureVisualization", 0)]),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Wisp\Pen\SysEventParameters",
         [("HoldMode", 3)]),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Policies\Microsoft\Windows\EdgeUI",
         [("AllowEdgeSwipe", 0)]),
    ]

    for hive, key_path, values in touch_settings:
        try:
            key = winreg.CreateKeyEx(hive, key_path, 0, winreg.KEY_SET_VALUE)
            for name, val in values:
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, val)
            winreg.CloseKey(key)
        except Exception as e:
            log(f"[WARN] Registry write failed ({key_path}): {e}")

    log("[INFO] Touch-to-mouse registry settings applied.")

    # --- Install Git LFS if not present ---
    try:
        result = subprocess.run(
            ["git", "lfs", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            log(f"[INFO] Git LFS already installed: {result.stdout.strip()}")
        else:
            raise FileNotFoundError
    except Exception:
        log("[INFO] Installing Git LFS...")
        try:
            subprocess.run(
                ["git", "lfs", "install"],
                capture_output=True, text=True, timeout=30,
            )
            log("[INFO] Git LFS installed.")
        except Exception as e:
            log(f"[WARN] Git LFS install failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup_staging() -> None:
    for path in [STAGING_DIR, TMP_EXTRACT_DIR, ZIP_PATH]:
        try:
            if path.is_dir():
                shutil.rmtree(str(path), ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Update orchestration
# ---------------------------------------------------------------------------

def perform_update(remote_sha: str) -> bool:
    log(f"[INFO] === Starting update to {remote_sha[:12]} ===")

    log("[1/6] Stopping services...")
    stop_services()

    log("[2/6] Downloading repo archive...")
    if not download_repo_zip():
        log("[ERROR] Download failed; aborting update.")
        start_services()
        return False

    log("[3/6] Extracting archive...")
    if not extract_repo_zip():
        log("[ERROR] Extraction failed; aborting update.")
        cleanup_staging()
        start_services()
        return False

    log("[4/6] Deploying files...")
    if not deploy_files():
        log("[ERROR] File deployment failed; aborting update.")
        cleanup_staging()
        start_services()
        return False

    log("[5/6] Updating version file...")
    write_version_file(remote_sha)

    log("[6/6] Updating Python dependencies...")
    update_pip_dependencies()

    log("[INFO] Restarting services...")
    start_services()

    cleanup_staging()

    log(f"[INFO] === Update to {remote_sha[:12]} completed successfully ===")
    return True


# ---------------------------------------------------------------------------
# Launch activation
# ---------------------------------------------------------------------------

def launch_activation() -> None:
    activation_script = KIOSK_DIR / "activation_win.py"
    if not activation_script.exists():
        log(f"[ERROR] activation_win.py not found at {activation_script}")
        return

    # --- Debug / maintenance mode ---
    # If maintenance.flag exists, open PowerShell for admin access instead
    maint_flag = PROGRAMDATA_ROOT / "config" / "maintenance.flag"
    if maint_flag.exists():
        log("[INFO] Maintenance flag detected — opening PowerShell for admin")
        try:
            maint_flag.unlink(missing_ok=True)  # one-shot: remove flag
            subprocess.Popen(["powershell.exe"], creationflags=subprocess.CREATE_NEW_CONSOLE)
            subprocess.Popen(["explorer.exe"])
        except Exception as e:
            log(f"[WARN] Failed to open maintenance shell: {e}")
        return  # Don't launch kiosk in maintenance mode

    cmd = [str(PYTHON), str(activation_script)]
    log(f"[INFO] Launching activation: {' '.join(cmd)}")
    try:
        touch_allow_exit_flag()
        subprocess.Popen(cmd, cwd=str(KIOSK_DIR))
    except Exception as e:
        log(f"[ERROR] Failed to launch activation_win.py: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def wait_for_network(max_wait: int = 60) -> bool:
    """Wait up to max_wait seconds for network to become available."""
    log(f"[INFO] Waiting for network (up to {max_wait}s)...")
    for i in range(max_wait):
        try:
            requests.head("https://api.github.com", timeout=3)
            log(f"[INFO] Network ready after {i}s")
            return True
        except Exception:
            time.sleep(1)
    log("[WARN] Network not available after timeout")
    return False


def main():
    log("=== AIO Auto-Updater (GitHub) ===")

    # Diagnostics
    headers = _get_github_headers()
    has_token = "Authorization" in headers
    log(f"[INFO] GitHub token: {'found' if has_token else 'MISSING'} ({GITHUB_TOKEN_FILE})")
    log(f"[INFO] Target API: {GITHUB_API_URL}")

    # Wait for network before checking updates (runs early at boot)
    wait_for_network()

    local_sha = get_local_commit_sha()
    if local_sha:
        log(f"[INFO] Local commit SHA: {local_sha[:12]}")
    else:
        log("[INFO] No local commit SHA found (first run or legacy install)")

    remote_sha = get_remote_commit_sha()

    if remote_sha and remote_sha != local_sha:
        log(f"[INFO] Update available: {local_sha[:12] if local_sha else '(none)'} -> {remote_sha[:12]}")
        try:
            success = perform_update(remote_sha)
            if not success:
                log("[WARN] Update failed; proceeding with existing installation.")
        except Exception as e:
            log(f"[ERROR] Unexpected error during update: {e}")
            log(traceback.format_exc())
            log("[WARN] Proceeding with existing installation.")
    elif remote_sha and remote_sha == local_sha:
        log("[INFO] Already up to date.")
    else:
        log("[WARN] Could not check for updates (no network?). Proceeding.")

    launch_activation()


if __name__ == "__main__":
    main()
