"""Every unit a manager has, side by side.

Somebody with more than one unit -- a head of department with a unit per
discipline, or a manager who also looks after a second team -- needs the whole
picture before the detail: which unit and which team is stretched, where there
is room, how much of their own week leading people takes in all of them, and
anybody who books time in more than one unit.

Each unit's own Check-ins is the source, so the figures here are the ones the
unit shows when it is opened.  People are matched across units by the name
the unit knows them by.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Sequence, Tuple

from .people import NO_TEAM as UNASSIGNED


def unit_summary(name: str, unit_id: str, view: Dict[str, Any]) -> Dict[str, Any]:
    """One unit's line, and a line for each of its teams, from its Check-ins."""
    people = view.get("people") or []
    teams: Dict[str, Dict[str, Any]] = {}
    for person in people:
        team = teams.setdefault(person.get("team_name") or UNASSIGNED, {
            "name": person.get("team_name") or UNASSIGNED, "people": 0,
            "free_week": 0.0, "rest": 0, "busy": 0, "fresh": 0, "urgent": 0})
        team["people"] += 1
        team["free_week"] += person["free_week"]
        key = person["signal"]["key"]
        if key in ("rest", "busy", "fresh"):
            team[key] += 1
        team["urgent"] += sum(1 for c in person["checkpoints"] if c["level"] == "now")
    for team in teams.values():
        team["free_week"] = round(team["free_week"], 1)
    signals = {s["key"]: s["count"] for s in view.get("signals") or []}
    return {
        "id": unit_id,
        "name": name,
        "people": len(people),
        "free_week": view.get("free_week", 0.0),
        "rest": signals.get("rest", 0),
        "busy": signals.get("busy", 0),
        "fresh": signals.get("fresh", 0),
        "urgent": view.get("urgent", 0),
        "stale": bool(view.get("stale")),
        "through": view.get("through"),
        "teams": sorted(teams.values(), key=lambda t: (t["name"] == UNASSIGNED,
                                                       t["name"].lower())),
        "leading": [{"name": l["name"], "people": len(l["people"]),
                     "hours_a_day": l["hours_a_day"]}
                    for l in view.get("leading") or []],
        "can_take": [c["name"] for c in view.get("can_take") or []],
    }


def combine(units: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]],
            hours_per_day: float = 8.5) -> Dict[str, Any]:
    """All the units together. ``units`` is (summary, check-ins view) pairs."""
    units = sorted(units, key=lambda pair: pair[0]["name"].lower())
    seen: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    leading: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for summary, view in units:
        for person in view.get("people") or []:
            seen[person["name"]].append({
                "unit": summary["name"], "team": person.get("team_name") or "",
                "free_week": person["free_week"], "signal": person["signal"]["key"],
                "signal_label": person["signal"]["label"]})
        for lead in summary["leading"]:
            leading[lead["name"]].append({"unit": summary["name"], **lead})
    several = [{"name": name, "units": where,
                "free_week": round(sum(w["free_week"] for w in where), 1)}
               for name, where in sorted(seen.items()) if len(where) > 1]
    # Leading people in more than one unit adds up: the same person's day is
    # being kept for each unit's team at once.
    leaders = []
    for name, where in sorted(leading.items()):
        total = round(sum(w["hours_a_day"] for w in where), 2)
        leaders.append({"name": name, "units": where, "hours_a_day": total,
                        "share": round(total / hours_per_day, 3) if hours_per_day else None,
                        "too_much": total > hours_per_day / 2})
    summaries = [s for s, _ in units]
    return {
        "units": summaries,
        "people_in_several": several,
        "leaders": leaders,
        "totals": {
            "units": len(summaries),
            "people": len(seen),
            "teams": sum(len(s["teams"]) for s in summaries),
            "free_week": round(sum(s["free_week"] for s in summaries), 1),
            "rest": sum(s["rest"] for s in summaries),
            "urgent": sum(s["urgent"] for s in summaries),
        },
    }
