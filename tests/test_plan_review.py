"""Working to a plan: the week locked, checked against what happened; what an
urgent request pushes; and what-ifs kept to compare.

The rules that matter most: a lock already made is never redone by itself,
a member gives reasons only on their own lines, and nothing a request only
tries is saved.
"""

import datetime as _dt
import json

import pytest

from workload_app import service as service_module, tasks as task_sheet, weekplan
from workload_app import config as cfg

from test_roles import call, site, osama, PASSWORD, _sign_in, Client  # noqa: F401


def _task(site, person, hours=6, due=None, **extra):
    body = {"name": extra.pop("name", "Check the pile caps"), "assignees": [person],
            "required_hours": hours,
            "due": due or _dt.date.today().isoformat(), **extra}
    status, saved = call(site, "/api/tasks", "POST", body)
    assert status == 200, saved
    return saved.get("task", saved)


def _next_working(day, count=1):
    while count:
        day += _dt.timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


# --------------------------------------------------------------------------
# the sums, on made-up figures
# --------------------------------------------------------------------------

MON = _dt.date(2026, 9, 7)
WEEK = [MON + _dt.timedelta(days=i) for i in range(5)]


def _line(id_, person, kind, job="", task_id=None, hours=0.0, title="", due=None,
          reason=""):
    return {"id": id_, "person": person, "kind": kind, "job_number": job,
            "task_id": task_id, "hours": hours, "title": title or job, "due": due,
            "reason": reason, "reason_note": "", "locked_at": "2026-09-07T04:00:00"}


def _row(person, day, job, hours, job_type="1-Project"):
    return {"engineer": person, "date": day, "job_number": job, "hours": hours,
            "job_type": job_type}


class TestTheSums:
    def test_kept_slips_and_work_on_top(self):
        done = task_sheet.Task(id=1, name="Pile caps", project_number="J1",
                               assignees=["Mona"], required_hours=6,
                               due=WEEK[2], status=cfg.TASK_DONE_STATUS)
        late = task_sheet.Task(id=2, name="Deck slab", project_number="J1",
                               assignees=["Mona"], required_hours=8, due=WEEK[3])
        request = task_sheet.Task(id=3, name="RFI reply", project_number="J2",
                                  assignees=["Mona"], required_hours=4, due=WEEK[1],
                                  kind=cfg.TASK_REQUEST_KIND)
        lines = [_line(10, "Mona", "job", "J1", hours=30),
                 _line(11, "Mona", "job", "J3", hours=8),
                 _line(12, "Mona", "task", "J1", 1, 6, "Pile caps"),
                 _line(13, "Mona", "task", "J1", 2, 8, "Deck slab", WEEK[3].isoformat(),
                       reason="client"),
                 _line(14, "Mona", "other", hours=4, title=weekplan.OTHER_TITLE)]
        rows = ([_row("Mona", d, "J1", 5) for d in WEEK]
                + [_row("Mona", WEEK[1], "J2", 6)]
                + [_row("Mona", WEEK[0] - _dt.timedelta(days=3), "J1", 8)])
        slots = {3: {"person": "Mona", "start": f"{WEEK[1]}T10:00",
                     "end": f"{WEEK[1]}T14:00"}}
        view = weekplan.review(week_days=WEEK, lines=lines, locked=True, rows=rows,
                               tasks=[done, late, request], slots=slots,
                               today=WEEK[-1] + _dt.timedelta(days=3),
                               project_names={"J1": "Jetty"})
        mona = view["people"][0]
        assert view["state"] == "past"
        assert mona["timesheet_in"]
        # 25 of 30 on the jetty kept, nothing of the 8 on J3: 25 / 38.
        assert mona["kept"] == pytest.approx(25 / 38, abs=1e-3)
        assert mona["tasks_done"] == 1 and mona["tasks_planned"] == 2
        assert [t["state"] for t in mona["tasks"]] == ["late", "done"]
        what = {s["kind"]: s for s in mona["slips"]}
        assert what["task"]["reason"] == "client"
        assert what["job"]["job"] == "J3"                 # 0 of 8 h
        assert mona["on_top"][0]["title"] == "RFI reply"
        unplanned = [j for j in mona["jobs"] if j.get("unplanned")]
        assert unplanned[0]["job"] == "J2" and unplanned[0]["booked"] == 6
        assert view["reasons"][0] == {"key": "client", "label": weekplan.REASONS["client"],
                                      "count": 1}
        assert view["what_next"]

    def test_hours_wait_for_the_timesheet(self):
        lines = [_line(10, "Mona", "job", "J1", hours=30)]
        view = weekplan.review(week_days=WEEK, lines=lines, locked=True, rows=[],
                               tasks=[], slots={}, today=WEEK[-1] + _dt.timedelta(days=2),
                               project_names={})
        mona = view["people"][0]
        assert mona["timesheet_in"] is False and mona["kept"] is None
        assert mona["slips"] == []
        assert any("Timesheets not in yet" in line for line in view["what_next"])

    def test_snapshot_from_the_day_plan(self):
        task = task_sheet.Task(id=7, name="Calcs", project_number="J1",
                               assignees=["Mona"], required_hours=4, due=WEEK[1])
        pages = [{"people": [{"name": "Mona", "blocks": [
            {"hours": 2, "task_id": 7, "project": "J1", "kind": "task"},
            {"hours": 5, "task_id": None, "project": "J1", "kind": "work"},
            {"hours": 1, "task_id": None, "project": "", "kind": "meeting"}]}]}
            for _ in WEEK[:2]]
        lines = weekplan.snapshot(pages, [task], {"J1": "Jetty"})
        by = {(l["kind"], l["job_number"]): l for l in lines}
        assert by[("job", "J1")]["hours"] == 14 and by[("job", "J1")]["title"] == "Jetty"
        assert by[("task", "J1")]["hours"] == 4 and by[("task", "J1")]["task_id"] == 7
        assert by[("other", "")]["hours"] == 2


