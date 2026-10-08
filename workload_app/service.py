"""One open unit, and every change that can be made to it.

The service is the app's working memory: it holds the unit a person has open,
serialises access to it, and turns each request into a domain call.  It knows
nothing about HTTP, and nothing about who is logged in -- one account's service
instance simply never sees another account's unit.
"""

from __future__ import annotations

import base64
import datetime as _dt
import functools
import json
import threading
import traceback
import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from . import (calendar_, checkins as checkins_module, config as cfg, daily, derive,
               growth as growth_module, management as management_module,
               drawing_list as drawing_list_module,
               drawings as drawings_module, holidays as holidays_module,
               incoming, intake, metrics, myday, needs as needs_module,
               people as people_module, submissions as submissions_module,
               planner as planner_module, progress, reports,
               tasks as task_sheet, timesheets)
from .timesheet_store import TimesheetStore
from .timesheets import ParsedTimesheet
from .model import ValidationError, iso, today as _model_today
from . import emails as emails_module
from . import unit as unit_module
from . import weekly as weekly_module
from .unit import Unit, outside_message

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
#: How far ahead the Planner lists who will be away.
AWAY_AHEAD_DAYS = 60
#: The stretch public holidays are worked out for: back far enough for a
#: pace, ahead far enough for the staffing forecast.
HOLIDAYS_BEHIND_DAYS = 120
HOLIDAYS_AHEAD_DAYS = 400
#: Where the countries a unit's holidays come from are kept.
HOLIDAY_SETTING = "holiday_calendar"


#: Which person in the unit the signed-in manager is ("this is me"), one per
#: account.  Apart from the email inbox's own address (``inbox_me:``).
ME_PREFIX = "team_me:"


def me_key(user_id: int) -> str:
    return f"{ME_PREFIX}{int(user_id)}"


