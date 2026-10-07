"""Drawings: the measure the work is counted in.

A deliverable is so many drawings, and nobody's timesheet says how many, so
that one number is typed in -- once per deliverable, and nothing else.  Every
other drawing figure is worked out from it:

* **done** is the count times how far along the deliverable is, by the same
  rules of credit that already decide its progress, so a deliverable at IDC
  has 40% of its drawings to show and an approved one all of them;
* **left** is the rest;
* a person's drawings are each deliverable's times their share of it, the
  same split every other per-person figure uses;
* **hours a drawing** is the hours booked to the projects that have drawings,
  over the drawings done on them -- the unit's own rate, read from its own
  history rather than assumed.

Nothing here is written to the workbook.  The counts live in the unit's
database beside the timesheet rows.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import people as people_module

#: The most drawings one deliverable can be said to have, which is only there
#: to catch a typo -- a stray extra zero -- rather than to set a policy.
MAX_PER_DELIVERABLE = 100_000


#: "This form did not mention drawings", as opposed to "no drawings".
KEEP = object()


class DrawingsError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.errors = [message]


def clean_count(value: Any) -> Optional[int]:
    """A drawing count from a form: blank is "not known", not zero."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except ValueError:
        raise DrawingsError(f"{value!r} is not a number of drawings.")
    if number < 0 or number != int(number):
        raise DrawingsError("A number of drawings is a whole number, 0 or more.")
    if number > MAX_PER_DELIVERABLE:
        raise DrawingsError(
            f"{int(number):,} drawings on one deliverable looks like a typo.")
    return int(number)


def counts(store, deliverables: Iterable[Any]) -> Dict[int, int]:
    """Each deliverable row's drawing count, where one has been given.

    A count stays with the project it was typed against: a row that has since
    been cleared and reused by another project does not inherit it.
    """
    stored = store.drawings()
    out: Dict[int, int] = {}
    for deliverable in deliverables:
        row = getattr(deliverable, "row", None)
        if row is None and isinstance(deliverable, Mapping):
            row = deliverable.get("row")
        number = getattr(deliverable, "project_number", None)
        if number is None and isinstance(deliverable, Mapping):
            number = deliverable.get("project_number")
        hit = stored.get(row)
        if hit and hit["project_number"] == number:
            out[row] = hit["count"]
    return out


def save_counts(store, deliverables: Iterable[Any],
                values: Mapping[Any, Any]) -> Dict[int, Optional[int]]:
    """Set several counts at once, ``{row: count}``; blank clears one."""
    known = {d.row: d.project_number for d in deliverables}
    cleaned: Dict[int, Optional[int]] = {}
    for raw_row, value in values.items():
        try:
            row = int(raw_row)
        except (TypeError, ValueError):
            raise DrawingsError(f"{raw_row!r} is not a deliverable.")
        if row not in known:
            raise DrawingsError(f"There is no deliverable on row {row}.")
        cleaned[row] = clean_count(value)
    for row, count in cleaned.items():
        store.set_drawings(row, known[row], count)
    return cleaned


def _r(value: float, digits: int = 1) -> float:
    return round(value + 0.0, digits)


