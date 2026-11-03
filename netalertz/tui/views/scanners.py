"""Scanner status, discovery configuration and scan history."""

from __future__ import annotations

import shutil

from rich.console import Group
from rich.table import Table as RichTable
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from ...utils import local_ts, parse_ts
from ..widgets import StatCard, safe
from .base import BaseView

TOOLS = [
    ("arp-scan", "Layer 2 sweep", "best signal, usually needs root"),
    ("nmap", "Portable discovery", "ping + ARP hybrid, no root"),
    ("fping", "Fast ICMP sweep", "lightweight ping scanner"),
    ("ping", "Native fallback", "slow but always present"),
    ("cache", "ARP cache", "instant, what the OS already knows"),
]


class ScannersView(BaseView):
    """Discovery backend status and scan history."""

    view_id = "scanners"
    nav_title = "Scanners"
    nav_subtitle = "discovery backends · scan runs"

    BINDINGS = [
        ("s", "scan", "Scan"),
        ("r", "refresh", "Refresh"),
        ("g", "settings", "Settings"),
    ]

    def compose(self) -> ComposeResult:
        """Compose capability cards, history and configuration."""
        with Horizontal(id="scanner-stats"):
            for tool, label, note in TOOLS:
                yield StatCard(tool, "…", note, "muted", id=f"cap-{tool.replace('-', '_')}")
        with Horizontal(classes="toolbar slim"):
            yield Static("", id="scanner-method", classes="toolbar-title")
            yield Button("Run scan", id="scanner-scan", variant="primary")
            yield Button("Settings", id="scanner-settings")
            yield Button("Refresh", id="scanner-refresh")
        with Horizontal(id="scanner-body"):
            with Vertical(classes="panel", id="scan-history-panel"):
                yield Static("[b]Scan runs[/]  [dim]newest first[/]", classes="panel-title")
                yield DataTable(id="scan-history", zebra_stripes=True, cursor_type="row")
            with Vertical(classes="panel", id="scanner-config-panel"):
                yield Static("[b]Discovery configuration[/]  [dim]live settings[/]", classes="panel-title")
                yield Static("", id="scanner-config")

    def refresh_data(self) -> None:
        """Refresh capabilities, config and history."""
        caps = self.engine.scanner.capabilities()
        for tool, _, _ in TOOLS:
            card = self.query_one(f"#cap-{tool.replace('-', '_')}", StatCard)
            installed = bool(caps.get(tool))
            path = shutil.which(tool)
            if tool == "cache":
                installed, path = True, "built-in"
            card.update_stat("ready" if installed else "missing", path or "not installed")
            card.set_classes(f"stat-card tone-{'success' if installed else 'error'}")

        method = self.engine.scanner.effective_method()
        targets = self.engine.scanner.plan_targets()
        self.query_one("#scanner-method", Static).update(
            f"[b]Active method[/] [#22d3ee]{safe(method)}[/]   [dim]·[/]  "
            f"[b]Targets[/] {safe(', '.join(targets) or 'none detected')}"
        )

        settings = self.engine.settings
        config = RichTable.grid(padding=(0, 2))
        config.add_column(style="dim")
        config.add_column()
        config.add_row("Method", Text(str(settings.get("discovery_method") or "auto")))
        config.add_row("Effective", Text(method, style="#22d3ee"))
        config.add_row("Targets", Text(", ".join(targets) or "auto-detect", style="#7dd3fc"))
        config.add_row("Interval", Text(f"{settings.get_int('scan_interval')} sec", style="bold"))
        config.add_row("Schedule", Text("enabled" if settings.get_bool("scheduled_scans") else "disabled"))
        config.add_row("On launch", Text("yes" if settings.get_bool("auto_scan_on_start") else "no"))
        config.add_row("Interface", Text(str(settings.get("scan_interface") or "auto")))
        config.add_row("Timeout", Text(f"{settings.get_int('scan_timeout')} sec"))
        config.add_row("Resolve", Text("yes" if settings.get_bool("resolve_names") else "no"))
        config.add_row("Vendor", Text("yes" if settings.get_bool("vendor_lookup") else "no"))
        hint = Text(
            "\nInstall arp-scan for the strongest discovery signal.\n"
            "macOS: brew install arp-scan nmap\n"
            "Debian/Ubuntu: sudo apt install arp-scan nmap fping",
            style="dim italic",
        )
        self.query_one("#scanner-config", Static).update(Group(config, hint))

        narrow = self.app.size.width < 136
        table = self.query_one("#scan-history", DataTable)
        table.clear(columns=True)
        table.add_column("Started", width=12)
        table.add_column("Trigger", width=8)
        table.add_column("Found", width=5)
        table.add_column("New", width=3)
        table.add_column("Took", width=4)
        if not narrow:
            table.add_column("Method / note", width=14)
        table.add_column("Status", width=6)
        for run in self.engine.recent_scans(30):
            status = str(run.get("status") or "running")
            style = {"ok": "#34d399", "error": "#fb7185", "running": "#22d3ee"}.get(status, "#94a3b8")
            started = parse_ts(run.get("started_at"))
            finished = parse_ts(run.get("finished_at"))
            took = f"{int((finished - started).total_seconds())}s" if started and finished else "—"
            cells = [
                local_ts(run.get("started_at")),
                str(run.get("trigger") or "—"),
                str(run.get("found") or 0),
                str(run.get("new_devices") or 0),
                took,
            ]
            if not narrow:
                cells.append(safe(str(run.get("message") or "")))
            cells.append(Text(status.upper(), style=f"bold {style}"))
            table.add_row(*cells, key=f"run-{run.get('id')}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle scanner actions."""
        if event.button.id == "scanner-scan":
            self.app.start_scan()
        elif event.button.id == "scanner-settings":
            self.action_settings()
        elif event.button.id == "scanner-refresh":
            self.refresh_data()
            self.notify("Scanner status refreshed")

    def action_scan(self) -> None:
        """Start discovery."""
        self.app.start_scan()

    def action_settings(self) -> None:
        """Jump to the settings view."""
        self.app.switch_view("settings")

    def action_refresh(self) -> None:
        """Reload scanner data."""
        self.refresh_data()
