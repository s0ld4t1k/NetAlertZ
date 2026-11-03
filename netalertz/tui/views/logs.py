"""Application log viewer with level filters."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, RichLog, Select, Static

from ...config import home, log_path
from ...utils import local_ts
from ..modals import ConfirmModal
from ..widgets import LEVEL_COLORS, safe
from .base import BaseView

LEVELS = [
    ("All levels", "ALL"),
    ("Debug", "DEBUG"),
    ("Info and above", "INFO"),
    ("Warning", "WARN"),
    ("Error", "ERROR"),
]


class LogsView(BaseView):
    """Tail of the database log plus file location hints."""

    view_id = "logs"
    nav_title = "Logs"
    nav_subtitle = "runtime log · diagnostics"

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("f", "toggle_follow", "Follow"),
        ("r", "refresh", "Refresh"),
        ("s", "scan", "Scan"),
    ]

    def compose(self) -> ComposeResult:
        """Compose log filters and output."""
        with Horizontal(classes="toolbar slim"):
            yield Select(LEVELS, value="INFO", allow_blank=False, id="log-level")
            yield Input(placeholder="Filter messages…", id="log-search", classes="search-input")
            yield Button("Following", id="log-follow", variant="primary")
            yield Button("Clear log", id="log-clear", variant="error")
        with Horizontal(classes="subhead"):
            yield Static("", id="log-count", classes="count-label")
            yield Static(
                f"[dim]file: {safe(str(log_path()))}  ·  data: {safe(str(home()))}[/]",
                classes="hint",
            )
        yield RichLog(id="log-output", wrap=True, highlight=False, markup=True, max_lines=4000)

    def on_mount(self) -> None:
        """Initialise the follow state."""
        self._follow = True
        self._search_timer = None
        super().on_mount()

    def refresh_data(self) -> None:
        """Reload log rows and redraw the output pane."""
        level = str(self.query_one("#log-level", Select).value or "INFO")
        needle = self.query_one("#log-search", Input).value.strip()
        clauses = []
        params: list[str] = []
        if level != "ALL":
            if level == "INFO":
                clauses.append("level IN ('INFO','WARN','ERROR')")
            else:
                clauses.append("level=?")
                params.append(level)
        if needle:
            clauses.append("message LIKE ?")
            params.append(f"%{needle}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.engine.db.q(
            f"SELECT * FROM logs {where} ORDER BY id DESC LIMIT 500", tuple(params)
        )
        rows.reverse()
        self.query_one("#log-count", Static).update(
            f"[b]{len(rows)}[/] [dim]lines shown[/]   [dim]·[/]  level filter [b]{safe(level)}[/]"
        )
        output = self.query_one("#log-output", RichLog)
        output.clear()
        for row in rows:
            color = LEVEL_COLORS.get(str(row.get("level")), "#94a3b8")
            output.write(
                f"[dim]{local_ts(row.get('created_at'))}[/] "
                f"[{color}]{str(row.get('level') or 'INFO'):<5}[/] "
                f"{safe(row.get('message') or '')}"
            )
        if not rows:
            output.write("[dim]No log lines match the current filter.[/]")
        if self._follow:
            output.scroll_end(animate=False)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce the message filter."""
        if event.input.id != "log-search":
            return
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.18, self.refresh_data)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Refresh when the level filter changes."""
        if event.select.id == "log-level":
            self.refresh_data()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle log actions."""
        if event.button.id == "log-follow":
            self.action_toggle_follow()
        elif event.button.id == "log-clear":
            self.app.push_screen(
                ConfirmModal(
                    "Clear the log?",
                    "Database log entries are removed. The file log on disk is kept.",
                    "Clear log",
                    danger=True,
                ),
                self._cleared,
            )

    def _cleared(self, confirmed: bool | None) -> None:
        """Clear database log rows."""
        if not confirmed:
            return
        self.engine.db.x("DELETE FROM logs")
        self.refresh_data()
        self.notify("Database log cleared", "warning")

    def action_toggle_follow(self) -> None:
        """Toggle auto-scrolling."""
        self._follow = not self._follow
        button = self.query_one("#log-follow", Button)
        button.label = "Following" if self._follow else "Paused"
        button.variant = "primary" if self._follow else "default"
        self.refresh_data()

    def action_focus_search(self) -> None:
        """Focus the message filter."""
        self.focus_search("#log-search")

    def action_refresh(self) -> None:
        """Reload the log tail."""
        self.refresh_data()

    def action_scan(self) -> None:
        """Start discovery."""
        self.app.start_scan()
