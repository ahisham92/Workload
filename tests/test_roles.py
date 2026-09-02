"""Two kinds of account: a manager who runs a unit, and a member who reads.

The tests that matter here are the negative ones.  A member account has no
route into anything but its own page, and that page is built from one
engineer's name outwards -- so what a member can reach is a short list, and
these are the tests that keep it short.
"""

import json
import shutil
import threading
import urllib.error
import urllib.request

import pytest

from workload_app import member as member_view, storage
from workload_app.accounts import AccountError, ROLE_MANAGER, ROLE_MEMBER
from workload_app.server import make_server
from workload_app.workbook import WorkloadWorkbook

PASSWORD = "a-good-long-password"


class Client(str):
    cookie: str = ""
    app = None
    user = None


def call(base, path, method="GET", body=None):
    headers = {"Content-Type": "application/json"}
    if getattr(base, "cookie", ""):
        headers["Cookie"] = base.cookie
    request = urllib.request.Request(
        str(base) + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def _sign_in(base, username, password) -> str:
    request = urllib.request.Request(
        str(base) + "/api/auth/login", method="POST",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        return response.headers.get("Set-Cookie", "").split(";")[0]


@pytest.fixture
def site(tmp_path, workbook_copy, monkeypatch):
    """A running app with a manager who has the real workbook open."""
    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "instance"))
    httpd = make_server(tmp_path / "instance", "127.0.0.1", 0, quiet=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    app = httpd.app

    manager = app.accounts.create_user("ahmed", PASSWORD, display_name="Ahmed",
                                       is_admin=True)
    unit = app.accounts.create_unit(manager["id"], "Marine Structures", "")
    target = storage.unit_path(app.data_dir, manager["id"], f"{unit['id']}.xlsx")
    shutil.copy(workbook_copy, target)
    app.accounts_update_filename(manager["id"], unit["id"], target.name)

    client = Client(base)
    client.cookie = _sign_in(base, "ahmed", PASSWORD)
    client.app = app
    client.user = manager
    client.unit = unit                                   # type: ignore[attr-defined]
    call(client, f"/api/units/{unit['id']}/open", "POST")

    yield client
    app.close_all()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def osama(site):
    """A member account signed in, seeing the unit as Osama."""
    _status, granted = call(site, "/api/team/access", "POST",
                            {"engineer": "Osama", "username": "osama"})
    client = Client(str(site))
    client.cookie = _sign_in(site, "osama", granted["password"])
    client.app = site.app
    client.granted = granted                             # type: ignore[attr-defined]
    return client


class TestGivingAccess:
    def test_a_manager_gives_one_person_a_sign_in(self, site):
        status, granted = call(site, "/api/team/access", "POST",
                               {"engineer": "Osama", "username": "osama"})
        assert status == 200
        assert granted["user"]["role"] == ROLE_MEMBER
        assert granted["user"]["is_admin"] is False
        assert granted["password"], "the password is shown once, here"

        _status, access = call(site, "/api/team/access")
        assert [(m["username"], m["engineer"]) for m in access["members"]] == [
            ("osama", "Osama")]

    def test_it_has_to_be_somebody_on_the_team(self, site):
        status, body = call(site, "/api/team/access", "POST",
                            {"engineer": "Nobody", "username": "nobody"})
        assert status == 422 and "not on this unit's team" in body["error"]

    def test_a_manager_account_cannot_be_given_one_persons_view(self, site):
        call(site, "/api/admin/users", "POST",
             {"username": "kirolos", "password": PASSWORD, "role": "manager"})
        status, body = call(site, "/api/team/access", "POST",
                            {"engineer": "Kirolos", "username": "kirolos"})
        assert status == 422 and "manager account" in body["error"]

    def test_access_can_be_taken_away(self, site, osama):
        user_id = osama.granted["user"]["id"]
        status, _ = call(site, f"/api/team/access/{user_id}", "DELETE")
        assert status == 200
        status, body = call(osama, "/api/me")
        assert status == 404 and "No unit has been shared" in body["error"]

    def test_renaming_an_engineer_keeps_their_access(self, site, osama):
        status, _ = call(site, "/api/team/Osama", "PUT", {
            "short_name": "Osama H", "pattern": "*Osama*",
            "available_hours": 185, "availability": {}})
        assert status == 200
        _status, mine = call(osama, "/api/me")
        assert mine["engineer"] == "Osama H"

    def test_removing_an_engineer_takes_their_access_with_them(self, site, osama):
        status, body = call(site, "/api/team/Osama", "DELETE")
        assert status == 200
        assert body.get("access_revoked") == ["osama"]
        status, _ = call(osama, "/api/me")
        assert status == 404


class TestWhatAMemberSees:
    def test_their_own_page_and_nobody_elses_figures(self, osama):
        status, mine = call(osama, "/api/me?period=year&year=2026")
        assert status == 200
        assert mine["engineer"] == "Osama"
        assert mine["me"]["actual_mm"] > 0
        assert mine["projects"], "the projects they have a hand in"
        assert mine["timesheet"]["rows"] > 0

        # Not one other engineer's name is in the payload.
        blob = json.dumps({k: v for k, v in mine.items() if k != "unit"})
        assert "Ahmed" not in blob
        assert "Kirolos" not in blob

    def test_the_unit_says_whose_team_it_is(self, osama):
        _status, mine = call(osama, "/api/me")
        assert mine["unit"]["name"] == "Marine Structures"
        assert mine["unit"]["manager"] == "Ahmed"

    def test_figures_are_their_share_rather_than_the_teams(self, site, osama):
        _status, mine = call(osama, "/api/me?period=year&year=2026")
        _status, whole = call(site, "/api/reports?period=year&year=2026")
        theirs = whole["per_engineer"]["Osama"]
        assert mine["me"]["actual_mm"] == theirs["actual_mm"]
        assert mine["me"]["earned_mm"] == theirs["earned_mm"]
        # And a project row is scaled by their share of it.
        project = mine["projects"][0]
        assert 0 <= (project["share"] or 0) <= 1

    def test_their_months_carry_no_ranking(self, osama):
        _status, mine = call(osama, "/api/me?period=year&year=2026")
        for month in mine["months"]:
            assert set(month) == {
                "month", "label", "actual_mm", "earned_mm", "utilisation",
                "cpi", "projects_worked", "score", "won"}

    def test_the_units_they_can_see_are_the_ones_shared_with_them(self, osama):
        _status, units = call(osama, "/api/units")
        assert [u["name"] for u in units["units"]] == ["Marine Structures"]
        assert units["units"][0]["engineer"] == "Osama"
        assert units["read_only"] is True

    def test_the_member_page_is_what_they_are_served(self, osama):
        request = urllib.request.Request(str(osama) + "/",
                                         headers={"Cookie": osama.cookie})
        with urllib.request.urlopen(request) as response:
            page = response.read()
        assert b"member.js" in page
        assert b"view-overview" not in page          # not the manager's app


class TestWhatAMemberCannotDo:
    """Read-only is a missing route, not a hidden button."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/status"),
        ("GET", "/api/overview"),
        ("GET", "/api/projects"),
        ("GET", "/api/deliverables"),
        ("GET", "/api/reports"),
        ("GET", "/api/tasks"),
        ("GET", "/api/team"),
        ("GET", "/api/team/access"),
        ("GET", "/api/reference"),
        ("GET", "/api/timesheets"),
    ])
    def test_the_managers_reads_are_refused(self, osama, method, path):
        status, body = call(osama, path, method)
        assert status == 403
        assert "your own work" in body["error"]

    @pytest.mark.parametrize("method,path,body", [
        ("POST", "/api/projects", {"number": "X", "name": "Y", "budget_mm": 1}),
        ("POST", "/api/units", {"name": "Mine"}),
        ("POST", "/api/tasks", {"name": "Task"}),
        ("POST", "/api/team", {"short_name": "New"}),
        ("POST", "/api/save", {}),
        ("POST", "/api/reload", {}),
        ("POST", "/api/timesheets/capacity", {}),
        ("PUT", "/api/reference", {}),
        ("POST", "/api/team/access", {"engineer": "Osama", "username": "x"}),
    ])
    def test_every_write_is_refused(self, osama, method, path, body):
        status, answer = call(osama, path, method, body)
        assert status == 403, path
        assert "your own work" in answer["error"]

    def test_they_cannot_manage_accounts(self, osama):
        status, body = call(osama, "/api/admin/users")
        assert status == 403 and "administrators" in body["error"]
        status, _ = call(osama, "/api/admin/users", "POST",
                         {"username": "sneaky", "password": PASSWORD})
        assert status == 403

    def test_they_cannot_open_or_download_the_workbook(self, site, osama):
        unit_id = site.unit["id"]
        for method, path in (("POST", f"/api/units/{unit_id}/open"),
                             ("GET", f"/api/units/{unit_id}/download"),
                             ("DELETE", f"/api/units/{unit_id}")):
            status, _ = call(osama, path, method, {} if method == "POST" else None)
            assert status == 403, path

    def test_a_member_account_cannot_be_made_an_administrator(self, site, osama):
        user_id = osama.granted["user"]["id"]
        status, body = call(site, f"/api/admin/users/{user_id}/admin", "POST",
                            {"is_admin": True})
        assert status == 422
        assert "cannot manage accounts" in body["errors"][0]

    def test_reading_does_not_write_to_the_managers_workbook(self, site, osama):
        path = storage.unit_path(site.app.data_dir, site.user["id"],
                                 f"{site.unit['id']}.xlsx")
        before = path.stat().st_mtime_ns, path.stat().st_size
        call(osama, "/api/me?period=year&year=2026")
        call(osama, "/api/me?period=all")
        assert (path.stat().st_mtime_ns, path.stat().st_size) == before

    def test_the_two_can_work_at_the_same_time(self, site, osama):
        status, mine = call(osama, "/api/me?period=year&year=2026")
        assert status == 200
        status, projects = call(site, "/api/projects")
        assert status == 200 and len(projects["projects"]) == 40
        status, again = call(osama, "/api/me?period=year&year=2026")
        assert again["me"] == mine["me"]


class TestTheViewItself:
    """Built straight from the workbook, without the HTTP layer in the way."""

    def test_it_says_so_when_the_person_has_gone(self, readonly_wb):
        data = member_view.build(readonly_wb, "Somebody Else", year=2026)
        assert data["known"] is False
        assert "not on this unit's team" in data["message"]

    def test_a_shared_task_shows_only_this_person_s_share(self, wb):
        wb.save_task({"name": "Shared", "assignees": ["Ahmed", "Osama"],
                      "required_hours": 10, "due": "2026-09-30"})
        data = member_view.build(wb, "Osama", year=2026)
        task = data["tasks"]["tasks"][0]
        assert task["hours_each"] == 5.0
        assert task["assignees"] == ["Osama"]         # never the other name
        assert task["shared_with"] == 1
        assert data["tasks"]["open_hours"] == 5.0

    def test_tasks_belonging_to_others_are_not_there(self, wb):
        wb.save_task({"name": "Not theirs", "assignees": ["Ahmed"],
                      "required_hours": 4})
        data = member_view.build(wb, "Osama", year=2026)
        assert data["tasks"]["tasks"] == []

    def test_only_their_projects_are_listed(self, readonly_wb):
        data = member_view.build(readonly_wb, "Osama", year=2026)
        numbers = {p["number"] for p in data["projects"]}
        assert numbers
        for project in data["projects"]:
            assert project["share"] > 0 or project["actual_mm"]


class TestTheAccountRules:
    def test_a_member_cannot_be_created_as_an_administrator(self, tmp_path):
        from workload_app.accounts import Accounts

        db = Accounts(tmp_path / "accounts.db")
        with pytest.raises(AccountError, match="Only a manager"):
            db.create_user("osama", PASSWORD, is_admin=True, role=ROLE_MEMBER)

    def test_a_manager_is_what_an_account_is_by_default(self, tmp_path):
        from workload_app.accounts import Accounts

        db = Accounts(tmp_path / "accounts.db")
        assert db.create_user("ahmed", PASSWORD)["role"] == ROLE_MANAGER

    def test_an_older_database_gains_the_column(self, tmp_path):
        import sqlite3

        from workload_app.accounts import Accounts

        path = tmp_path / "accounts.db"
        db = Accounts(path)
        db.create_user("ahmed", PASSWORD)
        with sqlite3.connect(path) as connection:
            connection.execute("ALTER TABLE users DROP COLUMN role")
        again = Accounts(path)                        # opens and migrates
        assert again.users()[0]["role"] == ROLE_MANAGER
