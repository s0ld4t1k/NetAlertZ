"""Presence heatmap and uptime analytics."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Static

from ..widgets import StatCard, safe
from .base import BaseView


def _hour_label(bucket: str) -> str:
    """Convert a UTC presence bucket to a local hour label."""
    try:
        moment = datetime.strptime(bucket, "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
        return moment.astimezone().strftime("%H")
    except ValueError:
        return bucket[-2:]


def _cell(value: float) -> Text:
    """Render one presence cell."""
    if value < 0:
        return Text("·", style="#334155")
    if value >= 1:
        return Text("█", style="#34d399")
    if value > 0:
        return Text("▓", style="#fbbf24")
    return Text("░", style="#475569")


class PresenceView(BaseView):
    """Hourly presence heatmap for active devices."""

    view_id = "presence"
    nav_title = "Presence"
    nav_subtitle = "uptime · availability · history"

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "scan", "Scan"),
    ]

    def compose(self) -> ComposeResult:
        """Compose summary cards and the heatmap."""
        with Horizontal(id="presence-stats"):
            yield StatCard("Tracked", "0", "devices with samples", "primary", id="pres-tracked")
            yield StatCard("Average uptime", "0%", "last 24 hours", "success", id="pres-uptime")
            yield StatCard("Offline now", "0", "active devices", "warning", id="pres-offline")
            yield StatCard("Samples", "0", "hourly observations", "secondary", id="pres-samples")
        with Horizontal(classes="toolbar slim"):
            yield Static("[b]Hourly presence[/]  [dim]last 24 hours · local time[/]", classes="toolbar-title")
            yield Button("Refresh", id="presence-refresh")
            yield Button("Scan", id="presence-scan", variant="primary")
        with Horizontal(classes="subhead"):
            yield Static(
                "[#34d399]█[/] online   [#fbbf24]▓[/] partial   [#475569]░[/] offline   [dim]·[/] no sample",
                classes="hint",
            )
            yield Static("[dim]Enter opens the device detail[/]", classes="hint right")
        yield DataTable(id="presence-table", zebra_stripes=False, cursor_type="row")

    def refresh_data(self) -> None:
        """Reload aggregates and rebuild the heatmap."""
        summary = self.engine.presence_summary(hours=24, limit=5000)
        total_online = sum(int(row.get("online") or 0) for row in summary)
        total_samples = sum(int(row.get("samples") or 0) for row in summary)
        uptime = (100.0 * total_online / total_samples) if total_samples else 0.0
        counts = self.engine.counts()

        self.query_one("#pres-tracked", StatCard).update_stat(len(summary), "active devices")
        self.query_one("#pres-uptime", StatCard).update_stat(f"{uptime:.1f}%", f"{total_samples:,} samples")
        self.query_one("#pres-offline", StatCard).update_stat(counts.get("offline", 0) + counts.get("down", 0), "not answering")
        self.query_one("#pres-samples", StatCard).update_stat(f"{total_samples:,}", "hourly observations")

        grid, buckets = self.engine.presence_grid(hours=24, limit=200)
        buckets = buckets[-24:]
        table = self.query_one("#presence-table", DataTable)
        table.cell_padding = 0
        table.clear(columns=True)
        table.add_column("Device", width=17)
        table.add_column("Uptime", width=7)
        for bucket in buckets:
            table.add_column(_hour_label(bucket), width=3)

        if not grid:
            table.add_row(
                Text("No presence samples yet", style="dim"),
                Text("—", style="dim"),
                *[Text("·", style="#334155") for _ in buckets],
                key="empty",
            )
            return

        for entry in grid:
            rows = []
            for bucket in buckets:
                value = entry["cells"].get(bucket, -1)
                rows.append(_cell(float(value)))
            online = sum(max(0.0, float(entry["cells"].get(bucket, 0))) for bucket in buckets)
            coverage = sum(1 for bucket in buckets if bucket in entry["cells"])
            uptime_pct = (online / coverage * 100) if coverage else 0.0
            style = "#34d399" if uptime_pct >= 90 else "#fbbf24" if uptime_pct >= 50 else "#fb7185"
            table.add_row(
                Text(str(entry.get("name") or entry.get("mac")), style="bold"),
                Text(f"{uptime_pct:.0f}%", style=style),
                *rows,
                key=str(entry["mac"]),
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle toolbar actions."""
        if event.button.id == "presence-refresh":
            self.refresh_data()
            self.notify("Presence refreshed")
        elif event.button.id == "presence-scan":
            self.app.start_scan()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected device."""
        key = str(event.row_key.value or "")
        if key and key != "empty":
            self.app.open_device(key)

    def action_refresh(self) -> None:
        """Reload presence data."""
        self.refresh_data()

    def action_scan(self) -> None:
        """Start discovery."""
        self.app.start_scan()
