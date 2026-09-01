"""The workbook's report sheets, recomputed in the app.

Five sheets are reproduced here -- Dashboard, Engineer KPIs, Team Member,
Scorecard and Management Review -- and they overlap heavily: the same actual MM
appears on all five, the same per-engineer allocation on four.  So everything is
computed **once**, into a :class:`ReportSet`, and each view is a selection from
it rather than its own arithmetic.  Nothing is calculated twice, and no two
views can drift apart.

The definitions are the workbook's own:

* **planned MM** per project per quarter -- the budget spread across the
  project's dates, unless a value is typed into the Phasing override block;
* **actual MM** -- timesheet hours in the quarter, over hours per man-month;
* **earned MM** in a quarter -- the project's total earned value, split across
  quarters in proportion to the effort actually spent in each;
* **capacity to date** -- the team's availability for the year, pro-rated to the
  as-at date;
* **per-engineer figures** -- each project's value multiplied by that engineer's
  share of it;
* **type-weighted** figures -- earned value scaled by the portfolio weight of
  the work's project type, which is what the KPI and scorecard views rank on.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import config as cfg
from .metrics import TimesheetIndex, is_proposal_code, project_rows
from .workbook import WorkloadWorkbook, iso
from .xlsx_io import col_to_index, index_to_col


def _round(value: Optional[float], places: int = 3) -> Optional[float]:
    return None if value is None else round(value, places)


def _safe(numerator: Optional[float], denominator: Optional[float]
          ) -> Optional[float]:
    if not denominator:
        return None
    if numerator is None:
        return None
    return numerator / denominator


# --------------------------------------------------------------------------
# periods
# --------------------------------------------------------------------------

@dataclass
class Quarter:
    """One column of the Phasing grid."""
    column: str
    label: str
    year: Optional[int]
    start: _dt.date
    end: _dt.date
    opening: bool = False

    def overlap_days(self, start: _dt.date, end: _dt.date) -> int:
        first = max(start, self.start)
        last = min(end, self.end)
        return max(0, (last - first).days + 1)

    def elapsed_fraction(self, as_at: _dt.date) -> float:
        """How much of this quarter has already happened."""
        total = (self.end - self.start).days + 1
        if total <= 0:
            return 0.0
        done = (min(as_at, self.end) - self.start).days + 1
        return max(0.0, min(1.0, done / total))


@dataclass
class Period:
    kind: str                      # "all" | "year" | "quarter"
    label: str
    quarters: List[Quarter]
    year: Optional[int] = None
    quarter: Optional[str] = None

    @property
    def start(self) -> Optional[_dt.date]:
        return min((q.start for q in self.quarters), default=None)

    @property
    def end(self) -> Optional[_dt.date]:
        return max((q.end for q in self.quarters), default=None)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "label": self.label, "year": self.year,
            "quarter": self.quarter,
            "from": iso(self.start), "to": iso(self.end),
        }


def read_quarters(wb: WorkloadWorkbook) -> List[Quarter]:
    """The Phasing grid: an opening column, then one column per quarter."""
    raw = wb.raw
    out: List[Quarter] = []
    for index in range(col_to_index(cfg.PHASING_FIRST_COL),
                       col_to_index(cfg.PHASING_LAST_COL) + 1):
        column = index_to_col(index)
        start = raw.get_date(cfg.SHEET_PHASING, f"{column}{cfg.PHASING_START_ROW}")
        end = raw.get_date(cfg.SHEET_PHASING, f"{column}{cfg.PHASING_END_ROW}")
        if start is None or end is None:
            continue
        year = raw.get_number(cfg.SHEET_PHASING, f"{column}{cfg.PHASING_YEAR_ROW}")
        label = raw.get_text(cfg.SHEET_PHASING, f"{column}{cfg.PHASING_QUARTER_ROW}")
        opening = year is None or not label or label.lower() == "opening"
        out.append(Quarter(
            column=column,
            label=label or "Opening",
            year=int(year) if year else None,
            start=start, end=end, opening=opening,
        ))
    return out


def resolve_period(quarters: Sequence[Quarter], kind: str,
                   year: Optional[int] = None,
                   quarter: Optional[str] = None) -> Period:
    """Pick the columns a chosen period covers, the way the Dashboard filter does."""
    if kind == "year" and year is not None:
        chosen = [q for q in quarters if q.year == year]
        return Period("year", f"Full year {year}", chosen, year=year)
    if kind == "quarter" and year is not None and quarter:
        chosen = [q for q in quarters
                  if q.year == year and q.label.upper().startswith(quarter.upper())]
        return Period("quarter", f"{quarter} {year}", chosen, year=year,
                      quarter=quarter)
    return Period("all", "All time, including opening balances", list(quarters))


# --------------------------------------------------------------------------
# the whole report set
# --------------------------------------------------------------------------

@dataclass
class ReportSet:
    """Everything the five report views need, computed once."""

    period: Period
    as_at: _dt.date
    hours_per_mm: float
    engineers: List[str]
    projects: List[Dict[str, Any]] = field(default_factory=list)
    team: Dict[str, Any] = field(default_factory=dict)
    per_engineer: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    by_status: List[Dict[str, Any]] = field(default_factory=list)
    scorecard: Dict[str, Any] = field(default_factory=dict)
    quarterly: List[Dict[str, Any]] = field(default_factory=list)
    delivery_mix: List[Dict[str, Any]] = field(default_factory=list)
    monthly: List[Dict[str, Any]] = field(default_factory=list)
    heroes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period.to_dict(),
            "as_at": iso(self.as_at),
            "hours_per_man_month": self.hours_per_mm,
            "engineers": self.engineers,
            "projects": self.projects,
            "team": self.team,
            "per_engineer": self.per_engineer,
            "by_status": self.by_status,
            "scorecard": self.scorecard,
            "quarterly": self.quarterly,
            "delivery_mix": self.delivery_mix,
            "monthly": self.monthly,
            "heroes": self.heroes,
        }


def build(wb: WorkloadWorkbook, kind: str = "year", year: Optional[int] = None,
          quarter: Optional[str] = None,
          index: Optional[TimesheetIndex] = None) -> ReportSet:
    """Compute every report figure for one period, in a single pass."""
    index = index or TimesheetIndex(wb)
    quarters = read_quarters(wb)
    if year is None and kind != "all":
        year = wb.plan_year()
    period = resolve_period(quarters, kind, year, quarter)
    as_at = wb.raw.get_date(cfg.SHEET_INPUTS, cfg.AS_AT_DATE_CELL) or _dt.date.today()
    hours_per_mm = wb.hours_per_man_month()
    engineers = wb.engineer_names()

    lifetime = {row["number"]: row for row in project_rows(wb, index)}
    type_factors = _type_factors(wb)
    overrides = _planned_overrides(wb, quarters)

    projects = [
        _project_in_period(wb, index, row, period, quarters, overrides,
                           type_factors, hours_per_mm)
        for row in lifetime.values()
    ]

    capacity = _capacity(wb, period, as_at)
    team = _team_totals(projects, capacity, period, as_at)
    per_engineer = _per_engineer(projects, engineers, capacity, wb, index, period)
    report = ReportSet(
        period=period, as_at=as_at, hours_per_mm=hours_per_mm,
        engineers=engineers, projects=projects, team=team,
        per_engineer=per_engineer,
        by_status=_by_status(wb, projects),
        scorecard=_scorecard(per_engineer, engineers, wb.scorecard_factors()),
        quarterly=_quarterly(wb, index, quarters, engineers, hours_per_mm),
        delivery_mix=_delivery_mix(wb, index, hours_per_mm, period),
    )
    report.monthly = _monthly_scores(wb, index, projects, engineers, period,
                                     as_at, hours_per_mm)
    report.heroes = _heroes(report.monthly, report.scorecard, as_at, period)
    return report


# -- per project -----------------------------------------------------------

def _type_factors(wb: WorkloadWorkbook) -> Dict[str, float]:
    """Each project's weighted average project-type factor."""
    weights = {t.code: (t.portfolio_weight if t.portfolio_weight is not None else 1.0)
               for t in wb.project_types()}
    totals: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0])
    for deliverable in wb.deliverables():
        weight = deliverable.phase_weight or 0.0
        factor = weights.get(deliverable.type_code, 1.0)
        entry = totals[deliverable.project_number]
        entry[0] += weight * factor
        entry[1] += weight
    return {
        number: (value / total if total else 1.0)
        for number, (value, total) in totals.items()
    }


