"""The task list: a sheet of the app's own, and the arithmetic of a working day.

Nothing here may reach the model.  Several of these tests exist only to prove
that: the workbook's own figures have to come out identical with a full task
list beside them.
"""

import datetime as dt
import xml.etree.ElementTree as ET
import zipfile

import pytest

from workload_app import config as cfg, tasks
from workload_app.tasks import TaskError


MONDAY = dt.date(2026, 9, 7)          # the anchor for every dated test below


class TestTheSheet:
    def test_the_sheet_is_made_on_demand(self, wb):
        assert cfg.SHEET_TASKS not in wb.raw.sheet_names
        wb.save_task({"name": "Draft the layout", "assignees": ["Ahmed"],
                      "required_hours": 6})
        assert cfg.SHEET_TASKS in wb.raw.sheet_names

    def test_a_task_survives_a_save_and_reopen(self, wb, workbook_copy):
        wb.save_task({"name": "Draft the layout", "definition": "First pass GA",
                      "assignees": ["Ahmed", "Osama"], "required_hours": 9,
                      "due": "2026-09-18"})
        wb.save()
        from workload_app.workbook import WorkloadWorkbook
        again = WorkloadWorkbook(workbook_copy).tasks()
        assert len(again) == 1
        assert again[0]["name"] == "Draft the layout"
        assert again[0]["assignees"] == ["Ahmed", "Osama"]
        assert again[0]["due"] == "2026-09-18"
        assert again[0]["hours_each"] == 4.5

    def test_the_workbook_is_still_sound_with_a_task_sheet(self, wb, workbook_copy):
        wb.save_task({"name": "Draft", "assignees": ["Ahmed"]})
        wb.save()
        with zipfile.ZipFile(workbook_copy) as zf:
            for name in zf.namelist():
                if name.endswith(".xml"):
                    ET.fromstring(zf.read(name))
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.load_workbook(workbook_copy)
        assert cfg.SHEET_TASKS in book.sheetnames
        assert sum(len(book[n]._charts) for n in book.sheetnames) == 14

    def test_the_model_cannot_see_the_tasks(self, wb):
        """The whole point of the tab: it changes none of the figures."""
        from workload_app import metrics
        before = metrics.overview(wb, 2026)["portfolio"]
        wb.save_task({"name": "Draft", "assignees": ["Ahmed"],
                      "required_hours": 400, "actual_hours": 400})
        wb.generate_weekly_meetings({"start": MONDAY.isoformat(), "weeks": 8})
        assert metrics.overview(wb, 2026)["portfolio"] == before

    def test_dates_are_written_as_dates(self, wb, workbook_copy):
        wb.save_task({"name": "Draft", "assignees": ["Ahmed"], "due": "2026-09-10"})
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        cell = openpyxl.load_workbook(workbook_copy)[cfg.SHEET_TASKS]["K3"]
        assert cell.value == dt.datetime(2026, 9, 10)


class TestChangingTheList:
    def test_ids_carry_on_from_the_last(self, wb):
        first = wb.save_task({"name": "One", "assignees": []})
        second = wb.save_task({"name": "Two", "assignees": []})
        assert (first["id"], second["id"]) == (1, 2)

    def test_an_edit_replaces_the_task_it_names(self, wb):
        task = wb.save_task({"name": "One", "assignees": ["Ahmed"],
                             "required_hours": 4})
        wb.save_task({"name": "One, revised", "assignees": ["Osama"],
                      "required_hours": 6, "status": "In progress"},
                     task_id=task["id"])
        stored = wb.tasks()
        assert len(stored) == 1
        assert stored[0]["name"] == "One, revised"
        assert stored[0]["assignees"] == ["Osama"]
        assert stored[0]["status"] == "In progress"

    def test_deleting_leaves_no_gap(self, wb):
        for name in ("One", "Two", "Three"):
            wb.save_task({"name": name, "assignees": []})
        wb.delete_task(2)
        assert [t["name"] for t in wb.tasks()] == ["One", "Three"]
        assert [t["id"] for t in wb.tasks()] == [1, 3]

    def test_a_whole_series_can_go_at_once(self, wb):
        wb.generate_weekly_meetings({"start": MONDAY.isoformat(), "weeks": 5})
        series = wb.tasks()[0]["series"]
        result = wb.delete_task_series(series)
        assert result["deleted"] == 5
        assert wb.tasks() == []

    def test_everything_wrong_is_said_at_once(self, wb):
        with pytest.raises(TaskError) as error:
            wb.save_task({"name": "", "assignees": ["Nobody"],
                          "required_hours": -3, "project_number": "NOPE"})
        joined = " ".join(error.value.errors)
        assert "needs a name" in joined
        assert "Nobody" in joined
        assert "negative" in joined
        assert "NOPE" in joined

    def test_a_task_cannot_be_due_before_it_starts(self, wb):
        with pytest.raises(TaskError, match="before it starts"):
            wb.save_task({"name": "One", "assignees": [],
                          "start": "2026-09-10", "due": "2026-09-01"})


