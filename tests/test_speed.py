"""What is kept between requests, and that it never changes a figure.

Every tab's figures are worked out once per revision of the unit and kept
(``service._remembered``); the timesheet rows are read once and kept until
the rows themselves are written; a unit opened again in the same worker
starts from what that worker already read.  These tests hold all of it to
the one rule that matters: the answer is the same as working it out afresh,
after any change, made here or by another worker.
"""

import datetime as dt
import gzip
import json
import os
import shutil
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from workload_app import unit as unit_module
from workload_app.app import Request, WorkloadApp
from workload_app.service import WorkloadService
from workload_app.timesheet_store import Row, TimesheetStore
from workload_app.unit import Unit

#: Every read a tab makes that is kept, with the arguments the tabs send.
VIEWS = [
    ("overview", (2026,)), ("overview", (None,)), ("projects", ()),
    ("deliverables", ()), ("reports", ("year", None, None)),
    ("reports", ("all", None, None)), ("roster", ()), ("resourcing", (None,)),
    ("portfolio_map", (None,)), ("drawings", ()), ("needs", ()),
    ("checkins", ()), ("day_plan", ({},)), ("day_plan", ({"span": ["week"]},)),
    ("holidays", ()), ("submissions", ()),
]
#: The ones a change is checked against: one of each kind of figure.
AFTER_A_CHANGE = [("overview", (2026,)), ("projects", ()),
                  ("reports", ("year", None, None)), ("roster", ()),
                  ("needs", ()), ("checkins", ()), ("holidays", ())]


@pytest.fixture(autouse=True)
def fresh_worker():
    """Each test starts as a worker that has read nothing yet."""
    unit_module._open_units.clear()
    yield
    unit_module._open_units.clear()


def _open(path) -> WorkloadService:
    service = WorkloadService(autosave=True)
    service.open(path, unit={"id": "u1", "name": "Marine Structures"})
    return service


def _views(service, views=AFTER_A_CHANGE):
    return {f"{name}{args}": json.loads(json.dumps(getattr(service, name)(*args),
                                                   default=str))
            for name, args in views}


def _afresh(path, monkeypatch, views=AFTER_A_CHANGE):
    """Every view worked out with nothing kept at all, as before caching."""
    with monkeypatch.context() as m:
        m.setattr(Unit, "_cached", lambda self, key, build: build())
        unit_module._open_units.clear()
        try:
            return _views(_open(path), views)
        finally:
            unit_module._open_units.clear()


def _same(kept, afresh):
    assert kept.keys() == afresh.keys()
    for key in kept:
        assert kept[key] == afresh[key], key


class TestFiguresDoNotChange:
    def test_kept_answers_are_the_ones_worked_out_afresh(self, unit_copy, monkeypatch):
        service = _open(unit_copy)
        first = _views(service, VIEWS)
        again = _views(service, VIEWS)          # every one from what was kept
        _same(first, again)
        _same(again, _afresh(unit_copy, monkeypatch, VIEWS))

    def test_changing_an_answer_does_not_change_the_next(self, unit_copy):
        service = _open(unit_copy)
        before = service.projects()
        before["projects"].clear()
        before["metrics"][0]["actual_mm"] = 12345
        after = service.projects()
        assert after["projects"] and after["metrics"][0]["actual_mm"] != 12345

    def test_rows_are_shared_so_cannot_be_changed(self, unit_copy):
        rows = Unit(unit_copy).store.all_rows()
        assert rows and isinstance(rows[0], Row)
        with pytest.raises(TypeError):
            rows[0]["hours"] = 0
        with pytest.raises(TypeError):
            rows[0].update(hours=0)
        copy = dict(rows[0])
        copy["hours"] = 0                       # a copy is anybody's to change


class TestAChangeIsSeenAtOnce:
    def test_a_change_made_here(self, unit_copy, monkeypatch):
        service = _open(unit_copy)
        _views(service)
        person = service.roster()["people"][0]["name"]
        service.add_absence({"person": person, "start": "2026-09-07",
                             "end": "2026-09-11"})
        service.add_engineer({"short_name": "Newcomer", "full_name": "A Newcomer",
                              "grade": "Engineer"})
        _same(_views(service), _afresh(unit_copy, monkeypatch))

    def test_rows_written_by_another_worker(self, unit_copy, monkeypatch):
        service = _open(unit_copy)
        kept = _views(service)
        other = TimesheetStore(unit_copy)       # another process's handle
        person = other.all_rows()[0]["engineer"]
        other.append(person, [{"date": "2026-08-31", "job_number": "LEAVE",
                               "job_type": "Leave", "hours": 8.5}])
        service.refresh()
        now = _views(service)
        assert now != kept
        _same(now, _afresh(unit_copy, monkeypatch))

    def test_rows_changed_under_the_app_entirely(self, unit_copy, monkeypatch):
        """Even a write the app did not make is seen: the database counts it."""
        service = _open(unit_copy)
        kept = _views(service)
        db = sqlite3.connect(unit_copy)
        db.execute("UPDATE rows SET hours = hours * 2")
        db.commit()
        db.close()
        service.refresh()
        now = _views(service)
        assert now != kept
        _same(now, _afresh(unit_copy, monkeypatch))

    def test_anything_else_written_by_another_worker(self, unit_copy, monkeypatch):
        service = _open(unit_copy)
        _views(service)
        rows_before = service.store.all_rows()
        other = Unit(unit_copy)
        project = other.projects()[0]
        data = project.to_dict()
        data["status"] = "Cancelled"
        other.update_project(project.number, data)
        service.refresh()
        _same(_views(service), _afresh(unit_copy, monkeypatch))
        # ...and the rows, which did not change, were not read again.
        assert service.store.all_rows()[0] is rows_before[0]

    def test_a_copy_put_back_with_the_same_counts(self, unit_copy, tmp_path, monkeypatch):
        """A restored copy is a new file, even if it has made as many writes."""
        service = _open(unit_copy)
        _views(service)
        changed = tmp_path / "changed.db"
        shutil.copy(unit_copy, changed)
        db = sqlite3.connect(changed)
        db.execute("UPDATE rows SET hours = hours + 1")
        db.execute("UPDATE settings SET value = ? WHERE key = 'unit.rows_revision'",
                   (service.workbook.revision[2],))
        db.commit()
        db.close()
        os.replace(changed, unit_copy)
        assert unit_module.shared(unit_copy) is not service.workbook
        service.refresh()
        _same(_views(service), _afresh(unit_copy, monkeypatch))


