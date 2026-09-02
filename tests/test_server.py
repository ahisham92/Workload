"""The HTTP layer, driven against a real server with a real account signed in.

Every request here carries a session cookie, because without one the app
answers nothing: that is the point of the login.  The isolation tests are the
ones to read first -- they are what make one account's workbook private.
"""

import base64
import datetime as dt
import io
import json
import shutil
import threading
import urllib.error
import urllib.request

import pytest

from workload_app import storage
from workload_app.server import make_server

PASSWORD = "a-good-long-password"


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "instance"))


class Client(str):
    """The base URL, and the cookie that says who is asking."""

    cookie: str = ""
    app = None
    user = None


def _serve(data_dir):
    httpd = make_server(data_dir, "127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _sign_in(base: str, username: str, password: str) -> str:
    request = urllib.request.Request(
        base + "/api/auth/login", method="POST",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        cookie = response.headers.get("Set-Cookie", "")
    return cookie.split(";")[0]


def _account(httpd, base, username="ahmed", *, admin=True) -> Client:
    app = httpd.app
    user = app.accounts.create_user(username, PASSWORD, is_admin=admin)
    client = Client(base)
    client.cookie = _sign_in(base, username, PASSWORD)
    client.app = app
    client.user = user
    return client


def _adopt(client: Client, workbook, name="Marine Structures") -> str:
    """Put a workbook into the signed-in account without a 3 MB upload."""
    app = client.app
    unit = app.accounts.create_unit(client.user["id"], name, "")
    target = storage.unit_path(app.data_dir, client.user["id"],
                               f"{unit['id']}.xlsx")
    shutil.copy(workbook, target)
    app.accounts_update_filename(client.user["id"], unit["id"], target.name)
    return unit["id"]


@pytest.fixture
def empty_server(tmp_path):
    """Signed in, with no unit open -- as a new account starts."""
    httpd = _serve(tmp_path / "instance")
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    client = _account(httpd, base)
    yield client
    httpd.app.close_all()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def server(empty_server, workbook_copy):
    """Signed in, with the real workbook open as this account's unit."""
    unit_id = _adopt(empty_server, workbook_copy)
    call(empty_server, f"/api/units/{unit_id}/open", "POST")
    return empty_server


@pytest.fixture
def stranger(server):
    """A second account, signed in, that has nothing of its own."""
    client = _account(_ServerHolder(server), str(server), "osama", admin=False)
    return client


class _ServerHolder:
    """Lets ``_account`` reuse the running server behind an existing client."""

    def __init__(self, client: Client):
        self.app = client.app


def call(base, path, method="GET", body=None):
    headers = {"Content-Type": "application/json"}
    cookie = getattr(base, "cookie", "")
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(
        str(base) + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request) as response:
            _keep_cookie(base, response)
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def _keep_cookie(base, response) -> None:
    """Follow a re-issued session the way a browser would."""
    issued = response.headers.get("Set-Cookie")
    if issued and hasattr(base, "cookie"):
        base.cookie = issued.split(";")[0]


def get(base, path):
    """A plain GET that carries the cookie, for the pages rather than the API."""
    cookie = getattr(base, "cookie", "")
    request = urllib.request.Request(
        str(base) + path,
        headers={"Cookie": cookie} if cookie else {})
    return urllib.request.urlopen(request)


class TestStaticAndRouting:
    def test_the_page_is_served(self, server):
        with get(server, "/") as response:
            assert response.status == 200
            body = response.read()
            assert b"Workload" in body and b"view-overview" in body

    @pytest.mark.parametrize("path", ["/app.css", "/app.js"])
    def test_assets_are_served(self, server, path):
        with get(server, path) as response:
            assert response.status == 200

    def test_an_unknown_api_path_is_a_404(self, server):
        status, _ = call(server, "/api/nope")
        assert status == 404

    def test_paths_cannot_escape_the_static_directory(self, server):
        try:
            with get(server, "/../workbook.py") as response:
                assert response.status == 404
        except urllib.error.HTTPError as error:
            assert error.code in (400, 404)


class TestReads:
    def test_status(self, server):
        status, body = call(server, "/api/status")
        assert status == 200
        assert body["unit"]["name"] == "Marine Structures"
        assert body["projects"] == 40
        assert body["unsaved_changes"] is False

    def test_reference_drives_the_dropdowns(self, server):
        _status, body = call(server, "/api/reference")
        assert [t["code"] for t in body["project_types"]][:3] == ["DD", "CD", "FS"]
        assert body["credit_steps"]["DD"][0]["step_no"] == 1
        assert body["statuses"][0] == "Active"
        assert {e["short_name"] for e in body["engineers"]} == {
            "Ahmed", "Osama", "Kirolos"}

    def test_overview_can_be_filtered_by_year(self, server):
        _status, body = call(server, "/api/overview?year=2026")
        assert body["year"] == 2026
        assert all(m["month"].startswith("2026")
                   for m in body["engineers"]["Ahmed"]["months"])

    def test_a_bad_year_is_rejected(self, server):
        status, _ = call(server, "/api/overview?year=banana")
        assert status == 400

    def test_projects_and_deliverables_come_with_their_figures(self, server):
        _status, projects = call(server, "/api/projects")
        assert len(projects["projects"]) == len(projects["metrics"]) == 40
        _status, deliverables = call(server, "/api/deliverables")
        assert len(deliverables["deliverables"]) == 64


class TestWrites:
    PROJECT = {
        "number": "API-0100D", "name": "API test", "budget_mm": 2.5,
        "status": "Active", "start": "2026-01-01", "end": "2026-12-31",
    }

    def test_add_update_and_delete_a_project(self, server):
        status, body = call(server, "/api/projects", "POST", self.PROJECT)
        assert status == 200
        assert body["project"]["number"] == "API-0100D"
        assert body["save"]["saved"] is True

        status, body = call(server, "/api/projects/API-0100D", "PUT",
                            {**self.PROJECT, "budget_mm": 3.5})
        assert status == 200 and body["project"]["budget_mm"] == 3.5

        status, _ = call(server, "/api/projects/API-0100D", "DELETE")
        assert status == 200
        _status, listing = call(server, "/api/projects")
        assert all(p["number"] != "API-0100D" for p in listing["projects"])

    def test_validation_errors_come_back_as_422_with_reasons(self, server):
        status, body = call(server, "/api/projects", "POST",
                            {"number": "", "budget_mm": -1, "status": "Nope"})
        assert status == 422
        assert len(body["errors"]) >= 3

    def test_a_deliverable_needs_a_project_that_exists(self, server):
        status, body = call(server, "/api/deliverables", "POST", {
            "project_number": "GHOST-0100D", "name": "x", "type_code": "FS",
            "phase_weight": 1, "step_no": 1,
        })
        assert status == 422
        assert any("not in the project register" in m for m in body["errors"])

    def test_adding_a_deliverable_grows_the_actuals_block(self, server):
        call(server, "/api/projects", "POST", self.PROJECT)
        _status, before = call(server, "/api/status")
        status, body = call(server, "/api/deliverables", "POST", {
            "project_number": "API-0100D", "name": "Phase 1", "type_code": "FS",
            "phase_weight": 1, "step_no": 2, "share_ahmed": 1, "ts_phase": 1,
        })
        assert status == 200
        _status, after = call(server, "/api/status")
        assert after["actuals_last_row"] > before["actuals_last_row"]
        assert after["actuals_last_row"] == body["deliverable"]["row"]

    def test_deleting_a_project_with_deliverables_needs_confirmation(self, server):
        call(server, "/api/projects", "POST", self.PROJECT)
        call(server, "/api/deliverables", "POST", {
            "project_number": "API-0100D", "name": "Phase 1", "type_code": "FS",
            "phase_weight": 1, "step_no": 2, "share_ahmed": 1, "ts_phase": 1,
        })
        status, body = call(server, "/api/projects/API-0100D", "DELETE")
        assert status == 422
        assert any("still point at" in m for m in body["errors"])

        status, body = call(server, "/api/projects/API-0100D?cascade=true", "DELETE")
        assert status == 200 and body["deliverables_removed"] == 1


class TestTimesheetEndpoints:
    def _export(self, readonly_wb, name="Kirolos Nabil"):
        openpyxl = pytest.importorskip("openpyxl")
        headers = readonly_wb.timesheet_headers("Kirolos")
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(headers)
        index = {h: i for i, h in enumerate(headers)}
        for day in range(1, 6):
            row = [None] * len(headers)
            row[index["Job Type"]] = "1-Projects"
            row[index["JobNumber"]] = "N25185-0100D"
            row[index["FullName"]] = name
            row[index["Date"]] = dt.date(2026, 9, day)
            row[index["Phase"]] = 4
            row[index["RegularHours"]] = 8.5
            row[index["TotalHours"]] = 8.5
            sheet.append(row)
        buffer = io.BytesIO()
        book.save(buffer)
        return base64.b64encode(buffer.getvalue()).decode()

    def test_stage_then_apply_replaces_the_sheet(self, server, readonly_wb):
        status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": self._export(readonly_wb),
        })
        assert status == 200
        assert staged["row_count"] == 5
        assert staged["errors"] == []
        _status, check = call(server, "/api/timesheets")
        assert staged["existing_rows"] == check["per_engineer"]["Kirolos"]["rows"]

        status, applied = call(server, "/api/timesheets/apply", "POST",
                               {"token": staged["token"], "mode": "replace"})
        assert status == 200 and applied["rows"] == 5
        assert applied["data_check"]["per_engineer"]["Kirolos"]["rows"] == 5

    def test_append_keeps_what_was_there(self, server, readonly_wb):
        _status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": self._export(readonly_wb),
        })
        _status, applied = call(server, "/api/timesheets/apply", "POST",
                                {"token": staged["token"], "mode": "append"})
        assert applied["rows"] == staged["existing_rows"] + 5

    def test_one_persons_export_is_refused_on_anothers_sheet(self, server, readonly_wb):
        status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": self._export(readonly_wb, name="Ahmed Mitwally"),
        })
        assert status == 200
        assert staged["errors"]
        status, _ = call(server, "/api/timesheets/apply", "POST",
                         {"token": staged["token"], "mode": "replace"})
        assert status == 400

    def test_a_stale_token_is_reported_clearly(self, server):
        status, body = call(server, "/api/timesheets/apply", "POST",
                            {"token": "nope", "mode": "replace"})
        assert status == 404
        assert "expired" in body["error"]

    def test_an_unknown_mode_is_refused(self, server, readonly_wb):
        _status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": self._export(readonly_wb),
        })
        status, _ = call(server, "/api/timesheets/apply", "POST",
                         {"token": staged["token"], "mode": "sideways"})
        assert status == 400

    def test_a_file_that_is_not_an_export_is_refused(self, server):
        status, body = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Ahmed", "filename": "notes.csv",
            "content_base64": base64.b64encode(b"hello,world\n1,2\n").decode(),
        })
        assert status == 400
        assert "header row" in body["error"]

    def test_an_unknown_engineer_is_refused(self, server, readonly_wb):
        status, _ = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Someone", "filename": "k.xlsx",
            "content_base64": self._export(readonly_wb),
        })
        assert status == 400


