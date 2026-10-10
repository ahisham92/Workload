"""Check-ins: free hours, who needs to ease off, and what to ask each person.

Built from timesheet exports alone against a blank unit, so like
``test_planning`` these need no private workbook.
"""

import base64
import datetime as dt
import io

import pytest

from workload_app import checkins, storage
from workload_app.service import WorkloadService

openpyxl = pytest.importorskip("openpyxl")

HEADERS = ["Job Type", "JobNumber", "FullName", "Grade", "Date", "Phase",
           "RegularHours", "OvertimeHours", "TotalHours", "JobStatus",
           "DeliverableDescription", "CurrentUnitDesc"]

TODAY = dt.date(2026, 10, 7)          # a Wednesday
LAST = dt.date(2026, 10, 2)           # the newest timesheet, a Friday


def export(name, rows):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Timesheet export"])
    sheet.append([])
    sheet.append(HEADERS)
    for item in rows:
        sheet.append([item.get(h) for h in HEADERS])
    buffer = io.BytesIO()
    book.save(buffer)
    return {"filename": f"{name}.xlsx",
            "content_base64": base64.b64encode(buffer.getvalue()).decode()}


def weekdays(count, last=LAST):
    out, day = [], last
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day -= dt.timedelta(days=1)
    return sorted(out)


def booking(full, job, hours_a_day, *, overtime=0.0, days=30, last=LAST,
            job_type="1-Projects", deliverable="Detailed Design"):
    return [{"Job Type": job_type, "JobNumber": job, "FullName": full,
             "Grade": "P2", "Date": day, "Phase": 1,
             "RegularHours": hours_a_day - overtime, "OvertimeHours": overtime,
             "TotalHours": hours_a_day, "JobStatus": "Active",
             "DeliverableDescription": deliverable, "CurrentUnitDesc": "BERTHS"}
            for day in weekdays(days, last)]


def leave(full, days):
    return [{"Job Type": "3-Leave", "JobNumber": "LEAVE", "FullName": full,
             "Grade": "P2", "Date": day, "Phase": "", "RegularHours": 8.5,
             "OvertimeHours": 0, "TotalHours": 8.5, "JobStatus": "",
             "DeliverableDescription": "Annual leave", "CurrentUnitDesc": "BERTHS"}
            for day in days]


def team():
    back = weekdays(4)                      # the last four working days
    return [
        # Osama has been doing eleven hours a day for six weeks.
        export("osama", booking("Osama Ashdown", "N1-0100D", 11, overtime=2.5)),
        # Kirolos has been on three hours a day: plenty of room.
        export("kirolos", booking("Kirolos Northwind", "N1-0100D", 3)),
        # Mariam is at her hours, then four days' leave to end the fortnight.
        export("mariam", booking("Mariam Ashgrove", "N2-0100D", 8.5, last=back[0]
                                 - dt.timedelta(days=1))
               + leave("Mariam Ashgrove", back)),
    ]


