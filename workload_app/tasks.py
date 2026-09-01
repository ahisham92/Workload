"""Task management: what has to be done, by whom, and whether it fits.

This is deliberately the one part of the app that does **not** feed the
workbook's model.  Nothing here touches a project's actual MM, its progress or
anyone's CPI -- the timesheet remains the only source of what was spent.  Tasks
are the plan beside it: the work in front of the team, split between the people
who share it, measured against the hours a working day actually holds.

The list lives on a sheet of the app's own making, so it travels with the
workbook and survives being mailed to someone else, without any formula in the
file so much as seeing it.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import config as cfg
from .xlsx_io import Workbook, from_serial, to_serial


class TaskError(Exception):
    """A task the sheet will not accept, with every reason at once."""

    def __init__(self, errors: Sequence[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


# --------------------------------------------------------------------------
# the task itself
# --------------------------------------------------------------------------

@dataclass
class Task:
    id: int
    name: str = ""
    definition: str = ""
    project_number: str = ""
    deliverable_row: Optional[int] = None
    deliverable_name: str = ""
    #: Short names.  More than one means the task is shared, and its hours are
    #: split between them.
    assignees: List[str] = field(default_factory=list)
    required_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    start: Optional[_dt.date] = None
    due: Optional[_dt.date] = None
    status: str = cfg.TASK_STATUSES[0]
    kind: str = cfg.TASK_KINDS[0]
    #: Set on generated tasks, so a series can be recognised and not doubled.
    series: str = ""
    notes: str = ""

    @property
    def done(self) -> bool:
        return self.status == cfg.TASK_DONE_STATUS

    def hours_each(self) -> float:
        """A shared task costs each person only their share of it."""
        if not self.required_hours:
            return 0.0
        return self.required_hours / max(1, len(self.assignees))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "definition": self.definition,
            "project_number": self.project_number,
            "deliverable_row": self.deliverable_row,
            "deliverable_name": self.deliverable_name,
            "assignees": list(self.assignees),
            "required_hours": self.required_hours,
            "actual_hours": self.actual_hours,
            "start": _iso(self.start),
            "due": _iso(self.due),
            "status": self.status,
            "kind": self.kind,
            "series": self.series,
            "notes": self.notes,
            "done": self.done,
            "shared": len(self.assignees) > 1,
            "hours_each": round(self.hours_each(), 2),
        }


def _iso(value: Optional[_dt.date]) -> Optional[str]:
    return value.isoformat() if value else None


def _parse_date(value: Any) -> Optional[_dt.date]:
    if value in (None, ""):
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, (int, float)):
        return from_serial(float(value))
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise TaskError([f"{value!r} is not a date the app understands (YYYY-MM-DD)."])


def _parse_hours(value: Any, label: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        hours = float(value)
    except (TypeError, ValueError):
        raise TaskError([f"{label} has to be a number of hours."])
    if hours < 0:
        raise TaskError([f"{label} cannot be negative."])
    return round(hours, 2)


# --------------------------------------------------------------------------
# the sheet
# --------------------------------------------------------------------------

def has_sheet(wb: Workbook) -> bool:
    return cfg.SHEET_TASKS in wb.sheet_names


def ensure_sheet(wb: Workbook) -> bool:
    """Create the task sheet if this workbook has never had one.

    Returns whether it was created, so the caller knows the file changed.
    """
    if has_sheet(wb):
        return False
    wb.add_sheet(cfg.SHEET_TASKS)
    sheet = wb.sheet(cfg.SHEET_TASKS)
    sheet.set_value(
        cfg.TASKS_TITLE_CELL,
        "TASKS - written by the Workload app. No formula in this workbook reads "
        "this sheet; it is the plan, not the record.",
    )
    for name, column in cfg.TASK_COLUMNS.items():
        header = cfg.TASK_HEADERS[list(cfg.TASK_COLUMNS).index(name)]
        sheet.set_value(f"{column}{cfg.TASKS_HEADER_ROW}", header)
    sheet.set_value(cfg.TASKS_SETTINGS_LABEL_CELL, "Settings (edited in the app)")
    _write_settings(wb, dict(cfg.TASK_DEFAULT_SETTINGS))
    return True


def settings(wb: Workbook) -> Dict[str, Any]:
    """The working day, and the defaults the generators use."""
    out = dict(cfg.TASK_DEFAULT_SETTINGS)
    if not has_sheet(wb):
        return out
    raw = wb.sheet(cfg.SHEET_TASKS).get_value(cfg.TASKS_SETTINGS_CELL)
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            stored = json.loads(raw)
        except ValueError:
            stored = {}
        if isinstance(stored, dict):
            out.update({k: v for k, v in stored.items() if k in out})
    out["work_days"] = sorted({int(d) for d in out["work_days"] if 0 <= int(d) <= 6})
    return out


def _write_settings(wb: Workbook, values: Dict[str, Any]) -> None:
    wb.sheet(cfg.SHEET_TASKS).set_value(
        cfg.TASKS_SETTINGS_CELL, json.dumps(values, separators=(",", ":")))


def save_settings(wb: Workbook, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and store the working day. Everything else keeps its value."""
    ensure_sheet(wb)
    current = settings(wb)
    errors: List[str] = []
    updated = dict(current)

    for key in ("day_start", "day_end"):
        if key in data and data[key] not in (None, ""):
            text = str(data[key]).strip()
            try:
                _dt.datetime.strptime(text, "%H:%M")
            except ValueError:
                errors.append(f"{key.replace('_', ' ')} has to be a time like 09:00.")
                continue
            updated[key] = text
    if not errors and _minutes(updated["day_end"]) <= _minutes(updated["day_start"]):
        errors.append("The day has to end after it starts.")

    if "work_days" in data and data["work_days"] is not None:
        days = sorted({int(d) for d in data["work_days"] if 0 <= int(d) <= 6})
        if not days:
            errors.append("A week needs at least one working day.")
        else:
            updated["work_days"] = days

    for key, label, low, high in (
        ("horizon_weeks", "The window", 1, 52),
        ("submission_lead_days", "The run-up to a deliverable", 1, 60),
        ("meeting_weeks", "The meeting series", 1, 104),
    ):
        if key in data and data[key] not in (None, ""):
            try:
                value = int(data[key])
            except (TypeError, ValueError):
                errors.append(f"{label} has to be a whole number.")
                continue
            if not low <= value <= high:
                errors.append(f"{label} has to be between {low} and {high}.")
            else:
                updated[key] = value

    for key, label in (("submission_hours_per_day", "Submission hours a day"),
                       ("meeting_hours", "Meeting hours")):
        if key in data and data[key] not in (None, ""):
            try:
                updated[key] = _parse_hours(data[key], label)
            except TaskError as error:
                errors.extend(error.errors)

    if "meeting_weekday" in data and data["meeting_weekday"] not in (None, ""):
        try:
            weekday = int(data["meeting_weekday"])
        except (TypeError, ValueError):
            weekday = -1
        if not 0 <= weekday <= 6:
            errors.append("The meeting day has to be a day of the week.")
        else:
            updated["meeting_weekday"] = weekday

    if errors:
        raise TaskError(errors)
    _write_settings(wb, updated)
    return updated