class TestUnits:
    """A unit is a name and a workbook, and it belongs to one account."""

    def test_an_account_starts_with_nothing_open(self, empty_server):
        status, body = call(empty_server, "/api/status")
        assert status == 200
        assert body["open"] is False
        assert body["unit"] is None

    def test_the_registers_are_refused_until_one_is_open(self, empty_server):
        for path in ("/api/projects", "/api/deliverables", "/api/reference",
                     "/api/overview", "/api/timesheets", "/api/tasks"):
            status, body = call(empty_server, path)
            assert status == 409, path
            assert "No workbook is open" in body["error"]

    def test_a_new_unit_starts_from_the_blank_template(self, empty_server):
        status, body = call(empty_server, "/api/units", "POST",
                            {"name": "New unit"})
        assert status == 200
        assert body["open"] is True
        assert body["unit"]["name"] == "New unit"
        # The template carries the model but none of anybody's data.
        assert body["projects"] == 0
        assert body["deliverables"] == 0
        assert body["engineers"] == ["Engineer 1", "Engineer 2", "Engineer 3"]
        _status, reference = call(empty_server, "/api/reference")
        assert len(reference["project_types"]) > 5

    def test_a_workbook_can_be_uploaded_as_a_unit(self, empty_server, workbook_copy):
        content = base64.b64encode(workbook_copy.read_bytes()).decode()
        status, body = call(empty_server, "/api/units/upload", "POST", {
            "name": "Marine Structures", "filename": "Workload.xlsx",
            "content_base64": content,
        })
        assert status == 200
        assert body["projects"] == 40
        assert body["engineers"] == ["Ahmed", "Osama", "Kirolos"]

    def test_something_that_is_not_a_workbook_is_refused(self, empty_server):
        status, body = call(empty_server, "/api/units/upload", "POST", {
            "name": "Nonsense", "filename": "notes.xlsx",
            "content_base64": base64.b64encode(b"not a spreadsheet").decode(),
        })
        assert status == 422
        assert "not readable as a spreadsheet" in body["error"]
        # And it leaves nothing behind.
        _status, units = call(empty_server, "/api/units")
        assert units["units"] == []

    def test_units_are_listed_renamed_and_deleted(self, server):
        _status, listed = call(server, "/api/units")
        assert [u["name"] for u in listed["units"]] == ["Marine Structures"]
        unit_id = listed["units"][0]["id"]
        assert listed["units"][0]["exists"] is True

        status, renamed = call(server, f"/api/units/{unit_id}", "PUT",
                               {"name": "Marine Structures East"})
        assert status == 200 and renamed["unit"]["name"] == "Marine Structures East"

        status, _ = call(server, f"/api/units/{unit_id}", "DELETE")
        assert status == 200
        _status, listed = call(server, "/api/units")
        assert listed["units"] == []

    def test_the_workbook_can_be_taken_away_again(self, server):
        _status, listed = call(server, "/api/units")
        unit_id = listed["units"][0]["id"]
        status, body = call(server, f"/api/units/{unit_id}/download")
        assert status == 200
        data = base64.b64decode(body["content_base64"])
        assert data[:2] == b"PK"                      # a real xlsx
        assert body["filename"].endswith(".xlsx")
        assert body["size_bytes"] == len(data)

    def test_two_units_of_the_same_name_are_refused(self, server):
        status, body = call(server, "/api/units", "POST",
                            {"name": "Marine Structures"})
        assert status == 422
        assert "already have a unit" in body["errors"][0]


