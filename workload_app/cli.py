"""Command line entry point: ``python -m workload_app``.

Runs the app on this machine, with the same accounts, the same login and the
same storage as a hosted copy -- so what is tested locally is what is deployed.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .server import make_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workload_app",
        description=(
            "Enter timesheets, projects, deliverables and tasks into the "
            "Workload & Profit Plan workbook without touching the spreadsheet "
            "by hand."
        ),
    )
    parser.add_argument(
        "-d", "--data-dir", type=Path, default=None,
        help="where accounts and workbooks live "
             "(default: $WORKLOAD_DATA_DIR, else ./instance)",
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

    try:
        server = make_server(args.data_dir, args.host, args.port,
                             autosave=not args.no_autosave, quiet=args.quiet)
    except OSError as exc:
        print(f"error: cannot listen on {args.host}:{args.port} ({exc})",
              file=sys.stderr)
        return 2

    app = server.app                                 # type: ignore[attr-defined]
    url = f"http://{args.host}:{args.port}/"
    print(f"Workload {__version__}")
    print(f"  data     : {app.data_dir}")
    print(f"  autosave : {'on' if not args.no_autosave else 'off'}")
    print(f"  open     : {url}")
    if app.accounts.user_count() == 0:
        print()
        print("  There are no accounts yet, so nobody can sign in. Make one:")
        print("    python -m workload_app.admin add <username> --admin")
        print()
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        app.close_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
