"""Accounts, sessions, and the storage that belongs to each of them.

The security-shaped tests are here: what a password looks like once stored,
what a session token looks like once stored, and the fact that a unit's file
is named by the app rather than by whoever asked for it.
"""

import datetime as dt
import sqlite3

import pytest

from workload_app import storage
from workload_app.accounts import Accounts, AccountError

PASSWORD = "a-good-long-password"


@pytest.fixture
def db(tmp_path):
    return Accounts(tmp_path / "accounts.db")


class TestPasswords:
    def test_a_password_is_never_stored(self, db, tmp_path):
        db.create_user("ahmed", PASSWORD)
        raw = (tmp_path / "accounts.db").read_bytes()
        assert PASSWORD.encode() not in raw

    def test_it_is_salted_so_two_accounts_never_match(self, db):
        db.create_user("ahmed", PASSWORD)
        db.create_user("osama", PASSWORD)
        with sqlite3.connect(db.path) as connection:
            hashes = [row[0] for row in
                      connection.execute("SELECT password_hash FROM users")]
        assert hashes[0] != hashes[1]

    def test_the_right_password_is_accepted_and_others_are_not(self, db):
        db.create_user("ahmed", PASSWORD)
        assert db.verify("ahmed", PASSWORD) is not None
        assert db.verify("ahmed", PASSWORD.upper()) is None
        assert db.verify("ahmed", "") is None
        assert db.verify("nobody", PASSWORD) is None

    def test_a_username_is_matched_after_tidying(self, db):
        db.create_user("Ahmed", PASSWORD)
        assert db.verify("  AHMED ", PASSWORD) is not None

    @pytest.mark.parametrize("bad", ["", "a", "ahmed!", "1234567890" * 4, " x"])
    def test_a_username_has_to_be_a_username(self, db, bad):
        with pytest.raises(AccountError):
            db.create_user(bad, PASSWORD)

    def test_a_password_has_to_be_long_enough(self, db):
        with pytest.raises(AccountError, match="at least"):
            db.create_user("ahmed", "short")

    def test_it_cannot_be_the_username(self, db):
        with pytest.raises(AccountError, match="cannot be the username"):
            db.create_user("a-long-username", "a-long-username")

    def test_two_accounts_cannot_share_a_name(self, db):
        db.create_user("ahmed", PASSWORD)
        with pytest.raises(AccountError, match="already an account"):
            db.create_user("ahmed", PASSWORD + "!")


class TestSessions:
    def test_a_token_opens_a_session_and_logging_out_closes_it(self, db):
        user = db.create_user("ahmed", PASSWORD)
        token = db.start_session(user["id"])
        assert db.session_user(token)["username"] == "ahmed"
        db.end_session(token)
        assert db.session_user(token) is None

    def test_the_token_itself_is_not_stored(self, db, tmp_path):
        user = db.create_user("ahmed", PASSWORD)
        token = db.start_session(user["id"])
        raw = (tmp_path / "accounts.db").read_bytes()
        assert token.encode() not in raw

    def test_nothing_and_nonsense_are_nobody(self, db):
        assert db.session_user(None) is None
        assert db.session_user("") is None
        assert db.session_user("made-up") is None

    def test_a_session_expires(self, db):
        user = db.create_user("ahmed", PASSWORD)
        token = db.start_session(user["id"], days=0)
        with sqlite3.connect(db.path) as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = ?",
                ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
                 .isoformat(timespec="seconds"),))
        assert db.session_user(token) is None

    def test_changing_a_password_ends_every_session(self, db):
        user = db.create_user("ahmed", PASSWORD)
        first = db.start_session(user["id"])
        second = db.start_session(user["id"])
        db.set_password(user["id"], "another-long-password")
        assert db.session_user(first) is None
        assert db.session_user(second) is None
        assert db.verify("ahmed", "another-long-password") is not None

    def test_deleting_an_account_takes_its_sessions(self, db):
        user = db.create_user("ahmed", PASSWORD)
        token = db.start_session(user["id"])
        db.create_user("osama", PASSWORD, is_admin=True)
        db.delete_user(user["id"])
        assert db.session_user(token) is None


class TestAdministrators:
    def test_the_last_one_cannot_be_removed_or_demoted(self, db):
        admin = db.create_user("ahmed", PASSWORD, is_admin=True)
        db.create_user("osama", PASSWORD)
        with pytest.raises(AccountError, match="only administrator"):
            db.delete_user(admin["id"])
        with pytest.raises(AccountError, match="only administrator"):
            db.set_admin(admin["id"], False)

    def test_with_two_of_them_either_may_go(self, db):
        first = db.create_user("ahmed", PASSWORD, is_admin=True)
        db.create_user("osama", PASSWORD, is_admin=True)
        assert db.delete_user(first["id"])["deleted"] == "ahmed"