def hours_per_day(config: Dict[str, Any]) -> float:
    """The contracted day: 09:00 to 17:30 is 8.5 hours."""
    return (_minutes(config["day_end"]) - _minutes(config["day_start"])) / 60.0


def _minutes(text: str) -> int:
    when = _dt.datetime.strptime(str(text), "%H:%M")
    return when.hour * 60 + when.minute


def read(wb: Workbook) -> List[Task]:
    """Every task on the sheet, in the order it is stored."""
    if not has_sheet(wb):
        return []
    cols = cfg.TASK_COLUMNS
    sheet = wb.sheet(cfg.SHEET_TASKS)
    out: List[Task] = []
    for row in range(cfg.TASKS_FIRST_ROW, cfg.TASKS_LAST_ROW + 1):
        identifier = sheet.get_value(f"{cols['id']}{row}")
        if identifier in (None, ""):
            continue
        assignees = str(sheet.get_value(f"{cols['assignees']}{row}") or "")
        deliverable_row = sheet.get_value(f"{cols['deliverable_row']}{row}")
        out.append(Task(
            id=int(identifier),
            name=_text(sheet, f"{cols['name']}{row}"),
            definition=_text(sheet, f"{cols['definition']}{row}"),
            project_number=_text(sheet, f"{cols['project_number']}{row}"),
            deliverable_row=int(deliverable_row) if deliverable_row not in (None, "")
            else None,
            deliverable_name=_text(sheet, f"{cols['deliverable_name']}{row}"),
            assignees=[a.strip() for a in assignees.split(",") if a.strip()],
            required_hours=_number(sheet, f"{cols['required_hours']}{row}"),
            actual_hours=_number(sheet, f"{cols['actual_hours']}{row}"),
            start=_date(sheet, f"{cols['start']}{row}"),
            due=_date(sheet, f"{cols['due']}{row}"),
            status=_text(sheet, f"{cols['status']}{row}") or cfg.TASK_STATUSES[0],
            kind=_text(sheet, f"{cols['kind']}{row}") or cfg.TASK_KINDS[0],
            series=_text(sheet, f"{cols['series']}{row}"),
            notes=_text(sheet, f"{cols['notes']}{row}"),
        ))
    return out


