"""An engineer's own day, and the few things they can say from it.

The page a team member opens each morning: today in order, as the planner
already lays it out for them, with each task's due date; one tap to say a task
is done, stuck, or that they need help; a quick "I'm off on" for leave; and,
for the end of the week, a **ready timesheet** -- their hours by job and phase
from their own plan and tasks, to copy line by line into BISpark.  Nothing is
sent to BISpark: they still enter it there themselves, only faster.

Everything a member can write is decided here, from their own name, never
from anything in the request: a task is theirs only when their name is on it,
and the time off they enter is only ever their own.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import calendar_
from . import config as cfg
from . import tasks as task_sheet
from .model import ValidationError

#: What a member can say about a task, and what each does to it.
DONE, STUCK, HELP, OFF = "done", "stuck", "help", "off"
TASK_MARKS = (DONE, STUCK, HELP)
#: The status a task is given by each mark; help leaves it as it is.
STATUS_FOR = {DONE: cfg.TASK_DONE_STATUS, STUCK: "Blocked"}
#: A note is a line, not a letter.
NOTE_LONGEST = 300
#: Open asks one person can have at once, so a stuck button cannot fill a table.
OPEN_LIMIT = 40
#: How long the lead hears of somebody's new time off.
OFF_NEWS_DAYS = 7
#: Hours are given to the quarter, as the day plan lays them out.
QUARTER = 0.25
#: The line for time that is no project's: meetings, team support.
OVERHEAD = "Meetings and team support"
#: The line for tasks given without a job number.
NO_JOB = "Tasks with no job on them: ask your lead for the code"


class MyDayError(ValidationError):
    pass


def clean_note(value: Any) -> str:
    return " ".join(str(value or "").split())[:NOTE_LONGEST]


def my_task(tasks: Sequence[task_sheet.Task], engineer: str,
            task_id: Any) -> task_sheet.Task:
    """The task, if it is this person's; refused otherwise, whoever's it is."""
    try:
        wanted = int(task_id)
    except (TypeError, ValueError):
        raise MyDayError(["That is not a task."])
    task = next((t for t in tasks if t.id == wanted), None)
    if task is None or engineer not in task.assignees:
        # Not "it is someone else's": the same answer as no task at all.
        raise MyDayError(["That task is not on your list."])
    return task


def quarter(hours: float) -> float:
    return round(round(hours / QUARTER) * QUARTER, 2)


# --------------------------------------------------------------------------
# today
# --------------------------------------------------------------------------

def today_page(*, engineer: str, day: Dict[str, Any], tasks: Sequence[task_sheet.Task],
               marks: Sequence[Dict[str, Any]], away: Sequence[Dict[str, Any]],
               today: _dt.date, project_names: Mapping[str, str]) -> Dict[str, Any]:
    """Today's list in order, what else is open, and what they have said."""
    by_id = {t.id: t for t in tasks}
    mine = [t for t in tasks if engineer in t.assignees]
    open_marks: Dict[int, Dict[str, Any]] = {}
    for mark in marks:
        if mark["cleared_at"] is None and mark["task_id"] is not None \
                and mark["kind"] in TASK_MARKS:
            open_marks[mark["task_id"]] = mark
    done_today = {m["task_id"]: m for m in marks if m["kind"] == DONE
                  and m["cleared_at"] is None
                  and (m["created_at"] or "")[:10] == today.isoformat()}

    def task_view(task: task_sheet.Task) -> Dict[str, Any]:
        mark = open_marks.get(task.id)
        return {
            "id": task.id, "name": task.name, "project": task.project_number,
            "project_name": project_names.get(task.project_number, ""),
            "deliverable": task.deliverable_name, "status": task.status,
            "done": task.done, "due": task.due.isoformat() if task.due else None,
            "overdue": bool(task.due and task.due < today and not task.done),
            "due_today": bool(task.due and task.due == today),
            "hours": round(task.hours_each(), 2),
            "mark": _mark_view(mark) if mark else None,
        }

    me = next((p for p in day["people"] if p["name"] == engineer), None) or {}
    blocks, seen = [], set()
    for block in me.get("blocks", []):
        item = {k: block[k] for k in ("start", "end", "hours", "kind", "title",
                                      "project")}
        item["project_name"] = project_names.get(block["project"], "")
        task = by_id.get(block.get("task_id")) if block.get("task_id") else None
        if task is not None and engineer in task.assignees:
            item["task"] = task_view(task)
            seen.add(task.id)
        blocks.append(item)
    # Done today: still on the page, ticked, with Undo.
    for task_id in done_today:
        task = by_id.get(task_id)
        if task is not None and task.id not in seen and engineer in task.assignees:
            seen.add(task.id)
            blocks.append({"start": "", "end": "", "hours": 0, "kind": "done",
                           "title": task.name, "project": task.project_number,
                           "project_name": project_names.get(task.project_number, ""),
                           "task": task_view(task)})

    later = sorted((t for t in mine if not t.done and t.id not in seen),
                   key=lambda t: (t.due is None, t.due or today, t.id))
    asks = [_mark_view(m) for m in marks if m["kind"] in (STUCK, HELP)
            and (m["cleared_at"] is None
                 or (m["cleared_at"] or "")[:10] == today.isoformat())]
    for ask in asks:
        task = by_id.get(ask["task_id"]) if ask["task_id"] else None
        ask["task_name"] = task.name if task else ""
    return {
        "date": day["date"],
        "working_day": day["working_day"],
        "day_start": day["day_start"],
        "day_end": day["day_end"],
        "away": bool(me.get("away")),
        "hours": me.get("hours", 0.0),
        "free_hours": me.get("free_hours", 0.0),
        "over_hours": me.get("over_hours", 0.0),
        "blocks": blocks,
        "later": [task_view(t) for t in later],
        "asks": asks,
        "off": away,
    }


