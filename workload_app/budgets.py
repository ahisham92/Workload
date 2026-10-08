"""Budgets: what BISpark says each job has, and how much of it is the team's.

Two exports carry it, and both come from pages the manager can already open:

* **the Projects list** (BISpark > DD or HoD or GL > Projects): one line per
  job with the department's budget, what it has spent, what is left to do,
  EAC, progress and status.  Its *Summarized data* export has the budget
  column; the *underlying data* export does not, but still gives the spend,
  the work remaining and whether more effort is needed.  Either is read.
* **the staff expenditure** of one job (Project Detail > MH Expenditure):
  every day anybody booked to it, with the unit they sit in.

A job's budget in BISpark is the department's, and a department is several
units: not all of it is this team's.  Nothing in the exports says how it is
split, so the team's share is the manager's to set once per job; until they
do, it is worked out from who has spent the hours so far.

The staff expenditure also shows hours the team's own timesheet exports may
not have -- each person's export shows only their own rows.  Where a team
member's day on the job is missing here, it is filled in from it, tagged so
the next import replaces it and never doubles it.  Nobody's own rows are
changed.

Who counts as the team is not only who sits in the unit: a draftsman from
another unit may work for it, somebody may be on loan for a few months, and
somebody who left still counts up to the day they left.  The manager says so
once per person (``spend_people``); everybody else on a job is one line,
"other units".

A job that drops off the Projects list -- finished, so BISpark no longer
shows it -- keeps everything it had, and shows as closed.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import derive, timesheets
from .model import ValidationError, iso, pattern_to_regex, stored_date, today

#: What the rows a staff expenditure fills in are tagged with.
SPEND_SOURCE = "staff-export"
#: The job type a project's hours carry in a timesheet export.
PROJECT_JOB_TYPE = "1-Projects"
#: The unit's own copy of the two export requests, for the manager's PC.
REQUESTS_SETTING = "budget_requests"
#: How many jobs' staff expenditure one night asks BISpark for.
MAX_SPEND_EXPORTS = 40
#: Stands for the job number in the saved staff expenditure request.
JOB_SLOT = "{{JOB}}"
#: The pace a budget is being spent at is read over this many days.
PACE_DAYS = 91
DAYS_A_MONTH = 30.44
#: Months of budget left past which a job is not said to run out at all.
LONGEST_RUN = 1200
#: A staff expenditure may hold less than the last one -- a correction -- but
#: not much less: past this, the job's last one is kept and the new one is not.
LARGEST_SHRINK = 0.10

#: What somebody on a staff expenditure is to the team.
KINDS = {"team": "My team", "draftsman": "Draftsman in my team",
         "other": "Other unit", "left": "Left the team",
         "loan": "On loan to my team"}

_JOB_NUMBER = re.compile(r"[A-Z]{1,4}\d{5}-\d{4}[A-Z]")


class BudgetError(ValueError):
    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


# --------------------------------------------------------------------------
# reading the exports
# --------------------------------------------------------------------------

_norm = timesheets._normalise

PROJECT_COLUMNS = {
    "job_number": ("jobnumber", "number", "projectnumber"),
    "title": ("title", "projecttitle"),
    "lead": ("lead", "leaddepartment"),
    "status": ("status", "jobsstatus", "jobstatus"),
    "dept": ("mappeddepartmentabr", "budgeteddeptabr", "departmentabr"),
    "budget_mm": ("budgetmm", "totalmmbudget", "budget"),
    "spent_mm": ("spentmm", "spent"),
    "remaining_mm": ("remainingworkload",),
    "eac_mm": ("eac",),
    "ev_mm": ("ev",),
    "progress": ("progress", "percentprogress"),
    "start": ("startdate", "start"),
    "end": ("enddate", "end"),
    "needs_more": ("requiresadditioneffort",),
}

SPEND_COLUMNS = {
    "job_number": ("jobnumber",),
    "name": ("employeename", "fullname"),
    "mm": ("mmspent",),
    "hours": ("totalhours",),
    "regular_hours": ("regularhours",),
    "overtime_hours": ("overtimehours",),
    "day": ("date",),
    "phase": ("phase",),
    "deliverable": ("deliverabledescription",),
    "unit": ("currentunitdesc",),
    "dept": ("budgeteddeptabr", "dept", "departmentabr"),
    "grade": ("grade",),
    "job_status": ("jobstatus",),
}

_ADDED_UP = ("budget_mm", "spent_mm", "remaining_mm", "eac_mm", "ev_mm")


def _columns(headers: Sequence[Any], wanted: Dict[str, Tuple[str, ...]]
             ) -> Dict[str, int]:
    """Where each field is, by header name, first match winning."""
    at: Dict[str, int] = {}
    for index, header in enumerate(headers):
        at.setdefault(_norm(header), index)
    out = {}
    for field, names in wanted.items():
        for name in names:
            if name in at:
                out[field] = at[name]
                break
    return out


def _header_row(grid: Sequence[Sequence[Any]]) -> int:
    for index, row in enumerate(grid[:15]):
        cells = {_norm(c) for c in row if c not in (None, "")}
        if "jobnumber" in cells or ({"number", "title"} <= cells):
            return index
    raise BudgetError("No header row found. Export the Projects table, or the "
                      "Staff expenditure table on a project's MH Expenditure page.")


def _number(value: Any) -> Optional[float]:
    return timesheets._coerce_number(value) if value not in (None, "") else None


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


_text = timesheets._text


def parse(filename: str, data: bytes) -> Dict[str, Any]:
    """Read one upload: ``{"kind": "projects", "jobs": [...]}`` or
    ``{"kind": "spend", "rows": [...]}``."""
    try:
        grid = timesheets.read_grid(filename, data)
    except timesheets.ImportError_ as error:
        raise BudgetError(str(error)) from None
    if not grid:
        raise BudgetError(f"{filename!r} is empty.")
    head = _header_row(grid)
    headers = grid[head]
    names = {_norm(h) for h in headers if h not in (None, "")}
    body = grid[head + 1:]
    if "jobtype" in names and "fullname" in names:
        raise BudgetError(f"{filename!r} is a timesheet export: bring it in on "
                          "the Timesheets tab instead.")
    if names & {"employeename", "fullname"}:
        return {"kind": "spend", "filename": filename,
                "rows": _spend_rows(body, _columns(headers, SPEND_COLUMNS))}
    columns = _columns(headers, PROJECT_COLUMNS)
    if "job_number" in columns and "spent_mm" in columns:
        return {"kind": "projects", "filename": filename,
                "has_budget": "budget_mm" in columns,
                # What this export cannot say, so what is held is kept.
                "missing": [f for f in PROJECT_COLUMNS if f not in columns],
                "jobs": _project_jobs(body, columns)}
    raise BudgetError(f"{filename!r} is neither BISpark's Projects list nor a "
                      "project's staff expenditure.")


def _cell(row: Sequence[Any], columns: Dict[str, int], field: str) -> Any:
    at = columns.get(field)
    return row[at] if at is not None and at < len(row) else None


def _job(value: Any) -> str:
    text = _text(value)
    found = _JOB_NUMBER.search(text.upper())
    return found.group(0) if found else text


def _project_jobs(body, columns) -> List[Dict[str, Any]]:
    jobs: Dict[str, Dict[str, Any]] = {}
    month_first = timesheets.month_first(
        _cell(row, columns, field) for row in body for field in ("start", "end"))
    for row in body:
        number = _job(_cell(row, columns, "job_number"))
        if not number or number.lower() == "total":
            continue
        job = jobs.get(number)
        if job is None:
            job = jobs[number] = {
                "job_number": number, "title": "", "lead": "", "status": "",
                "dept": "", "start": None, "end": None, "needs_more": 0,
                "progress": None, "rows": 0,
                **{f: None for f in _ADDED_UP}}
        job["rows"] += 1
        for field in ("title", "lead", "status", "dept"):
            job[field] = job[field] or _text(_cell(row, columns, field))
        for field in _ADDED_UP:
            value = _number(_cell(row, columns, field))
            if value is not None:
                job[field] = (job[field] or 0.0) + value
        progress = _number(_cell(row, columns, "progress"))
        if progress is not None:
            job["progress"] = progress / 100 if progress > 1.5 else progress
        for field, pick in (("start", min), ("end", max)):
            day = timesheets._coerce_date(_cell(row, columns, field), month_first)
            if day and day.year > 1900:
                job[field] = pick(job[field], day) if job[field] else day
        if _flag(_cell(row, columns, "needs_more")):
            job["needs_more"] = 1
    out = []
    for job in jobs.values():
        if job.pop("rows") > 1 and job["ev_mm"] and job["budget_mm"]:
            job["progress"] = job["ev_mm"] / job["budget_mm"]
        job["start"], job["end"] = iso(job["start"]), iso(job["end"])
        out.append(job)
    return out


def _spend_rows(body, columns) -> List[Dict[str, Any]]:
    if "job_number" not in columns or "name" not in columns:
        raise BudgetError("The staff expenditure needs its JobNumber and "
                          "Employee Name columns.")
    if "mm" not in columns and "hours" not in columns:
        raise BudgetError("The staff expenditure has neither MM Spent nor "
                          "TotalHours.")
    out = []
    month_first = timesheets.month_first(_cell(row, columns, "day") for row in body)
    for row in body:
        number = _job(_cell(row, columns, "job_number"))
        name = _text(_cell(row, columns, "name"))
        if not number or not name:
            continue
        phase = _number(_cell(row, columns, "phase"))
        day = timesheets._coerce_date(_cell(row, columns, "day"), month_first)
        out.append({
            "job_number": number, "name": name,
            "mm": _number(_cell(row, columns, "mm")),
            "hours": _number(_cell(row, columns, "hours")) or 0.0,
            "regular_hours": _number(_cell(row, columns, "regular_hours")) or 0.0,
            "overtime_hours": _number(_cell(row, columns, "overtime_hours")) or 0.0,
            "day": day.isoformat() if day else None,
            "phase": int(phase) if phase is not None else None,
            "deliverable": _text(_cell(row, columns, "deliverable")),
            "unit": _text(_cell(row, columns, "unit")),
            "dept": _text(_cell(row, columns, "dept")),
            "grade": _text(_cell(row, columns, "grade")),
            "job_status": _text(_cell(row, columns, "job_status")),
        })
    return out


# --------------------------------------------------------------------------
# who is on the team
# --------------------------------------------------------------------------

def _same(a: str, b: str) -> bool:
    return bool(a) and a.strip().lower() == (b or "").strip().lower()


def own_unit(service) -> str:
    """The unit the team's people sit in, as the exports spell it.

    Their own timesheet rows say so; rows from before the exports carried a
    unit leave it to where the team's names sit on the staff expenditures,
    and failing that to the unit's own name.
    """
    team = set(service.workbook.engineer_names())
    counted: Dict[str, int] = defaultdict(int)
    for person, unit in service.store.latest_units().items():
        if person in team and unit:
            counted[unit.upper()] += 1
    if not counted:
        names = _team_full_names(service)
        units = set()
        for entry in service.store.job_spend():
            units.add(entry["unit"].upper())
            if entry["full_name"] in names and entry["unit"]:
                counted[entry["unit"].upper()] += 1
        name = str((getattr(service, "unit", None) or {}).get("name") or "").upper()
        if not counted and name in units:
            return name
    return max(counted, key=counted.get) if counted else ""


def _unit_of_team(service, by_job) -> str:
    """The team's unit from the incoming staff lists, when nothing held says."""
    names = _team_full_names(service)
    counted: Dict[str, int] = defaultdict(int)
    for rows in by_job.values():
        for row in rows:
            if row["name"] in names and row["unit"]:
                counted[row["unit"].upper()] += 1
    return max(counted, key=counted.get) if counted else ""


