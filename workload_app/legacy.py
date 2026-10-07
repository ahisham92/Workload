"""Bringing a unit made in the workbook days across to its own database.

Until the database, a unit was a Workload workbook -- its registers, its
reference tables, its task list -- with a timesheet database beside it.  This
reads such a workbook once, through the cells the app used to read, and writes
everything into a new unit database alongside the timesheet rows that were
already there.  Ids are kept: a project or deliverable keeps the row number it
had, so the tasks, drawing counts and submissions that point at it still do.

Nothing is written to the workbook or its timesheet database.  Once the unit
is across, the caller keeps them both as a backup.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config as cfg, progress
from .model import as_text
from .tasks import Task
from .unit import Unit
from .xlsx_io import Workbook, col_to_index, from_serial, index_to_col

#: The workbook had room for twelve people, three of them where its own
#: formulas looked and the rest in free space to the right and below.
_SLOTS = 12
_BUILT_IN = 3
_EXTRA_ROW = 100
_DELIVERABLE_SHARE_COLUMNS = ["K", "L", "M"]
_DELIVERABLE_SHARE_EXTRA = "AG"
_PROJECT_SHARE_COLUMNS = ["W", "X", "Y"]
_PROJECT_SHARE_EXTRA = "AB"
_ENGINEER_FIRST_ROW = 20
_AVAILABILITY_FIRST_ROW = 91

#: The blank template's stand-ins, which are nobody.
_PLACEHOLDER = re.compile(r"^Engineer \d+$")


def is_workbook(path: Path) -> bool:
    return Path(path).suffix.lower() in {".xlsx", ".xlsm"}


# --------------------------------------------------------------------------
# reading the workbook
# --------------------------------------------------------------------------

def read_workbook(path: Path, *, with_timesheets: bool = False) -> Dict[str, Any]:
    """Everything a unit held in its workbook, in the shape ``Unit`` loads."""
    wb = Workbook(Path(path))
    years = _availability_years(wb)
    engineers = _engineers(wb, years)
    names = [e["short_name"] for e in engineers]
    projects = _projects(wb, engineers)
    data: Dict[str, Any] = {
        "hours_per_man_month": wb.get_number(
            cfg.SHEET_PROFIT_PLAN, cfg.HOURS_PER_MAN_MONTH_CELL) or 185.0,
        "hours_per_day": wb.get_number(
            cfg.SHEET_CALENDAR, cfg.HOURS_PER_DAY_CELL) or 8.5,
        "plan_year": int(wb.get_number(cfg.SHEET_PROFIT_PLAN, cfg.PLAN_YEAR_CELL)
                         or _dt.date.today().year),
        "as_at": _typed_as_at(wb),
        "availability_years": sorted(years.values()),
        "project_types": _project_types(wb),
        "credit_steps": _credit_steps(wb),
        "scorecard_factors": _scorecard(wb),
        "definitions": _definitions(wb),
        "non_project_codes": _non_project_codes(wb),
        "holidays": _holidays(wb),
        "engineers": engineers,
        "projects": projects,
        "deliverables": _deliverables(wb, engineers),
        "phasing": _phasing(wb, projects),
    }
    tasks, task_settings = _tasks(wb)
    data["tasks"] = tasks
    if task_settings:
        data["task_settings"] = task_settings
    if with_timesheets:
        data["timesheets"] = _timesheet_rows(wb, names)
    return data


def _slot(index: int) -> Dict[str, Any]:
    if index < _BUILT_IN:
        return {"calendar_row": _ENGINEER_FIRST_ROW + index,
                "availability_row": _AVAILABILITY_FIRST_ROW + index,
                "share_column": _DELIVERABLE_SHARE_COLUMNS[index],
                "manual_share_column": _PROJECT_SHARE_COLUMNS[index]}
    offset = index - _BUILT_IN
    return {"calendar_row": _EXTRA_ROW + offset,
            "availability_row": _EXTRA_ROW + offset,
            "share_column": index_to_col(col_to_index(_DELIVERABLE_SHARE_EXTRA) + offset),
            "manual_share_column": index_to_col(col_to_index(_PROJECT_SHARE_EXTRA) + offset)}


def _availability_years(wb: Workbook) -> Dict[str, int]:
    years: Dict[str, int] = {}
    for index in range(col_to_index(cfg.AVAILABILITY_FIRST_COL),
                       col_to_index(cfg.AVAILABILITY_LAST_COL) + 1):
        col = index_to_col(index)
        value = wb.get_number(cfg.SHEET_INPUTS, f"{col}{cfg.AVAILABILITY_HEADER_ROW}")
        if value:
            years[col] = int(value)
    return years


def _engineers(wb: Workbook, years: Dict[str, int]) -> List[Dict[str, Any]]:
    cols = cfg.ENGINEER_COLUMNS
    out = []
    for index in range(_SLOTS):
        slot = _slot(index)
        row = slot["calendar_row"]
        name = wb.get_text(cfg.SHEET_CALENDAR, f"{cols['short_name']}{row}")
        if not name:
            continue
        availability = {}
        for col, year in years.items():
            value = wb.get_number(cfg.SHEET_INPUTS, f"{col}{slot['availability_row']}")
            if value is not None:
                availability[year] = value
        out.append({
            "short_name": name,
            "pattern": wb.get_text(cfg.SHEET_CALENDAR, f"{cols['pattern']}{row}")
            or f"*{name}*",
            "available_hours": wb.get_number(
                cfg.SHEET_CALENDAR, f"{cols['available_hours']}{row}"),
            "availability": availability,
            **slot,
        })
    return out


def _shares(wb: Workbook, sheet: str, row: int, engineers: List[Dict[str, Any]],
            key: str) -> Dict[str, float]:
    out = {}
    for person in engineers:
        value = wb.get_number(sheet, f"{person[key]}{row}")
        if value is not None:
            out[person["short_name"]] = value
    return out


def _projects(wb: Workbook, engineers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cols = cfg.PROJECT_INPUT_COLUMNS
    out = []
    for row in range(cfg.PROJECT_FIRST_ROW, cfg.PROJECT_LAST_ROW + 1):
        number = wb.get_text(cfg.SHEET_INPUTS, f"{cols['number']}{row}")
        if not number:
            continue
        out.append({
            "row": row,
            "number": number,
            "name": wb.get_text(cfg.SHEET_INPUTS, f"{cols['name']}{row}"),
            "budget_mm": wb.get_number(cfg.SHEET_INPUTS, f"{cols['budget_mm']}{row}"),
            "start": wb.get_date(cfg.SHEET_INPUTS, f"{cols['start']}{row}"),
            "end": wb.get_date(cfg.SHEET_INPUTS, f"{cols['end']}{row}"),
            "status": wb.get_text(cfg.SHEET_INPUTS, f"{cols['status']}{row}"),
            "cac_override": wb.get_number(cfg.SHEET_INPUTS, f"{cols['cac_override']}{row}"),
            "notes": wb.get_text(cfg.SHEET_INPUTS, f"{cols['notes']}{row}"),
            "manual_percent": wb.get_number(
                cfg.SHEET_INPUTS, f"{cols['manual_percent']}{row}"),
            "shares": _shares(wb, cfg.SHEET_INPUTS, row, engineers,
                              "manual_share_column"),
        })
    return _first_of_each(out, ("number",))


def _deliverables(wb: Workbook, engineers: List[Dict[str, Any]]
                  ) -> List[Dict[str, Any]]:
    cols = cfg.DELIVERABLE_INPUT_COLUMNS
    acols = cfg.ACTUALS_INPUT_COLUMNS
    out = []
    for row in range(cfg.DELIVERABLE_FIRST_ROW, cfg.DELIVERABLE_LAST_ROW + 1):
        number = wb.get_text(cfg.SHEET_DELIVERABLES, f"{cols['project_number']}{row}")
        if not number:
            continue
        step = wb.get_number(cfg.SHEET_DELIVERABLES, f"{cols['step_no']}{row}")
        phase = wb.get_number(cfg.SHEET_ACTUALS, f"{acols['ts_phase']}{row}")
        item = {
            "row": row,
            "project_number": number,
            "name": wb.get_text(cfg.SHEET_DELIVERABLES, f"{cols['name']}{row}"),
            "type_code": wb.get_text(cfg.SHEET_DELIVERABLES, f"{cols['type_code']}{row}"),
            "phase_weight": wb.get_number(
                cfg.SHEET_DELIVERABLES, f"{cols['phase_weight']}{row}"),
            "step_no": int(step) if step is not None else None,
            "status_date": wb.get_date(
                cfg.SHEET_DELIVERABLES, f"{cols['status_date']}{row}"),
            "notes": wb.get_text(cfg.SHEET_DELIVERABLES, f"{cols['notes']}{row}"),
            "ts_phase": int(phase) if phase is not None else None,
            "shares": _shares(wb, cfg.SHEET_DELIVERABLES, row, engineers,
                              "share_column"),
        }
        for name in cfg.ACTUALS_DATE_FIELDS:
            item[name] = wb.get_date(cfg.SHEET_ACTUALS, f"{acols[name]}{row}")
        out.append(item)
    return out


def _project_types(wb: Workbook) -> List[Dict[str, Any]]:
    cols = cfg.PROJECT_TYPE_COLUMNS
    out = []
    for row in range(cfg.PROJECT_TYPES_FIRST_ROW, cfg.PROJECT_TYPES_LAST_ROW + 1):
        code = wb.get_text(cfg.SHEET_PROJECT_TYPES, f"{cols['code']}{row}")
        if not code:
            continue
        item = {name: wb.get_text(cfg.SHEET_PROJECT_TYPES, f"{col}{row}")
                for name, col in cols.items()}
        item["portfolio_weight"] = wb.get_number(
            cfg.SHEET_PROJECT_TYPES, f"{cols['portfolio_weight']}{row}")
        out.append(item)
    return _first_of_each(out, ("code",))


def _credit_steps(wb: Workbook) -> List[Dict[str, Any]]:
    cols = cfg.RULES_COLUMNS
    out = []
    for row in range(cfg.RULES_FIRST_ROW, cfg.RULES_LAST_ROW + 1):
        code = wb.get_text(cfg.SHEET_RULES, f"{cols['type_code']}{row}")
        step = wb.get_number(cfg.SHEET_RULES, f"{cols['step_no']}{row}")
        if not code or step is None:
            continue
        out.append({
            "type_code": code, "step_no": int(step),
            "step_name": wb.get_text(cfg.SHEET_RULES, f"{cols['step_name']}{row}"),
            "credit": wb.get_number(cfg.SHEET_RULES, f"{cols['credit']}{row}") or 0.0,
            "data_source": wb.get_text(cfg.SHEET_RULES, f"{cols['data_source']}{row}"),
        })
    return _first_of_each(out, ("type_code", "step_no"))


def _first_of_each(items: List[Dict[str, Any]], key: Tuple[str, ...]
                   ) -> List[Dict[str, Any]]:
    """Drop rows repeating an earlier row's key.

    The workbook let a project number or a type code be typed twice; the
    database holds each once, so the first one typed is the one kept.
    """
    seen = set()
    out = []
    for item in items:
        k = tuple(item[name] for name in key)
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def _scorecard(wb: Workbook) -> List[Dict[str, Any]]:
    cols = cfg.SCORECARD_COLUMNS
    out = []
    for offset in range(cfg.SCORECARD_LAST_ROW - cfg.SCORECARD_FIRST_ROW + 1):
        row = cfg.SCORECARD_FIRST_ROW + offset
        label = wb.get_text(cfg.SHEET_SCORECARD, f"{cols['factor']}{row}")
        if not label:
            continue
        direction = wb.get_text(cfg.SHEET_SCORECARD, f"{cols['direction']}{row}")
        out.append({
            "key": cfg.SCORECARD_KEYS[offset] if offset < len(cfg.SCORECARD_KEYS)
            else None,
            "factor": label,
            "weight": wb.get_number(cfg.SHEET_SCORECARD, f"{cols['weight']}{row}") or 0.0,
            "direction": ("higher" if direction == cfg.SCORECARD_DIRECTION_HIGHER
                          else "target"),
            "target": wb.get_number(cfg.SHEET_SCORECARD, f"{cols['target']}{row}"),
            "how": wb.get_text(cfg.SHEET_SCORECARD, f"{cols['how']}{row}"),
        })
    return out


def _definitions(wb: Workbook) -> List[Dict[str, str]]:
    cols = cfg.DEFINITIONS_COLUMNS
    out = []
    for row in range(1, cfg.DEFINITIONS_LAST_ROW + 1):
        field = wb.get_text(cfg.SHEET_DEFINITIONS, f"{cols['field']}{row}")
        means = wb.get_text(cfg.SHEET_DEFINITIONS, f"{cols['means']}{row}")
        if not field or not means or field in {"Field", "What you see"}:
            continue
        out.append({"field": field, "means": means,
                    "how": wb.get_text(cfg.SHEET_DEFINITIONS, f"{cols['how']}{row}")})
    return out


def _non_project_codes(wb: Workbook) -> List[Dict[str, str]]:
    cols = cfg.NON_PROJECT_CODE_COLUMNS
    out = []
    for row in cfg.NON_PROJECT_CODE_ROWS:
        code = wb.get_text(cfg.SHEET_CALENDAR, f"{cols['code']}{row}")
        if code:
            out.append({name: wb.get_text(cfg.SHEET_CALENDAR, f"{col}{row}")
                        for name, col in cols.items()})
    return out


def _holidays(wb: Workbook) -> List[Dict[str, Any]]:
    out = []
    for row in range(cfg.HOLIDAY_FIRST_ROW, cfg.HOLIDAY_LAST_ROW + 1):
        day = _date(wb.get_value(cfg.SHEET_CALENDAR,
                                 f"{cfg.HOLIDAY_COLUMNS['date']}{row}"))
        if day and 2000 <= day.year <= 2100:
            out.append({"day": day, "name": wb.get_text(
                cfg.SHEET_CALENDAR, f"{cfg.HOLIDAY_COLUMNS['name']}{row}")})
    return out


def _typed_as_at(wb: Workbook) -> Optional[str]:
    """The report date, only if somebody typed one: ``=TODAY()`` means today."""
    sheet = wb.sheet(cfg.SHEET_INPUTS)
    if sheet.cell_has_formula(cfg.AS_AT_DATE_CELL):
        return None
    day = wb.get_date(cfg.SHEET_INPUTS, cfg.AS_AT_DATE_CELL)
    return day.isoformat() if day else None


def _phasing(wb: Workbook, projects: List[Dict[str, Any]]
             ) -> Dict[str, Dict[str, float]]:
    """Planned MM typed into the Phasing sheet, by project and quarter start."""
    if cfg.SHEET_PHASING not in wb.sheet_names:
        return {}
    starts: Dict[str, str] = {}
    for index in range(col_to_index(cfg.PHASING_FIRST_COL),
                       col_to_index(cfg.PHASING_LAST_COL) + 1):
        col = index_to_col(index)
        day = wb.get_date(cfg.SHEET_PHASING, f"{col}{cfg.PHASING_START_ROW}")
        if day and day.year >= 2000:
            starts[col] = day.isoformat()
    out: Dict[str, Dict[str, float]] = {}
    for project in projects:
        row = cfg.PHASING_OVERRIDE_FIRST_ROW + (project["row"] - cfg.PROJECT_FIRST_ROW)
        for col, start in starts.items():
            value = wb.get_number(cfg.SHEET_PHASING, f"{col}{row}")
            if value is not None:
                out.setdefault(project["number"], {})[start] = value
    return out


def _date(value: Any) -> Optional[_dt.date]:
    if isinstance(value, (int, float)) and value > 0:
        return from_serial(float(value))
    if isinstance(value, str) and value:
        try:
            return _dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _tasks(wb: Workbook) -> Tuple[List[Task], Optional[Dict[str, Any]]]:
    """The Tasks sheet the app used to keep in the workbook, if it had one."""
    if cfg.SHEET_TASKS not in wb.sheet_names:
        return [], None
    sheet = wb.sheet(cfg.SHEET_TASKS)
    settings = None
    raw = sheet.get_value(cfg.TASKS_SETTINGS_CELL)
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            stored = json.loads(raw)
        except ValueError:
            stored = None
        if isinstance(stored, dict):
            settings = stored
    cols = cfg.TASK_COLUMNS

    def text(ref: str) -> str:
        value = sheet.get_value(ref)
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def number(ref: str) -> Optional[float]:
        value = sheet.get_value(ref)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    out: List[Task] = []
    for row in range(cfg.TASKS_FIRST_ROW, cfg.TASKS_LAST_ROW + 1):
        identifier = sheet.get_value(f"{cols['id']}{row}")
        if identifier in (None, ""):
            continue
        assignees = text(f"{cols['assignees']}{row}")
        deliverable_row = sheet.get_value(f"{cols['deliverable_row']}{row}")
        out.append(Task(
            id=int(identifier),
            name=text(f"{cols['name']}{row}"),
            definition=text(f"{cols['definition']}{row}"),
            project_number=text(f"{cols['project_number']}{row}"),
            deliverable_row=int(deliverable_row)
            if deliverable_row not in (None, "") else None,
            deliverable_name=text(f"{cols['deliverable_name']}{row}"),
            assignees=[a.strip() for a in assignees.split(",") if a.strip()],
            required_hours=number(f"{cols['required_hours']}{row}"),
            actual_hours=number(f"{cols['actual_hours']}{row}"),
            start=_date(sheet.get_value(f"{cols['start']}{row}")),
            due=_date(sheet.get_value(f"{cols['due']}{row}")),
            status=text(f"{cols['status']}{row}") or cfg.TASK_STATUSES[0],
            kind=text(f"{cols['kind']}{row}") or cfg.TASK_KINDS[0],
            series=text(f"{cols['series']}{row}"),
            notes=text(f"{cols['notes']}{row}"),
            progress_mode=text(f"{cols['progress_mode']}{row}")
            or progress.MODE_PRO_RATA,
            stage=text(f"{cols['stage']}{row}") or progress.STAGE_KEYS[0],
            review_code=text(f"{cols['review_code']}{row}").upper(),
            revisions=int(number(f"{cols['revisions']}{row}") or 0),
            pro_rata=number(f"{cols['pro_rata']}{row}"),
        ))
    return out, settings


def _timesheet_rows(wb: Workbook, names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """The rows pasted onto each person's TS sheet, for a unit whose
    timesheet database was never made."""
    sheets = [n for n in wb.sheet_names if n.startswith(cfg.TS_SHEET_PREFIX)]
    mapping: Dict[str, str] = {}
    for name in names:
        wanted = f"{cfg.TS_SHEET_PREFIX}{name}"
        if wanted in sheets:
            mapping[name] = wanted
            sheets.remove(wanted)
    for name in names:
        if name not in mapping and sheets:
            mapping[name] = sheets.pop(0)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for name, sheet in mapping.items():
        rows = []
        for raw in wb.read_table(sheet, cfg.TS_FIRST_DATA_ROW, None,
                                 ["A", "B", "C", "J", "K", "L", "M", "P"]):
            date = raw.get("L")
            hours = raw.get("P")
            phase = raw.get("M")
            if not as_text(raw.get("B")) and not isinstance(hours, (int, float)):
                continue
            rows.append({
                "job_type": as_text(raw.get("A")),
                "job_number": as_text(raw.get("B")).strip(),
                "full_name": as_text(raw.get("C")),
                "regular_hours": float(raw.get("J") or 0.0)
                if isinstance(raw.get("J"), (int, float)) else 0.0,
                "overtime_hours": float(raw.get("K") or 0.0)
                if isinstance(raw.get("K"), (int, float)) else 0.0,
                "date": from_serial(float(date))
                if isinstance(date, (int, float)) and date > 0 else None,
                "phase": int(phase) if isinstance(phase, (int, float)) else None,
                "hours": float(hours) if isinstance(hours, (int, float)) else 0.0,
            })
        if rows:
            out[name] = rows
    return out


# --------------------------------------------------------------------------
# writing the unit
# --------------------------------------------------------------------------

def migrate(workbook: Path, target: Path) -> Dict[str, Any]:
    """Make ``target``, a unit database, from an old unit's two files.

    The workbook and the timesheet database beside it are read, never
    written.  The database is built under a temporary name and only takes
    ``target``'s name once it is complete, so a move that fails part way
    leaves nothing behind that could be mistaken for the unit.
    """
    workbook = Path(workbook)
    target = Path(target)
    old_store = workbook.with_suffix(".timesheets.db")
    partial = target.with_name(target.name + ".partial")
    _remove(partial)
    if old_store.is_file():
        source = sqlite3.connect(old_store)
        copy = sqlite3.connect(partial)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
    try:
        unit = Unit(partial, seed=False)
        data = read_workbook(workbook, with_timesheets=unit.store.is_empty())
        moved = 0
        for person, rows in (data.get("timesheets") or {}).items():
            moved += unit.store.replace(person, rows, source="the workbook")
        unit.seed(data)
        load_registers(unit, data)
        added = _put_everyone_on_the_team(unit)
        summary = {
            "engineers": len(unit.engineers()),
            "projects": len(unit.projects()),
            "deliverables": len(unit.deliverables()),
            "tasks": len(unit.read_tasks()),
            "timesheet_rows": unit.store.count(),
            "rows_from_sheets": moved,
            "people_added": added,
        }
        del unit
    except Exception:
        _remove(partial)
        raise
    os.replace(partial, target)
    return summary


def load_registers(unit: Unit, data: Dict[str, Any]) -> None:
    """The team, the registers, the task list and any phasing, ids and all."""
    placeholders = _unused_placeholders(unit, data)
    engineers = [e for e in data.get("engineers") or []
                 if e["short_name"] not in placeholders]
    with unit._write() as db:                          # noqa: SLF001 - same package
        for position, person in enumerate(engineers):
            db.execute(
                "INSERT OR REPLACE INTO engineers (name, pattern, available_hours, "
                "position) VALUES (?, ?, ?, ?)",
                (person["short_name"], person["pattern"], person["available_hours"],
                 position))
            unit._write_availability(db, person["short_name"], person["availability"])
        for project in data.get("projects") or []:
            db.execute(
                "INSERT INTO projects (row, number, name, budget_mm, start, end, "
                "status, cac_override, notes, manual_percent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project["row"], project["number"], project["name"],
                 project["budget_mm"], _iso(project["start"]), _iso(project["end"]),
                 project["status"], project["cac_override"], project["notes"],
                 project["manual_percent"]))
            for name, share in project["shares"].items():
                db.execute("INSERT INTO project_shares (project_row, engineer, share) "
                           "VALUES (?, ?, ?)", (project["row"], name, share))
        columns = ["row", "project_number", "name", "type_code", "phase_weight",
                   "step_no", "status_date", "notes", "ts_phase",
                   *cfg.ACTUALS_DATE_FIELDS]
        for item in data.get("deliverables") or []:
            db.execute(
                f"INSERT INTO deliverables ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [_iso(item[c]) if isinstance(item[c], _dt.date) else item[c]
                 for c in columns])
            for name, share in item["shares"].items():
                db.execute("INSERT INTO deliverable_shares (deliverable_row, "
                           "engineer, share) VALUES (?, ?, ?)",
                           (item["row"], name, share))
        for number, quarters in (data.get("phasing") or {}).items():
            for start, mm in quarters.items():
                db.execute("INSERT OR REPLACE INTO phasing (project_number, "
                           "quarter_start, mm) VALUES (?, ?, ?)", (number, start, mm))
    if data.get("tasks"):
        unit.write_tasks(data["tasks"])


def _unused_placeholders(unit: Unit, data: Dict[str, Any]) -> set:
    """The template's "Engineer 1, 2, 3" nobody ever replaced: no rows, no
    splits, no tasks.  They would only be ranked against real people."""
    holding = set(unit.store.people_with_rows())
    used = set()
    for item in (data.get("projects") or []) + (data.get("deliverables") or []):
        used |= {name for name, share in item["shares"].items() if share}
    for task in data.get("tasks") or []:
        used |= set(task.assignees)
    return {e["short_name"] for e in data.get("engineers") or []
            if _PLACEHOLDER.match(e["short_name"])
            and e["short_name"] not in holding | used}


def _put_everyone_on_the_team(unit: Unit) -> List[str]:
    """Anybody with timesheet rows the workbook had no room for joins the team."""
    on_team = set(unit.engineer_names())
    full_names: Dict[str, List[str]] = {}
    for full, person in unit.store.names_by_full_name().items():
        full_names.setdefault(person, []).append(full)
    people = []
    for person in unit.store.people_with_rows():
        if person in on_team:
            continue
        names = full_names.get(person) or []
        people.append({
            "short_name": person,
            "pattern": names[0] if len(names) == 1 else f"*{person}*",
            "available_hours": unit.hours_per_man_month(),
            "availability": {year: 1.0 for year in unit.availability_years()},
        })
    return unit.add_engineers(people) if people else []


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, _dt.date) else value


def _remove(path: Path) -> None:
    for each in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"),
                 Path(str(path) + "-journal")):
        try:
            each.unlink()
        except FileNotFoundError:
            pass
