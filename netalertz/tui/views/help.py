"""In-app help: keyboard map, workflows and operational notes."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static

from ...config import TAGLINE, VERSION, home
from .base import BaseView

HELP = """
[b #22d3ee]NETALERTZ[/]  [dim]network intelligence, in your terminal[/]

[bold]Quick start[/]
[#94a3b8]1.[/] Press [b]s[/] to discover hosts on your local network.
[#94a3b8]2.[/] Open [b]Devices[/] to rename hardware, assign owners and groups.
[#94a3b8]3.[/] Set a parent device to draw your topology in [b]Network tree[/].
[#94a3b8]4.[/] Add rules in [b]Automations[/] to enrich new devices automatically.
[#94a3b8]5.[/] Alerts appear in [b]Alerts[/] and can also go to a webhook or Telegram.

[bold]Keyboard[/]
[#94a3b8]1–9[/]      jump between views
[#94a3b8]l[/]        logs          [#94a3b8]?[/]  this help
[#94a3b8]s[/]        run a scan     [#94a3b8]r[/]  refresh the current view
[#94a3b8]F2[/]       cycle themes   [#94a3b8]ctrl+q[/]  quit
[#94a3b8]/[/]        focus search   [#94a3b8]Enter[/]  open the selected row
[#94a3b8]n[/]        new device / automation (context sensitive)
[#94a3b8]d[/]        delete the selected event / notification / automation
[#94a3b8]e[/]        export devices to CSV (Devices view)
[#94a3b8]w[/]        wake a device with Wake-on-LAN (device detail)
[#94a3b8]a[/]        archive a device (device detail)
[#94a3b8]Esc[/]      close a dialog without saving

[bold]Discovery backends[/]
NetAlertZ shells out to standard tools and falls back gracefully:
[#22d3ee]arp-scan[/]  →  [#22d3ee]nmap[/]  →  [#22d3ee]fping[/]  →  OS ARP cache.
Only one is required. Configure the method and targets in [b]Settings → Scanning[/].
No Docker image, daemon or web server is involved.

[bold]How presence works[/]
Every scan records an hourly sample per device. The Presence view turns those
samples into a heatmap and uptime percentages. A device is [b]Down[/] after the
configured threshold; sleepy devices are marked [b]Sleeping[/] instead of alerting.

[bold]Automations[/]
A rule is [dim]trigger → condition → action[/dim]. Triggers: new device, online,
or every scan. Actions can set a name, owner, group, location, flags and more.
Rules are applied after discovery and never delete devices.

[bold]Notifications[/]
By default alerts stay in-app. Disable [b]In-app only[/] and set a webhook URL
and/or Telegram bot token to fan out to external services.

[bold]Data & privacy[/]
Everything lives in [b]~/.netalertz[/b] (override with [b]NETALERTZ_HOME[/b]):
[dim]netalertz.db[/] — SQLite database
[dim]netalertz.log[/] — rotating file log
[dim]exports/[/] — CSV exports
No telemetry leaves your machine unless you configure a webhook or Telegram.

[bold]Command line[/]
[#94a3b8]$[/] netalertz                 [#94a3b8]start with the saved database[/]
[#94a3b8]$[/] netalertz --demo          [#94a3b8]seed and open a demo network[/]
[#94a3b8]$[/] netalertz --scan          [#94a3b8]scan immediately after launch[/]
[#94a3b8]$[/] netalertz --no-scan       [#94a3b8]never scan automatically[/]
[#94a3b8]$[/] netalertz --db PATH       [#94a3b8]use a specific database file[/]
[#94a3b8]$[/] netalertz --interval 60   [#94a3b8]override the scan interval[/]
"""


class HelpView(BaseView):
    """Static reference documentation."""

    view_id = "help"
    nav_title = "Help"
    nav_subtitle = "keys · concepts · command line"
    auto_refresh = False

    BINDINGS = [("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        """Compose the scrollable help document."""
        with VerticalScroll(id="help-scroll"):
            yield Static(HELP, id="help-body", markup=True)
        with Horizontal(classes="subhead"):
            yield Static(
                f"[dim]{TAGLINE} · v{VERSION} · data in {home()}[/]",
                classes="hint",
            )

    def refresh_data(self) -> None:
        """Help content is static."""

    def action_refresh(self) -> None:
        """Nothing to refresh."""
        self.notify("Help is already up to date")