def _team_full_names(service) -> Dict[str, str]:
    """Full name on an export -> the team member whose own rows carry it."""
    team = set(service.workbook.engineer_names())
    return {full: person for full, person in
            service.store.names_by_full_name().items() if person in team}


def kind_of(name: str, unit: str, people: Dict, own: str) -> Dict[str, Any]:
    """What somebody is to the team: the manager's word, else their unit's."""
    said = people.get((name, unit))
    if said:
        return {"kind": said["kind"], "from": said["from_day"],
                "to": said["to_day"], "set": True}
    return {"kind": "team" if own and _same(unit, own) else "other",
            "from": None, "to": None, "set": False}


def counts(kind: Dict[str, Any], day: Optional[str]) -> bool:
    """Whether a day of somebody's hours is the team's."""
    if kind["kind"] in {"team", "draftsman"}:
        return True
    if kind["kind"] == "left":
        return bool(kind["to"]) and bool(day) and day <= kind["to"]
    if kind["kind"] == "loan":
        return bool(day) and (not kind["from"] or day >= kind["from"]) \
            and (not kind["to"] or day <= kind["to"])
    return False


def team_members(service, rows: Sequence[Dict[str, Any]], unit: str,
                 people: Dict) -> Dict[str, str]:
    """Full name on the export -> the team member on Team it is.

    A name their own rows already carry is certain.  Otherwise their name
    pattern on Team has to match, and the person has to be the team's (by
    unit, or by the manager's word): a pattern like ``*Ahmed*`` should not
    take in an Ahmed from another unit who booked to the same job.
    """
    seen = _team_full_names(service)
    known_for = defaultdict(set)
    for full, person in seen.items():
        known_for[person].add(full)
    matchers = [(e.short_name, pattern_to_regex(e.pattern))
                for e in service.workbook.engineers() if e.pattern]
    out: Dict[str, str] = {}
    units = {r["name"]: r.get("unit") or "" for r in rows}
    for name, their_unit in units.items():
        if name in seen:
            out[name] = seen[name]
            continue
        if kind_of(name, their_unit, people, unit)["kind"] == "other":
            continue
        hits = [short for short, rx in matchers
                if rx.match(name) and not known_for[short]]
        if len(hits) == 1:
            out[name] = hits[0]
    return out


