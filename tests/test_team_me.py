""""This is me": a manager marks which person in the unit is them.

Kept per account, so two managers sharing a unit each mark themselves, and it
follows the person through a rename. Made-up timesheets; no private workbook.
"""

import pytest

from test_across import app, ask, unit  # noqa: F401  (fixture)
from test_checkins import booking, export


def _unit(app):
    unit(app, "Marine Structures", [
        export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
        export("bassem", booking("Bassem Northwind", "N1-0100D", 8))])


class TestThisIsMe:
    def test_nobody_until_said(self, app):
        _unit(app)
        assert ask("GET", "/api/team/me") == (200, {"me": ""})

    def test_mark_and_clear(self, app):
        _unit(app)
        assert ask("PUT", "/api/team/me", {"me": "Amal"}) == (200, {"me": "Amal"})
        assert ask("GET", "/api/team/me")[1] == {"me": "Amal"}
        assert ask("PUT", "/api/team/me", {"me": ""}) == (200, {"me": ""})
        assert ask("GET", "/api/team/me")[1] == {"me": ""}

    def test_somebody_not_in_the_team_is_refused(self, app):
        _unit(app)
        status, body = ask("PUT", "/api/team/me", {"me": "Nobody"})
        assert status == 404, body
        assert ask("GET", "/api/team/me")[1] == {"me": ""}

    def test_follows_a_rename(self, app):
        _unit(app)
        ask("PUT", "/api/team/me", {"me": "Amal"})
        status, body = ask("PUT", "/api/team/Amal", {"short_name": "Amala"})
        assert status == 200, body
        assert ask("GET", "/api/team/me")[1] == {"me": "Amala"}

    def test_grade_is_left_to_the_manager(self, app):
        _unit(app)
        ask("PUT", "/api/team/me", {"me": "Amal"})
        people = {p["name"]: p for p in ask("GET", "/api/people")[1]["people"]}
        assert people["Amal"]["grade"] != "manager"
        assert ask("PUT", "/api/people/Amal", {"grade": "manager"})[0] == 200
        people = {p["name"]: p for p in ask("GET", "/api/people")[1]["people"]}
        assert people["Amal"]["grade"] == "manager"

    def test_does_not_touch_the_inbox_address(self, app):
        _unit(app)
        ask("PUT", "/api/team/me", {"me": "Amal"})
        store = app.service_for(ask("GET", "/api/auth/me")[1]["user"]["id"]).store
        assert not any(k.startswith("inbox_me:") for k in store.settings())
