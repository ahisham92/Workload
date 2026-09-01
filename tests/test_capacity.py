"""The two row caps on the consolidated timesheet.

These are the limits that made an engineer's hours disappear: the workbook
reads ``Timesheet Raw`` rows 4:8000 and nothing warns you when the three sheets
together hold more than that.
"""

import re
import zipfile
import xml.etree.ElementTree as ET

import pytest

from workload_app import capacity, config as cfg
from workload_app.workbook import ValidationError, WorkloadWorkbook


class TestDetection:
    def test_both_caps_are_read_from_the_workbook(self, raw):
        assert capacity.source_limit(raw) == 6000
        assert capacity.raw_limit(raw) == 8000

    def test_the_report_measures_what_is_used(self, readonly_wb):
        report = readonly_wb.timesheet_capacity()
        assert report["total_capacity"] == 7997
        assert report["rows_used"] == 7682
        assert report["headroom"] == 315
        assert report["over_capacity"] is False
        assert report["low_headroom"] is True

    def test_rows_are_counted_per_engineer_in_stack_order(self, readonly_wb):
        report = readonly_wb.timesheet_capacity()
        assert report["stack_order"] == ["Ahmed", "Osama", "Kirolos"]
        assert report["per_sheet"]["Ahmed"]["rows"] == 5822


class TestOverflow:
    """Whose rows fall off the end, and does anyone say so."""

    def test_the_last_engineer_in_the_stack_loses_the_rows(self, raw):
        report = capacity.report(
            raw, {"Ahmed": 5000, "Osama": 2000, "Kirolos": 1500})
        assert report["over_capacity"] is True
        assert [c["engineer"] for c in report["cut_off"]] == ["Kirolos"]
        assert report["cut_off"][0]["rows_lost"] == 8500 - 7997

    def test_an_earlier_engineer_can_be_cut_too_once_it_is_bad_enough(self, raw):
        report = capacity.report(
            raw, {"Ahmed": 7900, "Osama": 500, "Kirolos": 500})
        assert [c["engineer"] for c in report["cut_off"]] == ["Osama", "Kirolos"]
        assert report["cut_off"][-1]["rows_lost"] == 500

    def test_overflow_is_reported_as_an_error_naming_the_engineer(self, raw):
        report = capacity.report(
            raw, {"Ahmed": 5000, "Osama": 2000, "Kirolos": 1500})
        messages = capacity.messages(report)
        assert messages[0]["level"] == "error"
        assert "Kirolos" in messages[0]["message"]
        assert "reach nothing" in messages[0]["message"]

    def test_a_near_miss_is_reported_as_a_warning(self, readonly_wb):
        messages = readonly_wb.capacity_messages()
        assert messages
        assert messages[0]["level"] == "warning"
        assert "315 rows left" in messages[0]["message"]

    def test_plenty_of_room_says_nothing(self, raw):
        report = capacity.report(raw, {"Ahmed": 100, "Osama": 100, "Kirolos": 100})
        assert capacity.messages(report) == []

    def test_a_full_single_sheet_is_reported_separately(self, raw):
        report = capacity.report(raw, {"Ahmed": 6100, "Osama": 10, "Kirolos": 10})
        assert report["per_sheet"]["Ahmed"]["over"] is True
        assert any("TS Ahmed holds" in m["message"] for m in capacity.messages(report))

    def test_the_suggestion_leaves_years_of_headroom(self, readonly_wb):
        report = readonly_wb.timesheet_capacity()
        assert report["suggested_raw_last_row"] == 12000
        assert report["suggested_raw_last_row"] > report["raw_last_row"]


class TestExtending:
    def _counts(self, wb):
        return wb.timesheet_capacity()

    def test_it_raises_both_caps(self, wb):
        wb.extend_timesheet_capacity(raw_last_row=12000, source_last_row=9000)
        report = self._counts(wb)
        assert report["raw_last_row"] == 12000
        assert report["source_last_row"] == 9000
        assert report["headroom"] == 11997 - 7682

    def test_every_consumer_is_repointed_and_none_is_left_behind(self, wb, workbook_copy):
        wb.extend_timesheet_capacity(raw_last_row=12000)
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.load_workbook(workbook_copy)
        stale = 0
        updated = 0
        for sheet in book.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    value = cell.value
                    value = value.text if hasattr(value, "text") else value
                    if not isinstance(value, str) or not value.startswith("="):
                        continue
                    for end in re.findall(
                        r"'?Timesheet Raw'?!\$?[A-Z]{1,2}\$?4:\$?[A-Z]{1,2}\$?(\d+)",
                        value,
                    ):
                        if end == "12000":
                            updated += 1
                        else:
                            stale += 1
        assert stale == 0
        assert updated > 50000

    def test_the_helper_columns_reach_the_new_last_row(self, wb, workbook_copy):
        wb.extend_timesheet_capacity(raw_last_row=9000)
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        sheet = openpyxl.load_workbook(workbook_copy)["Timesheet Raw"]
        for col in cfg.TS_RAW_HELPER_COLUMNS:
            assert sheet[f"{col}9000"].value, col
        assert "$L9000" in str(sheet["BU9000"].value)

    def test_the_vstack_reads_further_down_each_sheet(self, wb, workbook_copy):
        wb.extend_timesheet_capacity(raw_last_row=12000, source_last_row=9000)
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        formula = openpyxl.load_workbook(workbook_copy)["Timesheet Raw"]["A4"].value
        text = formula.text if hasattr(formula, "text") else formula
        assert "'TS Ahmed'!$A$4:$P$9000" in text
        assert "$P$6000" not in text

    def test_the_workbook_is_still_sound_afterwards(self, wb, workbook_copy):
        wb.extend_timesheet_capacity(raw_last_row=9000)
        wb.save()
        with zipfile.ZipFile(workbook_copy) as zf:
            for name in zf.namelist():
                if name.endswith(".xml"):
                    ET.fromstring(zf.read(name))
            assert "xl/calcChain.xml" not in zf.namelist()
            assert "xl/comments1.xml" in zf.namelist()
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.load_workbook(workbook_copy)
        assert sum(len(book[n]._charts) for n in book.sheetnames) == 14

    def test_lowering_the_cap_is_a_no_op(self, wb):
        before = wb.timesheet_capacity()["raw_last_row"]
        wb.extend_timesheet_capacity(raw_last_row=before - 1000)
        assert wb.timesheet_capacity()["raw_last_row"] == before

    def test_asking_for_more_than_the_stack_can_supply_is_refused(self, wb):
        with pytest.raises(ValidationError, match="beyond what the stack"):
            wb.extend_timesheet_capacity(raw_last_row=99000)

    def test_the_extension_survives_a_reopen(self, wb, workbook_copy):
        wb.extend_timesheet_capacity(raw_last_row=12000, source_last_row=9000)
        wb.save()
        reopened = WorkloadWorkbook(workbook_copy)
        report = reopened.timesheet_capacity()
        assert report["raw_last_row"] == 12000
        assert report["source_last_row"] == 9000
        assert report["low_headroom"] is False


class TestImportWarnsBeforehand:
    def test_an_import_that_would_overflow_says_so(self, wb):
        rows = [[None] * 72] * 3000
        result = wb.replace_timesheet("Kirolos", rows)
        warnings = result["capacity_warnings"]
        assert any(w["level"] == "error" for w in warnings)
        assert any("Kirolos" in w["message"] for w in warnings)

    def test_an_import_that_fits_does_not(self, wb):
        rows = [[None] * 72] * 10
        assert all(w["level"] != "error"
                   for w in wb.replace_timesheet("Kirolos", rows)["capacity_warnings"])
