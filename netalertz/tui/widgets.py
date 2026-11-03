"""Reusable TUI widgets: navigation rows, stat cards and status helpers."""

from __future__ import annotations

from datetime import datetime

from rich.markup import escape
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Label, Select, Static, Switch, TextArea

STATUS_COLORS = {
    "online": "#34d399",
    "offline": "#94a3b8",
    "down": "#fb7185",
    "sleeping": "#fbbf24",
    "archived": "#a78bfa",
    "new": "#22d3ee",
    "ok": "#34d399",
    "error": "#fb7185",
    "running": "#22d3ee",
}

LEVEL_COLORS = {
    "alert": "#fb7185",
    "warn": "#fbbf24",
    "success": "#34d399",
    "info": "#7dd3fc",
    "ERROR": "#fb7185",
    "WARN": "#fbbf24",
    "INFO": "#7dd3fc",
    "DEBUG": "#64748b",
}

STATUS_GLYPHS = {
    "online": "●",
    "offline": "○",
    "down": "▼",
    "sleeping": "◐",
    "archived": "▣",
}


def safe(value: object) -> str:
    """Escape text for Rich markup."""
    return escape(str(value if value is not None else ""))


def status_text(row: dict, with_label: bool = True) -> Text:
    """Build a coloured status indicator for a device row."""
    status = str(row.get("status") or "offline")
    color = STATUS_COLORS.get(status, "#94a3b8")
    glyph = STATUS_GLYPHS.get(status, "○")
    text = Text()
    text.append(f"{glyph} ", style=f"bold {color}")
    if with_label:
        text.append(status.title(), style=color)
    return text


def event_text(event_type: str) -> Text:
    """Colour an event type label."""
    colors = {
        "New Device": "#22d3ee",
        "Connected": "#34d399",
        "Device Up": "#34d399",
        "Disconnected": "#94a3b8",
        "Device Down": "#fb7185",
        "Sleeping": "#fbbf24",
        "Device Deleted": "#fb7185",
        "Device Added": "#a78bfa",
        "Wake-on-LAN": "#a78bfa",
        "Settings": "#94a3b8",
        "Workflow": "#a78bfa",
    }
    return Text(event_type, style=colors.get(event_type, "#cbd5e1"))


def clock_parts() -> tuple[str, str]:
    """Return the current local time and date strings."""
    now = datetime.now()
    return now.strftime("%H:%M:%S"), now.strftime("%a %d %b")


class NavItem(Horizontal):
    """Clickable sidebar navigation row with an optional count."""

    class Selected(Message):
        """Posted when the row is activated."""

        def __init__(self, nav_id: str) -> None:
            super().__init__()
            self.nav_id = nav_id

    def __init__(self, nav_id: str, icon: str, label: str, hotkey: str = "") -> None:
        super().__init__(id=f"nav-{nav_id}", classes="nav-item")
        self.nav_id = nav_id
        self.icon = icon
        self.label = label
        self.hotkey = hotkey

    def compose(self) -> ComposeResult:
        """Compose the icon/label and count columns."""
        yield Static(f"{self.icon}  {self.label}", classes="nav-label")
        yield Static("", classes="nav-count")

    def on_click(self) -> None:
        """Activate the row on click."""
        self.post_message(self.Selected(self.nav_id))

    def set_count(self, count: int | None, tone: str = "") -> None:
        """Update the right-hand badge."""
        widget = self.query_one(".nav-count", Static)
        widget.update(str(count) if count else "")
        widget.set_classes(f"nav-count {tone}".strip())

    def set_active(self, active: bool) -> None:
        """Toggle the active highlight."""
        self.set_class(active, "active")

    def set_compact(self, compact: bool) -> None:
        """Collapse the sidebar row to its icon."""
        self.set_class(compact, "compact")
        try:
            label = self.query_one(".nav-label", Static)
        except Exception:
            return
        label.update(self.icon if compact else f"{self.icon}  {self.label}")


class StatCard(Vertical):
    """Compact KPI card used on the dashboard."""

    def __init__(
        self,
        label: str,
        value: str = "0",
        note: str = "",
        tone: str = "primary",
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=f"stat-card tone-{tone}")
        self.initial_label = label
        self.initial_value = value
        self.initial_note = note

    def compose(self) -> ComposeResult:
        """Compose label, value and footnote."""
        yield Static(self.initial_label, classes="stat-label")
        yield Static(self.initial_value, classes="stat-value")
        yield Static(self.initial_note, classes="stat-note")

    def update_stat(self, value: str | int, note: str | None = None) -> None:
        """Update the displayed value and optional note."""
        self.query_one(".stat-value", Static).update(str(value))
        if note is not None:
            self.query_one(".stat-note", Static).update(note)


