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

from . import derive
from .model import ValidationError

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
#: A public holiday on a timesheet, as opposed to somebody's own leave.
HOLIDAY_CODE = re.compile(r"holiday|public|official|feast|\beid\b", re.IGNORECASE)
#: A personal excuse: part of a day off with permission.  Half a day or more
#: of one is half a day of leave, so nobody has to type it.
EXCUSE = re.compile(r"excuse|permission", re.IGNORECASE)
#: At least this many people, and most of those who booked that day, booked
#: it as a holiday: it was an official holiday.
HOLIDAY_QUORUM = 2
#: A built-in holiday worked through, with a holiday booked this close to it,
#: was moved (Egypt moves many to a Thursday).
MOVED_WITHIN_DAYS = 7


class CalendarError(ValidationError):
    pass


def workbook_holidays(wb) -> Set[str]:
    """The days off the unit typed in itself, as ISO strings."""
    return {day.isoformat() for day in wb.holidays()}


def leave_codes(wb) -> Set[str]:
    """The charge codes the unit treats as a day off."""
    codes = wb.non_project_codes()
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


def _row_text(row: Dict[str, Any]) -> str:
    return " ".join(str(row.get(k) or "") for k in
                    ("job_number", "job_type", "deliverable", "job_name"))


def half_days_from_timesheets(rows: Iterable[Dict[str, Any]], *,
                              min_hours: float = HALF_DAY_HOURS) -> Dict[str, Set[str]]:
    """The days each person took a personal excuse of half a day or more.

    A personal excuse of about four hours is half a day of leave.  Nothing is
    typed for it: the timesheet says so.
    """
    hours: Dict[tuple, float] = defaultdict(float)
    for row in rows:
        day = row.get("date")
        if not day or derive.is_project_work(row.get("job_type") or ""):
            continue
        if EXCUSE.search(_row_text(row)):
            hours[(row["engineer"], day.isoformat())] += float(row.get("hours") or 0.0)
    out: Dict[str, Set[str]] = defaultdict(set)
    for (name, day), booked in hours.items():
        if booked >= min_hours:
            out[name].add(day)
    return dict(out)


def holidays_from_timesheets(rows: Iterable[Dict[str, Any]], *,
                             min_hours: float = HALF_DAY_HOURS) -> Dict[str, Dict[str, int]]:
    """Day -> how many people booked it, booked it as a holiday, or worked.

    A row is a holiday when its code or description says holiday (not
    leave: leave is somebody's own).  Worked means half a day or more on
    anything that is not time off.
    """
    holiday: Dict[tuple, float] = defaultdict(float)
    work: Dict[tuple, float] = defaultdict(float)
    booked: Dict[str, Set[str]] = defaultdict(set)
    for row in rows:
        day = row.get("date")
        if not day:
            continue
        key = (row["engineer"], day.isoformat())
        booked[key[1]].add(key[0])
        hours = float(row.get("hours") or 0.0)
        text = _row_text(row)
        if derive.is_project_work(row.get("job_type") or ""):
            work[key] += hours
        elif HOLIDAY_CODE.search(text) and not re.search(r"leave", text, re.IGNORECASE):
            holiday[key] += hours
        elif not (LEAVE.search(text) or EXCUSE.search(text)
                  or re.search(r"late|absen", text, re.IGNORECASE)):
            work[key] += hours
    out: Dict[str, Dict[str, int]] = {}
    for day, people in booked.items():
        out[day] = {
            "people": len(people),
            "holiday": sum(1 for p in people if holiday.get((p, day), 0) >= min_hours),
            "worked": sum(1 for p in people if work.get((p, day), 0) >= min_hours),
        }
    return out


def learned_holidays(counts: Mapping[str, Mapping[str, int]],
                     built_in: Iterable[str] = ()) -> Dict[str, Any]:
    """What the timesheets say about which days were official holidays.

    ``add``: days at least two people, and most of those who booked that
    day, booked as a holiday.  ``remove``: built-in holidays most people
    worked through and nobody booked as one, with a holiday booked within the
    week instead -- it was moved, or the moon put it on another day.
    """
    add = sorted(day for day, c in counts.items()
                 if c["holiday"] >= HOLIDAY_QUORUM and c["holiday"] * 2 > c["people"])
    added = [_dt.date.fromisoformat(day) for day in add]

    def moved(day: str) -> bool:
        # Only when a holiday was booked within the week: the holiday went to
        # another day.  People who simply work through holidays (or never book
        # them) take nothing off anybody's list.
        when = _dt.date.fromisoformat(day)
        return any(0 < abs((other - when).days) <= MOVED_WITHIN_DAYS for other in added)

    remove = sorted(day for day in built_in
                    if day in counts and counts[day]["holiday"] == 0
                    and counts[day]["worked"] >= HOLIDAY_QUORUM
                    and counts[day]["worked"] * 2 > counts[day]["people"]
                    and moved(day))
    return {"add": add, "remove": remove}


def _days(start: _dt.date, end: _dt.date) -> List[str]:
    return [(start + _dt.timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)]


def with_calendar(config: Dict[str, Any], *, holidays: Iterable[str] = (),
                  absences: Sequence[Dict[str, Any]] = (),
                  leave: Mapping[str, Iterable[str]] = (),
                  own_holidays: Mapping[str, Iterable[str]] = (),
                  half_days: Mapping[str, Iterable[str]] = ()) -> Dict[str, Any]:
    """The working-day settings, with who is away added to them.

    ``holidays`` are days nobody works; ``own_holidays`` are public holidays
    only some people have, because their team is in another country;
    ``half_days`` are half days of leave (a personal excuse).
    """
    out = dict(config)
    days_off = set(holidays)
    away: Dict[str, Set[str]] = defaultdict(set)
    for source in (leave, own_holidays):
        for name, days in dict(source).items():
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
    out["half_away"] = {name: set(days) - away.get(name, set())
                        for name, days in dict(half_days).items()
                        if set(days) - away.get(name, set())}
    return out


def is_away(config: Dict[str, Any], person: str, day: _dt.date) -> bool:
    return day.isoformat() in (config.get("away") or {}).get(person, ())


def is_half_away(config: Dict[str, Any], person: str, day: _dt.date) -> bool:
    """Half the day off (a personal excuse), and in for the other half."""
    return day.isoformat() in (config.get("half_away") or {}).get(person, ())


def present_days(config: Dict[str, Any], person: str,
                 days: Iterable[_dt.date]) -> float:
    """Days in, a half day off counting as half."""
    away = (config.get("away") or {}).get(person, ())
    half = (config.get("half_away") or {}).get(person, ())
    there = 0.0
    for d in days:
        key = d.isoformat()
        if key not in away:
            there += 0.5 if key in half else 1
    return there


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
             country_names: Mapping[str, str] = (),
             half_days: Mapping[str, Iterable[str]] = ()) -> List[Dict[str, Any]]:
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
    for name, days in dict(half_days).items():
        for day in sorted(d for d in days if today.isoformat() <= d <= until.isoformat()):
            out.append({"id": None, "person": name, "start": day, "end": day,
                        "note": "half a day off: a personal excuse on the timesheet",
                        "source": "half_day"})
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
