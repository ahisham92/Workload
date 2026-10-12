"""Everybody's day, filled in by itself.

Nobody types a plan.  A person's day is laid out from what the app already
knows, in this order:

1. **requests** that came in, at the time they were given, the
   **meetings** of anybody who leads people, everybody's weekly
   **development time** (see ``management``) and the **Outlook meetings** of
   anybody whose calendar is linked (see ``busy_calendar``);
2. for somebody who leads people, their daily **team support**;
3. **tasks** on the list for that day -- the submission run-ups the
   submissions plan put there, meetings, anything else dated -- a task over
   several days taking its share of each.

Nothing is guessed from past timesheets: what is left of the day is free.

Each goes into the first free stretch of the working day, so the result reads
like a page of a pocket diary: 09:00 to 10:30 this, 10:30 to 11:00 that.
Whatever does not fit before the end of the day is shown as over, which is
the honest answer to "can they take this on today".  Somebody away that day
has an empty page marked away, and a public holiday is not a working day.

The week is the same thing, day by day.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import busy_calendar
from . import calendar_
from . import intake
from . import people as people_module
from . import planner
from . import tasks as task_sheet

#: How a meeting typed in reads on the page, by who it is with.
MEETING_KINDS = {"client": "Client meeting", "trade": "Meeting with another trade",
                 "internal": "Internal meeting"}

def task_hours_on(task: task_sheet.Task, day: _dt.date, today: _dt.date,
                  config: Dict[str, Any], name: Optional[str] = None) -> float:
    """The part of a task that falls on ``day`` (``name``'s part of it)."""
    if task.done or not task.required_hours or task.due is None:
        return 0.0
    each = task.hours_for(name) if name else task.hours_each()
    if task.due < today and is_prep_step(task):
        # A run-up day that has gone is gone: piling every missed day of
        # preparation onto today would book people for days at once.
        return 0.0
    if task.due < today:                       # overdue: it is today's
        # (or the next working day's, when today is a weekend or a holiday)
        return each if day == _first_working(today, config) else 0.0
    first = min(max(task.start or today, today), task.due)
    days = (task_sheet.working_days(first, task.due, config)
            or [_first_working(first, config)])
    return each / len(days) if day in days else 0.0


def is_prep_step(task: task_sheet.Task) -> bool:
    """One of the daily preparation steps the app makes before a submission."""
    return task.kind == "Submission" and bool(task.series)


def prep_title(task: task_sheet.Task, submitted_on: Optional[_dt.date]) -> str:
    """A preparation step as a task reads: what to prepare and for when."""
    what = task.deliverable_name or task.name.split(" — ")[0]
    when = f", due {submitted_on:%d/%m}" if submitted_on else ""
    return f"Prepare the submission: {what}{when}"


def _first_working(day: _dt.date, config: Dict[str, Any]) -> _dt.date:
    """``day`` when it is a working day, else the next one."""
    return (planner.days_ahead(day, 1, config) or [day])[0]


def plan_day(*, day: _dt.date, today: _dt.date, roster: Sequence[Dict[str, Any]],
             tasks: Sequence[task_sheet.Task],
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
    # A run-up's last step falls on the submission day itself.
    submitted_on: Dict[str, _dt.date] = {}
    for task in tasks:
        if is_prep_step(task) and task.due:
            submitted_on[task.series] = max(task.due, submitted_on.get(task.series, task.due))

    people = []
    for person in roster:
        if not person.get("active", True):
            continue
        name = person["name"]
        fixed: List[Dict[str, Any]] = []
        flexible: List[Dict[str, Any]] = []
        away = calendar_.is_away(config, name, day)
        if working and not away and calendar_.is_half_away(config, name, day):
            # A personal excuse of half a day: the second half is off.
            middle = day_start + (day_end - day_start) / 2
            fixed.append({"start": middle, "end": day_end, "kind": "half_day",
                          "title": "Half a day off (personal excuse)",
                          "project": "", "task_id": None, "done": False})
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
                if meeting["kind"] in ("outlook", "typed"):
                    # Only what no request or meeting above already holds.
                    for first, last in busy_calendar.minus(
                            [(meeting["start"], meeting["end"])],
                            [(b["start"], b["end"]) for b in fixed]):
                        fixed.append({"start": first, "end": last, "kind": "meeting",
                                      "source": meeting["kind"],
                                      "what": meeting.get("what", ""),
                                      "meeting_id": meeting.get("meeting_id"),
                                      "title": _meeting_title(meeting, name),
                                      "project": "", "task_id": None, "done": False,
                                      "agenda": []})
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
            for task in tasks:
                if intake.is_request(task) or name not in task.assignees:
                    continue
                hours = task_hours_on(task, day, today, config, name)
                if hours <= 0:
                    continue
                flexible.append({"hours": hours, "kind": task.kind.lower(),
                                 "title": (prep_title(task, submitted_on.get(task.series))
                                           if is_prep_step(task) else task.name),
                                 "project": task.project_number,
                                 "task_id": task.id, "done": False,
                                 "row": (task.deliverable_row
                                         if is_prep_step(task) else None),
                                 "fills": is_prep_step(task)})
            # Preparation fills whatever time is left, so it goes last and
            # what does not fit is not "too much": it is the free time.
            flexible.sort(key=lambda item: bool(item.get("fills")))
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
    if meeting["kind"] == "outlook":
        return "In a meeting (from Outlook)"
    if meeting["kind"] == "typed":
        what = MEETING_KINDS.get(meeting.get("what") or "", "Meeting")
        return f"{what}: {meeting['title']}" if meeting.get("title") else what
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
                           "task_id": item["task_id"], "done": item["done"],
                           **({"row": item["row"]} if item.get("row") is not None else {})})
            remaining -= used
            if end >= last:
                gaps.pop(0)
            else:
                gaps[0] = (end, last)
        if remaining > 0.5 and not item.get("fills"):
            over += remaining / 60.0
    blocks.sort(key=lambda b: b["start"])
    return [dict(b) for b in blocks], over



def week_of(day: _dt.date, config: Dict[str, Any]) -> List[_dt.date]:
    start = task_sheet.week_start(day, config)
    return task_sheet.working_days(start, start + _dt.timedelta(days=6), config)
