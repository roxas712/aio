#!/usr/bin/env python3
# updater_win.py

import os
import sys
import json
import re
import subprocess
from pathlib import Path

import requests
from urllib.parse import urlparse

def touch_allow_exit_flag():
    try:
        flag = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio" / "config" / "allow_exit.flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    except Exception:
        pass

# Paths
AIO_ROOT = Path(r"C:\Program Files\aio")
KIOSK_DIR = AIO_ROOT / "kiosk"

PROGRAMDATA_ROOT = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "aio"
RAW_UPDATE_DIR = PROGRAMDATA_ROOT / "updates"

# We keep version.json alongside the kiosk scripts
VERSION_FILE = KIOSK_DIR / "version.json"

# Update endpoint
UPDATE_API_URL = "https://pgoc.ai/update"


def parse_version(vstr: str):
    """
    Parse a version string like 'V1.17' or '1.17' or 'v2.0.0' into a tuple of ints.
    """
    if not vstr:
        return (0,)
    v = vstr.strip()
    if v.lower().startswith(("v", "V")):
        v = v[1:]
    nums = re.findall(r"\d+", v)
    if not nums:
        return (0,)
    return tuple(int(n) for n in nums)


def get_local_version() -> str:
    """
    Read the local version.json if present, otherwise return '0.0'.
    """
    if VERSION_FILE.exists():
        try:
            with VERSION_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("version", "0.0")
        except Exception:
            return "0.0"
    return "0.0"


def write_local_version(version: str) -> None:
    """
    Write the given version string into version.json.
    """
    try:
        with VERSION_FILE.open("w", encoding="utf-8") as f:
            json.dump({"version": version}, f, indent=2)
    except Exception as e:
        print(f"[WARN] Failed to write version.json: {e}")


def get_server_version():
    """
    Query the update API for the latest version and download link.
    Returns (latest_version, download_link) or (None, None) on failure.
    """
    try:
        print("[INFO] Checking server for updates...")
        resp = requests.get(UPDATE_API_URL, timeout=10)
        if not resp.ok:
            print(f"[WARN] Update API returned {resp.status_code}: {resp.text}")
            return None, None
        data = resp.json()
        latest = data.get("latest_version")
        link = data.get("download_link")
        print(f"[INFO] Server reports latest_version={latest}, download_link={link}")
        return latest, link
    except Exception as e:
        print(f"[WARN] Failed to contact update API: {e}")
        return None, None


def download_installer(download_url: str, version: str) -> Path:
    
    RAW_UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    parsed = urlparse(download_url)
    name = os.path.basename(parsed.path) or f"AIOv2-Update-{version}.exe"
    installer_path = RAW_UPDATE_DIR / name

    print(f"[INFO] Downloading update installer to {installer_path}...")
    r = requests.get(download_url, stream=True, timeout=60)
    r.raise_for_status()
    with installer_path.open("wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    print("[INFO] Download completed.")
    return installer_path


def run_installer_silent(installer_path: Path) -> None:
    """
    Run the given installer EXE silently using Inno Setup-style flags.
    """
    if not installer_path.exists():
        print(f"[ERROR] Installer not found at {installer_path}")
        return

    cmd = [
        str(installer_path),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
    ]
    print(f"[INFO] Running installer: {' '.join(cmd)}")
    try:
        # We don't use check=True so a failure doesn't crash the updater outright.
        subprocess.run(cmd, cwd=str(installer_path.parent), timeout=600)
        print("[INFO] Installer finished (or timed out).")
    except Exception as e:
        print(f"[ERROR] Failed to run installer: {e}")


def launch_activation() -> None:
    """
    Launch activation_win.py via the current Python interpreter (sys.executable).
    """
    activation_script = KIOSK_DIR / "activation_win.py"
    if not activation_script.exists():
        print(f"[ERROR] activation_win.py not found at {activation_script}")
        return

    cmd = [sys.executable, str(activation_script)]
    print(f"[INFO] Launching activation: {' '.join(cmd)}")
    try:
        touch_allow_exit_flag()
        subprocess.Popen(cmd, cwd=str(KIOSK_DIR))
    except Exception as e:
        print(f"[ERROR] Failed to launch activation_win.py: {e}")


def main():
    print("=== AIO v2 Updater (Windows) ===")
    local_version = get_local_version()
    print(f"[INFO] Local version: {local_version}")

    server_version, download_link = get_server_version()

    if server_version and download_link:
        try:
            local_tuple = parse_version(local_version)
            remote_tuple = parse_version(server_version)
        except Exception:
            local_tuple = (0,)
            remote_tuple = (0,)

        if remote_tuple > local_tuple:
            print(f"[INFO] Update available: {local_version} -> {server_version}")
            try:
                installer_path = download_installer(download_link, server_version)
            except Exception as e:
                print(f"[ERROR] Failed to download update installer: {e}")
                print("[INFO] Proceeding to launch existing activation.")
                launch_activation()
                return

            run_installer_silent(installer_path)
            # Assume update succeeded; write new version locally
            write_local_version(server_version)
        else:
            print("[INFO] No update needed; local version is up to date.")
    else:
        print("[WARN] Could not retrieve update info; skipping update.")

    # Always launch activation at the end
    launch_activation()


if __name__ == "__main__":
    main()