@pytest.fixture
def unit(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
    service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
    service.import_exports(team())
    return service


def person(view, name):
    return next(p for p in view["people"] if p["name"] == name)


class TestHowLoaded:
    def test_weeks_well_over_their_hours_means_ease_off(self, unit):
        osama = person(unit.checkins(), "Osama")
        assert osama["signal"]["key"] == "rest"
        assert osama["signal"]["load"] > checkins.REST_LOAD
        assert osama["signal"]["weeks_over"] >= checkins.REST_STREAK
        assert any(c["kind"] == "rest" and c["level"] == "now"
                   for c in osama["checkpoints"])

    def test_a_quiet_fortnight_means_they_can_take_more(self, unit):
        kirolos = person(unit.checkins(), "Kirolos")
        assert kirolos["signal"]["key"] == "fresh"
        assert kirolos["signal"]["recent_load"] < checkins.QUIET_LOAD

    def test_back_from_leave_is_fresh_not_quiet(self, unit):
        mariam = person(unit.checkins(), "Mariam")
        assert mariam["signal"]["key"] == "fresh"
        assert mariam["signal"]["days_off_lately"] >= checkins.BACK_FROM_LEAVE_DAYS
        assert "back from" in mariam["signal"]["reasons"][0]
        # Days away are neither hours available nor hours missing.
        last = mariam["weeks"][-1]
        assert last["days_off"] >= 1 and last["load"] in (None, pytest.approx(
            last["hours"] / last["capacity"], abs=1e-3))

    def test_the_overloaded_come_first(self, unit):
        names = [p["name"] for p in unit.checkins()["people"]]
        assert names[0] == "Osama"

    def test_signal_rules(self):
        week = lambda load, overtime=0.0, off=0: {  # noqa: E731
            "week": "2026-09-07", "hours": 42.5 * load, "overtime": overtime,
            "capacity": 42.5, "days_off": off, "load": load}
        steady = checkins.signal([week(0.95)] * 8, days_since_break=20)
        assert steady["key"] == "steady"
        busy = checkins.signal([week(1.02)] * 8, days_since_break=20)
        assert busy["key"] == "busy"
        long_haul = checkins.signal([week(0.95)] * 8, days_since_break=100)
        assert long_haul["key"] == "busy"
        assert "no day off" in long_haul["reasons"][-1]
        overtime = checkins.signal([week(1.0, overtime=9)] * 8, days_since_break=5)
        assert overtime["key"] == "rest"


class TestFreeHours:
    def test_free_hours_follow_the_planners_day(self, unit):
        view = unit.checkins()
        kirolos = person(view, "Kirolos")
        osama = person(view, "Osama")
        assert len(view["days"]) == checkins.AHEAD_DAYS
        assert kirolos["free_week"] > 0 and osama["free_week"] == 0
        today = unit.day_plan({})["days"][0]
        planned = next(p for p in today["people"] if p["name"] == "Kirolos")
        assert kirolos["days"][0]["free"] == planned["free_hours"]

    def test_the_next_job_goes_to_who_has_room_and_is_not_overloaded(self, unit):
        view = unit.checkins()
        names = [p["name"] for p in view["can_take"]]
        assert "Kirolos" in names and "Osama" not in names
        assert view["free_week"] == pytest.approx(
            sum(p["free_week"] for p in view["people"]), abs=0.2)


class TestCheckpoints:
    def task(self, unit, **extra):
        body = {"name": "Pile calcs", "project_number": "N1-0100D",
                "required_hours": 10, "status": "In progress", **extra}
        unit.add_task(body)

    def test_blocked_overdue_due_and_over_hours(self, unit):
        self.task(unit, name="Blocked one", assignees=["Kirolos"], status="Blocked",
                  due="2026-10-20")
        self.task(unit, name="Late one", assignees=["Kirolos"], due="2026-10-05")
        self.task(unit, name="Soon one", assignees=["Kirolos"], due="2026-10-08",
                  status="Not started")
        self.task(unit, name="Long one", assignees=["Kirolos"], due="2026-10-30",
                  actual_hours=14)
        points = person(unit.checkins(), "Kirolos")["checkpoints"]
        kinds = {c["kind"]: c for c in points}
        assert kinds["blocked"]["level"] == "now"
        assert "Blocked one" in kinds["blocked"]["text"]
        assert kinds["overdue"]["level"] == "now"
        assert "Late one" in kinds["overdue"]["text"]
        assert kinds["due"]["level"] == "now"          # not started, due tomorrow
        assert "has not started" in kinds["due"]["text"]
        assert "14 h of the 10 h" in kinds["over_hours"]["text"]
        levels = [c["level"] for c in points]
        assert levels == sorted(levels, key=checkins.LEVELS.index)

    def test_done_tasks_and_other_peoples_are_left_out(self, unit):
        self.task(unit, name="Done one", assignees=["Kirolos"], status="Done",
                  due="2026-10-01")
        self.task(unit, name="Not mine", assignees=["Osama"], status="Blocked")
        texts = " ".join(c["text"] for c in person(unit.checkins(), "Kirolos")["checkpoints"])
        assert "Done one" not in texts and "Not mine" not in texts

    def test_a_timesheet_that_stopped_arriving(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
        service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
        service.import_exports([
            export("a", booking("Osama Ashdown", "N1-0100D", 8)),
            export("b", booking("Kirolos Northwind", "N1-0100D", 8,
                                last=LAST - dt.timedelta(days=14))),
        ])
        points = person(service.checkins(), "Kirolos")["checkpoints"]
        assert any(c["kind"] == "timesheet" for c in points)

    def test_leave_coming_up_asks_for_a_handover(self, unit):
        unit.add_absence({"person": "Osama", "start": "2026-10-12",
                          "end": "2026-10-14", "reason": "leave"})
        osama = person(unit.checkins(), "Osama")
        away = next(c for c in osama["checkpoints"] if c["kind"] == "away")
        assert "Away 3 day(s)" in away["text"] and "handover" in away["text"]
        assert sum(1 for d in osama["days"] if d["away"]) == 3


class TestWeeks:
    def test_a_sunday_week_starts_on_sunday(self):
        config = {"work_days": [6, 0, 1, 2, 3]}
        assert checkins.week_start(dt.date(2026, 10, 7), config) == dt.date(2026, 10, 4)
        assert checkins.week_start(dt.date(2026, 10, 4), config) == dt.date(2026, 10, 4)
        assert checkins.week_start(dt.date(2026, 10, 3), config) == dt.date(2026, 9, 27)
        assert checkins.week_start(dt.date(2026, 10, 7),
                                   {"work_days": [0, 1, 2, 3, 4]}) == dt.date(2026, 10, 5)


class TestSubmissionPreparation:
    """A submission's daily preparation steps are asked about as one line."""

    @staticmethod
    def steps(*, done=0, blocked=False):
        from workload_app.tasks import Task
        days = [dt.date(2026, 10, d) for d in (4, 5, 6, 7, 8, 11)]
        out = []
        for i, day in enumerate(days, start=1):
            out.append(Task(
                id=i, name=f"Berth 9 drawings — submission day {i} of 6",
                project_number="25-0100", deliverable_row=7,
                deliverable_name="Berth 9 drawings", assignees=["Kirolos"],
                required_hours=2.0, start=day, due=day, kind="Submission",
                series="submission:7",
                status=("Done" if i <= done else
                        "Blocked" if blocked and i == done + 1 else "Not started")))
        return out

    def points(self, tasks, today=TODAY):
        return checkins._submission_points("Kirolos", tasks, today, today + dt.timedelta(days=5))

    def test_behind_is_one_line_not_one_per_day(self):
        points = self.points(self.steps())
        assert len(points) == 1
        text = points[0]["text"]
        assert "day 1 of 6" not in text
        assert "Berth 9 drawings (25-0100) submission is due Sun 11 Oct" in text
        assert "0 h of 12 h of preparation done, 6 h should be by now" in text
        assert points[0]["level"] == "now"

    def test_on_track_says_nothing(self):
        assert self.points(self.steps(done=3)) == []

    def test_a_blocked_step_is_raised(self):
        points = self.points(self.steps(done=3, blocked=True))
        assert [p["kind"] for p in points] == ["blocked"]

    def test_a_finished_run_says_nothing(self):
        assert self.points(self.steps(done=6), today=dt.date(2026, 10, 20)) == []

    def test_the_steps_never_show_one_by_one(self):
        points = checkins.checkpoints(
            "Kirolos", tasks=self.steps(), today=TODAY, config=storage_config(),
            load={"key": "steady", "reasons": [], "days_since_break": None},
            last_row=None, team_last=None, ahead=[])
        assert sum(1 for p in points if "Berth 9" in p["text"]) == 1


class TestSentSubmissions:
    """Ahmed (2026-10-10): a submission already sent was still asked about."""

    def points(self, submissions, today=dt.date(2026, 10, 14)):
        return checkins._submission_points("Kirolos", TestSubmissionPreparation.steps(),
                                           today, today + dt.timedelta(days=5), submissions)

    def test_recorded_as_sent_is_not_asked_about(self):
        assert self.points({7: {"sent": ["2026-10-11"], "date": None}}) == []

    def test_sent_long_before_this_run_up_does_not_count(self):
        points = self.points({7: {"sent": ["2026-03-01"], "date": "2026-10-11"}})
        assert len(points) == 1 and "Was it sent?" in points[0]["text"]

    def test_moved_to_another_date_is_not_asked_about(self):
        assert self.points({7: {"sent": [], "date": "2026-11-01"}}) == []

    def test_a_deliverable_that_is_gone_is_not_asked_about(self):
        assert self.points({}) == []


def storage_config():
    from workload_app.config import TASK_DEFAULT_SETTINGS
    return dict(TASK_DEFAULT_SETTINGS)


def test_a_submission_long_gone_is_left_to_the_submissions_list():
    steps = TestSubmissionPreparation.steps()
    late = checkins._submission_points("Kirolos", steps, dt.date(2026, 10, 14),
                                       dt.date(2026, 10, 19))
    assert len(late) == 1 and "Was it sent?" in late[0]["text"]
    gone = checkins._submission_points("Kirolos", steps, dt.date(2026, 10, 30),
                                       dt.date(2026, 11, 4))
    assert gone == []
