"""Leading people takes time: team support, the team meeting, one-to-ones.

A manager's day keeps time for the team before any project work goes in, so
they never look free when they are not; every meeting comes with its agenda.
Built from made-up timesheet exports, so no private workbook is needed.
"""

import datetime as dt
from collections import Counter

import pytest

from workload_app import management, storage
from workload_app.service import WorkloadService

from test_checkins import TODAY, booking, export

CONFIG = {"work_days": [0, 1, 2, 3, 4], "day_start": "08:00", "day_end": "16:30",
          "hours_per_day": 8.5, "holidays": set(), "away": {}}


def roster(*people):
    return [{"name": n, "grade": g, "team_id": t, "active": True}
            for n, g, t in people]


TEAM = roster(("Amal", "manager", None), ("Bassem", "junior", None),
              ("Dina", "engineer", None), ("Fady", "senior", None))


@pytest.fixture
def config():
    return {**CONFIG, "away": {}}


class TestWhoLeadsWhom:
    def test_a_manager_leads_everybody_else(self):
        led = management.leaders(TEAM)
        assert list(led) == ["Amal"]
        assert sorted(p["name"] for p in led["Amal"]) == ["Bassem", "Dina", "Fady"]

    def test_a_team_lead_leads_their_team(self):
        people = roster(("Amal", "engineer", "t1"), ("Bassem", "junior", "t1"),
                        ("Dina", "engineer", "t2"))
        led = management.leaders(people, [{"id": "t1", "name": "Berths", "lead": "Amal"},
                                          {"id": "t2", "name": "Quays", "lead": ""}])
        assert {k: [p["name"] for p in v] for k, v in led.items()} == {"Amal": ["Bassem"]}

    def test_nobody_leads_when_nobody_is_set_to(self):
        assert management.leaders(roster(("Bassem", "junior", None))) == {}


class TestTeamSupport:
    def test_more_for_a_junior_than_a_senior(self, config):
        led = management.leaders(TEAM)["Amal"]
        # 30 + 20 + 10 minutes.
        assert management.support_hours(led, config) == 1.0

    def test_never_more_than_half_the_day(self, config):
        many = roster(*[(f"J{i}", "junior", None) for i in range(30)])
        assert management.support_hours(many, config) == pytest.approx(4.25)


class TestMeetings:
    def fortnights(self, plan, weeks=4, first=dt.date(2026, 10, 5)):
        out = []
        for i in range(weeks * 7):
            out.extend(plan.meetings_on(first + dt.timedelta(days=i)))
        return out

    def test_the_team_meeting_is_at_the_start_of_each_week(self, config):
        plan = management.Plan(TEAM, [], config)
        team = [m for m in self.fortnights(plan) if m["kind"] == "team"]
        assert [m["start"].date().weekday() for m in team] == [0, 0, 0, 0]
        assert team[0]["start"].strftime("%H:%M") == "08:00"
        assert team[0]["with"] == ["Bassem", "Dina", "Fady"]
        assert (team[0]["end"] - team[0]["start"]).seconds // 60 == 45

    def test_one_one_to_one_each_a_fortnight_never_on_meeting_day(self, config):
        plan = management.Plan(TEAM, [], config)
        ones = [m for m in self.fortnights(plan) if m["kind"] == "one_to_one"]
        assert Counter(m["with"][0] for m in ones) == {"Bassem": 2, "Dina": 2, "Fady": 2}
        assert all(m["start"].weekday() != 0 for m in ones)
        assert all(m["end"].strftime("%H:%M") <= "16:30" for m in ones)

    def test_nothing_is_held_while_the_leader_is_away(self, config):
        monday = dt.date(2026, 10, 5)
        config["away"] = {"Amal": {monday.isoformat()}}
        plan = management.Plan(TEAM, [], config)
        assert plan.meetings_on(monday) == []
        # The team meeting moves to the first day of the week they are in.
        tuesday = [m for m in plan.meetings_on(monday + dt.timedelta(days=1))
                   if m["kind"] == "team"]
        assert tuesday

    def test_somebody_away_is_not_in_it(self, config):
        monday = dt.date(2026, 10, 5)
        config["away"] = {"Dina": {monday.isoformat()}}
        team = next(m for m in management.Plan(TEAM, [], config).meetings_on(monday)
                    if m["kind"] == "team")
        assert team["with"] == ["Bassem", "Fady"]

    def test_the_agenda_comes_from_the_checkpoints(self, config):
        plan = management.Plan(TEAM, [], config)
        one = next(m for m in self.fortnights(plan) if m["kind"] == "one_to_one")
        name = one["with"][0]
        points = {name: [{"level": "now", "text": "Quay wall calcs are late. When?"}]}
        lines = management.agenda(one, checkpoints=points,
                                  signals={name: "Needs to ease off"}, tasks=[],
                                  day=one["start"].date(), config=config)
        assert lines[0] == "How the load feels: needs to ease off."
        assert "Quay wall calcs are late. When?" in lines


class TestInTheApp:
    @pytest.fixture
    def unit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
        service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
        service.import_exports([
            export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
            export("bassem", booking("Bassem Northwind", "N1-0100D", 3)),
            export("dina", booking("Dina Ashgrove", "N2-0100D", 4)),
        ])
        return service

    def person(self, day, name):
        return next(p for p in day["people"] if p["name"] == name)

    def test_setting_a_manager_keeps_time_in_their_day(self, unit):
        before = self.person(unit.day_plan({})["days"][0], "Amal")
        unit.save_person("Amal", {"grade": "manager"})
        after = self.person(unit.day_plan({})["days"][0], "Amal")
        kinds = [b["kind"] for b in after["blocks"]]
        assert "management" in kinds and "management" not in [
            b["kind"] for b in before["blocks"]]
        assert after["free_hours"] < before["free_hours"]

    def test_the_week_has_the_meetings_with_their_agendas(self, unit):
        unit.save_person("Amal", {"grade": "manager"})
        week = unit.day_plan({"span": ["week"]})["days"]
        meetings = [(d["date"], p["name"], b) for d in week for p in d["people"]
                    for b in p["blocks"] if b["kind"] == "meeting"]
        team = [m for m in meetings if "team meeting" in m[2]["title"].lower()]
        assert {name for _, name, _ in team} == {"Amal", "Bassem", "Dina"}
        assert all(b["agenda"] for _, _, b in team)

    def test_check_ins_shows_the_leaders_side(self, unit):
        unit.save_person("Amal", {"grade": "manager"})
        view = unit.checkins()
        leading = view["leading"]
        assert [l["name"] for l in leading] == ["Amal"]
        assert leading[0]["people"] == ["Bassem", "Dina"]
        assert leading[0]["meetings"] and all(m["agenda"] for m in leading[0]["meetings"])
        amal = next(p for p in view["people"] if p["name"] == "Amal")
        assert amal["leads"] == 2 and amal["leading_hours"] > 0
        assert "Amal" not in [p["name"] for p in view["can_take"]]

    def test_requests_are_not_booked_over_a_meeting(self, unit):
        unit.save_person("Amal", {"grade": "manager"})
        monday = dt.date(2026, 10, 12)
        made = unit.add_request({"title": "Check a section", "person": "Amal",
                                 "hours": 0.5, "due": monday.isoformat(),
                                 "now": f"{monday.isoformat()}T07:30"})
        meeting = next(m for m in management.Plan(
            unit._planning(unit.workbook)["roster"], [],
            unit._planning(unit.workbook)["config"]).meetings_on(monday)
            if m["kind"] == "team")
        assert made["start"] >= meeting["end"].isoformat(timespec="minutes")
