"""Working to a plan: each week's plan agreed, and checked against what happened.

The day plan is redrawn every morning from the newest figures, which is right
for "what now" and useless for "did we do what we said".  So once a week the
plan is **locked**: per person, the hours on each job, the tasks they were to
finish, and the time that is no project's.  The daily run locks the current
week by itself the first time it sees it; the manager can lock it again (or
lock next week ahead) after changing things, and reasons already given stay.

At the end of the week the locked plan is laid beside:

* **the task list** -- which of the planned tasks are done, which are not;
* **the timesheets** -- the hours each person booked to each job that week,
  which arrive after the week is over, so a week is only judged on hours
  once that person's timesheet is in;
* **what came in on top** -- requests slotted into the week after it was
  locked, and hours booked to jobs that were not in the plan at all.

What did not go to plan is a **slip**, and a slip has a reason, given with a
tap by the manager or by the person themselves: waiting on the client, urgent
work came in, it took longer, away, moved to somebody else.  Week after week
the reasons say what to fix, and the share of the plan kept says whether it
is getting better.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import derive
from . import intake
from . import tasks as task_sheet
from .model import ValidationError, iso

#: Why something did not go to plan, as a tap.
REASONS = {
    "client": "Waiting on the client or others",
    "request": "Urgent work came in",
    "longer": "Took longer than planned",
    "away": "Away or off sick",
    "moved": "Moved to someone else",
    "other": "Something else",
}
#: Booked under this share of the planned hours on a job is a slip.
SLIP_SHARE = 0.75
#: A job planned for less than this in a week is too small to call a slip.
SLIP_SMALLEST_HOURS = 2.0
#: Weeks shown in the trend.
TREND_WEEKS = 8
#: A reason's note is a line.
NOTE_LONGEST = 200
#: The line for time that is no project's.
OTHER_TITLE = "Meetings, team support and development"
#: Task blocks without a job are kept under this key.
NO_JOB = ""


class WeekPlanError(ValidationError):
    pass


def _round(value: float) -> float:
    return round(value + 0.0, 1)


# --------------------------------------------------------------------------
# locking
# --------------------------------------------------------------------------

def snapshot(day_plans: Sequence[Dict[str, Any]],
             tasks: Sequence[task_sheet.Task],
             project_names: Mapping[str, str]) -> List[Dict[str, Any]]:
    """The lines a week's plan is kept as, from ``daily.plan_day`` for each
    of its days.  Done tasks are not planned work any more and do not show
    in a plan, so a task done before the lock is not a line."""
    by_id = {t.id: t for t in tasks}
    jobs: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    others: Dict[str, float] = defaultdict(float)
    task_hours: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for day in day_plans:
        for person in day.get("people", []):
            name = person["name"]
            for block in person.get("blocks", []):
                hours = float(block.get("hours") or 0.0)
                if hours <= 0:
                    continue
                task_id = block.get("task_id")
                project = block.get("project") or ""
                if task_id is not None:
                    task_hours[name][task_id] += hours
                    jobs[name][project or NO_JOB] += hours
                elif project:
                    jobs[name][project] += hours
                else:
                    others[name] += hours
    out: List[Dict[str, Any]] = []
    for name in sorted(set(jobs) | set(others) | set(task_hours)):
        for job, hours in sorted(jobs.get(name, {}).items(), key=lambda kv: -kv[1]):
            out.append({"person": name, "kind": "job", "job_number": job,
                        "task_id": None, "hours": round(hours, 2), "due": None,
                        "title": (project_names.get(job) or job) if job
                        else "Tasks with no job"})
        for task_id, hours in task_hours.get(name, {}).items():
            task = by_id.get(task_id)
            if task is None:
                continue
            out.append({"person": name, "kind": "task",
                        "job_number": task.project_number or "", "task_id": task_id,
                        "title": task.name or f"Task {task_id}",
                        "hours": round(hours, 2), "due": iso(task.due)})
        if others.get(name):
            out.append({"person": name, "kind": "other", "job_number": "",
                        "task_id": None, "title": OTHER_TITLE,
                        "hours": round(others[name], 2), "due": None})
    return out


def current_week(today: _dt.date, config: Dict[str, Any], week_of) -> List[_dt.date]:
    """The working days of the week being worked: once a week's last working
    day has passed (a weekend), the coming one."""
    days = week_of(today, config)
    if days and days[-1] >= today:
        return days
    probe = today
    for _ in range(21):
        probe += _dt.timedelta(days=1)
        following = week_of(probe, config)
        if following and following[0] > today:
            return following
    return days


def lockable(week: _dt.date, today: _dt.date, config: Dict[str, Any],
             week_of) -> bool:
    """This week or next: a past week is history, and further ahead the plan
    is still a guess."""
    this = current_week(today, config, week_of)
    if not this:
        return False
    following = week_of(this[0] + _dt.timedelta(days=7), config)
    return week in (this[0], following[0] if following else None)


def clean_reason(body: Mapping[str, Any]) -> Dict[str, Any]:
    reason = str(body.get("reason") or "").strip()
    if reason and reason not in REASONS:
        raise WeekPlanError(["Pick one of the reasons."])
    note = " ".join(str(body.get("note") or "").split())[:NOTE_LONGEST]
    try:
        line_id = int(body.get("id"))
    except (TypeError, ValueError):
        raise WeekPlanError(["Say which line it is for."])
    return {"id": line_id, "reason": reason, "note": note if reason else ""}


# --------------------------------------------------------------------------
# the week, checked
# --------------------------------------------------------------------------

def review(*, week_days: Sequence[_dt.date], lines: Sequence[Dict[str, Any]],
           locked: bool, rows: Sequence[Dict[str, Any]],
           tasks: Sequence[task_sheet.Task], slots: Mapping[int, Dict[str, Any]],
           today: _dt.date, project_names: Mapping[str, str],
           people: Optional[Iterable[str]] = None,
           roster: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Each person's week: planned, done, booked, and what slipped."""
    first, last = week_days[0], week_days[-1]
    over = last < today
    by_id = {t.id: t for t in tasks}
    wanted = set(people) if people is not None else None
    teams = {p["name"]: p.get("team_name", "") for p in roster}

    plan_by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for line in lines:
        if wanted is None or line["person"] in wanted:
            plan_by[line["person"]].append(line)

    booked: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    booked_other: Dict[str, float] = defaultdict(float)
    sheet_days: Dict[str, set] = defaultdict(set)
    for row in rows:
        day = row.get("date")
        if not day or day < first or day > last:
            continue
        name = row["engineer"]
        if wanted is not None and name not in wanted:
            continue
        sheet_days[name].add(day)
        hours = float(row.get("hours") or 0.0)
        if derive.is_project_work(row.get("job_type") or "") and row.get("job_number"):
            booked[name][row["job_number"]] += hours
        else:
            booked_other[name] += hours

    planned_tasks = {line["task_id"] for line in lines if line["kind"] == "task"}
    on_top: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        if not intake.is_request(task) or task.id in planned_tasks:
            continue
        slot = slots.get(task.id)
        if not slot:
            continue
        start = slot["start"][:10]
        if not (first.isoformat() <= start <= last.isoformat()):
            continue
        if wanted is not None and slot["person"] not in wanted:
            continue
        on_top[slot["person"]].append({
            "id": task.id, "title": task.name, "job": task.project_number,
            "hours": round(float(task.required_hours or 0.0), 2), "done": task.done,
            "start": slot["start"]})

    names = sorted(set(plan_by) | set(booked) | set(on_top))
    out_people = []
    reasons_tally: Dict[str, int] = defaultdict(int)
    for name in names:
        own = plan_by.get(name, [])
        sheet_in = bool(sheet_days.get(name))
        planned_jobs = {l["job_number"]: l for l in own if l["kind"] == "job"}
        jobs = []
        kept = planned_project = 0.0
        slips = []
        for job, line in planned_jobs.items():
            hours_booked = booked[name].get(job, 0.0) if job else None
            if job:
                planned_project += line["hours"]
                kept += min(line["hours"], hours_booked or 0.0)
            short = bool(job and sheet_in and over
                         and line["hours"] >= SLIP_SMALLEST_HOURS
                         and (hours_booked or 0.0) < line["hours"] * SLIP_SHARE)
            entry = {
                "id": line["id"], "job": job,
                "name": line["title"] or project_names.get(job) or job,
                "planned": _round(line["hours"]),
                "booked": _round(hours_booked) if hours_booked is not None and sheet_in else None,
                "short": short,
                "reason": line.get("reason") or "", "note": line.get("reason_note") or "",
            }
            jobs.append(entry)
            if short:
                slips.append({**entry, "kind": "job",
                              "what": f"{entry['name']}: {entry['booked']:g} h of "
                                      f"{entry['planned']:g} h planned"})
        for job, hours in booked[name].items():
            if job not in planned_jobs and hours > 0:
                jobs.append({"id": None, "job": job,
                             "name": project_names.get(job) or job, "planned": 0.0,
                             "booked": _round(hours), "short": False, "unplanned": True,
                             "reason": "", "note": ""})
        jobs.sort(key=lambda j: -max(j["planned"], j["booked"] or 0.0))

        task_rows = []
        done = 0
        for line in (l for l in own if l["kind"] == "task"):
            task = by_id.get(line["task_id"])
            if task is None:
                state = "removed"
            elif task.done:
                state = "done"
                done += 1
            elif over or (task.due and task.due < today):
                state = "late" if task.due and task.due <= last else "not_done"
            else:
                state = "open"
            entry = {"id": line["id"], "task_id": line["task_id"], "title": line["title"],
                     "job": line["job_number"], "hours": _round(line["hours"]),
                     "due": line["due"], "state": state,
                     "reason": line.get("reason") or "",
                     "note": line.get("reason_note") or ""}
            task_rows.append(entry)
            if state in ("late", "not_done"):
                slips.append({**entry, "kind": "task",
                              "what": f"{line['title']}: not done"
                                      + (f", due {line['due']}" if line["due"] else "")})
        task_rows.sort(key=lambda t: (t["state"] == "done", t["due"] or "9999"))

        for slip in slips:
            if slip["reason"]:
                reasons_tally[slip["reason"]] += 1
        other = next((l for l in own if l["kind"] == "other"), None)
        top_hours = sum(r["hours"] for r in on_top.get(name, []))
        unplanned = sum(j["booked"] or 0.0 for j in jobs if j.get("unplanned"))
        planned_total = sum(l["hours"] for l in own if l["kind"] in ("job", "other"))
        out_people.append({
            "name": name,
            "team_name": teams.get(name, ""),
            "planned_hours": _round(planned_total),
            "planned_project_hours": _round(planned_project),
            "booked_hours": _round(sum(booked[name].values()) + booked_other[name])
            if sheet_in else None,
            "timesheet_in": sheet_in,
            "kept": round(kept / planned_project, 3)
            if sheet_in and planned_project else None,
            "kept_hours": _round(kept) if sheet_in else None,
            "tasks_planned": len(task_rows),
            "tasks_done": done,
            "on_top": on_top.get(name, []),
            "on_top_hours": _round(top_hours),
            "unplanned_hours": _round(unplanned) if sheet_in else None,
            "other_planned": _round(other["hours"]) if other else 0.0,
            "jobs": jobs,
            "tasks": task_rows,
            "slips": slips,
        })

    sheets = [p for p in out_people if p["timesheet_in"] and p["planned_project_hours"]]
    planned_hours = sum(p["planned_project_hours"] for p in sheets)
    kept_hours = sum(p["kept_hours"] or 0.0 for p in sheets)
    tasks_planned = sum(p["tasks_planned"] for p in out_people)
    tasks_done = sum(p["tasks_done"] for p in out_people)
    slip_count = sum(len(p["slips"]) for p in out_people)
    explained = sum(1 for p in out_people for s in p["slips"] if s["reason"])
    return {
        "week": first.isoformat(),
        "week_end": last.isoformat(),
        "days": [d.isoformat() for d in week_days],
        "state": "past" if over else ("ahead" if first > today else "current"),
        "locked": locked,
        "locked_at": max((l.get("locked_at") or "" for l in lines), default="") or None,
        "people": out_people,
        "summary": {
            "people": len(out_people),
            "timesheets_in": sum(1 for p in out_people if p["timesheet_in"]),
            "kept": round(kept_hours / planned_hours, 3) if planned_hours else None,
            "tasks_planned": tasks_planned,
            "tasks_done": tasks_done,
            "tasks_done_share": round(tasks_done / tasks_planned, 3) if tasks_planned else None,
            "on_top_hours": _round(sum(p["on_top_hours"] for p in out_people)),
            "on_top_count": sum(len(p["on_top"]) for p in out_people),
            "unplanned_hours": _round(sum(p["unplanned_hours"] or 0.0 for p in out_people)),
            "slips": slip_count,
            "slips_explained": explained,
        },
        "reasons": [{"key": key, "label": REASONS[key], "count": reasons_tally.get(key, 0)}
                    for key in REASONS],
        "what_next": what_next(out_people, reasons_tally, over),
    }


