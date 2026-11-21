"""Core application engine: discovery ingestion, events, alerts and tools."""

from __future__ import annotations

import csv
import logging
import queue
import re
import socket
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from .config import VERSION, db_path as default_db_path, export_dir, log_path
from .db import Database
from .notifications import Notifier
from .scanner import Host, Scanner
from .utils import (
    ago,
    default_gateway,
    default_network,
    human_duration,
    is_ip,
    is_mac,
    local_ts,
    normalize_mac,
    now_str,
    parse_ts,
    run_command,
    utcnow,
)

STATUS_LABELS = {
    "online": "Online",
    "offline": "Offline",
    "down": "Down",
    "sleeping": "Sleeping",
    "archived": "Archived",
}

EDITABLE_FIELDS = {
    "name",
    "owner",
    "type",
    "vendor",
    "group_name",
    "location",
    "site",
    "ssid",
    "vlan",
    "icon",
    "comments",
    "favorite",
    "archived",
    "is_new",
    "scan_enabled",
    "static_ip",
    "can_sleep",
    "alert_down",
    "skip_repeated",
    "parent_mac",
    "parent_port",
    "parent_rel",
    "custom_props",
    "name_source",
    "ip",
}

BOOL_FIELDS = {
    "favorite",
    "archived",
    "is_new",
    "scan_enabled",
    "static_ip",
    "can_sleep",
    "alert_down",
    "skip_repeated",
}

WORKFLOW_ACTIONS = EDITABLE_FIELDS - {"ip", "custom_props", "name_source"}

OPERATORS = [
    "equals",
    "not_equals",
    "contains",
    "starts_with",
    "ends_with",
    "is_empty",
    "not_empty",
    "regex",
]


def _as_bool(value: Any) -> int:
    """Coerce common truthy values to 0/1."""
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "on"} else 0