class TestOpeningAgain:
    def test_the_worker_keeps_what_it_read(self, unit_copy):
        first = _open(unit_copy)
        first.needs()
        second = _open(unit_copy)
        assert second.workbook is first.workbook

    def test_a_write_in_between_is_still_seen(self, unit_copy, monkeypatch):
        first = _open(unit_copy)
        _views(first)
        first.close()
        TimesheetStore(unit_copy).forget(Unit(unit_copy).store.all_rows()[0]["engineer"])
        _same(_views(_open(unit_copy)), _afresh(unit_copy, monkeypatch))


# -- delivery ---------------------------------------------------------------

@pytest.fixture
def app(tmp_path):
    return WorkloadApp(tmp_path / "instance")


def _get(app, path, **headers):
    query = {}
    if "?" in path:
        path, _, qs = path.partition("?")
        query = {k: [v] for k, v in (p.split("=") for p in qs.split("&"))}
    return app.handle(Request(method="GET", path=path, query=query,
                              accept_encoding=headers.get("encoding", ""),
                              if_none_match=headers.get("etag", "")))


class TestDelivery:
    def test_scripts_compressed_and_checked_not_resent(self, app):
        plain = _get(app, "/app.js")
        assert plain.status == 200 and b"function" in plain.body
        etag = dict(plain.headers)["ETag"]
        assert dict(plain.headers)["Cache-Control"] == "no-cache"
        packed = _get(app, "/app.js", encoding="gzip, deflate")
        assert ("Content-Encoding", "gzip") in packed.headers
        assert gzip.decompress(packed.body) == plain.body
        assert len(packed.body) < len(plain.body) / 2
        again = _get(app, "/app.js", etag=etag)
        assert again.status == 304 and again.body == b""

    def test_a_versioned_script_is_kept(self, app):
        version = dict(_get(app, "/app.js").headers)["ETag"].strip('"')
        kept = dict(_get(app, f"/app.js?v={version}").headers)
        assert "immutable" in kept["Cache-Control"]
        stale = dict(_get(app, "/app.js?v=000000000000").headers)
        assert stale["Cache-Control"] == "no-cache"

    def test_the_service_worker_is_always_checked(self, app):
        response = _get(app, "/sw.js", etag="")
        version = dict(response.headers)["ETag"].strip('"')
        assert dict(_get(app, f"/sw.js?v={version}").headers)["Cache-Control"] == "no-cache"

    def test_the_page_names_its_scripts_by_version(self, app):
        page = _get(app, "/")                  # nobody signed in: the sign-in page
        assert page.status == 200
        assert not any(name == "Cache-Control" for name, _ in page.headers)
        from workload_app.app import STATIC_DIR, _Asset
        index = _Asset(STATIC_DIR / "index.html").versioned_page().decode()
        version = dict(_get(app, "/app.js").headers)["ETag"].strip('"')
        assert f'src="app.js?v={version}"' in index
        assert 'href="app.css?v=' in index
        assert 'href="manifest.json"' in index      # only scripts and styles

    def test_json_is_compressed_when_it_is_big(self):
        from workload_app.app import Response, _compressed
        big = Response.json(200, {"rows": [{"hours": n} for n in range(2000)]})
        body = big.body
        packed = _compressed(big, Request(method="GET", path="/api/x",
                                          accept_encoding="gzip"))
        assert ("Content-Encoding", "gzip") in packed.headers
        assert gzip.decompress(packed.body) == body
        small = Response.json(200, {"ok": True})
        assert _compressed(small, Request(method="GET", path="/api/x",
                                          accept_encoding="gzip")).body == b'{"ok": true}'
        refused = Response.json(200, {"rows": list(range(2000))})
        assert _compressed(refused, Request(method="GET", path="/api/x")).headers == []


class TestOverHttp:
    def test_headers_reach_the_browser(self, tmp_path):
        from workload_app.server import make_server
        httpd = make_server(tmp_path / "instance", "127.0.0.1", 0, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    base + "/app.js", headers={"Accept-Encoding": "gzip"})) as r:
                assert r.headers["Content-Encoding"] == "gzip"
                assert r.headers["Cache-Control"] == "no-cache"
                etag = r.headers["ETag"]
                gzip.decompress(r.read())
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(
                    base + "/app.js", headers={"If-None-Match": etag}))
            assert caught.value.code == 304
            with urllib.request.urlopen(base + "/api/auth/me") as r:
                assert r.headers["Cache-Control"] == "no-store"
        finally:
            httpd.shutdown()
