"""Budgets: BISpark's Projects list and each job's staff expenditure.

Made-up people and job numbers throughout; like test_from_timesheets these
start from a unit set up from synthetic exports, so no private workbook.
"""

import base64
import io
import json
import zipfile

import pytest

from test_from_timesheets import D, team_exports
from workload_app import budgets, derive, storage
from workload_app.service import ApiError, WorkloadService

openpyxl = pytest.importorskip("openpyxl")

JOB = "T10001-0100D"
OTHER_JOB = "T10003-0100D"

PROJECT_HEADERS = ["Number", "Title", "Lead", "PDs", "PMs", "Status",
                   "Budget MM", "Spent MM", "Budget Variance",
                   "Remaining Workload", "EAC", "Progress", "EV", "Start", "End"]

UNDERLYING_HEADERS = [".", "Title", "Lead", "'Jobs'[Status]", "Spent MM",
                      "Remaining Workload", "Start Date", "End Date",
                      "RequiresAdditionEffort", "MappedDepartmentABR",
                      "JobNumber"]

STAFF_HEADERS = ["Dept", "Office", "Employee Name", "MM Spent", "JobNumber",
                 "RegularHours", "OvertimeHours", "Date", "Phase",
                 "TotalHours", "Grade", "BudgetedDeptABR", "CurrentUnitDesc",
                 "JobStatus", "DeliverableDescription"]


def sheet(headers, rows, filename, title="Applied filters:\nJob Type is 1-Projects"):
    book = openpyxl.Workbook()
    ws = book.active
    ws.append([title])
    ws.append([])
    ws.append(headers)
    for item in rows:
        ws.append([item.get(h) for h in headers])
    buffer = io.BytesIO()
    book.save(buffer)
    return {"filename": filename,
            "content_base64": base64.b64encode(buffer.getvalue()).decode()}


def project(number, budget, spent, *, status="Active", end="12/31/2026",
            title="Quay wall"):
    return {"Number": number, "Title": title, "Lead": "XX", "Status": status,
            "Budget MM": budget, "Spent MM": spent,
            "Budget Variance": budget - spent, "Remaining Workload": 1.0,
            "EAC": spent + 1, "Progress": "50.00 %", "EV": budget / 2,
            "Start": "1/1/2026", "End": end}


def projects_list(*rows, filename="projects.xlsx"):
    return sheet(PROJECT_HEADERS, rows, filename)


def staff(name, day, hours, *, unit="MARINE STRUCTURES", job=JOB, phase=4,
          overtime=0):
    return {"Dept": "XB", "Office": "Cairo", "Employee Name": name,
            "MM Spent": round(hours / 185, 4), "JobNumber": job,
            "RegularHours": hours - overtime, "OvertimeHours": overtime,
            "Date": day, "Phase": phase, "TotalHours": hours,
            "Grade": "Professional", "BudgetedDeptABR": "XB",
            "CurrentUnitDesc": unit, "JobStatus": "Active",
            "DeliverableDescription": "Detailed Design ST"}


def staff_list(*rows, filename="Staff expenditure.xlsx"):
    return sheet(STAFF_HEADERS, rows, filename,
                 title=f"Applied filters:\nJobNumber is {JOB}")


#: Osama's own export has 24 h on 4 Aug; the staff list also has two days
#: his own export never showed, and people from two other units.
def the_staff_list():
    return staff_list(
        staff("Osama Ashdown", D(2026, 8, 4), 24),
        staff("Osama Ashdown", D(2026, 9, 10), 8),
        staff("Osama Ashdown", D(2026, 9, 11), 6, overtime=2),
        staff("Ahmed Mockridge", D(2026, 9, 12), 8),
        staff("Ahmed Otherunit", D(2026, 9, 12), 37, unit="STEEL STRUCTURES"),
        staff("Draft Person", D(2026, 9, 13), 37, unit="CONCRETE BUILDINGS"),
    )


