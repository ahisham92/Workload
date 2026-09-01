"""Shared fixtures. Every test runs against the real workbook, on a copy."""

import shutil
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from workload_app.workbook import WorkloadWorkbook   # noqa: E402
from workload_app.xlsx_io import Workbook            # noqa: E402

WORKBOOK = Path(__file__).resolve().parents[1] / "data" / "Workload.xlsx"


@pytest.fixture(scope="session")
def source_path() -> Path:
    if not WORKBOOK.is_file():
        pytest.skip(f"no workbook at {WORKBOOK}")
    return WORKBOOK


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
