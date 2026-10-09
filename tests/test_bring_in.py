"""Bring in data: any mix of files in one place, each sent where it belongs.

Synthetic exports only, built by the helpers the timesheet and budget tests
already use, so no private workbook is needed.
"""

import base64
import io

import pytest

from test_budgets import JOB, project, projects_list, the_staff_list
from test_from_timesheets import D, export, row, team_exports
from workload_app import bringin, storage
from workload_app.service import ApiError, WorkloadService

openpyxl = pytest.importorskip("openpyxl")


def drawing_list(rows, filename="Drawing list.xlsx"):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Drawing list"
    sheet.append(["Job Number", "Deliverable", "Drawing No.", "Title",
                  "Revision", "Status", "Issued", "Code", "Returned"])
    for item in rows:
        sheet.append(item)
    buffer = io.BytesIO()
    book.save(buffer)
    return {"filename": filename,
            "content_base64": base64.b64encode(buffer.getvalue()).decode()}


def drawings():
    return drawing_list([
        [JOB, "Detailed Design ST", f"ST-{i:03d}", f"Quay wall {i}", "A",
         "IFC" if i < 3 else "In progress", D(2026, 9, 1 + i) if i < 3 else None,
         "", None]
        for i in range(5)])


def kind(item):
    return bringin.classify(item["filename"],
                            base64.b64decode(item["content_base64"]))[0]


@pytest.fixture
def blank(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", "2026-10-01")
    return WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))


class TestTellingFilesApart:
    def test_each_kind_is_known_by_its_headings(self):
        assert kind(team_exports()[0]) == "timesheets"
        assert kind(projects_list(project(JOB, 10, 4))) == "projects"
        assert kind(the_staff_list()) == "spend"
        assert kind(drawings()) == "drawings"

    def test_a_timesheet_without_its_job_type_column_is_still_one(self):
        item = export([row("Ahmed Mockridge", JOB, D(2026, 8, 2), 8)])
        data = base64.b64decode(item["content_base64"])
        book = openpyxl.load_workbook(io.BytesIO(data))
        book.active.delete_cols(1)                           # no "Job Type"
        buffer = io.BytesIO()
        book.save(buffer)
        assert bringin.classify("x.xlsx", buffer.getvalue())[0] == "timesheets"

    def test_anything_else_is_named_and_not_guessed(self):
        found, why = bringin.classify("notes.csv", b"a,b\n1,2\n")
        assert found is None and "notes.csv" in why


class TestOnePlace:
    def test_every_file_at_once_fills_everything(self, blank):
        files = team_exports() + [projects_list(project(JOB, 10, 4)),
                                  the_staff_list(), drawings()]
        check = blank.bring_in_check(files)
        assert check["ready"] and check["errors"] == []
        assert [f["kind"] for f in check["files"]] == [
            "timesheets", "timesheets", "projects", "spend", "drawings"]
        assert check["timesheets"]["rows"] == 6
        assert check["timesheets"]["new_people"] == ["Ahmed", "Osama"]
        # Nothing is written until it is brought in.
        assert blank.bring_in_state()["timesheets"]["rows"] == 0

        done = blank.bring_in_apply(check["token"])
        assert [s["kind"] for s in done["steps"]] == ["timesheets", "budgets", "drawings"]
        assert all(s["ok"] for s in done["steps"]), done["steps"]
        state = done["state"]
        # Six rows of their own, and three days the staff list filled in.
        assert state["timesheets"]["rows"] == 9 and state["timesheets"]["people"] == 2
        assert state["projects"] == {"jobs": 1, "with_budget": 1}
        assert state["spend"] == {"jobs": 1}
        assert state["drawings"]["drawings"] == 5

    def test_the_drawings_land_on_the_deliverables_the_timesheets_made(self, blank):
        done = blank.bring_in_apply(
            blank.bring_in_check(team_exports() + [drawings()])["token"])
        assert "5 drawing(s) matched" in done["steps"][-1]["said"]

    def test_a_file_it_does_not_know_is_left_out_and_the_rest_come_in(self, blank):
        bad = {"filename": "notes.csv",
               "content_base64": base64.b64encode(b"a,b\n1,2\n").decode()}
        check = blank.bring_in_check(team_exports() + [bad])
        assert check["ready"] and len(check["errors"]) == 1
        assert check["files"][-1]["kind"] is None
        done = blank.bring_in_apply(check["token"])
        assert done["state"]["timesheets"]["rows"] == 6

    def test_a_check_is_used_once(self, blank):
        token = blank.bring_in_check(team_exports())["token"]
        blank.bring_in_apply(token)
        with pytest.raises(ApiError):
            blank.bring_in_apply(token)

    def test_nothing_chosen_is_refused(self, blank):
        with pytest.raises(ApiError):
            blank.bring_in_check([])


