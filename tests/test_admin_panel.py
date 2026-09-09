"""The Admin tab: who may see it, and the passwords it shows.

Passwords being readable is a deliberate choice, not an accident, so the tests
say exactly how far it goes: an administrator can read them, nobody else can,
they are not in the account list that loads on every visit, and the database on
its own -- without the key file beside it -- does not give them up.
"""

import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from workload_app import secretbox
from workload_app.accounts import Accounts
from workload_app.server import make_server

PASSWORD = "a-good-long-password"


@pytest.fixture
def db(tmp_path):
    return Accounts(tmp_path / "accounts.db")


class Site:
    """A running app with one account of each kind. No workbook needed."""

    def __init__(self, base, app):
        self.base, self.app, self.cookie = base, app, ""
        self.ids = {}

    def sign_in(self, username):
        request = urllib.request.Request(
            self.base + "/api/auth/login", method="POST",
            data=json.dumps({"username": username,
                             "password": f"{username}-long-password"}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request) as response:
            self.cookie = response.headers.get("Set-Cookie", "").split(";")[0]
        return self

    def get(self, path):
        return self.call(path)[1]

    def status(self, path):
        return self.call(path)[0]

    def call(self, path):
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        request = urllib.request.Request(self.base + path, headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "instance"))
    httpd = make_server(tmp_path / "instance", "127.0.0.1", 0, quiet=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    site = Site(f"http://127.0.0.1:{httpd.server_address[1]}", httpd.app)
    accounts = httpd.app.accounts
    site.ids["ahmed"] = accounts.create_user(
        "ahmed", "ahmed-long-password", is_admin=True)["id"]
    site.ids["osama"] = accounts.create_user(
        "osama", "osama-long-password")["id"]
    site.ids["kirolos"] = accounts.create_user(
        "kirolos", "kirolos-long-password", role="member")["id"]
    yield site
    httpd.app.close_all()
    httpd.shutdown()


class TestTheSealedCopy:
    def test_a_new_account_keeps_a_readable_password(self, db):
        user = db.create_user("ahmed", PASSWORD, is_admin=True)
        assert db.password_of(user["id"]) == PASSWORD
        assert user["password_stored"] is True

    def test_a_reset_replaces_it(self, db):
        user = db.create_user("osama", PASSWORD)
        db.set_password(user["id"], "another-long-password")
        assert db.password_of(user["id"]) == "another-long-password"

    def test_every_account_at_once_for_the_tab(self, db):
        one = db.create_user("ahmed", PASSWORD, is_admin=True)
        two = db.create_user("kirolos", "kirolos-long-password", role="member")
        assert db.passwords() == {one["id"]: PASSWORD,
                                  two["id"]: "kirolos-long-password"}

    def test_the_hash_is_still_what_signs_you_in(self, db):
        """The sealed copy is for reading, never for checking."""
        user = db.create_user("ahmed", PASSWORD)
        with sqlite3.connect(db.path) as connection:
            connection.execute("UPDATE users SET password_seal = ? WHERE id = ?",
                               (secretbox.seal(db._key, "not-my-password"),
                                user["id"]))
        assert db.verify("ahmed", PASSWORD) is not None
        assert db.verify("ahmed", "not-my-password") is None

    def test_the_database_alone_does_not_give_them_up(self, db, tmp_path):
        db.create_user("ahmed", PASSWORD)
        raw = (tmp_path / "accounts.db").read_bytes()
        assert PASSWORD.encode() not in raw
        # ... and the key that would open it is not in there either.
        assert (tmp_path / "secret.key").read_bytes() not in raw

    def test_the_key_file_is_private(self, tmp_path, db):
        assert oct((tmp_path / "secret.key").stat().st_mode)[-3:] == "600"

    def test_a_different_key_reads_nothing(self, db, tmp_path):
        user = db.create_user("ahmed", PASSWORD)
        stranger = Accounts(db.path, secret_key=b"\x00" * 32)
        assert stranger.password_of(user["id"]) is None
        assert stranger.users()[0]["password_stored"] is True

    def test_an_account_from_before_this_feature_shows_nothing(self, db):
        user = db.create_user("ahmed", PASSWORD)
        with sqlite3.connect(db.path) as connection:
            connection.execute("UPDATE users SET password_seal = NULL")
        assert db.password_of(user["id"]) is None
        assert db.users()[0]["password_stored"] is False

    def test_an_older_database_gains_the_columns(self, tmp_path):
        path = tmp_path / "old.db"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL "
                "DEFAULT '', password_hash BLOB NOT NULL, salt BLOB NOT NULL, "
                "iterations INTEGER NOT NULL, is_admin INTEGER NOT NULL "
                "DEFAULT 0, created_at TEXT NOT NULL, last_seen TEXT)")
        upgraded = Accounts(path)
        user = upgraded.create_user("ahmed", PASSWORD, is_admin=True)
        assert upgraded.password_of(user["id"]) == PASSWORD


class TestWhoMaySee:
    def test_an_administrator_reads_every_password(self, site):
        data = site.sign_in("ahmed").get("/api/admin/passwords")
        assert data["passwords"][str(site.ids["osama"])] == "osama-long-password"
        assert data["passwords"][str(site.ids["kirolos"])] == "kirolos-long-password"

    def test_a_manager_who_is_not_an_administrator_cannot(self, site):
        assert site.sign_in("osama").status("/api/admin/passwords") == 403

    def test_a_team_member_cannot(self, site):
        assert site.sign_in("kirolos").status("/api/admin/passwords") == 403

    def test_a_stranger_cannot(self, site):
        assert site.status("/api/admin/passwords") == 401

    def test_the_account_list_carries_no_passwords(self, site):
        """They cross the wire when asked for, not on every visit to the tab."""
        data = site.sign_in("ahmed").get("/api/admin/users")
        assert "osama-long-password" not in json.dumps(data)
        assert all("password_stored" in user for user in data["users"])

    def test_the_tab_shows_a_password_set_from_the_console(self, site):
        """However the account was made, the tab can read it back."""
        site.app.accounts.set_password(site.ids["osama"], "reset-from-console")
        data = site.sign_in("ahmed").get("/api/admin/passwords")
        assert data["passwords"][str(site.ids["osama"])] == "reset-from-console"