# --------------------------------------------------------------------------
# through the app
# --------------------------------------------------------------------------

class TestLocking:
    def test_the_first_look_locks_once(self, site):
        _task(site, "Osama", due=_next_working(_dt.date.today(), 2).isoformat())
        status, view = call(site, "/api/plan-review")
        assert status == 200, view
        assert view["locked"] is True and view["state"] == "current"
        first = view["locked_at"]
        assert any(p["name"] == "Osama" for p in view["people"])
        # Work changes; looking again never redoes the lock.
        _task(site, "Osama", hours=3, name="Late extra")
        _s, again = call(site, "/api/plan-review")
        assert again["locked_at"] == first
        assert not any(t["title"] == "Late extra" for p in again["people"]
                       for t in p["tasks"])

    def test_the_daily_run_never_redoes_a_lock(self, site):
        _s, view = call(site, "/api/plan-review")
        app = site.app
        svc = service_module.WorkloadService(autosave=False)
        app._open(svc, site.user["id"], site.unit["id"])
        try:
            assert svc.lock_week_if_due() is False
        finally:
            svc.close()
        _s, again = call(site, "/api/plan-review")
        assert again["locked_at"] == view["locked_at"]

    def test_relock_keeps_the_reasons(self, site):
        _task(site, "Osama", due=_next_working(_dt.date.today(), 1).isoformat())
        _s, view = call(site, "/api/plan-review")
        line = next(t for p in view["people"] for t in p["tasks"])
        status, said = call(site, "/api/plan-review/reason", "POST",
                            {"id": line["id"], "reason": "client", "note": "No loads"})
        assert status == 200, said
        status, locked = call(site, "/api/plan-review/lock", "POST", {"week": view["week"]})
        assert status == 200, locked
        _s, after = call(site, "/api/plan-review")
        again = next(t for p in after["people"] for t in p["tasks"]
                     if t["task_id"] == line["task_id"])
        assert again["reason"] == "client" and again["note"] == "No loads"

    def test_a_past_week_cannot_be_locked(self, site):
        status, body = call(site, "/api/plan-review/lock", "POST", {"week": "2025-01-06"})
        assert status == 422

    def test_a_reason_must_be_one_of_the_list(self, site):
        _task(site, "Osama")
        _s, view = call(site, "/api/plan-review")
        line = next(t for p in view["people"] for t in p["tasks"])
        status, _ = call(site, "/api/plan-review/reason", "POST",
                         {"id": line["id"], "reason": "the dog ate it"})
        assert status == 422

    def test_a_member_cannot_lock_or_see_everybody(self, site, osama):
        assert call(osama, "/api/plan-review")[0] == 403
        assert call(osama, "/api/plan-review/lock", "POST", {})[0] == 403


class TestMyWeek:
    def test_their_own_week_only(self, site, osama):
        _task(site, "Osama", name="Mine")
        _task(site, "Kirolos", name="Not mine")
        call(site, "/api/plan-review")                   # the week is locked
        status, week = call(osama, "/api/me/week")
        assert status == 200, week
        assert week["engineer"] == "Osama" and week["locked"] is True
        titles = [t["title"] for t in week["me"]["tasks"]]
        assert "Mine" in titles and "Not mine" not in titles
        assert "people" not in week

    def test_reasons_only_on_their_own_lines(self, site, osama):
        _task(site, "Osama", name="Mine")
        _task(site, "Kirolos", name="Theirs")
        _s, view = call(site, "/api/plan-review")
        theirs = next(t for p in view["people"] if p["name"] == "Kirolos"
                      for t in p["tasks"])
        mine = next(t for p in view["people"] if p["name"] == "Osama"
                    for t in p["tasks"])
        status, _ = call(osama, "/api/me/week/reason", "POST",
                         {"id": theirs["id"], "reason": "longer",
                          "person": "Kirolos", "engineer": "Kirolos"})
        assert status == 404
        _s, again = call(site, "/api/plan-review")
        still = next(t for p in again["people"] if p["name"] == "Kirolos"
                     for t in p["tasks"])
        assert still["reason"] == ""
        status, said = call(osama, "/api/me/week/reason", "POST",
                            {"id": mine["id"], "reason": "longer"})
        assert status == 200, said
        # The lead's own reason is not the member's to change.
        call(site, "/api/plan-review/reason", "POST", {"id": mine["id"], "reason": "client"})
        status, _ = call(osama, "/api/me/week/reason", "POST",
                         {"id": mine["id"], "reason": "other"})
        assert status == 422