# --------------------------------------------------------------------------
# bringing them in
# --------------------------------------------------------------------------

def bring_in(service, parsed: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Write what the uploads hold.  The caller holds the service's lock."""
    store = service.store
    hours_per_mm = service.workbook.hours_per_man_month() or 0.0
    service._copy_first()
    result: Dict[str, Any] = {"jobs_listed": 0, "has_budget": None,
                              "spend_jobs": [], "kept": [], "rows_filled": 0,
                              "warnings": []}
    projects = [p for p in parsed if p["kind"] == "projects"]
    if projects:
        jobs: Dict[str, Dict[str, Any]] = {}
        held_jobs = {j["job_number"]: j for j in store.job_budgets()}
        for item in projects:
            for job in item["jobs"]:
                number = job["job_number"]
                before = jobs.get(number) or held_jobs.get(number) or {}
                # The underlying-data export has no budget, EAC or EV column:
                # it must not wipe the budget the summarized one brought in.
                jobs[number] = {**job, "source": item["filename"],
                                **{f: before.get(f) for f in item.get("missing", ())
                                   if f in before}}
        result["jobs_listed"] = store.save_job_budgets(list(jobs.values()))
        result["has_budget"] = all(p["has_budget"] for p in projects)
        if not result["has_budget"]:
            result["warnings"].append(
                "That Projects export has no budget column. Export the "
                "Projects table as Summarized data to bring the budgets in.")

    by_job: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in parsed:
        if item["kind"] == "spend":
            # A job's staff expenditure is the whole of it: a second export
            # of the same job in one go replaces the first, never adds to it.
            in_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for row in item["rows"]:
                in_file[row["job_number"]].append(row)
            by_job.update(in_file)
    if by_job:
        unit = own_unit(service) or _unit_of_team(service, by_job)
        held = defaultdict(float)
        for entry in store.job_spend():
            held[entry["job_number"]] += entry["mm"] or 0.0
        for job, rows in sorted(by_job.items()):
            for row in rows:
                if row["mm"] is None:
                    row["mm"] = row["hours"] / hours_per_mm if hours_per_mm else 0.0
            total = sum(r["mm"] for r in rows)
            if held[job] and total < held[job] * (1 - LARGEST_SHRINK):
                result["kept"].append(job)
                result["warnings"].append(
                    f"{job}: the new staff expenditure has {total:.2f} MM, "
                    f"less than the {held[job]:.2f} MM already held, so the "
                    "last one was kept.")
                continue
            people = store.spend_people()
            members = team_members(service, rows, unit, people)
            entries, gaps = _entries(store, job, rows, members, people, unit)
            result["rows_filled"] += store.replace_job_spend(
                job, entries, gaps, SPEND_SOURCE)
            result["spend_jobs"].append(job)
    result["projects_updated"] = apply_to_register(service)
    return result


def _entries(store, job: str, rows, members: Dict[str, str], people: Dict,
             unit: str):
    """The job's spend as kept here, and the team's days it fills in."""
    entries: Dict[tuple, Dict[str, float]] = defaultdict(
        lambda: {"hours": 0.0, "overtime": 0.0, "mm": 0.0})
    covered = store.own_days(job, SPEND_SOURCE)
    gaps: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["name"], row["unit"], row["dept"], row["day"], row["phase"],
               row["deliverable"])
        entries[key]["hours"] += row["hours"]
        entries[key]["overtime"] += row["overtime_hours"]
        entries[key]["mm"] += row["mm"]
        person = members.get(row["name"])
        if person is None or not row["day"] \
                or not counts(kind_of(row["name"], row["unit"], people, unit), row["day"]):
            continue
        if (person, row["day"], row["phase"]) not in covered:
            gaps[person].append({
                "job_type": PROJECT_JOB_TYPE, "job_number": job,
                "full_name": row["name"], "date": row["day"],
                "phase": row["phase"], "regular_hours": row["regular_hours"],
                "overtime_hours": row["overtime_hours"], "hours": row["hours"],
                "deliverable": row["deliverable"], "job_status": row["job_status"],
                "grade": row["grade"], "unit": row["unit"]})
    fields = ("full_name", "unit", "dept", "day", "phase", "deliverable")
    return [{**dict(zip(fields, key)), **sums} for key, sums in entries.items()], gaps


