"""What one engineer is allowed to see of their own unit.

A team member's account has no write route anywhere in the app, and no read
route into the unit either -- except this one.  Everything a member sees is
built here, from their own name outwards: their figures, the projects they hold
a share of or booked time to, their own hours, their own tasks.

That is deliberate.  Filtering the manager's screens would mean every future
change to those screens had to remember the filter; a separate, small view
means a member sees exactly what this file returns and nothing else.  Nobody
else's name, score or hours is in the payload at all.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from . import reports, tasks as task_sheet
from .metrics import TimesheetIndex
from .workbook import WorkloadWorkbook


def build(wb: WorkloadWorkbook, engineer: str, *, kind: str = "year",
          year: Optional[int] = None, quarter: Optional[str] = None,
          index: Optional[TimesheetIndex] = None) -> Dict[str, Any]:
    """One engineer's own page, for one period."""
    index = index or TimesheetIndex(wb)
    report = reports.build(wb, kind, year, quarter, index=index)
    if engineer not in report.engineers:
        # The team changed under the permission: say so plainly rather than
        # showing a page of zeroes.
        return {
            "engineer": engineer,
            "known": False,
            "period": report.period.to_dict(),
            "as_at": reports.iso(report.as_at),
            "message": (
                f"{engineer} is not on this unit's team any more. Ask the "
                f"manager to point your access at the right person."
            ),
        }

    mine = dict(report.per_engineer[engineer])
    mine["engineer"] = engineer
    mine["score"] = (report.scorecard.get("totals") or {}).get(engineer)

    return {
        "engineer": engineer,
        "known": True,
        "period": report.period.to_dict(),
        "periods": {"years": sorted({q.year for q in report.period.quarters
                                     if q.year} | _years(index))},
        "as_at": reports.iso(report.as_at),
        "hours_per_man_month": report.hours_per_mm,
        "me": mine,
        "projects": _my_projects(report, engineer),
        "timesheet": _my_timesheet(wb, engineer, report.period),
        "months": _my_months(report, engineer),
        "tasks": _my_tasks(wb, engineer),
        "definitions": wb.definitions(),
    }


def _years(index: TimesheetIndex) -> set:
    return {row["date"].year for row in index.rows if row["date"]}


def _my_projects(report: reports.ReportSet, engineer: str) -> List[Dict[str, Any]]:
    """The projects this person has a hand in, at their own share of them.

    Money and man-months are scaled to that share, so the figures on the page
    are theirs rather than the team's.
    """
    out: List[Dict[str, Any]] = []
    for project in report.projects:
        share = (project.get("shares") or {}).get(engineer) or 0.0
        booked = _booked_by(report, project["number"], engineer)
        if not share and not booked:
            continue
        out.append({
            "number": project["number"],
            "name": project["name"],
            "status": project["status"],
            "live": project["live"],
            "progress": project["progress"],
            "share": round(share, 4),
            "budget_mm": _times(project["budget_mm"], share),
            "planned_mm": _times(project["planned_mm"], share),
            "actual_mm": _times(project["actual_mm"], share),
            "earned_mm": _times(project["earned_mm"], share),
            "profit_mm": _times(project["profit_mm"], share),
            "remaining_mm": _times(project["remaining_mm"], share),
            "cpi": project["cpi"],
            "start": project["start"],
            "end": project["end"],
        })
    out.sort(key=lambda p: -(p["actual_mm"] or 0))
    return out


def _booked_by(report: reports.ReportSet, number: str, engineer: str) -> float:
    """What this person booked to the project in the period, if anything."""
    for row in report.per_engineer.get(engineer, {}).get("projects", []):
        if row["number"] == number:
            return row["actual_mm"] or 0.0
    return 0.0


def _times(value: Optional[float], share: float) -> Optional[float]:
    return None if value is None else round(value * share, 3)


def _my_timesheet(wb: WorkloadWorkbook, engineer: str, period) -> Dict[str, Any]:
    """This person's own rows: how many, how many hours, and when."""
    year = period.year if period.kind == "year" else None
    check = wb.data_check(year)
    entry = dict(check["per_engineer"].get(engineer) or {})
    entry.pop("rows_not_matching_pattern", None)
    entry["year"] = year
    return entry


def _my_months(report: reports.ReportSet, engineer: str) -> List[Dict[str, Any]]:
    """Their month by month effort and score -- theirs only, no ranking."""
    out: List[Dict[str, Any]] = []
    for month in report.monthly:
        figures = (month.get("per_engineer") or {}).get(engineer)
        if not figures:
            continue
        out.append({
            "month": month["month"],
            "label": month["label"],
            "actual_mm": figures.get("actual_mm"),
            "earned_mm": figures.get("earned_mm"),
            "utilisation": figures.get("utilisation"),
            "cpi": figures.get("cpi"),
            "projects_worked": figures.get("projects_worked"),
            "score": (month.get("scores") or {}).get(engineer),
            # Whether they won it, but never who did if they did not.
            "won": month.get("hero") == engineer,
        })
    return out


def _my_tasks(wb: WorkloadWorkbook, engineer: str) -> Dict[str, Any]:
    """The tasks with this person's name on them, and what they add up to."""
    if not task_sheet.has_sheet(wb.raw):
        return {"tasks": [], "open_hours": 0.0, "overdue": 0, "settings": None}
    settings = wb.task_settings()
    today = _dt.date.today()
    mine = [t for t in task_sheet.read(wb.raw) if engineer in t.assignees]
    rows = []
    open_hours = overdue = 0
    for task in mine:
        record = task.to_dict()
        # A shared task shows what it costs this person, not its whole size.
        record["assignees"] = [engineer] if len(task.assignees) > 1 else list(
            task.assignees)
        record["shared_with"] = max(0, len(task.assignees) - 1)
        if not task.done:
            open_hours += task.hours_each()
            if task.due and task.due < today:
                overdue += 1
                record["overdue"] = True
        rows.append(record)
    rows.sort(key=lambda t: (t["done"], t["due"] or "9999-12-31", t["id"]))
    return {
        "tasks": rows,
        "open_hours": round(open_hours, 2),
        "overdue": overdue,
        "hours_per_day": task_sheet.hours_per_day(settings),
    }
