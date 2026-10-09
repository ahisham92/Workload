"""When a team needs more people, how many, for how long -- and when it does not.

The work ahead is the projects' own forecast, week by week:

* a **confirmed** project still to finish has its effort to complete
  (``remaining_mm``, the same figure the Map draws) spread evenly from today to
  its end date -- or, when that date has already gone, over the next
  ``LATE_SPREAD_WEEKS``, because the work is still there to do and the date is
  what was wrong;
* a project the timesheets set up and nobody has confirmed yet has no budget
  worth forecasting from, so its recent **pace** is taken to carry on while it
  is live.  It is marked as assumed, and confirming the project replaces the
  assumption with its real figures;
* a project **just assigned**, that nobody has booked to yet, is its rough
  hours spread from its start to its end, less what has been booked since,
  until its own figures or the timesheets take over (see ``incoming``);
* where a project has **drawings** still to do and the unit has a drawing
  rate of its own, the drawing office's share of that project is its drawings
  left times the hours a drawing takes -- drawings are the one measure here
  that does not depend on anybody's estimate of effort.

Each project's work is shared between teams and between engineers and
draftsmen the way its recent hours were, because that is who is doing it.
Against it stands each team's capacity -- its people of that kind, times the
working hours in the week, less public holidays and anybody's booked time off.  The gap, in people, is the answer:

* **ask for more** when a team is short by half a person or more for a run of
  weeks: how many (the peak of the run, rounded), from when, until when, and
  when to ask so they arrive in time;
* **room** when a team has a whole person spare for most of a month;
* and **no more needed** said outright, because "nothing flagged" and "we
  checked, you are fine" are not the same thing to a lead deciding whether to
  ask.

Everything is a forecast built on the projects' own figures; the alert says
what it rests on.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import Counter, defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import calendar_
from . import derive
from . import people as people_module
from . import planner
from . import tasks as task_sheet
from .tasks import week_start
from .model import today as _today

#: How far ahead the forecast looks, in weeks.
HORIZON_WEEKS = 12
#: An overrunning project's work is spread over this many weeks from now.
LATE_SPREAD_WEEKS = 6
#: Short by at least this many people in a week counts as short.
SHORT_AT = 0.5
#: Short for fewer weeks than this is somebody away or a busy week: the
#: Planner's handovers cover it, nobody is hired for it.
MIN_NEED_WEEKS = 2
#: Spare by at least this many people counts as room.
ROOM_AT = 1.0
#: Room has to last this long to be worth saying.
ROOM_WEEKS = 3
#: How long it takes to get somebody: ask this many weeks before they are
#: needed.
LEAD_WEEKS = 2
#: An unconfirmed project still counts as live if somebody booked to it this
#: recently.
LIVE_WITHIN_DAYS = 45
#: Weeks of history a project's split between teams and kinds of work is read
#: from.
SPLIT_WEEKS = 13


def _monday(day: _dt.date) -> _dt.date:
    return day - _dt.timedelta(days=day.weekday())


def weeks_ahead(today: _dt.date, count: int,
                config: Optional[Dict[str, Any]] = None
                ) -> List[Tuple[_dt.date, _dt.date]]:
    """``count`` weeks from today, each as (first day, last day).

    The first week starts today rather than on its first day, so a forecast
    made on a Wednesday does not count the days before it as still to work.
    With ``config`` the weeks are the unit's own: Sunday to Saturday where the
    working week starts on a Sunday, so a forecast made on a Sunday in Cairo
    does not open with a week of one day.
    """
    out = []
    start = today
    for _ in range(count):
        first = week_start(start, config) if config else _monday(start)
        end = first + _dt.timedelta(days=6)
        out.append((start, end))
        start = end + _dt.timedelta(days=1)
    return out


def forecast(*, rows: Sequence[Dict[str, Any]], project_rows: Sequence[Dict[str, Any]],
             projects: Sequence[Any], roster: Sequence[Dict[str, Any]],
             config: Dict[str, Any], hours_per_mm: float,
             drawings_left: Mapping[str, float],
             drafting_hours_per_drawing: Optional[float],
             today: Optional[_dt.date] = None, weeks: int = HORIZON_WEEKS,
             unit_name: str = "",
             requests: Sequence[Tuple[str, _dt.date, float]] = (),
             planned: Sequence[Dict[str, Any]] = (),
             team_names: Optional[Mapping[str, str]] = None,
             management: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    today = today or _today()
    # Leading people takes part of a leader's day; that part does no project work.
    management = management or {}
    hours_per_mm = float(hours_per_mm or 0) or 185.0
    a_day = task_sheet.hours_per_day(config)
    span = weeks_ahead(today, weeks, config)
    week_dates = [task_sheet.working_days(a, b, config) for a, b in span]
    week_days = [len(days) for days in week_dates]
    person_week = [d * a_day for d in week_days]
    horizon_end = span[-1][1]

    people = {p["name"]: p for p in roster}
    teams = {t["id"]: t["name"] for t in _teams(roster)}
    for team_id, name in (team_names or {}).items():
        teams.setdefault(team_id, name)

    def bucket(name: str) -> Tuple[str, str]:
        person = people.get(name) or {}
        return (person.get("team_id") or people_module.UNASSIGNED,
                people_module.role_of(person.get("grade")))

    # -- who does each project's work: recent hours by team and kind -------
    # Leave booked ahead is on the timesheets too; it is no part of who has
    # been doing what, nor of how recent the data is.
    dated = [r for r in rows if r.get("date") and r.get("job_number")
             and r["date"] <= today]
    last_day = max((r["date"] for r in dated), default=None)
    since = last_day - _dt.timedelta(weeks=SPLIT_WEEKS) if last_day else None
    split: Dict[str, Dict[Tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
    whole: Dict[str, Dict[Tuple[str, str], float]] = defaultdict(lambda: defaultdict(float))
    last_booked: Dict[str, _dt.date] = {}
    booked: Dict[str, float] = defaultdict(float)
    for row in dated:
        number, hours = row["job_number"], row["hours"] or 0.0
        key = bucket(row["engineer"])
        if row["date"] >= since:
            split[number][key] += hours
        whole[number][key] += hours
        if number not in last_booked or row["date"] > last_booked[number]:
            last_booked[number] = row["date"]
        booked[number] += hours

    rates = planner.pace(rows, config)["rates"]
    rate_by_project: Dict[str, float] = defaultdict(float)
    for (_person, number), rate in rates.items():
        rate_by_project[number] += rate

    register = {p.number: p for p in projects}
    demand: Dict[Tuple[str, str], List[float]] = defaultdict(lambda: [0.0] * len(span))

    # -- work coming: projects just assigned, on their rough hours -------
    by_team: Dict[str, Dict[Tuple[str, str], float]] = defaultdict(dict)
    for key, hours in (sum((Counter(v) for v in split.values()), Counter())).items():
        by_team[key[0]][key] = hours
    figures_by_number = {f["number"]: f for f in project_rows}
    coming: List[Dict[str, Any]] = []
    counted_numbers = set()
    for item in planned:
        number = item.get("job_number") or ""
        project = register.get(number) if number else None
        own = figures_by_number.get(number) or {}
        start = _dt.date.fromisoformat(item["start"])
        end = _dt.date.fromisoformat(item["end"])
        done = booked.get(number, 0.0) if number else 0.0
        left = max(0.0, float(item["hours"]) - done)
        if project is not None and not derive.needs_confirming(project.notes or "") \
                and (own.get("remaining_mm") or 0) > 0:
            status = "taken over"
        elif left <= 0:
            status = "used up"
        elif done > 0:
            status = "started"
        elif start > today:
            status = "waiting"
        else:
            status = "due to start"
        weekly = [0.0] * len(span)
        if status in ("started", "waiting", "due to start"):
            first = max(start, today)
            last = end if end >= first + _dt.timedelta(days=7) else \
                first + _dt.timedelta(weeks=LATE_SPREAD_WEEKS) - _dt.timedelta(days=1)
            weekly = _spread(left, first, last, span, config)
            if number:
                counted_numbers.add(number)
            team_key = item.get("team_id") or people_module.UNASSIGNED
            shares = (split.get(number) or whole.get(number) if number else None) \
                or by_team.get(team_key) \
                or {(team_key, people_module.ROLE_ENGINEERING): 1.0}
            total = sum(shares.values()) or 1.0
            for key, value in shares.items():
                target = demand[key]
                for i, hours in enumerate(weekly):
                    target[i] += hours * value / total
        coming.append({
            "id": item.get("id"), "name": item["name"], "job_number": number,
            "team_id": item.get("team_id") or "",
            "team_name": teams.get(item.get("team_id") or "", ""),
            "hours": round(float(item["hours"]), 1), "booked": round(done, 1),
            "left": round(left, 1), "start": item["start"], "end": item["end"],
            "status": status, "in_horizon": round(sum(weekly), 1),
        })

    # -- the work ahead, project by project, week by week -----------------
    assumed: List[str] = []
    late: List[str] = []
    unstaffed: List[str] = []
    for figures in project_rows:
        number = figures["number"]
        project = register.get(number)
        if project is None or not figures.get("in_scope", True):
            continue
        if number in counted_numbers:
            continue                      # read from its rough hours above
        shares = split.get(number) or whole.get(number) or {}
        total_share = sum(shares.values())
        weekly = [0.0] * len(span)
        confirmed = not derive.needs_confirming(getattr(project, "notes", "") or "")
        remaining = max(0.0, float(figures.get("remaining_mm") or 0.0)) * hours_per_mm
        if confirmed and remaining > 0:
            if project.end is not None and project.end < today:
                late.append(number)
            weekly = _spread(remaining, today, _spread_end(project, today, confirmed),
                             span, config)
        elif not confirmed:
            seen = last_booked.get(number)
            if seen and (today - seen).days <= LIVE_WITHIN_DAYS and rate_by_project.get(number):
                weekly = [rate_by_project[number] * d for d in week_days]
                assumed.append(number)
        if not any(weekly):
            continue
        if not total_share:
            unstaffed.append(number)
            shares = {(people_module.UNASSIGNED, people_module.ROLE_ENGINEERING): 1.0}
            total_share = 1.0

        # The drawing office's part, from drawings left where that is known.
        drafting_keys = [k for k in shares if k[1] == people_module.ROLE_DRAFTING]
        left = drawings_left.get(number) or 0.0
        by_drawings = None
        if confirmed and left and drafting_hours_per_drawing and drafting_keys:
            by_drawings = _spread(left * drafting_hours_per_drawing, today,
                                  _spread_end(project, today, confirmed), span, config)
        drafting_share = sum(shares[k] for k in drafting_keys)
        for key, value in shares.items():
            fraction = value / total_share
            if by_drawings is not None and key[1] == people_module.ROLE_DRAFTING:
                own = value / drafting_share if drafting_share else 0.0
                series = [h * own for h in by_drawings]
            else:
                series = [h * fraction for h in weekly]
            target = demand[key]
            for i, hours in enumerate(series):
                target[i] += hours

    # Requests that came in sit on top of the projects' own work, in the
    # week they are due, with the team and kind of whoever has them.
    for name, due, hours in requests:
        for i, (first, last) in enumerate(span):
            if first <= max(due, today) <= last:
                demand[bucket(name)][i] += hours
                break

    # -- capacity, and the gap ------------------------------------------
    headcount: Dict[Tuple[str, str], int] = defaultdict(int)
    # Hours each team and kind has, week by week: a public holiday is not a
    # working day, and somebody away is not counted for the days they are.
    supply: Dict[Tuple[str, str], List[float]] = defaultdict(lambda: [0.0] * len(span))
    away_days: Dict[Tuple[str, str], List[int]] = defaultdict(lambda: [0] * len(span))
    for person in roster:
        if person.get("active", True):
            key = bucket(person["name"])
            headcount[key] += 1
            for i, days in enumerate(week_dates):
                present = calendar_.present_days(config, person["name"], days)
                supply[key][i] += present * max(
                    0.0, a_day - management.get(person["name"], 0.0))
                away_days[key][i] += _whole(len(days) - present)

    groups = []
    alerts = []
    for key in sorted(set(demand) | set(headcount),
                      key=lambda k: (teams.get(k[0], "~"), k[1])):
        team_id, role = key
        heads = headcount.get(key, 0)
        work = demand.get(key, [0.0] * len(span))
        if not heads and not any(work):
            continue
        team_name = teams.get(team_id) or (unit_name if len(teams) == 0 else people_module.NO_TEAM) \
            or "The unit"
        series = []
        for i, (first, last) in enumerate(span):
            cap = supply[key][i] if key in supply else 0.0
            gap = (work[i] - cap) / person_week[i] if person_week[i] else 0.0
            series.append({
                "from": first.isoformat(), "to": last.isoformat(),
                "demand_hours": round(work[i], 1),
                "capacity_hours": round(cap, 1),
                "away_days": _whole(away_days[key][i]) if key in away_days else 0,
                "load": round(work[i] / cap, 3) if cap else None,
                "gap_people": round(gap, 2),
            })
        group = {"team_id": team_id, "team_name": team_name, "role": role,
                 "role_label": people_module.role_label(role),
                 "people": heads, "weeks": series}
        groups.append(group)
        alerts.extend(_alerts(group, today))

    # One line per team and kind with nothing to ask for, so a lead reading
    # the list knows they were looked at, not forgotten.
    needing = {(a["team_id"], a["role"]) for a in alerts if a["kind"] in ("need", "cover")}
    for group in groups:
        key = (group["team_id"], group["role"])
        if key in needing or not group["people"]:
            continue
        alerts.append({
            "kind": "fine", "severity": "ok",
            "team_id": group["team_id"], "team_name": group["team_name"],
            "role": group["role"],
            "title": f"{group['team_name']}: no more {people_module.role_label(group['role'], 2)} needed",
            "detail": f"The work forecast to {horizon_end:%d %b} fits the "
                      f"{group['people']} {people_module.role_label(group['role'], group['people'])} "
                      f"the team has.",
            "people": 0, "weeks": 0, "from": None, "to": None, "ask_by": None,
        })
    order = {"now": 0, "soon": 1, "cover": 2, "room": 3, "ok": 4}
    alerts.sort(key=lambda a: (order.get(a["severity"], 9), a["team_name"], a["role"]))

    names = {p.number: p.name or p.number for p in projects}
    return {
        "today": today.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "weeks": [{"from": a.isoformat(), "to": b.isoformat(), "working_days": d}
                  for (a, b), d in zip(span, week_days)],
        "hours_per_day": round(a_day, 2),
        "groups": groups,
        "alerts": alerts,
        "assumed": [{"number": n, "name": names.get(n, n)} for n in assumed],
        "late": [{"number": n, "name": names.get(n, n)} for n in late],
        "unstaffed": [{"number": n, "name": names.get(n, n)} for n in unstaffed],
        "coming": coming,
        "data_through": last_day.isoformat() if last_day else None,
        "summary": {
            "asks": sum(1 for a in alerts if a["kind"] == "need"),
            "people_needed": sum(a["people"] for a in alerts if a["kind"] == "need"),
            "room": sum(1 for a in alerts if a["kind"] == "room"),
        },
        "rules": {"short_at": SHORT_AT, "room_at": ROOM_AT, "lead_weeks": LEAD_WEEKS,
                  "late_spread_weeks": LATE_SPREAD_WEEKS},
    }


def _teams(roster: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for person in roster:
        if person.get("team_id"):
            seen.setdefault(person["team_id"], {"id": person["team_id"],
                                                "name": person.get("team_name") or ""})
    return list(seen.values())


def _spread_end(project: Any, today: _dt.date, confirmed: bool) -> _dt.date:
    end = getattr(project, "end", None)
    if confirmed and end and end >= today + _dt.timedelta(days=7):
        return end
    return today + _dt.timedelta(weeks=LATE_SPREAD_WEEKS) - _dt.timedelta(days=1)


def _spread(hours: float, start: _dt.date, end: _dt.date,
            span: Sequence[Tuple[_dt.date, _dt.date]],
            config: Dict[str, Any]) -> List[float]:
    """``hours`` evenly over the working days from ``start`` to ``end``."""
    days = task_sheet.working_days(start, end, config)
    if not days:
        return [0.0] * len(span)
    each = hours / len(days)
    return [each * sum(1 for d in days if first <= d <= last) for first, last in span]


def _runs(weeks: Sequence[Dict[str, Any]], hit) -> List[Tuple[int, int]]:
    """Each run of consecutive weeks ``hit`` holds for, as (first, last) index."""
    out = []
    i = 0
    while i < len(weeks):
        if not hit(weeks[i]):
            i += 1
            continue
        j = i
        while j + 1 < len(weeks) and hit(weeks[j + 1]):
            j += 1
        out.append((i, j))
        i = j + 1
    return out


def _alerts(group: Dict[str, Any], today: _dt.date) -> List[Dict[str, Any]]:
    weeks = group["weeks"]
    role = group["role"]
    out: List[Dict[str, Any]] = []

    # Runs of short weeks.
    for i, j in _runs(weeks, lambda w: w["gap_people"] >= SHORT_AT):
        run = weeks[i:j + 1]
        peak = max(w["gap_people"] for w in run)
        average = sum(w["gap_people"] for w in run) / len(run)
        count = max(1, math.ceil(peak - 0.25))
        start = _dt.date.fromisoformat(run[0]["from"])
        end = _dt.date.fromisoformat(run[-1]["to"])
        open_ended = j == len(weeks) - 1
        if len(run) < MIN_NEED_WEEKS and not open_ended:
            away = _whole(sum(w.get("away_days", 0) for w in run))
            why = (f"{away} day{'s' if away != 1 else ''} away" if away
                   else "a busy week")
            out.append({
                "kind": "cover", "severity": "cover",
                "team_id": group["team_id"], "team_name": group["team_name"],
                "role": role,
                "title": (f"{group['team_name']}: short of {people_module.role_label(role, 2)} "
                          f"in the week of {start:%d %b}"),
                "detail": (f"About {peak:.1f} {people_module.role_label(role, 2)} short "
                           f"for one week ({why}). Hand some work over in Next days "
                           f"rather than asking for people."),
                "people": 0, "weeks": len(run),
                "from": start.isoformat(), "to": end.isoformat(), "ask_by": None,
            })
            continue
        ask_by = start - _dt.timedelta(weeks=LEAD_WEEKS)
        severity = "now" if ask_by <= today else "soon"
        who = people_module.role_label(role, count)
        length = f"{len(run)} week{'s' if len(run) != 1 else ''}"
        title = (f"{group['team_name']}: ask for {count} more {who} "
                 f"for {length}{'+' if open_ended else ''}")
        has = group["people"]
        detail = (f"From {start:%d %b} to {end:%d %b}"
                  f"{' and beyond' if open_ended else ''}, the work forecast needs "
                  f"{average:.1f} more {people_module.role_label(role, 2)} than the "
                  f"{has} the team has")
        detail += (f", {peak:.1f} at the peak. " if peak - average >= 0.1 else ". ")
        detail += ("Ask now." if severity == "now"
                   else f"Ask by {ask_by:%d %b} so they are there in time.")
        out.append({
            "kind": "need", "severity": severity,
            "team_id": group["team_id"], "team_name": group["team_name"],
            "role": role, "title": title, "detail": detail,
            "people": count, "weeks": len(run),
            "from": start.isoformat(), "to": end.isoformat(),
            "open_ended": open_ended,
            "ask_by": max(ask_by, today).isoformat(),
            "peak_people": round(peak, 2), "average_people": round(average, 2),
        })

    # Room: a run of weeks at least a whole person spare.
    for i, j in _runs(weeks, lambda w: -w["gap_people"] >= ROOM_AT):
        run = weeks[i:j + 1]
        if len(run) >= ROOM_WEEKS:
            spare = math.floor(min(-w["gap_people"] for w in run))
            start = _dt.date.fromisoformat(run[0]["from"])
            end = _dt.date.fromisoformat(run[-1]["to"])
            who = people_module.role_label(role, spare)
            out.append({
                "kind": "room", "severity": "room",
                "team_id": group["team_id"], "team_name": group["team_name"],
                "role": role,
                "title": f"{group['team_name']}: room for {spare} {who}'s worth of work",
                "detail": (f"From {start:%d %b} to {end:%d %b} the forecast leaves "
                           f"at least {spare} {who} free. Take on work, or lend "
                           f"{'them' if spare != 1 else 'one'} to a team that is short."),
                "people": spare, "weeks": len(run),
                "from": start.isoformat(), "to": end.isoformat(), "ask_by": None,
            })
    return out


def _whole(value: float) -> float:
    """5.0 days reads as 5; half a day off stays a half."""
    return int(value) if float(value).is_integer() else value
