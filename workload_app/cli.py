"""Command line entry point: ``python -m workload_app``."""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__, config as cfg
from .server import make_server

DEFAULT_WORKBOOK = Path("data/Workload.xlsx")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workload_app",
        description=(
            "Enter timesheets, projects and deliverables into the Workload & "
            "Profit Plan workbook without touching the spreadsheet by hand."
        ),
    )
    parser.add_argument(
        "-w", "--workbook", type=Path, default=DEFAULT_WORKBOOK,
        help=f"path to the workbook (default: {DEFAULT_WORKBOOK})",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to listen on (default: 127.0.0.1)")
    parser.add_argument("-p", "--port", type=int, default=8765,
                        help="port to listen on (default: 8765)")
    parser.add_argument(
        "--no-autosave", action="store_true",
        help="keep changes in memory until Save is pressed, instead of writing "
             "the workbook after every change",
    )
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open a browser window on start")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="do not log every request")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    workbook = args.workbook.expanduser()
    if not workbook.is_file():
        print(f"error: no workbook at {workbook}", file=sys.stderr)
        print("Point the app at your copy with --workbook path/to/Workload.xlsx",
              file=sys.stderr)
        return 2

    try:
        server = make_server(workbook.resolve(), args.host, args.port,
                             autosave=not args.no_autosave, quiet=args.quiet)
    except OSError as exc:
        print(f"error: cannot listen on {args.host}:{args.port} ({exc})",
              file=sys.stderr)
        return 2

    url = f"http://{args.host}:{args.port}/"
    print(f"Workload input app {__version__}")
    print(f"  workbook : {workbook.resolve()}")
    print(f"  backups  : {workbook.resolve().parent / cfg.BACKUP_DIRNAME}")
    print(f"  autosave : {'on' if not args.no_autosave else 'off'}")
    print(f"  open     : {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        result = server.service.save()               # type: ignore[attr-defined]
        if result.get("saved"):
            print(f"Saved pending changes to {workbook}")
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
