"""Where each account's workbooks live on disk.

One folder per account, one file per unit, and a template that ships with the
code so a new unit can be made without anybody having a spreadsheet to hand.

Nothing here takes a filename from a request.  A unit's file is named after the
identifier the database generated for it, so a crafted name cannot walk out of
the account's own folder.
"""

from __future__ import annotations

import datetime as _dt
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from . import config as cfg, library

#: The blank workbook every new unit starts from: the real model -- formulas,
#: charts, reference tables -- with the data taken out.
TEMPLATE_NAME = "template.xlsx"
#: More than anyone runs, and small enough that a full account is obvious.
MAX_UNITS_PER_USER = 12

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


def package_data_dir() -> Path:
    return Path(__file__).resolve().parent / "data"


def template_path() -> Path:
    return package_data_dir() / TEMPLATE_NAME


def user_dir(data_dir: Path, user_id: int) -> Path:
    path = Path(data_dir) / "users" / str(int(user_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def unit_path(data_dir: Path, user_id: int, filename: str) -> Path:
    """The file for one unit, which is always inside that account's folder."""
    name = Path(str(filename or "")).name          # never a path, only a name
    return user_dir(data_dir, user_id) / name


def new_from_template(data_dir: Path, user_id: int, unit_id: str) -> Path:
    template = template_path()
    if not template.is_file():
        raise library.NotAWorkbook(
            "This installation has no blank template. Upload a workbook "
            "instead, or run tools/build_template.py to make one."
        )
    target = _target(data_dir, user_id, unit_id)
    shutil.copy(template, target)
    library.validate(target)                        # never hand out a broken file
    return target


def save_upload(data_dir: Path, user_id: int, unit_id: str, data: bytes) -> Path:
    """Write an uploaded workbook, and keep it only if it really is one."""
    target = _target(data_dir, user_id, unit_id)
    target.write_bytes(data)
    try:
        library.validate(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target


def replace_unit_file(data_dir: Path, user_id: int, unit_id: str,
                      data: bytes) -> Dict[str, Any]:
    """Put a workbook into a unit that already exists.

    This is how a unit is restored from a copy: the file it had is kept as a
    backup first, so a restore is never the thing that loses the last version,
    and the new file is only kept if it really is a Workload workbook.

    The unit's timesheet database goes with the old workbook. Its rows came
    from the file being replaced, so keeping them would leave the unit showing
    one workbook's projects against another's hours; cleared, the rows on the
    incoming file are adopted on the next open, exactly as for a new unit.
    """
    target = _target(data_dir, user_id, unit_id)
    previous = target.read_bytes() if target.is_file() else None
    kept = keep_a_copy(data_dir, user_id, target) if previous else None
    target.write_bytes(data)
    try:
        library.validate(target)
    except Exception:
        # Put back exactly what was there; a refused upload changes nothing.
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(previous)
        raise
    forget_timesheets(target)
    return {"path": target, "backup": kept}


def forget_timesheets(workbook: Path) -> None:
    """Drop a unit's timesheet database, so the workbook is the record again."""
    store = Path(workbook).with_suffix(".timesheets.db")
    for companion in (store, Path(str(store) + "-wal"), Path(str(store) + "-shm")):
        companion.unlink(missing_ok=True)


def remove_unit_file(data_dir: Path, user_id: int, filename: str) -> None:
    path = unit_path(data_dir, user_id, filename)
    path.unlink(missing_ok=True)
    Path(str(path) + ".lock").unlink(missing_ok=True)
    forget_timesheets(path)


def remove_user_files(data_dir: Path, user_id: int) -> None:
    """Everything an account had, including its backups."""
    shutil.rmtree(user_dir(data_dir, user_id), ignore_errors=True)


def keep_a_copy(data_dir: Path, user_id: int, workbook: Path) -> Optional[Path]:
    """A timestamped copy of a workbook, beside the account's other backups."""
    if not Path(workbook).is_file():
        return None
    folder = backups_dir(data_dir, user_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = folder / f"{Path(workbook).stem}-{stamp}{Path(workbook).suffix}"
    shutil.copy2(workbook, dest)
    return dest


def backups_dir(data_dir: Path, user_id: int) -> Path:
    return user_dir(data_dir, user_id) / cfg.BACKUP_DIRNAME


def usage_mb(data_dir: Path, user_id: int) -> float:
    total = 0
    for path in user_dir(data_dir, user_id).rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return round(total / 1_048_576, 2)


def _target(data_dir: Path, user_id: int, unit_id: str) -> Path:
    if not _SAFE_ID.match(str(unit_id or "")):
        raise ValueError(f"{unit_id!r} is not a unit identifier.")
    return user_dir(data_dir, user_id) / f"{unit_id}.xlsx"


def find_orphans(data_dir: Path, user_id: int, keep: Optional[set] = None) -> list:
    """Workbook files in an account's folder that no unit points at."""
    keep = {Path(name).name for name in (keep or set())}
    return [p for p in user_dir(data_dir, user_id).glob("*.xlsx")
            if p.name not in keep]
