"""The application: who is asking, what they may see, and what happens next.

Everything above the domain code lives here -- accounts, sessions, each
account's units, and the route table -- with no HTTP server in sight.  Two thin
transports call in: the stdlib server used locally, and the WSGI entry point
used on a host.  Both hand over a :class:`Request` and send back a
:class:`Response`.

The rule that makes the site private is short enough to state in one line:
every route below is either public, or resolves a session cookie to an account
and works only inside that account's own row of the database and its own folder
of units.

**As one tab of a larger site.**  Mounted inside another site, Workload does no
signing in of its own: the site hands over who is asking (``Request.site``) and
that is the account.  Nothing else about the rule above changes -- the account
is found a different way, and then sees exactly what it always did.
"""

from __future__ import annotations

import base64
import functools
import gzip
import hashlib
import json
import mimetypes
import re
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import (accounts as accounts_module, budgets, busy_calendar,
               export as export_module, management,
               member as member_view, nightly, notify, storage, webpush,
               weekly as weekly_module)
from .accounts import (AccountError, Accounts, ROLE_MANAGER,
                       ROLE_MEMBER)
from .library import NotAWorkbook
from .people import DEFAULT_GRADE, GRADE_KEYS
from .service import (ApiError, WorkloadService, _decode, _flag,
                      _int, _stage, _today as service_today, _year)
from .timesheets import ImportError_
from .model import ValidationError
from .xlsx_io import XlsxError

STATIC_DIR = Path(__file__).parent / "static"
SESSION_COOKIE = "workload_session"
#: How many accounts' open units are kept in memory at once.  A unit is read
#: from its database as it is needed, so this only bounds what is cached.
OPEN_WORKBOOK_LIMIT = 16


@dataclass
class Request:
    method: str
    path: str
    query: Dict[str, List[str]] = field(default_factory=dict)
    body: Dict[str, Any] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    secure: bool = False
    #: Who the surrounding site says is asking, when Workload is mounted in
    #: one: ``{"id", "login", "name", "home", "label", "logout"}`` -- the
    #: site's own identifier for them, and what they sign in with.  Only the code
    #: that mounts Workload can set this -- a browser cannot.
    site: Optional[Dict[str, Any]] = None
    #: Where Workload is mounted (``/workload``), or empty at the root.
    mount: str = ""
    #: The browser's ``Accept-Encoding`` and ``If-None-Match`` headers.
    accept_encoding: str = ""
    if_none_match: str = ""


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


# -- delivery ---------------------------------------------------------------

#: Only these are worth compressing, and only when bigger than this.
_COMPRESSIBLE = ("application/json", "text/", "application/javascript",
                 "image/svg+xml", "application/manifest+json")
_COMPRESS_FROM = 1024
#: The page's own scripts and styles, as the HTML names them.
_ASSET_REF = re.compile(r'((?:src|href)=")([\w./-]+\.(?:js|css))(")')


class _Asset:
    """One file of the app's own, read once, with its version."""

    def __init__(self, path: Path):
        self.path = path
        self.stamp = _stamp(path)
        self.body = path.read_bytes()
        self.version = hashlib.sha256(self.body).hexdigest()[:12]
        self.etag = f'"{self.version}"'
        self._page: Optional[bytes] = None
        #: The files the page names, as they were when it was versioned.
        self._refs: List[Tuple[Path, Optional[Tuple[int, int]]]] = []

    def versioned_page(self) -> bytes:
        """The HTML, with ``?v=<version>`` on each script and style it names,
        so a browser keeps them until they change."""
        # A browser keeps a script for a year and never asks for it again, so
        # the page must notice the change itself, not wait for that request.
        if self._page is not None and any(_stamp_or_none(ref) != stamp
                                          for ref, stamp in self._refs):
            self._page = None
        if self._page is None:
            refs: List[Tuple[Path, Optional[Tuple[int, int]]]] = []

            def versioned(match: "re.Match") -> str:
                ref = _static_file(match.group(2))
                if ref is None:
                    return match.group(0)
                asset = _static(ref)
                refs.append((ref, asset.stamp))
                return (f"{match.group(1)}{match.group(2)}"
                        f"?v={asset.version}{match.group(3)}")
            page = _ASSET_REF.sub(
                versioned, self.body.decode("utf-8")).encode("utf-8")
            self._page, self._refs = page, refs
        return self._page


_assets: Dict[Path, _Asset] = {}
_assets_lock = threading.Lock()


def _stamp(path: Path) -> Tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _stamp_or_none(path: Path) -> Optional[Tuple[int, int]]:
    try:
        return _stamp(path)
    except OSError:
        return None


def _static_file(name: str) -> Optional[Path]:
    """The file ``name`` inside the static folder, or None: nothing outside
    it (not even a folder next to it whose name starts the same way), and
    nothing a path cannot even name."""
    root = STATIC_DIR.resolve()
    try:
        target = (root / name).resolve()
        target.relative_to(root)
        return target if target.is_file() else None
    except (ValueError, OSError):
        return None


def _static(path: Path) -> _Asset:
    """A static file, re-read only when it changes on disk (a deploy)."""
    with _assets_lock:
        asset = _assets.get(path)
    if asset is None or asset.stamp != _stamp(path):
        asset = _Asset(path)
        with _assets_lock:
            _assets[path] = asset
            # A page's versions follow the files it names.
            for other in _assets.values():
                other._page = None
    return asset


#: Compressed bodies of static files, by their content, so each is
#: compressed once.
_gzipped: "OrderedDict[str, bytes]" = OrderedDict()


def _compressed(response: Response, request: Request) -> Response:
    """The response gzipped, when the browser takes it and it is worth it."""
    if (len(response.body) < _COMPRESS_FROM
            or "gzip" not in request.accept_encoding.lower()
            or not response.content_type.startswith(_COMPRESSIBLE)
            or any(name.lower() == "content-encoding" for name, _ in response.headers)):
        return response
    etag = next((value for name, value in response.headers
                 if name.lower() == "etag"), None)
    body = _gzipped.get(etag) if etag else None
    if body is None:
        body = gzip.compress(response.body, compresslevel=6, mtime=0)
        if etag:
            with _assets_lock:
                _gzipped[etag] = body
                while len(_gzipped) > 64:
                    _gzipped.popitem(last=False)
    response.body = body
    response.headers = list(response.headers) + [
        ("Content-Encoding", "gzip"), ("Vary", "Accept-Encoding")]
    return response