def set_person(service, body: Dict[str, Any]) -> None:
    """Say what somebody on the staff expenditures is to the team."""
    name = _text(body.get("full_name"))
    unit = _text(body.get("unit"))
    kind = body.get("kind")
    if not name:
        raise BudgetError("Whose?")
    if kind in (None, "", "default"):
        service.store.set_spend_person(name, unit, None)
        return
    if kind not in KINDS:
        raise BudgetError("Choose my team, draftsman, other unit, left or on loan.")
    days = {}
    for field in ("from", "to"):
        value = body.get(field)
        day = timesheets._coerce_date(value) if value not in (None, "") else None
        if value not in (None, "") and day is None:
            raise BudgetError("Give the dates as days, like 01/03/2026.")
        days[field] = day.isoformat() if day else None
    if kind == "left" and not days["to"]:
        raise BudgetError("Say the day they left.")
    if kind == "loan" and days["from"] and days["to"] and days["to"] < days["from"]:
        raise BudgetError("The loan ends before it starts.")
    if kind not in {"left", "loan"}:
        days = {"from": None, "to": None}
    if kind == "left":
        days["from"] = None
    service.store.set_spend_person(name, unit, kind, days["from"], days["to"])
    # The days it fills in for the team change with it.
    refill(service)
    apply_to_register(service)


