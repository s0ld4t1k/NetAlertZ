"""Realistic demo dataset so the TUI can be explored without a live network."""

from __future__ import annotations

import random
import uuid
from datetime import timedelta

from .engine import Engine
from .utils import now_str, utcnow

NOW = utcnow()


def _ago(**kwargs) -> str:
    """Return a UTC timestamp offset into the past."""
    return (NOW - timedelta(**kwargs)).strftime("%Y-%m-%d %H:%M:%S")


DEVICES = [
    dict(mac="aa:bb:cc:00:00:00", name="Fiber Gateway", vendor="Huawei", type="Router", ip="192.168.31.1",
         owner="Infrastructure", group_name="Core", location="Hallway", favorite=1,
         first=_ago(days=210), parent="", port="", rel="", present=1),
    dict(mac="aa:bb:cc:00:00:01", name="Core Switch", vendor="Ubiquiti", type="Switch", ip="192.168.31.2",
         owner="Infrastructure", group_name="Core", location="Rack", favorite=1,
         first=_ago(days=210), parent="aa:bb:cc:00:00:00", port="eth0", rel="wired", present=1),
    dict(mac="aa:bb:cc:00:00:02", name="Office AP", vendor="Ubiquiti", type="Access Point", ip="192.168.31.3",
         owner="Infrastructure", group_name="Network", location="Office",
         first=_ago(days=190), parent="aa:bb:cc:00:00:01", port="eth4", rel="wired", present=1),
    dict(mac="aa:bb:cc:00:00:03", name="Living Room AP", vendor="Ubiquiti", type="Access Point", ip="192.168.31.4",
         owner="Infrastructure", group_name="Network", location="Living Room",
         first=_ago(days=190), parent="aa:bb:cc:00:00:01", port="eth5", rel="wired", present=1),
    dict(mac="30:24:32:11:22:01", name="homelab-node", vendor="Raspberry Pi", type="Server", ip="192.168.31.10",
         owner="Alex", group_name="Homelab", location="Rack", favorite=1, ssid="",
         first=_ago(days=180), parent="aa:bb:cc:00:00:01", port="eth1", rel="wired", present=1),
    dict(mac="d8:3a:dd:44:55:02", name="pi-hole", vendor="Raspberry Pi", type="Server", ip="192.168.31.11",
         owner="Alex", group_name="Homelab", location="Rack",
         first=_ago(days=170), parent="aa:bb:cc:00:00:01", port="eth2", rel="wired", present=1),
    dict(mac="b8:27:eb:77:88:03", name="sensor-garage", vendor="Raspberry Pi", type="IoT", ip="192.168.31.12",
         owner="Alex", group_name="Sensors", location="Garage", can_sleep=1,
         first=_ago(days=90), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=0),
    dict(mac="3c:22:fb:aa:01:10", name="MacBook Pro 14", vendor="Apple", type="Laptop", ip="192.168.31.21",
         owner="Alex", group_name="Personal", location="Office", favorite=1, ssid="home-5g",
         first=_ago(days=120), parent="aa:bb:cc:00:00:02", port="wifi", rel="wifi", present=1),
    dict(mac="a4:83:e7:aa:02:11", name="iPhone 15", vendor="Apple", type="Phone", ip="192.168.31.22",
         owner="Alex", group_name="Personal", location="Home", ssid="home-5g",
         first=_ago(days=100), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=1),
    dict(mac="9c:fc:01:aa:03:12", name="iPad Air", vendor="Apple", type="Tablet", ip="192.168.31.23",
         owner="Sam", group_name="Personal", ssid="home-5g",
         first=_ago(days=80), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=1),
    dict(mac="f0:18:98:aa:04:13", name="Living Room TV", vendor="Apple", type="TV", ip="192.168.31.24",
         owner="Family", group_name="Media", location="Living Room", ssid="home-5g",
         first=_ago(days=150), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=1),
    dict(mac="7c:04:d0:aa:05:14", name="Switch Console", vendor="Nintendo", type="Game Console", ip="192.168.31.25",
         owner="Family", group_name="Media", ssid="home-5g",
         first=_ago(days=75), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=0),
    dict(mac="38:18:4c:aa:06:15", name="Sony Bravia", vendor="Sony", type="TV", ip="192.168.31.26",
         owner="Family", group_name="Media", location="Bedroom", ssid="home-5g",
         first=_ago(days=140), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=1),
    dict(mac="48:b0:2d:aa:07:16", name="SHIELD", vendor="NVIDIA", type="Media Player", ip="192.168.31.27",
         owner="Family", group_name="Media", ssid="home-5g",
         first=_ago(days=130), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=1),
    dict(mac="84:0d:8e:aa:08:17", name="shelly-plug-01", vendor="Espressif", type="IoT", ip="192.168.31.31",
         owner="Alex", group_name="Sensors", location="Office", ssid="home-iot",
         first=_ago(days=60), parent="aa:bb:cc:00:00:02", port="wifi", rel="wifi", present=1),
    dict(mac="ec:fa:bc:aa:09:18", name="tasmota-lamp", vendor="Espressif", type="IoT", ip="192.168.31.32",
         owner="Alex", group_name="Sensors", location="Living Room", ssid="home-iot",
         first=_ago(days=55), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=1),
    dict(mac="ac:9e:17:aa:10:19", name="Front Door Cam", vendor="Reolink", type="Camera", ip="192.168.31.33",
         owner="Infrastructure", group_name="Security", location="Porch",
         first=_ago(days=160), parent="aa:bb:cc:00:00:01", port="eth7", rel="wired", present=1),
    dict(mac="00:1c:bf:aa:11:20", name="truenas", vendor="Supermicro", type="Server", ip="192.168.31.14",
         owner="Alex", group_name="Homelab", location="Rack", favorite=1,
         first=_ago(days=200), parent="aa:bb:cc:00:00:01", port="eth3", rel="wired", present=1),
    dict(mac="00:1b:63:aa:12:21", name="Sam's MacBook", vendor="Apple", type="Laptop", ip="192.168.31.41",
         owner="Sam", group_name="Personal", ssid="home-5g",
         first=_ago(days=45), parent="aa:bb:cc:00:00:02", port="wifi", rel="wifi", present=0),
    dict(mac="50:c7:bf:aa:13:22", name="garage-plug", vendor="TP-Link", type="Smart Plug", ip="192.168.31.34",
         owner="Alex", group_name="Sensors", location="Garage", ssid="home-iot",
         first=_ago(days=35), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=0),
    dict(mac="00:17:c8:aa:14:23", name="Bedroom TV", vendor="LG", type="TV", ip="192.168.31.28",
         owner="Family", group_name="Media", location="Bedroom", ssid="home-5g",
         first=_ago(days=110), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=0, down=1),
    dict(mac="00:1f:a7:aa:15:24", name="PlayStation 5", vendor="Sony", type="Game Console", ip="192.168.31.29",
         owner="Family", group_name="Media", ssid="home-5g",
         first=_ago(days=65), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=0, down=1),
    dict(mac="00:13:ce:aa:16:25", name="Old Samsung TV", vendor="Samsung", type="TV", ip="192.168.31.30",
         owner="Family", group_name="Archive", location="Storage", archived=1,
         first=_ago(days=400), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=0),
    dict(mac="00:15:5d:aa:17:26", name="build-runner", vendor="Microsoft", type="VM", ip="192.168.31.50",
         owner="Alex", group_name="Homelab", location="Rack",
         first=_ago(days=20), parent="aa:bb:cc:00:00:01", port="vmbr1", rel="virtual", present=1, new=1),
    dict(mac="dc:a6:32:aa:18:27", name="weather-station", vendor="Raspberry Pi", type="IoT", ip="192.168.31.35",
         owner="Alex", group_name="Sensors", location="Roof", ssid="home-iot",
         first=_ago(days=15), parent="aa:bb:cc:00:00:03", port="wifi", rel="wifi", present=0),
]


