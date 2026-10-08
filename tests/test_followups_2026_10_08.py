"""Follow-ups the owner asked for on 2026-10-08.

Utilisation counts only up to today; dates are read day first whatever form
they come in; reports frozen on a month's last day score that month.
"""

from __future__ import annotations

import datetime as dt

from workload_app import model, reports, timesheets
from workload_app import people as ppl
from tests.test_people import book, staff, store  # noqa: F401

SUN_THU = (6, 0, 1, 2, 3)


class TestMonthSoFar:
    def test_a_month_over_is_whole_and_one_not_reached_is_nothing(self):
        assert model.month_done("2026-09", dt.date(2026, 10, 8)) == 1.0
        assert model.month_done("2026-11", dt.date(2026, 10, 8)) == 0.0

    def test_the_month_we_are_in_is_its_working_days_so_far(self):
        # October 2026, Sunday to Thursday: 21 working days, 6 of them by the 8th.
        assert model.month_done("2026-10", dt.date(2026, 10, 8), SUN_THU) == 6 / 21

    def test_the_last_day_of_the_month_is_the_whole_month(self):
        assert model.month_done("2026-10", dt.date(2026, 10, 31), SUN_THU) == 1.0


class TestUtilisationToDate:
    def test_a_full_first_week_is_a_full_load_not_a_quarter_of_one(self, store):
        staff(store, ("Ahmed", "coastal", "engineer"))
        # The first six working days of October at 8.5 h: fully loaded so far.
        days = [dt.date(2026, 10, d) for d in (1, 4, 5, 6, 7, 8)]
        store.append("Ahmed", [{"job_number": "20-1", "hours": 8.5, "date": d}
                               for d in days])
        result = ppl.balance(store, monthly_capacity=178.5,
                             today=dt.date(2026, 10, 8), work_days=SUN_THU)
        member = next(m for m in result["members"] if m["name"] == "Ahmed")
        assert member["recent_utilisation"] == 1.0

    def test_a_month_already_over_still_counts_whole(self, store):
        staff(store, ("Ahmed", "coastal", "engineer"))
        book(store, "Ahmed", [9], 185)
        result = ppl.balance(store, monthly_capacity=185.0,
                             today=dt.date(2026, 10, 8), work_days=SUN_THU)
        member = next(m for m in result["members"] if m["name"] == "Ahmed")
        assert member["utilisation"] == 1.0


class TestDayFirst:
    def test_a_date_with_a_time_is_day_first(self):
        assert timesheets._coerce_date("9/3/2026 12:00:00 AM") == dt.date(2026, 3, 9)
        assert timesheets._coerce_date("9/3/2026 00:00:00") == dt.date(2026, 3, 9)
        assert timesheets._coerce_date("9/3/2026") == dt.date(2026, 3, 9)

    def test_month_first_only_when_day_first_cannot_be(self):
        assert timesheets._coerce_date("12/31/2026") == dt.date(2026, 12, 31)
        assert model.as_date("12/31/2026") == dt.date(2026, 12, 31)

    def test_typed_dates_are_day_first_too(self):
        assert model.as_date("9/3/2026") == dt.date(2026, 3, 9)
        assert model.as_date("9/3/2026 12:00:00 AM") == dt.date(2026, 3, 9)


class TestFrozenOnAMonthsLastDay:
    def test_the_month_ending_on_the_frozen_day_is_scored(self, wb):
        wb.save_settings({"as_at": "2026-08-31"})
        months = [m["month"] for m in reports.build(wb, "year", 2026).monthly]
        assert months[-1] == "2026-08"

    def test_frozen_the_day_before_it_is_not(self, wb):
        wb.save_settings({"as_at": "2026-08-30"})
        months = [m["month"] for m in reports.build(wb, "year", 2026).monthly]
        assert months[-1] == "2026-07"


class TestMonthFirstFiles:
    def test_a_file_with_a_date_only_month_first_can_be_is_month_first(self):
        assert timesheets.month_first(["9/3/2026", "3/25/2026 12:00:00 AM"])
        assert not timesheets.month_first(["9/3/2026", "25/3/2026"])
        assert not timesheets.month_first(["9/3/2026", "10/4/2026"])
        assert not timesheets.month_first([dt.date(2026, 3, 9), None, ""])

    def test_a_month_first_export_is_converted(self):
        import io
        import openpyxl
        from workload_app import config as cfg
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(["JobNumber", "FullName", "Date", "TotalHours"])
        sheet.append(["J-1", "Pat", "9/3/2026 12:00:00 AM", 8])
        sheet.append(["J-1", "Pat", "9/25/2026 12:00:00 AM", 8])
        buffer = io.BytesIO()
        book.save(buffer)
        parsed = timesheets.parse("Pat", "e.xlsx", buffer.getvalue(), cfg.TS_HEADERS)
        assert sorted(r["date"] for r in parsed.records()) == [
            dt.date(2026, 9, 3), dt.date(2026, 9, 25)]

    def test_a_day_first_export_stays_day_first(self):
        csv = ("JobNumber,FullName,Date,TotalHours\r\n"
               "J-1,Pat,9/3/2026,8\r\nJ-1,Pat,25/3/2026,8\r\n").encode()
        from workload_app import config as cfg
        parsed = timesheets.parse("Pat", "e.csv", csv, cfg.TS_HEADERS)
        assert sorted(r["date"] for r in parsed.records()) == [
            dt.date(2026, 3, 9), dt.date(2026, 3, 25)]

    def test_a_month_first_drawing_list_is_converted(self):
        from workload_app import drawing_list
        rows = drawing_list._rows(
            [["J-1", "D-001", "9/3/2026"], ["J-1", "D-002", "9/25/2026"]],
            {"job_number": 0, "number": 1, "issued": 2})
        assert [r["issued"] for r in rows] == [dt.date(2026, 9, 3), dt.date(2026, 9, 25)]
