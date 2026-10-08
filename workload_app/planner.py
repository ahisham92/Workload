"""The coming days: who has what, and what handing some of it over would do.

Nobody has to plan anything for this to work.  The timesheets already say
what each person has been doing lately -- so many hours a day on this project,
so many on that -- and the plain assumption is that, left alone, they carry on
at that pace.  That is each person's **pace**, read from the last two working
weeks the timesheets hold.  Open tasks due in the window count too, and where
a person's tasks on a project need more than their pace gives it, the tasks
win: they are somebody saying so.

A manager then moves work, and sees what it does before anything changes:

* **a share of a project** -- "half of Osama's time on the jetty goes to
  Kirolos for the next five days" -- moves that much of the pace, and the
  drawings still to do on it follow, since drawings in hand are shared out by
  who is working on the project;
* **a task** -- it changes hands, whole.

Nothing is written until it is committed.  Committed project moves are kept
for the window they were made for, and then lapse by themselves; a moved task
is simply reassigned.

Pace is history, not a promise.  When the newest timesheet is weeks old the
outlook says so, because a pace that old is a guess.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import calendar_
from . import config as cfg
from . import derive
from . import people as people_module
from . import tasks as task_sheet
from .model import ValidationError

#: Working days of bookings a pace is read from.
LOOKBACK_DAYS = 10
#: How far ahead, in working days, the planner looks.
DEFAULT_DAYS = 5
DAY_CHOICES = (3, 5, 10, 15)
#: A person above this share of their hours is overloaded; below the second
#: they have room.  The same lines the Tasks tab draws.
OVER = 1.0
ROOM = 0.8
#: A suggestion fills a person to here at most, so it never solves one
#: overload by making another.
FILL_TO = 0.9
#: The most moves a suggestion offers -- past that it is a reorganisation,
#: which is the Resourcing tab's job, not the next few days'.
MAX_SUGGESTIONS = 8
#: A newest timesheet older than this makes the pace a guess, and says so.
STALE_AFTER_DAYS = 21


#: A what-if's new work: hours on somebody over the days on show.  Tried
#: and kept as a what-if, never committed -- real new work goes under Work
#: coming or the task list.
EXTRA = "extra"
EXTRA_LONGEST_HOURS = 400.0
#: The key new work is kept under in a person's items.
NEW_PREFIX = "new:"


class PlanError(ValidationError):
    pass


# --------------------------------------------------------------------------
# days
# --------------------------------------------------------------------------

def _working_days(day: _dt.date, count: int, config: Dict[str, Any],
                  step: int) -> List[_dt.date]:
    """Up to ``count`` working days from ``day`` on, a day at a time by ``step``."""
    out: List[_dt.date] = []
    for _ in range(400):
        if len(out) >= count:
            break
        if task_sheet.is_working_day(day, config):
            out.append(day)
        day += _dt.timedelta(days=step)
    return out


def days_ahead(today: _dt.date, count: int, config: Dict[str, Any]) -> List[_dt.date]:
    """The next ``count`` working days, today included if it is one."""
    return _working_days(today, count, config, 1)


def days_back(last: _dt.date, count: int, config: Dict[str, Any]) -> List[_dt.date]:
    """The ``count`` working days up to and including ``last``."""
    return sorted(_working_days(last, count, config, -1))


def clean_days(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return min(max(days, 1), 30)


# --------------------------------------------------------------------------
# pace
# --------------------------------------------------------------------------

def pace(rows: Iterable[Dict[str, Any]], config: Dict[str, Any], *,
         lookback: int = LOOKBACK_DAYS) -> Dict[str, Any]:
    """Hours a working day each person has been putting into each project."""
    rows = list(rows)
    project_rows = [r for r in rows if r.get("date") and r.get("job_number")
                    and derive.is_project_work(r.get("job_type") or "")]
    if not project_rows:
        return {"rates": {}, "from": None, "to": None, "days": 0}
    last = max(r["date"] for r in project_rows)
    window = days_back(last, lookback, config)
    first = window[0]
    sums: Dict[Tuple[str, str], float] = defaultdict(float)
    for row in project_rows:
        if first <= row["date"] <= last:
            sums[(row["engineer"], row["job_number"])] += float(row["hours"] or 0.0)
    # Days somebody was off do not count against their pace: a week of leave
    # in the fortnight does not make them half as quick.
    # Nor do the days before somebody joined: three days in at full speed is
    # full speed, not a third of it.
    joined: Dict[str, _dt.date] = {}
    for row in rows:
        name, day = row.get("engineer"), row.get("date")
        if name and day and (name not in joined or day < joined[name]):
            joined[name] = day
    present = {name: max(1, calendar_.present_days(
                   config, name, [d for d in window
                                  if name not in joined or d >= joined[name]]))
               for name, _project in sums}
    rates = {key: value / present[key[0]] for key, value in sums.items() if value > 0}
    return {"rates": rates, "from": first, "to": last, "days": len(window)}


# --------------------------------------------------------------------------
# moves
# --------------------------------------------------------------------------

def _parse_share(value: Any) -> Optional[float]:
    try:
        share = float(value)
    except (TypeError, ValueError):
        return None
    if share > 1.0 + 1e-9:          # typed as a percentage
        share /= 100.0
    return share


def clean_moves(raw: Any, *, people: Iterable[str],
                tasks: Sequence[task_sheet.Task]) -> List[Dict[str, Any]]:
    """Moves from a request, checked against who and what exist."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise PlanError(["Moves have to be a list."])
    known = set(people)
    by_id = {t.id: t for t in tasks}
    out: List[Dict[str, Any]] = []
    errors: List[str] = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            errors.append(f"Move {position} is not a move.")
            continue
        kind = item.get("kind") or ("task" if item.get("task_id") else "project")
        source = str(item.get("from") or "").strip()
        target = str(item.get("to") or "").strip()
        if kind == EXTRA:
            label = " ".join(str(item.get("project") or "").split())[:60]
            try:
                hours = float(item.get("hours"))
            except (TypeError, ValueError):
                hours = -1.0
            if target not in known:
                errors.append(f"Move {position}: {target or 'nobody'} is not on this "
                              f"unit's team.")
            elif not label:
                errors.append(f"Move {position}: say what the new work is.")
            elif not 0 < hours <= EXTRA_LONGEST_HOURS:
                errors.append(f"Move {position}: new work is more than 0 and at most "
                              f"{EXTRA_LONGEST_HOURS:g} hours.")
            else:
                out.append({"kind": EXTRA, "project": label, "to": target,
                            "hours": round(hours, 1)})
            continue
        if not source or not target:
            errors.append(f"Move {position} needs somebody to move it from and to.")
            continue
        if source == target:
            errors.append(f"Move {position} hands {source}'s work to {source}.")
            continue
        if target not in known:
            errors.append(f"{target} is not on this unit's team.")
            continue
        if kind == "task":
            try:
                task = by_id.get(int(item.get("task_id")))
            except (TypeError, ValueError):
                task = None
            if task is None or task.done:
                errors.append(f"Move {position}: there is no such open task.")
                continue
            if source not in task.assignees:
                errors.append(f"{source} is not on task {task.name or task.id}.")
                continue
            out.append({"kind": "task", "task_id": task.id, "from": source,
                        "to": target})
        else:
            project = str(item.get("project") or "").strip()
            share = _parse_share(item.get("share", 1.0))
            if not project:
                errors.append(f"Move {position} needs a project.")
                continue
            if share is None or share <= 0 or share > 1.0 + 1e-9:
                errors.append(f"Move {position}: a share is more than 0 and at most 100%.")
                continue
            out.append({"kind": "project", "project": project, "from": source,
                        "to": target, "share": round(min(share, 1.0), 4)})
    if errors:
        raise PlanError(errors)
    return out


