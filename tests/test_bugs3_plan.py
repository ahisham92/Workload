"""Round 3 bug hunt: planner, tasks, people, needs, derive (synthetic data)."""

from __future__ import annotations

import datetime as dt

import pytest

from workload_app import derive, needs, planner
from workload_app import people as ppl
from workload_app import tasks as task_sheet
from tests.test_people import staff, store  # noqa: F401

ENGINEERS = ["Ahmed", "Osama", "Kirolos"]


def _config():
    config = task_sheet.settings(None)
    config["holidays"] = set()
    return config


# -- tasks -----------------------------------------------------------------

class TestTaskForm:
    def test_a_bad_progress_does_not_hide_the_other_mistakes(self):
        with pytest.raises(task_sheet.TaskError) as caught:
            task_sheet.validate({"name": "", "pro_rata": "half",
                                 "progress_mode": "nonsense"},
                                engineers=ENGINEERS, projects=[])
        errors = caught.value.errors
        assert "A task needs a name." in errors
        assert "Progress has to be a number." in errors
        assert len(errors) >= 3          # the progress mode is named too

    def test_the_same_person_twice_is_one_person(self):
        task = task_sheet.validate(
            {"name": "Check", "assignees": ["Ahmed", "Ahmed"], "required_hours": 6},
            engineers=ENGINEERS, projects=[])
        assert task.assignees == ["Ahmed"]
        assert task.hours_each() == 6

    def test_assignees_that_are_not_a_list_are_refused_not_a_crash(self):
        with pytest.raises(task_sheet.TaskError):
            task_sheet.validate({"name": "Check", "assignees": 5},
                                engineers=ENGINEERS, projects=[])


class _Source:
    def __init__(self):
        self.tasks = []

    def read_tasks(self):
        return list(self.tasks)

    def write_tasks(self, tasks):
        self.tasks = list(tasks)

    def read_task_settings(self):
        return None


class TestMeetingSeries:
    @pytest.mark.parametrize("field,value", [
        ("weeks", "ten"), ("weekday", "Sunday"), ("hours", "an hour"),
        ("hours", "-2"), ("hours", "inf")])
    def test_a_bad_field_is_a_clear_message(self, field, value):
        source = _Source()
        with pytest.raises(task_sheet.TaskError):
            task_sheet.generate_meetings(source, engineers=ENGINEERS,
                                         start=dt.date(2026, 10, 4),
                                         **{field: value})
        assert source.tasks == []

    def test_blank_fields_take_the_settings(self):
        source = _Source()
        result = task_sheet.generate_meetings(
            source, engineers=ENGINEERS, start=dt.date(2026, 10, 4),
            weeks="", weekday="", hours="")
        assert result["added"] == task_sheet.settings(None)["meeting_weeks"]


class TestPinnedToday:
    def test_task_load_and_outlook_and_forecast_use_the_pinned_day(self, monkeypatch):
        monkeypatch.setenv("WORKLOAD_TODAY", "2031-03-04")
        config = _config()
        assert task_sheet.load([], ENGINEERS, config)["from"] == "2031-03-04"
        view = planner.outlook(rows=[], tasks=[], roster=[], config=config,
                               project_names={}, drawings_left={})
        assert view["from"] == "2031-03-04"
        data = needs.forecast(rows=[], project_rows=[], projects=[], roster=[],
                              config=config, hours_per_mm=185, drawings_left={},
                              drafting_hours_per_drawing=None)
        assert data["today"] == "2031-03-04"


# -- planner ---------------------------------------------------------------

def _booked(name, job, hours, last, days=14):
    return [{"engineer": name, "job_number": job, "job_type": "1-Projects",
             "hours": hours, "date": last - dt.timedelta(days=i)}
            for i in range(days)]