class ApiError(Exception):
    def __init__(self, status: int, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.errors = errors or [message]



def _remembered(method):
    """A read whose answer is kept until the unit is next written.

    Every tab asks for its figures again each time it is shown, and most of
    them start from the same rows; worked out once per revision of the unit,
    they cost one lookup after that.  The answer depends on the unit's data
    (the revision), the arguments, which unit this is, and today's date --
    all of which are part of the key.  Each caller gets its own copy.
    """
    @functools.wraps(method)
    def remembered(self, *args):
        with self._lock:
            wb = self.workbook
            key = ("view", method.__name__, json.dumps(
                [args, self.unit, self.read_only, self._unlocked],
                sort_keys=True, default=str), _today().isoformat())
            return unit_module.fresh_copy(
                wb._cached(key, lambda: method(self, *args)))
    return remembered


class WorkloadService:
    """Holds the chosen unit, if one is open yet, and serialises access."""

    def __init__(self, path: Optional[Path] = None, *, autosave: bool = True):
        self.path: Optional[Path] = None
        self.unit: Optional[Dict[str, Any]] = None
        #: Kept for the callers that pass it; every change is written at once.
        self.autosave = autosave
        self._lock = threading.RLock()
        self._wb: Optional[Unit] = None
        self._staged: Dict[str, Any] = {}
        self._unlocked = False
        #: The unit's timesheet rows and planning tables, in the same file.
        self._store: Optional[TimesheetStore] = None
        #: A member's view of somebody else's unit never changes it.
        self.read_only = False
        #: Takes a dated copy of the unit, before a change that replaces a lot
        #: at once; the app knows where copies go, so it hands this in.
        self.keep_copy: Optional[Callable[[], Any]] = None
        if path is not None:
            self.open(path)

    # -- choosing a unit -------------------------------------------------
    @property
    def workbook(self) -> Unit:
        """The open unit, or a clear refusal if none has been chosen.

        Still called ``workbook`` because so much calls it that; it has not
        been one for a while.
        """
        if self._wb is None:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "No unit is open. Choose one of your units first.",
            )
        return self._wb

    def open(self, path: Union[str, Path], *,
             unit: Optional[Dict[str, Any]] = None,
             read_only: bool = False,
             keep_copy: Optional[Callable[[], Any]] = None) -> Dict[str, Any]:
        """Open a unit's database, and remember which unit it is.

        ``read_only`` is for a member looking at their manager's unit: nothing
        is written to it.
        """
        with self._lock:
            resolved = Path(path)
            if not resolved.is_file():
                raise ApiError(HTTPStatus.NOT_FOUND,
                               "That unit's data is missing.")
            self._wb = unit_module.shared(resolved)
            self.path = resolved
            self.unit = unit
            self.read_only = read_only
            self.keep_copy = keep_copy
            self._staged.clear()
            self._unlocked = False
            self._store = self._wb.store
            return self.status()

    def _index(self, wb: Unit) -> "metrics.TimesheetIndex":
        """The timesheet rows, indexed; built once per revision of the unit."""
        if self._store is not getattr(wb, "store", None):
            return metrics.TimesheetIndex(wb, self._store)
        return wb._cached("index", lambda: metrics.TimesheetIndex(wb, self._store))

    @property
    def store(self) -> "TimesheetStore":
        """The unit's timesheet rows."""
        if self._store is None:
            raise ApiError(HTTPStatus.CONFLICT,
                           "No unit is open. Choose one of your units first.")
        return self._store

    def close(self) -> Dict[str, Any]:
        with self._lock:
            self._wb = None
            self.path = None
            self.unit = None
            self._store = None
            self.read_only = False
            self.keep_copy = None
            self._unlocked = False
            self._staged.clear()
            return self.status()

    def refresh(self) -> None:
        """Forget what was read if another worker has written the unit since."""
        with self._lock:
            if self._wb is not None:
                self._wb.refresh()

    def _copy_first(self) -> None:
        """A dated copy of the unit before a change that replaces a lot."""
        if self.keep_copy is None or self.read_only:
            return
        try:
            self.keep_copy()
        except Exception:                  # pragma: no cover - a copy is a
            traceback.print_exc()          # nicety, never a reason to refuse

    def _commit(self) -> Dict[str, Any]:
        """Every change is written as it is made; this says so."""
        if self.read_only:
            raise ApiError(HTTPStatus.FORBIDDEN,
                           "This unit is open for reading only.")
        return {"saved": True}

    def _known_job_numbers(self) -> set:
        wb = self.workbook
        return {p.number for p in wb.projects()} | set(wb.non_project_codes())

    # -- reads -----------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self._lock:
            if self._wb is None:
                return {"open": False, "workbook": None, "unit": None,
                        "autosave": self.autosave}
            counts = self._wb.summary()
            return {
                "open": True,
                "unit": self.unit,
                "reference_unlocked": self._unlocked,
                "engineers": self._wb.engineer_names(),
                "workbook": str(self.path),
                "workbook_name": self.path.name,
                "folder": str(self.path.parent),
                "autosave": self.autosave,
                "unsaved_changes": False,
                "projects": counts["projects"],
                "deliverables": counts["deliverables"],
                "timesheet_rows": counts["rows"],
                "tasks": counts["tasks"],
                "backups": str(self.path.parent / cfg.BACKUP_DIRNAME),
            }

    def reference(self) -> Dict[str, Any]:
        with self._lock:
            return self.workbook.reference()

    @_remembered
    def overview(self, year: Optional[int]) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            index = self._index(wb)
            data = metrics.overview(wb, year, self._store, index=index)
            data["available_years"] = metrics.available_years(wb, index)
            return data

    @_remembered
    def projects(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            index = self._index(wb)
            rows = metrics.project_rows(wb, index)
            return {
                "projects": [p.to_dict() for p in wb.projects()],
                "metrics": rows,
                "drawings": self._drawings(wb, index, rows)["projects"],
            }

    @_remembered
    def deliverables(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            index = self._index(wb)
            return {
                "deliverables": [d.to_dict() for d in wb.deliverables()],
                "metrics": metrics.deliverable_rows(wb, index),
            }

    # -- the team --------------------------------------------------------
    def team(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            return {
                "engineers": wb.team(),
                "years": wb.availability_years(),
            }

    def team_me(self, user_id: int) -> Dict[str, Any]:
        """Which of the unit's people the signed-in manager is, if they said."""
        with self._lock:
            me = self.store.setting(me_key(user_id)) or ""
            known = {p["short_name"] for p in self.workbook.team()}
            return {"me": me if me in known else ""}

    def set_team_me(self, user_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            me = " ".join(str(body.get("me") or "").split())
            if me and me not in {p["short_name"] for p in self.workbook.team()}:
                raise ApiError(HTTPStatus.NOT_FOUND,
                               f"{me} is not in this unit's team.")
            self.store.set_setting(me_key(user_id), me or None)
            return {"me": me}

    def add_engineer(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.add_engineer(body)
            result["save"] = self._commit()
            return result

    def update_engineer(self, engineer: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.update_engineer(engineer, body)
            result["save"] = self._commit()
            return result

    def remove_engineer(self, engineer: str) -> Dict[str, Any]:
        with self._lock:
            self.workbook._require_engineer(engineer)    # noqa: SLF001
            self._copy_first()
            result = self.workbook.remove_engineer(engineer)
            result["save"] = self._commit()
            return result

    @_remembered
    def reports(self, kind: str, year: Optional[int],
                quarter: Optional[str]) -> Dict[str, Any]:
        """Every report figure for one period, computed in a single pass."""
        with self._lock:
            wb = self.workbook
            index = self._index(wb)
            data = reports.build(wb, kind, year, quarter, index=index).to_dict()
            data["periods"] = self._periods(wb)
            data["unit"] = self.unit
            data["issues"] = wb.register_issues()
            data["definitions"] = wb.definitions()
            period = data["period"]
            data["data_check"] = wb.data_check(
                period["year"] if period["kind"] == "year" else None,
                store=self._store)
            return data

    def _periods(self, wb) -> Dict[str, Any]:
        quarters = reports.read_quarters(wb)
        years = sorted({q.year for q in quarters if q.year})
        return {
            "years": years,
            "quarters": sorted({q.label.split("-")[0] for q in quarters
                                if not q.opening}),
            "plan_year": wb.plan_year(),
        }

    def timesheet_status(self) -> Dict[str, Any]:
        with self._lock:
            return self.workbook.data_check(store=self._store)

    # -- writes ----------------------------------------------------------
    def add_project(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            project = self.workbook.add_project(body)
            return {"project": project.to_dict(), "save": self._commit()}

    def update_project(self, number: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            project = self.workbook.update_project(number, body)
            return {"project": project.to_dict(), "save": self._commit()}

    def delete_project(self, number: str, cascade: bool) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.delete_project(number, cascade=cascade)
            result["save"] = self._commit()
            return result

    def add_deliverable(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            deliverable = self.workbook.add_deliverable(body)
            return {"deliverable": deliverable.to_dict(), "save": self._commit()}

    def update_deliverable(self, row: int, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            deliverable = self.workbook.update_deliverable(row, body)
            return {"deliverable": deliverable.to_dict(), "save": self._commit()}

    def save_project_with_deliverables(self, number: Optional[str],
                                       body: Dict[str, Any]) -> Dict[str, Any]:
        """Save a project and its whole deliverable set in one go."""
        with self._lock:
            project = dict(_object(body.get("project") or {}, "project"))
            # Saving a project the timesheets set up is somebody confirming it.
            if derive.needs_confirming(project.get("notes") or ""):
                project["notes"] = (project["notes"] or "").replace(
                    derive.TO_CONFIRM, "").strip()
            items = _objects(body.get("deliverables") or [], "deliverables")
            # Drawings are checked before anything is written, so a typo in
            # one count does not leave the project saved without its drawings.
            counts = [drawings_module.clean_count(item.get("drawings"))
                      if "drawings" in item else drawings_module.KEEP
                      for item in items]
            result = self.workbook.save_project_with_deliverables(
                number, project, items)
            for written, count in zip(result["deliverables"], counts):
                if count is not drawings_module.KEEP:
                    self.store.set_drawings(written["row"],
                                            written["project_number"], count)
                    written["drawings"] = count
            result["save"] = self._commit()
            return result

    def project_detail(self, number: str) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            project = wb.project(number)
            if project is None:
                raise ApiError(HTTPStatus.NOT_FOUND,
                               f"No project numbered {number!r}.")
            index = self._index(wb)
            rows = {m["row"]: m for m in metrics.deliverable_rows(wb, index)}
            attached = [d for d in wb.deliverables()
                        if d.project_number == project.number]
            drawn = drawings_module.counts(self.store, attached)
            figures = [m for m in metrics.project_rows(wb, index)
                       if m["number"] == project.number]
            return {
                "project": project.to_dict(),
                "metrics": figures[0] if figures else None,
                "deliverables": [
                    {**d.to_dict(), "computed": rows.get(d.row),
                     "drawings": drawn.get(d.row)} for d in attached
                ],
            }

    def delete_deliverable(self, row: int) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.delete_deliverable(row)
            self.store.set_drawings(row, "", None)
            self.store.clear_drawing_list_row(row)
            result["save"] = self._commit()
            return result

    def save(self) -> Dict[str, Any]:
        """Nothing to do: kept so an old screen's Save button still answers."""
        with self._lock:
            return {"saved": self._wb is not None}

    def reload(self) -> Dict[str, Any]:
        with self._lock:
            self.workbook.reload()
            return self.status()

    # -- timesheets ------------------------------------------------------
    def stage_timesheet(self, engineer: str, filename: str, data: bytes,
                        *, registered_only: bool = True) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            if engineer not in wb.engineer_names():
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    f"{engineer!r} is not on this unit's team "
                    f"({', '.join(wb.engineer_names())}).",
                )
            engineers = {e.short_name: e for e in wb.engineers()}
            pattern = engineers[engineer].pattern if engineer in engineers else None
            parsed = timesheets.parse(
                engineer, filename, data, wb.timesheet_headers(engineer),
                name_pattern=pattern,
                known_job_numbers=self._known_job_numbers(),
                registered_only=registered_only,
                keep_job_types=cfg.PROPOSAL_JOB_TYPES,
            )
            existing = self.store.rows_for(engineer)
            duplicates = _duplicates(existing, parsed.records()) if parsed.rows else 0
            token = uuid.uuid4().hex
            self._staged[token] = parsed
            payload = parsed.to_dict()
            payload["token"] = token
            payload["existing_rows"] = len(existing)
            payload["duplicate_rows_if_appended"] = duplicates
            return payload

    def apply_timesheet(self, token: str, mode: str) -> Dict[str, Any]:
        with self._lock:
            parsed = self._staged.pop(token, None)
            if not isinstance(parsed, ParsedTimesheet):
                raise ApiError(
                    HTTPStatus.NOT_FOUND,
                    "That import has expired. Upload the export again.",
                )
            if parsed.errors:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "The export still has errors that must be fixed first.",
                    parsed.errors,
                )
            if mode not in {"append", "replace"}:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "Mode must be 'replace' (the monthly routine) or 'append'.",
                )
            wb = self.workbook
            records = parsed.records()
            store = self.store
            if mode == "replace":
                self._copy_first()
            # No room to make and no limit to raise: the rows go to the store,
            # which has neither.
            written = (store.append(parsed.engineer, records)
                       if mode == "append"
                       else store.replace(parsed.engineer, records))
            result = {
                "engineer": parsed.engineer,
                # "rows" is what this person now holds, which is what the
                # sheet-based import used to report.
                "rows": store.counts().get(parsed.engineer, 0),
                "rows_written": written,
                "rows_held": store.counts().get(parsed.engineer, 0),
                "rows_in_unit": store.count(),
                "mode": mode,
                "capacity_raised": None,
            }
            result["save"] = self._commit()
            result["data_check"] = wb.data_check(store=store)
            return result

    # -- timesheets as the only input ------------------------------------
    #
    # The routine above wants the engineer chosen first and the projects in
    # the register before their hours will count. These two need neither: the
    # exports say who booked and to what, so the people and the projects are
    # read out of them, and only the hours have to be supplied at all.

    def stage_exports(self, files: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Read any number of exports, for anyone, and say what they will do."""
        with self._lock:
            wb = self.workbook
            if not files:
                raise ApiError(HTTPStatus.BAD_REQUEST,
                               "Choose at least one timesheet export.")
            headers = wb.timesheet_headers()
            parsed: List[ParsedTimesheet] = []
            errors: List[str] = []
            warnings: List[str] = []
            for item in _objects(files, "files"):
                filename = str(item.get("filename") or "export.xlsx")
                data = _decode(item.get("content_base64"))
                try:
                    result = timesheets.parse("", filename, data, headers)
                except timesheets.ImportError_ as error:
                    errors.append(f"{filename}: {error}")
                    continue
                errors.extend(f"{filename}: {m}" for m in result.errors)
                # Unknown job numbers are not a problem here: they are the
                # projects this import is about to set up.
                warnings.extend(
                    f"{filename}: {m}" for m in result.warnings
                    if not m.startswith("Job numbers charged but not"))
                parsed.append(result)

            records = [r for p in parsed if p.ok for r in p.records()]
            if not records and not errors:
                errors.append("None of the files held any timesheet rows.")
            people = self._people_in(records)
            for record in records:
                record["engineer"] = people[record["full_name"]]["name"]

            plan = self._plan(records)
            outside = self._without_a_place(people)
            if outside:
                warnings.append(outside_message(outside))
            token = uuid.uuid4().hex
            self._staged[token] = {"records": records, "people": people,
                                   "files": [p.source_name for p in parsed]}
            dates = [r["date"] for r in records if r.get("date")]
            return {
                "token": token,
                "files": [p.source_name for p in parsed],
                "errors": errors,
                "warnings": warnings,
                "rows": len(records),
                "hours": round(sum(r["hours"] for r in records), 2),
                "first_date": min(dates).isoformat() if dates else None,
                "last_date": max(dates).isoformat() if dates else None,
                "unit_name": derive.unit_name(records),
                "people": sorted((
                    {"full_name": full, **info,
                     "rows": sum(1 for r in records if r["full_name"] == full),
                     "hours": round(sum(r["hours"] for r in records
                                        if r["full_name"] == full), 2)}
                    for full, info in people.items()),
                    key=lambda p: -p["hours"]),
                "people_outside_workbook": outside,
                "new_projects": derive.describe(plan["fits"]),
                "projects_left_out": derive.describe(plan["left_out"]),
            }

    def apply_exports(self, token: str, mode: str = "replace") -> Dict[str, Any]:
        """Write staged exports: the people, their rows, then the projects."""
        with self._lock:
            staged = self._staged.pop(token, None)
            if not isinstance(staged, dict):
                raise ApiError(HTTPStatus.NOT_FOUND,
                               "That import has expired. Choose the files again.")
            if mode not in {"append", "replace"}:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "Mode must be 'replace' (the monthly routine) or 'append'.")
            wb = self.workbook
            store = self.store
            if mode == "replace":
                self._copy_first()
            # Grades only for people the establishment does not know yet, so
            # a grade somebody set by hand is never undone by an import.
            graded = {p["name"] for p in store.people()}
            people_added = self._set_up_people(staged["people"])

            by_person: Dict[str, List[Dict[str, Any]]] = {}
            for record in staged["records"]:
                by_person.setdefault(record["engineer"], []).append(record)
            written = 0
            for person, rows in by_person.items():
                written += (store.append(person, rows) if mode == "append"
                            else store.replace(person, rows))

            for person, title in derive.latest_by_person(
                    staged["records"], "grade").items():
                grade = derive.grade_for(title)
                if grade and person not in graded:
                    store.save_person(person, grade=grade)

            teams = people_module.teams_from_timesheets(
                store, lambda: uuid.uuid4().hex[:12])
            projects = self._add_derived_projects()
            placed = set(wb.engineer_names())
            result = {
                "teams_from_timesheets": teams,
                "rows_written": written,
                "rows_in_unit": store.count(),
                "mode": mode,
                "people": sorted(by_person),
                "people_added": people_added,
                "people_outside_workbook": [
                    name for name in sorted(by_person) if name not in placed],
                **projects,
            }
            result["save"] = self._commit()
            result["data_check"] = wb.data_check(store=store)
            return result

    def import_exports(self, files: Sequence[Dict[str, Any]],
                       mode: str = "replace") -> Dict[str, Any]:
        """Stage and write in one go, for a unit being set up from scratch."""
        staged = self.stage_exports(files)
        if staged["errors"]:
            self._staged.pop(staged["token"], None)
            raise ApiError(HTTPStatus.BAD_REQUEST,
                           "Those files could not be read as timesheet exports.",
                           staged["errors"])
        result = self.apply_exports(staged["token"], mode)
        result["staged"] = staged
        return result

    def sync_projects(self) -> Dict[str, Any]:
        """Add any project the timesheets already held imply, on request."""
        with self._lock:
            result = self._add_derived_projects()
            result["save"] = self._commit()
            return result

    def _people_in(self, records: Sequence[Dict[str, Any]]
                   ) -> Dict[str, Dict[str, Any]]:
        """Who each full name in the rows is, in this unit.

        Somebody already on the team is matched by their Work Calendar
        pattern, as the per-engineer import always did; anybody else gets a
        short name of their own and is marked new.
        """
        wb = self.workbook
        engineers = wb.engineers()
        matchers = [(e.short_name, timesheets._wildcard(e.pattern))
                    for e in engineers if e.pattern]
        established = set(self.store.people_with_rows()) | {
            p["name"] for p in self.store.people()}
        # Somebody with rows but no place on the team has no pattern to
        # match, so the rows they already have say who they are.
        seen = self.store.names_by_full_name()
        out: Dict[str, Dict[str, Any]] = {}
        unknown: List[str] = []
        for full in dict.fromkeys(r["full_name"] for r in records):
            hit = next((short for short, rx in matchers if rx.match(full)), None)
            if hit is None:
                hit = seen.get(full) or (full if full in established else None)
            if hit is None:
                unknown.append(full)
            else:
                out[full] = {"name": hit, "new": False}
        taken = {e.short_name for e in engineers} | established
        for full, short in derive.short_names(unknown, taken).items():
            out[full] = {"name": short, "new": True}
        return out

    def _set_up_people(self, people: Dict[str, Dict[str, Any]]) -> List[str]:
        """Put everybody new on the team.  There is no limit to how many."""
        wb = self.workbook
        years = wb.availability_years()
        return wb.add_engineers([
            # A full month, every year: what the timesheets cannot say
            # otherwise, and easy to change on Team.
            {"short_name": info["name"], "pattern": full,
             "available_hours": wb.hours_per_man_month(),
             "availability": {year: 1.0 for year in years}}
            for full, info in people.items() if info["new"]])

    def _without_a_place(self, people: Dict[str, Dict[str, Any]]) -> List[str]:
        """Who in these exports would have hours here but no place on the team.

        Everybody new is given one, so this is only somebody already holding
        rows here who was taken off the team.
        """
        placed = set(self.workbook.engineer_names())
        return [info["name"] for info in people.values()
                if not info["new"] and info["name"] not in placed]

    def _plan(self, records: Sequence[Dict[str, Any]]) -> Dict[str, List]:
        """The projects these rows add, and which would not fit."""
        wb = self.workbook
        rows = list(records)
        staged_people = {r["engineer"] for r in rows}
        # Hours already held count too, so a phase's split and weight reflect
        # everybody who booked it, not only this batch.
        rows += [r for r in self.store.all_rows()
                 if r["engineer"] not in staged_people]
        engineers = list(dict.fromkeys(
            wb.engineer_names() + sorted({r["engineer"] for r in rows})))
        plans = derive.plan_projects(
            rows,
            existing=[p.number for p in wb.projects()],
            engineers=engineers,
            credit_steps=wb.reference()["credit_steps"],
            hours_per_mm=wb.hours_per_man_month() or 0.0,
        )
        # Every project fits: the register has no last row any more.
        return {"fits": list(plans), "left_out": []}

    def _add_derived_projects(self) -> Dict[str, Any]:
        wb = self.workbook
        plan = self._plan([])
        names = set(wb.engineer_names())
        added, failed = [], []
        for item in plan["fits"]:
            deliverables = [
                {**d, "shares": {k: v for k, v in d["shares"].items()
                                 if k in names}}
                for d in item["deliverables"]]
            for d in deliverables:
                if d["shares"] and abs(sum(d["shares"].values()) - 1) > 1e-4:
                    d["shares"] = derive._split(d["shares"], list(d["shares"]))
            try:
                wb.save_project_with_deliverables(
                    None, item["project"], deliverables)
                added.append(item["project"]["number"])
            except ValidationError as error:
                failed.append({"number": item["project"]["number"],
                               "errors": error.errors})
        return {
            "projects_added": added,
            "projects_failed": failed,
            "projects_left_out": [p["project"]["number"] for p in plan["left_out"]],
        }

    # -- teams and people ------------------------------------------------
    #
    # The establishment: which team each person is in, and their grade.  A
    # head of department has many people, and they move between teams often.

    @_remembered
    def roster(self) -> Dict[str, Any]:
        with self._lock:
            # Units imported before teams were read from the timesheets get
            # theirs the first time anybody looks.
            people_module.teams_from_timesheets(
                self.store, lambda: uuid.uuid4().hex[:12])
            return people_module.roster(self.store,
                                        known=self.workbook.ts_sheets())

    @_remembered
    def resourcing(self, year: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            data = people_module.balance(
                self.store, monthly_capacity=wb.hours_per_man_month(), year=year)
            data["roster"] = people_module.roster(self.store,
                                                  known=wb.ts_sheets())
            data["available_years"] = metrics.available_years(
                wb, self._index(wb))
            return data

    @_remembered
    def portfolio_map(self, year: Optional[int] = None) -> Dict[str, Any]:
        """The picture: circles for projects, threads for the people on them."""
        with self._lock:
            wb = self.workbook
            index = self._index(wb)
            data = people_module.portfolio_map(
                self.store, metrics.project_rows(wb, index), year=year)
            data["available_years"] = metrics.available_years(wb, index)
            return data

    def add_team(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            name = " ".join(str(body.get("name") or "").split())
            if not name:
                raise people_module.PeopleError("A team needs a name.")
            if any(t["name"].lower() == name.lower() for t in self.store.teams()):
                raise people_module.PeopleError(
                    f"There is already a team called {name}.")
            team = self.store.add_team(uuid.uuid4().hex[:12], name,
                                       str(body.get("lead") or "").strip())
            return {"team": team}

    def update_team(self, team_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if not any(t["id"] == team_id for t in self.store.teams()):
                raise ApiError(HTTPStatus.NOT_FOUND, "There is no such team.")
            name = body.get("name")
            self.store.update_team(
                team_id,
                name=" ".join(str(name).split()) if name is not None else None,
                lead=str(body["lead"]).strip() if "lead" in body else None)
            return {"team_id": team_id}

    def remove_team(self, team_id: str) -> Dict[str, Any]:
        with self._lock:
            self.store.remove_team(team_id)
            return {"removed": team_id}

    def save_person(self, name: str, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            person = people_module.clean_name(name)
            fields: Dict[str, Any] = {}
            if "grade" in body:
                fields["grade"] = people_module.clean_grade(body["grade"])
            if "team_id" in body:
                team_id = body["team_id"] or None
                if team_id and not any(t["id"] == team_id
                                       for t in self.store.teams()):
                    raise ApiError(HTTPStatus.NOT_FOUND, "There is no such team.")
                fields["team_id"] = team_id
            if "capacity_hours" in body:
                value = body["capacity_hours"]
                fields["capacity_hours"] = float(value) if value not in (None, "") \
                    else None
            if "active" in body:
                fields["active"] = 1 if body["active"] else 0
            self.store.save_person(person, **fields)
            return {"person": person, "changed": sorted(fields)}

    def move_people(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Several people into one team at once, which is how it is really done."""
        with self._lock:
            names = [people_module.clean_name(n) for n in (body.get("names") or [])]
            if not names:
                raise people_module.PeopleError("Choose somebody to move first.")
            team_id = body.get("team_id") or None
            if team_id and not any(t["id"] == team_id for t in self.store.teams()):
                raise ApiError(HTTPStatus.NOT_FOUND, "There is no such team.")
            moved = self.store.move_people(names, team_id)
            team = next((t for t in self.store.teams() if t["id"] == team_id), None)
            return {"moved": moved, "names": names,
                    "team": team["name"] if team else None}

    def remove_person(self, name: str) -> Dict[str, Any]:
        with self._lock:
            self.store.remove_person(people_module.clean_name(name))
            return {"removed": name}

    # -- drawings, the coming days, and who is needed ---------------------
    def _listed(self, deliverables) -> Dict[int, Dict[str, Any]]:
        """The drawing list's figures, for deliverables still on their project."""
        by_row = {d.row: d for d in deliverables}
        return {row: entry for row, entry in self.store.drawing_list().items()
                if row in by_row and drawing_list_module._job(by_row[row].project_number)
                == drawing_list_module._job(entry["project_number"])}

    def _drawings(self, wb, index, project_rows=None) -> Dict[str, Any]:
        deliverables = wb.deliverables()
        return drawings_module.summary(
            metrics.deliverable_rows(wb, index),
            drawings_module.counts(self.store, deliverables),
            project_rows if project_rows is not None
            else metrics.project_rows(wb, index),
            people_module.roster(self.store, known=wb.ts_sheets())["people"],
            measured={p.number for p in wb.projects()
                      if not derive.needs_confirming(p.notes or "")},
            issued={row: e["issued"] for row, e in self._listed(deliverables).items()})

    @_remembered
    def drawings(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            return self._drawings(wb, self._index(wb))

    def save_drawings(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            saved = drawings_module.save_counts(
                self.store, wb.deliverables(),
                _object(body.get("counts") or {}, "counts"))
            return {"saved": saved, "drawings": self._drawings(wb, self._index(wb))}

    def _holiday_choice(self, teams: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
        """Which country's public holidays the unit, and each team, keeps.

        Until somebody chooses, a country named in the unit's or a team's
        name is taken as a guess, and the Planner asks to confirm it.
        """
        try:
            choice = json.loads(self.store.setting(HOLIDAY_SETTING) or "{}")
        except ValueError:
            choice = {}
        choice = {"unit": choice.get("unit"), "teams": dict(choice.get("teams") or {}),
                  "off": list(choice.get("off") or []), "chosen": "unit" in choice}
        if not choice["chosen"]:
            unit = self.unit if isinstance(self.unit, dict) else {}
            names = [unit.get("name") or ""] + [t.get("name") or "" for t in teams]
            choice["unit"] = next((c for c in map(holidays_module.guess, names) if c), None)
        return choice

    # -- the drawing list ------------------------------------------------
    def _list_proposals(self, wb) -> List[Dict[str, Any]]:
        deliverables = wb.deliverables()
        return drawing_list_module.proposals(
            list(self._listed(deliverables).values()), deliverables,
            wb.credit_steps(), _today())

    def drawing_list_template(self) -> Dict[str, Any]:
        """An empty drawing list with a starter row per live deliverable."""
        with self._lock:
            wb = self.workbook
            live = {p.number for p in wb.projects()
                    if p.status not in ("Finalized", "Cancelled", "Proposal")}
            starters = [{"project_number": d.project_number, "name": d.name}
                        for d in wb.deliverables() if d.project_number in live]
            data = drawing_list_module.template(starters)
            unit = self.unit if isinstance(self.unit, dict) else {}
            return {"filename": f"Drawing list{' - ' + unit['name'] if unit.get('name') else ''}.xlsx",
                    "content_base64": base64.b64encode(data).decode("ascii")}

    def import_drawing_list(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Counts, issues and codes from the office's own drawing list."""
        with self._lock:
            wb = self.workbook
            files = body.get("files") or []
            if not files:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Choose a drawing list to upload.")
            drawings: List[Dict[str, Any]] = []
            for item in _objects(files, "files"):
                drawings.extend(drawing_list_module.read(
                    _decode(item.get("content_base64")), item.get("filename") or ""))
            deliverables = wb.deliverables()
            matched = drawing_list_module.match(drawings, deliverables)
            self.store.save_drawing_list(matched["deliverables"], matched["projects"])
            for entry in matched["deliverables"]:
                self.store.set_drawings(entry["row"], entry["project_number"], entry["total"])
            return {
                "read": len(drawings),
                "matched": matched["drawings"],
                "deliverables": matched["deliverables"],
                "unmatched": matched["unmatched"],
                "proposals": self._list_proposals(wb),
                "drawings": self._drawings(wb, self._index(wb)),
            }

    def apply_drawing_list(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Put what the drawing list says onto the register, in one tap."""
        with self._lock:
            wb = self.workbook
            try:
                wanted = {int(r) for r in body.get("rows") or []}
            except (TypeError, ValueError):
                raise ApiError(HTTPStatus.BAD_REQUEST, "Choose deliverables by their row.")
            proposals = [p for p in self._list_proposals(wb)
                         if not wanted or p["row"] in wanted]
            if not proposals:
                raise ApiError(HTTPStatus.BAD_REQUEST, "There is nothing to apply.")
            by_row = {d.row: d for d in wb.deliverables()}
            for proposal in proposals:
                data = by_row[proposal["row"]].to_dict()
                data.update({k: v for k, v in proposal["change"].items()
                             if k != "step_name"})
                wb.update_deliverable(proposal["row"], data)
            return {"applied": len(proposals), "save": self._commit(),
                    "proposals": self._list_proposals(wb)}

    def _calendar(self, wb, rows, people: Sequence[Dict[str, Any]] = (),
                  teams: Sequence[Dict[str, Any]] = ()):
        """The working-day settings, less holidays and whoever is away."""
        today = _today()
        leave = {name: set(days) for name, days in self._leave(wb, rows).items()}
        absences = self.store.absences()
        choice = self._holiday_choice(teams)
        public = holidays_module.calendar_for(
            choice, people=people,
            start=today - _dt.timedelta(days=HOLIDAYS_BEHIND_DAYS),
            end=today + _dt.timedelta(days=HOLIDAYS_AHEAD_DAYS))
        config = calendar_.with_calendar(
            wb.task_settings(),
            holidays=calendar_.workbook_holidays(wb) | public["common"],
            absences=absences, leave=leave, own_holidays=public["own"])
        return config, absences, leave, public, choice

    def _leave(self, wb, rows) -> Dict[str, Any]:
        """Days off booked on the timesheets, read once per revision."""
        codes = calendar_.leave_codes(wb)
        build = lambda: calendar_.leave_from_timesheets(          # noqa: E731
            rows, codes=codes)
        if self._store is not getattr(wb, "store", None):
            return build()
        # Kept with the rows, for as long as the codes that mean leave hold.
        return wb._cached(("leave", tuple(sorted(codes))), build)

    def _planning(self, wb) -> Dict[str, Any]:
        """What the planner and the forecast both start from."""
        index = self._index(wb)
        project_rows = metrics.project_rows(wb, index)
        drawn = self._drawings(wb, index, project_rows)
        people_module.teams_from_timesheets(self.store,
                                            lambda: uuid.uuid4().hex[:12])
        roster = people_module.roster(self.store, known=wb.ts_sheets())
        rows = self.store.all_rows()
        config, absences, leave, public, choice = self._calendar(
            wb, rows, roster["people"], roster["teams"])
        return {
            "management": management_module.Plan(
                roster["people"], roster["teams"], config,
                goals=growth_module.goals_by_person(
                    self.store.goals(quarter=growth_module.quarter_of(_today())),
                    growth_module.quarter_of(_today()))),
            "rows": rows,
            "tasks": wb.task_records(),
            "roster": roster["people"],
            "teams": roster["teams"],
            "config": config,
            "absences": absences,
            "leave": leave,
            "public": public,
            "holiday_choice": choice,
            "project_rows": project_rows,
            "project_names": {p.number: p.name or p.number for p in wb.projects()},
            "drawings": drawn,
        }

    def _outlook(self, wb, body: Dict[str, Any], *, suggest: bool = False
                 ) -> Dict[str, Any]:
        inputs = self._planning(wb)
        days = planner_module.clean_days(body.get("days"))
        moves = planner_module.clean_moves(
            body.get("moves"), people=[p["name"] for p in inputs["roster"]],
            tasks=inputs["tasks"])
        common = dict(
            rows=inputs["rows"], tasks=inputs["tasks"], roster=inputs["roster"],
            config=inputs["config"], project_names=inputs["project_names"],
            drawings_left=drawings_module.left_by_project(inputs["drawings"]),
            saved=self.store.plan_moves(), days=days, today=_today(),
            management=inputs["management"].taken_a_day())
        suggested: List[Dict[str, Any]] = []
        if suggest:
            suggested = planner_module.suggest(moves=moves, **common)
            moves = moves + suggested
        data = planner_module.outlook(moves=moves, **common)
        data["suggested"] = suggested
        data["drawings"] = {k: inputs["drawings"][k] for k in
                            ("known", "total", "done", "left", "hours_per_drawing",
                             "drafting_hours_per_drawing", "people", "teams",
                             "projects")}
        data["open_tasks"] = [
            {"id": t.id, "name": t.name, "project_number": t.project_number,
             "assignees": list(t.assignees), "hours_each": round(t.hours_each(), 1),
             "due": iso(t.due)}
            for t in inputs["tasks"] if not t.done and t.assignees]
        data["projects"] = [{"number": n, "name": name}
                            for n, name in inputs["project_names"].items()]
        return data

    def planner(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            return self._outlook(self.workbook, body)

    def planner_suggest(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            return self._outlook(self.workbook, body, suggest=True)

    def planner_commit(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Make the moves real: tasks change hands, shares of projects are kept."""
        with self._lock:
            wb = self.workbook
            inputs = self._planning(wb)
            moves = planner_module.clean_moves(
                body.get("moves"), people=[p["name"] for p in inputs["roster"]],
                tasks=inputs["tasks"])
            if not moves:
                raise planner_module.PlanError(["There is nothing to commit."])
            days = planner_module.clean_days(body.get("days"))
            window = planner_module.days_ahead(_today(), days, inputs["config"])
            start, end = window[0].isoformat(), window[-1].isoformat()
            engineers = set(wb.engineer_names())
            tasks_by_id = {t.id: t for t in inputs["tasks"]}
            for move in moves:
                if move["kind"] == "task" and move["to"] not in engineers:
                    raise planner_module.PlanError([
                        f"{move['to']} is not on the team yet, so a task cannot "
                        f"be given to them. Add them on Team, or hand them a "
                        f"share of the project instead."])
            saved_projects, saved_tasks = 0, 0
            for move in moves:
                if move["kind"] == "project":
                    self.store.add_plan_move(
                        project=move["project"], from_person=move["from"],
                        to_person=move["to"], share=move["share"],
                        start=start, end=end)
                    saved_projects += 1
                else:
                    task = tasks_by_id[move["task_id"]].to_dict()
                    task["assignees"] = list(dict.fromkeys(
                        move["to"] if n == move["from"] else n
                        for n in task["assignees"]))
                    wb.save_task(task, task_id=move["task_id"])
                    saved_tasks += 1
            result: Dict[str, Any] = {"projects_moved": saved_projects,
                                      "tasks_moved": saved_tasks}
            if saved_tasks:
                result["save"] = self._commit()
            result["outlook"] = self._outlook(wb, {"days": days})
            return result

    def remove_plan_move(self, move_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if not self.store.remove_plan_move(move_id):
                raise ApiError(HTTPStatus.NOT_FOUND, "There is no such handover.")
            return {"removed": move_id,
                    "outlook": self._outlook(self.workbook, body or {})}

    @_remembered
    def needs(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            inputs = self._planning(wb)
            drawn = inputs["drawings"]
            unit = self.unit or {}
            data = needs_module.forecast(
                rows=inputs["rows"], project_rows=inputs["project_rows"],
                projects=wb.projects(), roster=inputs["roster"],
                config=inputs["config"], hours_per_mm=wb.hours_per_man_month(),
                drawings_left=drawings_module.left_by_project(drawn),
                drafting_hours_per_drawing=drawn["drafting_hours_per_drawing"],
                today=_today(),
                unit_name=(unit.get("name") if isinstance(unit, dict) else "") or "",
                requests=[(name, t.due, t.hours_each())
                          for t in inputs["tasks"]
                          if intake.is_request(t) and not t.done and t.due
                          for name in t.assignees],
                planned=self.store.planned_work(),
                team_names={t["id"]: t["name"] for t in self.store.teams()},
                management=inputs["management"].taken_a_day())
            data["drawings"] = {k: drawn[k] for k in
                                ("known", "total", "done", "left", "progress",
                                 "hours_per_drawing", "drafting_hours_per_drawing",
                                 "deliverables_with_drawings",
                                 "deliverables_without")}
            data["teams"] = [{"id": t["id"], "name": t["name"]}
                             for t in sorted(self.store.teams(), key=lambda t: t["name"])]
            return data

    @_remembered
    def checkins(self) -> Dict[str, Any]:
        """Free hours, how loaded each person has been, and what to ask them."""
        with self._lock:
            wb = self.workbook
            inputs = self._planning(wb)
            return checkins_module.build(
                rows=inputs["rows"], tasks=inputs["tasks"], roster=inputs["roster"],
                config=inputs["config"], project_names=inputs["project_names"],
                saved=self.store.plan_moves(), slots=self.store.slots(),
                today=_today(), management=inputs["management"],
                marks=self._open_marks())

    def _open_marks(self) -> List[Dict[str, Any]]:
        """What people said from My day that the lead has not dealt with,
        with each day off they entered beside its mark."""
        absences = {a["id"]: a for a in self.store.absences()}
        out = []
        for mark in self.store.marks(open_only=True):
            if mark["kind"] == myday.OFF:
                mark["absence"] = absences.get(mark["absence_id"])
            out.append(mark)
        return out

    @_remembered
    def weekly(self) -> Dict[str, Any]:
        """This week's report, from what Check-ins, the forecast and the
        submissions plan already work out."""
        with self._lock:
            wb = self.workbook
            inputs = self._planning(wb)
            unit = self.unit if isinstance(self.unit, dict) else {}
            return weekly_module.build(
                unit_name=unit.get("name") or "", today=_today(),
                config=inputs["config"], checkins=self.checkins(),
                needs=self.needs(), submissions=self.submissions(),
                rows=inputs["rows"], project_names=inputs["project_names"])

    def _agendas(self, inputs: Dict[str, Any], today: _dt.date,
                 saved: List[Dict[str, Any]], slots: Dict[int, Dict[str, Any]]):
        """Each meeting's agenda, from the checkpoints Check-ins raises."""
        seen = checkins_module.build(
            rows=inputs["rows"], tasks=inputs["tasks"], roster=inputs["roster"],
            config=inputs["config"], project_names=inputs["project_names"],
            saved=saved, slots=slots, today=today, management=inputs["management"],
            marks=self._open_marks())
        points = {p["name"]: p["checkpoints"] for p in seen["people"]}
        signals = {p["name"]: p["signal"]["label"] for p in seen["people"]}
        room = [p["name"] for p in seen["can_take"]]

        def agenda(meeting: Dict[str, Any], day: _dt.date) -> List[str]:
            return management_module.agenda(
                meeting, checkpoints=points, signals=signals, tasks=inputs["tasks"],
                day=day, config=inputs["config"], can_take=room)
        return agenda

    def add_planned_work(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """A project just assigned: one line, and the forecast counts it."""
        with self._lock:
            item = incoming.clean(body, teams=[t["id"] for t in self.store.teams()],
                                  today=_today())
            new_id = self.store.add_planned_work(**item)
            return {"id": new_id, **item, "needs": self.needs()}

    def remove_planned_work(self, item_id: int) -> Dict[str, Any]:
        with self._lock:
            if not self.store.remove_planned_work(item_id):
                raise ApiError(HTTPStatus.NOT_FOUND, "There is no such project coming.")
            return {"removed": item_id, "needs": self.needs()}

    # -- the day, requests as they come in, and the submissions plan -------
    @_remembered
    def day_plan(self, query: Dict[str, List[str]]) -> Dict[str, Any]:
        """Everybody's day -- or week -- laid out from what is already known."""
        with self._lock:
            wb = self.workbook
            inputs = self._planning(wb)
            today = _today()
            raw = (query.get("date") or [""])[0]
            try:
                day = _dt.date.fromisoformat(raw) if raw else today
            except ValueError:
                raise ApiError(HTTPStatus.BAD_REQUEST, f"{raw!r} is not a date.")
            span = (query.get("span") or ["day"])[0]
            config = inputs["config"]
            days = daily.week_of(day, config) if span == "week" else [day]
            saved = self.store.plan_moves()
            slots = self.store.slots()
            plan = inputs["management"]
            agendas = None
            if any(plan.meetings_on(each) for each in days):
                agendas = self._agendas(inputs, today, saved, slots)
            out = []
            for each in days:
                out.append(daily.plan_day(
                    day=each, today=today, roster=inputs["roster"],
                    rates=daily.rates_on(each, inputs["rows"], config, saved),
                    tasks=inputs["tasks"], slots=slots, config=config,
                    project_names=inputs["project_names"],
                    **plan.for_day(each, agendas)))
            requests = []
            for task in inputs["tasks"]:
                if not intake.is_request(task):
                    continue
                slot = slots.get(task.id)
                if task.done and not (slot and slot["start"][:10] >= today.isoformat()):
                    continue
                requests.append({
                    "id": task.id, "title": task.name,
                    "project_number": task.project_number,
                    "person": (task.assignees or [""])[0],
                    "hours": task.required_hours, "due": iso(task.due),
                    "done": task.done,
                    "start": slot["start"] if slot else None,
                    "end": slot["end"] if slot else None,
                    "late": bool(slot and task.due
                                 and slot["end"][:10] > task.due.isoformat()),
                })
            requests.sort(key=lambda r: (r["done"], r["start"] or ""))
            teams = {p["team_id"]: p["team_name"] for p in inputs["roster"]
                     if p.get("team_id")}
            return {
                "today": today.isoformat(),
                "date": day.isoformat(),
                "span": "week" if span == "week" else "day",
                "days": out,
                "requests": requests,
                "teams": [{"id": k, "name": v} for k, v in sorted(
                    teams.items(), key=lambda kv: kv[1])],
                "people": [{"name": p["name"], "role": people_module.role_of(p.get("grade")),
                            "team_name": p.get("team_name", "")}
                           for p in inputs["roster"] if p.get("active", True)],
                "projects": [{"number": n, "name": name}
                             for n, name in inputs["project_names"].items()],
                "engineers": wb.engineer_names(),
                "unit": (self.unit or {}).get("name") if isinstance(self.unit, dict) else "",
                "away": self._away(inputs, today),
                "holidays": {k: v for k, v in self._holidays_view(inputs, today).items()
                             if k in ("unit", "unit_name", "chosen", "week_differs",
                                      "country_week", "work_days", "countries", "teams")},
            }

    def _away(self, inputs: Dict[str, Any], today: _dt.date) -> List[Dict[str, Any]]:
        return calendar_.upcoming(
            inputs["config"], inputs["absences"], inputs["leave"], today,
            today + _dt.timedelta(days=AWAY_AHEAD_DAYS),
            public=inputs["public"]["named"],
            country_names={c["code"]: c["name"] for c in holidays_module.choices()})

    def _holidays_view(self, inputs: Dict[str, Any], today: _dt.date) -> Dict[str, Any]:
        choice = inputs["holiday_choice"]
        countries = holidays_module.choices()
        names = {c["code"]: c["name"] for c in countries}
        week = inputs["config"]["work_days"]
        unit_week = (holidays_module.COUNTRIES[choice["unit"]]["week"]
                     if choice["unit"] else None)
        return {
            "unit": choice["unit"],
            "unit_name": names.get(choice["unit"], ""),
            "chosen": choice["chosen"],
            "teams": [{"id": t["id"], "name": t["name"],
                       "country": choice["teams"].get(t["id"]) or ""}
                      for t in inputs["teams"]],
            "off": choice["off"],
            "countries": countries,
            "work_days": list(week),
            "country_week": unit_week,
            "week_differs": bool(unit_week and sorted(unit_week) != sorted(week)),
            "lunar_until": holidays_module.LUNAR_YEARS[1],
            "next": [h for h in inputs["public"]["named"]
                     if h["date"] >= today.isoformat()][:40],
        }

    @_remembered
    def holidays(self) -> Dict[str, Any]:
        with self._lock:
            return self._holidays_view(self._planning(self.workbook), _today())

    def save_holidays(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Choose the countries once; take a wrong day off, or put it back."""
        with self._lock:
            wb = self.workbook
            inputs = self._planning(wb)
            choice = dict(inputs["holiday_choice"])
            errors = []
            try:
                if "unit" in body:
                    choice["unit"] = holidays_module.clean_country(body.get("unit"))
                teams = dict(choice["teams"])
                known = {t["id"] for t in inputs["teams"]}
                for team_id, code in dict(body.get("teams") or {}).items():
                    if team_id not in known:
                        continue
                    code = holidays_module.clean_country(code)
                    if code:
                        teams[team_id] = code
                    else:
                        teams.pop(team_id, None)
                choice["teams"] = teams
            except ValueError as exc:
                errors.append(str(exc))
            off = set(choice["off"])
            for typed in body.get("skip") or []:
                try:
                    off.add(_dt.date.fromisoformat(str(typed)).isoformat())
                except ValueError:
                    errors.append(f"{typed!r} is not a date.")
            if body.get("restore"):
                off = set()
            if errors:
                raise ValidationError(errors)
            self.store.set_setting(HOLIDAY_SETTING, json.dumps({
                "unit": choice["unit"], "teams": choice["teams"],
                "off": sorted(off)}))
            result: Dict[str, Any] = {}
            if body.get("use_week") and choice["unit"]:
                week = holidays_module.COUNTRIES[choice["unit"]]["week"]
                wb.save_task_settings({"work_days": week})
                result["save"] = self._commit()
            inputs = self._planning(wb)
            result["holidays"] = self._holidays_view(inputs, _today())
            result["away"] = self._away(inputs, _today())
            return result

    def add_absence(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Somebody will be away -- or, for everybody, a day nobody works."""
        with self._lock:
            wb = self.workbook
            today = _today()
            roster = people_module.roster(self.store, known=wb.ts_sheets())["people"]
            absence = calendar_.clean_absence(
                body, people=[p["name"] for p in roster], today=today)
            new_id = self.store.add_absence(**absence)
            return {"id": new_id, **absence,
                    "away": self._away(self._planning(wb), today)}

    def remove_absence(self, absence_id: int) -> Dict[str, Any]:
        with self._lock:
            if not self.store.remove_absence(absence_id):
                raise ApiError(HTTPStatus.NOT_FOUND, "There is no such absence.")
            return {"removed": absence_id,
                    "away": self._away(self._planning(self.workbook), _today())}

    def add_request(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """One line in; a person and a time slot out."""
        with self._lock:
            wb = self.workbook
            inputs = self._planning(wb)
            today = _today()
            request = intake.clean(body, projects=inputs["project_names"],
                                   today=today)
            engineers = wb.engineer_names()
            person = request["person"]
            if person and person not in engineers:
                raise intake.IntakeError([
                    f"{person} has no place on the task list yet, so a request "
                    f"cannot be given to them."])
            if not person:
                view = planner_module.outlook(
                    rows=inputs["rows"], tasks=inputs["tasks"],
                    roster=inputs["roster"], config=inputs["config"],
                    project_names=inputs["project_names"],
                    drawings_left=drawings_module.left_by_project(inputs["drawings"]),
                    saved=self.store.plan_moves(), today=today,
                    management=inputs["management"].taken_a_day(),
                    days=max(1, len(task_sheet.working_days(
                        today, max(request["due"], today), inputs["config"]))))
                history: Dict[str, set] = {}
                for row in inputs["rows"]:
                    history.setdefault(row["job_number"], set()).add(row["engineer"])
                person = intake.choose(view, role=request["role"],
                                       project=request["project_number"],
                                       eligible=engineers, history=history,
                                       away=calendar_.away_on(inputs["config"], today))
            if not person:
                raise intake.IntakeError(["There is nobody on the team to give it to."])
            now = intake.parse_now(body.get("now"))
            if now.date() < today:
                now = _dt.datetime.combine(today, _dt.time(0, 0))
            taken = [(_dt.datetime.fromisoformat(s["start"]),
                      _dt.datetime.fromisoformat(s["end"]))
                     for s in self.store.slots().values() if s["person"] == person]
            taken += inputs["management"].busy(person, now.date(), 60)
            start, end = intake.slot(
                hours=request["hours"], now=now, taken=taken, config=inputs["config"],
                away=(inputs["config"].get("away") or {}).get(person, ()))
            task = wb.save_task({
                "name": request["title"],
                "definition": " ".join(filter(None, [
                    f"Came in {now:%a %d %b %H:%M}.",
                    " ".join(str(body.get("note") or "").split())[:300]])),
                "project_number": request["project_number"],
                "assignees": [person],
                "required_hours": request["hours"],
                "start": start.date().isoformat(),
                "due": max(request["due"], start.date()).isoformat(),
                "kind": cfg.TASK_REQUEST_KIND,
                "status": cfg.TASK_STATUSES[0],
            })
            self.store.set_slot(task["id"], person, start.isoformat(timespec="minutes"),
                                end.isoformat(timespec="minutes"))
            return {"task": task, "person": person,
                    "start": start.isoformat(timespec="minutes"),
                    "end": end.isoformat(timespec="minutes"),
                    "late": end.date() > request["due"],
                    "save": self._commit()}

    def finish_request(self, task_id: int) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            task = next((t for t in wb.task_records() if t.id == task_id), None)
            if task is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "There is no such request.")
            data = task.to_dict()
            data["status"] = cfg.TASK_DONE_STATUS
            saved = wb.save_task(data, task_id=task_id)
            return {"task": saved, "save": self._commit()}

    # -- a team member's own day: the only writes a member can make --------
    #
    # A member opens their manager's unit for reading (``read_only``), and
    # everything else they can reach stays read-only.  These few write on
    # purpose, and only ever for ``engineer`` -- the person their access names,
    # which the app takes from the membership, never from the request.

    def _day_for(self, inputs: Dict[str, Any], day: _dt.date,
                 engineer: str) -> Dict[str, Any]:
        """One person's page of the day plan, without the meeting agendas
        (those carry what the leader is told about other people)."""
        me = [p for p in inputs["roster"] if p["name"] == engineer]
        config = inputs["config"]
        return daily.plan_day(
            day=day, today=_today(), roster=me,
            rates=daily.rates_on(day, inputs["rows"], config, self.store.plan_moves()),
            tasks=inputs["tasks"], slots=self.store.slots(), config=config,
            project_names=inputs["project_names"],
            **inputs["management"].for_day(day, None))

    @_remembered
    def my_day(self, engineer: str, query: Dict[str, List[str]]) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            today = _today()
            day = _date_in(query, "date", today)
            inputs = self._planning(wb)
            marks = self.store.marks(person=engineer)
            page = myday.today_page(
                engineer=engineer, day=self._day_for(inputs, day, engineer),
                tasks=inputs["tasks"], marks=marks,
                away=myday.my_time_off(self.store.absences(), marks, engineer, today),
                today=today, project_names=inputs["project_names"])
            page["today"] = today.isoformat()
            following = today + _dt.timedelta(days=1)
            for _ in range(14):
                if task_sheet.is_working_day(following, inputs["config"]):
                    break
                following += _dt.timedelta(days=1)
            page["next_day"] = following.isoformat()
            page["engineer"] = engineer
            page["known"] = engineer in wb.engineer_names()
            quarter = growth_module.quarter_of(today)
            page["goals"] = {
                "quarter": quarter, "label": growth_module.label(quarter),
                "items": [growth_module.goal_view(g) for g in
                          self.store.goals(quarter=quarter, person=engineer)]}
            return page

    @_remembered
    def my_timesheet(self, engineer: str, query: Dict[str, List[str]]) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            today = _today()
            inputs = self._planning(wb)
            config = inputs["config"]
            days = daily.week_of(_date_in(query, "week", today), config)
            codes = sorted(calendar_.leave_codes(wb))
            out = myday.ready_timesheet(
                engineer=engineer, days=days,
                plans={d.isoformat(): self._day_for(inputs, d, engineer) for d in days},
                rows=inputs["rows"], tasks=inputs["tasks"],
                deliverable_phases={d.row: d.ts_phase for d in wb.deliverables()},
                project_names=inputs["project_names"], config=config,
                leave_code=codes[0] if codes else "Leave", today=today)
            anchor = days[0] if days else _date_in(query, "week", today)
            out.update({
                "engineer": engineer,
                "week_start": days[0].isoformat() if days else anchor.isoformat(),
                "week_end": days[-1].isoformat() if days else anchor.isoformat(),
                "previous": (anchor - _dt.timedelta(days=7)).isoformat(),
                "next": (anchor + _dt.timedelta(days=7)).isoformat(),
                "this_week": bool(days and days[0] <= today <= days[-1] + _dt.timedelta(days=2)),
            })
            return out

    def mark_my_task(self, engineer: str, task_id: Any,
                     body: Dict[str, Any]) -> Dict[str, Any]:
        """Done, stuck, or help needed, on a task with their name on it."""
        with self._lock:
            wb = self.workbook
            kind = str(body.get("kind") or "")
            if kind not in myday.TASK_MARKS:
                raise myday.MyDayError(["Say done, stuck or need help."])
            note = myday.clean_note(body.get("note"))
            task = myday.my_task(wb.task_records(), engineer, task_id)
            if kind == myday.DONE and task.done:
                raise myday.MyDayError(["That task is already done."])
            self._limit_open(engineer)
            before = task.status
            # A task has one live mark: a new one replaces what was said before.
            for old in self.store.marks(person=engineer, open_only=True):
                if old["task_id"] == task.id and old["kind"] in myday.TASK_MARKS:
                    before = old["before"] or before
                    self.store.clear_mark(old["id"], "replaced")
            status = myday.STATUS_FOR.get(kind)
            if status and status != task.status:
                data = task.to_dict()
                data["status"] = status
                wb.save_task(data, task_id=task.id)
            mark_id = self.store.add_mark(engineer, kind, task_id=task.id,
                                          note=note, before=before)
            return {"mark": myday._mark_view(self.store.mark(mark_id))}

    def ask_for_help(self, engineer: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Help with something that is not on the task list."""
        with self._lock:
            note = myday.clean_note(body.get("note"))
            if not note:
                raise myday.MyDayError(["Say in a line what you need help with."])
            self._limit_open(engineer)
            mark_id = self.store.add_mark(engineer, myday.HELP, note=note)
            return {"mark": myday._mark_view(self.store.mark(mark_id))}

    def undo_my_mark(self, engineer: str, mark_id: Any) -> Dict[str, Any]:
        """Take back what they said: the task goes back to how it was."""
        with self._lock:
            mark = self._my_mark(engineer, mark_id)
            if mark["kind"] == myday.OFF:
                raise myday.MyDayError(["Take time off back from the list of days off."])
            if mark["task_id"] is not None and mark["kind"] in myday.STATUS_FOR:
                wb = self.workbook
                task = next((t for t in wb.task_records()
                             if t.id == mark["task_id"]
                             and engineer in t.assignees), None)
                if task is not None and task.status == myday.STATUS_FOR[mark["kind"]] \
                        and mark["before"] in cfg.TASK_STATUSES:
                    data = task.to_dict()
                    data["status"] = mark["before"]
                    wb.save_task(data, task_id=task.id)
            self.store.clear_mark(mark["id"], "undone")
            return {"undone": mark["id"]}

    def add_my_time_off(self, engineer: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """"I'm off on": their own days away, never anybody else's."""
        with self._lock:
            today = _today()
            absence = calendar_.clean_absence(
                {**body, "person": engineer}, people=[engineer], today=today)
            if absence["end"] < today.isoformat():
                raise myday.MyDayError(["Those days have passed."])
            absence_id = self.store.add_absence(**absence)
            mark_id = self.store.add_mark(engineer, myday.OFF, absence_id=absence_id,
                                          note=absence["note"])
            return {"mark_id": mark_id, **absence}

    def remove_my_time_off(self, engineer: str, mark_id: Any) -> Dict[str, Any]:
        """Only days off they entered themselves; the manager's stay."""
        with self._lock:
            mark = self._my_mark(engineer, mark_id)
            if mark["kind"] != myday.OFF or mark["absence_id"] is None:
                raise myday.MyDayError(["That is not time off you entered."])
            mine = next((a for a in self.store.absences()
                         if a["id"] == mark["absence_id"] and a["person"] == engineer),
                        None)
            if mine is not None:
                self.store.remove_absence(mine["id"])
            self.store.clear_mark(mark["id"], "undone")
            return {"removed": mark["id"]}

    def _my_mark(self, engineer: str, mark_id: Any) -> Dict[str, Any]:
        try:
            mark = self.store.mark(int(mark_id))
        except (TypeError, ValueError):
            mark = None
        if mark is None or mark["person"] != engineer or mark["cleared_at"]:
            raise ApiError(HTTPStatus.NOT_FOUND, "There is nothing of yours to undo there.")
        return mark

    def _limit_open(self, engineer: str) -> None:
        open_now = [m for m in self.store.marks(person=engineer, open_only=True)
                    if m["kind"] in (myday.STUCK, myday.HELP)]
        if len(open_now) >= myday.OPEN_LIMIT:
            raise myday.MyDayError([
                "You have a lot of asks open already. Talk to your lead, or undo "
                "the ones that are sorted."])

    def seen_mark(self, mark_id: int) -> Dict[str, Any]:
        """The lead has picked up a stuck or help ask."""
        with self._lock:
            mark = self.store.mark(mark_id)
            if mark is None or mark["kind"] not in (myday.STUCK, myday.HELP):
                raise ApiError(HTTPStatus.NOT_FOUND, "There is no such ask.")
            self.store.clear_mark(mark_id, "lead")
            return {"seen": mark_id, "save": self._commit()}

    # -- developing people: goals each quarter and KPIs by grade ----------
    @_remembered
    def growth(self, query: Dict[str, List[str]]) -> Dict[str, Any]:
        """Development time, each person's goals for the quarter, and KPIs
        weighed and ranked by grade."""
        with self._lock:
            wb = self.workbook
            today = _today()
            try:
                quarter = growth_module.clean_quarter(
                    (query.get("quarter") or [""])[0], today)
            except growth_module.GrowthError as error:
                raise ApiError(HTTPStatus.BAD_REQUEST, error.errors[0])
            inputs = self._planning(wb)
            plan = inputs["management"]
            first, last = growth_module.quarter_bounds(quarter)
            delivery = self._delivery_by_grade(wb, inputs["roster"], first)
            delivery_from = quarter
            if not delivery:
                # Early in a quarter nothing is booked yet: the quarter before
                # stands in until it is, and the page says so.
                delivery_from = growth_module.shift(quarter, -1)
                delivery = self._delivery_by_grade(
                    wb, inputs["roster"], growth_module.quarter_bounds(delivery_from)[0])
            asks = [m for m in self.store.marks(since=first.isoformat())
                    if m["created_at"][:10] <= last.isoformat()]
            day = min(max(today, first), last)
            return growth_module.build(
                quarter=quarter, today=today, roster=inputs["roster"],
                led=plan.led, delivery=delivery, goals=self.store.goals(),
                asks=asks, development=plan.development, delivery_from=delivery_from,
                development_day={name: iso(plan.development_day(name, day))
                                 for name in plan.development})

    def _delivery_by_grade(self, wb, roster: Sequence[Dict[str, Any]],
                           first: _dt.date) -> Dict[str, Dict[str, float]]:
        """The Reports scorecard for the quarter, run within each grade, so
        nobody is set against a different grade."""
        number = (first.month - 1) // 3 + 1
        try:
            report = reports.build(wb, kind="quarter", year=first.year,
                                   quarter=f"Q{number}", index=self._index(wb))
        except (ValueError, KeyError):
            return {}
        per = report.per_engineer
        factors = wb.scorecard_factors()
        by_grade: Dict[str, List[str]] = {}
        for person in roster:
            name = person["name"]
            if person.get("active", True) and (per.get(name) or {}).get("actual_mm"):
                by_grade.setdefault(person.get("grade") or "", []).append(name)
        return {grade: reports._scorecard(per, names, factors)["totals"]
                for grade, names in by_grade.items()}

    def add_goal(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            names = [p["name"] for p in people_module.roster(
                self.store, known=self.workbook.ts_sheets())["people"]]
            goal = growth_module.clean_goal(body, people=names, today=_today(),
                                            existing=self.store.goals())
            saved = self._commit()
            return {"id": self.store.add_goal(**goal), **goal, "save": saved}

    def _goal(self, goal_id: int) -> Dict[str, Any]:
        goal = self.store.goal(goal_id)
        if goal is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "There is no such goal.")
        return goal

    def edit_goal(self, goal_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            goal = self._goal(goal_id)
            text = growth_module._text(body.get("goal", goal["goal"]))
            if not text:
                raise growth_module.GrowthError(["Write the goal."])
            saved = self._commit()
            self.store.edit_goal(goal_id, text,
                                 growth_module._text(body.get("measure", goal["measure"])))
            return {"id": goal_id, "save": saved}

    def review_goal(self, goal_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._goal(goal_id)
            review = growth_module.clean_review(body)
            saved = self._commit()
            self.store.review_goal(goal_id, review["result"], review["note"])
            return {"id": goal_id, **review, "save": saved}

    def remove_goal(self, goal_id: int) -> Dict[str, Any]:
        with self._lock:
            self._goal(goal_id)
            saved = self._commit()
            self.store.remove_goal(goal_id)
            return {"removed": goal_id, "save": saved}

    # -- emails in, as draft tasks ---------------------------------------
    def inbox(self, user_id: int) -> Dict[str, Any]:
        """One senior's emails: drafts to hand out, and what needed nothing."""
        with self._lock:
            store = self.store
            store.forget_old_inbox((_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(
                days=emails_module.KEEP_DAYS)).isoformat(timespec="seconds"))
            items = emails_module.sorted_items(store.inbox(user_id))
            by = {status: [i for i in items if i["status"] == status]
                  for status in emails_module.STATUSES}
            return {
                "drafts": by[emails_module.STATUS_DRAFT],
                "no_action": by[emails_module.STATUS_NO_ACTION][:50],
                "assigned": by[emails_module.STATUS_ASSIGNED][:20],
                "dismissed": by[emails_module.STATUS_DISMISSED][:20],
                "quiet": emails_module.read_quiet(
                    store.setting(emails_module.quiet_key(user_id))),
                "me": store.setting(emails_module.me_key(user_id)) or "",
                "keep_days": emails_module.KEEP_DAYS,
            }

    def take_email(self, user_id: int, body: Dict[str, Any], *,
                   pasted: bool = False) -> Dict[str, Any]:
        """One email in: a draft, a reply joining one, or no action."""
        with self._lock:
            if self.read_only:
                raise ApiError(HTTPStatus.FORBIDDEN, "This unit is not yours to change.")
            store = self.store
            email = emails_module.clean(
                emails_module.from_paste(body.get("text")) if pasted else body)
            if not email["me"]:
                email["me"] = store.setting(emails_module.me_key(user_id)) or ""
            if store.inbox_by_key(user_id, email["message_key"]):
                return {"status": "already", "added": False}
            topic = emails_module.topic(email["subject"])
            open_draft = store.inbox_by_topic(user_id, topic, [emails_module.STATUS_DRAFT])
            if open_draft and not pasted:
                # A reply in a conversation that is already a draft: one draft,
                # with the newest words.
                store.update_inbox(open_draft["id"], snippet=email["snippet"],
                                   received_at=email["received_at"],
                                   replies=int(open_draft["replies"] or 0) + 1)
                store.add_inbox(user_id, message_key=email["message_key"], topic=topic,
                                received_at=email["received_at"], sender=email["sender"],
                                subject=email["subject"], snippet="",
                                status=emails_module.STATUS_NO_ACTION,
                                reason="A reply in a conversation that is already a draft.")
                return {"status": emails_module.STATUS_DRAFT, "id": open_draft["id"],
                        "added": False, "joined": True}
            wb = self.workbook
            reason = None if pasted else emails_module.judge(
                email, quiet=emails_module.read_quiet(
                    store.setting(emails_module.quiet_key(user_id))))
            if reason is None and not pasted:
                handed = store.inbox_by_topic(user_id, topic, [emails_module.STATUS_ASSIGNED])
                task = next((t for t in wb.task_records()
                             if handed and t.id == handed["task_id"]), None)
                if task is not None and not task.done:
                    who = (task.assignees or [""])[0]
                    reason = (f"Already a task: {task.name}"
                              + (f", with {who}" if who else "") + ".")
            projects = {p.number: p.name for p in wb.projects()}
            guess = emails_module.guess(email, projects=projects, today=_today())
            status = emails_module.STATUS_NO_ACTION if reason else emails_module.STATUS_DRAFT
            new_id = store.add_inbox(
                user_id, message_key=email["message_key"], topic=topic,
                received_at=email["received_at"], sender=email["sender"],
                subject=email["subject"], snippet=email["snippet"], status=status,
                reason=reason or "", guess=json.dumps(guess))
            return {"status": status, "id": new_id, "added": True, "reason": reason or ""}

    def _email(self, user_id: int, item_id: int) -> Dict[str, Any]:
        item = self.store.inbox_item(user_id, item_id)
        if item is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "There is no such email.")
        return item

    def assign_email(self, user_id: int, item_id: int,
                     body: Dict[str, Any]) -> Dict[str, Any]:
        """The senior's pick: the draft becomes a request, given a time slot."""
        with self._lock:
            item = self._email(user_id, item_id)
            if item["status"] == emails_module.STATUS_ASSIGNED:
                raise ApiError(HTTPStatus.CONFLICT, "That email is already a task.")
            who = emails_module.sender_address(item["sender"])
            result = self.add_request({
                **{k: body.get(k) for k in ("title", "project_number", "hours", "due",
                                            "role", "person", "now")},
                "title": body.get("title") or emails_module.title_of(item),
                "note": f"From an email{f' from {who}' if who else ''}.",
            })
            self.store.update_inbox(item_id, status=emails_module.STATUS_ASSIGNED,
                                    task_id=result["task"]["id"],
                                    decided_at=_dt.datetime.now().isoformat(timespec="minutes"))
            return result

    def set_email_status(self, user_id: int, item_id: int, status: str) -> Dict[str, Any]:
        """Put an email aside as needing nothing, or bring it back as a draft."""
        with self._lock:
            item = self._email(user_id, item_id)
            if status not in (emails_module.STATUS_DRAFT, emails_module.STATUS_DISMISSED):
                raise ApiError(HTTPStatus.BAD_REQUEST, "A draft, or put aside.")
            if item["status"] == emails_module.STATUS_ASSIGNED:
                raise ApiError(HTTPStatus.CONFLICT, "That email is already a task.")
            self.store.update_inbox(
                item_id, status=status,
                reason="" if status == emails_module.STATUS_DRAFT else "You put it aside.",
                decided_at=_dt.datetime.now().isoformat(timespec="minutes"))
            return {"id": item_id, "status": status}

    def save_inbox_settings(self, user_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        """Senders who never need a task, and the senior's own address."""
        with self._lock:
            store = self.store
            quiet = emails_module.read_quiet(store.setting(emails_module.quiet_key(user_id)))
            for typed in body.get("quiet_add") or []:
                address = emails_module.sender_address(str(typed))
                if address and address not in quiet:
                    quiet.append(address)
            drop = {emails_module.sender_address(str(t)) for t in body.get("quiet_remove") or []}
            quiet = [q for q in quiet if q not in drop][:500]
            store.set_setting(emails_module.quiet_key(user_id), json.dumps(quiet))
            if "me" in body:
                me = emails_module.sender_address(str(body.get("me") or ""))
                if me and "@" not in me:
                    raise ValidationError(["Give your work email address."])
                store.set_setting(emails_module.me_key(user_id), me or None)
            # Drafts from a sender now quiet are put aside with them.
            if body.get("quiet_add"):
                for item in store.inbox(user_id):
                    if item["status"] == emails_module.STATUS_DRAFT and \
                            emails_module.sender_address(item["sender"]) in quiet:
                        store.update_inbox(item["id"], status=emails_module.STATUS_NO_ACTION,
                                           reason="You said emails from this sender "
                                                  "never need a task.")
            return self.inbox(user_id)

    @_remembered
    def submissions(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            index = self._index(wb)
            deliverables = wb.deliverables()
            rows = self.store.all_rows()
            roster = people_module.roster(self.store, known=wb.ts_sheets())
            result = submissions_module.plan(
                deliverable_rows=metrics.deliverable_rows(wb, index),
                deliverables=deliverables,
                project_rows=metrics.project_rows(wb, index),
                projects=wb.projects(), rows=rows,
                tasks=wb.task_records(),
                config=self._calendar(wb, rows, roster["people"], roster["teams"])[0],
                hours_per_mm=wb.hours_per_man_month(),
                drawing_counts=drawings_module.counts(self.store, deliverables),
                today=_today())
            listed = self._listed(deliverables)
            for item in result["items"] + result["waiting"]:
                entry = listed.get(item["row"])
                if entry:
                    item["list"] = {k: entry[k] for k in
                                    ("total", "issued", "code_a", "code_b", "code_c",
                                     "last_issued", "last_returned")}
            result["from_list"] = self._list_proposals(wb)
            return result

    def confirm_submissions(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Write the confirmed dates, and put each run-up on the task list."""
        with self._lock:
            wb = self.workbook
            items = body.get("items") or []
            if not items:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Choose a submission to confirm.")
            by_row = {d.row: d for d in wb.deliverables()}
            errors, chosen = [], []
            for item in _objects(items, "items"):
                try:
                    row = int(item.get("row"))
                    date = _dt.date.fromisoformat(str(item.get("date")))
                except (TypeError, ValueError):
                    errors.append(f"{item.get('date')!r} is not a date.")
                    continue
                if row not in by_row:
                    errors.append(f"There is no deliverable on row {row}.")
                    continue
                chosen.append((row, date))
            if errors:
                raise ValidationError(errors)
            prepared = 0
            for row, date in chosen:
                data = by_row[row].to_dict()
                data["status_date"] = date.isoformat()
                wb.update_deliverable(row, data)
            if body.get("prepare", True):
                for row, _date in chosen:
                    prepared += wb.generate_submission_tasks(
                        only_row=row, today=_today())["added"]
            result = {"confirmed": len(chosen), "tasks_added": prepared,
                      "save": self._commit()}
            return result

    # -- reference tables ------------------------------------------------
    def unlock(self, password: str) -> Dict[str, Any]:
        """Open the reference tables for editing.

        A deterrent against a stray keystroke changing a credit percentage,
        not a security control: the same values are editable in Excel by
        anyone who can open the file.
        """
        with self._lock:
            if password != cfg.REFERENCE_PASSWORD:
                raise ApiError(HTTPStatus.FORBIDDEN, "That password is not right.")
            self._unlocked = True
            return {"unlocked": True}

    def lock(self) -> Dict[str, Any]:
        with self._lock:
            self._unlocked = False
            return {"unlocked": False}

    def save_reference(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if not self._unlocked:
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "The reference tables are locked. Unlock them first.",
                )
            wb = self.workbook
            result = wb.save_reference(
                body.get("project_types"), body.get("credit_steps"))
            if body.get("scorecard_factors") is not None:
                result.update(wb.save_scorecard_factors(body["scorecard_factors"]))
            result["save"] = self._commit()
            return result

    # -- tasks -----------------------------------------------------------
    def tasks(self) -> Dict[str, Any]:
        """The list, the load it puts on the team, and what a task may refer to."""
        with self._lock:
            wb = self.workbook
            deliverables = [
                {
                    "row": d.row,
                    "name": d.name,
                    "project_number": d.project_number,
                    "date": iso(d.status_date),
                }
                for d in wb.deliverables()
            ]
            return {
                "tasks": wb.tasks(),
                "settings": wb.task_settings(),
                "load": wb.task_load(),
                "engineers": wb.engineer_names(),
                "projects": [{"number": p.number, "name": p.name}
                             for p in wb.projects()],
                "deliverables": deliverables,
                "statuses": list(cfg.TASK_STATUSES),
                "kinds": list(cfg.TASK_KINDS),
                # How progress may be measured, and what a review can say.
                "progress_modes": progress.MODES,
                "stages": [{"key": key, "label": label, "value": value}
                           for key, label, value in progress.STAGES],
                "review_codes": [{"key": key, "label": rule["label"],
                                  "floor": rule["floor"], "cap": rule["cap"]}
                                 for key, rule in progress.REVIEW_CODES.items()],
                "rework": progress.rework(
                    wb.task_records(), wb.engineer_names()),
                "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday",
                             "Friday", "Saturday", "Sunday"],
            }

    def add_task(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            task = self.workbook.save_task(body)
            return {"task": task, "save": self._commit()}

    def update_task(self, task_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            task = self.workbook.save_task(body, task_id=task_id)
            return {"task": task, "save": self._commit()}

    def delete_task(self, task_id: int) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.delete_task(task_id)
            self.store.remove_slot(task_id)
            result["save"] = self._commit()
            return result

    def delete_task_series(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.delete_task_series(str(body.get("series") or ""))
            result["save"] = self._commit()
            return result

    def save_task_settings(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            result = {"settings": self.workbook.save_task_settings(body)}
            result["save"] = self._commit()
            return result

    def generate_submission_tasks(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            row = body.get("deliverable_row")
            result = self.workbook.generate_submission_tasks(
                only_row=int(row) if row not in (None, "") else None,
                include_past=bool(body.get("include_past")))
            result["save"] = self._commit()
            return result

    def generate_weekly_meetings(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.generate_weekly_meetings(body)
            result["save"] = self._commit()
            return result

    def discard_timesheet(self, token: str) -> Dict[str, Any]:
        with self._lock:
            self._staged.pop(token, None)
            return {"discarded": True}



def _today():
    """Today, which the tests can pin with ``WORKLOAD_TODAY``."""
    return _model_today()


def _date_in(query: Dict[str, List[str]], key: str, default: _dt.date) -> _dt.date:
    raw = (query.get(key) or [""])[0]
    if not raw:
        return default
    try:
        return _dt.date.fromisoformat(raw)
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{raw!r} is not a date.")


def _year(query: Dict[str, List[str]]) -> Optional[int]:
    values = query.get("year")
    if not values or not values[0] or values[0] == "all":
        return None
    try:
        return int(values[0])
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{values[0]!r} is not a year.")


def _flag(query: Dict[str, List[str]], name: str) -> bool:
    values = query.get(name)
    return bool(values) and values[0].lower() in {"1", "true", "yes"}


def _object(value: Any, what: str) -> Dict[str, Any]:
    """``value`` if it is a JSON object, else a plain refusal."""
    if not isinstance(value, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{what} should be an object.")
    return value


def _objects(value: Any, what: str) -> List[Dict[str, Any]]:
    """``value`` if it is a list of JSON objects, else a plain refusal."""
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{what} should be a list of objects.")
    return value


def _int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{value!r} is not a row number.")


def _decode(content: Any) -> bytes:
    if not content:
        raise ApiError(HTTPStatus.BAD_REQUEST, "No file content was uploaded.")
    try:
        data = base64.b64decode(content)
    except Exception:
        raise ApiError(HTTPStatus.BAD_REQUEST, "The upload was not valid base64.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            f"That file is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )
    return data


def _stage(service: WorkloadService, body: Dict[str, Any]) -> Dict[str, Any]:
    return service.stage_timesheet(
        body.get("engineer", ""), str(body.get("filename") or "upload.xlsx"),
        _decode(body.get("content_base64")),
        registered_only=bool(body.get("registered_only", True)),
    )


def _duplicates(existing: Sequence[Dict[str, Any]],
                incoming: Sequence[Dict[str, Any]]) -> int:
    """How many incoming rows are already held: same job, day, phase and hours.

    Only meaningful when appending; the monthly routine replaces instead.
    """
    def key(row: Dict[str, Any]):
        return (row.get("job_number"), row.get("date"), row.get("phase"),
                round(float(row.get("hours") or 0.0), 4))
    seen = {key(row) for row in existing}
    return sum(1 for row in incoming if key(row) in seen)
