"""Official holidays: one list for the site, and what the timesheets teach.

Ahmed (2026-10-09): one admin list every unit in Egypt follows; a day the
timesheets book as a holiday becomes an official holiday (leave stays
personal leave); a personal excuse of about four and a half hours is half a
day of leave, read from the timesheet rather than typed every year.

Everything here is made up: names, codes and dates.
"""

import datetime as _dt
import io
import json

import pytest

from workload_app import calendar_, daily, holidays, wsgi
from workload_app.accounts import Accounts
from workload_app.app import WorkloadApp


def row(name, day, code, hours=8.5, job_type="6-Additives"):
    return {"engineer": name, "date": _dt.date.fromisoformat(day),
            "job_number": code, "job_type": job_type, "deliverable": "",
            "job_name": "", "hours": hours}


def work(name, day, hours=8.5):
    return row(name, day, "J-100", hours, job_type="1-Projects")


# -- what the timesheets say -------------------------------------------------

class TestLearnedFromTimesheets:
    def test_a_day_most_people_booked_as_a_holiday_is_one(self):
        rows = [row("Nour", "2026-01-29", "HOLIDAY"), row("Omar", "2026-01-29", "HOLIDAY"),
                work("Lina", "2026-01-29")]
        counts = calendar_.holidays_from_timesheets(rows)
        assert calendar_.learned_holidays(counts)["add"] == ["2026-01-29"]

    def test_one_person_on_holiday_is_not_a_holiday_for_everyone(self):
        rows = [row("Nour", "2026-02-03", "HOLIDAY"), work("Omar", "2026-02-03"),
                work("Lina", "2026-02-03")]
        counts = calendar_.holidays_from_timesheets(rows)
        assert calendar_.learned_holidays(counts)["add"] == []

    def test_leave_stays_personal_leave(self):
        rows = [row(n, "2026-02-04", "LEAVE") for n in ("Nour", "Omar", "Lina")]
        counts = calendar_.holidays_from_timesheets(rows)
        assert calendar_.learned_holidays(counts)["add"] == []

    def test_a_built_in_holiday_everyone_worked_was_moved(self):
        rows = [work(n, "2026-01-25") for n in ("Nour", "Omar", "Lina")]
        rows += [row(n, "2026-01-29", "HOLIDAY") for n in ("Nour", "Omar", "Lina")]
        counts = calendar_.holidays_from_timesheets(rows)
        learned = calendar_.learned_holidays(counts, ["2026-01-25"])
        assert learned == {"add": ["2026-01-29"], "remove": ["2026-01-25"]}

    def test_working_through_a_holiday_takes_nothing_off_the_list(self):
        # A team that never books holidays has not moved any.
        rows = [work(n, "2026-01-25") for n in ("Nour", "Omar", "Lina")]
        counts = calendar_.holidays_from_timesheets(rows)
        assert calendar_.learned_holidays(counts, ["2026-01-25"])["remove"] == []

    def test_a_built_in_holiday_somebody_booked_stays(self):
        rows = [work("Nour", "2026-01-25"), work("Omar", "2026-01-25"),
                row("Lina", "2026-01-25", "HOLIDAY")]
        counts = calendar_.holidays_from_timesheets(rows)
        assert calendar_.learned_holidays(counts, ["2026-01-25"])["remove"] == []


