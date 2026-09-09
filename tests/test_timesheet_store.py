"""Timesheet rows in a database rather than in the workbook.

The workbook's consolidated sheet stops at a fixed row and every SUMIFS in the
file stops there too, so it had two ceilings: how many rows, and -- through the
calendar rows and share columns -- how many people. Both are gone here, and
these tests say so in numbers.
"""

import datetime as dt

import pytest

from workload_app.timesheet_store import TimesheetStore


@pytest.fixture
def store(tmp_path):
    return TimesheetStore(tmp_path / "unit.timesheets.db")


def rows(n, *, person="Ahmed", job="20-1234", start=dt.date(2026, 1, 1)):
    return [{"job_type": "1-Projects", "job_number": job, "job_name": "Port Deck",
             "full_name": f"{person} Mitwally", "date": start + dt.timedelta(days=i % 300),
             "phase": 4, "regular_hours": 8, "overtime_hours": 0, "hours": 8}
            for i in range(n)]


class TestHoldingRows:
    def test_it_starts_empty(self, store):
        assert store.is_empty() and store.count() == 0

    def test_replace_is_the_monthly_routine(self, store):
        store.replace("Ahmed", rows(10))
        store.replace("Ahmed", rows(4))
        assert store.count() == 4

    def test_append_adds_to_what_is_there(self, store):
        store.replace("Ahmed", rows(10))
        store.append("Ahmed", rows(5))
        assert store.count() == 15

    def test_one_persons_import_leaves_another_alone(self, store):
        store.replace("Ahmed", rows(10))
        store.replace("Osama", rows(3, person="Osama"))
        store.replace("Ahmed", rows(2))
        assert store.counts() == {"Ahmed": 2, "Osama": 3}

    def test_far_past_what_the_workbook_could_hold(self, store):
        """25,000 was the workbook's cap for the whole unit; this is one person."""
        store.replace("Ahmed", rows(30_000))
        assert store.count() == 30_000
        assert len(store.all_rows()) == 30_000

    def test_eighty_people_is_not_a_problem(self, store):
        for number in range(80):
            store.replace(f"Engineer {number}", rows(200, person=f"E{number}"))
        assert store.count() == 16_000
        assert len(store.people()) == 80


class TestWhatItCanAnswer:
    def test_a_row_comes_back_in_the_shape_the_calculations_want(self, store):
        store.replace("Ahmed", rows(1))
        row = store.all_rows()[0]
        assert row["engineer"] == "Ahmed"
        assert row["date"] == dt.date(2026, 1, 1)
        assert row["hours"] == 8.0 and row["phase"] == 4

    def test_dates_are_kept_as_dates_however_they_arrive(self, store):
        store.replace("Ahmed", [
            {"job_number": "1", "date": dt.date(2026, 3, 4), "hours": 1},
            {"job_number": "1", "date": "2026-03-05", "hours": 1},
            {"job_number": "1", "date": dt.datetime(2026, 3, 6, 9, 0), "hours": 1},
            {"job_number": "1", "date": None, "hours": 1},
        ])
        assert store.date_range() == (dt.date(2026, 3, 4), dt.date(2026, 3, 6))

    def test_it_reports_the_job_numbers_it_has_seen(self, store):
        store.replace("Ahmed", rows(5, job="20-1234"))
        store.append("Ahmed", rows(2, job="21-0007"))
        store.replace("Osama", rows(3, job="20-1234", person="Osama"))
        seen = {job["job_number"]: job for job in store.jobs_seen()}
        assert seen["20-1234"]["entries"] == 8
        assert seen["20-1234"]["people"] == 2
        assert seen["20-1234"]["hours"] == 64.0
        assert seen["21-0007"]["entries"] == 2
        # Ranked by the effort behind them, so the real projects come first.
        assert [j["job_number"] for j in store.jobs_seen()] == ["20-1234", "21-0007"]

    def test_the_name_people_typed_most_often_wins(self, store):
        store.replace("Ahmed", [
            {"job_number": "20-1", "job_name": "Port Deck Demolition", "hours": 1},
            {"job_number": "20-1", "job_name": "Port Deck Demolition", "hours": 1},
            {"job_number": "20-1", "job_name": "port deck", "hours": 1},
        ])
        assert store.jobs_seen()[0]["job_name"] == "Port Deck Demolition"

    def test_renaming_a_person_keeps_their_rows(self, store):
        store.replace("Kirolos", rows(6, person="Kirolos"))
        store.rename_person("Kirolos", "Kirolos Nabil")
        assert store.counts() == {"Kirolos Nabil": 6}

    def test_removing_a_person_takes_their_rows(self, store):
        store.replace("Ahmed", rows(3))
        store.replace("Osama", rows(3, person="Osama"))
        store.forget("Osama")
        assert store.counts() == {"Ahmed": 3}


class TestSettings:
    def test_a_setting_survives_a_reopen(self, store, tmp_path):
        store.set_setting("start_date", "2025-01-01")
        again = TimesheetStore(tmp_path / "unit.timesheets.db")
        assert again.setting("start_date") == "2025-01-01"

    def test_an_unset_key_gives_the_default(self, store):
        assert store.setting("start_date") is None
        assert store.setting("start_date", "2020-01-01") == "2020-01-01"

    def test_clearing_one(self, store):
        store.set_setting("start_date", "2025-01-01")
        store.set_setting("start_date", None)
        assert store.settings() == {}
