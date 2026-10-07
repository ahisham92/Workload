"""Workload as one tab of a larger site.

Mounted inside another site, Workload signs nobody in: the site says who is
asking, and that is the account. What these tests pin down is that the rule
which keeps one account's work from another survives the move -- a colleague
who opens the tab sees nothing of yours until you give it to them -- and that
somebody who used Workload at its own address can bring their units with them.

They start from new, empty units, so they need no workbook of anybody's.
"""

import io
import json
from pathlib import Path

import pytest

from workload_app import wsgi
from workload_app.app import WorkloadApp

PASSWORD = "a-good-long-password"
AHMED = {"id": 1, "login": "ahmed@example.com", "name": "Ahmed", "home": "/",
         "label": "AHM", "logout": "/logout"}
OSAMA = {"id": 2, "login": "osama", "name": "Osama", "home": "/",
         "label": "AHM", "logout": "/logout"}
PEOPLE = [{"id": 1, "login": "ahmed@example.com", "name": "Ahmed"},
          {"id": 2, "login": "osama", "name": "Osama"}]


@pytest.fixture
def app(tmp_path, monkeypatch):
    application = WorkloadApp(tmp_path / "instance")
    application.site_people = lambda: PEOPLE
    monkeypatch.setattr(wsgi, "_app", application)
    return application


def ask(method, path, body=None, *, site=None, cookie=None, mount="/workload"):
    """One call the way the mounting site makes it."""
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": mount,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
        "wsgi.url_scheme": "http",
    }
    if site is not None:
        environ[wsgi.SITE_KEY] = site
    if cookie:
        environ["HTTP_COOKIE"] = cookie
    seen = {}

    def start_response(status, headers):
        seen["status"] = int(status.split()[0])
        seen["headers"] = dict(headers)

    payload = b"".join(wsgi.application(environ, start_response))
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = payload.decode("utf-8", "replace")
    return seen["status"], seen["headers"], parsed


def unit_for(site, name="Marine Structures"):
    status, _, opened = ask("POST", "/api/units", {"name": name}, site=site)
    assert status == 200, opened
    _, _, listed = ask("GET", "/api/units", site=site)
    return next(u for u in listed["units"] if u["name"] == name)


def an_engineer(site, name="Osama"):
    status, _, answer = ask("POST", "/api/team", {
        "short_name": name, "pattern": f"*{name}*", "available_hours": 160,
    }, site=site)
    assert status == 200, answer
    return name


