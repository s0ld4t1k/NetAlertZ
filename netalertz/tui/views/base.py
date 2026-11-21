"""Shared view scaffolding and small rendering helpers."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical

from ...engine import Engine
from ..widgets import STATUS_COLORS, STATUS_GLYPHS, safe


def panel(title: str, note: str = "", classes: str = "") -> ComposeResult:
    """Yield a consistent panel heading (used inside panels)."""
    markup = f"[b]{safe(title)}[/]"
    if note:
        markup += f"  [dim]{safe(note)}[/]"
    from textual.widgets import Static

    yield Static(markup, classes=f"panel-title {classes}".strip())


def table_cursor_key(table) -> str | None:
    """Return the row key under the cursor of a DataTable, if any."""
    if table.row_count == 0:
        return None
    try:
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
    except Exception:
        return None
    return None if key is None else str(key)


def restore_table_cursor(table, key: str | None) -> None:
    """Move the cursor back onto a row key after the table was rebuilt."""
    if not key:
        return
    try:
        table.move_cursor(row=table.get_row_index(key))
    except Exception:
        # The row disappeared; keep the default cursor position.
        pass


def status_cell(device: dict, label: bool = True) -> Text:
    """Render a coloured status value for tables."""
    status = str(device.get("status") or "offline")
    color = STATUS_COLORS.get(status, "#94a3b8")
    glyph = STATUS_GLYPHS.get(status, "○")
    text = Text(f"{glyph} ", style=f"bold {color}")
    if label:
        text.append(status.title(), style=color)
    return text


def device_title(device: dict) -> str:
    """Return a compact human identity for a device."""
    return str(device.get("name") or device.get("mac") or "unknown")


def device_meta(device: dict) -> str:
    """Return the secondary identity line (IP · MAC · vendor)."""
    parts = [device.get("ip") or "no ip"]
    if device.get("mac"):
        parts.append(str(device["mac"]))
    if device.get("vendor"):
        parts.append(str(device["vendor"]))
    return "  ·  ".join(parts)


class BaseView(Vertical):
    """Base class for content views mounted inside the content switcher."""

    view_id = ""
    nav_title = ""
    nav_subtitle = ""
    auto_refresh = True

    def __init__(self, engine: Engine) -> None:
        super().__init__(id=f"view-{self.view_id}", classes="view")
        self.engine = engine

    def on_mount(self) -> None:
        """Load data the first time the view is mounted."""
        self.refresh_data()

    def refresh_view(self) -> None:
        """Refresh data when the view becomes visible."""
        if self.is_mounted:
            self.refresh_data()

    def refresh_data(self) -> None:
        """Override in subclasses to reload data."""

    def notify(self, message: str, severity: str = "information") -> None:
        """Show an app notification."""
        self.app.notify(message, severity=severity)

    def focus_search(self, selector: str) -> None:
        """Focus a search field and select its contents."""
        from textual.widgets import Input

        field = self.query_one(selector, Input)
        field.focus()
        field.action_select_all()