def refill(service) -> int:
    """Work the gap rows out again from the staff expenditures held."""
    store = service.store
    unit = own_unit(service)
    people = store.spend_people()
    by_job: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in store.job_spend():
        by_job[e["job_number"]].append(
            {"job_number": e["job_number"], "name": e["full_name"],
             "unit": e["unit"], "dept": e["dept"], "day": e["day"],
             "phase": e["phase"], "deliverable": e["deliverable"],
             "hours": e["hours"], "mm": e["mm"],
             "regular_hours": e["hours"] - e["overtime"],
             "overtime_hours": e["overtime"], "grade": "", "job_status": ""})
    added = 0
    for job, rows in by_job.items():
        members = team_members(service, rows, unit, people)
        entries, gaps = _entries(store, job, rows, members, people, unit)
        added += store.replace_job_spend(job, entries, gaps, SPEND_SOURCE)
    return added


def set_share(service, job: str, percent: Any) -> None:
    job = _job(job)
    if not job:
        raise BudgetError("Which job?")
    if percent in (None, ""):
        share = None
    else:
        value = _number(percent)
        if value is None or not 0 <= value <= 100:
            raise BudgetError("The team's share is a percentage from 0 to 100.")
        share = value / 100
    service.store.set_job_share(job, share)
    apply_to_register(service)


def apply_to_register(service) -> List[str]:
    """Put the team's budget on its projects, where nobody has typed one.

    A project follows BISpark if its budget is still the one this last put
    there, or -- the first time -- if it was set up from timesheets and its
    budget is still a stand-in.  A budget typed by hand is left alone; the
    Budgets tab shows the difference instead.
    """
    wb = service.workbook
    store = service.store
    view = {j["job_number"]: j for j in _jobs(service)}
    held = {j["job_number"]: j for j in store.job_budgets()}
    updated = []
    for project in wb.projects():
        job = view.get(project.number)
        if job is None or job["team_budget_mm"] is None:
            continue
        target = round(job["team_budget_mm"], 2)
        if target <= 0:
            continue
        applied = held[project.number]["applied_budget_mm"]
        if project.budget_mm is None:
            follows = True
        elif applied is not None:
            follows = abs(project.budget_mm - applied) < 0.005
        else:
            follows = derive.needs_confirming(project.notes)
        if not follows:
            continue
        if project.budget_mm is None or abs(project.budget_mm - target) >= 0.005:
            try:
                wb.update_project(project.number,
                                  {**project.to_dict(), "budget_mm": target})
            except ValidationError:
                continue
            updated.append(project.number)
        if applied is None or abs(applied - target) >= 0.005:
            store.set_applied_budget(project.number, target)
    return updated


# --------------------------------------------------------------------------
# the requests the manager's PC sends
# --------------------------------------------------------------------------

def requests(service) -> Dict[str, Any]:
    raw = service.store.setting(REQUESTS_SETTING)
    return json.loads(raw) if raw else {}


def requests_info(service) -> Dict[str, Any]:
    held = requests(service)
    return {"projects": "projects" in held, "spend": "spend" in held,
            "spend_job": (held.get("spend") or {}).get("job", "")}


