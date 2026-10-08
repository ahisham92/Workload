"""Public holidays, built in, by country -- chosen once, never typed.

A unit picks the country its people work in, and a team somewhere else picks
its own.  From then on every public holiday is simply not a working day for
the people it applies to: their day is empty, no request is slotted into it,
and the staffing forecast does not count them.

What is built in is the usual private-sector set for each country:

* **fixed dates** -- national days, New Year, Labour Day and the rest;
* **Easter**, worked out for the year, Western or Orthodox as the country
  keeps it;
* **the Islamic holidays** -- Eid al-Fitr, Arafat and Eid al-Adha, the Islamic
  New Year, the Prophet's Birthday.  These follow the moon, so the dates here
  are the expected ones and the official announcement can move them by a day.
  When it does, the manager adds the day for everybody or takes the wrong one
  off, in one tap each.

A government can add a bridge day or shift a holiday to a Thursday; those are
the same one tap.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Expected first days, by Gregorian year.  Lunar: an announcement can move
#: any of them by a day, which is why every holiday can be adjusted.
_ISLAMIC: Dict[str, Dict[int, str]] = {
    "eid_al_fitr": {2024: "2024-04-10", 2025: "2025-03-30", 2026: "2026-03-20",
                    2027: "2027-03-09", 2028: "2028-02-26", 2029: "2029-02-14",
                    2030: "2030-02-04"},
    "eid_al_adha": {2024: "2024-06-16", 2025: "2025-06-06", 2026: "2026-05-27",
                    2027: "2027-05-16", 2028: "2028-05-05", 2029: "2029-04-24",
                    2030: "2030-04-13"},
    "islamic_new_year": {2024: "2024-07-07", 2025: "2025-06-26", 2026: "2026-06-16",
                         2027: "2027-06-06", 2028: "2028-05-25", 2029: "2029-05-14",
                         2030: "2030-05-03"},
    "mawlid": {2024: "2024-09-15", 2025: "2025-09-04", 2026: "2026-08-25",
               2027: "2027-08-14", 2028: "2028-08-03", 2029: "2029-07-23",
               2030: "2030-07-13"},
}
#: The years the lunar table covers; past them only fixed dates are known.
LUNAR_YEARS = (2024, 2030)

SUN_THU = [6, 0, 1, 2, 3]
MON_FRI = [0, 1, 2, 3, 4]

#: Each country: its name, its usual working week, and its holidays.
#: ``fixed`` is (month, day, name, days); ``lunar`` is (key, offset from the
#: first day, name, days); ``easter`` is (kind, offset from Easter Sunday,
#: name) with kind ``western`` or ``orthodox``; ``rules`` names computed ones.
COUNTRIES: Dict[str, Dict[str, Any]] = {
    "EG": {
        "name": "Egypt", "week": SUN_THU,
        "fixed": [(1, 7, "Coptic Christmas", 1), (1, 25, "Revolution Day", 1),
                  (4, 25, "Sinai Liberation Day", 1), (5, 1, "Labour Day", 1),
                  (6, 30, "June 30 Revolution", 1), (7, 23, "Revolution Day", 1),
                  (10, 6, "Armed Forces Day", 1)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 3),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3),
                  ("islamic_new_year", 0, "Islamic New Year", 1),
                  ("mawlid", 0, "Prophet's Birthday", 1)],
        "easter": [("orthodox", 1, "Sham el-Nessim")],
    },
    "SA": {
        "name": "Saudi Arabia", "week": SUN_THU,
        "fixed": [(2, 22, "Founding Day", 1), (9, 23, "National Day", 1)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 4),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3)],
    },
    "AE": {
        "name": "United Arab Emirates", "week": MON_FRI,
        "fixed": [(1, 1, "New Year's Day", 1), (12, 1, "Commemoration Day", 1),
                  (12, 2, "National Day", 2)],
        "lunar": [("eid_al_fitr", -1, "Eid al-Fitr", 4),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3),
                  ("islamic_new_year", 0, "Islamic New Year", 1),
                  ("mawlid", 0, "Prophet's Birthday", 1)],
    },
    "QA": {
        "name": "Qatar", "week": SUN_THU,
        "fixed": [(12, 18, "National Day", 1)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 3),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3)],
        "rules": ["qatar_sports_day"],
    },
    "KW": {
        "name": "Kuwait", "week": SUN_THU,
        "fixed": [(1, 1, "New Year's Day", 1), (2, 25, "National Day", 1),
                  (2, 26, "Liberation Day", 1)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 3),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3),
                  ("islamic_new_year", 0, "Islamic New Year", 1),
                  ("mawlid", 0, "Prophet's Birthday", 1)],
    },
    "JO": {
        "name": "Jordan", "week": SUN_THU,
        "fixed": [(1, 1, "New Year's Day", 1), (5, 1, "Labour Day", 1),
                  (5, 25, "Independence Day", 1), (12, 25, "Christmas Day", 1)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 3),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3),
                  ("islamic_new_year", 0, "Islamic New Year", 1),
                  ("mawlid", 0, "Prophet's Birthday", 1)],
    },
    "LB": {
        "name": "Lebanon", "week": MON_FRI,
        "fixed": [(1, 1, "New Year's Day", 1), (1, 6, "Armenian Christmas", 1),
                  (2, 9, "St Maroun's Day", 1), (3, 25, "Annunciation", 1),
                  (5, 1, "Labour Day", 1), (8, 15, "Assumption", 1),
                  (11, 22, "Independence Day", 1), (12, 25, "Christmas Day", 1)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 2),
                  ("eid_al_adha", 0, "Eid al-Adha", 2),
                  ("islamic_new_year", 0, "Islamic New Year", 1),
                  ("islamic_new_year", 9, "Ashura", 1),
                  ("mawlid", 0, "Prophet's Birthday", 1)],
        "easter": [("western", -2, "Good Friday"), ("orthodox", -2, "Orthodox Good Friday"),
                   ("western", 1, "Easter Monday"), ("orthodox", 1, "Orthodox Easter Monday")],
    },
    "OM": {
        "name": "Oman", "week": SUN_THU,
        "fixed": [(11, 20, "National Day", 2)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 3),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3),
                  ("islamic_new_year", 0, "Islamic New Year", 1),
                  ("mawlid", 0, "Prophet's Birthday", 1)],
    },
    "BH": {
        "name": "Bahrain", "week": SUN_THU,
        "fixed": [(1, 1, "New Year's Day", 1), (5, 1, "Labour Day", 1),
                  (12, 16, "National Day", 2)],
        "lunar": [("eid_al_fitr", 0, "Eid al-Fitr", 3),
                  ("eid_al_adha", -1, "Arafat Day", 1),
                  ("eid_al_adha", 0, "Eid al-Adha", 3),
                  ("islamic_new_year", 0, "Islamic New Year", 1),
                  ("islamic_new_year", 8, "Ashura", 2),
                  ("mawlid", 0, "Prophet's Birthday", 1)],
    },
    "GB": {
        "name": "United Kingdom (England and Wales)", "week": MON_FRI,
        "fixed": [],
        "easter": [("western", -2, "Good Friday"), ("western", 1, "Easter Monday")],
        "rules": ["uk_bank_holidays"],
    },
}


def choices() -> List[Dict[str, Any]]:
    """The countries on offer, for a picker."""
    return [{"code": code, "name": c["name"], "week": list(c["week"])}
            for code, c in sorted(COUNTRIES.items(), key=lambda kv: kv[1]["name"])]


def clean_country(value: Any) -> Optional[str]:
    code = str(value or "").strip().upper()
    if not code:
        return None
    if code not in COUNTRIES:
        raise ValueError(f"{value!r} is not a country the app has holidays for.")
    return code


# --------------------------------------------------------------------------
# Easter
# --------------------------------------------------------------------------

def western_easter(year: int) -> _dt.date:
    """Easter Sunday in the Gregorian calendar (the anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return _dt.date(year, month, day)


def orthodox_easter(year: int) -> _dt.date:
    """Orthodox Easter Sunday, as a Gregorian date (Meeus' Julian method)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month = (d + e + 114) // 31
    day = (d + e + 114) % 31 + 1
    julian = _dt.date(year, month, day)
    return julian + _dt.timedelta(days=(year // 100) - (year // 400) - 2)


# --------------------------------------------------------------------------
# rules that are not a fixed date
# --------------------------------------------------------------------------

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """The ``n``th ``weekday`` of a month; ``n = -1`` is the last."""
    if n > 0:
        first = _dt.date(year, month, 1)
        shift = (weekday - first.weekday()) % 7
        return first + _dt.timedelta(days=shift + 7 * (n - 1))
    nxt = _dt.date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - _dt.timedelta(days=1)
    return last - _dt.timedelta(days=(last.weekday() - weekday) % 7)


def _substitute(day: _dt.date, taken: Iterable[_dt.date]) -> _dt.date:
    """A bank holiday on a weekend moves to the next free weekday."""
    taken = set(taken)
    while day.weekday() >= 5 or day in taken:
        day += _dt.timedelta(days=1)
    return day


def _rule(name: str, year: int) -> List[Tuple[_dt.date, str]]:
    if name == "qatar_sports_day":
        return [(_nth_weekday(year, 2, 1, 2), "National Sports Day")]
    if name == "uk_bank_holidays":
        out = [(_nth_weekday(year, 5, 0, 1), "Early May bank holiday"),
               (_nth_weekday(year, 5, 0, -1), "Spring bank holiday"),
               (_nth_weekday(year, 8, 0, -1), "Summer bank holiday")]
        new_year = _substitute(_dt.date(year, 1, 1), [])
        christmas = _substitute(_dt.date(year, 12, 25), [])
        boxing = _substitute(_dt.date(year, 12, 26), [christmas])
        out += [(new_year, "New Year's Day"), (christmas, "Christmas Day"),
                (boxing, "Boxing Day")]
        return out
    raise KeyError(name)


# --------------------------------------------------------------------------
# the calendar
# --------------------------------------------------------------------------

def for_year(code: str, year: int) -> List[Dict[str, Any]]:
    """Every public holiday in ``year``: one entry a day, with its name."""
    country = COUNTRIES[code]
    days: Dict[_dt.date, Tuple[str, bool]] = {}

    def add(first: _dt.date, name: str, count: int = 1, expected: bool = False):
        for i in range(count):
            day = first + _dt.timedelta(days=i)
            if day.year == year and day not in days:
                days[day] = (name, expected)

    for month, day, name, count in country.get("fixed", ()):
        add(_dt.date(year, month, day), name, count)
    for key, offset, name, count in country.get("lunar", ()):
        # A holiday early in a year can start in the year before, so look at
        # both years' dates.
        for each in (year - 1, year, year + 1):
            iso = _ISLAMIC[key].get(each)
            if iso:
                add(_dt.date.fromisoformat(iso) + _dt.timedelta(days=offset),
                    name, count, expected=True)
    for kind, offset, name in country.get("easter", ()):
        sunday = western_easter(year) if kind == "western" else orthodox_easter(year)
        add(sunday + _dt.timedelta(days=offset), name)
    for rule in country.get("rules", ()):
        for day, name in _rule(rule, year):
            add(day, name)
    return [{"date": day.isoformat(), "name": name, "expected": expected}
            for day, (name, expected) in sorted(days.items())]


def between(code: str, start: _dt.date, end: _dt.date) -> List[Dict[str, Any]]:
    out = []
    for year in range(start.year, end.year + 1):
        out.extend(h for h in for_year(code, year)
                   if start.isoformat() <= h["date"] <= end.isoformat())
    return out


def days_between(code: str, start: _dt.date, end: _dt.date,
                 skipped: Iterable[str] = ()) -> Dict[str, str]:
    """ISO date -> holiday name, less any the manager took off."""
    skipped = set(skipped)
    return {h["date"]: h["name"] for h in between(code, start, end)
            if h["date"] not in skipped}


def guess(text: str) -> Optional[str]:
    """A country from a unit's or a team's name, when one is in it."""
    words = str(text or "").lower()
    hints = {"cairo": "EG", "egypt": "EG", "riyadh": "SA", "jeddah": "SA",
             "khobar": "SA", "saudi": "SA", "ksa": "SA", "dubai": "AE",
             "abu dhabi": "AE", "uae": "AE", "doha": "QA", "qatar": "QA",
             "kuwait": "KW", "amman": "JO", "jordan": "JO", "beirut": "LB",
             "lebanon": "LB", "muscat": "OM", "oman": "OM", "manama": "BH",
             "bahrain": "BH", "london": "GB", "uk": "GB"}
    for hint, code in hints.items():
        if re.search(rf"\b{re.escape(hint)}\b", words):
            return code
    return None


def calendar_for(choice: Dict[str, Any], *, people: Sequence[Dict[str, Any]],
                 start: _dt.date, end: _dt.date) -> Dict[str, Any]:
    """Who has which public holidays, from the unit's and the teams' countries.

    Returns ``common`` (days off for everybody) and ``own`` (person -> the
    days off only they have, because their team is somewhere else), plus the
    named list for showing.
    """
    unit = choice.get("unit")
    teams = choice.get("teams") or {}
    skipped = choice.get("off") or []
    cache: Dict[str, Dict[str, str]] = {}

    def of(code: Optional[str]) -> Dict[str, str]:
        if not code:
            return {}
        if code not in cache:
            cache[code] = days_between(code, start, end, skipped)
        return cache[code]

    everyone = of(unit)
    by_person = {p["name"]: of(teams.get(p.get("team_id") or "") or unit)
                 for p in people}
    sets = [set(days) for days in by_person.values()] or [set(everyone)]
    if unit:
        sets.append(set(everyone))
    common = set.intersection(*sets)
    own = {name: set(days) - common for name, days in by_person.items()
           if set(days) - common}
    named: Dict[str, Dict[str, Any]] = {}
    for code in cache:
        for iso, name in cache[code].items():
            entry = named.setdefault(iso, {"date": iso, "name": name, "countries": []})
            entry["countries"].append(code)
    return {"common": common, "own": own,
            "named": sorted(named.values(), key=lambda h: h["date"])}