def seed_demo(engine: Engine, force: bool = False) -> bool:
    """Populate a fresh database with a believable home network."""
    existing = int(engine.db.scalar("SELECT COUNT(*) FROM devices", default=0) or 0)
    if existing and not force:
        return False
    if force:
        for table in (
            "devices", "events", "presence", "sessions", "scan_runs",
            "notifications", "device_history", "workflows",
        ):
            engine.db.x(f"DELETE FROM {table}")

    rng = random.Random(31)
    for item in DEVICES:
        present = int(item.get("present", 0))
        if present:
            last_seen = _ago(minutes=rng.randint(1, 4))
        elif item.get("down"):
            last_seen = _ago(hours=rng.randint(30, 80))
        elif item.get("can_sleep"):
            last_seen = _ago(minutes=rng.randint(20, 40))
        else:
            last_seen = _ago(hours=rng.randint(2, 26))
        engine.db.x(
            "INSERT OR REPLACE INTO devices(mac, guid, name, name_source, owner, type, vendor, "
            "group_name, location, site, ssid, vlan, ip, first_seen, last_seen, present, archived, "
            "favorite, is_new, can_sleep, alert_down, down_notified, comments, parent_mac, "
            "parent_port, parent_rel, source) "
            "VALUES (?, ?, ?, 'user', ?, ?, ?, ?, ?, '', ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo')",
            (
                item["mac"],
                str(uuid.uuid4()),
                item["name"],
                item.get("owner", ""),
                item.get("type", ""),
                item.get("vendor", ""),
                item.get("group_name", ""),
                item.get("location", ""),
                item.get("ssid", ""),
                item.get("ip", ""),
                item["first"],
                last_seen,
                present,
                int(item.get("archived", 0)),
                int(item.get("favorite", 0)),
                int(item.get("new", 0)),
                int(item.get("can_sleep", 0)),
                1,
                1 if item.get("down") else 0,
                item.get("comments", ""),
                item.get("parent", ""),
                item.get("port", ""),
                item.get("rel", ""),
            ),
        )

    _seed_events(engine, rng)
    _seed_presence(engine, rng)
    _seed_sessions(engine)
    _seed_notifications(engine)
    _seed_scans(engine)
    _seed_workflows(engine)
    engine.settings.set("demo_seeded", True)
    engine.log("INFO", f"demo dataset loaded · {len(DEVICES)} devices")
    return True


