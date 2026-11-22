"""Textual application shell: navigation, timers, scans and theme handling."""

from __future__ import annotations

import time
from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, Static

from ..config import VERSION, db_path
from ..engine import Engine
from ..utils import ago, human_bytes
from .detail import DeviceDetailScreen
from .themes import THEMES, THEME_ORDER
from .views import VIEW_CLASSES, BaseView
from .widgets import FooterBar, NavItem, Sidebar, TopBar, clock_parts

SEVERITY = {
    "alert": "error",
    "warn": "warning",
    "success": "information",
    "info": "information",
}


class NetAlertZApp(App):
    """The NetAlertZ terminal application."""

    CSS_PATH = "theme.tcss"
    TITLE = "NetAlertZ"
    SUB_TITLE = "network intelligence in your terminal"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("f2", "cycle_theme", "Theme"),
        Binding("s", "scan", "Scan"),
        Binding("r", "refresh", "Refresh"),
        Binding("question_mark", "view_help", "Help"),
        Binding("1", "view_dashboard", "Dashboard", show=False),
        Binding("2", "view_devices", "Devices", show=False),
        Binding("3", "view_events", "Events", show=False),
        Binding("4", "view_presence", "Presence", show=False),
        Binding("5", "view_network", "Network", show=False),
        Binding("6", "view_scanners", "Scanners", show=False),
        Binding("7", "view_automations", "Automations", show=False),
        Binding("8", "view_notifications", "Alerts", show=False),
        Binding("9", "view_settings", "Settings", show=False),
        Binding("l", "view_logs", "Logs", show=False),
        Binding("h", "view_help", "Help", show=False),
    ]

    def __init__(
        self,
        database: str | Path | None = None,
        *,
        allow_scan: bool = True,
        interval: int | None = None,
        scan_on_start: bool | None = None,
    ) -> None:
        super().__init__()
        self.engine = Engine(database or db_path())
        self.allow_scan = allow_scan
        self.scan_on_start = scan_on_start
        if interval is not None:
            self.engine.settings.set("scan_interval", max(15, int(interval)))
        self.current_view = "dashboard"
        self._scanning_since: float | None = None
        self._last_event_refresh = 0.0
        # NB: App itself uses ``_resize_timer`` for its layout reflow. Never
        # reuse that name here, or the screen stops resizing with the terminal.
        self._resize_refresh_timer = None

    def compose(self) -> ComposeResult:
        """Compose the persistent application shell."""
        with Vertical(id="app-shell"):
            yield TopBar()
            with Horizontal(id="main"):
                yield Sidebar()
                yield ContentSwitcher(
                    *[view_class(self.engine) for view_class in VIEW_CLASSES],
                    initial="view-dashboard",
                    id="content",
                )
            yield FooterBar()

    # ------------------------------------------------------------------ startup
    def on_mount(self) -> None:
        """Register themes, start timers and schedule the first scan."""
        for theme in THEMES.values():
            self.register_theme(theme)
        saved_theme = str(self.engine.settings.get("theme") or "netalertz")
        self.apply_theme(saved_theme if saved_theme in THEME_ORDER else "netalertz", persist=False)

        self.refresh_sidebar()
        self.update_topbar()
        self.set_interval(1.0, self._tick_clock)
        self.set_interval(0.4, self._poll_events)
        self.set_interval(5.0, self._tick_refresh)

        if self.allow_scan:
            self.engine.start_scheduler()
            should_scan = (
                self.scan_on_start
                if self.scan_on_start is not None
                else self.engine.settings.get_bool("auto_scan_on_start")
            )
            if should_scan:
                self.set_timer(1.6, self.start_scan)
        self._apply_layout()
        self.switch_view("dashboard", notify=False)

    def _apply_layout(self, width: int | None = None, height: int | None = None) -> None:
        """Toggle responsive classes for narrow or short terminals."""
        try:
            shell = self.query_one("#app-shell")
        except Exception:
            return
        width = self.size.width if width is None else width
        height = self.size.height if height is None else height
        shell.set_class(width < 132, "narrow")
        shell.set_class(height < 40, "short")
        tiny = width < 110
        shell.set_class(tiny, "tiny")
        micro = width < 76
        shell.set_class(micro, "micro")
        for item in self.query(NavItem):
            item.set_compact(tiny)

    def on_resize(self, event) -> None:
        """Re-evaluate responsive layout after a terminal resize."""
        size = getattr(event, "size", None)
        if size is not None:
            self._apply_layout(size.width, size.height)
        else:
            self._apply_layout()
        if self._resize_refresh_timer is not None:
            self._resize_refresh_timer.stop()
        self._resize_refresh_timer = self.set_timer(0.25, self.refresh_current)

    def on_unmount(self) -> None:
        """Stop the background scheduler when the app exits."""
        self.engine.stop_scheduler()

    # ------------------------------------------------------------------ top bar
    def _tick_clock(self) -> None:
        """Update the clock once a second."""
        clock, date = clock_parts()
        self.query_one(TopBar).update_clock(clock, date)

    def update_topbar(self) -> None:
        """Refresh network, scan and clock metadata."""
        targets = self.engine.scanner.plan_targets()
        network = escape(targets[0]) if targets else "no network"
        method = self.engine.scanner.effective_method()
        if self.engine.scanning:
            elapsed = int(time.monotonic() - (self._scanning_since or time.monotonic()))
            scan_line = f"[#22d3ee]◉ scanning[/] [dim]{elapsed}s · {method}[/]"
        else:
            last = self.engine.last_scan()
            when = ago(last.get("started_at")) if last else "never"
            scan_line = f"[dim]last scan {when} · {method}[/]"
        clock, date = clock_parts()
        self.query_one(TopBar).update_meta(
            f"[#34d399]●[/] {network}",
            scan_line,
            clock,
            date,
        )
        db_file = Path(self.engine.db.path)
        size = human_bytes(db_file.stat().st_size) if db_file.exists() else "0 B"
        self.query_one("#footer-meta", Static).update(
            f"v{VERSION}  ·  {self.theme}  ·  db {size}"
        )

    def refresh_sidebar(self) -> None:
        """Refresh navigation counters and the live network summary."""
        try:
            counts = self.engine.counts()
            active = max(0, counts.get("total", 0) - counts.get("archived", 0))
            unread = self.engine.notifier.unread_count()
            workflows = self.engine.workflows()
            enabled = sum(1 for rule in workflows if int(rule.get("enabled") or 0))
            self._nav("dashboard").set_count(counts.get("online", 0))
            self._nav("devices").set_count(active)
            self._nav("events").set_count(None)
            self._nav("presence").set_count(None)
            self._nav("network").set_count(None)
            self._nav("scanners").set_count(None)
            self._nav("automations").set_count(enabled)
            self._nav("notifications").set_count(unread or None, "alert")
            self._nav("settings").set_count(None)
            self._nav("logs").set_count(None)
            self._nav("help").set_count(None)
            for nav_id in self._nav_ids():
                self._nav(nav_id).set_active(nav_id == self.current_view)
            targets = self.engine.scanner.plan_targets()
            self.query_one("#sidebar-status", Static).update(
                f"[#34d399]●[/] {counts.get('online', 0)} online  "
                f"[#fb7185]▼[/] {counts.get('down', 0)} down\n"
                f"[#fbbf24]◐[/] {counts.get('sleeping', 0)} sleeping  "
                f"[#22d3ee]✦[/] {counts.get('new', 0)} new\n"
                f"[dim]{escape(targets[0]) if targets else 'no target'}[/]\n"
                f"[dim]{self.engine.scanner.effective_method()} · v{VERSION}[/]"
            )
        except Exception:
            # The sidebar must never be able to crash the app during startup.
            pass

    def _nav_ids(self) -> list[str]:
        """Return every navigation identifier."""
        return [
            "dashboard",
            "devices",
            "events",
            "presence",
            "network",
            "scanners",
            "automations",
            "notifications",
            "settings",
            "logs",
            "help",
        ]

    def _nav(self, nav_id: str) -> NavItem:
        """Return a navigation row by id."""
        return self.query_one(f"#nav-{nav_id}", NavItem)

    # --------------------------------------------------------------- navigation
    def on_nav_item_selected(self, event: NavItem.Selected) -> None:
        """Switch views when a sidebar row is clicked."""
        event.stop()
        self.switch_view(event.nav_id)

    def switch_view(self, nav_id: str, notify: bool = True) -> None:
        """Show one view and refresh its data."""
        if nav_id not in self._nav_ids():
            return
        self.current_view = nav_id
        switcher = self.query_one("#content", ContentSwitcher)
        switcher.current = f"view-{nav_id}"
        view = self.query_one(f"#view-{nav_id}", BaseView)
        view.refresh_view()
        self._focus_view(view)
        for candidate in self._nav_ids():
            self._nav(candidate).set_active(candidate == nav_id)
        self.query_one(TopBar).update_view(view.nav_title, view.nav_subtitle)
        if notify:
            self.update_topbar()

    @staticmethod
    def _focus_view(view: BaseView) -> None:
        """Focus the main interactive widget so view shortcuts keep working."""
        from textual.widgets import DataTable, Input, RichLog, Tree

        for widget_type in (DataTable, Tree, RichLog, Input):
            for widget in view.query(widget_type):
                try:
                    if widget.is_mounted and widget.display:
                        widget.focus()
                        return
                except Exception:
                    continue

    def action_view_dashboard(self) -> None:
        """Jump to the dashboard."""
        self.switch_view("dashboard")

    def action_view_devices(self) -> None:
        """Jump to devices."""
        self.switch_view("devices")

    def action_view_events(self) -> None:
        """Jump to events."""
        self.switch_view("events")

    def action_view_presence(self) -> None:
        """Jump to presence."""
        self.switch_view("presence")

    def action_view_network(self) -> None:
        """Jump to the network tree."""
        self.switch_view("network")

    def action_view_scanners(self) -> None:
        """Jump to scanners."""
        self.switch_view("scanners")

    def action_view_automations(self) -> None:
        """Jump to automations."""
        self.switch_view("automations")

    def action_view_notifications(self) -> None:
        """Jump to alerts."""
        self.switch_view("notifications")

    def action_view_settings(self) -> None:
        """Jump to settings."""
        self.switch_view("settings")

    def action_view_logs(self) -> None:
        """Jump to logs."""
        self.switch_view("logs")

    def action_view_help(self) -> None:
        """Jump to help."""
        self.switch_view("help")

    # -------------------------------------------------------------------- themes
    def apply_theme(self, name: str, persist: bool = True) -> None:
        """Apply one of the bundled themes."""
        theme = name if name in THEME_ORDER else "netalertz"
        self.theme = theme
        if persist:
            self.engine.settings.set("theme", theme)
        self.update_topbar()
        self.refresh_sidebar()

    def action_cycle_theme(self) -> None:
        """Cycle through the bundled palettes."""
        try:
            index = THEME_ORDER.index(self.theme)
        except ValueError:
            index = 0
        new_theme = THEME_ORDER[(index + 1) % len(THEME_ORDER)]
        self.apply_theme(new_theme)
        self.notify(f"Theme · {new_theme}")

    # --------------------------------------------------------------------- scans
    def start_scan(self) -> None:
        """Start a background discovery scan."""
        if not self.allow_scan:
            self.notify("Scanning is disabled for this session", "warning")
            return
        if self.engine.scanning or self._scanning_since is not None:
            self.notify("A scan is already running", "warning")
            return
        self._scanning_since = time.monotonic()
        self.update_topbar()
        self.notify("Discovery scan started")
        self._scan_worker()

    @work(thread=True, exclusive=True, group="scan")
    def _scan_worker(self) -> None:
        """Run the scan pipeline on a worker thread."""
        self.engine.scan(trigger="manual")

    def action_scan(self) -> None:
        """Binding target for s."""
        self.start_scan()

    def action_refresh(self) -> None:
        """Refresh the active view."""
        self.refresh_current()
        self.refresh_sidebar()
        self.update_topbar()
        self.notify("Refreshed")

    def refresh_current(self) -> None:
        """Refresh the visible view, if it supports it."""
        try:
            view = self.query_one(f"#view-{self.current_view}", BaseView)
        except Exception:
            return
        view.refresh_view()

    # ------------------------------------------------------------------ events
    def _poll_events(self) -> None:
        """Drain engine events and update the interface."""
        changed = False
        for event in self.engine.drain_events(200):
            kind = str(event.get("type") or "")
            if kind == "scan_start":
                self._scanning_since = time.monotonic()
                self.update_topbar()
                changed = True
            elif kind in {"scan_done", "scan_error"}:
                self._scanning_since = None
                summary = event.get("summary") or {}
                if kind == "scan_done":
                    self.notify(
                        f"Scan complete · {summary.get('found', 0)} found · "
                        f"{summary.get('new', 0)} new · {summary.get('duration', '?')}s",
                        "information",
                    )
                else:
                    self.notify(str(event.get("message") or "Scan failed"), "error")
                self.update_topbar()
                self.refresh_sidebar()
                self.refresh_current()
                changed = True
            elif kind == "notification":
                self.notify(
                    str(event.get("content") or "New alert"),
                    SEVERITY.get(str(event.get("level")), "information"),
                )
                changed = True
            elif kind in {"devices_changed", "workflows_changed", "settings_changed"}:
                self.refresh_sidebar()
                self.refresh_current()
                changed = True
        if changed:
            self.refresh_sidebar()

    def _tick_refresh(self) -> None:
        """Periodically refresh the visible view and metadata."""
        self.update_topbar()
        if self.engine.scanning:
            return
        try:
            view = self.query_one(f"#view-{self.current_view}", BaseView)
            if view.auto_refresh:
                view.refresh_view()
        except Exception:
            pass

    # ------------------------------------------------------------------ devices
    def open_device(self, mac: str) -> None:
        """Open the detail modal for a device key."""
        if not mac:
            return
        device = self.engine.get_device(mac)
        if device is None:
            self.notify(f"Device not found: {mac}", "warning")
            return
        self.push_screen(DeviceDetailScreen(self.engine, str(device["mac"])))

    def notify(self, message: str, severity: str = "information", **kwargs) -> None:  # type: ignore[override]
        """Show a toast, tolerating invalid severities from callers."""
        if severity not in {"information", "warning", "error"}:
            severity = "information"
        super().notify(message, severity=severity, **kwargs)


def run() -> None:
    """Entry point used by the CLI."""
    NetAlertZApp().run()
