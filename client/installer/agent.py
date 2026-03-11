import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
import requests


DEFAULT_IDLE_INTERVAL = 5        # seconds
DEFAULT_ACTIVE_INTERVAL = 45     # seconds
MIN_INTERVAL = 3                 # safety floor


def is_frozen() -> bool:
    """Return True if running as a frozen EXE (PyInstaller)."""
    return getattr(sys, "frozen", False) is not False


def get_base_root() -> Path:
    r"""
    Base root for AIO runtime.

    - When running from source:   C:\AIOv2  (assuming C:\AIOv2\agent\agent.py)
    - When running as EXE:        C:\Program Files\aio  (assuming ...\agent\agent.exe)
    """
    if is_frozen():
        exe_path = Path(sys.executable).resolve()
        # ...\aio\agent\agent.exe -> ...\aio
        return exe_path.parent.parent
    else:
        script_path = Path(__file__).resolve()
        # ...\AIOv2\agent\agent.py -> ...\AIOv2
        return script_path.parent.parent


def get_paths() -> Dict[str, Path]:
    """Return important paths for config and logging."""
    root = get_base_root()
    config_dir = root / "config"
    logs_dir = root / "logs"

    # Make sure folders exist in dev mode; in production the installer will create them
    logs_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": root,
        "config_dir": config_dir,
        "logs_dir": logs_dir,
        "config_file": config_dir / "client.json",
        "log_file": logs_dir / "agent.log",
    }


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("AIO Agent starting up")


def load_config(config_file: Path) -> Dict[str, Any]:
    """
    Load client config from JSON.

    Expected structure (example):
    {
        "uuid": "dev-machine-001",
        "server_url": "http://10.0.0.36:5000",
        "terminal_type": "multi",
        "poll_interval_idle": 5,
        "poll_interval_active": 45,
        "ping_path": "/client/ping",
        "app_version": "2.0.0",
        "lock_status": "unlocked"
    }
    """
    if not config_file.exists():
        logging.warning("Config file not found at %s; using minimal defaults", config_file)
        return {}

    try:
        with config_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Config root must be a JSON object")
        return data
    except Exception as e:
        logging.error("Failed to load config from %s: %s", config_file, e)
        return {}


def save_config(config_file: Path, cfg: Dict[str, Any]) -> None:
    """Persist updated client config back to disk."""
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with config_file.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        logging.info("Config saved to %s", config_file)
    except Exception as e:
        logging.error("Failed to save config to %s: %s", config_file, e)


def get_config_value(cfg: Dict[str, Any], key: str, default: Any) -> Any:
    value = cfg.get(key, default)
    if isinstance(default, (int, float)):
        # Defensive cast for numeric fields
        try:
            return type(default)(value)
        except Exception:
            return default
    return value


def clamp_interval(value: int) -> int:
    try:
        value = int(value)
    except Exception:
        value = DEFAULT_IDLE_INTERVAL
    return max(MIN_INTERVAL, value)


def get_system_info() -> Dict[str, Any]:
    """Collect lightweight system info for the heartbeat."""
    try:
        cpu = psutil.cpu_percent(interval=None)
    except Exception:
        cpu = None

    try:
        mem = psutil.virtual_memory().percent
    except Exception:
        mem = None

    hostname = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown"

    return {
        "hostname": hostname,
        "cpu_percent": cpu,
        "mem_percent": mem,
    }


def determine_activity_state() -> str:
    """
    Determine 'idle' vs 'active' state.

    For now this checks an optional text file at:
    <base_root>/config/activity_state.txt

    If the file exists and contains 'active' or 'idle' (case-insensitive),
    that value is used. Otherwise, the default is 'idle'.
    """
    try:
        root = get_base_root()
        state_file = root / "config" / "activity_state.txt"
        if state_file.exists():
            content = state_file.read_text(encoding="utf-8").strip().lower()
            if content in ("idle", "active"):
                return content
    except Exception as e:
        logging.debug("Failed to read activity state file: %s", e)
    return "idle"


