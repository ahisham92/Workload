"""Meetings typed in by hand: a client, another trade, or an internal one.

The app cannot see Outlook where people work, so the meetings that matter
most -- with clients and the other trades -- are put in by hand: what it is,
who it is with, the day, from and to, and who goes.  A meeting that comes
round every week or every second week is put in once.

The day plan shows each as it is, at its time, and the hours come off free
time, the Planner and the Forecast like any other meeting.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Iterable, List, Sequence

from .model import ValidationError

KINDS = ("client", "trade", "internal")
REPEATS = {"": 0, "weekly": 7, "fortnightly": 14}
#: A repeating meeting runs at most this long, so a forgotten end date does
#: not hold a slot for ever.
LONGEST_REPEAT_DAYS = 366
TITLE_CHARS = 120


class MeetingError(ValidationError):
    pass


def _clock(text: Any, label: str, errors: List[str]) -> str:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(text or "").strip())
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        errors.append(f"{label} is not a time like 10:00.")
        return ""
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def clean(body: Dict[str, Any], *, people: Sequence[str],
          today: _dt.date) -> Dict[str, Any]:
    """A meeting as typed, checked."""
    errors: List[str] = []
    title = " ".join(str(body.get("title") or "").split())[:TITLE_CHARS]
    kind = str(body.get("kind") or "client").strip().lower()
    if kind not in KINDS:
        errors.append("Say whether it is with a client, another trade, or internal.")
    try:
        day = _dt.date.fromisoformat(str(body.get("day") or ""))
    except ValueError:
        errors.append("Choose the day of the meeting.")
        day = today
    start = _clock(body.get("start"), "From", errors)
    end = _clock(body.get("end"), "To", errors)
    if start and end and end <= start:
        errors.append("The meeting has to end after it starts.")
    who = []
    for name in body.get("people") or []:
        name = " ".join(str(name or "").split())
        if name and name not in who:
            who.append(name)
    unknown = [n for n in who if n not in people]
    if unknown:
        errors.append(f"{', '.join(unknown)} is not on the team.")
    if not who:
        errors.append("Choose who is in the meeting.")
    repeat = str(body.get("repeat") or "").strip().lower()
    if repeat not in REPEATS:
        errors.append("Repeat is none, weekly or fortnightly.")
        repeat = ""
    until = None
    if repeat:
        raw = str(body.get("until") or "").strip()
        try:
            until = _dt.date.fromisoformat(raw) if raw else day + _dt.timedelta(days=90)
        except ValueError:
            errors.append(f"{raw!r} is not a date.")
            until = day
        if until < day:
            errors.append("The repeats have to end after the first meeting.")
        until = min(until, day + _dt.timedelta(days=LONGEST_REPEAT_DAYS))
    last = until or day
    if last < today - _dt.timedelta(days=1):
        errors.append("That meeting has already passed.")
    if errors:
        raise MeetingError(errors)
    return {"title": title, "kind": kind, "day": day.isoformat(), "start": start,
            "end": end, "people": who, "repeat": repeat,
            "until": until.isoformat() if until else None}


def occurrences(rows: Iterable[Dict[str, Any]], first: _dt.date, last: _dt.date
                ) -> List[Dict[str, Any]]:
    """Each time each meeting falls between ``first`` and ``last``."""
    out = []
    for row in rows:
        day = _dt.date.fromisoformat(row["day"])
        step = REPEATS.get(row.get("repeat") or "", 0)
        until = _dt.date.fromisoformat(row["until"]) if row.get("until") else day
        if step and first > day:
            day += _dt.timedelta(days=((first - day).days // step) * step)
        while day <= min(until, last):
            if day >= first:
                out.append({
                    "id": row["id"], "title": row["title"], "kind": row["kind"],
                    "people": list(row["people"]),
                    "start": _dt.datetime.combine(day, _dt.time.fromisoformat(row["start"])),
                    "end": _dt.datetime.combine(day, _dt.time.fromisoformat(row["end"]))})
            if not step:
                break
            day += _dt.timedelta(days=step)
    return sorted(out, key=lambda m: m["start"])


def upcoming(rows: Iterable[Dict[str, Any]], today: _dt.date) -> List[Dict[str, Any]]:
    """The meetings still to come, each with its next time."""
    out = []
    for row in rows:
        next_ones = occurrences([row], today, today + _dt.timedelta(days=LONGEST_REPEAT_DAYS))
        if not next_ones:
            continue
        out.append({**{k: row[k] for k in ("id", "title", "kind", "day", "start", "end",
                                           "repeat", "until", "added_by")},
                    "people": list(row["people"]),
                    "next": next_ones[0]["start"].date().isoformat()})
    return sorted(out, key=lambda m: (m["next"], m["start"]))
