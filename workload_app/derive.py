"""A unit set up from its timesheets, with no workbook to start from.

The export says far more than the hours. Every row carries who booked it, the
job and the phase it went to, what that phase is called, the job's status and
the booker's grade. Put a month or a decade of those side by side and most of
what used to be typed into the workbook is already there:

=====================  ===================================================
The team               everyone who booked, by ``FullName``
A person's grade       their latest ``Grade``
The project register   every ``1-Projects`` job number
Project dates          the first and last day anyone booked to it
Project status         the latest ``JobStatus``, and Finalized once nobody
                       has booked to it for :data:`DORMANT_AFTER_DAYS`
Deliverables           one per phase booked, named by its
                       ``DeliverableDescription``
Phase weights          each phase's share of the job's hours
The engineer split     each person's share of the phase's hours
Deliverable type       read from the phase's name (Concept, Tender, ...)
Actual start / finish  the first and last booking to the phase
=====================  ===================================================

Three things are not in any timesheet and so are estimates until somebody
says otherwise, which is what :data:`TO_CONFIRM` marks on the project:

- **the project's name** -- the export has no job-name column, so a project is
  named by its number;
- **the budget** -- the export's Budget column is empty, so the budget starts
  as the effort already spent, rounded up;
- **progress** -- a phase somebody has booked to is at least *started*, and a
  finished project is complete; anything in between is a step only the
  person running it knows.

Nothing here overwrites what is already in the register. A job number that is
already a project is left exactly as it is, so whatever was corrected by hand
stays corrected, and running this again after next month's import only adds
the projects that are new.
"""

from __future__ import annotations

import datetime as _dt
import math
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


#: The job type of real project work. Proposals, leave, idle time and the rest
#: are charge codes, not projects.
PROJECT_JOB_TYPE_PREFIX = "1-"

#: A job nobody has booked to for this long is finished, whatever its status
#: said the last time somebody did. The status on a row is the status on the
#: day it was booked, so an old row says "Active" for ever.
DORMANT_AFTER_DAYS = 180

#: Written into a derived project's notes, and how the Projects tab knows which
#: ones still want a person to look at them.
TO_CONFIRM = "Set up from timesheets: confirm the name, budget and progress."

#: Grades in the export, mapped onto the establishment's own.
_GRADE_RULES: Sequence[Tuple[str, str]] = (
    (r"draft|\bcad\b", "drafter"),
    (r"bim|model+er", "bim"),
    (r"lead|principal|head|manager|director|senior|^p[3-9]\b", "senior"),
    (r"junior|graduate|trainee|assistant", "junior"),
    (r"^p[12]\b|engineer", "engineer"),
    (r"professional|junior|graduate|trainee|assistant|^p0\b", "junior"),
)

#: A phase's type, read from what it is called. First match wins, so the
#: specific comes before the general.
_TYPE_RULES: Sequence[Tuple[str, str]] = (
    (r"tender|boq|bill of quantit|specification", "TD"),
    (r"feasib|master ?plan|study|studies", "FS"),
    (r"review|check|audit|comments?\b", "DR"),
    (r"supervis|site|construction|rfi|query", "CS"),
    (r"analys|mooring|collision|dynamic|geotech|numerical|fem\b", "SA"),
    (r"concept|prelim|feed|schematic|stage ?[23]a?\b|design development|option",
     "CD"),
    (r"detail|final design|ifc|stage ?4", "DD"),
)
DEFAULT_TYPE = "DD"

_STATUS_RULES: Sequence[Tuple[str, str]] = (
    (r"hold|suspend", "On Hold"),
    (r"cancel", "Cancelled"),
    (r"clos|complet|final|finish", "Finalized"),
    (r"not ?started", "Not Started"),
    (r"proposal|bid", "Proposal"),
)


def _match(rules: Sequence[Tuple[str, str]], text: str) -> Optional[str]:
    lowered = (text or "").strip().lower()
    for pattern, value in rules:
        if re.search(pattern, lowered):
            return value
    return None


