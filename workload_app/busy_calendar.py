"""Each person's Outlook meetings, as busy times and nothing more.

People's days are full of meetings the app cannot see, and a plan that does
not know about them shows people free when they are not.  Outlook can publish
a calendar as a link with *availability only* ("Can view when I'm busy"): a
standard iCalendar (.ics) file that says when somebody is busy and nothing
else.  Each person publishes theirs once and pastes the link into Selecao+.

From that file the app keeps only a start and an end for each busy stretch:

* no titles, no places, no attendees, no notes -- whatever the file holds;
* only the coming weeks (``AHEAD_DAYS``), read again as the plan is opened;
* *free* and *working elsewhere* times are not meetings and are skipped;
  busy, tentative and out-of-office times count;
* a meeting that repeats is laid out on each day it falls, with the days
  moved or cancelled in Outlook taken into account;
* every time is put in the calendar's own time zone -- the one its owner
  works in -- so a meeting sent from another country lands at the right hour.

Only Microsoft's own calendar addresses are read, over HTTPS, so the link
cannot be pointed anywhere else.
"""

from __future__ import annotations

import datetime as _dt
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .model import ValidationError

try:                                   # pragma: no cover - always there on 3.9+
    from zoneinfo import ZoneInfo
except ImportError:                    # pragma: no cover
    ZoneInfo = None                    # type: ignore

#: How far ahead busy times are kept.
AHEAD_DAYS = 42
#: And how far back, so today's earlier meetings still show.
BEHIND_DAYS = 1
#: Where an Outlook calendar is published.  Nothing else is ever fetched.
HOSTS = ("outlook.office365.com", "outlook.office.com", "outlook.live.com")
#: The largest calendar file read, and how long to wait for it.
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 15
#: A repeating meeting is followed no further than this many times.
MAX_REPEATS = 3000

#: What Outlook calls each kind of time, and whether it is a meeting.
_COUNTS = {"BUSY": True, "TENTATIVE": True, "OOF": True,
           "FREE": False, "WORKINGELSEWHERE": False}
#: The words a busy-only calendar uses for the same thing, when the status
#: line is missing.
_WORDS = {"busy": True, "tentative": True, "away": True, "out of office": True,
          "free": False, "working elsewhere": False}

Interval = Tuple[_dt.datetime, _dt.datetime]


class CalendarLinkError(ValidationError):
    pass


# --------------------------------------------------------------------------
# the link
# --------------------------------------------------------------------------

def clean_link(raw: Any) -> str:
    """The pasted link, checked to be an Outlook published calendar."""
    text = "".join(str(raw or "").split())
    if not text:
        raise CalendarLinkError(["Paste the calendar link from Outlook."])
    if text.lower().startswith("webcal://"):
        text = "https://" + text[len("webcal://"):]
    parts = urllib.parse.urlsplit(text)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in HOSTS:
        raise CalendarLinkError([
            "That is not an Outlook calendar link. In Outlook on the web: "
            "Settings, Calendar, Shared calendars, Publish a calendar, choose "
            "\"Can view when I'm busy\", Publish, then copy the ICS link."])
    if not parts.path.lower().endswith(".ics"):
        raise CalendarLinkError([
            "Copy the ICS link, the one ending in .ics, not the HTML one."])
    if len(text) > 1000:
        raise CalendarLinkError(["That link is too long to be a calendar link."])
    return urllib.parse.urlunsplit(("https", host, parts.path, parts.query, ""))


