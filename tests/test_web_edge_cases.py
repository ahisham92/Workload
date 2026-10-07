"""The web layer when more than one thing happens at once, or a request is odd.

Driven through ``WorkloadApp.handle`` with no socket, the way both the local
server and a WSGI host call it.
"""

import base64
import json
import threading

import pytest

from workload_app import admin as admin_cli, deployment
from workload_app.accounts import ROLE_MEMBER
from workload_app.app import Request, WorkloadApp

PASSWORD = "a-good-long-password"
CSV = "JobNumber,FullName,Date,TotalHours\nX1,Some Person,2026-09-01,8\n"


def _b64(data):
    return base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()


def call(app, method, path, body=None, cookie=None):
    response = app.handle(Request(
        method=method, path=path, body=body or {},
        cookies={"workload_session": cookie} if cookie else {}))
    return response.status, json.loads(response.body)


def sign_in(app, username, **kwargs):
    user = app.accounts.create_user(username, PASSWORD, **kwargs)
    return user, app.accounts.start_session(user["id"])


def new_unit(app, cookie, name):
    status, body = call(app, "POST", "/api/units", {"name": name}, cookie)
    assert status == 200, body
    return body["unit"]["id"]


@pytest.fixture
def app(tmp_path):
    return WorkloadApp(tmp_path / "instance")


@pytest.fixture
def boss(app):
    user, cookie = sign_in(app, "boss", is_admin=True)
    return user, cookie