def _apply_project_moves(rates: Dict[Tuple[str, str], float],
                         moves: Iterable[Dict[str, Any]]
                         ) -> Tuple[Dict[Tuple[str, str], float], List[float]]:
    """The pace after each project move, and how much each one moved."""
    out = dict(rates)
    moved: List[float] = []
    for move in moves:
        key = (move["from"], move["project"])
        amount = out.get(key, 0.0) * move["share"]
        moved.append(amount)
        if amount <= 0:
            continue
        out[key] = out.get(key, 0.0) - amount
        if out[key] <= 1e-9:
            out.pop(key)
        target = (move["to"], move["project"])
        out[target] = out.get(target, 0.0) + amount
    return out, moved


def rates_in_force(rates: Dict[Tuple[str, str], float],
                   saved: Iterable[Dict[str, Any]], day: _dt.date
                   ) -> Dict[Tuple[str, str], float]:
    """The pace on ``day``, with the committed handovers in force then."""
    return _apply_project_moves(rates, _active_saved(saved, day, day))[0]


def _apply_task_moves(assignees: Dict[int, List[str]],
                      moves: Iterable[Dict[str, Any]]) -> Dict[int, List[str]]:
    out = {key: list(value) for key, value in assignees.items()}
    for move in moves:
        names = out.get(move["task_id"])
        if names is None or move["from"] not in names:
            continue
        names = [move["to"] if n == move["from"] else n for n in names]
        out[move["task_id"]] = list(dict.fromkeys(names))
    return out


