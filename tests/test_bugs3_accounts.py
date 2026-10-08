"""Round 3 bug hunt: accounts, notifications, the nightly key, admin commands.

Each test failed before its fix. Made-up people and job numbers only.
"""

import datetime as dt
import json
import os

import pytest

from workload_app import accounts as accounts_module, admin, notify, secretbox
from workload_app.accounts import ROLE_MEMBER, Accounts

from test_across import app, ask  # noqa: F401  (fixtures)
from test_weekly_push import Phone, Service, team


def _member(app, username, engineer):  # noqa: F811
    unit_id = app.accounts.units(app.accounts.users()[0]["id"])[0]["id"]
    user = app.accounts.create_user(username, "a long password 123", role=ROLE_MEMBER)
    app.accounts.grant(user_id=user["id"], unit_id=unit_id, engineer=engineer)
    phone = Phone(f"https://fcm.googleapis.com/fcm/send/{username}")
    keys = phone.subscription()["keys"]
    app.accounts.add_push_device(user["id"], endpoint=phone.endpoint, auth=keys["auth"],
                                 p256dh=keys["p256dh"], label="Android phone")
    return user, phone


class TestNotificationsNameOnlyWhoYouMaySee:
    def test_a_lead_is_not_told_about_a_peer_of_the_same_grade(self, app):  # noqa: F811
        # Amal and Bassem are both graded Manager. On the app Amal cannot open
        # Bassem's page (only people graded below), so her phone must not name
        # him either.
        team(app)
        ask("PUT", "/api/people/Amal", {"grade": "manager"})
        ask("PUT", "/api/people/Bassem", {"grade": "manager"})
        amal, phone = _member(app, "amal", "Amal")
        notify.run(app, sender=Service([phone]))
        said = json.dumps(app.accounts.push_messages(amal["id"]))
        assert "Bassem" not in said
        # Dina is graded below Amal: still named.
        assert app._led_by(app.service_for(app.accounts.users()[0]["id"]), "Amal") \
            == ["Dina"]

    def test_due_items_do_not_name_people_outside_the_team(self):
        report = {"week_start": "2026-10-04",
                  "this_week": {"due": [
                      {"row": 1, "name": "Deck GA", "project": "P1",
                       "date": "2026-10-08", "people": ["Dina", "Bassem"],
                       "progress": None, "late": False, "was_due": None}]}}
        checkins = {"people": [], "leading": [], "days": ["2026-10-07", "2026-10-08"]}
        found = notify.member_alerts(report, checkins, "Dina",
                                     today=dt.date(2026, 10, 7))
        due = next(f for f in found if f["key"].startswith("due:"))
        assert "Bassem" not in due["body"] and "Dina" in due["body"]


class TestSecretKeyFile:
    def test_a_failed_write_leaves_no_empty_key_behind(self, tmp_path, monkeypatch):
        # A full disk while the key is first written must not leave an empty
        # key file that every later password is "sealed" with.
        real_write = os.write

        def full(handle, data):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "write", full)
        with pytest.raises(OSError):
            secretbox.load_key(tmp_path)
        monkeypatch.setattr(os, "write", real_write)
        key = secretbox.load_key(tmp_path)
        assert len(key) == secretbox.KEY_BYTES

    def test_a_key_made_meanwhile_by_another_worker_is_used(self, tmp_path, monkeypatch):
        # Two workers starting at once: the one that loses the race reads the
        # winner's key instead of crashing.
        winner = os.urandom(secretbox.KEY_BYTES)
        real_exists = type(tmp_path).exists

        def racing(self):
            if self.name == secretbox.KEY_NAME and not real_exists(self):
                self.write_bytes(winner)        # the other worker, just now
                return False
            return real_exists(self)

        monkeypatch.setattr(type(tmp_path), "exists", racing)
        assert secretbox.load_key(tmp_path) == winner


class TestPasswords:
    def test_a_password_that_is_not_text_is_refused_not_a_crash(self, tmp_path):
        db = Accounts(tmp_path / "accounts.db")
        with pytest.raises(accounts_module.AccountError):
            db.create_user("ahmed", "long enough \ud800 password")
        user = db.create_user("osama", "a long password 123")
        with pytest.raises(accounts_module.AccountError):
            db.set_password(user["id"], "long enough \ud800 password")
        # Signing in with one is simply a wrong password.
        assert db.verify("osama", "long enough \ud800 password") is None


class TestAdminCommands:
    def test_units_names_the_newest_copy(self, tmp_path, capsys):
        db = Accounts(tmp_path / "accounts.db")
        user = db.create_user("ahmed", "a long password 123")
        folder = tmp_path / "users" / str(user["id"]) / "backups"
        folder.mkdir(parents=True)
        old = folder / "bbbb-20261001-090000-000001.db"
        new = folder / "aaaa-20261008-090000-000001.db"
        before = folder / "cccc-before-database-20260901-090000.xlsx"
        for i, path in enumerate((before, old, new)):
            path.write_bytes(b"x")
            os.utime(path, (1_700_000_000 + i * 1000,) * 2)
        assert admin.main(["--data-dir", str(tmp_path), "units"]) == 0
        assert f"newest {new.name}" in capsys.readouterr().out

    def test_a_failed_restore_still_points_at_the_unit_it_brought_across(
            self, tmp_path, workbook_copy, capsys):
        from workload_app import storage

        db = Accounts(tmp_path / "accounts.db")
        user = db.create_user("ahmed", "a long password 123")
        unit = db.create_unit(user["id"], "Marine Structures", "")
        folder = storage.user_dir(tmp_path, user["id"])
        folder.mkdir(parents=True, exist_ok=True)
        old = folder / f"{unit['id']}.xlsx"
        old.write_bytes(workbook_copy.read_bytes())
        db.set_unit_filename(user["id"], unit["id"], old.name)
        bad = tmp_path / "not-a-unit.db"
        bad.write_bytes(b"this is not a database")
        assert admin.main(["--data-dir", str(tmp_path), "restore", "ahmed",
                           "Marine Structures", str(bad)]) == 2
        held = db.unit(user["id"], unit["id"])["filename"]
        assert storage.unit_path(tmp_path, user["id"], held).is_file()


class TestImportKey:
    def test_a_garbled_key_is_not_recognised_rather_than_a_crash(self, tmp_path):
        db = Accounts(tmp_path / "accounts.db")
        user = db.create_user("ahmed", "a long password 123")
        unit = db.create_unit(user["id"], "Marine Structures", "u.db")
        key = db.make_import_key(user["id"], unit["id"])
        assert db.import_key_owner(key)["unit"]["id"] == unit["id"]
        assert db.import_key_owner(key[:-1] + "\ud800") is None
        assert db.session_user("\ud800") is None
        # A new key shuts the old one out.
        db.make_import_key(user["id"], unit["id"])
        assert db.import_key_owner(key) is None
