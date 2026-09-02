"""The WSGI entry point -- the way a host such as PythonAnywhere serves this.

Driven directly, with no socket: the same application object the local server
uses, called the way a web host calls it.
"""

import io
import json

import pytest

from workload_app import wsgi
from workload_app.app import WorkloadApp

PASSWORD = "a-good-long-password"


@pytest.fixture
def app(tmp_path):
    application = WorkloadApp(tmp_path / "instance")
    application.accounts.create_user("ahmed", PASSWORD, is_admin=True)
    return application


def request(app, method, path, body=None, cookie=None, https=False):
    """One WSGI call, returning ``(status, headers, parsed body)``."""
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
        "wsgi.url_scheme": "https" if https else "http",
    }
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    if https:
        environ["HTTP_X_FORWARDED_PROTO"] = "https"

    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    wsgi._app = app                     # the module holds one per process
    chunks = wsgi.application(environ, start_response)
    payload = b"".join(chunks)
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = payload
    return captured["status"], dict(captured["headers"]), parsed


def sign_in(app) -> str:
    _status, headers, _body = request(
        app, "POST", "/api/auth/login",
        {"username": "ahmed", "password": PASSWORD})
    return headers["Set-Cookie"].split(";")[0]


class TestTheEntryPoint:
    def test_the_login_page_is_what_a_stranger_gets(self, app):
        status, headers, body = request(app, "GET", "/")
        assert status.startswith("200")
        assert b"login-form" in body
        assert headers["Content-Type"].startswith("text/html")

    def test_the_api_refuses_without_a_session(self, app):
        status, _headers, body = request(app, "GET", "/api/status")
        assert status.startswith("401")
        assert "Sign in" in body["error"]

    def test_signing_in_gives_a_cookie_that_works(self, app):
        cookie = sign_in(app)
        assert cookie.startswith("workload_session=")
        status, _headers, body = request(app, "GET", "/api/status",
                                         cookie=cookie)
        assert status.startswith("200") and body["open"] is False

    def test_the_whole_flow_runs_over_wsgi(self, app):
        cookie = sign_in(app)
        status, _headers, body = request(app, "POST", "/api/units",
                                         {"name": "New unit"}, cookie=cookie)
        if status.startswith("422"):
            pytest.skip("no template built in this checkout")
        assert status.startswith("200")
        assert body["open"] is True

        status, _headers, tasks = request(app, "GET", "/api/tasks", cookie=cookie)
        assert status.startswith("200") and tasks["tasks"] == []

    def test_a_session_cookie_is_marked_secure_only_over_https(self, app):
        _status, headers, _body = request(
            app, "POST", "/api/auth/login",
            {"username": "ahmed", "password": PASSWORD})
        assert "Secure" not in headers["Set-Cookie"]

        _status, headers, _body = request(
            app, "POST", "/api/auth/login",
            {"username": "ahmed", "password": PASSWORD}, https=True)
        cookie = headers["Set-Cookie"]
        assert "Secure" in cookie
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie

    def test_every_answer_carries_the_headers_a_host_should_send(self, app):
        _status, headers, _body = request(app, "GET", "/api/auth/me")
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"

    def test_a_body_that_is_not_json_is_a_bad_request(self, app):
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/api/auth/login",
            "QUERY_STRING": "",
            "CONTENT_LENGTH": "5",
            "wsgi.input": io.BytesIO(b"{{{{{"),
            "wsgi.url_scheme": "http",
        }
        captured = {}
        wsgi._app = app
        body = b"".join(wsgi.application(
            environ, lambda s, h: captured.update(status=s)))
        assert captured["status"].startswith("400")
        assert b"Bad request" in body

    def test_an_unknown_route_is_a_404(self, app):
        status, _headers, _body = request(app, "GET", "/api/nope")
        assert status.startswith("404")