class TestTheWorkingDay:
    def test_the_day_is_the_hours_it_holds(self, wb):
        assert tasks.hours_per_day(wb.task_settings()) == 8.5

    def test_the_day_can_be_changed(self, wb):
        saved = wb.save_task_settings({"day_end": "18:00"})
        assert saved["day_end"] == "18:00"
        assert tasks.hours_per_day(wb.task_settings()) == 9.0

    def test_a_week_can_run_sunday_to_thursday(self, wb):
        saved = wb.save_task_settings({"work_days": [6, 0, 1, 2, 3]})
        assert saved["work_days"] == [0, 1, 2, 3, 6]
        # A Friday is then not a working day, and a Sunday is.
        assert not tasks.is_working_day(dt.date(2026, 9, 11), saved)
        assert tasks.is_working_day(dt.date(2026, 9, 13), saved)

    def test_a_day_that_ends_before_it_starts_is_refused(self, wb):
        with pytest.raises(TaskError, match="end after it starts"):
            wb.save_task_settings({"day_start": "17:00", "day_end": "09:00"})

    def test_a_week_needs_a_working_day(self, wb):
        with pytest.raises(TaskError, match="at least one working day"):
            wb.save_task_settings({"work_days": []})

    def test_a_time_that_is_not_a_time_is_refused(self, wb):
        with pytest.raises(TaskError, match="time like 09:00"):
            wb.save_task_settings({"day_start": "nine"})


class TestWhoIsOverloaded:
    def test_a_shared_task_is_split_between_them(self, wb):
        wb.save_task({"name": "Shared", "assignees": ["Ahmed", "Osama"],
                      "required_hours": 20, "due": (MONDAY + dt.timedelta(days=3)).isoformat()})
        load = wb.task_load(today=MONDAY)
        assert load["per_engineer"]["Ahmed"]["hours"] == 10
        assert load["per_engineer"]["Osama"]["hours"] == 10
        assert load["per_engineer"]["Kirolos"]["hours"] == 0

    def test_capacity_is_working_days_times_the_day(self, wb):
        load = wb.task_load(today=MONDAY, weeks=2)
        assert load["working_days"] == 10        # two Monday-to-Friday weeks
        assert load["capacity_hours"] == 85.0
        assert load["hours_per_day"] == 8.5

    def test_over_the_day_is_overloaded_and_under_it_is_not(self, wb):
        due = (MONDAY + dt.timedelta(days=2)).isoformat()
        wb.save_task({"name": "Too much", "assignees": ["Osama"],
                      "required_hours": 200, "due": due})
        wb.save_task({"name": "A little", "assignees": ["Kirolos"],
                      "required_hours": 4, "due": due})
        load = wb.task_load(today=MONDAY)
        assert load["per_engineer"]["Osama"]["verdict"] == "overloaded"
        assert load["per_engineer"]["Osama"]["overtime_hours"] == 30.0
        assert load["per_engineer"]["Kirolos"]["verdict"] == "underloaded"
        assert load["busiest"] == "Osama"

    def test_overdue_counts_but_later_and_undated_do_not(self, wb):
        wb.save_task({"name": "Late", "assignees": ["Ahmed"], "required_hours": 5,
                      "due": (MONDAY - dt.timedelta(days=5)).isoformat()})
        wb.save_task({"name": "Someday", "assignees": ["Ahmed"], "required_hours": 7})
        wb.save_task({"name": "Next year", "assignees": ["Ahmed"],
                      "required_hours": 9, "due": "2027-06-01"})
        entry = wb.task_load(today=MONDAY)["per_engineer"]["Ahmed"]
        assert (entry["overdue_hours"], entry["undated_hours"], entry["later_hours"]) \
            == (5.0, 7.0, 9.0)
        assert entry["hours"] == 0.0
        # Only the overdue work counts against the days in hand.
        assert entry["days"] == pytest.approx(5 / 8.5, abs=0.01)

    def test_finished_work_stops_weighing_on_anyone(self, wb):
        due = (MONDAY + dt.timedelta(days=1)).isoformat()
        task = wb.save_task({"name": "Done one", "assignees": ["Ahmed"],
                             "required_hours": 40, "due": due})
        assert wb.task_load(today=MONDAY)["per_engineer"]["Ahmed"]["hours"] == 40
        wb.save_task({"name": "Done one", "assignees": ["Ahmed"],
                      "required_hours": 40, "actual_hours": 44, "due": due,
                      "status": "Done"}, task_id=task["id"])
        entry = wb.task_load(today=MONDAY)["per_engineer"]["Ahmed"]
        assert entry["hours"] == 0
        assert entry["done_hours"] == 40
        assert entry["actual_hours"] == 44

    def test_work_belonging_to_nobody_is_still_counted_somewhere(self, wb):
        wb.save_task({"name": "Orphan", "assignees": [], "required_hours": 12,
                      "due": (MONDAY + dt.timedelta(days=2)).isoformat()})
        load = wb.task_load(today=MONDAY)
        assert load["unassigned"] == {"hours": 12.0, "tasks": 1}


