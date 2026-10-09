"""What "busy on real work" on the formation and in Reports counts (2026-10-09).

Project and proposal hours, against the time the person was there to work:
capacity less their leave and holidays. General and department hours are the
gap. Capacity runs to the working days so far, and stops at the last day the
timesheets reach when they stop before today. Days with nothing on the
timesheet are counted apart, as days not filled in yet.
"""

from __future__ import annotations

import datetime as dt

from workload_app import metrics, reports


def _person(report, name="Ahmed"):
    return report.per_engineer[name]


class TestWhatCounts:
    def test_general_and_department_hours_are_the_gap(self, wb):
        before = _person(reports.build(wb, "year", 2026))
        wb.store.append("Ahmed", [{"job_number": "GENERAL.DEPT", "job_type": "4-General",
                                   "hours": 40.0, "date": dt.date(2026, 6, 10)}])
        after = _person(reports.build(wb, "year", 2026))
        assert after["hours"]["general"] == before["hours"]["general"] + 40
        # Booked, so the timesheet is fuller, but it is not real work.
        assert after["utilisation"] == before["utilisation"]
        assert after["timesheet_filled"] > before["timesheet_filled"]
        # Project figures are about projects, so they do not move.
        assert after["actual_mm"] == before["actual_mm"]

    def test_proposals_are_real_work_without_a_register_line(self, wb):
        before = _person(reports.build(wb, "year", 2026))
        wb.store.append("Ahmed", [{"job_number": "BID-ANY", "job_type": "3-Proposals Regular",
                                   "hours": 20.0, "date": dt.date(2026, 6, 10)}])
        after = _person(reports.build(wb, "year", 2026))
        assert after["hours"]["proposals"] == before["hours"]["proposals"] + 20
        assert after["utilisation"] > before["utilisation"]

    def test_leave_comes_off_the_time_there_was_to_work(self, wb):
        person = _person(reports.build(wb, "year", 2026))
        hours = person["hours"]
        assert hours["time_off"] > 0
        assert hours["total"] == round(hours["projects"] + hours["proposals"]
                                       + hours["general"] + hours["time_off"], 1)
        hpm = wb.hours_per_man_month()
        there = person["capacity_to_date_mm"] - hours["time_off"] / hpm
        expected = (hours["projects"] + hours["proposals"]) / hpm / there
        assert abs(person["utilisation"] - expected) < 0.002
        filled = hours["total"] / hpm / person["capacity_to_date_mm"]
        assert abs(person["timesheet_filled"] - filled) < 0.002

    def test_more_leave_never_lowers_it(self, wb):
        code = sorted(wb.non_project_codes())[0]
        before = _person(reports.build(wb, "year", 2026))
        wb.store.append("Ahmed", [{"job_number": code, "hours": 8.5,
                                   "date": dt.date(2026, 6, 10)}])
        after = _person(reports.build(wb, "year", 2026))
        assert abs(after["hours"]["time_off"] - before["hours"]["time_off"] - 8.5) < 0.11
        assert after["utilisation"] >= before["utilisation"]

    def test_the_team_is_everyone_together(self, wb):
        report = reports.build(wb, "year", 2026)
        total = sum(e["hours"]["total"] for e in report.per_engineer.values())
        assert abs(report.team["hours"]["total"] - total) < 0.5
        assert report.team["days_not_filled"] == sum(
            e["days_not_filled"] for e in report.per_engineer.values())