class TestWhoIsAsking:
    def test_the_site_signs_you_in_and_there_is_no_login_page(self, app):
        status, _, who = ask("GET", "/api/auth/me", site=AHMED)
        assert status == 200
        assert who["user"]["site_key"] == "1"
        assert who["user"]["site_login"] == "ahmed@example.com"
        assert who["user"]["display_name"] == "Ahmed"
        assert who["user"]["role"] == "manager"
        assert who["site"] == {"home": "/", "label": "AHM", "logout": "/logout",
                               "login": "ahmed@example.com"}

        status, headers, _ = ask("GET", "/login.html", site=AHMED)
        assert status == 303
        assert headers["Location"] == "/workload/"

    def test_the_same_person_is_the_same_account_every_time(self, app):
        first = ask("GET", "/api/auth/me", site=AHMED)[2]["user"]["id"]
        assert ask("GET", "/api/auth/me", site=AHMED)[2]["user"]["id"] == first
        assert app.accounts.user_count() == 1

    def test_changing_what_you_sign_in_with_does_not_lose_your_units(self, app):
        """The site's own identifier is the key; an address can be corrected."""
        unit_for(AHMED)
        renamed = dict(AHMED, login="ahmed.mitwally@example.com", name="Ahmed M")
        _, _, who = ask("GET", "/api/auth/me", site=renamed)
        assert who["user"]["site_login"] == "ahmed.mitwally@example.com"
        assert [u["name"] for u in ask("GET", "/api/units", site=renamed)[2]["units"]] \
            == ["Marine Structures"]
        # And somebody given the old address afterwards does not inherit them.
        taker = {"id": 9, "login": "ahmed@example.com", "name": "Not Ahmed"}
        assert ask("GET", "/api/units", site=taker)[2]["units"] == []

    def test_nobody_is_an_administrator_for_having_arrived(self, app):
        assert ask("GET", "/api/auth/me", site=AHMED)[2]["user"]["is_admin"] is False
        assert ask("GET", "/api/admin/users", site=AHMED)[0] == 403

    def test_an_account_made_for_the_site_has_no_password_to_guess(self, app):
        user = ask("GET", "/api/auth/me", site=AHMED)[2]["user"]
        assert user["password_stored"] is False
        for guess in ("", "ahmed", "ahmed@example.com", PASSWORD):
            assert app.accounts.verify(user["username"], guess) is None

    def test_a_browser_cannot_say_who_it_is(self, app):
        """Only the mounting site can; a header of the same name is just a header."""
        raw = b""
        environ = {
            "REQUEST_METHOD": "GET", "SCRIPT_NAME": "/workload",
            "PATH_INFO": "/api/units", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(raw),
            "wsgi.url_scheme": "http",
            "HTTP_WORKLOAD_SITE": json.dumps(AHMED),
            "HTTP_X_WORKLOAD_SITE": "1",
        }
        seen = {}
        b"".join(wsgi.application(
            environ, lambda status, headers: seen.update(status=status)))
        assert seen["status"].startswith("401")

    def test_an_old_cookie_does_not_outrank_the_site(self, app):
        other = app.accounts.create_user("someone", PASSWORD)
        token = app.accounts.start_session(other["id"])
        _, _, who = ask("GET", "/api/auth/me", site=AHMED,
                        cookie=f"workload_session={token}")
        assert who["user"]["site_key"] == "1"

    def test_signing_in_and_passwords_are_the_sites(self, app):
        app.accounts.create_user("ahmed", PASSWORD)
        assert ask("POST", "/api/auth/login",
                   {"username": "ahmed", "password": PASSWORD}, site=OSAMA)[0] == 409
        assert ask("POST", "/api/auth/password",
                   {"current_password": "x", "new_password": PASSWORD},
                   site=OSAMA)[0] == 409
        status, headers, answer = ask("POST", "/api/auth/logout", site=OSAMA)
        assert status == 200 and answer["logout"] == "/logout"
        assert "Set-Cookie" not in headers

    def test_the_pages_ask_for_everything_under_the_mount(self, app):
        """A page that asked the site's root for /api would get the wrong app."""
        static = Path(wsgi.__file__).parent / "static"
        for page in ("app.js", "member.js", "login.html"):
            body = (static / page).read_text(encoding="utf-8")
            assert "const BASE = new URL('.', window.location.href)" in body
            assert "fetch('/api" not in body and "fetch(path" not in body
            assert "href = '/" not in body
        # And they are served from under it.
        status, _, body = ask("GET", "/app.js", site=AHMED)
        assert status == 200 and "fetch(BASE + path" in body


class TestYoursAlone:
    def test_a_colleague_who_opens_the_tab_sees_none_of_your_units(self, app):
        mine = unit_for(AHMED)
        _, _, theirs = ask("GET", "/api/units", site=OSAMA)
        assert theirs["units"] == []
        # Not by its address either.
        for method, path in [("POST", f"/api/units/{mine['id']}/open"),
                             ("GET", f"/api/units/{mine['id']}/download"),
                             ("DELETE", f"/api/units/{mine['id']}"),
                             ("PUT", f"/api/units/{mine['id']}")]:
            assert ask(method, path, {"name": "Mine now"}, site=OSAMA)[0] == 404
        assert ask("GET", "/api/units", site=AHMED)[2]["units"][0]["name"] \
            == "Marine Structures"

    def test_each_account_has_a_folder_of_its_own(self, app, tmp_path):
        unit_for(AHMED)
        unit_for(OSAMA, "Buildings")
        folders = sorted(p.name for p in (tmp_path / "instance" / "users").iterdir())
        assert len(folders) == 2
        for folder in folders:
            assert len(list((tmp_path / "instance" / "users" / folder).glob("*.db"))) == 1


