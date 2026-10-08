"""Developing people: weekly development time, quarterly goals, and KPIs that
differ by grade and are ranked only within a grade.

Built from made-up timesheet exports, so no private workbook is needed.
"""

import datetime as dt

import pytest

from workload_app import growth, management, storage
from workload_app.service import WorkloadService

from test_checkins import TODAY, booking, export
from test_management import CONFIG, TEAM, roster


@pytest.fixture
def config():
    return {**CONFIG, "away": {}}


class TestDevelopmentTime:
    def test_everybody_gets_a_block_each_week_on_the_last_working_day(self, config):
        plan = management.Plan(TEAM, [], config)
        friday = dt.date(2026, 10, 9)
        blocks = plan.development_on(friday)
        assert sorted(b["leader"] for b in blocks) == ["Amal", "Bassem", "Dina", "Fady"]
        for day in (friday - dt.timedelta(days=i) for i in range(1, 5)):
            assert plan.development_on(day) == []
        bassem = next(b for b in blocks if b["leader"] == "Bassem")
        # A junior keeps three hours, at the end of the day.
        assert (bassem["end"] - bassem["start"]).seconds == 3 * 3600
        assert bassem["end"].strftime("%H:%M") == "16:30"

    def test_it_never_sits_over_a_one_to_one(self, config):
        plan = management.Plan(TEAM, [], config)
        for offset in range(14):
            day = dt.date(2026, 10, 5) + dt.timedelta(days=offset)
            meetings = plan.meetings_on(day)
            for block in plan.development_on(day, meetings):
                for m in meetings:
                    if block["leader"] in [m["leader"], *m["with"]]:
                        assert block["end"] <= m["start"] or block["start"] >= m["end"]

    def test_somebody_away_on_friday_has_it_on_thursday(self, config):
        friday = dt.date(2026, 10, 9)
        config["away"] = {"Dina": {friday.isoformat()}}
        plan = management.Plan(TEAM, [], config)
        assert plan.development_day("Dina", friday) == friday - dt.timedelta(days=1)

    def test_it_comes_out_of_project_time_and_carries_the_goals(self, config):
        plan = management.Plan(TEAM, [], config, goals={"Dina": ["Learn pile design"]})
        assert plan.taken_a_day()["Dina"] == pytest.approx(2.0 / 5)
        block = next(b for b in plan.development_on(dt.date(2026, 10, 9))
                     if b["leader"] == "Dina")
        assert block["agenda"] == ["Goal: Learn pile design"]

    def test_requests_are_not_booked_over_it(self, config):
        plan = management.Plan(TEAM, [], config)
        busy = plan.busy("Dina", dt.date(2026, 10, 5), 7)
        assert any(start.date() == dt.date(2026, 10, 9) for start, _ in busy)


class TestQuarters:
    def test_quarters(self):
        assert growth.quarter_of(dt.date(2026, 10, 8)) == "2026-Q4"
        assert growth.shift("2026-Q4", 1) == "2027-Q1"
        assert growth.shift("2026-Q1", -1) == "2025-Q4"
        assert growth.quarter_bounds("2026-Q3") == (dt.date(2026, 7, 1),
                                                     dt.date(2026, 9, 30))

    def test_a_bad_quarter_is_refused(self):
        with pytest.raises(growth.GrowthError):
            growth.quarter_bounds("2026-Q5")


def goal(gid, person, result="", quarter="2026-Q4"):
    return {"id": gid, "person": person, "quarter": quarter, "goal": f"Goal {gid}",
            "measure": "", "result": result, "review_note": "", "reviewed_at": None}


def page(goals=(), asks=(), delivery=None, people=TEAM, led=None, today=TODAY):
    plan = management.Plan(people, [], {**CONFIG, "away": {}})
    return growth.build(
        quarter="2026-Q4", today=today, roster=people,
        led=plan.led if led is None else led,
        delivery=delivery if delivery is not None else {
            "manager": {"Amal": 70.0}, "junior": {"Bassem": 90.0},
            "engineer": {"Dina": 80.0}, "senior": {"Fady": 60.0}},
        goals=list(goals), asks=list(asks), development=plan.development,
        development_day={})


