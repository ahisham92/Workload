"""My day: the engineer's own page, and the only things a member can change.

The negative tests matter most: a member writes only for the person their
access names, only on tasks with that name on them, and only their own time
off -- whatever they put in the request.
"""

import datetime as _dt

import pytest

from workload_app import checkins as checkins_module, myday, notify
from workload_app.unit import Unit

from test_roles import call, site, osama, PASSWORD, _sign_in, Client  # noqa: F401


def _today(client):
    _status, day = call(client, "/api/me/day")
    return day


def _a_task_for(site, person, **extra):
    body = {"name": "Check the pile caps", "assignees": [person],
            "required_hours": 6, "due": extra.pop("due", None) or
            _dt.date.today().isoformat(), **extra}
    status, saved = call(site, "/api/tasks", "POST", body)
    assert status == 200, saved
    return saved.get("task", saved)


@pytest.fixture
def quiet(site):
    site.app.tell_in_background = False
    sent = []
    original = notify.run
    notify.run = lambda app, **kw: sent.append(kw) or {}
    yield sent
    notify.run = original


class TestTheDay:
    def test_the_page_is_their_own_day_in_order(self, site, osama, quiet):
        task = _a_task_for(site, "Osama")
        status, day = call(osama, "/api/me/day")
        assert status == 200, day
        assert day["engineer"] == "Osama"
        starts = [b["start"] for b in day["blocks"] if b["start"]]
        assert starts == sorted(starts)
        ids = [b["task"]["id"] for b in day["blocks"] if b.get("task")] + [
            t["id"] for t in day["later"]]
        assert task["id"] in ids

    def test_a_manager_has_no_my_day_without_access(self, site):
        status, _body = call(site, "/api/me/day")
        assert status == 404


class TestMarks:
    def test_done_ticks_the_task_and_undo_puts_it_back(self, site, osama, quiet):
        task = _a_task_for(site, "Osama")
        status, said = call(osama, f"/api/me/tasks/{task['id']}/mark", "POST",
                            {"kind": "done"})
        assert status == 200, said
        _s, tasks = call(site, "/api/tasks")
        mine = next(t for t in tasks["tasks"] if t["id"] == task["id"])
        assert mine["status"] == "Done"
        assert quiet == [], "done is not worth waking the lead for"

        status, _ = call(osama, f"/api/me/marks/{said['mark']['id']}/undo", "POST")
        assert status == 200
        _s, tasks = call(site, "/api/tasks")
        mine = next(t for t in tasks["tasks"] if t["id"] == task["id"])
        assert mine["status"] == task["status"]

    def test_stuck_reaches_check_ins_and_the_lead_is_told(self, site, osama, quiet):
        task = _a_task_for(site, "Osama")
        status, said = call(osama, f"/api/me/tasks/{task['id']}/mark", "POST",
                            {"kind": "stuck", "note": "No loads from the client"})
        assert status == 200, said
        assert len(quiet) == 1
        _s, view = call(site, "/api/checkins")
        me = next(p for p in view["people"] if p["name"] == "Osama")
        points = [c for c in me["checkpoints"] if c["kind"] == "stuck"]
        assert points and "No loads from the client" in points[0]["text"]
        assert not [c for c in me["checkpoints"]
                    if c["kind"] == "blocked" and c.get("task_id") == task["id"]]
        alerts = notify.said_alerts(view["people"], prefix="", url="./")
        assert any(a["title"] == "Osama is stuck" for a in alerts)

        status, _ = call(site, f"/api/marks/{said['mark']['id']}/seen", "POST")
        assert status == 200
        _s, view = call(site, "/api/checkins")
        me = next(p for p in view["people"] if p["name"] == "Osama")
        assert not [c for c in me["checkpoints"] if c["kind"] == "stuck"]
        day = _today(osama)
        assert day["asks"][0]["seen"] is True

    def test_help_without_a_task_needs_a_line(self, site, osama, quiet):
        status, body = call(osama, "/api/me/help", "POST", {"note": " "})
        assert status == 422
        status, said = call(osama, "/api/me/help", "POST",
                            {"note": "Second pair of eyes on the deck slab"})
        assert status == 200 and said["mark"]["kind"] == "help"

    def test_nobody_elses_task(self, site, osama, quiet):
        task = _a_task_for(site, "Kirolos")
        status, body = call(osama, f"/api/me/tasks/{task['id']}/mark", "POST",
                            {"kind": "done", "engineer": "Kirolos",
                             "person": "Kirolos"})
        assert status == 422 and "not on your list" in " ".join(body["errors"])
        _s, tasks = call(site, "/api/tasks")
        theirs = next(t for t in tasks["tasks"] if t["id"] == task["id"])
        assert theirs["status"] != "Done"

    def test_nobody_elses_mark(self, site, osama, quiet):
        status, said = call(site.app and osama, "/api/me/help", "POST",
                            {"note": "help"})
        # Kirolos, given access too, cannot undo Osama's.
        _st, granted = call(site, "/api/team/access", "POST",
                            {"engineer": "Kirolos", "username": "kirolos"})
        kirolos = Client(str(site))
        kirolos.cookie = _sign_in(site, "kirolos", granted["password"])
        status, _ = call(kirolos, f"/api/me/marks/{said['mark']['id']}/undo", "POST")
        assert status == 404

    def test_a_member_cannot_mark_seen(self, site, osama, quiet):
        status, _ = call(osama, "/api/marks/1/seen", "POST")
        assert status == 403


