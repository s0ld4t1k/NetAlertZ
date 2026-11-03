"""Settings editor, data paths and import/export tools."""

from __future__ import annotations

from pathlib import Path

from rich.console import Group
from rich.table import Table as RichTable
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static

from ...config import SETTING_META, VERSION, home, log_path
from ...utils import human_bytes
from ..modals import ConfirmModal, EditSettingModal, PromptModal
from ..widgets import safe
from .base import BaseView

GROUP_ORDER = ["Scanning", "Alerts", "Integrations", "Data", "Interface"]


class SettingsView(BaseView):
    """Edit every persisted setting from one place."""

    view_id = "settings"
    nav_title = "Settings"
    nav_subtitle = "scanner · alerts · data · interface"

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the settings table and data panel."""
        with Horizontal(classes="toolbar slim"):
            yield Input(placeholder="Filter settings…", id="setting-search", classes="search-input")
            yield Button("Edit", id="setting-edit", variant="primary")
            yield Button("Reset", id="setting-reset")
            yield Button("Export", id="setting-export")
            yield Button("Import", id="setting-import")
        with Horizontal(id="settings-body"):
            with Vertical(classes="panel", id="settings-table-panel"):
                yield Static("[b]Configuration[/]  [dim]Enter edits the highlighted row[/]", classes="panel-title")
                yield DataTable(id="setting-table", zebra_stripes=True, cursor_type="row")
                yield Static("", id="setting-desc")
            with Vertical(classes="panel", id="settings-info-panel"):
                yield Static("[b]Storage & runtime[/]  [dim]local, no services[/]", classes="panel-title")
                yield Static("", id="setting-info")

    def refresh_data(self) -> None:
        """Reload settings rows and runtime information."""
        needle = self.query_one("#setting-search", Input).value.strip().lower()
        narrow = self.app.size.width < 136
        info_panel = self.query_one("#settings-info-panel")
        info_panel.styles.width = 34 if narrow else 42
        table = self.query_one("#setting-table", DataTable)
        table.clear(columns=True)
        if not narrow:
            table.add_column("Group", width=14)
        table.add_column("Setting", width=26 if narrow else 22)
        table.add_column("Value", width=20 if narrow else 18)
        for group in GROUP_ORDER:
            items = [
                (key, meta)
                for key, meta in SETTING_META.items()
                if meta.get("group", "General") == group
            ]
            for key, meta in items:
                haystack = f"{key} {meta.get('label', '')} {meta.get('help', '')} {group}".lower()
                if needle and needle not in haystack:
                    continue
                value = self.engine.settings.get(key)
                cells = [
                    Text(str(meta.get("label") or key), style="bold"),
                    Text(self._display(key, meta, value), style="#7dd3fc"),
                ]
                if not narrow:
                    cells.insert(0, Text(group, style="dim"))
                table.add_row(*cells, key=key)

        db_path = Path(self.engine.db.path)
        size = human_bytes(db_path.stat().st_size) if db_path.exists() else "0 B"
        info = RichTable.grid(padding=(0, 2))
        info.add_column(style="dim")
        info.add_column()
        info.add_row("Version", Text(f"NetAlertZ {VERSION}", style="bold #22d3ee"))
        info.add_row("Data folder", Text(str(home())))
        info.add_row("Database", Text(str(db_path)))
        info.add_row("DB size", Text(size))
        info.add_row("File log", Text(str(log_path())))
        info.add_row("Devices", Text(str(self.engine.counts().get("total", 0))))
        info.add_row("Scan method", Text(self.engine.scanner.effective_method()))
        info.add_row("Targets", Text(", ".join(self.engine.scanner.plan_targets()) or "auto"))
        info.add_row("Delivery", Text("in-app only" if self.engine.settings.get_bool("in_app_only") else "webhook / Telegram"))
        note = Text(
            "\nEverything is stored in one SQLite file.\n"
            "No Docker, daemon or external service is required.\n"
            "Back up the database by copying the file.",
            style="dim italic",
        )
        self.query_one("#setting-info", Static).update(Group(info, note))
        self._update_desc()

    def _update_desc(self, key: str | None = None) -> None:
        """Show the help text for the highlighted setting."""
        if key is None:
            key = self._selected_key()
        meta = SETTING_META.get(key or "", {})
        label = str(meta.get("label") or key or "")
        help_text = str(meta.get("help") or "Select a setting to see what it controls.")
        self.query_one("#setting-desc", Static).update(
            f"[b]{safe(label)}[/]  [dim]{safe(help_text)}[/]"
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update the description when the cursor moves."""
        if event.data_table.id == "setting-table":
            self._update_desc(str(event.row_key.value or ""))

    def _display(self, key: str, meta: dict, value) -> str:
        """Render a setting value for the table."""
        kind = meta.get("type", "str")
        if kind == "bool":
            return "enabled" if value else "disabled"
        if kind == "secret":
            return "•••••• set" if value else "not set"
        if kind == "choice":
            return str(value or "—")
        suffix = meta.get("suffix")
        return f"{value}{' ' + suffix if suffix else ''}"

    def _selected_key(self) -> str | None:
        """Return the highlighted setting key."""
        table = self.query_one("#setting-table", DataTable)
        if table.cursor_row < 0 or table.row_count == 0:
            return None
        try:
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        except Exception:
            return None

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter settings live."""
        if event.input.id == "setting-search":
            self.refresh_data()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the editor for the selected setting."""
        key = str(event.row_key.value or "")
        if key:
            self._edit(key)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle settings actions."""
        handlers = {
            "setting-edit": self.action_edit_selected,
            "setting-reset": self._reset,
            "setting-export": self._export,
            "setting-import": self._import,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            handler()

    def _edit(self, key: str) -> None:
        """Push the editor modal for one setting."""
        meta = SETTING_META.get(key, {})
        value = self.engine.settings.get(key)
        self.app.push_screen(EditSettingModal(key, meta, value), lambda result: self._saved(result))

    def _saved(self, result: dict | None) -> None:
        """Persist an edited setting."""
        if not result:
            return
        key, value = result["key"], result["value"]
        self.engine.set_setting(key, value)
        if key == "theme":
            self.app.apply_theme(str(value))
        if key == "show_macs":
            self.app.refresh_sidebar()
        self.refresh_data()
        self.notify(f"Updated {SETTING_META.get(key, {}).get('label', key)}")

    def action_edit_selected(self) -> None:
        """Edit the highlighted setting."""
        key = self._selected_key()
        if key is None:
            self.notify("Select a setting first", "warning")
            return
        self._edit(key)

    def action_focus_search(self) -> None:
        """Focus the settings filter."""
        self.focus_search("#setting-search")

    def _reset(self) -> None:
        """Confirm and restore defaults."""
        self.app.push_screen(
            ConfirmModal(
                "Reset all settings?",
                "Every setting returns to its default value. Devices and history are untouched.",
                "Reset settings",
                danger=True,
            ),
            self._reset_done,
        )

    def _reset_done(self, confirmed: bool | None) -> None:
        """Restore defaults after confirmation."""
        if not confirmed:
            return
        self.engine.settings.reset()
        self.app.apply_theme(str(self.engine.settings.get("theme")))
        self.refresh_data()
        self.notify("Settings restored to defaults", "warning")

    def _export(self) -> None:
        """Export devices to CSV."""
        try:
            path = self.engine.export_csv()
        except OSError as exc:
            self.notify(f"Export failed: {exc}", "error")
            return
        self.notify(f"Exported to {path}")

    def _import(self) -> None:
        """Ask for a CSV path and import devices."""
        self.app.push_screen(
            PromptModal(
                "Import devices",
                "CSV file path",
                default=str(home() / "devices.csv"),
                hint="Supports NetAlertX-style columns such as devMac, devName and devLastIP.",
            ),
            self._imported,
        )

    def _imported(self, path: str | None) -> None:
        """Run the CSV import."""
        if not path:
            return
        try:
            created, updated = self.engine.import_csv(path)
        except (OSError, ValueError) as exc:
            self.notify(f"Import failed: {exc}", "error")
            return
        self.refresh_data()
        self.app.refresh_sidebar()
        self.notify(f"Imported {created} new, updated {updated}")
