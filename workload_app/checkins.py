"""What a manager should know about each person this week, with nothing typed.

Three things, all read from what the app already holds -- the timesheets, the
task list, the calendar and the plan for the coming days:

* **free hours** -- each person's working day for the next fortnight laid out
  the way the Planner's Today lays it out, and what is left of it.  That is
  who can take a request, and when;
* **how loaded they have been** -- the hours they booked week by week against
  the hours they had, and the overtime.  Somebody well over their hours for
  weeks on end needs to ease off before the quality of the work goes; somebody
  back from leave or coming off a quiet spell is fresh and can take more;
* **checkpoints** -- the few things worth raising with each person: work that
  is late, blocked or about to fall due, a task that has used more hours than
  it was given, a timesheet that has stopped arriving, leave coming up that
  needs a handover.  Each is phrased as the question to ask.

Nothing is stored.  Every figure is worked out again on each read, so it is
never out of step with the latest timesheet.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import calendar_
from . import daily
from . import people as people_module
from . import planner
from . import tasks as task_sheet
from .tasks import week_start

#: Working days of free hours shown ahead.
AHEAD_DAYS = 10
#: Weeks of booked hours shown behind.
WEEKS_BACK = 8
#: The weeks the load signal is judged on, and the shorter spell that says
#: somebody has had a quiet time lately.
RECENT_WEEKS = 4
QUIET_WEEKS = 2

#: A four-week load at or above this, or this many weeks in a row over the
#: line, means the person needs to ease off.
REST_LOAD = 1.10
OVER_LINE = 1.05
REST_STREAK = 3
#: Overtime over the four weeks that says the same, whatever the load says.
REST_OVERTIME = 30.0
#: Heavy but not yet a problem: worth keeping an eye on.
BUSY_LOAD = 1.0
BUSY_OVERTIME = 12.0
#: Working days without a single day off before it is worth suggesting some.
NO_BREAK_DAYS = 80
#: Below this load over the last fortnight somebody has room to take more;
#: this many days away in the fortnight means they are just back.
QUIET_LOAD = 0.75
BACK_FROM_LEAVE_DAYS = 3
#: A person whose newest timesheet row is this many working days behind the
#: team's newest has stopped sending them.
TIMESHEET_GAP_DAYS = 5
#: A task due within this many working days is coming up.
DUE_SOON_DAYS = 3

SIGNALS = {
    "rest": "Needs to ease off",
    "busy": "Heavy, keep an eye",
    "fresh": "Fresh, can take more",
    "steady": "Steady",
}
#: The order a manager reads them in: who needs something done first.
SIGNAL_ORDER = ["rest", "busy", "fresh", "steady"]
LEVELS = ("now", "soon", "note")


def _short(day: Optional[_dt.date]) -> str:
    return day.strftime("%a %d %b") if day else ""


def _task_label(task: task_sheet.Task) -> str:
    """A task as a check-in names it: "Name (project)"."""
    label = task.name or f"Task {task.id}"
    return f"{label} ({task.project_number})" if task.project_number else label


def _hours(value: float) -> str:
    return f"{value:,.0f} h" if abs(value - round(value)) < 0.05 else f"{value:,.1f} h"


# --------------------------------------------------------------------------
# looking back: hours booked against hours available
# --------------------------------------------------------------------------

def history(rows: Iterable[Dict[str, Any]], names: Sequence[str],
            config: Dict[str, Any], *, through: _dt.date,
            weeks: int = WEEKS_BACK) -> Dict[str, Any]:
    """Each person's booked hours, overtime and load, week by week.

    Days somebody was away count neither as hours available nor as hours
    worked, so a week of leave reads as a short week, not a quiet one.
    """
    a_day = task_sheet.hours_per_day(config)
    last_start = week_start(through, config)
    starts = [last_start - _dt.timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    first = starts[0]
    away = config.get("away") or {}
    booked: Dict[Tuple[str, _dt.date], float] = defaultdict(float)
    extra: Dict[Tuple[str, _dt.date], float] = defaultdict(float)
    last_row: Dict[str, _dt.date] = {}
    first_row: Dict[str, _dt.date] = {}
    for row in rows:
        day, name = row.get("date"), row.get("engineer")
        if not day or not name:
            continue
        # Leave booked ahead is not a timesheet that has come in.
        if day <= through and (name not in last_row or day > last_row[name]):
            last_row[name] = day
        if name not in first_row or day < first_row[name]:
            first_row[name] = day
        if day < first or day > through or day.isoformat() in away.get(name, ()):
            continue
        key = (name, week_start(day, config))
        booked[key] += float(row.get("hours") or 0.0)
        extra[key] += float(row.get("overtime_hours") or 0.0)

    out: Dict[str, List[Dict[str, Any]]] = {}
    for name in names:
        own = away.get(name, ())
        # Somebody who joined in the window had no hours to give before their
        # first timesheet day: a new joiner's first week is not a quiet one.
        joined = first_row.get(name)
        # Nor are the days after their newest timesheet quiet ones: those
        # hours have not come in yet (the check-in asks for them).
        seen = last_row.get(name)
        series = []
        for start in starts:
            end = min(start + _dt.timedelta(days=6), through, seen or through)
            days = [d for d in task_sheet.working_days(start, end, config)
                    if joined is None or d >= joined]
            off = sum(1 for d in days if d.isoformat() in own)
            capacity = (len(days) - off) * a_day
            hours = booked.get((name, start), 0.0)
            series.append({
                "week": start.isoformat(),
                "hours": round(hours, 1),
                "overtime": round(extra.get((name, start), 0.0), 1),
                "capacity": round(capacity, 1),
                "days_off": off,
                "load": round(hours / capacity, 3) if capacity else None,
            })
        out[name] = series
    return {"weeks": [s.isoformat() for s in starts], "people": out,
            "last_row": last_row}


def _sum_load(series: Sequence[Dict[str, Any]]) -> Optional[float]:
    capacity = sum(w["capacity"] for w in series)
    hours = sum(w["hours"] for w in series)
    return round(hours / capacity, 3) if capacity else None


def _streak_over(series: Sequence[Dict[str, Any]]) -> int:
    count = 0
    for week in reversed(series):
        if week["load"] is None:
            continue           # a week fully away neither breaks nor adds
        if week["load"] < OVER_LINE:
            break
        count += 1
    return count


def _last_day_off(own_away: Iterable[str], through: _dt.date) -> Optional[_dt.date]:
    days = [d for d in own_away if d <= through.isoformat()]
    return _dt.date.fromisoformat(max(days)) if days else None


def signal(series: Sequence[Dict[str, Any]], *, days_since_break: Optional[int]
           ) -> Dict[str, Any]:
    """How loaded somebody has been, and what that means for the next weeks."""
    recent = list(series[-RECENT_WEEKS:])
    quiet = list(series[-QUIET_WEEKS:])
    load = _sum_load(recent)
    quiet_load = _sum_load(quiet)
    overtime = round(sum(w["overtime"] for w in recent), 1)
    streak = _streak_over(series)
    days_off_lately = sum(w["days_off"] for w in quiet)
    reasons: List[str] = []

    if load is not None and load >= REST_LOAD:
        reasons.append(f"{load:.0%} of their hours over the last {len(recent)} weeks")
    if streak >= REST_STREAK:
        reasons.append(f"{streak} weeks in a row over their hours")
    if overtime >= REST_OVERTIME:
        reasons.append(f"{_hours(overtime)} overtime in {len(recent)} weeks")
    if reasons:
        key = "rest"
    else:
        if days_off_lately >= BACK_FROM_LEAVE_DAYS:
            reasons.append(f"back from {days_off_lately} day(s) off")
        elif quiet_load is not None and quiet_load < QUIET_LOAD:
            reasons.append(f"only {quiet_load:.0%} of their hours over the last "
                           f"{len(quiet)} weeks")
        if reasons:
            key = "fresh"
        else:
            if load is not None and load >= BUSY_LOAD:
                reasons.append(f"{load:.0%} of their hours over the last {len(recent)} weeks")
            if overtime >= BUSY_OVERTIME:
                reasons.append(f"{_hours(overtime)} overtime in {len(recent)} weeks")
            key = "busy" if reasons else "steady"
    if days_since_break is not None and days_since_break >= NO_BREAK_DAYS and key != "fresh":
        reasons.append(f"no day off in {days_since_break} working days")
        if key == "steady":
            key = "busy"
    if key == "steady" and load is not None:
        reasons.append(f"{load:.0%} of their hours over the last {len(recent)} weeks")
    return {
        "key": key,
        "label": SIGNALS[key],
        "reasons": reasons,
        "load": load,
        "recent_load": quiet_load,
        "overtime": overtime,
        "weeks_over": streak,
        "days_off_lately": days_off_lately,
        "days_since_break": days_since_break,
    }


# --------------------------------------------------------------------------
# looking ahead: free hours
# --------------------------------------------------------------------------

def free_hours(*, rows: Sequence[Dict[str, Any]], tasks: Sequence[task_sheet.Task],
               roster: Sequence[Dict[str, Any]], config: Dict[str, Any],
               saved: Sequence[Dict[str, Any]], slots: Mapping[int, Dict[str, Any]],
               project_names: Mapping[str, str], today: _dt.date,
               days: int = AHEAD_DAYS, management: Optional[Any] = None
               ) -> Dict[str, Any]:
    """Each person's free hours on each of the next working days.

    The days are laid out exactly as the Planner lays out Today, so the two
    never disagree about whether somebody has room.
    """
    window = planner.days_ahead(today, days, config)
    measured = planner.pace(rows, config)["rates"]
    per: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for day in window:
        rates = planner.rates_in_force(measured, saved, day)
        laid = daily.plan_day(day=day, today=today, roster=roster, rates=rates,
                              tasks=tasks, slots=slots, config=config,
                              project_names=project_names,
                              **(management.for_day(day) if management else {}))
        for person in laid["people"]:
            per[person["name"]].append({
                "date": day.isoformat(),
                "free": person["free_hours"],
                "booked": person["hours"],
                "over": person["over_hours"],
                "away": person["away"],
            })
    return {"days": [d.isoformat() for d in window], "people": dict(per),
            "hours_per_day": round(task_sheet.hours_per_day(config), 2)}


# --------------------------------------------------------------------------
# checkpoints
# --------------------------------------------------------------------------

def _point(level: str, kind: str, text: str, **extra: Any) -> Dict[str, Any]:
    return {"level": level, "kind": kind, "text": text, **extra}


def checkpoints(name: str, *, tasks: Sequence[task_sheet.Task], today: _dt.date,
                config: Dict[str, Any], load: Dict[str, Any],
                last_row: Optional[_dt.date], team_last: Optional[_dt.date],
                ahead: Sequence[Dict[str, Any]], top_work: str = ""
                ) -> List[Dict[str, Any]]:
    """The few things worth asking this person about, most pressing first."""
    out: List[Dict[str, Any]] = []
    soon_days = planner.days_ahead(today, DUE_SOON_DAYS, config)
    soon_end = soon_days[-1] if soon_days else today
    for task in tasks:
        if task.done or name not in task.assignees:
            continue
        label = _task_label(task)
        if task.status == "Blocked":
            out.append(_point("now", "blocked", f"{label} is blocked. What do they need "
                              f"to get it moving?", task_id=task.id))
        elif task.due and task.due < today:
            late = len(task_sheet.working_days(task.due + _dt.timedelta(days=1), today, config))
            out.append(_point("now", "overdue",
                              f"{label} was due {_short(task.due)}"
                              f"{f', {late} working day(s) ago' if late else ''}. "
                              f"When will it be done?", task_id=task.id))
        elif task.due and task.due <= soon_end:
            started = task.status != task_sheet.cfg.TASK_STATUSES[0]
            text = (f"{label} is due {_short(task.due)}. Is it on track?" if started else
                    f"{label} is due {_short(task.due)} and has not started. Can it "
                    f"still make it?")
            out.append(_point("soon" if started else "now", "due", text,
                              task_id=task.id))
        if (task.required_hours and task.actual_hours
                and task.actual_hours > task.required_hours * 1.05):
            out.append(_point("soon", "over_hours",
                              f"{label} has taken {_hours(task.actual_hours)} of the "
                              f"{_hours(task.required_hours)} it was given. How much is "
                              f"left?", task_id=task.id))

    why = "; ".join(load["reasons"])
    no_break = bool(load["days_since_break"]
                    and load["days_since_break"] >= NO_BREAK_DAYS)
    if load["key"] == "rest":
        out.append(_point("now", "rest",
                          f"Overloaded ({why}). Agree what can wait or move to someone "
                          f"with room, and give them a lighter week."))
    elif load["key"] == "fresh":
        out.append(_point("note", "fresh",
                          f"Has room ({why}). Ask what they would like to pick up "
                          f"next."))
    elif load["key"] == "busy" and not (no_break and len(load["reasons"]) == 1):
        out.append(_point("soon", "busy",
                          f"Running heavy ({why}). Check the coming weeks are lighter, "
                          f"or it turns into overload."))
    elif no_break:
        out.append(_point("soon", "break",
                          f"No day off in {load['days_since_break']} working days. "
                          f"Suggest they book some leave."))

    if last_row and team_last and last_row < team_last:
        gap = [d for d in task_sheet.working_days(last_row + _dt.timedelta(days=1), team_last, config)
               if not calendar_.is_away(config, name, d)]
        if len(gap) >= TIMESHEET_GAP_DAYS:
            out.append(_point("soon", "timesheet",
                              f"No hours from them since {_short(last_row)}, while the "
                              f"rest of the team is in up to {_short(team_last)}. Ask "
                              f"for their timesheet."))

    away = [d for d in ahead if d["away"]]
    if away:
        first = _dt.date.fromisoformat(away[0]["date"])
        what = f" for {top_work}" if top_work else ""
        out.append(_point("soon" if first <= soon_end else "note", "away",
                          f"Away {len(away)} day(s) from {_short(first)}. Agree a "
                          f"handover{what} before then."))

    rank = {level: i for i, level in enumerate(LEVELS)}
    out.sort(key=lambda p: rank[p["level"]])
    return out


# --------------------------------------------------------------------------
# the whole page
# --------------------------------------------------------------------------

def build(*, rows: Sequence[Dict[str, Any]], tasks: Sequence[task_sheet.Task],
          roster: Sequence[Dict[str, Any]], config: Dict[str, Any],
          project_names: Mapping[str, str], saved: Sequence[Dict[str, Any]] = (),
          slots: Optional[Mapping[int, Dict[str, Any]]] = None,
          today: Optional[_dt.date] = None,
          management: Optional[Any] = None,
          marks: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """The whole Check-ins page. ``management`` (a ``management.Plan``) puts
    the time leaders give their people into the free hours, and gives each
    leader their meetings with the agenda for each. ``marks`` are what people
    said from their own My day: stuck, help needed, days off."""
    today = today or _dt.date.today()
    active = [p for p in roster if p.get("active", True)]
    names = [p["name"] for p in active]
    dated = [r["date"] for r in rows if r.get("date") and r["date"] <= today]
    through = max(dated) if dated else today
    past = history(rows, names, config, through=through)
    ahead = free_hours(rows=rows, tasks=tasks, roster=active, config=config,
                       saved=saved, slots=slots or {}, project_names=project_names,
                       today=today, management=management)
    rates = planner.pace(rows, config)["rates"]
    away = config.get("away") or {}
    a_day = ahead["hours_per_day"]

    led = management.led if management else {}
    leading_hours = management.hours_a_day() if management else {}
    people = []
    for person in active:
        name = person["name"]
        series = past["people"].get(name, [])
        off = _last_day_off(away.get(name, ()), through)
        first_row = None
        if off is None:
            own = [r["date"] for r in rows if r.get("engineer") == name and r.get("date")]
            first_row = min(own) if own else None
        since_from = off or first_row
        since = (len(task_sheet.working_days(since_from + _dt.timedelta(days=1), through, config))
                 if since_from else None)
        load = signal(series, days_since_break=since)
        days = ahead["people"].get(name, [])
        mine = sorted(((h, p) for (n, p), h in rates.items() if n == name), reverse=True)
        top = project_names.get(mine[0][1]) or mine[0][1] if mine else ""
        week = days[:5]
        asks, off_news = _said(name, marks, tasks, today)
        last_row = past["last_row"].get(name)
        points = checkpoints(
            name, tasks=tasks, today=today, config=config, load=load,
            last_row=last_row, team_last=through,
            ahead=days, top_work=top)
        stuck_tasks = {a["task_id"] for a in asks if a["kind"] == "stuck"}
        points = [_ask_point(a) for a in asks] + [
            p for p in points
            if not (p["kind"] == "blocked" and p.get("task_id") in stuck_tasks)]
        people.append({
            "name": name,
            "grade_label": people_module.grade_label(
                person.get("grade") or people_module.DEFAULT_GRADE),
            "role": people_module.role_of(person.get("grade")),
            "team_id": person.get("team_id"),
            "team_name": person.get("team_name", ""),
            "weeks": series,
            "signal": load,
            "last_day_off": off.isoformat() if off else None,
            "last_timesheet": last_row.isoformat() if last_row else None,
            "days": days,
            "free_week": round(sum(d["free"] for d in week), 1),
            "free_total": round(sum(d["free"] for d in days), 1),
            "next_free": next((d["date"] for d in days if d["free"] >= 1), None),
            "checkpoints": points,
            "asks": asks,
            "off_news": off_news,
            "leads": len(led.get(name, ())),
            "is_manager": person.get("grade") == "manager",
            "leading_hours": leading_hours.get(name, 0.0),
        })

    order = {key: i for i, key in enumerate(SIGNAL_ORDER)}
    people.sort(key=lambda p: (order[p["signal"]["key"]], -len(p["checkpoints"]),
                               p["name"]))
    counts = {key: sum(1 for p in people if p["signal"]["key"] == key)
              for key in SIGNAL_ORDER}
    free_by_day = [{"date": day,
                    "free": round(sum(p["days"][i]["free"] for p in people
                                      if i < len(p["days"])), 1)}
                   for i, day in enumerate(ahead["days"])]
    # Who to give the next piece of work to: room this week, and not somebody
    # who has just been told to ease off.
    take = sorted((p for p in people if p["free_week"] >= 1
                   and p["signal"]["key"] != "rest" and not p["is_manager"]),
                  key=lambda p: (p["signal"]["key"] != "fresh", -p["free_week"]))
    leading = _leading(management, people, tasks=tasks, config=config,
                       window=[_dt.date.fromisoformat(d) for d in ahead["days"]],
                       can_take=[p["name"] for p in take]) if management else []
    return {
        "leading": leading,
        "today": today.isoformat(),
        "through": through.isoformat(),
        "stale": (today - through).days > planner.STALE_AFTER_DAYS,
        "weeks": past["weeks"],
        "days": ahead["days"],
        "hours_per_day": a_day,
        "people": people,
        "signals": [{"key": k, "label": SIGNALS[k], "count": counts[k]}
                    for k in SIGNAL_ORDER],
        "free_by_day": free_by_day,
        "free_week": round(sum(p["free_week"] for p in people), 1),
        "free_total": round(sum(p["free_total"] for p in people), 1),
        "can_take": [{"name": p["name"], "free_week": p["free_week"],
                      "next_free": p["next_free"], "signal": p["signal"]["key"]}
                     for p in take],
        "checkpoints": sum(len(p["checkpoints"]) for p in people),
        "urgent": sum(1 for p in people for c in p["checkpoints"] if c["level"] == "now"),
        "thresholds": {"rest_load": REST_LOAD, "busy_load": BUSY_LOAD,
                       "quiet_load": QUIET_LOAD, "over_line": OVER_LINE},
    }


#: How long a lead hears of somebody's newly entered time off.
OFF_NEWS_DAYS = 7


def _said(name: str, marks: Sequence[Dict[str, Any]], tasks: Sequence[task_sheet.Task],
          today: _dt.date) -> tuple:
    """What this person said from My day that is still open: asks for help or
    stuck tasks (not once the task is done), and time off entered lately."""
    by_id = {t.id: t for t in tasks}
    since = (today - _dt.timedelta(days=OFF_NEWS_DAYS)).isoformat()
    asks, off = [], []
    for mark in marks:
        if mark["person"] != name or mark.get("cleared_at"):
            continue
        task = by_id.get(mark["task_id"]) if mark.get("task_id") else None
        if mark["kind"] in ("stuck", "help"):
            if mark.get("task_id") and (task is None or task.done
                                        or name not in task.assignees):
                continue
            label = _task_label(task) if task is not None else ""
            asks.append({"id": mark["id"], "kind": mark["kind"], "note": mark["note"],
                         "task_id": mark.get("task_id"), "task": label,
                         "at": mark["created_at"]})
        elif mark["kind"] == "off" and (mark["created_at"] or "") >= since \
                and mark.get("absence"):
            off.append({"id": mark["id"], "start": mark["absence"]["start"],
                        "end": mark["absence"]["end"], "note": mark["note"]})
    return asks, off


def _ask_point(ask: Dict[str, Any]) -> Dict[str, Any]:
    said = f": \u201c{ask['note']}\u201d" if ask["note"] else ""
    if ask["kind"] == "stuck":
        text = f"Stuck on {ask['task']}{said}. What do they need to get it moving?"
    elif ask["task"]:
        text = f"Asked for help with {ask['task']}{said}."
    else:
        text = f"Asked for help{said}."
    return _point("now", ask["kind"], text, task_id=ask["task_id"], mark_id=ask["id"])


def _leading(management: Any, people: Sequence[Dict[str, Any]], *,
             tasks: Sequence[task_sheet.Task], config: Dict[str, Any],
             window: Sequence[_dt.date], can_take: Sequence[str]
             ) -> List[Dict[str, Any]]:
    """Each leader's side of it: the time the team takes from their day, and
    the coming meetings with what to go through in each."""
    from . import management as management_module

    points = {p["name"]: p["checkpoints"] for p in people}
    signals = {p["name"]: p["signal"]["label"] for p in people}
    hours = management.hours_a_day()
    out = []
    for name, led in management.led.items():
        meetings = []
        for day in window:
            for meeting in management.meetings_on(day):
                if meeting["leader"] != name:
                    continue
                meetings.append({
                    "date": day.isoformat(),
                    "start": meeting["start"].strftime("%H:%M"),
                    "end": meeting["end"].strftime("%H:%M"),
                    "kind": meeting["kind"],
                    "title": ("Team meeting" if meeting["kind"] == "team"
                              else f"One-to-one with {meeting['with'][0]}"),
                    "with": meeting["with"],
                    "agenda": management_module.agenda(
                        meeting, checkpoints=points, signals=signals, tasks=tasks,
                        day=day, config=config, can_take=can_take),
                })
        out.append({
            "name": name,
            "people": sorted(p["name"] for p in led),
            "support_hours": management.support.get(name, 0.0),
            "hours_a_day": hours.get(name, 0.0),
            "meetings": meetings,
        })
    return out
