"""Is this file really a Workload workbook?

Whether it arrives as an upload or is copied from the template, a file has to
be checked before the rest of the app is handed it: the sheets it names are the
ones every read below depends on.

Finding and remembering workbooks used to live here too.  It does not any more:
an account's units are rows in the database and files in that account's own
folder, so nothing in the app has any business listing the server's disk.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from . import config as cfg

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
