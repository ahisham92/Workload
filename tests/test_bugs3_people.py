"""Round 3 bug hunt, people side: Check-ins, the weekly report, Outlook busy
times and the day plan. Each test failed before its fix."""

import datetime as dt

from workload_app import busy_calendar, checkins, daily, tasks, weekly
from workload_app import config as cfg

SUN_THU = [6, 0, 1, 2, 3]


def cairo(**extra):
    return dict(tasks.settings(None), work_days=SUN_THU, holidays=set(), away={},
                **extra)


def _rows(name, first, last, config, extra=()):
    out, day = [], first
    while day <= last:
        if tasks.is_working_day(day, config):
            out.append({"engineer": name, "date": day, "hours": 8.0,
                        "job_number": "J-100", "job_type": "1-Projects"})
        day += dt.timedelta(days=1)
    return out + list(extra)


class TestTimesheetGapWithLeaveBookedAhead:
    """Somebody whose timesheets stopped weeks ago, but who has leave booked
    on a timesheet next month, was taken as up to date: no "ask for their
    timesheet", and their last timesheet showed as a date still to come."""

    def test_leave_ahead_does_not_hide_a_missing_timesheet(self):
        config = cairo()
        today = dt.date(2026, 10, 7)
        ahead = {"engineer": "Ahmed", "date": dt.date(2026, 11, 2), "hours": 8.0,
                 "job_number": "LEAVE", "job_type": "3-Leave"}
        rows = (_rows("Osama", dt.date(2026, 8, 2), dt.date(2026, 10, 6), config)
                + _rows("Ahmed", dt.date(2026, 8, 2), dt.date(2026, 9, 10), config,
                        [ahead]))
        view = checkins.build(rows=rows, tasks=[], config=config, project_names={},
                              roster=[{"name": "Ahmed"}, {"name": "Osama"}],
                              today=today)
        ahmed = next(p for p in view["people"] if p["name"] == "Ahmed")
        assert ahmed["last_timesheet"] == "2026-09-10"
        assert "timesheet" in [c["kind"] for c in ahmed["checkpoints"]]

    def test_hours_not_in_yet_are_not_room_to_take_more(self):
        """Weeks with no timesheet from them read as weeks they did nothing:
        "Fresh, can take more", and first in line for new work."""
        config = cairo()
        today = dt.date(2026, 10, 7)
        rows = (_rows("Osama", dt.date(2026, 8, 2), dt.date(2026, 10, 6), config)
                + _rows("Ahmed", dt.date(2026, 8, 2), dt.date(2026, 9, 10), config))
        view = checkins.build(rows=rows, tasks=[], config=config, project_names={},
                              roster=[{"name": "Ahmed"}, {"name": "Osama"}],
                              today=today)
        ahmed = next(p for p in view["people"] if p["name"] == "Ahmed")
        assert ahmed["signal"]["key"] != "fresh"
        assert ahmed["weeks"][-1]["capacity"] == 0.0
        assert ahmed["weeks"][-1]["load"] is None


class TestWeeklyReportDates:
    """The downloaded weekly report wrote "made 2026-10-08": every date
    shown is day first."""

    def test_made_and_timesheets_up_to_are_day_first(self):
        report = weekly.build(
            unit_name="Marine Structures", today=dt.date(2026, 10, 8), config=cairo(),
            checkins={"through": "2026-10-06", "people": [], "weeks": []},
            needs={}, submissions={}, rows=[])
        page = weekly.as_html(report)
        assert "made 08/10/2026" in page
        assert "timesheets up to 06/10/2026" in page
        assert "2026-10-08" not in page

    def test_text_is_still_escaped(self):
        report = weekly.build(
            unit_name="<b>Marine</b>", today=dt.date(2026, 10, 8), config=cairo(),
            checkins={"people": [], "weeks": []}, needs={}, submissions={}, rows=[])
        assert "<b>Marine</b>" not in weekly.as_html(report)