def grade_for(title: str) -> Optional[str]:
    """The establishment's grade for an export's ``Grade``, if it means one."""
    return _match(_GRADE_RULES, title)


def type_for(description: str, known: Iterable[str]) -> str:
    """A deliverable's type code from its name, among the types that exist."""
    known = set(known)
    guess = _match(_TYPE_RULES, description)
    if guess in known:
        return guess
    if DEFAULT_TYPE in known or not known:
        return DEFAULT_TYPE
    return sorted(known)[0]


def status_for(job_status: str, last_day: Optional[_dt.date],
               newest_day: Optional[_dt.date]) -> str:
    status = _match(_STATUS_RULES, job_status) or "Active"
    dormant = (last_day is not None and newest_day is not None
               and (newest_day - last_day).days > DORMANT_AFTER_DAYS)
    if dormant and status in {"Active", "Not Started"}:
        return "Finalized"
    return status


def is_project_work(job_type: str) -> bool:
    return str(job_type or "").strip().startswith(PROJECT_JOB_TYPE_PREFIX)


# --------------------------------------------------------------------------
# people
# --------------------------------------------------------------------------

def short_names(full_names: Iterable[str], taken: Iterable[str]) -> Dict[str, str]:
    """A short name for each person: their first name, unless it is taken.

    The short name heads their sheet and their column of every split, so it
    has to be unique and it has to fit (25 characters, none of ``[]:*?/\\``).
    """
    used = {name.lower() for name in taken}
    firsts = defaultdict(int)
    clean = {}
    for full in full_names:
        tidy = re.sub(r"[\[\]:*?/\\]", "", " ".join(str(full).split()))
        clean[full] = tidy
        firsts[(tidy.split() or [tidy])[0].lower()] += 1

    out: Dict[str, str] = {}
    for full, tidy in clean.items():
        words = tidy.split() or [tidy or "Person"]
        candidates = [words[0]] if firsts[words[0].lower()] == 1 else []
        if len(words) > 1:
            candidates.append(f"{words[0]} {words[-1][0]}")
        candidates.append(tidy[:25])
        name = next((c for c in candidates if c.lower() not in used), None)
        suffix = 2
        while name is None or name.lower() in used:
            name = f"{tidy[:21]} {suffix}"
            suffix += 1
        used.add(name.lower())
        out[full] = name[:25]
    return out


def latest_by_person(rows: Iterable[Dict[str, Any]], field: str) -> Dict[str, str]:
    """Each person's most recent non-blank value of ``field``."""
    best: Dict[str, Tuple[_dt.date, str]] = {}
    for row in rows:
        value = row.get(field) or ""
        if not value:
            continue
        day = row.get("date") or _dt.date.min
        person = row["engineer"]
        if person not in best or day >= best[person][0]:
            best[person] = (day, value)
    return {person: value for person, (_day, value) in best.items()}


# --------------------------------------------------------------------------
# the register
# --------------------------------------------------------------------------

def _round_weights(hours: Sequence[float]) -> List[float]:
    """Shares of a total, to four places, that add to exactly 1."""
    total = sum(hours)
    if total <= 0:
        even = [round(1.0 / len(hours), 4)] * len(hours)
        even[-1] = round(1.0 - sum(even[:-1]), 4)
        return even
    shares = [round(h / total, 4) for h in hours]
    biggest = max(range(len(shares)), key=lambda i: shares[i])
    shares[biggest] = round(shares[biggest] + 1.0 - sum(shares), 4)
    return shares


def _split(hours_by_person: Dict[str, float], engineers: Sequence[str]
           ) -> Dict[str, Optional[float]]:
    """The engineer split, among the people the workbook has a column for."""
    held = {name: hours_by_person.get(name, 0.0) for name in engineers}
    held = {name: h for name, h in held.items() if h > 0}
    if not held:
        return {}
    names = list(held)
    return dict(zip(names, _round_weights([held[n] for n in names])))


