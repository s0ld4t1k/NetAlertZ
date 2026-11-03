"""Devices inventory with search, filters and manual creation."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Select, Static

from ..modals import NewDeviceModal
from ..widgets import safe
from .base import BaseView, status_cell

STATUS_OPTIONS = [
    ("All active devices", "active"),
    ("Online", "online"),
    ("Offline", "offline"),
    ("Down", "down"),
    ("Sleeping", "sleeping"),
    ("New devices", "new"),
    ("Favourites", "favorites"),
    ("Archived", "archived"),
    ("Everything", "all"),
]


class DevicesView(BaseView):
    """Searchable device inventory."""

    view_id = "devices"
    nav_title = "Devices"
    nav_subtitle = "inventory · identity · ownership"

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("n", "new_device", "New"),
        ("e", "export", "Export"),
        ("s", "scan", "Scan"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the toolbar, counters and table."""
        with Horizontal(classes="toolbar"):
            yield Input(
                placeholder="Search name, IP, MAC, vendor, owner, group…",
                id="device-search",
                classes="search-input",
            )
            yield Select(STATUS_OPTIONS, value="active", allow_blank=False, id="device-status")
            yield Button("Add", id="device-add")
            yield Button("Export", id="device-export")
            yield Button("Scan", id="device-scan", variant="primary")
        with Horizontal(classes="subhead"):
            yield Static("", id="device-count", classes="count-label")
            yield Static(
                "[dim]Enter opens details  ·  [b]/[/] search  ·  [b]n[/] new device  ·  [b]e[/] export[/]",
                classes="hint",
            )
        yield DataTable(id="device-table", zebra_stripes=True, cursor_type="row")

    def on_mount(self) -> None:
        """Load the initial inventory."""
        self._search_timer = None
        super().on_mount()

    def refresh_data(self) -> None:
        """Rebuild the table from the current filter state."""
        search = self.query_one("#device-search", Input).value
        status = self.query_one("#device-status", Select).value
        status = "active" if status in (Select.BLANK, None) else str(status)
        devices = self.engine.list_devices(search=search, status=status, limit=4000)
        counts = self.engine.counts()
        label = {
            "active": "active devices",
            "all": "devices",
            "online": "online devices",
            "offline": "offline devices",
            "down": "down devices",
            "sleeping": "sleeping devices",
            "new": "new devices",
            "favorites": "favourite devices",
            "archived": "archived devices",
        }.get(status, "devices")
        self.query_one("#device-count", Static).update(
            f"[b]{len(devices)}[/] [dim]{safe(label)}[/]"
            f"   [dim]·[/]  [b]{counts.get('online', 0)}[/] [dim]online[/]"
            f"   [dim]·[/]  [#fb7185]{counts.get('down', 0)}[/] [dim]down[/]"
        )

        table = self.query_one("#device-table", DataTable)
        table.clear(columns=True)
        show_macs = self.engine.settings.get_bool("show_macs")
        compact = self.app.size.width < 138
        table.add_column("State", width=10)
        table.add_column("Name", width=22 if compact else 17)
        table.add_column("IP address", width=15)
        if show_macs and not compact:
            table.add_column("MAC", width=17)
        if not compact:
            table.add_column("Vendor", width=12)
        table.add_column("Type", width=12)
        table.add_column("Last seen", width=10)

        for device in devices:
            name = Text()
            if int(device.get("favorite") or 0):
                name.append("★ ", style="#fbbf24")
            name.append(str(device.get("name") or device.get("mac")))
            if int(device.get("is_new") or 0):
                name.append("  NEW", style="bold #22d3ee")
            if int(device.get("archived") or 0):
                name.stylize("dim")
            cells = [
                status_cell(device),
                name,
                Text(str(device.get("ip") or "—"), style="#7dd3fc"),
            ]
            if show_macs and not compact:
                cells.append(Text(str(device.get("mac") or "—"), style="dim"))
            if not compact:
                cells.append(safe(device.get("vendor") or "—"))
            cells.extend(
                [
                    safe(device.get("type") or "—"),
                    Text(str(device.get("last_seen_human") or "never"), style="dim"),
                ]
            )
            table.add_row(*cells, key=str(device["mac"]))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce search input updates."""
        if event.input.id != "device-search":
            return
        if self._search_timer is not None:
            self._search_timer.stop()
        self._search_timer = self.set_timer(0.18, self.refresh_data)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Refresh when the status filter changes."""
        if event.select.id == "device-status":
            self.refresh_data()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected device."""
        self.app.open_device(str(event.row_key.value or ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle toolbar buttons."""
        handlers = {
            "device-add": self.action_new_device,
            "device-export": self.action_export,
            "device-scan": self.action_scan,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            handler()

    def action_focus_search(self) -> None:
        """Focus the search box."""
        self.focus_search("#device-search")

    def action_new_device(self) -> None:
        """Open the create-device dialog."""
        self.app.push_screen(NewDeviceModal(), self._created)

    def _created(self, result: dict | None) -> None:
        """Persist a newly created device."""
        if not result:
            return
        try:
            mac = self.engine.create_device(**result)
        except (ValueError, KeyError) as exc:
            self.notify(str(exc), "error")
            return
        self.notify(f"Device created · {mac}", "information")
        self.refresh_data()
        self.app.refresh_sidebar()

    def action_export(self) -> None:
        """Export the inventory to CSV."""
        try:
            path = self.engine.export_csv()
        except OSError as exc:
            self.notify(f"Export failed: {exc}", "error")
            return
        self.notify(f"Exported to {path}", "information")

    def action_scan(self) -> None:
        """Start a discovery scan."""
        self.app.start_scan()

    def action_refresh(self) -> None:
        """Reload the device list."""
        self.refresh_data()
        self.notify("Devices refreshed")
