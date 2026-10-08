"""Everybody's day, filled in by itself.

Nobody types a plan.  A person's day is laid out from what the app already
knows, in this order:

1. **requests** that came in, at the time they were given, the
   **meetings** of anybody who leads people and everybody's weekly
   **development time** (see ``management``);
2. for somebody who leads people, their daily **team support**;
3. **tasks** on the list for that day -- the submission run-ups the
   submissions plan put there, meetings, anything else dated -- a task over
   several days taking its share of each;
4. **their usual project work** in what is left, at the pace their newest
   timesheets set, with any handover in force for that day applied.

Each goes into the first free stretch of the working day, so the result reads
like a page of a pocket diary: 09:00 to 10:30 this, 10:30 to 11:00 that.
Whatever does not fit before the end of the day is shown as over, which is
the honest answer to "can they take this on today".  Somebody away that day
has an empty page marked away, and a public holiday is not a working day.

The week is the same thing, day by day.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import calendar_
from . import intake
from . import people as people_module
from . import planner
from . import tasks as task_sheet

#: Usual project work shorter than this in a day is folded into the largest,
#: so a diary page is not cut into ten-minute slivers.
SMALLEST_BLOCK_HOURS = 0.5


def _minutes(moment: _dt.datetime) -> float:
    return moment.hour * 60 + moment.minute


def task_hours_on(task: task_sheet.Task, day: _dt.date, today: _dt.date,
                  config: Dict[str, Any]) -> float:
    """The part of a task that falls on ``day``."""
    if task.done or not task.required_hours or task.due is None:
        return 0.0
    each = task.hours_each()
    if task.due < today:                       # overdue: it is today's
        return each if day == today else 0.0
    first = task.start or today
    first = max(first, today)
    if first > task.due:
        first = task.due
    days = task_sheet.working_days(first, task.due, config) or [task.due]
    return each / len(days) if day in days else 0.0


def plan_day(*, day: _dt.date, today: _dt.date, roster: Sequence[Dict[str, Any]],
             rates: Mapping[Tuple[str, str], float], tasks: Sequence[task_sheet.Task],
             slots: Mapping[int, Dict[str, Any]], config: Dict[str, Any],
             project_names: Mapping[str, str],
             meetings: Sequence[Dict[str, Any]] = (),
             support: Optional[Mapping[str, float]] = None,
             led: Optional[Mapping[str, int]] = None) -> Dict[str, Any]:
    """One day for everybody. ``meetings`` are that day's, from
    ``management.Plan.meetings_on``; ``support`` is each leader's daily team
    support in hours and ``led`` how many people they lead."""
    support = support or {}
    led = led or {}
    working = task_sheet.is_working_day(day, config)
    day_start = intake._at(day, config["day_start"])
    day_end = intake._at(day, config["day_end"])
    a_day = task_sheet.hours_per_day(config)
    tasks_by_id = {t.id: t for t in tasks}

    pace: Dict[str, Dict[str, float]] = defaultdict(dict)
    for (person, project), rate in rates.items():
        pace[person][project] = rate

    people = []
    for person in roster:
        if not person.get("active", True):
            continue
        name = person["name"]
        fixed: List[Dict[str, Any]] = []
        flexible: List[Dict[str, Any]] = []
        away = calendar_.is_away(config, name, day)
        if working:
            # A request booked before the absence was known still shows, so
            # it is seen and handed on rather than lost.
            for task_id, slot in slots.items():
                task = tasks_by_id.get(task_id)
                if task is None or slot["person"] != name:
                    continue
                start = _dt.datetime.fromisoformat(slot["start"])
                end = _dt.datetime.fromisoformat(slot["end"])
                first, last = max(start, day_start), min(end, day_end)
                if start.date() <= day <= end.date() and last > first:
                    fixed.append({"start": first, "end": last, "kind": "request",
                                  "title": task.name, "project": task.project_number,
                                  "task_id": task.id, "done": task.done})
        if working and not away:
            for meeting in meetings:
                if name != meeting["leader"] and name not in meeting["with"]:
                    continue
                fixed.append({"start": meeting["start"], "end": meeting["end"],
                              "kind": ("development"
                                       if meeting["kind"] == "development"
                                       else "meeting"),
                              "title": _meeting_title(meeting, name),
                              "project": "", "task_id": None, "done": False,
                              "agenda": list(meeting.get("agenda") or ())})
            if support.get(name):
                count = led.get(name, 0)
                flexible.append({"hours": support[name], "kind": "management",
                                 "title": "Team support: questions, checking and "
                                          f"replies ({count} "
                                          f"{'person' if count == 1 else 'people'})",
                                 "project": "", "task_id": None, "done": False})
            on_task_projects: Dict[str, float] = defaultdict(float)
            for task in tasks:
                if intake.is_request(task) or name not in task.assignees:
                    continue
                hours = task_hours_on(task, day, today, config)
                if hours <= 0:
                    continue
                flexible.append({"hours": hours, "kind": task.kind.lower(),
                                 "title": task.name, "project": task.project_number,
                                 "task_id": task.id, "done": False})
                if task.project_number:
                    on_task_projects[task.project_number] += hours
            work = []
            for project, rate in pace.get(name, {}).items():
                hours = max(0.0, rate - on_task_projects.get(project, 0.0))
                if hours > 0:
                    work.append([project, hours])
            work.sort(key=lambda item: -item[1])
            # Fold slivers into the biggest piece of work.
            if len(work) > 1:
                kept = [w for w in work if w[1] >= SMALLEST_BLOCK_HOURS]
                spare = sum(w[1] for w in work if w[1] < SMALLEST_BLOCK_HOURS)
                if kept:
                    kept[0][1] += spare
                    work = kept
            for project, hours in work:
                flexible.append({"hours": hours, "kind": "work",
                                 "title": project_names.get(project) or project,
                                 "project": project, "task_id": None, "done": False})
        blocks, over = _lay_out(fixed, flexible, day_start, day_end)
        booked = sum((b["end"] - b["start"]).total_seconds() / 3600 for b in blocks)
        people.append({
            "name": name,
            "team_id": person.get("team_id"),
            "team_name": person.get("team_name", ""),
            "grade_label": person.get("grade_label", ""),
            "role": people_module.role_of(person.get("grade")),
            "blocks": [{**b, "start": b["start"].strftime("%H:%M"),
                        "end": b["end"].strftime("%H:%M"),
                        "hours": round((b["end"] - b["start"]).total_seconds() / 3600, 2)}
                       for b in blocks],
            "hours": round(booked, 2),
            "over_hours": round(over, 2),
            "free_hours": 0.0 if away else round(max(0.0, a_day - booked), 2),
            "away": away,
            "requests": sum(1 for b in blocks if b["kind"] == "request"),
        })
    return {
        "date": day.isoformat(),
        "working_day": working,
        "day_start": config["day_start"],
        "day_end": config["day_end"],
        "hours_per_day": round(a_day, 2),
        "people": people,
    }


def _meeting_title(meeting: Dict[str, Any], name: str) -> str:
    """The meeting as the person reading their own day would put it."""
    leader = meeting["leader"]
    if meeting["kind"] == "development":
        return "Development time: your goals for the quarter"
    if meeting["kind"] == "one_to_one":
        other = meeting["with"][0] if name == leader else leader
        return f"One-to-one with {other}"
    if name == leader:
        count = len(meeting["with"])
        return f"Runs the team meeting ({count} {'person' if count == 1 else 'people'})"
    return f"Team meeting with {leader}"


def _lay_out(fixed: List[Dict[str, Any]], flexible: List[Dict[str, Any]],
             day_start: _dt.datetime, day_end: _dt.datetime
             ) -> Tuple[List[Dict[str, Any]], float]:
    """Fixed blocks where they are; the rest poured into the gaps in order."""
    blocks = sorted(fixed, key=lambda b: b["start"])
    busy = [(b["start"], b["end"]) for b in blocks]
    gaps = list(intake._gaps(day_start, day_end, busy))
    over = 0.0
    for item in flexible:
        # Quarter hours, so a diary page reads cleanly.
        remaining = round(item["hours"] * 4) * 15.0
        while remaining > 0.5 and gaps:
            first, last = gaps[0]
            length = (last - first).total_seconds() / 60.0
            used = min(length, remaining)
            end = first + _dt.timedelta(minutes=used)
            blocks.append({"start": first, "end": end, "kind": item["kind"],
                           "title": item["title"], "project": item["project"],
                           "task_id": item["task_id"], "done": item["done"]})
            remaining -= used
            if end >= last:
                gaps.pop(0)
            else:
                gaps[0] = (end, last)
        if remaining > 0.5:
            over += remaining / 60.0
    blocks.sort(key=lambda b: b["start"])
    # Two pieces of the same work back to back read as one.
    merged: List[Dict[str, Any]] = []
    for block in blocks:
        if merged and merged[-1]["end"] == block["start"] \
                and merged[-1]["kind"] == block["kind"] == "work" \
                and merged[-1]["project"] == block["project"]:
            merged[-1]["end"] = block["end"]
        else:
            merged.append(dict(block))
    return merged, over


def rates_on(day: _dt.date, rows: Sequence[Dict[str, Any]], config: Dict[str, Any],
             saved: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], float]:
    """Each person's pace on a project, with the handovers in force that day."""
    measured = planner.pace(rows, config)["rates"]
    active = planner._active_saved(saved, day, day)
    rates, _ = planner._apply_project_moves(measured, active)
    return rates


def week_of(day: _dt.date, config: Dict[str, Any]) -> List[_dt.date]:
    start = day - _dt.timedelta(days=day.weekday())
    # A Sunday-to-Thursday week starts on the Sunday on or before the day.
    if 6 in config["work_days"] and 4 not in config["work_days"]:
        start = day - _dt.timedelta(days=(day.weekday() + 1) % 7)
    return [d for d in (start + _dt.timedelta(days=i) for i in range(7))
            if task_sheet.is_working_day(d, config)]