def plan_projects(rows: Sequence[Dict[str, Any]], *,
                  existing: Iterable[str],
                  engineers: Sequence[str],
                  credit_steps: Dict[str, List[Dict[str, Any]]],
                  hours_per_mm: float) -> List[Dict[str, Any]]:
    """Every project the timesheets imply that the register does not have.

    Most recently worked first, so if the register runs out of rows it is the
    oldest history that waits rather than this month's work.
    """
    have = {str(n).strip() for n in existing}
    newest = max((r["date"] for r in rows if r.get("date")), default=None)

    jobs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        number = str(row.get("job_number") or "").strip()
        if number and number not in have and is_project_work(row.get("job_type")):
            jobs[number].append(row)

    plans: List[Dict[str, Any]] = []
    for number, booked in jobs.items():
        days = [r["date"] for r in booked if r.get("date")]
        first, last = (min(days), max(days)) if days else (None, None)
        latest = max(booked, key=lambda r: r.get("date") or _dt.date.min)
        status = status_for(latest.get("job_status") or "", last, newest)
        hours = sum(r.get("hours") or 0.0 for r in booked)
        spent_mm = hours / hours_per_mm if hours_per_mm else 0.0

        phases: Dict[Optional[int], List[Dict[str, Any]]] = defaultdict(list)
        for row in booked:
            phases[row.get("phase")].append(row)
        order = sorted(phases, key=lambda p: (p is None, p if p is not None else 0))
        weights = _round_weights(
            [sum(r.get("hours") or 0.0 for r in phases[p]) for p in order])

        deliverables = []
        used_names = set()
        for phase, weight in zip(order, weights):
            in_phase = phases[phase]
            named: Dict[str, float] = defaultdict(float)
            for row in in_phase:
                named[row.get("deliverable") or ""] += row.get("hours") or 0.0
            name = max(named, key=named.get) if named else ""
            name = name or (f"Phase {phase}" if phase is not None else "General")
            if name.lower() in used_names:
                name = f"{name} (phase {phase})"
            used_names.add(name.lower())
            type_code = type_for(name, credit_steps)
            steps = sorted(s["step_no"] for s in credit_steps.get(type_code, []))
            # Somebody booking to a phase is evidence it has started; a
            # finished project is evidence it is done. Nothing in a timesheet
            # says anything about the steps in between.
            step = (steps[-1] if status == "Finalized" else steps[0]) if steps else None
            by_person: Dict[str, float] = defaultdict(float)
            for row in in_phase:
                by_person[row["engineer"]] += row.get("hours") or 0.0
            phase_days = [r["date"] for r in in_phase if r.get("date")]
            deliverables.append({
                "name": name[:200],
                "type_code": type_code,
                "phase_weight": weight,
                "step_no": step,
                "shares": _split(by_person, engineers),
                "ts_phase": phase,
                "actual_start": min(phase_days) if phase_days else None,
                "actual_finish": (max(phase_days) if phase_days
                                  and status == "Finalized" else None),
            })

        plans.append({
            "project": {
                "number": number,
                "name": number,
                # Never zero: the register refuses a project with no budget.
                "budget_mm": max(0.1, math.ceil(spent_mm * 10) / 10),
                "start": first.replace(day=1) if first else None,
                "end": _month_end(last) if last else None,
                "status": status,
                "notes": TO_CONFIRM,
            },
            "deliverables": deliverables,
            "hours": round(hours, 2),
            "last_day": last,
        })

    plans.extend(_proposal_plans(rows, have, newest, credit_steps, hours_per_mm))
    plans.sort(key=lambda p: (p["last_day"] or _dt.date.min, p["hours"]),
               reverse=True)
    return plans


