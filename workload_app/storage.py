"""Where each account's units live on disk.

One folder per account, one database file per unit, and a folder of copies
beside them.  A unit made in the workbook days is brought across to its own
database the first time it is opened (see ``legacy``); its old files are kept
in the copies folder, untouched.

Nothing here takes a filename from a request.  A unit's file is named after the
identifier the database generated for it, so a crafted name cannot walk out of
the account's own folder.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from . import config as cfg, legacy, library
from .unit import Unit

#: What a unit's file is called after its id.
UNIT_SUFFIX = ".db"
#: How many automatic copies of each unit are kept; older ones are let go.
BACKUPS_KEPT = 20
#: A unit is copied when it is opened, at most this often.
BACKUP_EVERY = _dt.timedelta(hours=12)
#: The first bytes of every SQLite database file.
SQLITE_HEADER = b"SQLite format 3\x00"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


class NotAUnit(library.NotAWorkbook):
    """An upload that is neither a unit's database nor a Workload workbook."""


def user_dir(data_dir: Path, user_id: int) -> Path:
    path = Path(data_dir) / "users" / str(int(user_id))
    path.mkdir(parents=True, exist_ok=True)
    return path


def unit_path(data_dir: Path, user_id: int, filename: str) -> Path:
    """The file for one unit, which is always inside that account's folder."""
    name = Path(str(filename or "")).name          # never a path, only a name
    return user_dir(data_dir, user_id) / name


def new_unit(data_dir: Path, user_id: int, unit_id: str) -> Path:
    """A new unit's database, set up with the built-in reference tables."""
    target = _target(data_dir, user_id, unit_id)
    _remove_database(target)
    Unit(target)
    return target


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    """Hold ``path`` exclusively across worker processes, where the host can."""
    try:
        import fcntl
    except ImportError:                                # pragma: no cover
        yield
        return
    handle = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            os.close(handle)


def bring_across(data_dir: Path, user_id: int, unit_id: str,
                 filename: str) -> Dict[str, Any]:
    """The unit's database, made from its old workbook if it is still one.

    Returns ``{"path", "filename", "moved"}``; ``moved`` describes what came
    across, and is ``None`` when the unit was already a database.  The old
    workbook and timesheet database are moved into the copies folder, so the
    unit can never be read from them again by mistake, and nothing is lost.
    """
    current = unit_path(data_dir, user_id, filename)
    if not legacy.is_workbook(current):
        return {"path": current, "filename": current.name, "moved": None}
    target = _target(data_dir, user_id, unit_id)
    with _exclusive(user_dir(data_dir, user_id) / f".{unit_id}.moving"):
        if target.is_file() and not current.is_file():
            # Another worker brought it across while this one waited.
            return {"path": target, "filename": target.name, "moved": None}
        if not current.is_file():
            raise library.NotAWorkbook("The workbook for this unit is missing.")
        moved = legacy.migrate(current, target)
        kept = _retire(data_dir, user_id, current)
        moved["kept"] = [p.name for p in kept]
    return {"path": target, "filename": target.name, "moved": moved}