def save_requests(service, body: Dict[str, Any], parse_capture) -> Dict[str, Any]:
    """Keep a pasted Projects or staff expenditure request, or both.

    The staff expenditure request is for one job; the job number in it is
    swapped for a slot, so the PC can ask the same of every job.
    """
    held = requests(service)
    if str(body.get("projects_capture") or "").strip():
        held["projects"] = parse_capture(body["projects_capture"])
    if str(body.get("spend_capture") or "").strip():
        request = parse_capture(body["spend_capture"])
        found = sorted(set(_JOB_NUMBER.findall(request["body"])))
        if len(found) != 1:
            raise BudgetError(
                "Copy the staff expenditure request from one project's MH "
                "Expenditure page, with that one project chosen.")
        request["body"] = request["body"].replace(found[0], JOB_SLOT)
        request["job"] = found[0]
        held["spend"] = request
    for name in ("projects", "spend"):
        if body.get(f"forget_{name}"):
            held.pop(name, None)
    service.store.set_setting(REQUESTS_SETTING, json.dumps(held) if held else None)
    return requests_info(service)


def jobs_to_fetch(service) -> List[str]:
    """The jobs the PC asks for the staff expenditure of, most live first."""
    order = {"active": 0, "on-hold": 1, "pending": 2, "not started": 3}
    listed = [j for j in service.store.job_budgets() if j["listed"]]
    listed.sort(key=lambda j: (order.get((j["status"] or "").lower(), 4),
                               -(j["spent_mm"] or 0)))
    return [j["job_number"] for j in listed][:MAX_SPEND_EXPORTS]


# --------------------------------------------------------------------------
# the view
# --------------------------------------------------------------------------

def _jobs(service, as_at: Optional[_dt.date] = None) -> List[Dict[str, Any]]:
    """Every job with a budget or a spend, worked out for the team."""
    as_at = as_at or today()
    wb = service.workbook
    store = service.store
    unit = own_unit(service)
    people = store.spend_people()
    hours_per_mm = wb.hours_per_man_month() or 0.0
    team = set(wb.engineer_names())
    budgets = {j["job_number"]: j for j in store.job_budgets()}
    spend = defaultdict(list)
    for entry in store.job_spend():
        spend[entry["job_number"]].append(entry)
    projects = {p.number: p for p in wb.projects()}
    own_hours = defaultdict(list)
    for row in store.all_rows():
        if row["engineer"] in team and row["job_number"]:
            own_hours[row["job_number"]].append(row)
    pace_from = as_at - _dt.timedelta(days=PACE_DAYS)

    numbers = [n for n, j in budgets.items()
               if j["imported_at"] or j["job_number"] in spend]
    numbers += [n for n in spend if n not in budgets]
    out = []
    for number in numbers:
        job = budgets.get(number) or {}
        entries = spend.get(number, [])
        kinds = {}
        for e in entries:
            if (e["full_name"], e["unit"]) not in kinds:
                kinds[(e["full_name"], e["unit"])] = kind_of(
                    e["full_name"], e["unit"], people, unit)
        mine = [e for e in entries
                if counts(kinds[(e["full_name"], e["unit"])], e["day"])]
        dept = job.get("dept") or _most(e["dept"] for e in mine) \
            or _most(e["dept"] for e in entries)
        in_dept = [e for e in entries if not dept or not e["dept"] or e["dept"] == dept]
        dept_mm = sum(e["mm"] for e in in_dept)
        # Only what the team booked to this department's budget is a share
        # of it: hours booked to another department's would make it over 100%.
        counted_in_dept = {id(e) for e in in_dept}
        own_mm = sum(e["mm"] for e in mine if id(e) in counted_in_dept)
        guess = own_mm / dept_mm if dept_mm > 0 else None
        share = job.get("team_share")
        if share is not None:
            basis = "set"
        elif guess is not None:
            share, basis = guess, "booked"
        else:
            share, basis = 1.0, "unknown"
        budget = job.get("budget_mm")
        team_budget = budget * share if budget is not None else None
        if entries:
            spent_days = [(e["day"], e["mm"]) for e in mine]
            spent_from = "staff"
        else:
            spent_days = [(iso(r["date"]), r["hours"] / hours_per_mm)
                          for r in own_hours.get(number, []) if hours_per_mm]
            spent_from = "timesheets" if spent_days else "none"
        team_spent = sum(mm for _, mm in spent_days)
        recent = sum(mm for day, mm in spent_days
                     if day and pace_from.isoformat() < day <= as_at.isoformat())
        pace = recent / (PACE_DAYS / DAYS_A_MONTH)
        left = team_budget - team_spent if team_budget is not None else None
        months_left = left / pace if left is not None and left > 0 and pace > 0 else None
        # A trickle of hours against a big budget lasts for centuries: past
        # LONGEST_RUN it does not run out, and a date that far is no date.
        runs_out = (as_at + _dt.timedelta(days=round(months_left * DAYS_A_MONTH))
                    if months_left is not None and months_left <= LONGEST_RUN
                    else None)
        project = projects.get(number)
        end = stored_date(job.get("end")) or (project.end if project else None)
        status = job.get("status") or (project.status if project else "")
        listed = bool(job.get("listed")) or (not job and bool(entries))
        state = _state(budget, left, runs_out, end, status, as_at) if listed else "closed"
        counted_ids = {id(e) for e in mine}
        others = [e for e in entries if id(e) not in counted_ids]
        out.append({
            "job_number": number,
            "title": job.get("title") or (project.name if project else ""),
            "lead": job.get("lead") or "", "status": status, "dept": dept or "",
            "listed": listed, "last_seen": (job.get("imported_at") or "")[:10] or None,
            "budget_mm": _r(budget), "spent_mm": _r(job.get("spent_mm")),
            "remaining_mm": _r(job.get("remaining_mm")),
            "eac_mm": _r(job.get("eac_mm")), "progress": job.get("progress"),
            "start": job.get("start"), "end": iso(end),
            "needs_more": bool(job.get("needs_more")),
            "share": share, "share_basis": basis, "share_guess": guess,
            "team_budget_mm": _r(team_budget), "team_spent_mm": _r(team_spent),
            "team_left_mm": _r(left), "spent_from": spent_from,
            "pace_mm_a_month": _r(pace), "runs_out": iso(runs_out),
            "state": state,
            "in_register": project is not None,
            "project_budget_mm": _r(project.budget_mm) if project else None,
            "follows_bispark": bool(project) and job.get("applied_budget_mm") is not None
                and project.budget_mm is not None
                and abs(project.budget_mm - job["applied_budget_mm"]) < 0.005,
            "people": _people(mine, kinds),
            "other_units_mm": _r(sum(e["mm"] for e in others)),
            "months": _months(spent_days, as_at),
            "updated": max([e["imported_at"] for e in entries]
                           + [job.get("imported_at") or ""])[:10] or None,
        })
    rank = {"over": 0, "short": 1, "ok": 2, "paused": 3, "no_budget": 4, "closed": 5}
    out.sort(key=lambda j: (rank.get(j["state"], 6), -(j["team_spent_mm"] or 0)))
    return out


