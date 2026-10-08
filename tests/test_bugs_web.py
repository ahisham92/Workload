"""Bugs found in the web layer (app.py, server.py, wsgi.py), each pinned down.

Synthetic accounts and empty units only; no workbook is needed.
"""

import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from workload_app import app as app_module, wsgi
from workload_app.app import Request, WorkloadApp
from workload_app.server import make_server
from workload_app.service import MAX_UPLOAD_BYTES

PASSWORD = "a-good-long-password"
AHMED = {"id": 1, "login": "ahmed", "email": "ahmed@example.com", "name": "Ahmed",
         "home": "/", "label": "AHM", "logout": "/logout"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = WorkloadApp(tmp_path / "instance")
    monkeypatch.setattr(wsgi, "_app", application)
    return application


def ask(method, path, body=None, *, site=None, cookie=None,
        content_type="application/json", raw=None):
    """One WSGI call; returns (status, parsed body, headers)."""
    if raw is None:
        raw = json.dumps(body).encode() if body is not None else b""
    environ = {
        "REQUEST_METHOD": method, "SCRIPT_NAME": "", "PATH_INFO": path,
        "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw), "wsgi.url_scheme": "http",
    }
    if content_type is not None:
        environ["CONTENT_TYPE"] = content_type
    if site is not None:
        environ[wsgi.SITE_KEY] = site
    if cookie:
        environ["HTTP_COOKIE"] = f"workload_session={cookie}"
    seen = {}
    payload = b"".join(wsgi.application(
        environ, lambda status, headers: seen.update(
            status=int(status.split()[0]), headers=dict(headers))))
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = payload
    return seen["status"], parsed, seen["headers"]


def manager(app, name="boss"):
    user = app.accounts.create_user(name, PASSWORD, is_admin=True)
    return user, app.accounts.start_session(user["id"])


def unit_for(site, name="Marine Structures"):
    status, opened, _ = ask("POST", "/api/units", {"name": name}, site=site)
    assert status == 200, opened


# --------------------------------------------------------------------------
# CSRF: a write with no body at all must still say it is JSON
# --------------------------------------------------------------------------

class TestBodilessWritesFromAnotherSite:
    def test_an_empty_form_post_is_refused(self, app):
        """A cross-site <form method=post> with no fields sends an empty body
        typed as a form. Inside a host site the browser carries the site's own
        cookie, so it must be refused before it reaches any route."""
        unit_for(AHMED)
        status, _, _ = ask("POST", "/api/tasks/generate/meetings", site=AHMED,
                           content_type="application/x-www-form-urlencoded")
        assert status == 415
        status, _, _ = ask("POST", "/api/units/close", site=AHMED, content_type=None)
        assert status == 415

    def test_the_app_itself_still_gets_through(self, app):
        unit_for(AHMED)
        status, body, _ = ask("POST", "/api/units/close", site=AHMED)
        assert status == 200, body

    def test_the_local_server_refuses_it_too(self, app):
        _user, cookie = manager(app)
        server = make_server(app=app, port=0, quiet=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            request = urllib.request.Request(
                base + "/api/units/close", data=b"", method="POST",
                headers={"Cookie": f"workload_session={cookie}",
                         "Content-Type": "text/plain"})
            with pytest.raises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(request)
            assert refused.value.code == 415
        finally:
            server.shutdown()
            server.server_close()


class TestTooLargeOnAHost:
    def test_an_oversized_upload_says_so(self, app, monkeypatch):
        monkeypatch.setattr(wsgi, "MAX_UPLOAD_BYTES", 4)
        status, body, _ = ask("POST", "/api/auth/login",
                              {"username": "x", "password": "y"})
        assert status == 413
        assert "too large" in body["error"].lower()
        assert MAX_UPLOAD_BYTES > 4              # the real limit is untouched


# --------------------------------------------------------------------------
# permissions inside a host site
# --------------------------------------------------------------------------

class TestSiteAdministrator:
    def test_an_email_on_a_team_row_never_makes_the_site_admin_a_member(self, app):
        unit_for(AHMED)
        status, body, _ = ask("POST", "/api/team", {
            "short_name": "Nour", "pattern": "*Nour*", "available_hours": 160,
            "email": "admin@example.com"}, site=AHMED)
        assert status == 200, body
        admin = {"id": 7, "login": "boss", "email": "admin@example.com",
                 "name": "Boss", "admin": True}
        _, who, _ = ask("GET", "/api/auth/me", site=admin)
        assert who["user"]["role"] == "manager"
        status, together, _ = ask("GET", "/api/units/together", site=admin)
        assert status == 200, together
        assert together["everyone"] is True


class TestUnvouchedEmail:
    def test_a_login_that_looks_like_an_email_is_not_trusted_when_the_site_vouches_none(
            self, app):
        """The host leaves "email" empty while anybody may sign up: a login
        typed as somebody's address must not link that person's row."""
        unit_for(AHMED)
        assert ask("POST", "/api/team", {
            "short_name": "Nour", "pattern": "*Nour*", "available_hours": 160,
            "email": "nour@example.com"}, site=AHMED)[0] == 200
        impostor = {"id": 9, "login": "nour@example.com", "email": None,
                    "name": "Nour?"}
        _, who, _ = ask("GET", "/api/auth/me", site=impostor)
        assert who["user"]["role"] == "manager"
        assert ask("GET", "/api/me", site=impostor)[0] != 200

    def test_an_older_site_with_no_email_key_still_uses_the_login(self, app):
        unit_for(AHMED)
        assert ask("POST", "/api/team", {
            "short_name": "Nour", "pattern": "*Nour*", "available_hours": 160,
            "email": "nour@example.com"}, site=AHMED)[0] == 200
        old_style = {"id": 9, "login": "nour@example.com", "name": "Nour"}
        assert ask("GET", "/api/me", site=old_style)[0] == 200


# --------------------------------------------------------------------------
# notifications: a phone is removed by its own id, not an account's
# --------------------------------------------------------------------------

class TestRemovingAPhone:
    def test_a_device_id_with_no_account_of_that_number_is_still_removed(self, app):
        user, cookie = manager(app)
        for n in range(3):
            app.accounts.add_push_device(
                user["id"], endpoint=f"https://push.example.com/{n}",
                auth="a", p256dh="b")
        device = app.accounts.push_devices(user["id"])[-1]["id"]
        assert app.accounts.user(device) is None      # no account has that id
        status, body, _ = ask("DELETE", f"/api/push/devices/{device}", cookie=cookie)
        assert status == 200, body
        assert body == {"removed": True}
        assert len(app.accounts.push_devices(user["id"])) == 2

    def test_a_non_number_is_a_bad_request(self, app):
        _user, cookie = manager(app)
        assert ask("DELETE", "/api/push/devices/abc", cookie=cookie)[0] == 400


# --------------------------------------------------------------------------
# the open services, from several threads
# --------------------------------------------------------------------------

class _Watched:
    """A lock that knows whether it is held."""

    def __init__(self):
        self._lock = threading.Lock()
        self.held = False

    def __enter__(self):
        self._lock.acquire()
        self.held = True
        return self

    def __exit__(self, *exc):
        self.held = False
        self._lock.release()


class TestServicesLock:
    def test_every_change_to_the_open_services_holds_the_lock(self, app):
        watched = _Watched()

        class Guarded(dict):
            def pop(self, *args):
                assert watched.held, "the services were changed without the lock"
                return super().pop(*args)

        app._services_lock = watched
        app._services = Guarded()
        # A member whose access was all taken away is turned back into an
        # account of their own; that forgets their service.
        member = app.accounts.create_site_user(9, login="nour", role="member")
        app._services[member["id"]] = object()
        response = app.handle(Request(method="GET", path="/api/auth/me",
                                      site={"id": 9, "login": "nour"}))
        assert response.status == 200
        assert app.accounts.user(member["id"])["role"] == "manager"

    def test_reset_password_forgets_under_the_lock(self, app):
        watched = _Watched()

        class Guarded(dict):
            def pop(self, *args):
                assert watched.held, "the services were changed without the lock"
                return super().pop(*args)

        boss, cookie = manager(app)
        other = app.accounts.create_user("osama", PASSWORD)
        app._services_lock = watched
        app._services = Guarded()
        status, body, _ = ask("POST", f"/api/admin/users/{other['id']}/password",
                              {}, cookie=cookie)
        assert status == 200, body

    def test_a_busy_request_keeps_its_unit_when_others_crowd_in(self, app):
        """With more accounts than are kept, the oldest is forgotten -- but a
        request still using it must not have its unit closed underneath."""
        _user, cookie = manager(app)
        status, opened, _ = ask("POST", "/api/units", {"name": "Marine Structures"},
                                cookie=cookie)
        assert status == 200, opened
        busy = app.service_for(_user["id"])
        assert busy.unit is not None
        for other in range(app_module.OPEN_WORKBOOK_LIMIT + 1):
            app.service_for(1000 + other)
        assert _user["id"] not in app._services
        assert busy.unit is not None and busy.workbook is not None


class TestRenameSeenByEveryWorker:
    def test_another_worker_shows_the_new_name(self, app):
        _user, cookie = manager(app)
        status, opened, _ = ask("POST", "/api/units", {"name": "Marine Structures"},
                                cookie=cookie)
        assert status == 200, opened
        unit_id = opened["unit"]["id"]
        second = WorkloadApp(app.data_dir)          # another worker, same data

        def status_from(worker):
            response = worker.handle(Request(method="GET", path="/api/status",
                                             cookies={"workload_session": cookie}))
            return json.loads(response.body)

        assert status_from(second)["unit"]["name"] == "Marine Structures"
        renamed = app.handle(Request(method="PUT", path=f"/api/units/{unit_id}",
                                     body={"name": "Marine Works"},
                                     cookies={"workload_session": cookie}))
        assert renamed.status == 200
        assert status_from(second)["unit"]["name"] == "Marine Works"