def _retire(data_dir: Path, user_id: int, workbook: Path) -> List[Path]:
    """Put a unit's old workbook and timesheet database with the copies."""
    folder = backups_dir(data_dir, user_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = []
    store = workbook.with_suffix(".timesheets.db")
    for path, suffix in ((workbook, workbook.suffix),
                         (store, ".timesheets.db")):
        if path.is_file():
            if path == store:
                _checkpoint(store)
            dest = folder / f"{workbook.stem}-before-database-{stamp}{suffix}"
            shutil.move(str(path), dest)
            kept.append(dest)
        for extra in (Path(str(path) + "-wal"), Path(str(path) + "-shm"),
                      Path(str(path) + ".lock")):
            extra.unlink(missing_ok=True)
    return kept


def _checkpoint(path: Path) -> None:
    """Fold a database's write-ahead log back in, so the file is complete."""
    try:
        db = sqlite3.connect(path)
        try:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()
    except sqlite3.Error:                              # pragma: no cover
        pass


def is_database(data: bytes) -> bool:
    return data[:len(SQLITE_HEADER)] == SQLITE_HEADER


def import_workbook(data_dir: Path, user_id: int, unit_id: str,
                    data: bytes) -> Dict[str, Any]:
    """Make a unit from an old Workload workbook somebody still has.

    The workbook is read once and then thrown away: the unit is its database
    from then on.
    """
    folder = user_dir(data_dir, user_id)
    upload = folder / f".{unit_id}.upload.xlsx"
    upload.write_bytes(data)
    try:
        library.validate(upload)
        target = _target(data_dir, user_id, unit_id)
        _remove_database(target)
        moved = legacy.migrate(upload, target)
    finally:
        upload.unlink(missing_ok=True)
    return {"path": target, "moved": moved}


def replace_unit_file(data_dir: Path, user_id: int, unit_id: str,
                      data: bytes) -> Dict[str, Any]:
    """Put another copy of a unit in place of the one it has.

    The copy is either one of the unit's own databases -- from the copies
    folder -- or an old Workload workbook, which is brought across on the way
    in.  What the unit had is kept as a copy first, so a restore is never the
    thing that loses the last version, and nothing is changed at all unless
    the incoming file really is one or the other.
    """
    target = _target(data_dir, user_id, unit_id)
    folder = user_dir(data_dir, user_id)
    incoming = folder / f".{unit_id}.incoming.db"
    _remove_database(incoming)
    try:
        if is_database(data):
            incoming.write_bytes(data)
            _check_unit_database(incoming)
        else:
            upload = folder / f".{unit_id}.incoming.xlsx"
            upload.write_bytes(data)
            try:
                try:
                    library.validate(upload)
                except library.NotAWorkbook:
                    raise NotAUnit(
                        "That file is neither a copy of a unit nor a Workload "
                        "workbook.")
                legacy.migrate(upload, incoming)
            finally:
                upload.unlink(missing_ok=True)
        kept = keep_a_copy(data_dir, user_id, target) if target.is_file() else None
        _remove_database(target)
        os.replace(incoming, target)
    finally:
        _remove_database(incoming)
    return {"path": target, "backup": kept}


def _check_unit_database(path: Path) -> None:
    try:
        db = sqlite3.connect(path)
        try:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            db.execute("PRAGMA quick_check").fetchone()
        finally:
            db.close()
    except sqlite3.Error:
        raise NotAUnit("That file is damaged, or is not a copy of a unit.")
    if not {"projects", "deliverables", "engineers", "rows"} <= tables:
        raise NotAUnit("That database is not a copy of a unit.")


def remove_unit_file(data_dir: Path, user_id: int, filename: str) -> None:
    """A unit's file goes; its copies stay, in case it was a mistake."""
    path = unit_path(data_dir, user_id, filename)
    _remove_database(path)
    Path(str(path) + ".lock").unlink(missing_ok=True)
    if legacy.is_workbook(path):
        _remove_database(path.with_suffix(".timesheets.db"))


def remove_user_files(data_dir: Path, user_id: int) -> None:
    """Everything an account had, including its copies."""
    shutil.rmtree(user_dir(data_dir, user_id), ignore_errors=True)


def keep_a_copy(data_dir: Path, user_id: int, unit_file: Path) -> Optional[Path]:
    """A dated copy of a unit, beside the account's other copies.

    A database is copied through SQLite itself, so a copy taken while
    somebody else is writing is still a whole one.
    """
    unit_file = Path(unit_file)
    if not unit_file.is_file():
        return None
    folder = backups_dir(data_dir, user_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = folder / f"{unit_file.stem}-{stamp}{unit_file.suffix}"
    if unit_file.suffix == UNIT_SUFFIX:
        source = sqlite3.connect(unit_file)
        copy = sqlite3.connect(dest)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        _prune(folder, unit_file.stem)
    else:
        shutil.copy2(unit_file, dest)
    return dest


def backup_if_due(data_dir: Path, user_id: int, unit_file: Path) -> Optional[Path]:
    """Copy a unit if its newest copy is older than ``BACKUP_EVERY``."""
    unit_file = Path(unit_file)
    newest = latest_backup(data_dir, user_id, unit_file.stem)
    if newest is not None:
        age = _dt.datetime.now() - _dt.datetime.fromtimestamp(newest.stat().st_mtime)
        if age < BACKUP_EVERY:
            return None
    return keep_a_copy(data_dir, user_id, unit_file)


def backups_of(data_dir: Path, user_id: int, unit_id: str) -> List[Path]:
    """A unit's own database copies, oldest first."""
    folder = backups_dir(data_dir, user_id)
    if not folder.is_dir():
        return []
    return sorted(folder.glob(f"{unit_id}-*{UNIT_SUFFIX}"))


def latest_backup(data_dir: Path, user_id: int, unit_id: str) -> Optional[Path]:
    kept = backups_of(data_dir, user_id, unit_id)
    return kept[-1] if kept else None


def _prune(folder: Path, unit_id: str) -> None:
    kept = sorted(folder.glob(f"{unit_id}-*{UNIT_SUFFIX}"))
    for old in kept[:-BACKUPS_KEPT]:
        old.unlink(missing_ok=True)


def backups_dir(data_dir: Path, user_id: int) -> Path:
    return user_dir(data_dir, user_id) / cfg.BACKUP_DIRNAME


def size_mb(path: Path) -> float:
    """A unit's size on disk, its write-ahead log included."""
    total = 0
    for each in (path, Path(str(path) + "-wal")):
        if each.is_file():
            total += each.stat().st_size
    return round(total / 1_048_576, 2)


def _target(data_dir: Path, user_id: int, unit_id: str) -> Path:
    if not _SAFE_ID.match(str(unit_id or "")):
        raise ValueError(f"{unit_id!r} is not a unit identifier.")
    return user_dir(data_dir, user_id) / f"{unit_id}{UNIT_SUFFIX}"


def _remove_database(path: Path) -> None:
    for each in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"),
                 Path(str(path) + "-journal")):
        each.unlink(missing_ok=True)
