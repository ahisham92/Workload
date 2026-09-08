"""Is this installation set up correctly, and what should the host's file say?

Running a second web app beside an existing one is where deployments go wrong,
and they go wrong quietly: the wrong source directory, a virtualenv shared with
the other app, or -- the one that loses data -- a data directory inside the
code, which the next ``git pull`` or redeploy walks over.

``python -m workload_app.admin check`` answers all of that from the outside:
what this checkout is, where its data would live, what is wrong with that, and
the exact text to paste into the host's WSGI file for *this* checkout.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import accounts as accounts_module, storage

#: The app is written for this and tested on it; older Pythons lack
#: ``Path.unlink(missing_ok=)`` and the SQLite upsert the accounts use.
MINIMUM_PYTHON = (3, 9)


@dataclass
class Finding:
    level: str          # "ok" | "warn" | "bad"
    title: str
    detail: str = ""

    @property
    def mark(self) -> str:
        return {"ok": "ok  ", "warn": "warn", "bad": "BAD "}[self.level]


@dataclass
class Report:
    root: Path
    data_dir: Path
    findings: List[Finding] = field(default_factory=list)

    def add(self, level: str, title: str, detail: str = "") -> None:
        self.findings.append(Finding(level, title, detail))

    @property
    def ok(self) -> bool:
        return not any(f.level == "bad" for f in self.findings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "ok": self.ok,
            "findings": [
                {"level": f.level, "title": f.title, "detail": f.detail}
                for f in self.findings
            ],
        }


def suggested_data_dir() -> Path:
    """Where the data should live on a host: outside the code, in $HOME."""
    return Path.home() / "workload-data"


def check(data_dir: Optional[Path] = None) -> Report:
    """Everything worth knowing before a deploy is reloaded."""
    root = Path(__file__).resolve().parent.parent
    resolved = Path(data_dir).expanduser().resolve() if data_dir \
        else accounts_module.data_dir().expanduser().resolve()
    report = Report(root=root, data_dir=resolved)

    _check_python(report)
    _check_dependencies(report)
    _check_code(report, root)
    _check_data_dir(report, root, resolved)
    _check_accounts(report, resolved)
    return report


def _check_python(report: Report) -> None:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] >= MINIMUM_PYTHON:
        report.add("ok", f"Python {version}",
                   f"the interpreter at {sys.executable}")
    else:
        wanted = ".".join(str(p) for p in MINIMUM_PYTHON)
        report.add("bad", f"Python {version} is too old",
                   f"this app needs {wanted} or newer. On the host, pick a "
                   f"newer Python when you make the virtualenv, and set the "
                   f"same version on the Web tab.")


def _check_dependencies(report: Report) -> None:
    try:
        import openpyxl                                    # noqa: F401
    except ImportError:
        report.add("bad", "openpyxl is not installed",
                   "run: pip install -r requirements.txt  (with the "
                   "virtualenv for THIS web app activated)")
        return
    report.add("ok", f"openpyxl {openpyxl.__version__}",
               "the only dependency; everything else is the standard library")


def _check_code(report: Report, root: Path) -> None:
    template = storage.template_path()
    if template.is_file():
        size = template.stat().st_size / 1_048_576
        report.add("ok", f"Blank template present ({size:.1f} MB)",
                   str(template))
    else:
        report.add("warn", "No blank template in this checkout",
                   "'Start blank' will not work; accounts can still upload a "
                   "workbook. Build one with tools/build_template.py.")

    missing = [name for name in ("index.html", "login.html", "member.html",
                                 "app.js", "member.js", "app.css", "charts.js")
               if not (root / "workload_app" / "static" / name).is_file()]
    if missing:
        report.add("bad", "The front end is incomplete",
                   f"missing: {', '.join(missing)}")
    else:
        report.add("ok", "Front end complete",
                   str(root / "workload_app" / "static"))


def _check_data_dir(report: Report, root: Path, data_dir: Path) -> None:
    configured = os.environ.get("WORKLOAD_DATA_DIR")
    inside_code = data_dir == root or root in data_dir.parents

    if configured and inside_code:
        # Somebody pointed it at the code on purpose. This is the mistake that
        # loses everyone's workbooks.
        report.add("bad", f"Data directory: {data_dir}",
                   f"WORKLOAD_DATA_DIR puts the data inside {root}. A deploy "
                   f"replaces the code, so it would take the accounts and "
                   f"every workbook with it. Point it outside the checkout, "
                   f"e.g. {suggested_data_dir()}.")
    elif configured:
        report.add("ok", f"Data directory: {data_dir}",
                   "from WORKLOAD_DATA_DIR, and outside the code, so a deploy "
                   "cannot touch it")
    elif inside_code:
        report.add("warn", f"Data directory: {data_dir}",
                   f"the default beside the code, which is right for running "
                   f"it on your own machine and wrong on a host: a deploy "
                   f"replaces the code. On a host set WORKLOAD_DATA_DIR to "
                   f"something outside it, e.g. {suggested_data_dir()} -- the "
                   f"WSGI file below already does.")
    else:
        report.add("warn", f"Data directory: {data_dir}",
                   "WORKLOAD_DATA_DIR is not set, so this is the default. On "
                   "a host, set it explicitly in the WSGI file.")

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report.add("bad", "The data directory cannot be created", str(exc))
        return

    probe = data_dir / ".write-test"
    try:
        probe.write_text("x")
        probe.unlink()
        report.add("ok", "The data directory is writable")
    except OSError as exc:
        report.add("bad", "The data directory is not writable",
                   f"{exc}. The app saves every change, so it cannot run.")

    users = data_dir / "users"
    if users.is_dir():
        workbooks = list(users.rglob("*.xlsx"))
        size = sum(p.stat().st_size for p in data_dir.rglob("*") if p.is_file())
        report.add("ok",
                   f"{len(workbooks)} workbook(s), {size / 1_048_576:.1f} MB in all",
                   "including the timestamped backup before every save")


def _check_accounts(report: Report, data_dir: Path) -> None:
    database = data_dir / "accounts.db"
    try:
        accounts = accounts_module.Accounts(database)
        users = accounts.users()
    except Exception as exc:                               # pragma: no cover
        report.add("bad", "The account database cannot be opened", str(exc))
        return

    if not users:
        report.add("warn", "No accounts yet",
                   "nobody can sign in. Make the first one with:  "
                   "python -m workload_app.admin add <username> --admin")
        return

    managers = [u for u in users if u["role"] == accounts_module.ROLE_MANAGER]
    members = [u for u in users if u["role"] == accounts_module.ROLE_MEMBER]
    admins = [u for u in users if u["is_admin"]]
    report.add("ok" if admins else "bad",
               f"{len(users)} account(s): {len(managers)} manager(s), "
               f"{len(members)} team member(s)",
               f"administrators: {', '.join(u['username'] for u in admins)}"
               if admins else
               "no administrator, so no new account can be made from the app. "
               "Fix with: python -m workload_app.admin add <username> --admin")


# --------------------------------------------------------------------------
# what to paste into the host
# --------------------------------------------------------------------------

def wsgi_file(root: Optional[Path] = None,
              data_dir: Optional[Path] = None) -> str:
    """The host's WSGI file, with this checkout's real paths already in it."""
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    resolved = (Path(data_dir).expanduser().resolve() if data_dir
                else accounts_module.data_dir().expanduser().resolve())
    # Never hand back a data directory that a deploy would overwrite.
    if resolved == root or root in resolved.parents:
        resolved = suggested_data_dir().resolve()
    return f'''\
import os
import sys

# This web app's own code. Another web app on this account has its own line
# here pointing somewhere else; the two must never be the same directory.
path = {str(root)!r}
if path not in sys.path:
    sys.path.insert(0, path)

# Accounts and workbooks, outside the code so a deploy cannot touch them, and
# not shared with any other web app on this account.
os.environ['WORKLOAD_DATA_DIR'] = {str(resolved)!r}

from workload_app.wsgi import application       # noqa: E402,F401
'''


def static_files(root: Optional[Path] = None) -> List[Dict[str, str]]:
    """The static mappings to add on the host's Web tab."""
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    static = root / "workload_app" / "static"
    return [{"url": f"/{name}", "path": str(static / name)}
            for name in ("app.css", "app.js", "member.js", "charts.js")]


def render(report: Report, *, show_wsgi: bool = True) -> str:
    """The whole check as something to read in a console."""
    lines = [
        "Workload deployment check",
        f"  code : {report.root}",
        f"  data : {report.data_dir}",
        "",
    ]
    for finding in report.findings:
        lines.append(f"  [{finding.mark}] {finding.title}")
        if finding.detail:
            lines.append(f"          {finding.detail}")
    lines.append("")
    lines.append("Ready to serve." if report.ok
                 else "Not ready: fix the BAD lines above.")

    if show_wsgi:
        lines += ["", "-- WSGI file for this checkout "
                      "(Web tab -> WSGI configuration file) --", ""]
        lines += [f"  {line}" for line in wsgi_file(
            report.root, report.data_dir).splitlines()]
        lines += ["", "-- Static files (Web tab -> Static files) --", ""]
        for mapping in static_files(report.root):
            lines.append(f"  {mapping['url']:<12} {mapping['path']}")
    return "\n".join(lines)
