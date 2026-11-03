"""SQLite storage layer.

NetAlertZ keeps a single portable database file. All timestamps are UTC and
stored as ``YYYY-MM-DD HH:MM:SS`` text, which sorts lexicographically.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    mac            TEXT PRIMARY KEY,
    guid           TEXT NOT NULL,
    name           TEXT NOT NULL DEFAULT '',
    name_source    TEXT NOT NULL DEFAULT 'auto',
    owner          TEXT NOT NULL DEFAULT '',
    type           TEXT NOT NULL DEFAULT '',
    vendor         TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    group_name     TEXT NOT NULL DEFAULT '',
    location       TEXT NOT NULL DEFAULT '',
    site           TEXT NOT NULL DEFAULT '',
    ssid           TEXT NOT NULL DEFAULT '',
    vlan           TEXT NOT NULL DEFAULT '',
    icon           TEXT NOT NULL DEFAULT '',
    ip             TEXT NOT NULL DEFAULT '',
    first_seen     TEXT,
    last_seen      TEXT,
    present        INTEGER NOT NULL DEFAULT 0,
    archived       INTEGER NOT NULL DEFAULT 0,
    favorite       INTEGER NOT NULL DEFAULT 0,
    is_new         INTEGER NOT NULL DEFAULT 1,
    scan_enabled   INTEGER NOT NULL DEFAULT 1,
    static_ip      INTEGER NOT NULL DEFAULT 0,
    can_sleep      INTEGER NOT NULL DEFAULT 0,
    alert_down     INTEGER NOT NULL DEFAULT 1,
    skip_repeated  INTEGER NOT NULL DEFAULT 0,
    down_notified  INTEGER NOT NULL DEFAULT 0,
    comments       TEXT NOT NULL DEFAULT '',
    parent_mac     TEXT NOT NULL DEFAULT '',
    parent_port    TEXT NOT NULL DEFAULT '',
    parent_rel     TEXT NOT NULL DEFAULT '',
    custom_props   TEXT NOT NULL DEFAULT '{}',
    source         TEXT NOT NULL DEFAULT 'scan'
);
CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices(ip);
CREATE INDEX IF NOT EXISTS idx_devices_present ON devices(present);
CREATE INDEX IF NOT EXISTS idx_devices_parent ON devices(parent_mac);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mac        TEXT NOT NULL DEFAULT '',
    ip         TEXT NOT NULL DEFAULT '',
    type       TEXT NOT NULL,
    info       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    pending    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_mac ON events(mac);

CREATE TABLE IF NOT EXISTS presence (
    mac     TEXT NOT NULL,
    bucket  TEXT NOT NULL,
    samples INTEGER NOT NULL DEFAULT 0,
    online  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (mac, bucket)
);
CREATE INDEX IF NOT EXISTS idx_presence_bucket ON presence(bucket);

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mac           TEXT NOT NULL,
    ip            TEXT NOT NULL DEFAULT '',
    connected_at  TEXT NOT NULL,
    disconnected_at TEXT,
    info          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_mac ON sessions(mac, connected_at);

CREATE TABLE IF NOT EXISTS scan_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    trigger     TEXT NOT NULL DEFAULT 'manual',
    found       INTEGER NOT NULL DEFAULT 0,
    new_devices INTEGER NOT NULL DEFAULT 0,
    online      INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'running',
    message     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    level      TEXT NOT NULL DEFAULT 'info',
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);

CREATE TABLE IF NOT EXISTS logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    level      TEXT NOT NULL DEFAULT 'INFO',
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);

CREATE TABLE IF NOT EXISTS workflows (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    trigger      TEXT NOT NULL DEFAULT 'new_device',
    field        TEXT NOT NULL DEFAULT '',
    operator     TEXT NOT NULL DEFAULT 'equals',
    value        TEXT NOT NULL DEFAULT '',
    action_field TEXT NOT NULL DEFAULT '',
    action_value TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mac        TEXT NOT NULL,
    field      TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    changed_by TEXT NOT NULL DEFAULT 'USER',
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_mac ON device_history(mac, changed_at);
"""


class Database:
    """Thin connection wrapper with dict rows and safe transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived connection with sensible pragmas."""
        con = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init(self) -> None:
        """Create the schema and enable WAL mode."""
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)

    def q(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        """Run a read query and return rows as dictionaries."""
        with self.connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def q1(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        """Run a read query and return the first row or None."""
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: tuple | list = (), default: Any = None) -> Any:
        """Return the first column of the first row."""
        with self.connect() as con:
            row = con.execute(sql, params).fetchone()
        return row[0] if row is not None else default

    def x(self, sql: str, params: tuple | list = ()) -> int:
        """Run a write statement and return lastrowid (or rowcount)."""
        with self.connect() as con:
            cur = con.execute(sql, params)
            return int(cur.lastrowid or cur.rowcount or 0)

    def xmany(self, sql: str, rows: list[tuple]) -> None:
        """Run a write statement for many parameter sets in one transaction."""
        if not rows:
            return
        with self.connect() as con:
            con.executemany(sql, rows)

    def execute_script(self, sql: str) -> None:
        """Execute multiple statements."""
        with self.connect() as con:
            con.executescript(sql)
