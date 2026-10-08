"""The local web server: a thin transport in front of :mod:`workload_app.app`.

Used when the app runs on someone's own machine.  On a host it is replaced by
:mod:`workload_app.wsgi`, which serves the same application object -- the
routing, the accounts and the workbook handling are shared, and only the way
bytes arrive differs.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .app import Request, WorkloadApp, parse_body, parse_cookies
from .service import ApiError, MAX_UPLOAD_BYTES


class Handler(BaseHTTPRequestHandler):
    server_version = "Workload/2.0"
    app: WorkloadApp = None                   # set by make_server

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(fmt, *args)

    # -- request ---------------------------------------------------------
    def _read_body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Bad Content-Length.")
        if length > MAX_UPLOAD_BYTES * 2:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
        # Parsed even when empty: a write with no body must still say it is
        # JSON, which a form on another site cannot.
        return parse_body(self.rfile.read(length) if length > 0 else b"",
                          self.headers.get("Content-Type") or "")

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._read_body() if method in {"POST", "PUT", "DELETE"} else {}
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message, "errors": exc.errors})
            return

        request = Request(
            method=method,
            # Decoded, as a WSGI host's PATH_INFO already is: a name with a
            # space in it reaches the route as "Engineer 1", not "Engineer%201".
            path=unquote(parsed.path),
            query=parse_qs(parsed.query),
            body=body,
            cookies=parse_cookies(self.headers.get("Cookie")),
            # The first hop is the browser's, as on a host (see wsgi).
            secure=(self.headers.get("X-Forwarded-Proto") or "").split(",")[0]
            .strip().lower() == "https",
            accept_encoding=self.headers.get("Accept-Encoding") or "",
            if_none_match=self.headers.get("If-None-Match") or "",
        )
        response = self.app.handle(request)
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            if not any(name.lower() == "cache-control"
                       for name, _ in response.headers):
                self.send_header("Cache-Control", "no-store")
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(response.body)
        except BrokenPipeError:
            pass

    def _send_json(self, status: int, data: Any) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:      # noqa: N802
        self._handle("GET")

    def do_HEAD(self) -> None:     # noqa: N802
        self._handle("HEAD")

    def do_POST(self) -> None:     # noqa: N802
        self._handle("POST")

    def do_PUT(self) -> None:      # noqa: N802
        self._handle("PUT")

    def do_DELETE(self) -> None:   # noqa: N802
        self._handle("DELETE")


def make_server(data_dir: Optional[Path] = None, host: str = "127.0.0.1",
                port: int = 8765, *, autosave: bool = True,
                quiet: bool = False, app: Optional[WorkloadApp] = None
                ) -> ThreadingHTTPServer:
    application = app or WorkloadApp(data_dir, autosave=autosave)
    handler = type("BoundHandler", (Handler,), {"app": application})
    server = ThreadingHTTPServer((host, port), handler)
    server.quiet = quiet                              # type: ignore[attr-defined]
    server.app = application                          # type: ignore[attr-defined]
    return server
