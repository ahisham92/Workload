"""The submissions plan, drafted by the app rather than typed.

Every deliverable still short of being submitted gets a date, and the plan
says where each date came from:

* **set** -- the deliverable already has a date in the register, still ahead;
* **estimated** -- worked out from how much is left to do before it can go
  and how fast it is being done:

  - *left to do*: a submission is the ``Submitted`` step, 80% of the credit,
    not the finish.  On a confirmed project the deliverable's share of the
    forecast cost at completion, less what it has had, gives the hours to that
    point.  On one the timesheets set up and nobody has confirmed, there is no
    budget to read, so the effort already spent is scaled by the progress it
    bought: hours spent to reach 10% say how many more reach 80%.
  - *how fast*: the hours a working day booked to that phase over the newest
    two working weeks of timesheets -- the same pace the planner uses.

* **typical** -- on a project nobody has confirmed, progress is only a
  placeholder, so effort left cannot be read from it.  The date is instead the
  phase's first booking plus how long this unit's phases usually take from
  first booking to submission (the middle of its own finished phases, or three
  months until it has some); one already past that is due in the next two
  weeks.  Confirming the project on Projects turns this into an estimate;
* **overdue** -- the register's date has passed and nothing says it went; it
  is re-estimated as above, and the old date is shown beside it;
* **idle** -- nobody has booked to it lately, so no pace and no date.  It is
  listed so it is not forgotten.

The manager confirms dates, or changes them, and the confirmed ones are
written to the deliverable.  With them, if asked, the run-up to each one goes
onto the task list -- the existing *Submission tasks*, a slice of every
working day of the week before -- so the plan becomes the coming days' work
without being typed twice.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import derive
from . import planner
from . import tasks as task_sheet

#: The credit at which a deliverable has been sent to the client.
SUBMITTED_AT = 0.8
#: No estimate runs further ahead than this; past it the date says nothing.
LONGEST_DAYS = 260
#: A phase's usual length when the unit has no finished phases to learn from.
TYPICAL_DAYS = 90
TYPICAL_BOUNDS = (20, 240)
#: Not booked to for this long, and it is idle.
IDLE_AFTER_DAYS = 30
#: A phase past its usual length is due within this many working days.
SOON_DAYS = 10


def typical_length(deliverable_rows: Sequence[Dict[str, Any]],
                   finished: Iterable[str]) -> Dict[str, Any]:
    """How long this unit's phases take, first booking to last, when finished."""
    finished = set(finished)
    lengths = []
    for item in deliverable_rows:
        done = (item["project_number"] in finished
                or (item.get("credit") or 0.0) >= SUBMITTED_AT - 1e-9)
        if done and item.get("first_charge") and item.get("last_charge"):
            first = _dt.date.fromisoformat(item["first_charge"])
            last = _dt.date.fromisoformat(item["last_charge"])
            if (last - first).days >= 5:
                lengths.append((last - first).days)
    if not lengths:
        return {"days": TYPICAL_DAYS, "from": 0}
    lengths.sort()
    middle = lengths[len(lengths) // 2]
    low, high = TYPICAL_BOUNDS
    return {"days": min(high, max(low, middle)), "from": len(lengths)}


def pace_by_phase(rows: Iterable[Dict[str, Any]], config: Dict[str, Any]
                  ) -> Dict[tuple, float]:
    """Hours a working day booked to each (job, phase) in the newest fortnight."""
    dated = [r for r in rows if r.get("date") and r.get("job_number")]
    if not dated:
        return {}
    last = max(r["date"] for r in dated)
    window = planner.days_back(last, planner.LOOKBACK_DAYS, config)
    first = window[0]
    sums: Dict[tuple, float] = defaultdict(float)
    for row in dated:
        if first <= row["date"] <= last:
            sums[(row["job_number"], row.get("phase"))] += float(row["hours"] or 0.0)
            sums[(row["job_number"], None)] += float(row["hours"] or 0.0)
    return {key: value / len(window) for key, value in sums.items() if value > 0}


def add_working_days(start: _dt.date, count: int, config: Dict[str, Any]) -> _dt.date:
    days = planner.days_ahead(start, max(1, count), config)
    return days[-1] if days else start


def plan(*, deliverable_rows: Sequence[Dict[str, Any]], deliverables: Sequence[Any],
         project_rows: Sequence[Dict[str, Any]], projects: Sequence[Any],
         rows: Sequence[Dict[str, Any]], tasks: Sequence[task_sheet.Task],
         config: Dict[str, Any], hours_per_mm: float,
         drawing_counts: Mapping[int, int], today: _dt.date) -> Dict[str, Any]:
    hours_per_mm = float(hours_per_mm or 0) or 185.0
    register = {p.number: p for p in projects}
    figures = {p["number"]: p for p in project_rows}
    by_row = {d.row: d for d in deliverables}
    rates = pace_by_phase(rows, config)
    prepared = {t.series for t in tasks if t.series}
    typical = typical_length(deliverable_rows,
                             [p.number for p in projects if p.status == "Finalized"])

    items: List[Dict[str, Any]] = []
    for metric in deliverable_rows:
        number = metric["project_number"]
        project = register.get(number)
        totals = figures.get(number) or {}
        deliverable = by_row.get(metric["row"])
        if project is None or deliverable is None:
            continue
        if not totals.get("in_scope", True) or project.status in {"Finalized", "Cancelled"}:
            continue
        credit = min(1.0, max(0.0, metric.get("credit") or 0.0))
        if credit >= SUBMITTED_AT - 1e-9 or deliverable.submitted_to_client \
                or deliverable.completed:
            continue

        spent = float(metric.get("actual_hours") or 0.0)
        confirmed = not derive.needs_confirming(project.notes or "")
        weight = float(metric.get("phase_weight") or 0.0)
        if confirmed and totals.get("cost_at_completion_mm"):
            whole = weight * float(totals["cost_at_completion_mm"]) * hours_per_mm
            left = max(0.0, whole * SUBMITTED_AT - spent)
        elif credit > 0 and spent > 0:
            left = spent * (SUBMITTED_AT - credit) / credit
        else:
            left = None

        phase = metric.get("ts_phase")
        rate = rates.get((number, phase)) if phase is not None else None
        if rate is None:
            project_rate = rates.get((number, None))
            rate = project_rate * weight if project_rate and weight else None

        set_date = deliverable.status_date
        last_charge = (_dt.date.fromisoformat(metric["last_charge"])
                       if metric.get("last_charge") else None)
        idle = not rate and (last_charge is None
                             or (today - last_charge).days > IDLE_AFTER_DAYS)
        estimate, how = None, "estimated"
        if not confirmed:
            # Placeholder progress says nothing about effort left; the unit's
            # own phases say how long one usually runs.
            left = None
            if not idle:
                first = (_dt.date.fromisoformat(metric["first_charge"])
                         if metric.get("first_charge") else today)
                estimate = first + _dt.timedelta(days=typical["days"])
                soon = add_working_days(today, SOON_DAYS, config)
                if estimate < soon:
                    estimate = soon
                how = "typical"
        elif left is not None and rate:
            days = math.ceil(left / rate) if left > 0 else 1
            if days <= LONGEST_DAYS:
                estimate = add_working_days(today, days, config)

        if set_date and set_date >= today:
            basis, date = "set", set_date
        elif set_date:
            basis, date = "overdue", estimate
        elif estimate:
            basis, date = how, estimate
        elif idle:
            basis, date = "idle", None
        else:
            basis, date = "far", None

        shares = {k: v for k, v in (deliverable.shares or {}).items() if v}
        items.append({
            "row": metric["row"],
            "project_number": number,
            "project_name": project.name or number,
            "name": metric["name"],
            "step_name": metric.get("step_name") or "",
            "progress": round(credit, 4),
            "basis": basis,
            "date": date.isoformat() if date else None,
            "register_date": set_date.isoformat() if set_date else None,
            "hours_left": round(left, 1) if left is not None else None,
            "pace": round(rate, 2) if rate else None,
            "confirmed_project": confirmed,
            "people": sorted(shares, key=lambda n: -shares[n]),
            "drawings": drawing_counts.get(metric["row"]),
            "prepared": task_sheet.submission_series(metric["row"]) in prepared,
        })

    items.sort(key=lambda i: (i["date"] is None, i["date"] or "", i["project_number"]))
    weeks: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not item["date"]:
            continue
        day = _dt.date.fromisoformat(item["date"])
        monday = day - _dt.timedelta(days=day.weekday())
        week = weeks.setdefault(monday.isoformat(), {"week": monday.isoformat(),
                                                     "count": 0, "drawings": 0})
        week["count"] += 1
        week["drawings"] += item["drawings"] or 0
    return {
        "today": today.isoformat(),
        "items": items,
        "weeks": sorted(weeks.values(), key=lambda w: w["week"]),
        "counts": {basis: sum(1 for i in items if i["basis"] == basis)
                   for basis in ("set", "estimated", "typical", "overdue",
                                 "idle", "far")},
        "typical_days": typical["days"],
        "typical_from": typical["from"],
        "lead_days": int(config.get("submission_lead_days", 7)),
        "hours_a_day": float(config.get("submission_hours_per_day", 2.0)),
    }