class _SameHosts(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = (urllib.parse.urlsplit(newurl).hostname or "").lower()
        if not newurl.lower().startswith("https://") or host not in HOSTS:
            raise urllib.error.HTTPError(newurl, code, "Moved away from Outlook",
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(link: str) -> str:
    """The calendar file behind a link checked by ``clean_link``."""
    link = clean_link(link)
    opener = urllib.request.build_opener(_SameHosts)
    request = urllib.request.Request(link, headers={
        "User-Agent": "Selecao+ (busy times only)", "Accept": "text/calendar"})
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404, 410):
            raise CalendarLinkError([
                "Outlook did not give the calendar for that link. It may have "
                "been stopped from Outlook, or calendar publishing may be "
                "turned off where you work."]) from None
        raise CalendarLinkError([f"Outlook answered {exc.code}; try again later."]) \
            from None
    except (urllib.error.URLError, OSError) as exc:
        raise CalendarLinkError([
            f"Could not reach Outlook just now ({getattr(exc, 'reason', exc)}); "
            "try again later."]) from None
    if len(body) > MAX_BYTES:
        raise CalendarLinkError(["That calendar is too big to read."])
    text = body.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        raise CalendarLinkError([
            "That link did not give a calendar. Copy the ICS link, not the "
            "HTML one."])
    return text


# --------------------------------------------------------------------------
# reading the file
# --------------------------------------------------------------------------

def _lines(text: str) -> List[Tuple[str, Dict[str, str], str]]:
    """(NAME, {PARAM: value}, value) for each unfolded line."""
    unfolded: List[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += raw[1:]
        elif raw:
            unfolded.append(raw)
    out = []
    for line in unfolded:
        head, sep, value = _split_value(line)
        if not sep:
            continue
        name, *params = head.split(";")
        found = {}
        for param in params:
            key, _, val = param.partition("=")
            found[key.upper()] = val.strip('"')
        out.append((name.upper(), found, value))
    return out


def _split_value(line: str) -> Tuple[str, str, str]:
    # The first colon outside quotes ends the name and its parameters.
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            return line[:i], ":", line[i + 1:]
    return line, "", ""


def _components(lines) -> List[Tuple[str, List]]:
    """The calendar's top-level parts: each VEVENT and VTIMEZONE with its
    lines, the nested parts of a time zone kept as (name, lines) inside."""
    out: List[Tuple[str, List]] = []
    stack: List[Tuple[str, List]] = []
    for name, params, value in lines:
        if name == "BEGIN":
            stack.append((value.upper(), []))
        elif name == "END":
            if not stack:
                continue
            done = stack.pop()
            if stack and stack[-1][0] != "VCALENDAR":
                stack[-1][1].append(("__PART__", done, ""))
            elif done[0] in ("VEVENT", "VTIMEZONE"):
                out.append(done)
        elif stack:
            stack[-1][1].append((name, params, value))
    return out


def _first(lines, name: str):
    for each in lines:
        if each[0] == name:
            return each
    return None


# -- time zones --------------------------------------------------------------

#: Windows' names for the zones Outlook uses most around the offices, for when
#: a file carries no description of its own.
WINDOWS_ZONES = {
    "utc": "UTC", "gmt standard time": "Europe/London",
    "greenwich standard time": "Atlantic/Reykjavik",
    "w. europe standard time": "Europe/Berlin",
    "romance standard time": "Europe/Paris",
    "central europe standard time": "Europe/Budapest",
    "e. europe standard time": "Europe/Chisinau",
    "gtb standard time": "Europe/Bucharest",
    "fle standard time": "Europe/Kiev",
    "egypt standard time": "Africa/Cairo",
    "south africa standard time": "Africa/Johannesburg",
    "israel standard time": "Asia/Jerusalem",
    "jordan standard time": "Asia/Amman",
    "middle east standard time": "Asia/Beirut",
    "syria standard time": "Asia/Damascus",
    "arab standard time": "Asia/Riyadh",
    "arabic standard time": "Asia/Baghdad",
    "arabian standard time": "Asia/Dubai",
    "iran standard time": "Asia/Tehran",
    "turkey standard time": "Europe/Istanbul",
    "russian standard time": "Europe/Moscow",
    "pakistan standard time": "Asia/Karachi",
    "india standard time": "Asia/Kolkata",
    "china standard time": "Asia/Shanghai",
    "singapore standard time": "Asia/Singapore",
    "tokyo standard time": "Asia/Tokyo",
    "aus eastern standard time": "Australia/Sydney",
    "eastern standard time": "America/New_York",
    "central standard time": "America/Chicago",
    "pacific standard time": "America/Los_Angeles",
}

#: Where each country the holidays know works, so a calendar's times land in
#: the owner's own working hours.
COUNTRY_ZONES = {"EG": "Africa/Cairo", "SA": "Asia/Riyadh", "AE": "Asia/Dubai",
                 "QA": "Asia/Qatar", "KW": "Asia/Kuwait", "JO": "Asia/Amman",
                 "LB": "Asia/Beirut", "OM": "Asia/Muscat", "BH": "Asia/Bahrain",
                 "GB": "Europe/London"}

_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _offset(text: str) -> _dt.timedelta:
    sign = -1 if text.startswith("-") else 1
    digits = text.lstrip("+-")
    hours, minutes = int(digits[:2]), int(digits[2:4] or 0)
    return sign * _dt.timedelta(hours=hours, minutes=minutes)


class _Zone:
    """A time zone as the file describes it: standard and daylight times, each
    starting on a rule like "the last Sunday of October at 03:00"."""

    def __init__(self, parts: List[Tuple[str, List]]):
        self.rules = []
        for kind, lines in parts:
            start = _first(lines, "DTSTART")
            to = _first(lines, "TZOFFSETTO")
            if not start or not to:
                continue
            frm = _first(lines, "TZOFFSETFROM")
            rule = _first(lines, "RRULE")
            self.rules.append({
                "start": _parse_local(start[2]),
                "to": _offset(to[2]),
                "from": _offset(frm[2]) if frm else _offset(to[2]),
                "rule": _rule(rule[2]) if rule else None})

    def utcoffset(self, local: _dt.datetime) -> _dt.timedelta:
        best: Optional[Tuple[_dt.datetime, _dt.timedelta]] = None
        for each in self.rules:
            for year in (local.year - 1, local.year):
                at = self._change_in(each, year)
                if at is not None and at <= local and (best is None or at > best[0]):
                    best = (at, each["to"])
        if best is not None:
            return best[1]
        if self.rules:
            return min(self.rules, key=lambda r: r["start"])["from"]
        return _dt.timedelta(0)

    @staticmethod
    def _change_in(each, year: int) -> Optional[_dt.datetime]:
        start = each["start"]
        rule = each["rule"]
        if rule is None:
            return start if start.year == year else None
        if year < start.year:
            return None
        if rule.get("UNTIL") and _parse_local(rule["UNTIL"][:15]).year < year:
            return None
        month = int((rule.get("BYMONTH") or str(start.month)).split(",")[0])
        day = _nth_weekday(year, month, rule.get("BYDAY", ""))
        if day is None:
            try:
                day = _dt.date(year, month, int(rule.get("BYMONTHDAY") or start.day))
            except ValueError:
                return None
        return _dt.datetime.combine(day, start.time())


def _nth_weekday(year: int, month: int, byday: str) -> Optional[_dt.date]:
    match = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", byday.split(",")[0])
    if not match:
        return None
    nth = int(match.group(1) or 1)
    days = _weekdays_in_month(year, month, _DAYS[match.group(2)])
    try:
        return days[nth - 1] if nth > 0 else days[nth]
    except IndexError:
        return None


def _weekdays_in_month(year: int, month: int, weekday: int) -> List[_dt.date]:
    day = _dt.date(year, month, 1)
    day += _dt.timedelta(days=(weekday - day.weekday()) % 7)
    out = []
    while day.month == month:
        out.append(day)
        day += _dt.timedelta(days=7)
    return out


class _Zones:
    """Every zone a file names, by its TZID."""

    def __init__(self, described: Dict[str, _Zone]):
        self.described = described

    def offset(self, tzid: Optional[str], local: _dt.datetime) -> Optional[_dt.timedelta]:
        """The UTC offset of a wall-clock time in ``tzid``; None when the zone
        is not known at all."""
        if not tzid:
            return None
        zone = self.described.get(tzid)
        if zone is not None and zone.rules:
            return zone.utcoffset(local)
        name = WINDOWS_ZONES.get(tzid.strip().lower(), tzid.strip())
        if ZoneInfo is not None:
            try:
                return local.replace(tzinfo=ZoneInfo(name)).utcoffset()
            except Exception:
                return None
        return None


# -- times ----------------------------------------------------------------

def _parse_local(text: str) -> _dt.datetime:
    text = text.strip()
    if len(text) >= 15 and "T" in text:
        return _dt.datetime.strptime(text[:15], "%Y%m%dT%H%M%S")
    return _dt.datetime.strptime(text[:8], "%Y%m%d")


class _When:
    """A moment from the file: a date, or a time (UTC, or wall clock in a zone)."""

    __slots__ = ("local", "all_day", "utc", "tzid")

    def __init__(self, value: str, params: Dict[str, str]):
        value = value.strip()
        self.all_day = params.get("VALUE", "").upper() == "DATE" or "T" not in value
        self.local = _parse_local(value)
        self.utc = value.endswith("Z")
        self.tzid = params.get("TZID")


def _to_home(local: _dt.datetime, *, utc: bool, tzid: Optional[str],
             zones: _Zones, home: Optional[str]) -> _dt.datetime:
    """A wall-clock time moved into the calendar owner's own zone."""
    if not utc and (tzid is None or tzid == home):
        return local
    there = _dt.timedelta(0) if utc else zones.offset(tzid, local)
    if there is None:
        return local
    absolute = local - there
    here = zones.offset(home, absolute) if home else None
    if here is None:
        return local if not utc else absolute
    # The owner's offset at that moment, settled twice around a change of clock.
    guess = absolute + here
    here = zones.offset(home, guess) or here
    return absolute + here


# -- repeating meetings -----------------------------------------------------

def _rule(text: str) -> Dict[str, str]:
    out = {}
    for part in text.split(";"):
        key, _, value = part.partition("=")
        if key:
            out[key.upper()] = value.upper()
    return out


def _add_months(day: _dt.date, months: int) -> _dt.date:
    total = day.year * 12 + day.month - 1 + months
    return _dt.date(total // 12, total % 12 + 1, 1)


def _repeats(first: _dt.datetime, rule: Dict[str, str], until: _dt.datetime,
             since: Optional[_dt.datetime] = None) -> Iterable[_dt.datetime]:
    """Each start of a repeating meeting, in its own wall-clock time, from the
    first up to ``until`` (or the rule's own end).  With no count to keep,
    the years before ``since`` are stepped over rather than walked through."""
    freq = rule.get("FREQ", "")
    try:
        interval = max(1, int(rule.get("INTERVAL") or 1))
    except ValueError:
        interval = 1
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    end = until
    if rule.get("UNTIL"):
        try:
            end = min(end, _parse_local(rule["UNTIL"]).replace(
                hour=23, minute=59, second=59) if "T" not in rule["UNTIL"]
                else _parse_local(rule["UNTIL"]))
        except ValueError:
            pass
    bydays = [d for d in rule.get("BYDAY", "").split(",") if d]
    months = [int(m) for m in rule.get("BYMONTH", "").split(",") if m.isdigit()]
    monthdays = [int(m) for m in rule.get("BYMONTHDAY", "").split(",")
                 if re.fullmatch(r"-?\d+", m)]
    setpos = [int(p) for p in rule.get("BYSETPOS", "").split(",")
              if re.fullmatch(r"-?\d+", p)]
    week_start = _DAYS.get(rule.get("WKST", "MO"), 0)
    clock = first.time()

    def period_days(index: int) -> List[_dt.date]:
        if freq == "DAILY":
            day = first.date() + _dt.timedelta(days=index * interval)
            if bydays and day.weekday() not in {_DAYS.get(d[-2:]) for d in bydays}:
                return []
            return [day]
        if freq == "WEEKLY":
            anchor = first.date() - _dt.timedelta(days=(first.weekday() - week_start) % 7)
            monday = anchor + _dt.timedelta(weeks=index * interval)
            wanted = ({_DAYS[d[-2:]] for d in bydays if d[-2:] in _DAYS}
                      or {first.weekday()})
            return sorted(monday + _dt.timedelta(days=(w - week_start) % 7)
                          for w in wanted)
        if freq == "MONTHLY":
            start = _add_months(first.date().replace(day=1), index * interval)
            return _in_month(start.year, start.month, bydays, monthdays, setpos,
                             first.day)
        if freq == "YEARLY":
            year = first.year + index * interval
            out = []
            for month in months or [first.month]:
                out += _in_month(year, month, bydays, monthdays, setpos,
                                 first.day if not bydays else None)
            return sorted(out)
        return []

    skip = 0
    if count is None and since is not None and since > first:
        gap = (since - first).days
        per = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 31, "YEARLY": 366}.get(freq, 1)
        skip = max(0, gap // (per * interval) - 2)
    made = 0
    for index in range(skip, skip + MAX_REPEATS):
        days = period_days(index)
        if not days and freq not in ("DAILY",):
            # An empty month (the 31st in April) is skipped, not the end.
            if index and _period_start(first, freq, interval, index) > end:
                return
            continue
        for day in days:
            moment = _dt.datetime.combine(day, clock)
            if moment < first:
                continue
            if moment > end:
                return
            yield moment
            made += 1
            if count is not None and made >= count:
                return
        if _period_start(first, freq, interval, index) > end:
            return


def _period_start(first: _dt.datetime, freq: str, interval: int, index: int
                  ) -> _dt.datetime:
    if freq == "DAILY":
        return first + _dt.timedelta(days=index * interval)
    if freq == "WEEKLY":
        return first + _dt.timedelta(weeks=index * interval)
    if freq == "MONTHLY":
        return _dt.datetime.combine(
            _add_months(first.date().replace(day=1), index * interval), first.time())
    return first.replace(year=first.year + index * interval, month=1, day=1)


def _in_month(year: int, month: int, bydays: Sequence[str],
              monthdays: Sequence[int], setpos: Sequence[int],
              default_day: Optional[int]) -> List[_dt.date]:
    last = (_add_months(_dt.date(year, month, 1), 1) - _dt.timedelta(days=1)).day
    days: List[_dt.date] = []
    for spec in bydays:
        match = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", spec)
        if not match:
            continue
        all_of = _weekdays_in_month(year, month, _DAYS[match.group(2)])
        if match.group(1):
            nth = int(match.group(1))
            try:
                days.append(all_of[nth - 1] if nth > 0 else all_of[nth])
            except IndexError:
                pass
        else:
            days.extend(all_of)
    for number in monthdays:
        day = number if number > 0 else last + 1 + number
        if 1 <= day <= last:
            days.append(_dt.date(year, month, day))
    if not bydays and not monthdays and default_day:
        if default_day <= last:
            days.append(_dt.date(year, month, default_day))
    days = sorted(set(days))
    if setpos:
        picked = []
        for pos in setpos:
            try:
                picked.append(days[pos - 1] if pos > 0 else days[pos])
            except IndexError:
                pass
        days = sorted(set(picked))
    return days


# -- the busy times ----------------------------------------------------------

def _counts(lines) -> bool:
    """Whether a calendar entry is time somebody is not free."""
    status = _first(lines, "STATUS")
    if status and status[2].strip().upper() == "CANCELLED":
        return False
    shown = _first(lines, "X-MICROSOFT-CDO-BUSYSTATUS")
    if shown:
        return _COUNTS.get(shown[2].strip().upper(), True)
    transp = _first(lines, "TRANSP")
    if transp and transp[2].strip().upper() == "TRANSPARENT":
        return False
    # A busy-only calendar names each entry only by its kind of time.
    summary = _first(lines, "SUMMARY")
    if summary:
        return _WORDS.get(summary[2].strip().lower(), True)
    return True


def _home_zone(text_lines, events) -> Optional[str]:
    named = _first(text_lines, "X-WR-TIMEZONE")
    if named:
        return named[2].strip()
    used: Dict[str, int] = {}
    for lines in events:
        start = _first(lines, "DTSTART")
        if start and start[1].get("TZID"):
            used[start[1]["TZID"]] = used.get(start[1]["TZID"], 0) + 1
    return max(used, key=used.get) if used else None


def busy_times(text: str, *, start: _dt.date, end: _dt.date,
               day_start: str = "00:00", day_end: str = "23:59",
               home: Optional[str] = None) -> List[Interval]:
    """When the calendar's owner is busy between ``start`` and ``end``
    (inclusive), in their own zone, overlaps joined.  ``home`` is that zone
    (a name like "Asia/Riyadh") when the team's country says it; otherwise
    the calendar's own, or the zone most of its entries are in.  An all-day out-of-office
    entry counts from ``day_start`` to ``day_end``; other all-day entries
    (a reminder, a holiday someone noted) do not count."""
    lines = _lines(text)
    parts = _components(lines)
    zones = _Zones({})
    events = []
    for kind, part in parts:
        if kind == "VTIMEZONE":
            tzid = _first(part, "TZID")
            if tzid:
                nested = [(p[1][0], p[1][1]) for p in part
                          if p[0] == "__PART__" and p[1][0] in ("STANDARD", "DAYLIGHT")]
                zones.described[tzid[2].strip()] = _Zone(nested)
        else:
            events.append(part)
    home = home or _home_zone(lines, events)
    window_start = _dt.datetime.combine(start, _dt.time(0, 0))
    window_end = _dt.datetime.combine(end + _dt.timedelta(days=1), _dt.time(0, 0))

    def moment(when: _When) -> _dt.datetime:
        return _to_home(when.local, utc=when.utc, tzid=when.tzid, zones=zones, home=home)

    # Moved or cancelled single meetings of a series, by series and original time.
    replaced: Dict[str, set] = {}
    singles = []
    series = []
    for lines_ in events:
        uid = (_first(lines_, "UID") or ("", {}, ""))[2]
        rid = _first(lines_, "RECURRENCE-ID")
        if rid:
            replaced.setdefault(uid, set()).add(moment(_When(rid[2], rid[1])))
            singles.append(lines_)
        elif _first(lines_, "RRULE"):
            series.append((uid, lines_))
        else:
            singles.append(lines_)

    out: List[Interval] = []

    def add(first: _dt.datetime, last: _dt.datetime) -> None:
        first, last = max(first, window_start), min(last, window_end)
        if last > first:
            out.append((first, last))

    def length_of(lines_, begin: _When) -> _dt.timedelta:
        finish = _first(lines_, "DTEND")
        if finish:
            return _When(finish[2], finish[1]).local - begin.local
        duration = _first(lines_, "DURATION")
        if duration:
            return _duration(duration[2])
        return _dt.timedelta(days=1) if begin.all_day else _dt.timedelta(0)

    def all_day(first_day: _dt.date, days: int) -> None:
        for i in range(max(1, days)):
            day = first_day + _dt.timedelta(days=i)
            add(_dt.datetime.combine(day, _clock(day_start)),
                _dt.datetime.combine(day, _clock(day_end)))

    def is_oof(lines_) -> bool:
        shown = _first(lines_, "X-MICROSOFT-CDO-BUSYSTATUS")
        summary = _first(lines_, "SUMMARY")
        return bool((shown and shown[2].strip().upper() == "OOF") or
                    (summary and summary[2].strip().lower() in ("away", "out of office")))

    for lines_ in singles:
        if not _counts(lines_):
            continue
        begin_line = _first(lines_, "DTSTART")
        if not begin_line:
            continue
        try:
            begin = _When(begin_line[2], begin_line[1])
            length = length_of(lines_, begin)
        except ValueError:
            continue
        if begin.all_day:
            if is_oof(lines_):
                all_day(begin.local.date(), length.days)
            continue
        first = moment(begin)
        add(first, first + length)

    horizon = window_end + _dt.timedelta(days=2)
    for uid, lines_ in series:
        if not _counts(lines_):
            continue
        begin_line = _first(lines_, "DTSTART")
        if not begin_line:
            continue
        try:
            begin = _When(begin_line[2], begin_line[1])
            length = length_of(lines_, begin)
        except ValueError:
            continue
        skipped = set(replaced.get(uid, ()))
        for each in lines_:
            if each[0] == "EXDATE":
                for value in each[2].split(","):
                    try:
                        skipped.add(moment(_When(value, each[1])))
                    except ValueError:
                        pass
        oof = is_oof(lines_)
        for local in _repeats(begin.local, _rule(_first(lines_, "RRULE")[2]), horizon,
                              since=window_start - _dt.timedelta(days=2)):
            if begin.all_day:
                if oof and local not in skipped:
                    all_day(local.date(), length.days)
                continue
            first = _to_home(local, utc=begin.utc, tzid=begin.tzid, zones=zones,
                             home=home)
            if first in skipped:
                continue
            add(first, first + length)
    return join(out)


def _clock(hhmm: str) -> _dt.time:
    hours, minutes = (int(x) for x in str(hhmm).split(":")[:2])
    return _dt.time(hours, minutes)


def _duration(text: str) -> _dt.timedelta:
    match = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
                         text.strip().upper())
    if not match:
        return _dt.timedelta(0)
    sign, weeks, days, hours, minutes, seconds = match.groups()
    total = _dt.timedelta(weeks=int(weeks or 0), days=int(days or 0),
                          hours=int(hours or 0), minutes=int(minutes or 0),
                          seconds=int(seconds or 0))
    return -total if sign == "-" else total


def join(intervals: Iterable[Interval]) -> List[Interval]:
    """Overlapping or touching stretches made one."""
    out: List[Interval] = []
    for first, last in sorted(intervals):
        if out and first <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], last))
        else:
            out.append((first, last))
    return out


def minus(intervals: Sequence[Interval], taken: Sequence[Interval]) -> List[Interval]:
    """What is left of ``intervals`` outside ``taken``, so time already in the
    plan is never counted twice."""
    left: List[Interval] = []
    taken = join(taken)
    for first, last in intervals:
        cursor = first
        for t_first, t_last in taken:
            if t_last <= cursor or t_first >= last:
                continue
            if t_first > cursor:
                left.append((cursor, t_first))
            cursor = max(cursor, t_last)
            if cursor >= last:
                break
        if cursor < last:
            left.append((cursor, last))
    return left


def window(today: _dt.date) -> Tuple[_dt.date, _dt.date]:
    """The days whose busy times are kept."""
    return today - _dt.timedelta(days=BEHIND_DAYS), today + _dt.timedelta(days=AHEAD_DAYS)
