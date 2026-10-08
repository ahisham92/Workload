"""Round 3 bugs in the lower half of workload_app/service.py, each pinned."""

import pytest

from workload_app import storage
from workload_app.service import WorkloadService

from test_planning import TODAY, department


@pytest.fixture
def unit(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
    service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
    service.import_exports(department())
    return service


def _requests_on(service, name):
    day = service.day_plan({})["days"][0]
    person = next(p for p in day["people"] if p["name"] == name)
    return [b["title"] for b in person["blocks"] if b["kind"] == "request"]


class TestARequestHandedOn:
    def _request(self, unit):
        made = unit.add_request({"title": "Check the RFI", "hours": 2,
                                 "person": "Kirolos", "now": "2026-10-07T10:00"})
        assert _requests_on(unit, "Kirolos") == ["Check the RFI"]
        return made["task"]

    def test_it_moves_to_the_new_person_s_day(self, unit):
        task = self._request(unit)
        unit.update_task(task["id"], {**task, "assignees": ["Osama"]})
        assert _requests_on(unit, "Kirolos") == []
        assert _requests_on(unit, "Osama") == ["Check the RFI"]
        mine = unit.my_day("Osama", {})
        assert any((b.get("task") or {}).get("id") == task["id"]
                   for b in mine["blocks"])

    def test_no_longer_a_request_it_is_not_booked_twice(self, unit):
        task = self._request(unit)
        unit.update_task(task["id"], {**task, "kind": "Task"})
        assert _requests_on(unit, "Kirolos") == []
        assert task["id"] not in unit.store.slots()

    def test_an_edit_that_keeps_the_person_keeps_the_time(self, unit):
        task = self._request(unit)
        before = unit.store.slots()[task["id"]]
        unit.update_task(task["id"], {**task, "name": "Check the RFI again"})
        after = unit.store.slots()[task["id"]]
        assert (after["person"], after["start"], after["end"]) == (
            before["person"], before["start"], before["end"])


class TestUndoAfterStuckThenHelp:
    def test_the_task_is_not_left_blocked(self, unit):
        task = unit.add_task({"name": "Pile caps", "assignees": ["Osama"],
                              "required_hours": 6, "due": "2026-10-09",
                              "status": "In progress"})["task"]

        def status():
            return next(t for t in unit.workbook.task_records()
                        if t.id == task["id"]).status

        unit.mark_my_task("Osama", task["id"], {"kind": "stuck"})
        assert status() == "Blocked"
        help_ = unit.mark_my_task("Osama", task["id"], {"kind": "help", "note": "Loads?"})
        unit.undo_my_mark("Osama", help_["mark"]["id"])
        assert status() == "In progress"
        assert unit.store.marks(person="Osama", open_only=True) == []

    def test_plain_help_and_undo_leave_the_status_alone(self, unit):
        task = unit.add_task({"name": "Deck slab", "assignees": ["Osama"],
                              "required_hours": 4, "due": "2026-10-09",
                              "status": "Blocked"})["task"]
        help_ = unit.mark_my_task("Osama", task["id"], {"kind": "help", "note": "x"})
        unit.undo_my_mark("Osama", help_["mark"]["id"])
        assert next(t for t in unit.workbook.task_records()
                    if t.id == task["id"]).status == "Blocked"


class TestTheWeekIsCopiedWhenItBegins:
    def _sun_to_thu(self, tmp_path, monkeypatch, today):
        monkeypatch.setenv("WORKLOAD_TODAY", today)
        service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
        service.import_exports(department())
        service.save_task_settings({"work_days": [6, 0, 1, 2, 3]})
        return service

    def test_not_on_the_weekend_before(self, tmp_path, monkeypatch):
        # Friday 9 October 2026: Cairo's week of Sunday 11 October is shown
        # but not copied yet.
        unit = self._sun_to_thu(tmp_path, monkeypatch, "2026-10-09")
        assert unit.lock_week_if_due() is False
        view = unit.plan_review({})
        assert view["week"] == "2026-10-11" and view["locked"] is False
        assert unit.store.week_plan("2026-10-11") == []

    def test_on_its_first_working_day(self, tmp_path, monkeypatch):
        unit = self._sun_to_thu(tmp_path, monkeypatch, "2026-10-09")
        unit.lock_week_if_due()
        monkeypatch.setenv("WORKLOAD_TODAY", "2026-10-11")
        assert unit.lock_week_if_due() is True
        assert unit.store.week_plan("2026-10-11")
