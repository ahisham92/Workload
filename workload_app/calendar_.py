"""Who will not be there: public holidays and time away, known ahead.

Capacity is only worth forecasting if it leaves out the people who will be
away, and the app gathers that from three places so as little as possible is
typed:

* **public holidays** from the workbook's own holiday table on Work Calendar,
  which the workbook already uses for its own working-day sums;
* **leave on the timesheets** -- a day booked to a leave or holiday code.  One
  dated ahead is time off somebody has already booked; one in the past means
  their pace over those weeks is read from the days they were in, not
  dragged down by the days they were not;
* **"Away"**, one tap on a person in the Planner, with the days -- or for the
  whole team, a public holiday the workbook does not have.

The result goes into the working-day settings every planning sum is given, so
a holiday is simply not a working day anywhere, and a person away is simply
not counted on the days they are away.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from . import config as cfg
from . import derive

EVERYONE = "*"

#: What a leave or holiday row on a timesheet looks like, by its job number,
#: job type or phase description.
LEAVE = re.compile(r"leave|holiday|vacation|annual|sick|absen|day ?off|public",
                   re.IGNORECASE)
#: The longest single absence one tap may record, so a typo in a year does
#: not take somebody out of every forecast.
LONGEST_DAYS = 120
#: Booked off for at least this much of a day, and the day is off.
HALF_DAY_HOURS = 4.0


class CalendarError(ValueError):
    def __init__(self, errors: Sequence[str]):
        errors = list(errors)
        super().__init__("; ".join(errors))
        self.errors = errors


def workbook_holidays(wb) -> Set[str]:
    """The unit's own public holidays, as ISO strings."""
    try:
        return {day.isoformat() for day in wb.holidays()}
    except Exception:                       # pragma: no cover - odd workbook
        return set()


def leave_codes(wb) -> Set[str]:
    """The charge codes the workbook treats as a day off (Work Calendar)."""
    try:
        codes = wb.non_project_codes()
    except Exception:                       # pragma: no cover - odd workbook
        return set()
    return {code.strip().upper() for code, treat in codes.items()
            if "day off" in str(treat or "").lower()}


def leave_from_timesheets(rows: Iterable[Dict[str, Any]], *,
                          codes: Iterable[str] = (),
                          min_hours: float = HALF_DAY_HOURS) -> Dict[str, Set[str]]:
    """The days each person booked as time off, ahead or past.

    A row is time off when its charge code is one the workbook treats as a day
    off, or when its code or description says leave or holiday.  A day counts
    once half of it or more is booked that way, so an hour off for an errand
    does not take somebody out of the plan.
    """
    codes = {c.upper() for c in codes}
    hours: Dict[tuple, float] = defaultdict(float)
    for row in rows:
        day = row.get("date")
        if not day or derive.is_project_work(row.get("job_type") or ""):
            continue
        number = str(row.get("job_number") or "").strip().upper()
        text = " ".join(str(row.get(k) or "") for k in
                        ("job_number", "job_type", "deliverable", "job_name"))
        if number in codes or LEAVE.search(text):
            hours[(row["engineer"], day.isoformat())] += float(row.get("hours") or 0.0)
    out: Dict[str, Set[str]] = defaultdict(set)
    for (name, day), booked in hours.items():
        if booked >= min_hours:
            out[name].add(day)
    return dict(out)


def _days(start: _dt.date, end: _dt.date) -> List[str]:
    return [(start + _dt.timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)]


def with_calendar(config: Dict[str, Any], *, holidays: Iterable[str] = (),
                  absences: Sequence[Dict[str, Any]] = (),
                  leave: Mapping[str, Iterable[str]] = (),
                  own_holidays: Mapping[str, Iterable[str]] = ()) -> Dict[str, Any]:
    """The working-day settings, with who is away added to them.

    ``holidays`` are days nobody works; ``own_holidays`` are public holidays
    only some people have, because their team is in another country.
    """
    out = dict(config)
    days_off = set(holidays)
    away: Dict[str, Set[str]] = defaultdict(set)
    for name, days in dict(leave).items():
        away[name] |= set(days)
    for name, days in dict(own_holidays).items():
        away[name] |= set(days)
    for absence in absences:
        try:
            start = _dt.date.fromisoformat(absence["start"])
            end = _dt.date.fromisoformat(absence["end"])
        except (TypeError, ValueError):
            continue
        days = _days(start, end)
        if absence["person"] == EVERYONE:
            days_off |= set(days)
        else:
            away[absence["person"]] |= set(days)
    out["holidays"] = days_off
    out["away"] = dict(away)
    return out


