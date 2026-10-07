"""Task management: what has to be done, by whom, and whether it fits.

Nothing here touches a project's actual MM, its progress or anyone's CPI --
the timesheet remains the only source of what was spent.  Tasks are the plan
beside it: the work in front of the team, split between the people who share
it, measured against the hours a working day actually holds.

The list is kept in the unit's own database (see ``unit.py``).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import config as cfg, progress
from .xlsx_io import from_serial


class TaskError(Exception):
    """A task the list will not accept, with every reason at once."""

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
    #: How far along, and how that is arrived at -- see ``progress``.
    progress_mode: str = progress.MODE_PRO_RATA
    stage: str = progress.STAGE_KEYS[0]
    review_code: str = ""
    revisions: int = 0
    #: Only for a pro-rata task: the fraction somebody typed.
    pro_rata: Optional[float] = None

    @property
    def done(self) -> bool:
        return self.status == cfg.TASK_DONE_STATUS

    @property
    def progress(self) -> float:
        return progress.of(self.progress_mode, stage=self.stage,
                           code=self.review_code, revisions=self.revisions,
                           pro_rata=self.pro_rata, done=self.done)

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
            "progress_mode": self.progress_mode,
            "stage": self.stage,
            "stage_label": progress.STAGE_LABEL.get(self.stage, self.stage),
            "review_code": self.review_code,
            "revisions": self.revisions,
            "pro_rata": self.pro_rata,
            "progress": round(self.progress, 4),
            "progress_why": progress.explain(
                self.progress_mode, stage=self.stage, code=self.review_code,
                revisions=self.revisions),
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
# where the list is kept
# --------------------------------------------------------------------------
#
# Every function below that reads or changes the list is handed the place it
# is kept -- the unit -- and asks it for four things: the tasks, a way to write
# them all back, the stored settings, and a way to store those.  Nothing here
# knows that place is a database.

def settings(source: Any) -> Dict[str, Any]:
    """The working day, and the defaults the generators use."""
    out = dict(cfg.TASK_DEFAULT_SETTINGS)
    stored = source.read_task_settings() if source is not None else None
    if isinstance(stored, dict):
        out.update({k: v for k, v in stored.items() if k in out})
    out["work_days"] = sorted({int(d) for d in out["work_days"] if 0 <= int(d) <= 6})
    return out


def _write_settings(source: Any, values: Dict[str, Any]) -> None:
    source.write_task_settings(dict(values))


def save_settings(source: Any, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and store the working day. Everything else keeps its value."""
    current = settings(source)
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
    _write_settings(source, updated)
    return updated


def hours_per_day(config: Dict[str, Any]) -> float:
    """The contracted day: 09:00 to 17:30 is 8.5 hours."""
    return (_minutes(config["day_end"]) - _minutes(config["day_start"])) / 60.0


def _minutes(text: str) -> int:
    when = _dt.datetime.strptime(str(text), "%H:%M")
    return when.hour * 60 + when.minute


def read(source: Any) -> List[Task]:
    """Every task, in the order it is kept."""
    return list(source.read_tasks()) if source is not None else []


def write_all(source: Any, tasks: Sequence[Task]) -> None:
    """Write the whole list back: there is no half-changed list to leave."""
    source.write_tasks(list(tasks))


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

    # How progress is measured, and what the review said about it.
    mode = progress.MODE_PRO_RATA
    stage = progress.STAGE_KEYS[0]
    code = ""
    revisions = 0
    pro_rata = None
    try:
        mode = progress.clean_mode(data.get("progress_mode"))
        stage = progress.clean_stage(data.get("stage"))
        code = progress.clean_code(data.get("review_code"))
        revisions = progress.clean_revisions(data.get("revisions"))
        pro_rata = _parse_fraction(data.get("pro_rata"))
    except progress.ProgressError as error:
        errors.extend(error.errors)
    if mode == progress.MODE_WORKFLOW and stage != progress.SUBMITTED:
        # A code or a resubmission count on a deliverable that has not been
        # submitted is a mistake somebody will otherwise puzzle over later.
        if code or revisions:
            errors.append(
                "A review code and a revision count only make sense once the "
                "deliverable has been submitted.")

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
        progress_mode=mode,
        stage=stage,
        review_code=code,
        revisions=revisions,
        pro_rata=pro_rata,
    )


def _parse_fraction(value: Any) -> Optional[float]:
    """A percentage typed as 60, or a fraction typed as 0.6. Both mean 60%."""
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise TaskError(["Progress has to be a number."])
    if number < 0:
        raise TaskError(["Progress cannot be negative."])
    if number > 100:
        raise TaskError(["Progress cannot be more than 100%."])
    return round(number / 100 if number > 1 else number, 4)


def next_id(tasks: Iterable[Task]) -> int:
    return max((t.id for t in tasks), default=0) + 1


def save(wb: Any, data: Dict[str, Any], *, engineers: Sequence[str],
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


def delete(wb: Any, task_id: int) -> Dict[str, Any]:
    tasks = read(wb)
    kept = [t for t in tasks if t.id != task_id]
    if len(kept) == len(tasks):
        raise TaskError([f"There is no task {task_id} to delete."])
    write_all(wb, kept)
    return {"deleted": task_id, "remaining": len(kept)}


def delete_series(wb: Any, series: str) -> Dict[str, Any]:
    """Drop a whole generated run -- a meeting series, or one deliverable's."""
    tasks = read(wb)
    kept = [t for t in tasks if t.series != series]
    write_all(wb, kept)
    return {"deleted": len(tasks) - len(kept), "series": series}


# --------------------------------------------------------------------------
# the working calendar
# --------------------------------------------------------------------------

def is_working_day(day: _dt.date, config: Dict[str, Any]) -> bool:
    """A day of the working week that is not a public holiday.

    ``holidays`` is only in the config when the caller has added the unit's
    calendar to it; the stored settings never carry it.
    """
    if day.weekday() not in config["work_days"]:
        return False
    holidays = config.get("holidays")
    return not (holidays and day.isoformat() in holidays)


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


def generate_submissions(wb: Any, deliverables: Sequence[Dict[str, Any]], *,
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
        if only_row is None and not include_past:
            # Run-up days already gone would be overdue the moment they exist.
            window_start = max(window_start, today)
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


def generate_meetings(wb: Any, *, engineers: Sequence[str],
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
