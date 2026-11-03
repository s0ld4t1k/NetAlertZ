"""Full device detail with overview, activity, presence, sessions and tools."""

from __future__ import annotations

from rich.console import Group
from rich.table import Table as RichTable
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, RichLog, Sparkline, Static, TabbedContent, TabPane

from ..engine import Engine
from ..utils import local_ts, parse_ts
from .modals import ConfirmModal, EditDeviceModal
from .widgets import STATUS_COLORS, STATUS_GLYPHS, event_text


class DeviceDetailScreen(ModalScreen):
    """Modal inspector for a single device."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("e", "edit", "Edit"),
        Binding("w", "wake", "Wake"),
        Binding("f", "favorite", "Favourite"),
        Binding("a", "archive", "Archive"),
        Binding("d", "delete", "Delete"),
    ]

    def __init__(self, engine: Engine, mac: str) -> None:
        super().__init__()
        self.engine = engine
        self.mac = mac
        self.device = engine.get_device(mac) or {}

    def compose(self) -> ComposeResult:
        """Compose the detail card."""
        with Container(id="detail-card"):
            with Horizontal(id="detail-head"):
                with Vertical(id="detail-head-text"):
                    yield Static("", id="detail-name")
                    yield Static("", id="detail-meta")
                yield Static("", id="detail-status")
                yield Button("✕", id="detail-close", classes="close-button")
            with TabbedContent(initial="tab-overview", id="detail-tabs"):
                with TabPane("Overview", id="tab-overview"):
                    with VerticalScroll(classes="detail-scroll"):
                        yield Static("", id="detail-overview")
                with TabPane("Activity", id="tab-activity"):
                    yield DataTable(id="detail-events", zebra_stripes=True, cursor_type="row")
                with TabPane("Presence", id="tab-presence"):
                    with VerticalScroll(classes="detail-scroll"):
                        yield Static("", id="detail-presence-summary")
                        yield Sparkline([], id="detail-spark")
                        yield Static("", id="detail-presence-note")
                with TabPane("Sessions", id="tab-sessions"):
                    yield DataTable(id="detail-sessions", zebra_stripes=True, cursor_type="row")
                with TabPane("Tools", id="tab-tools"):
                    with Horizontal(classes="toolbar detail-tools"):
                        yield Static("", id="tool-target", classes="toolbar-title")
                        yield Button("Ping", id="tool-ping")
                        yield Button("nmap", id="tool-nmap", variant="primary")
                        yield Button("Traceroute", id="tool-trace")
                    yield RichLog(id="tool-output", wrap=True, markup=True, max_lines=800)
            with Horizontal(id="detail-actions"):
                yield Button("Edit  e", id="detail-edit", variant="primary")
                yield Button("Wake  w", id="detail-wake")
                yield Button("Favourite  f", id="detail-fav")
                yield Button("Archive  a", id="detail-archive")
                yield Button("Delete  d", id="detail-delete", variant="error")
                yield Button("Close", id="detail-close-2")

    def on_mount(self) -> None:
        """Populate all tabs."""
        self._follow = True
        self._prepare_tables()
        self._reload()
        output = self.query_one("#tool-output", RichLog)
        output.write("[dim]Run a diagnostic against this device. Output appears here.[/]")

    def _prepare_tables(self) -> None:
        """Create the static table headers."""
        events = self.query_one("#detail-events", DataTable)
        events.add_column("When", width=12)
        events.add_column("Event", width=16)
        events.add_column("Detail", width=None)
        sessions = self.query_one("#detail-sessions", DataTable)
        sessions.add_column("Connected", width=15)
        sessions.add_column("Disconnected", width=15)
        sessions.add_column("Duration", width=10)
        sessions.add_column("IP", width=None)

    def _reload(self) -> None:
        """Reload the device and refresh every tab."""
        device = self.engine.get_device(self.mac)
        if not device:
            self.notify("This device no longer exists", "error")
            self.dismiss(None)
            return
        self.device = device
        name = str(device.get("name") or device.get("mac"))
        status = str(device.get("status") or "offline")
        color = STATUS_COLORS.get(status, "#94a3b8")
        glyph = STATUS_GLYPHS.get(status, "○")
        self.query_one("#detail-name", Static).update(Text(name, style="bold"))
        self.query_one("#detail-meta", Static).update(
            Text(
                f"{device.get('ip') or 'no address'}  ·  {device.get('mac')}  ·  "
                f"{device.get('vendor') or 'unknown vendor'}  ·  {device.get('type') or 'untyped'}",
                style="#94a3b8",
            )
        )
        status_text = Text()
        status_text.append(f"{glyph} ", style=f"bold {color}")
        status_text.append(str(device.get("status_label") or status.title()), style=f"bold {color}")
        self.query_one("#detail-status", Static).update(status_text)
        self.query_one("#tool-target", Static).update(
            f"[b]Diagnostics[/]  [dim]target[/] [#7dd3fc]{device.get('ip') or 'no IP address'}[/]"
        )
        self._render_overview(device)
        self._render_events()
        self._render_presence(device)
        self._render_sessions()
        self._update_buttons(device)

    def _render_overview(self, device: dict) -> None:
        """Render the key/value overview grid."""
        parent = self.engine.db.q1(
            "SELECT name, mac FROM devices WHERE mac=?", (device.get("parent_mac"),)
        )
        flags = []
        for key, label in (
            ("favorite", "favourite"),
            ("archived", "archived"),
            ("scan_enabled", "scanned"),
            ("alert_down", "down alerts"),
            ("can_sleep", "can sleep"),
            ("static_ip", "static IP"),
        ):
            if int(device.get(key) or 0):
                flags.append(label)
        table = RichTable.grid(padding=(0, 2))
        table.add_column(style="dim", justify="left")
        table.add_column(justify="left")
        rows = [
            ("IP address", device.get("ip") or "—"),
            ("MAC", device.get("mac") or "—"),
            ("Vendor", device.get("vendor") or "—"),
            ("Type", device.get("type") or "—"),
            ("Group", device.get("group_name") or "—"),
            ("Owner", device.get("owner") or "—"),
            ("Location", device.get("location") or "—"),
            ("Site", device.get("site") or "—"),
            ("SSID", device.get("ssid") or "—"),
            ("VLAN", device.get("vlan") or "—"),
            ("Parent", (parent or {}).get("name") or "—"),
            ("Parent port", device.get("parent_port") or "—"),
            ("Link type", device.get("parent_rel") or "—"),
            ("First seen", local_ts(device.get("first_seen"))),
            ("Last seen", f"{local_ts(device.get('last_seen'))}  ({device.get('last_seen_human')})"),
            ("Source", device.get("source") or "—"),
            ("Name source", device.get("name_source") or "—"),
            ("Flags", ", ".join(flags) or "none"),
            ("History entries", str(len(self.engine.history(self.mac, limit=500)))),
        ]
        for label, value in rows:
            table.add_row(label, Text(str(value), style="#dbe7ff"))
        heading = Text("Device profile", style="bold #22d3ee")
        comments = str(device.get("comments") or "").strip()
        body = [heading, Text(""), table]
        if comments:
            body.extend([Text(""), Text("Notes", style="bold #22d3ee"), Text(comments, style="#cbd5e1")])
        body.extend(
            [
                Text(""),
                Text(
                    "Use Edit to change identity, ownership and behaviour flags. "
                    "Parent links drive the network tree.",
                    style="dim italic",
                ),
            ]
        )
        self.query_one("#detail-overview", Static).update(Group(*body))

    def _render_events(self) -> None:
        """Fill the activity table."""
        table = self.query_one("#detail-events", DataTable)
        table.clear()
        events = self.engine.events_for(self.mac, limit=200)
        for event in events:
            table.add_row(
                Text(local_ts(event.get("created_at")), style="dim"),
                event_text(str(event.get("type") or "")),
                str(event.get("info") or ""),
                key=f"event-{event.get('id')}",
            )
        if not events:
            table.add_row(Text("—", style="dim"), Text("No activity yet", style="dim"), Text(""))

    def _render_presence(self, device: dict) -> None:
        """Draw the device sparkline and uptime summary."""
        rows = self.engine.presence_for(self.mac, hours=168)
        samples = sum(int(row.get("samples") or 0) for row in rows)
        online = sum(int(row.get("online") or 0) for row in rows)
        uptime = (100.0 * online / samples) if samples else 0.0
        values = [
            (100.0 * int(row.get("online") or 0) / int(row["samples"]))
            if int(row.get("samples") or 0)
            else 0.0
            for row in rows
        ]
        self.query_one("#detail-spark", Sparkline).data = values or [0.0]
        table = RichTable.grid(padding=(0, 2))
        table.add_column(style="dim")
        table.add_column()
        table.add_row("Uptime", Text(f"{uptime:.1f}%", style="bold #34d399" if uptime >= 90 else "bold #fbbf24"))
        table.add_row("Samples", Text(f"{samples:,}"))
        table.add_row("Online samples", Text(f"{online:,}"))
        table.add_row("Buckets", Text(str(len(rows))))
        table.add_row("Window", Text("last 7 days"))
        self.query_one("#detail-presence-summary", Static).update(
            Group(Text("Presence", style="bold #22d3ee"), Text(""), table)
        )
        missing = "No presence samples recorded yet. Run a scan to begin tracking."
        if rows:
            last = rows[-1]
            missing = f"Latest bucket {last.get('bucket')} · {int(last.get('online') or 0)}/{int(last.get('samples') or 0)} samples online."
        self.query_one("#detail-presence-note", Static).update(Text("\n" + missing, style="dim italic"))

    def _render_sessions(self) -> None:
        """Fill the session history table."""
        table = self.query_one("#detail-sessions", DataTable)
        table.clear()
        sessions = self.engine.sessions_for(self.mac, limit=100)
        for session in sessions:
            table.add_row(
                session.get("start") or "—",
                session.get("end") or "—",
                session.get("duration") or "—",
                str(session.get("ip") or "—"),
                key=f"session-{session.get('id')}",
            )
        if not sessions:
            table.add_row("—", "—", "—", "No sessions recorded", key="none")

    def _update_buttons(self, device: dict) -> None:
        """Reflect favourite/archive state on the action buttons."""
        fav = self.query_one("#detail-fav", Button)
        fav.label = "Unfavourite  f" if int(device.get("favorite") or 0) else "Favourite  f"
        archive = self.query_one("#detail-archive", Button)
        archive.label = "Unarchive  a" if int(device.get("archived") or 0) else "Archive  a"

    # ------------------------------------------------------------------ actions
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle detail actions."""
        button = event.button.id or ""
        if button in {"detail-close", "detail-close-2"}:
            self.dismiss(None)
        elif button == "detail-edit":
            self.action_edit()
        elif button == "detail-wake":
            self.action_wake()
        elif button == "detail-fav":
            self.action_favorite()
        elif button == "detail-archive":
            self.action_archive()
        elif button == "detail-delete":
            self.action_delete()
        elif button == "tool-ping":
            self._run_tool("ping")
        elif button == "tool-nmap":
            self._run_tool("nmap")
        elif button == "tool-trace":
            self._run_tool("traceroute")

    def action_close(self) -> None:
        """Close the detail modal."""
        self.dismiss(None)

    def action_edit(self) -> None:
        """Open the edit form."""
        self.app.push_screen(EditDeviceModal(self.engine, self.device), self._edited)

    def _edited(self, changes: dict | None) -> None:
        """Apply edited fields."""
        if not changes:
            return
        try:
            self.engine.update_device(self.mac, changes)
        except (KeyError, ValueError) as exc:
            self.notify(str(exc), "error")
            return
        self._reload()
        self.notify("Device updated")

    def action_favorite(self) -> None:
        """Toggle the favourite flag."""
        self.engine.toggle_favorite(self.mac)
        self._reload()

    def action_archive(self) -> None:
        """Toggle the archived flag."""
        self.engine.toggle_archive(self.mac)
        self._reload()

    def action_delete(self) -> None:
        """Confirm deletion of the device."""
        self.app.push_screen(
            ConfirmModal(
                "Delete this device?",
                "The device, its presence samples and its sessions are permanently removed.",
                "Delete device",
                danger=True,
            ),
            self._deleted,
        )

    def _deleted(self, confirmed: bool | None) -> None:
        """Delete the device and close the modal."""
        if not confirmed:
            return
        try:
            self.engine.delete_device(self.mac)
        except KeyError:
            pass
        self.dismiss(None)
        self.app.notify("Device deleted", "warning")
        self.app.refresh_sidebar()
        self.app.refresh_current()

    def action_wake(self) -> None:
        """Send a Wake-on-LAN packet in the background."""
        self._wake_worker()

    @work(thread=True, exclusive=True, group="detail-wake")
    def _wake_worker(self) -> None:
        """Send WoL without blocking the UI."""
        try:
            message = self.engine.wake_on_lan(self.mac)
        except (ValueError, RuntimeError, OSError) as exc:
            message = f"Wake-on-LAN failed: {exc}"
            severity = "error"
        else:
            severity = "information"
        self.app.call_from_thread(self._background_notify, message, severity)

    def _run_tool(self, tool: str) -> None:
        """Validate the target and launch a diagnostic."""
        target = str(self.device.get("ip") or "")
        if not target:
            self.notify("This device has no IP address to probe", "warning")
            return
        if tool in {"ping", "traceroute", "nmap"} and not target.replace(".", "").isdigit():
            self.notify("Diagnostics require a numeric IP address", "warning")
            return
        output = self.query_one("#tool-output", RichLog)
        output.write(f"[#22d3ee]→ {tool} {target}[/]")
        self._tool_worker(tool, target)

    @work(thread=True, exclusive=True, group="detail-tool")
    def _tool_worker(self, tool: str, target: str) -> None:
        """Run the diagnostic off the UI thread."""
        try:
            text = self.engine.run_tool(tool, target, mode="fast")
        except (ValueError, RuntimeError) as exc:
            text = f"error: {exc}"
        self.app.call_from_thread(self._append_tool_output, text)

    def _append_tool_output(self, text: str) -> None:
        """Append tool output to the log pane."""
        output = self.query_one("#tool-output", RichLog)
        for line in (text or "(no output)").splitlines():
            output.write(line)
        output.write("[dim]— done —[/]")

    def _background_notify(self, message: str, severity: str = "information") -> None:
        """Show a notification from a worker thread."""
        self.notify(message, severity)