class TestGivingAccess:
    def test_access_goes_to_a_site_sign_in_and_needs_no_password(self, app):
        unit_for(AHMED)
        engineer = an_engineer(AHMED)
        status, _, given = ask("POST", "/api/team/access",
                               {"engineer": engineer, "person": "2"},
                               site=AHMED)
        assert status == 200, given
        assert given["password"] is None
        assert given["user"]["role"] == "member"

        _, _, who = ask("GET", "/api/auth/me", site=OSAMA)
        assert who["user"]["role"] == "member"
        status, _, mine = ask("GET", "/api/me", site=OSAMA)
        assert status == 200, mine
        assert mine["unit"]["name"] == "Marine Structures"
        # Their own page, and the manager's shell is not served to them.
        status, _, page = ask("GET", "/", site=OSAMA)
        assert status == 200 and "member.js" in page
        # And nothing in the unit can be changed or read from that account.
        assert ask("GET", "/api/projects", site=OSAMA)[0] == 403
        assert ask("POST", "/api/units", {"name": "X"}, site=OSAMA)[0] == 403

    def test_somebody_who_looked_in_first_can_still_be_given_access(self, app):
        """They were made an empty account of their own; it becomes the member."""
        assert ask("GET", "/api/auth/me", site=OSAMA)[2]["user"]["role"] == "manager"
        unit_for(AHMED)
        engineer = an_engineer(AHMED)
        status, _, given = ask("POST", "/api/team/access",
                               {"engineer": engineer, "person": "2"},
                               site=AHMED)
        assert status == 200, given
        assert ask("GET", "/api/me", site=OSAMA)[0] == 200
        assert app.accounts.user_count() == 2

    def test_somebody_with_units_of_their_own_is_not_turned_into_a_member(self, app):
        unit_for(OSAMA, "Buildings")
        unit_for(AHMED)
        engineer = an_engineer(AHMED)
        status, _, refused = ask("POST", "/api/team/access",
                                 {"engineer": engineer, "person": "2"},
                                 site=AHMED)
        assert status == 422
        assert "units of their own" in refused["error"]
        assert ask("GET", "/api/units", site=OSAMA)[2]["units"][0]["name"] == "Buildings"

    def test_only_people_the_site_knows_can_be_given_access(self, app):
        unit_for(AHMED)
        engineer = an_engineer(AHMED)
        _, _, access = ask("GET", "/api/team/access", site=AHMED)
        # Everybody but yourself.
        assert access["site"]["people"] == [
            {"id": "2", "login": "osama", "name": "Osama"}]
        for nobody in ("77", "", "osama", None):
            status, _, refused = ask("POST", "/api/team/access",
                                     {"engineer": engineer, "person": nobody},
                                     site=AHMED)
            assert status == 422, refused
        status, _, given = ask("POST", "/api/team/access",
                               {"engineer": engineer, "person": "2"}, site=AHMED)
        assert status == 200 and given["user"]["display_name"] == "Osama"
        _, _, access = ask("GET", "/api/team/access", site=AHMED)
        assert access["members"][0]["site_key"] == "2"
        assert access["members"][0]["site_login"] == "osama"

    def test_you_cannot_give_it_to_yourself(self, app):
        unit_for(AHMED)
        engineer = an_engineer(AHMED)
        assert ask("POST", "/api/team/access",
                   {"engineer": engineer, "person": 1}, site=AHMED)[0] == 422

    def test_taking_it_away_again_leaves_them_with_nothing_of_yours(self, app):
        unit_for(AHMED)
        engineer = an_engineer(AHMED)
        _, _, given = ask("POST", "/api/team/access",
                          {"engineer": engineer, "person": "2"}, site=AHMED)
        assert ask("GET", "/api/me", site=OSAMA)[0] == 200
        assert ask("DELETE", f"/api/team/access/{given['user']['id']}",
                   site=AHMED)[0] == 200
        # An ordinary account again: no page of yours, and no units.
        _, _, who = ask("GET", "/api/auth/me", site=OSAMA)
        assert who["user"]["role"] == "manager"
        assert ask("GET", "/api/units", site=OSAMA)[2]["units"] == []
        assert ask("GET", "/api/me", site=OSAMA)[0] == 404


