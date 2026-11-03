"""Event stream with type filters and retention controls."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Input, Select, Static

from ..modals import ConfirmModal, PromptModal
from ..widgets import event_text, safe
from .base import BaseView


class EventsView(BaseView):
    """Chronological network event log."""

    view_id = "events"
    nav_title = "Events"
    nav_subtitle = "activity stream · audit trail"

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("d", "delete_selected", "Delete"),
        ("r", "refresh", "Refresh"),
        ("s", "scan", "Scan"),
    ]

    def compose(self) -> ComposeResult:
        """Compose filters and the event table."""
        with Horizontal(classes="toolbar"):
            yield Input(placeholder="Search events, devices, IPs…", id="event-search", classes="search-input")
            yield Select([("All event types", "all")], value="all", allow_blank=False, id="event-type")
            yield Button("Clear older…", id="event-prune")
            yield Button("Clear all", id="event-clear", variant="error")
        with Horizontal(classes="subhead"):
            yield Static("", id="event-count", classes="count-label")
            yield Static(
                "[dim]Enter opens the related device  ·  [b]/[/] search  ·  [b]d[/] delete selected[/]",
                classes="hint",
            )
        yield DataTable(id="event-table", zebra_stripes=True, cursor_type="row")

    def on_mount(self) -> None:
        """Populate event type options once."""
        self._search_timer = None
        self._event_macs: dict[str, str] = {}
        select = self.query_one("#event-type", Select)
        types = self.engine.event_types()
        options = [("All event types", "all")] + [(item, item) for item in types]
        select.set_options(options)
        super().on_mount()

    def refresh_data(self) -> None:
        """Reload events for the current filters."""
        search = self.query_one("#event-search", Input).value
        event_type = self.query_one("#event-type", Select).value
        event_type = "all" if event_type in (Select.BLANK, None) else str(event_type)
        events = self.engine.list_events(search=search, event_type=event_type, limit=800)
        self.query_one("#event-count", Static).update(
            f"[b]{len(events)}[/] [dim]events[/]   [dim]·[/]  newest first"
        )

        narrow = self.app.size.width < 132
        table = self.query_one("#event-table", DataTable)
        table.clear(columns=True)
        table.add_column("When", width=13)
        table.add_column("Event", width=17)
        table.add_column("Device", width=22)
        if not narrow:
            table.add_column("IP", width=15)
        table.add_column("Detail", width=None)
        self._event_macs = {}
        for event in events:
            key = str(event.get("id"))
            mac = str(event.get("mac") or "")
            self._event_macs[key] = mac
            cells = [
                Text(str(self._local(event.get("created_at"))), style="dim"),
                event_text(str(event.get("type") or "")),
                safe(event.get("device_name") or mac or "system"),
            ]
            if not narrow:
                cells.append(Text(str(event.get("ip") or "—"), style="#7dd3fc"))
            cells.append(safe(str(event.get("info") or "")))
            table.add_row(*cells, key=key)

    @staticmethod
    def _local(value: str | None) -> str:
        """Format an event timestamp."""
        from ...utils import local_ts

        return local_ts(value)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce the search box."""
        if event.input.id != "event-search":
            return
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.18, self.refresh_data)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Refresh when the type filter changes."""
        if event.select.id == "event-type":
            self.refresh_data()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the device behind the event, when there is one."""
        mac = self._event_macs.get(str(event.row_key.value or ""), "")
        if mac:
            self.app.open_device(mac)
        elif mac == "":
            self.notify("This event is not linked to a device", "warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle retention buttons."""
        if event.button.id == "event-prune":
            self.app.push_screen(
                PromptModal(
                    "Clear old events",
                    "Delete events older than",
                    default="30",
                    int_only=True,
                    hint="Days of history to keep. Everything older is removed.",
                ),
                self._prune,
            )
        elif event.button.id == "event-clear":
            self.app.push_screen(
                ConfirmModal(
                    "Clear every event?",
                    "This permanently removes the entire activity stream. Devices are not affected.",
                    "Clear events",
                    danger=True,
                ),
                self._clear,
            )

    def _prune(self, days: int | None) -> None:
        """Delete events older than the chosen number of days."""
        if not days:
            return
        removed = self.engine.clear_events(days)
        self.refresh_data()
        self.app.refresh_sidebar()
        self.notify(f"Removed {removed} event(s)", "information")

    def _clear(self, confirmed: bool | None) -> None:
        """Delete all events after confirmation."""
        if not confirmed:
            return
        removed = self.engine.clear_events(None)
        self.refresh_data()
        self.app.refresh_sidebar()
        self.notify(f"Cleared {removed} event(s)", "warning")

    def action_focus_search(self) -> None:
        """Focus the search box."""
        self.focus_search("#event-search")

    def action_delete_selected(self) -> None:
        """Delete the highlighted event."""
        table = self.query_one("#event-table", DataTable)
        if table.cursor_row < 0:
            return
        try:
            key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        except Exception:
            return
        self.engine.delete_event(int(key))
        self.refresh_data()
        self.notify("Event deleted")

    def action_scan(self) -> None:
        """Start discovery."""
        self.app.start_scan()

    def action_refresh(self) -> None:
        """Reload the stream."""
        self.refresh_data()
        self.notify("Events refreshed")
