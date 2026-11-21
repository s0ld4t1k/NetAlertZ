"""Topology tree built from declared parent relationships."""

from __future__ import annotations

from rich.console import Group
from rich.table import Table as RichTable
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static, Tree

from ...utils import local_ts
from ..widgets import STATUS_COLORS, STATUS_GLYPHS
from .base import BaseView


class NetworkView(BaseView):
    """Interactive network tree with a detail inspector."""

    view_id = "network"
    nav_title = "Network tree"
    nav_subtitle = "topology · parents · uplinks"

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "scan", "Scan"),
        ("e", "expand", "Expand"),
        ("c", "collapse", "Collapse"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the tree and inspector panes."""
        with Horizontal(id="network-body"):
            with Vertical(classes="panel", id="tree-panel"):
                with Horizontal(classes="toolbar slim"):
                    yield Static("[b]Topology[/]  [dim]parent links[/]", classes="toolbar-title")
                    yield Button("Expand", id="tree-expand")
                    yield Button("Collapse", id="tree-collapse")
                    yield Button("Scan", id="network-scan", variant="primary")
                yield Tree("Home network", id="network-tree")
            with Vertical(classes="panel", id="network-detail-panel"):
                yield Static("[b]Inspector[/]  [dim]select a node[/]", classes="panel-title")
                yield Static("", id="network-detail")

    _built = False

    def refresh_data(self) -> None:
        """Rebuild the tree from current device relationships."""
        devices = self.engine.list_devices(status="all", limit=2000)
        by_mac = {str(device["mac"]): device for device in devices}
        children: dict[str, list[dict]] = {}
        roots: list[dict] = []
        for device in devices:
            parent = str(device.get("parent_mac") or "")
            if parent and parent in by_mac and parent != device["mac"]:
                children.setdefault(parent, []).append(device)
            else:
                roots.append(device)

        tree = self.query_one("#network-tree", Tree)
        # Remember what the user had open and selected, so the 5-second
        # auto-refresh does not collapse the tree under their cursor.
        first_build = not self._built
        expanded_now = self._expanded_macs(tree)
        selected = self._selected_mac(tree)
        tree.clear()
        tree.root.label = Text(f"Home network   {len(devices)} devices", style="bold #22d3ee")
        roots.sort(key=lambda row: (str(row.get("type") or ""), str(row.get("name") or "")))
        visited: set[str] = set()

        def attach(parent_node, device: dict, depth: int) -> None:
            mac = str(device["mac"])
            if mac in visited:
                return
            visited.add(mac)
            is_open = depth < 2 if first_build else mac in expanded_now
            node = parent_node.add(self._label(device, depth), data=mac, expand=is_open)
            for child in sorted(children.get(mac, []), key=lambda row: str(row.get("name") or "")):
                attach(node, child, depth + 1)

        for root in roots:
            attach(tree.root, root, 0)
        # Cycles or orphans that were never attached.
        for device in devices:
            if str(device["mac"]) not in visited:
                attach(tree.root, device, 0)
        tree.root.expand()
        self._built = True
        self._roots = roots

        target = self._find_node(tree.root, selected) if selected else None
        if target is not None:
            # Tree line numbers are computed lazily, so move after the redraw.
            self.call_after_refresh(tree.move_cursor, target)
            self._render_detail(self.engine.get_device(selected))
        else:
            self._render_detail(roots[0] if roots else None)

    @staticmethod
    def _expanded_macs(tree: Tree) -> set[str]:
        """Return the MACs of every currently expanded node."""
        found: set[str] = set()
        stack = list(tree.root.children)
        while stack:
            node = stack.pop()
            if node.is_expanded and node.data:
                found.add(str(node.data))
            stack.extend(node.children)
        return found

    @staticmethod
    def _selected_mac(tree: Tree) -> str:
        """Return the MAC under the tree cursor, or an empty string."""
        node = tree.cursor_node
        return str(node.data) if node is not None and node.data else ""

    def _find_node(self, node, mac: str):
        """Depth-first search for the tree node carrying a MAC."""
        stack = [node]
        while stack:
            current = stack.pop()
            if current.data == mac:
                return current
            stack.extend(current.children)
        return None

    def _label(self, device: dict, depth: int) -> Text:
        """Build a coloured tree label for one device."""
        status = str(device.get("status") or "offline")
        color = STATUS_COLORS.get(status, "#94a3b8")
        glyph = STATUS_GLYPHS.get(status, "○")
        label = Text()
        label.append(f"{glyph} ", style=f"bold {color}")
        label.append(str(device.get("name") or device.get("mac")), style=f"bold {color}" if status == "online" else "")
        if device.get("ip"):
            label.append(f" {device['ip']}", style="#7dd3fc")
        if device.get("type"):
            label.append(f" {device['type']}", style="dim")
        return label

    def _render_detail(self, device: dict | None) -> None:
        """Render the inspector card for a device."""
        panel = self.query_one("#network-detail", Static)
        if not device:
            panel.update(Text("No device selected.", style="dim"))
            return
        table = RichTable.grid(padding=(0, 2))
        table.add_column(style="dim", justify="left")
        table.add_column(style="", justify="left")
        table.add_row("Name", Text(str(device.get("name") or device.get("mac")), style="bold"))
        table.add_row("Status", Text(str(device.get("status_label") or device.get("status")), style=STATUS_COLORS.get(str(device.get("status")), "#94a3b8")))
        table.add_row("Address", Text(str(device.get("ip") or "—"), style="#7dd3fc"))
        table.add_row("MAC", Text(str(device.get("mac") or "—")))
        table.add_row("Vendor", Text(str(device.get("vendor") or "—")))
        table.add_row("Type", Text(str(device.get("type") or "—")))
        table.add_row("Group", Text(str(device.get("group_name") or "—")))
        table.add_row("Owner", Text(str(device.get("owner") or "—")))
        table.add_row("Location", Text(str(device.get("location") or "—")))
        if device.get("ssid"):
            table.add_row("SSID", Text(str(device["ssid"])))
        parent = self.engine.db.q1("SELECT name FROM devices WHERE mac=?", (device.get("parent_mac"),))
        table.add_row("Parent", Text(str(parent["name"]) if parent else "—"))
        table.add_row("Port", Text(str(device.get("parent_port") or "—")))
        table.add_row("Link", Text(str(device.get("parent_rel") or "—")))
        table.add_row("First seen", Text(local_ts(device.get("first_seen"))))
        table.add_row("Last seen", Text(f"{local_ts(device.get('last_seen'))}  ({device.get('last_seen_human')})"))
        heading = Text()
        heading.append("◈ ", style="#22d3ee")
        heading.append(str(device.get("name") or device.get("mac")), style="bold")
        hint = Text("\nEnter on the tree opens the full device detail.", style="dim italic")
        panel.update(Group(heading, Text(""), table, hint))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Show the selected node in the inspector."""
        mac = str(event.node.data or "")
        if not mac:
            return
        device = self.engine.get_device(mac)
        if device:
            self._render_detail(device)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle tree controls."""
        if event.button.id == "tree-expand":
            self.query_one("#network-tree", Tree).root.expand_all()
        elif event.button.id == "tree-collapse":
            self.query_one("#network-tree", Tree).root.collapse_all()
            self.query_one("#network-tree", Tree).root.expand()
        elif event.button.id == "network-scan":
            self.app.start_scan()

    def action_expand(self) -> None:
        """Expand every tree node."""
        self.query_one("#network-tree", Tree).root.expand_all()

    def action_collapse(self) -> None:
        """Collapse the tree back to the roots."""
        tree = self.query_one("#network-tree", Tree)
        tree.root.collapse_all()
        tree.root.expand()

    def action_scan(self) -> None:
        """Start discovery."""
        self.app.start_scan()

    def action_refresh(self) -> None:
        """Reload topology data."""
        self.refresh_data()
        self.notify("Topology refreshed")
