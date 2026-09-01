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


@pytest.fixture
def server(workbook_copy):
    httpd = make_server(workbook_copy, "127.0.0.1", 0, quiet=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
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
            assert b"Workload Input" in response.read()

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
