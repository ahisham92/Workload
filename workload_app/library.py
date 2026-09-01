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
MAX_RECENT = 10
MAX_CANDIDATES = 40

#: A file has to have these to be a Workload workbook rather than any old xlsx.
REQUIRED_SHEETS = [
    cfg.SHEET_INPUTS, cfg.SHEET_DELIVERABLES, cfg.SHEET_ACTUALS,
    cfg.SHEET_PROJECT_TYPES, cfg.SHEET_RULES, cfg.SHEET_CALENDAR,
    cfg.SHEET_TS_RAW, *cfg.TS_SHEETS.values(),
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
    return [sheet for sheet in REQUIRED_SHEETS if sheet not in names]


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
# remembering
# --------------------------------------------------------------------------

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


def recent() -> List[Dict[str, Any]]:
    """Recently opened workbooks that are still on disk."""
    out: List[Dict[str, Any]] = []
    for entry in _load().get("recent", []):
        path = Path(entry)
        if path.is_file():
            out.append(describe(path))
    return out


def remember(path: Path) -> None:
    data = _load()
    entries = [str(path)] + [
        e for e in data.get("recent", []) if e != str(path)
    ]
    data["recent"] = entries[:MAX_RECENT]
    _store(data)


def forget(path: Path) -> None:
    data = _load()
    data["recent"] = [e for e in data.get("recent", []) if e != str(path)]
    _store(data)


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