def _mark_view(mark: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": mark["id"], "kind": mark["kind"], "note": mark["note"],
            "task_id": mark["task_id"], "at": mark["created_at"],
            "seen": mark["cleared_by"] == "lead"}


def my_time_off(absences: Sequence[Dict[str, Any]], marks: Sequence[Dict[str, Any]],
                engineer: str, today: _dt.date) -> List[Dict[str, Any]]:
    """Their own days away from today on; the ones they entered can be taken
    back, the ones the manager entered are shown as the manager's."""
    entered = {m["absence_id"]: m["id"] for m in marks
               if m["kind"] == OFF and m["absence_id"] is not None
               and m["cleared_at"] is None}
    out = []
    for absence in absences:
        if absence["person"] != engineer or absence["end"] < today.isoformat():
            continue
        out.append({"start": absence["start"], "end": absence["end"],
                    "note": absence["note"],
                    "mark_id": entered.get(absence["id"]),
                    "mine": absence["id"] in entered})
    out.sort(key=lambda a: a["start"])
    return out


# --------------------------------------------------------------------------
# the ready timesheet
# --------------------------------------------------------------------------

def recent_phases(rows: Sequence[Dict[str, Any]], engineer: str
                  ) -> Dict[str, Tuple[Optional[int], str]]:
    """The phase this person last booked to on each job, and its name."""
    latest: Dict[str, Tuple[_dt.date, Optional[int], str]] = {}
    for row in rows:
        if row.get("engineer") != engineer or not row.get("date"):
            continue
        job = row.get("job_number") or ""
        seen = latest.get(job)
        if seen is None or row["date"] >= seen[0]:
            latest[job] = (row["date"], row.get("phase"), row.get("deliverable") or "")
    return {job: (phase, name) for job, (_, phase, name) in latest.items()}