class TestTimeOff:
    def test_off_is_always_their_own(self, site, osama, quiet):
        start = (_dt.date.today() + _dt.timedelta(days=10)).isoformat()
        status, off = call(osama, "/api/me/off", "POST",
                           {"start": start, "end": start, "person": "Kirolos",
                            "note": "Family"})
        assert status == 200, off
        assert off["person"] == "Osama"
        assert len(quiet) == 1
        day = _today(osama)
        assert [o["start"] for o in day["off"] if o["mine"]] == [start]
        _s, view = call(site, "/api/checkins")
        me = next(p for p in view["people"] if p["name"] == "Osama")
        assert me["off_news"] and me["off_news"][0]["start"] == start

        status, _ = call(osama, f"/api/me/off/{off['mark_id']}/remove", "POST")
        assert status == 200
        assert not [o for o in _today(osama)["off"] if o["start"] == start]

    def test_the_managers_entry_stays(self, site, osama, quiet):
        start = (_dt.date.today() + _dt.timedelta(days=12)).isoformat()
        status, added = call(site, "/api/absences", "POST",
                             {"person": "Osama", "start": start, "end": start})
        assert status == 200, added
        day = _today(osama)
        entry = next(o for o in day["off"] if o["start"] == start)
        assert entry["mine"] is False and entry["mark_id"] is None

    def test_past_days_are_refused(self, site, osama, quiet):
        status, _ = call(osama, "/api/me/off", "POST",
                         {"start": "2020-01-01", "end": "2020-01-02"})
        assert status == 422


class TestReadyTimesheet:
    def test_a_week_by_job_and_phase(self, site, osama, quiet):
        status, sheet = call(osama, "/api/me/timesheet")
        assert status == 200, sheet
        assert sheet["engineer"] == "Osama"
        dates = [d["date"] for d in sheet["days"]]
        for line in sheet["lines"]:
            assert set(line["hours"]) <= set(dates)
            assert line["total"] == pytest.approx(sum(line["hours"].values()))
        assert sheet["copy"].splitlines()[0].startswith("Job\tPhase\tName")

    def test_an_old_week_comes_from_what_was_booked(self, site, osama, quiet):
        rows = site.app.service_for(site.user["id"]).store.rows_for("Osama")
        last = max(r["date"] for r in rows if r["date"])
        status, sheet = call(osama, f"/api/me/timesheet?week={last.isoformat()}")
        assert status == 200
        booked = [d for d in sheet["days"] if d["source"] == "booked"]
        assert booked
        want = sum(r["hours"] for r in rows if r["date"] and r["date"].isoformat()
                   in {d["date"] for d in booked})
        got = sum(d["total"] for d in booked)
        assert got == pytest.approx(want, abs=0.25 * 20)


class TestPureParts:
    def test_quarter_hours(self):
        assert myday.quarter(1.13) == 1.25
        assert myday.quarter(0.1) == 0.0

    def test_leave_line_on_a_day_off(self):
        config = {"work_days": [0, 1, 2, 3, 4], "day_start": "08:00",
                  "day_end": "16:00", "hours_per_day": 8,
                  "away": {"Osama": {"2030-01-07"}}}
        day = _dt.date(2030, 1, 7)
        sheet = myday.ready_timesheet(
            engineer="Osama", days=[day], plans={}, rows=[], tasks=[],
            deliverable_phases={}, project_names={}, config=config,
            leave_code="AL", today=day)
        assert sheet["lines"][0]["job"] == "AL"
        assert sheet["days"][0]["source"] == "off"
