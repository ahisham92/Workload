"""Adding, editing and removing engineers.

A unit may have any number of people. The workbook ships with room for three
in fixed positions, so a fourth goes into free space rather than being inserted
-- inserting a row or column would shift the ninety-odd formulas that address
those positions, and every one would have to be repaired.
"""

import zipfile
import xml.etree.ElementTree as ET

import pytest

from workload_app import capacity, config as cfg
from workload_app.workbook import ValidationError, WorkloadWorkbook


class TestSlots:
    def test_the_first_three_sit_where_the_workbook_expects(self, readonly_wb):
        slots = readonly_wb.engineer_slots()
        assert [s.calendar_row for s in slots[:3]] == [20, 21, 22]
        assert [s.availability_row for s in slots[:3]] == [91, 92, 93]
        assert [s.share_column for s in slots[:3]] == ["K", "L", "M"]
        assert [s.manual_share_column for s in slots[:3]] == ["W", "X", "Y"]
        assert all(s.built_in for s in slots[:3])

    def test_a_fourth_goes_into_free_space(self, readonly_wb):
        slot = readonly_wb.engineer_slots()[3]
        assert slot.built_in is False
        assert slot.calendar_row == cfg.ENGINEER_EXTRA_FIRST_ROW
        assert slot.share_column == cfg.DELIVERABLE_SHARE_EXTRA_FIRST_COL

    def test_slots_are_offered_up_to_the_limit(self, readonly_wb):
        assert len(readonly_wb.engineer_slots()) == cfg.MAX_ENGINEERS

    def test_the_team_reads_back_with_its_sheets_and_row_counts(self, readonly_wb):
        team = readonly_wb.team()
        assert [p["short_name"] for p in team] == ["Ahmed", "Osama", "Kirolos"]
        assert team[0]["sheet"] == "TS Ahmed"
        assert team[0]["rows"] == 5822


class TestAdding:
    NEW = {"short_name": "Nadia", "available_hours": 185,
           "availability": {2026: 1.0, 2027: 0.5}}

    def test_a_fourth_engineer_joins_the_team(self, wb):
        result = wb.add_engineer(self.NEW)
        assert result["slot"] == 3
        assert result["sheet"] == "TS Nadia"
        assert [p.short_name for p in wb.engineers()] == [
            "Ahmed", "Osama", "Kirolos", "Nadia"]

    def test_they_get_a_paste_target_of_their_own(self, wb):
        wb.add_engineer(self.NEW)
        assert wb.ts_sheet("Nadia") == "TS Nadia"
        assert wb.timesheet_headers("Nadia")[:3] == [
            "Job Type", "JobNumber", "FullName"]

    def test_they_join_the_stack_that_builds_the_consolidated_view(self, wb):
        wb.add_engineer(self.NEW)
        assert capacity.stack_order(wb.raw)[-1] == "TS Nadia"
        assert wb.timesheet_capacity()["stack_order"][-1] == "Nadia"

    def test_they_get_a_column_of_every_split(self, wb):
        wb.add_engineer(self.NEW)
        assert wb._share_columns()["Nadia"] == cfg.DELIVERABLE_SHARE_EXTRA_FIRST_COL
        assert set(wb.deliverables()[0].shares) == {
            "Ahmed", "Osama", "Kirolos", "Nadia"}

    def test_their_availability_is_stored(self, wb):
        wb.add_engineer(self.NEW)
        person = next(p for p in wb.engineers() if p.short_name == "Nadia")
        assert person.availability[2026] == pytest.approx(1.0)
        assert person.availability[2027] == pytest.approx(0.5)
        assert person.pattern == "*Nadia*"

    def test_a_split_can_be_given_to_them(self, wb):
        wb.add_engineer(self.NEW)
        wb.add_project({"number": "T-0100D", "name": "T", "budget_mm": 1,
                        "status": "Active"})
        deliverable = wb.add_deliverable({
            "project_number": "T-0100D", "name": "Phase", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "ts_phase": 1,
            "shares": {"Nadia": 0.6, "Ahmed": 0.4},
        })
        stored = wb.deliverable(deliverable.row)
        assert stored.shares["Nadia"] == pytest.approx(0.6)

    def test_the_addition_survives_a_save(self, wb, workbook_copy):
        wb.add_engineer(self.NEW)
        wb.save()
        reopened = WorkloadWorkbook(workbook_copy)
        assert "Nadia" in reopened.engineer_names()
        assert reopened.ts_sheet("Nadia") == "TS Nadia"

    def test_the_workbook_is_still_sound(self, wb, workbook_copy):
        wb.add_engineer(self.NEW)
        wb.save()
        with zipfile.ZipFile(workbook_copy) as zf:
            for name in zf.namelist():
                if name.endswith(".xml"):
                    ET.fromstring(zf.read(name))
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.load_workbook(workbook_copy)
        assert sum(len(book[n]._charts) for n in book.sheetnames) == 14
        assert "TS Nadia" in book.sheetnames

    def test_nothing_the_workbook_already_used_moved(self, wb, workbook_copy):
        """The point of using free space: no row or column shifts."""
        wb.add_engineer(self.NEW)
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        sheet = openpyxl.load_workbook(workbook_copy)["Deliverables"]
        assert sheet["K4"].value == "Ahmed %"
        assert sheet["N4"].value == "Split Check"
        assert sheet["P4"].value == "Type Factor (KPI only)"
        assert sheet["AG4"].value == "Nadia %"

    @pytest.mark.parametrize("name,fragment", [
        ("", "needs a short name"),
        ("Ahmed", "already an engineer"),
        ("A" * 40, "under 25 characters"),
        ("Bad/Name", "cannot contain"),
    ])
    def test_bad_names_are_refused(self, wb, name, fragment):
        with pytest.raises(ValidationError) as exc:
            wb.add_engineer({**self.NEW, "short_name": name})
        assert any(fragment in message for message in exc.value.errors)

    def test_the_limit_is_enforced(self, wb):
        for index in range(cfg.MAX_ENGINEERS - 3):
            wb.add_engineer({"short_name": f"Extra{index}", "available_hours": 185})
        with pytest.raises(ValidationError, match="is full"):
            wb.add_engineer({"short_name": "OneTooMany"})


