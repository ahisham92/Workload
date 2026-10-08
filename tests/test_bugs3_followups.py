"""Round 3 follow-ups that span several files, each pinned."""

import datetime as dt

import pytest

from workload_app import storage
from workload_app.model import ValidationError
from workload_app.service import WorkloadService

from test_planning import TODAY, department


@pytest.fixture
def unit(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
    service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
    service.import_exports(department())
    return service


def _day_off(service, day):
    with service.workbook._connect() as db:
        db.execute("INSERT INTO holidays (day, name) VALUES (?, ?)",
                   (day.isoformat(), "Day off"))


class TestTasksTabCountsTheUnitsDaysOff:
    def test_a_holiday_takes_a_day_off_the_hours_the_team_has(self, unit):
        before = unit.tasks()["load"]
        _day_off(unit, TODAY + dt.timedelta(days=1))
        after = unit.tasks()["load"]
        assert after["capacity_hours"] < before["capacity_hours"]


class TestSubmissionRunUp:
    def test_a_deliverable_that_is_no_number_gets_a_clear_message(self, unit):
        with pytest.raises(ValidationError):
            unit.generate_submission_tasks({"deliverable_row": "abc"})


class TestTheNightlyImportOfAFewRows:
    def test_one_row_fewer_out_of_five_still_goes_in(self, tmp_path, monkeypatch):
        from test_from_timesheets import D, export, row
        import test_nightly as n
        client_gen = n.client.__wrapped__(tmp_path, monkeypatch)
        client = next(client_gen)
        try:
            n.make_unit(client)
            key, _archive, _ini = n.make_kit(client)
            n.call(n.anonymous(client), "/api/nightly/timesheets", "POST",
                   {"key": key, "files": [n.tonight()]})
            fewer = export([
                row("Ahmed Mockridge", "T10001-0100D", D(2026, 3, 1), 8, grade="Lead"),
                row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8, phase=4,
                    deliverable="Detailed Design ST", grade="Lead"),
                row("Ahmed Mockridge", "LEAVE", D(2026, 8, 3), 8,
                    job_type="6-Additives", phase=0, deliverable="", grade="Lead"),
                row("Ahmed Mockridge", "T10004-0100D", D(2026, 10, 6), 6,
                    grade="Lead"),
            ], "bispark.xlsx")
            status, body = n.call(n.anonymous(client), "/api/nightly/timesheets",
                                  "POST", {"key": key, "files": [fewer]})
            assert status == 200, body

            # A token that is not text is a clear "no such preview", not a 500.
            for path in ("/api/timesheets/discard", "/api/timesheets/exports/apply",
                         "/api/timesheets/apply"):
                status, body = n.call(client, path, "POST", {"token": ["x"]})
                assert status < 500, (path, body)
        finally:
            next(client_gen, None)


class TestADeletedTasksIdIsNotGivenAgain:
    def test_a_new_task_does_not_inherit_a_done_mark(self, unit):
        wb = unit.workbook
        first = wb.save_task({"name": "Check the RFI", "assignees": ["Osama"],
                              "required_hours": 2})
        wb.store.add_mark("Osama", "done", task_id=first["id"])
        wb.delete_task(first["id"])
        second = wb.save_task({"name": "Draw the pile cap", "assignees": ["Osama"],
                               "required_hours": 4})
        assert second["id"] != first["id"]


class TestTheSiteAdministratorPickedOnTeamAccess:
    def test_they_keep_every_units_view(self, tmp_path, monkeypatch):
        import test_site as site
        from workload_app import wsgi
        from workload_app.app import WorkloadApp
        application = WorkloadApp(tmp_path / "instance")
        application.site_people = lambda: site.PEOPLE
        monkeypatch.setattr(wsgi, "_app", application)
        site.unit_for(site.AHMED)
        engineer = site.an_engineer(site.AHMED)
        status, _, given = site.ask("POST", "/api/team/access",
                                    {"engineer": engineer, "person": "2"},
                                    site=site.AHMED)
        assert status == 200, given
        admin = {**site.OSAMA, "admin": True}
        _, _, who = site.ask("GET", "/api/auth/me", site=admin)
        assert who["user"]["role"] == "manager"
        status, _, together = site.ask("GET", "/api/units/together", site=admin)
        assert status == 200, together


class TestAZipThatUnpacksToGigabytes:
    def test_it_is_refused_before_it_is_opened(self):
        import base64
        import io
        import zipfile
        from workload_app.service import ApiError
        from workload_app.service import _decode
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/worksheets/sheet1.xml", b"\0" * (300 * 1024 * 1024))
        with pytest.raises(ApiError) as refused:
            _decode(base64.b64encode(raw.getvalue()).decode())
        assert refused.value.status == 413

    def test_a_real_workbook_still_goes_through(self):
        from test_from_timesheets import team_exports
        content = team_exports()[0]["content_base64"]
        assert _decode_ok(content)


def _decode_ok(content):
    from workload_app.service import _decode
    return len(_decode(content)) > 0
