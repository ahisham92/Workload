"""WSGI entry point, for PythonAnywhere and any other host that speaks WSGI.

The host's configuration points at ``workload_app.wsgi:application``.  Set
``WORKLOAD_DATA_DIR`` to a folder **outside** the checked-out code -- accounts
and workbooks live there, and a deploy replaces the code, not the data.

    import os
    os.environ['WORKLOAD_DATA_DIR'] = '/home/<you>/workload-data'
    from workload_app.wsgi import application   # noqa

Everything below is the standard library.  There is no framework to keep in
step, and the same application object serves the local server too.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs

from .app import ApiError, Request, Response, WorkloadApp, parse_body, parse_cookies
from .service import MAX_UPLOAD_BYTES

#: Where a site that mounts Workload says who is asking. See ``Request.site``.
SITE_KEY = "workload.site"

#: One application per worker process.  Each holds its own parsed workbooks and
#: re-reads a file whenever another worker has written it.
_app: Optional[WorkloadApp] = None


def get_app() -> WorkloadApp:
    global _app
    if _app is None:
        _app = WorkloadApp()
    return _app


def application(environ: Dict[str, Any],
                start_response: Callable[..., Any]) -> Iterable[bytes]:
    try:
        request = _request_from(environ)
    except ApiError as exc:
        return _reply(start_response, Response.json(
            exc.status, {"error": exc.message, "errors": exc.errors}))
    app = get_app()
    app.tell_after_response = True
    # A change waiting longer than this was made through a door that never
    # closed its response; tell its phones now rather than never.
    app.tell_pending(older_than=STALE_TELL_SECONDS)
    response = app.handle(request)
    return _Then(_reply(start_response, response, head=request.method == "HEAD"),
                 app.tell_pending)


#: See application().
STALE_TELL_SECONDS = 30.0


class _Then:
    """The response body, and something to do once it has been sent: the
    server calls close() after the last byte (PEP 3333)."""

    def __init__(self, body: List[bytes], then: Callable[[], None]):
        self._body = body
        self._then = then

    def __iter__(self):
        return iter(self._body)

    def close(self) -> None:
        self._then()


def _request_from(environ: Dict[str, Any]) -> Request:
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/") or "/"
    try:
        # PEP 3333 hands the URL's bytes over one byte to one character; the
        # browser sent UTF-8, so "José" arrives as "JosÃ©" until read again.
        path = path.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass                    # already text, from a door that decoded it
    query = parse_qs(environ.get("QUERY_STRING", ""))

    body: Dict[str, Any] = {}
    if method in {"POST", "PUT", "DELETE"}:
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > MAX_UPLOAD_BYTES * 2:
            raise ApiError(413, "Request too large.")
        # Parsed even when empty: a write with no body must still say it is
        # JSON, which a form on another site cannot.
        body = parse_body(environ["wsgi.input"].read(length) if length > 0 else b"",
                          environ.get("CONTENT_TYPE") or "")

    # Behind the host's proxy the connection to the browser is the one that
    # matters: it decides whether the session cookie may be marked Secure.
    site = environ.get(SITE_KEY)
    forwarded = environ.get("HTTP_X_FORWARDED_PROTO", "").split(",")[0].strip()
    secure = (forwarded or environ.get("wsgi.url_scheme", "http")).lower() == "https"

    return Request(
        method=method,
        path=path,
        query=query,
        body=body,
        cookies=parse_cookies(environ.get("HTTP_COOKIE")),
        secure=secure,
        # Set by a site that mounts Workload and has already signed the person
        # in. A browser cannot set it: everything a request brings arrives
        # under HTTP_*, and this key is not one of those.
        site=site if isinstance(site, dict) and site.get("id") not in (None, "") else None,
        mount=str(environ.get("SCRIPT_NAME") or "").rstrip("/"),
        accept_encoding=str(environ.get("HTTP_ACCEPT_ENCODING") or ""),
        if_none_match=str(environ.get("HTTP_IF_NONE_MATCH") or ""),
    )


def _reply(start_response: Callable[..., Any], response: Response,
           head: bool = False) -> Iterable[bytes]:
    status = f"{int(response.status)} {_reason(response.status)}"
    headers: List = [
        ("Content-Type", response.content_type),
        ("Content-Length", str(len(response.body))),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "same-origin"),
    ]
    # Nothing is kept by the browser unless the response says it may be.
    if not any(name.lower() == "cache-control" for name, _ in response.headers):
        headers.append(("Cache-Control", "no-store"))
    headers.extend(response.headers)
    start_response(status, headers)
    return [b""] if head else [response.body]


def _reason(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:                                  # pragma: no cover
        return "Status"