class TestEditing:
    def test_availability_can_be_changed(self, wb):
        wb.update_engineer("Kirolos", {
            "short_name": "Kirolos", "available_hours": 160,
            "availability": {2024: 0.5, 2026: 1.0},
        })
        person = next(p for p in wb.engineers() if p.short_name == "Kirolos")
        assert person.available_hours == 160
        assert person.availability[2024] == pytest.approx(0.5)

    def test_renaming_carries_the_sheet_with_it(self, wb, workbook_copy):
        result = wb.update_engineer("Kirolos", {"short_name": "Mina"})
        assert result["renamed"] is True
        assert "Mina" in wb.engineer_names()
        assert wb.ts_sheet("Mina") == "TS Mina"
        wb.save()
        reopened = WorkloadWorkbook(workbook_copy)
        assert reopened.ts_sheet("Mina") == "TS Mina"
        assert reopened.timesheet_capacity()["stack_order"] == [
            "Ahmed", "Osama", "Mina"]

    def test_a_rename_keeps_their_timesheet_rows(self, wb):
        before = wb.rows_per_engineer()["Kirolos"]
        wb.update_engineer("Kirolos", {"short_name": "Mina"})
        assert wb.rows_per_engineer()["Mina"] == before

    def test_renaming_onto_someone_else_is_refused(self, wb):
        with pytest.raises(ValidationError, match="already an engineer"):
            wb.update_engineer("Kirolos", {"short_name": "Ahmed"})

    def test_an_unknown_engineer_is_refused(self, wb):
        with pytest.raises(ValidationError, match="not one of this workbook"):
            wb.update_engineer("Nobody", {"short_name": "Nobody"})


class TestRemoving:
    def test_they_leave_with_their_sheet_and_their_column(self, wb, workbook_copy):
        result = wb.remove_engineer("Kirolos")
        assert result["sheet_removed"] == "TS Kirolos"
        assert "Kirolos" not in wb.engineer_names()
        assert wb.timesheet_capacity()["stack_order"] == ["Ahmed", "Osama"]
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.load_workbook(workbook_copy)
        assert "TS Kirolos" not in book.sheetnames
        assert sum(len(book[n]._charts) for n in book.sheetnames) == 14

    def test_their_share_of_every_deliverable_is_cleared(self, wb):
        result = wb.remove_engineer("Kirolos")
        assert result["deliverables_cleared"] > 0
        assert all("Kirolos" not in d.shares for d in wb.deliverables())

    def test_the_last_engineer_cannot_be_removed(self, wb):
        wb.remove_engineer("Osama")
        wb.remove_engineer("Kirolos")
        with pytest.raises(ValidationError, match="at least one engineer"):
            wb.remove_engineer("Ahmed")

    def test_a_freed_slot_is_reused(self, wb):
        wb.remove_engineer("Osama")
        result = wb.add_engineer({"short_name": "Nadia", "available_hours": 185})
        assert result["slot"] == 1
        assert wb._share_columns()["Nadia"] == "L"


class TestReportsFollowTheTeam:
    def test_a_new_engineer_appears_in_the_reports(self, wb):
        from workload_app import reports
        wb.add_engineer({"short_name": "Nadia", "available_hours": 185,
                         "availability": {2026: 1.0}})
        report = reports.build(wb, "year", 2026)
        assert "Nadia" in report.engineers
        assert "Nadia" in report.per_engineer
        assert "Nadia" in report.scorecard["totals"]

    def test_capacity_counts_the_larger_team(self, wb):
        from workload_app import reports
        before = reports.build(wb, "year", 2026).team["capacity_to_date_mm"]
        wb.add_engineer({"short_name": "Nadia", "available_hours": 185,
                         "availability": {2026: 1.0}})
        after = reports.build(wb, "year", 2026).team["capacity_to_date_mm"]
        assert after > before