def summary(deliverable_rows: Sequence[Dict[str, Any]],
            drawing_counts: Mapping[int, int],
            project_rows: Sequence[Dict[str, Any]],
            roster: Sequence[Dict[str, Any]],
            measured: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Every drawing figure the app shows, worked out once.

    ``deliverable_rows`` and ``project_rows`` are the metrics the rest of the
    app already computes, so progress here is the same progress as everywhere.
    """
    people = {p["name"]: p for p in roster}
    projects = {p["number"]: p for p in project_rows}

    per_deliverable = []
    per_project: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"total": 0.0, "done": 0.0, "left": 0.0, "deliverables": 0})
    per_person: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"done": 0.0, "left": 0.0})
    for item in deliverable_rows:
        count = drawing_counts.get(item["row"])
        if count is None:
            continue
        credit = min(1.0, max(0.0, item.get("credit") or 0.0))
        done = count * credit
        left = count - done
        per_deliverable.append({
            "row": item["row"],
            "project_number": item["project_number"],
            "name": item["name"],
            "drawings": count,
            "progress": credit,
            "done": _r(done),
            "left": _r(left),
        })
        totals = per_project[item["project_number"]]
        totals["total"] += count
        totals["done"] += done
        totals["left"] += left
        totals["deliverables"] += 1
        for name, share in (item.get("shares") or {}).items():
            if share:
                per_person[name]["done"] += done * share
                per_person[name]["left"] += left * share

    # The rate: hours on the projects that have drawings, over the drawings
    # done on them, all hours and the drawing office's alone.  Only projects
    # whose progress somebody has confirmed count: on one the timesheets set
    # up, progress is a placeholder, and hours over a placeholder is not a
    # rate anybody should plan people from.
    measured = set(measured) if measured is not None else None
    hours_all = hours_drafting = done_all = 0.0
    project_out = []
    for number, totals in per_project.items():
        project = projects.get(number) or {}
        hours = float(project.get("actual_hours") or 0.0)
        drafting = sum(
            float(value or 0.0)
            for name, value in (project.get("hours_by_engineer") or {}).items()
            if people_module.role_of((people.get(name) or {}).get("grade"))
            == people_module.ROLE_DRAFTING)
        if totals["done"] > 0 and (measured is None or number in measured):
            hours_all += hours
            hours_drafting += drafting
            done_all += totals["done"]
        project_out.append({
            "number": number,
            "name": project.get("name") or number,
            "status": project.get("status") or "",
            "total": int(totals["total"]),
            "done": _r(totals["done"]),
            "left": _r(totals["left"]),
            "deliverables": int(totals["deliverables"]),
            "hours": _r(hours),
            "hours_per_drawing": _r(hours / totals["done"], 2)
            if totals["done"] >= 1 and (measured is None or number in measured)
            else None,
        })
    project_out.sort(key=lambda p: -p["left"])

    person_out = []
    for name, totals in per_person.items():
        person = people.get(name) or {}
        person_out.append({
            "name": name,
            "team_id": person.get("team_id"),
            "team_name": person.get("team_name", ""),
            "grade": person.get("grade", people_module.DEFAULT_GRADE),
            "done": _r(totals["done"]),
            "left": _r(totals["left"]),
        })
    person_out.sort(key=lambda p: -p["done"])

    team_totals: Dict[Any, Dict[str, Any]] = {}
    for person in person_out:
        key = person["team_id"] or people_module.UNASSIGNED
        entry = team_totals.setdefault(key, {
            "id": key, "name": person["team_name"] or "Not in a team",
            "done": 0.0, "left": 0.0})
        entry["done"] += person["done"]
        entry["left"] += person["left"]
    teams_out = [{**t, "done": _r(t["done"]), "left": _r(t["left"])}
                 for t in sorted(team_totals.values(), key=lambda t: t["name"])]

    total = sum(p["total"] for p in project_out)
    done = sum(per_project[n]["done"] for n in per_project)
    return {
        "known": bool(per_deliverable),
        "total": int(total),
        "done": _r(done),
        "left": _r(total - done),
        "progress": round(done / total, 4) if total else None,
        "hours_per_drawing": _r(hours_all / done_all, 2) if done_all >= 1 else None,
        "drafting_hours_per_drawing": _r(hours_drafting / done_all, 2)
        if done_all >= 1 and hours_drafting else None,
        "deliverables_with_drawings": len(per_deliverable),
        "deliverables_without": sum(1 for d in deliverable_rows
                                    if d["row"] not in drawing_counts),
        "deliverables": per_deliverable,
        "projects": project_out,
        "people": person_out,
        "teams": teams_out,
    }


def left_by_project(data: Dict[str, Any]) -> Dict[str, float]:
    return {p["number"]: p["left"] for p in data["projects"]}