def _seed_events(engine: Engine, rng: random.Random) -> None:
    """Create a week of believable activity."""
    events: list[tuple] = []
    types = ["Connected", "Disconnected", "Device Down", "Connected", "Connected"]
    for item in DEVICES:
        if item.get("archived"):
            continue
        events.append(
            (item["mac"], item["ip"], "New Device", "First seen on the network",
             _ago(days=rng.randint(8, 40)))
        )
        for index in range(rng.randint(1, 4)):
            event_type = rng.choice(types)
            info = {
                "Connected": "Device came back online",
                "Disconnected": "No longer visible",
                "Device Down": "No response for over 60 min",
            }[event_type]
            events.append(
                (item["mac"], item["ip"], event_type, info,
                 _ago(hours=rng.randint(1, 160), minutes=rng.randint(0, 59)))
            )
    events.append(("", "", "Tool: nmap", "192.168.31.0/24 · fast", _ago(hours=6)))
    events.append(("", "", "Wake-on-LAN", "3c:22:fb:aa:01:10", _ago(hours=11)))
    events.append(("", "", "Settings", "scan_interval changed", _ago(days=2)))
    events.sort(key=lambda row: row[4])
    engine.db.xmany(
        "INSERT INTO events(mac, ip, type, info, created_at) VALUES (?, ?, ?, ?, ?)",
        events,
    )


