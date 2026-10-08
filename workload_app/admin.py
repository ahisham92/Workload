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

from . import accounts as accounts_module, config as cfg, deployment, storage
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
                        help="where accounts and units live "
                             "(default: $WORKLOAD_DATA_DIR, else ./instance)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="create an account")
    add.add_argument("username")
    add.add_argument("--name", default="", help="the name shown in the app")
    add.add_argument("--admin", action="store_true",
                     help="may create and remove other accounts")
    add.add_argument("--member", action="store_true",
                     help="a read-only team member account, given sight of one "
                          "engineer by their manager")
    add.add_argument("--password", default=None,
                     help="omit to be asked, or to have one generated")

    sub.add_parser("list", help="list the accounts")

    password = sub.add_parser("password", help="set an account's password")
    password.add_argument("username")
    password.add_argument("--password", default=None)

    remove = sub.add_parser("remove", help="delete an account and its units")
    remove.add_argument("username")
    remove.add_argument("--yes", action="store_true", help="do not ask")

    adopt = sub.add_parser(
        "import", help="make a unit in an account from an old Workload workbook")
    adopt.add_argument("username")
    adopt.add_argument("workbook", type=Path)
    adopt.add_argument("--name", default="", help="the unit's name")

    restore = sub.add_parser(
        "restore", help="put a kept copy of a unit (or an old workbook) in "
                        "place of what a unit holds now")
    restore.add_argument("username")
    restore.add_argument("unit", help="the unit's name, or its id")
    restore.add_argument("workbook", type=Path, metavar="copy",
                         help="a .db copy from the backups folder, or a workbook")

    bring = sub.add_parser(
        "bring", help="copy an account's units from another Workload folder "
                      "(the old site's) into an account here; that folder is "
                      "only read, never changed")
    bring.add_argument("source", type=Path,
                       help="the other Workload data folder, e.g. ~/workload-data")
    bring.add_argument("--from", dest="from_user", default=None,
                       help="the account there (default: the only one with units)")
    bring.add_argument("--to", dest="to_user", default=None,
                       help="the account here: its username, or what it signs "
                            "in to the site with (default: the only one here)")

    units = sub.add_parser(
        "units", help="what each unit actually holds: rows, hours, projects")
    units.add_argument("username", nargs="?", default=None,
                       help="omit for every account")

    link = sub.add_parser(
        "link", help="tie an account to its owner's sign-in on the surrounding "
                     "site, when Workload is a tab of one")
    link.add_argument("username")
    link.add_argument("site_id", nargs="?", default=None,
                      help="the site's identifier for that person; leave out "
                           "to unlink")
    link.add_argument("--login", default=None,
                      help="what they sign in to the site with, for show")

    sub.add_parser(
        "notify", help="send each manager's phone what is new: the weekly "
                       "report, and anything that needs them (for the host's "
                       "scheduled task, once a day)")

    checker = sub.add_parser(
        "check", help="is this installation ready to serve, and what should "
                      "the host's WSGI file say?")
    checker.add_argument("--wsgi-only", action="store_true",
                         help="print just the WSGI file, to redirect to it")

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return _check(None, None, args)
    db = _accounts(args.data_dir)
    data_dir = db.path.parent
    try:
        return COMMANDS[args.command](db, data_dir, args)
    except AccountError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _add(db: Accounts, data_dir: Path, args) -> int:
    password, generated = _password_from(args)
    role = accounts_module.ROLE_MEMBER if args.member else accounts_module.ROLE_MANAGER
    user = db.create_user(args.username, password, display_name=args.name,
                          is_admin=args.admin, role=role)
    print(f"Created {user['username']} ({user['role']})"
          + (", administrator" if user["is_admin"] else ""))
    if user["role"] == accounts_module.ROLE_MEMBER:
        print("  A manager gives them sight of one engineer from their Team tab.")
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
        print(f"{user['username']:<{width}}  {user['role']:<7}  {marker}  "
              f"{user['units'] or 0} unit(s)  last seen {user['last_seen'] or 'never'}")
    return 0