class TestKpis:
    def test_each_grade_has_its_own_parts(self):
        view = page()
        parts = {p["name"]: [x["key"] for x in p["parts"]] for p in view["people"]}
        assert parts["Bassem"] == ["delivery", "own_goals"]
        assert parts["Amal"] == ["delivery", "own_goals", "team_support", "developing"]
        assert parts["Fady"] == ["delivery", "own_goals", "team_support", "developing"]
        amal = next(p for p in view["people"] if p["name"] == "Amal")
        weights = {x["key"]: x["weight"] for x in amal["parts"]}
        # A manager is measured mostly on the team, not on their own delivery.
        assert weights["delivery"] < weights["team_support"] + weights["developing"]

    def test_ranked_only_within_a_grade(self):
        people = roster(("Amal", "engineer", None), ("Bassem", "engineer", None),
                        ("Dina", "junior", None))
        view = page(people=people, led={}, delivery={
            "engineer": {"Amal": 100.0, "Bassem": 50.0}, "junior": {"Dina": 100.0}})
        by = {p["name"]: p for p in view["people"]}
        assert (by["Amal"]["rank"], by["Amal"]["of"]) == (1, 2)
        assert (by["Bassem"]["rank"], by["Bassem"]["of"]) == (2, 2)
        assert (by["Dina"]["rank"], by["Dina"]["of"]) == (1, 1)
        assert [g["grade"] for g in view["grades"]] == ["engineer", "junior"]

    def test_parts_with_nothing_yet_are_left_out_not_scored_zero(self):
        view = page()
        bassem = next(p for p in view["people"] if p["name"] == "Bassem")
        assert bassem["score"] == 90.0 and not bassem["complete"]

    def test_reviewed_goals_count(self):
        view = page(goals=[goal(1, "Bassem", "met"), goal(2, "Bassem", "not_met")])
        bassem = next(p for p in view["people"] if p["name"] == "Bassem")
        own = next(x for x in bassem["parts"] if x["key"] == "own_goals")
        assert own["score"] == 50.0
        assert bassem["score"] == pytest.approx(0.85 * 90 + 0.15 * 50, abs=0.1)

    def test_the_manager_is_measured_on_developing_and_supporting_people(self):
        goals = [goal(1, "Bassem", "met"), goal(2, "Dina", "partly")]
        asks = [{"person": "Bassem", "kind": "help", "cleared_by": "lead",
                 "cleared_at": "x"},
                {"person": "Dina", "kind": "stuck", "cleared_by": "", "cleared_at": None}]
        amal = next(p for p in page(goals=goals, asks=asks)["people"]
                    if p["name"] == "Amal")
        parts = {x["key"]: x["score"] for x in amal["parts"]}
        # 1 of 2 asks answered (50) and the team's delivery (90+80+60)/3.
        assert parts["team_support"] == pytest.approx((50 + (90 + 80 + 60) / 3) / 2, abs=0.1)
        # 2 of 3 with goals (66.7) and their goals 75% met.
        assert parts["developing"] == pytest.approx((200 / 3 + 75) / 2, abs=0.1)

    def test_what_to_do(self):
        goals = [goal(1, "Bassem", quarter="2026-Q3")]
        kinds = [t["kind"] for t in page(goals=goals)["todo"]]
        assert kinds[:2] == ["review", "set"]


class TestInTheApp:
    @pytest.fixture
    def unit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
        service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
        service.import_exports([
            export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
            export("bassem", booking("Bassem Northwind", "N1-0100D", 3)),
        ])
        service.save_person("Amal", {"grade": "manager"})
        return service

    def test_goals_are_set_reviewed_and_shown(self, unit):
        made = unit.add_goal({"person": "Bassem", "goal": "Design a pile cap alone",
                              "measure": "One checked without mark-ups"})
        assert made["quarter"] == "2026-Q4"
        view = unit.growth({})
        bassem = next(p for p in view["people"] if p["name"] == "Bassem")
        assert [g["goal"] for g in bassem["goals"]] == ["Design a pile cap alone"]
        unit.review_goal(made["id"], {"result": "met", "note": "Done in November"})
        bassem = next(p for p in unit.growth({})["people"] if p["name"] == "Bassem")
        assert bassem["goals"][0]["result"] == "met"
        amal = next(p for p in unit.growth({})["people"] if p["name"] == "Amal")
        assert amal["leads"] == 1
        unit.remove_goal(made["id"])
        assert not next(p for p in unit.growth({})["people"]
                        if p["name"] == "Bassem")["goals"]

    def test_bad_goals_are_refused(self, unit):
        with pytest.raises(growth.GrowthError):
            unit.add_goal({"person": "Nobody", "goal": ""})
        for i in range(growth.MOST_GOALS):
            unit.add_goal({"person": "Bassem", "goal": f"Goal {i}"})
        with pytest.raises(growth.GrowthError):
            unit.add_goal({"person": "Bassem", "goal": "One too many"})
        with pytest.raises(growth.GrowthError):
            unit.review_goal(unit.store.goals()[0]["id"], {"result": "brilliant"})

    def test_development_time_is_in_the_day_and_my_day_shows_the_goals(self, unit):
        unit.add_goal({"person": "Bassem", "goal": "Learn the wave loads"})
        friday = dt.date(2026, 10, 9)
        day = unit.day_plan({"date": [friday.isoformat()]})["days"][0]
        bassem = next(p for p in day["people"] if p["name"] == "Bassem")
        block = next(b for b in bassem["blocks"] if b["kind"] == "development")
        assert block["agenda"] == ["Goal: Learn the wave loads"]
        mine = unit.my_day("Bassem", {})
        assert [g["goal"] for g in mine["goals"]["items"]] == ["Learn the wave loads"]

    def test_my_day_shows_only_my_own_goals(self, unit):
        unit.add_goal({"person": "Bassem", "goal": "Mine"})
        unit.add_goal({"person": "Amal", "goal": "Not theirs to see"})
        items = unit.my_day("Bassem", {})["goals"]["items"]
        assert [g["goal"] for g in items] == ["Mine"]
        assert all(g["person"] == "Bassem" for g in items)

    def test_renaming_a_person_keeps_their_goals(self, unit):
        unit.add_goal({"person": "Bassem", "goal": "Lead a site visit"})
        unit.store.rename_person_everywhere("Bassem", "Bassem N")
        assert unit.store.goals()[0]["person"] == "Bassem N"