@dataclass
class Context:
    """One request's account, and the workbook that account has open."""
    user: Optional[Dict[str, Any]] = None
    service: Optional[WorkloadService] = None
    token: Optional[str] = None
    secure: bool = False
    site: Optional[Dict[str, Any]] = None
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
        #: user id -> their open unit, most recently used last.
        self._services: "OrderedDict[int, WorkloadService]" = OrderedDict()
        #: Requests arrive on several threads at once; one service per account.
        self._services_lock = threading.Lock()
        #: Set by a site that mounts Workload: a call returning the people who
        #: can sign in to it, as ``[{"id", "login", "name"}]``.  Access to a
        #: unit is given by picking one of them.
        self.site_people: Optional[Callable[[], List[Dict[str, Any]]]] = None
        #: (unit file, person) -> when their calendar was last read, so
        #: opening the plan reads it again only now and then.
        self._calendar_checked: Dict[Tuple[str, str], float] = {}
        self.routes = self._build_routes()
        #: unit id -> (owner id, when): changes whose phones are still to be
        #: told; see tell_pending.
        self._to_tell: Dict[str, Tuple[int, float]] = {}

    # -- the services one account at a time ------------------------------
    def service_for(self, user_id: int) -> WorkloadService:
        with self._services_lock:
            service = self._services.pop(user_id, None)
            if service is None:
                service = WorkloadService(autosave=self.autosave)
            self._services[user_id] = service
            # The oldest is only forgotten, not closed: a request on another
            # thread may still be using it, and closing it would pull its unit
            # out from under that request. Nothing else is held open.
            while len(self._services) > OPEN_WORKBOOK_LIMIT:
                self._services.popitem(last=False)
        return service

    def _forget_service(self, user_id: int) -> None:
        """Forget an account's service without closing it, so the next request
        starts a fresh one (after a change of role or access)."""
        with self._services_lock:
            self._services.pop(user_id, None)

    def _drop_service(self, user_id: int) -> None:
        with self._services_lock:
            service = self._services.pop(user_id, None)
        if service is not None:
            service.close()

    def _follow_open_unit(self, ctx: "Context") -> None:
        """Have this worker open the unit the manager last opened anywhere.

        Which unit is open is kept in the account database, not only in this
        process: a host may run several workers, and a request is not always
        answered by the one that opened the unit.
        """
        user_id = ctx.user["id"]
        wanted = self.accounts.open_unit_of(user_id)
        current = (ctx.service.unit or {}).get("id")
        if wanted == current:
            if wanted is not None:
                # Renamed in another worker: keep the name in step here too.
                row = self.accounts.unit(user_id, wanted)
                if row and row["name"] != ctx.service.unit.get("name"):
                    ctx.service.unit = {**ctx.service.unit, "name": row["name"]}
            return
        if wanted is None:
            ctx.service.close()
            return
        try:
            self._open(ctx.service, user_id, wanted)
        except ApiError:
            # Deleted, or its data has gone: there is nothing to follow.
            self.accounts.set_open_unit(user_id, None)
            ctx.service.close()

    def close_all(self) -> None:
        with self._services_lock:
            services = list(self._services.values())
            self._services.clear()
        for service in services:
            try:
                service.close()
            except Exception:                  # pragma: no cover - best effort
                traceback.print_exc()

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
        except ValidationError as exc:     # every refused input, whichever module
            response = Response.json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error": "The change was rejected.", "errors": exc.errors})
        except AccountError as exc:
            response = Response.json(HTTPStatus.UNPROCESSABLE_ENTITY,
                                     {"error": str(exc), "errors": exc.errors})
        except (NotAWorkbook, ImportError_, XlsxError) as exc:
            status = (HTTPStatus.UNPROCESSABLE_ENTITY if isinstance(exc, NotAWorkbook)
                      else HTTPStatus.BAD_REQUEST if isinstance(exc, ImportError_)
                      else HTTPStatus.CONFLICT)
            response = Response.json(status, {"error": str(exc), "errors": [str(exc)]})
        except Exception as exc:                       # pragma: no cover - net
            traceback.print_exc()
            message = f"{type(exc).__name__}: {exc}"
            response = Response.json(HTTPStatus.INTERNAL_SERVER_ERROR,
                                     {"error": message, "errors": [message]})
        return _compressed(self._with_cookies(response, ctx), request)

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
            if ctx.user["role"] == ROLE_MANAGER:
                self._follow_open_unit(ctx)
            if ctx.service.path is not None and not ctx.service.path.is_file():
                # Deleted in another request (a member's unit, by its
                # manager): reading it again would leave an empty file there.
                ctx.service.close()
            ctx.service.refresh()
        before = self._unit_version(ctx) if request.method != "GET" else None
        result = handler(ctx, request.query, request.body, *captured)
        if before is not None:
            # A manager changed the unit: whatever that makes new reaches the
            # phones now, not at the next scheduled run.
            after = self._unit_version(ctx)
            if (after is not None and after[0] == before[0] and after[1] != before[1]
                    and self.accounts.has_push_devices(
                        notify.people_of_unit(self, ctx.user["id"], before[0]))):
                self._tell(ctx.user["id"], before[0])
        return Response.json(HTTPStatus.OK, result)

    def _handle_page(self, request: Request, ctx: Context) -> Response:
        if request.method not in {"GET", "HEAD"}:
            raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed.")
        self._authenticate(request, ctx)
        home = (request.mount or "") + "/"
        if request.site is not None and ctx.user is None:
            return Response(HTTPStatus.FORBIDDEN,
                            b"Your sign-in has no email address Workload can use.",
                            "text/plain; charset=utf-8")
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
                            "text/plain; charset=utf-8", [("Location", home)])
        target = _static_file(name)
        if target is None:
            return Response(HTTPStatus.NOT_FOUND, b"Not found",
                            "text/plain; charset=utf-8")
        content_type, _ = mimetypes.guess_type(str(target))
        content_type = content_type or "application/octet-stream"
        asset = _static(target)
        if target.suffix == ".html":
            # A page depends on who is asking, so it is never kept; the
            # scripts and styles it names carry their version, so they are.
            return Response(HTTPStatus.OK, asset.versioned_page(), content_type)
        # sw.js must be checked each time, or a phone keeps an old worker.
        lasting = (request.query.get("v") == [asset.version]
                   and target.name != "sw.js")
        headers = [("ETag", asset.etag), ("Cache-Control",
                   "public, max-age=31536000, immutable" if lasting
                   else "no-cache")]
        if asset.etag in [tag.strip() for tag in request.if_none_match.split(",")]:
            return Response(HTTPStatus.NOT_MODIFIED, b"", content_type, headers)
        return Response(HTTPStatus.OK, asset.body, content_type, headers)

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
        if request.site is not None:
            # The site has signed this person in; a cookie of Workload's own
            # is not consulted at all, so an old one cannot outrank the site.
            ctx.site = request.site
            ctx.user = self._site_user(request.site)
            return
        ctx.token = request.cookies.get(SESSION_COOKIE)
        ctx.user = self.accounts.session_user(ctx.token)

    def _site_user(self, site: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The account for whoever the site says is asking.

        Somebody arriving for the first time is given an account of their own
        with nothing in it: they can start units, and they can see nobody
        else's. Somebody a manager has given access to arrives as that team
        member and sees their own page.
        """
        key = site.get("id")
        login = str(site.get("login") or "").strip()
        name = str(site.get("name") or "").strip()
        try:
            user = self.accounts.site_user(key)
            if user is None:
                try:
                    user = self.accounts.create_site_user(
                        key, login=login, display_name=name)
                except AccountError:
                    # Another worker made it between the look and the insert.
                    user = self.accounts.site_user(key)
        except AccountError:
            return None
        if user is None:
            return None
        if login and user["site_login"] != login:
            # They sign in with something else now. Same person, same units.
            self.accounts.set_site_login(user["id"], login)
            user["site_login"] = login
        email = _site_email(site)
        # Never an administrator, here or on the site: linking would make them
        # a member, and a member reaches none of what they run.
        if email and not user["is_admin"] and not _site_admin(site):
            user = self._link_by_email(user, email)
        if _site_admin(site) and user["role"] == ROLE_MEMBER:
            # A manager picked the site's administrator on Team > Access. The
            # administrator keeps every unit's view instead.
            for row in self.accounts.memberships(user["id"]):
                self.accounts.revoke(user_id=user["id"], unit_id=row["unit_id"])
        if user["role"] == ROLE_MEMBER and not self.accounts.memberships(user["id"]):
            # Every unit they were shown has been taken away again. Rather
            # than leave them at a page with nothing on it for good, they are
            # an ordinary account once more and may start a unit of their own.
            self.accounts.set_role(user["id"], ROLE_MANAGER)
            self._forget_service(user["id"])
            user = self.accounts.user(user["id"])
        return user

    def _link_by_email(self, user: Dict[str, Any], email: str) -> Dict[str, Any]:
        """Link somebody to the team row a manager wrote their email on.

        Only a row nobody else has been given is taken, and never in a unit
        the person runs themselves. Somebody who runs units of their own stays
        a manager: an account cannot be both.
        """
        try:
            rows = self.accounts.rows_for_email(email, user["id"])
        except AccountError:
            return user
        if not rows or self.accounts.units(user["id"]):
            return user
        linked = False
        for row in rows:
            taken = any(m["engineer"] == row["engineer"] and m["user_id"] != user["id"]
                        for m in self.accounts.unit_members(row["unit_id"]))
            if taken:
                continue                   # somebody else is that person already
            if user["role"] != ROLE_MEMBER:
                self._forget_service(user["id"])
                self.accounts.set_role(user["id"], ROLE_MEMBER)
                user = self.accounts.user(user["id"])
            self.accounts.grant(user_id=user["id"], unit_id=row["unit_id"],
                                engineer=row["engineer"],
                                granted_by=row["set_by"] or row["owner_id"])
            self.accounts.mark_email_linked(row["unit_id"], row["engineer"],
                                            user["id"])
            linked = True
        return self.accounts.user(user["id"]) if linked else user

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
        if ctx.site is not None:
            raise ApiError(HTTPStatus.CONFLICT,
                           "You are signed in through the site already.")
        user = self.accounts.verify(body.get("username", ""),
                                    body.get("password", ""))
        if user is None:
            raise ApiError(HTTPStatus.UNAUTHORIZED,
                           "That username and password do not match an account.")
        ctx.set_cookie = self.accounts.start_session(user["id"])
        ctx.user = user
        return {"user": user}

    def logout(self, ctx: Context, query, body) -> Dict[str, Any]:
        if ctx.site is not None:
            # Signing out is the site's to do; the page goes there next.
            return {"signed_out": False, "logout": ctx.site.get("logout")}
        self.accounts.end_session(ctx.token)
        if ctx.user:
            self.accounts.set_open_unit(ctx.user["id"], None)
            self._drop_service(ctx.user["id"])
        ctx.clear_cookie = True
        return {"signed_out": True}

    def whoami(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Public, so the login page can ask whether anyone is signed in."""
        answer = {
            "user": ctx.user,
            "any_accounts": self.accounts.user_count() > 0,
        }
        if ctx.site is not None:
            if ctx.user:
                self.accounts.seen(ctx.user["id"])
            answer["site"] = {
                "home": ctx.site.get("home") or "/",
                "label": ctx.site.get("label") or "Home",
                "logout": ctx.site.get("logout") or "",
                "login": (ctx.user or {}).get("site_login"),
                "admin": _site_admin(ctx.site),
            }
        return answer

    def link_existing(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Bring an account from before Workload moved into the site.

        Whoever used Workload at its own address has units under a username
        and password. Typing those once, here, ties that account to the
        sign-in they use now, and its units are simply there from then on.
        The files do not move and nothing is copied.
        """
        if ctx.site is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "There is nothing to link here.")
        old = self.accounts.verify(body.get("username", ""),
                                   body.get("password", ""))
        if old is None:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                           "That username and password do not match a "
                           "Workload account.")
        current = ctx.user
        if old["id"] == current["id"]:
            return {"user": current, "linked": False}
        if old["site_key"]:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                           "That Workload account already belongs to another "
                           "sign-in on this site.")
        if self.accounts.units(current["id"]) \
                or self.accounts.memberships(current["id"]):
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "You already have units here under this sign-in, and two "
                "accounts cannot be folded into one. Download those units, "
                "delete them, and try again -- then upload them into the "
                "account you bring across.")
        key, login = current["site_key"], current["site_login"]
        self._drop_service(current["id"])
        self.accounts.link_site(current["id"], None)
        if self.accounts.remove_if_empty(current["id"]):
            storage.remove_user_files(self.data_dir, current["id"])
        user = self.accounts.link_site(old["id"], key, login)
        ctx.user = user
        return {"user": user, "linked": True,
                "units": len(self.accounts.units(user["id"]))}

    def change_password(self, ctx: Context, query, body) -> Dict[str, Any]:
        if ctx.site is not None:
            raise ApiError(HTTPStatus.CONFLICT,
                           "Your password is the site's; change it there.")
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

    def list_passwords(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Every account's password, for an administrator who asked to see.

        A separate request from the account list on purpose: passwords cross
        the wire only when somebody presses the button, not on every load.
        """
        return {"passwords": {str(user_id): password for user_id, password
                              in self.accounts.passwords().items()}}

    def create_user(self, ctx: Context, query, body) -> Dict[str, Any]:
        password, _generated = _password_in(body)
        user = self.accounts.create_user(
            body.get("username", ""), password,
            display_name=body.get("display_name", ""),
            is_admin=bool(body.get("is_admin")),
            role=body.get("role") or ROLE_MANAGER)
        # Shown here whether generated or typed; the Admin tab can show it
        # again later, which is what the sealed copy is for.
        return {"user": user, "password": password}

    def reset_password(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        target = self._account_id(user_id)
        password, generated = _password_in(body)
        self.accounts.set_password(target, password)
        self._forget_service(target)
        if target == ctx.user["id"] and ctx.site is None:
            # That ended every session of theirs, this one too: as on the
            # change-password route, the administrator is not thrown out.
            ctx.set_cookie = self.accounts.start_session(target)
        return {"user_id": target, "password": password if generated else None}

    def set_admin(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        target = self._account_id(user_id)
        self.accounts.set_admin(target, bool(body.get("is_admin")))
        return {"user": self.accounts.user(target)}

    def _account_id(self, value: str) -> int:
        """An account's id from a path, or Not Found."""
        try:
            target = int(value)
        except ValueError:
            target = None
        if target is None or self.accounts.user(target) is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "There is no such account.")
        return target

    def delete_user(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        target = self._account_id(user_id)
        if target == ctx.user["id"]:
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                           "You cannot delete the account you are signed in to.")
        self._drop_service(target)
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
                "limit": None,
                "read_only": True,
                "template_available": False,
            }
        out = []
        for unit in self.accounts.units(user_id):
            path = storage.unit_path(self.data_dir, user_id, unit["filename"])
            record = dict(unit)
            record["exists"] = path.is_file()
            if record["exists"]:
                record["size_mb"] = storage.size_mb(path)
            out.append(record)
        return {
            "units": out,
            # No limit: an account holds as many units as it runs.
            "limit": None,
            "template_available": True,
        }

    def create_unit(self, ctx: Context, query, body) -> Dict[str, Any]:
        """A new, empty unit, with the built-in reference tables."""
        return self._start_unit(ctx, query, body, body.get("name", ""),
                                lambda user_id, unit_id: storage.new_unit(
                                    self.data_dir, user_id, unit_id))

    def _start_unit(self, ctx: Context, query, body, name: str,
                    make: Callable[[int, str], Path]) -> Dict[str, Any]:
        """A new unit whose file ``make(user_id, unit_id)`` writes, opened; if
        the file cannot be made, the unit is not kept either."""
        user_id = ctx.user["id"]
        unit = self.accounts.create_unit(user_id, name, "")
        try:
            path = make(user_id, unit["id"])
            self.accounts_update_filename(user_id, unit["id"], path.name)
        except Exception:
            self.accounts.delete_unit(user_id, unit["id"])
            raise
        return self.open_unit(ctx, query, body, unit["id"])

    def create_unit_from_timesheets(self, ctx: Context, query, body
                                    ) -> Dict[str, Any]:
        """A new unit whose only input is its people's timesheet exports.

        It starts empty, and the exports supply the rest: the team, the
        project register, the deliverables and their splits. Left unnamed, the
        unit takes the name the exports give it.
        """
        user_id = ctx.user["id"]
        files = body.get("files") or []
        if not files:
            raise ApiError(HTTPStatus.BAD_REQUEST,
                           "Choose your team's timesheet exports first.")
        wanted = " ".join(str(body.get("name") or "").split())
        unit = self.accounts.create_unit(
            user_id, wanted or f"New unit {uuid.uuid4().hex[:6]}", "")
        path = None
        before = self.accounts.open_unit_of(user_id)
        try:
            path = storage.new_unit(self.data_dir, user_id, unit["id"])
            self.accounts_update_filename(user_id, unit["id"], path.name)
            self.open_unit(ctx, query, body, unit["id"])
            service = ctx.service or self.service_for(user_id)
            imported = service.import_exports(files)
        except Exception:
            if _is_open(ctx, unit["id"]):
                ctx.service.close()
            self.accounts.delete_unit(user_id, unit["id"])
            if path is not None:
                storage.remove_unit_file(self.data_dir, user_id, path.name)
            # Back to the unit they had open before, as if nothing happened.
            self.accounts.set_open_unit(user_id, before)
            if before and ctx.service is not None:
                self._follow_open_unit(ctx)
            raise
        if not wanted:
            self._name_after_exports(ctx, user_id, unit["id"],
                                     imported["staged"].get("unit_name") or "")
        status = service.status()
        status["imported"] = {k: v for k, v in imported.items() if k != "staged"}
        return status

    def _name_after_exports(self, ctx: Context, user_id: int, unit_id: str,
                            name: str) -> None:
        """Name a unit as its exports do, or as near as is free."""
        if not name:
            return
        for candidate in [name] + [f"{name} ({n})" for n in range(2, 10)]:
            try:
                unit = self.accounts.rename_unit(user_id, unit_id, candidate)
            except Exception:
                continue
            if _is_open(ctx, unit_id):
                ctx.service.unit = unit
            return

    def upload_unit(self, ctx: Context, query, body) -> Dict[str, Any]:
        """A new unit from an old Workload workbook somebody still has.

        The workbook is read once, into the unit's own database, and is not
        kept: from then on the unit is the database.
        """
        data = _decode(body.get("content_base64"))
        name = body.get("name") or Path(str(body.get("filename") or "workbook")).stem
        return self._start_unit(ctx, query, body, name,
                                lambda user_id, unit_id: storage.import_workbook(
                                    self.data_dir, user_id, unit_id, data)["path"])

    def replace_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        """Put a copy of a unit back in place of what it holds now.

        The copy is one of the unit's own kept copies, or an old Workload
        workbook. The unit keeps its name, and the accounts your team reach it
        through; what it held is kept as a copy first.
        """
        user_id = ctx.user["id"]
        unit = self._own_unit(user_id, unit_id)
        data = _decode(body.get("content_base64"))
        # Let go of it before it is overwritten underneath us.
        was_open = _is_open(ctx, unit_id)
        if was_open:
            ctx.service.close()
        try:
            if storage.legacy.is_workbook(storage.unit_path(
                    self.data_dir, user_id, unit["filename"])):
                # Still a workbook unit: bring it across first, so what it
                # held is kept as a copy like any other.
                self._unit_file(user_id, unit_id, unit["filename"])
            result = storage.replace_unit_file(self.data_dir, user_id, unit_id, data)
        except Exception:
            if was_open:                   # the upload was refused: as you were
                self._follow_open_unit(ctx)
            raise
        self.accounts_update_filename(user_id, unit_id, result["path"].name)
        opened = self.open_unit(ctx, query, body, unit_id)
        opened["replaced"] = {
            "unit": unit["name"],
            "megabytes": round(len(data) / 1_048_576, 2),
            "previous_kept_as": result["backup"].name if result["backup"] else None,
        }
        return opened

    def accounts_update_filename(self, user_id: int, unit_id: str,
                                 filename: str) -> None:
        self.accounts.set_unit_filename(user_id, unit_id, filename)

    def open_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        user_id = ctx.user["id"]
        service = ctx.service or self.service_for(user_id)
        result = self._open(service, user_id, unit_id)
        self.accounts.touch_unit(user_id, unit_id)
        self.accounts.set_open_unit(user_id, unit_id)
        return result

    def units_together(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Every unit of this account side by side, from each one's Check-ins.

        Each unit is opened in a service of its own, so whatever is open in
        the browser is left exactly as it was.
        """
        from . import across

        user_id = ctx.user["id"]
        current = (ctx.service.unit or {}).get("id") if ctx.service else None
        pairs, missing = [], []
        hours = 8.5
        everyone = ctx.site is not None and _site_admin(ctx.site)
        units = self.accounts.all_units() if everyone else self.accounts.units(user_id)
        for unit in units:
            theirs = unit["user_id"] != user_id
            name = f"{unit['name']} · {unit['owner_name']}" if theirs else unit["name"]
            if unit["id"] == current and ctx.service._wb is not None:
                view = ctx.service.checkins()
            else:
                service = WorkloadService(autosave=self.autosave)
                try:
                    if theirs:
                        # Another manager's unit, looked at and never changed.
                        self._open_to_read(service, unit)
                    else:
                        self._open(service, user_id, unit["id"])
                    view = service.checkins()
                except Exception as error:
                    # One unit that cannot be read (damaged, or an old
                    # workbook that will not come across) is named as
                    # missing; it never takes every other unit's figures
                    # down with it.
                    if not isinstance(error, ApiError):
                        traceback.print_exc()
                    missing.append(name)
                    continue
                finally:
                    service.close()
            hours = view.get("hours_per_day") or hours
            pairs.append((across.unit_summary(name, unit["id"], view), view))
        result = across.combine(pairs, hours_per_day=hours)
        result["missing"] = missing
        result["current"] = current
        result["everyone"] = everyone
        return result

    def _open_to_read(self, service: WorkloadService, unit: Dict[str, Any]) -> None:
        path = self._unit_file_or_missing(
            unit["user_id"], unit["id"], unit["filename"],
            f"The data for {unit['name']} is missing.")
        service.open(path, unit={"id": unit["id"], "name": unit["name"]},
                     read_only=True)

    def close_unit(self, ctx: Context, query, body) -> Dict[str, Any]:
        self.accounts.set_open_unit(ctx.user["id"], None)
        return ctx.service.close()

    def _own_unit(self, user_id: int, unit_id: str) -> Dict[str, Any]:
        """One of this account's units; anybody else's is simply not found."""
        unit = self.accounts.unit(user_id, unit_id)
        if unit is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "That unit is not yours.")
        return unit

    def _open(self, service: WorkloadService, user_id: int,
              unit_id: str) -> Dict[str, Any]:
        """Open one of this account's units in ``service``."""
        unit = self._own_unit(user_id, unit_id)
        path = self._unit_file_or_missing(user_id, unit_id, unit["filename"],
                                          f"The data for {unit['name']} is missing.")
        unit = self.accounts.unit(user_id, unit_id)
        try:
            storage.backup_if_due(self.data_dir, user_id, path)
        except Exception:                  # pragma: no cover - a copy is a
            traceback.print_exc()          # nicety, never a reason not to open
        return service.open(path, unit=unit,
                            keep_copy=self._copier(user_id, path))

    def _copier(self, owner_id: int, path: Path):
        """What a service calls to keep a dated copy of the unit it has open."""
        return functools.partial(storage.keep_a_copy, self.data_dir, owner_id, path)

    def _unit_file(self, owner_id: int, unit_id: str, filename: str) -> Path:
        """The unit's database, brought across from its old workbook if it
        still has one."""
        result = storage.bring_across(self.data_dir, owner_id, unit_id, filename)
        if result["filename"] != filename:
            self.accounts_update_filename(owner_id, unit_id, result["filename"])
        return result["path"]

    def _unit_file_or_missing(self, owner_id: int, unit_id: str, filename: str,
                              missing: str) -> Path:
        """:meth:`_unit_file`, or Not Found saying ``missing`` when the unit's
        data is not on disk at all."""
        if not storage.unit_path(self.data_dir, owner_id, filename).is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, missing)
        return self._unit_file(owner_id, unit_id, filename)

    def rename_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        # Look first, so a unit that is not this account's is refused the same
        # way everywhere: not found, rather than a rule about names.
        self._own_unit(ctx.user["id"], unit_id)
        unit = self.accounts.rename_unit(ctx.user["id"], unit_id,
                                         body.get("name", ""))
        if _is_open(ctx, unit_id):
            ctx.service.unit = unit
        return {"unit": unit}

    def delete_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        user_id = ctx.user["id"]
        unit = self._own_unit(user_id, unit_id)
        if _is_open(ctx, unit_id):
            ctx.service.close()
        if self.accounts.open_unit_of(user_id) == unit_id:
            self.accounts.set_open_unit(user_id, None)
        self.accounts.delete_unit(user_id, unit_id)
        storage.remove_unit_file(self.data_dir, user_id, unit["filename"])
        return {"deleted": unit_id, "name": unit["name"]}

    def download_unit(self, ctx: Context, query, body, unit_id) -> Dict[str, Any]:
        """Everything the unit holds, as a spreadsheet to keep or send on."""
        user_id = ctx.user["id"]
        unit = self._own_unit(user_id, unit_id)
        path = self._unit_file_or_missing(user_id, unit_id, unit["filename"],
                                          "That unit's data is missing.")
        if _is_open(ctx, unit_id):
            data = export_module.unit_workbook(ctx.service.workbook, unit["name"])
        else:
            data = export_module.unit_workbook(storage.Unit(path), unit["name"])
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
        granted, row, service = self._member_unit(
            ctx, (query.get("unit") or [None])[0])
        person = self._person_shown(row, service, query)

        kind = (query.get("period") or ["year"])[0]
        data = member_view.build(
            service.workbook, person, kind=kind, year=_year(query),
            quarter=(query.get("quarter") or [None])[0],
            store=service._store)                      # noqa: SLF001 - same app
        data["unit"] = {"id": row["unit_id"], "name": row["unit_name"],
                        "manager": row.get("owner_name") or ""}
        data["units"] = [{"id": g["unit_id"], "name": g["unit_name"],
                          "engineer": g["engineer"]} for g in granted]
        data["viewer"] = row["engineer"]
        data["people"] = [row["engineer"]] + self._led_by(service, row["engineer"])
        return data

    def _led_by(self, service: WorkloadService, engineer: str) -> List[str]:
        """Who a member may look at besides themselves: the people they lead
        (a team they lead, or the whole unit when their grade is Manager),
        and of those only the ones graded below them. An engineer leads
        nobody, so sees nobody else."""
        store = service._store                          # noqa: SLF001 - same app
        people = store.people()
        grades = {p["name"]: p.get("grade") or DEFAULT_GRADE for p in people}

        def rank(name: str) -> int:
            grade = grades.get(name, DEFAULT_GRADE)
            return GRADE_KEYS.index(grade) if grade in GRADE_KEYS else len(GRADE_KEYS)

        known = set(service.workbook.engineer_names())
        led = management.leaders(people, store.teams()).get(engineer, [])
        return sorted(p["name"] for p in led
                      if p["name"] in known and rank(p["name"]) > rank(engineer))

    def _person_shown(self, row: Dict[str, Any], service: WorkloadService,
                      query) -> str:
        """Whose figures to show: the member's own, or, when they asked for
        somebody, one of the people below them. Anybody else is Not Found,
        the same answer as a name that is not there at all."""
        wanted = " ".join(str((query.get("person") or [""])[0] or "").split())
        if not wanted or wanted == row["engineer"]:
            return row["engineer"]
        if wanted in self._led_by(service, row["engineer"]):
            return wanted
        raise ApiError(HTTPStatus.NOT_FOUND,
                       "You can see your own figures and those of the people "
                       "you lead, and nobody else's.")

    def _member_unit(self, ctx: Context, wanted: Optional[str]):
        """The unit a member was given access to, open for reading, and the
        row that says who in it they are."""
        granted = self.accounts.memberships(ctx.user["id"])
        if not granted:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "No unit has been shared with you yet. Your manager can do "
                "that from their Team tab.")
        row = next((g for g in granted if g["unit_id"] == wanted), granted[0])
        path = self._unit_file_or_missing(row["owner_id"], row["unit_id"],
                                          row["filename"],
                                          "That unit is not there any more.")

        service = ctx.service
        if service.path != path or not service.read_only:
            service.open(path, unit={"id": row["unit_id"],
                                     "name": row["unit_name"]},
                         read_only=True)
        return granted, row, service

    # ------------------------------------------------------------------
    # My day: the only things a member can change, and only their own
    # ------------------------------------------------------------------

    def _mine(self, ctx: Context, query, body):
        """Who this member is in the unit they asked about -- from their
        access, never from anything they sent."""
        wanted = (query.get("unit") or [None])[0] or (body or {}).get("unit")
        _, row, service = self._member_unit(ctx, wanted)
        return row, service

    def my_day(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.my_day(self._person_shown(row, service, query), query)

    def my_timesheet(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.my_timesheet(self._person_shown(row, service, query), query)

    def mark_my_task(self, ctx: Context, query, body, task_id) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        result = service.mark_my_task(row["engineer"], task_id, body)
        if result["mark"]["kind"] != "done":
            self._tell_leads(row)
        return result

    def ask_for_help(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        result = service.ask_for_help(row["engineer"], body)
        self._tell_leads(row)
        return result

    def undo_my_mark(self, ctx: Context, query, body, mark_id) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.undo_my_mark(row["engineer"], mark_id)

    def add_my_time_off(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        result = service.add_my_time_off(row["engineer"], body)
        self._tell_leads(row)
        return result

    def remove_my_time_off(self, ctx: Context, query, body, mark_id) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.remove_my_time_off(row["engineer"], mark_id)

    def my_week(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.my_week(row["engineer"], query)

    def my_slip_reason(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.set_slip_reason(body or {}, engineer=row["engineer"])

    #: Set to False by tests: the phones are told on a thread of its own.
    tell_in_background = True
    #: Set when served over WSGI: the phones are told after the response has
    #: gone back, since a host may not run threads between requests.
    tell_after_response = False

    # ------------------------------------------------------------------
    # Outlook calendars: busy times only (see busy_calendar)
    # ------------------------------------------------------------------

    #: How long a calendar read stays fresh before opening the plan reads it
    #: again.
    calendar_fresh_seconds = 20 * 60
    #: The calendars read at once.
    calendar_workers = 6
    #: What reads a link; tests give their own.
    calendar_fetch = staticmethod(busy_calendar.fetch)

    def _read_calendars(self, service, people=None, *, force: bool = False
                        ) -> Dict[str, Any]:
        """Read the linked calendars that are due, and keep their busy times.
        The network is used outside the unit's lock, a few calendars at once."""
        seals = service.calendar_seals(people)
        now = time.monotonic()
        checked = self._calendar_checked
        due = {name: blob for name, blob in seals.items()
               if force or now - checked.get((str(service.path), name), -1e9)
               >= self.calendar_fresh_seconds}
        if not due:
            return {"read": 0, "changed": 0, "problems": []}
        first, last = busy_calendar.window(service_today())
        day_start, day_end = service.working_hours()
        zones = service.calendar_zones()

        def read(item):
            name, blob = item
            link = self.accounts.unseal(blob)
            if not link:
                return name, None, ("The link can no longer be read here; "
                                    "paste it again.")
            try:
                text = self.calendar_fetch(link)
                return name, busy_calendar.busy_times(
                    text, start=first, end=last,
                    day_start=day_start, day_end=day_end,
                    home=zones.get(name)), ""
            except busy_calendar.CalendarLinkError as exc:
                return name, None, " ".join(exc.errors)
            except Exception as exc:          # a broken file is that person's
                traceback.print_exc()          # problem, never the page's
                return name, None, f"That calendar could not be read ({type(exc).__name__})."

        items = sorted(due.items())
        if len(items) == 1 or self.calendar_workers <= 1:
            results = [read(item) for item in items]
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(self.calendar_workers,
                                                    len(items))) as pool:
                results = list(pool.map(read, items))
        changed = 0
        problems = []
        for name, busy, problem in results:
            checked[(str(service.path), name)] = now
            if problem:
                problems.append({"person": name, "problem": problem})
            changed += bool(service.record_calendar(name, busy=busy, problem=problem))
        return {"read": len(results), "changed": changed, "problems": problems}

    def _calendar_link(self, body) -> str:
        return busy_calendar.clean_link((body or {}).get("link"))

    # -- the manager: everybody's
    def calendars(self, ctx: Context, query, body) -> Dict[str, Any]:
        return ctx.service.calendars()

    def set_calendar(self, ctx: Context, query, body) -> Dict[str, Any]:
        person = " ".join(str((body or {}).get("person") or "").split())
        link = self._calendar_link(body)
        ctx.service.set_calendar_link(person, self.accounts.seal(link), "manager")
        result = self._read_calendars(ctx.service, [person], force=True)
        return {**ctx.service.calendars(), "result": result}

    def remove_calendar(self, ctx: Context, query, body) -> Dict[str, Any]:
        person = " ".join(str((body or {}).get("person") or "").split())
        ctx.service.remove_calendar_link(person)
        return ctx.service.calendars()

    def refresh_calendars(self, ctx: Context, query, body) -> Dict[str, Any]:
        result = self._read_calendars(ctx.service,
                                      force=bool((body or {}).get("force")))
        return {**ctx.service.calendars(), "result": result}

    # -- meetings typed in: a member's own
    def my_meetings(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.meetings(person=row["engineer"])

    def add_my_meeting(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.add_meeting(body or {}, person=row["engineer"])

    def remove_my_meeting(self, ctx: Context, query, body, meeting_id) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.remove_meeting(meeting_id, person=row["engineer"])

    # -- a member: their own, and nobody else's
    def my_calendar(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        return service.calendars(person=row["engineer"])

    def set_my_calendar(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        link = self._calendar_link(body)
        service.set_calendar_link(row["engineer"], self.accounts.seal(link), "self")
        result = self._read_calendars(service, [row["engineer"]], force=True)
        return {**service.calendars(person=row["engineer"]), "result": result}

    def remove_my_calendar(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        service.remove_calendar_link(row["engineer"])
        return service.calendars(person=row["engineer"])

    def refresh_my_calendar(self, ctx: Context, query, body) -> Dict[str, Any]:
        row, service = self._mine(ctx, query, body)
        result = self._read_calendars(service, [row["engineer"]],
                                      force=bool((body or {}).get("force")))
        return {**service.calendars(person=row["engineer"]), "result": result}

    def _tell_leads(self, row: Dict[str, Any]) -> None:
        """Tell the manager's and team leads' phones now, not at 04:00. Each
        hears only what is theirs (see notify), and a tap never waits on it."""
        self._tell(row["owner_id"], row["unit_id"])

    def _tell(self, owner_id: int, unit_id: str) -> None:
        """Send whatever a change to this unit makes new, to the phones of
        everybody on it."""
        people = notify.people_of_unit(self, owner_id, unit_id)

        def run() -> None:
            try:
                notify.run(self, user_ids=people, unit_ids=[unit_id])
            except Exception:              # pragma: no cover - a notification
                traceback.print_exc()      # never fails what was said
        if not self.tell_in_background:
            run()
        elif self.tell_after_response:
            # Under WSGI: once the answer has gone back (wsgi.py), so the
            # person who made the change never waits for the phones.
            with self._services_lock:
                self._to_tell[unit_id] = (owner_id, time.monotonic())
        else:
            threading.Thread(target=run, daemon=True).start()

    def tell_pending(self, older_than: float = 0.0) -> None:
        """Tell the phones about the changes waiting to be told."""
        now = time.monotonic()
        with self._services_lock:
            due = {u: o for u, (o, at) in self._to_tell.items() if now - at >= older_than}
            for unit_id in due:
                self._to_tell.pop(unit_id, None)
        for unit_id, owner_id in due.items():
            try:
                notify.run(self, user_ids=notify.people_of_unit(self, owner_id, unit_id),
                           unit_ids=[unit_id])
            except Exception:              # pragma: no cover - best effort
                traceback.print_exc()

    def _unit_version(self, ctx: Context) -> Optional[Tuple[str, Any]]:
        """Which unit the manager has open, and which version of it."""
        service = ctx.service
        if (service is None or ctx.user is None or ctx.user["role"] != ROLE_MANAGER
                or service._wb is None or not isinstance(service.unit, dict)):
            return None
        try:
            return service.unit["id"], service._wb._read_revision()
        except Exception:                  # pragma: no cover - deleted under us
            return None

    # ------------------------------------------------------------------
    # who on the team has an account
    # ------------------------------------------------------------------

    def team_access(self, ctx: Context, query, body) -> Dict[str, Any]:
        unit = self._open_unit_or_refuse(ctx)
        answer = {
            "unit": {"id": unit["id"], "name": unit["name"]},
            "members": self.accounts.unit_members(unit["id"]),
            "engineers": ctx.service.workbook.engineer_names(),
            "emails": {name: row["email"] for name, row
                       in self.accounts.member_emails(unit["id"]).items()},
        }
        if ctx.site is not None:
            mine = ctx.user.get("site_key")
            answer["site"] = {
                "people": sorted(
                    (p for p in self._people().values() if p["id"] != mine),
                    key=lambda p: (p["name"] or p["login"]).lower()),
            }
        return answer

    def _people(self) -> Dict[str, Dict[str, str]]:
        """Who can sign in to the site, by the site's identifier for them."""
        out: Dict[str, Dict[str, str]] = {}
        for person in (self.site_people() if self.site_people else []):
            key = str(person.get("id") if person.get("id") is not None else "").strip()
            if key:
                out[key] = {"id": key,
                            "login": str(person.get("login") or "").strip(),
                            "name": str(person.get("name") or "").strip()}
        return out

    def grant_access(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Give one person a read-only account for their own figures."""
        unit = self._open_unit_or_refuse(ctx)
        engineer = str(body.get("engineer") or "").strip()
        if engineer not in ctx.service.workbook.engineer_names():
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                           f"{engineer!r} is not on this unit's team.")
        if ctx.site is not None:
            return self._grant_site_access(ctx, unit, engineer, body)

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
            others = {m["owner_id"] for m in self.accounts.memberships(existing["id"])}
            if others - {ctx.user["id"]}:
                # Somebody else's team member: not yours to add to a unit, or
                # to learn anything about.
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                               "That username is taken. Choose another.")
            user = existing

        self.accounts.grant(user_id=user["id"], unit_id=unit["id"],
                            engineer=engineer, granted_by=ctx.user["id"])
        return {"user": user, "engineer": engineer,
                "password": password}          # shown once, never stored

    def _grant_site_access(self, ctx: Context, unit: Dict[str, Any],
                           engineer: str, body) -> Dict[str, Any]:
        """Give access to somebody who signs in to the site.

        There is no password to hand over: they sign in to the site as they
        always do, open Workload, and land on their own page.
        """
        key = accounts_module.clean_site_key(body.get("person"))
        if key == ctx.user.get("site_key"):
            raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                           "That is your own sign-in; you already see the "
                           "whole unit.")
        known = self._people().get(key)
        if known is None:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "That is not somebody who can open Selecao+ on this site. Ask "
                "the administrator to make them an account with Selecao+ "
                "ticked, then give them access here.")
        who = known["name"] or known["login"] or engineer

        existing = self.accounts.site_user(key)
        if existing is None:
            user = self.accounts.create_site_user(
                key, login=known["login"], display_name=who, role=ROLE_MEMBER)
        elif existing["role"] != ROLE_MEMBER:
            if existing["is_admin"] or self.accounts.units(existing["id"]):
                raise ApiError(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    f"{who} runs units of their own here; an account that "
                    f"manages units cannot also be given one person's view.")
            # They opened Workload before anybody had given them anything, so
            # they were made an empty account of their own. Nothing is lost by
            # making that account the team member it was meant to be.
            self._forget_service(existing["id"])
            self.accounts.set_role(existing["id"], ROLE_MEMBER)
            user = self.accounts.user(existing["id"])
        else:
            user = existing

        self.accounts.grant(user_id=user["id"], unit_id=unit["id"],
                            engineer=engineer, granted_by=ctx.user["id"])
        return {"user": user, "engineer": engineer, "password": None}

    def revoke_access(self, ctx: Context, query, body, user_id) -> Dict[str, Any]:
        unit = self._open_unit_or_refuse(ctx)
        try:
            target = int(user_id)
        except ValueError:
            target = None
        held = None if target is None else self.accounts.membership(target, unit["id"])
        if held is None:
            raise ApiError(HTTPStatus.NOT_FOUND,
                           "That account has no access to this unit.")
        engineer = held["engineer"]
        self.accounts.revoke(user_id=target, unit_id=unit["id"])
        self._forget_service(target)
        # Their email would only link them straight back in at their next
        # sign-in, so it goes too.
        linked = self.accounts.member_emails(unit["id"]).get(engineer)
        if linked and linked["linked_user"] == target:
            self.accounts.forget_member_email(unit["id"], engineer)
        return {"revoked": target}

    def add_engineer(self, ctx: Context, query, body) -> Dict[str, Any]:
        email = self._email_in(ctx, body, None)
        unit = ctx.service.unit
        result = ctx.service.add_engineer(body)
        if unit and email:
            result["email"] = self.accounts.set_member_email(
                unit["id"], result["engineer"], email,
                set_by=ctx.user["id"])["email"]
        return result

    def _email_in(self, ctx: Context, body, engineer: Optional[str]) -> Optional[str]:
        """The email sent for ``engineer``, if any; refused, before anything
        is saved, when somebody else in the open unit has it."""
        email = accounts_module.clean_email(body.get("email")) \
            if "email" in body else None
        unit = ctx.service.unit
        if unit and email:
            taken = next((who for who, row
                          in self.accounts.member_emails(unit["id"]).items()
                          if row["email"] == email and who != engineer), None)
            if taken:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY,
                               f"{taken} already has that email in this unit. "
                               f"Each person needs their own.")
        return email

    def _save_email(self, ctx: Context, unit: Dict[str, Any], engineer: str,
                    email: str) -> str:
        saved = self.accounts.set_member_email(unit["id"], engineer, email,
                                               set_by=ctx.user["id"])
        gone = saved["unlinked"]
        if gone is not None:
            held = self.accounts.membership(gone, unit["id"])
            if held and held["engineer"] == engineer:
                # A corrected email never leaves the wrong person looking in.
                self.accounts.revoke(user_id=gone, unit_id=unit["id"])
                self._forget_service(gone)
        return saved["email"]

    def update_engineer(self, ctx: Context, query, body, name) -> Dict[str, Any]:
        """Rename or re-rate an engineer, and keep any access in step."""
        email = self._email_in(ctx, body, name)
        unit = ctx.service.unit
        result = ctx.service.update_engineer(name, body)
        renamed = result.get("engineer") or name
        if unit and renamed != name:
            # Otherwise a rename would quietly cut that person off from their
            # own page, which looks exactly like a bug to them.
            self.accounts.rename_engineer_in_memberships(unit["id"], name, renamed)
        if unit and email is not None:
            result["email"] = self._save_email(ctx, unit, renamed, email)
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
                    self._forget_service(row["user_id"])
                    result.setdefault("access_revoked", []).append(row["username"])
            self.accounts.forget_member_email(unit["id"], name)
        return result

    def _open_unit_or_refuse(self, ctx: Context) -> Dict[str, Any]:
        """The unit this manager has open, or a plain refusal."""
        unit = ctx.service.unit if ctx.service else None
        if not unit:
            raise ApiError(HTTPStatus.CONFLICT,
                           "Open the unit first; access is given per unit.")
        return self._own_unit(ctx.user["id"], unit["id"])

    # -- the nightly import ----------------------------------------------
    #
    # A job on the manager's PC exports from BISpark at night and posts the
    # file here.  It has no browser session, so it signs with the unit's
    # import key; see nightly.py.

    def import_key_status(self, ctx: Context, query, body) -> Dict[str, Any]:
        unit = self._open_unit_or_refuse(ctx)
        return {"unit": unit["name"],
                "source": nightly.source(ctx.service),
                "key": self.accounts.import_key_info(ctx.user["id"], unit["id"])}

    def save_import_source(self, ctx: Context, query, body) -> Dict[str, Any]:
        """The export request, pasted once from the browser."""
        self._open_unit_or_refuse(ctx)
        return {"source": nightly.save_source(ctx.service, body)}

    def team_kit(self, ctx: Context, query, body) -> Dict[str, Any]:
        """The kit for a team member's PC: export to the shared folder, no key."""
        self._open_unit_or_refuse(ctx)
        folder = nightly.source(ctx.service)["shared_folder"]
        if not folder:
            raise ApiError(HTTPStatus.CONFLICT,
                           "Give the team's shared folder first.")
        return {"filename": "selecao-nightly-team.zip",
                "kit_base64": nightly.encode(nightly.kit(
                    nightly.request_for(ctx.service), shared_folder=folder))}

    def make_import_key(self, ctx: Context, query, body) -> Dict[str, Any]:
        """A new key for the open unit, and the kit for the PC built round it.

        The key is in the kit and nowhere else: only its digest is kept, so
        making a new one is also how an old PC is shut out.
        """
        unit = self._open_unit_or_refuse(ctx)
        app_url = str(body.get("app_url") or "").strip()
        if not app_url.startswith(("https://", "http://")):
            raise ApiError(HTTPStatus.BAD_REQUEST,
                           "Say where Selecao+ is, as a web address.")
        request = nightly.request_for(ctx.service)
        folder = nightly.source(ctx.service)["shared_folder"]
        key = self.accounts.make_import_key(ctx.user["id"], unit["id"])
        return {"unit": unit["name"],
                "filename": "selecao-nightly-manager.zip",
                "kit_base64": nightly.encode(nightly.kit(
                    request, shared_folder=folder, app_url=app_url, key=key,
                    budget_requests=budgets.requests(ctx.service))),
                "key": self.accounts.import_key_info(ctx.user["id"], unit["id"])}

    def revoke_import_key(self, ctx: Context, query, body) -> Dict[str, Any]:
        unit = self._open_unit_or_refuse(ctx)
        return {"revoked": self.accounts.revoke_import_key(ctx.user["id"],
                                                           unit["id"])}

    def nightly_import(self, ctx: Context, query, body) -> Dict[str, Any]:
        owner = self.accounts.import_key_owner(body.get("key"))
        if owner is None:
            raise ApiError(HTTPStatus.UNAUTHORIZED,
                           "That import key is not recognised. Make a new one "
                           "on the Timesheets tab.")
        user, unit = owner["user"], owner["unit"]
        if user["role"] != ROLE_MANAGER:
            raise ApiError(HTTPStatus.FORBIDDEN,
                           "Only a manager's unit takes a nightly import.")
        if body.get("failed"):
            # The PC could not get an export out of BISpark.  Nothing to
            # import, but the morning's Timesheets tab should say so.
            self.accounts.record_import(unit["id"], {
                "ok": False, "error": str(body["failed"])[:500], "errors": []})
            return {"ok": False, "recorded": True}
        # A service of its own: whatever the manager has open in the browser,
        # and anything they have staged there, is left exactly as it was.
        service = WorkloadService(autosave=self.autosave)
        kind = str(body.get("kind") or "timesheets")
        if kind != "timesheets":
            # The budgets step. Its answer is for the PC's log alone: the
            # Timesheets tab keeps showing how the timesheets went.
            try:
                self._open(service, user["id"], unit["id"])
                return {"ok": True, "unit": unit["name"],
                        **nightly.run_budgets(service, kind, body.get("files") or [])}
            finally:
                service.close()
        try:
            self._open(service, user["id"], unit["id"])
            late = body.get("late") or []
            result = nightly.run(service, body.get("files") or [],
                                 late if isinstance(late, list) else [late])
        except Exception as error:
            # Whatever stopped it, the morning's Timesheets tab must not go on
            # showing the last night that worked.
            message = (error.message if isinstance(error, ApiError)
                       else str(error) or type(error).__name__)
            errors = error.errors if isinstance(error, ApiError) else [message]
            self.accounts.record_import(unit["id"], {
                "ok": False, "error": message, "errors": errors})
            raise
        finally:
            service.close()
        result = {"ok": True, "unit": unit["name"], **result}
        self.accounts.record_import(unit["id"], result)
        # Fresh timesheets can change what needs the manager: tell their phone.
        try:
            notify.run(self, user_ids=notify.people_of_unit(self, user["id"], unit["id"]),
                       unit_ids=[unit["id"]])
        except Exception:                  # pragma: no cover - a notification
            traceback.print_exc()          # never fails an import
        return result

    # ------------------------------------------------------------------
    # the weekly report, and notifications on the manager's phone
    # ------------------------------------------------------------------

    def weekly_download(self, ctx: Context, query, body) -> Dict[str, Any]:
        """The report as a page to keep, send on or print to PDF."""
        report = ctx.service.weekly()
        data = weekly_module.as_html(report).encode("utf-8")
        name = re.sub(r'[\\/:*?"<>|]+', " ", report["unit"] or "Selecao+").strip()
        return {"filename": f"{name} weekly report {report['week_start']}.html",
                "size_bytes": len(data),
                "content_base64": base64.b64encode(data).decode("ascii")}

    def push_status(self, ctx: Context, query, body) -> Dict[str, Any]:
        user_id = ctx.user["id"]
        devices = []
        for device in self.accounts.push_devices(user_id, secrets_too=True):
            # Enough for a phone to know itself in the list; the address
            # itself never leaves the server again.
            device["fingerprint"] = hashlib.sha256(
                device.pop("endpoint").encode("utf-8")).hexdigest()[:12]
            device.pop("auth")
            device.pop("p256dh")
            devices.append(device)
        manager = ctx.user["role"] == ROLE_MANAGER
        return {"public_key": notify.keys_for(self.data_dir).public,
                "devices": devices,
                "messages": self.accounts.push_messages(user_id),
                "about": notify.ABOUT_MANAGER if manager else notify.ABOUT_MEMBER,
                # The host's scheduled task is the manager's to set up, once.
                "task": notify.task_command(self) if manager else None}

    def push_subscribe(self, ctx: Context, query, body) -> Dict[str, Any]:
        endpoint = str(body.get("endpoint") or "").strip()
        keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
        auth, p256dh = str(keys.get("auth") or ""), str(keys.get("p256dh") or "")
        if not endpoint.startswith("https://") or len(endpoint) > 1000:
            raise ApiError(HTTPStatus.BAD_REQUEST, "That is not a push address.")
        try:
            webpush._point(webpush.unb64url(p256dh))
            if len(webpush.unb64url(auth)) < 16:
                raise ValueError
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST,
                           "This browser sent keys that cannot be used.")
        site = str(body.get("site") or "").strip()
        if not site.startswith("https://"):
            site = ""
        device = self.accounts.add_push_device(
            ctx.user["id"], endpoint=endpoint, auth=auth, p256dh=p256dh,
            label=str(body.get("label") or "").strip(), site=site)
        return {"device": device}

    def push_unsubscribe(self, ctx: Context, query, body, device_id) -> Dict[str, Any]:
        return {"removed": self.accounts.remove_push_device(
            ctx.user["id"], _int(device_id))}

    def push_test(self, ctx: Context, query, body) -> Dict[str, Any]:
        if not self.accounts.push_devices(ctx.user["id"]):
            raise ApiError(HTTPStatus.CONFLICT,
                           "Turn notifications on on this phone first.")
        return {"results": notify.test(self, ctx.user["id"])}

    def push_check(self, ctx: Context, query, body) -> Dict[str, Any]:
        """Look now, rather than waiting for the morning's run."""
        return notify.run(self, user_ids=[ctx.user["id"]])

    # ------------------------------------------------------------------
    # the routes
    # ------------------------------------------------------------------

    def _build_routes(self) -> List[Route]:
        def s(method_name: str, *, body: bool = False):
            """A route that is simply a call on the account's own service, with
            what the path captured and then, when ``body`` is set, the body."""
            def call(ctx: Context, query, request_body, *captured):
                args = (*captured, request_body) if body else captured
                return getattr(ctx.service, method_name)(*args)
            return call

        return [
            # -- who you are
            ("GET", "/api/auth/me", self.whoami, "public"),
            ("POST", "/api/auth/login", self.login, "public"),
            ("POST", "/api/auth/logout", self.logout, "public"),
            ("POST", "/api/auth/password", self.change_password, "user"),
            ("POST", "/api/auth/link", self.link_existing, "manager"),

            # -- administration
            ("GET", "/api/admin/users", self.list_users, "admin"),
            ("GET", "/api/admin/passwords", self.list_passwords, "admin"),
            ("POST", "/api/admin/users", self.create_user, "admin"),
            ("POST", "/api/admin/users/{}/password", self.reset_password, "admin"),
            ("POST", "/api/admin/users/{}/admin", self.set_admin, "admin"),
            ("DELETE", "/api/admin/users/{}", self.delete_user, "admin"),

            # -- a team member's own page, which is all they can reach
            ("GET", "/api/me", self.my_view, "user"),
            ("GET", "/api/me/day", self.my_day, "user"),
            ("GET", "/api/me/timesheet", self.my_timesheet, "user"),
            ("POST", "/api/me/tasks/{}/mark", self.mark_my_task, "user"),
            ("POST", "/api/me/help", self.ask_for_help, "user"),
            ("POST", "/api/me/marks/{}/undo", self.undo_my_mark, "user"),
            ("POST", "/api/me/off", self.add_my_time_off, "user"),
            ("POST", "/api/me/off/{}/remove", self.remove_my_time_off, "user"),
            ("GET", "/api/me/week", self.my_week, "user"),
            ("POST", "/api/me/week/reason", self.my_slip_reason, "user"),
            ("GET", "/api/me/meetings", self.my_meetings, "user"),
            ("POST", "/api/me/meetings", self.add_my_meeting, "user"),
            ("POST", "/api/me/meetings/{}/remove", self.remove_my_meeting, "user"),
            ("GET", "/api/me/calendar", self.my_calendar, "user"),
            ("PUT", "/api/me/calendar", self.set_my_calendar, "user"),
            ("POST", "/api/me/calendar/remove", self.remove_my_calendar, "user"),
            ("POST", "/api/me/calendar/refresh", self.refresh_my_calendar, "user"),
            ("POST", "/api/marks/{}/seen",
             lambda ctx, q, b, mark_id: ctx.service.seen_mark(_int(mark_id)), "manager"),

            # -- this account's units
            ("GET", "/api/units", self.units, "user"),
            ("POST", "/api/units", self.create_unit, "manager"),
            ("POST", "/api/units/from-timesheets",
             self.create_unit_from_timesheets, "manager"),
            ("POST", "/api/units/upload", self.upload_unit, "manager"),
            ("POST", "/api/units/{}/replace", self.replace_unit, "manager"),
            ("POST", "/api/units/{}/open", self.open_unit, "manager"),
            ("PUT", "/api/units/{}", self.rename_unit, "manager"),
            ("DELETE", "/api/units/{}", self.delete_unit, "manager"),
            ("GET", "/api/units/{}/download", self.download_unit, "manager"),
            ("POST", "/api/units/close", self.close_unit, "manager"),

            # -- the workbook that account has open
            ("GET", "/api/status", s("status"), "manager"),
            ("GET", "/api/reference", s("reference"), "manager"),
            ("POST", "/api/reference/unlock",
             lambda ctx, q, b: ctx.service.unlock(b.get("password", "")), "manager"),
            ("POST", "/api/reference/lock", s("lock"), "manager"),
            ("PUT", "/api/reference", s("save_reference", body=True), "manager"),
            ("GET", "/api/overview",
             lambda ctx, q, b: ctx.service.overview(_year(q)), "manager"),
            ("GET", "/api/projects", s("projects"), "manager"),
            ("POST", "/api/projects", s("add_project", body=True), "manager"),
            ("PUT", "/api/projects/{}", s("update_project", body=True), "manager"),
            ("DELETE", "/api/projects/{}",
             lambda ctx, q, b, number: ctx.service.delete_project(
                 number, _flag(q, "cascade")), "manager"),
            ("GET", "/api/deliverables", s("deliverables"), "manager"),
            ("GET", "/api/projects/{}", s("project_detail"), "manager"),
            ("POST", "/api/projects/full",
             lambda ctx, q, b: ctx.service.save_project_with_deliverables(None, b),
             "manager"),
            ("PUT", "/api/projects/{}/full",
             s("save_project_with_deliverables", body=True), "manager"),
            ("POST", "/api/deliverables", s("add_deliverable", body=True), "manager"),
            ("PUT", "/api/deliverables/{}",
             lambda ctx, q, b, row: ctx.service.update_deliverable(_int(row), b),
             "manager"),
            ("DELETE", "/api/deliverables/{}",
             lambda ctx, q, b, row: ctx.service.delete_deliverable(_int(row)), "manager"),
            # -- the establishment: teams, grades, and where to move people
            ("GET", "/api/people", s("roster"), "manager"),
            ("PUT", "/api/people/{}", s("save_person", body=True), "manager"),
            ("DELETE", "/api/people/{}", s("remove_person"), "manager"),
            ("POST", "/api/people/move", s("move_people", body=True), "manager"),
            ("GET", "/api/resourcing",
             lambda ctx, q, b: ctx.service.resourcing(_year(q)), "manager"),
            ("GET", "/api/portfolio-map",
             lambda ctx, q, b: ctx.service.portfolio_map(_year(q)), "manager"),
            ("GET", "/api/drawings", s("drawings"), "manager"),
            ("PUT", "/api/drawings", s("save_drawings", body=True), "manager"),
            ("GET", "/api/drawing-list/template",
             s("drawing_list_template"), "manager"),
            ("POST", "/api/drawing-list",
             s("import_drawing_list", body=True), "manager"),
            ("POST", "/api/drawing-list/apply",
             s("apply_drawing_list", body=True), "manager"),
            ("POST", "/api/planner", s("planner", body=True), "manager"),
            ("POST", "/api/planner/suggest",
             s("planner_suggest", body=True), "manager"),
            ("POST", "/api/planner/commit", s("planner_commit", body=True), "manager"),
            ("POST", "/api/planner/moves/{}/remove",
             lambda ctx, q, b, move_id: ctx.service.remove_plan_move(_int(move_id), b),
             "manager"),
            ("GET", "/api/needs", s("needs"), "manager"),
            ("GET", "/api/checkins", s("checkins"), "manager"),
            ("GET", "/api/growth", lambda ctx, q, b: ctx.service.growth(q), "manager"),
            ("POST", "/api/growth/goals", s("add_goal", body=True), "manager"),
            ("PUT", "/api/growth/goals/{}",
             lambda ctx, q, b, goal_id: ctx.service.edit_goal(_int(goal_id), b), "manager"),
            ("POST", "/api/growth/goals/{}/review",
             lambda ctx, q, b, goal_id: ctx.service.review_goal(_int(goal_id), b),
             "manager"),
            ("DELETE", "/api/growth/goals/{}",
             lambda ctx, q, b, goal_id: ctx.service.remove_goal(_int(goal_id)), "manager"),
            ("GET", "/api/budgets", s("budgets"), "manager"),
            ("POST", "/api/budgets/import",
             lambda ctx, q, b: ctx.service.import_budgets(b.get("files") or []),
             "manager"),
            ("PUT", "/api/budgets/requests",
             lambda ctx, q, b: ctx.service.save_budget_requests(b, nightly.parse_capture),
             "manager"),
            ("PUT", "/api/budgets/people",
             s("set_budget_person", body=True), "manager"),
            ("PUT", "/api/budgets/jobs/{}",
             s("set_budget_share", body=True), "manager"),
            ("GET", "/api/weekly", s("weekly"), "manager"),
            ("GET", "/api/weekly/download", self.weekly_download, "manager"),
            ("GET", "/api/push", self.push_status, "user"),
            ("POST", "/api/push/devices", self.push_subscribe, "user"),
            ("DELETE", "/api/push/devices/{}", self.push_unsubscribe, "user"),
            ("POST", "/api/push/test", self.push_test, "user"),
            ("POST", "/api/push/check", self.push_check, "user"),
            ("GET", "/api/units/together", self.units_together, "manager"),
            ("POST", "/api/planned-work", s("add_planned_work", body=True), "manager"),
            ("POST", "/api/planned-work/{}/remove",
             lambda ctx, q, b, item_id: ctx.service.remove_planned_work(_int(item_id)),
             "manager"),
            ("GET", "/api/day", lambda ctx, q, b: ctx.service.day_plan(q), "manager"),
            ("GET", "/api/meetings", s("meetings"), "manager"),
            ("POST", "/api/meetings",
             lambda ctx, q, b: ctx.service.add_meeting(b or {}), "manager"),
            ("POST", "/api/meetings/{}/remove", s("remove_meeting"), "manager"),
            ("GET", "/api/calendars", self.calendars, "manager"),
            ("PUT", "/api/calendars", self.set_calendar, "manager"),
            ("POST", "/api/calendars/remove", self.remove_calendar, "manager"),
            ("POST", "/api/calendars/refresh", self.refresh_calendars, "manager"),
            ("POST", "/api/requests", s("add_request", body=True), "manager"),
            ("POST", "/api/requests/preview",
             s("request_preview", body=True), "manager"),
            ("GET", "/api/plan-review",
             lambda ctx, q, b: ctx.service.plan_review(q), "manager"),
            ("POST", "/api/plan-review/lock", s("lock_week", body=True), "manager"),
            ("POST", "/api/plan-review/reason",
             s("set_slip_reason", body=True), "manager"),
            ("GET", "/api/what-ifs", s("what_ifs"), "manager"),
            ("POST", "/api/what-ifs", s("save_what_if", body=True), "manager"),
            ("DELETE", "/api/what-ifs/{}",
             lambda ctx, q, b, what_if_id: ctx.service.remove_what_if(_int(what_if_id)),
             "manager"),
            ("POST", "/api/requests/{}/done",
             lambda ctx, q, b, task_id: ctx.service.finish_request(_int(task_id)),
             "manager"),
            ("GET", "/api/holidays", s("holidays"), "manager"),
            ("PUT", "/api/holidays", s("save_holidays", body=True), "manager"),
            ("POST", "/api/absences", s("add_absence", body=True), "manager"),
            ("POST", "/api/absences/{}/remove",
             lambda ctx, q, b, absence_id: ctx.service.remove_absence(_int(absence_id)),
             "manager"),
            ("GET", "/api/submissions", s("submissions"), "manager"),
            ("POST", "/api/submissions/confirm",
             s("confirm_submissions", body=True), "manager"),
            ("POST", "/api/teams", s("add_team", body=True), "manager"),
            ("PUT", "/api/teams/{}", s("update_team", body=True), "manager"),
            ("DELETE", "/api/teams/{}", s("remove_team"), "manager"),

            ("GET", "/api/team", s("team"), "manager"),
            ("GET", "/api/team/access", self.team_access, "manager"),
            ("POST", "/api/team/access", self.grant_access, "manager"),
            ("DELETE", "/api/team/access/{}", self.revoke_access, "manager"),
            ("GET", "/api/team/me",
             lambda ctx, q, b: ctx.service.team_me(ctx.user["id"]), "manager"),
            ("PUT", "/api/team/me",
             lambda ctx, q, b: ctx.service.set_team_me(ctx.user["id"], b), "manager"),
            ("POST", "/api/team", self.add_engineer, "manager"),
            ("PUT", "/api/team/{}", self.update_engineer, "manager"),
            ("DELETE", "/api/team/{}", self.remove_engineer, "manager"),
            ("GET", "/api/reports",
             lambda ctx, q, b: ctx.service.reports(
                 q.get("period", ["year"])[0], _year(q),
                 q.get("quarter", [None])[0]), "manager"),
            ("GET", "/api/tasks", s("tasks"), "manager"),
            ("POST", "/api/tasks", s("add_task", body=True), "manager"),
            ("PUT", "/api/tasks/settings",
             s("save_task_settings", body=True), "manager"),
            ("POST", "/api/tasks/series/delete",
             s("delete_task_series", body=True), "manager"),
            ("POST", "/api/tasks/generate/submissions",
             s("generate_submission_tasks", body=True), "manager"),
            ("POST", "/api/tasks/generate/meetings",
             s("generate_weekly_meetings", body=True), "manager"),
            ("PUT", "/api/tasks/{}",
             lambda ctx, q, b, task_id: ctx.service.update_task(_int(task_id), b),
             "manager"),
            ("DELETE", "/api/tasks/{}",
             lambda ctx, q, b, task_id: ctx.service.delete_task(_int(task_id)),
             "manager"),
            ("GET", "/api/timesheets", s("timesheet_status"), "manager"),
            ("POST", "/api/timesheets/stage",
             lambda ctx, q, b: _stage(ctx.service, b), "manager"),
            ("POST", "/api/timesheets/apply",
             lambda ctx, q, b: ctx.service.apply_timesheet(
                 str(b.get("token") or ""), b.get("mode", "replace")), "manager"),
            ("GET", "/api/import-key", self.import_key_status, "manager"),
            ("POST", "/api/import-key", self.make_import_key, "manager"),
            ("DELETE", "/api/import-key", self.revoke_import_key, "manager"),
            ("PUT", "/api/import-key/source", self.save_import_source, "manager"),
            ("POST", "/api/import-key/team-kit", self.team_kit, "manager"),
            ("POST", "/api/nightly/timesheets", self.nightly_import, "public"),
            ("POST", "/api/timesheets/exports/stage",
             lambda ctx, q, b: ctx.service.stage_exports(b.get("files") or []),
             "manager"),
            ("POST", "/api/timesheets/exports/apply",
             lambda ctx, q, b: ctx.service.apply_exports(
                 str(b.get("token") or ""), b.get("mode", "replace")), "manager"),
            ("POST", "/api/projects/from-timesheets", s("sync_projects"), "manager"),
            ("POST", "/api/timesheets/discard",
             lambda ctx, q, b: ctx.service.discard_timesheet(str(b.get("token") or "")),
             "manager"),
            ("POST", "/api/save", s("save"), "manager"),
            ("POST", "/api/reload", s("reload"), "manager"),
        ]


def _password_in(body: Dict[str, Any]) -> Tuple[str, bool]:
    """The password typed, or a generated one, and whether it was generated."""
    password = str(body.get("password") or "").strip()
    if password:
        return password, False
    return accounts_module.generated_password(), True


def _site_admin(site: Dict[str, Any]) -> bool:
    """Whether the mounting site says this is its administrator, who sees
    every manager's units side by side. Only the site can say so."""
    return site.get("admin") is True


def _site_email(site: Dict[str, Any]) -> str:
    """The email the mounting site vouches for, or ''.

    The site says so under "email"; one that predates that key signs people
    in with their email as their login, and that is used instead. A site that
    sends the key but leaves it empty is saying it vouches for no email (it
    lets anybody sign up), so the login is not trusted in its place.
    """
    vouched = (site.get("email"),) if "email" in site else (site.get("login"),)
    for value in vouched:
        try:
            email = accounts_module.clean_email(value)
        except AccountError:
            continue
        if email:
            return email
    return ""


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


def _is_open(ctx: "Context", unit_id: str) -> bool:
    """Whether the request's service has this unit open."""
    return bool(ctx.service and ctx.service.unit
                and ctx.service.unit.get("id") == unit_id)


def parse_cookies(header: Optional[str]) -> Dict[str, str]:
    """Cookies by name, read one at a time.

    By hand rather than with ``SimpleCookie``, which gives up on the whole
    header at the first cookie it dislikes -- one odd cookie from another app
    on the same host would hide the session and sign everyone out.
    """
    cookies: Dict[str, str] = {}
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name and name not in cookies:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            cookies[name] = value
    return cookies


def parse_body(raw: bytes, content_type: str) -> Dict[str, Any]:
    """A request's JSON body, for the local server and WSGI alike.

    Every POST, PUT and DELETE must say it is JSON, with a body or without.
    A browser only sends that cross-site after asking first, so a form on
    another site cannot post to the API -- not even to sign somebody in to an
    account of its choosing, nor fire a change that needs no body at all.
    """
    if not (content_type or "").lower().startswith("application/json"):
        raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                       "Send the request as application/json.")
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Request body was not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Request body must be an object.")
    return body