def _seed_presence(engine: Engine, rng: random.Random) -> None:
    """Build a week of hourly presence samples."""
    rows: list[tuple] = []
    for item in DEVICES:
        if item.get("archived"):
            continue
        base = 0.94 if item.get("present") else 0.55
        if item.get("can_sleep"):
            base = 0.35
        for hour in range(168, -1, -1):
            moment = NOW - timedelta(hours=hour)
            bucket = moment.strftime("%Y-%m-%d %H")
            online = 0
            if rng.random() < base:
                online = 1
            rows.append((item["mac"], bucket, 2, online * 2))
    engine.db.xmany(
        "INSERT OR REPLACE INTO presence(mac, bucket, samples, online) VALUES (?, ?, ?, ?)",
        rows,
    )


def _seed_sessions(engine: Engine) -> None:
    """Create a handful of connection sessions."""
    sessions = [
        ("30:24:32:11:22:01", "192.168.31.10", _ago(days=6), _ago(days=5, hours=4)),
        ("30:24:32:11:22:01", "192.168.31.10", _ago(days=2), None),
        ("3c:22:fb:aa:01:10", "192.168.31.21", _ago(hours=20), _ago(hours=13)),
        ("3c:22:fb:aa:01:10", "192.168.31.21", _ago(hours=3), None),
        ("a4:83:e7:aa:02:11", "192.168.31.22", _ago(days=1, hours=8), _ago(days=1, hours=2)),
        ("a4:83:e7:aa:02:11", "192.168.31.22", _ago(hours=2), None),
        ("ac:9e:17:aa:10:19", "192.168.31.33", _ago(days=4), _ago(days=4, hours=1)),
    ]
    engine.db.xmany(
        "INSERT INTO sessions(mac, ip, connected_at, disconnected_at) VALUES (?, ?, ?, ?)",
        sessions,
    )


def _seed_notifications(engine: Engine) -> None:
    """Create sample in-app notifications."""
    notes = [
        ("alert", "New device: build-runner (192.168.31.50)", _ago(hours=19)),
        ("warn", "Device down: PlayStation 5 (192.168.31.29)", _ago(hours=30)),
        ("warn", "Device down: Bedroom TV (192.168.31.28)", _ago(hours=31)),
        ("success", "Back online: MacBook Pro 14 (192.168.31.21)", _ago(hours=3)),
        ("info", "Demo dataset loaded", _ago(days=1)),
    ]
    engine.db.xmany(
        "INSERT INTO notifications(level, content, created_at, read) VALUES (?, ?, ?, 0)",
        notes,
    )


def _seed_scans(engine: Engine) -> None:
    """Create recent scan-run history."""
    runs = []
    for hours, found, new, status in (
        (0.1, 22, 0, "ok"),
        (2.1, 22, 0, "ok"),
        (4.2, 21, 0, "ok"),
        (8.3, 23, 1, "ok"),
        (26.0, 20, 0, "error"),
    ):
        started = _ago(hours=hours)
        finished = (NOW - timedelta(hours=hours) + timedelta(seconds=14)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        runs.append(
            (started, finished, "schedule", found, new, found, status,
             "nmap · 192.168.31.0/24" if status == "ok" else "no scan target")
        )
    engine.db.xmany(
        "INSERT INTO scan_runs(started_at, finished_at, trigger, found, new_devices, online, "
        "status, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        runs,
    )


def _seed_workflows(engine: Engine) -> None:
    """Add two example automation rules."""
    engine.add_workflow(
        "Tag Apple devices",
        "new_device",
        "vendor",
        "contains",
        "Apple",
        "group_name",
        "Apple",
    )
    engine.add_workflow(
        "Label homelab servers",
        "scan",
        "type",
        "equals",
        "Server",
        "location",
        "Rack",
    )
    engine.db.x("UPDATE workflows SET enabled=1")
