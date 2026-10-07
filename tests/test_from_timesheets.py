"""A unit set up from nothing but timesheet exports.

These run against the blank template that ships with the app, so unlike most
of the suite they need no private workbook: the exports are the input.
"""

import base64
import datetime as dt
import io
import shutil

import pytest

from workload_app import derive, storage
from workload_app.service import ApiError, WorkloadService

openpyxl = pytest.importorskip("openpyxl")

HEADERS = ["Job Type", "JobNumber", "FullName", "Grade", "Date", "Phase",
           "RegularHours", "OvertimeHours", "TotalHours", "JobStatus",
           "DeliverableDescription", "CurrentUnitDesc"]


def row(name, job, day, hours, *, phase=1, deliverable="Concept Design SB",
        status="Active", job_type="1-Projects", grade="P2"):
    return {"Job Type": job_type, "JobNumber": job, "FullName": name,
            "Grade": grade, "Date": day, "Phase": phase,
            "RegularHours": hours, "OvertimeHours": 0, "TotalHours": hours,
            "JobStatus": status, "DeliverableDescription": deliverable,
            "CurrentUnitDesc": "MARINE STRUCTURES"}


def export(rows, filename="export.xlsx"):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Timesheet export"])
    sheet.append([])
    sheet.append(HEADERS)
    for item in rows:
        sheet.append([item.get(h) for h in HEADERS])
    buffer = io.BytesIO()
    book.save(buffer)
    return {"filename": filename,
            "content_base64": base64.b64encode(buffer.getvalue()).decode()}


D = dt.date


def team_exports():
    ahmed = [
        row("Ahmed Mitwally", "N25185-0100D", D(2026, 3, 1), 8, grade="Lead"),
        row("Ahmed Mitwally", "N25185-0100D", D(2026, 8, 2), 8, phase=4,
            deliverable="Detailed Design ST", grade="Lead"),
        row("Ahmed Mitwally", "LEAVE", D(2026, 8, 3), 8, job_type="6-Additives",
            phase=0, deliverable="", grade="Lead"),
        # Last booked years before everything else: finished, whatever the
        # status on the row says.
        row("Ahmed Mitwally", "S12066-0100D", D(2019, 5, 1), 40, phase=4,
            deliverable="Tender Documents SB", grade="P1"),
    ]
    osama = [
        row("Osama Ayman", "N25185-0100D", D(2026, 8, 4), 24, phase=4,
            deliverable="Detailed Design ST", grade="Professional"),
        row("Osama Ayman", "E26084-0100D", D(2026, 8, 5), 4,
            deliverable="Schematic Design - STR", status="Not Started",
            grade="Professional"),
    ]
    return [export(ahmed, "ahmed.xlsx"), export(osama, "osama.xlsx")]


@pytest.fixture
def blank(tmp_path):
    target = tmp_path / "unit.xlsx"
    shutil.copy(storage.template_path(), target)
    return WorkloadService(target)


class TestReadingTheTeamOutOfTheExports:
    def test_everyone_is_found_without_being_chosen(self, blank):
        staged = blank.stage_exports(team_exports())
        assert staged["errors"] == []
        assert {p["name"] for p in staged["people"]} == {"Ahmed", "Osama"}
        assert all(p["new"] for p in staged["people"])
        assert staged["unit_name"] == "Marine Structures"

    def test_the_template_placeholders_give_way_to_real_people(self, blank):
        blank.import_exports(team_exports())
        assert sorted(blank.workbook.engineer_names()) == ["Ahmed", "Osama"]
        team = {e["short_name"]: e for e in blank.workbook.team()}
        assert team["Ahmed"]["pattern"] == "Ahmed Mitwally"
        assert team["Ahmed"]["available_hours"] == pytest.approx(
            blank.workbook.hours_per_man_month())

    def test_grades_come_from_the_latest_row(self, blank):
        blank.import_exports(team_exports())
        grades = {p["name"]: p["grade"] for p in blank.store.people()}
        assert grades == {"Ahmed": "senior", "Osama": "junior"}

    def test_a_second_import_matches_people_already_there(self, blank):
        blank.import_exports(team_exports())
        again = blank.stage_exports(team_exports()[1:])
        assert [p["new"] for p in again["people"]] == [False]

    def test_a_department_bigger_than_the_workbook(self, blank):
        crowd = [row(f"Person{n} Surname", "N25185-0100D", D(2026, 8, 1), 8)
                 for n in range(14)]
        result = blank.import_exports([export(crowd, "department.xlsx")])
        assert len(result["people_added"]) == 14
        assert len(blank.workbook.engineer_names()) == 12
        assert len(blank.store.people_with_rows()) == 14
        again = blank.stage_exports([export(crowd, "department.xlsx")])
        assert not any(p["new"] for p in again["people"])

    def test_a_file_that_is_not_an_export_is_refused_and_writes_nothing(
            self, blank):
        bad = {"filename": "notes.csv",
               "content_base64": base64.b64encode(b"a,b\n1,2\n").decode()}
        with pytest.raises(ApiError):
            blank.import_exports([bad])
        assert blank.store.count() == 0