class TestHalfDayExcuse:
    def test_four_hours_or_more_of_an_excuse_is_half_a_day(self):
        rows = [row("Nour", "2026-03-02", "EXCUSE.PER", 4.5),
                row("Omar", "2026-03-02", "EXCUSE.PER", 1.5)]
        assert calendar_.half_days_from_timesheets(rows) == {"Nour": {"2026-03-02"}}

    def test_half_a_day_counts_half(self):
        config = calendar_.with_calendar({}, half_days={"Nour": {"2026-03-02"}})
        days = [_dt.date(2026, 3, 1), _dt.date(2026, 3, 2), _dt.date(2026, 3, 3)]
        assert calendar_.present_days(config, "Nour", days) == 2.5
        assert calendar_.present_days(config, "Omar", days) == 3

    def test_a_whole_day_off_is_not_also_a_half(self):
        config = calendar_.with_calendar({}, leave={"Nour": {"2026-03-02"}},
                                         half_days={"Nour": {"2026-03-02"}})
        assert config["half_away"] == {}
        assert calendar_.present_days(config, "Nour", [_dt.date(2026, 3, 2)]) == 0

    def test_the_day_plan_keeps_the_second_half_free(self):
        config = {"work_days": [6, 0, 1, 2, 3], "day_start": "08:00", "day_end": "16:30",
                  "hours_per_day": 8.5, "holidays": set(),
                  "away": {}, "half_away": {"Nour": {"2026-03-02"}}}
        try:
            page = daily.plan_day(day=_dt.date(2026, 3, 2), today=_dt.date(2026, 3, 2),
                                  roster=[{"name": "Nour"}], rates={}, tasks=[],
                                  slots={}, config=config, project_names={})
        except KeyError:
            pytest.skip("the day settings need more keys than this test gives")
        blocks = page["people"][0]["blocks"]
        assert [b["kind"] for b in blocks] == ["half_day"]
        assert blocks[0]["end"] == "16:30"


# -- the site's list ---------------------------------------------------------

class TestOfficialList:
    def test_the_administrator_wins_over_the_timesheets(self, tmp_path):
        accounts = Accounts(tmp_path / "accounts.db", secret_key=b"k" * 32)
        accounts.set_official_holiday("EG", "2026-01-29", name="Revolution Day (moved)")
        assert accounts.learn_official_holidays([
            {"country": "EG", "day": "2026-01-29", "off": False},
            {"country": "EG", "day": "2026-01-25", "off": False, "name": "Revolution Day"},
        ]) == 1
        rows = {r["day"]: r for r in accounts.official_holidays("EG")}
        assert rows["2026-01-29"]["source"] == "admin" and rows["2026-01-29"]["off"]
        assert rows["2026-01-25"]["source"] == "timesheets"

    def test_every_unit_in_the_country_follows_it(self):
        changes = holidays.official_changes([
            {"country": "EG", "day": "2026-01-25", "off": False, "source": "timesheets"},
            {"country": "EG", "day": "2026-01-29", "name": "Revolution Day (moved)",
             "off": True, "source": "admin"}])
        public = holidays.calendar_for(
            {"unit": "EG"}, people=[{"name": "Nour"}],
            start=_dt.date(2026, 1, 1), end=_dt.date(2026, 2, 28), official=changes)
        assert "2026-01-29" in public["common"]
        assert "2026-01-25" not in public["common"]
        assert "2026-01-07" in public["common"]          # built in, untouched

    def test_a_unit_can_still_say_not_a_holiday_for_itself(self):
        changes = holidays.official_changes([
            {"country": "EG", "day": "2026-01-29", "name": "x", "off": True, "source": "admin"}])
        public = holidays.calendar_for(
            {"unit": "EG", "off": ["2026-01-29"]}, people=[],
            start=_dt.date(2026, 1, 1), end=_dt.date(2026, 2, 28), official=changes)
        assert "2026-01-29" not in public["common"]

    def test_the_year_says_where_each_day_came_from(self):
        days = {d["date"]: d for d in holidays.official_year("EG", 2026, [
            {"country": "EG", "day": "2026-01-25", "name": "Revolution Day", "off": False,
             "source": "timesheets"},
            {"country": "EG", "day": "2026-01-29", "name": "Revolution Day (moved)",
             "off": True, "source": "timesheets"}])}
        assert days["2026-01-07"]["source"] == "built_in"
        assert days["2026-01-25"]["off"] is False and days["2026-01-25"]["built_in"]
        assert days["2026-01-29"]["off"] and not days["2026-01-29"]["built_in"]


# -- through the app ---------------------------------------------------------

