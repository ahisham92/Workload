"""The deployment check.

Its whole reason to exist is the second web app on one hosting account: the
mistakes there are silent ones -- a data directory inside the code that the
next deploy walks over, or two web apps pointed at the same folder -- so the
check has to name them out loud, and the WSGI file it hands out has to be
right for the checkout it was run from.
"""

import os
from pathlib import Path

import pytest

from workload_app import deployment
from workload_app.accounts import Accounts


@pytest.fixture
def outside(tmp_path, monkeypatch):
    """A data directory the way a host should have it: outside the code."""
    data = tmp_path / "workload-data"
    data.mkdir()
    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(data))
    return data


def levels(report, needle):
    return [f.level for f in report.findings if needle in f.title]


class TestWhatItLooksAt:
    def test_a_healthy_installation_is_ready_to_serve(self, outside):
        Accounts(outside / "accounts.db").create_user(
            "ahmed", "a-good-long-password", is_admin=True)
        report = deployment.check()
        assert report.ok
        assert "Ready to serve." in deployment.render(report)

    def test_it_finds_the_code_and_the_template(self, outside):
        report = deployment.check()
        assert (report.root / "workload_app" / "app.py").is_file()
        assert levels(report, "template") == ["ok"]
        assert levels(report, "Front end complete") == ["ok"]

    def test_it_reports_python_and_openpyxl(self, outside):
        report = deployment.check()
        titles = " ".join(f.title for f in report.findings)
        assert "Python" in titles and "openpyxl" in titles

    def test_no_account_means_nobody_can_sign_in(self, outside):
        report = deployment.check()
        assert levels(report, "No accounts yet") == ["warn"]
        assert report.ok          # a warning, not a refusal to start

    def test_accounts_without_an_administrator_are_a_problem(self, outside):
        Accounts(outside / "accounts.db").create_user("ahmed", "a-good-long-password")
        report = deployment.check()
        assert not report.ok
        assert "no administrator" in deployment.render(report)

    def test_it_counts_managers_and_members_apart(self, outside):
        db = Accounts(outside / "accounts.db")
        db.create_user("ahmed", "a-good-long-password", is_admin=True)
        db.create_user("osama", "a-good-long-password", role="member")
        report = deployment.check()
        assert levels(report, "2 account(s): 1 manager(s), 1 team member(s)") == ["ok"]

    def test_a_directory_that_cannot_exist_stops_the_deploy(self, tmp_path,
                                                            monkeypatch):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("a file is in the way")
        monkeypatch.setenv("WORKLOAD_DATA_DIR", str(blocker / "data"))
        report = deployment.check()
        assert not report.ok
        assert "Not ready" in deployment.render(report)

    @pytest.mark.skipif(os.geteuid() == 0,
                        reason="root writes to a read-only directory anyway")
    def test_a_directory_it_cannot_write_to_stops_the_deploy(self, tmp_path,
                                                             monkeypatch):
        data = tmp_path / "read-only"
        data.mkdir()
        data.chmod(0o500)
        monkeypatch.setenv("WORKLOAD_DATA_DIR", str(data))
        try:
            report = deployment.check()
            assert not report.ok
        finally:
            data.chmod(0o700)


class TestTheDataDirectory:
    def test_data_inside_the_code_is_the_mistake_that_loses_workbooks(
            self, monkeypatch):
        root = Path(deployment.__file__).resolve().parent.parent
        monkeypatch.setenv("WORKLOAD_DATA_DIR", str(root / "instance"))
        report = deployment.check()
        assert not report.ok
        rendered = deployment.render(report)
        assert "A deploy" in rendered and "every workbook" in rendered

    def test_the_shipped_default_is_a_warning_not_a_failure(self, monkeypatch):
        # Running from a checkout on your own machine: ./instance is fine.
        monkeypatch.delenv("WORKLOAD_DATA_DIR", raising=False)
        report = deployment.check()
        assert report.ok
        assert levels(report, "Data directory") == ["warn"]

    def test_a_directory_outside_the_code_passes(self, outside):
        report = deployment.check()
        assert levels(report, "Data directory") == ["ok"]

    def test_an_explicit_directory_beats_the_environment(self, tmp_path, outside):
        elsewhere = tmp_path / "second-app-data"
        report = deployment.check(elsewhere)
        assert report.data_dir == elsewhere.resolve()


