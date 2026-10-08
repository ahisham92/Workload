"""Round 3 bug hunt, first half of workload_app/service.py: each bug pinned."""

from __future__ import annotations

import pytest

from tests.test_from_timesheets import D, blank, export, row  # noqa: F401
from workload_app.service import ApiError


def _team(service, *names):
    for name in names:
        service.add_engineer({"short_name": name})


class TestImportedNamesThatOverlap:
    """A person added by hand has the pattern ``*Ahmed*``; a colleague whose
    family name is Ahmed must not have their hours put under him."""

    def test_a_new_colleague_whose_name_holds_ahmed_is_somebody_new(self, blank):
        _team(blank, "Ahmed")
        first = blank.stage_exports([export(
            [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8)])])
        assert first["people"][0]["name"] == "Ahmed"
        blank.apply_exports(first["token"], "append")
        staged = blank.stage_exports([export(
            [row("Kirolos Ahmed", "T10001-0100D", D(2026, 8, 3), 6)])])
        kirolos = staged["people"][0]
        assert kirolos["name"] != "Ahmed"
        assert kirolos["new"] is True

    def test_rows_already_held_say_who_somebody_is(self, blank):
        _team(blank, "Ahmed")
        staged = blank.stage_exports([export(
            [row("Kirolos Ahmed", "T10001-0100D", D(2026, 8, 3), 6)],
            "kirolos.xlsx")])
        # First time round nobody holds rows yet: the hand-added Ahmed's
        # wildcard is all there is to go on.
        assert staged["people"][0]["name"] == "Ahmed"

    def test_the_more_exact_pattern_wins(self, blank):
        _team(blank, "Ahmed")
        blank.add_engineer({"short_name": "Kirolos", "pattern": "Kirolos Ahmed"})
        staged = blank.stage_exports([export(
            [row("Kirolos Ahmed", "T10001-0100D", D(2026, 8, 3), 6)])])
        assert staged["people"][0]["name"] == "Kirolos"

    def test_one_person_s_own_rows_still_find_them(self, blank):
        _team(blank, "Ahmed")
        first = blank.stage_exports([export(
            [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8)])])
        blank.apply_exports(first["token"], "append")
        again = blank.stage_exports([export(
            [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 9), 8)])])
        assert again["people"][0] == {**again["people"][0],
                                      "name": "Ahmed", "new": False}


class TestPerPersonUploadOfSomebodyElse:
    def test_an_export_whose_rows_are_another_engineer_s_is_refused(self, blank):
        _team(blank, "Ahmed")
        blank.add_engineer({"short_name": "Kirolos", "pattern": "Kirolos Ahmed"})
        staged = blank.stage_exports([export(
            [row("Kirolos Ahmed", "T10001-0100D", D(2026, 8, 3), 6)])])
        blank.apply_exports(staged["token"], "append")
        data = export([row("Kirolos Ahmed", "T10001-0100D", D(2026, 8, 10), 6)])
        import base64
        payload = blank.stage_timesheet(
            "Ahmed", "kirolos.xlsx", base64.b64decode(data["content_base64"]),
            registered_only=False)
        assert any("Kirolos" in e for e in payload["errors"])
        with pytest.raises(ApiError):
            blank.apply_timesheet(payload["token"], "append")
        assert blank.store.counts().get("Ahmed", 0) == 0

    def test_the_right_person_s_export_is_still_taken(self, blank):
        _team(blank, "Ahmed")
        data = export([row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 3), 6)])
        import base64
        payload = blank.stage_timesheet(
            "Ahmed", "ahmed.xlsx", base64.b64decode(data["content_base64"]),
            registered_only=False)
        assert payload["errors"] == []


class TestPlannerCommitSameTaskTwice:
    def test_two_moves_on_one_task_both_hold(self, blank):
        _team(blank, "Ahmed", "Osama", "Kirolos")
        blank.add_project({"number": "T10001-0100D", "name": "Quay wall",
                           "budget_mm": 10})
        blank.add_task({"name": "Check piles", "assignees": ["Ahmed", "Osama"],
                        "required_hours": 20, "due": "2026-12-20",
                        "project_number": "T10001-0100D"})
        task = blank.tasks()["tasks"][0]
        moves = [{"kind": "task", "task_id": task["id"], "from": "Ahmed",
                  "to": "Kirolos"},
                 {"kind": "task", "task_id": task["id"], "from": "Osama",
                  "to": "Kirolos"}]
        blank.planner_commit({"days": 5, "moves": moves})
        assert blank.tasks()["tasks"][0]["assignees"] == ["Kirolos"]


class TestRenamingATeamLead:
    def test_the_team_s_lead_follows_the_new_name(self, blank):
        _team(blank, "Ahmed", "Osama")
        team = blank.add_team({"name": "Berths", "lead": "Ahmed"})["team"]
        blank.update_engineer("Ahmed", {"short_name": "Ahmed M"})
        lead = next(t["lead"] for t in blank.store.teams() if t["id"] == team["id"])
        assert lead == "Ahmed M"


class TestARowWithNoName:
    def test_a_row_without_a_full_name_does_not_stop_the_import(self, blank):
        rows = [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8),
                row("", "T10001-0100D", D(2026, 8, 2), 3)]
        staged = blank.stage_exports([export(rows)])
        assert [p["full_name"] for p in staged["people"]] == ["Ahmed Mockridge"]
        assert any("no FullName" in w for w in staged["warnings"])
        result = blank.apply_exports(staged["token"], "append")
        assert result["people_added"] == ["Ahmed"]
        assert blank.store.count() == 1


class TestPreviewsNobodyWentOnWith:
    def test_old_previews_are_let_go_and_the_newest_still_applies(self, blank):
        from workload_app import service as service_module
        files = [export([row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8)])]
        tokens = [blank.stage_exports(files)["token"]
                  for _ in range(service_module.STAGED_LIMIT + 4)]
        assert len(blank._staged) <= service_module.STAGED_LIMIT
        assert blank.apply_exports(tokens[-1], "append")["rows_written"] == 1
        with pytest.raises(ApiError):
            blank.apply_exports(tokens[0], "append")


class TestPlannerCommitMovesARequestSlot:
    def test_a_request_s_booked_time_goes_to_the_new_person(self, blank):
        _team(blank, "Ahmed", "Osama", "Kirolos")
        blank.add_project({"number": "T10001-0100D", "name": "Quay wall",
                           "budget_mm": 10})
        blank.add_task({"name": "Check a fender", "assignees": ["Kirolos"],
                        "kind": "Request", "required_hours": 3,
                        "due": "2026-12-20", "project_number": "T10001-0100D"})
        task = blank.tasks()["tasks"][0]
        blank.store.set_slot(task["id"], "Kirolos", "2026-12-01T09:00",
                             "2026-12-01T12:00")
        blank.planner_commit({"days": 5, "moves": [
            {"kind": "task", "task_id": task["id"], "from": "Kirolos",
             "to": "Osama"}]})
        assert blank.store.slots()[task["id"]]["person"] == "Osama"
