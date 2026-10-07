"""Several teams, the coming days, drawings, and when to ask for people.

Built from timesheet exports alone against the blank template, so like
``test_from_timesheets`` these need no private workbook.
"""

import base64
import datetime as dt
import io
import math
import shutil

import pytest

from workload_app import (derive, drawings, holidays, needs, people, planner,
                          storage, submissions)
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


def booking(full, grade, unit, job, phase, deliverable, hours_a_day, days=15):
    return [{"Job Type": "1-Projects", "JobNumber": job, "FullName": full,
             "Grade": grade, "Date": day, "Phase": phase,
             "RegularHours": hours_a_day, "OvertimeHours": 0,
             "TotalHours": hours_a_day, "JobStatus": "Active",
             "DeliverableDescription": deliverable, "CurrentUnitDesc": unit}
            for day in weekdays(days)]


def department():
    """Two teams under one manager, and a drawing office in one of them."""
    berths, coastal = "BERTHS", "COASTAL"
    return [
        # Osama is doing the work of one and a half people.
        export("osama", booking("Osama Ayman", "P2", berths, "N1-0100D", 1,
                                "Detailed Design ST", 8)
               + booking("Osama Ayman", "P2", berths, "N2-0100D", 1,
                         "Concept Design", 4)),
        export("kirolos", booking("Kirolos Naguib", "P1", berths, "N1-0100D", 1,
                                  "Detailed Design ST", 3)),
        export("mariam", booking("Mariam Adel", "Lead", coastal, "N3-0100D", 1,
                                 "Coastal Study", 4)),
        export("hany", booking("Hany Draftsman", "Senior Draftsman", berths,
                               "N1-0100D", 1, "Detailed Design ST", 7)),
    ]