def what_next(people: Sequence[Dict[str, Any]], reasons: Mapping[str, int],
              over: bool) -> List[str]:
    """A few plain lines on what to change, from what the week shows."""
    out: List[str] = []
    top = max(reasons.items(), key=lambda kv: kv[1], default=(None, 0))
    if top[0] == "request" and top[1] >= 2:
        out.append("Urgent work is what knocks the plan most. Keep a few hours a "
                   "day free for it, or send requests to whoever has room first.")
    elif top[0] == "longer" and top[1] >= 2:
        out.append("Work keeps taking longer than planned. Plan the same kind of "
                   "work with more hours next week.")
    elif top[0] == "client" and top[1] >= 2:
        out.append("Waiting on the client is what holds things up. Chase the "
                   "inputs at the start of the week and have a second job ready.")
    late = [p for p in people if any(t["state"] in ("late", "not_done") for t in p["tasks"])]
    if late:
        names = ", ".join(p["name"] for p in late[:3])
        out.append(f"Tasks did not get done for {names}. Look at them first in "
                   f"next week's plan.")
    heavy = sorted((p for p in people if p["on_top_hours"] >= 4),
                   key=lambda p: -p["on_top_hours"])
    if heavy:
        p = heavy[0]
        out.append(f"{p['name']} took {p['on_top_hours']:g} h of requests on top of "
                   f"the plan. Share requests out next week.")
    unexplained = sum(1 for p in people for s in p["slips"] if not s["reason"])
    if over and unexplained:
        out.append(f"{unexplained} slip{'s' if unexplained != 1 else ''} without a "
                   f"reason. A tap each tells you what to fix.")
    missing = [p["name"] for p in people if not p["timesheet_in"]]
    if over and missing:
        out.append(f"Timesheets not in yet for {', '.join(missing[:4])}"
                   + (" and others" if len(missing) > 4 else "")
                   + ". Hours are compared once they are.")
    return out[:5]


def trend_point(view: Dict[str, Any]) -> Dict[str, Any]:
    s = view["summary"]
    return {"week": view["week"], "kept": s["kept"],
            "tasks_done_share": s["tasks_done_share"], "on_top_hours": s["on_top_hours"],
            "slips": s["slips"], "state": view["state"]}
