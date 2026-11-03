"""In-app notification centre."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Select, Static

from ...utils import local_ts
from ..modals import ConfirmModal
from ..widgets import safe
from .base import BaseView

LEVEL_STYLES = {
    "alert": ("#fb7185", "ALERT"),
    "warn": ("#fbbf24", "WARN"),
    "success": ("#34d399", "OK"),
    "info": ("#7dd3fc", "INFO"),
}


class NotificationsView(BaseView):
    """Read and manage alerts raised by scans and automations."""

    view_id = "notifications"
    nav_title = "Alerts"
    nav_subtitle = "notifications · delivery log"

    BINDINGS = [
        ("m", "mark_all", "Mark all read"),
        ("d", "delete_selected", "Delete"),
        ("r", "refresh", "Refresh"),
        ("s", "scan", "Scan"),
    ]

    def compose(self) -> ComposeResult:
        """Compose filter toolbar and notification table."""
        with Horizontal(classes="toolbar"):
            yield Select(
                [("All notifications", "all"), ("Unread only", "unread")],
                value="all",
                allow_blank=False,
                id="note-filter",
            )
            yield Static("", id="note-count", classes="toolbar-title")
            yield Button("Mark all read", id="note-read-all")
            yield Button("Delete", id="note-delete")
            yield Button("Clear all", id="note-clear", variant="error")
        with Horizontal(classes="subhead"):
            yield Static(
                "[dim]Enter reads · [b]m[/] mark all · [b]d[/] delete · [b]r[/] refresh[/]",
                classes="hint",
            )
        yield DataTable(id="note-table", zebra_stripes=True, cursor_type="row")

    def refresh_data(self) -> None:
        """Reload notifications for the chosen filter."""
        mode = self.query_one("#note-filter", Select).value
        unread_only = mode == "unread"
        notes = self.engine.notifier.list(unread_only=unread_only, limit=600)
        unread = self.engine.notifier.unread_count()
        self.query_one("#note-count", Static).update(
            f"[b]{len(notes)}[/] [dim]shown[/]   [dim]·[/]  "
            f"[#fb7185]{unread}[/] [dim]unread[/]"
        )
        table = self.query_one("#note-table", DataTable)
        table.clear(columns=True)
        table.add_column("", width=2)
        table.add_column("Level", width=7)
        table.add_column("When", width=12)
        table.add_column("Message", width=None)
        for note in notes:
            level = str(note.get("level") or "info")
            color, label = LEVEL_STYLES.get(level, ("#94a3b8", level.upper()))
            table.add_row(
                Text("●" if not int(note.get("read") or 0) else " ", style=f"bold {color}"),
                Text(label, style=f"bold {color}"),
                Text(local_ts(note.get("created_at")), style="dim"),
                Text(safe(str(note.get("content") or "")), style="" if not note.get("read") else "dim"),
                key=str(note.get("id")),
            )
        if not notes:
            table.add_row(
                Text(""),
                Text("—", style="dim"),
                Text(""),
                Text("No notifications. Quiet is good.", style="dim"),
                key="empty",
            )

    def _selected_id(self) -> int | None:
        """Return the selected notification id."""
        table = self.query_one("#note-table", DataTable)
        if table.cursor_row < 0 or table.row_count == 0:
            return None
        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            return int(str(key))
        except (ValueError, TypeError):
            return None

    def on_select_changed(self, event: Select.Changed) -> None:
        """Refresh when the filter changes."""
        if event.select.id == "note-filter":
            self.refresh_data()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Mark the selected notification as read."""
        try:
            note_id = int(str(event.row_key.value))
        except (ValueError, TypeError):
            return
        self.engine.notifier.mark_read(note_id)
        self.refresh_data()
        self.app.refresh_sidebar()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle notification actions."""
        handlers = {
            "note-read-all": self.action_mark_all,
            "note-delete": self.action_delete_selected,
            "note-clear": self._clear_all,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            handler()

    def action_mark_all(self) -> None:
        """Mark every notification as read."""
        self.engine.notifier.mark_all_read()
        self.refresh_data()
        self.app.refresh_sidebar()
        self.notify("All notifications marked as read")

    def action_delete_selected(self) -> None:
        """Delete the highlighted notification."""
        note_id = self._selected_id()
        if note_id is None:
            self.notify("Select a notification first", "warning")
            return
        self.engine.notifier.delete(note_id)
        self.refresh_data()
        self.app.refresh_sidebar()

    def _clear_all(self) -> None:
        """Confirm and clear all notifications."""
        self.app.push_screen(
            ConfirmModal(
                "Clear all notifications?",
                "Every in-app alert will be permanently removed.",
                "Clear alerts",
                danger=True,
            ),
            self._cleared,
        )

    def _cleared(self, confirmed: bool | None) -> None:
        """Clear notifications after confirmation."""
        if not confirmed:
            return
        self.engine.notifier.clear()
        self.refresh_data()
        self.app.refresh_sidebar()
        self.notify("Notification centre cleared", "warning")

    def action_refresh(self) -> None:
        """Reload notifications."""
        self.refresh_data()

    def action_scan(self) -> None:
        """Start discovery."""
        self.app.start_scan()