def build_payload(cfg: Dict[str, Any]) -> Dict[str, Any]:
    uuid = cfg.get("uuid") or "unknown-uuid"
    terminal_type = cfg.get("terminal_type", "multi")
    state = determine_activity_state()
    app_version = cfg.get("app_version", "unknown")
    lock_status = cfg.get("lock_status", "unlocked")

    payload = {
        "uuid": uuid,
        "terminal_type": terminal_type,
        "state": state,
        "system": get_system_info(),
        "app_version": app_version,
        "lock_status": lock_status,
        # room for more fields later
    }
    return payload


def send_ping(
    server_url: str, ping_path: str, payload: Dict[str, Any], timeout: float = 5.0
) -> Optional[Dict[str, Any]]:
    url = server_url.rstrip("/") + ping_path
    try:
        logging.debug("Sending ping to %s with payload: %s", url, payload)
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        logging.info("Ping OK (status %s)", resp.status_code)
        logging.debug("Server response: %s", data)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logging.warning("Ping failed to %s: %s", url, e)
        return None


def apply_server_response(
    cfg: Dict[str, Any], response: Dict[str, Any], config_file: Path
) -> Dict[str, Any]:
    """
    Handle any commands or config updates from the server.

    This is a skeleton for now; it:
    - Logs commands/config
    - Updates local in-memory config with new poll intervals if provided
    - Persists config changes back to disk when a 'config' block is present
    """
    if not response:
        return cfg

    commands = response.get("commands") or {}
    new_config = response.get("config") or {}

    if commands:
        logging.info("Received commands from server: %s", commands)

        if commands.get("restart"):
            logging.info("Executing system restart (requested by server)")
            try:
                subprocess.Popen(
                    ["shutdown", "/r", "/t", "5", "/c", "AIO remote restart"],
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
            except Exception as e:
                logging.error("Failed to execute restart: %s", e)

    if new_config:
        logging.info("Received config from server: %s", new_config)
        # Merge server-provided config into local cfg
        cfg.update(new_config)
        # Persist changes to disk
        save_config(config_file, cfg)

    # Dynamic poll intervals from server
    ping_config = response.get("poll") or {}
    idle_interval = ping_config.get("idle_interval")
    active_interval = ping_config.get("active_interval")

    if idle_interval is not None:
        cfg["poll_interval_idle"] = clamp_interval(idle_interval)
    if active_interval is not None:
        cfg["poll_interval_active"] = clamp_interval(active_interval)

    return cfg


def main_loop() -> None:
    paths = get_paths()
    setup_logging(paths["log_file"])

    logging.info("Base root: %s", paths["root"])
    logging.info("Config file: %s", paths["config_file"])

    cfg = load_config(paths["config_file"])

    server_url = get_config_value(cfg, "server_url", "http://127.0.0.1:5000")
    ping_path = cfg.get("ping_path", "/client/ping")

    idle_interval = clamp_interval(get_config_value(cfg, "poll_interval_idle", DEFAULT_IDLE_INTERVAL))
    active_interval = clamp_interval(get_config_value(cfg, "poll_interval_active", DEFAULT_ACTIVE_INTERVAL))

    logging.info("Initial server URL: %s", server_url)
    logging.info("Ping path: %s", ping_path)
    logging.info("Idle interval: %s seconds", idle_interval)
    logging.info("Active interval: %s seconds", active_interval)

    backoff_factor = 1

    while True:
        try:
            state = determine_activity_state()
            payload = build_payload(cfg)
            response = send_ping(server_url, ping_path, payload)

            if response is not None:
                cfg = apply_server_response(cfg, response, paths["config_file"])
                # refresh intervals in case server changed them
                idle_interval = clamp_interval(cfg.get("poll_interval_idle", idle_interval))
                active_interval = clamp_interval(cfg.get("poll_interval_active", active_interval))
                backoff_factor = 1  # reset on success
            else:
                # simple backoff on failure, capped
                backoff_factor = min(backoff_factor * 2, 6)
                logging.info("Backing off due to failures (factor=%s)", backoff_factor)

            interval = idle_interval if state == "idle" else active_interval
            sleep_time = interval * backoff_factor
            logging.debug("State=%s sleeping for %s seconds", state, sleep_time)
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            logging.info("AIO Agent shutting down (KeyboardInterrupt)")
            break
        except Exception as e:
            logging.exception("Unexpected error in main loop: %s", e)
            time.sleep(10)


if __name__ == "__main__":
    main_loop()