class Engine:
    """Owns the database, scanner, notifier and all domain operations."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.db = Database(database_path or default_db_path())
        from .config import Settings

        self.settings = Settings(self.db)
        self.scanner = Scanner(self.settings)
        self.events: queue.Queue[dict] = queue.Queue()
        self.notifier = Notifier(self.db, self.settings, self.emit, self.log)
        self.scan_lock = threading.Lock()
        self._scanning = False
        self._scheduler: ScanScheduler | None = None
        self._gateway: str | None = None
        self.started_at = now_str()
        self._logger = self._setup_logger()
        self.log("INFO", f"NetAlertZ {VERSION} ready · database {self.db.path}")

    # ------------------------------------------------------------------ plumbing
    def _setup_logger(self) -> logging.Logger:
        """Configure the rotating file logger once per process."""
        logger = logging.getLogger("netalertz")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        if not logger.handlers:
            try:
                handler = logging.FileHandler(log_path(), encoding="utf-8")
                handler.setFormatter(
                    logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
                )
                logger.addHandler(handler)
            except OSError:
                pass
        return logger

    def emit(self, kind: str, **payload: Any) -> None:
        """Publish an event for the TUI to consume."""
        try:
            self.events.put_nowait({"type": kind, **payload})
        except queue.Full:  # pragma: no cover
            pass

    def drain_events(self, limit: int = 100) -> list[dict]:
        """Drain pending UI events."""
        items = []
        for _ in range(limit):
            try:
                items.append(self.events.get_nowait())
            except queue.Empty:
                break
        return items

    def log(self, level: str, message: str) -> None:
        """Write to the file log, the database log and the UI stream."""
        level = level.upper()
        self._logger.log(getattr(logging, level, logging.INFO), message)
        try:
            self.db.x(
                "INSERT INTO logs(level, message, created_at) VALUES (?, ?, ?)",
                (level, message, now_str()),
            )
            if self.db.scalar("SELECT COUNT(*) FROM logs", default=0) > 3000:
                self.db.x(
                    "DELETE FROM logs WHERE id NOT IN "
                    "(SELECT id FROM logs ORDER BY id DESC LIMIT 2000)"
                )
        except Exception:
            pass
        self.emit("log", level=level, message=message)

    # ------------------------------------------------------------------- status
    @property
    def scanning(self) -> bool:
        """Return True while a scan is in progress."""
        return self._scanning

    def _down_cutoff(self) -> str:
        """Return the timestamp before which missing devices are Down."""
        minutes = self.settings.get_int("down_after_minutes")
        return (utcnow() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")

    def device_status(self, row: dict) -> str:
        """Derive a display status from a device row."""
        if int(row.get("archived") or 0):
            return "archived"
        if int(row.get("present") or 0):
            return "online"
        cutoff = self._down_cutoff()
        if int(row.get("can_sleep") or 0) and (row.get("last_seen") or "") >= cutoff:
            return "sleeping"
        if int(row.get("down_notified") or 0):
            return "down"
        return "offline"

    def decorate(self, row: dict) -> dict:
        """Add derived fields used by the UI."""
        row = dict(row)
        row["status"] = self.device_status(row)
        row["status_label"] = STATUS_LABELS.get(row["status"], row["status"].title())
        row["last_seen_human"] = ago(row.get("last_seen"))
        row["last_seen_local"] = local_ts(row.get("last_seen"))
        return row

    def counts(self) -> dict[str, int]:
        """Return aggregate device counters for dashboards and navigation."""
        cutoff = self._down_cutoff()
        row = self.db.q1(
            """
            SELECT COUNT(*) AS total,
              SUM(CASE WHEN present=1 AND archived=0 THEN 1 ELSE 0 END) AS online,
              SUM(CASE WHEN present=0 AND archived=0 AND down_notified=0
                        AND NOT (can_sleep=1 AND last_seen>=?) THEN 1 ELSE 0 END) AS offline,
              SUM(CASE WHEN present=0 AND archived=0 AND down_notified=1 THEN 1 ELSE 0 END) AS down,
              SUM(CASE WHEN present=0 AND archived=0 AND can_sleep=1 AND last_seen>=? THEN 1 ELSE 0 END) AS sleeping,
              SUM(CASE WHEN is_new=1 AND archived=0 THEN 1 ELSE 0 END) AS new,
              SUM(CASE WHEN archived=1 THEN 1 ELSE 0 END) AS archived,
              SUM(CASE WHEN favorite=1 AND archived=0 THEN 1 ELSE 0 END) AS favorites
            FROM devices
            """,
            (cutoff, cutoff),
        ) or {}
        return {key: int(value or 0) for key, value in row.items()}

    # ------------------------------------------------------------------ devices
    def list_devices(
        self,
        search: str = "",
        status: str = "active",
        limit: int = 2000,
    ) -> list[dict]:
        """Return devices filtered by free text and a status bucket."""
        clauses: list[str] = []
        params: list[Any] = []
        cutoff = self._down_cutoff()
        if status == "active":
            clauses.append("archived=0")
        elif status == "online":
            clauses.append("present=1 AND archived=0")
        elif status == "offline":
            clauses.append(
                "present=0 AND archived=0 AND down_notified=0 "
                "AND NOT (can_sleep=1 AND last_seen>=?)"
            )
            params.append(cutoff)
        elif status == "down":
            clauses.append("present=0 AND archived=0 AND down_notified=1")
        elif status == "sleeping":
            clauses.append("present=0 AND archived=0 AND can_sleep=1 AND last_seen>=?")
            params.append(cutoff)
        elif status == "archived":
            clauses.append("archived=1")
        elif status == "new":
            clauses.append("is_new=1 AND archived=0")
        elif status == "favorites":
            clauses.append("favorite=1 AND archived=0")
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append(
                "(name LIKE ? OR ip LIKE ? OR mac LIKE ? OR vendor LIKE ? "
                "OR owner LIKE ? OR type LIKE ? OR group_name LIKE ? OR location LIKE ?)"
            )
            params.extend([needle] * 8)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.q(
            f"SELECT * FROM devices {where} "
            "ORDER BY present DESC, name COLLATE NOCASE ASC LIMIT ?",
            (*params, limit),
        )
        return [self.decorate(row) for row in rows]

    def get_device(self, mac: str) -> dict | None:
        """Return one decorated device by MAC (or synthetic key)."""
        row = self.db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
        return self.decorate(row) if row else None

    def find_device(self, query: str) -> dict | None:
        """Find a device by exact MAC, IP or case-insensitive name."""
        query = (query or "").strip()
        if not query:
            return None
        row = self.db.q1("SELECT * FROM devices WHERE mac=?", (query,))
        if row is None:
            row = self.db.q1("SELECT * FROM devices WHERE ip=? LIMIT 1", (query,))
        if row is None:
            row = self.db.q1(
                "SELECT * FROM devices WHERE name=? COLLATE NOCASE LIMIT 1", (query,)
            )
        return self.decorate(row) if row else None

    def _record_history(self, mac: str, field: str, old: Any, new: Any, by: str) -> None:
        """Log one field change to the audit history."""
        if str(old) == str(new):
            return
        self.db.x(
            "INSERT INTO device_history(mac, field, old_value, new_value, changed_by, changed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mac, field, str(old or ""), str(new or ""), by, now_str()),
        )

    def update_device(self, mac: str, changes: dict[str, Any], changed_by: str = "USER") -> dict:
        """Update whitelisted device fields and return the fresh row."""
        current = self.db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
        if current is None:
            raise KeyError(f"device not found: {mac}")
        clean: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in EDITABLE_FIELDS:
                continue
            if key in BOOL_FIELDS:
                value = _as_bool(value)
            clean[key] = value
        if "name" in clean and clean["name"] != current.get("name"):
            clean["name_source"] = "user"
        if clean.get("archived") == 1:
            clean["is_new"] = 0
        if not clean:
            return self.decorate(current)
        assignments = ", ".join(f"{key}=?" for key in clean)
        self.db.x(
            f"UPDATE devices SET {assignments} WHERE mac=?",
            (*clean.values(), mac),
        )
        for key, value in clean.items():
            self._record_history(mac, key, current.get(key), value, changed_by)
        self.log("INFO", f"device updated: {current.get('name') or mac} ({', '.join(clean)})")
        self.emit("devices_changed", mac=mac)
        updated = self.db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
        return self.decorate(updated or current)

    def toggle_favorite(self, mac: str) -> dict:
        """Toggle the favorite flag for a device."""
        row = self.db.q1("SELECT favorite FROM devices WHERE mac=?", (mac,))
        if row is None:
            raise KeyError(mac)
        return self.update_device(mac, {"favorite": 0 if row["favorite"] else 1})

    def toggle_archive(self, mac: str) -> dict:
        """Toggle the archived flag for a device."""
        row = self.db.q1("SELECT archived FROM devices WHERE mac=?", (mac,))
        if row is None:
            raise KeyError(mac)
        return self.update_device(mac, {"archived": 0 if row["archived"] else 1})

    def acknowledge(self, mac: str) -> None:
        """Clear the 'new device' badge."""
        self.db.x("UPDATE devices SET is_new=0 WHERE mac=? AND is_new=1", (mac,))

    def create_device(self, name: str, ip: str = "", mac: str = "", **fields: Any) -> str:
        """Create a manual device and return its identity key."""
        mac = normalize_mac(mac)
        if not mac:
            if is_ip(ip):
                mac = f"ip:{ip}"
            else:
                mac = f"manual:{uuid.uuid4().hex[:12]}"
        if self.db.q1("SELECT mac FROM devices WHERE mac=?", (mac,)):
            raise ValueError("a device with this MAC/IP already exists")
        stamp = now_str()
        vendor = fields.get("vendor", "")
        dtype = fields.get("type", "") or self.scanner.guess_type(vendor, name)
        self.db.x(
            "INSERT INTO devices(mac, guid, name, name_source, owner, type, vendor, group_name, "
            "location, site, ip, first_seen, last_seen, present, is_new, source, alert_down) "
            "VALUES (?, ?, ?, 'user', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'manual', 1)",
            (
                mac,
                str(uuid.uuid4()),
                name.strip() or f"device-{ip or mac[-5:]}",
                fields.get("owner", ""),
                dtype,
                vendor,
                fields.get("group_name", ""),
                fields.get("location", ""),
                fields.get("site", ""),
                ip.strip(),
                stamp,
                stamp,
            ),
        )
        self.add_event(mac, ip, "Device Added", f"Created manually: {name}")
        self.log("INFO", f"manual device created: {name} ({ip or mac})")
        self.emit("devices_changed", mac=mac)
        return mac

    def delete_device(self, mac: str) -> None:
        """Delete a device plus its presence and session data."""
        row = self.db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
        if row is None:
            raise KeyError(mac)
        for table in ("devices", "presence", "sessions"):
            self.db.x(f"DELETE FROM {table} WHERE mac=?", (mac,))
        self.add_event(mac, row.get("ip", ""), "Device Deleted", row.get("name", ""))
        self.log("WARN", f"device deleted: {row.get('name') or mac} ({mac})")
        self.emit("devices_changed", mac=mac)

    def history(self, mac: str, limit: int = 100) -> list[dict]:
        """Return the change audit trail for a device."""
        return self.db.q(
            "SELECT * FROM device_history WHERE mac=? ORDER BY id DESC LIMIT ?",
            (mac, limit),
        )

    # ------------------------------------------------------------------- events
    def add_event(self, mac: str, ip: str, event_type: str, info: str = "") -> int:
        """Append one event row."""
        event_id = self.db.x(
            "INSERT INTO events(mac, ip, type, info, created_at) VALUES (?, ?, ?, ?, ?)",
            (mac, ip or "", event_type, info, now_str()),
        )
        self.emit("event", event_type=event_type, mac=mac)
        return event_id

    def list_events(
        self,
        search: str = "",
        event_type: str = "all",
        limit: int = 500,
    ) -> list[dict]:
        """Return events newest first with an optional type filter."""
        clauses: list[str] = []
        params: list[Any] = []
        if event_type and event_type != "all":
            clauses.append("e.type=?")
            params.append(event_type)
        if search.strip():
            needle = f"%{search.strip()}%"
            clauses.append(
                "(e.mac LIKE ? OR e.ip LIKE ? OR e.type LIKE ? OR e.info LIKE ? "
                "OR d.name LIKE ?)"
            )
            params.extend([needle] * 5)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self.db.q(
            f"SELECT e.*, d.name AS device_name FROM events e "
            f"LEFT JOIN devices d ON d.mac=e.mac {where} "
            f"ORDER BY e.id DESC LIMIT ?",
            (*params, limit),
        )

    def events_for(self, mac: str, limit: int = 100) -> list[dict]:
        """Return events belonging to one device."""
        return self.db.q(
            "SELECT * FROM events WHERE mac=? ORDER BY id DESC LIMIT ?", (mac, limit)
        )

    def event_types(self) -> list[str]:
        """Return all distinct event types."""
        return [row["type"] for row in self.db.q("SELECT DISTINCT type FROM events ORDER BY type")]

    def clear_events(self, older_than_days: int | None = None) -> int:
        """Delete events older than N days, or all when N is None."""
        if older_than_days is None:
            count = int(self.db.scalar("SELECT COUNT(*) FROM events", default=0) or 0)
            self.db.x("DELETE FROM events")
        else:
            cutoff = (utcnow() - timedelta(days=older_than_days)).strftime("%Y-%m-%d %H:%M:%S")
            count = int(
                self.db.scalar("SELECT COUNT(*) FROM events WHERE created_at<?", (cutoff,), 0) or 0
            )
            self.db.x("DELETE FROM events WHERE created_at<?", (cutoff,))
        self.log("INFO", f"events cleared ({count})")
        return count

    def delete_event(self, event_id: int) -> None:
        """Delete a single event."""
        self.db.x("DELETE FROM events WHERE id=?", (event_id,))

    # -------------------------------------------------------------------- scans
    def scan(self, trigger: str = "manual") -> dict:
        """Run one full discovery + ingestion cycle (thread-safe, never overlapping)."""
        if not self.scan_lock.acquire(blocking=False):
            self.log("WARN", "scan skipped: another scan is already running")
            return {"status": "busy", "found": 0, "new": 0, "online": 0}
        started_monotonic = time.monotonic()
        self._scanning = True
        self.emit("scan_start", trigger=trigger)
        run_id = self.db.x(
            "INSERT INTO scan_runs(started_at, trigger, status) VALUES (?, ?, 'running')",
            (now_str(), trigger),
        )
        summary: dict[str, Any] = {
            "status": "ok",
            "found": 0,
            "new": 0,
            "online": 0,
            "method": self.scanner.effective_method(),
            "targets": [],
            "errors": [],
        }
        try:
            targets = self.scanner.plan_targets()
            summary["targets"] = targets
            if not targets:
                raise RuntimeError(
                    "no scan target: set scan_subnets or connect to a network"
                )
            self.log("INFO", f"scan started ({trigger}) · {', '.join(targets)}")
            hosts: list[Host] = []
            by_key: dict[str, Host] = {}
            for target in targets:
                result = self.scanner.discover(target, progress=lambda msg: self.log("DEBUG", msg))
                if result.error:
                    summary["errors"].append(result.error)
                    self.log("WARN", f"discovery note for {target}: {result.error}")
                for host in result.hosts:
                    key = host.key()
                    if key in by_key:
                        if not by_key[key].mac and host.mac:
                            by_key[key] = host
                    else:
                        by_key[key] = host
            hosts = list(by_key.values())
            self.scanner.resolve_hostnames(hosts, progress=lambda msg: self.log("DEBUG", msg))

            ingest = self._ingest(hosts)
            self._evaluate_down()
            self._run_workflows("scan")
            self._record_presence()
            self._cleanup()

            summary.update(
                found=len(hosts),
                new=ingest["new"],
                online=ingest["online"],
                duration=round(time.monotonic() - started_monotonic, 1),
            )
            self.db.x(
                "UPDATE scan_runs SET finished_at=?, found=?, new_devices=?, online=?, "
                "status='ok', message=? WHERE id=?",
                (
                    now_str(),
                    len(hosts),
                    ingest["new"],
                    ingest["online"],
                    f"{summary['method']} · {', '.join(targets)}",
                    run_id,
                ),
            )
            self.log(
                "INFO",
                f"scan complete · {len(hosts)} host(s) · {ingest['new']} new · "
                f"{summary['duration']}s",
            )
            self.emit("scan_done", summary=summary)
        except Exception as exc:
            summary["status"] = "error"
            summary["errors"].append(str(exc))
            self.db.x(
                "UPDATE scan_runs SET finished_at=?, status='error', message=? WHERE id=?",
                (now_str(), str(exc)[:300], run_id),
            )
            self.log("ERROR", f"scan failed: {exc}")
            self.emit("scan_error", message=str(exc))
        finally:
            self._scanning = False
            self.scan_lock.release()
        return summary

    def _identity_for(self, host: Host) -> str:
        """Resolve a host to a stable device key, reusing an IP match when possible."""
        if host.mac:
            return host.mac
        existing = self.db.q1("SELECT mac FROM devices WHERE ip=? LIMIT 1", (host.ip,))
        return existing["mac"] if existing else f"ip:{host.ip}"

    def _auto_name(self, host: Host) -> str:
        """Build a friendly default name for a discovered host."""
        if host.hostname:
            return host.hostname[:80]
        if host.vendor:
            return f"{host.vendor} {host.ip.rsplit('.', 1)[-1]}"
        if self._gateway is None:
            network = default_network() or {}
            self._gateway = default_gateway(str(network.get("iface") or ""))
        if host.ip == self._gateway:
            return "Gateway"
        return f"Host {host.ip}"

    def _ingest(self, hosts: list[Host]) -> dict[str, int]:
        """Insert or refresh every observed host, then mark missing ones offline."""
        stamp = now_str()
        seen: set[str] = set()
        new_count = 0
        for host in hosts:
            key = self._identity_for(host)
            seen.add(key)
            existing = self.db.q1("SELECT * FROM devices WHERE mac=?", (key,))
            vendor = host.vendor or self.scanner.lookup_vendor(host.mac)
            if existing is None:
                dtype = self.scanner.guess_type(vendor, host.hostname)
                self.db.x(
                    "INSERT INTO devices(mac, guid, name, name_source, type, vendor, ip, "
                    "first_seen, last_seen, present, is_new, source, alert_down) "
                    "VALUES (?, ?, ?, 'auto', ?, ?, ?, ?, ?, 1, 1, ?, 1)",
                    (
                        key,
                        str(uuid.uuid4()),
                        self._auto_name(host),
                        dtype,
                        vendor,
                        host.ip,
                        stamp,
                        stamp,
                        host.source,
                    ),
                )
                self.add_event(
                    key,
                    host.ip,
                    "New Device",
                    f"{host.hostname or 'unknown host'} · {vendor or 'unknown vendor'}",
                )
                if self.settings.get_bool("notify_new"):
                    self.notifier.push(
                        "alert",
                        f"New device: {self._auto_name(host)} ({host.ip})",
                    )
                self._run_workflows("new_device", mac=key)
                new_count += 1
            else:
                updates: dict[str, Any] = {
                    "ip": host.ip,
                    "last_seen": stamp,
                    "present": 1,
                    "down_notified": 0,
                }
                if vendor and not existing.get("vendor"):
                    updates["vendor"] = vendor
                if host.hostname and existing.get("name_source") == "auto":
                    if existing.get("name") != host.hostname:
                        updates["name"] = host.hostname[:80]
                if not existing.get("type"):
                    guessed = self.scanner.guess_type(vendor, host.hostname)
                    if guessed:
                        updates["type"] = guessed
                was_present = int(existing.get("present") or 0)
                was_down = int(existing.get("down_notified") or 0)
                assignments = ", ".join(f"{k}=?" for k in updates)
                self.db.x(
                    f"UPDATE devices SET {assignments} WHERE mac=?",
                    (*updates.values(), key),
                )
                if not was_present:
                    self.add_event(key, host.ip, "Connected", "Device is back online")
                    if was_down and self.settings.get_bool("notify_online"):
                        self.notifier.push(
                            "success", f"Back online: {existing.get('name') or key} ({host.ip})"
                        )
                    self._open_session(key, host.ip)
                    self.emit("device_online", mac=key)
            self._run_workflows("online", mac=key)

        # Anything previously online but not observed this cycle is now offline.
        for row in self.db.q("SELECT * FROM devices WHERE present=1"):
            if row["mac"] in seen:
                continue
            self.db.x("UPDATE devices SET present=0 WHERE mac=?", (row["mac"],))
            self._close_session(row["mac"])
            self.add_event(row["mac"], row.get("ip", ""), "Disconnected", "No longer visible")
            self.emit("device_offline", mac=row["mac"])

        online = int(self.db.scalar("SELECT COUNT(*) FROM devices WHERE present=1", default=0) or 0)
        return {"new": new_count, "online": online}

    def _evaluate_down(self) -> None:
        """Promote long-missing devices to Down and raise alerts."""
        cutoff = self._down_cutoff()
        rows = self.db.q(
            "SELECT * FROM devices WHERE present=0 AND archived=0 AND down_notified=0 "
            "AND last_seen IS NOT NULL AND last_seen<? AND scan_enabled=1",
            (cutoff,),
        )
        for row in rows:
            self.db.x("UPDATE devices SET down_notified=1 WHERE mac=?", (row["mac"],))
            if int(row.get("can_sleep") or 0):
                self.add_event(row["mac"], row.get("ip", ""), "Sleeping", "Device likely asleep")
                continue
            self.add_event(
                row["mac"],
                row.get("ip", ""),
                "Device Down",
                f"No response for over {self.settings.get_int('down_after_minutes')} min",
            )
            if self.settings.get_bool("notify_down") and int(row.get("alert_down") or 0):
                self.notifier.push(
                    "warn", f"Device down: {row.get('name') or row['mac']} ({row.get('ip') or '—'})"
                )

    def _record_presence(self) -> None:
        """Accumulate hourly online/offline samples for every active device."""
        bucket = utcnow().strftime("%Y-%m-%d %H")
        rows = self.db.q("SELECT mac, present FROM devices WHERE archived=0")
        payload = [
            (row["mac"], bucket, 1, 1 if row["present"] else 0) for row in rows
        ]
        self.db.xmany(
            "INSERT INTO presence(mac, bucket, samples, online) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(mac, bucket) DO UPDATE SET samples=samples+1, online=online+excluded.online",
            payload,
        )

    def _open_session(self, mac: str, ip: str) -> None:
        """Close dangling sessions and start a new one."""
        stamp = now_str()
        self.db.x(
            "UPDATE sessions SET disconnected_at=? WHERE mac=? AND disconnected_at IS NULL",
            (stamp, mac),
        )
        self.db.x(
            "INSERT INTO sessions(mac, ip, connected_at) VALUES (?, ?, ?)",
            (mac, ip, stamp),
        )

    def _close_session(self, mac: str) -> None:
        """Close the open session for a device."""
        self.db.x(
            "UPDATE sessions SET disconnected_at=? WHERE mac=? AND disconnected_at IS NULL",
            (now_str(), mac),
        )

    def _cleanup(self) -> None:
        """Apply retention windows and caps."""
        days = self.settings.get_int("retention_days")
        cutoff = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        self.db.x("DELETE FROM events WHERE created_at<?", (cutoff,))
        presence_cutoff = (utcnow() - timedelta(days=max(days, 30))).strftime("%Y-%m-%d %H")
        self.db.x("DELETE FROM presence WHERE bucket<?", (presence_cutoff,))
        max_events = self.settings.get_int("max_events")
        self.db.x(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (max_events,),
        )
        self.db.x(
            "DELETE FROM device_history WHERE id NOT IN "
            "(SELECT id FROM device_history ORDER BY id DESC LIMIT 10000)"
        )
        self.db.x(
            "DELETE FROM notifications WHERE id NOT IN "
            "(SELECT id FROM notifications ORDER BY id DESC LIMIT 1000)"
        )

    def last_scan(self) -> dict | None:
        """Return the most recent finished scan."""
        return self.db.q1(
            "SELECT * FROM scan_runs WHERE status IN ('ok','error') ORDER BY started_at DESC, id DESC LIMIT 1"
        )

    def recent_scans(self, limit: int = 12) -> list[dict]:
        """Return recent scan runs newest first."""
        return self.db.q(
            "SELECT * FROM scan_runs ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        )

    # --------------------------------------------------------------- presence
    def presence_for(self, mac: str, hours: int = 24) -> list[dict]:
        """Return hourly presence rows for one device."""
        since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H")
        return self.db.q(
            "SELECT * FROM presence WHERE mac=? AND bucket>=? ORDER BY bucket",
            (mac, since),
        )

    def presence_series(self, hours: int = 24) -> list[dict]:
        """Return hourly online device ratios for the network."""
        since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H")
        return self.db.q(
            "SELECT bucket, "
            "SUM(CASE WHEN online>0 THEN 1 ELSE 0 END) AS devices, "
            "COUNT(*) AS tracked "
            "FROM presence WHERE bucket>=? GROUP BY bucket ORDER BY bucket",
            (since,),
        )

    def presence_summary(self, hours: int = 24, limit: int = 200) -> list[dict]:
        """Return uptime aggregates per device for the presence screen."""
        since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H")
        return self.db.q(
            "SELECT p.mac, d.name, d.ip, d.present, d.archived, "
            "SUM(p.online) AS online, SUM(p.samples) AS samples "
            "FROM presence p JOIN devices d ON d.mac=p.mac "
            "WHERE p.bucket>=? AND d.archived=0 "
            "GROUP BY p.mac ORDER BY (CAST(SUM(p.online) AS REAL)/MAX(SUM(p.samples),1)) DESC "
            "LIMIT ?",
            (since, limit),
        )

    def presence_grid(self, hours: int = 24, limit: int = 40) -> tuple[list[dict], list[str]]:
        """Return per-device hourly cell data for heat rows."""
        since = (utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H")
        rows = self.db.q(
            "SELECT p.mac, p.bucket, p.online, p.samples, d.name, d.ip "
            "FROM presence p JOIN devices d ON d.mac=p.mac "
            "WHERE p.bucket>=? AND d.archived=0 ORDER BY p.bucket",
            (since,),
        )
        buckets = sorted({row["bucket"] for row in rows})
        grid: dict[str, dict] = {}
        for row in rows:
            entry = grid.setdefault(
                row["mac"],
                {"mac": row["mac"], "name": row["name"], "ip": row["ip"], "cells": {}},
            )
            entry["cells"][row["bucket"]] = (
                1.0 if row["samples"] and row["online"] >= row["samples"] else 0.5 if row["online"] else 0.0
            )
        ordered = sorted(
            grid.values(),
            key=lambda item: -sum(item["cells"].values()),
        )[:limit]
        for entry in ordered:
            entry["series"] = [entry["cells"].get(bucket, -1) for bucket in buckets]
        return ordered, buckets

    def sessions_for(self, mac: str, limit: int = 100) -> list[dict]:
        """Return sessions for a device."""
        rows = self.db.q(
            "SELECT * FROM sessions WHERE mac=? ORDER BY id DESC LIMIT ?", (mac, limit)
        )
        for row in rows:
            start = parse_ts(row.get("connected_at"))
            end = parse_ts(row.get("disconnected_at")) or utcnow()
            row["duration"] = human_duration((end - start).total_seconds()) if start else "—"
            row["start"] = local_ts(row.get("connected_at"))
            row["end"] = local_ts(row.get("disconnected_at")) if row.get("disconnected_at") else "active"
        return rows

    # ---------------------------------------------------------------- workflows
    def workflows(self) -> list[dict]:
        """Return all automation rules."""
        return self.db.q("SELECT * FROM workflows ORDER BY id")

    def add_workflow(
        self,
        name: str,
        trigger: str,
        field: str,
        operator: str,
        value: str,
        action_field: str,
        action_value: str,
    ) -> int:
        """Create an automation rule."""
        if action_field not in WORKFLOW_ACTIONS:
            raise ValueError(f"unsupported action field: {action_field}")
        workflow_id = self.db.x(
            "INSERT INTO workflows(name, enabled, trigger, field, operator, value, "
            "action_field, action_value, created_at) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)",
            (
                name or "Untitled automation",
                trigger,
                field,
                operator,
                value,
                action_field,
                action_value,
                now_str(),
            ),
        )
        self.log("INFO", f"automation created: {name}")
        self.emit("workflows_changed")
        return workflow_id

    def delete_workflow(self, workflow_id: int) -> None:
        """Delete an automation rule."""
        self.db.x("DELETE FROM workflows WHERE id=?", (workflow_id,))
        self.emit("workflows_changed")

    def toggle_workflow(self, workflow_id: int) -> None:
        """Enable or disable an automation rule."""
        self.db.x(
            "UPDATE workflows SET enabled = 1-enabled WHERE id=?", (workflow_id,)
        )
        self.emit("workflows_changed")

    def _condition_matches(self, row: dict, field: str, operator: str, value: str) -> bool:
        """Evaluate one workflow condition against a device row."""
        actual = str(row.get(field, "") or "")
        expected = str(value or "")
        if operator == "equals":
            return actual.lower() == expected.lower()
        if operator == "not_equals":
            return actual.lower() != expected.lower()
        if operator == "contains":
            return expected.lower() in actual.lower()
        if operator == "starts_with":
            return actual.lower().startswith(expected.lower())
        if operator == "ends_with":
            return actual.lower().endswith(expected.lower())
        if operator == "is_empty":
            return not actual.strip()
        if operator == "not_empty":
            return bool(actual.strip())
        if operator == "regex":
            try:
                return re.search(expected, actual, re.IGNORECASE) is not None
            except re.error:
                return False
        return False

    def _run_workflows(self, trigger: str, mac: str | None = None) -> None:
        """Apply enabled automation rules to one device or the whole inventory."""
        rules = self.db.q(
            "SELECT * FROM workflows WHERE enabled=1 AND trigger=? ORDER BY id", (trigger,)
        )
        if not rules:
            return
        if mac:
            rows = self.db.q("SELECT * FROM devices WHERE mac=?", (mac,))
        elif trigger == "online":
            rows = self.db.q("SELECT * FROM devices WHERE present=1 AND archived=0")
        else:
            rows = self.db.q("SELECT * FROM devices WHERE archived=0")
        for row in rows:
            for rule in rules:
                if not rule["field"] or rule["field"] not in row:
                    continue
                if not self._condition_matches(row, rule["field"], rule["operator"], rule["value"]):
                    continue
                target = rule["action_field"]
                if target not in WORKFLOW_ACTIONS:
                    continue
                new_value: Any = rule["action_value"]
                if target in BOOL_FIELDS:
                    new_value = _as_bool(new_value)
                if str(row.get(target, "")) == str(new_value):
                    continue
                try:
                    self.db.x(
                        f"UPDATE devices SET {target}=? WHERE mac=?", (new_value, row["mac"])
                    )
                    if target == "name":
                        self.db.x(
                            "UPDATE devices SET name_source='workflow' WHERE mac=?", (row["mac"],)
                        )
                    self._record_history(
                        row["mac"], target, row.get(target), new_value, "WORKFLOW"
                    )
                    self.log(
                        "INFO",
                        f"automation '{rule['name']}' set {target}={new_value} on "
                        f"{row.get('name') or row['mac']}",
                    )
                except Exception as exc:
                    self.log("WARN", f"automation failed: {exc}")

    # ----------------------------------------------------------------- settings
    def set_setting(self, key: str, value: Any) -> None:
        """Persist a setting and notify the UI."""
        self.settings.set(key, value)
        self.log("INFO", f"setting updated: {key}")
        self.emit("settings_changed", key=key)

    # -------------------------------------------------------------------- tools
    def wake_on_lan(self, mac: str) -> str:
        """Send a Wake-on-LAN magic packet."""
        normalized = normalize_mac(mac)
        if not is_mac(normalized):
            raise ValueError("device has no valid MAC address")
        payload = b"\xff" * 6 + bytes.fromhex(normalized.replace(":", "")) * 16
        sent = 0
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            for port in (9, 7):
                try:
                    sock.sendto(payload, ("255.255.255.255", port))
                    sent += 1
                except OSError:
                    continue
        finally:
            sock.close()
        if not sent:
            raise RuntimeError("could not send magic packet")
        self.add_event("", "", "Wake-on-LAN", normalized)
        self.log("INFO", f"Wake-on-LAN sent to {normalized}")
        return f"Magic packet sent to {normalized}"

    def run_tool(self, tool: str, target: str, mode: str = "fast") -> str:
        """Run nmap, traceroute, ping or nslookup and return the output text."""
        target = (target or "").strip()
        if not target:
            raise ValueError("target is required")
        # A leading dash would be read as a command-line option by the tool.
        if target.startswith("-"):
            raise ValueError("target must not start with '-'")
        if tool in {"nmap", "ping", "traceroute"} and not is_ip(target) and "/" not in target:
            raise ValueError("target must be an IP address or CIDR")
        if tool == "nmap":
            flags = {"fast": ["-F"], "normal": [], "detail": ["-A"], "skipdiscovery": ["-Pn"]}
            if mode not in flags:
                raise ValueError("unknown nmap mode")
            cmd = ["nmap", *flags[mode], "-T4", target]
        elif tool == "traceroute":
            cmd = ["traceroute", "-m", "20", "-w", "2", target]
        elif tool == "nslookup":
            cmd = ["nslookup", target]
        elif tool == "ping":
            cmd = ["ping", "-c", "4", "-W", "2", target] if not target.startswith("-") else []
        else:
            raise ValueError(f"unknown tool: {tool}")
        rc, out, err = run_command(cmd, timeout=120)
        text = (out or err or "").strip()
        if rc != 0 and not text:
            text = f"command failed with exit code {rc}"
        self.add_event("", "", f"Tool: {tool}", f"{target} · {mode}")
        self.log("INFO", f"tool {tool} · {target} · exit {rc}")
        return text[:30000]

    # --------------------------------------------------------------- data files
    def export_csv(self, destination: str | Path | None = None) -> Path:
        """Export all devices to CSV and return the file path."""
        path = Path(destination) if destination else export_dir() / f"devices_{utcnow():%Y%m%d_%H%M%S}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.list_devices(status="all", limit=100000)
        fields = [
            "mac", "name", "ip", "vendor", "type", "owner", "group_name", "location",
            "site", "ssid", "vlan", "favorite", "archived", "present", "first_seen",
            "last_seen", "comments", "parent_mac", "parent_port", "status",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        self.log("INFO", f"devices exported to {path}")
        return path

    def import_csv(self, source: str | Path) -> tuple[int, int]:
        """Import devices from a CSV file, returning (created, updated)."""
        path = Path(source).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))
        aliases = {
            "mac": ("mac", "devmac"),
            "name": ("name", "devname"),
            "ip": ("ip", "devlastip", "devip"),
            "vendor": ("vendor", "devvendor"),
            "type": ("type", "devtype"),
            "owner": ("owner", "devowner"),
            "group_name": ("group_name", "group", "devgroup"),
            "location": ("location", "devlocation"),
            "site": ("site", "devsite"),
            "comments": ("comments", "devcomments"),
            "favorite": ("favorite", "devfavorite"),
            "archived": ("archived", "devisarchived"),
        }
        created = updated = 0
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                normalized = {str(k).strip().lower(): (v or "").strip() for k, v in raw.items()}
                values: dict[str, str] = {}
                for target, names in aliases.items():
                    for name in names:
                        if name in normalized and normalized[name]:
                            values[target] = normalized[name]
                            break
                mac = normalize_mac(values.get("mac", ""))
                if not mac:
                    continue
                existing = self.db.q1("SELECT * FROM devices WHERE mac=?", (mac,))
                if existing:
                    changes = {
                        key: value
                        for key, value in values.items()
                        if key != "mac" and str(existing.get(key) or "") != value
                    }
                    if changes:
                        self.update_device(mac, changes, changed_by="IMPORT")
                        updated += 1
                else:
                    self.create_device(
                        values.get("name") or f"imported-{mac[-5:]}",
                        ip=values.get("ip", ""),
                        mac=mac,
                        vendor=values.get("vendor", ""),
                        type=values.get("type", ""),
                        owner=values.get("owner", ""),
                        group_name=values.get("group_name", ""),
                        location=values.get("location", ""),
                        site=values.get("site", ""),
                    )
                    created += 1
        self.log("INFO", f"CSV import complete: {created} created, {updated} updated")
        self.emit("devices_changed")
        return created, updated

    # ---------------------------------------------------------------- scheduler
    def start_scheduler(self) -> None:
        """Start the background scheduled-scan thread."""
        if self._scheduler and self._scheduler.is_alive():
            return
        self._scheduler = ScanScheduler(self)
        self._scheduler.start()

    def stop_scheduler(self) -> None:
        """Stop the scheduler thread."""
        if self._scheduler:
            self._scheduler.stop()
            self._scheduler = None

    # ------------------------------------------------------------------- stats
    def dashboard_data(self) -> dict[str, Any]:
        """Collect everything the dashboard needs in one place."""
        series = self.presence_series(24)
        scans = self.recent_scans(5)
        net = self.scanner.plan_targets()
        return {
            "counts": self.counts(),
            "series": series,
            "events": self.list_events(limit=8),
            "scans": scans,
            "last_scan": self.last_scan(),
            "targets": net,
            "method": self.scanner.effective_method(),
            "db_size": Path(self.db.path).stat().st_size if Path(self.db.path).exists() else 0,
            "uptime": human_duration(
                (utcnow() - (parse_ts(self.started_at) or utcnow())).total_seconds()
            ),
            "unread": self.notifier.unread_count(),
            "networks": self.scanner.capabilities(),
        }


class ScanScheduler(threading.Thread):
    """Background loop that triggers scans at the configured interval."""

    def __init__(self, engine: Engine) -> None:
        super().__init__(daemon=True, name="netalertz-scheduler")
        self.engine = engine
        self._stop = threading.Event()
        self.next_scan = time.monotonic() + 4

    def run(self) -> None:
        """Wait, check settings, and scan on schedule."""
        while not self._stop.wait(1.0):
            try:
                if not self.engine.settings.get_bool("scheduled_scans"):
                    self.next_scan = time.monotonic() + 4
                    continue
                if time.monotonic() < self.next_scan:
                    continue
                if self.engine.scan_lock.locked():
                    self.next_scan = time.monotonic() + 10
                    continue
                self.engine.scan(trigger="schedule")
                interval = max(15, self.engine.settings.get_int("scan_interval"))
                self.next_scan = time.monotonic() + interval
            except Exception as exc:  # pragma: no cover - defensive
                self.engine.log("ERROR", f"scheduler error: {exc}")
                self.next_scan = time.monotonic() + 30

    def stop(self) -> None:
        """Ask the loop to exit."""
        self._stop.set()