class TopBar(Horizontal):
    """Application header: brand, active view, network state and clock."""

    def compose(self) -> ComposeResult:
        """Compose the header sections."""
        yield Static("◆ NETALERTZ", id="top-brand")
        with Vertical(id="top-title-block"):
            yield Static("Dashboard", id="top-view")
            yield Static("network intelligence", id="top-sub")
        yield Static("", id="top-spacer")
        with Vertical(id="top-meta"):
            yield Static("", id="top-network")
            yield Static("", id="top-scan")
        with Vertical(id="top-clock-block"):
            yield Static("", id="top-clock")
            yield Static("", id="top-date")

    def update_view(self, title: str, subtitle: str) -> None:
        """Set the active view title and subtitle."""
        self.query_one("#top-view", Static).update(title)
        self.query_one("#top-sub", Static).update(subtitle)

    def update_meta(self, network: str, scan_line: str, clock: str, date: str) -> None:
        """Update network, scan and clock labels."""
        self.query_one("#top-network", Static).update(network)
        self.query_one("#top-scan", Static).update(scan_line)
        self.update_clock(clock, date)

    def update_clock(self, clock: str, date: str) -> None:
        """Update just the clock labels (called once a second)."""
        self.query_one("#top-clock", Static).update(clock)
        self.query_one("#top-date", Static).update(date)


class Sidebar(Vertical):
    """Persistent navigation rail with live counters."""

    def compose(self) -> ComposeResult:
        """Compose navigation groups and the live network summary."""
        yield Static("MONITOR", classes="side-heading")
        yield NavItem("dashboard", "◈", "Dashboard", "1")
        yield NavItem("devices", "▤", "Devices", "2")
        yield NavItem("events", "≡", "Events", "3")
        yield NavItem("presence", "▦", "Presence", "4")
        yield NavItem("network", "⌘", "Network tree", "5")
        yield Static("OPERATIONS", classes="side-heading")
        yield NavItem("scanners", "◎", "Scanners", "6")
        yield NavItem("automations", "⚙", "Automations", "7")
        yield Static("SYSTEM", classes="side-heading")
        yield NavItem("notifications", "◆", "Alerts", "8")
        yield NavItem("settings", "⚒", "Settings", "9")
        yield NavItem("logs", "▥", "Logs", "l")
        yield NavItem("help", "?", "Help", "?")
        yield Static("", id="sidebar-spacer")
        yield Static("", id="sidebar-status")


class FooterBar(Horizontal):
    """Bottom hint bar."""

    def compose(self) -> ComposeResult:
        """Compose hints and app metadata."""
        yield Static(
            "[b]1-9[/] navigate  [b]s[/] scan  [b]r[/] refresh  [b]F2[/] theme  [b]?[/] help  [b]ctrl+q[/] quit",
            id="footer-hints",
        )
        yield Static("", id="footer-meta")


class FormRow(Horizontal):
    """Horizontal label + control row used by form modals."""

    def __init__(self, label: str, control, hint: str = "") -> None:
        super().__init__(classes="form-row")
        self.control = control
        self.label_text = label
        self.hint = hint

    def compose(self) -> ComposeResult:
        """Compose the label and control."""
        with Vertical(classes="form-label-col"):
            yield Label(self.label_text, classes="field-label")
            if self.hint:
                yield Static(self.hint, classes="field-hint")
        yield self.control


class SwitchRow(Horizontal):
    """A labelled switch."""

    def __init__(self, label: str, switch: Switch, hint: str = "") -> None:
        super().__init__(classes="switch-row")
        self.label_text = label
        self.switch = switch
        self.hint = hint

    def compose(self) -> ComposeResult:
        """Compose label, hint and switch."""
        with Vertical(classes="form-label-col"):
            yield Label(self.label_text, classes="field-label")
            if self.hint:
                yield Static(self.hint, classes="field-hint")
        yield Static("", classes="switch-spacer")
        yield self.switch


class ModalShell(VerticalScroll):
    """Scrollable card container for modal dialogs."""

    pass


class TextAreaField(TextArea):
    """TextArea with a stable default height for forms."""

    def __init__(self, text: str = "", **kwargs) -> None:
        kwargs.setdefault("soft_wrap", True)
        super().__init__(text, **kwargs)


__all__ = [
    "Button",
    "FooterBar",
    "FormRow",
    "Input",
    "LEVEL_COLORS",
    "Label",
    "ModalShell",
    "NavItem",
    "Select",
    "Sidebar",
    "StatCard",
    "STATUS_COLORS",
    "STATUS_GLYPHS",
    "Switch",
    "SwitchRow",
    "TextArea",
    "TextAreaField",
    "TopBar",
    "clock_parts",
    "event_text",
    "safe",
    "status_text",
]
