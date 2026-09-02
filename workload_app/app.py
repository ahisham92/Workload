"""The application: who is asking, what they may see, and what happens next.

Everything above the domain code lives here -- accounts, sessions, each
account's units, and the route table -- with no HTTP server in sight.  Two thin
transports call in: the stdlib server used locally, and the WSGI entry point
used on a host.  Both hand over a :class:`Request` and send back a
:class:`Response`.

The rule that makes the site private is short enough to state in one line:
every route below is either public, or resolves a session cookie to an account
and works only inside that account's own row of the database and its own folder
of workbooks.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import accounts as accounts_module, member as member_view, storage
from .accounts import (AccountError, Accounts, ROLE_MANAGER,
                       ROLE_MEMBER)
from .library import NotAWorkbook
from .service import ApiError, MAX_UPLOAD_BYTES, WorkloadService, _flag, _int, _stage, _year
from .tasks import TaskError
from .timesheets import ImportError_
from .workbook import ValidationError
from .xlsx_io import XlsxError

STATIC_DIR = Path(__file__).parent / "static"
SESSION_COOKIE = "workload_session"
#: How many accounts' workbooks are held parsed in memory at once.  A workbook
#: is tens of megabytes once parsed, and a small host does not have many of
#: those; the least recently used is saved and dropped.
OPEN_WORKBOOK_LIMIT = 4


@dataclass
class Request:
    method: str
    path: str
    query: Dict[str, List[str]] = field(default_factory=dict)
    body: Dict[str, Any] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    secure: bool = False


@dataclass
class Response:
    status: int
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"
    headers: List[Tuple[str, str]] = field(default_factory=list)

    @classmethod
    def json(cls, status: int, data: Any, headers=None) -> "Response":
        return cls(status, json.dumps(data, default=str).encode("utf-8"),
                   headers=list(headers or []))


@dataclass
class Context:
    """One request's account, and the workbook that account has open."""
    user: Optional[Dict[str, Any]] = None
    service: Optional[WorkloadService] = None
    token: Optional[str] = None
    secure: bool = False
    set_cookie: Optional[str] = None
    clear_cookie: bool = False


Handler = Callable[..., Any]
#: ``(method, pattern, handler, access)`` where access is one of ``public``
#: (no account), ``user`` (any account), ``manager`` (an account that owns
#: units and may change them) or ``admin`` (an account that makes accounts).
#: A team member reaches only the ``user`` routes and their own read-only view,
#: which is what makes their account read-only: not a hidden button, a missing
#: route.
Route = Tuple[str, str, Handler, str]


