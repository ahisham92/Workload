"""Reading and editing the two registers, and the rules that guard them."""

import datetime as dt

import pytest

from workload_app import config as cfg
from workload_app.workbook import (
    ValidationError, as_date, as_fraction, as_number, as_text,
)


class TestCoercion:
    @pytest.mark.parametrize("value,expected", [
        ("25%", 0.25), ("25", 0.25), (25, 0.25), (0.25, 0.25), ("0.25", 0.25),
        (1, 1.0), ("100", 1.0), (None, None), ("", None),
    ])
    def test_shares_accept_either_notation(self, value, expected):
        assert as_fraction(value) == expected

    @pytest.mark.parametrize("value", [
        "2026-07-01", "01/07/2026", dt.date(2026, 7, 1),
        dt.datetime(2026, 7, 1, 9, 30), 46204,
    ])
    def test_dates_accept_the_usual_shapes(self, value):
        assert as_date(value) == dt.date(2026, 7, 1)

    def test_nonsense_is_not_a_date(self):
        assert as_date("not a date") is None

    def test_numbers_survive_thousands_separators(self):
        assert as_number("1,234.5") == 1234.5

    def test_text_of_a_whole_number_has_no_decimal_point(self):
        assert as_text(4.0) == "4"


class TestReading:
    def test_registers_load(self, readonly_wb):
        assert len(readonly_wb.projects()) == 40
        assert len(readonly_wb.deliverables()) == 64

    def test_reference_tables_load(self, readonly_wb):
        codes = [t.code for t in readonly_wb.project_types()]
        assert codes == ["DD", "CD", "FS", "SA", "DR", "TD", "CS", "PP", "OH"]
        assert len(readonly_wb.credit_steps()) == 34
        assert readonly_wb.hours_per_man_month() == 185.0

    def test_credit_lookup_follows_rules_of_credit(self, readonly_wb):
        assert readonly_wb.credit_for("DD", 5) == 1.0
        assert readonly_wb.credit_for("CD", 3) == 0.65
        assert readonly_wb.credit_for("DD", 9) is None

    def test_engineers_come_from_the_work_calendar(self, readonly_wb):
        engineers = {e.short_name: e for e in readonly_wb.engineers()}
        assert set(engineers) == {"Ahmed", "Osama", "Kirolos"}
        assert engineers["Ahmed"].pattern == "*Ahmed*"
        assert engineers["Kirolos"].availability[2024] == 0.35

    def test_a_deliverable_carries_its_actuals_inputs(self, readonly_wb):
        first = readonly_wb.deliverables()[0]
        assert first.project_number == "N25178-0100D"
        assert first.type_code == "CD"
        assert first.ts_phase == 1


