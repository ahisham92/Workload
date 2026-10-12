"""The summary video: the week ahead and how the team is doing, as a story.

The Video tab (static/video.js) draws and records the video in the browser;
this module only picks what it shows, from figures the app already works
out: the weekly report, Who needs help, People needed, the submissions plan,
the year's report and the budgets. Nothing new is measured here, and nothing
is stored.

Two parts, either or both in one video:

  - ``week``: the desks and the work piled on them for the next two weeks,
    what goes out soon, where the planned hours go, whether there are
    people enough, and the week's to-do list;
  - ``doing``: busy on real work, earned against spent, keeping to the
    plan, last week's hours, the jobs with the most hours, and the budgets.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

# The most of each list one scene has room for.
MOST_DESKS = 12
MOST_DUE = 6
MOST_JOBS = 5
MOST_TODO = 5
MOST_MONTHS = 6
# Submissions due within this many days are "going out soon".
DUE_WITHIN = 14


def _num(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _r(value: Any, places: int = 1) -> Optional[float]:
    number = _num(value)
    return None if number is None else round(number, places)


def _date(value: Any) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# -- the week -----------------------------------------------------------------


def _desks(checkins: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each person's next two weeks: hours lined up against hours there are."""
    per_day = _num(checkins.get("hours_per_day")) or 8.5
    out = []
    for person in checkins.get("people") or ():
        days = person.get("days") or ()
        booked = sum(_num(d.get("booked")) or 0 for d in days)
        there = sum(per_day for d in days if not d.get("away"))
        signal = person.get("signal") or {}
        out.append({
            "name": person.get("name") or "",
            "hours": round(booked, 1),
            "capacity": round(there, 1),
            "load": round(booked / there, 3) if there else None,
            "ease_off": signal.get("key") == "rest",
            "manager": bool(person.get("is_manager")),
        })
    # The manager first, at the big desk; then the most loaded.
    out.sort(key=lambda d: (not d["manager"], -(d["load"] or 0), d["name"]))
    return out[:MOST_DESKS]


def _due(submissions: Dict[str, Any], today: _dt.date) -> Dict[str, Any]:
    """What goes out in the next two weeks, and what is already late."""
    soon, late = [], []
    for item in submissions.get("items") or ():
        when = _date(item.get("date"))
        if when is None or item.get("prepared"):
            continue
        was = _date(item.get("register_date"))
        # Late the way the weekly report counts it: its date has passed.
        overdue = item.get("basis") == "overdue"
        entry = {
            "name": item.get("name") or "",
            "job": item.get("project_number") or "",
            "job_name": item.get("project_name") or "",
            "date": when.isoformat(),
            "was_due": was.isoformat() if overdue and was else None,
            "late": bool(overdue),
            "people": list(item.get("people") or ())[:6],
            "progress": _r(item.get("progress"), 2),
        }
        if overdue:
            late.append(entry)
        elif 0 <= (when - today).days <= DUE_WITHIN:
            soon.append(entry)
    late.sort(key=lambda e: e["was_due"] or e["date"])
    soon.sort(key=lambda e: e["date"])
    shown = (late + soon)[:MOST_DUE]
    return {"items": shown, "soon": len(soon), "late": len(late),
            "more": len(late) + len(soon) - len(shown), "within_days": DUE_WITHIN}


def _months(needs: Dict[str, Any]) -> Dict[str, Any]:
    by_month = needs.get("by_month") or {}
    months = []
    for month in (by_month.get("months") or ())[:MOST_MONTHS]:
        months.append({
            "month": month.get("month"),
            "hours": _r(month.get("hours")),
            "capacity_hours": _r(month.get("capacity_hours")),
            "needed": _r(month.get("needed")),
            "have": _r(month.get("have")),
            "nothing_planned": bool(month.get("nothing_planned")),
            "jobs": [{"job": j.get("number") or "", "hours": _r(j.get("hours"))}
                     for j in (month.get("jobs") or ())[:MOST_JOBS]],
        })
    asks = [{"title": a.get("title") or "", "people": a.get("people"),
             "severity": a.get("severity")}
            for a in needs.get("alerts") or ()
            if a.get("kind") == "need" and a.get("severity") in ("now", "soon")][:3]
    summary = needs.get("summary") or {}
    return {
        "months": months,
        "engineers": by_month.get("engineers"),
        "well_used": by_month.get("well_used"),
        "planned_until": by_month.get("planned_until"),
        "asks": asks,
        "people_needed": summary.get("people_needed") or 0,
        "unplanned": len(needs.get("unplanned") or ()),
    }


