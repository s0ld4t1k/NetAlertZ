"""Command line entry point for NetAlertZ."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import home
from .demo import seed_demo
from .engine import Engine
from .tui.app import NetAlertZApp


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="netalertz",
        description="NetAlertZ — terminal-native network discovery, inventory and alerting.",
        epilog="Data lives in ~/.netalertz unless NETALERTZ_HOME is set.",
    )
    parser.add_argument("--db", metavar="PATH", help="use a specific SQLite database file")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="seed a realistic demo network when the database is empty",
    )
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="wipe the database and reload the demo dataset (destructive)",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="run a discovery scan immediately after launch",
    )
    parser.add_argument(
        "--no-scan",
        action="store_true",
        help="disable all automatic and scheduled scanning for this session",
    )
    parser.add_argument(
        "--interval",
        type=int,
        metavar="SECONDS",
        help="override the scheduled scan interval (minimum 15 seconds)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"NetAlertZ {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, prepare the database and start the TUI."""
    args = build_parser().parse_args(argv)
    database = Path(args.db).expanduser() if args.db else None

    if args.demo or args.reset_demo:
        engine = Engine(database)
        seeded = seed_demo(engine, force=args.reset_demo)
        if seeded:
            print(f"NetAlertZ demo dataset loaded · {home()}")
        elif not args.reset_demo:
            print("NetAlertZ · database already has devices, demo seed skipped")

    allow_scan = not args.no_scan
    if args.demo and not args.scan and not args.reset_demo:
        # A demo should stay a demo: no surprise traffic on first launch.
        allow_scan = False
    if args.no_scan and args.scan:
        print("NetAlertZ: --scan ignored because --no-scan was also given", file=sys.stderr)
        allow_scan = False

    app = NetAlertZApp(
        database,
        allow_scan=allow_scan,
        interval=args.interval,
        scan_on_start=True if args.scan and allow_scan else None,
    )
    app.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
