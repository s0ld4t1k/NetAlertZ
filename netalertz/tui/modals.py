"""Modal dialogs used across the TUI."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch, TextArea

from ..engine import OPERATORS, WORKFLOW_ACTIONS, Engine
from ..utils import is_ip, normalize_mac
from .widgets import FormRow, SwitchRow, safe

DEVICE_TEXT_FIELDS = [
    ("name", "Name", "Friendly name shown across the app"),
    ("owner", "Owner", "Person or team responsible"),
    ("type", "Type", "Router, Laptop, IoT, Camera…"),
    ("vendor", "Vendor", "Hardware manufacturer"),
    ("group_name", "Group", "Logical grouping or tag"),
    ("location", "Location", "Room, rack or site"),
    ("site", "Site", "Building or customer site"),
    ("ssid", "SSID", "Wireless network name"),
    ("vlan", "VLAN", "VLAN id or label"),
    ("parent_port", "Parent port", "Switch port or uplink"),
]

FLAGS = [
    ("favorite", "Favourite", "Pin to the top of dashboards"),
    ("archived", "Archived", "Hide from active device views"),
    ("alert_down", "Alert when down", "Raise an alert after the down threshold"),
    ("can_sleep", "Can sleep", "Suppress down alerts for sleepy devices"),
    ("skip_repeated", "Skip repeated alerts", "Do not repeat identical alerts"),
]


class BaseModal(ModalScreen):
    """Shared modal card scaffold."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    title_text = ""
    subtitle_text = ""
    card_width = 76

    def compose(self) -> ComposeResult:
        """Compose the card shell; subclasses override body/actions."""
        with Container(id="modal-card", classes=f"w{self.card_width}"):
            yield Static(self.title_text, classes="modal-title")
            if self.subtitle_text:
                yield Static(self.subtitle_text, classes="modal-sub")
            with VerticalScroll(id="modal-body"):
                yield from self.body()
            with Horizontal(classes="modal-actions"):
                yield from self.actions()

    def body(self) -> ComposeResult:
        """Yield modal body widgets."""
        yield Static("")

    def actions(self) -> ComposeResult:
        """Yield modal action buttons."""
        yield Button("Cancel", id="cancel")
        yield Button("Save", id="save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle cancel/save."""
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self.save()

    def save(self) -> None:
        """Validate and dismiss with a result."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Dismiss the dialog without applying changes."""
        self.dismiss(None)

    def on_mount(self) -> None:
        """Focus the first input when the modal opens."""
        inputs = self.query(Input)
        if inputs:
            inputs.first().focus()


class ConfirmModal(BaseModal):
    """Yes/no confirmation."""

    card_width = 62

    def __init__(self, title: str, message: str, confirm_label: str = "Confirm", danger: bool = False) -> None:
        super().__init__()
        self.title_text = title
        self.subtitle_text = ""
        self.message = message
        self.confirm_label = confirm_label
        self.danger = danger

    def body(self) -> ComposeResult:
        """Show the confirmation message."""
        yield Static(self.message, classes="modal-text")

    def actions(self) -> ComposeResult:
        """Render cancel + confirm."""
        yield Button("Cancel", id="cancel")
        yield Button(
            self.confirm_label,
            id="save",
            variant="error" if self.danger else "primary",
        )

    def save(self) -> None:
        """Confirm the action."""
        self.dismiss(True)


class PromptModal(BaseModal):
    """Single-value text or integer prompt."""

    card_width = 64

    def __init__(
        self,
        title: str,
        label: str,
        default: str = "",
        placeholder: str = "",
        int_only: bool = False,
        hint: str = "",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.input_label = label
        self.default = default
        self.placeholder = placeholder
        self.int_only = int_only
        self.hint = hint

    def body(self) -> ComposeResult:
        """Render the input field."""
        yield FormRow(
            self.input_label,
            Input(value=self.default, placeholder=self.placeholder, id="prompt-input"),
            self.hint,
        )

    def save(self) -> None:
        """Validate and return the value."""
        value = self.query_one("#prompt-input", Input).value.strip()
        if self.int_only:
            try:
                number = int(value)
            except ValueError:
                self.app.notify("Enter a whole number", severity="error")
                return
            self.dismiss(number)
        else:
            if not value:
                self.app.notify("A value is required", severity="error")
                return
            self.dismiss(value)


class NewDeviceModal(BaseModal):
    """Create a manual device."""

    card_width = 72
    title_text = "Add device"
    subtitle_text = "Track something that discovery cannot see."

    def body(self) -> ComposeResult:
        """Render identity fields."""
        yield FormRow("Name", Input(placeholder="e.g. Office printer", id="new-name"))
        yield FormRow("IP address", Input(placeholder="192.168.1.50", id="new-ip"))
        yield FormRow(
            "MAC address",
            Input(placeholder="aa:bb:cc:dd:ee:ff (optional)", id="new-mac"),
            "Leave blank to create a virtual device keyed by IP.",
        )

    def save(self) -> None:
        """Validate the device fields."""
        name = self.query_one("#new-name", Input).value.strip()
        ip = self.query_one("#new-ip", Input).value.strip()
        mac = self.query_one("#new-mac", Input).value.strip()
        if not name:
            self.app.notify("Name is required", severity="error")
            return
        if ip and not is_ip(ip):
            self.app.notify("IP address is not valid", severity="error")
            return
        if mac and not normalize_mac(mac):
            self.app.notify("MAC address is not valid", severity="error")
            return
        self.dismiss({"name": name, "ip": ip, "mac": mac})


class EditDeviceModal(BaseModal):
    """Edit every user-facing device field."""

    card_width = 88

    def __init__(self, engine: Engine, device: dict) -> None:
        super().__init__()
        self.engine = engine
        self.device = device
        self.title_text = f"Edit · {device.get('name') or device['mac']}"
        self.subtitle_text = f"{device.get('mac')}   {device.get('ip') or 'no address'}"

    def body(self) -> ComposeResult:
        """Render the full edit form."""
        for key, label, hint in DEVICE_TEXT_FIELDS:
            yield FormRow(
                label,
                Input(value=str(self.device.get(key) or ""), id=f"f-{key}"),
                hint,
            )

        others = [
            (f"{row.get('name') or row['mac']}  ·  {row.get('ip') or '—'}", row["mac"])
            for row in self.engine.list_devices(status="all", limit=500)
            if row["mac"] != self.device["mac"]
        ]
        current_parent = self.device.get("parent_mac") or Select.BLANK
        yield FormRow(
            "Parent device",
            Select(
                options=others,
                value=current_parent,
                allow_blank=True,
                prompt="— no parent —",
                id="f-parent",
            ),
            "Used by the Network tree view.",
        )

        yield Label("Behaviour", classes="section-label")
        for key, label, hint in FLAGS:
            yield SwitchRow(
                label,
                Switch(value=bool(self.device.get(key)), id=f"sw-{key}"),
                hint,
            )

        yield Label("Notes", classes="section-label")
        yield TextArea(
            str(self.device.get("comments") or ""),
            id="f-comments",
            classes="comments-area",
        )

    def save(self) -> None:
        """Return the edited field dictionary."""
        changes: dict[str, Any] = {}
        for key, _, _ in DEVICE_TEXT_FIELDS:
            changes[key] = self.query_one(f"#f-{key}", Input).value.strip()
        parent = self.query_one("#f-parent", Select).value
        changes["parent_mac"] = "" if parent in (Select.BLANK, None) else str(parent)
        changes["comments"] = self.query_one("#f-comments", TextArea).text.strip()
        for key, _, _ in FLAGS:
            changes[key] = 1 if self.query_one(f"#sw-{key}", Switch).value else 0
        if not changes["name"]:
            self.app.notify("Name cannot be empty", severity="error")
            return
        self.dismiss(changes)


class EditSettingModal(BaseModal):
    """Edit one application setting."""

    card_width = 72

    def __init__(self, key: str, meta: dict, value: Any) -> None:
        super().__init__()
        self.key = key
        self.meta = meta
        self.value = value
        self.title_text = meta.get("label", key)
        self.subtitle_text = f"{key} · {meta.get('group', 'General')}"

    def body(self) -> ComposeResult:
        """Render the appropriate editor for the setting type."""
        kind = self.meta.get("type", "str")
        hint = self.meta.get("help", "")
        if kind == "bool":
            yield SwitchRow("Enabled", Switch(value=bool(self.value), id="set-bool"), hint)
        elif kind == "choice":
            options = [(option.title(), option) for option in self.meta.get("options", [])]
            yield FormRow(
                "Value",
                Select(options=options, value=self.value, allow_blank=False, id="set-choice"),
                hint,
            )
        elif kind == "int":
            yield FormRow("Value", Input(value=str(self.value), id="set-int", type="integer"), hint)
        elif kind == "secret":
            yield FormRow("Value", Input(value=str(self.value), password=True, id="set-secret"), hint)
        else:
            yield FormRow("Value", Input(value=str(self.value), id="set-str"), hint)

    def save(self) -> None:
        """Validate and return the new value."""
        kind = self.meta.get("type", "str")
        if kind == "bool":
            value = self.query_one("#set-bool", Switch).value
        elif kind == "choice":
            value = self.query_one("#set-choice", Select).value
        elif kind == "int":
            raw = self.query_one("#set-int", Input).value.strip()
            try:
                value = int(raw)
            except ValueError:
                self.app.notify("Enter a whole number", severity="error")
                return
            low, high = self.meta.get("min"), self.meta.get("max")
            if low is not None and value < low:
                self.app.notify(f"Minimum is {low}", severity="error")
                return
            if high is not None and value > high:
                self.app.notify(f"Maximum is {high}", severity="error")
                return
        elif kind == "secret":
            value = self.query_one("#set-secret", Input).value
        else:
            value = self.query_one("#set-str", Input).value.strip()
        self.dismiss({"key": self.key, "value": value})


class NewWorkflowModal(BaseModal):
    """Create an automation rule."""

    card_width = 82
    title_text = "New automation"
    subtitle_text = "Conditionally change a device field before/after scans."

    def body(self) -> ComposeResult:
        """Render the rule builder."""
        yield FormRow("Name", Input(placeholder="Tag Apple devices", id="wf-name"))
        yield FormRow(
            "Trigger",
            Select(
                options=[
                    ("New device discovered", "new_device"),
                    ("Device comes online", "online"),
                    ("Every scan (all devices)", "scan"),
                ],
                value="new_device",
                allow_blank=False,
                id="wf-trigger",
            ),
        )
        yield Label("Condition", classes="section-label")
        yield FormRow(
            "Field",
            Input(placeholder="vendor", value="vendor", id="wf-field"),
            "Any device column, e.g. vendor, type, ip, name, group_name.",
        )
        yield FormRow(
            "Operator",
            Select(
                options=[(op.replace("_", " ").title(), op) for op in OPERATORS],
                value="contains",
                allow_blank=False,
                id="wf-operator",
            ),
        )
        yield FormRow("Value", Input(placeholder="Apple", id="wf-value"))
        yield Label("Action", classes="section-label")
        yield FormRow(
            "Set field",
            Select(
                options=[(field.replace("_", " ").title(), field) for field in sorted(WORKFLOW_ACTIONS)],
                value="group_name",
                allow_blank=False,
                id="wf-action-field",
            ),
        )
        yield FormRow("To value", Input(placeholder="Apple", id="wf-action-value"))

    def save(self) -> None:
        """Validate and return the workflow definition."""
        payload = {
            "name": self.query_one("#wf-name", Input).value.strip(),
            "trigger": self.query_one("#wf-trigger", Select).value,
            "field": self.query_one("#wf-field", Input).value.strip(),
            "operator": self.query_one("#wf-operator", Select).value,
            "value": self.query_one("#wf-value", Input).value.strip(),
            "action_field": self.query_one("#wf-action-field", Select).value,
            "action_value": self.query_one("#wf-action-value", Input).value.strip(),
        }
        if not payload["name"] or not payload["field"]:
            self.app.notify("Name and field are required", severity="error")
            return
        self.dismiss(payload)