class TestBringingAnOldAccount:
    @pytest.fixture
    def old(self, app):
        """Ahmed as he was at Workload's own address, with a unit."""
        user = app.accounts.create_user("ahmed", PASSWORD, display_name="Ahmed M",
                                        is_admin=True)
        token = app.accounts.start_session(user["id"])
        status, _, _ = ask("POST", "/api/units", {"name": "Marine Structures"},
                           cookie=f"workload_session={token}", mount="")
        assert status == 200
        return user

    def test_the_tab_starts_empty_until_the_old_account_is_brought(self, app, old):
        assert ask("GET", "/api/units", site=AHMED)[2]["units"] == []
        status, _, linked = ask("POST", "/api/auth/link",
                                {"username": "ahmed", "password": PASSWORD},
                                site=AHMED)
        assert status == 200, linked
        assert linked["linked"] is True and linked["units"] == 1
        _, _, units = ask("GET", "/api/units", site=AHMED)
        assert [u["name"] for u in units["units"]] == ["Marine Structures"]
        assert units["units"][0]["exists"] is True
        # One account, not two: the empty one made on arrival is gone.
        assert [u["username"] for u in app.accounts.users()] == ["ahmed"]
        assert ask("GET", "/api/auth/me", site=AHMED)[2]["user"]["id"] == old["id"]

    def test_the_wrong_password_brings_nothing(self, app, old):
        status, _, refused = ask("POST", "/api/auth/link",
                                 {"username": "ahmed", "password": "not-the-password"},
                                 site=OSAMA)
        assert status == 422
        assert ask("GET", "/api/units", site=OSAMA)[2]["units"] == []
        assert app.accounts.user(old["id"])["site_key"] is None

    def test_an_account_somebody_already_brought_cannot_be_taken(self, app, old):
        assert ask("POST", "/api/auth/link",
                   {"username": "ahmed", "password": PASSWORD}, site=AHMED)[0] == 200
        status, _, refused = ask("POST", "/api/auth/link",
                                 {"username": "ahmed", "password": PASSWORD},
                                 site=OSAMA)
        assert status == 422 and "another sign-in" in refused["error"]

    def test_units_started_here_first_are_not_thrown_away(self, app, old):
        unit_for(AHMED, "Started here")
        status, _, refused = ask("POST", "/api/auth/link",
                                 {"username": "ahmed", "password": PASSWORD},
                                 site=AHMED)
        assert status == 422 and "already have units" in refused["error"]
        assert [u["name"] for u in ask("GET", "/api/units", site=AHMED)[2]["units"]] \
            == ["Started here"]

    def test_it_can_be_done_from_the_console_too(self, app, old, tmp_path, capsys):
        from workload_app import admin

        ask("GET", "/api/auth/me", site=AHMED)          # looked in first
        code = admin.main(["--data-dir", str(tmp_path / "instance"),
                           "link", "ahmed", "1", "--login", "ahmed@example.com"])
        assert code == 0
        assert [u["name"] for u in ask("GET", "/api/units", site=AHMED)[2]["units"]] \
            == ["Marine Structures"]
        assert app.accounts.user_count() == 1


class TestOnItsOwnNothingChanged:
    def test_without_a_site_it_still_signs_people_in_itself(self, app):
        app.accounts.create_user("ahmed", PASSWORD)
        assert ask("GET", "/api/units", mount="")[0] == 401
        status, headers, _ = ask("POST", "/api/auth/login",
                                 {"username": "ahmed", "password": PASSWORD}, mount="")
        assert status == 200 and "workload_session=" in headers["Set-Cookie"]
        _, _, who = ask("GET", "/api/auth/me", mount="")
        assert "site" not in who
        assert ask("POST", "/api/auth/link", {"username": "a", "password": "b"},
                   cookie=headers["Set-Cookie"].split(";")[0], mount="")[0] == 404