class TestTheRegisterFromTheExports:
    def test_every_project_job_becomes_a_project(self, blank):
        result = blank.import_exports(team_exports())
        numbers = {p.number for p in blank.workbook.projects()}
        assert numbers == {"N25185-0100D", "E26084-0100D", "S12066-0100D"}
        assert set(result["projects_added"]) == numbers
        # Leave is a charge code, never a project.
        assert "LEAVE" not in numbers

    def test_dates_status_and_budget(self, blank):
        blank.import_exports(team_exports())
        projects = {p.number: p for p in blank.workbook.projects()}
        live = projects["N25185-0100D"]
        assert live.start == D(2026, 3, 1)
        assert live.end == D(2026, 8, 31)
        assert live.status == "Active"
        assert live.budget_mm == pytest.approx(0.3)      # 40 h / 185, rounded up
        assert derive.needs_confirming(live.notes)
        assert projects["E26084-0100D"].status == "Not Started"
        assert projects["S12066-0100D"].status == "Finalized"

    def test_a_deliverable_per_phase_weighted_and_split_by_hours(self, blank):
        blank.import_exports(team_exports())
        mine = {d.name: d for d in blank.workbook.deliverables()
                if d.project_number == "N25185-0100D"}
        assert set(mine) == {"Concept Design SB", "Detailed Design ST"}
        concept, detail = mine["Concept Design SB"], mine["Detailed Design ST"]
        assert concept.phase_weight == pytest.approx(0.2)    # 8 of 40 hours
        assert detail.phase_weight == pytest.approx(0.8)
        assert concept.type_code == "CD"
        assert detail.type_code == "DD"
        assert detail.ts_phase == 4
        assert detail.shares["Osama"] == pytest.approx(0.75)
        assert detail.shares["Ahmed"] == pytest.approx(0.25)
        # Booked to, so at least started; nothing more is known.
        assert concept.step_no == 1

    def test_a_finished_project_is_complete(self, blank):
        blank.import_exports(team_exports())
        (old,) = [d for d in blank.workbook.deliverables()
                  if d.project_number == "S12066-0100D"]
        assert old.type_code == "TD"
        steps = blank.workbook.reference()["credit_steps"]["TD"]
        assert old.step_no == max(s["step_no"] for s in steps)

    def test_a_project_already_in_the_register_is_left_alone(self, blank):
        blank.import_exports(team_exports())
        detail = blank.project_detail("N25185-0100D")
        project = dict(detail["project"], name="Port Modernisation", budget_mm=26)
        blank.save_project_with_deliverables(
            "N25185-0100D",
            {"project": project, "deliverables": detail["deliverables"]})
        result = blank.import_exports(team_exports())
        assert result["projects_added"] == []
        kept = blank.workbook.project("N25185-0100D")
        assert kept.name == "Port Modernisation"
        assert kept.budget_mm == 26
        # Saving it is what confirms it.
        assert not derive.needs_confirming(kept.notes)

    def test_proposal_effort_is_a_project_a_year(self, blank):
        bids = [
            row("Ahmed Mitwally", "PS250346", D(2026, 2, 1), 10, phase=0,
                job_type="3-Proposals Regular", deliverable=""),
            row("Ahmed Mitwally", "PE240049C", D(2025, 6, 1), 6, phase=0,
                job_type="2-Proposals Chargeable", deliverable=""),
            # Too long ago to be worth a row of the register.
            row("Ahmed Mitwally", "PE17262", D(2017, 6, 1), 6, phase=0,
                job_type="2-Proposals Chargeable", deliverable=""),
        ]
        blank.import_exports(team_exports() + [export(bids, "bids.xlsx")])
        projects = {p.number: p for p in blank.workbook.projects()}
        assert projects["Proposals 26"].status == "Active"
        assert projects["Chargeable Proposals 25"].status == "Finalized"
        assert "Chargeable Proposals 17" not in projects
        rows = {r["number"]: r for r in blank.projects()["metrics"]}
        assert rows["Proposals 26"]["actual_mm"] == pytest.approx(10 / 185, abs=1e-3)

    def test_hours_reach_the_figures(self, blank):
        blank.import_exports(team_exports())
        rows = {r["number"]: r for r in blank.projects()["metrics"]}
        assert rows["N25185-0100D"]["actual_mm"] == pytest.approx(40 / 185, abs=1e-3)