def _planned_overrides(wb: WorkloadWorkbook, quarters: Sequence[Quarter]
                       ) -> Dict[Tuple[str, str], float]:
    """Typed-in planned MM, which beats the spread from the project's dates."""
    out: Dict[Tuple[str, str], float] = {}
    raw = wb.raw
    for offset, project in enumerate(wb.projects()):
        row = cfg.PHASING_OVERRIDE_FIRST_ROW + (project.row - cfg.PROJECT_FIRST_ROW)
        for quarter in quarters:
            value = raw.get_number(cfg.SHEET_PHASING, f"{quarter.column}{row}")
            if value is not None:
                out[(project.number, quarter.column)] = value
    return out


def _project_in_period(wb, index, lifetime, period, quarters, overrides,
                       type_factors, hours_per_mm) -> Dict[str, Any]:
    number = lifetime["number"]
    start = _parse(lifetime["start"])
    end = _parse(lifetime["end"])
    budget = lifetime["budget_mm"] or 0.0

    planned = 0.0
    planned_to_date = 0.0
    for quarter in period.quarters:
        value = overrides.get((number, quarter.column))
        if value is None:
            value = _spread(budget, start, end, quarter)
        planned += value
        planned_to_date += value * quarter.elapsed_fraction(_as_at(wb))

    actual_hours = _hours_in(index, number, period)
    actual = actual_hours / hours_per_mm if hours_per_mm else 0.0

    # The workbook splits a project's earned value across quarters in proportion
    # to the effort spent in each, so a period's share follows its effort.
    lifetime_actual = lifetime["actual_mm"] or 0.0
    lifetime_earned = lifetime["earned_mm"] or 0.0
    earned = (actual / lifetime_actual * lifetime_earned) if lifetime_actual else 0.0

    live = bool(start and end and period.start and period.end
                and start <= period.end and end >= period.start)
    return {
        "number": number,
        "name": lifetime["name"],
        "status": lifetime["status"],
        "in_scope": lifetime["in_scope"],
        "live": live or period.kind == "all",
        "budget_mm": budget,
        "progress": lifetime["progress"],
        "planned_mm": _round(planned),
        "planned_to_date_mm": _round(planned_to_date),
        "actual_mm": _round(actual),
        "actual_hours": _round(actual_hours, 2),
        "earned_mm": _round(earned),
        "profit_mm": _round(earned - actual),
        "cpi": _round(_safe(earned, actual)),
        "lifetime_actual_mm": lifetime["actual_mm"],
        "lifetime_earned_mm": lifetime["earned_mm"],
        "cost_at_completion_mm": lifetime["cost_at_completion_mm"],
        "remaining_mm": lifetime["remaining_mm"],
        "lifetime_profit_mm": lifetime["profit_mm"],
        "type_factor": _round(type_factors.get(number, 1.0)),
        "shares": lifetime["share_by_engineer"],
        "start": lifetime["start"],
        "end": lifetime["end"],
    }


