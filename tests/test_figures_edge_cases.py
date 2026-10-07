"""Figures that drifted on the edges: week starts, run-ups, shares that add up."""

import datetime as dt

import pytest

from workload_app import daily, derive, metrics, people, reports, submissions, tasks
from workload_app.unit import Unit


class _Tasks:
    def __init__(self):
        self.tasks = []

    def read_tasks(self):
        return list(self.tasks)

    def write_tasks(self, tasks):
        self.tasks = list(tasks)

    def read_task_settings(self):
        return None


class TestWeeks:
    @pytest.mark.parametrize("offset", range(7))
    def test_every_day_of_a_sunday_week_opens_that_week(self, offset):
        config = dict(tasks.settings(None), work_days=[6, 0, 1, 2, 3])
        sunday = dt.date(2026, 10, 4)
        week = daily.week_of(sunday + dt.timedelta(days=offset), config)
        assert week[0] == sunday and week[-1] == dt.date(2026, 10, 8)

    def test_a_monday_week_is_unchanged(self):
        week = daily.week_of(dt.date(2026, 10, 7), tasks.settings(None))
        assert week[0] == dt.date(2026, 10, 5) and len(week) == 5


class TestSubmissions:
    def test_hours_with_no_phase_count_once(self):
        rows = [{"date": dt.date(2026, 9, 7), "job_number": "J1", "phase": None,
                 "hours": 8.0, "engineer": "A", "job_type": "1-Projects"}]
        pace = submissions.pace_by_phase(rows, tasks.settings(None))
        assert sum(pace.values()) == pytest.approx(2 * 8.0 / 10)   # its phase, its job
        assert pace[("J1", None)] == pytest.approx(0.8)

    def test_a_run_up_does_not_start_in_the_past(self):
        source, config = _Tasks(), tasks.settings(None)
        today = dt.date(2026, 9, 7)
        tasks.generate_submissions(
            source, [{"row": 1, "status_date": "2026-09-09", "name": "D",
                      "shares": {"A": 1.0}, "project_number": "P"}],
            engineers=["A"], config=config, today=today)
        assert source.tasks and min(t.due for t in source.tasks) >= today
        load = tasks.load(source.tasks, ["A"], config, today=today)["per_engineer"]["A"]
        assert load["overdue_tasks"] == 0


class TestGrades:
    @pytest.mark.parametrize("title", ["Junior Engineer", "Graduate Engineer",
                                       "Trainee Engineer", "Assistant Engineer"])
    def test_junior_titles_are_junior(self, title):
        assert derive.grade_for(title) == "junior"

    def test_no_rules_of_credit_still_gives_a_type(self):
        assert derive.type_for("Detailed design", []) == derive.DEFAULT_TYPE


class TestReconciles:
    @pytest.fixture
    def unit(self, migrated, tmp_path):
        from conftest import copy_unit
        return Unit(copy_unit(migrated, tmp_path / "unit.db"))

    def test_all_time_earned_value_matches_the_overview(self, unit):
        team = reports.build(unit, "all").team
        portfolio = metrics.overview(unit)["portfolio"]
        assert team["earned_mm"] == pytest.approx(
            portfolio["all_projects_earned_mm"], abs=0.02)

    def test_effort_shares_on_the_portfolio_map_add_to_one(self, unit):
        rows = metrics.project_rows(unit, metrics.TimesheetIndex(unit))
        circles = people.portfolio_map(unit.store, rows)["projects"]
        if any(c["recent_hours"] for c in circles):
            assert sum(c["effort_share"] for c in circles) == pytest.approx(1.0, abs=0.01)