# --------------------------------------------------------------------------
# the outlook
# --------------------------------------------------------------------------

def _active_saved(saved: Iterable[Dict[str, Any]], start: _dt.date,
                  end: _dt.date) -> List[Dict[str, Any]]:
    out = []
    for move in saved:
        try:
            first = _dt.date.fromisoformat(move["start"])
            last = _dt.date.fromisoformat(move["end"])
        except (TypeError, ValueError):
            continue
        if first <= end and last >= start:
            out.append({"kind": "project", "id": move["id"],
                        "project": move["project"], "from": move["from_person"],
                        "to": move["to_person"], "share": move["share"],
                        "start": move["start"], "end": move["end"]})
    return out


def _state(*, rates, assignees, tasks_by_id, window: List[_dt.date],
           today: _dt.date, drawings_left: Mapping[str, float],
           present: Mapping[str, int]) -> Dict[str, Dict[str, Any]]:
    """Each person's hours in the window, project by project.

    Usual work runs only on the days a person is in; tasks and requests are
    theirs whenever they fall.
    """
    days = len(window)
    end = window[-1] if window else today
    pace_hours: Dict[str, Dict[str, float]] = defaultdict(dict)
    for (person, project), rate in rates.items():
        pace_hours[person][project] = rate * present.get(person, days)
    task_hours: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    # Requests came in on top of the usual work, so they add to it rather
    # than standing in for part of it the way a planned task does.
    extra_hours: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    task_ids: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    for task_id, names in assignees.items():
        task = tasks_by_id[task_id]
        if task.due is None or task.due > end or not task.required_hours:
            continue
        each = task.required_hours / max(1, len(names))
        key = task.project_number or f"task:{task.id}"
        bucket = extra_hours if task.kind == cfg.TASK_REQUEST_KIND else task_hours
        for name in names:
            bucket[name][key] += each
            task_ids[name][key].append(task.id)

    # Drawings in hand: what is left on a project, shared out by who is
    # working on it at the pace this state has.
    on_project: Dict[str, float] = defaultdict(float)
    for (_person, project), rate in rates.items():
        on_project[project] += rate

    out: Dict[str, Dict[str, Any]] = {}
    for person in set(pace_hours) | set(task_hours) | set(extra_hours):
        items: Dict[str, Dict[str, Any]] = {}
        own_pace = pace_hours.get(person, {})
        own_tasks = task_hours.get(person, {})
        own_requests = extra_hours.get(person, {})
        for key in set(own_pace) | set(own_tasks) | set(own_requests):
            from_pace = own_pace.get(key, 0.0)
            from_tasks = own_tasks.get(key, 0.0)
            from_requests = own_requests.get(key, 0.0)
            rate = rates.get((person, key), 0.0)
            in_hand = (drawings_left.get(key, 0.0) * rate / on_project[key]
                       if on_project.get(key) else 0.0)
            items[key] = {
                "key": key,
                "pace_hours": from_pace,
                "task_hours": from_tasks + from_requests,
                "hours": max(from_pace, from_tasks) + from_requests,
                "rate": rate,
                "tasks": task_ids.get(person, {}).get(key, []),
                "drawings": in_hand,
            }
        out[person] = {
            "items": items,
            "hours": sum(item["hours"] for item in items.values()),
            "drawings": sum(item["drawings"] for item in items.values()),
        }
    return out