class TestRules:
    @pytest.mark.parametrize("title, grade", [
        ("Lead", "senior"), ("P3", "senior"), ("P2", "engineer"),
        ("P1", "engineer"), ("Professional", "junior"), ("BIM Modeller", "bim"),
        ("", None),
    ])
    def test_grades(self, title, grade):
        assert derive.grade_for(title) == grade

    @pytest.mark.parametrize("name, code", [
        ("Tender Documents Package SB", "TD"), ("Concept Design ST", "CD"),
        ("Preliminary Design Package SB", "CD"), ("Design Review SB", "DR"),
        ("Detailed Design - ST", "DD"), ("Phase 4 SB", "DD"),
        ("Vessel Collision - Calculations", "SA"),
    ])
    def test_types(self, name, code):
        known = ["DD", "CD", "FS", "SA", "DR", "TD", "CS", "PP", "OH"]
        assert derive.type_for(name, known) == code

    def test_short_names_are_unique(self):
        names = derive.short_names(
            ["Ahmed Mitwally", "Ahmed Hassan", "Osama Ayman"], taken=["Osama"])
        assert names == {"Ahmed Mitwally": "Ahmed M", "Ahmed Hassan": "Ahmed H",
                         "Osama Ayman": "Osama A"}

    def test_weights_always_total_one(self):
        weights = derive._round_weights([1, 1, 1])
        assert sum(weights) == pytest.approx(1.0, abs=1e-9)


class TestOverHttp:
    """The chooser's one button, and the Timesheets tab's import."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from test_server import _account, _serve
        monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "instance"))
        httpd = _serve(tmp_path / "instance")
        try:
            yield _account(httpd, f"http://127.0.0.1:{httpd.server_address[1]}")
        finally:
            httpd.app.close_all()
            httpd.shutdown()
            httpd.server_close()

    def test_a_unit_is_made_from_timesheets_alone(self, client):
        from test_server import call
        status, body = call(client, "/api/units/from-timesheets", "POST",
                            {"files": team_exports()})
        assert status == 200, body
        assert body["open"] is True
        assert body["unit"]["name"] == "Marine Structures"
        assert sorted(body["engineers"]) == ["Ahmed", "Osama"]
        assert body["projects"] == 3
        assert body["imported"]["rows_written"] == 6

    def test_a_typed_name_wins(self, client):
        from test_server import call
        status, body = call(client, "/api/units/from-timesheets", "POST",
                            {"name": "Ports", "files": team_exports()})
        assert status == 200
        assert body["unit"]["name"] == "Ports"

    def test_files_that_are_not_exports_leave_no_unit_behind(self, client):
        from test_server import call
        bad = {"filename": "notes.csv",
               "content_base64": base64.b64encode(b"a,b\n1,2\n").decode()}
        status, _body = call(client, "/api/units/from-timesheets", "POST",
                             {"files": [bad]})
        assert status == 400
        _status, units = call(client, "/api/units")
        assert units["units"] == []

    def test_the_monthly_import_adds_new_people_and_projects(self, client):
        from test_server import call
        call(client, "/api/units/from-timesheets", "POST",
             {"files": team_exports()[:1]})
        joiner = export([row("Kirolos Nazih", "AN23232-0100D", D(2026, 8, 6), 7,
                             deliverable="TENDER DOCUMENTS (SB)")])
        status, staged = call(client, "/api/timesheets/exports/stage", "POST",
                              {"files": [joiner]})
        assert status == 200
        assert staged["people"][0]["new"] is True
        assert [p["number"] for p in staged["new_projects"]] == ["AN23232-0100D"]
        status, applied = call(client, "/api/timesheets/exports/apply", "POST",
                               {"token": staged["token"]})
        assert status == 200, applied
        assert applied["people_added"] == ["Kirolos"]
        assert applied["projects_added"] == ["AN23232-0100D"]