def _text(sheet, ref: str) -> str:
    value = sheet.get_value(ref)
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(sheet, ref: str) -> Optional[float]:
    value = sheet.get_value(ref)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _date(sheet, ref: str) -> Optional[_dt.date]:
    value = sheet.get_value(ref)
    if isinstance(value, (int, float)) and value > 0:
        return from_serial(float(value))
    if isinstance(value, str) and value:
        try:
            return _dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def write_all(wb: Workbook, tasks: Sequence[Task]) -> None:
    """Rewrite the whole block.

    The sheet holds no formulas and nothing reads it, so rewriting is both safe
    and simpler than patching rows in place -- there is no way to leave a half
    deleted row behind.
    """
    ensure_sheet(wb)
    if len(tasks) > cfg.TASKS_LAST_ROW - cfg.TASKS_FIRST_ROW + 1:
        raise TaskError([
            f"The task sheet holds {cfg.TASKS_LAST_ROW - cfg.TASKS_FIRST_ROW + 1:,} "
            f"tasks. Close some off before adding more."
        ])
    sheet = wb.sheet(cfg.SHEET_TASKS)
    cols = cfg.TASK_COLUMNS
    # Dates are serial numbers underneath; borrowing the register's own date
    # format means the sheet reads as dates in Excel rather than as 46,276.
    date_style = _date_style(wb)
    row = cfg.TASKS_FIRST_ROW
    for task in tasks:
        values = {
            "id": task.id,
            "name": task.name,
            "definition": task.definition,
            "project_number": task.project_number,
            "deliverable_row": task.deliverable_row,
            "deliverable_name": task.deliverable_name,
            "assignees": ", ".join(task.assignees),
            "required_hours": task.required_hours,
            "actual_hours": task.actual_hours,
            "start": to_serial(task.start) if task.start else None,
            "due": to_serial(task.due) if task.due else None,
            "status": task.status,
            "kind": task.kind,
            "series": task.series,
            "notes": task.notes,
        }
        for name, column in cols.items():
            style = date_style if name in ("start", "due") else None
            sheet.set_value(f"{column}{row}", values[name], style=style)
        row += 1

    # Anything the list used to be longer than is cleared, not left dangling.
    while sheet.get_value(f"{cols['id']}{row}") not in (None, ""):
        for column in cols.values():
            sheet.set_value(f"{column}{row}", None)
        row += 1


def _date_style(wb: Workbook) -> Optional[str]:
    """The style the deliverable register uses for a date, if it can be read."""
    try:
        column = cfg.DELIVERABLE_INPUT_COLUMNS["status_date"]
        return wb.sheet(cfg.SHEET_DELIVERABLES).cell_style(
            f"{column}{cfg.DELIVERABLE_FIRST_ROW}")
    except Exception:                      # a workbook without the register
        return None


# --------------------------------------------------------------------------
# changing the list
# --------------------------------------------------------------------------