def _as_at(wb: WorkloadWorkbook) -> _dt.date:
    return wb.raw.get_date(cfg.SHEET_INPUTS, cfg.AS_AT_DATE_CELL) or _dt.date.today()


def _parse(value: Optional[str]) -> Optional[_dt.date]:
    return _dt.date.fromisoformat(value) if value else None


def _spread(budget: float, start: Optional[_dt.date], end: Optional[_dt.date],
            quarter: Quarter) -> float:
    """A project's budget spread evenly across the days it runs."""
    if not budget or start is None or end is None:
        return 0.0
    duration = (end - start).days + 1
    if duration <= 0:
        return 0.0
    return budget * quarter.overlap_days(start, end) / duration


def _hours_in(index: TimesheetIndex, number: str, period: Period,
              engineer: Optional[str] = None) -> float:
    start, end = period.start, period.end
    if start is None or end is None:
        return 0.0
    if is_proposal_code(number):
        rows = [r for r in index.rows if r["job_type"] in (
            "2-Proposals Chargeable", "3-Proposals Regular")]
        year = None
        import re
        m = re.search(r"(\d{2})\s*$", number.strip())
        if m:
            year = 2000 + int(m.group(1))
        chargeable = "chargable" in number.lower() or "chargeable" in number.lower()
        wanted = "2-Proposals Chargeable" if chargeable else "3-Proposals Regular"
        total = 0.0
        for row in rows:
            if row["job_type"] != wanted:
                continue
            if engineer and row["engineer"] != engineer:
                continue
            date = row["date"]
            if date is None or not (start <= date <= end):
                continue
            if year is not None and date.year != year:
                continue
            total += row["hours"]
        return total
    total = 0.0
    for row in index.by_job.get(number.strip(), ()):  # type: ignore[arg-type]
        if engineer and row["engineer"] != engineer:
            continue
        date = row["date"]
        if date is None or not (start <= date <= end):
            continue
        total += row["hours"]
    return total


