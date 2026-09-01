"""A small local web server in front of the workbook.

Deliberately built on the standard library: the only third-party package the
app needs is openpyxl, for reading uploaded exports.  Uploads arrive as base64
inside a JSON body rather than as multipart forms, which keeps the request
handling short and works the same on every supported Python version.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import threading
import traceback
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlparse

from . import config as cfg, library, metrics, timesheets
from .timesheets import ImportError_, ParsedTimesheet
from .library import NotAWorkbook
from .workbook import ValidationError, WorkloadWorkbook
from .xlsx_io import XlsxError

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status: int, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.errors = errors or [message]


class WorkloadService:
    """Holds the chosen workbook, if one is open yet, and serialises access."""

    def __init__(self, path: Optional[Path] = None, *, autosave: bool = True):
        self.path: Optional[Path] = None
        self.autosave = autosave
        self._lock = threading.RLock()
        self._wb: Optional[WorkloadWorkbook] = None
        self._staged: Dict[str, ParsedTimesheet] = {}
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

    def open(self, path: Union[str, Path]) -> Dict[str, Any]:
        with self._lock:
            resolved = library.validate(Path(path))
            if self._wb is not None and self._wb.dirty:
                self._wb.save()
            self._wb = WorkloadWorkbook(resolved)
            self.path = resolved
            self._staged.clear()
            library.remember(resolved)
            return self.status()

    def close(self) -> Dict[str, Any]:
        with self._lock:
            if self._wb is not None and self._wb.dirty:
                self._wb.save()
            self._wb = None
            self.path = None
            self._staged.clear()
            return self.status()

    def library(self, folder: Optional[str] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "recent": library.recent(),
            "suggestions": library.candidates(),
            "cwd": str(Path.cwd()),
            "home": str(Path.home()),
        }
        if folder is not None:
            data["browse"] = library.browse(folder)
        return data

    # -- helpers ---------------------------------------------------------
    def _commit(self) -> Dict[str, Any]:
        if self.autosave:
            return self.workbook.save()
        return {"saved": False, "pending": True}

    def _known_job_numbers(self) -> set:
        wb = self.workbook
        return {p.number for p in wb.projects()} | set(wb.non_project_codes())

    # -- reads -----------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self._lock:
            if self._wb is None:
                return {"open": False, "workbook": None,
                        "autosave": self.autosave}
            return {
                "open": True,
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

    def delete_deliverable(self, row: int) -> Dict[str, Any]:
        with self._lock:
            result = self.workbook.delete_deliverable(row)
            result["save"] = self._commit()
            return result

    def save(self) -> Dict[str, Any]:
        with self._lock:
            if self._wb is None:
                return {"saved": False}
            return self._wb.save()

    def reload(self) -> Dict[str, Any]:
        with self._lock:
            self.workbook.reload()
            self._staged.clear()
            return self.status()

    # -- timesheets ------------------------------------------------------
    def stage_timesheet(self, engineer: str, filename: str, data: bytes
                        ) -> Dict[str, Any]:
        with self._lock:
            if engineer not in cfg.TS_SHEETS:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    f"{engineer!r} is not one of {', '.join(cfg.TS_SHEETS)}.",
                )
            wb = self.workbook
            engineers = {e.short_name: e for e in wb.engineers()}
            pattern = engineers[engineer].pattern if engineer in engineers else None
            parsed = timesheets.parse(
                engineer, filename, data, wb.timesheet_headers(engineer),
                name_pattern=pattern,
                known_job_numbers=self._known_job_numbers(),
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
            result = wb.replace_timesheet(parsed.engineer, rows)
            result["mode"] = mode
            result["save"] = self._commit()
            result["data_check"] = wb.data_check()
            return result

    def extend_capacity(self, body: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            wb = self.workbook
            current = wb.timesheet_capacity()
            raw = body.get("raw_last_row") or current["suggested_raw_last_row"]
            source = body.get("source_last_row")
            result = wb.extend_timesheet_capacity(
                raw_last_row=int(raw),
                source_last_row=int(source) if source else None,
            )
            result["save"] = self._commit()
            result["capacity"] = wb.timesheet_capacity()
            return result

    def discard_timesheet(self, token: str) -> Dict[str, Any]:
        with self._lock:
            self._staged.pop(token, None)
            return {"discarded": True}


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------

Route = Tuple[str, str, Callable[..., Any]]


def build_routes(service: WorkloadService) -> List[Route]:
    """``(method, pattern, handler)``; ``{}`` in a pattern captures a segment."""
    return [
        ("GET", "/api/status", lambda q, b: service.status()),
        ("GET", "/api/workbooks",
         lambda q, b: service.library(q.get("folder", [None])[0])),
        ("POST", "/api/workbooks/open", lambda q, b: service.open(b.get("path", ""))),
        ("POST", "/api/workbooks/close", lambda q, b: service.close()),
        ("GET", "/api/reference", lambda q, b: service.reference()),
        ("GET", "/api/overview", lambda q, b: service.overview(_year(q))),
        ("GET", "/api/projects", lambda q, b: service.projects()),
        ("POST", "/api/projects", lambda q, b: service.add_project(b)),
        ("PUT", "/api/projects/{}", lambda q, b, number: service.update_project(number, b)),
        ("DELETE", "/api/projects/{}",
         lambda q, b, number: service.delete_project(number, _flag(q, "cascade"))),
        ("GET", "/api/deliverables", lambda q, b: service.deliverables()),
        ("POST", "/api/deliverables", lambda q, b: service.add_deliverable(b)),
        ("PUT", "/api/deliverables/{}",
         lambda q, b, row: service.update_deliverable(_int(row), b)),
        ("DELETE", "/api/deliverables/{}",
         lambda q, b, row: service.delete_deliverable(_int(row))),
        ("GET", "/api/timesheets", lambda q, b: service.timesheet_status()),
        ("POST", "/api/timesheets/stage", lambda q, b: _stage(service, b)),
        ("POST", "/api/timesheets/apply",
         lambda q, b: service.apply_timesheet(b.get("token", ""), b.get("mode", "replace"))),
        ("POST", "/api/timesheets/capacity", lambda q, b: service.extend_capacity(b)),
        ("POST", "/api/timesheets/discard",
         lambda q, b: service.discard_timesheet(b.get("token", ""))),
        ("POST", "/api/save", lambda q, b: service.save()),
        ("POST", "/api/reload", lambda q, b: service.reload()),
    ]


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
    return service.stage_timesheet(engineer, filename, data)


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkloadInput/1.0"
    service: WorkloadService = None       # set by make_server
    routes: List[Route] = []

    # -- plumbing --------------------------------------------------------
    def log_message(self, fmt: str, *args: Any) -> None:
        if self.server.quiet:                      # type: ignore[attr-defined]
            return
        super().log_message(fmt, *args)

    def _send(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _send_json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_UPLOAD_BYTES * 2:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Request body was not valid JSON.")
        if not isinstance(body, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Request body must be an object.")
        return body

    # -- dispatch --------------------------------------------------------
    def _match(self, method: str, path: str):
        wanted = [p for p in path.strip("/").split("/") if p != ""]
        for route_method, pattern, handler in self.routes:
            if route_method != method:
                continue
            parts = [p for p in pattern.strip("/").split("/") if p != ""]
            if len(parts) != len(wanted):
                continue
            captured: List[str] = []
            for expected, actual in zip(parts, wanted):
                if expected == "{}":
                    captured.append(actual)
                elif expected != actual:
                    break
            else:
                return handler, captured
        return None, []

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path.startswith("/api/"):
                handler, captured = self._match(method, path)
                if handler is None:
                    raise ApiError(HTTPStatus.NOT_FOUND, f"No route for {method} {path}.")
                body = self._read_body() if method in {"POST", "PUT", "DELETE"} else {}
                query = parse_qs(parsed.query)
                self._send_json(HTTPStatus.OK, handler(query, body, *captured))
                return
            if method not in {"GET", "HEAD"}:
                raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")
            self._serve_static(path)
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message, "errors": exc.errors})
        except ValidationError as exc:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY,
                            {"error": "The change was rejected.", "errors": exc.errors})
        except NotAWorkbook as exc:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY,
                            {"error": str(exc), "errors": [str(exc)]})
        except ImportError_ as exc:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": str(exc), "errors": [str(exc)]})
        except XlsxError as exc:
            self._send_json(HTTPStatus.CONFLICT,
                            {"error": str(exc), "errors": [str(exc)]})
        except BrokenPipeError:
            pass
        except Exception as exc:                       # pragma: no cover - safety net
            traceback.print_exc()
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": f"{type(exc).__name__}: {exc}",
                "errors": [f"{type(exc).__name__}: {exc}"],
            })

    def _serve_static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")
            return
        content_type, _ = mimetypes.guess_type(str(target))
        self._send(HTTPStatus.OK, target.read_bytes(),
                   content_type or "application/octet-stream")

    def do_GET(self) -> None:      # noqa: N802
        self._handle("GET")

    def do_HEAD(self) -> None:     # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:     # noqa: N802
        self._handle("POST")

    def do_PUT(self) -> None:      # noqa: N802
        self._handle("PUT")

    def do_DELETE(self) -> None:   # noqa: N802
        self._handle("DELETE")


def make_server(workbook: Optional[Path] = None, host: str = "127.0.0.1",
                port: int = 8765, *, autosave: bool = True,
                quiet: bool = False) -> ThreadingHTTPServer:
    service = WorkloadService(workbook, autosave=autosave)
    routes = build_routes(service)
    handler = type("BoundHandler", (Handler,), {"service": service, "routes": routes})
    server = ThreadingHTTPServer((host, port), handler)
    server.quiet = quiet                              # type: ignore[attr-defined]
    server.service = service                          # type: ignore[attr-defined]
    return server
