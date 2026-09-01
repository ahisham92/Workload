"""Finding and remembering workbooks.

The app does not carry a workbook of its own: you point it at yours.  This
module works out which files are plausible candidates, remembers the ones you
have opened, and checks a file really is a Workload workbook before the rest of
the app tries to read it.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config as cfg

SETTINGS_FILE = Path.home() / ".workload_app.json"
MAX_CANDIDATES = 40
#: How long to leave the native file dialog open before giving up on it.
PICKER_TIMEOUT_SECONDS = 300

#: A file has to have these to be a Workload workbook rather than any old xlsx.
#: The paste-target sheets are not listed by name -- another unit's copy names
#: them after its own people -- but at least one has to be there.
REQUIRED_SHEETS = [
    cfg.SHEET_INPUTS, cfg.SHEET_DELIVERABLES, cfg.SHEET_ACTUALS,
    cfg.SHEET_PROJECT_TYPES, cfg.SHEET_RULES, cfg.SHEET_CALENDAR,
    cfg.SHEET_TS_RAW,
]


class NotAWorkbook(ValueError):
    """The chosen file is not a Workload workbook."""


def describe(path: Path) -> Dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "folder": str(path.parent),
        "size_mb": round(stat.st_size / 1_048_576, 2),
        "modified": _dt.datetime.fromtimestamp(stat.st_mtime).isoformat(
            timespec="seconds"),
    }


def check(path: Path) -> List[str]:
    """Return the sheets a Workload workbook needs and this file lacks."""
    if not path.is_file():
        raise NotAWorkbook(f"There is no file at {path}.")
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise NotAWorkbook(f"{path.name} is not an .xlsx file.")
    try:
        with zipfile.ZipFile(path) as zf:
            workbook_xml = zf.read("xl/workbook.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError):
        raise NotAWorkbook(
            f"{path.name} is not readable as a spreadsheet. If it is open in "
            f"Excel, close it and try again."
        )
    import re
    names = {
        m.group(1).replace("&amp;", "&")
        for m in re.finditer(r'<sheet[^>]*\bname="([^"]*)"', workbook_xml)
    }
    missing = [sheet for sheet in REQUIRED_SHEETS if sheet not in names]
    if not any(name.startswith(cfg.TS_SHEET_PREFIX) for name in names):
        missing.append(f"{cfg.TS_SHEET_PREFIX}<engineer>")
    return missing


def validate(path: Path) -> Path:
    """Resolve and check a chosen path, or explain why it will not do."""
    path = Path(path).expanduser()
    try:
        path = path.resolve(strict=True)
    except (OSError, FileNotFoundError):
        raise NotAWorkbook(f"There is no file at {path}.")
    missing = check(path)
    if missing:
        raise NotAWorkbook(
            f"{path.name} does not look like the Workload workbook — it has no "
            f"{', '.join(missing[:4])} sheet"
            + ("s" if len(missing) > 1 else "")
            + ("." if len(missing) <= 4 else f", and {len(missing) - 4} more.")
        )
    if not os.access(path, os.W_OK):
        raise NotAWorkbook(f"{path.name} is read-only; the app cannot save to it.")
    return path


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------
#
# A unit is a name and the workbook that belongs to it -- Marine Structures and
# its file, another discipline and its own.  Keeping them side by side is what
# lets you put one down, work on another, and come back to the first.

def _load() -> Dict[str, Any]:
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _store(data: Dict[str, Any]) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2))
    except OSError:
        pass          # remembering is a convenience, never a reason to fail


def _unit_id(name: str, path: Path) -> str:
    import hashlib

    digest = hashlib.sha1(f"{name}|{path}".encode("utf-8")).hexdigest()
    return digest[:12]


def units() -> List[Dict[str, Any]]:
    """Saved units, most recently opened first, with their file's state."""
    out: List[Dict[str, Any]] = []
    for entry in _load().get("units", []):
        path = Path(entry.get("workbook", ""))
        record = {
            "id": entry.get("id") or _unit_id(entry.get("name", ""), path),
            "name": entry.get("name") or path.stem,
            "workbook": str(path),
            "opened": entry.get("opened"),
            "exists": path.is_file(),
        }
        if record["exists"]:
            try:
                # Only the file's own details; the unit keeps the name you gave it.
                details = describe(path)
                record.update({k: details[k] for k in
                               ("folder", "size_mb", "modified")})
                record["file_name"] = details["name"]
            except OSError:
                record["exists"] = False
        out.append(record)
    out.sort(key=lambda u: (u["opened"] or ""), reverse=True)
    return out


def find_unit(unit_id: str) -> Optional[Dict[str, Any]]:
    for unit in units():
        if unit["id"] == unit_id:
            return unit
    return None


def save_unit(name: str, path: Path) -> Dict[str, Any]:
    """Add or update a unit, and mark it as the one just opened."""
    name = (name or path.stem).strip()
    data = _load()
    entries = [
        e for e in data.get("units", [])
        if not (e.get("workbook") == str(path) and e.get("name") == name)
    ]
    record = {
        "id": _unit_id(name, path),
        "name": name,
        "workbook": str(path),
        # Microseconds, not seconds: two units opened in the same second would
        # otherwise tie and the order would stop meaning anything.
        "opened": _dt.datetime.now().isoformat(),
    }
    data["units"] = [record] + entries
    _store(data)
    return record