def validate(data: Dict[str, Any], *, engineers: Sequence[str],
             projects: Sequence[str], task_id: Optional[int] = None) -> Task:
    """Turn a form into a task, or say everything that is wrong with it."""
    errors: List[str] = []

    name = str(data.get("name") or "").strip()
    if not name:
        errors.append("A task needs a name.")

    assignees = data.get("assignees") or []
    if isinstance(assignees, str):
        assignees = [a.strip() for a in assignees.split(",") if a.strip()]
    unknown = [a for a in assignees if a not in engineers]
    if unknown:
        errors.append(
            f"{', '.join(unknown)} is not on this unit's team. "
            f"The team is {', '.join(engineers)}."
        )

    project = str(data.get("project_number") or "").strip()
    if project and project not in projects:
        errors.append(f"{project} is not a project in the register.")

    status = str(data.get("status") or cfg.TASK_STATUSES[0]).strip()
    if status not in cfg.TASK_STATUSES:
        errors.append(f"Status has to be one of {', '.join(cfg.TASK_STATUSES)}.")

    kind = str(data.get("kind") or cfg.TASK_KINDS[0]).strip()
    if kind not in cfg.TASK_KINDS:
        errors.append(f"Kind has to be one of {', '.join(cfg.TASK_KINDS)}.")

    required = actual = None
    start = due = None
    for reader in (
        lambda: _parse_hours(data.get("required_hours"), "Required hours"),
        lambda: _parse_hours(data.get("actual_hours"), "Actual hours"),
        lambda: _parse_date(data.get("start")),
        lambda: _parse_date(data.get("due")),
    ):
        try:
            reader()
        except TaskError as error:
            errors.extend(error.errors)
    if not errors:
        required = _parse_hours(data.get("required_hours"), "Required hours")
        actual = _parse_hours(data.get("actual_hours"), "Actual hours")
        start = _parse_date(data.get("start"))
        due = _parse_date(data.get("due"))
        if start and due and due < start:
            errors.append("A task cannot be due before it starts.")

    deliverable_row = data.get("deliverable_row")
    if deliverable_row in ("", None):
        deliverable_row = None
    else:
        try:
            deliverable_row = int(deliverable_row)
        except (TypeError, ValueError):
            errors.append("The deliverable could not be identified.")
            deliverable_row = None

    if errors:
        raise TaskError(errors)

    return Task(
        id=task_id or 0,
        name=name,
        definition=str(data.get("definition") or "").strip(),
        project_number=project,
        deliverable_row=deliverable_row,
        deliverable_name=str(data.get("deliverable_name") or "").strip(),
        assignees=list(assignees),
        required_hours=required,
        actual_hours=actual,
        start=start,
        due=due,
        status=status,
        kind=kind,
        series=str(data.get("series") or "").strip(),
        notes=str(data.get("notes") or "").strip(),
    )


def next_id(tasks: Iterable[Task]) -> int:
    return max((t.id for t in tasks), default=0) + 1


def save(wb: Workbook, data: Dict[str, Any], *, engineers: Sequence[str],
         projects: Sequence[str], task_id: Optional[int] = None) -> Task:
    """Add a task, or replace the one with this id."""
    existing = read(wb)
    task = validate(data, engineers=engineers, projects=projects, task_id=task_id)
    if task_id is None:
        task.id = next_id(existing)
        existing.append(task)
    else:
        position = next((i for i, t in enumerate(existing) if t.id == task_id), None)
        if position is None:
            raise TaskError([f"There is no task {task_id} to change."])
        # A generated task keeps its series even when edited by hand.
        task.series = task.series or existing[position].series
        existing[position] = task
    write_all(wb, existing)
    return task


def delete(wb: Workbook, task_id: int) -> Dict[str, Any]:
    tasks = read(wb)
    kept = [t for t in tasks if t.id != task_id]
    if len(kept) == len(tasks):
        raise TaskError([f"There is no task {task_id} to delete."])
    write_all(wb, kept)
    return {"deleted": task_id, "remaining": len(kept)}


def delete_series(wb: Workbook, series: str) -> Dict[str, Any]:
    """Drop a whole generated run -- a meeting series, or one deliverable's."""
    tasks = read(wb)
    kept = [t for t in tasks if t.series != series]
    write_all(wb, kept)
    return {"deleted": len(tasks) - len(kept), "series": series}


# --------------------------------------------------------------------------
# the working calendar
# --------------------------------------------------------------------------

def is_working_day(day: _dt.date, config: Dict[str, Any]) -> bool:
    return day.weekday() in config["work_days"]


def working_days(start: _dt.date, end: _dt.date, config: Dict[str, Any]
                 ) -> List[_dt.date]:
    """Every working day from ``start`` to ``end`` inclusive."""
    if end < start:
        return []
    days = []
    day = start
    while day <= end:
        if is_working_day(day, config):
            days.append(day)
        day += _dt.timedelta(days=1)
    return days


# --------------------------------------------------------------------------
# generating the repetitive part
# --------------------------------------------------------------------------