# -- team and people -------------------------------------------------------

def _capacity(wb: WorkloadWorkbook, period: Period, as_at: _dt.date
              ) -> Dict[str, Dict[str, float]]:
    """Capacity per engineer for the period, and pro-rated to the as-at date."""
    months = wb.raw.get_number(cfg.SHEET_INPUTS, cfg.MONTHS_PER_QUARTER_CELL) or 3.0
    out: Dict[str, Dict[str, float]] = {}
    for engineer in wb.engineers():
        full = 0.0
        to_date = 0.0
        for quarter in period.quarters:
            if quarter.opening:
                continue
            availability = engineer.availability.get(quarter.year or 0, 1.0)
            value = availability * months
            full += value
            to_date += value * quarter.elapsed_fraction(as_at)
        out[engineer.short_name] = {"full": full, "to_date": to_date}
    return out


def _team_totals(projects, capacity, period, as_at) -> Dict[str, Any]:
    # The headline block on the Dashboard is "all projects regardless of
    # status"; only the status table below it is narrowed to what is live in
    # the period, so the two are counted differently on purpose.
    live = [p for p in projects if p["live"]]
    planned = sum(p["planned_mm"] or 0.0 for p in projects)
    planned_to_date = sum(p["planned_to_date_mm"] or 0.0 for p in projects)
    actual = sum(p["actual_mm"] or 0.0 for p in projects)
    earned = sum(p["earned_mm"] or 0.0 for p in projects)
    capacity_to_date = sum(c["to_date"] for c in capacity.values())
    capacity_full = sum(c["full"] for c in capacity.values())
    return {
        "planned_mm": _round(planned, 2),
        "planned_to_date_mm": _round(planned_to_date, 2),
        "actual_mm": _round(actual, 2),
        "earned_mm": _round(earned, 2),
        "profit_mm": _round(earned - actual, 2),
        "capacity_mm": _round(capacity_full, 2),
        "capacity_to_date_mm": _round(capacity_to_date, 2),
        "utilisation": _round(_safe(actual, capacity_to_date)),
        "plan_adherence": _round(_safe(actual, planned_to_date)),
        "cpi": _round(_safe(earned, actual)),
        "spi": _round(_safe(earned, planned_to_date)),
        "projects_live": len(live),
        "projects_active": sum(1 for p in live if p["status"] == "Active"),
        "projects_not_started": sum(1 for p in live if p["status"] == "Not Started"),
        "projects_in_scope": sum(1 for p in live if p["in_scope"]),
    }