class TestPrivacy:
    """The point of the login: one account cannot reach another's work."""

    def test_nothing_is_answered_without_a_session(self, server):
        anonymous = Client(str(server))               # no cookie
        for method, path in (("GET", "/api/status"), ("GET", "/api/units"),
                             ("GET", "/api/projects"), ("GET", "/api/tasks"),
                             ("POST", "/api/save")):
            status, body = call(anonymous, path, method)
            assert status == 401, path
            assert "Sign in" in body["error"]

    def test_the_app_shell_is_behind_the_login(self, server):
        anonymous = Client(str(server))
        with urllib.request.urlopen(str(anonymous) + "/") as response:
            page = response.read()
        assert b"login-form" in page
        assert b"view-overview" not in page

    def test_another_account_cannot_open_your_unit(self, server, stranger):
        _status, mine = call(server, "/api/units")
        unit_id = mine["units"][0]["id"]

        _status, theirs = call(stranger, "/api/units")
        assert theirs["units"] == []

        for method, path in (("POST", f"/api/units/{unit_id}/open"),
                             ("GET", f"/api/units/{unit_id}/download"),
                             ("PUT", f"/api/units/{unit_id}"),
                             ("DELETE", f"/api/units/{unit_id}")):
            status, body = call(stranger, path, method,
                                {} if method in ("PUT", "POST") else None)
            assert status == 404, path
            assert "not yours" in body["error"]

    def test_one_account_working_does_not_disturb_another(self, server, stranger):
        call(stranger, "/api/units", "POST", {"name": "Their unit"})
        status, theirs = call(stranger, "/api/status")
        assert theirs["projects"] == 0                # their blank template
        status, mine = call(server, "/api/status")
        assert mine["projects"] == 40                 # still my workbook

    def test_administration_is_for_administrators(self, server, stranger):
        status, _ = call(server, "/api/admin/users")
        assert status == 200
        status, body = call(stranger, "/api/admin/users")
        assert status == 403 and "administrators" in body["error"]

    def test_signing_out_ends_the_session(self, server):
        status, _ = call(server, "/api/auth/logout", "POST")
        assert status == 200
        status, _ = call(server, "/api/status")
        assert status == 401


