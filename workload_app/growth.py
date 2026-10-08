"""Developing people: weekly development time, goals each quarter, and KPIs
that differ by grade.

A manager is measured partly on how they develop and support the people they
lead, a senior partly on the team they help, and an engineer mostly on what
they deliver.  So each grade has its own parts and weights, and a person is
ranked only against people of the same grade: a junior is never set against
a manager.

* **Development time** -- every week, never every day: one block for each
  person, sized by grade (``management.DEVELOPMENT_HOURS``), kept in their
  plan like a meeting.
* **Goals** -- a few per person per quarter, set by the manager at the start
  and marked met, partly or not met at the review three months on.
* **KPI parts**, each 0 to 100:

  - *Delivery*: the scorecard (Reports), worked out among the same grade only;
  - *Own goals*: how far their own goals for the quarter were met;
  - *Team support*: for somebody who leads people, the asks from their people
    (Stuck / Need help on My day) they answered, and how their people deliver;
  - *Developing people*: for somebody who leads people, whether each person
    led has goals for the quarter, and how far those goals were met.

  A part with nothing to go on yet (goals not reviewed, nobody led) is left
  out and the others count in proportion, so the score never punishes what
  could not happen; it says so beside the part.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import management
from . import people as people_module
from .model import ValidationError

#: The parts of a KPI, in the order they are shown.
PARTS = [
    ("delivery", "Delivery"),
    ("own_goals", "Own goals"),
    ("team_support", "Team support"),
    ("developing", "Developing people"),
]
PART_LABEL = dict(PARTS)

#: Each grade's weights. Leading grades carry the team parts.
WEIGHTS: Dict[str, Dict[str, float]] = {
    "junior": {"delivery": 0.85, "own_goals": 0.15},
    "drafter": {"delivery": 0.85, "own_goals": 0.15},
    "bim": {"delivery": 0.85, "own_goals": 0.15},
    "engineer": {"delivery": 0.80, "own_goals": 0.20},
    "senior": {"delivery": 0.60, "own_goals": 0.15, "team_support": 0.15,
               "developing": 0.10},
    management.MANAGER_GRADE: {"delivery": 0.25, "own_goals": 0.15,
                               "team_support": 0.25, "developing": 0.35},
}
#: Somebody with no grade yet is weighed like an engineer.
DEFAULT_WEIGHTS = WEIGHTS["engineer"]

#: Results a goal can be given at the review, and what each scores.
RESULTS = {"met": 100.0, "partly": 50.0, "not_met": 0.0}
RESULT_LABEL = {"met": "Met", "partly": "Partly met", "not_met": "Not met", "": "Not reviewed"}
#: Goals one person can have in a quarter: a few, so each one matters.
MOST_GOALS = 5
LONGEST = 200
#: The review is due this many days before the quarter ends.
REVIEW_DAYS_BEFORE_END = 14

_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")


class GrowthError(ValidationError):
    pass


# --------------------------------------------------------------------------
# quarters
# --------------------------------------------------------------------------

def quarter_of(day: _dt.date) -> str:
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def quarter_bounds(quarter: str) -> tuple:
    match = _QUARTER.match(quarter or "")
    if not match:
        raise GrowthError([f"{quarter!r} is not a quarter, like 2026-Q4."])
    year, number = int(match.group(1)), int(match.group(2))
    if year < 1:
        raise GrowthError([f"{quarter!r} is not a quarter, like 2026-Q4."])
    first = _dt.date(year, 3 * number - 2, 1)
    last = (_dt.date(year + 1, 1, 1) if number == 4
            else _dt.date(year, 3 * number + 1, 1)) - _dt.timedelta(days=1)
    return first, last


def shift(quarter: str, by: int) -> str:
    first, _ = quarter_bounds(quarter)
    index = first.year * 4 + (first.month - 1) // 3 + by
    return f"{index // 4}-Q{index % 4 + 1}"


def label(quarter: str) -> str:
    first, last = quarter_bounds(quarter)
    return f"{quarter.split('-')[1]} {first.year} ({first:%b} to {last:%b})"


def clean_quarter(value: Any, today: _dt.date) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return quarter_of(today)
    quarter_bounds(text)
    return text


# --------------------------------------------------------------------------
# goals
# --------------------------------------------------------------------------

def _text(value: Any) -> str:
    return " ".join(str(value or "").split())[:LONGEST]


def clean_goal(body: Mapping[str, Any], *, people: Sequence[str], today: _dt.date,
               existing: Sequence[Dict[str, Any]] = ()) -> Dict[str, str]:
    """A new goal from the form, or the reasons it cannot be kept."""
    errors = []
    person = str(body.get("person") or "").strip()
    if person not in people:
        errors.append("Pick somebody on the team.")
    goal = _text(body.get("goal"))
    if not goal:
        errors.append("Write the goal: what they will be able to do by the end "
                      "of the quarter.")
    try:
        quarter = clean_quarter(body.get("quarter"), today)
    except GrowthError as error:
        errors.extend(error.errors)
        quarter = ""
    if quarter and person and sum(1 for g in existing if g["person"] == person
                                  and g["quarter"] == quarter) >= MOST_GOALS:
        errors.append(f"{person} already has {MOST_GOALS} goals for {quarter}. "
                      "A few that matter beat many that do not.")
    if errors:
        raise GrowthError(errors)
    return {"person": person, "quarter": quarter, "goal": goal,
            "measure": _text(body.get("measure"))}


def clean_review(body: Mapping[str, Any]) -> Dict[str, str]:
    result = str(body.get("result") or "").strip().lower()
    if result not in RESULTS and result != "":
        raise GrowthError(["Mark it met, partly met or not met."])
    return {"result": result, "note": _text(body.get("note"))}


def goal_view(goal: Mapping[str, Any]) -> Dict[str, Any]:
    return {"id": goal["id"], "person": goal["person"], "quarter": goal["quarter"],
            "goal": goal["goal"], "measure": goal["measure"],
            "result": goal["result"], "result_label": RESULT_LABEL.get(goal["result"], ""),
            "note": goal["review_note"], "reviewed_at": goal["reviewed_at"]}


def goals_by_person(goals: Sequence[Mapping[str, Any]], quarter: str
                    ) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for goal in goals:
        if goal["quarter"] == quarter:
            out.setdefault(goal["person"], []).append(goal["goal"])
    return out


def _achieved(goals: Sequence[Mapping[str, Any]]) -> Optional[float]:
    """How far reviewed goals were met, 0 to 100; None before any review."""
    marked = [RESULTS[g["result"]] for g in goals if g["result"] in RESULTS]
    return sum(marked) / len(marked) if marked else None


# --------------------------------------------------------------------------
# the KPIs
# --------------------------------------------------------------------------

def _round(value: Optional[float], places: int = 1) -> Optional[float]:
    return None if value is None else round(value, places)


def build(*, quarter: str, today: _dt.date, roster: Sequence[Dict[str, Any]],
          led: Mapping[str, Sequence[Dict[str, Any]]],
          delivery: Mapping[str, Mapping[str, float]],
          goals: Sequence[Mapping[str, Any]],
          asks: Sequence[Mapping[str, Any]],
          development: Mapping[str, float],
          development_day: Mapping[str, Optional[str]],
          delivery_from: Optional[str] = None) -> Dict[str, Any]:
    """The Growth page for ``quarter``.

    ``delivery`` is each grade's scorecard totals among that grade only;
    ``asks`` are the Stuck / Need help marks raised in the quarter;
    ``development`` the weekly hours and ``development_day`` the day this
    week that holds them.  ``delivery_from`` names the quarter the delivery
    figures come from when it is not ``quarter`` itself.
    """
    delivery_from = delivery_from or quarter
    stand_in = (f" Nothing is booked in {quarter} yet, so {delivery_from} "
                "stands in." if delivery_from != quarter else "")
    first, last = quarter_bounds(quarter)
    active = [p for p in roster if p.get("active", True)]
    names = [p["name"] for p in active]
    of_quarter = [g for g in goals if g["quarter"] == quarter and g["person"] in names]
    mine: Dict[str, List[Mapping[str, Any]]] = {n: [] for n in names}
    for goal in of_quarter:
        mine[goal["person"]].append(goal)

    # Asks from each person, answered by a lead or still open.
    answered: Dict[str, int] = {}
    waiting: Dict[str, int] = {}
    for ask in asks:
        if ask["kind"] not in ("stuck", "help"):
            continue
        if ask.get("cleared_by") == "lead":
            answered[ask["person"]] = answered.get(ask["person"], 0) + 1
        elif not ask.get("cleared_at"):
            waiting[ask["person"]] = waiting.get(ask["person"], 0) + 1

    def delivery_of(name: str, grade: str) -> Optional[float]:
        value = (delivery.get(grade) or {}).get(name)
        return None if value is None else float(value)

    grade_of = {p["name"]: p.get("grade") or "" for p in active}

    people_out = []
    for person in sorted(active, key=lambda p: p["name"].lower()):
        name = person["name"]
        grade = grade_of[name]
        weights = WEIGHTS.get(grade, DEFAULT_WEIGHTS)
        led_names = [p["name"] for p in led.get(name, ()) if p["name"] in mine]
        parts = []

        def part(key: str, score: Optional[float], why: str) -> None:
            if key not in weights:
                return
            parts.append({"key": key, "label": PART_LABEL[key],
                          "weight": weights[key], "score": _round(score),
                          "why": why})

        own = delivery_of(name, grade)
        part("delivery", own,
             ("The Reports scorecard for the quarter, scored against the same "
              "grade only." + stand_in) if own is not None else
             "No project hours booked in the quarter yet.")

        achieved = _achieved(mine[name])
        if not mine[name]:
            why = "No goals set for this quarter yet."
        elif achieved is None:
            why = (f"{len(mine[name])} goal{'s' if len(mine[name]) != 1 else ''} "
                   "set; counted once reviewed.")
        else:
            why = f"From the review of {len(mine[name])} goal{'s' if len(mine[name]) != 1 else ''}."
        part("own_goals", achieved, why)

        if led_names:
            got = sum(answered.get(n, 0) for n in led_names)
            open_ = sum(waiting.get(n, 0) for n in led_names)
            pieces = []
            notes = []
            if got + open_:
                pieces.append(100.0 * got / (got + open_))
                notes.append(f"{got} of {got + open_} asks from the team answered")
            team = [delivery_of(n, grade_of[n]) for n in led_names]
            team = [t for t in team if t is not None]
            if team:
                pieces.append(sum(team) / len(team))
                notes.append(f"the team's delivery averages {sum(team) / len(team):.0f}")
            part("team_support", sum(pieces) / len(pieces) if pieces else None,
                 ("; ".join(notes) + ".").capitalize() if notes else
                 "Nothing from the team to go on yet.")

            with_goals = [n for n in led_names if mine[n]]
            share = 100.0 * len(with_goals) / len(led_names)
            reached = [a for a in (_achieved(mine[n]) for n in with_goals) if a is not None]
            pieces = [share] + ([sum(reached) / len(reached)] if reached else [])
            part("developing", sum(pieces) / len(pieces),
                 f"{len(with_goals)} of {len(led_names)} people led have goals"
                 + (f"; their goals were {sum(reached) / len(reached):.0f}% met."
                    if reached else "; how far they are met counts once reviewed."))
        else:
            for key in ("team_support", "developing"):
                part(key, None, "Leads nobody yet: make them a team's lead on "
                                "Resourcing, or set their grade to Manager.")

        counted = [p for p in parts if p["score"] is not None]
        weight = sum(p["weight"] for p in counted)
        score = (sum(p["score"] * p["weight"] for p in counted) / weight
                 if weight else None)
        people_out.append({
            "name": name,
            "grade": grade,
            "grade_label": people_module.grade_label(grade) if grade else "No grade",
            "team_name": person.get("team_name", ""),
            "leads": len(led_names),
            "development_hours": development.get(name, 0.0),
            "development_day": development_day.get(name),
            "goals": [goal_view(g) for g in mine[name]],
            "score": _round(score),
            "complete": all(p["score"] is not None for p in parts),
            "parts": parts,
        })

    # Rank within each grade, never across.
    grades = []
    order = [g for g, _label in people_module.GRADES]
    for grade in sorted({p["grade"] for p in people_out},
                        key=lambda g: (order.index(g) if g in order else len(order), g)):
        group = [p for p in people_out if p["grade"] == grade]
        ranked = sorted((p for p in group if p["score"] is not None),
                        key=lambda p: (-p["score"], p["name"].lower()))
        for position, p in enumerate(ranked, start=1):
            p["rank"], p["of"] = position, len(ranked)
        weights = WEIGHTS.get(grade, DEFAULT_WEIGHTS)
        grades.append({
            "grade": grade,
            "label": group[0]["grade_label"],
            "weights": [{"key": k, "label": PART_LABEL[k], "weight": weights[k]}
                        for k, _ in PARTS if k in weights],
            "people": [p["name"] for p in ranked]
                      + [p["name"] for p in group if p["score"] is None],
        })

    return {
        "quarter": quarter,
        "label": label(quarter),
        "first": first.isoformat(),
        "last": last.isoformat(),
        "current": quarter_of(today),
        "quarters": [shift(quarter_of(today), by) for by in (-2, -1, 0, 1)],
        "people": people_out,
        "grades": grades,
        "todo": _todo(quarter, today, people_out, goals, names),
        "most_goals": MOST_GOALS,
        "delivery_from": delivery_from,
    }


def _todo(quarter: str, today: _dt.date, people_out: Sequence[Dict[str, Any]],
          goals: Sequence[Mapping[str, Any]], names: Sequence[str]
          ) -> List[Dict[str, Any]]:
    """What the manager should do next, most pressing first."""
    out = []
    current = quarter_of(today)
    first, last = quarter_bounds(quarter)
    previous = shift(current, -1)
    behind = [g for g in goals if g["quarter"] == previous and not g["result"]
              and g["person"] in names]
    if behind and quarter in (current, previous):
        people = sorted({g["person"] for g in behind})
        out.append({"kind": "review", "level": "now", "quarter": previous,
                    "text": f"Review last quarter's goals: {len(behind)} not marked yet "
                            f"({', '.join(people[:4])}{'…' if len(people) > 4 else ''}). "
                            "Mark each met, partly met or not met."})
    if quarter == current:
        missing = [p["name"] for p in people_out if not p["goals"]]
        if missing:
            out.append({"kind": "set", "level": "now" if (today - first).days > 14 else "soon",
                        "quarter": quarter, "people": missing,
                        "text": f"Set goals for {len(missing)} "
                                f"{'person' if len(missing) == 1 else 'people'} this quarter: "
                                f"{', '.join(missing[:4])}{'…' if len(missing) > 4 else ''}."})
        open_ = sum(1 for p in people_out for g in p["goals"] if not g["result"])
        if open_ and (last - today).days <= REVIEW_DAYS_BEFORE_END:
            out.append({"kind": "review", "level": "soon", "quarter": quarter,
                        "text": f"The quarter ends {last:%d %b}: review {open_} "
                                f"goal{'s' if open_ != 1 else ''} with each person."})
    unled = [p["name"] for p in people_out
             if "team_support" in {x["key"] for x in p["parts"]} and not p["leads"]]
    if unled:
        out.append({"kind": "lead", "level": "note",
                    "text": f"{', '.join(unled)} lead{'s' if len(unled) == 1 else ''} "
                            "nobody, so the team parts of their KPI are not counted. "
                            "Make them a team's lead on Resourcing if they do lead."})
    days = sorted({p["development_day"] for p in people_out if p["development_day"]})
    if days and quarter == current:
        when = ", ".join(_dt.date.fromisoformat(d).strftime("%a %d %b") for d in days)
        out.append({"kind": "development", "level": "note",
                    "text": f"Development time this week is kept for everybody "
                            f"({when}, end of the day). Nothing is booked over it."})
    return out