def submission_series(deliverable_row: int) -> str:
    return f"submission:{deliverable_row}"


def generate_submissions(wb: Workbook, deliverables: Sequence[Dict[str, Any]], *,
                         engineers: Sequence[str],
                         config: Optional[Dict[str, Any]] = None,
                         only_row: Optional[int] = None,
                         today: Optional[_dt.date] = None,
                         include_past: bool = False) -> Dict[str, Any]:
    """A daily task through the run-up to every dated deliverable still ahead.

    A submission is never one day's work that lands on the date itself, so a
    deliverable's date pulls a task onto each working day of the week before
    it.  Dates already past are left alone -- nobody needs a to-do list for
    last spring -- unless one deliverable is named, in which case that is
    plainly what was asked for.  Running this again only fills the gaps: a day
    that already has its task, however it was since edited, is untouched.
    """
    ensure_sheet(wb)
    config = config or settings(wb)
    today = today or _dt.date.today()
    existing = read(wb)
    have = {(t.series, t.due) for t in existing}
    identifier = next_id(existing)
    added: List[Task] = []
    covered = 0
    past = 0

    for deliverable in deliverables:
        row = deliverable.get("row")
        due = _parse_date(deliverable.get("status_date"))
        if row is None or due is None:
            continue
        if only_row is not None and row != only_row:
            continue
        if only_row is None and not include_past and due < today:
            past += 1
            continue
        covered += 1
        series = submission_series(int(row))
        window_start = due - _dt.timedelta(days=int(config["submission_lead_days"]))
        days = working_days(window_start, due, config)
        if not days:
            continue
        shares = deliverable.get("shares") or {}
        assignees = [name for name in engineers if (shares.get(name) or 0) > 0]
        for position, day in enumerate(days, start=1):
            if (series, day) in have:
                continue
            name = deliverable.get("name") or f"Deliverable on row {row}"
            task = Task(
                id=identifier,
                name=f"{name} — submission day {position} of {len(days)}",
                definition=(
                    f"Preparation for the {due.isoformat()} submission of "
                    f"{name}."
                ),
                project_number=str(deliverable.get("project_number") or ""),
                deliverable_row=int(row),
                deliverable_name=name,
                assignees=assignees,
                required_hours=float(config["submission_hours_per_day"]),
                start=day,
                due=day,
                status=cfg.TASK_STATUSES[0],
                kind="Submission",
                series=series,
            )
            existing.append(task)
            added.append(task)
            have.add((series, day))
            identifier += 1

    if added:
        write_all(wb, existing)
    return {
        "added": len(added),
        "deliverables": covered,
        "past_deliverables": past,
        "tasks": [t.to_dict() for t in added],
    }


def meeting_series(project_number: str, weekday: int) -> str:
    return f"meeting:{project_number or 'unit'}:{weekday}"