@pytest.fixture
def unit(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", "2026-10-01")
    service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
    service.import_exports(team_exports())
    return service


def job(service, number=JOB):
    return next(j for j in service.budgets()["jobs"] if j["job_number"] == number)


class TestReadingTheExports:
    def test_the_summarized_projects_list_carries_the_budget(self):
        data = projects_list(project(JOB, 10.0, 4.0))
        parsed = budgets.parse("p.xlsx", base64.b64decode(data["content_base64"]))
        assert parsed["kind"] == "projects" and parsed["has_budget"]
        (item,) = parsed["jobs"]
        assert item["budget_mm"] == 10.0 and item["spent_mm"] == 4.0
        assert item["progress"] == pytest.approx(0.5)
        assert item["end"] == "2026-12-31"

    def test_the_underlying_data_is_added_up_per_job(self):
        rows = [{"JobNumber": JOB, "Title": "Quay wall", "'Jobs'[Status]": "Active",
                 "Spent MM": spent, "Remaining Workload": 0.5,
                 "RequiresAdditionEffort": flag, "MappedDepartmentABR": "XB",
                 ".": "https://reports.example.com/x"}
                for spent, flag in ((1.0, False), (2.5, True))]
        data = sheet(UNDERLYING_HEADERS, rows, "data.xlsx")
        parsed = budgets.parse("data.xlsx", base64.b64decode(data["content_base64"]))
        assert parsed["has_budget"] is False
        (item,) = parsed["jobs"]
        assert item["spent_mm"] == 3.5 and item["remaining_mm"] == 1.0
        assert item["needs_more"] == 1 and item["dept"] == "XB"
        assert item["budget_mm"] is None

    def test_a_staff_list_is_told_apart(self):
        data = the_staff_list()
        parsed = budgets.parse("s.xlsx", base64.b64decode(data["content_base64"]))
        assert parsed["kind"] == "spend"
        assert {r["name"] for r in parsed["rows"]} >= {"Osama Ashdown", "Draft Person"}
        assert "office" not in parsed["rows"][0]

    def test_a_timesheet_export_is_sent_to_the_timesheets_tab(self, unit):
        with pytest.raises(ApiError) as caught:
            unit.import_budgets([team_exports()[0]])
        assert "Timesheets tab" in " ".join(caught.value.errors)


class TestTheTeamsShare:
    def test_the_share_comes_from_who_booked_the_hours(self, unit):
        unit.import_budgets([projects_list(project(JOB, 10.0, 4.0)), the_staff_list()])
        item = job(unit)
        mine = (24 + 8 + 6 + 8) / 185
        assert item["share_basis"] == "booked"
        assert item["share"] == pytest.approx(mine / (mine + 74 / 185), abs=1e-3)
        assert item["team_spent_mm"] == pytest.approx(mine, abs=0.01)
        assert item["other_units_mm"] == pytest.approx(74 / 185, abs=0.01)
        assert item["team_budget_mm"] == pytest.approx(10 * item["share"], abs=0.01)
        assert {p["name"] for p in item["people"]} == {"Osama Ashdown", "Ahmed Mockridge"}

    def test_a_namesake_from_another_unit_is_not_the_team(self, unit):
        unit.import_budgets([the_staff_list()])
        people = {p["name"]: p for p in unit.budgets()["people"]}
        assert people["Ahmed Otherunit"]["kind"] == "other"
        assert people["Ahmed Mockridge"]["kind"] == "team"

    def test_the_manager_can_set_it(self, unit):
        unit.import_budgets([projects_list(project(JOB, 10.0, 4.0)), the_staff_list()])
        unit.set_budget_share(JOB, {"share_percent": 60})
        assert job(unit)["share"] == 0.6 and job(unit)["team_budget_mm"] == 6.0
        unit.set_budget_share(JOB, {"share_percent": ""})
        assert job(unit)["share_basis"] == "booked"

    def test_a_share_out_of_range_is_refused(self, unit):
        with pytest.raises(ApiError):
            unit.set_budget_share(JOB, {"share_percent": 140})

    def test_without_a_staff_list_the_team_is_all_of_it(self, unit):
        unit.import_budgets([projects_list(project(OTHER_JOB, 3.0, 1.0))])
        item = job(unit, OTHER_JOB)
        assert item["share_basis"] == "unknown" and item["share"] == 1.0
        assert item["spent_from"] == "timesheets"
        assert any("Set your share" in t["text"] for t in unit.budgets()["todo"])


class TestPeopleOnTheJobs:
    def test_a_draftsman_from_another_unit_counts(self, unit):
        unit.import_budgets([the_staff_list()])
        before = job(unit)["team_spent_mm"]
        unit.set_budget_person({"full_name": "Draft Person",
                                "unit": "CONCRETE BUILDINGS", "kind": "draftsman"})
        assert job(unit)["team_spent_mm"] == pytest.approx(before + 37 / 185, abs=0.01)

    def test_a_loan_counts_only_for_its_dates(self, unit):
        unit.import_budgets([the_staff_list()])
        before = job(unit)["team_spent_mm"]
        unit.set_budget_person({"full_name": "Ahmed Otherunit", "unit": "STEEL STRUCTURES",
                                "kind": "loan", "from": "2026-09-13", "to": "2026-12-31"})
        assert job(unit)["team_spent_mm"] == pytest.approx(before, abs=0.001)
        unit.set_budget_person({"full_name": "Ahmed Otherunit", "unit": "STEEL STRUCTURES",
                                "kind": "loan", "from": "2026-09-01", "to": "2026-12-31"})
        assert job(unit)["team_spent_mm"] == pytest.approx(before + 37 / 185, abs=0.01)

    def test_somebody_who_left_counts_to_the_day_they_left(self, unit):
        unit.import_budgets([the_staff_list()])
        unit.set_budget_person({"full_name": "Osama Ashdown", "unit": "MARINE STRUCTURES",
                                "kind": "left", "to": "2026-09-10"})
        assert job(unit)["team_spent_mm"] == pytest.approx((24 + 8 + 8) / 185, abs=0.01)

    def test_left_needs_the_day(self, unit):
        unit.import_budgets([the_staff_list()])
        with pytest.raises(ApiError):
            unit.set_budget_person({"full_name": "Osama Ashdown",
                                    "unit": "MARINE STRUCTURES", "kind": "left"})

    def test_people_outside_the_team_keep_only_a_name_unit_and_hours(self, unit):
        unit.import_budgets([the_staff_list()])
        entry = next(e for e in unit.store.job_spend() if e["full_name"] == "Draft Person")
        assert set(entry) == {"job_number", "full_name", "unit", "dept", "day", "phase",
                              "deliverable", "hours", "overtime", "mm", "imported_at"}


class TestFillingTheTeamsDays:
    def test_missing_days_are_filled_and_own_rows_kept(self, unit):
        own = [dict(r) for r in unit.store.rows_for("Osama")]
        unit.import_budgets([the_staff_list()])
        rows = unit.store.rows_for("Osama")
        days = sorted(r["date"].isoformat() for r in rows if r["job_number"] == JOB)
        assert days == ["2026-08-04", "2026-09-10", "2026-09-11"]
        for before in own:
            assert before in [dict(r) for r in rows]
        added = [r for r in rows if r["date"] == D(2026, 9, 11)][0]
        assert added["overtime_hours"] == 2 and added["hours"] == 6

    def test_a_second_import_never_doubles_them(self, unit):
        unit.import_budgets([the_staff_list()])
        count = unit.store.count()
        unit.import_budgets([the_staff_list()])
        assert unit.store.count() == count

    def test_nobody_outside_the_team_gets_rows(self, unit):
        unit.import_budgets([the_staff_list()])
        assert set(unit.store.people_with_rows()) == {"Ahmed", "Osama"}

    def test_a_much_smaller_staff_list_is_not_taken(self, unit):
        unit.import_budgets([the_staff_list()])
        result = unit.import_budgets([staff_list(staff("Osama Ashdown", D(2026, 8, 4), 2))])
        assert result["kept"] == [JOB]
        assert job(unit)["team_spent_mm"] > 0.2

    def test_the_nightly_guard_counts_only_own_rows(self, unit):
        held = unit.store.counts()
        unit.import_budgets([the_staff_list()])
        assert unit.store.counts(without_source=budgets.SPEND_SOURCE) == held
        assert unit.store.counts()["Osama"] > held["Osama"]


class TestFinishedJobs:
    def test_a_job_that_drops_off_the_list_is_kept_as_closed(self, unit):
        unit.import_budgets([projects_list(project(JOB, 10.0, 4.0),
                                           project(OTHER_JOB, 3.0, 1.0)),
                             the_staff_list()])
        unit.import_budgets([projects_list(project(OTHER_JOB, 3.0, 1.5))])
        item = job(unit)
        assert item["state"] == "closed" and item["listed"] is False
        assert item["budget_mm"] == 10.0 and item["team_spent_mm"] > 0
        assert item["last_seen"]
        assert unit.budgets()["totals"]["closed"] == 1
        assert budgets.jobs_to_fetch(unit) == [OTHER_JOB]


class TestTheProjectsTab:
    def test_a_project_set_up_from_timesheets_takes_the_teams_budget(self, unit):
        assert derive.needs_confirming(unit.workbook.project(JOB).notes)
        result = unit.import_budgets([projects_list(project(JOB, 10.0, 4.0)),
                                      the_staff_list()])
        assert result["projects_updated"] == [JOB]
        share = job(unit)["share"]
        assert unit.workbook.project(JOB).budget_mm == pytest.approx(round(10 * share, 2))
        unit.set_budget_share(JOB, {"share_percent": 50})
        assert unit.workbook.project(JOB).budget_mm == 5.0
        assert job(unit)["follows_bispark"] is True

    def test_a_budget_typed_by_hand_is_left_alone(self, unit):
        p = unit.workbook.project(JOB)
        unit.update_project(JOB, {**p.to_dict(), "budget_mm": 7.5, "notes": ""})
        unit.import_budgets([projects_list(project(JOB, 10.0, 4.0))])
        assert unit.workbook.project(JOB).budget_mm == 7.5
        assert any("typed by hand" in t["text"] for t in unit.budgets()["todo"])


class TestRunningOut:
    def test_over_budget_comes_first(self, unit):
        unit.import_budgets([projects_list(project(JOB, 0.1, 4.0),
                                           project(OTHER_JOB, 3.0, 1.0)),
                             the_staff_list()])
        view = unit.budgets()
        assert view["jobs"][0]["job_number"] == JOB
        assert view["jobs"][0]["state"] == "over"
        assert view["todo"][0]["level"] == "now"

    def test_a_job_spending_too_fast_runs_out_before_its_end(self, unit):
        unit.import_budgets([projects_list(project(JOB, 0.5, 0.2, end="12/31/2027")),
                             the_staff_list()])
        unit.set_budget_share(JOB, {"share_percent": 100})
        item = job(unit)
        assert item["state"] == "short"
        assert item["runs_out"] < "2027-12-31"


#: Copy as PowerShell of the staff expenditure export, cut down, made-up server.
SPEND_CAPTURE = (
    'Invoke-WebRequest -UseBasicParsing -Uri "https://bi.example.com/powerbi/api/explore/reports/abc/export/xlsx" `\n'
    '-Method "POST" `\n'
    '-Body "{`"filter`":`"JobNumber eq \'T10001-0100D\'`",`"again`":`"T10001-0100D`"}"')
PROJECTS_CAPTURE = SPEND_CAPTURE.replace("T10001-0100D", "all")


class TestTheRequests:
    def test_the_job_number_becomes_a_slot(self, unit):
        from workload_app import nightly
        info = unit.save_budget_requests({"spend_capture": SPEND_CAPTURE,
                                          "projects_capture": PROJECTS_CAPTURE},
                                         nightly.parse_capture)
        assert info == {"projects": True, "spend": True, "spend_job": JOB}
        held = budgets.requests(unit)
        assert JOB not in held["spend"]["body"]
        assert held["spend"]["body"].count(budgets.JOB_SLOT) == 2

    def test_a_request_without_one_job_is_refused(self, unit):
        from workload_app import nightly
        with pytest.raises(ApiError):
            unit.save_budget_requests({"spend_capture": PROJECTS_CAPTURE},
                                      nightly.parse_capture)


# -------------------------------------------------------------- over the web

@pytest.fixture
def client(tmp_path, monkeypatch):
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


class TestOverTheWeb:
    def setup_kit(self, client):
        from test_nightly import call, make_kit, make_unit
        make_unit(client)
        status, body = call(client, "/api/budgets/requests", "PUT",
                            {"projects_capture": PROJECTS_CAPTURE,
                             "spend_capture": SPEND_CAPTURE})
        assert status == 200, body
        return make_kit(client)

    def test_the_manager_kit_carries_both_requests(self, client):
        _key, archive, _ini = self.setup_kit(client)
        held = json.loads(archive.read("selecao-nightly/budgets.json"))
        assert set(held) == {"projects", "spend"}
        script = archive.read("selecao-nightly/nightly.ps1").decode()
        assert "'{{JOB}}'" in script and "$mostStaffLists = 40" in script

    def test_the_team_kit_has_no_budgets(self, client):
        from test_nightly import call
        self.setup_kit(client)
        status, body = call(client, "/api/import-key/team-kit", "POST", {})
        assert status == 200
        archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(body["kit_base64"])))
        assert "selecao-nightly/budgets.json" not in archive.namelist()

    def test_the_night_brings_the_list_then_the_staff(self, client):
        from test_nightly import anonymous, call
        key, _archive, _ini = self.setup_kit(client)
        status, body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                            {"key": key, "kind": "budgets",
                             "files": [projects_list(project(JOB, 10.0, 4.0))]})
        assert status == 200, body
        assert body["jobs"] == [JOB]
        status, body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                            {"key": key, "kind": "spend", "files": [the_staff_list()]})
        assert status == 200, body
        assert body["spend_jobs"] == [JOB] and body["rows_filled"] > 0
        status, view = call(client, "/api/budgets")
        assert status == 200
        assert next(j for j in view["jobs"] if j["job_number"] == JOB)["share_basis"] == "booked"

    def test_a_failed_budgets_step_leaves_the_timesheet_status(self, client):
        from test_nightly import anonymous, call, tonight
        key, _archive, _ini = self.setup_kit(client)
        call(anonymous(client), "/api/nightly/timesheets", "POST",
             {"key": key, "files": [tonight()]})
        status, _body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                             {"key": key, "kind": "budgets", "files": [the_staff_list()]})
        assert status == 400
        _status, info = call(client, "/api/import-key")
        assert info["key"]["last_result"]["ok"] is True

    def test_people_and_shares_are_set_over_the_web(self, client):
        from test_nightly import call, make_unit
        make_unit(client)
        status, _ = call(client, "/api/budgets/import", "POST",
                         {"files": [projects_list(project(JOB, 10.0, 4.0)), the_staff_list()]})
        assert status == 200
        status, view = call(client, f"/api/budgets/jobs/{JOB}", "PUT", {"share_percent": 40})
        assert status == 200
        assert next(j for j in view["jobs"] if j["job_number"] == JOB)["share"] == 0.4
        status, view = call(client, "/api/budgets/people", "PUT",
                            {"full_name": "Draft Person", "unit": "CONCRETE BUILDINGS",
                             "kind": "draftsman"})
        assert status == 200
        assert {p["name"]: p["kind"] for p in view["people"]}["Draft Person"] == "draftsman"