def _state(budget, left, runs_out, end, status, as_at) -> str:
    if not budget:
        return "no_budget"
    if left is not None and left < -0.005:
        return "over"
    if (status or "").lower() in {"on-hold", "on hold"}:
        return "paused"
    if runs_out and end and runs_out < end and end >= as_at:
        return "short"
    return "ok"


def _most(values: Iterable[str]) -> str:
    counted: Dict[str, int] = defaultdict(int)
    for value in values:
        if value:
            counted[value] += 1
    return max(counted, key=counted.get) if counted else ""


def _r(value: Optional[float], places: int = 2) -> Optional[float]:
    return None if value is None else round(value, places)


def _people(entries, kinds) -> List[Dict[str, Any]]:
    sums: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        item = sums.setdefault(e["full_name"], {
            "name": e["full_name"], "mm": 0.0, "last_day": None,
            "kind": kinds[(e["full_name"], e["unit"])]["kind"]})
        item["mm"] += e["mm"]
        if e["day"] and (item["last_day"] is None or e["day"] > item["last_day"]):
            item["last_day"] = e["day"]
    return sorted(({**p, "mm": _r(p["mm"])} for p in sums.values()),
                  key=lambda p: -p["mm"])


def _months(spent_days, as_at: _dt.date, count: int = 12) -> List[Dict[str, Any]]:
    keys = []
    year, month = as_at.year, as_at.month
    for _ in range(count):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    keys.reverse()
    sums = dict.fromkeys(keys, 0.0)
    for day, mm in spent_days:
        if day and day[:7] in sums:
            sums[day[:7]] += mm
    return [{"month": k, "mm": _r(v)} for k, v in sums.items()]


