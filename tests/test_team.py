"""Adding, editing and removing engineers.

A unit may have any number of people.  They are rows in its own database, so
there are no slots to run out of and no sheets to make or take away.
"""

import pytest

from workload_app.model import ValidationError
from workload_app.unit import Unit


class TestTheTeam:
    def test_the_team_reads_back_in_order_with_row_counts(self, readonly_wb):
        team = readonly_wb.team()
        assert [p["short_name"] for p in team][:3] == ["Ahmed", "Osama", "Kirolos"]
        assert team[0]["rows"] == 5822


class TestAdding:
    NEW = {"short_name": "Nadia", "available_hours": 185,
           "availability": {2026: 1.0, 2027: 0.5}}

    def test_a_new_engineer_joins_the_end_of_the_team(self, wb):
        before = wb.engineer_names()
        result = wb.add_engineer(self.NEW)
        assert result["engineer"] == "Nadia"
        assert wb.engineer_names() == before + ["Nadia"]

    def test_their_timesheets_take_the_usual_export_columns(self, wb):
        wb.add_engineer(self.NEW)
        assert wb.timesheet_headers("Nadia")[:3] == [
            "Job Type", "JobNumber", "FullName"]

    def test_they_get_a_share_of_every_split(self, wb):
        wb.add_engineer(self.NEW)
        assert "Nadia" in wb.deliverables()[0].shares

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

    def test_the_addition_is_there_when_the_unit_is_opened_again(self, wb, unit_copy):
        wb.add_engineer(self.NEW)
        assert "Nadia" in Unit(unit_copy).engineer_names()

    @pytest.mark.parametrize("name,fragment", [
        ("", "needs a short name"),
        ("Ahmed", "already an engineer"),
        ("ahmed", "already an engineer"),
        ("A" * 80, "under 60 characters"),
    ])
    def test_bad_names_are_refused(self, wb, name, fragment):
        with pytest.raises(ValidationError) as exc:
            wb.add_engineer({**self.NEW, "short_name": name})
        assert any(fragment in message for message in exc.value.errors)

    def test_there_is_no_limit_to_the_team(self, wb):
        """A unit was once held to twelve; now it holds whoever works in it."""
        before = len(wb.engineers())
        for index in range(30):
            wb.add_engineer({"short_name": f"Extra{index}", "available_hours": 185})
        assert len(wb.engineers()) == before + 30

    def test_several_can_be_added_at_once_skipping_anyone_already_there(self, wb):
        added = wb.add_engineers([{"short_name": "Nadia"},
                                  {"short_name": "AHMED"},
                                  {"short_name": "Youssef"}])
        assert added == ["Nadia", "Youssef"]
        assert wb.engineer_names().count("Ahmed") == 1


class TestEditing:
    def test_availability_can_be_changed(self, wb):
        wb.update_engineer("Kirolos", {
            "short_name": "Kirolos", "available_hours": 160,
            "availability": {2024: 0.5, 2026: 1.0},
        })
        person = next(p for p in wb.engineers() if p.short_name == "Kirolos")
        assert person.available_hours == 160
        assert person.availability[2024] == pytest.approx(0.5)

    def test_a_rename_follows_them_into_their_splits(self, wb):
        shared = [d.row for d in wb.deliverables() if d.shares.get("Kirolos")]
        result = wb.update_engineer("Kirolos", {"short_name": "Mina"})
        assert result["renamed"] is True
        assert "Mina" in wb.engineer_names()
        assert "Kirolos" not in wb.engineer_names()
        assert shared and all(wb.deliverable(row).shares.get("Mina")
                              for row in shared)

    def test_a_rename_keeps_their_timesheet_rows(self, wb):
        before = wb.rows_per_engineer()["Kirolos"]
        wb.update_engineer("Kirolos", {"short_name": "Mina"})
        assert wb.rows_per_engineer()["Mina"] == before
        assert "Kirolos" not in wb.rows_per_engineer()

    def test_renaming_onto_someone_else_is_refused(self, wb):
        with pytest.raises(ValidationError, match="already an engineer"):
            wb.update_engineer("Kirolos", {"short_name": "Ahmed"})

    def test_an_unknown_engineer_is_refused(self, wb):
        with pytest.raises(ValidationError, match="not on this unit's team"):
            wb.update_engineer("Nobody", {"short_name": "Nobody"})


class TestRemoving:
    def test_they_leave_the_team_but_their_hours_stay(self, wb):
        rows = wb.rows_per_engineer()["Kirolos"]
        wb.remove_engineer("Kirolos")
        assert "Kirolos" not in wb.engineer_names()
        assert wb.rows_per_engineer()["Kirolos"] == rows

    def test_their_share_of_every_deliverable_is_cleared(self, wb):
        result = wb.remove_engineer("Kirolos")
        assert result["deliverables_cleared"] > 0
        assert all(not d.shares.get("Kirolos") for d in wb.deliverables())

    def test_the_last_engineer_cannot_be_removed(self, wb):
        for name in wb.engineer_names()[1:]:
            wb.remove_engineer(name)
        with pytest.raises(ValidationError, match="at least one engineer"):
            wb.remove_engineer(wb.engineer_names()[0])


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