@pytest.fixture
def unit(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
    target = tmp_path / "unit.xlsx"
    shutil.copy(storage.template_path(), target)
    service = WorkloadService(target)
    service.import_exports(department())
    return service


def person(view, name):
    return next(p for p in view["people"] if p["name"] == name)


class TestTeamsFromTheTimesheets:
    def test_each_unit_on_the_export_is_a_team(self, unit):
        roster = unit.roster()
        teams = {p["name"]: p["team_name"] for p in roster["people"]}
        assert teams["Osama"] == "BERTHS"
        assert teams["Mariam"] == "COASTAL"
        assert {t["name"] for t in roster["teams"]} == {"BERTHS", "COASTAL"}

    def test_a_manager_s_own_move_is_not_undone(self, unit):
        coastal = next(t for t in unit.store.teams() if t["name"] == "COASTAL")
        unit.move_people({"names": ["Osama"], "team_id": coastal["id"]})
        unit.import_exports(department())
        teams = {p["name"]: p["team_name"] for p in unit.roster()["people"]}
        assert teams["Osama"] == "COASTAL"

    def test_one_unit_on_every_row_makes_no_teams(self, tmp_path):
        target = tmp_path / "unit.xlsx"
        shutil.copy(storage.template_path(), target)
        service = WorkloadService(target)
        service.import_exports([export("a", booking(
            "Solo Person", "P2", "ONE", "N9-0100D", 1, "Design", 8))])
        assert service.store.teams() == []

    def test_draftsmen_are_their_own_grade_and_role(self, unit):
        grades = {p["name"]: p["grade"] for p in unit.roster()["people"]}
        assert grades["Hany"] == "drafter"
        assert people.role_of("drafter") == people.ROLE_DRAFTING
        assert people.role_of("engineer") == people.ROLE_ENGINEERING
        assert derive.grade_for("CAD Operator") == "drafter"
        assert derive.grade_for("BIM Modeller") == "bim"


class TestDrawings:
    def test_a_count_per_deliverable_and_everything_else_follows(self, unit):
        rows = {d.project_number: d.row for d in unit.workbook.deliverables()}
        unit.save_drawings({"counts": {rows["N1-0100D"]: 40}})
        data = unit.drawings()
        assert data["total"] == 40
        project = next(p for p in data["projects"] if p["number"] == "N1-0100D")
        # Set up from timesheets, a live phase is at its first step.
        assert 0 < project["done"] < 40
        assert project["done"] + project["left"] == pytest.approx(40)
        by_person = {p["name"]: p for p in data["people"]}
        assert by_person["Osama"]["left"] > by_person["Kirolos"]["left"]

    def test_saved_with_the_project(self, unit):
        detail = unit.project_detail("N2-0100D")
        items = [dict(d, drawings=12) for d in detail["deliverables"]]
        unit.save_project_with_deliverables(
            "N2-0100D", {"project": detail["project"], "deliverables": items})
        again = unit.project_detail("N2-0100D")
        assert [d["drawings"] for d in again["deliverables"]] == [12]

    def test_blank_clears_and_nonsense_is_refused(self, unit):
        row = unit.workbook.deliverables()[0].row
        unit.save_drawings({"counts": {row: 5}})
        unit.save_drawings({"counts": {row: ""}})
        assert unit.drawings()["total"] == 0
        with pytest.raises(drawings.DrawingsError):
            unit.save_drawings({"counts": {row: "-3"}})
        with pytest.raises(drawings.DrawingsError):
            unit.save_drawings({"counts": {99999: 3}})


class TestTheComingDays:
    def test_pace_is_read_from_the_newest_two_weeks(self, unit):
        view = unit.planner({"days": 5})
        osama = person(view, "Osama")
        assert osama["before"]["hours"] == pytest.approx(60)    # 12 h a day
        assert osama["verdict_before"] == "over"
        assert person(view, "Kirolos")["verdict_before"] == "room"
        assert view["pace_to"] == LAST.isoformat()
        assert view["from"] == TODAY.isoformat()

    def test_moving_half_a_project_shows_its_effect_before_committing(self, unit):
        move = {"kind": "project", "project": "N2-0100D", "from": "Osama",
                "to": "Kirolos", "share": 0.5}
        view = unit.planner({"days": 5, "moves": [move]})
        assert person(view, "Osama")["after"]["hours"] == pytest.approx(50)
        assert person(view, "Kirolos")["after"]["hours"] == pytest.approx(25)
        assert view["moves"][0]["hours"] == pytest.approx(10)
        # Nothing was written.
        assert person(unit.planner({"days": 5}), "Osama")["after"]["hours"] \
            == pytest.approx(60)

    def test_drawings_in_hand_follow_the_work(self, unit):
        rows = {d.project_number: d.row for d in unit.workbook.deliverables()}
        unit.save_drawings({"counts": {rows["N1-0100D"]: 90}})
        move = {"kind": "project", "project": "N1-0100D", "from": "Osama",
                "to": "Kirolos", "share": 1}
        view = unit.planner({"days": 5, "moves": [move]})
        osama, kirolos = person(view, "Osama"), person(view, "Kirolos")
        assert osama["after"]["drawings"] == 0
        assert kirolos["after"]["drawings"] == pytest.approx(
            kirolos["before"]["drawings"] + osama["before"]["drawings"], abs=0.2)

    def test_a_suggestion_relieves_the_overloaded_with_like_for_like(self, unit):
        view = unit.planner_suggest({"days": 5})
        assert view["suggested"]
        assert person(view, "Osama")["verdict_after"] != "over"
        for move in view["suggested"]:
            assert move["to"] != "Hany"            # no design to the drawing office
        # Somebody who already knows the project comes first.
        assert view["suggested"][0]["to"] == "Kirolos"

    def test_committing_keeps_the_handover_for_its_days(self, unit):
        move = {"kind": "project", "project": "N2-0100D", "from": "Osama",
                "to": "Kirolos", "share": 1}
        result = unit.planner_commit({"days": 5, "moves": [move]})
        assert result["projects_moved"] == 1
        view = unit.planner({"days": 5})
        assert person(view, "Osama")["before"]["hours"] == pytest.approx(40)
        assert len(view["saved"]) == 1
        unit.remove_plan_move(view["saved"][0]["id"], {"days": 5})
        assert person(unit.planner({"days": 5}), "Osama")["before"]["hours"] \
            == pytest.approx(60)

    def test_a_task_changes_hands(self, unit):
        engineers = unit.workbook.engineer_names()
        assert "Osama" in engineers and "Kirolos" in engineers
        unit.add_task({"name": "Check piles", "assignees": ["Osama"],
                       "required_hours": 30, "due": "2026-10-09",
                       "project_number": "N2-0100D"})
        task = unit.tasks()["tasks"][0]
        move = {"kind": "task", "task_id": task["id"], "from": "Osama",
                "to": "Kirolos"}
        unit.planner_commit({"days": 5, "moves": [move]})
        assert unit.tasks()["tasks"][0]["assignees"] == ["Kirolos"]

    def test_bad_moves_are_refused(self, unit):
        with pytest.raises(planner.PlanError):
            unit.planner({"moves": [{"project": "N1-0100D", "from": "Osama",
                                     "to": "Nobody"}]})
        with pytest.raises(planner.PlanError):
            unit.planner({"moves": [{"project": "N1-0100D", "from": "Osama",
                                     "to": "Osama"}]})


class TestWhenToAskForPeople:
    def test_one_person_over_is_a_planner_matter_not_a_hiring_one(self, unit):
        # Osama is over, but Kirolos has the room: the team is not short.
        data = unit.needs()
        assert not [a for a in data["alerts"] if a["kind"] == "need"]
        fine = [a for a in data["alerts"] if a["kind"] == "fine"]
        assert {a["team_name"] for a in fine} == {"BERTHS", "COASTAL"}

    def test_an_overloaded_team_is_told_how_many_and_for_how_long(self, unit):
        unit.import_exports([export("more", booking(
            "Kirolos Naguib", "P1", "BERTHS", "N4-0100D", 1, "Detail", 8))],
            mode="append")
        data = unit.needs()
        asks = [a for a in data["alerts"] if a["kind"] == "need"]
        berths = [a for a in asks if a["team_name"] == "BERTHS"
                  and a["role"] == people.ROLE_ENGINEERING]
        assert berths, data["alerts"]
        ask = berths[0]
        assert ask["people"] >= 1
        assert ask["weeks"] >= 1
        assert ask["ask_by"] == TODAY.isoformat()        # needed already
        assert "ask for" in ask["title"]

    def test_a_team_with_room_is_told_it_needs_nobody(self, unit):
        data = unit.needs()
        coastal = [a for a in data["alerts"] if a["team_name"] == "COASTAL"]
        assert coastal and all(a["kind"] in {"fine", "room"} for a in coastal)
        # The forecast rests on pace for projects nobody has confirmed.
        assert {p["number"] for p in data["assumed"]} >= {"N1-0100D"}

    def test_a_confirmed_project_is_forecast_from_its_own_figures(self, unit):
        detail = unit.project_detail("N3-0100D")
        project = dict(detail["project"], budget_mm=40, cac_override=12, start="2026-01-01",
                       end="2026-12-31", notes="")
        unit.save_project_with_deliverables(
            "N3-0100D", {"project": project, "deliverables": detail["deliverables"]})
        data = unit.needs()
        coastal = [a for a in data["alerts"] if a["team_name"] == "COASTAL"
                   and a["kind"] == "need"]
        assert coastal and coastal[0]["people"] >= 2
        assert "N3-0100D" not in {p["number"] for p in data["assumed"]}

    def test_weeks_start_today(self):
        span = needs.weeks_ahead(TODAY, 3)
        assert span[0] == (TODAY, dt.date(2026, 10, 11))
        assert span[1][0] == dt.date(2026, 10, 12)


class TestTheDayFillsItself:
    def test_everybody_s_day_is_laid_out_from_their_pace(self, unit):
        data = unit.day_plan({})
        day = data["days"][0]
        assert day["date"] == TODAY.isoformat() and day["working_day"]
        osama = person(day, "Osama")
        assert osama["blocks"][0]["start"] == "09:00"
        assert {b["project"] for b in osama["blocks"]} == {"N1-0100D", "N2-0100D"}
        # Twelve hours of pace in an eight and a half hour day.
        assert osama["over_hours"] == pytest.approx(3.5, abs=0.3)
        kirolos = person(day, "Kirolos")
        assert kirolos["free_hours"] == pytest.approx(5.5, abs=0.3)

    def test_the_week_is_the_same_day_by_day(self, unit):
        data = unit.day_plan({"span": ["week"]})
        assert [d["date"] for d in data["days"]] == [
            "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]

    def test_a_weekend_is_a_day_off(self, unit):
        day = unit.day_plan({"date": ["2026-10-10"]})["days"][0]
        assert not day["working_day"]
        assert all(not p["blocks"] for p in day["people"])


class TestTimeAway:
    def test_one_tap_away_takes_them_out_of_the_coming_days(self, unit):
        before = person(unit.planner({"days": 5}), "Kirolos")
        unit.add_absence({"person": "Kirolos", "start": "2026-10-08",
                          "end": "2026-10-09", "note": "Site visit"})
        after = person(unit.planner({"days": 5}), "Kirolos")
        assert after["away_days"] == 2
        assert after["capacity"] == pytest.approx(before["capacity"] * 3 / 5)
        # Three days of his usual three hours, not five.
        assert after["before"]["hours"] == pytest.approx(9)
        day = person(unit.day_plan({"date": ["2026-10-08"]})["days"][0], "Kirolos")
        assert day["away"] and not day["blocks"] and day["free_hours"] == 0
        listed = unit.day_plan({})["away"]
        assert listed[0]["person"] == "Kirolos" and listed[0]["source"] == "typed"

    def test_a_request_skips_whoever_is_away(self, unit):
        unit.add_absence({"person": "Kirolos", "start": TODAY.isoformat()})
        result = unit.add_request({"title": "Check the RFI", "hours": 1,
                                   "now": "2026-10-07T10:00"})
        assert result["person"] != "Kirolos"
        named = unit.add_request({"title": "His one", "hours": 1, "person": "Kirolos",
                                  "now": "2026-10-07T10:00"})
        assert named["start"] == "2026-10-08T09:00"

    def test_a_public_holiday_is_nobody_s_working_day(self, unit):
        unit.add_absence({"person": "*", "start": "2026-10-08", "note": "Holiday"})
        week = unit.day_plan({"span": ["week"]})["days"]
        assert "2026-10-08" not in [d["date"] for d in week]
        view = unit.planner({"days": 5})
        assert view["to"] == "2026-10-14"

    def test_leave_booked_on_a_timesheet_is_read_ahead_and_behind(self, unit):
        leave = [{"Job Type": "3-Leave", "JobNumber": "LEAVE", "FullName": "Mariam Adel",
                  "Grade": "Lead", "Date": day, "Phase": None, "RegularHours": 8,
                  "OvertimeHours": 0, "TotalHours": 8, "JobStatus": "",
                  "DeliverableDescription": "Annual leave", "CurrentUnitDesc": "COASTAL"}
                 for day in (dt.date(2026, 10, 12), dt.date(2026, 10, 13))]
        unit.import_exports([export("mariam-leave", leave)])
        view = person(unit.planner({"days": 10}), "Mariam")
        assert view["away_days"] == 2
        away = unit.day_plan({})["away"]
        assert {"person": "Mariam", "start": "2026-10-12", "end": "2026-10-13",
                "source": "timesheet"}.items() <= next(
                    a for a in away if a["person"] == "Mariam").items()

    def test_the_forecast_counts_who_is_there(self, unit):
        before = unit.needs()
        unit.add_absence({"person": "Mariam", "start": "2026-10-12", "end": "2026-10-16"})
        after = unit.needs()
        def week(data, i):
            group = next(g for g in data["groups"] if g["team_name"] == "COASTAL")
            return group["weeks"][i]
        assert week(after, 1)["capacity_hours"] == 0
        assert week(after, 1)["away_days"] == 5
        assert week(before, 1)["capacity_hours"] > 0

    def test_nonsense_is_refused_and_a_typed_absence_can_go(self, unit):
        from workload_app.calendar_ import CalendarError
        with pytest.raises(CalendarError):
            unit.add_absence({"person": "Nobody Here", "start": "2026-10-08"})
        with pytest.raises(CalendarError):
            unit.add_absence({"person": "Osama", "start": "2026-10-09",
                              "end": "2026-10-08"})
        made = unit.add_absence({"person": "Osama", "start": "2026-10-08"})
        assert unit.remove_absence(made["id"])["away"] == []


class TestPublicHolidays:
    def test_the_dates_are_built_in(self):
        named = {h["date"]: h["name"] for h in holidays.for_year("EG", 2026)}
        assert named["2026-10-06"] == "Armed Forces Day"
        assert named["2026-04-13"] == "Sham el-Nessim"        # Orthodox Easter Monday
        assert named["2026-03-20"] == "Eid al-Fitr"
        uk = {h["date"] for h in holidays.for_year("GB", 2026)}
        assert {"2026-04-03", "2026-04-06", "2026-08-31", "2026-12-28"} <= uk

    def test_chosen_once_for_the_unit_and_kept_off_the_plan(self, unit):
        assert unit.holidays()["unit"] is None
        unit.save_holidays({"unit": "AE"})
        day = unit.day_plan({"date": ["2026-12-02"]})["days"][0]
        assert not day["working_day"]
        away = unit.day_plan({})["away"]
        national = next(a for a in away if a["note"] == "National Day")
        assert (national["start"], national["end"]) == ("2026-12-02", "2026-12-03")

    def test_a_team_elsewhere_keeps_its_own(self, unit):
        coastal = next(t for t in unit.store.teams() if t["name"] == "COASTAL")
        unit.save_holidays({"unit": "EG", "teams": {coastal["id"]: "AE"}})
        dec = unit.day_plan({"date": ["2026-12-02"]})["days"][0]
        assert dec["working_day"]
        assert person(dec, "Mariam")["away"] and not person(dec, "Osama")["away"]
        jan = unit.day_plan({"date": ["2027-01-07"]})["days"][0]
        assert person(jan, "Osama")["away"] and not person(jan, "Mariam")["away"]

    def test_the_country_s_week_comes_with_it_when_asked(self, unit):
        unit.save_holidays({"unit": "EG", "use_week": True})
        assert sorted(unit.workbook.task_settings()["work_days"]) == [0, 1, 2, 3, 6]
        assert not unit.holidays()["week_differs"]

    def test_a_day_announced_differently_is_taken_off_or_added(self, unit):
        unit.save_holidays({"unit": "AE", "skip": ["2026-12-02"]})
        assert unit.day_plan({"date": ["2026-12-02"]})["days"][0]["working_day"]
        unit.save_holidays({"restore": True})
        assert not unit.day_plan({"date": ["2026-12-02"]})["days"][0]["working_day"]

    def test_a_city_in_the_unit_s_name_is_a_guess_to_confirm(self, unit):
        unit.unit = {"name": "Marine Structures Cairo"}
        view = unit.holidays()
        assert view["unit"] == "EG" and not view["chosen"]

    def test_an_unknown_country_is_refused(self, unit):
        from workload_app.workbook import ValidationError
        with pytest.raises(ValidationError):
            unit.save_holidays({"unit": "XX"})


class TestRequestsAsTheyComeIn:
    def test_one_line_gets_a_person_and_a_time(self, unit):
        result = unit.add_request({"title": "Check the RFI on piles",
                                   "hours": 1.5, "now": "2026-10-07T10:07"})
        # Kirolos has the most room among the engineers.
        assert result["person"] == "Kirolos"
        assert result["start"] == "2026-10-07T10:15"
        assert result["end"] == "2026-10-07T11:45"
        assert result["task"]["kind"] == "Request"

    def test_the_next_one_goes_after_it(self, unit):
        unit.add_request({"title": "One", "hours": 2, "person": "Kirolos",
                          "now": "2026-10-07T16:00"})
        second = unit.add_request({"title": "Two", "hours": 1, "person": "Kirolos",
                                   "now": "2026-10-07T16:00"})
        # The first takes the last hour and a half of today and the first
        # half hour of tomorrow; the second comes straight after it.
        assert second["start"] == "2026-10-08T09:30"
        assert second["end"] == "2026-10-08T10:30"

    def test_it_sits_in_the_day_and_adds_to_the_load(self, unit):
        before = person(unit.planner({"days": 1}), "Kirolos")["after"]["hours"]
        unit.add_request({"title": "Markup", "hours": 2, "person": "Kirolos",
                          "now": "2026-10-07T09:00"})
        day = person(unit.day_plan({})["days"][0], "Kirolos")
        assert day["blocks"][0] == {**day["blocks"][0], "start": "09:00",
                                    "end": "11:00", "kind": "request"}
        after = person(unit.planner({"days": 1}), "Kirolos")["after"]["hours"]
        assert after == pytest.approx(before + 2)

    def test_drafting_goes_to_the_drawing_office(self, unit):
        result = unit.add_request({"title": "Revise GA", "hours": 1,
                                   "role": "drafting", "now": "2026-10-07T09:00"})
        assert result["person"] == "Hany"

    def test_done_and_listed(self, unit):
        result = unit.add_request({"title": "Call the client", "hours": 0.5,
                                   "now": "2026-10-07T09:00"})
        unit.finish_request(result["task"]["id"])
        listed = unit.day_plan({})["requests"]
        assert listed[0]["done"] and listed[0]["start"] == "2026-10-07T09:00"

    def test_a_line_with_nothing_in_it_is_refused(self, unit):
        from workload_app.intake import IntakeError
        with pytest.raises(IntakeError):
            unit.add_request({"title": "", "hours": 1})
        with pytest.raises(IntakeError):
            unit.add_request({"title": "x", "hours": 500})


class TestTheSubmissionsPlan:
    def test_every_live_deliverable_gets_a_date_and_where_it_came_from(self, unit):
        data = unit.submissions()
        by_project = {i["project_number"]: i for i in data["items"]}
        item = by_project["N1-0100D"]
        # Nobody has confirmed it, so its progress is a placeholder: it is
        # dated by how long a phase usually runs here, not by effort left.
        assert item["basis"] == "typical"
        assert item["hours_left"] is None
        assert item["date"] > TODAY.isoformat()
        assert item["pace"] == pytest.approx(18)        # 8 + 3 + 7 h a day
        assert "Osama" in item["people"]

    def test_a_confirmed_project_is_dated_by_effort_left_and_pace(self, unit):
        detail = unit.project_detail("N3-0100D")
        project = dict(detail["project"], budget_mm=2, cac_override=2,
                       start="2026-01-01", end="2026-12-31", notes="")
        unit.save_project_with_deliverables(
            "N3-0100D", {"project": project, "deliverables": detail["deliverables"]})
        item = next(i for i in unit.submissions()["items"]
                    if i["project_number"] == "N3-0100D")
        assert item["basis"] == "estimated"
        # 80% of 2 MM, less the 60 h booked, at Mariam's 4 h a day.
        left = 2 * 185 * 0.8 - 60
        assert item["hours_left"] == pytest.approx(left, abs=1)
        assert item["date"] == submissions.add_working_days(
            TODAY, math.ceil(left / 4), {"work_days": [0, 1, 2, 3, 4]}).isoformat()

    def test_confirming_writes_the_date_and_plans_the_run_up(self, unit):
        item = next(i for i in unit.submissions()["items"]
                    if i["project_number"] == "N2-0100D")
        result = unit.confirm_submissions({"items": [
            {"row": item["row"], "date": "2026-10-16"}]})
        assert result["confirmed"] == 1 and result["tasks_added"] >= 4
        again = next(i for i in unit.submissions()["items"]
                     if i["row"] == item["row"])
        assert again["basis"] == "set" and again["date"] == "2026-10-16"
        assert again["prepared"]
        # The run-up is in Osama's day.
        day = unit.day_plan({"date": ["2026-10-12"]})["days"][0]
        assert any(b["kind"] == "submission" for b in person(day, "Osama")["blocks"])
