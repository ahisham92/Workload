"""Build the blank workbook that ships with the app.

    python tools/build_template.py path/to/Workload.xlsx

The output is `workload_app/data/template.xlsx`: the same model -- every
formula, chart, reference table, validation and printer setting -- with the
data taken out.  A new account starts from it, so nobody's projects, hours or
names travel to anybody else.

What is kept: Project Types, Rules of Credit, the scorecard factors, the
Definitions glossary, the phasing grid, the working calendar's shape and every
formula that reads them.  What is cleared: the project register, the
deliverable register and its actuals, every timesheet row, and the task list.
The three engineer slots are kept but renamed, because a unit's people are the
first thing its owner will set.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workload_app import config as cfg, library, tasks          # noqa: E402
from workload_app.workbook import WorkloadWorkbook              # noqa: E402
from workload_app.xlsx_io import col_to_index, index_to_col     # noqa: E402

TARGET = ROOT / "workload_app" / "data" / "template.xlsx"
#: What the engineers are called before anyone renames them.
PLACEHOLDERS = ["Engineer 1", "Engineer 2", "Engineer 3"]


def clear_registers(wb: WorkloadWorkbook) -> None:
    """Empty the project and deliverable registers, and their actuals."""
    raw = wb.raw

    inputs = raw.sheet(cfg.SHEET_INPUTS)
    columns = list(cfg.PROJECT_INPUT_COLUMNS.values()) + \
        list(cfg.PROJECT_MANUAL_SHARE_COLUMNS)
    for row in range(cfg.PROJECT_FIRST_ROW, cfg.PROJECT_LAST_ROW + 1):
        for column in columns:
            _clear(inputs, f"{column}{row}")

    deliverables = raw.sheet(cfg.SHEET_DELIVERABLES)
    share_columns = list(cfg.DELIVERABLE_SHARE_COLUMNS)
    extra = col_to_index(cfg.DELIVERABLE_SHARE_EXTRA_FIRST_COL)
    share_columns += [index_to_col(extra + i) for i in range(cfg.MAX_ENGINEERS)]
    for row in range(cfg.DELIVERABLE_FIRST_ROW, cfg.DELIVERABLE_LAST_ROW + 1):
        for column in list(cfg.DELIVERABLE_INPUT_COLUMNS.values()) + share_columns:
            _clear(deliverables, f"{column}{row}")

    actuals = raw.sheet(cfg.SHEET_ACTUALS)
    last = wb.actuals_last_row()
    for row in range(cfg.ACTUALS_FIRST_ROW, last + 1):
        for column in cfg.ACTUALS_INPUT_COLUMNS.values():
            _clear(actuals, f"{column}{row}")


def clear_timesheets(wb: WorkloadWorkbook) -> None:
    for engineer in list(wb.ts_sheets()):
        wb.replace_timesheet(engineer, [])


def rename_engineers(wb: WorkloadWorkbook) -> None:
    """Generic names, so a new unit is not handed somebody else's team."""
    for placeholder, engineer in zip(PLACEHOLDERS, list(wb.engineers())):
        if engineer.short_name == placeholder:
            continue
        # Availability and hours are kept: a new unit needs a working capacity
        # from the first day, and its owner edits both on the Team tab.
        wb.update_engineer(engineer.short_name, {
            "short_name": placeholder,
            "pattern": f"*{placeholder}*",
            "available_hours": engineer.available_hours,
            "availability": engineer.availability,
        })


def drop_tasks(wb: WorkloadWorkbook) -> None:
    if tasks.has_sheet(wb.raw):
        wb.raw.remove_sheet(cfg.SHEET_TASKS)


def _clear(sheet, ref: str) -> None:
    """Blank a cell, unless the workbook calculates it."""
    if sheet.cell_has_formula(ref):
        return
    sheet.set_value(ref, None)


def build(source: Path, target: Path = TARGET) -> Path:
    library.validate(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, target)

    wb = WorkloadWorkbook(target)
    clear_timesheets(wb)
    clear_registers(wb)
    drop_tasks(wb)
    rename_engineers(wb)
    wb.save(backup=False)

    library.validate(target)
    check(target)
    return target


def check(path: Path) -> None:
    """Open the result the way the app will, and say what is in it."""
    from workload_app import metrics, reports

    wb = WorkloadWorkbook(path)
    projects = wb.projects()
    deliverables = wb.deliverables()
    rows = sum(len(wb.timesheet_rows(name, ["B"])) for name in wb.ts_sheets())
    overview = metrics.overview(wb, None)
    report = reports.build(wb, "all")

    print(f"  engineers    : {', '.join(wb.engineer_names())}")
    print(f"  projects     : {len(projects)}")
    print(f"  deliverables : {len(deliverables)}")
    print(f"  timesheet    : {rows} row(s)")
    print(f"  project types: {len(wb.project_types())}")
    print(f"  credit steps : {len(wb.credit_steps())}")
    print(f"  scorecard    : {len(wb.scorecard_factors())} factor(s)")
    print(f"  definitions  : {len(wb.definitions())}")
    print(f"  overview     : {overview['portfolio']['budget_mm']} MM in hand")
    print(f"  reports      : {len(report.projects)} project row(s), "
          f"{len(report.quarterly)} quarter(s) with effort")
    assert not projects, "the template still holds projects"
    assert not deliverables, "the template still holds deliverables"
    assert rows == 0, "the template still holds timesheet rows"
    assert wb.project_types(), "the template lost its project types"
    assert wb.credit_steps(), "the template lost its rules of credit"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    source = Path(argv[0]).expanduser()
    target = Path(argv[1]).expanduser() if len(argv) > 1 else TARGET
    print(f"Building {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}"
          f" from {source}")
    build(source, target)
    size = target.stat().st_size / 1_048_576
    print(f"  size         : {size:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
