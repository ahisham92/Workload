"""The summary video: what it shows (workload_app/video.py) and its tab."""
import datetime as dt
import re

from workload_app import video
from workload_app.app import STATIC_DIR

from test_across import SITE, app, ask, unit  # noqa: F401  (fixtures)
from test_checkins import booking, export

INDEX = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "video.js").read_text(encoding="utf-8")
PATHS = (STATIC_DIR / "paths.js").read_text(encoding="utf-8")
GUIDE = (STATIC_DIR / "guide.js").read_text(encoding="utf-8")
POCKET = (STATIC_DIR / "pocket.js").read_text(encoding="utf-8")

TODAY = dt.date(2026, 10, 12)


def team(app):  # noqa: F811
    unit(app, "Marine Structures", [
        export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
        export("bassem", booking("Bassem Northwind", "N1-0100D", 11, overtime=2.5)),
        export("dina", booking("Dina Ashgrove", "N1-0200D", 3))])


def _story(**over):
    """The smallest set of replies the story is built from."""
    parts = dict(
        unit_name="Unit A", today=TODAY,
        weekly={"title": "Week of Mon 12 Oct", "week_start": "2026-10-12",
                "week_end": "2026-10-18", "through": "2026-10-08",
                "this_week": {"room": [{"name": "Dina", "free_week": 20}],
                              "free_week": 20, "meetings": 2},
                "todo": [{"tone": "bad", "text": f"Thing {i}"} for i in range(7)],
                "last_week": {"week": "2026-10-04", "hours": 90, "capacity": 100,
                              "load": 0.9, "people": [{"name": "Amal", "hours": 40,
                                                       "capacity": 42.5, "load": 0.94}]}},
        checkins={"hours_per_day": 8.5, "days": ["2026-10-12", "2026-10-13"], "people": [
            {"name": "Amal", "is_manager": False, "signal": {"key": "rest"},
             "days": [{"booked": 8.5}, {"booked": 8.5}]},
            {"name": "Lead", "is_manager": True, "signal": {"key": "ok"},
             "days": [{"booked": 4}, {"booked": 0, "away": True}]},
            {"name": "Dina", "is_manager": False, "signal": {"key": "ok"},
             "days": [{"booked": 1}, {"booked": 1}]}]},
        needs={"by_month": {"engineers": 3, "well_used": 0.85, "planned_until": "2026-10-30",
                            "months": [{"month": "2026-10", "hours": 300, "capacity_hours": 400,
                                        "needed": 2.4, "have": 3,
                                        "jobs": [{"number": "J-1", "hours": 200},
                                                 {"number": "J-2", "hours": 100}]},
                                       {"month": "2026-11", "hours": 0, "needed": 0,
                                        "nothing_planned": True, "jobs": []}]},
               "alerts": [{"kind": "need", "severity": "now", "title": "Ask for 1", "people": 1},
                          {"kind": "room", "severity": "now", "title": "Room"}],
               "summary": {"people_needed": 1}, "unplanned": [{"number": "J-9"}]},
        submissions={"items": [
            {"name": "Late one", "project_number": "J-1", "project_name": "Job one",
             "date": "2026-10-20", "register_date": "2026-09-01", "basis": "overdue",
             "people": ["Amal"], "progress": 0.5},
            {"name": "Soon one", "project_number": "J-2", "project_name": "Job two",
             "date": "2026-10-19", "basis": "set", "people": ["Dina"], "progress": 0.2},
            {"name": "Far one", "project_number": "J-2", "date": "2026-12-19", "basis": "set"},
            {"name": "Sent", "project_number": "J-2", "date": "2026-10-13", "prepared": True}]},
        report={"period": {"label": "Full year 2026"}, "counted_to": "2026-10-08",
                "engineers": ["Amal", "Dina"],
                "per_engineer": {"Amal": {"utilisation": 1.1}, "Dina": {"utilisation": None}},
                "team": {"utilisation": 0.93, "cpi": 1.05, "earned_mm": 10.5, "actual_mm": 10,
                         "planned_to_date_mm": 12, "plan_adherence": 0.83, "projects_active": 2},
                "projects": [{"number": "J-1", "name": "Job one", "actual_mm": 6, "progress": 0.4},
                             {"number": "J-2", "name": "Job two", "actual_mm": 4},
                             {"number": "J-3", "name": "Not started", "actual_mm": 0}]},
        budgets={"totals": {"jobs": 0}})
    parts.update(over)
    return video.build(**parts)