class TestUrgent:
    def test_what_it_pushes_before_it_is_added(self, site):
        tomorrow = _next_working(_dt.date.today(), 1)
        _task(site, "Osama", hours=14, due=tomorrow.isoformat(), name="Due tomorrow")
        _s, before = call(site, "/api/tasks")
        status, view = call(site, "/api/requests/preview", "POST", {
            "title": "Client wants the bearing check", "hours": 8, "due":
            tomorrow.isoformat(), "person": "Osama", "role": "engineering",
            "now": f"{_dt.date.today()}T08:00"})
        assert status == 200, view
        assert view["person"] == "Osama"
        urgent = view["urgent"]
        assert urgent["pushed_hours"] > 0 and urgent["verdict"].startswith("Pushes")
        assert urgent["pushed_mm"] is not None
        assert view["room"]["urgency"] == "room"
        assert view["room"]["pushed_hours"] <= urgent["pushed_hours"]
        assert all(o["person"] != "Osama" for o in view["others"])
        _s, after = call(site, "/api/tasks")
        assert len(after["tasks"]) == len(before["tasks"]), "a preview saves nothing"

    def test_when_there_is_room_waits_for_free_time(self, site):
        due = _next_working(_dt.date.today(), 5).isoformat()
        now = f"{_dt.date.today()}T08:00"
        body = {"title": "Tidy the sketch", "hours": 1, "due": due,
                "person": "Osama", "now": now}
        status, urgent = call(site, "/api/requests", "POST", body)
        assert status == 200, urgent
        assert urgent["urgency"] == "urgent"
        status, room = call(site, "/api/requests", "POST",
                            {**body, "title": "Another", "urgency": "room"})
        assert status == 200, room
        assert room["urgency"] == "room"
        assert room["start"] >= urgent["end"]


class TestWhatIfs:
    def test_keep_compare_and_delete(self, site, monkeypatch):
        moves = [{"kind": "extra", "to": "Osama", "project": "New berth", "hours": 30}]
        status, view = call(site, "/api/planner", "POST", {"days": 5, "moves": moves})
        assert status == 200, view
        osama = next(p for p in view["people"] if p["name"] == "Osama")
        assert osama["after"]["hours"] > osama["before"]["hours"]
        assert any(i["name"] == "New: New berth" for i in osama["items"])

        status, saved = call(site, "/api/what-ifs", "POST",
                             {"name": "Berth comes in", "days": 5, "moves": moves})
        assert status == 200, saved
        _s, listed = call(site, "/api/what-ifs")
        item = next(w for w in listed["what_ifs"] if w["id"] == saved["id"])
        assert item["summary"]["hours"] > 0 and item["moves"][0]["kind"] == "extra"

        status, refused = call(site, "/api/planner/commit", "POST",
                               {"days": 5, "moves": moves})
        assert status == 422

        status, _ = call(site, f"/api/what-ifs/{saved['id']}", "DELETE")
        assert status == 200
        _s, listed = call(site, "/api/what-ifs")
        assert not listed["what_ifs"]

    def test_capped(self, site, monkeypatch):
        monkeypatch.setattr(service_module, "WHAT_IF_LIMIT", 2)
        moves = [{"kind": "extra", "to": "Osama", "project": "X", "hours": 5}]
        for name in ("One", "Two"):
            assert call(site, "/api/what-ifs", "POST",
                        {"name": name, "moves": moves})[0] == 200
        status, body = call(site, "/api/what-ifs", "POST", {"name": "Three", "moves": moves})
        assert status == 422 and "Delete one first" in " ".join(body["errors"])

    def test_a_member_cannot_keep_one(self, site, osama):
        assert call(osama, "/api/what-ifs")[0] == 403
        assert call(osama, "/api/what-ifs", "POST", {"name": "x", "moves": []})[0] == 403


class TestCairoWeek:
    def test_a_sunday_week_is_copied_on_sunday(self):
        from workload_app import daily
        config = {**cfg.DEFAULTS, "work_days": [6, 0, 1, 2, 3]} if hasattr(cfg, "DEFAULTS") \
            else {"work_days": [6, 0, 1, 2, 3], "holidays": [], "away": {}}
        friday = _dt.date(2026, 10, 9)
        days = weekplan.current_week(friday, config, daily.week_of)
        assert days[0] == _dt.date(2026, 10, 11) and days[0].weekday() == 6
        assert weekplan.current_week(_dt.date(2026, 10, 11), config, daily.week_of)[0] \
            == _dt.date(2026, 10, 11)
