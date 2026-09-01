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
        assert stored.shares["Ahmed"] == pytest.approx(0.5)
        assert stored.shares["Osama"] == pytest.approx(0.5)

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


class TestAnotherUnitsTeam:
    """Nothing may assume who the engineers are, or how many there are.

    A workbook set up for a different discipline names different people and
    different paste-target sheets; the app has to read both from the file.
    """

    @pytest.fixture
    def renamed(self, workbook_copy):
        from workload_app.xlsx_io import Workbook
        from workload_app.workbook import WorkloadWorkbook

        raw = Workbook(workbook_copy)
        swaps = [("Ahmed", "Nadia"), ("Osama", "Tarek"), ("Kirolos", "Mina")]
        for row, (_old, new) in zip((20, 21, 22), swaps):
            raw.sheet(cfg.SHEET_CALENDAR).set_value(f"A{row}", new)
            raw.sheet(cfg.SHEET_CALENDAR).set_value(f"B{row}", f"*{new}*")
        for row, (_old, new) in zip((91, 92, 93), swaps):
            raw.sheet(cfg.SHEET_INPUTS).set_value(f"A{row}", new)
        workbook_xml = raw._entries["xl/workbook.xml"].decode()
        sheet = raw.sheet(cfg.SHEET_TS_RAW)
        for old, new in swaps:
            workbook_xml = workbook_xml.replace(f'name="TS {old}"', f'name="TS {new}"')
            sheet.xml = sheet.xml.replace(f"'TS {old}'!", f"'TS {new}'!")
        raw._entries["xl/workbook.xml"] = workbook_xml.encode()
        raw.save()
        return WorkloadWorkbook(workbook_copy)

    def test_the_engineers_come_from_the_workbook(self, renamed):
        assert renamed.engineer_names() == ["Nadia", "Tarek", "Mina"]

    def test_the_paste_targets_are_found_by_name(self, renamed):
        assert dict(renamed.ts_sheets()) == {
            "Nadia": "TS Nadia", "Tarek": "TS Tarek", "Mina": "TS Mina"}

    def test_the_stack_order_follows_the_formula(self, renamed):
        assert renamed.timesheet_capacity()["stack_order"] == [
            "Nadia", "Tarek", "Mina"]

    def test_splits_are_keyed_by_the_new_names(self, renamed):
        assert set(renamed.deliverables()[0].shares) == {"Nadia", "Tarek", "Mina"}

    def test_a_split_is_validated_against_the_new_names(self, renamed):
        renamed.add_project({"number": "U2-0100D", "name": "T", "budget_mm": 1,
                             "status": "Active"})
        deliverable = renamed.add_deliverable({
            "project_number": "U2-0100D", "name": "Phase", "type_code": "FS",
            "phase_weight": 1, "step_no": 1, "ts_phase": 1,
            "shares": {"Nadia": 0.5, "Mina": 0.5},
        })
        stored = renamed.deliverable(deliverable.row)
        assert stored.shares["Nadia"] == pytest.approx(0.5)
        assert stored.shares["Mina"] == pytest.approx(0.5)

    def test_the_data_check_reports_the_new_team(self, renamed):
        assert set(renamed.data_check()["per_engineer"]) == {"Nadia", "Tarek", "Mina"}


class TestProjectWithItsDeliverables:
    """Saving a project and its deliverables as one set."""

    PROJECT = {"number": "SET-0100D", "name": "Together", "budget_mm": 3,
               "status": "Active"}

    def _item(self, **overrides):
        item = {"name": "Phase", "type_code": "DD", "phase_weight": 1.0,
                "ts_phase": 1, "shares": {"Ahmed": 1.0}}
        item.update(overrides)
        return item

    def test_a_new_project_carries_its_deliverables_in(self, wb):
        result = wb.save_project_with_deliverables(None, self.PROJECT, [
            self._item(name="A", phase_weight=0.3),
            self._item(name="B", phase_weight=0.7),
        ])
        assert result["weight_total"] == 1.0
        assert len(wb.deliverables()) == 66

    def test_the_deliverables_are_not_rejected_for_a_project_being_created(self, wb):
        # The project is not in the register until this same call writes it.
        wb.save_project_with_deliverables(None, self.PROJECT, [self._item()])
        assert wb.project("SET-0100D") is not None

    def test_weights_that_do_not_add_up_stop_the_whole_save(self, wb):
        before = len(wb.projects())
        with pytest.raises(ValidationError, match="not 100%"):
            wb.save_project_with_deliverables(None, self.PROJECT,
                                              [self._item(phase_weight=0.5)])
        assert len(wb.projects()) == before

    def test_a_bad_deliverable_names_itself_in_the_error(self, wb):
        with pytest.raises(ValidationError) as exc:
            wb.save_project_with_deliverables(None, self.PROJECT, [
                self._item(name="Concept", step_no=9)])
        assert any(message.startswith("Concept:") for message in exc.value.errors)

    def test_renaming_the_project_carries_its_deliverables(self, wb):
        wb.save_project_with_deliverables(None, self.PROJECT, [self._item()])
        wb.save_project_with_deliverables(
            "SET-0100D", {**self.PROJECT, "number": "SET-0200D"}, [self._item()])
        assert wb.project("SET-0100D") is None
        assert [d.project_number for d in wb.deliverables()].count("SET-0200D") == 1

    def test_a_deliverable_keeps_its_row_so_its_actuals_stay_with_it(self, wb):
        wb.save_project_with_deliverables(None, self.PROJECT, [
            self._item(name="A", phase_weight=0.5),
            self._item(name="B", phase_weight=0.5),
        ])
        rows = {d.name: d.row for d in wb.deliverables()
                if d.project_number == "SET-0100D"}
        wb.save_project_with_deliverables("SET-0100D", self.PROJECT, [
            self._item(name="A", phase_weight=0.4),
            self._item(name="B", phase_weight=0.6),
        ])
        after = {d.name: d.row for d in wb.deliverables()
                 if d.project_number == "SET-0100D"}
        assert after == rows

    def test_dropping_one_clears_its_row_on_both_sheets(self, wb):
        wb.save_project_with_deliverables(None, self.PROJECT, [
            self._item(name="Keep", phase_weight=0.5),
            self._item(name="Drop", phase_weight=0.5),
        ])
        dropped = next(d for d in wb.deliverables() if d.name == "Drop")
        result = wb.save_project_with_deliverables(
            "SET-0100D", self.PROJECT, [self._item(name="Keep", phase_weight=1.0)])
        assert result["removed"] == 1
        assert wb.raw.get_value(cfg.SHEET_ACTUALS, f"E{dropped.row}") is None