class TestAccounts:
    def test_who_am_i_is_public_and_honest(self, server):
        status, body = call(server, "/api/auth/me")
        assert status == 200 and body["user"]["username"] == "ahmed"
        anonymous = Client(str(server))
        status, body = call(anonymous, "/api/auth/me")
        assert status == 200 and body["user"] is None
        assert body["any_accounts"] is True

    def test_a_wrong_password_says_nothing_useful(self, server):
        status, body = call(server, "/api/auth/login", "POST",
                            {"username": "ahmed", "password": "wrong"})
        assert status == 401
        assert body["error"] == ("That username and password do not match an "
                                 "account.")
        status, body = call(server, "/api/auth/login", "POST",
                            {"username": "nobody", "password": "wrong"})
        assert body["error"].startswith("That username and password")

    def test_an_administrator_can_add_and_remove_accounts(self, server):
        status, made = call(server, "/api/admin/users", "POST",
                            {"username": "kirolos", "display_name": "Kirolos"})
        assert status == 200
        assert made["password"], "a generated password comes back once"
        assert made["user"]["is_admin"] is False

        # And that password works.
        cookie = _sign_in(str(server), "kirolos", made["password"])
        theirs = Client(str(server))
        theirs.cookie = cookie
        status, body = call(theirs, "/api/auth/me")
        assert body["user"]["username"] == "kirolos"

        status, _ = call(server, f"/api/admin/users/{made['user']['id']}", "DELETE")
        assert status == 200
        status, _ = call(theirs, "/api/status")
        assert status == 401                          # their session went too

    def test_the_last_administrator_cannot_be_removed(self, server):
        me = call(server, "/api/auth/me")[1]["user"]
        status, body = call(server, f"/api/admin/users/{me['id']}", "DELETE")
        assert status == 422
        assert "signed in to" in body["errors"][0]

    def test_a_password_can_be_changed_and_the_session_survives(self, server):
        status, _ = call(server, "/api/auth/password", "POST", {
            "current_password": PASSWORD, "new_password": "another-long-one"})
        assert status == 200
        status, _ = call(server, "/api/status")
        assert status == 200                          # still signed in here

    def test_a_password_change_needs_the_current_one(self, server):
        status, body = call(server, "/api/auth/password", "POST", {
            "current_password": "not it", "new_password": "another-long-one"})
        assert status == 403 and "current password" in body["error"]

    def test_a_short_password_is_refused(self, server):
        status, body = call(server, "/api/admin/users", "POST",
                            {"username": "shorty", "password": "abc"})
        assert status == 422
        assert "at least" in body["errors"][0]


class TestCapacityEndpoint:
    def test_status_reports_how_much_room_is_left(self, server):
        _status, body = call(server, "/api/status")
        assert body["capacity"]["headroom"] == 315
        assert body["capacity"]["low_headroom"] is True

    def test_the_data_check_carries_the_warning(self, server):
        _status, body = call(server, "/api/timesheets")
        assert any("rows left" in w["message"] for w in body["capacity_warnings"])

    def test_the_limit_can_be_raised(self, server):
        status, body = call(server, "/api/timesheets/capacity", "POST",
                            {"raw_last_row": 12000})
        assert status == 200
        assert body["raw_last_row"] == 12000
        assert body["capacity"]["low_headroom"] is False
        assert body["helper_rows_added"] == 4000

    def test_it_defaults_to_the_suggested_limit(self, server):
        status, body = call(server, "/api/timesheets/capacity", "POST", {})
        assert status == 200 and body["raw_last_row"] == 12000

    def test_an_impossible_limit_is_refused(self, server):
        status, body = call(server, "/api/timesheets/capacity", "POST",
                            {"raw_last_row": 90000})
        assert status == 422
        assert any("beyond what the stack" in m for m in body["errors"])


