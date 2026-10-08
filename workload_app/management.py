"""The time a manager gives the team, laid out by itself.

Somebody who leads people does not spend the whole day on project work:
juniors' questions, checking and replying, the team meeting, a word with each
person now and then.  None of that is in a timesheet export as such, and if
the planner ignores it the manager looks free when they are not.

So it is reserved, from what the app already knows about who leads whom:

* **who leads whom** -- a person whose grade is *Manager* leads everybody else
  in the unit; a team's lead leads that team;
* **team support every day** -- a few minutes per person led, more for a
  junior than for a senior, as one block early in the day;
* **the team meeting** -- once a week, on the first working day, at the start
  of the day, longer for a bigger team;
* **a one-to-one with each person** -- every second week, short, at the end of
  a day, spread over the fortnight so no day is all one-to-ones;
* **meetings typed in** -- a client or another trade, a time and who is in
  it (see ``meetings``), taken as they are;
* **Outlook meetings** -- for anybody whose calendar link is in (see
  ``busy_calendar``), the times Outlook says they are busy, less any time the
  meetings above already hold, so nothing is counted twice;
* **development time for everybody** -- not every day but every week, one
  block at the end of the last working day of the week, longer for a junior,
  with the person's goals for the quarter as what to work on (see ``growth``).
  Like the meetings, it comes out of the hours free for project work and
  requests are never booked over it.

Every meeting carries its agenda, built from the same checkpoints the
Check-ins tab raises.  Nothing is typed and nothing is stored.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import busy_calendar
from . import calendar_
from . import tasks as task_sheet
from .busy_calendar import _clock
from .checkins import week_start

MANAGER_GRADE = "manager"

#: Minutes a day of support each person led takes, by their grade.
PER_PERSON_MINUTES = {
    "junior": 30,
    # The drawing office needs as much as a junior: mark-ups, checking each
    # drawing, and the questions that come with them.
    "drafter": 30,
    "bim": 30,
    "engineer": 20,
    "senior": 10,
    MANAGER_GRADE: 10,
}
#: Never more than this share of a working day goes on team support.
MAX_SUPPORT_SHARE = 0.5
#: The weekly team meeting: a base, a little more for each person, a ceiling.
TEAM_MEETING_MINUTES = 30
TEAM_MEETING_PER_PERSON = 5
TEAM_MEETING_MAX = 60
#: A one-to-one with each person, once in this many weeks.
ONE_TO_ONE_MINUTES = 20
ONE_TO_ONE_EVERY_WEEKS = 2


def _quarter(hours: float) -> float:
    return round(hours * 4) / 4


def leaders(roster: Sequence[Dict[str, Any]],
            teams: Sequence[Dict[str, Any]] = ()) -> Dict[str, List[Dict[str, Any]]]:
    """Each person who leads somebody, and the people they lead.

    A manager comes before the team leads, so their meeting is the first of
    the day.
    """
    active = [p for p in roster if p.get("active", True)]
    names = {p["name"] for p in active}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for person in sorted(active, key=lambda p: p["name"].lower()):
        if person.get("grade") == MANAGER_GRADE:
            out[person["name"]] = [p for p in active if p["name"] != person["name"]]
    for team in sorted(teams, key=lambda t: str(t.get("name") or "").lower()):
        lead = team.get("lead") or ""
        if lead not in names:
            continue
        members = [p for p in active
                   if p.get("team_id") == team.get("id") and p["name"] != lead]
        if not members:
            continue
        have = out.setdefault(lead, [])
        known = {p["name"] for p in have}
        have.extend(p for p in members if p["name"] not in known)
    return {name: led for name, led in out.items() if led}


def support_hours(led: Sequence[Dict[str, Any]], config: Dict[str, Any]) -> float:
    """Hours a day of team support for the people led."""
    minutes = sum(PER_PERSON_MINUTES.get(p.get("grade") or "", 20) for p in led)
    ceiling = task_sheet.hours_per_day(config) * MAX_SUPPORT_SHARE
    return _quarter(min(minutes / 60.0, ceiling))


def _working(first: _dt.date, days: int, config: Dict[str, Any]) -> List[_dt.date]:
    return [d for d in (first + _dt.timedelta(days=i) for i in range(days))
            if task_sheet.is_working_day(d, config)]


#: Hours a week each person keeps for their own development, by grade.
DEVELOPMENT_HOURS = {
    "junior": 3.0,
    "drafter": 2.0,
    "bim": 2.0,
    "engineer": 2.0,
    "senior": 2.0,
    MANAGER_GRADE: 2.0,
}
#: For somebody with no grade yet.
DEVELOPMENT_HOURS_DEFAULT = 2.0
#: Outlook meetings are averaged over this many coming working days when a
#: plan wants hours a day rather than the days themselves.
OUTLOOK_AVERAGE_DAYS = 10


def development_hours(grade: Optional[str]) -> float:
    """Hours a week of development time for somebody of ``grade``."""
    return DEVELOPMENT_HOURS.get(grade or "", DEVELOPMENT_HOURS_DEFAULT)


class Plan:
    """Who leads whom, and what that puts in each day."""

    def __init__(self, roster: Sequence[Dict[str, Any]],
                 teams: Sequence[Dict[str, Any]], config: Dict[str, Any],
                 goals: Optional[Mapping[str, Sequence[str]]] = None,
                 outlook: Optional[Mapping[str, Sequence[tuple]]] = None,
                 today: Optional[_dt.date] = None,
                 typed: Optional[Sequence[Dict[str, Any]]] = None):
        self.config = config
        self.led = leaders(roster, teams)
        self.support = {name: support_hours(led, config)
                        for name, led in self.led.items()}
        #: Each active person's weekly development hours.
        self.development = {p["name"]: development_hours(p.get("grade"))
                            for p in roster if p.get("active", True)}
        #: What each person works on in it: their goals for the quarter.
        self.goals = dict(goals or {})
        #: When each person's Outlook calendar says they are busy.
        self.outlook = {name: [(_moment(a), _moment(b)) for a, b in spans]
                        for name, spans in (outlook or {}).items() if spans}
        self.today = today
        #: Meetings typed in by hand (see ``meetings``), each time it falls.
        self.typed = list(typed or ())

    def hours_a_day(self) -> Dict[str, float]:
        """What leading people takes from each leader's day, on average:
        the daily support, plus the meetings spread over the fortnight."""
        a_day = task_sheet.hours_per_day(self.config)
        days = max(1, len(_working(_dt.date(2024, 1, 1), 7, self.config)))
        out = {}
        for name, led in self.led.items():
            weekly = (_team_meeting_minutes(led)
                      + len(led) * ONE_TO_ONE_MINUTES / ONE_TO_ONE_EVERY_WEEKS) / 60
            out[name] = round(min(a_day, self.support[name] + weekly / days), 2)
        return out

    def taken_a_day(self) -> Dict[str, float]:
        """Everything that is not project work, on average a day: leading
        people, and everybody's own development time."""
        a_day = task_sheet.hours_per_day(self.config)
        days = max(1, len(_working(_dt.date(2024, 1, 1), 7, self.config)))
        out = dict(self.hours_a_day())
        for name, hours in self.development.items():
            out[name] = round(min(a_day, out.get(name, 0.0) + hours / days), 2)
        for name, hours in self.outlook_a_day().items():
            out[name] = round(min(a_day, out.get(name, 0.0) + hours), 2)
        return out

    def outlook_a_day(self) -> Dict[str, float]:
        """Each person's meetings from outside the app -- typed in or from
        Outlook -- on average a working day over the coming days, beyond what
        the meetings above already hold."""
        if not (self.outlook or self.typed) or self.today is None:
            return {}
        days = []
        day = self.today
        for _ in range(OUTLOOK_AVERAGE_DAYS * 3):
            if len(days) >= OUTLOOK_AVERAGE_DAYS:
                break
            if task_sheet.is_working_day(day, self.config):
                days.append(day)
            day += _dt.timedelta(days=1)
        if not days:
            return {}
        total: Dict[str, float] = {}
        for day in days:
            for block in self.day_blocks(day)[2]:
                hours = (block["end"] - block["start"]).total_seconds() / 3600
                total[block["leader"]] = total.get(block["leader"], 0.0) + hours
        return {name: round(hours / len(days), 2) for name, hours in total.items()}

    def outlook_on(self, day: _dt.date, taken: Sequence[Dict[str, Any]] = ()
                   ) -> List[Dict[str, Any]]:
        """Each person's Outlook meetings on ``day``, inside the working day,
        less the time ``taken`` (meetings already in the plan) holds."""
        config = self.config
        if not self.outlook or not task_sheet.is_working_day(day, config):
            return []
        start = _dt.datetime.combine(day, _clock(config["day_start"]))
        close = _dt.datetime.combine(day, _clock(config["day_end"]))
        out = []
        for name in sorted(self.outlook, key=str.lower):
            if calendar_.is_away(config, name, day):
                continue
            spans = [(max(a, start), min(b, close)) for a, b in self.outlook[name]
                     if a < close and b > start]
            held = [(m["start"], m["end"]) for m in taken
                    if name == m["leader"] or name in m["with"]]
            for first, last in busy_calendar.minus(spans, held):
                if last > first:
                    out.append({"kind": "outlook", "leader": name, "with": [],
                                "start": first, "end": last,
                                "title": "In a meeting (Outlook)"})
        return out

    def typed_on(self, day: _dt.date, taken: Sequence[Dict[str, Any]] = ()
                 ) -> List[Dict[str, Any]]:
        """The meetings typed in for ``day``, one block for each person in
        them, inside the working day, less the time ``taken`` holds."""
        config = self.config
        if not self.typed or not task_sheet.is_working_day(day, config):
            return []
        start = _dt.datetime.combine(day, _clock(config["day_start"]))
        close = _dt.datetime.combine(day, _clock(config["day_end"]))
        out = []
        for meeting in self.typed:
            if not (meeting["start"] < close and meeting["end"] > start):
                continue
            span = (max(meeting["start"], start), min(meeting["end"], close))
            for name in meeting["people"]:
                if calendar_.is_away(config, name, day):
                    continue
                held = [(m["start"], m["end"]) for m in taken
                        if name == m["leader"] or name in m["with"]]
                for first, last in busy_calendar.minus([span], held):
                    out.append({"kind": "typed", "leader": name, "with": [],
                                "start": first, "end": last,
                                "title": meeting["title"], "what": meeting["kind"],
                                "meeting_id": meeting.get("id")})
        return out

    def day_blocks(self, day: _dt.date) -> tuple:
        """The day's meetings, development times, and the meetings from
        outside the app (typed in, then Outlook), each placed around the ones
        before it."""
        meetings = self.meetings_on(day)
        raw = [{"leader": name, "with": [], "start": a, "end": b}
               for name, spans in self.outlook.items() for a, b in spans
               if a.date() <= day <= b.date()]
        raw += [{"leader": name, "with": [], "start": m["start"], "end": m["end"]}
                for m in self.typed if m["start"].date() == day for name in m["people"]]
        development = self.development_on(day, meetings + raw)
        typed = self.typed_on(day, meetings + development)
        outlook = self.outlook_on(day, meetings + development + typed)
        return meetings, development, typed + outlook

    def development_day(self, name: str, day: _dt.date) -> Optional[_dt.date]:
        """The day of ``day``'s week that holds ``name``'s development time:
        the last working day of the week they are in."""
        week = _working(week_start(day, self.config), 7, self.config)
        here = [d for d in week if not calendar_.is_away(self.config, name, d)]
        return here[-1] if here else None

    def development_on(self, day: _dt.date,
                       meetings: Optional[Sequence[Dict[str, Any]]] = None
                       ) -> List[Dict[str, Any]]:
        """Each person's development block, on the day it falls: at the end of
        the day, before any one-to-one they have there."""
        config = self.config
        if not task_sheet.is_working_day(day, config):
            return []
        if meetings is None:
            meetings = self.meetings_on(day)
        start = _dt.datetime.combine(day, _clock(config["day_start"]))
        close = _dt.datetime.combine(day, _clock(config["day_end"]))
        out = []
        for name in sorted(self.development, key=str.lower):
            hours = self.development[name]
            if not hours or self.development_day(name, day) != day:
                continue
            length = _dt.timedelta(minutes=round(hours * 60))
            taken = sorted(((m["start"], m["end"]) for m in meetings
                            if name == m["leader"] or name in m["with"]),
                           key=lambda pair: pair[1], reverse=True)
            end = close
            moved = True
            while moved:
                moved = False
                for first, last in taken:
                    if first < end and last > end - length:
                        end = first
                        moved = True
            begin = max(start, end - length)
            if end <= begin:
                continue
            goals = list(self.goals.get(name, ()))
            out.append({"kind": "development", "leader": name, "with": [],
                        "start": begin, "end": end, "title": "Development time",
                        "agenda": ([f"Goal: {g}" for g in goals] if goals else
                                   ["No goals set for this quarter yet: ask your "
                                    "manager to set them on Growth."])})
        return out

    def meetings_on(self, day: _dt.date) -> List[Dict[str, Any]]:
        """The meetings on ``day``, each with its time, who runs it and who is in it.

        Somebody away is not in it; a meeting whose leader is away that day is
        not held.
        """
        config = self.config
        if not task_sheet.is_working_day(day, config):
            return []
        start = _dt.datetime.combine(day, _clock(config["day_start"]))
        close = _dt.datetime.combine(day, _clock(config["day_end"]))
        week = _working(week_start(day, config), 7, config)
        fortnight_start = week_start(day, config)
        if (fortnight_start.toordinal() // 7) % ONE_TO_ONE_EVERY_WEEKS:
            fortnight_start -= _dt.timedelta(days=7)
        fortnight = _working(fortnight_start, 7 * ONE_TO_ONE_EVERY_WEEKS, config)

        out: List[Dict[str, Any]] = []
        cursor = start
        late = close
        for leader, led in self.led.items():
            if calendar_.is_away(config, leader, day):
                continue
            # The team meeting: the first day of the week the leader is in.
            held = next((d for d in week
                         if not calendar_.is_away(config, leader, d)), None)
            if held == day:
                there = [p["name"] for p in led
                         if not calendar_.is_away(config, p["name"], day)]
                if there:
                    end = cursor + _dt.timedelta(minutes=_team_meeting_minutes(led))
                    out.append({"kind": "team", "leader": leader, "with": there,
                                "start": cursor, "end": end,
                                "title": "Team meeting"})
                    cursor = end
            # One-to-ones: person i on the fortnight's day i, round and round,
            # at the end of the day.
            # Not on a team-meeting day: the first working day of either week.
            # The same list from any day of the fortnight, so each person
            # gets exactly one.
            firsts = {min(d for d in fortnight if week_start(d, config) == w)
                      for w in {week_start(d, config) for d in fortnight}}
            days = [d for d in fortnight if d not in firsts] or fortnight
            for i, person in enumerate(sorted(led, key=lambda p: p["name"].lower())):
                if days[i % len(days)] != day:
                    continue
                if calendar_.is_away(config, person["name"], day):
                    continue
                begin = late - _dt.timedelta(minutes=ONE_TO_ONE_MINUTES)
                if begin < cursor:
                    continue
                out.append({"kind": "one_to_one", "leader": leader,
                            "with": [person["name"]], "start": begin, "end": late,
                            "title": f"One-to-one: {leader} and {person['name']}"})
                late = begin
        return out

    def for_day(self, day: _dt.date, agendas: Optional[Any] = None) -> Dict[str, Any]:
        """What ``daily.plan_day`` takes for ``day``. ``agendas``, when given,
        is called with each meeting and returns its agenda."""
        meetings, development, outlook = self.day_blocks(day)
        if agendas is not None:
            for meeting in meetings:
                meeting["agenda"] = agendas(meeting, day)
        meetings = meetings + development + outlook
        return {"meetings": meetings, "support": self.support,
                "led": {name: len(led) for name, led in self.led.items()}}

    def busy(self, name: str, first: _dt.date, days: int) -> List[tuple]:
        """The meeting times ``name`` is in over the coming days, for slotting
        requests around them."""
        out = []
        for day in (first + _dt.timedelta(days=i) for i in range(days)):
            for meeting in [m for part in self.day_blocks(day) for m in part]:
                if name == meeting["leader"] or name in meeting["with"]:
                    out.append((meeting["start"], meeting["end"]))
        return out


def _team_meeting_minutes(led: Sequence[Any]) -> int:
    return min(TEAM_MEETING_MAX,
               TEAM_MEETING_MINUTES + TEAM_MEETING_PER_PERSON * len(led))


def _moment(value: Any) -> _dt.datetime:
    return value if isinstance(value, _dt.datetime) else _dt.datetime.fromisoformat(value)


# --------------------------------------------------------------------------
# agendas
# --------------------------------------------------------------------------

#: Points raised per person in the team meeting; a one-to-one has room for all.
TEAM_POINTS_EACH = 2
ONE_TO_ONE_POINTS = 6


def agenda(meeting: Dict[str, Any], *, checkpoints: Mapping[str, Sequence[Dict[str, Any]]],
           signals: Mapping[str, str], tasks: Sequence[task_sheet.Task],
           day: _dt.date, config: Dict[str, Any],
           can_take: Sequence[str] = ()) -> List[str]:
    """What to go through, from the same checkpoints Check-ins raises."""
    lines: List[str] = []
    if meeting["kind"] == "one_to_one":
        name = meeting["with"][0]
        if signals.get(name):
            lines.append(f"How the load feels: {signals[name].lower()}.")
        for point in list(checkpoints.get(name, ()))[:ONE_TO_ONE_POINTS]:
            lines.append(point["text"])
        lines.append("Anything blocking them, and what they would like to "
                     "pick up next.")
        return lines

    week = _working(week_start(day, config), 7, config)
    end = week[-1] if week else day
    due = sorted((t for t in tasks if not t.done and t.due and day <= t.due <= end
                  and (set(t.assignees) & set(meeting["with"] + [meeting["leader"]]))),
                 key=lambda t: t.due)
    for task in due[:6]:
        who = ", ".join(task.assignees)
        lines.append(f"Due {task.due:%a %d %b}: {task.name}"
                     + (f" ({task.project_number})" if task.project_number else "")
                     + (f" -- {who}" if who else ""))
    for name in meeting["with"]:
        for point in [p for p in checkpoints.get(name, ()) if p["level"] == "now"
                      ][:TEAM_POINTS_EACH]:
            lines.append(f"{name}: {point['text']}")
    room = [n for n in can_take if n in meeting["with"]]
    if room:
        lines.append(f"Room this week: {', '.join(room)}.")
    lines.append("Who is away in the coming days, and the handovers.")
    return lines