def touch_unit(unit_id: str) -> None:
    """Mark a unit as the one just opened, so it sorts to the front."""
    data = _load()
    entries = data.get("units", [])
    for entry in entries:
        if entry.get("id") == unit_id:
            entry["opened"] = _dt.datetime.now().isoformat()
    data["units"] = (
        [e for e in entries if e.get("id") == unit_id]
        + [e for e in entries if e.get("id") != unit_id]
    )
    _store(data)


def forget_unit(unit_id: str) -> None:
    """Remove a unit from the list.  The workbook itself is left alone."""
    data = _load()
    data["units"] = [e for e in data.get("units", []) if e.get("id") != unit_id]
    _store(data)


def rename_unit(unit_id: str, name: str) -> None:
    data = _load()
    for entry in data.get("units", []):
        if entry.get("id") == unit_id:
            entry["name"] = name.strip() or entry.get("name")
    _store(data)


# --------------------------------------------------------------------------
# the operating system's own file dialog
# --------------------------------------------------------------------------

_PICKER_SCRIPT = """
import sys
try:
    import tkinter
    from tkinter import filedialog
except Exception:
    sys.exit(3)
root = tkinter.Tk()
root.withdraw()
root.attributes('-topmost', True)
path = filedialog.askopenfilename(
    title='Choose your Workload workbook',
    filetypes=[('Excel workbook', '*.xlsx *.xlsm'), ('All files', '*.*')],
)
root.destroy()
sys.stdout.write(path or '')
"""


def pick_file() -> Optional[str]:
    """Open the operating system's file dialog and return what was chosen.

    Runs in a subprocess: the toolkit insists on owning the main thread, which
    the web server already has.  ``None`` means the dialog was cancelled;
    a missing toolkit raises, so the caller can fall back to typing a path.
    """
    import subprocess
    import sys

    try:
        finished = subprocess.run(
            [sys.executable, "-c", _PICKER_SCRIPT],
            capture_output=True, text=True, timeout=PICKER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise NotAWorkbook("The file dialog was left open too long.")
    except OSError as exc:
        raise NotAWorkbook(f"Could not open a file dialog ({exc}).")
    if finished.returncode == 3:
        raise NotAWorkbook(
            "This Python has no file dialog available (tkinter is missing). "
            "Paste the full path instead, or use Browse folders below."
        )
    if finished.returncode != 0:
        raise NotAWorkbook("The file dialog could not be opened.")
    chosen = finished.stdout.strip()
    return chosen or None


# --------------------------------------------------------------------------
# looking around
# --------------------------------------------------------------------------

def candidates(extra: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Spreadsheets in the usual places, newest first.

    Only a shallow look: the working directory two levels down, plus the
    folders a download or a shared drive copy normally lands in.
    """
    home = Path.home()
    roots = [Path.cwd()]
    roots += [home / name for name in ("Desktop", "Documents", "Downloads", "OneDrive")]
    if extra:
        roots.append(Path(extra))

    seen: Dict[str, Dict[str, Any]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in _walk(root, depth=2):
            key = str(path)
            if key not in seen:
                try:
                    seen[key] = describe(path)
                except OSError:
                    continue
    found = sorted(seen.values(), key=lambda item: item["modified"], reverse=True)
    return found[:MAX_CANDIDATES]


def _walk(root: Path, depth: int) -> List[Path]:
    out: List[Path] = []
    try:
        entries = sorted(root.iterdir())
    except (OSError, PermissionError):
        return out
    for entry in entries:
        name = entry.name
        if name.startswith((".", "~$")):
            continue
        if entry.is_dir():
            if depth > 0 and name not in {cfg.BACKUP_DIRNAME, "__pycache__",
                                          "node_modules", "venv", ".venv"}:
                out.extend(_walk(entry, depth - 1))
        elif entry.suffix.lower() in {".xlsx", ".xlsm"}:
            out.append(entry)
    return out


def browse(folder: Optional[str]) -> Dict[str, Any]:
    """List one folder: its sub-folders and its spreadsheets."""
    path = Path(folder).expanduser() if folder else Path.cwd()
    try:
        path = path.resolve(strict=True)
    except OSError:
        raise NotAWorkbook(f"There is no folder at {folder}.")
    if not path.is_dir():
        path = path.parent
    folders: List[Dict[str, str]] = []
    files: List[Dict[str, Any]] = []
    try:
        for entry in sorted(path.iterdir()):
            if entry.name.startswith((".", "~$")):
                continue
            if entry.is_dir():
                folders.append({"name": entry.name, "path": str(entry)})
            elif entry.suffix.lower() in {".xlsx", ".xlsm"}:
                try:
                    files.append(describe(entry))
                except OSError:
                    continue
    except PermissionError:
        raise NotAWorkbook(f"No permission to read {path}.")
    return {
        "folder": str(path),
        "parent": str(path.parent) if path.parent != path else None,
        "folders": folders,
        "files": files,
    }
