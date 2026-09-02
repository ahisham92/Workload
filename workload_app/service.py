"""One open workbook, and every change that can be made to it.

The service is the app's working memory: it holds the workbook a person has
open, serialises access to it, and turns each request into a domain call.  It
knows nothing about HTTP, and nothing about who is logged in -- one account's
service instance simply never sees another account's file.
"""

from __future__ import annotations

import base64
import os
import threading
import uuid
from contextlib import contextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from . import config as cfg, library, metrics, reports, timesheets
from .timesheets import ParsedTimesheet
from .workbook import WorkloadWorkbook, iso

MAX_UPLOAD_BYTES = 64 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status: int, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.errors = errors or [message]


@contextmanager
def _file_lock(path: Optional[Path]):
    """Hold a workbook exclusively while it is written.

    Advisory, and only where the platform has it: on a host this stops two
    workers writing the same file at once, and on Windows it does nothing,
    which is the same as today.
    """
    if path is None:
        yield
        return
    try:
        import fcntl
    except ImportError:                                # pragma: no cover
        yield
        return
    lock_path = Path(str(path) + ".lock")
    handle = None
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                os.close(handle)


class WorkloadService:
    """Holds the chosen workbook, if one is open yet, and serialises access."""

    def __init__(self, path: Optional[Path] = None, *, autosave: bool = True):
        self.path: Optional[Path] = None
        self.unit: Optional[Dict[str, Any]] = None
        self.autosave = autosave
        self._lock = threading.RLock()
        self._wb: Optional[WorkloadWorkbook] = None
        self._staged: Dict[str, ParsedTimesheet] = {}
        self._unlocked = False
        self._stack_raised_to: Optional[int] = None
        self._file_stamp = None
        #: A member's view of somebody else's workbook never writes to it.
        self.read_only = False
        if path is not None:
            self.open(path)

    # -- choosing a workbook ---------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._wb is not None

    @property
    def workbook(self) -> WorkloadWorkbook:
        """The open workbook, or a clear refusal if none has been chosen."""
        if self._wb is None:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "No workbook is open. Choose your Workload file first.",
            )
        return self._wb

    def open(self, path: Union[str, Path], *,
             unit: Optional[Dict[str, Any]] = None,
             read_only: bool = False) -> Dict[str, Any]:
        """Open a workbook file, and remember which unit it is.

        ``read_only`` is for a member looking at their manager's workbook:
        nothing is written to it, not even the widening the app would otherwise
        do on the way in.
        """
        with self._lock:
            resolved = library.validate(Path(path))
            if self._wb is not None and self._wb.dirty:
                self._save_locked()
            self._wb = WorkloadWorkbook(resolved)
            self.path = resolved
            self.unit = unit
            self.read_only = read_only
            self._staged.clear()
            self._unlocked = False
            self._stack_raised_to = None if read_only else self._widen_stack()
            self._stamp()
            return self.status()

    def close(self) -> Dict[str, Any]:
        with self._lock:
            if self._wb is not None and self._wb.dirty:
                self._save_locked()
            self._wb = None
            self.path = None
            self.unit = None
            self.read_only = False
            self._unlocked = False
            self._stack_raised_to = None
            self._staged.clear()
            return self.status()

    # -- the file underneath ---------------------------------------------
    #
    # A hosted app runs in more than one worker process, and each one holds its
    # own parsed copy of a workbook.  Two rules keep them honest: a writer
    # takes an exclusive lock on the file, and a reader that finds the file
    # changed underneath it re-reads before answering.

    def _stamp(self) -> None:
        self._file_stamp = self._current_stamp()

    def _current_stamp(self):
        try:
            stat = self.path.stat() if self.path else None
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size) if stat else None

    def refresh(self) -> None:
        """Re-read the workbook if another worker has written it since."""
        with self._lock:
            if self._wb is None or self.path is None:
                return
            if self._wb.dirty:
                # Our own unsaved work is newer than anything on disk.
                return
            if self._current_stamp() != self._file_stamp:
                self._wb.reload()
                self._staged.clear()
                self._stamp()

    # -- helpers ---------------------------------------------------------
    def _widen_stack(self) -> Optional[int]:
        """Deepen the per-sheet stack as soon as a workbook is opened.

        The workbook ships reading 6,000 rows from each monthly sheet, and that
        is the limit an engineer's own sheet reaches first.  Widening it is a
        one-line change to the VSTACK with no recalculation cost -- unlike the
        consolidated limit -- so it is done here rather than offered as a
        button nobody would have a reason to decline.
        """
        wb = self._wb
        if wb is None:
            return None
        report = wb.timesheet_capacity()
        if not report["source_is_short"]:
            return None
        target = report["suggested_source_last_row"]
        wb.extend_timesheet_capacity(source_last_row=target)
        if self.autosave:
            self._save_locked()
        return target

    def _commit(self) -> Dict[str, Any]:
        if self.autosave:
            return self._save_locked()
        return {"saved": False, "pending": True}

    def _save_locked(self) -> Dict[str, Any]:
        """Write the workbook with the file held exclusively."""
        if self.read_only:
            raise ApiError(HTTPStatus.FORBIDDEN,
                           "This workbook is open for reading only.")
        with _file_lock(self.path):
            result = self.workbook.save()
        self._stamp()
        return result

    def _known_job_numbers(self) -> set:
        wb = self.workbook
        return {p.number for p in wb.projects()} | set(wb.non_project_codes())

    # -- reads -----------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self._lock:
            if self._wb is None:
                return {"open": False, "workbook": None, "unit": None,
                        "autosave": self.autosave}
            return {
                "open": True,
                "unit": self.unit,
                "reference_unlocked": self._unlocked,
                "engineers": self._wb.engineer_names(),
                "workbook": str(self.path),
                "workbook_name": self.path.name,
                "folder": str(self.path.parent),
                "autosave": self.autosave,
                "unsaved_changes": self._wb.dirty,
                "sheets": self._wb.raw.sheet_names,
                "projects": len(self._wb.projects()),
                "deliverables": len(self._wb.deliverables()),
                "actuals_last_row": self._wb.actuals_last_row(),
                "capacity": self._wb.timesheet_capacity(),
                "stack_raised_to": self._stack_raised_to,
                "backups": str(self.path.parent / cfg.BACKUP_DIRNAME),
            }

    def reference(self) -> Dict[str, Any]:
        with self._lock:
            return self.workbook.reference()

    def overview(self, year: Optional[int]) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            index = metrics.TimesheetIndex(wb)
            data = metrics.overview(wb, year)
            data["available_years"] = metrics.available_years(wb, index)
            return data

    def projects(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            index = metrics.TimesheetIndex(wb)
            return {
                "projects": [p.to_dict() for p in wb.projects()],
                "metrics": metrics.project_rows(wb, index),
            }

    def deliverables(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            index = metrics.TimesheetIndex(wb)
            return {
                "deliverables": [d.to_dict() for d in wb.deliverables()],
                "metrics": metrics.deliverable_rows(wb, index),
                "actuals_last_row": wb.actuals_last_row(),
            }

    # -- the team --------------------------------------------------------
    def team(self) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            return {
                "engineers": wb.team(),
                "years": sorted(wb._availability_years().values()),
                "max_engineers": cfg.MAX_ENGINEERS,
                "built_in_slots": cfg.ENGINEER_BUILT_IN_SLOTS,
            }

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
            result = self.workbook.remove_engineer(engineer)
            result["save"] = self._commit()
            return result

    def reports(self, kind: str, year: Optional[int],
                quarter: Optional[str]) -> Dict[str, Any]:
        """Every report figure for one period, computed in a single pass."""
        with self._lock:
            wb = self.workbook
            index = metrics.TimesheetIndex(wb)
            data = reports.build(wb, kind, year, quarter, index=index).to_dict()
            data["periods"] = self._periods(wb)
            data["unit"] = self.unit
            data["issues"] = wb.register_issues()
            data["definitions"] = wb.definitions()
            period = data["period"]
            data["data_check"] = wb.data_check(
                period["year"] if period["kind"] == "year" else None)
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
            return self.workbook.data_check()

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
            result = self.workbook.save_project_with_deliverables(
                number, body.get("project", {}), body.get("deliverables", []))
            result["save"] = self._commit()
            return result

    def project_detail(self, number: str) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            project = wb.project(number)
            if project is None:
                raise ApiError(HTTPStatus.NOT_FOUND,
                               f"No project numbered {number!r}.")
            index = metrics.TimesheetIndex(wb)
            rows = {m["row"]: m for m in metrics.deliverable_rows(wb, index)}
            attached = [d for d in wb.deliverables()
                        if d.project_number == project.number]
            figures = [m for m in metrics.project_rows(wb, index)
                       if m["number"] == project.number]
            return {
                "project": project.to_dict(),
                "metrics": figures[0] if figures else None,
                "deliverables": [
                    {**d.to_dict(), "computed": rows.get(d.row)} for d in attached
                ],
            }

    def delete_deliverable(self, row: int) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.delete_deliverable(row)
            result["save"] = self._commit()
            return result

    def save(self) -> Dict[str, Any]:
        with self._lock:
            if self._wb is None:
                return {"saved": False}
            return self._save_locked()

    def reload(self) -> Dict[str, Any]:
        with self._lock:
            self.workbook.reload()
            self._staged.clear()
            self._stamp()
            return self.status()

    # -- timesheets ------------------------------------------------------
    def stage_timesheet(self, engineer: str, filename: str, data: bytes,
                        *, registered_only: bool = True) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            if engineer not in wb.ts_sheets():
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    f"{engineer!r} is not one of this workbook's engineers "
                    f"({', '.join(wb.ts_sheets())}).",
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
            existing = self._existing_rows(engineer)
            duplicates = timesheets.find_duplicates(
                existing, parsed.rows, parsed.headers) if parsed.rows else 0
            token = uuid.uuid4().hex
            self._staged[token] = parsed
            payload = parsed.to_dict()
            payload["token"] = token
            payload["existing_rows"] = len(existing)
            payload["duplicate_rows_if_appended"] = duplicates
            return payload

    def _existing_rows(self, engineer: str) -> List[List[Any]]:
        from .xlsx_io import col_to_index, index_to_col
        width = col_to_index(cfg.TS_LAST_COLUMN)
        columns = [index_to_col(i) for i in range(1, width + 1)]
        return [
            [row.get(col) for col in columns]
            for row in self.workbook.timesheet_rows(engineer, columns)
        ]

    def apply_timesheet(self, token: str, mode: str) -> Dict[str, Any]:
        with self._lock:
            parsed = self._staged.pop(token, None)
            if parsed is None:
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
            if mode == "append":
                rows = self._existing_rows(parsed.engineer) + list(parsed.rows)
            elif mode == "replace":
                rows = list(parsed.rows)
            else:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "Mode must be 'replace' (the monthly routine) or 'append'.",
                )
            wb = self.workbook
            # Make room before writing: a row past the limit is on the sheet
            # but reaches nothing, and that is the one failure nobody sees.
            room = wb.ensure_room_for(parsed.engineer, len(rows))
            result = wb.replace_timesheet(parsed.engineer, rows)
            result["mode"] = mode
            result["capacity_raised"] = room if room.get("raised") else None
            result["save"] = self._commit()
            result["data_check"] = wb.data_check()
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

    def extend_capacity(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            current = wb.timesheet_capacity()
            raw = body.get("raw_last_row")
            source = body.get("source_last_row")
            if not raw and not source:
                raw = current["suggested_raw_last_row"]
            result = wb.extend_timesheet_capacity(
                raw_last_row=int(raw) if raw else None,
                source_last_row=int(source) if source else None,
            )
            result["save"] = self._commit()
            result["capacity"] = wb.timesheet_capacity()
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


def _int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{value!r} is not a row number.")


def _stage(service: WorkloadService, body: Dict[str, Any]) -> Dict[str, Any]:
    engineer = body.get("engineer", "")
    filename = body.get("filename", "upload.xlsx")
    content = body.get("content_base64")
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
    return service.stage_timesheet(
        engineer, filename, data,
        registered_only=bool(body.get("registered_only", True)),
    )


