"""Administration from the command line: ``python -m workload_app.admin``.

There is no public sign-up, so the first account has to be made here -- on the
host's console, by whoever owns the installation.  Everything this does is also
in the app's own Accounts panel, for an administrator who is already signed in.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Optional

from . import accounts as accounts_module, storage
from .accounts import AccountError, Accounts


def _accounts(data_dir: Optional[Path]) -> Accounts:
    directory = Path(data_dir) if data_dir else accounts_module.data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return Accounts(directory / "accounts.db")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m workload_app.admin",
        description="Create and manage the accounts that can sign in.",
    )
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="where accounts and workbooks live "
                             "(default: $WORKLOAD_DATA_DIR, else ./instance)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="create an account")
    add.add_argument("username")
    add.add_argument("--name", default="", help="the name shown in the app")
    add.add_argument("--admin", action="store_true",
                     help="may create and remove other accounts")
    add.add_argument("--password", default=None,
                     help="omit to be asked, or to have one generated")

    sub.add_parser("list", help="list the accounts")

    password = sub.add_parser("password", help="set an account's password")
    password.add_argument("username")
    password.add_argument("--password", default=None)

    remove = sub.add_parser("remove", help="delete an account and its workbooks")
    remove.add_argument("username")
    remove.add_argument("--yes", action="store_true", help="do not ask")

    adopt = sub.add_parser(
        "import", help="put an existing workbook into an account as a unit")
    adopt.add_argument("username")
    adopt.add_argument("workbook", type=Path)
    adopt.add_argument("--name", default="", help="the unit's name")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    db = _accounts(args.data_dir)
    data_dir = db.path.parent
    try:
        return COMMANDS[args.command](db, data_dir, args)
    except AccountError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _add(db: Accounts, data_dir: Path, args) -> int:
    password = args.password or _ask_password()
    generated = password is None
    if generated:
        password = accounts_module.generated_password()
    user = db.create_user(args.username, password, display_name=args.name,
                          is_admin=args.admin)
    print(f"Created {user['username']}"
          + (" (administrator)" if user["is_admin"] else ""))
    if generated:
        print(f"  password: {password}")
        print("  Write it down now; it cannot be read back.")
    return 0


def _list(db: Accounts, data_dir: Path, args) -> int:
    users = db.users()
    if not users:
        print("No accounts yet. Make one with:  python -m workload_app.admin add <username> --admin")
        return 0
    width = max(len(u["username"]) for u in users)
    for user in users:
        marker = "admin" if user["is_admin"] else "     "
        print(f"{user['username']:<{width}}  {marker}  "
              f"{user['units'] or 0} unit(s)  last seen {user['last_seen'] or 'never'}")
    return 0


def _password(db: Accounts, data_dir: Path, args) -> int:
    user = next((u for u in db.users() if u["username"] == args.username), None)
    if user is None:
        print(f"error: no account called {args.username}", file=sys.stderr)
        return 2
    password = args.password or _ask_password()
    generated = password is None
    if generated:
        password = accounts_module.generated_password()
    db.set_password(user["id"], password)
    print(f"Password changed for {user['username']}; every session was ended.")
    if generated:
        print(f"  password: {password}")
    return 0


def _remove(db: Accounts, data_dir: Path, args) -> int:
    user = next((u for u in db.users() if u["username"] == args.username), None)
    if user is None:
        print(f"error: no account called {args.username}", file=sys.stderr)
        return 2
    if not args.yes:
        answer = input(f"Delete {user['username']} and every workbook they have? "
                       f"[y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Left alone.")
            return 0
    db.delete_user(user["id"])
    storage.remove_user_files(data_dir, user["id"])
    print(f"Deleted {user['username']}.")
    return 0


def _import(db: Accounts, data_dir: Path, args) -> int:
    from . import library

    user = next((u for u in db.users() if u["username"] == args.username), None)
    if user is None:
        print(f"error: no account called {args.username}", file=sys.stderr)
        return 2
    source = Path(args.workbook).expanduser()
    try:
        library.validate(source)
    except library.NotAWorkbook as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    unit = db.create_unit(user["id"], args.name or source.stem, "")
    path = storage.save_upload(data_dir, user["id"], unit["id"],
                               source.read_bytes())
    with db._connect() as connection:                  # noqa: SLF001 - same package
        connection.execute("UPDATE units SET filename = ? WHERE id = ?",
                           (path.name, unit["id"]))
    print(f"{source.name} is now {user['username']}'s unit {unit['name']!r}.")
    print(f"  stored at {path}")
    return 0


def _ask_password() -> Optional[str]:
    """Ask twice, or return None to have one generated."""
    if not sys.stdin.isatty():
        return None
    first = getpass.getpass("Password (blank to generate one): ")
    if not first:
        return None
    again = getpass.getpass("Again: ")
    if first != again:
        raise AccountError("Those two passwords are not the same.")
    return first


COMMANDS = {
    "add": _add,
    "list": _list,
    "password": _password,
    "remove": _remove,
    "import": _import,
}


if __name__ == "__main__":
    raise SystemExit(main())