class TestStory:
    def test_desks_put_the_manager_first_then_the_most_loaded(self):
        desks = _story()["week"]["desks"]
        assert [d["name"] for d in desks] == ["Lead", "Amal", "Dina"]
        lead, amal, dina = desks
        assert lead["capacity"] == 8.5 and lead["load"] == 0.471  # away a day
        assert amal["load"] == 1.0 and amal["ease_off"]
        assert dina["hours"] == 2.0

    def test_late_first_then_the_next_two_weeks_and_never_what_went(self):
        due = _story()["week"]["due"]
        assert [i["name"] for i in due["items"]] == ["Late one", "Soon one"]
        assert due["late"] == 1 and due["soon"] == 1 and due["more"] == 0
        assert due["items"][0]["was_due"] == "2026-09-01"
        assert due["items"][1]["was_due"] is None

    def test_the_month_names_its_jobs_and_people_needed_only_asks(self):
        week = _story()["week"]
        assert week["month"]["jobs"][0] == {"job": "J-1", "hours": 200.0, "name": "Job one"}
        assert [a["title"] for a in week["people"]["asks"]] == ["Ask for 1"]
        assert week["people"]["months"][1]["nothing_planned"]
        assert week["people"]["unplanned"] == 1

    def test_the_todo_list_is_cut_and_counts_the_rest(self):
        week = _story()["week"]
        assert len(week["todo"]) == video.MOST_TODO and week["todo_more"] == 2

    def test_how_we_are_doing(self):
        doing = _story()["doing"]
        assert doing["busy"] == 0.93 and doing["cpi"] == 1.05
        assert doing["plan_done"] == round(10.5 / 12, 3)
        assert doing["people"] == [{"name": "Amal", "busy": 1.1}]
        assert [j["job"] for j in doing["jobs"]] == ["J-1", "J-2"]
        assert doing["budgets"] is None
        assert doing["last_week"]["people"][0]["name"] == "Amal"

    def test_budgets_show_when_brought_in(self):
        doing = _story(budgets={"totals": {"jobs": 2, "over": 1, "team_budget_mm": 10,
                                           "team_spent_mm": 11},
                                "jobs": [{"job_number": "J-1", "title": "Job one", "state": "over"},
                                         {"job_number": "J-2", "state": "ok"}]})["doing"]
        assert doing["budgets"]["over"] == 1
        assert [j["job"] for j in doing["budgets"]["worst"]] == ["J-1"]

    def test_an_empty_unit_still_tells_a_story(self):
        story = video.build(unit_name="", today=TODAY, weekly={}, checkins={}, needs={},
                            submissions={}, report={}, budgets={})
        assert story["week"]["desks"] == [] and story["week"]["month"] is None
        assert story["doing"]["busy"] is None and story["doing"]["last_week"] is None


class TestRoute:
    def test_from_existing_data(self, app):  # noqa: F811
        team(app)
        status, story = ask("GET", "/api/video")
        assert status == 200, story
        assert story["unit"] == "Marine Structures"
        assert {d["name"] for d in story["week"]["desks"]} == {"Amal", "Bassem", "Dina"}
        assert story["week"]["title"].startswith("Week of")
        assert "busy" in story["doing"]


class TestTab:
    def test_the_tab_and_its_files_are_on_the_page(self):
        assert 'data-view="video"' in INDEX and 'id="view-video"' in INDEX
        assert 'id="video-body"' in INDEX
        assert INDEX.index('src="subs.js"') < INDEX.index('src="video.js"') < INDEX.index('src="pocket.js"')
        assert 'href="video.css"' in INDEX

    def test_it_is_on_every_path_and_on_the_start_page(self):
        always = re.search(r"const ALWAYS = \[([^\]]*)\]", PATHS).group(1)
        assert "'video'" in always
        assert "switchView('video')" in PATHS
        assert "'video'" in re.search(r"const DAILY = \[([^\]]*)\]", POCKET).group(1)

    def test_the_guide_says_where_it_is(self):
        assert "['video']" in GUIDE and "Summary video" in GUIDE

    def test_three_choices_and_it_records_on_an_iphone(self):
        for title in ("Our week", "How we\\'re doing", "Both"):
            assert f"title: '{title}'" in SCRIPT
        assert "MediaRecorder" in SCRIPT and "video/mp4" in SCRIPT
        assert "playsinline" in SCRIPT and "navigator.share" in SCRIPT
        assert "/api/video" in SCRIPT

    def test_no_sports_words(self):
        for word in ("football", "soccer", "goal!", "kick-off", "squad", "match"):
            assert word not in SCRIPT.lower(), word