class TestProjectWithDeliverables:
    """Deliverables live inside their project and are saved with it."""

    PROJECT = {"number": "SET-0100D", "name": "One go", "budget_mm": 4,
               "status": "Active"}

    def _deliverable(self, **overrides):
        item = {"name": "Phase", "type_code": "DD", "phase_weight": 1.0,
                "ts_phase": 1, "shares": {"Ahmed": 1.0}}
        item.update(overrides)
        return item

    def test_a_project_and_its_deliverables_are_created_together(self, server):
        status, body = call(server, "/api/projects/full", "POST", {
            "project": self.PROJECT,
            "deliverables": [
                self._deliverable(name="Design", phase_weight=0.4),
                self._deliverable(name="Report", phase_weight=0.6, ts_phase=2),
            ],
        })
        assert status == 200
        assert body["project"]["number"] == "SET-0100D"
        assert [d["name"] for d in body["deliverables"]] == ["Design", "Report"]
        assert body["weight_total"] == 1.0

    def test_weights_short_of_one_hundred_are_refused(self, server):
        status, body = call(server, "/api/projects/full", "POST", {
            "project": self.PROJECT,
            "deliverables": [self._deliverable(phase_weight=0.4)],
        })
        assert status == 422
        assert any("total 40.0%, not 100%" in m for m in body["errors"])

    def test_weights_over_one_hundred_are_refused(self, server):
        status, body = call(server, "/api/projects/full", "POST", {
            "project": self.PROJECT,
            "deliverables": [self._deliverable(phase_weight=0.7),
                             self._deliverable(name="Two", phase_weight=0.7)],
        })
        assert status == 422
        assert any("140.0%" in m for m in body["errors"])

    def test_a_project_with_no_deliverables_yet_can_still_be_saved(self, server):
        status, _ = call(server, "/api/projects/full", "POST",
                         {"project": self.PROJECT, "deliverables": []})
        assert status == 200

    def test_a_deliverable_split_is_named_per_engineer(self, server):
        call(server, "/api/projects/full", "POST", {
            "project": self.PROJECT,
            "deliverables": [self._deliverable(shares={"Ahmed": 0.25, "Osama": 0.75})],
        })
        _status, body = call(server, "/api/projects/SET-0100D")
        shares = body["deliverables"][0]["shares"]
        assert shares["Ahmed"] == 0.25 and shares["Osama"] == 0.75

    def test_a_split_that_misses_one_hundred_is_refused(self, server):
        status, body = call(server, "/api/projects/full", "POST", {
            "project": self.PROJECT,
            "deliverables": [self._deliverable(shares={"Ahmed": 0.6, "Osama": 0.3})],
        })
        assert status == 422
        assert any("must total 100%" in m for m in body["errors"])

    def test_the_detail_view_carries_its_figures(self, server):
        _status, body = call(server, "/api/projects/N25185-0100D")
        assert body["project"]["number"] == "N25185-0100D"
        assert body["metrics"]["progress"] == pytest.approx(0.316, abs=0.001)
        assert len(body["deliverables"]) == 22

    def test_editing_keeps_each_deliverable_on_its_own_row(self, server):
        _status, before = call(server, "/api/projects/N25178-0100D")
        row = before["deliverables"][0]["row"]
        status, body = call(server, "/api/projects/N25178-0100D/full", "PUT", {
            "project": before["project"],
            "deliverables": [{**before["deliverables"][0], "name": "Renamed"}],
        })
        assert status == 200
        assert body["deliverables"][0]["row"] == row

    def test_a_removed_deliverable_is_cleared(self, server):
        call(server, "/api/projects/full", "POST", {
            "project": self.PROJECT,
            "deliverables": [self._deliverable(name="Keep", phase_weight=0.5),
                             self._deliverable(name="Drop", phase_weight=0.5)],
        })
        status, body = call(server, "/api/projects/SET-0100D/full", "PUT", {
            "project": self.PROJECT,
            "deliverables": [self._deliverable(name="Keep", phase_weight=1.0)],
        })
        assert status == 200 and body["removed"] == 1
        _status, detail = call(server, "/api/projects/SET-0100D")
        assert [d["name"] for d in detail["deliverables"]] == ["Keep"]

    def test_an_unknown_project_is_a_404(self, server):
        status, _ = call(server, "/api/projects/GHOST-0100D")
        assert status == 404


