"""What the utilisation on the formation and in Reports counts (2026-10-09).

Every hour on the timesheet counts: projects, proposals, general and
department codes, and time off, so a full timesheet is 100%. Capacity runs to
the working days so far, and stops at the last day the timesheets reach when
they stop before today.
"""

from __future__ import annotations

import datetime as dt

from workload_app import metrics, reports


def _person(report, name="Ahmed"):
    return report.per_engineer[name]


class TestWhatCounts:
    def test_general_and_department_hours_count(self, wb):
        before = _person(reports.build(wb, "year", 2026))
        wb.store.append("Ahmed", [{"job_number": "GENERAL.DEPT", "job_type": "4-General",
                                   "hours": 40.0, "date": dt.date(2026, 6, 10)}])
        after = _person(reports.build(wb, "year", 2026))
        assert after["hours"]["general"] == before["hours"]["general"] + 40
        assert after["utilisation"] > before["utilisation"]
        # Project figures are about projects, so they do not move.
        assert after["actual_mm"] == before["actual_mm"]

    def test_proposals_count_without_a_register_line(self, wb):
        before = _person(reports.build(wb, "year", 2026))
        wb.store.append("Ahmed", [{"job_number": "BID-ANY", "job_type": "3-Proposals Regular",
                                   "hours": 20.0, "date": dt.date(2026, 6, 10)}])
        after = _person(reports.build(wb, "year", 2026))
        assert after["hours"]["proposals"] == before["hours"]["proposals"] + 20
        assert after["utilisation"] > before["utilisation"]

    def test_time_off_is_time_accounted_for(self, wb):
        person = _person(reports.build(wb, "year", 2026))
        hours = person["hours"]
        assert hours["time_off"] > 0
        assert hours["total"] == round(hours["projects"] + hours["proposals"]
                                       + hours["general"] + hours["time_off"], 1)
        hpm = wb.hours_per_man_month()
        expected = hours["total"] / hpm / person["capacity_to_date_mm"]
        assert abs(person["utilisation"] - expected) < 0.002

    def test_the_team_is_everyone_together(self, wb):
        report = reports.build(wb, "year", 2026)
        total = sum(e["hours"]["total"] for e in report.per_engineer.values())
        assert abs(report.team["hours"]["total"] - total) < 0.5


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
