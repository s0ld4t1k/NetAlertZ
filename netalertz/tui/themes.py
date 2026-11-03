"""Custom Textual themes for NetAlertZ."""

from __future__ import annotations

from textual.theme import Theme

THEMES: dict[str, Theme] = {
    "netalertz": Theme(
        name="netalertz",
        primary="#22d3ee",
        secondary="#a78bfa",
        accent="#22d3ee",
        success="#34d399",
        warning="#fbbf24",
        error="#fb7185",
        foreground="#dbe7ff",
        background="#070b14",
        surface="#0d1526",
        panel="#0a1120",
        boost="#16233d",
        dark=True,
        luminosity_spread=0.12,
    ),
    "ember": Theme(
        name="ember",
        primary="#ffb86b",
        secondary="#ff7a90",
        accent="#ffd166",
        success="#8bd49c",
        warning="#ffd166",
        error="#ff6b6b",
        foreground="#ffe9d6",
        background="#120b08",
        surface="#1d120d",
        panel="#160e0a",
        boost="#2b1a12",
        dark=True,
    ),
    "nord": Theme(
        name="nord",
        primary="#88c0d0",
        secondary="#b48ead",
        accent="#8fbcbb",
        success="#a3be8c",
        warning="#ebcb8b",
        error="#bf616a",
        foreground="#eceff4",
        background="#242933",
        surface="#2e3440",
        panel="#272c36",
        boost="#3b4252",
        dark=True,
    ),
    "mono": Theme(
        name="mono",
        primary="#e5e5e5",
        secondary="#a3a3a3",
        accent="#fafafa",
        success="#d4d4d4",
        warning="#e5e5e5",
        error="#ffffff",
        foreground="#ededed",
        background="#080808",
        surface="#141414",
        panel="#0e0e0e",
        boost="#222222",
        dark=True,
    ),
}

THEME_ORDER = ["netalertz", "ember", "nord", "mono"]
