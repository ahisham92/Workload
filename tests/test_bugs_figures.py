"""Figures that came out wrong on the edges: Sunday weeks, joiners, holidays
in a sample week, leave booked ahead, and numbers no calendar has."""

import datetime as dt
from types import SimpleNamespace

import pytest

from workload_app import checkins, growth, management, needs, progress, submissions
from workload_app import people as ppl
from workload_app import tasks
from workload_app.timesheet_store import TimesheetStore

SUN_THU = [6, 0, 1, 2, 3]


def cairo(**extra):
    return dict(tasks.settings(None), work_days=SUN_THU, **extra)


class TestTaskNumbers:
    @pytest.mark.parametrize("value", [0, -3, 0.0])
    def test_a_serial_of_nought_or_less_is_no_date(self, value):
        assert tasks._parse_date(value) is None

    @pytest.mark.parametrize("value", [1e12, float("inf"), float("nan")])
    def test_a_serial_past_any_calendar_is_refused_not_a_crash(self, value):
        with pytest.raises(tasks.TaskError):
            tasks.validate({"name": "T", "due": value}, engineers=[], projects=[])

    @pytest.mark.parametrize("field", ["required_hours", "actual_hours", "pro_rata"])
    @pytest.mark.parametrize("value", ["inf", "nan", float("inf")])
    def test_hours_that_are_not_a_number_are_refused(self, field, value):
        with pytest.raises(tasks.TaskError):
            tasks.validate({"name": "T", field: value}, engineers=[], projects=[])

    def test_working_days_that_are_not_days_are_refused(self):
        class Source:
            def read_task_settings(self):
                return None

            def write_task_settings(self, values):
                raise AssertionError("nothing should be written")

        with pytest.raises(tasks.TaskError):
            tasks.save_settings(Source(), {"work_days": ["Sun", "Mon"]})
        with pytest.raises(tasks.TaskError):
            tasks.save_settings(Source(), {"work_days": 5})

    def test_a_revision_count_past_any_number_is_refused(self):
        with pytest.raises(progress.ProgressError):
            progress.clean_revisions("1e999")


class TestSundayWeeks:
    SUNDAY = dt.date(2026, 10, 4)

    def test_a_forecast_made_on_a_sunday_opens_with_a_whole_week(self):
        span = needs.weeks_ahead(self.SUNDAY, 2, cairo())
        assert span[0] == (self.SUNDAY, dt.date(2026, 10, 10))
        assert span[1] == (dt.date(2026, 10, 11), dt.date(2026, 10, 17))
        days = tasks.working_days(*span[0], cairo())
        assert len(days) == 5

    def test_the_forecast_weeks_are_the_units_own(self):
        data = needs.forecast(rows=[], project_rows=[], projects=[], roster=[],
                              config=cairo(), hours_per_mm=185.0, drawings_left={},
                              drafting_hours_per_drawing=None, today=self.SUNDAY,
                              weeks=3)
        assert [w["working_days"] for w in data["weeks"]] == [5, 5, 5]

    def test_a_monday_week_forecast_is_unchanged(self):
        span = needs.weeks_ahead(dt.date(2026, 10, 7), 2, tasks.settings(None))
        assert span[0] == (dt.date(2026, 10, 7), dt.date(2026, 10, 11))

    def test_a_sunday_submission_opens_its_week_in_the_plan(self):
        project = SimpleNamespace(number="P1", name="Quay", status="Active", notes="")
        deliverable = SimpleNamespace(
            row=5, status_date=dt.date(2026, 10, 11), submitted_to_client=None,
            comments_received=None, completed=None, shares={"Ahmed": 1.0})
        metric = {"row": 5, "project_number": "P1", "name": "GA drawings",
                  "credit": 0.0, "actual_hours": 0.0, "phase_weight": 1.0,
                  "ts_phase": None, "first_charge": None, "last_charge": None}
        result = submissions.plan(
            deliverable_rows=[metric], deliverables=[deliverable],
            project_rows=[{"number": "P1", "in_scope": True}], projects=[project],
            rows=[], tasks=[], config=cairo(), hours_per_mm=185.0,
            drawing_counts={}, today=self.SUNDAY)
        assert [w["week"] for w in result["weeks"]] == ["2026-10-11"]