class TestUnits:
    def test_a_unit_belongs_to_one_account(self, db):
        mine = db.create_user("ahmed", PASSWORD)
        theirs = db.create_user("osama", PASSWORD)
        unit = db.create_unit(mine["id"], "Marine Structures", "a.xlsx")

        assert [u["name"] for u in db.units(mine["id"])] == ["Marine Structures"]
        assert db.units(theirs["id"]) == []
        assert db.unit(theirs["id"], unit["id"]) is None

    def test_another_account_cannot_rename_or_delete_it(self, db):
        mine = db.create_user("ahmed", PASSWORD)
        theirs = db.create_user("osama", PASSWORD)
        unit = db.create_unit(mine["id"], "Marine Structures", "a.xlsx")
        with pytest.raises(AccountError, match="not yours"):
            db.rename_unit(theirs["id"], unit["id"], "Mine now")
        with pytest.raises(AccountError, match="not yours"):
            db.delete_unit(theirs["id"], unit["id"])
        assert db.unit(mine["id"], unit["id"])["name"] == "Marine Structures"

    def test_two_accounts_may_use_the_same_unit_name(self, db):
        mine = db.create_user("ahmed", PASSWORD)
        theirs = db.create_user("osama", PASSWORD)
        db.create_unit(mine["id"], "Marine Structures", "a.xlsx")
        db.create_unit(theirs["id"], "Marine Structures", "b.xlsx")

    def test_but_one_account_may_not_use_it_twice(self, db):
        mine = db.create_user("ahmed", PASSWORD)
        db.create_unit(mine["id"], "Marine Structures", "a.xlsx")
        with pytest.raises(AccountError, match="already have a unit"):
            db.create_unit(mine["id"], "Marine Structures", "b.xlsx")


class TestStorage:
    def test_each_account_gets_its_own_folder(self, tmp_path):
        one = storage.user_dir(tmp_path, 1)
        two = storage.user_dir(tmp_path, 2)
        assert one != two and one.is_dir() and two.is_dir()

    def test_a_filename_can_never_leave_the_folder(self, tmp_path):
        path = storage.unit_path(tmp_path, 1, "../../etc/passwd")
        assert path.parent == storage.user_dir(tmp_path, 1)
        assert path.name == "passwd"

    def test_a_unit_file_is_named_by_the_app(self, tmp_path):
        with pytest.raises(ValueError):
            storage._target(tmp_path, 1, "../secret")
        with pytest.raises(ValueError):
            storage._target(tmp_path, 1, "")

    def test_a_new_unit_is_a_copy_of_the_template(self, tmp_path):
        if not storage.template_path().is_file():
            pytest.skip("no template built in this checkout")
        made = storage.new_from_template(tmp_path, 7, "a1b2c3d4")
        assert made.is_file()
        assert made.read_bytes() == storage.template_path().read_bytes()

    def test_an_upload_that_is_not_a_workbook_is_not_kept(self, tmp_path):
        from workload_app.library import NotAWorkbook

        with pytest.raises(NotAWorkbook):
            storage.save_upload(tmp_path, 7, "a1b2c3d4", b"not a spreadsheet")
        assert not list(storage.user_dir(tmp_path, 7).glob("*.xlsx"))

    def test_removing_an_account_removes_its_files(self, tmp_path):
        directory = storage.user_dir(tmp_path, 7)
        (directory / "a.xlsx").write_bytes(b"x")
        storage.remove_user_files(tmp_path, 7)
        assert not (tmp_path / "users" / "7" / "a.xlsx").exists()


class TestTheTemplate:
    """What ships with the app, and what it must not carry."""

    def test_it_is_there_and_is_a_workbook(self):
        from workload_app import library

        path = storage.template_path()
        if not path.is_file():
            pytest.skip("no template built in this checkout")
        assert library.check(path) == []

    def test_it_holds_the_model_but_nobody_s_data(self):
        from workload_app.workbook import WorkloadWorkbook

        path = storage.template_path()
        if not path.is_file():
            pytest.skip("no template built in this checkout")
        wb = WorkloadWorkbook(path)
        assert wb.projects() == []
        assert wb.deliverables() == []
        assert all(len(wb.timesheet_rows(name, ["B"])) == 0
                   for name in wb.ts_sheets())
        assert wb.project_types() and wb.credit_steps()
        assert wb.scorecard_factors()
        assert wb.engineer_names() == ["Engineer 1", "Engineer 2", "Engineer 3"]
