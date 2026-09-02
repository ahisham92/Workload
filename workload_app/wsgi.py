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

import json
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs

from .app import Request, Response, WorkloadApp, parse_cookies
from .service import MAX_UPLOAD_BYTES

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
    request = _request_from(environ)
    if request is None:
        return _reply(start_response, Response.json(
            400, {"error": "Bad request.", "errors": ["Bad request."]}))
    response = get_app().handle(request)
    return _reply(start_response, response, head=request.method == "HEAD")


def _request_from(environ: Dict[str, Any]) -> Optional[Request]:
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/") or "/"
    query = parse_qs(environ.get("QUERY_STRING", ""))

    body: Dict[str, Any] = {}
    if method in {"POST", "PUT", "DELETE"}:
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > MAX_UPLOAD_BYTES * 2:
            return None
        if length > 0:
            raw = environ["wsgi.input"].read(length)
            if raw.strip():
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return None
                if not isinstance(parsed, dict):
                    return None
                body = parsed

    # Behind the host's proxy the connection to the browser is the one that
    # matters: it decides whether the session cookie may be marked Secure.
    forwarded = environ.get("HTTP_X_FORWARDED_PROTO", "").split(",")[0].strip()
    secure = (forwarded or environ.get("wsgi.url_scheme", "http")).lower() == "https"

    return Request(
        method=method,
        path=path,
        query=query,
        body=body,
        cookies=parse_cookies(environ.get("HTTP_COOKIE")),
        secure=secure,
    )


def _reply(start_response: Callable[..., Any], response: Response,
           head: bool = False) -> Iterable[bytes]:
    status = f"{int(response.status)} {_reason(response.status)}"
    headers: List = [
        ("Content-Type", response.content_type),
        ("Content-Length", str(len(response.body))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "same-origin"),
    ]
    headers.extend(response.headers)
    start_response(status, headers)
    return [b""] if head else [response.body]


def _reason(status: int) -> str:
    try:
        from http import HTTPStatus

        return HTTPStatus(status).phrase
    except ValueError:                                  # pragma: no cover
        return "Status"
