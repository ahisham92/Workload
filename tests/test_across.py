"""All of a manager's units side by side, on Check-ins.

Somebody with more than one unit sees each unit and each of its teams in one
table, how much leading people takes from their day across all of them, and
who books time in more than one unit. Made-up timesheets; no private workbook.
"""

import io
import json

import pytest

from workload_app import across, wsgi
from workload_app.app import WorkloadApp

from test_checkins import TODAY, booking, export

SITE = {"id": 1, "login": "ahmed@example.com", "name": "Ahmed", "home": "/",
        "label": "AHM", "logout": "/logout"}


def ask(method, path, body=None):
    raw = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "SCRIPT_NAME": "/workload", "PATH_INFO": path,
               "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
               "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw),
               "wsgi.url_scheme": "https", wsgi.SITE_KEY: SITE}
    seen = {}
    payload = b"".join(wsgi.application(environ, lambda s, h: seen.update(s=s)))
    return int(seen["s"].split()[0]), json.loads(payload)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
    application = WorkloadApp(tmp_path / "instance")
    monkeypatch.setattr(wsgi, "_app", application)
    return application


def unit(app, name, files):
    status, made = ask("POST", "/api/units", {"name": name})
    assert status == 200, made
    me = ask("GET", "/api/auth/me")[1]["user"]["id"]
    app.service_for(me).import_exports(files)
    return made["unit"]["id"]


class TestAllUnits:
    def test_two_units_side_by_side(self, app):
        unit(app, "Marine Structures", [
            export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
            export("bassem", booking("Bassem Northwind", "N1-0100D", 11, overtime=2.5))])
        ask("PUT", "/api/people/Amal", {"grade": "manager"})
        second = unit(app, "Geotechnics", [
            export("amal", booking("Amal Ashdown", "G1-0200D", 2)),
            export("dina", booking("Dina Ashgrove", "G1-0200D", 3))])
        ask("PUT", "/api/people/Amal", {"grade": "manager"})

        status, view = ask("GET", "/api/units/together")
        assert status == 200, view
        assert [u["name"] for u in view["units"]] == ["Geotechnics", "Marine Structures"]
        assert view["current"] == second
        assert view["totals"]["units"] == 2 and view["totals"]["people"] == 3
        marine = next(u for u in view["units"] if u["name"] == "Marine Structures")
        assert marine["rest"] == 1                       # Bassem
        # Amal leads in both, and it adds up.
        amal = next(l for l in view["leaders"] if l["name"] == "Amal")
        assert [u["unit"] for u in amal["units"]] == ["Geotechnics", "Marine Structures"]
        assert amal["hours_a_day"] == pytest.approx(
            sum(u["hours_a_day"] for u in amal["units"]))
        assert [p["name"] for p in view["people_in_several"]] == ["Amal"]
        # The unit open in the browser is still the one open.
        names = {p["name"] for p in ask("GET", "/api/checkins")[1]["people"]}
        assert names == {"Amal", "Dina"}

    def test_leading_more_than_half_the_day_is_flagged(self):
        summary = {"name": "U", "teams": [], "free_week": 0, "rest": 0, "urgent": 0,
                   "leading": [{"name": "Amal", "people": 9, "hours_a_day": 2.5}]}
        twice = across.combine([(summary, {}), ({**summary, "name": "V"}, {})],
                               hours_per_day=8.5)
        assert twice["leaders"][0]["hours_a_day"] == 5.0
        assert twice["leaders"][0]["too_much"] is True
