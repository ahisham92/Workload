"""Who is in which team, and where the work is not where the people are.

The workbook has room for twelve engineers in one flat list, which is fine for
a unit and no use to a head of department with teams under him.  So the
organisation lives in the unit's own database: a person has a grade and a team,
a team has a lead, and moving somebody is one row changing.

The point of it is the last function here.  Timesheets say where the hours
actually went; the establishment says where the people actually are.  Put the
two together per month and the questions a HOD asks answer themselves -- which
team is over its capacity and by how many people, which team has room, who
should move, and from which month it started rather than "at some point".

Everything is measured against *booked hours*, which are history.  A trend in
history is not a forecast, and this module never pretends otherwise: it says
what the last three months did and leaves the decision where it belongs.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: What somebody is, in the order they rank. The label is what the app shows.
GRADES = [
    ("senior", "Senior"),
    ("engineer", "Engineer"),
    ("junior", "Junior"),
    ("bim", "BIM modeller"),
]
GRADE_KEYS = [key for key, _label in GRADES]
DEFAULT_GRADE = "engineer"

#: Above this a person or a team is doing more than a full month, every month.
OVER = 1.0
#: Below this there is room to take work on, or to lend somebody.
UNDER = 0.75
#: How many recent months a judgement is made on. One month is a holiday or a
#: deadline; three is a pattern.
WINDOW = 3

UNASSIGNED = "__none__"


class PeopleError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.errors = [message]


def grade_label(key: str) -> str:
    return dict(GRADES).get(key, key)


def clean_grade(value: Any) -> str:
    key = str(value or "").strip().lower()
    if not key:
        return DEFAULT_GRADE
    if key not in GRADE_KEYS:
        raise PeopleError(
            f"{value!r} is not a grade. Use one of: "
            + ", ".join(f"{k} ({label})" for k, label in GRADES))
    return key


def clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise PeopleError("A person needs a name.")
    if len(name) > 80:
        raise PeopleError("A name has to be 80 characters or fewer.")
    return name


def month_of(date: Optional[_dt.date]) -> Optional[str]:
    return f"{date.year:04d}-{date.month:02d}" if date else None


# --------------------------------------------------------------------------
# the establishment
# --------------------------------------------------------------------------

def roster(store, *, known: Iterable[str] = ()) -> Dict[str, Any]:
    """Everyone this unit knows about, whether or not they have booked time.

    Somebody who appears in the timesheets but has never been given a team is
    still a person -- the roster is the union, so nobody is invisible just
    because the establishment was not filled in first.
    """
    defined = {person["name"]: person for person in store.people()}
    seen = set(store.people_with_rows()) | set(known)
    for name in sorted(seen - set(defined)):
        defined[name] = {"name": name, "team_id": None, "grade": DEFAULT_GRADE,
                         "capacity_hours": None, "active": 1, "created_at": None}
    teams = {team["id"]: team for team in store.teams()}
    people = []
    for person in sorted(defined.values(), key=lambda p: p["name"].lower()):
        team = teams.get(person["team_id"])
        people.append({
            **person,
            "active": bool(person.get("active", 1)),
            "grade": person.get("grade") or DEFAULT_GRADE,
            "grade_label": grade_label(person.get("grade") or DEFAULT_GRADE),
            "team_name": team["name"] if team else "",
            "on_the_establishment": person["created_at"] is not None,
        })
    return {"people": people, "teams": list(teams.values()), "grades": GRADES}


# --------------------------------------------------------------------------
# where the work is against where the people are
# --------------------------------------------------------------------------

def balance(store, *, monthly_capacity: float, year: Optional[int] = None,
            today: Optional[_dt.date] = None) -> Dict[str, Any]:
    """The resourcing picture: teams, their people, and what to do about it."""
    monthly_capacity = float(monthly_capacity or 0) or 185.0
    people = {p["name"]: p for p in roster(store)["people"]}
    teams = {team["id"]: dict(team) for team in store.teams()}

    rows = [row for row in store.all_rows()
            if year is None or (row["date"] and row["date"].year == year)]

    # hours[person][month], and the projects each person and team touched
    hours: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    person_projects: Dict[str, set] = defaultdict(set)
    project_teams: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        month = month_of(row["date"])
        if month is None:
            continue
        hours[row["engineer"]][month] += row["hours"]
        if row["job_number"]:
            person_projects[row["engineer"]].add(row["job_number"])
            team_id = (people.get(row["engineer"]) or {}).get("team_id") or UNASSIGNED
            project_teams[row["job_number"]][team_id] += row["hours"]

    months = sorted({month for person in hours.values() for month in person})
    recent = months[-WINDOW:]

    member_rows = []
    for name, person in people.items():
        booked = hours.get(name, {})
        capacity = float(person.get("capacity_hours") or monthly_capacity)
        member_rows.append({
            "name": name,
            "grade": person["grade"],
            "grade_label": person["grade_label"],
            "team_id": person["team_id"],
            "team_name": person["team_name"],
            "active": person["active"],
            "monthly_capacity": round(capacity, 1),
            "hours": round(sum(booked.values()), 1),
            "months_booked": len(booked),
            "projects": len(person_projects.get(name, ())),
            "by_month": {month: round(booked.get(month, 0.0), 1)
                         for month in months},
            "recent_utilisation": _utilisation(booked, recent, capacity),
            "utilisation": _utilisation(booked, months, capacity),
        })

    team_rows = []
    for team_id in list(teams) + [UNASSIGNED]:
        members = [m for m in member_rows
                   if (m["team_id"] or UNASSIGNED) == team_id and m["active"]]
        if team_id == UNASSIGNED and not members:
            continue
        capacity = sum(m["monthly_capacity"] for m in members)
        booked: Dict[str, float] = defaultdict(float)
        for member in members:
            for month, value in member["by_month"].items():
                booked[month] += value
        team_rows.append({
            "id": team_id,
            "name": (teams[team_id]["name"] if team_id in teams
                     else "Not in a team"),
            "lead": teams.get(team_id, {}).get("lead", ""),
            "headcount": len(members),
            "by_grade": {key: sum(1 for m in members if m["grade"] == key)
                         for key, _ in GRADES},
            "monthly_capacity": round(capacity, 1),
            "hours": round(sum(booked.values()), 1),
            "projects": len({p for m in members
                             for p in person_projects.get(m["name"], ())}),
            "members": [m["name"] for m in members],
            "by_month": {month: round(booked.get(month, 0.0), 1)
                         for month in months},
            "recent_utilisation": _utilisation(booked, recent, capacity),
            "utilisation": _utilisation(booked, months, capacity),
            "over_since": _over_since(booked, months, capacity),
        })

    return {
        "year": year,
        "months": months,
        "recent_months": recent,
        "monthly_capacity": round(monthly_capacity, 1),
        "teams": team_rows,
        "members": member_rows,
        "projects": _projects(project_teams, teams),
        "findings": findings(team_rows, member_rows, monthly_capacity),
        "thresholds": {"over": OVER, "under": UNDER, "window": WINDOW},
    }


def _utilisation(booked: Dict[str, float], months: Sequence[str],
                 capacity: float) -> Optional[float]:
    """Booked against capacity over these months, or None with nothing to say."""
    if not months or capacity <= 0:
        return None
    total = sum(booked.get(month, 0.0) for month in months)
    return round(total / (capacity * len(months)), 3)


def _over_since(booked: Dict[str, float], months: Sequence[str],
                capacity: float) -> Optional[str]:
    """The first month of the run of over-capacity months ending at the last.

    Answering "since when", which is the question, rather than "at some point",
    which is not. A month back under capacity ends the run.
    """
    if capacity <= 0:
        return None
    started = None
    for month in months:
        if booked.get(month, 0.0) > capacity * OVER:
            started = started or month
        else:
            started = None
    return started


def _projects(project_teams: Dict[str, Dict[str, float]],
              teams: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Which teams each project is being carried by, biggest share first."""
    out = []
    for number, shares in project_teams.items():
        total = sum(shares.values()) or 1.0
        ordered = sorted(shares.items(), key=lambda item: -item[1])
        # Percentages that add up: rounding each share on its own gives
        # "68% and 33%", which anybody reading it will take for a mistake.
        percents = _whole_percents([value / total for _team, value in ordered])
        out.append({
            "job_number": number,
            "hours": round(total, 1),
            "teams": [
                {"id": team_id,
                 "name": teams[team_id]["name"] if team_id in teams
                         else "Not in a team",
                 "hours": round(value, 1),
                 "share": round(value / total, 3),
                 "percent": percent}
                for (team_id, value), percent in zip(ordered, percents)],
        })
    out.sort(key=lambda item: -item["hours"])
    return out


