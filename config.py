"""
Configuration management for Pick Note Print Service.

Stores and retrieves settings from a local config.json file,
including Frappe credentials, printer settings, and poll intervals.
"""

import json
import os
from typing import Any

# Path to the config file — stored alongside the application
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Default configuration values
DEFAULT_CONFIG: dict[str, Any] = {
    "frappe_url": "",
    "api_token": "",
    "branch": "",
    "printer_name": "",
    "printer_type": "windows",     # "usb", "network", "serial", or "windows"
    "printer_address": "",         # IP:port for network, COM port for serial
    "poll_interval_seconds": 30,
    "print_format": "",            # Optional Frappe print format name
    "auto_start_worker": False,    # Auto-start print worker on app startup
    # Thermal receipt layout settings
    "paper_width": 42,             # Characters per line (42 for 80mm paper)
    "auto_cut": True,              # Send ESC/POS paper cut after printing
    "feed_lines": 3,               # Blank lines before cut (for tear-off)
}

# In-memory cache of the current configuration
_config: dict[str, Any] = {}


def load_config() -> dict[str, Any]:
    """
    Load configuration from config.json on disk.

    If the file does not exist, returns a copy of the default config.
    Merges any missing keys from DEFAULT_CONFIG so that new fields
    added in future versions are always present.

    Returns:
        dict: The loaded configuration dictionary.
    """
    global _config

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)

            # Merge defaults for any keys not yet in the stored config
            merged = {**DEFAULT_CONFIG, **stored}
            _config = merged
        except (json.JSONDecodeError, IOError) as exc:
            print(f"[config] Warning: Failed to read {CONFIG_FILE}: {exc}")
            _config = DEFAULT_CONFIG.copy()
    else:
        _config = DEFAULT_CONFIG.copy()

    # Backward compatibility: migrate api_key + api_secret to api_token
    if _config.get("api_key") and _config.get("api_secret") and not _config.get("api_token"):
        _config["api_token"] = f"{_config['api_key']}:{_config['api_secret']}"
        _config.pop("api_key", None)
        _config.pop("api_secret", None)

    return _config.copy()


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    """
    Save the provided configuration dictionary to config.json.

    Merges the incoming data with DEFAULT_CONFIG so that every
    expected key is present and correctly typed.

    Args:
        data: A dict of configuration values to persist.

    Returns:
        dict: The saved configuration dictionary.

    Raises:
        IOError: If the file cannot be written.
    """
    global _config

    # Start from defaults, overlay with incoming data
    merged = {**DEFAULT_CONFIG, **data}

    # Ensure poll_interval_seconds is an integer ≥ 5
    try:
        merged["poll_interval_seconds"] = max(5, int(merged["poll_interval_seconds"]))
    except (ValueError, TypeError):
        merged["poll_interval_seconds"] = DEFAULT_CONFIG["poll_interval_seconds"]

    # Ensure paper_width is a sensible integer
    try:
        merged["paper_width"] = max(20, min(64, int(merged["paper_width"])))
    except (ValueError, TypeError):
        merged["paper_width"] = DEFAULT_CONFIG["paper_width"]

    # Ensure feed_lines is a sensible integer
    try:
        merged["feed_lines"] = max(0, min(10, int(merged["feed_lines"])))
    except (ValueError, TypeError):
        merged["feed_lines"] = DEFAULT_CONFIG["feed_lines"]

    # Ensure auto_cut is a boolean
    merged["auto_cut"] = bool(merged.get("auto_cut", True))

    # Strip whitespace from string fields
    for key in ("frappe_url", "api_token", "branch",
                "printer_name", "printer_type", "printer_address"):
        if isinstance(merged.get(key), str):
            merged[key] = merged[key].strip()

    # Remove trailing slash from frappe_url
    if merged["frappe_url"].endswith("/"):
        merged["frappe_url"] = merged["frappe_url"].rstrip("/")

    _config = merged

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    return _config.copy()


def get_config() -> dict[str, Any]:
    """
    Return the current in-memory configuration.

    If the config has not been loaded yet, loads it from disk first.

    Returns:
        dict: The current configuration dictionary.
    """
    if not _config:
        load_config()
    return _config.copy()


def is_configured() -> bool:
    """
    Check whether the minimum required settings are present.

    The service needs at least a Frappe URL, API credentials,
    a branch name, and a printer name to operate.

    Returns:
        bool: True if the essential fields are populated.
    """
    cfg = get_config()
    return all([
        cfg.get("frappe_url"),
        cfg.get("api_token"),
        cfg.get("branch"),
        cfg.get("printer_name"),
    ])