class TestPlannerMoves:
    def test_a_share_that_is_not_a_number_is_refused(self):
        with pytest.raises(planner.PlanError):
            planner.clean_moves([{"kind": "project", "project": "P-1",
                                  "from": "Ahmed", "to": "Osama", "share": "nan"}],
                                people=ENGINEERS, tasks=[])

    def test_work_is_never_suggested_for_somebody_who_has_left(self):
        today = dt.date(2026, 10, 5)
        last = today - dt.timedelta(days=1)
        rows = (_booked("Ahmed", "P-1", 12.0, last)
                + _booked("Osama", "P-2", 1.0, last))
        roster = [
            {"name": "Ahmed", "grade": "engineer", "active": True, "team_id": None},
            {"name": "Osama", "grade": "engineer", "active": False, "team_id": None},
        ]
        suggested = planner.suggest(rows=rows, tasks=[], roster=roster,
                                    config=_config(), project_names={},
                                    drawings_left={}, today=today)
        assert all(move["to"] != "Osama" for move in suggested)


# -- staffing forecast -----------------------------------------------------

class TestForecastData:
    def test_leave_booked_ahead_is_not_the_newest_data(self):
        today = dt.date(2026, 10, 8)
        rows = [
            {"engineer": "Ahmed", "job_number": "P-1", "job_type": "1-Projects",
             "hours": 8.0, "date": dt.date(2026, 10, 6)},
            {"engineer": "Ahmed", "job_number": "LEAVE", "job_type": "5-Leave",
             "hours": 8.0, "date": dt.date(2026, 12, 20)},
        ]
        data = needs.forecast(rows=rows, project_rows=[], projects=[], roster=[],
                              config=_config(), hours_per_mm=185, drawings_left={},
                              drafting_hours_per_drawing=None, today=today)
        assert data["data_through"] == "2026-10-06"


# -- projects set up from timesheets --------------------------------------

class TestDerivedProposals:
    def test_leave_in_january_does_not_finish_this_years_proposals(self, monkeypatch):
        monkeypatch.setenv("WORKLOAD_TODAY", "2026-10-08")
        rows = [
            {"engineer": "Ahmed", "job_number": "PROP", "job_type": "3-Proposals",
             "hours": 8.0, "date": dt.date(2026, 9, 10)},
            {"engineer": "Ahmed", "job_number": "LEAVE", "job_type": "5-Leave",
             "hours": 8.0, "date": dt.date(2027, 1, 5)},
        ]
        plans = derive.plan_projects(
            rows, existing=[], engineers=["Ahmed"],
            credit_steps={"PP": [{"step_no": 1}, {"step_no": 2}]}, hours_per_mm=185)
        proposals = next(p for p in plans if p["project"]["number"] == "Proposals 26")
        assert proposals["project"]["status"] == "Active"
        assert proposals["deliverables"][0]["actual_finish"] is None


# -- resourcing ------------------------------------------------------------

class TestJoiners:
    def test_months_before_somebody_joined_are_not_idle_months(self, store):  # noqa: F811
        staff(store, ("Ahmed", "quay", "engineer"), ("Kirolos", "quay", "engineer"))
        for month in (8, 9, 10):
            store.append("Ahmed", [{"job_number": "20-1", "hours": 185.0,
                                    "date": dt.date(2026, month, 10)}])
        store.append("Kirolos", [{"job_number": "20-1", "hours": 185.0,
                                  "date": dt.date(2026, 10, 10)}])
        result = ppl.balance(store, monthly_capacity=185.0,
                             today=dt.date(2026, 10, 31))
        kirolos = next(m for m in result["members"] if m["name"] == "Kirolos")
        assert kirolos["recent_utilisation"] == 1.0
        assert result["teams"][0]["recent_utilisation"] == 1.0
        assert not any(f["kind"] == "spare" for f in result["findings"])


class TestPortfolioMap:
    def test_leave_booked_ahead_does_not_push_recent_months_out(self, store):  # noqa: F811
        for month in (7, 8, 9):
            store.append("Ahmed", [{"job_number": "20-1", "hours": 100.0,
                                    "date": dt.date(2026, month, 10)}])
        store.append("Ahmed", [{"job_number": "LEAVE", "hours": 8.0,
                                "date": dt.date(2026, month, 3)} for month in (11, 12)])
        data = ppl.portfolio_map(store, [{"number": "20-1", "remaining_mm": 2.0}],
                                 today=dt.date(2026, 10, 8))
        circle = next(c for c in data["projects"] if c["number"] == "20-1")
        assert circle["recent_hours"] == 300.0
        assert data["recent_months"] == ["2026-07", "2026-08", "2026-09"]