def _clean(username: str) -> str:
    """Usernames are stored as typed into the sign-in form: folded to lower case."""
    try:
        return accounts_module.clean_username(username)
    except AccountError:
        return username


def _find_user(db: Accounts, username: str):
    wanted = _clean(username)
    return next((u for u in db.users() if u["username"] == wanted), None)


def _named_user(db: Accounts, username: str):
    """:func:`_find_user`, saying so on stderr when there is no such account."""
    user = _find_user(db, username)
    if user is None:
        print(f"error: no account called {username}", file=sys.stderr)
    return user


def _link(db: Accounts, data_dir: Path, args) -> int:
    user = _named_user(db, args.username)
    if user is None:
        return 2
    if args.site_id:
        # Somebody who opened the Workload tab before this was run was given
        # an empty account of their own. It is in the way.
        placeholder = db.site_user(args.site_id)
        if placeholder and placeholder["id"] != user["id"]:
            db.link_site(placeholder["id"], None)
            if db.remove_if_empty(placeholder["id"]):
                storage.remove_user_files(data_dir, placeholder["id"])
            else:
                db.link_site(placeholder["id"], args.site_id,
                             placeholder["site_login"])
                print(f"error: that sign-in already has units here as "
                      f"{placeholder['username']}.", file=sys.stderr)
                return 2
    linked = db.link_site(user["id"], args.site_id, args.login)
    if linked["site_key"]:
        print(f"{linked['username']} is now reached by signing in to the site"
              + (f" as {linked['site_login']}." if linked["site_login"] else "."))
    else:
        print(f"{linked['username']} is no longer linked to a site sign-in.")
    return 0


def _password(db: Accounts, data_dir: Path, args) -> int:
    user = _named_user(db, args.username)
    if user is None:
        return 2
    password, generated = _password_from(args)
    db.set_password(user["id"], password)
    print(f"Password changed for {user['username']}; every session was ended.")
    if generated:
        print(f"  password: {password}")
    return 0