def _week(weekly: Dict[str, Any], checkins: Dict[str, Any], needs: Dict[str, Any],
          submissions: Dict[str, Any], names: Dict[str, str],
          today: _dt.date) -> Dict[str, Any]:
    this_week = weekly.get("this_week") or {}
    months = _months(needs)
    first = months["months"][0] if months["months"] else None
    jobs = []
    if first:
        for job in first["jobs"]:
            jobs.append({**job, "name": names.get(job["job"], "")})
    desks = _desks(checkins)
    return {
        "title": weekly.get("title") or "",
        "week_start": weekly.get("week_start"),
        "week_end": weekly.get("week_end"),
        "desks": desks,
        "desk_days": len((checkins.get("days") or ())),
        "ease_off": [d["name"] for d in desks if d["ease_off"]],
        "room": [r.get("name") for r in this_week.get("room") or () if r.get("name")],
        "free_week": _r(this_week.get("free_week")),
        "meetings": this_week.get("meetings") or 0,
        "due": _due(submissions, today),
        "month": None if not first else {
            "month": first["month"], "hours": first["hours"],
            "capacity_hours": first["capacity_hours"], "jobs": jobs,
        },
        "people": months,
        "todo": [{"text": t.get("text") or "", "tone": t.get("tone") or "ok"}
                 for t in (weekly.get("todo") or ())[:MOST_TODO]],
        "todo_more": max(0, len(weekly.get("todo") or ()) - MOST_TODO)
        + (weekly.get("more") or 0),
    }


# -- how we're doing ----------------------------------------------------------


def _jobs(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    jobs = [p for p in report.get("projects") or ()
            if (_num(p.get("actual_mm")) or 0) > 0]
    jobs.sort(key=lambda p: -(_num(p.get("actual_mm")) or 0))
    return [{
        "job": p.get("number") or "", "name": p.get("name") or "",
        "status": p.get("status") or "",
        "actual_mm": _r(p.get("actual_mm"), 2), "earned_mm": _r(p.get("earned_mm"), 2),
        "budget_mm": _r(p.get("budget_mm"), 2), "progress": _r(p.get("progress"), 3),
        "cpi": _r(p.get("cpi"), 2),
    } for p in jobs[:MOST_JOBS]]


def _budgets(budgets: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    totals = budgets.get("totals") or {}
    if not totals.get("jobs"):
        return None
    live = [j for j in budgets.get("jobs") or () if j.get("state") not in ("closed",)]
    worst = [{"job": j.get("job_number") or "", "name": j.get("title") or "",
              "state": j.get("state"),
              "team_budget_mm": _r(j.get("team_budget_mm"), 2),
              "team_spent_mm": _r(j.get("team_spent_mm"), 2)}
             for j in live if j.get("state") in ("over", "short")][:3]
    return {
        "jobs": totals.get("jobs"), "over": totals.get("over") or 0,
        "short": totals.get("short") or 0,
        "team_budget_mm": _r(totals.get("team_budget_mm"), 2),
        "team_spent_mm": _r(totals.get("team_spent_mm"), 2),
        "team_left_mm": _r(totals.get("team_left_mm"), 2),
        "worst": worst,
    }


def _doing(report: Dict[str, Any], weekly: Dict[str, Any],
           budgets: Dict[str, Any]) -> Dict[str, Any]:
    team = report.get("team") or {}
    per = report.get("per_engineer") or {}
    people = [{"name": name, "busy": _r((per.get(name) or {}).get("utilisation"), 3)}
              for name in report.get("engineers") or ()
              if (per.get(name) or {}).get("utilisation") is not None]
    last = weekly.get("last_week") or {}
    period = report.get("period") or {}
    return {
        "label": period.get("label") or "",
        "counted_to": report.get("counted_to"),
        "busy": _r(team.get("utilisation"), 3),
        "days_not_filled": team.get("days_not_filled") or 0,
        "people": people,
        "cpi": _r(team.get("cpi"), 2),
        "earned_mm": _r(team.get("earned_mm"), 2),
        "actual_mm": _r(team.get("actual_mm"), 2),
        "profit_mm": _r(team.get("profit_mm"), 2),
        "planned_to_date_mm": _r(team.get("planned_to_date_mm"), 2),
        "plan_adherence": _r(team.get("plan_adherence"), 3),
        # Planned work done: the value delivered over the value planned so far.
        "plan_done": (_r((_num(team.get("earned_mm")) or 0) / _num(team.get("planned_to_date_mm")), 3)
                      if _num(team.get("planned_to_date_mm")) else None),
        "projects_active": team.get("projects_active") or 0,
        "projects_not_started": team.get("projects_not_started") or 0,
        "projects_live": team.get("projects_live") or 0,
        "last_week": None if not last else {
            "week": last.get("week"), "week_end": last.get("week_end"),
            "hours": _r(last.get("hours")), "capacity": _r(last.get("capacity")),
            "overtime": _r(last.get("overtime")), "load": _r(last.get("load"), 3),
            "people": [{"name": p.get("name") or "", "hours": _r(p.get("hours")),
                        "capacity": _r(p.get("capacity")), "load": _r(p.get("load"), 3)}
                       for p in (last.get("people") or ())[:MOST_DESKS]],
        },
        "jobs": _jobs(report),
        "budgets": _budgets(budgets),
    }


def build(*, unit_name: str, today: _dt.date, weekly: Dict[str, Any],
          checkins: Dict[str, Any], needs: Dict[str, Any],
          submissions: Dict[str, Any], report: Dict[str, Any],
          budgets: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the video shows, in the order it shows it."""
    names = {p.get("number"): p.get("name") or ""
             for p in report.get("projects") or () if p.get("number")}
    return {
        "unit": unit_name,
        "made": today.isoformat(),
        "through": weekly.get("through") or report.get("counted_to"),
        "stale": bool(weekly.get("stale")),
        "week": _week(weekly, checkins, needs, submissions, names, today),
        "doing": _doing(report, weekly, budgets),
    }
