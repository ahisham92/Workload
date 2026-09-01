"""The HTTP layer, driven against a real server on a real workbook copy."""

import base64
import datetime as dt
import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from workload_app.server import make_server


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    from workload_app import library
    monkeypatch.setattr(library, "SETTINGS_FILE", tmp_path / "settings.json")


def _serve(workbook):
    httpd = make_server(workbook, "127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


@pytest.fixture
def server(workbook_copy):
    httpd = _serve(workbook_copy)
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def empty_server():
    """A server started with no workbook, as it is when you just run it."""
    httpd = _serve(None)
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(base, path, method="GET", body=None):
    request = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


class TestStaticAndRouting:
    def test_the_page_is_served(self, server):
        with urllib.request.urlopen(server + "/") as response:
            assert response.status == 200
            assert b"Workload" in response.read()

    @pytest.mark.parametrize("path", ["/app.css", "/app.js"])
    def test_assets_are_served(self, server, path):
        with urllib.request.urlopen(server + path) as response:
            assert response.status == 200

    def test_an_unknown_api_path_is_a_404(self, server):
        status, _ = call(server, "/api/nope")
        assert status == 404

    def test_paths_cannot_escape_the_static_directory(self, server):
        try:
            with urllib.request.urlopen(server + "/../workbook.py") as response:
                assert response.status == 404
        except urllib.error.HTTPError as error:
            assert error.code in (400, 404)


class TestReads:
    def test_status(self, server, workbook_copy):
        status, body = call(server, "/api/status")
        assert status == 200
        assert body["workbook"] == str(workbook_copy)
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


class TestChoosingAUnit:
    """A unit is a name and the workbook behind it; nothing opens until one is."""

    def test_it_starts_with_none_open(self, empty_server):
        status, body = call(empty_server, "/api/status")
        assert status == 200
        assert body["open"] is False
        assert body["workbook"] is None
        assert body["unit"] is None

    def test_the_registers_are_refused_until_one_is_chosen(self, empty_server):
        for path in ("/api/projects", "/api/deliverables", "/api/reference",
                     "/api/overview", "/api/timesheets"):
            status, body = call(empty_server, path)
            assert status == 409, path
            assert "No workbook is open" in body["error"]

    def test_the_page_still_loads_so_you_can_choose(self, empty_server):
        with urllib.request.urlopen(empty_server + "/") as response:
            assert response.status == 200

    def test_the_list_starts_empty_with_somewhere_to_look(self, empty_server):
        status, body = call(empty_server, "/api/units")
        assert status == 200
        assert body["units"] == []
        assert "cwd" in body and "suggestions" in body

    def test_opening_one_names_it_and_makes_everything_work(self, empty_server,
                                                            workbook_copy):
        status, body = call(empty_server, "/api/units/open", "POST",
                            {"path": str(workbook_copy), "name": "Marine Structures"})
        assert status == 200
        assert body["open"] is True
        assert body["unit"]["name"] == "Marine Structures"
        assert body["projects"] == 40
        assert body["engineers"] == ["Ahmed", "Osama", "Kirolos"]
        status, body = call(empty_server, "/api/projects")
        assert status == 200 and len(body["projects"]) == 40

    def test_an_opened_unit_is_remembered_and_can_be_reopened_by_id(
            self, empty_server, workbook_copy):
        call(empty_server, "/api/units/open", "POST",
             {"path": str(workbook_copy), "name": "Marine Structures"})
        _status, body = call(empty_server, "/api/units")
        assert [u["name"] for u in body["units"]] == ["Marine Structures"]
        unit_id = body["units"][0]["id"]

        call(empty_server, "/api/units/close", "POST")
        status, body = call(empty_server, "/api/units/open", "POST",
                            {"unit_id": unit_id})
        assert status == 200 and body["unit"]["name"] == "Marine Structures"

    def test_a_unit_that_is_no_longer_saved_is_reported(self, empty_server):
        status, body = call(empty_server, "/api/units/open", "POST",
                            {"unit_id": "nope"})
        assert status == 404
        assert "no longer saved" in body["error"]

    def test_forgetting_a_unit(self, empty_server, workbook_copy):
        call(empty_server, "/api/units/open", "POST",
             {"path": str(workbook_copy), "name": "Marine Structures"})
        _status, body = call(empty_server, "/api/units")
        unit_id = body["units"][0]["id"]
        status, _ = call(empty_server, f"/api/units/{unit_id}", "DELETE")
        assert status == 200
        _status, body = call(empty_server, "/api/units")
        assert body["units"] == []

    def test_the_wrong_file_is_refused_with_a_reason(self, empty_server, tmp_path):
        other = tmp_path / "notes.txt"
        other.write_text("hello")
        status, body = call(empty_server, "/api/units/open", "POST",
                            {"path": str(other)})
        assert status == 422
        assert "not an .xlsx file" in body["error"]

    def test_closing_saves_and_lets_you_pick_again(self, server):
        call(server, "/api/projects", "POST", {
            "number": "CLOSE-0100D", "name": "x", "budget_mm": 1, "status": "Active"})
        status, body = call(server, "/api/units/close", "POST")
        assert status == 200 and body["open"] is False
        status, _ = call(server, "/api/projects")
        assert status == 409

    def test_browsing_a_folder(self, empty_server, workbook_copy):
        folder = str(workbook_copy.parent)
        _status, body = call(empty_server, f"/api/units?folder={folder}")
        assert body["browse"]["folder"] == folder
        assert any(f["name"] == workbook_copy.name for f in body["browse"]["files"])


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
