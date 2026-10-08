"""Bugs found in a review of workload_app/service.py, each pinned by a test."""

import pytest

from workload_app import people, storage
from workload_app.model import ValidationError
from workload_app.service import WorkloadService


@pytest.fixture
def service(tmp_path):
    return WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))


class TestConfirmSubmissions:
    def test_a_bad_row_is_named_as_the_row_not_the_date(self, service):
        with pytest.raises(ValidationError) as caught:
            service.confirm_submissions(
                {"items": [{"row": "first", "date": "2026-11-02"}]})
        message = " ".join(caught.value.errors)
        assert "'first'" in message
        assert "row" in message
        assert "2026-11-02" not in message

    def test_a_bad_date_is_still_named_as_the_date(self, service):
        with pytest.raises(ValidationError) as caught:
            service.confirm_submissions(
                {"items": [{"row": 1, "date": "next week"}]})
        assert caught.value.errors == ["'next week' is not a date."]


class TestDayPlanUnitName:
    def test_a_unit_without_a_name_gives_a_blank_not_null(self, tmp_path):
        service = WorkloadService()
        service.open(storage.new_unit(tmp_path, 1, "unit-one"),
                     unit={"id": "unit-one"})
        assert service.day_plan({})["unit"] == ""

    def test_a_named_unit_keeps_its_name(self, tmp_path):
        service = WorkloadService()
        service.open(storage.new_unit(tmp_path, 1, "unit-one"),
                     unit={"id": "unit-one", "name": "Marine Structures"})
        assert service.day_plan({})["unit"] == "Marine Structures"


class TestTeams:
    def test_a_team_cannot_be_renamed_to_nothing(self, service):
        team = service.add_team({"name": "Berths"})["team"]
        with pytest.raises(people.PeopleError):
            service.update_team(team["id"], {"name": "   "})
        assert [t["name"] for t in service.store.teams()] == ["Berths"]

    def test_a_team_cannot_take_another_team_s_name(self, service):
        service.add_team({"name": "Berths"})
        coastal = service.add_team({"name": "Coastal"})["team"]
        with pytest.raises(people.PeopleError):
            service.update_team(coastal["id"], {"name": "berths"})
        assert sorted(t["name"] for t in service.store.teams()) == ["Berths", "Coastal"]

    def test_a_team_keeps_its_own_name_with_a_new_lead(self, service):
        team = service.add_team({"name": "Berths"})["team"]
        service.update_team(team["id"], {"name": "Berths", "lead": "Osama"})
        saved = next(t for t in service.store.teams() if t["id"] == team["id"])
        assert (saved["name"], saved["lead"]) == ("Berths", "Osama")


class TestPersonCapacity:
    @pytest.mark.parametrize("typed", ["35h", "nan", "-5", [7]])
    def test_hours_that_are_not_hours_are_refused_not_a_crash(self, service, typed):
        with pytest.raises(people.PeopleError):
            service.save_person("Ahmed", {"capacity_hours": typed})

    def test_hours_and_blank_still_save(self, service):
        service.save_person("Ahmed", {"capacity_hours": "35"})
        assert next(p for p in service.store.people()
                    if p["name"] == "Ahmed")["capacity_hours"] == 35.0
        service.save_person("Ahmed", {"capacity_hours": ""})
        assert next(p for p in service.store.people()
                    if p["name"] == "Ahmed")["capacity_hours"] is None