def people_on_jobs(service) -> List[Dict[str, Any]]:
    """Everybody on the staff expenditures, and what they are to the team."""
    store = service.store
    unit = own_unit(service)
    people = store.spend_people()
    sums: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in store.job_spend():
        key = (e["full_name"], e["unit"])
        item = sums.setdefault(key, {"name": key[0], "unit": key[1], "mm": 0.0,
                                     "jobs": set(), "first_day": None,
                                     "last_day": None})
        item["mm"] += e["mm"]
        item["jobs"].add(e["job_number"])
        if e["day"]:
            item["first_day"] = min(item["first_day"] or e["day"], e["day"])
            item["last_day"] = max(item["last_day"] or e["day"], e["day"])
    out = []
    for key, item in sums.items():
        kind = kind_of(key[0], key[1], people, unit)
        out.append({**item, "mm": _r(item["mm"]), "jobs": len(item["jobs"]),
                    "unit_label": item["unit"].title() if item["unit"].isupper() else item["unit"],
                    "kind": kind["kind"], "kind_label": KINDS[kind["kind"]],
                    "from": kind["from"], "to": kind["to"], "set": kind["set"]})
    counted_first = {"team": 0, "draftsman": 1, "loan": 2, "left": 3, "other": 4}
    out.sort(key=lambda p: (counted_first[p["kind"]], -p["mm"]))
    return out


def view(service) -> Dict[str, Any]:
    jobs = _jobs(service)
    unit = own_unit(service)
    live = [j for j in jobs if j["listed"]]
    with_budget = [j for j in live if j["team_budget_mm"] is not None]
    total = lambda key, rows: _r(sum(j[key] or 0 for j in rows))
    todo = []
    over = [j for j in live if j["state"] == "over"]
    short = [j for j in live if j["state"] == "short"]
    guessed = [j for j in live if j["share_basis"] == "unknown" and j["budget_mm"]]
    needs = [j for j in live if j["needs_more"] and j["state"] != "over"]
    typed = [j for j in live if j["in_register"] and j["team_budget_mm"]
             and not j["follows_bispark"] and j["project_budget_mm"] is not None
             and abs(j["project_budget_mm"] - j["team_budget_mm"]) >= 0.05]
    people = people_on_jobs(service)
    unsure = [p for p in people if not p["set"] and p["kind"] == "other"
              and p["mm"] >= 0.25]
    if over:
        todo.append({"level": "now", "jobs": [j["job_number"] for j in over],
                     "text": f"{_count(over, 'job')} past the team's budget. Agree more "
                             "budget with the project manager, or stop booking to it."})
    if short:
        todo.append({"level": "soon", "jobs": [j["job_number"] for j in short],
                     "text": f"{_count(short, 'job')} will run out before the end at this "
                             "pace. Slow the hours down or ask for more budget now."})
    if needs:
        todo.append({"level": "soon", "jobs": [j["job_number"] for j in needs],
                     "text": f"BISpark says {_count(needs, 'job')} need more effort than "
                             "is left. Raise it at the next project meeting."})
    if guessed:
        todo.append({"level": "note", "jobs": [j["job_number"] for j in guessed],
                     "text": f"{_count(guessed, 'job')} have no staff expenditure yet, "
                             "so the team is counted as all of the budget. Set your share."})
    if unsure:
        todo.append({"level": "note", "people": [p["name"] for p in unsure],
                     "text": f"{_count(unsure, 'person', 'people')} from other units booked "
                             "to your jobs. Mark any draftsman or loan in People on your jobs."})
    if typed:
        todo.append({"level": "note", "jobs": [j["job_number"] for j in typed],
                     "text": f"{_count(typed, 'project')} have a budget typed by hand "
                             "that differs from BISpark's. Check which is right."})
    held = service.store.job_budgets()
    return {
        "unit": unit.title() if unit.isupper() else unit,
        "jobs": jobs,
        "people": people,
        "kinds": [{"value": k, "label": v} for k, v in KINDS.items()],
        "todo": todo,
        "totals": {
            "jobs": len(live), "closed": len(jobs) - len(live),
            "team_budget_mm": total("team_budget_mm", with_budget),
            "team_spent_mm": total("team_spent_mm", with_budget),
            "team_left_mm": total("team_left_mm", with_budget),
            "dept_budget_mm": total("budget_mm", with_budget),
            "over": len(over), "short": len(short),
        },
        "has_list": any(j["listed"] for j in held),
        "list_updated": (max((j["imported_at"] or "" for j in held if j["listed"]),
                             default="") or "")[:10] or None,
        "requests": requests_info(service),
        "max_spend_exports": MAX_SPEND_EXPORTS,
    }


def _count(items, noun: str, plural: str = "") -> str:
    return f"{len(items)} {noun if len(items) == 1 else plural or noun + 's'}"