class TestOverHttp:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from test_server import _account, _serve
        monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "instance"))
        monkeypatch.setenv("WORKLOAD_TODAY", "2026-10-01")
        httpd = _serve(tmp_path / "instance")
        try:
            yield _account(httpd, f"http://127.0.0.1:{httpd.server_address[1]}")
        finally:
            httpd.app.close_all()
            httpd.shutdown()
            httpd.server_close()

    def test_a_new_unit_takes_every_file_at_once(self, client):
        from test_server import call
        status, body = call(client, "/api/units/from-timesheets", "POST", {
            "files": team_exports() + [projects_list(project(JOB, 10, 4)), drawings()]})
        assert status == 200, body
        assert body["imported"]["rows_written"] == 6
        assert [s["kind"] for s in body["brought_in"]] == ["budgets", "drawings"]
        status, state = call(client, "/api/bring-in")
        assert state["projects"]["jobs"] == 1 and state["drawings"]["drawings"] == 5

    def test_budgets_alone_cannot_start_a_unit(self, client):
        from test_server import call
        status, _ = call(client, "/api/units/from-timesheets", "POST",
                         {"files": [projects_list(project(JOB, 10, 4))]})
        assert status == 400
        _status, units = call(client, "/api/units")
        assert units["units"] == []

    def test_check_then_bring_in(self, client):
        from test_server import call
        call(client, "/api/units/from-timesheets", "POST", {"files": team_exports()[:1]})
        status, check = call(client, "/api/bring-in/check", "POST",
                             {"files": team_exports()[1:] + [the_staff_list()]})
        assert status == 200, check
        status, done = call(client, "/api/bring-in/apply", "POST",
                            {"token": check["token"]})
        assert status == 200, done
        assert done["state"]["timesheets"]["people"] == 2
        assert done["state"]["spend"]["jobs"] == 1


class TestThePage:
    def setup_method(self):
        from workload_app.app import STATIC_DIR
        self.index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    def test_the_tab_its_view_and_its_files_are_on_the_page(self):
        assert 'data-view="bringin"' in self.index and 'id="view-bringin"' in self.index
        assert 'src="bringin.js"' in self.index and 'href="bringin.css"' in self.index
        assert "window.bringin.load()" in self.app

    def test_a_newcomer_reads_from_what_to_do_now_down_to_the_detail(self):
        import re
        tabs = re.findall(r'data-view="([a-z]+)"', self.index)
        assert tabs[:4] == ["overview", "planner", "checkins", "weekly"]
        assert tabs.index("bringin") > tabs.index("team")
        start = self.index.index('id="overview-start"')
        assert start < self.index.index('id="overview-checkins"') \
            < self.index.index('id="overview-cards"') < self.index.index('id="formation"')

    def test_the_start_card_is_drawn_after_every_refresh(self):
        assert "window.bringin.startHere()" in self.app


class TestPaths:
    def setup_method(self):
        from workload_app.app import STATIC_DIR
        self.index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.paths = (STATIC_DIR / "paths.js").read_text(encoding="utf-8")
        self.app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    def test_the_app_opens_on_the_paths(self):
        assert 'id="view-paths"' in self.index and 'src="paths.js"' in self.index
        assert "window.paths.opened()" in self.app

    def test_every_path_leads_to_tabs_that_exist(self):
        import re
        views = set(re.findall(r'data-view="([a-z]+)"', self.index))
        lists = re.findall(r"tabs: \[([^\]]+)\]", self.paths)
        assert len(lists) == 4
        for found in lists:
            for view in re.findall(r"'([a-z]+)'", found):
                assert view in views, view
        # Between them, the paths reach every tab but help and Admin.
        reached = {v for found in lists for v in re.findall(r"'([a-z]+)'", found)}
        assert views - reached == {"guide", "admin"}
