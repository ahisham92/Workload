"""What a new piece of work does to the plan, before it is added.

A request can go in two ways:

* **urgent** -- it starts at the first free moment from now, on top of the
  day's planned work, as requests always have.  What it pushes aside is the
  planned work that no longer fits in those days.
* **when there is room** -- it waits for the first day the person's planned
  tasks and meetings leave room for it, so it pushes only their usual project
  work and no task goes late, but it may finish later than wanted.

For an urgent one the manager is shown the cost before saying yes: the
planned work it pushes, by task and by job, which tasks would then miss their
due date and by how much, and the hours of overtime it would take to keep
everything on time.  The same is worked out for the few others who could take
it, so a cheaper choice is one tap away.

Everything here is worked out from ``daily.plan_day``, the same day plan
everybody sees, laid out once without the new work and once with it.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import config as cfg
from . import tasks as task_sheet

URGENT, ROOM = "urgent", "room"
URGENCIES = (URGENT, ROOM)
#: Working days ahead the effect is followed for.
WINDOW_DAYS = 10
#: Other people a cost is worked out for.
ALTERNATIVES = 3
#: Planned work moved by less than this is not worth a line.
SMALLEST_HOURS = 0.25

#: The id the new work is given while it is only being tried.
TRIAL_ID = -1


def clean_urgency(value: Any) -> str:
    value = str(value or URGENT).strip().lower()
    return value if value in URGENCIES else URGENT


def trial_task(request: Dict[str, Any], person: str, start: _dt.datetime,
               end: _dt.datetime) -> task_sheet.Task:
    return task_sheet.Task(
        id=TRIAL_ID, name=request["title"], project_number=request["project_number"],
        assignees=[person], required_hours=request["hours"], start=start.date(),
        due=max(request["due"], start.date()), kind=cfg.TASK_REQUEST_KIND)


def _hours_by(page: Optional[Dict[str, Any]]) -> Dict[Tuple[str, Any], float]:
    """A person's day as hours by what they are: a task, a job, or the rest."""
    out: Dict[Tuple[str, Any], float] = defaultdict(float)
    for block in (page or {}).get("blocks", []):
        if block.get("task_id") == TRIAL_ID:
            continue
        if block.get("task_id") is not None:
            key = ("task", block["task_id"])
        elif block.get("project"):
            key = ("job", block["project"])
        else:
            key = ("other", block.get("kind") or "")
        out[key] += float(block.get("hours") or 0.0)
    return out


def effect(*, person: str, days: Sequence[_dt.date],
           plan: Callable[[_dt.date, bool], Optional[Dict[str, Any]]],
           tasks_by_id: Mapping[int, task_sheet.Task],
           project_names: Mapping[str, str], hours_per_day: float,
           hours_per_mm: float, config: Dict[str, Any]) -> Dict[str, Any]:
    """What adding the work does to ``person``'s coming days.

    ``plan(day, with_new)`` is that person's page of the day plan, without
    or with the new work in it.
    """
    pushed: Dict[Tuple[str, Any], float] = defaultdict(float)
    pushed_on: Dict[Tuple[str, Any], _dt.date] = {}
    free_after: Dict[_dt.date, float] = {}
    over_before = over_after = 0.0
    for day in days:
        before, after = plan(day, False), plan(day, True)
        b, a = _hours_by(before), _hours_by(after)
        for key in set(b) | set(a):
            lost = b.get(key, 0.0) - a.get(key, 0.0)
            if lost > 1e-6:
                pushed[key] += lost
                pushed_on.setdefault(key, day)
        # A task that is pushed catches up in free time and in usual project
        # work before it is due: dated work wins over the usual pace.
        free_after[day] = float((after or {}).get("free_hours") or 0.0) + sum(
            float(b.get("hours") or 0.0) for b in (after or {}).get("blocks", [])
            if b.get("kind") == "work")
        over_before += float((before or {}).get("over_hours") or 0.0)
        over_after += float((after or {}).get("over_hours") or 0.0)

    items: List[Dict[str, Any]] = []
    late = 0
    for (kind, ref), hours in sorted(pushed.items(), key=lambda kv: -kv[1]):
        if hours < SMALLEST_HOURS:
            continue
        if kind == "task":
            task = tasks_by_id.get(ref)
            if task is None:
                continue
            due = task.due
            # Can it still be done in time from the room left before it is due?
            spare = sum(h for d, h in free_after.items()
                        if d > pushed_on[(kind, ref)] and (due is None or d <= due))
            short = max(0.0, hours - spare)
            days_late = (math.ceil(short / hours_per_day) if short > 1e-6
                         and hours_per_day else 0)
            if days_late:
                late += 1
            items.append({
                "kind": "task", "task_id": ref, "title": task.name,
                "job": task.project_number,
                "job_name": project_names.get(task.project_number, ""),
                "hours": round(hours, 2), "due": due.isoformat() if due else None,
                "late": bool(days_late), "days_late": days_late,
                "late_until": _late_until(due, days_late, config) if days_late else None,
            })
        elif kind == "job":
            items.append({"kind": "job", "job": ref,
                          "title": project_names.get(ref) or ref,
                          "hours": round(hours, 2)})
        else:
            items.append({"kind": "other", "title": "Team support and meetings",
                          "hours": round(hours, 2)})
    total = sum(i["hours"] for i in items)
    overtime = max(0.0, over_after - over_before)
    return {
        "person": person,
        "pushed": items,
        "pushed_hours": round(total, 2),
        "late_tasks": late,
        "overtime_hours": round(overtime, 2),
        "pushed_mm": round(total / hours_per_mm, 3) if hours_per_mm else None,
        "nothing": not items,
    }


def _late_until(due: Optional[_dt.date], days_late: int,
                config: Dict[str, Any]) -> Optional[str]:
    if due is None:
        return None
    day, count = due, 0
    for _ in range(120):
        day += _dt.timedelta(days=1)
        if task_sheet.is_working_day(day, config):
            count += 1
            if count >= days_late:
                return day.isoformat()
    return None


def verdict(view: Dict[str, Any]) -> str:
    """The cost in one line."""
    if view["nothing"]:
        return "Pushes nothing: it fits in time nobody has planned."
    parts = [f"Pushes {view['pushed_hours']:g} h of planned work"]
    if view["late_tasks"]:
        parts.append(f"{view['late_tasks']} task"
                     f"{'s' if view['late_tasks'] != 1 else ''} would go late")
    else:
        parts.append("nothing goes late")
    return ", ".join(parts) + "."