class TestReferenceLock:
    """The reference tables are a deterrent against a stray edit, not a vault."""

    def test_they_are_locked_to_begin_with(self, server):
        _status, body = call(server, "/api/status")
        assert body["reference_unlocked"] is False

    def test_saving_while_locked_is_refused(self, server):
        status, body = call(server, "/api/reference", "PUT", {"project_types": []})
        assert status == 403
        assert "locked" in body["error"]

    def test_the_wrong_password_does_not_unlock(self, server):
        status, body = call(server, "/api/reference/unlock", "POST",
                            {"password": "1234"})
        assert status == 403
        assert "not right" in body["error"]
        _status, status_body = call(server, "/api/status")
        assert status_body["reference_unlocked"] is False

    def _unlock(self, server):
        status, _ = call(server, "/api/reference/unlock", "POST",
                         {"password": "2026"})
        assert status == 200

    def test_the_right_password_unlocks(self, server):
        self._unlock(server)
        _status, body = call(server, "/api/status")
        assert body["reference_unlocked"] is True

    def _tables(self, server):
        _status, ref = call(server, "/api/reference")
        steps = [dict(s, type_code=code)
                 for code, items in ref["credit_steps"].items() for s in items]
        return ref["project_types"], steps

    def test_a_credit_can_be_changed_and_comes_back(self, server):
        self._unlock(server)
        types, steps = self._tables(server)
        for step in steps:
            if step["type_code"] == "DD" and step["step_no"] == 1:
                step["credit"] = 0.15
        status, _ = call(server, "/api/reference", "PUT",
                         {"project_types": types, "credit_steps": steps})
        assert status == 200
        _status, ref = call(server, "/api/reference")
        assert [s["credit"] for s in ref["credit_steps"]["DD"]
                if s["step_no"] == 1] == [0.15]

    def test_a_portfolio_weight_can_be_changed(self, server):
        self._unlock(server)
        types, steps = self._tables(server)
        for item in types:
            if item["code"] == "CD":
                item["portfolio_weight"] = 1.25
        call(server, "/api/reference", "PUT",
             {"project_types": types, "credit_steps": steps})
        _status, ref = call(server, "/api/reference")
        assert [t["portfolio_weight"] for t in ref["project_types"]
                if t["code"] == "CD"] == [1.25]

    def test_a_step_for_an_unknown_type_is_refused(self, server):
        self._unlock(server)
        types, steps = self._tables(server)
        steps[0] = {**steps[0], "type_code": "ZZ"}
        status, body = call(server, "/api/reference", "PUT",
                            {"project_types": types, "credit_steps": steps})
        assert status == 422
        assert any("not in Project Types" in m for m in body["errors"])

    def test_a_duplicated_step_is_refused(self, server):
        self._unlock(server)
        types, steps = self._tables(server)
        steps[1] = {**steps[1], "type_code": steps[0]["type_code"],
                    "step_no": steps[0]["step_no"]}
        status, body = call(server, "/api/reference", "PUT",
                            {"project_types": types, "credit_steps": steps})
        assert status == 422
        assert any("appears twice" in m for m in body["errors"])

    def test_locking_again_closes_it(self, server):
        self._unlock(server)
        call(server, "/api/reference/lock", "POST")
        status, _ = call(server, "/api/reference", "PUT", {"project_types": []})
        assert status == 403


class TestImportFilter:
    """Narrowing an import to registered projects is what keeps the sheet small."""

    def _export(self, readonly_wb, job_numbers):
        openpyxl = pytest.importorskip("openpyxl")
        headers = readonly_wb.timesheet_headers("Kirolos")
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(headers)
        index = {h: i for i, h in enumerate(headers)}
        for position, job in enumerate(job_numbers):
            row = [None] * len(headers)
            row[index["Job Type"]] = "1-Projects"
            row[index["JobNumber"]] = job
            row[index["FullName"]] = "Kirolos Nabil"
            row[index["Date"]] = dt.date(2026, 9, (position % 28) + 1)
            row[index["Phase"]] = 1
            row[index["TotalHours"]] = 8.0
            sheet.append(row)
        buffer = io.BytesIO()
        book.save(buffer)
        return base64.b64encode(buffer.getvalue()).decode()

    def test_unregistered_rows_are_left_out(self, server, readonly_wb):
        content = self._export(readonly_wb,
                               ["N25185-0100D"] * 3 + ["MYSTERY-0100D"] * 2)
        _status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": content, "registered_only": True,
        })
        assert staged["row_count"] == 3
        assert staged["dropped_rows"] == 2
        assert staged["dropped"][0]["code"] == "MYSTERY-0100D"

    def test_turning_the_filter_off_keeps_everything(self, server, readonly_wb):
        content = self._export(readonly_wb,
                               ["N25185-0100D"] * 3 + ["MYSTERY-0100D"] * 2)
        _status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": content, "registered_only": False,
        })
        assert staged["row_count"] == 5
        assert staged["dropped_rows"] == 0

    def test_absence_codes_are_kept(self, server, readonly_wb):
        content = self._export(readonly_wb, ["LEAVE", "HOLIDAY", "N25185-0100D"])
        _status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": content, "registered_only": True,
        })
        assert staged["row_count"] == 3
        assert staged["dropped_rows"] == 0

    def test_an_export_with_nothing_registered_says_so(self, server, readonly_wb):
        content = self._export(readonly_wb, ["MYSTERY-0100D"] * 3)
        _status, staged = call(server, "/api/timesheets/stage", "POST", {
            "engineer": "Kirolos", "filename": "k.xlsx",
            "content_base64": content, "registered_only": True,
        })
        assert any("nothing to import" in m for m in staged["errors"])