class TestSeveralWorkers:
    def test_another_worker_answers_for_the_unit_you_opened(self, app, boss):
        _user, cookie = boss
        unit_a = new_unit(app, cookie, "Unit A")
        unit_b = new_unit(app, cookie, "Unit B")
        call(app, "POST", f"/api/units/{unit_a}/open", cookie=cookie)
        second = WorkloadApp(app.data_dir)
        status, body = call(second, "GET", "/api/status", cookie=cookie)
        assert status == 200 and body["unit"]["id"] == unit_a
        # Switching on the second worker is followed by the first.
        call(second, "POST", f"/api/units/{unit_b}/open", cookie=cookie)
        assert call(app, "GET", "/api/status", cookie=cookie)[1]["unit"]["id"] == unit_b
        # And closing is too.
        call(app, "POST", "/api/units/close", cookie=cookie)
        assert call(second, "GET", "/api/status", cookie=cookie)[1]["open"] is False

    def test_one_account_gets_one_service_however_many_threads_ask(self, app):
        seen, barrier = [], threading.Barrier(8)

        def ask():
            barrier.wait()
            seen.append(app.service_for(1))

        threads = [threading.Thread(target=ask) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len({id(s) for s in seen}) == 1

    def test_the_nightly_import_leaves_what_you_have_open_alone(self, app, boss):
        user, cookie = boss
        mine = new_unit(app, cookie, "Unit A")
        nightly = new_unit(app, cookie, "Unit B")
        key = app.accounts.make_import_key(user["id"], nightly)
        call(app, "POST", f"/api/units/{mine}/open", cookie=cookie)
        status, staged = call(app, "POST", "/api/timesheets/exports/stage",
                              {"files": [{"filename": "a.csv",
                                          "content_base64": _b64(CSV)}]}, cookie)
        assert status == 200, staged
        call(app, "POST", "/api/nightly/timesheets",
             {"key": key, "files": [{"filename": "a.csv", "content_base64": _b64(CSV)}]})
        assert call(app, "GET", "/api/status", cookie=cookie)[1]["unit"]["id"] == mine
        status, body = call(app, "POST", "/api/timesheets/exports/apply",
                            {"token": staged["token"], "mode": "append"}, cookie)
        assert status == 200, body


class TestFailuresLeaveThingsAsTheyWere:
    def test_a_file_that_is_not_a_workbook_is_reported_not_a_crash(self, app, boss):
        _user, cookie = boss
        call(app, "POST", f"/api/units/{new_unit(app, cookie, 'Unit A')}/open",
             cookie=cookie)
        status, body = call(app, "POST", "/api/timesheets/exports/stage",
                            {"files": [{"filename": "t.xlsx",
                                        "content_base64": _b64(b"not a zip")}]}, cookie)
        assert status < 500
        assert "Excel workbook" in json.dumps(body)

    def test_a_failed_new_unit_keeps_the_one_you_had_open(self, app, boss):
        _user, cookie = boss
        unit = new_unit(app, cookie, "Unit A")
        call(app, "POST", f"/api/units/{unit}/open", cookie=cookie)
        status, _ = call(app, "POST", "/api/units/from-timesheets",
                         {"files": [{"filename": "a.xlsx",
                                     "content_base64": _b64(b"junk")}]}, cookie)
        assert status >= 400
        status, body = call(app, "GET", "/api/status", cookie=cookie)
        assert body["open"] and body["unit"]["id"] == unit
        units = call(app, "GET", "/api/units", cookie=cookie)[1]["units"]
        assert [u["name"] for u in units] == ["Unit A"]

    def test_a_refused_replacement_keeps_the_unit_open(self, app, boss):
        _user, cookie = boss
        unit = new_unit(app, cookie, "Unit A")
        call(app, "POST", f"/api/units/{unit}/open", cookie=cookie)
        status, _ = call(app, "POST", f"/api/units/{unit}/replace",
                         {"content_base64": _b64(b"junk")}, cookie)
        assert status >= 400
        assert call(app, "GET", "/api/status", cookie=cookie)[1]["open"] is True


class TestOddRequests:
    @pytest.mark.parametrize("method,path,body", [
        ("POST", "/api/auth/login", {"username": "boss", "password": 123}),
        ("POST", "/api/admin/users/abc/password", {}),
        ("DELETE", "/api/admin/users/abc", None),
        ("POST", "/api/admin/users/999/admin", {"is_admin": True}),
        ("POST", "/api/units/upload", {"filename": None, "content_base64": _b64(b"x")}),
        ("POST", "/api/timesheets/exports/stage", {"files": "abc"}),
        ("POST", "/api/timesheets/exports/stage", {"files": ["x"]}),
        ("POST", "/api/projects/full", {"project": None}),
        ("POST", "/api/projects/full", {"project": {}, "deliverables": ["x"]}),
    ])
    def test_a_wrong_shape_is_refused_not_a_crash(self, app, boss, method, path, body):
        _user, cookie = boss
        call(app, "POST", f"/api/units/{new_unit(app, cookie, 'Unit A')}/open",
             cookie=cookie)
        status, _ = call(app, method, path, body, cookie)
        assert 400 <= status < 500

    def test_a_project_number_with_a_slash_is_refused(self, app, boss):
        _user, cookie = boss
        call(app, "POST", f"/api/units/{new_unit(app, cookie, 'Unit A')}/open",
             cookie=cookie)
        status, body = call(app, "POST", "/api/projects/full",
                            {"project": {"number": "TEST/01", "name": "T"},
                             "deliverables": []}, cookie)
        assert status == 422 and "slash" in json.dumps(body)


class TestTeamAccess:
    def test_another_managers_member_cannot_be_added_to_your_unit(self, app, boss):
        _user, cookie = boss
        other, other_cookie = sign_in(app, "other")
        unit = new_unit(app, cookie, "Unit A")
        call(app, "POST", f"/api/units/{unit}/open", cookie=cookie)
        people = call(app, "POST", "/api/team", {"short_name": "Pat"}, cookie)
        assert people[0] == 200, people
        status, _ = call(app, "POST", "/api/team/access",
                         {"engineer": "Pat", "username": "pat"}, cookie)
        assert status == 200
        theirs = new_unit(app, other_cookie, "Their unit")
        call(app, "POST", f"/api/units/{theirs}/open", cookie=other_cookie)
        call(app, "POST", "/api/team", {"short_name": "Sam"}, other_cookie)
        status, body = call(app, "POST", "/api/team/access",
                            {"engineer": "Sam", "username": "pat"}, other_cookie)
        assert status == 422 and "taken" in body["error"]

    def test_a_member_sees_their_managers_username_when_there_is_no_name(self, app):
        manager = app.accounts.create_user("boss", PASSWORD)
        member = app.accounts.create_user("pat", PASSWORD, role=ROLE_MEMBER)
        unit = app.accounts.create_unit(manager["id"], "Unit A", "a.db")
        with app.accounts._connect() as db:
            db.execute("UPDATE users SET display_name = '' WHERE id = ?",
                       (manager["id"],))
        app.accounts.grant(user_id=member["id"], unit_id=unit["id"], engineer="Pat")
        assert app.accounts.memberships(member["id"])[0]["owner_name"] == "boss"


class TestConsoleAndDeploy:
    def test_the_console_finds_an_account_whatever_the_case(self, app, monkeypatch):
        app.accounts.create_user("alice", PASSWORD)
        assert admin_cli._find_user(app.accounts, "Alice")["username"] == "alice"

    def test_the_deploy_check_wants_every_script_a_page_loads(self, tmp_path):
        import shutil
        from pathlib import Path
        root = tmp_path / "code"
        shutil.copytree(Path(__file__).resolve().parents[1] / "workload_app",
                        root / "workload_app")
        (root / "workload_app" / "static" / "planner.js").unlink()
        report = deployment.Report(root, tmp_path / "data")
        deployment._check_code(report, root)
        bad = [f for f in report.findings if f.level == "bad"]
        assert bad and "planner.js" in bad[0].detail
