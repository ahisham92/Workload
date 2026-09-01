"""Workload and efficiency figures, computed from the raw inputs.

The workbook caches the result of every formula, but those cached values go
stale the moment the app writes a change and stay stale until Excel next opens
the file.  Reading them back would show the user yesterday's answer, so this
module recomputes the headline numbers from the timesheet rows and the two
registers instead, following the same definitions the workbook uses:

* actual MM   -- timesheet hours for the job number, divided by hours per MM
* progress    -- sum of (phase weight x rules-of-credit credit) over total weight
* earned MM   -- budget MM x progress
* CPI         -- earned MM / actual MM
* utilisation -- hours booked / (available hours x the year's availability)
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config as cfg
from .workbook import Deliverable, WorkloadWorkbook, as_text
from .xlsx_io import from_serial

#: Job Type values the Phasing sheet uses to pick up proposal effort.
PROPOSAL_JOB_TYPES = {
    "chargeable": cfg.PROPOSAL_JOB_TYPES[0],
    "regular": cfg.PROPOSAL_JOB_TYPES[1],
}


def _round(value: Optional[float], places: int = 2) -> Optional[float]:
    return None if value is None else round(value, places)


class TimesheetIndex:
    """Every timesheet row from the three TS sheets, indexed for lookups."""

    def __init__(self, wb: WorkloadWorkbook):
        self.rows: List[Dict[str, Any]] = []
        for engineer in wb.ts_sheets():
            for raw in wb.timesheet_rows(engineer, ["A", "B", "C", "J", "K", "L", "M", "P"]):
                date = raw.get("L")
                hours = raw.get("P")
                phase = raw.get("M")
                self.rows.append({
                    "engineer": engineer,
                    "job_type": as_text(raw.get("A")),
                    "job_number": as_text(raw.get("B")).strip(),
                    "full_name": as_text(raw.get("C")),
                    "regular_hours": float(raw.get("J") or 0.0),
                    "overtime_hours": float(raw.get("K") or 0.0),
                    "date": from_serial(float(date)) if isinstance(date, (int, float)) and date > 0 else None,
                    "phase": int(phase) if isinstance(phase, (int, float)) else None,
                    "hours": float(hours) if isinstance(hours, (int, float)) else 0.0,
                })

        self.by_job: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in self.rows:
            self.by_job[row["job_number"]].append(row)

    def hours_for_job(self, job_number: str, *, phase: Optional[int] = None,
                      engineer: Optional[str] = None) -> float:
        total = 0.0
        for row in self.by_job.get(job_number.strip(), ()):
            if phase is not None and row["phase"] != phase:
                continue
            if engineer is not None and row["engineer"] != engineer:
                continue
            total += row["hours"]
        return total

    def dates_for_job(self, job_number: str, *, phase: Optional[int] = None
                      ) -> Tuple[Optional[_dt.date], Optional[_dt.date]]:
        dates = [
            row["date"] for row in self.by_job.get(job_number.strip(), ())
            if row["date"] and (phase is None or row["phase"] == phase)
        ]
        return (min(dates), max(dates)) if dates else (None, None)

    def hours_for_proposal(self, code: str, *, engineer: Optional[str] = None) -> float:
        """Proposal effort, matched the way the Phasing sheet matches it."""
        job_type = PROPOSAL_JOB_TYPES[
            "chargeable" if "chargable" in code.lower() or "chargeable" in code.lower()
            else "regular"
        ]
        year = _year_suffix(code)
        total = 0.0
        for row in self.rows:
            if row["job_type"] != job_type:
                continue
            if engineer is not None and row["engineer"] != engineer:
                continue
            if year is not None and (row["date"] is None or row["date"].year != year):
                continue
            total += row["hours"]
        return total


def _year_suffix(code: str) -> Optional[int]:
    m = re.search(r"(\d{2})\s*$", code.strip())
    return 2000 + int(m.group(1)) if m else None


def is_proposal_code(code: str) -> bool:
    return "proposal" in code.lower()


# --------------------------------------------------------------------------
# project level
# --------------------------------------------------------------------------

def project_progress(deliverables: Iterable[Deliverable],
                     credit_lookup, fallback: Optional[float]) -> Tuple[Optional[float], float, float]:
    """Return ``(progress, total weight, earned weight)`` for one project."""
    total_weight = 0.0
    earned_weight = 0.0
    seen = False
    for deliverable in deliverables:
        seen = True
        weight = deliverable.phase_weight or 0.0
        total_weight += weight
        credit = credit_lookup(deliverable.type_code, deliverable.step_no)
        if credit is not None:
            earned_weight += weight * credit
    if not seen or total_weight == 0:
        return fallback, total_weight, earned_weight
    return earned_weight / total_weight, total_weight, earned_weight


def engineer_shares(deliverables: List[Deliverable], credit_lookup,
                    names: Sequence[str]) -> Dict[str, Optional[float]]:
    """The person split the workbook derives for a project.

    Weighted by earned progress where there is any, and by scope weight before
    the project has earned anything -- exactly what Deliverables W:Y do.
    """
    earned_total = 0.0
    weight_total = 0.0
    earned_parts: Dict[str, float] = {name: 0.0 for name in names}
    weight_parts: Dict[str, float] = {name: 0.0 for name in names}
    for deliverable in deliverables:
        weight = deliverable.phase_weight or 0.0
        credit = credit_lookup(deliverable.type_code, deliverable.step_no) or 0.0
        earned = weight * credit
        earned_total += earned
        weight_total += weight
        for name in names:
            share = deliverable.shares.get(name) or 0.0
            earned_parts[name] += earned * share
            weight_parts[name] += weight * share
    if earned_total > 0:
        return {name: earned_parts[name] / earned_total for name in names}
    if weight_total > 0:
        return {name: weight_parts[name] / weight_total for name in names}
    return {name: None for name in names}


def project_rows(wb: WorkloadWorkbook, index: TimesheetIndex) -> List[Dict[str, Any]]:
    """One row per project: effort spent, value earned and how efficient it was."""
    hours_per_mm = wb.hours_per_man_month()
    steps = {(s.type_code, s.step_no): s.credit for s in wb.credit_steps()}

    def credit_lookup(type_code: str, step_no: Optional[int]) -> Optional[float]:
        if not type_code or step_no is None:
            return None
        return steps.get((type_code, step_no))

    names = wb.engineer_names()
    by_project: Dict[str, List[Deliverable]] = defaultdict(list)
    for deliverable in wb.deliverables():
        by_project[deliverable.project_number].append(deliverable)

    out: List[Dict[str, Any]] = []
    for project in wb.projects():
        attached = by_project.get(project.number, [])
        progress, total_weight, _earned = project_progress(
            attached, credit_lookup, project.manual_percent
        )
        if is_proposal_code(project.number):
            actual_hours = index.hours_for_proposal(project.number)
            per_engineer = {
                name: index.hours_for_proposal(project.number, engineer=name)
                for name in wb.ts_sheets()
            }
            first = last = None
        else:
            actual_hours = index.hours_for_job(project.number)
            per_engineer = {
                name: index.hours_for_job(project.number, engineer=name)
                for name in wb.ts_sheets()
            }
            first, last = index.dates_for_job(project.number)

        actual_mm = actual_hours / hours_per_mm if hours_per_mm else 0.0
        budget = project.budget_mm or 0.0
        earned_mm = budget * progress if progress is not None else None

        if project.cac_override is not None:
            cost_at_completion = project.cac_override
        elif actual_mm and progress:
            cost_at_completion = actual_mm / progress
        else:
            cost_at_completion = budget
        cpi = (earned_mm / actual_mm) if (earned_mm is not None and actual_mm) else None

        shares = engineer_shares(attached, credit_lookup, names)
        if all(v is None for v in shares.values()):
            shares = dict(project.manual_shares)

        out.append({
            "row": project.row,
            "number": project.number,
            "name": project.name,
            "status": project.status,
            "in_scope": project.status in cfg.PROJECT_IN_SCOPE_STATUSES,
            "budget_mm": budget,
            "progress": _round(progress, 4),
            "weight_total": _round(total_weight, 4),
            "weight_ok": (not attached) or abs(total_weight - 1.0) <= 1e-4,
            "deliverables": len(attached),
            "actual_hours": _round(actual_hours),
            "actual_mm": _round(actual_mm, 3),
            "earned_mm": _round(earned_mm, 3),
            "cost_at_completion_mm": _round(cost_at_completion, 3),
            "remaining_mm": _round(max(0.0, cost_at_completion - actual_mm), 3),
            "profit_mm": _round(budget - cost_at_completion, 3),
            "cpi": _round(cpi, 3),
            "hours_by_engineer": {k: _round(v) for k, v in per_engineer.items()},
            "share_by_engineer": {k: _round(v, 4) for k, v in shares.items()},
            "first_charge": first.isoformat() if first else None,
            "last_charge": last.isoformat() if last else None,
            "start": project.start.isoformat() if project.start else None,
            "end": project.end.isoformat() if project.end else None,
        })
    return out


def deliverable_rows(wb: WorkloadWorkbook, index: TimesheetIndex) -> List[Dict[str, Any]]:
    """One row per deliverable, with its credit and the hours actually booked."""
    hours_per_mm = wb.hours_per_man_month()
    steps = {(s.type_code, s.step_no): s for s in wb.credit_steps()}
    weights = wb.weight_by_project()
    names = {p.number: p.name for p in wb.projects()}

    # Several deliverables can share one TS phase (the berth-by-berth rows);
    # the workbook splits those hours evenly, so count the sharers first.
    sharers: Dict[Tuple[str, Optional[int]], int] = defaultdict(int)
    for deliverable in wb.deliverables():
        sharers[(deliverable.project_number, deliverable.ts_phase)] += 1

    out: List[Dict[str, Any]] = []
    for deliverable in wb.deliverables():
        step = steps.get((deliverable.type_code, deliverable.step_no))
        credit = step.credit if step else None
        weight = deliverable.phase_weight or 0.0
        if deliverable.ts_phase is None:
            hours = 0.0
            first = last = None
        else:
            share_count = max(1, sharers[(deliverable.project_number, deliverable.ts_phase)])
            hours = index.hours_for_job(
                deliverable.project_number, phase=deliverable.ts_phase) / share_count
            first, last = index.dates_for_job(
                deliverable.project_number, phase=deliverable.ts_phase)
        project_weight = weights.get(deliverable.project_number, 0.0)
        out.append({
            "row": deliverable.row,
            "project_number": deliverable.project_number,
            "project_name": names.get(deliverable.project_number, ""),
            "name": deliverable.name,
            "type_code": deliverable.type_code,
            "phase_weight": weight,
            "weight_share_of_project": _round(
                weight / project_weight if project_weight else None, 4),
            "step_no": deliverable.step_no,
            "step_name": step.step_name if step else "",
            "credit": credit,
            "weighted_progress": _round(weight * credit if credit is not None else None, 4),
            "status_date": deliverable.status_date.isoformat() if deliverable.status_date else None,
            "ts_phase": deliverable.ts_phase,
            "actual_hours": _round(hours),
            "actual_mm": _round(hours / hours_per_mm if hours_per_mm else 0.0, 3),
            "first_charge": first.isoformat() if first else None,
            "last_charge": last.isoformat() if last else None,
            "shares": dict(deliverable.shares),
            "split_ok": abs(
                sum(v for v in deliverable.shares.values() if v) - 1.0) <= 1e-4,
        })
    return out


# --------------------------------------------------------------------------
# people
# --------------------------------------------------------------------------

def engineer_workload(wb: WorkloadWorkbook, index: TimesheetIndex,
                      year: Optional[int] = None) -> Dict[str, Any]:
    """Monthly hours and utilisation per engineer."""
    engineers = {e.short_name: e for e in wb.engineers()}
    non_project = wb.non_project_codes()
    project_numbers = {p.number for p in wb.projects()}

    months: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    totals: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for row in index.rows:
        if row["date"] is None:
            continue
        if year is not None and row["date"].year != year:
            continue
        month = row["date"].strftime("%Y-%m")
        person = row["engineer"]
        code = row["job_number"]
        if code in non_project:
            bucket = "absence"
        elif row["job_type"].startswith(("2-Proposals", "3-Proposals")):
            bucket = "proposals"
        elif code in project_numbers:
            bucket = "projects"
        else:
            bucket = "other"
        months[person][month][bucket] += row["hours"]
        months[person][month]["total"] += row["hours"]
        months[person][month]["overtime"] += row["overtime_hours"]
        totals[person][bucket] += row["hours"]
        totals[person]["total"] += row["hours"]
        totals[person]["overtime"] += row["overtime_hours"]

    out: Dict[str, Any] = {}
    for name, engineer in engineers.items():
        available = engineer.available_hours or 0.0
        by_month = []
        for month in sorted(months.get(name, {})):
            values = months[name][month]
            month_year = int(month[:4])
            factor = engineer.availability.get(month_year, 1.0)
            capacity = available * factor
            by_month.append({
                "month": month,
                "projects": _round(values["projects"]),
                "proposals": _round(values["proposals"]),
                "absence": _round(values["absence"]),
                "other": _round(values["other"]),
                "overtime": _round(values["overtime"]),
                "total": _round(values["total"]),
                "capacity": _round(capacity),
                "utilisation": _round(
                    values["total"] / capacity if capacity else None, 3),
            })
        summary = totals.get(name, {})
        total_hours = summary.get("total", 0.0)
        # Capacity over the whole period is the sum of the monthly capacities,
        # so a part-time year (Kirolos in 2024) is not counted as a full one.
        capacity = sum(m["capacity"] or 0.0 for m in by_month)
        out[name] = {
            "available_hours_per_month": available,
            "availability": engineer.availability,
            "months": by_month,
            "total_hours": _round(total_hours),
            "project_hours": _round(summary.get("projects", 0.0)),
            "proposal_hours": _round(summary.get("proposals", 0.0)),
            "absence_hours": _round(summary.get("absence", 0.0)),
            "other_hours": _round(summary.get("other", 0.0)),
            "overtime_hours": _round(summary.get("overtime", 0.0)),
            "average_utilisation": _round(
                total_hours / capacity if capacity else None, 3),
        }
    return out


# --------------------------------------------------------------------------
# portfolio
# --------------------------------------------------------------------------

def overview(wb: WorkloadWorkbook, year: Optional[int] = None) -> Dict[str, Any]:
    """Everything the app's front page shows."""
    index = TimesheetIndex(wb)
    projects = project_rows(wb, index)
    hours_per_mm = wb.hours_per_man_month()

    in_scope = [p for p in projects if p["in_scope"]]
    budget = sum(p["budget_mm"] for p in in_scope)
    actual = sum(p["actual_mm"] or 0.0 for p in in_scope)
    earned = sum(p["earned_mm"] or 0.0 for p in in_scope)

    all_actual = sum(p["actual_mm"] or 0.0 for p in projects)
    all_earned = sum(p["earned_mm"] or 0.0 for p in projects)

    workload = engineer_workload(wb, index, year)
    return {
        "year": year,
        "hours_per_man_month": hours_per_mm,
        "plan_year": wb.plan_year(),
        "portfolio": {
            "projects": len(projects),
            "in_scope_projects": len(in_scope),
            "deliverables": len(wb.deliverables()),
            "budget_mm": _round(budget, 2),
            "actual_mm": _round(actual, 2),
            "earned_mm": _round(earned, 2),
            "profit_mm": _round(earned - actual, 2),
            "cpi": _round(earned / actual if actual else None, 3),
            "all_projects_actual_mm": _round(all_actual, 2),
            "all_projects_earned_mm": _round(all_earned, 2),
            "all_projects_cpi": _round(
                all_earned / all_actual if all_actual else None, 3),
        },
        "engineers": workload,
        "data_check": wb.data_check(),
        "issues": wb.register_issues(),
    }


def available_years(wb: WorkloadWorkbook, index: Optional[TimesheetIndex] = None
                    ) -> List[int]:
    index = index or TimesheetIndex(wb)
    return sorted({row["date"].year for row in index.rows if row["date"]})
