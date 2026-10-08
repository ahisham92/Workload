"""Bugs found in the data review: uploads, budgets, the drawing list, the
spreadsheet written out, and renaming somebody.  Made-up people and jobs."""

import base64
import datetime as dt
import io

import pytest

from test_budgets import (JOB, PROJECT_HEADERS, UNDERLYING_HEADERS, job, project,
                          projects_list, sheet, staff, staff_list, unit)  # noqa: F401
from test_from_timesheets import D
from workload_app import config as cfg, drawing_list, export, storage, timesheets
from workload_app.timesheet_store import TimesheetStore
from workload_app.unit import Unit

openpyxl = pytest.importorskip("openpyxl")


def _export(rows):
    book = openpyxl.Workbook()
    ws = book.active
    headers = ["Job Type", "JobNumber", "FullName", "Date", "Phase", "TotalHours"]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _row(**overrides):
    row = {"Job Type": "1-Projects", "JobNumber": "T10001-0100D",
           "FullName": "Ahmed Mockridge", "Date": dt.date(2026, 9, 1),
           "Phase": 4, "TotalHours": 8}
    row.update(overrides)
    return row


class TestDatesInAnExport:
    def test_a_number_no_date_has_is_a_row_without_a_date_not_a_crash(self):
        data = _export([_row(), _row(Date=20260903)])
        parsed = timesheets.parse("", "export.xlsx", data, cfg.TS_HEADERS)
        assert parsed.ok
        assert parsed.summary["rows_without_date"] == 1

    def test_a_serial_saved_as_text_is_a_date(self):
        text = "JobNumber,FullName,Date,TotalHours\nT10001-0100D,Ahmed Mockridge,46268,8\n"
        parsed = timesheets.parse("", "export.csv", text.encode(), cfg.TS_HEADERS)
        assert parsed.records()[0]["date"] == dt.date(2026, 9, 3)


def _decoded(item):
    return base64.b64decode(item["content_base64"])


class TestBudgetUploads:
    def test_the_underlying_data_export_keeps_the_budget_already_held(self, unit):
        unit.import_budgets([projects_list(project(JOB, 10.0, 4.0))])
        assert job(unit)["budget_mm"] == 10.0
        underlying = sheet(UNDERLYING_HEADERS, [{
            "JobNumber": JOB, "Title": "Quay wall", "'Jobs'[Status]": "Active",
            "Spent MM": 4.5, "Remaining Workload": 0.5,
            "RequiresAdditionEffort": False, "MappedDepartmentABR": "XB"}], "data.xlsx")
        unit.import_budgets([underlying])
        item = job(unit)
        assert item["budget_mm"] == 10.0
        assert item["spent_mm"] == 4.5

    def test_the_same_staff_list_twice_in_one_go_is_not_counted_twice(self, unit):
        one = staff_list(staff("Osama Ashdown", D(2026, 9, 10), 8),
                         staff("Draft Person", D(2026, 9, 13), 37,
                               unit="CONCRETE BUILDINGS"))
        unit.import_budgets([one])
        once = job(unit)
        spend = sum(e["mm"] for e in unit.store.job_spend())
        again = staff_list(staff("Osama Ashdown", D(2026, 9, 10), 8),
                           staff("Draft Person", D(2026, 9, 13), 37,
                                 unit="CONCRETE BUILDINGS"),
                           filename="Staff expenditure (1).xlsx")
        unit.import_budgets([one, again])
        assert sum(e["mm"] for e in unit.store.job_spend()) == pytest.approx(spend)
        assert job(unit)["team_spent_mm"] == once["team_spent_mm"]


class TestTheDrawingList:
    def test_not_issued_is_not_sent(self):
        book = openpyxl.Workbook()
        ws = book.active
        ws.append(["Job Number", "Deliverable", "Drawing No.", "Status"])
        ws.append(["T10001-0100D", "Detailed Design", "D-001", "Not issued"])
        ws.append(["T10001-0100D", "Detailed Design", "D-002", "To be issued"])
        ws.append(["T10001-0100D", "Detailed Design", "D-003", "IFC"])
        out = io.BytesIO()
        book.save(out)
        rows = drawing_list.read(out.getvalue(), "list.xlsx")
        assert [r["sent"] for r in rows] == [False, False, True]


class TestTheSpreadsheetWrittenOut:
    def test_time_away_is_written_as_dates(self, tmp_path):
        wb = Unit(storage.new_unit(tmp_path, 1, "unit-one"))
        wb.store.add_absence("Osama", "2026-09-01", "2026-09-03", "Leave")
        book = openpyxl.load_workbook(io.BytesIO(export.unit_workbook(wb)))
        row = list(book["Time away"].iter_rows(min_row=2, values_only=True))[0]
        assert row[0] == "Osama"
        assert row[1].date() == dt.date(2026, 9, 1)
        assert row[2].date() == dt.date(2026, 9, 3)


class TestRenamingSomebody:
    def test_the_weeks_plans_follow_the_new_name(self, tmp_path):
        store = TimesheetStore(tmp_path / "unit.db")
        store.lock_week("2026-09-06", [{"person": "Osama", "kind": "job",
                                        "job_number": JOB, "hours": 20}])
        line = store.week_plan("2026-09-06")[0]
        store.set_slip_reason(line["id"], "waiting", "", "Osama")
        store.rename_person_everywhere("Osama", "Osama A")
        (line,) = store.week_plan("2026-09-06")
        assert line["person"] == "Osama A" and line["reason_by"] == "Osama A"
