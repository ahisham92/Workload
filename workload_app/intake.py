"""Requests that come in during the day, given somebody and a time at once.

A request is a line -- what it is, which project if any, roughly how long,
when it is wanted -- and everything else is decided for the manager:

* **who**: whoever doing that kind of work has the most room over the coming
  days, by the same outlook the planner draws; somebody who has worked on the
  project before wins a tie.  The manager can name somebody instead.
* **when**: the first free stretch in that person's working day from now on,
  after the requests they already have.  A request is an interruption, so it
  goes on top of the day's usual work rather than waiting for a gap in it;
  what it pushes aside is exactly what the planner then shows as load.

It becomes an ordinary task of kind *Request*, so it is on the task list, in
everybody's load and in the staffing forecast like any other work, and its
time of day is kept beside it.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import config as cfg
from . import people as people_module
from . import tasks as task_sheet

#: Slots start on the quarter hour.
STEP_MINUTES = 15
#: The longest a single request may be, in hours -- past that it is a task to
#: plan, not something that came in this morning.
LONGEST_HOURS = 80.0


class IntakeError(ValueError):
    def __init__(self, errors: Sequence[str]):
        errors = list(errors)
        super().__init__("; ".join(errors))
        self.errors = errors


def _at(day: _dt.date, hhmm: str) -> _dt.datetime:
    hours, minutes = (int(x) for x in str(hhmm).split(":"))
    return _dt.datetime.combine(day, _dt.time(hours, minutes))


def round_up(moment: _dt.datetime) -> _dt.datetime:
    moment = moment.replace(second=0, microsecond=0)
    extra = (-moment.minute) % STEP_MINUTES
    return moment + _dt.timedelta(minutes=extra)


def parse_now(value: Any) -> _dt.datetime:
    """The browser's own clock, so a slot is in the team's time, not the host's."""
    if value:
        try:
            moment = _dt.datetime.fromisoformat(str(value)[:19])
            return moment.replace(tzinfo=None)
        except ValueError:
            pass
    return _dt.datetime.now()


def clean(body: Mapping[str, Any], *, projects: Iterable[str],
          today: _dt.date) -> Dict[str, Any]:
    errors: List[str] = []
    title = " ".join(str(body.get("title") or body.get("name") or "").split())
    if not title:
        errors.append("Say what the request is.")
    project = str(body.get("project_number") or "").strip()
    if project and project not in set(projects):
        errors.append(f"{project} is not a project in the register.")
    try:
        hours = float(body.get("hours") or 1.0)
    except (TypeError, ValueError):
        hours = -1
    if not 0 < hours <= LONGEST_HOURS:
        errors.append(f"Hours are more than 0 and at most {LONGEST_HOURS:g}.")
    due_raw = body.get("due")
    try:
        due = _dt.date.fromisoformat(str(due_raw)) if due_raw else today
    except ValueError:
        errors.append(f"{due_raw!r} is not a date.")
        due = today
    role = str(body.get("role") or people_module.ROLE_ENGINEERING)
    if role not in dict(people_module.ROLES):
        errors.append("The kind of work is engineering or drafting.")
    if errors:
        raise IntakeError(errors)
    return {"title": title, "project_number": project, "hours": hours,
            "due": due, "role": role,
            "person": str(body.get("person") or "").strip()}


def choose(view: Dict[str, Any], *, role: str, project: str,
           eligible: Iterable[str], history: Mapping[str, set]) -> Optional[str]:
    """Who has the most room among those doing this kind of work."""
    eligible = set(eligible)
    knows = history.get(project, set()) if project else set()
    candidates = [p for p in view["people"]
                  if p["name"] in eligible and p["role"] == role]
    if not candidates:
        candidates = [p for p in view["people"] if p["name"] in eligible]
    if not candidates:
        return None
    best = min(candidates, key=lambda p: (round(p["after"]["load"] or 0, 2),
                                          p["name"] not in knows, p["name"]))
    return best["name"]


def slot(*, hours: float, now: _dt.datetime, taken: Sequence[Tuple[_dt.datetime, _dt.datetime]],
         config: Dict[str, Any]) -> Tuple[_dt.datetime, _dt.datetime]:
    """The first free stretch from ``now`` in the working days, after ``taken``.

    A request longer than what is left of a day carries on into the next
    working day's first free time.
    """
    remaining = hours * 60.0
    cursor = round_up(now)
    start: Optional[_dt.datetime] = None
    end = cursor
    day = cursor.date()
    busy = sorted(taken)
    for _ in range(370):
        if task_sheet.is_working_day(day, config):
            open_at = max(_at(day, config["day_start"]), cursor)
            close_at = _at(day, config["day_end"])
            for gap_start, gap_end in _gaps(open_at, close_at, busy):
                length = (gap_end - gap_start).total_seconds() / 60.0
                if length <= 0:
                    continue
                if start is None:
                    start = gap_start
                used = min(length, remaining)
                end = gap_start + _dt.timedelta(minutes=used)
                remaining -= used
                if remaining <= 1e-6:
                    return start, end
        day += _dt.timedelta(days=1)
        cursor = _dt.datetime.combine(day, _dt.time(0, 0))
    return start or cursor, end


def _gaps(open_at: _dt.datetime, close_at: _dt.datetime,
          busy: Sequence[Tuple[_dt.datetime, _dt.datetime]]):
    point = open_at
    for first, last in busy:
        if last <= point or first >= close_at:
            continue
        if first > point:
            yield point, min(first, close_at)
        point = max(point, last)
        if point >= close_at:
            return
    if point < close_at:
        yield point, close_at


def is_request(task: task_sheet.Task) -> bool:
    return task.kind == cfg.TASK_REQUEST_KIND