def _remove(db: Accounts, data_dir: Path, args) -> int:
    user = _named_user(db, args.username)
    if user is None:
        return 2
    if not args.yes:
        answer = input(f"Delete {user['username']} and every unit they have? "
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

    user = _named_user(db, args.username)
    if user is None:
        return 2
    source = Path(args.workbook).expanduser()
    if not source.is_file():
        print(f"error: {source} is not there", file=sys.stderr)
        return 2
    unit = db.create_unit(user["id"], args.name or source.stem, "")
    try:
        result = storage.import_workbook(data_dir, user["id"], unit["id"],
                                         source.read_bytes())
    except (library.NotAWorkbook, ValueError) as exc:
        db.delete_unit(user["id"], unit["id"])
        print(f"error: {exc}", file=sys.stderr)
        return 2
    path = result["path"]
    db.set_unit_filename(user["id"], unit["id"], path.name)
    print(f"{source.name} is now {user['username']}'s unit {unit['name']!r}.")
    print(f"  stored at {path}; the workbook itself is not kept or read again")
    return 0


def _restore(db: Accounts, data_dir: Path, args) -> int:
    """The console half of the app's ⭱ button, for a file already on the host."""
    from . import library

    user = _named_user(db, args.username)
    if user is None:
        return 2
    wanted = str(args.unit).strip().lower()
    units = db.units(user["id"])
    unit = next((u for u in units
                 if u["id"] == args.unit or u["name"].strip().lower() == wanted), None)
    if unit is None:
        print(f"error: {args.username} has no unit called {args.unit!r}. "
              f"They have: {', '.join(repr(u['name']) for u in units) or 'none'}",
              file=sys.stderr)
        return 2

    source = Path(args.workbook).expanduser()
    if not source.is_file():
        print(f"error: {source} is not there", file=sys.stderr)
        return 2
    # A unit still on its old workbook is brought across first, so the copy
    # kept of what it had is a database like every other copy.
    found = storage.bring_across(data_dir, user["id"], unit["id"], unit["filename"])
    if found["filename"] != unit["filename"]:
        # The workbook is with the copies now; the unit is its database,
        # whether or not the restore below goes through.
        db.set_unit_filename(user["id"], unit["id"], found["filename"])
    try:
        result = storage.replace_unit_file(data_dir, user["id"], unit["id"],
                                           source.read_bytes())
    except (library.NotAWorkbook, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    db.set_unit_filename(user["id"], unit["id"], result["path"].name)
    print(f"{unit['name']!r} now holds {source.name} "
          f"({source.stat().st_size / 1_048_576:.1f} MB).")
    if result["backup"]:
        print(f"  what it had is kept as {result['backup'].name}")
    return 0


def _bring(db: Accounts, data_dir: Path, args) -> int:
    """Units from a Workload that ran somewhere else, copied into an account here.

    For the day Workload becomes a tab of a bigger site: the old site's folder
    is copied aside first and only the copy is opened, so the old site keeps
    working on exactly what it had, and running this twice brings nothing twice.
    """
    import shutil
    import tempfile

    source = Path(args.source).expanduser()
    if not (source / "accounts.db").is_file():
        print(f"error: {source} is not a Workload folder (no accounts.db in it)",
              file=sys.stderr)
        return 2
    if source.resolve() == Path(data_dir).resolve():
        print("error: that is this folder; name the other one", file=sys.stderr)
        return 2

    target = _pick(db.users(), args.to_user, "here", "--to")
    if target is None:
        return 2

    with tempfile.TemporaryDirectory(prefix="workload-bring-") as scratch:
        copy = Path(scratch) / "copy"
        # Its kept copies are not needed to bring the units, and can be large.
        shutil.copytree(source, copy,
                        ignore=shutil.ignore_patterns(cfg.BACKUP_DIRNAME))
        old = Accounts(copy / "accounts.db")
        owner = _pick([u for u in old.users() if args.from_user or u["units"]],
                      args.from_user, f"at {source}", "--from")
        if owner is None:
            return 2

        have = {u["name"].strip().lower() for u in db.units(target["id"])}
        brought = []
        for unit in old.units(owner["id"]):
            name = unit["name"]
            if name.strip().lower() in have:
                name = f"{name} (old site)"
                if name.strip().lower() in have:
                    print(f"  {unit['name']!r}: already brought, left alone")
                    continue
            try:
                found = storage.bring_across(copy, owner["id"], unit["id"],
                                             unit["filename"])
                storage._checkpoint(found["path"])
                storage._check_unit_database(found["path"])
            except Exception as exc:                    # noqa: BLE001 - said, then skipped
                print(f"  {unit['name']!r}: could not be read ({exc}); skipped")
                continue
            made = db.create_unit(target["id"], name, "")
            dest = storage._target(data_dir, target["id"], made["id"])
            shutil.copyfile(found["path"], dest)
            db.set_unit_filename(target["id"], made["id"], dest.name)
            have.add(name.strip().lower())
            brought.append(made)
            print(f"  {unit['name']!r} is now {target['username']}'s unit {name!r}")

    if brought and not db.open_unit_of(target["id"]):
        db.set_open_unit(target["id"], brought[0]["id"])
    print(f"Brought {len(brought)} unit(s) from {owner['username']} at {source} "
          f"to {target['username']}"
          + (f" ({target['site_login']})" if target.get("site_login") else "")
          + f". Nothing in {source} was changed.")
    if brought:
        print("  Who was given access to them there is not carried over: "
              "give it again from the Team tab.")
    return 0


def _pick(users, wanted: Optional[str], where: str, flag: str):
    """One account out of ``users``: the one named, or the only one there is."""
    if wanted:
        key = str(wanted).strip().lower()
        hits = [u for u in users
                if key in {str(u["username"]).lower(),
                           str(u.get("site_login") or "").lower()}]
        if len(hits) == 1:
            return hits[0]
    elif len(users) == 1:
        return users[0]
    names = ", ".join(u["username"] + (f" ({u['site_login']})" if u.get("site_login") else "")
                      for u in users)
    if wanted:
        print(f"error: no account {wanted!r} {where}. There are: {names or 'none'}",
              file=sys.stderr)
    elif not users:
        print(f"error: no account {where} yet"
              + (" -- open Workload in the site once first, so it has one"
                 if flag == "--to" else ""), file=sys.stderr)
    else:
        print(f"error: more than one account {where}; say which with {flag}. "
              f"There are: {names}", file=sys.stderr)
    return None


def _units(db: Accounts, data_dir: Path, args) -> int:
    """Say what is in each unit, straight from the files, for when the app
    looks empty and the question is whether the data is gone or unreachable."""
    from . import legacy
    from .unit import Unit

    users = db.users()
    if args.username:
        users = [u for u in users if u["username"] == _clean(args.username)]
        if not users:
            print(f"error: no account called {args.username}", file=sys.stderr)
            return 2

    for user in users:
        print(f"{user['username']}:")
        for unit in db.units(user["id"]):
            path = storage.unit_path(data_dir, user["id"], unit["filename"])
            print(f"  {unit['name']!r}  ({unit['filename']})")
            if not path.is_file():
                print("    THE FILE IS MISSING")
                continue
            print(f"    {path}  {storage.size_mb(path):.1f} MB")
            if legacy.is_workbook(path):
                print("    still an old workbook: it becomes the unit's own "
                      "database the first time it is opened")
                continue
            try:
                wb = Unit(path, seed=False)
            except Exception as exc:
                print(f"    cannot be opened: {exc}")
                continue
            store = wb.store
            print(f"    projects {len(wb.projects())}, "
                  f"deliverables {len(wb.deliverables())}, "
                  f"team {', '.join(wb.engineer_names()) or 'nobody yet'}")
            print(f"    timesheet rows: {store.count():,}")
            if store.count():
                print(f"      per person: {store.counts()}")
                low, high = store.date_range()
                print(f"      {low} to {high}, "
                      f"{sum(r['hours'] for r in store.all_rows()):,.1f} hours")
        kept = storage.backups_dir(data_dir, user["id"])
        # By when each was made: the names start with the unit, not the date.
        kept = sorted(kept.glob("*"), key=lambda p: p.stat().st_mtime) \
            if kept.is_dir() else []
        print(f"  backups: {len(kept)}"
              + (f", newest {kept[-1].name}" if kept else ""))
    return 0


def _notify(db: Accounts, data_dir: Path, args) -> int:
    """What the host's scheduled task runs: one look at every unit."""
    from .app import WorkloadApp
    from . import notify

    app = WorkloadApp(data_dir)
    try:
        report = notify.run(app, log=sys.stderr)
    finally:
        app.close_all()
    print(f"{report['accounts']} account(s) with notifications on, "
          f"{report['new']} new, sent to {report['sent']} phone(s)"
          + (f", {report['failed']} failed" if report["failed"] else "") + ".")
    for error in report["errors"]:
        print(f"  {error}", file=sys.stderr)
    return 0


def _check(db, data_dir, args) -> int:
    """The one command to run on a host before -- and after -- a reload."""
    if getattr(args, "wsgi_only", False):
        print(deployment.wsgi_file(data_dir=args.data_dir))
        return 0
    report = deployment.check(args.data_dir)
    print(deployment.render(report))
    return 0 if report.ok else 1


def _password_from(args):
    """The password given or typed, else a generated one; and whether it was."""
    password = args.password or _ask_password()
    generated = password is None
    if generated:
        password = accounts_module.generated_password()
    return password, generated


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
    "link": _link,
    "remove": _remove,
    "import": _import,
    "check": _check,
    "units": _units,
    "restore": _restore,
    "bring": _bring,
    "notify": _notify,
}


if __name__ == "__main__":
    raise SystemExit(main())