class TestProjects:
    def _valid(self, **overrides):
        data = {
            "number": "TEST-0100D", "name": "Test project", "budget_mm": 4.0,
            "start": "2026-01-01", "end": "2026-12-31", "status": "Active",
        }
        data.update(overrides)
        return data

    def test_add_uses_the_first_free_row(self, wb):
        project = wb.add_project(self._valid())
        assert cfg.PROJECT_FIRST_ROW <= project.row <= cfg.PROJECT_LAST_ROW
        assert wb.project("TEST-0100D").name == "Test project"
        assert wb.dirty

    def test_add_survives_a_save_and_reopen(self, wb, workbook_copy):
        wb.add_project(self._valid())
        wb.save()
        from workload_app.workbook import WorkloadWorkbook
        assert WorkloadWorkbook(workbook_copy).project("TEST-0100D").budget_mm == 4.0

    def test_percentages_round_trip(self, wb):
        wb.add_project(self._valid(manual_percent="35%"))
        assert wb.project("TEST-0100D").manual_percent == pytest.approx(0.35)

    @pytest.mark.parametrize("overrides,fragment", [
        ({"number": ""}, "Project number is required"),
        ({"name": ""}, "Project name is required"),
        ({"budget_mm": -1}, "greater than zero"),
        ({"budget_mm": None}, "Budget (MM) is required"),
        ({"status": "Whatever"}, "Status must be one of"),
        ({"start": "2026-12-31", "end": "2026-01-01"}, "before the start date"),
        ({"manual_percent": "150%"}, "between 0% and 100%"),
        ({"manual_share_ahmed": "60", "manual_share_osama": "30"}, "must total 100%"),
    ])
    def test_bad_input_is_rejected(self, wb, overrides, fragment):
        with pytest.raises(ValidationError) as exc:
            wb.add_project(self._valid(**overrides))
        assert any(fragment in message for message in exc.value.errors)

    def test_duplicate_numbers_are_rejected(self, wb):
        wb.add_project(self._valid())
        with pytest.raises(ValidationError, match="already on Inputs row"):
            wb.add_project(self._valid(name="Another"))

    def test_update_can_rename_and_carries_the_deliverables_with_it(self, wb):
        wb.add_project(self._valid())
        wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase 1", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "share_ahmed": 1,
        })
        wb.update_project("TEST-0100D", self._valid(number="TEST-0200D"))
        assert wb.project("TEST-0100D") is None
        assert [d.project_number for d in wb.deliverables()].count("TEST-0200D") == 1

    def test_delete_refuses_while_deliverables_point_at_it(self, wb):
        wb.add_project(self._valid())
        wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase 1", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "share_ahmed": 1,
        })
        with pytest.raises(ValidationError, match="still point at"):
            wb.delete_project("TEST-0100D")

    def test_delete_with_cascade_clears_both_registers(self, wb):
        wb.add_project(self._valid())
        wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase 1", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "share_ahmed": 1,
        })
        before = len(wb.deliverables())
        result = wb.delete_project("TEST-0100D", cascade=True)
        assert result["deliverables_removed"] == 1
        assert wb.project("TEST-0100D") is None
        assert len(wb.deliverables()) == before - 1


class TestDeliverables:
    def _project(self, wb):
        wb.add_project({
            "number": "TEST-0100D", "name": "Test project", "budget_mm": 4.0,
            "status": "Active",
        })

    def _valid(self, **overrides):
        data = {
            "project_number": "TEST-0100D", "name": "Concept", "type_code": "CD",
            "phase_weight": "100", "step_no": 2, "status_date": "2026-06-30",
            "share_ahmed": "50", "share_osama": "50", "ts_phase": 3,
        }
        data.update(overrides)
        return data

    def test_add_writes_both_sheets(self, wb):
        self._project(wb)
        deliverable = wb.add_deliverable(self._valid())
        stored = wb.deliverable(deliverable.row)
        assert stored.name == "Concept"
        assert stored.phase_weight == pytest.approx(1.0)
        assert stored.ts_phase == 3
        assert stored.share_ahmed == pytest.approx(0.5)

    def test_milestone_dates_are_stored(self, wb):
        self._project(wb)
        deliverable = wb.add_deliverable(self._valid(
            submitted_to_client="2026-07-15", comments_received="2026-08-01"))
        stored = wb.deliverable(deliverable.row)
        assert stored.submitted_to_client == dt.date(2026, 7, 15)
        assert stored.comments_received == dt.date(2026, 8, 1)

    @pytest.mark.parametrize("overrides,fragment", [
        ({"project_number": "NOT-A-PROJECT"}, "not in the project register"),
        ({"name": ""}, "name is required"),
        ({"type_code": "ZZ"}, "not in Project Types"),
        ({"step_no": 9}, "not a Rules of Credit step"),
        ({"phase_weight": None}, "Phase weight is required"),
        ({"phase_weight": "150"}, "between 0% and 100%"),
        ({"share_ahmed": "60", "share_osama": "30"}, "must total 100%"),
    ])
    def test_bad_input_is_rejected(self, wb, overrides, fragment):
        self._project(wb)
        with pytest.raises(ValidationError) as exc:
            wb.add_deliverable(self._valid(**overrides))
        assert any(fragment in message for message in exc.value.errors)

    def test_the_step_must_belong_to_the_chosen_type(self, wb):
        self._project(wb)
        wb.add_deliverable(self._valid(type_code="DR", step_no=4))     # DR has 4 steps
        with pytest.raises(ValidationError, match="not a Rules of Credit step"):
            wb.add_deliverable(self._valid(type_code="DR", step_no=5, name="x"))

    def test_weights_are_totalled_per_project(self, wb):
        self._project(wb)
        wb.add_deliverable(self._valid(phase_weight="40"))
        wb.add_deliverable(self._valid(name="Detail", phase_weight="60"))
        assert wb.weight_by_project()["TEST-0100D"] == pytest.approx(1.0)

    def test_delete_clears_the_actuals_row_too(self, wb):
        self._project(wb)
        deliverable = wb.add_deliverable(self._valid())
        wb.delete_deliverable(deliverable.row)
        assert wb.deliverable(deliverable.row) is None
        assert wb.raw.get_value(
            cfg.SHEET_ACTUALS, f"E{deliverable.row}") is None