#: Proposal effort is no job's, so the register carries it as one project a
#: year per kind -- "Proposals 26", "Chargeable Proposals 26" -- which is what
#: the figures match it by. Only the recent years: older bids are history that
#: would take register rows from real work.
PROPOSAL_YEARS = 3
PROPOSAL_KINDS = (
    ("2-Proposals", "Chargeable Proposals", "Chargeable proposals of"),
    ("3-Proposals", "Proposals", "Proposals of"),
)


def _proposal_key(number: str) -> Optional[Tuple[bool, int]]:
    match = re.search(r"(\d{2})\s*$", number)
    if "proposal" not in number.lower() or not match:
        return None
    return ("charg" in number.lower(), 2000 + int(match.group(1)))


def _proposal_plans(rows, have, newest, credit_steps, hours_per_mm):
    taken = {_proposal_key(n) for n in have} - {None}
    if newest is None:
        return []
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        day = row.get("date")
        job_type = str(row.get("job_type") or "")
        if not day or day.year <= newest.year - PROPOSAL_YEARS:
            continue
        for prefix, _number, _name in PROPOSAL_KINDS:
            if job_type.startswith(prefix):
                buckets[(prefix, day.year)].append(row)
    steps = sorted(s["step_no"] for s in credit_steps.get("PP", []))
    plans = []
    for (prefix, year), booked in buckets.items():
        number_stem, name_stem = next((n, m) for p, n, m in PROPOSAL_KINDS
                                      if p == prefix)
        number = f"{number_stem} {year % 100:02d}"
        if (prefix.startswith("2"), year) in taken or "PP" not in credit_steps:
            continue
        finished = year < newest.year
        hours = sum(r.get("hours") or 0.0 for r in booked)
        by_person: Dict[str, float] = defaultdict(float)
        for row in booked:
            by_person[row["engineer"]] += row.get("hours") or 0.0
        days = [r["date"] for r in booked]
        plans.append({
            "project": {
                "number": number,
                "name": f"{name_stem} {year}",
                "budget_mm": max(0.1, math.ceil(hours / hours_per_mm * 10) / 10)
                             if hours_per_mm else 0.1,
                "start": _dt.date(year, 1, 1),
                "end": _dt.date(year, 12, 31),
                "status": "Finalized" if finished else "Active",
                "notes": TO_CONFIRM,
            },
            "deliverables": [{
                "name": "Proposals",
                "type_code": "PP",
                "phase_weight": 1.0,
                "step_no": (steps[-1] if finished else steps[0]) if steps else None,
                "shares": dict(by_person),
                "ts_phase": None,
                "actual_start": min(days),
                "actual_finish": max(days) if finished else None,
            }],
            "hours": round(hours, 2),
            "last_day": max(days),
        })
    return plans


def _month_end(day: _dt.date) -> _dt.date:
    following = (day.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
    return following - _dt.timedelta(days=1)


def needs_confirming(notes: str) -> bool:
    return TO_CONFIRM in (notes or "")


def unit_name(rows: Iterable[Dict[str, Any]]) -> str:
    """The unit the exports belong to, as the export spells it, tidied."""
    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        if row.get("unit"):
            counts[row["unit"]] += 1
    if not counts:
        return ""
    name = max(counts, key=counts.get)
    return name.title() if name.isupper() else name


def describe(plans: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What a plan will add, for a person to read before it does."""
    return [{
        "number": p["project"]["number"],
        "status": p["project"]["status"],
        "budget_mm": p["project"]["budget_mm"],
        "start": p["project"]["start"].isoformat() if p["project"]["start"] else None,
        "end": p["project"]["end"].isoformat() if p["project"]["end"] else None,
        "hours": p["hours"],
        "deliverables": [d["name"] for d in p["deliverables"]],
    } for p in plans]


__all__ = [
    "DORMANT_AFTER_DAYS", "TO_CONFIRM", "grade_for", "type_for", "status_for",
    "short_names", "latest_by_person", "plan_projects", "needs_confirming",
    "unit_name", "describe", "is_project_work",
]