def outlook(*, rows: Sequence[Dict[str, Any]], tasks: Sequence[task_sheet.Task],
            roster: Sequence[Dict[str, Any]], config: Dict[str, Any],
            project_names: Mapping[str, str], drawings_left: Mapping[str, float],
            saved: Sequence[Dict[str, Any]] = (), moves: Sequence[Dict[str, Any]] = (),
            today: Optional[_dt.date] = None, days: int = DEFAULT_DAYS,
            team_names: Optional[Mapping[str, str]] = None,
            management: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    """Who has what over the next few working days, before and after ``moves``.

    ``management`` is the hours a day that are not project work for each
    person -- leading people and their own development time
    (``management.Plan.taken_a_day``).
    """
    management = management or {}
    today = today or _dt.date.today()
    window = days_ahead(today, days, config)
    end = window[-1] if window else today
    a_day = task_sheet.hours_per_day(config)
    measured = pace(rows, config)
    active_saved = _active_saved(saved, today, end)
    base_rates, _ = _apply_project_moves(measured["rates"], active_saved)

    open_tasks = [t for t in tasks if not t.done]
    tasks_by_id = {t.id: t for t in open_tasks}
    base_assignees = {t.id: list(t.assignees) for t in open_tasks if t.assignees}

    project_moves = [m for m in moves if m["kind"] == "project"]
    task_moves = [m for m in moves if m["kind"] == "task"]
    extra_moves = [m for m in moves if m["kind"] == EXTRA]
    after_rates, moved_amounts = _apply_project_moves(base_rates, project_moves)
    after_assignees = _apply_task_moves(base_assignees, task_moves)

    everybody = ({p["name"] for p in roster} | {k[0] for k in measured["rates"]}
                 | {n for names in base_assignees.values() for n in names}
                 | {m["to"] for m in moves})
    present = {name: calendar_.present_days(config, name, window)
               for name in everybody}
    # New work being tried: its hours spread over the days the person is in.
    for move in extra_moves:
        key = (move["to"], NEW_PREFIX + move["project"])
        after_rates[key] = (after_rates.get(key, 0.0)
                            + move["hours"] / max(1, present.get(move["to"], len(window))))
    before = _state(rates=base_rates, assignees=base_assignees,
                    tasks_by_id=tasks_by_id, window=window, today=today,
                    drawings_left=drawings_left, present=present)
    after = _state(rates=after_rates, assignees=after_assignees,
                   tasks_by_id=tasks_by_id, window=window, today=today,
                   drawings_left=drawings_left, present=present)

    people = {p["name"]: p for p in roster}
    names = [p["name"] for p in roster if p.get("active", True)]
    names += sorted((set(before) | set(after)) - set(names))
    # A full person's hours in the window; each person's own leaves out the
    # days they are away.
    capacity = len(window) * a_day

    def figure(state: Dict[str, Any], own: float) -> Dict[str, Any]:
        hours = state.get("hours", 0.0) if state else 0.0
        return {
            "hours": round(hours, 1),
            "load": round(hours / own, 3) if own else (None if not hours else 9.99),
            "drawings": round(state.get("drawings", 0.0), 1) if state else 0.0,
        }

    def label(key: str) -> str:
        if key.startswith("task:"):
            task = tasks_by_id.get(int(key.split(":", 1)[1]))
            return task.name if task else key
        if key.startswith(NEW_PREFIX):
            return f"New: {key[len(NEW_PREFIX):]}"
        return project_names.get(key) or key

    out_people = []
    for name in names:
        person = people.get(name) or {}
        grade = person.get("grade") or people_module.DEFAULT_GRADE
        b, a = before.get(name, {}), after.get(name, {})
        b_items, a_items = b.get("items") or {}, a.get("items") or {}
        items = []
        for key in set(b_items) | set(a_items):
            bi = b_items.get(key) or {}
            ai = a_items.get(key) or {}
            items.append({
                "key": key,
                "project": "" if key.startswith(("task:", NEW_PREFIX)) else key,
                "name": label(key),
                "hours_before": round(bi.get("hours", 0.0), 1),
                "hours_after": round(ai.get("hours", 0.0), 1),
                "pace_before": round(bi.get("rate", 0.0), 2),
                "pace_after": round(ai.get("rate", 0.0), 2),
                "task_hours": round(ai.get("task_hours", bi.get("task_hours", 0.0)), 1),
                "tasks": sorted(set(bi.get("tasks", []) + ai.get("tasks", []))),
                "drawings_before": round(bi.get("drawings", 0.0), 1),
                "drawings_after": round(ai.get("drawings", 0.0), 1),
            })
        items.sort(key=lambda item: -max(item["hours_before"], item["hours_after"]))
        days_in = present.get(name, len(window))
        own = days_in * max(0.0, a_day - management.get(name, 0.0))
        fb, fa = figure(b, own), figure(a, own)
        out_people.append({
            "name": name,
            "team_id": person.get("team_id"),
            "team_name": person.get("team_name", ""),
            "grade": grade,
            "grade_label": people_module.grade_label(grade),
            "role": people_module.role_of(grade),
            "capacity": round(own, 1),
            "away_days": len(window) - days_in,
            "before": fb,
            "after": fa,
            "verdict_before": verdict(fb["load"]) if own or fb["hours"] else "away",
            "verdict_after": verdict(fa["load"]) if own or fa["hours"] else "away",
            "items": items,
        })

    team_rows: Dict[Any, Dict[str, Any]] = {}
    for person in out_people:
        key = person["team_id"] or people_module.UNASSIGNED
        team = team_rows.setdefault(key, {
            "id": key,
            "name": person["team_name"] or (
                (team_names or {}).get(key) or people_module.NO_TEAM),
            "people": 0, "capacity": 0.0,
            "before_hours": 0.0, "after_hours": 0.0,
            "over_before": 0, "over_after": 0,
            "drawings_before": 0.0, "drawings_after": 0.0})
        team["people"] += 1
        team["capacity"] += person["capacity"]
        team["before_hours"] += person["before"]["hours"]
        team["after_hours"] += person["after"]["hours"]
        team["drawings_before"] += person["before"]["drawings"]
        team["drawings_after"] += person["after"]["drawings"]
        team["over_before"] += person["verdict_before"] == "over"
        team["over_after"] += person["verdict_after"] == "over"
    teams = []
    for team in sorted(team_rows.values(), key=lambda t: t["name"]):
        cap = team["capacity"]
        teams.append({**team,
                      "capacity": round(cap, 1),
                      "before_hours": round(team["before_hours"], 1),
                      "after_hours": round(team["after_hours"], 1),
                      "drawings_before": round(team["drawings_before"], 1),
                      "drawings_after": round(team["drawings_after"], 1),
                      "before_load": round(team["before_hours"] / cap, 3) if cap else None,
                      "after_load": round(team["after_hours"] / cap, 3) if cap else None})

    described = []
    amounts = iter(moved_amounts)
    for move in moves:
        entry = dict(move)
        if move["kind"] == "project":
            entry["hours"] = round(next(amounts) * present.get(move["from"], len(window)), 1)
            entry["name"] = project_names.get(move["project"]) or move["project"]
        elif move["kind"] == EXTRA:
            entry["name"] = move["project"]
        else:
            task = tasks_by_id.get(move["task_id"])
            entry["name"] = task.name if task else str(move["task_id"])
            entry["hours"] = round(task.hours_each(), 1) if task else 0.0
        described.append(entry)

    loads_before = [p["before"]["load"] or 0 for p in out_people]
    loads_after = [p["after"]["load"] or 0 for p in out_people]
    data_through = measured["to"]
    return {
        "from": window[0].isoformat() if window else today.isoformat(),
        "to": end.isoformat(),
        "days": len(window),
        "day_choices": list(DAY_CHOICES),
        "hours_per_day": round(a_day, 2),
        "capacity": round(capacity, 1),
        "pace_from": measured["from"].isoformat() if measured["from"] else None,
        "pace_to": data_through.isoformat() if data_through else None,
        "stale": bool(data_through and (today - data_through).days > STALE_AFTER_DAYS),
        "people": out_people,
        "teams": teams,
        "moves": described,
        "saved": active_saved,
        "summary": {
            "over_before": sum(1 for p in out_people if p["verdict_before"] == "over"),
            "over_after": sum(1 for p in out_people if p["verdict_after"] == "over"),
            "room_before": sum(1 for p in out_people if p["verdict_before"] == "room"),
            "room_after": sum(1 for p in out_people if p["verdict_after"] == "room"),
            "away": sum(1 for p in out_people if p["away_days"]),
            "peak_before": round(max(loads_before), 3) if loads_before else None,
            "peak_after": round(max(loads_after), 3) if loads_after else None,
            "hours": round(sum(p["after"]["hours"] for p in out_people), 1),
        },
        "thresholds": {"over": OVER, "room": ROOM},
    }


def verdict(load: Optional[float]) -> str:
    if load is None:
        return "unknown"
    if load > OVER + 1e-9:
        return "over"
    if load < ROOM:
        return "room"
    return "full"


# --------------------------------------------------------------------------
# suggesting moves
# --------------------------------------------------------------------------

def suggest(*, rows: Sequence[Dict[str, Any]], tasks: Sequence[task_sheet.Task],
            roster: Sequence[Dict[str, Any]], config: Dict[str, Any],
            project_names: Mapping[str, str], drawings_left: Mapping[str, float],
            saved: Sequence[Dict[str, Any]] = (), moves: Sequence[Dict[str, Any]] = (),
            today: Optional[_dt.date] = None, days: int = DEFAULT_DAYS,
            management: Optional[Mapping[str, float]] = None,
            ) -> List[Dict[str, Any]]:
    """Moves that bring the overloaded back under a full load, if any can.

    Work only goes to somebody doing the same kind of work -- a draftsman's
    drawings to another draftsman, an engineer's design to another engineer --
    and to whoever has room: first somebody who has worked on that project
    before, then somebody in the same team, then anyone, the least loaded
    first.  Nobody is filled past ``FILL_TO`` to relieve somebody else.
    """
    plan = list(moves)
    history: Dict[str, set] = defaultdict(set)
    for row in rows:
        if row.get("job_number"):
            history[row["job_number"]].add(row["engineer"])
    proposed: List[Dict[str, Any]] = []
    tried: set = set()
    for _round in range(MAX_SUGGESTIONS * 3):
        if len(proposed) >= MAX_SUGGESTIONS:
            break
        view = outlook(rows=rows, tasks=tasks, roster=roster, config=config,
                       project_names=project_names, drawings_left=drawings_left,
                       saved=saved, moves=plan, today=today, days=days,
                       management=management)
        if not view["capacity"]:
            break
        over = sorted((p for p in view["people"] if p["verdict_after"] == "over"
                       and p["name"] not in tried),
                      key=lambda p: -(p["after"]["load"] or 0))
        if not over:
            break
        person = over[0]
        excess = person["after"]["hours"] - person["capacity"] * OVER
        move = None
        for item in person["items"]:
            if not item["project"] or item["pace_after"] <= 0:
                continue
            pace_hours = item["pace_after"] * (view["days"] - person["away_days"])
            # Only the part of the pace above any tasks there actually lowers
            # this person's hours.
            movable = pace_hours - min(pace_hours, item["task_hours"])
            if movable < 1:
                continue
            target = _best_target(view, person, item["project"], history)
            if target is None:
                continue
            room = target["capacity"] * FILL_TO - target["after"]["hours"]
            amount = min(excess, room, movable)
            if amount < 1:
                continue
            share = math.ceil(amount / pace_hours * 20) / 20     # in 5% steps
            move = {"kind": "project", "project": item["project"],
                    "from": person["name"], "to": target["name"],
                    "share": round(min(1.0, share), 2)}
            break
        if move is None:
            tried.add(person["name"])
            continue
        plan.append(move)
        proposed.append(move)
    return proposed


def _best_target(view: Dict[str, Any], person: Dict[str, Any], project: str,
                 history: Mapping[str, set]) -> Optional[Dict[str, Any]]:
    candidates = [
        p for p in view["people"]
        if p["name"] != person["name"] and p["role"] == person["role"]
        and p["after"]["hours"] < p["capacity"] * FILL_TO - 1
    ]
    knows = history.get(project, set())
    return min(candidates, default=None, key=lambda p: (
        p["name"] not in knows,
        (p["team_id"] or "") != (person["team_id"] or ""),
        p["after"]["load"] or 0,
        p["name"]))