class TestActualsCapacity:
    """The actuals block ships full, so a 65th deliverable has to grow it."""

    def test_it_starts_exactly_full(self, readonly_wb):
        assert readonly_wb.actuals_last_row() == cfg.ACTUALS_DEFAULT_LAST_ROW
        assert len(readonly_wb.deliverables()) == (
            cfg.ACTUALS_DEFAULT_LAST_ROW - cfg.ACTUALS_FIRST_ROW + 1)

    def test_adding_a_deliverable_grows_the_block(self, wb):
        wb.add_project({"number": "TEST-0100D", "name": "T", "budget_mm": 1,
                        "status": "Active"})
        deliverable = wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "share_ahmed": 1, "ts_phase": 1,
        })
        assert deliverable.row == cfg.ACTUALS_DEFAULT_LAST_ROW + 1
        assert wb.actuals_last_row() == deliverable.row

    def test_the_grown_rows_carry_translated_formulas(self, wb, workbook_copy):
        wb.add_project({"number": "TEST-0100D", "name": "T", "budget_mm": 1,
                        "status": "Active"})
        row = wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "share_ahmed": 1, "ts_phase": 1,
        }).row
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        sheet = openpyxl.load_workbook(workbook_copy)["Deliverable Actuals"]
        assert f"Deliverables!$A{row}" in str(sheet[f"A{row}"].value)
        # the shared formula in column H must have become an explicit one
        assert str(sheet[f"H{row}"].value).startswith("=IF(OR($A")
        # and every range anchored to the old last row must have grown
        assert f"$A$5:$A${row}" in str(sheet["AJ5"].value)

    def test_growing_the_block_leaves_the_workbook_readable(self, wb, workbook_copy):
        wb.add_project({"number": "TEST-0100D", "name": "T", "budget_mm": 1,
                        "status": "Active"})
        wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "share_ahmed": 1, "ts_phase": 1,
        })
        wb.save()
        import xml.etree.ElementTree as ET
        import zipfile
        with zipfile.ZipFile(workbook_copy) as zf:
            for name in zf.namelist():
                if name.endswith(".xml"):
                    ET.fromstring(zf.read(name))
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.load_workbook(workbook_copy)
        assert sum(len(book[n]._charts) for n in book.sheetnames) == 14


class TestChecks:
    def test_a_clean_workbook_reports_nothing(self, readonly_wb):
        assert readonly_wb.register_issues() == []

    def test_a_broken_weight_is_reported(self, wb):
        wb.add_project({"number": "TEST-0100D", "name": "T", "budget_mm": 1,
                        "status": "Active"})
        wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase", "type_code": "FS",
            "phase_weight": "40", "step_no": 1, "share_ahmed": 1, "ts_phase": 1,
        })
        messages = [i["message"] for i in wb.register_issues() if i["level"] == "error"]
        assert any("total 40.0%, not 100%" in m for m in messages)

    def test_a_missing_ts_phase_is_reported(self, wb):
        wb.add_project({"number": "TEST-0100D", "name": "T", "budget_mm": 1,
                        "status": "Active"})
        wb.add_deliverable({
            "project_number": "TEST-0100D", "name": "Phase", "type_code": "FS",
            "phase_weight": "100", "step_no": 1, "share_ahmed": 1,
        })
        assert any("no TS Phase" in i["message"] for i in wb.register_issues())

    def test_data_check_matches_the_work_calendar_block(self, readonly_wb):
        check = readonly_wb.data_check()
        assert check["rows"] == 7682
        assert check["rows_not_matching_pattern"] == 0
        assert check["verdict"] == "All rows matched to an engineer."
        assert set(check["per_engineer"]) == {"Ahmed", "Osama", "Kirolos"}
