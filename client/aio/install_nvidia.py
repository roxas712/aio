#!/usr/bin/env python3
"""Download and install NVIDIA RTX 3050 drivers silently.

Usage (run as Administrator):
    py -3.14 install_nvidia.py
"""

import os
import sys
import subprocess
import urllib.request
import tempfile

# Latest Game Ready Driver for RTX 3050 (Windows 10/11 64-bit DCH)
DRIVER_URL = "https://us.download.nvidia.com/Windows/572.83/572.83-desktop-win10-win11-64bit-international-dch-whql.exe"
DRIVER_FILE = os.path.join(tempfile.gettempdir(), "nvidia_driver.exe")


def main():
    print("=" * 60)
    print("  NVIDIA RTX 3050 Driver Installer")
    print("=" * 60)

    # Download
    if os.path.exists(DRIVER_FILE) and os.path.getsize(DRIVER_FILE) > 100_000_000:
        print(f"\n[INFO] Driver already downloaded: {DRIVER_FILE}")
        print(f"       Size: {os.path.getsize(DRIVER_FILE) // 1_000_000} MB")
    else:
        print(f"\n[INFO] Downloading driver...")
        print(f"       URL: {DRIVER_URL}")
        print(f"       Saving to: {DRIVER_FILE}")
        print()

        def progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(100, downloaded * 100 // total_size)
                mb = downloaded // 1_000_000
                total_mb = total_size // 1_000_000
                bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
                print(f"\r       [{bar}] {pct}%  ({mb}/{total_mb} MB)", end="", flush=True)

        try:
            urllib.request.urlretrieve(DRIVER_URL, DRIVER_FILE, reporthook=progress)
            print(f"\n\n[OK] Download complete: {os.path.getsize(DRIVER_FILE) // 1_000_000} MB")
        except Exception as e:
            print(f"\n\n[ERROR] Download failed: {e}")
            sys.exit(1)

    # Install silently
    print("\n[INFO] Starting silent install (this may take a few minutes)...")
    print("       The screen may flicker during installation.")
    try:
        result = subprocess.run(
            [DRIVER_FILE, "-s", "-noreboot"],
            timeout=600,
        )
        if result.returncode == 0:
            print("\n[OK] Driver installed successfully!")
        else:
            print(f"\n[WARN] Installer exited with code {result.returncode}")
            print("       This may still be OK — check Device Manager.")
    except subprocess.TimeoutExpired:
        print("\n[WARN] Install timed out after 10 minutes")
    except Exception as e:
        print(f"\n[ERROR] Install failed: {e}")
        sys.exit(1)

    print("\n[INFO] Reboot required for driver to take effect.")
    resp = input("       Reboot now? (y/n): ").strip().lower()
    if resp == "y":
        subprocess.run(["shutdown", "/r", "/t", "5", "/c", "NVIDIA driver installed - rebooting"])
        print("       Rebooting in 5 seconds...")
    else:
        print("       Please reboot manually when ready.")


if __name__ == "__main__":
    main()
