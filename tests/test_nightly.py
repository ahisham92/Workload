"""The nightly import: a PC posts BISpark's export, signed with a unit key."""

import base64
import io
import zipfile

import pytest

from test_from_timesheets import D, export, row, team_exports

pytest.importorskip("openpyxl")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from test_server import _account, _serve
    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "instance"))
    httpd = _serve(tmp_path / "instance")
    try:
        yield _account(httpd, f"http://127.0.0.1:{httpd.server_address[1]}")
    finally:
        httpd.app.close_all()
        httpd.shutdown()
        httpd.server_close()


def call(*args, **kwargs):
    from test_server import call as server_call
    return server_call(*args, **kwargs)


def anonymous(client):
    return type(client)(str(client))


def make_unit(client):
    status, body = call(client, "/api/units/from-timesheets", "POST",
                        {"files": team_exports()})
    assert status == 200, body
    return body


def make_kit(client):
    status, body = call(client, "/api/import-key", "POST",
                        {"app_url": "https://selecao.example.com/"})
    assert status == 200, body
    archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(body["kit_base64"])))
    ini = archive.read("selecao-nightly/settings.ini").decode()
    key = next(line.split("=", 1)[1].strip() for line in ini.splitlines()
               if line.startswith("key ="))
    return key, archive, ini


def tonight(extra_hours=0):
    rows = [
        row("Ahmed Mitwally", "N25185-0100D", D(2026, 3, 1), 8, grade="Lead"),
        row("Ahmed Mitwally", "N25185-0100D", D(2026, 8, 2), 8, phase=4,
            deliverable="Detailed Design ST", grade="Lead"),
        row("Ahmed Mitwally", "LEAVE", D(2026, 8, 3), 8, job_type="6-Additives",
            phase=0, deliverable="", grade="Lead"),
        row("Ahmed Mitwally", "S12066-0100D", D(2019, 5, 1), 40, phase=4,
            deliverable="Tender Documents SB", grade="P1"),
        row("Ahmed Mitwally", "AN23232-0100D", D(2026, 10, 6), 6 + extra_hours,
            grade="Lead"),
    ]
    return export(rows, "bispark.xlsx")


class TestTheKit:
    def test_the_kit_carries_the_job_and_its_settings(self, client):
        make_unit(client)
        key, archive, ini = make_kit(client)
        names = set(archive.namelist())
        for name in ("pull.py", "setup.bat", "schedule.ps1", "README.txt"):
            assert f"selecao-nightly/{name}" in names
        assert "app_url = https://selecao.example.com\r\n" in ini
        assert key.startswith("sel_")

    def test_only_the_digest_is_kept(self, client):
        make_unit(client)
        key, _archive, _ini = make_kit(client)
        _status, body = call(client, "/api/import-key")
        assert key not in str(body)
        assert body["key"]["last_result"] is None

    def test_a_kit_needs_an_open_unit(self, client):
        status, _body = call(client, "/api/import-key", "POST",
                             {"app_url": "https://x.example.com"})
        assert status == 409


class TestTheNightlyImport:
    def test_an_export_goes_in_with_the_key_alone(self, client):
        make_unit(client)
        key, _archive, _ini = make_kit(client)
        status, body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                            {"key": key, "files": [tonight()]})
        assert status == 200, body
        assert body["ok"] is True
        assert body["rows"] == 5
        assert body["last_date"] == "2026-10-06"
        assert "AN23232-0100D" in body["projects_added"]
        _status, info = call(client, "/api/import-key")
        assert info["key"]["last_result"]["ok"] is True
        # Osama's rows are not in Ahmed's export, and are left alone.
        counts = client.app.service_for(client.user["id"]).store.counts()
        assert counts["Ahmed"] == 5
        assert counts["Osama"] == 2

    def test_a_wrong_key_is_refused(self, client):
        make_unit(client)
        make_kit(client)
        status, _body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                             {"key": "sel_nope", "files": [tonight()]})
        assert status == 401

    def test_a_new_kit_shuts_the_old_one_out(self, client):
        make_unit(client)
        old, _archive, _ini = make_kit(client)
        make_kit(client)
        status, _body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                             {"key": old, "files": [tonight()]})
        assert status == 401

    def test_stopping_shuts_it_out(self, client):
        make_unit(client)
        key, _archive, _ini = make_kit(client)
        assert call(client, "/api/import-key", "DELETE")[1]["revoked"] is True
        status, _body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                             {"key": key, "files": [tonight()]})
        assert status == 401

    def test_an_export_that_would_lose_rows_is_refused(self, client):
        make_unit(client)
        key, _archive, _ini = make_kit(client)
        call(anonymous(client), "/api/nightly/timesheets", "POST",
             {"key": key, "files": [tonight()]})
        narrow = export([row("Ahmed Mitwally", "AN23232-0100D",
                             D(2026, 10, 6), 6, grade="Lead")], "bispark.xlsx")
        status, body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                            {"key": key, "files": [narrow]})
        assert status == 409, body
        assert "nothing was replaced" in body["error"]
        _status, info = call(client, "/api/import-key")
        assert info["key"]["last_result"]["ok"] is False
        # The rows from the night before are all still there.
        status, again = call(anonymous(client), "/api/nightly/timesheets", "POST",
                             {"key": key, "files": [tonight(extra_hours=1)]})
        assert status == 200, again

    def test_the_pc_can_say_the_export_failed(self, client):
        make_unit(client)
        key, _archive, _ini = make_kit(client)
        status, _body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                             {"key": key, "failed": "BISpark did not load"})
        assert status == 200
        _status, info = call(client, "/api/import-key")
        assert info["key"]["last_result"] == {
            "ok": False, "error": "BISpark did not load", "errors": []}

    def test_the_unit_the_manager_had_open_stays_open(self, client):
        make_unit(client)
        key, _archive, _ini = make_kit(client)
        _status, second = call(client, "/api/units/from-timesheets", "POST",
                               {"name": "Ports", "files": team_exports()[1:]})
        assert second["unit"]["name"] == "Ports"
        status, body = call(anonymous(client), "/api/nightly/timesheets", "POST",
                            {"key": key, "files": [tonight()]})
        assert status == 200, body
        assert body["unit"] == "Marine Structures"
        _status, now_open = call(client, "/api/status")
        assert now_open["unit"]["name"] == "Ports"
