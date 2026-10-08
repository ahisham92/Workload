"""Round 3 bug hunt, imports: messy exports, budgets, the drawing list and
the spreadsheet written out.  Made-up people and job numbers throughout."""

from __future__ import annotations

import datetime as dt
import io
from types import SimpleNamespace

import pytest

from test_budgets import JOB, job, project, projects_list, staff, staff_list, unit  # noqa: F401
from test_from_timesheets import D, blank, export, row  # noqa: F401
from workload_app import config as cfg, drawing_list, drawings, timesheets
from workload_app import export as export_module

openpyxl = pytest.importorskip("openpyxl")

HEAD = "Job Type{d}JobNumber{d}FullName{d}Date{d}TotalHours"
LINE = "1-Projects{d}T10001-0100D{d}Ahmed Mockridge{d}{day}{d}8"


def _text_export(delimiter: str, title: str) -> str:
    lines = [title, "", HEAD.format(d=delimiter),
             LINE.format(d=delimiter, day="09/03/2026"),
             LINE.format(d=delimiter, day="10/03/2026")]
    return "\r\n".join(lines) + "\r\n"


class TestMessyTimesheetExports:
    def test_a_total_line_under_the_table_is_not_counted(self, blank):
        rows = [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8),
                row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 3), 8),
                {"Job Type": "Total", "RegularHours": 16, "TotalHours": 16}]
        staged = blank.stage_exports([export(rows)])
        assert staged["hours"] == 16
        assert [p["full_name"] for p in staged["people"]] == ["Ahmed Mockridge"]

    def test_a_grand_total_in_the_job_column_is_not_counted(self):
        text = _text_export(",", "Timesheet") + ",Grand Total,,,16\r\n"
        parsed = timesheets.parse("", "e.csv", text.encode(), cfg.TS_HEADERS)
        assert sum(r["hours"] for r in parsed.records()) == 16

    def test_unicode_text_with_a_title_line_is_read(self):
        # Excel's "Unicode text": UTF-16, tab between columns.
        data = _text_export("\t", "Timesheet export").encode("utf-16")
        parsed = timesheets.parse("", "e.txt", data, cfg.TS_HEADERS)
        assert parsed.errors == []
        assert [r["date"] for r in parsed.records()] == [D(2026, 3, 9), D(2026, 3, 10)]

    def test_a_semicolon_file_with_a_title_line_is_read(self):
        data = _text_export(";", "Timesheet export;;").encode("utf-8-sig")
        parsed = timesheets.parse("", "e.csv", data, cfg.TS_HEADERS)
        assert len(parsed.records()) == 2

    def test_a_two_digit_year_is_a_date_read_day_first(self):
        assert timesheets._coerce_date("08/10/26") == D(2026, 10, 8)
        assert timesheets._coerce_date("10/25/26", month_first=True) == D(2026, 10, 25)


class TestBudgets:
    def test_a_trickle_against_a_big_budget_does_not_stop_the_import(self, unit):
        unit.import_budgets([projects_list(project(JOB, 120.0, 0.1)),
                             staff_list(staff("Osama Ashdown", D(2026, 9, 10), 0.5))])
        item = job(unit)
        assert item["runs_out"] is None and item["state"] == "ok"


class TestDrawingList:
    def test_dates_written_with_a_time_are_read(self):
        rows = drawing_list._rows(
            [["J-1", "D-001", "9/3/2026 12:00:00 AM"],
             ["J-1", "D-002", "2026-03-10T00:00:00"],
             ["J-1", "D-003", 46091]],
            {"job_number": 0, "number": 1, "issued": 2})
        assert [r["issued"] for r in rows] == [D(2026, 3, 9), D(2026, 3, 10),
                                              D(2026, 3, 10)]

    @pytest.mark.parametrize("written, code", [
        ("Code B - Approved with comments", "B"), ("Approved with comments", "B"),
        ("Approved as noted", "B"), ("Code: C", "C"), ("A", "A"), ("2", "B"),
        ("Approved", "A"), ("Rejected", "C")])
    def test_the_return_code_is_read_as_written(self, written, code):
        rows = drawing_list._rows([["J-1", "D-001", written]],
                                  {"job_number": 0, "number": 1, "code": 2})
        assert rows[0]["code"] == code

    def test_a_drawing_listed_once_per_revision_counts_once(self):
        rows = drawing_list._rows(
            [["J-1", "D-001", "0", "IFA", "C"],
             ["J-1", "D-001", "1", "IFA", ""],
             ["J-1", "D-002", "0", "In progress", ""]],
            {"job_number": 0, "number": 1, "revision": 2, "status": 3, "code": 4})
        deliverable = SimpleNamespace(row=7, project_number="J-1", name="Piles",
                                      ts_phase=1)
        matched = drawing_list.match(rows, [deliverable])
        entry = matched["deliverables"][0]
        assert (entry["total"], entry["issued"], entry["code_c"]) == (2, 1, 0)


class TestDrawingCounts:
    @pytest.mark.parametrize("value", ["nan", "inf", "1e999"])
    def test_a_count_that_is_no_number_is_refused(self, value):
        with pytest.raises(drawings.DrawingsError):
            drawings.clean_count(value)


class TestTheSpreadsheetWrittenOut:
    def test_first_and_last_charge_are_dates_shown_day_first(self, blank):
        blank.import_exports([export(
            [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8),
             row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 13), 8)])])
        data = export_module.unit_workbook(blank.workbook, "Marine Structures")
        sheet = openpyxl.load_workbook(io.BytesIO(data))["Projects"]
        headers = [c.value for c in sheet[1]]
        first = sheet.cell(2, headers.index("First charge") + 1)
        last = sheet.cell(2, headers.index("Last charge") + 1)
        assert first.value == dt.datetime(2026, 8, 2)
        assert last.value == dt.datetime(2026, 8, 13)
        assert first.number_format == "dd/mm/yyyy"


class TestTheTeamsShare:
    def test_hours_booked_to_another_departments_budget_are_not_a_share_of_this_one(
            self, unit):
        other_dept = staff("Osama Ashdown", D(2026, 9, 10), 80)
        other_dept["BudgetedDeptABR"] = other_dept["Dept"] = "YY"
        unit.import_budgets([staff_list(
            staff("Osama Ashdown", D(2026, 9, 11), 10),
            staff("Kirolos Otherunit", D(2026, 9, 11), 30, unit="STEEL STRUCTURES"),
            other_dept)])
        item = job(unit)
        assert item["dept"] == "XB"
        assert item["share"] == pytest.approx(0.25, abs=0.001)