class TestReportsEndpoint:
    def test_a_year_is_the_default(self, server):
        status, body = call(server, "/api/reports")
        assert status == 200
        assert body["period"]["kind"] == "year"
        assert body["period"]["year"] == body["periods"]["plan_year"]

    def test_the_headline_figures_are_there(self, server):
        _status, body = call(server, "/api/reports?period=year&year=2026")
        assert body["team"]["actual_mm"] == pytest.approx(17.91, abs=0.01)
        assert body["team"]["planned_mm"] == pytest.approx(44.83, abs=0.01)

    def test_every_view_has_what_it_needs(self, server):
        _status, body = call(server, "/api/reports?period=year&year=2026")
        assert set(body) >= {"team", "per_engineer", "by_status", "scorecard",
                             "quarterly", "delivery_mix", "projects", "periods",
                             "engineers", "issues"}
        assert set(body["per_engineer"]) == set(body["engineers"])

    def test_a_quarter_can_be_asked_for(self, server):
        _status, body = call(server, "/api/reports?period=quarter&year=2026&quarter=Q1")
        assert body["period"]["kind"] == "quarter"
        assert body["period"]["from"] == "2026-01-01"
        assert body["period"]["to"] == "2026-03-31"

    def test_all_time_is_accepted(self, server):
        _status, body = call(server, "/api/reports?period=all")
        assert body["period"]["kind"] == "all"

    def test_the_years_offered_come_from_the_workbook(self, server):
        _status, body = call(server, "/api/reports")
        assert 2026 in body["periods"]["years"]
        assert body["periods"]["quarters"] == ["Q1", "Q2", "Q3", "Q4"]

    def test_reports_need_a_workbook(self, empty_server):
        status, _ = call(empty_server, "/api/reports")
        assert status == 409


class TestTeamEndpoint:
    def test_the_team_lists_itself(self, server):
        status, body = call(server, "/api/team")
        assert status == 200
        assert [p["short_name"] for p in body["engineers"]] == [
            "Ahmed", "Osama", "Kirolos"]
        assert body["years"] == [2024, 2025, 2026, 2027, 2028]

    def test_an_engineer_can_be_added(self, server):
        status, body = call(server, "/api/team", "POST", {
            "short_name": "Nadia", "available_hours": 185,
            "availability": {"2026": 1.0},
        })
        assert status == 200
        assert body["sheet"] == "TS Nadia"
        _status, team = call(server, "/api/team")
        assert "Nadia" in [p["short_name"] for p in team["engineers"]]

    def test_a_new_engineer_reaches_the_reports(self, server):
        call(server, "/api/team", "POST",
             {"short_name": "Nadia", "available_hours": 185,
              "availability": {"2026": 1.0}})
        _status, body = call(server, "/api/reports?period=year&year=2026")
        assert "Nadia" in body["engineers"]
        assert "Nadia" in body["per_engineer"]

    def test_a_new_engineer_can_take_a_timesheet(self, server):
        call(server, "/api/team", "POST",
             {"short_name": "Nadia", "available_hours": 185})
        _status, check = call(server, "/api/timesheets")
        assert "Nadia" in check["per_engineer"]
        assert check["per_engineer"]["Nadia"]["rows"] == 0

    def test_an_engineer_can_be_renamed(self, server):
        status, body = call(server, "/api/team/Kirolos", "PUT",
                            {"short_name": "Mina"})
        assert status == 200 and body["renamed"] is True
        _status, team = call(server, "/api/team")
        assert "Mina" in [p["short_name"] for p in team["engineers"]]

    def test_an_engineer_can_be_removed(self, server):
        status, body = call(server, "/api/team/Kirolos", "DELETE")
        assert status == 200
        assert body["sheet_removed"] == "TS Kirolos"
        _status, team = call(server, "/api/team")
        assert [p["short_name"] for p in team["engineers"]] == ["Ahmed", "Osama"]

    def test_a_duplicate_name_is_refused(self, server):
        status, body = call(server, "/api/team", "POST", {"short_name": "Ahmed"})
        assert status == 422
        assert any("already an engineer" in m for m in body["errors"])

    def test_the_team_needs_a_workbook(self, empty_server):
        status, _ = call(empty_server, "/api/team")
        assert status == 409


class TestScorecardFactorsEndpoint:
    def _unlock(self, server):
        call(server, "/api/reference/unlock", "POST", {"password": "2026"})

    def test_the_factors_come_back_with_the_reference(self, server):
        _status, body = call(server, "/api/reference")
        assert len(body["scorecard_factors"]) == 6
        assert body["scorecard_factors"][0]["key"] == "type_weighted_cpi"
        assert body["definitions"]

    def test_they_cannot_be_changed_while_locked(self, server):
        status, _ = call(server, "/api/reference", "PUT",
                         {"scorecard_factors": []})
        assert status == 403

    def test_a_weight_can_be_changed(self, server):
        self._unlock(server)
        _status, ref = call(server, "/api/reference")
        factors = ref["scorecard_factors"]
        factors[0]["weight"] = 0.4
        factors[1]["weight"] = 0.1
        status, _ = call(server, "/api/reference", "PUT", {
            "project_types": ref["project_types"],
            "credit_steps": [dict(s, type_code=code)
                             for code, items in ref["credit_steps"].items()
                             for s in items],
            "scorecard_factors": factors,
        })
        assert status == 200
        _status, after = call(server, "/api/reference")
        assert after["scorecard_factors"][0]["weight"] == pytest.approx(0.4)

    def test_weights_that_do_not_add_up_are_refused(self, server):
        self._unlock(server)
        _status, ref = call(server, "/api/reference")
        factors = ref["scorecard_factors"]
        factors[0]["weight"] = 0.9
        status, body = call(server, "/api/reference", "PUT",
                            {"scorecard_factors": factors})
        assert status == 422
        assert any("not 100%" in m for m in body["errors"])