class TestTheRunUpToADeliverable:
    def _dated(self, wb, when):
        deliverable = wb.deliverables()[0]
        wb.update_deliverable(deliverable.row, {
            **deliverable.to_dict(), "status_date": when.isoformat()})
        return wb.deliverables()[0]

    def test_a_date_pulls_a_task_onto_every_working_day_before_it(self, wb):
        due = MONDAY + dt.timedelta(days=9)          # a Wednesday
        deliverable = self._dated(wb, due)
        result = wb.generate_submission_tasks(today=MONDAY)
        assert result["added"] == 6                  # a week of working days
        made = [t for t in wb.tasks() if t["kind"] == "Submission"]
        assert all(t["deliverable_row"] == deliverable.row for t in made)
        assert [t["due"] for t in made] == [
            "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14",
            "2026-09-15", "2026-09-16",
        ]
        assert made[-1]["due"] == due.isoformat()

    def test_it_lands_on_whoever_holds_a_share_of_it(self, wb):
        deliverable = self._dated(wb, MONDAY + dt.timedelta(days=9))
        holders = [name for name, share in deliverable.shares.items() if share]
        wb.generate_submission_tasks(today=MONDAY)
        made = [t for t in wb.tasks() if t["kind"] == "Submission"]
        assert made[0]["assignees"] == holders

    def test_running_it_again_adds_nothing(self, wb):
        self._dated(wb, MONDAY + dt.timedelta(days=9))
        first = wb.generate_submission_tasks(today=MONDAY)["added"]
        again = wb.generate_submission_tasks(today=MONDAY)["added"]
        assert first > 0 and again == 0

    def test_dates_already_past_are_left_alone(self, wb):
        result = wb.generate_submission_tasks(today=MONDAY)
        assert result["added"] == 0
        assert result["past_deliverables"] > 0
        assert wb.generate_submission_tasks(
            today=MONDAY, include_past=True)["added"] > 0

    def test_one_deliverable_can_be_asked_for_by_name(self, wb):
        deliverable = wb.deliverables()[0]
        result = wb.generate_submission_tasks(today=MONDAY, only_row=deliverable.row)
        assert result["deliverables"] == 1
        assert all(t["deliverable_row"] == deliverable.row
                   for t in wb.tasks())


class TestTheWeeklyMeeting:
    def test_one_button_puts_in_the_whole_series(self, wb):
        result = wb.generate_weekly_meetings({"start": "2026-09-02", "weeks": 6})
        assert result["added"] == 6
        made = wb.tasks()
        assert [t["due"] for t in made] == [
            "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28",
            "2026-10-05", "2026-10-12",
        ]
        assert all(t["kind"] == "Meeting" for t in made)
        assert made[0]["assignees"] == wb.engineer_names()

    def test_it_extends_rather_than_doubles(self, wb):
        wb.generate_weekly_meetings({"start": MONDAY.isoformat(), "weeks": 3})
        again = wb.generate_weekly_meetings({"start": MONDAY.isoformat(), "weeks": 5})
        assert again["added"] == 2
        assert len(wb.tasks()) == 5

    def test_a_project_gets_its_own_series(self, wb):
        number = wb.projects()[0].number
        wb.generate_weekly_meetings({"project_number": number, "weeks": 2,
                                     "start": MONDAY.isoformat(), "weekday": 2})
        made = wb.tasks()
        assert all(t["project_number"] == number for t in made)
        assert made[0]["series"] == f"meeting:{number}:2"
        assert made[0]["due"] == "2026-09-09"        # the first Wednesday

    def test_an_unknown_project_is_refused(self, wb):
        from workload_app.workbook import ValidationError
        with pytest.raises(ValidationError, match="not a project"):
            wb.generate_weekly_meetings({"project_number": "NOPE"})
