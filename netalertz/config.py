"""Application paths, settings defaults and metadata.

All user data lives under ``NETALERTZ_HOME`` (``~/.netalertz`` by default) so the
app can be launched from anywhere with a single command.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "NetAlertZ"
VERSION = "1.0.0"
TAGLINE = "network intelligence, in your terminal"

DEFAULT_SETTINGS: dict[str, Any] = {
    # scanning
    "scan_interval": 120,
    "scheduled_scans": True,
    "auto_scan_on_start": True,
    "scan_subnets": "",
    "scan_interface": "",
    "discovery_method": "auto",
    "scan_timeout": 120,
    "resolve_names": True,
    "vendor_lookup": True,
    # behaviour
    "down_after_minutes": 60,
    "retention_days": 90,
    "max_events": 5000,
    "notify_new": True,
    "notify_down": True,
    "notify_online": False,
    "in_app_only": True,
    # integrations
    "webhook_url": "",
    "telegram_token": "",
    "telegram_chat": "",
    # interface
    "theme": "netalertz",
    "show_macs": True,
    "demo_seeded": False,
}

# Metadata drives the Settings screen (label, editor, validation, help text).
SETTING_META: dict[str, dict[str, Any]] = {
    "scan_interval": {
        "label": "Scan interval",
        "group": "Scanning",
        "type": "int",
        "suffix": "sec",
        "min": 15,
        "max": 86400,
        "help": "Seconds between scheduled discovery scans.",
    },
    "scheduled_scans": {
        "label": "Scheduled scans",
        "group": "Scanning",
        "type": "bool",
        "help": "Run discovery automatically in the background.",
    },
    "auto_scan_on_start": {
        "label": "Scan on launch",
        "group": "Scanning",
        "type": "bool",
        "help": "Start a discovery scan as soon as NetAlertZ opens.",
    },
    "scan_subnets": {
        "label": "Scan targets",
        "group": "Scanning",
        "type": "str",
        "help": "Comma separated CIDRs. Empty means auto-detect the local network.",
    },
    "scan_interface": {
        "label": "Interface",
        "group": "Scanning",
        "type": "str",
        "help": "Network interface for arp-scan (e.g. en0, eth0). Empty means auto.",
    },
    "discovery_method": {
        "label": "Discovery method",
        "group": "Scanning",
        "type": "choice",
        "options": ["auto", "arp-scan", "nmap", "ping", "cache"],
        "help": "How hosts are discovered. Auto picks the best available tool.",
    },
    "scan_timeout": {
        "label": "Scan timeout",
        "group": "Scanning",
        "type": "int",
        "suffix": "sec",
        "min": 15,
        "max": 1800,
        "help": "Hard limit for a single discovery command.",
    },
    "resolve_names": {
        "label": "Resolve hostnames",
        "group": "Scanning",
        "type": "bool",
        "help": "Reverse-DNS lookups for newly discovered devices.",
    },
    "vendor_lookup": {
        "label": "Vendor lookup",
        "group": "Scanning",
        "type": "bool",
        "help": "Map MAC prefixes to hardware vendors (offline OUI table).",
    },
    "down_after_minutes": {
        "label": "Down after",
        "group": "Alerts",
        "type": "int",
        "suffix": "min",
        "min": 1,
        "max": 10080,
        "help": "Minutes without a sighting before a device is marked Down.",
    },
    "notify_new": {
        "label": "Notify on new devices",
        "group": "Alerts",
        "type": "bool",
        "help": "Raise an in-app alert when an unknown device appears.",
    },
    "notify_down": {
        "label": "Notify on down devices",
        "group": "Alerts",
        "type": "bool",
        "help": "Raise an in-app alert when a monitored device goes down.",
    },
    "notify_online": {
        "label": "Notify on reconnect",
        "group": "Alerts",
        "type": "bool",
        "help": "Raise a note when a device comes back online.",
    },
    "in_app_only": {
        "label": "In-app only",
        "group": "Alerts",
        "type": "bool",
        "help": "Disable webhook and Telegram delivery.",
    },
    "webhook_url": {
        "label": "Webhook URL",
        "group": "Integrations",
        "type": "str",
        "help": "JSON POST target for alerts (optional).",
    },
    "telegram_token": {
        "label": "Telegram bot token",
        "group": "Integrations",
        "type": "secret",
        "help": "Optional bot token from @BotFather.",
    },
    "telegram_chat": {
        "label": "Telegram chat id",
        "group": "Integrations",
        "type": "str",
        "help": "Destination chat id for Telegram alerts.",
    },
    "retention_days": {
        "label": "Event retention",
        "group": "Data",
        "type": "int",
        "suffix": "days",
        "min": 1,
        "max": 3650,
        "help": "Delete events and presence history older than this.",
    },
    "max_events": {
        "label": "Maximum events",
        "group": "Data",
        "type": "int",
        "min": 100,
        "max": 100000,
        "help": "Hard cap for the events table.",
    },
    "theme": {
        "label": "Colour theme",
        "group": "Interface",
        "type": "choice",
        "options": ["netalertz", "ember", "nord", "mono"],
        "help": "Terminal colour palette. F2 cycles themes instantly.",
    },
    "show_macs": {
        "label": "Show MAC addresses",
        "group": "Interface",
        "type": "bool",
        "help": "Display MAC addresses in device tables.",
    },
}

THEME_LABELS = {
    "netalertz": "NetAlertZ",
    "ember": "Ember",
    "nord": "Nord",
    "mono": "Mono",
}


def home() -> Path:
    """Return the application data directory, creating it when needed."""
    override = os.environ.get("NETALERTZ_HOME")
    path = Path(override).expanduser() if override else Path.home() / ".netalertz"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    """Return the default SQLite database path."""
    return home() / "netalertz.db"


def log_path() -> Path:
    """Return the rotating log file path."""
    return home() / "netalertz.log"


def export_dir() -> Path:
    """Return the folder used for CSV exports."""
    path = home() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Settings:
    """Typed key/value settings persisted in SQLite."""

    def __init__(self, db: Any) -> None:
        self.db = db
        self._cache: dict[str, Any] = {}
        self.seed()
        self.reload()

    def seed(self) -> None:
        """Insert defaults for keys that do not exist yet."""
        for key, value in DEFAULT_SETTINGS.items():
            self.db.x(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def reload(self) -> None:
        """Reload all values from the database."""
        cache: dict[str, Any] = {}
        for row in self.db.q("SELECT key, value FROM settings"):
            try:
                cache[row["key"]] = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                cache[row["key"]] = row["value"]
        self._cache = cache

    def get(self, key: str, default: Any = None) -> Any:
        """Return a setting value, falling back to defaults."""
        if key in self._cache:
            return self._cache[key]
        if default is not None:
            return default
        return DEFAULT_SETTINGS.get(key)

    def get_int(self, key: str) -> int:
        """Return a setting coerced to int."""
        try:
            return int(self.get(key) or 0)
        except (TypeError, ValueError):
            return int(DEFAULT_SETTINGS.get(key, 0))

    def get_bool(self, key: str) -> bool:
        """Return a setting coerced to bool."""
        return bool(self.get(key))

    def set(self, key: str, value: Any) -> None:
        """Persist one setting and update the cache."""
        self._cache[key] = value
        self.db.x(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a copy of all current setting values."""
        return dict(self._cache)

    def reset(self) -> None:
        """Reset every setting to its default value."""
        for key, value in DEFAULT_SETTINGS.items():
            self.set(key, value)