def _whole_percents(shares: Sequence[float]) -> List[int]:
    """Whole numbers that still add up to 100: largest remainder wins."""
    if not shares:
        return []
    scaled = [share * 100 for share in shares]
    whole = [int(value) for value in scaled]
    short = 100 - sum(whole)
    order = sorted(range(len(scaled)), key=lambda i: -(scaled[i] - whole[i]))
    for position in order[:max(0, short)]:
        whole[position] += 1
    return whole


def findings(teams: Sequence[Dict[str, Any]], members: Sequence[Dict[str, Any]],
             monthly_capacity: float) -> List[Dict[str, Any]]:
    """What to do about it, in the order it is worth doing.

    Two kinds of answer, and they are different questions. A team over its
    capacity with nobody spare anywhere needs *hiring*; a team over its
    capacity while another has room needs a *move*, which is free.
    """
    out: List[Dict[str, Any]] = []
    stretched = [t for t in teams
                 if t["recent_utilisation"] is not None
                 and t["recent_utilisation"] > OVER and t["headcount"]]
    roomy = [t for t in teams
             if t["recent_utilisation"] is not None
             and t["recent_utilisation"] < UNDER and t["headcount"] >= 1]
    stretched.sort(key=lambda t: -t["recent_utilisation"])
    roomy.sort(key=lambda t: t["recent_utilisation"])

    spare = {t["id"]: _people_spare(t, monthly_capacity) for t in roomy}

    for team in stretched:
        short = (team["recent_utilisation"] - 1.0) * team["headcount"]
        # Only a team that can lose a whole person and stay inside its own
        # capacity: a move that overloads the lender has solved nothing.
        lender = next((t for t in roomy if spare.get(t["id"], 0) >= 1), None)
        if lender is not None:
            who = _who_to_move(lender, members)
            spare[lender["id"]] -= 1
            out.append({
                "kind": "move",
                "level": "warn",
                "team": team["name"],
                "from_team": lender["name"],
                "person": who["name"] if who else None,
                "grade": who["grade_label"] if who else None,
                "headline": (
                    f"Move {who['name']} from {lender['name']} to {team['name']}"
                    if who else
                    f"Move somebody from {lender['name']} to {team['name']}"),
                "detail": (
                    f"{team['name']} has been at "
                    f"{team['recent_utilisation'] * 100:.0f}% of its capacity"
                    + (f" since {team['over_since']}" if team["over_since"] else "")
                    + f", about {short:.1f} people short, while "
                      f"{lender['name']} has been at "
                      f"{lender['recent_utilisation'] * 100:.0f}%."),
                "people": round(short, 1),
            })
        elif short < 0.5 and team["recent_utilisation"] <= 1.1:
            # A team a few percent over is not a hire; if somebody inside it is
            # carrying the excess, the person finding below says so.
            #
            # Both halves of that test matter. "Half a person short" is small
            # for a team of eight and is the whole story for a team of one --
            # a single half-time person at 149% is a tenth of a hire by
            # headcount and still somebody drowning, and saying nothing about
            # them is the one outcome this tab must not produce.
            continue
        else:
            nearest = roomy[0] if roomy else None
            why = "No other team is under its capacity."
            if nearest is not None:
                # Say why the obvious move is not the answer, rather than
                # leaving somebody to work it out and disagree.
                left = nearest["headcount"] - 1
                after = (nearest["recent_utilisation"] * nearest["headcount"]
                         / left) if left else None
                why = (
                    f"{nearest['name']} is the least loaded at "
                    f"{nearest['recent_utilisation'] * 100:.0f}%, but moving one "
                    + (f"of its {nearest['headcount']} would leave the rest at "
                       f"{after * 100:.0f}%." if after
                       else "would leave it with nobody."))
            out.append({
                "kind": "hire",
                "level": "bad",
                "team": team["name"],
                "person": None,
                "headline": (f"{team['name']} needs "
                             f"{max(1, math.ceil(short))} more "
                             f"{'person' if math.ceil(short) <= 1 else 'people'}"),
                "detail": (
                    f"At {team['recent_utilisation'] * 100:.0f}% of capacity"
                    + (f" since {team['over_since']}" if team["over_since"] else "")
                    + f", about {short:.1f} people short. " + why),
                "people": round(short, 1),
            })

    for team in roomy:
        if spare.get(team["id"], 0) > 0.1 and not any(
                f["kind"] == "move" and f["from_team"] == team["name"]
                for f in out):
            out.append({
                "kind": "spare",
                "level": "ok",
                "team": team["name"],
                "person": None,
                "headline": (f"{team['name']} has room for more work"),
                "detail": (f"At {team['recent_utilisation'] * 100:.0f}% of "
                           f"capacity across {team['headcount']} people, about "
                           f"{spare[team['id']]:.1f} of a person spare."),
                "people": round(spare[team["id"]], 1),
            })

    # Only somebody carrying more than their own team is: when a whole team is
    # over, the team finding says so once, and repeating it per member buries
    # the person who is genuinely worse off than the people beside them.
    team_load = {t["name"]: (t["recent_utilisation"] or 0.0) for t in teams}
    for person in members:
        beside = team_load.get(person["team_name"] or "Not in a team", 0.0)
        if person["recent_utilisation"] is not None and person["active"] \
                and person["recent_utilisation"] > 1.25 \
                and person["recent_utilisation"] - beside > 0.15:
            out.append({
                "kind": "person",
                "level": "warn",
                "team": person["team_name"] or "Not in a team",
                "person": person["name"],
                "headline": f"{person['name']} is carrying too much",
                "detail": (f"{person['recent_utilisation'] * 100:.0f}% of a full "
                           f"month on {person['projects']} project(s), against "
                           f"{beside * 100:.0f}% for the team around them."),
                "people": round(person["recent_utilisation"] - 1.0, 2),
            })
    return out


def _people_spare(team: Dict[str, Any], monthly_capacity: float) -> float:
    if team["recent_utilisation"] is None:
        return 0.0
    return max(0.0, (1.0 - team["recent_utilisation"]) * team["headcount"])


def _who_to_move(team: Dict[str, Any],
                 members: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The least loaded of a team; never its lead; and on a tie, the junior.

    Whose hours are freest is the first question. Where that is even -- which
    it usually is, because a quiet team is quiet all through -- the tie goes to
    the least senior, because seniority is what holds a team's work together
    and moving it costs the lender more than the hours say. It is a default,
    not a decision: the name is a suggestion with a button beside it.
    """
    candidates = [m for m in members
                  if m["team_id"] == team["id"] and m["active"]
                  and m["name"] != team.get("lead")]
    if not candidates:
        return None
    return min(candidates, key=lambda m: (
        round(m["recent_utilisation"] or 0.0, 2),
        -GRADE_KEYS.index(m["grade"]) if m["grade"] in GRADE_KEYS else 0,
        m["name"]))
