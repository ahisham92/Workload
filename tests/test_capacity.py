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

    def test_the_suggestion_is_the_same_25000_as_the_stack(self, readonly_wb):
        # One limit for the whole timesheet: the consolidated sheet is raised
        # to the same number of entries the stack reads from each sheet.
        report = readonly_wb.timesheet_capacity()
        assert report["suggested_raw_last_row"] == cfg.TS_RAW_TARGET_LAST_ROW
        assert report["suggested_raw_last_row"] == 25000
        assert report["suggested_raw_last_row"] > report["raw_last_row"]

    def test_a_workbook_already_past_it_is_not_pulled_back(self):
        assert capacity.suggest_raw_last_row(100, 40000) == 40000

    def test_a_timesheet_bigger_than_the_target_gets_room_for_itself(self):
        # Its own rows, plus room for a few more years, rounded up.
        assert capacity.suggest_raw_last_row(30000, 8000) == 40000


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


class TestTheDefaultStackIsTooShallow:
    """A fresh workbook only reads 6,000 rows from each monthly sheet."""

    def test_a_short_per_sheet_limit_is_reported(self, readonly_wb):
        report = readonly_wb.timesheet_capacity()
        assert report["source_last_row"] == 6000
        assert report["source_is_short"] is True
        assert report["suggested_source_last_row"] == cfg.TS_SOURCE_TARGET_LAST_ROW
        assert cfg.TS_SOURCE_TARGET_LAST_ROW == 25000

    def test_the_per_sheet_limit_can_be_raised_on_its_own(self, wb):
        result = wb.extend_timesheet_capacity(source_last_row=25000)
        assert result["source_last_row"] == 25000
        after = wb.timesheet_capacity()
        assert after["source_last_row"] == 25000
        assert after["source_is_short"] is False
        assert after["raw_last_row"] == 8000        # untouched
        assert after["per_sheet_capacity"] == 25000 - cfg.TS_FIRST_DATA_ROW + 1

    def test_the_ceiling_follows_the_number_of_sheets(self, readonly_wb):
        report = readonly_wb.timesheet_capacity()
        assert report["max_raw_last_row"] == (
            cfg.TS_RAW_FIRST_DATA_ROW
            + len(report["stack_order"]) * report["per_sheet_capacity"] - 1)

    def test_widening_the_stack_lifts_the_ceiling(self, wb):
        beyond = wb.timesheet_capacity()["max_raw_last_row"] + 5000
        with pytest.raises(ValidationError):
            wb.extend_timesheet_capacity(raw_last_row=beyond)
        wb.extend_timesheet_capacity(source_last_row=25000)
        assert wb.timesheet_capacity()["max_raw_last_row"] > beyond

    def test_the_low_headroom_warning_names_no_one(self, readonly_wb):
        report = readonly_wb.timesheet_capacity()
        warning = capacity.messages(report)[0]
        assert warning["level"] == "warning"
        for name in report["stack_order"]:
            assert name not in warning["message"]


class TestMakingRoomForAnImport:
    """The limit follows the timesheet, so an import can never lose rows.

    The targets are patched down here so the test does not spend a minute
    rewriting 138,000 formulas; the behaviour under test is the same.
    """

    @pytest.fixture(autouse=True)
    def small_targets(self, monkeypatch):
        monkeypatch.setattr(cfg, "TS_RAW_TARGET_LAST_ROW", 9000)
        monkeypatch.setattr(cfg, "TS_SOURCE_TARGET_LAST_ROW", 9000)
        monkeypatch.setattr(cfg, "TS_RAW_GROWTH_HEADROOM", 500)
        monkeypatch.setattr(cfg, "TS_RAW_GROWTH_STEP", 1000)
        monkeypatch.setattr(cfg, "TS_RAW_AUTO_MAX", 12000)

    def test_an_import_that_fits_changes_nothing(self, wb):
        before = wb.timesheet_capacity()
        room = wb.ensure_room_for("Kirolos", 900)
        assert room["raised"] is False
        assert wb.timesheet_capacity()["raw_last_row"] == before["raw_last_row"]

    def test_an_import_that_does_not_fit_raises_the_limit(self, wb):
        # 7,682 rows already, 7,997 read: this asks for 1,500 more than fits.
        room = wb.ensure_room_for("Kirolos", 2500)
        assert room["raised"] is True
        assert room["raw_from"] == 8000
        assert room["raw_last_row"] >= 9000
        assert "entries" in room["why"]

        after = wb.timesheet_capacity()
        assert after["over_capacity"] is False
        # Room to spare, so next month does not pay for this again.
        assert after["headroom"] > 0

    def test_the_stack_is_deepened_with_it(self, wb):
        room = wb.ensure_room_for("Kirolos", 2500)
        # Each sheet is read as deep as the consolidated sheet: one number.
        assert room["source_last_row"] == room["raw_last_row"]

    def test_a_single_sheet_that_outgrows_its_own_limit_is_handled(self, wb, monkeypatch):
        # Only the decision is under test here: actually rewriting the workbook
        # for a sheet this size is a minute of formula surgery.
        asked = {}
        monkeypatch.setattr(cfg, "TS_RAW_AUTO_MAX", 40000)
        monkeypatch.setattr(
            wb, "extend_timesheet_capacity",
            lambda **kw: asked.update(kw) or {
                "raw_last_row": kw.get("raw_last_row") or 8000,
                "source_last_row": kw.get("source_last_row") or 6000})
        room = wb.ensure_room_for("Osama", 8000)
        assert room["raised"] is True
        # One sheet needs 8,000 rows, so the stack has to read that deep.
        assert asked["source_last_row"] >= 8000 + cfg.TS_FIRST_DATA_ROW - 1
        assert asked["raw_last_row"] >= 14759

    def test_something_far_too_big_is_refused_before_anything_is_written(self, wb):  # noqa: E501
        before = wb.timesheet_capacity()
        with pytest.raises(ValidationError) as error:
            wb.ensure_room_for("Kirolos", 40000)
        message = error.value.errors[0]
        assert "Nothing was written" in message
        assert "12,000" in message                 # the ceiling it will not pass
        assert wb.timesheet_capacity()["raw_last_row"] == before["raw_last_row"]

    def test_running_it_twice_only_raises_once(self, wb):
        first = wb.ensure_room_for("Kirolos", 2500)
        second = wb.ensure_room_for("Kirolos", 2500)
        assert first["raised"] is True
        assert second["raised"] is False


class TestTheSuggestionGrows:
    def test_it_starts_at_the_target(self):
        assert capacity.suggest_raw_last_row(100, 8000) == cfg.TS_RAW_TARGET_LAST_ROW

    def test_and_follows_the_timesheet_once_it_is_bigger(self):
        assert capacity.suggest_raw_last_row(24000, 8000) == 30000
        assert capacity.suggest_raw_last_row(40000, 8000) == 50000

    def test_it_never_pulls_a_limit_back_down(self):
        assert capacity.suggest_raw_last_row(100, 40000) == 40000

    def test_the_per_sheet_suggestion_works_the_same_way(self):
        assert capacity.suggest_source_last_row(100, 6000) == 25000
        assert capacity.suggest_source_last_row(30000, 25000) == 40000