def ready_timesheet(*, engineer: str, days: Sequence[_dt.date],
                    plans: Mapping[str, Dict[str, Any]],
                    rows: Sequence[Dict[str, Any]], tasks: Sequence[task_sheet.Task],
                    deliverable_phases: Mapping[int, Optional[int]],
                    project_names: Mapping[str, str], config: Dict[str, Any],
                    leave_code: str, today: _dt.date) -> Dict[str, Any]:
    """Their week by job and phase, ready to copy into BISpark.

    A day already in the timesheets is shown as booked, from those rows; any
    other working day is filled from their plan for it.  Leave is a line of its
    own; meetings and team support, which belong to no project, are one line
    to put on their usual code.
    """
    wanted = {d.isoformat() for d in days}
    booked: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("engineer") == engineer and row.get("date") \
                and row["date"].isoformat() in wanted:
            booked[row["date"].isoformat()].append(row)
    phases = recent_phases(rows, engineer)
    by_id = {t.id: t for t in tasks}
    a_day = task_sheet.hours_per_day(config)

    lines: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def line(job: str, phase: Optional[int], phase_name: str, name: str,
             kind: str) -> Dict[str, Any]:
        key = (job, "" if phase is None else str(phase))
        if key not in lines:
            lines[key] = {"job": job, "name": name, "phase": phase,
                          "phase_name": phase_name, "kind": kind, "hours": {}}
        found = lines[key]
        found["name"] = found["name"] or name
        found["phase_name"] = found["phase_name"] or phase_name
        return found

    def add(target: Dict[str, Any], date: str, hours: float) -> None:
        target["hours"][date] = target["hours"].get(date, 0.0) + hours

    day_views = []
    for day in days:
        date = day.isoformat()
        if booked.get(date):
            source = "booked"
            for row in booked[date]:
                job = row.get("job_number") or ""
                add(line(job, row.get("phase"), row.get("deliverable") or "",
                         row.get("job_name") or project_names.get(job, ""),
                         "booked"), date, row.get("hours") or 0.0)
        elif calendar_.is_away(config, engineer, day):
            source = "off"
            add(line(leave_code, None, "", "Leave", "leave"), date, a_day)
        else:
            plan = plans.get(date) or {}
            me = next((p for p in plan.get("people", []) if p["name"] == engineer),
                      None)
            source = "plan" if day >= today else "plan_past"
            for block in (me or {}).get("blocks", []):
                project = block.get("project") or ""
                if block["kind"] in ("meeting", "management"):
                    add(line("", None, "", OVERHEAD, "overhead"), date, block["hours"])
                    continue
                if not project:
                    add(line("?", None, "", NO_JOB, "no_job"), date, block["hours"])
                    continue
                phase, phase_name = phases.get(project, (None, ""))
                task = by_id.get(block.get("task_id")) if block.get("task_id") else None
                if task is not None and task.deliverable_row is not None \
                        and deliverable_phases.get(task.deliverable_row) is not None:
                    phase = deliverable_phases[task.deliverable_row]
                    phase_name = task.deliverable_name or phase_name
                add(line(project, phase, phase_name, project_names.get(project, ""),
                         "plan"), date, block["hours"])
        day_views.append({"date": date, "source": source})

    out_lines = []
    for item in lines.values():
        hours = {d: quarter(h) for d, h in item["hours"].items() if quarter(h) > 0}
        if not hours:
            continue
        out_lines.append({**item, "hours": hours,
                          "total": quarter(sum(hours.values()))})
    order = {"booked": 0, "plan": 0, "no_job": 1, "leave": 2, "overhead": 3}
    out_lines.sort(key=lambda l: (order.get(l["kind"], 3), l["job"],
                                  l["phase"] if l["phase"] is not None else -1))
    for view in day_views:
        view["total"] = quarter(sum(l["hours"].get(view["date"], 0.0)
                                    for l in out_lines))
    return {
        "days": day_views,
        "lines": out_lines,
        "total": quarter(sum(l["total"] for l in out_lines)),
        "hours_per_day": round(a_day, 2),
        "copy": _copy_text(out_lines, [d["date"] for d in day_views]),
    }


def _copy_text(lines: Sequence[Dict[str, Any]], dates: Sequence[str]) -> str:
    """Tab separated, so it pastes into a sheet or a form a column at a time."""
    head = ["Job", "Phase", "Name"] + [
        _dt.date.fromisoformat(d).strftime("%a %d %b") for d in dates] + ["Total"]
    out = ["\t".join(head)]
    for item in lines:
        out.append("\t".join(
            [item["job"] or "-", "" if item["phase"] is None else str(item["phase"]),
             item["name"]]
            + [f"{item['hours'].get(d, 0):g}" if item["hours"].get(d) else ""
               for d in dates]
            + [f"{item['total']:g}"]))
    return "\n".join(out)