class TestManagersWeek:
    ROSTER = [{"name": "Ahmed", "grade": "manager", "active": True, "team_id": None},
              {"name": "Osama", "grade": "engineer", "active": True, "team_id": None},
              {"name": "Kirolos", "grade": "junior", "active": True, "team_id": None}]

    def test_an_old_holiday_does_not_make_every_week_shorter(self):
        plain = management.Plan(self.ROSTER, [], cairo())
        # Coptic Christmas 2024 fell on a Sunday, in the week the average was
        # once read from.
        with_holiday = management.Plan(self.ROSTER, [],
                                       cairo(holidays={"2024-01-07", "2024-01-01"}))
        assert with_holiday.hours_a_day() == plain.hours_a_day()
        assert with_holiday.taken_a_day() == plain.taken_a_day()


class TestJoiners:
    def test_a_new_joiners_first_week_is_not_a_quiet_fortnight(self):
        config = cairo()
        through = dt.date(2026, 10, 8)                     # a Thursday
        rows = [{"date": through - dt.timedelta(days=n), "engineer": "Kirolos",
                 "hours": 8.5, "overtime_hours": 0.0} for n in range(5)]
        past = checkins.history(rows, ["Kirolos"], config, through=through)
        series = past["people"]["Kirolos"]
        assert series[-1]["load"] == pytest.approx(1.0)
        assert all(w["capacity"] == 0 and w["load"] is None for w in series[:-1])
        assert checkins.signal(series, days_since_break=4)["key"] != "fresh"


class TestLeaveAhead:
    def test_leave_booked_for_a_later_month_does_not_lighten_the_team(self, tmp_path):
        store = TimesheetStore(tmp_path / "unit.timesheets.db")
        store.add_team("quay", "Quay", lead="")
        store.save_person("Ahmed", team_id="quay", grade="engineer")
        store.append("Ahmed", [{"job_number": "20-1", "hours": 185.0,
                                "date": dt.date(2026, month, 10)} for month in (7, 8, 9)])
        store.append("Ahmed", [{"job_number": "LEAVE", "hours": 8.0,
                                "date": dt.date(2026, 12, 20)}])
        data = ppl.balance(store, monthly_capacity=185.0, today=dt.date(2026, 10, 1))
        assert data["months"] == ["2026-07", "2026-08", "2026-09"]
        assert data["teams"][0]["recent_utilisation"] == pytest.approx(1.0)


class TestQuarters:
    def test_a_year_nought_quarter_is_refused_not_a_crash(self):
        with pytest.raises(growth.GrowthError):
            growth.quarter_bounds("0000-Q1")


class TestMemberToday:
    def test_a_members_overdue_count_uses_the_apps_today(self, wb, monkeypatch):
        name = wb.engineer_names()[0]
        wb.save_task({"name": "Check the fender", "assignees": [name],
                      "due": "2035-06-01", "required_hours": 4})
        monkeypatch.setenv("WORKLOAD_TODAY", "2035-07-01")
        from workload_app import member
        assert member._my_tasks(wb, name)["overdue"] >= 1


class TestJoinersPace:
    def test_a_joiners_pace_is_read_from_the_days_since_they_joined(self):
        config = tasks.settings(None)
        last = dt.date(2026, 10, 8)                         # a Thursday
        rows = [{"date": last - dt.timedelta(days=n), "engineer": "Kirolos",
                 "job_number": "20-1", "job_type": "1-Projects", "hours": 8.0}
                for n in range(3)]                          # Tue to Thu
        rows.append({"date": last - dt.timedelta(days=20), "engineer": "Osama",
                     "job_number": "20-1", "job_type": "1-Projects", "hours": 8.0})
        from workload_app import planner
        rates = planner.pace(rows, config)["rates"]
        assert rates[("Kirolos", "20-1")] == pytest.approx(8.0)