class WorkloadApp:
    """Accounts, their units, and the workbook each of them has open."""

    def __init__(self, data_dir: Optional[Path] = None, *, autosave: bool = True):
        self.data_dir = Path(data_dir) if data_dir else accounts_module.data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.accounts = Accounts(self.data_dir / "accounts.db")
        self.autosave = autosave
        #: user id -> their open workbook, most recently used last.
        self._services: "OrderedDict[int, WorkloadService]" = OrderedDict()
        self.routes = self._build_routes()

    # -- the services one account at a time ------------------------------
    def service_for(self, user_id: int) -> WorkloadService:
        service = self._services.pop(user_id, None)
        if service is None:
            service = WorkloadService(autosave=self.autosave)
        self._services[user_id] = service
        while len(self._services) > OPEN_WORKBOOK_LIMIT:
            _old_id, old = self._services.popitem(last=False)
            try:
                old.close()                    # saves anything still pending
            except Exception:                  # pragma: no cover - best effort
                traceback.print_exc()
        return service

    def close_all(self) -> None:
        for service in list(self._services.values()):
            try:
                service.close()
            except Exception:                  # pragma: no cover - best effort
                traceback.print_exc()
        self._services.clear()

    # -- dispatch --------------------------------------------------------
    def handle(self, request: Request) -> Response:
        ctx = Context(secure=request.secure)
        try:
            if request.path.startswith("/api/"):
                response = self._handle_api(request, ctx)
            else:
                response = self._handle_page(request, ctx)
        except ApiError as exc:
            response = Response.json(exc.status,
                                     {"error": exc.message, "errors": exc.errors})
        except (ValidationError, TaskError) as exc:
            response = Response.json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error": "The change was rejected.", "errors": exc.errors})
        except AccountError as exc:
            response = Response.json(HTTPStatus.UNPROCESSABLE_ENTITY,
                                     {"error": str(exc), "errors": exc.errors})
        except NotAWorkbook as exc:
            response = Response.json(HTTPStatus.UNPROCESSABLE_ENTITY,
                                     {"error": str(exc), "errors": [str(exc)]})
        except ImportError_ as exc:
            response = Response.json(HTTPStatus.BAD_REQUEST,
                                     {"error": str(exc), "errors": [str(exc)]})
        except XlsxError as exc:
            response = Response.json(HTTPStatus.CONFLICT,
                                     {"error": str(exc), "errors": [str(exc)]})
        except Exception as exc:                       # pragma: no cover - net
            traceback.print_exc()
            message = f"{type(exc).__name__}: {exc}"
            response = Response.json(HTTPStatus.INTERNAL_SERVER_ERROR,
                                     {"error": message, "errors": [message]})
        return self._with_cookies(response, ctx)

    def _handle_api(self, request: Request, ctx: Context) -> Response:
        handler, captured, access = self._match(request.method, request.path)
        if handler is None:
            raise ApiError(HTTPStatus.NOT_FOUND,
                           f"No route for {request.method} {request.path}.")
        self._authenticate(request, ctx)
        if access != "public":
            if ctx.user is None:
                raise ApiError(HTTPStatus.UNAUTHORIZED,
                               "Sign in to use this.")
            if access == "admin" and not ctx.user["is_admin"]:
                raise ApiError(HTTPStatus.FORBIDDEN,
                               "That is for administrators.")
            if access == "manager" and ctx.user["role"] != ROLE_MANAGER:
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "Your account can see your own work, and nothing else can "
                    "be changed from it.")
            ctx.service = self.service_for(ctx.user["id"])
            ctx.service.refresh()
        return Response.json(HTTPStatus.OK,
                             handler(ctx, request.query, request.body, *captured))

    def _handle_page(self, request: Request, ctx: Context) -> Response:
        if request.method not in {"GET", "HEAD"}:
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")
        self._authenticate(request, ctx)
        name = "index.html" if request.path in ("/", "") else request.path.lstrip("/")
        # The app shell is behind the login: an unknown visitor is given the
        # sign-in page and nothing else, and a team member is given their own
        # page rather than the manager's, which they could not use anyway.
        if name in ("index.html", ""):
            if ctx.user is None:
                name = "login.html"
            elif ctx.user["role"] == ROLE_MEMBER:
                name = "member.html"
        if name == "login.html" and ctx.user is not None:
            return Response(HTTPStatus.SEE_OTHER, b"",
                            "text/plain; charset=utf-8", [("Location", "/")])
        if name == "index.html" and ctx.user and ctx.user["role"] == ROLE_MEMBER:
            name = "member.html"
        target = (STATIC_DIR / name).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return Response(HTTPStatus.NOT_FOUND, b"Not found",
                            "text/plain; charset=utf-8")
        content_type, _ = mimetypes.guess_type(str(target))
        return Response(HTTPStatus.OK, target.read_bytes(),
                        content_type or "application/octet-stream")

    def _match(self, method: str, path: str):
        wanted = [p for p in path.strip("/").split("/") if p != ""]
        for route_method, pattern, handler, access in self.routes:
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
                return handler, captured, access
        return None, [], "public"

    def _authenticate(self, request: Request, ctx: Context) -> None:
        ctx.token = request.cookies.get(SESSION_COOKIE)
        ctx.user = self.accounts.session_user(ctx.token)

    def _with_cookies(self, response: Response, ctx: Context) -> Response:
        if ctx.set_cookie:
            response.headers.append(
                ("Set-Cookie", _cookie(SESSION_COOKIE, ctx.set_cookie,
                                       secure=ctx.secure)))
        elif ctx.clear_cookie:
            response.headers.append(
                ("Set-Cookie", _cookie(SESSION_COOKIE, "", secure=ctx.secure,
                                       max_age=0)))
        return response

    # ------------------------------------------------------------------
    # accounts
    # ------------------------------------------------------------------

    def login(self, ctx: Context, query, body) -> Dict[str, Any]:
        user = self.accounts.verify(body.get("username", ""),
                                    body.get("password", ""))
        if user is None:
            raise ApiError(HTTPStatus.UNAUTHORIZED,
                           "That username and password do not match an account.")
        ctx.set_cookie = self.accounts.start_session(user["id"])
        ctx.user = user
        return {"user": user}

    def logout(self, ctx: Context, query, body) -> Dict[str, Any]:
        self.accounts.end_session(ctx.token)
        if ctx.user:
            service = self._services.pop(ctx.user["id"], None)
            if service is not None:
                service.close()
        ctx.clear_cookie = True
        return {"signed_out": True}

    def whoami(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Public, so the login page can ask whether anyone is signed in."""
        return {
            "user": ctx.user,
            "any_accounts": self.accounts.user_count() > 0,
        }

    def change_password(self, ctx: Context, query, body) -> Dict[str, Any]:
        if self.accounts.verify(ctx.user["username"],
                                body.get("current_password", "")) is None:
            raise ApiError(HTTPStatus.FORBIDDEN,
                           "The current password is not right.")
        self.accounts.set_password(ctx.user["id"], body.get("new_password", ""))
        # Changing a password ends every session, including this one; issue a
        # fresh cookie so the person changing it is not thrown out.
        ctx.set_cookie = self.accounts.start_session(ctx.user["id"])
        return {"changed": True}

    # -- administration --------------------------------------------------
    def list_users(self, ctx: Context, query, body) -> Dict[str, Any]:
        return {"users": self.accounts.users(),
                "min_password": accounts_module.MIN_PASSWORD}

    def create_user(self, ctx: Context, query, body) -> Dict[str, Any]:
        password = (body.get("password") or "").strip()
        generated = not password
        if generated:
            password = accounts_module.generated_password()
        user = self.accounts.create_user(
            body.get("username", ""), password,
            display_name=body.get("display_name", ""),
            is_admin=bool(body.get("is_admin")),
            role=body.get("role") or ROLE_MANAGER)
        # The password is shown once, here, because nobody can read it back.
        return {"user": user,
                "password": password if generated else None}

    def reset_password(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        target = int(user_id)
        password = (body.get("password") or "").strip()
        generated = not password
        if generated:
            password = accounts_module.generated_password()
        self.accounts.set_password(target, password)
        self._services.pop(target, None)
        return {"user_id": target, "password": password if generated else None}

    def set_admin(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        self.accounts.set_admin(int(user_id), bool(body.get("is_admin")))
        return {"user": self.accounts.user(int(user_id))}

    def delete_user(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        target = int(user_id)
        if target == ctx.user["id"]:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                           "You cannot delete the account you are signed in to.")
        service = self._services.pop(target, None)
        if service is not None:
            service.close()
        result = self.accounts.delete_user(target)
        storage.remove_user_files(self.data_dir, target)
        return result

    # ------------------------------------------------------------------
    # units: one account's workbooks
    # ------------------------------------------------------------------

    def units(self, ctx: Context, query, body) -> Dict[str, Any]:
        user_id = ctx.user["id"]
        if ctx.user["role"] == ROLE_MEMBER:
            # A member owns nothing; they see what a manager has shown them.
            return {
                "units": [
                    {
                        "id": row["unit_id"],
                        "name": row["unit_name"],
                        "engineer": row["engineer"],
                        "manager": row["owner_name"] or "",
                        "opened_at": row["created_at"],
                        "exists": storage.unit_path(
                            self.data_dir, row["owner_id"],
                            row["filename"]).is_file(),
                    }
                    for row in self.accounts.memberships(user_id)
                ],
                "limit": 0,
                "read_only": True,
                "template_available": False,
            }
        out = []
        for unit in self.accounts.units(user_id):
            path = storage.unit_path(self.data_dir, user_id, unit["filename"])
            record = dict(unit)
            record["exists"] = path.is_file()
            if record["exists"]:
                stat = path.stat()
                record["size_mb"] = round(stat.st_size / 1_048_576, 2)
            out.append(record)
        return {
            "units": out,
            "limit": storage.MAX_UNITS_PER_USER,
            "template_available": storage.template_path().is_file(),
        }

    def create_unit(self, ctx: Context, query, body) -> Dict[str, Any]:
        """A new unit from the blank template that ships with the app."""
        user_id = ctx.user["id"]
        self._check_room(user_id)
        name = body.get("name", "")
        unit = self.accounts.create_unit(user_id, name, "")
        try:
            path = storage.new_from_template(self.data_dir, user_id, unit["id"])
            self.accounts_update_filename(user_id, unit["id"], path.name)
        except Exception:
            self.accounts.delete_unit(user_id, unit["id"])
            raise
        return self.open_unit(ctx, query, body, unit["id"])

    def upload_unit(self, ctx: Context, query, body) -> Dict[str, Any]:
        """A new unit from a workbook the account already has."""
        user_id = ctx.user["id"]
        self._check_room(user_id)
        content = body.get("content_base64")
        if not content:
            raise ApiError(HTTPStatus.BAD_REQUEST, "No file was uploaded.")
        try:
            data = base64.b64decode(content)
        except Exception:
            raise ApiError(HTTPStatus.BAD_REQUEST, "The upload was not valid base64.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                           f"That file is larger than the "
                           f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
        name = body.get("name") or Path(body.get("filename", "workbook")).stem
        unit = self.accounts.create_unit(user_id, name, "")
        try:
            path = storage.save_upload(self.data_dir, user_id, unit["id"], data)
            self.accounts_update_filename(user_id, unit["id"], path.name)
        except Exception:
            self.accounts.delete_unit(user_id, unit["id"])
            raise
        return self.open_unit(ctx, query, body, unit["id"])

    def accounts_update_filename(self, user_id: int, unit_id: str,
                                 filename: str) -> None:
        with self.accounts._connect() as db:           # noqa: SLF001 - same package
            db.execute("UPDATE units SET filename = ? WHERE id = ? AND user_id = ?",
                       (filename, unit_id, user_id))

    def open_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        user_id = ctx.user["id"]
        unit = self.accounts.unit(user_id, unit_id)
        if unit is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "That unit is not yours.")
        path = storage.unit_path(self.data_dir, user_id, unit["filename"])
        if not path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND,
                           f"The workbook for {unit['name']} is missing.")
        service = ctx.service or self.service_for(user_id)
        result = service.open(path, unit=unit)
        self.accounts.touch_unit(user_id, unit_id)
        return result

    def rename_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        # Look first, so a unit that is not this account's is refused the same
        # way everywhere: not found, rather than a rule about names.
        if self.accounts.unit(ctx.user["id"], unit_id) is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "That unit is not yours.")
        unit = self.accounts.rename_unit(ctx.user["id"], unit_id,
                                         body.get("name", ""))
        if ctx.service and ctx.service.unit \
                and ctx.service.unit.get("id") == unit_id:
            ctx.service.unit = unit
        return {"unit": unit}

    def delete_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        user_id = ctx.user["id"]
        unit = self.accounts.unit(user_id, unit_id)
        if unit is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "That unit is not yours.")
        if ctx.service and ctx.service.unit \
                and ctx.service.unit.get("id") == unit_id:
            ctx.service.close()
        self.accounts.delete_unit(user_id, unit_id)
        storage.remove_unit_file(self.data_dir, user_id, unit["filename"])
        return {"deleted": unit_id, "name": unit["name"]}

    def download_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        """The workbook itself, base64 encoded, so it can be taken away again."""
        user_id = ctx.user["id"]
        unit = self.accounts.unit(user_id, unit_id)
        if unit is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "That unit is not yours.")
        if ctx.service and ctx.service.unit \
                and ctx.service.unit.get("id") == unit_id:
            ctx.service.save()
        path = storage.unit_path(self.data_dir, user_id, unit["filename"])
        if not path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "That workbook is missing.")
        data = path.read_bytes()
        return {
            "filename": f"{unit['name']}.xlsx",
            "size_bytes": len(data),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }

    # ------------------------------------------------------------------
    # a team member's own page
    # ------------------------------------------------------------------

    def my_view(self, ctx: Context, query, body) -> Dict[str, Any]:
        """One engineer's own figures, and nothing else in the unit.

        The permission is a row in ``memberships``; without one this answers
        Not Found, and with one it answers only what :mod:`member` builds.
        """
        user_id = ctx.user["id"]
        granted = self.accounts.memberships(user_id)
        if not granted:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "No unit has been shared with you yet. Your manager can do "
                "that from their Team tab.")

        wanted = (query.get("unit") or [None])[0]
        row = next((g for g in granted if g["unit_id"] == wanted), granted[0])
        path = storage.unit_path(self.data_dir, row["owner_id"], row["filename"])
        if not path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND,
                           "That workbook is not there any more.")

        service = ctx.service
        if service.path != path or not service.read_only:
            service.open(path, unit={"id": row["unit_id"],
                                     "name": row["unit_name"]},
                         read_only=True)

        kind = (query.get("period") or ["year"])[0]
        data = member_view.build(
            service.workbook, row["engineer"], kind=kind, year=_year(query),
            quarter=(query.get("quarter") or [None])[0])
        data["unit"] = {"id": row["unit_id"], "name": row["unit_name"],
                        "manager": row.get("owner_name") or ""}
        data["units"] = [{"id": g["unit_id"], "name": g["unit_name"],
                          "engineer": g["engineer"]} for g in granted]
        return data

    # ------------------------------------------------------------------
    # who on the team has an account
    # ------------------------------------------------------------------

    def team_access(self, ctx: Context, query, body) -> Dict[str, Any]:
        unit = self._open_unit_or_refuse(ctx)
        return {
            "unit": {"id": unit["id"], "name": unit["name"]},
            "members": self.accounts.unit_members(unit["id"]),
            "engineers": ctx.service.workbook.engineer_names(),
        }

    def grant_access(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Give one person a read-only account for their own figures."""
        unit = self._open_unit_or_refuse(ctx)
        engineer = str(body.get("engineer") or "").strip()
        if engineer not in ctx.service.workbook.engineer_names():
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                           f"{engineer!r} is not on this unit's team.")

        username = str(body.get("username") or "").strip().lower()
        existing = next((u for u in self.accounts.users()
                         if u["username"] == accounts_module.clean_username(username)),
                        None) if username else None

        password = None
        if existing is None:
            password = (body.get("password") or "").strip() \
                or accounts_module.generated_password()
            user = self.accounts.create_user(
                username, password, display_name=body.get("display_name") or engineer,
                role=ROLE_MEMBER)
        else:
            if existing["role"] != ROLE_MEMBER:
                raise ApiError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    f"{existing['username']} is a manager account; a manager "
                    f"cannot also be given one person's view.")
            user = existing

        self.accounts.grant(user_id=user["id"], unit_id=unit["id"],
                            engineer=engineer, granted_by=ctx.user["id"])
        return {"user": user, "engineer": engineer,
                "password": password}          # shown once, never stored

    def revoke_access(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        unit = self._open_unit_or_refuse(ctx)
        target = int(user_id)
        if self.accounts.membership(target, unit["id"]) is None:
            raise ApiError(HTTPStatus.NOT_FOUND,
                           "That account has no access to this unit.")
        self.accounts.revoke(user_id=target, unit_id=unit["id"])
        self._services.pop(target, None)
        return {"revoked": target}

    def update_engineer(self, ctx: Context, query, body, name) -> Dict[str, Any]:
        """Rename or re-rate an engineer, and keep any access in step."""
        result = ctx.service.update_engineer(name, body)
        unit = ctx.service.unit
        renamed = result.get("engineer") or name
        if unit and renamed != name:
            # Otherwise a rename would quietly cut that person off from their
            # own page, which looks exactly like a bug to them.
            self.accounts.rename_engineer_in_memberships(unit["id"], name, renamed)
        return result

    def remove_engineer(self, ctx: Context, query, body, name) -> Dict[str, Any]:
        """Remove an engineer, and with them any access given in their name."""
        result = ctx.service.remove_engineer(name)
        unit = ctx.service.unit
        if unit:
            for row in self.accounts.unit_members(unit["id"]):
                if row["engineer"] == name:
                    self.accounts.revoke(user_id=row["user_id"],
                                         unit_id=unit["id"])
                    self._services.pop(row["user_id"], None)
                    result.setdefault("access_revoked", []).append(row["username"])
        return result

    def _open_unit_or_refuse(self, ctx: Context) -> Dict[str, Any]:
        """The unit this manager has open, or a plain refusal."""
        unit = ctx.service.unit if ctx.service else None
        if not unit:
            raise ApiError(HTTPStatus.CONFLICT,
                           "Open the unit first; access is given per unit.")
        owned = self.accounts.unit(ctx.user["id"], unit["id"])
        if owned is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "That unit is not yours.")
        return owned

    def _check_room(self, user_id: int) -> None:
        if len(self.accounts.units(user_id)) >= storage.MAX_UNITS_PER_USER:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"An account holds up to {storage.MAX_UNITS_PER_USER} units. "
                f"Delete one you no longer need.")

    # ------------------------------------------------------------------
    # the routes
    # ------------------------------------------------------------------

    def _build_routes(self) -> List[Route]:
        def s(method_name: str):
            """A route that is simply a call on the account's own service."""
            def call(ctx: Context, query, body, *captured):
                return getattr(ctx.service, method_name)(*captured)
            return call

        return [
            # -- who you are
            ("GET", "/api/auth/me", self.whoami, "public"),
            ("POST", "/api/auth/login", self.login, "public"),
            ("POST", "/api/auth/logout", self.logout, "public"),
            ("POST", "/api/auth/password", self.change_password, "user"),

            # -- administration
            ("GET", "/api/admin/users", self.list_users, "admin"),
            ("POST", "/api/admin/users", self.create_user, "admin"),
            ("POST", "/api/admin/users/{}/password", self.reset_password, "admin"),
            ("POST", "/api/admin/users/{}/admin", self.set_admin, "admin"),
            ("DELETE", "/api/admin/users/{}", self.delete_user, "admin"),

            # -- a team member's own page, which is all they can reach
            ("GET", "/api/me", self.my_view, "user"),

            # -- this account's units
            ("GET", "/api/units", self.units, "user"),
            ("POST", "/api/units", self.create_unit, "manager"),
            ("POST", "/api/units/upload", self.upload_unit, "manager"),
            ("POST", "/api/units/{}/open", self.open_unit, "manager"),
            ("PUT", "/api/units/{}", self.rename_unit, "manager"),
            ("DELETE", "/api/units/{}", self.delete_unit, "manager"),
            ("GET", "/api/units/{}/download", self.download_unit, "manager"),
            ("POST", "/api/units/close",
             lambda ctx, q, b: ctx.service.close(), "manager"),

            # -- the workbook that account has open
            ("GET", "/api/status", lambda ctx, q, b: ctx.service.status(), "manager"),
            ("GET", "/api/reference", lambda ctx, q, b: ctx.service.reference(), "manager"),
            ("POST", "/api/reference/unlock",
             lambda ctx, q, b: ctx.service.unlock(b.get("password", "")), "manager"),
            ("POST", "/api/reference/lock",
             lambda ctx, q, b: ctx.service.lock(), "manager"),
            ("PUT", "/api/reference",
             lambda ctx, q, b: ctx.service.save_reference(b), "manager"),
            ("GET", "/api/overview",
             lambda ctx, q, b: ctx.service.overview(_year(q)), "manager"),
            ("GET", "/api/projects", lambda ctx, q, b: ctx.service.projects(), "manager"),
            ("POST", "/api/projects",
             lambda ctx, q, b: ctx.service.add_project(b), "manager"),
            ("PUT", "/api/projects/{}",
             lambda ctx, q, b, number: ctx.service.update_project(number, b), "manager"),
            ("DELETE", "/api/projects/{}",
             lambda ctx, q, b, number: ctx.service.delete_project(
                 number, _flag(q, "cascade")), "manager"),
            ("GET", "/api/deliverables",
             lambda ctx, q, b: ctx.service.deliverables(), "manager"),
            ("GET", "/api/projects/{}",
             lambda ctx, q, b, number: ctx.service.project_detail(number), "manager"),
            ("POST", "/api/projects/full",
             lambda ctx, q, b: ctx.service.save_project_with_deliverables(None, b),
             "manager"),
            ("PUT", "/api/projects/{}/full",
             lambda ctx, q, b, number: ctx.service.save_project_with_deliverables(
                 number, b), "manager"),
            ("POST", "/api/deliverables",
             lambda ctx, q, b: ctx.service.add_deliverable(b), "manager"),
            ("PUT", "/api/deliverables/{}",
             lambda ctx, q, b, row: ctx.service.update_deliverable(_int(row), b),
             "manager"),
            ("DELETE", "/api/deliverables/{}",
             lambda ctx, q, b, row: ctx.service.delete_deliverable(_int(row)), "manager"),
            ("GET", "/api/team", lambda ctx, q, b: ctx.service.team(), "manager"),
            ("GET", "/api/team/access", self.team_access, "manager"),
            ("POST", "/api/team/access", self.grant_access, "manager"),
            ("DELETE", "/api/team/access/{}", self.revoke_access, "manager"),
            ("POST", "/api/team", lambda ctx, q, b: ctx.service.add_engineer(b), "manager"),
            ("PUT", "/api/team/{}", self.update_engineer, "manager"),
            ("DELETE", "/api/team/{}", self.remove_engineer, "manager"),
            ("GET", "/api/reports",
             lambda ctx, q, b: ctx.service.reports(
                 q.get("period", ["year"])[0], _year(q),
                 q.get("quarter", [None])[0]), "manager"),
            ("GET", "/api/tasks", lambda ctx, q, b: ctx.service.tasks(), "manager"),
            ("POST", "/api/tasks", lambda ctx, q, b: ctx.service.add_task(b), "manager"),
            ("PUT", "/api/tasks/settings",
             lambda ctx, q, b: ctx.service.save_task_settings(b), "manager"),
            ("POST", "/api/tasks/series/delete",
             lambda ctx, q, b: ctx.service.delete_task_series(b), "manager"),
            ("POST", "/api/tasks/generate/submissions",
             lambda ctx, q, b: ctx.service.generate_submission_tasks(b), "manager"),
            ("POST", "/api/tasks/generate/meetings",
             lambda ctx, q, b: ctx.service.generate_weekly_meetings(b), "manager"),
            ("PUT", "/api/tasks/{}",
             lambda ctx, q, b, task_id: ctx.service.update_task(_int(task_id), b),
             "manager"),
            ("DELETE", "/api/tasks/{}",
             lambda ctx, q, b, task_id: ctx.service.delete_task(_int(task_id)),
             "manager"),
            ("GET", "/api/timesheets",
             lambda ctx, q, b: ctx.service.timesheet_status(), "manager"),
            ("POST", "/api/timesheets/stage",
             lambda ctx, q, b: _stage(ctx.service, b), "manager"),
            ("POST", "/api/timesheets/apply",
             lambda ctx, q, b: ctx.service.apply_timesheet(
                 b.get("token", ""), b.get("mode", "replace")), "manager"),
            ("POST", "/api/timesheets/capacity",
             lambda ctx, q, b: ctx.service.extend_capacity(b), "manager"),
            ("POST", "/api/timesheets/discard",
             lambda ctx, q, b: ctx.service.discard_timesheet(b.get("token", "")),
             "manager"),
            ("POST", "/api/save", lambda ctx, q, b: ctx.service.save(), "manager"),
            ("POST", "/api/reload", lambda ctx, q, b: ctx.service.reload(), "manager"),
        ]


def _cookie(name: str, value: str, *, secure: bool,
            max_age: int = accounts_module.SESSION_DAYS * 24 * 3600) -> str:
    """A session cookie: not readable by scripts, not sent across sites."""
    parts = [
        f"{name}={value}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def parse_cookies(header: Optional[str]) -> Dict[str, str]:
    if not header:
        return {}
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:                                   # pragma: no cover
        return {}
    return {key: morsel.value for key, morsel in jar.items()}
