"""Content views mounted inside the application shell."""

from __future__ import annotations

from .automations import AutomationsView
from .base import BaseView
from .dashboard import DashboardView
from .devices import DevicesView
from .events import EventsView
from .help import HelpView
from .logs import LogsView
from .network import NetworkView
from .notifications import NotificationsView
from .presence import PresenceView
from .scanners import ScannersView
from .settings import SettingsView

VIEW_CLASSES = [
    DashboardView,
    DevicesView,
    EventsView,
    PresenceView,
    NetworkView,
    ScannersView,
    AutomationsView,
    NotificationsView,
    SettingsView,
    LogsView,
    HelpView,
]

__all__ = ["BaseView", "VIEW_CLASSES"]
