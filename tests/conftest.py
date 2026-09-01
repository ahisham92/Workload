"""Shared fixtures. Every test runs against the real workbook, on a copy."""

import os
import shutil
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from workload_app.workbook import WorkloadWorkbook   # noqa: E402
from workload_app.xlsx_io import Workbook            # noqa: E402

#: The app carries no workbook of its own, so the tests need to be told where
#: one is.  Set WORKLOAD_TEST_WORKBOOK, or drop a copy at data/Workload.xlsx.
ENV_VAR = "WORKLOAD_TEST_WORKBOOK"
DEFAULT = Path(__file__).resolve().parents[1] / "data" / "Workload.xlsx"


def _workbook_path() -> Path:
    override = os.environ.get(ENV_VAR)
    return Path(override).expanduser() if override else DEFAULT


@pytest.fixture(scope="session")
def source_path() -> Path:
    path = _workbook_path()
    if not path.is_file():
        pytest.skip(
            f"no workbook at {path}. Point {ENV_VAR} at your Workload file, or "
            f"put a copy at {DEFAULT.relative_to(Path.cwd())} to run these tests."
        )
    return path


@pytest.fixture
def workbook_copy(source_path, tmp_path) -> Path:
    """A throw-away copy, so a test can write without touching the original."""
    target = tmp_path / "Workload.xlsx"
    shutil.copy(source_path, target)
    return target


@pytest.fixture
def raw(workbook_copy) -> Workbook:
    return Workbook(workbook_copy)


@pytest.fixture
def wb(workbook_copy) -> WorkloadWorkbook:
    return WorkloadWorkbook(workbook_copy)


@pytest.fixture(scope="session")
def readonly_wb(source_path) -> WorkloadWorkbook:
    """Shared read-only handle; do not write through this one."""
    return WorkloadWorkbook(source_path)