ICS = """BEGIN:VCALENDAR
BEGIN:VTIMEZONE
TZID:Arab Standard Time
BEGIN:STANDARD
DTSTART:16010101T000000
TZOFFSETFROM:+0300
TZOFFSETTO:+0300
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:series-1
X-MICROSOFT-CDO-BUSYSTATUS:BUSY
DTSTART;TZID=Arab Standard Time:20261011T100000
DTEND;TZID=Arab Standard Time:20261011T110000
RRULE:FREQ=WEEKLY;UNTIL=20261025T070000Z;INTERVAL=1;BYDAY=SU;WKST=SU
END:VEVENT
END:VCALENDAR
"""


class TestOutlookSeriesEnd:
    """Outlook ends a series with UNTIL in UTC: the last meeting's start.
    East of UTC that was read as wall-clock time, so the last meeting of
    every series (10:00 Riyadh = 07:00 UTC) was dropped."""

    def test_the_last_meeting_of_a_series_is_kept(self):
        busy = busy_calendar.busy_times(ICS, start=dt.date(2026, 10, 10),
                                        end=dt.date(2026, 11, 5))
        assert [first.date() for first, _ in busy] == [
            dt.date(2026, 10, 11), dt.date(2026, 10, 18), dt.date(2026, 10, 25)]
        assert busy[-1] == (dt.datetime(2026, 10, 25, 10, 0),
                            dt.datetime(2026, 10, 25, 11, 0))

    def test_nothing_after_the_end_is_added(self):
        text = ICS.replace("UNTIL=20261025T070000Z", "UNTIL=20261018T070000Z")
        busy = busy_calendar.busy_times(text, start=dt.date(2026, 10, 10),
                                        end=dt.date(2026, 11, 5))
        assert [first.date() for first, _ in busy] == [
            dt.date(2026, 10, 11), dt.date(2026, 10, 18)]


class TestOverdueWorkOverTheWeekend:
    """Seen on a Friday in Cairo, an overdue task was "today's", and today is
    no working day, so its hours were on no day at all: Check-ins, the
    Planner and the urgent-request preview showed the person free all of
    next week."""

    def _task(self, **extra):
        values = dict(id=7, name="Pile cap check", project_number="J-100",
                      assignees=["Ahmed"], required_hours=6.0,
                      due=dt.date(2026, 10, 6), status=cfg.TASK_STATUSES[0])
        values.update(extra)
        return tasks.Task(**values)

    def test_overdue_hours_land_on_the_next_working_day(self):
        config = cairo()
        friday, sunday = dt.date(2026, 10, 9), dt.date(2026, 10, 11)
        task = self._task()
        assert daily.task_hours_on(task, sunday, friday, config) == 6.0
        assert daily.task_hours_on(task, friday, friday, config) == 0.0

    def test_on_a_working_day_overdue_work_is_still_today(self):
        config = cairo()
        thursday = dt.date(2026, 10, 8)
        task = self._task()
        assert daily.task_hours_on(task, thursday, thursday, config) == 6.0
        assert daily.task_hours_on(task, dt.date(2026, 10, 11), thursday, config) == 0.0

    def test_work_due_on_the_weekend_is_not_lost(self):
        config = cairo()
        friday, saturday = dt.date(2026, 10, 9), dt.date(2026, 10, 10)
        task = self._task(due=saturday)
        assert daily.task_hours_on(task, dt.date(2026, 10, 11), friday, config) == 6.0

    def test_check_ins_free_hours_count_it(self):
        config = cairo()
        friday = dt.date(2026, 10, 9)
        view = checkins.build(rows=[], tasks=[self._task()], config=config,
                              project_names={}, roster=[{"name": "Ahmed"}],
                              today=friday)
        first = view["people"][0]["days"][0]
        assert first["date"] == "2026-10-11"
        assert first["booked"] >= 6.0


class TestLastQuarterOfTheCalendar:
    """?quarter=9999-Q4 on Growth, or a goal for it, gave a server error
    instead of saying it is not a quarter."""

    def test_it_is_refused_plainly(self):
        import pytest
        from workload_app import growth

        with pytest.raises(growth.GrowthError):
            growth.clean_quarter("9999-Q4", dt.date(2026, 10, 8))
        assert growth.quarter_bounds("9999-Q3")[1] == dt.date(9999, 9, 30)