class TestDaysNotFilled:
    """A working day is one most of the team booked on, whatever the week."""

    BOOKED = {
        "Ahmed": {dt.date(2026, 3, d) for d in (1, 2, 3, 4, 5)},
        "Osama": {dt.date(2026, 3, d) for d in (1, 2, 3, 4, 5)},
        "Kirolos": {dt.date(2026, 3, d) for d in (1, 2, 4)},
    }

    def test_an_empty_working_day_is_counted(self):
        days = reports._empty_days(self.BOOKED, dt.date(2026, 3, 1), dt.date(2026, 3, 7))
        assert days == {"Ahmed": 0, "Osama": 0, "Kirolos": 2}

    def test_one_persons_weekend_overtime_flags_nobody(self):
        booked = {name: set(dates) for name, dates in self.BOOKED.items()}
        booked["Ahmed"].add(dt.date(2026, 3, 6))
        days = reports._empty_days(booked, dt.date(2026, 3, 1), dt.date(2026, 3, 7))
        assert days == {"Ahmed": 0, "Osama": 0, "Kirolos": 2}

    def test_nobody_misses_days_before_they_started(self):
        booked = {name: set(dates) for name, dates in self.BOOKED.items()}
        booked["Nour"] = {dt.date(2026, 3, 4), dt.date(2026, 3, 5)}
        days = reports._empty_days(booked, dt.date(2026, 3, 1), dt.date(2026, 3, 7))
        assert days["Nour"] == 0

    def test_it_reaches_the_report(self, wb):
        report = reports.build(wb, "year", 2026)
        for person in report.per_engineer.values():
            assert isinstance(person["days_not_filled"], int)
            assert person["days_not_filled"] >= 0


class TestCountedTo:
    def test_frozen_reports_count_to_the_frozen_day(self, wb):
        assert metrics.counted_to(wb, metrics.TimesheetIndex(wb)) == wb.as_at()

    def test_live_reports_stop_where_the_timesheets_stop(self, wb, monkeypatch):
        wb.save_settings({"as_at": ""})
        monkeypatch.setattr(metrics, "today", lambda: dt.date(2026, 10, 8))
        index = metrics.TimesheetIndex(wb)
        last = max(r["date"] for r in index.rows if r["date"])
        assert last < dt.date(2026, 10, 8)
        assert metrics.counted_to(wb, index) == last
        report = reports.build(wb, "year", 2026)
        assert report.counted_to == last
        assert report.to_dict()["counted_to"] == last.isoformat()

    def test_leave_booked_ahead_does_not_move_it(self, wb, monkeypatch):
        wb.save_settings({"as_at": ""})
        monkeypatch.setattr(metrics, "today", lambda: dt.date(2026, 10, 8))
        before = metrics.counted_to(wb, metrics.TimesheetIndex(wb))
        wb.store.append("Ahmed", [{"job_number": "LEAVE", "job_type": "6-Additives",
                                   "hours": 8.5, "date": dt.date(2026, 10, 1)}])
        assert metrics.counted_to(wb, metrics.TimesheetIndex(wb)) == before

    def test_never_past_today(self, wb, monkeypatch):
        wb.save_settings({"as_at": ""})
        monkeypatch.setattr(metrics, "today", lambda: dt.date(2026, 3, 1))
        assert metrics.counted_to(wb, metrics.TimesheetIndex(wb)) <= dt.date(2026, 3, 1)

    def test_capacity_is_working_days_not_the_whole_year(self, wb):
        # Frozen on 1 September: eight months and a day of a twelve-month year.
        person = _person(reports.build(wb, "year", 2026))
        assert person["capacity_mm"] == 12
        assert 8.0 < person["capacity_to_date_mm"] < 8.1


class TestTheMeaningsOnScreen:
    STATIC = __import__("pathlib").Path(__file__).resolve().parents[1] / "workload_app" / "static"

    def test_both_pages_load_them_after_the_shared_helpers(self):
        for page in ("index.html", "member.html"):
            html = (self.STATIC / page).read_text(encoding="utf-8")
            assert html.index('src="common.js"') < html.index('src="meaning.js"')

    def test_every_name_points_at_a_meaning_with_all_three_parts(self):
        import re
        js = (self.STATIC / "meaning.js").read_text(encoding="utf-8")
        body = js[js.index("const MEANINGS"):js.index("const MEANING_NAMES")]
        keys = set(re.findall(r"^  (\w+): \{", body, re.M))
        named = set(re.findall(r", '(\w+)'\],", js[js.index("const MEANING_NAMES"):]))
        assert named and named <= keys
        for key in keys:
            entry = body[body.index(f"  {key}: {{"):]
            entry = entry[:entry.index("\n  },")]
            assert "what:" in entry and "how:" in entry and "good:" in entry, key