class TestReferenceTables:
    def test_a_credit_can_be_rewritten(self, wb):
        types = [t.__dict__ for t in wb.project_types()]
        steps = [
            {"type_code": s.type_code, "step_no": s.step_no,
             "step_name": s.step_name, "credit": s.credit,
             "data_source": s.data_source}
            for s in wb.credit_steps()
        ]
        for step in steps:
            if step["type_code"] == "DD" and step["step_no"] == 1:
                step["credit"] = 0.2
        wb.save_reference(types, steps)
        assert wb.credit_for("DD", 1) == pytest.approx(0.2)

    def test_a_type_can_be_reweighted(self, wb):
        types = [t.__dict__ for t in wb.project_types()]
        for item in types:
            if item["code"] == "CD":
                item["portfolio_weight"] = 1.4
        wb.save_reference(types, None)
        assert [t.portfolio_weight for t in wb.project_types()
                if t.code == "CD"] == [1.4]

    def test_removing_a_step_clears_its_row(self, wb):
        types = [t.__dict__ for t in wb.project_types()]
        steps = [
            {"type_code": s.type_code, "step_no": s.step_no,
             "step_name": s.step_name, "credit": s.credit}
            for s in wb.credit_steps() if not (s.type_code == "DD" and s.step_no == 5)
        ]
        wb.save_reference(types, steps)
        assert wb.credit_for("DD", 5) is None

    def test_more_rows_than_the_sheet_holds_are_refused(self, wb):
        types = [t.__dict__ for t in wb.project_types()]
        with pytest.raises(ValidationError, match="room for"):
            wb.save_reference(types * 3, None)

    def test_a_duplicate_type_code_is_refused(self, wb):
        types = [t.__dict__ for t in wb.project_types()]
        types[1] = {**types[1], "code": types[0]["code"]}
        with pytest.raises(ValidationError, match="more than once"):
            wb.save_reference(types, None)

    def test_a_credit_outside_zero_to_one_hundred_is_refused(self, wb):
        types = [t.__dict__ for t in wb.project_types()]
        steps = [{"type_code": "DD", "step_no": 1, "step_name": "x", "credit": 150}]
        with pytest.raises(ValidationError, match="between 0% and 100%"):
            wb.save_reference(types, steps)

    def test_a_credit_may_be_given_as_a_percentage_or_a_fraction(self, wb):
        types = [t.__dict__ for t in wb.project_types()]
        wb.save_reference(types, [
            {"type_code": "DD", "step_no": 1, "step_name": "a", "credit": 25},
            {"type_code": "DD", "step_no": 2, "step_name": "b", "credit": 0.5},
        ])
        assert wb.credit_for("DD", 1) == pytest.approx(0.25)
        assert wb.credit_for("DD", 2) == pytest.approx(0.5)


class TestTheDataCheckByYear:
    """The Overview is for one year, so its data check is too."""

    def test_a_year_narrows_the_counts_but_keeps_the_whole_file(self, readonly_wb):
        whole = readonly_wb.data_check()
        year = readonly_wb.data_check(2026)
        assert year["year"] == 2026
        assert 0 < year["rows"] < whole["rows"]
        assert 0 < year["hours"] < whole["hours"]
        assert year["all_time_rows"] == whole["rows"]
        assert year["all_time_hours"] == whole["hours"]

    def test_each_engineer_carries_both_counts(self, readonly_wb):
        year = readonly_wb.data_check(2026)
        for name, entry in year["per_engineer"].items():
            assert entry["rows"] <= entry["all_time_rows"], name
            assert entry["hours"] <= entry["all_time_hours"], name
        assert sum(e["rows"] for e in year["per_engineer"].values()) == year["rows"]

    def test_unknown_job_numbers_follow_the_year_too(self, readonly_wb):
        whole = readonly_wb.data_check()["unknown_job_numbers"]
        year = readonly_wb.data_check(2026)["unknown_job_numbers"]
        assert 0 < len(year) < len(whole)
        codes = {u["code"] for u in whole}
        assert {u["code"] for u in year} <= codes

    def test_the_capacity_report_still_sees_every_row(self, readonly_wb):
        year = readonly_wb.data_check(2026)
        assert year["capacity"]["rows_used"] == year["all_time_rows"]