def _per_engineer(projects, engineers, capacity, wb, index, period
                  ) -> Dict[str, Dict[str, Any]]:
    """Each project's figures multiplied by that engineer's share of it."""
    out: Dict[str, Dict[str, Any]] = {}
    total_actual = sum(p["actual_mm"] or 0.0 for p in projects)
    for engineer in engineers:
        planned = actual = earned = remaining = type_weighted = 0.0
        planned_to_date = 0.0
        worked: List[Dict[str, Any]] = []
        for project in projects:
            share = (project["shares"] or {}).get(engineer) or 0.0
            planned += (project["planned_mm"] or 0.0) * share
            planned_to_date += (project["planned_to_date_mm"] or 0.0) * share
            earned += (project["earned_mm"] or 0.0) * share
            # Work still to do counts only what the team is actually on the
            # hook for: in delivery scope, and live in the period.
            if project["in_scope"] and project["live"]:
                remaining += (project["remaining_mm"] or 0.0) * share
            type_weighted += ((project["earned_mm"] or 0.0) * share
                              * (project["type_factor"] or 1.0))
            hours = _hours_in(index, project["number"], period, engineer)
            booked = hours / wb.hours_per_man_month() if hours else 0.0
            actual += booked
            if booked:
                worked.append({
                    "number": project["number"], "name": project["name"],
                    "status": project["status"], "actual_mm": _round(booked),
                })
        room = capacity.get(engineer, {"full": 0.0, "to_date": 0.0})
        worked.sort(key=lambda item: -(item["actual_mm"] or 0))
        out[engineer] = {
            "planned_mm": _round(planned),
            "planned_to_date_mm": _round(planned_to_date),
            "actual_mm": _round(actual),
            "earned_mm": _round(earned),
            "profit_mm": _round(earned - actual),
            "remaining_mm": _round(remaining),
            "capacity_mm": _round(room["full"]),
            "capacity_to_date_mm": _round(room["to_date"]),
            "utilisation": _round(_safe(actual, room["to_date"])),
            "plan_adherence": _round(_safe(actual, planned_to_date)),
            "cpi": _round(_safe(earned, actual)),
            "type_weighted_earned_mm": _round(type_weighted),
            "type_weighted_cpi": _round(_safe(type_weighted, actual)),
            "average_type_factor": _round(_safe(type_weighted, earned)),
            "share_of_team_time": _round(_safe(actual, total_actual)),
            "projects_worked": len(worked),
            "average_mm_per_project": _round(_safe(actual, len(worked) or None)),
            "projects": worked,
        }
    return out


def _by_status(wb: WorkloadWorkbook, projects) -> List[Dict[str, Any]]:
    """The portfolio split by project status -- the part-to-whole view."""
    out: List[Dict[str, Any]] = []
    for status in cfg.PROJECT_STATUSES:
        rows = [p for p in projects if p["status"] == status and p["live"]]
        if not rows:
            continue
        out.append({
            "status": status,
            "projects": len(rows),
            "budget_mm": _round(sum(p["budget_mm"] for p in rows), 2),
            "planned_mm": _round(sum(p["planned_mm"] or 0.0 for p in rows), 2),
            "actual_mm": _round(sum(p["actual_mm"] or 0.0 for p in rows), 2),
            "earned_mm": _round(sum(p["earned_mm"] or 0.0 for p in rows), 2),
            "remaining_mm": _round(sum(p["remaining_mm"] or 0.0 for p in rows), 2),
            "profit_mm": _round(sum(p["lifetime_profit_mm"] or 0.0 for p in rows), 2),
            "in_scope": status in cfg.PROJECT_IN_SCOPE_STATUSES,
        })
    return out


def _quarterly(wb, index, quarters, engineers, hours_per_mm
               ) -> List[Dict[str, Any]]:
    """Actual MM per engineer per quarter -- the shape of the workload over time."""
    out: List[Dict[str, Any]] = []
    for quarter in quarters:
        if quarter.opening:
            continue
        row: Dict[str, Any] = {"label": quarter.label, "year": quarter.year}
        total = 0.0
        for engineer in engineers:
            hours = sum(
                r["hours"] for r in index.rows
                if r["engineer"] == engineer and r["date"]
                and quarter.start <= r["date"] <= quarter.end
            )
            value = hours / hours_per_mm if hours_per_mm else 0.0
            row[engineer] = _round(value)
            total += value
        row["total"] = _round(total)
        if total:
            out.append(row)
    return out


