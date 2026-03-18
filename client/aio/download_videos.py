#!/usr/bin/env python3
"""Download LFS-tracked video files for AIO kiosk.

Usage (run on terminal):
    py -3.14 download_videos.py
"""

import os
import sys
import requests
from pathlib import Path

AIO_ROOT = Path(r"C:\Program Files\aio")
KIOSK_DIR = AIO_ROOT / "kiosk"
GITHUB_TOKEN_FILE = AIO_ROOT / "config" / "github_token.txt"

REPO_OWNER = "roxas712"
REPO_NAME = "aio"
BRANCH = "main"
RAW_CONTENT_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/raw/refs/heads/{BRANCH}"

# Files to download: (repo_path, local_dest)
LFS_VIDEO_FILES = [
    ("client/aio/vids/AIO_upper-loop.mov", KIOSK_DIR / "vids" / "AIO_upper-loop.mov"),
]


def get_headers():
    headers = {}
    try:
        if GITHUB_TOKEN_FILE.exists():
            token = GITHUB_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                headers["Authorization"] = f"token {token}"
    except Exception:
        pass
    return headers


def main():
    print("=" * 60)
    print("  AIO Video Downloader")
    print("=" * 60)

    headers = get_headers()
    has_token = "Authorization" in headers
    print(f"\nGitHub token: {'found' if has_token else 'MISSING'}")

    for repo_path, local_dest in LFS_VIDEO_FILES:
        print(f"\n--- {local_dest.name} ---")

        # Check existing file
        if local_dest.exists():
            size = local_dest.stat().st_size
            print(f"  Existing: {size:,} bytes ({size // 1_000_000} MB)")
            if size > 1_000_000:
                print(f"  Already downloaded. Skipping.")
                continue
            else:
                print(f"  LFS pointer ({size} bytes). Downloading actual file...")
        else:
            print(f"  Not found. Downloading...")

        url = f"{RAW_CONTENT_URL}/{repo_path}"
        print(f"  URL: {url}")

        local_dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = local_dest.with_suffix(".tmp")

        try:
            resp = requests.get(url, headers=headers, stream=True, timeout=600)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with tmp_dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=262144):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(100, downloaded * 100 // total)
                            mb = downloaded // 1_000_000
                            total_mb = total // 1_000_000
                            bar = "#" * (pct // 2) + "-" * (50 - pct // 2)
                            print(f"\r  [{bar}] {pct}%  ({mb}/{total_mb} MB)", end="", flush=True)

            print()  # newline after progress bar

            if downloaded > 1_000_000:
                tmp_dest.rename(local_dest)
                print(f"  [OK] Downloaded: {downloaded:,} bytes ({downloaded // 1_000_000} MB)")
            else:
                print(f"  [WARN] File too small ({downloaded} bytes) — may be LFS pointer")
                tmp_dest.unlink(missing_ok=True)

        except Exception as e:
            print(f"  [ERROR] Download failed: {e}")
            if tmp_dest.exists():
                tmp_dest.unlink(missing_ok=True)

    # Also check for any .mp4 files in vids folder
    vids_dir = KIOSK_DIR / "vids"
    if vids_dir.exists():
        print(f"\n--- Video files in {vids_dir} ---")
        for f in sorted(vids_dir.iterdir()):
            sz = f.stat().st_size
            status = "OK" if sz > 1_000_000 else "LFS POINTER" if sz < 1024 else "small"
            print(f"  {f.name}: {sz:,} bytes ({sz // 1_000_000} MB) [{status}]")

    print("\nDone.")


if __name__ == "__main__":
    main()