class TestHeroesInTheApi:
    def test_the_report_carries_the_heroes(self, server):
        _status, body = call(server, "/api/reports?period=year&year=2026")
        assert body["heroes"]["month"]["month"] == "2026-08"
        assert body["heroes"]["year"]["engineer"] in body["engineers"]
        assert body["monthly"]


class TestTheStackIsWidenedOnOpen:
    """The workbook ships reading 6,000 rows a sheet; nobody should have to ask."""

    def test_opening_a_workbook_deepens_the_stack(self, server):
        _status, status = call(server, "/api/status")
        assert status["stack_raised_to"] == 25000
        assert status["capacity"]["source_last_row"] == 25000
        assert status["capacity"]["source_is_short"] is False

    def test_the_consolidated_limit_is_left_alone(self, server):
        _status, status = call(server, "/api/status")
        # Raising that one rewrites 138,000 formulas; it stays a decision.
        assert status["capacity"]["raw_last_row"] == 8000

    def test_a_workbook_already_deep_enough_is_not_rewritten(self, workbook_copy):
        from workload_app.service import WorkloadService
        first = WorkloadService(workbook_copy)
        assert first._stack_raised_to == 25000
        again = WorkloadService(workbook_copy)
        assert again._stack_raised_to is None


class TestTasks:
    """The task tab's endpoints. Nothing here may touch the model's figures."""

    def test_the_list_carries_everything_the_tab_needs(self, server):
        status, data = call(server, "/api/tasks")
        assert status == 200
        assert data["tasks"] == []
        assert data["engineers"] == ["Ahmed", "Osama", "Kirolos"]
        assert data["statuses"][0] == "Not started"
        assert data["settings"]["day_end"] == "17:30"
        assert data["load"]["hours_per_day"] == 8.5
        assert data["deliverables"] and "date" in data["deliverables"][0]

    def test_a_task_can_be_added_changed_and_dropped(self, server):
        status, added = call(server, "/api/tasks", "POST", {
            "name": "Check the mooring loads", "assignees": ["Osama", "Kirolos"],
            "required_hours": 10, "due": "2026-09-18",
        })
        assert status == 200
        assert added["task"]["hours_each"] == 5.0
        assert added["task"]["shared"] is True

        task_id = added["task"]["id"]
        status, changed = call(server, f"/api/tasks/{task_id}", "PUT", {
            "name": "Check the mooring loads", "assignees": ["Osama"],
            "required_hours": 10, "actual_hours": 12, "status": "Done",
        })
        assert status == 200 and changed["task"]["done"] is True

        status, gone = call(server, f"/api/tasks/{task_id}", "DELETE")
        assert status == 200 and gone["remaining"] == 0

    def test_a_rejected_task_says_why(self, server):
        status, body = call(server, "/api/tasks", "POST",
                            {"name": "", "assignees": ["Nobody"]})
        assert status == 422
        assert any("needs a name" in e for e in body["errors"])
        assert any("Nobody" in e for e in body["errors"])

    def test_the_working_day_is_stored_and_checked(self, server):
        status, saved = call(server, "/api/tasks/settings", "PUT",
                             {"day_end": "18:00", "work_days": [6, 0, 1, 2, 3]})
        assert status == 200
        assert saved["settings"]["day_end"] == "18:00"
        assert saved["settings"]["work_days"] == [0, 1, 2, 3, 6]

        status, body = call(server, "/api/tasks/settings", "PUT",
                            {"day_start": "half nine"})
        assert status == 422 and body["errors"]

    def test_the_weekly_meeting_button_fills_the_series(self, server):
        status, made = call(server, "/api/tasks/generate/meetings", "POST",
                            {"start": "2026-09-07", "weeks": 4})
        assert status == 200 and made["added"] == 4
        _status, data = call(server, "/api/tasks")
        assert len(data["tasks"]) == 4
        assert all(t["kind"] == "Meeting" for t in data["tasks"])

        _status, series = call(server, "/api/tasks/series/delete", "POST",
                               {"series": made["series"]})
        assert series["deleted"] == 4

    def test_submission_tasks_come_from_a_deliverable_date(self, server):
        _status, deliverables = call(server, "/api/deliverables")
        target = deliverables["deliverables"][0]
        call(server, f"/api/deliverables/{target['row']}", "PUT",
             {**target, "status_date": "2027-01-20"})
        status, made = call(server, "/api/tasks/generate/submissions", "POST", {})
        assert status == 200 and made["added"] > 0
        _status, data = call(server, "/api/tasks")
        assert all(t["deliverable_row"] == target["row"] for t in data["tasks"])
        assert all(t["kind"] == "Submission" for t in data["tasks"])
