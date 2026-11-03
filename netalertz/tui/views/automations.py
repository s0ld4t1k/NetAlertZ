"""Automation rules that enrich devices during scans."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, DataTable, Static

from ..modals import ConfirmModal, NewWorkflowModal
from ..widgets import safe
from .base import BaseView


class AutomationsView(BaseView):
    """Manage conditional device-field automations."""

    view_id = "automations"
    nav_title = "Automations"
    nav_subtitle = "rules · triggers · enrichment"

    BINDINGS = [
        ("n", "new_rule", "New"),
        ("t", "toggle_rule", "Toggle"),
        ("d", "delete_rule", "Delete"),
        ("r", "refresh", "Refresh"),
        ("s", "scan", "Scan"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the rules toolbar and table."""
        with Horizontal(classes="toolbar slim"):
            yield Static("", id="workflow-count", classes="toolbar-title")
            yield Button("New rule", id="wf-new", variant="primary")
            yield Button("Enable / disable", id="wf-toggle")
            yield Button("Delete", id="wf-delete", variant="error")
            yield Button("Refresh", id="wf-refresh")
        with Horizontal(classes="subhead"):
            yield Static(
                "[dim]Rules run after discovery and on state changes · they only set fields[/]",
                classes="hint",
            )
        yield DataTable(id="workflow-table", zebra_stripes=True, cursor_type="row")

    def refresh_data(self) -> None:
        """Reload automation rules."""
        rules = self.engine.workflows()
        enabled = sum(1 for rule in rules if int(rule.get("enabled") or 0))
        narrow = self.app.size.width < 130
        if narrow:
            summary = (
                f"[b]{len(rules)}[/] [dim]rules[/]  [dim]·[/]  "
                f"[#34d399]{enabled}[/] [dim]on[/]  [dim]·[/]  "
                f"[#94a3b8]{len(rules) - enabled}[/] [dim]off[/]"
            )
        else:
            summary = (
                f"[b]{len(rules)}[/] [dim]automation rules[/]   [dim]·[/]  "
                f"[#34d399]{enabled}[/] [dim]enabled[/]   [dim]·[/]  "
                f"[#94a3b8]{len(rules) - enabled}[/] [dim]paused[/]"
            )
        self.query_one("#workflow-count", Static).update(summary)
        table = self.query_one("#workflow-table", DataTable)
        table.clear(columns=True)
        table.add_column("State", width=9)
        table.add_column("Rule", width=19 if narrow else 22)
        table.add_column("Trigger", width=9 if narrow else 11)
        table.add_column("Condition", width=21 if narrow else 26)
        table.add_column("Action", width=20 if narrow else 22)
        for rule in rules:
            is_on = int(rule.get("enabled") or 0)
            condition = f"{rule.get('field')} {str(rule.get('operator') or '').replace('_', ' ')} {rule.get('value') or ''}".strip()
            action = f"{rule.get('action_field')} = {rule.get('action_value') or '∅'}"
            table.add_row(
                Text("● ON" if is_on else "○ PAUSED", style="bold #34d399" if is_on else "dim"),
                safe(rule.get("name") or "Untitled"),
                Text(str(rule.get("trigger") or ""), style="#7dd3fc"),
                safe(condition),
                safe(action),
                key=str(rule.get("id")),
            )
        if not rules:
            table.add_row(
                Text("—", style="dim"),
                Text("No automations yet", style="bold"),
                Text(""),
                Text("Press n to create your first rule", style="dim"),
                Text(""),
                key="empty",
            )

    def _selected_id(self) -> int | None:
        """Return the highlighted workflow id."""
        table = self.query_one("#workflow-table", DataTable)
        if table.cursor_row < 0 or table.row_count == 0:
            return None
        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            return int(str(key))
        except (ValueError, TypeError):
            return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle workflow actions."""
        handlers = {
            "wf-new": self.action_new_rule,
            "wf-toggle": self.action_toggle_rule,
            "wf-delete": self.action_delete_rule,
            "wf-refresh": self.action_refresh,
        }
        handler = handlers.get(event.button.id or "")
        if handler:
            handler()

    def action_new_rule(self) -> None:
        """Open the rule builder."""
        self.app.push_screen(NewWorkflowModal(), self._created)

    def _created(self, payload: dict | None) -> None:
        """Persist a new rule."""
        if not payload:
            return
        try:
            self.engine.add_workflow(**payload)
        except (ValueError, KeyError) as exc:
            self.notify(str(exc), "error")
            return
        self.refresh_data()
        self.app.refresh_sidebar()
        self.notify("Automation created")

    def action_toggle_rule(self) -> None:
        """Enable or pause the highlighted rule."""
        workflow_id = self._selected_id()
        if workflow_id is None:
            self.notify("Select a rule first", "warning")
            return
        self.engine.toggle_workflow(workflow_id)
        self.refresh_data()
        self.app.refresh_sidebar()

    def action_delete_rule(self) -> None:
        """Delete the highlighted rule after confirmation."""
        workflow_id = self._selected_id()
        if workflow_id is None:
            self.notify("Select a rule first", "warning")
            return
        self.app.push_screen(
            ConfirmModal(
                "Delete automation?",
                "The rule will stop running immediately. Existing device data is untouched.",
                "Delete rule",
                danger=True,
            ),
            lambda confirmed: self._delete(confirmed, workflow_id),
        )

    def _delete(self, confirmed: bool | None, workflow_id: int) -> None:
        """Delete a confirmed workflow."""
        if not confirmed:
            return
        self.engine.delete_workflow(workflow_id)
        self.refresh_data()
        self.app.refresh_sidebar()
        self.notify("Automation deleted")

    def action_refresh(self) -> None:
        """Reload rules."""
        self.refresh_data()

    def action_scan(self) -> None:
        """Start discovery."""
        self.app.start_scan()
