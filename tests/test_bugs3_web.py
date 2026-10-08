"""Round 3 bugs in the web layer (app.py, server.py, wsgi.py), each pinned down.

Synthetic accounts and empty units only; no workbook is needed.
"""

import io
import json
import os
import sqlite3
import threading
import time
import urllib.request

import pytest

from workload_app import app as app_module, nightly, wsgi
from workload_app.app import Request, WorkloadApp
from workload_app.server import make_server

PASSWORD = "a-good-long-password"
AHMED = {"id": 1, "login": "ahmed", "email": "ahmed@example.com", "name": "Ahmed",
         "home": "/", "label": "AHM", "logout": "/logout"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = WorkloadApp(tmp_path / "instance")
    application.tell_in_background = False
    monkeypatch.setattr(wsgi, "_app", application)
    return application


def ask(method, path, body=None, *, site=None, cookie=None,
        content_type="application/json", extra=None):
    """One WSGI call; returns (status, parsed body, headers)."""
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
    environ.update(extra or {})
    seen = {}
    payload = b"".join(wsgi.application(
        environ, lambda status, headers: seen.update(
            status=int(status.split()[0]), headers=dict(headers))))
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = payload
    return seen["status"], parsed, seen["headers"]


def as_wsgi_path(text):
    """A path as a WSGI server hands it over (PEP 3333): the URL's bytes,
    decoded one byte to one character."""
    return text.encode("utf-8").decode("latin-1")


def unit_for(site, name="Marine Structures"):
    status, opened, _ = ask("POST", "/api/units", {"name": name}, site=site)
    assert status == 200, opened
    return opened["unit"]["id"] if "unit" in opened else None


# --------------------------------------------------------------------------
# WSGI: a name with an accent in the path reaches its route
# --------------------------------------------------------------------------

class TestAccentedNamesOnAHost:
    def test_a_person_whose_name_has_an_accent_can_be_removed(self, app):
        unit_for(AHMED)
        assert ask("POST", "/api/team", {
            "short_name": "Kirolos", "pattern": "*Kirolos*", "available_hours": 160},
            site=AHMED)[0] == 200
        status, body, _ = ask("POST", "/api/team", {
            "short_name": "José", "pattern": "*Jose*", "available_hours": 160},
            site=AHMED)
        assert status == 200, body
        status, body, _ = ask("DELETE", as_wsgi_path("/api/team/José"), site=AHMED)
        assert status == 200, body
        _, team, _ = ask("GET", "/api/team/access", site=AHMED)
        assert "José" not in team["engineers"]

    def test_a_plain_unicode_path_is_left_alone(self, app):
        """A door that already hands over a decoded path keeps working."""
        unit_for(AHMED)
        for name in ("Kirolos", "José"):
            assert ask("POST", "/api/team", {
                "short_name": name, "pattern": "*x*", "available_hours": 160},
                site=AHMED)[0] == 200
        status, body, _ = ask("DELETE", "/api/team/José", site=AHMED)
        assert status == 200, body


# --------------------------------------------------------------------------
# the local server: behind a proxy that lists every hop
# --------------------------------------------------------------------------

class TestForwardedProtoOnTheLocalServer:
    def test_the_first_hop_decides_whether_the_cookie_is_secure(self, app):
        app.accounts.create_user("boss", PASSWORD, is_admin=True)
        server = make_server(app=app, port=0, quiet=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            request = urllib.request.Request(
                base + "/api/auth/login", method="POST",
                data=json.dumps({"username": "boss", "password": PASSWORD}).encode(),
                headers={"Content-Type": "application/json",
                         "X-Forwarded-Proto": "https, http"})
            with urllib.request.urlopen(request) as answer:
                cookie = answer.headers["Set-Cookie"]
            assert "Secure" in cookie
        finally:
            server.shutdown()
            server.server_close()


# --------------------------------------------------------------------------
# static files
# --------------------------------------------------------------------------

@pytest.fixture
def static(tmp_path, monkeypatch):
    folder = tmp_path / "web" / "static"
    folder.mkdir(parents=True)
    (folder / "login.html").write_text(
        '<html><script src="app.js"></script></html>', encoding="utf-8")
    (folder / "app.js").write_text("console.log(1);", encoding="utf-8")
    # A folder next door whose name merely starts the same way.
    (tmp_path / "web" / "static_private").mkdir()
    (tmp_path / "web" / "static_private" / "secret.txt").write_text("secret")
    monkeypatch.setattr(app_module, "STATIC_DIR", folder)
    monkeypatch.setattr(app_module, "_assets", {})
    return folder


class TestStaticFiles:
    def test_a_folder_next_to_static_is_not_served(self, app, static):
        response = app.handle(Request("GET", "/../static_private/secret.txt"))
        assert response.status == 404
        assert b"secret" not in response.body

    def test_a_null_byte_in_the_path_is_not_found_rather_than_a_crash(self, app, static):
        response = app.handle(Request("GET", "/app\x00.js"))
        assert response.status == 404

    def test_a_page_names_the_new_version_of_a_script_after_it_changes(
            self, app, static):
        """A browser keeps app.js?v=<old> for a year, so the page must name the
        new version once the file changes, even if nobody asked for app.js."""
        first = app.handle(Request("GET", "/login.html")).body
        script = static / "app.js"
        script.write_text("console.log(2); // changed", encoding="utf-8")
        later = time.time() + 5
        os.utime(script, (later, later))
        second = app.handle(Request("GET", "/login.html")).body
        assert first != second
        version = app_module._static(script.resolve()).version
        assert f"app.js?v={version}".encode() in second


# --------------------------------------------------------------------------
# a member whose unit was deleted
# --------------------------------------------------------------------------

class TestMemberOfADeletedUnit:
    def test_they_are_told_nothing_is_shared_rather_than_a_crash(self, app):
        boss = app.accounts.create_user("boss", PASSWORD)
        boss_cookie = app.accounts.start_session(boss["id"])
        status, opened, _ = ask("POST", "/api/units", {"name": "Marine Structures"},
                                cookie=boss_cookie)
        assert status == 200, opened
        unit_id = app.accounts.open_unit_of(boss["id"])
        assert ask("POST", "/api/team", {
            "short_name": "Osama", "pattern": "*Osama*", "available_hours": 160},
            cookie=boss_cookie)[0] == 200
        status, granted, _ = ask("POST", "/api/team/access", {
            "engineer": "Osama", "username": "osama", "password": PASSWORD},
            cookie=boss_cookie)
        assert status == 200, granted
        osama = app.accounts.verify("osama", PASSWORD)
        osama_cookie = app.accounts.start_session(osama["id"])
        status, mine, _ = ask("GET", "/api/me", cookie=osama_cookie)
        assert status == 200, mine

        unit = app.accounts.unit(boss["id"], unit_id)
        path = app_module.storage.unit_path(app.data_dir, boss["id"], unit["filename"])
        status, body, _ = ask("DELETE", f"/api/units/{unit_id}", cookie=boss_cookie)
        assert status == 200, body
        assert not path.exists()

        status, body, _ = ask("GET", "/api/me", cookie=osama_cookie)
        assert status == 404, body
        assert "shared" in body["error"]
        # ...and no empty file is left where the unit was.
        assert not path.exists()


# --------------------------------------------------------------------------
# the site administrator's every-unit view
# --------------------------------------------------------------------------

class TestEveryUnitWithOneDamaged:
    def test_one_damaged_unit_is_listed_as_missing_not_the_whole_page(self, app):
        unit_for(AHMED, "Marine Structures")
        kirolos = {"id": 3, "login": "kirolos", "email": "kirolos@example.com",
                   "name": "Kirolos"}
        unit_for(kirolos, "Bridges")
        owner = app.accounts.site_user("3")
        broken = app.accounts.units(owner["id"])[0]
        ask("POST", "/api/units/close", site=kirolos)
        app._drop_service(owner["id"])
        path = app_module.storage.unit_path(app.data_dir, owner["id"],
                                            broken["filename"])
        for extra in ("-wal", "-shm"):
            path.with_name(path.name + extra).unlink(missing_ok=True)
        path.write_bytes(b"this is not a database at all" * 100)

        admin = {"id": 7, "login": "boss", "email": "", "name": "Boss",
                 "admin": True}
        status, together, _ = ask("GET", "/api/units/together", site=admin)
        assert status == 200, together
        assert any("Bridges" in name for name in together["missing"])


# --------------------------------------------------------------------------
# the nightly import: any failure is what the morning's tab shows
# --------------------------------------------------------------------------

class TestNightlyFailureRecorded:
    def test_a_locked_database_is_recorded_as_a_failed_import(self, app, monkeypatch):
        unit_for(AHMED)
        user = app.accounts.site_user("1")
        unit_id = app.accounts.open_unit_of(user["id"])
        key = app.accounts.make_import_key(user["id"], unit_id)
        app.accounts.record_import(unit_id, {"ok": True, "rows": 10})

        def locked(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(nightly, "run", locked)
        status, _, _ = ask("POST", "/api/nightly/timesheets", {
            "key": key, "files": [{"filename": "x.xlsx", "content_base64": "UEs="}]})
        assert status == 500
        last = app.accounts.import_key_info(user["id"], unit_id)["last_result"]
        assert last["ok"] is False
        assert "locked" in last["error"]


# --------------------------------------------------------------------------
# an administrator resetting their own password from the Admin tab
# --------------------------------------------------------------------------

class TestAdminResetsOwnPassword:
    def test_they_stay_signed_in(self, app):
        boss = app.accounts.create_user("boss", PASSWORD, is_admin=True)
        cookie = app.accounts.start_session(boss["id"])
        status, body, headers = ask("POST", f"/api/admin/users/{boss['id']}/password",
                                    {"password": "another-long-password"}, cookie=cookie)
        assert status == 200, body
        fresh = headers.get("Set-Cookie", "").split(";")[0].partition("=")[2]
        assert fresh, "no new session was issued"
        _, who, _ = ask("GET", "/api/auth/me", cookie=fresh)
        assert who["user"] and who["user"]["id"] == boss["id"]
