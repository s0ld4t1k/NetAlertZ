"""Dashboard: live KPIs, presence trend, recent activity and attention list."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Sparkline, Static

from ...engine import Engine
from ...utils import local_ts
from ..widgets import StatCard, event_text, safe
from .base import BaseView, status_cell


class DashboardView(BaseView):
    """High-level overview of the whole network."""

    view_id = "dashboard"
    nav_title = "Dashboard"
    nav_subtitle = "live network intelligence"

    BINDINGS = [
        ("s", "scan", "Scan"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the dashboard grid."""
        with Horizontal(id="dash-head"):
            with Vertical(id="dash-head-text"):
                yield Static("Network overview", id="dash-headline")
                yield Static("", id="dash-summary")
            yield Button("Run scan  [b]s[/]", id="dash-scan", variant="primary")
        with Horizontal(id="stat-row"):
            yield StatCard("Devices", "0", "in inventory", "primary", id="stat-total")
            yield StatCard("Online", "0", "responding now", "success", id="stat-online")
            yield StatCard("Offline", "0", "not seen recently", "muted", id="stat-offline")
            yield StatCard("Down", "0", "past threshold", "error", id="stat-down")
            yield StatCard("Sleeping", "0", "known sleepy devices", "warning", id="stat-sleeping")
            yield StatCard("Alerts", "0", "unread notifications", "secondary", id="stat-alerts")
        with Horizontal(id="dash-mid"):
            with Vertical(classes="panel", id="presence-panel"):
                yield Static("[b]Network presence[/]  [dim]last 24 hours[/]", classes="panel-title")
                yield Sparkline([], id="presence-spark")
                yield Static("", id="presence-meta")
                yield Static("", id="presence-legend")
            with Vertical(classes="panel", id="scan-panel"):
                yield Static("[b]Scan history[/]  [dim]latest runs[/]", classes="panel-title")
                yield DataTable(id="scan-table", zebra_stripes=True, cursor_type="row")
        with Horizontal(id="dash-bottom"):
            with Vertical(classes="panel", id="activity-panel"):
                yield Static("[b]Recent activity[/]  [dim]events newest first[/]", classes="panel-title")
                yield DataTable(id="dash-events", zebra_stripes=True, cursor_type="row")
            with Vertical(classes="panel", id="attention-panel"):
                yield Static("[b]Needs attention[/]  [dim]down · new · offline[/]", classes="panel-title")
                yield DataTable(id="attention-table", zebra_stripes=True, cursor_type="row")

    def on_mount(self) -> None:
        """Prepare tables then load data."""
        scans = self.query_one("#scan-table", DataTable)
        for label, width in (("When", 12), ("Found", 5), ("New", 4), ("State", 7)):
            scans.add_column(label, width=width)
        events = self.query_one("#dash-events", DataTable)
        for label, width in (("Time", 12), ("Type", 12), ("Device", 15), ("Detail", 14)):
            events.add_column(label, width=width)
        attention = self.query_one("#attention-table", DataTable)
        for label, width in (("State", 9), ("Device", 13), ("Detail", 12)):
            attention.add_column(label, width=width)
        super().on_mount()

    def refresh_data(self) -> None:
        """Reload every dashboard widget."""
        data = self.engine.dashboard_data()
        counts = data["counts"]
        now = datetime.now()
        greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
        target = ", ".join(data["targets"]) or "no target detected"
        self.query_one("#dash-headline", Static).update(f"{greeting} — here is your network")
        self.query_one("#dash-summary", Static).update(
            f"[dim]{safe(target)}[/]  ·  [dim]{safe(data['method'])} discovery[/]  ·  "
            f"[b]{counts.get('online', 0)}[/] [dim]of[/] [b]{counts.get('total', 0)}[/] [dim]devices online[/]"
        )

        self.query_one("#stat-total", StatCard).update_stat(counts.get("total", 0), f"{counts.get('archived', 0)} archived")
        self.query_one("#stat-online", StatCard).update_stat(counts.get("online", 0), f"{counts.get('favorites', 0)} favourites")
        self.query_one("#stat-offline", StatCard).update_stat(counts.get("offline", 0), "missed last scan")
        self.query_one("#stat-down", StatCard).update_stat(counts.get("down", 0), "alert threshold hit")
        self.query_one("#stat-sleeping", StatCard).update_stat(counts.get("sleeping", 0), "down alerts suppressed")
        self.query_one("#stat-alerts", StatCard).update_stat(data["unread"], "in-app alerts")

        series = data["series"]
        spark = self.query_one("#presence-spark", Sparkline)
        spark.data = [float(row.get("devices") or 0) for row in series] or [0.0]
        average = sum(float(row.get("devices") or 0) for row in series) / max(len(series), 1)
        peak = max((int(row.get("devices") or 0) for row in series), default=0)
        sampled = int(sum(int(row.get("tracked") or 0) for row in series))
        self.query_one("#presence-meta", Static).update(
            f"[b]{average:.1f}[/] [dim]avg devices / hour[/]    "
            f"[b]{peak}[/] [dim]peak[/]    [b]{sampled:,}[/] [dim]samples[/]"
        )
        self.query_one("#presence-legend", Static).update(
            "[#34d399]▬ online[/]   [#94a3b8]▬ offline[/]   "
            "[dim]per scan[/]"
        )

        scans = self.query_one("#scan-table", DataTable)
        scans.clear()
        for run in data["scans"]:
            status = str(run.get("status") or "running")
            style = {"ok": "#34d399", "error": "#fb7185", "running": "#22d3ee"}.get(status, "#94a3b8")
            state = {"ok": "OK", "error": "ERR", "running": "RUN"}.get(status, status[:3].upper())
            scans.add_row(
                local_ts(run.get("started_at")),
                str(run.get("found") or 0),
                str(run.get("new_devices") or 0),
                Text(state, style=f"bold {style}"),
                key=f"scan-{run.get('id')}",
            )

        narrow = self.app.size.width < 132
        events = self.query_one("#dash-events", DataTable)
        events.clear(columns=True)
        if narrow:
            for label, width in (("Time", 12), ("Device", 16), ("Detail", 13)):
                events.add_column(label, width=width)
        else:
            for label, width in (("Time", 12), ("Type", 12), ("Device", 15), ("Detail", 14)):
                events.add_column(label, width=width)
        for event in data["events"]:
            cells = [
                local_ts(event.get("created_at")),
                safe(event.get("device_name") or event.get("mac") or "system"),
                safe(str(event.get("info") or "")[:80]),
            ]
            if not narrow:
                cells.insert(1, event_text(str(event.get("type") or "")))
            events.add_row(
                *cells, key=f"event-{event.get('id') or event.get('mac') or 'event'}"
            )

        attention = self.query_one("#attention-table", DataTable)
        attention.clear(columns=True)
        if narrow:
            for label, width in (("State", 9), ("Device", 9), ("Detail", 8)):
                attention.add_column(label, width=width)
        else:
            for label, width in (("State", 9), ("Device", 13), ("Detail", 12)):
                attention.add_column(label, width=width)
        # A device can match several buckets (e.g. new AND offline), so merge
        # them while keeping the most urgent status per MAC and avoiding
        # duplicate row keys.
        rank = {"down": 0, "new": 1, "offline": 2}
        merged: dict[str, dict] = {}
        for row in (
            self.engine.list_devices(status="down", limit=20)
            + self.engine.list_devices(status="new", limit=20)
            + self.engine.list_devices(status="offline", limit=20)
        ):
            key = str(row.get("mac") or "")
            if not key:
                continue
            current = merged.get(key)
            if current is None or rank.get(row.get("status", ""), 3) < rank.get(
                current.get("status", ""), 3
            ):
                merged[key] = row
        rows = sorted(
            merged.values(), key=lambda row: rank.get(row.get("status", ""), 3)
        )
        for device in rows[:8]:
            detail = device.get("ip") or device.get("mac") or ""
            if device.get("status") == "down":
                detail = f"missing since {device.get('last_seen_human')}"
            elif device.get("status") == "new":
                detail = f"first seen {device.get('last_seen_human')}"
            attention.add_row(
                status_cell(device),
                safe(device.get("name") or device.get("mac")),
                safe(detail),
                key=str(device.get("mac")),
            )
        if not rows:
            attention.add_row(
                Text("✓", style="bold #34d399"),
                Text("Everything looks quiet", style="bold"),
                Text("no down, new or stale devices", style="dim"),
                key="none",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Trigger a scan from the hero button."""
        if event.button.id == "dash-scan":
            self.action_scan()

    def action_scan(self) -> None:
        """Ask the application to start discovery."""
        self.app.start_scan()

    def action_refresh(self) -> None:
        """Reload dashboard data."""
        self.refresh_data()
        self.notify("Dashboard refreshed")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected device."""
        key = str(event.row_key.value or "")
        if key and not key.startswith(("scan-", "event-")) and key != "none":
            self.app.open_device(key)
        elif key.startswith("event-"):
            self.app.open_device(key.removeprefix("event-"))
