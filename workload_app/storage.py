"""Where each account's workbooks live on disk.

One folder per account, one file per unit, and a template that ships with the
code so a new unit can be made without anybody having a spreadsheet to hand.

Nothing here takes a filename from a request.  A unit's file is named after the
identifier the database generated for it, so a crafted name cannot walk out of
the account's own folder.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

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


def remove_unit_file(data_dir: Path, user_id: int, filename: str) -> None:
    path = unit_path(data_dir, user_id, filename)
    path.unlink(missing_ok=True)
    Path(str(path) + ".lock").unlink(missing_ok=True)


def remove_user_files(data_dir: Path, user_id: int) -> None:
    """Everything an account had, including its backups."""
    shutil.rmtree(user_dir(data_dir, user_id), ignore_errors=True)


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