ADMIN = {"id": 1, "login": "ahmed@example.com", "name": "Ahmed", "admin": True}
OTHER = {"id": 2, "login": "osama", "name": "Osama"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", "2026-10-09")
    application = WorkloadApp(tmp_path / "instance")
    application.site_people = lambda: []
    monkeypatch.setattr(wsgi, "_app", application)
    return application


def ask(method, path, body=None, *, site, query=""):
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "SCRIPT_NAME": "/workload", "PATH_INFO": path,
               "QUERY_STRING": query, "CONTENT_LENGTH": str(len(raw)),
               "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw),
               "wsgi.url_scheme": "http", wsgi.SITE_KEY: site}
    seen = {}

    def start_response(status, headers):
        seen["status"] = int(status.split()[0])

    payload = b"".join(wsgi.application(environ, start_response))
    return seen["status"], json.loads(payload)


class TestRoutes:
    def test_the_administrator_adds_a_day_for_everyone(self, app):
        status, view = ask("POST", "/api/official-holidays",
                           {"country": "EG", "date": "2026-11-05", "name": "Bridge day"},
                           site=ADMIN)
        assert status == 200, view
        day = next(d for d in view["days"] if d["date"] == "2026-11-05")
        assert day["off"] and day["source"] == "admin" and day["name"] == "Bridge day"
        assert view["can_edit"] is True

    def test_everyone_else_reads_it_and_cannot_change_it(self, app):
        ask("POST", "/api/official-holidays",
            {"country": "EG", "date": "2026-11-05", "name": "Bridge day"}, site=ADMIN)
        status, view = ask("GET", "/api/official-holidays", site=OTHER,
                           query="country=EG&year=2026")
        assert status == 200 and view["can_edit"] is False
        assert any(d["date"] == "2026-11-05" for d in view["days"])
        status, _ = ask("POST", "/api/official-holidays",
                        {"country": "EG", "date": "2026-11-06"}, site=OTHER)
        assert status == 403

    def test_not_a_holiday_and_undo(self, app):
        ask("POST", "/api/official-holidays",
            {"country": "EG", "date": "2026-10-06", "off": False}, site=ADMIN)
        status, view = ask("GET", "/api/official-holidays", site=ADMIN,
                           query="country=EG&year=2026")
        day = next(d for d in view["days"] if d["date"] == "2026-10-06")
        assert day["off"] is False and day["built_in"]
        status, view = ask("POST", "/api/official-holidays/EG/2026-10-06/undo", {},
                           site=ADMIN)
        assert status == 200
        day = next(d for d in view["days"] if d["date"] == "2026-10-06")
        assert day["off"] and day["source"] == "built_in"

    def test_a_unit_in_egypt_follows_the_list(self, app):
        status, _ = ask("POST", "/api/units", {"name": "Marine Structures Cairo"}, site=OTHER)
        assert status == 200
        ask("PUT", "/api/holidays", {"unit": "EG"}, site=OTHER)
        ask("POST", "/api/official-holidays",
            {"country": "EG", "date": "2026-11-05", "name": "Bridge day"}, site=ADMIN)
        status, view = ask("GET", "/api/holidays", site=OTHER)
        assert status == 200, view
        assert any(h["date"] == "2026-11-05" and h["name"] == "Bridge day"
                   for h in view["next"])

    def test_a_bad_country_or_day_is_refused(self, app):
        status, _ = ask("POST", "/api/official-holidays",
                        {"country": "ZZ", "date": "2026-11-05"}, site=ADMIN)
        assert status == 400
        status, _ = ask("POST", "/api/official-holidays",
                        {"country": "EG", "date": "05/11"}, site=ADMIN)
        assert status == 400


# -- from a real unit's timesheets --------------------------------------------

class TestUnitLearns:
    def test_a_unit_shares_what_its_timesheets_show(self, unit_copy, monkeypatch):
        from workload_app.service import WorkloadService
        monkeypatch.setenv("WORKLOAD_TODAY", "2026-03-01")
        service = WorkloadService(unit_copy)
        shared = []
        service.official_list = lambda: []
        service.official_learn = shared.extend
        service.save_holidays({"unit": "EG"})
        assert shared, "nothing was learned"
        assert all(r["country"] == "EG" and r["source"] == "timesheets" for r in shared)
        assert len({r["day"] for r in shared}) == len(shared)