def _delivery_mix(wb, index, hours_per_mm, period) -> List[Dict[str, Any]]:
    """Where the delivered hours came from in this period -- team, and support.

    Counted over the chosen period like everything else on the page, so the mix
    cannot quietly be a decade of history sitting beside a single year's KPIs.
    """
    start, end = period.start, period.end
    team_hours = sum(
        r["hours"] for r in index.rows
        if r["date"] and start and end and start <= r["date"] <= end
    )
    rows = [{"source": "This team (from timesheet)", "hours": _round(team_hours, 1),
             "man_months": _round(team_hours / hours_per_mm if hours_per_mm else 0)}]
    for label, cell in (("Bengaluru support", "B40"), ("Draftsman support", "B48")):
        hours = wb.raw.get_number(cfg.SHEET_SUPPORT_PLAN, cell) or 0.0
        rows.append({"source": label, "hours": _round(hours, 1),
                     "man_months": _round(hours / hours_per_mm if hours_per_mm else 0)})
    total = sum(r["hours"] or 0.0 for r in rows)
    for row in rows:
        row["share"] = _round(_safe(row["hours"], total), 4)
    return rows


# -- the scorecard ---------------------------------------------------------

def _scorecard(per_engineer: Dict[str, Dict[str, Any]], engineers: Sequence[str],
               definitions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Rank the team on the factors and weights the Scorecard sheet defines."""
    factors: List[Dict[str, Any]] = []
    scores: Dict[str, float] = {name: 0.0 for name in engineers}

    for factor in definitions:
        label = factor["factor"]
        key = factor.get("key")
        weight = factor.get("weight") or 0.0
        direction = factor.get("direction") or "higher"
        target = factor.get("target")
        values = {
            name: ((per_engineer[name].get(key) or 0.0) if key else 0.0)
            for name in engineers
        }
        best = max(values.values()) if values else 0.0
        row_scores: Dict[str, float] = {}
        for name, value in values.items():
            if direction == "higher":
                score = (value / best * 100.0) if best else 0.0
            else:
                reference = target or 1.0
                score = max(0.0, (1 - min(1.0, abs(value - reference) / reference)) * 100.0)
            row_scores[name] = score
            scores[name] += score * weight
        factors.append({
            "factor": label, "weight": weight, "direction": direction,
            "target": target, "key": key, "how": factor.get("how", ""),
            "values": {k: _round(v) for k, v in values.items()},
            "best": _round(best),
            "scores": {k: _round(v, 1) for k, v in row_scores.items()},
        })

    ranking = sorted(engineers, key=lambda name: -scores[name])
    strongest: Dict[str, str] = {}
    weakest: Dict[str, str] = {}
    for name in engineers:
        ordered = sorted(factors, key=lambda f: f["scores"][name])
        weakest[name] = ordered[0]["factor"] if ordered else ""
        strongest[name] = ordered[-1]["factor"] if ordered else ""
    return {
        "factors": factors,
        "totals": {name: _round(scores[name], 1) for name in engineers},
        "ranking": [
            {"rank": position + 1, "engineer": name,
             "score": _round(scores[name], 1),
             "strongest": strongest[name], "weakest": weakest[name]}
            for position, name in enumerate(ranking)
        ],
    }


# --------------------------------------------------------------------------
# hero of the month
# --------------------------------------------------------------------------

def _months_in(period: Period) -> List[Tuple[str, _dt.date, _dt.date]]:
    """Each calendar month the period covers, as (label, first day, last day)."""
    start, end = period.start, period.end
    if start is None or end is None:
        return []
    start = max(start, _dt.date(2000, 1, 1))
    out: List[Tuple[str, _dt.date, _dt.date]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = _dt.date(year, month, 1)
        last = (_dt.date(year + (month == 12), (month % 12) + 1, 1)
                - _dt.timedelta(days=1))
        out.append((first.strftime("%Y-%m"), first, last))
        year, month = (year + (month == 12), (month % 12) + 1)
    return out


def _monthly_scores(wb, index, projects, engineers, period, as_at, hours_per_mm
                    ) -> List[Dict[str, Any]]:
    """Run the scorecard month by month, so each finished month has a winner.

    Only months that have finished are scored: a month still in progress would
    rank whoever happens to have booked most so far.
    """
    factors = wb.scorecard_factors()
    availability = {e.short_name: e for e in wb.engineers()}
    by_project = {p["number"]: p for p in projects}

    # Bucket the timesheet once: month -> engineer -> job -> hours.
    buckets: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float)))
    for row in index.rows:
        date = row["date"]
        if date is None:
            continue
        buckets[date.strftime("%Y-%m")][row["engineer"]][row["job_number"]] += row["hours"]

    out: List[Dict[str, Any]] = []
    for label, first, last in _months_in(period):
        if last >= as_at:
            continue                      # not finished yet, so not scored
        per: Dict[str, Dict[str, Any]] = {}
        for name in engineers:
            jobs = buckets.get(label, {}).get(name, {})
            actual = sum(jobs.values()) / hours_per_mm if hours_per_mm else 0.0
            earned = type_weighted = planned = 0.0
            worked = 0
            for job, hours in jobs.items():
                project = by_project.get(job)
                if not project or not hours:
                    continue
                worked += 1
                share = (project["shares"] or {}).get(name) or 0.0
                lifetime = project["lifetime_actual_mm"] or 0.0
                month_mm = hours / hours_per_mm if hours_per_mm else 0.0
                value = ((month_mm / lifetime) * (project["lifetime_earned_mm"] or 0.0)
                         if lifetime else 0.0)
                earned += value
                type_weighted += value * (project["type_factor"] or 1.0)
            for project in projects:
                share = (project["shares"] or {}).get(name) or 0.0
                if not share:
                    continue
                start = _parse(project["start"])
                end = _parse(project["end"])
                if start and end and project["budget_mm"]:
                    days = (end - start).days + 1
                    overlap = max(0, (min(end, last) - max(start, first)).days + 1)
                    planned += project["budget_mm"] * overlap / days * share
            engineer = availability.get(name)
            factor = (engineer.availability.get(first.year, 1.0)
                      if engineer else 1.0)
            capacity = factor          # one month of availability
            per[name] = {
                "actual_mm": _round(actual),
                "earned_mm": _round(earned),
                "type_weighted_earned_mm": _round(type_weighted),
                "type_weighted_cpi": _round(_safe(type_weighted, actual)),
                "cpi": _round(_safe(earned, actual)),
                "utilisation": _round(_safe(actual, capacity)),
                "plan_adherence": _round(_safe(actual, planned)),
                "planned_mm": _round(planned),
                "capacity_mm": _round(capacity),
                "projects_worked": worked,
            }
        board = _scorecard(per, engineers, factors)
        winner = board["ranking"][0] if board["ranking"] else None
        out.append({
            "month": label,
            "label": first.strftime("%B %Y"),
            "per_engineer": per,
            "scores": board["totals"],
            "hero": winner["engineer"] if winner else None,
            "hero_score": winner["score"] if winner else None,
            "hero_strongest": winner["strongest"] if winner else "",
            "booked": _round(sum(p["actual_mm"] or 0.0 for p in per.values())),
        })
    return out


def _heroes(monthly: Sequence[Dict[str, Any]], scorecard: Dict[str, Any],
            as_at: _dt.date, period: Period) -> Dict[str, Any]:
    """The most recent month's winner, and the year's."""
    scored = [m for m in monthly if m["booked"]]
    latest = scored[-1] if scored else None

    # The year's hero is whoever tops the period's own scorecard; the count of
    # months won is the tie-breaker a reader will look for next.
    wins: Dict[str, int] = defaultdict(int)
    for month in scored:
        if month["hero"]:
            wins[month["hero"]] += 1
    ranking = scorecard.get("ranking") or []
    champion = ranking[0] if ranking else None
    return {
        "month": latest,
        "months_scored": len(scored),
        "wins": dict(wins),
        "year": {
            "engineer": champion["engineer"] if champion else None,
            "score": champion["score"] if champion else None,
            "strongest": champion["strongest"] if champion else "",
            "months_won": wins.get(champion["engineer"], 0) if champion else 0,
        } if champion else None,
        "period_label": period.label,
    }
