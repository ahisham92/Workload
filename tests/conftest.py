"""Shared fixtures.

Every test runs against a unit made from the real workbook, on a copy.  The
unit is its own database; the workbook is only where its data came from, the
way an old unit is brought across the first time it is opened.
"""

import os
import shutil
import sqlite3
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from workload_app import legacy                      # noqa: E402
from workload_app.unit import Unit                   # noqa: E402
from workload_app.xlsx_io import Workbook            # noqa: E402

#: The app carries no workbook of its own, so the tests need to be told where
#: one is.  Set WORKLOAD_TEST_WORKBOOK, or drop a copy at data/Workload.xlsx.
ENV_VAR = "WORKLOAD_TEST_WORKBOOK"
DEFAULT = Path(__file__).resolve().parents[1] / "data" / "Workload.xlsx"

#: The day the reports are counted to.  The workbook worked it out with a
#: formula; the figures the report tests check were taken on this day.
AS_AT = "2026-09-01"


def _workbook_path() -> Path:
    override = os.environ.get(ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT


def copy_unit(source: Path, target: Path) -> Path:
    """A whole copy of a unit's database, through SQLite."""
    target = Path(target)
    for extra in ("", "-wal", "-shm"):
        Path(str(target) + extra).unlink(missing_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


@pytest.fixture(scope="session")
def source_path() -> Path:
    path = _workbook_path()
    if not path.is_file():
        pytest.skip(
            f"no workbook at {path}. Point {ENV_VAR} at your Workload file, or "
            f"put a copy at {DEFAULT.relative_to(Path.cwd())} to run these tests."
        )
    return path


@pytest.fixture(scope="session")
def migrated(source_path, tmp_path_factory) -> Path:
    """The real workbook brought across into a unit, once per run."""
    target = tmp_path_factory.mktemp("migrated") / "unit.db"
    legacy.migrate(source_path, target)
    Unit(target).save_settings({"as_at": AS_AT})
    return target


@pytest.fixture
def workbook_copy(source_path, tmp_path) -> Path:
    """A throw-away copy of the workbook, for the tests that bring one in."""
    target = tmp_path / "Workload.xlsx"
    shutil.copy(source_path, target)
    return target


@pytest.fixture
def unit_copy(migrated, tmp_path) -> Path:
    """A throw-away copy of the unit, so a test can write without worry."""
    return copy_unit(migrated, tmp_path / "unit.db")


@pytest.fixture
def raw(workbook_copy) -> Workbook:
    """The workbook the unit came from, to check the figures against."""
    return Workbook(workbook_copy)


@pytest.fixture
def wb(unit_copy) -> Unit:
    return Unit(unit_copy)


@pytest.fixture(scope="session")
def readonly_wb(migrated) -> Unit:
    """Shared handle; do not write through this one."""
    return Unit(migrated)


#: Projects of the test workbook, by their place in its register.  The tests
#: name a project this way rather than by its job number, which is real and
#: has no business in a public repository.
FIRST_PROJECT = 0      # its first deliverable is the register's first
BUSY_PROJECT = 2       # all three engineers booked to it, several on phase 4
FINISHED_PROJECT = 14  # fully earned, with a CPI well over one


@pytest.fixture(scope="session")
def project_numbers(readonly_wb) -> list:
    """The test workbook's project numbers, in register order."""
    return [p.number for p in readonly_wb.projects()]