def generate_meetings(wb: Workbook, *, engineers: Sequence[str],
                      project_number: str = "", project_name: str = "",
                      start: Optional[_dt.date] = None,
                      weeks: Optional[int] = None,
                      weekday: Optional[int] = None,
                      hours: Optional[float] = None,
                      config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Put the weekly meeting in once, for as many weeks as it will run.

    The point of the button is that nobody types the same meeting fifty times.
    Re-running it extends the series rather than doubling it.
    """
    ensure_sheet(wb)
    config = config or settings(wb)
    weekday = config["meeting_weekday"] if weekday is None else int(weekday)
    weeks = int(config["meeting_weeks"] if weeks is None else weeks)
    hours = float(config["meeting_hours"] if hours is None else hours)
    if not 0 <= weekday <= 6:
        raise TaskError(["The meeting day has to be a day of the week."])
    if not 1 <= weeks <= 104:
        raise TaskError(["A meeting series runs between 1 and 104 weeks."])

    start = start or _dt.date.today()
    first = start + _dt.timedelta(days=(weekday - start.weekday()) % 7)

    existing = read(wb)
    have = {(t.series, t.due) for t in existing}
    identifier = next_id(existing)
    series = meeting_series(project_number, weekday)
    label = project_name or project_number or "the unit"
    added: List[Task] = []

    for week in range(weeks):
        day = first + _dt.timedelta(weeks=week)
        if (series, day) in have:
            continue
        task = Task(
            id=identifier,
            name=f"Weekly meeting — {label}",
            definition=(
                f"Standing weekly meeting for {label}, every "
                f"{_WEEKDAYS[weekday]}."
            ),
            project_number=project_number,
            assignees=list(engineers),
            required_hours=hours,
            start=day,
            due=day,
            status=cfg.TASK_STATUSES[0],
            kind="Meeting",
            series=series,
        )
        existing.append(task)
        added.append(task)
        identifier += 1

    if added:
        write_all(wb, existing)
    return {"added": len(added), "series": series, "from": _iso(first),
            "weekday": weekday, "hours": hours}


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


# --------------------------------------------------------------------------
# who is overloaded
# --------------------------------------------------------------------------

def load(tasks: Sequence[Task], engineers: Sequence[str],
         config: Dict[str, Any], *, today: Optional[_dt.date] = None,
         weeks: Optional[int] = None) -> Dict[str, Any]:
    """How the open work sits against the hours the team actually has.

    Shared tasks are split between the people who share them, because two
    people on a six hour task are three hours each, not six.  Overdue work and
    work with no date are counted separately: they are real, but they are not
    what makes the next four weeks fit or not fit.
    """
    today = today or _dt.date.today()
    weeks = int(weeks or config["horizon_weeks"])
    end = today + _dt.timedelta(weeks=weeks) - _dt.timedelta(days=1)
    a_day = hours_per_day(config)
    days = working_days(today, end, config)
    capacity = len(days) * a_day

    per: Dict[str, Dict[str, Any]] = {
        name: {
            "engineer": name,
            "hours": 0.0, "tasks": 0,
            "overdue_hours": 0.0, "overdue_tasks": 0,
            "undated_hours": 0.0, "undated_tasks": 0,
            "later_hours": 0.0,
            "done_hours": 0.0, "done_tasks": 0,
            "actual_hours": 0.0,
        }
        for name in engineers
    }
    unassigned = {"hours": 0.0, "tasks": 0}

    for task in tasks:
        share = task.hours_each()
        holders = [a for a in task.assignees if a in per]
        if task.done:
            for name in holders:
                per[name]["done_hours"] += share
                per[name]["done_tasks"] += 1
                per[name]["actual_hours"] += (task.actual_hours or 0.0) / max(
                    1, len(task.assignees))
            continue
        if not holders:
            unassigned["hours"] += task.required_hours or 0.0
            unassigned["tasks"] += 1
            continue
        for name in holders:
            entry = per[name]
            entry["actual_hours"] += (task.actual_hours or 0.0) / max(
                1, len(task.assignees))
            if task.due is None:
                entry["undated_hours"] += share
                entry["undated_tasks"] += 1
            elif task.due < today:
                entry["overdue_hours"] += share
                entry["overdue_tasks"] += 1
            elif task.due <= end:
                entry["hours"] += share
                entry["tasks"] += 1
            else:
                entry["later_hours"] += share

    for entry in per.values():
        booked = entry["hours"] + entry["overdue_hours"]
        entry["load"] = round(booked / capacity, 3) if capacity else None
        entry["days"] = round(booked / a_day, 2) if a_day else None
        entry["overtime_hours"] = round(max(0.0, booked - capacity), 2)
        entry["spare_hours"] = round(max(0.0, capacity - booked), 2)
        entry["verdict"] = _verdict(entry["load"])
        for key in ("hours", "overdue_hours", "undated_hours", "later_hours",
                    "done_hours", "actual_hours"):
            entry[key] = round(entry[key], 2)

    ranked = sorted(per.values(), key=lambda e: -(e["load"] or 0))
    return {
        "from": _iso(today),
        "to": _iso(end),
        "weeks": weeks,
        "working_days": len(days),
        "hours_per_day": round(a_day, 2),
        "capacity_hours": round(capacity, 2),
        "per_engineer": per,
        "busiest": ranked[0]["engineer"] if ranked else None,
        "quietest": ranked[-1]["engineer"] if ranked else None,
        "unassigned": {"hours": round(unassigned["hours"], 2),
                       "tasks": unassigned["tasks"]},
        "open_tasks": sum(1 for t in tasks if not t.done),
        "done_tasks": sum(1 for t in tasks if t.done),
    }


def _verdict(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    if value > cfg.TASK_OVERLOADED_AT:
        return "overloaded"
    if value < cfg.TASK_UNDERLOADED_AT:
        return "underloaded"
    return "on plan"