class TestWhatToPasteIntoTheHost:
    def test_the_wsgi_file_carries_this_checkout_and_its_data(self, outside):
        text = deployment.wsgi_file()
        assert repr(str(deployment.check().root)) in text
        assert repr(str(outside.resolve())) in text
        assert "from workload_app.wsgi import application" in text

    def test_it_never_hands_back_a_data_directory_inside_the_code(
            self, monkeypatch):
        monkeypatch.delenv("WORKLOAD_DATA_DIR", raising=False)
        root = deployment.check().root
        text = deployment.wsgi_file()
        assert str(deployment.suggested_data_dir()) in text
        assert f"WORKLOAD_DATA_DIR'] = '{root}" not in text

    def test_it_is_valid_python_that_imports_the_application(self, outside):
        import ast
        ast.parse(deployment.wsgi_file())

    def test_running_it_serves_the_login_page(self, outside, tmp_path):
        """The file we tell people to paste, run the way the host runs it."""
        import io
        import runpy
        import sys

        pasted = tmp_path / "app_wsgi.py"
        pasted.write_text(deployment.wsgi_file())
        application = runpy.run_path(str(pasted))["application"]

        status = []
        body = b"".join(application(
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
             "SERVER_NAME": "workload-you.pythonanywhere.com",
             "SERVER_PORT": "443", "wsgi.input": io.BytesIO(b""),
             "wsgi.errors": sys.stderr, "wsgi.url_scheme": "https"},
            lambda code, headers: status.append(code)))
        assert status == ["200 OK"]
        assert b"password" in body.lower()
        assert os.environ["WORKLOAD_DATA_DIR"] == str(outside.resolve())

    def test_it_says_the_two_web_apps_must_not_share(self, outside):
        text = deployment.wsgi_file()
        assert "Another web app" in text
        assert "not shared with any other web app" in text

    def test_the_static_mappings_point_at_files_that_exist(self, outside):
        mappings = deployment.static_files()
        assert {m["url"] for m in mappings} == {
            "/app.css", "/app.js", "/member.js", "/charts.js"}
        for mapping in mappings:
            assert Path(mapping["path"]).is_file()

    def test_the_shipped_wsgi_file_matches_the_generated_one(self, outside):
        shipped = (Path(deployment.__file__).resolve().parent.parent
                   / "deploy" / "pythonanywhere_wsgi.py").read_text()
        assert "os.environ['WORKLOAD_DATA_DIR'] = DATA" in shipped
        assert "from workload_app.wsgi import application" in shipped


class TestTheCommand:
    def test_check_prints_the_report_and_the_wsgi_file(self, outside, capsys):
        from workload_app import admin
        Accounts(outside / "accounts.db").create_user(
            "ahmed", "a-good-long-password", is_admin=True)
        assert admin.main(["check"]) == 0
        out = capsys.readouterr().out
        assert "Workload deployment check" in out
        assert "Static files" in out
        assert str(outside.resolve()) in out

    def test_it_exits_non_zero_when_the_installation_cannot_serve(
            self, outside, capsys):
        Accounts(outside / "accounts.db").create_user("ahmed", "a-good-long-password")
        from workload_app import admin
        assert admin.main(["check"]) == 1

    def test_wsgi_only_prints_a_file_and_nothing_else(self, outside, capsys):
        import ast
        from workload_app import admin
        assert admin.main(["check", "--wsgi-only"]) == 0
        ast.parse(capsys.readouterr().out)

    def test_it_does_not_make_an_account_database_of_its_own(self, tmp_path,
                                                             monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("WORKLOAD_DATA_DIR", raising=False)
        from workload_app import admin
        admin.main(["check", "--wsgi-only"])
        assert not (tmp_path / "instance" / "accounts.db").exists()