def is_away(config: Dict[str, Any], person: str, day: _dt.date) -> bool:
    return day.isoformat() in (config.get("away") or {}).get(person, ())


def present_days(config: Dict[str, Any], person: str,
                 days: Iterable[_dt.date]) -> int:
    away = (config.get("away") or {}).get(person, ())
    return sum(1 for d in days if d.isoformat() not in away)


def away_on(config: Dict[str, Any], day: _dt.date) -> Set[str]:
    """Everybody away on ``day``."""
    key = day.isoformat()
    return {name for name, days in (config.get("away") or {}).items() if key in days}


def clean_absence(body: Mapping[str, Any], *, people: Iterable[str],
                  today: _dt.date) -> Dict[str, Any]:
    errors: List[str] = []
    person = str(body.get("person") or "").strip()
    if person != EVERYONE and person not in set(people):
        errors.append(f"{person or 'Nobody'} is not on this unit's team.")
    try:
        start = _dt.date.fromisoformat(str(body.get("start") or today.isoformat()))
        end = _dt.date.fromisoformat(str(body.get("end") or start.isoformat()))
    except ValueError:
        raise CalendarError(["Give the days as dates."])
    if end < start:
        errors.append("The last day is before the first.")
    elif (end - start).days + 1 > LONGEST_DAYS:
        errors.append(f"One absence is at most {LONGEST_DAYS} days.")
    if errors:
        raise CalendarError(errors)
    return {"person": person, "start": start.isoformat(), "end": end.isoformat(),
            "note": " ".join(str(body.get("note") or "").split())[:120]}


def upcoming(config: Dict[str, Any], absences: Sequence[Dict[str, Any]],
             leave: Mapping[str, Iterable[str]], today: _dt.date,
             until: _dt.date, public: Sequence[Dict[str, Any]] = (),
             country_names: Mapping[str, str] = ()) -> List[Dict[str, Any]]:
    """Who is away between now and ``until``, for the Planner to list.

    ``public`` is the built-in public holidays, one entry a day; a holiday of
    several days is listed once.
    """
    out = []
    country_names = dict(country_names)
    several = len({c for h in public for c in h.get("countries", ())}) > 1
    named = set()
    run: Optional[Dict[str, Any]] = None
    for holiday in sorted(public, key=lambda h: h["date"]):
        if not today.isoformat() <= holiday["date"] <= until.isoformat():
            continue
        named.add(holiday["date"])
        day = _dt.date.fromisoformat(holiday["date"])
        if run and run["note"] == holiday["name"] and run["countries"] == holiday["countries"] \
                and (day - _dt.date.fromisoformat(run["end"])).days == 1:
            run["end"] = holiday["date"]
            run["dates"].append(holiday["date"])
            continue
        run = {"id": None, "person": EVERYONE, "start": holiday["date"],
               "end": holiday["date"], "note": holiday["name"], "source": "holiday",
               "countries": list(holiday.get("countries", ())),
               "where": (", ".join(country_names.get(c, c) for c in holiday["countries"])
                         if several else ""),
               "dates": [holiday["date"]]}
        out.append(run)
    for absence in absences:
        if absence["end"] >= today.isoformat() and absence["start"] <= until.isoformat():
            out.append({**absence, "source": "typed"})
    for name, days in dict(leave).items():
        ahead = sorted(d for d in days if today.isoformat() <= d <= until.isoformat())
        for run in _runs(ahead):
            out.append({"id": None, "person": name, "start": run[0], "end": run[-1],
                        "note": "booked on a timesheet", "source": "timesheet"})
    for day in sorted(d for d in config.get("holidays", ())
                      if today.isoformat() <= d <= until.isoformat() and d not in named):
        if not any(a["person"] == EVERYONE and a["start"] <= day <= a["end"]
                   for a in absences):
            out.append({"id": None, "person": EVERYONE, "start": day, "end": day,
                        "note": "public holiday", "source": "workbook"})
    out.sort(key=lambda a: (a["start"], a["person"]))
    return out


def _runs(days: Sequence[str]) -> List[List[str]]:
    runs: List[List[str]] = []
    for day in days:
        if runs and (_dt.date.fromisoformat(day)
                     - _dt.date.fromisoformat(runs[-1][-1])).days <= 3:
            runs[-1].append(day)
        else:
            runs.append([day])
    return runs
