"""Accounts, sessions and each account's units.

Everything the app knows about who you are lives here, in a SQLite file beside
the workbooks.  There is no public sign-up: an administrator makes an account,
and until they do there is nothing to log in to.

Passwords are stored as PBKDF2-HMAC-SHA256 with a per-account salt, and the
iteration count is stored beside each hash so it can be raised later without
invalidating anyone.  Session tokens are random, and only their SHA-256 digest
is stored -- a stolen database is not a set of usable cookies.

**Inside another site.**  When Workload is one tab of a larger site, that site
signs people in and tells Workload who is asking.  An account then carries the
site's own identifier for that person (``site_key``), and that -- not a
username and password typed here -- is what finds it.  It is the identifier
rather than the name or address they sign in with, because those can be
changed and the units have to stay with the person.  See ``site_user``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import secretbox

#: Cost of a password check.  About a tenth of a second on a small server, which
#: is slow enough to make guessing expensive and fast enough not to be felt.
ITERATIONS = 240_000
SALT_BYTES = 16
TOKEN_BYTES = 32
SESSION_DAYS = 14
#: Usernames are matched exactly after this cleanup, so "Ahmed " and "ahmed"
#: cannot become two accounts that look identical in a list.
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
MIN_PASSWORD = 10

#: What an account is for.  A manager owns units and edits them; a member is
#: given sight of one engineer's own figures in one unit, and can change
#: nothing at all.  An administrator is a manager who may also make accounts.
ROLE_MANAGER = "manager"
ROLE_MEMBER = "member"
ROLES = [ROLE_MANAGER, ROLE_MEMBER]


class AccountError(ValueError):
    """Something an administrator or a visitor did that cannot be accepted."""

    def __init__(self, message: str):
        super().__init__(message)
        self.errors = [message]


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL DEFAULT '',
    password_hash BLOB NOT NULL,
    salt          BLOB NOT NULL,
    iterations    INTEGER NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    role          TEXT NOT NULL DEFAULT 'manager',
    -- The password again, sealed under the key file beside this database, so
    -- an administrator can read out the one they issued.  Never consulted to
    -- sign anybody in; see secretbox.py.
    password_seal TEXT,
    password_at   TEXT,
    -- Who this is on the surrounding site, when Workload is one tab of a
    -- larger site and that site does the signing in: the site's own
    -- identifier for the person, and what they sign in there with (shown,
    -- never matched on -- it can change).
    site_key      TEXT,
    site_login    TEXT,
    -- The unit this manager has open, so every web worker opens the same one.
    open_unit_id  TEXT,
    created_at    TEXT NOT NULL,
    last_seen     TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS units (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    filename   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    opened_at  TEXT,
    UNIQUE (user_id, name)
);
CREATE INDEX IF NOT EXISTS units_user ON units(user_id);

-- Which engineer, in which unit, a member account is allowed to see.  One row
-- per person per unit; the unit's own row says whose workbook it is.
CREATE TABLE IF NOT EXISTS memberships (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    unit_id    TEXT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    engineer   TEXT NOT NULL,
    granted_by INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, unit_id)
);
CREATE INDEX IF NOT EXISTS memberships_unit ON memberships(unit_id);

-- The email a manager wrote against somebody on the team.  When a person
-- the surrounding site signs in arrives with that email, they are linked to
-- that row and land on their own page with no further step.  Kept lower-cased;
-- linked_user is the account it linked, so a corrected email unlinks it.
CREATE TABLE IF NOT EXISTS member_emails (
    unit_id     TEXT NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    engineer    TEXT NOT NULL,
    email       TEXT NOT NULL,
    set_by      INTEGER,
    set_at      TEXT NOT NULL,
    linked_user INTEGER,
    PRIMARY KEY (unit_id, engineer),
    UNIQUE (unit_id, email)
);
CREATE INDEX IF NOT EXISTS member_emails_email ON member_emails(email);

-- The key a scheduled job on the manager's own PC signs its nightly import
-- with.  One per unit; only its digest is kept, so it is shown once, when it
-- is made.  It can import timesheets into that unit and do nothing else.
CREATE TABLE IF NOT EXISTS import_keys (
    unit_id     TEXT PRIMARY KEY REFERENCES units(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash    TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    last_used   TEXT,
    last_result TEXT
);

-- A phone (or browser) that has turned notifications on.  The endpoint is the
-- address at its maker's push service; p256dh and auth are the keys a message
-- is sealed with for that phone alone.  site is the address the app was
-- opened at, which the push service is told as the sender's contact.
CREATE TABLE IF NOT EXISTS push_devices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    auth        TEXT NOT NULL,
    p256dh      TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    site        TEXT NOT NULL DEFAULT '',
    added_at    TEXT NOT NULL,
    last_ok_at  TEXT,
    failures    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT
);
CREATE INDEX IF NOT EXISTS push_devices_user ON push_devices(user_id);

-- Every notification sent.  The key says what it was about ("rest:Nour:
-- 2026-10-04"), so the same thing is never sent twice; the app lists the
-- recent ones beside the weekly report.
CREATE TABLE IF NOT EXISTS push_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    unit_id     TEXT NOT NULL DEFAULT '',
    key         TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, unit_id, key)
);

-- The site's own list of official holidays, by country, which every unit
-- in that country follows on top of the built-in ones.  off = 1 is a
-- holiday, off = 0 a built-in day that is not one this year.  source is
-- 'admin' (typed by the site's administrator, and always wins) or
-- 'timesheets' (most people booked the day as a holiday, or worked a
-- built-in one).
CREATE TABLE IF NOT EXISTS official_holidays (
    country     TEXT NOT NULL,
    day         TEXT NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    off         INTEGER NOT NULL DEFAULT 1,
    source      TEXT NOT NULL DEFAULT 'admin',
    set_by      INTEGER,
    set_at      TEXT NOT NULL,
    PRIMARY KEY (country, day)
);
"""


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class Accounts:
    """The account database.  Cheap to construct; a connection per operation."""

    def __init__(self, path: Path, *, secret_key: Optional[bytes] = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = secret_key if secret_key is not None \
            else secretbox.load_key(self.path.parent)
        with self._connect() as db:
            db.executescript(SCHEMA)
            self._migrate(db)

    @staticmethod
    def _migrate(db: sqlite3.Connection) -> None:
        """Bring a database made before roles existed up to date."""
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        # Everyone who already had an account was a manager by definition:
        # they were the only kind there was.  Accounts made before the Admin
        # tab have no readable copy of their password, and nothing can conjure
        # one out of a PBKDF2 hash.  They show as "not stored" until somebody
        # resets them.
        for column, kind in (("role", "TEXT NOT NULL DEFAULT 'manager'"),
                             ("password_seal", "TEXT"), ("password_at", "TEXT"),
                             ("site_key", "TEXT"), ("site_login", "TEXT"),
                             ("open_unit_id", "TEXT")):
            if column not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} {kind}")
        # One person on the site is one account here, never two.
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_site_key "
                   "ON users(site_key) WHERE site_key IS NOT NULL")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        # More than one web worker will have this file open at once.
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 15000")
        return db

    # -- official holidays ---------------------------------------------
    def official_holidays(self, country: Optional[str] = None) -> List[Dict[str, Any]]:
        """The site's list, for one country or all of them, by date."""
        with self._connect() as db:
            if country:
                rows = db.execute(
                    "SELECT country, day, name, off, source FROM official_holidays "
                    "WHERE country = ? ORDER BY day", (country,)).fetchall()
            else:
                rows = db.execute(
                    "SELECT country, day, name, off, source FROM official_holidays "
                    "ORDER BY country, day").fetchall()
        return [{**dict(row), "off": bool(row["off"])} for row in rows]

    def set_official_holiday(self, country: str, day: str, *, name: str = "",
                             off: bool = True, set_by: Optional[int] = None) -> None:
        """The administrator says a day is, or is not, an official holiday."""
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO official_holidays (country, day, name, off, "
                "source, set_by, set_at) VALUES (?, ?, ?, ?, 'admin', ?, ?)",
                (country, day, name, 1 if off else 0, set_by, now()))

    def clear_official_holiday(self, country: str, day: str) -> bool:
        """Take back what the administrator set, so the day is as built in
        (or as the timesheets show) again."""
        with self._connect() as db:
            return db.execute(
                "DELETE FROM official_holidays WHERE country = ? AND day = ?",
                (country, day)).rowcount > 0

    def learn_official_holidays(self, rows: Iterable[Dict[str, Any]]) -> int:
        """Days the timesheets showed; never over anything already listed."""
        added = 0
        with self._connect() as db:
            for row in rows:
                added += db.execute(
                    "INSERT OR IGNORE INTO official_holidays (country, day, name, "
                    "off, source, set_at) VALUES (?, ?, ?, ?, 'timesheets', ?)",
                    (row["country"], row["day"], row.get("name") or "",
                     1 if row.get("off", True) else 0, now())).rowcount
        return added

    # -- users -----------------------------------------------------------
    def user_count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def users(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT u.*, (SELECT COUNT(*) FROM units WHERE user_id = u.id) "
                "AS units FROM users u ORDER BY u.username"
            ).fetchall()
        return [_public_user(row) for row in rows]

    def user(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _public_user(row) if row else None

    def create_user(self, username: str, password: str, *,
                    display_name: str = "", is_admin: bool = False,
                    role: str = ROLE_MANAGER) -> Dict[str, Any]:
        username = clean_username(username)
        check_password(password, username)
        _check_role(role)
        if is_admin and role != ROLE_MANAGER:
            raise AccountError("Only a manager account can be an administrator.")
        salt = secrets.token_bytes(SALT_BYTES)
        digest = _hash(password, salt, ITERATIONS)
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "INSERT INTO users (username, display_name, password_hash, "
                    "salt, iterations, is_admin, role, created_at, "
                    "password_seal, password_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (username, (display_name or "").strip(), digest, salt,
                     ITERATIONS, 1 if is_admin else 0, role, now(),
                     secretbox.seal(self._key, password), now()),
                )
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise AccountError(f"There is already an account called {username}.")
        return self.user(user_id)                      # type: ignore[return-value]

    def set_password(self, user_id: int, password: str) -> None:
        with self._connect() as db:
            row = db.execute("SELECT username FROM users WHERE id = ?",
                             (user_id,)).fetchone()
            if row is None:
                raise AccountError("That account no longer exists.")
            password = str(password or "")
            check_password(password, row["username"])
            salt = secrets.token_bytes(SALT_BYTES)
            db.execute(
                "UPDATE users SET password_hash = ?, salt = ?, iterations = ?, "
                "password_seal = ?, password_at = ? WHERE id = ?",
                (_hash(password, salt, ITERATIONS), salt, ITERATIONS,
                 secretbox.seal(self._key, password), now(), user_id),
            )
            # A password change ends every session but the one changing it;
            # the caller re-issues its own.
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def passwords(self) -> Dict[int, Optional[str]]:
        """Every account's password as last set, for the Admin tab.

        ``None`` where there is nothing to show: an account made before the
        sealed copy existed, or one whose seal this key cannot open.
        """
        with self._connect() as db:
            rows = db.execute("SELECT id, password_seal FROM users").fetchall()
        return {row["id"]: secretbox.unseal(self._key, row["password_seal"])
                for row in rows}

    def seal(self, text: str) -> str:
        """Something kept in a unit that should not read plainly from a copy
        of it, such as a calendar link."""
        return secretbox.seal(self._key, text)

    def unseal(self, blob: Optional[str]) -> Optional[str]:
        return secretbox.unseal(self._key, blob)

    def password_of(self, user_id: int) -> Optional[str]:
        with self._connect() as db:
            row = db.execute("SELECT password_seal FROM users WHERE id = ?",
                             (user_id,)).fetchone()
        return secretbox.unseal(self._key, row["password_seal"]) if row else None

    def set_admin(self, user_id: int, is_admin: bool) -> None:
        with self._connect() as db:
            row = db.execute("SELECT role FROM users WHERE id = ?",
                             (user_id,)).fetchone()
            if is_admin and row and row["role"] != ROLE_MANAGER:
                raise AccountError(
                    "A team member account cannot manage accounts. Make it a "
                    "manager first."
                )
            if not is_admin and self._other_admins(db, user_id) == 0:
                raise AccountError(
                    "That is the only administrator; make someone else one first."
                )
            db.execute("UPDATE users SET is_admin = ? WHERE id = ?",
                       (1 if is_admin else 0, user_id))

    def delete_user(self, user_id: int) -> Dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise AccountError("That account no longer exists.")
            if row["is_admin"] and self._other_admins(db, user_id) == 0:
                raise AccountError(
                    "That is the only administrator; the site would be locked out."
                )
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return {"deleted": row["username"], "user_id": user_id}

    @staticmethod
    def _other_admins(db: sqlite3.Connection, user_id: int) -> int:
        return db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_admin = 1 AND id != ?",
            (user_id,),
        ).fetchone()["n"]

    # -- arriving from the site Workload is a tab of -----------------------
    #
    # The site has already signed the person in.  Nothing below checks a
    # password: it only answers "which account here is this person?", and the
    # caller is trusted to pass an identifier the site itself vouched for.

    def site_user(self, key: Any) -> Optional[Dict[str, Any]]:
        key = clean_site_key(key)
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE site_key = ?",
                             (key,)).fetchone()
        return _public_user(row) if row else None

    def create_site_user(self, key: Any, *, login: str = "",
                         display_name: str = "",
                         role: str = ROLE_MANAGER) -> Dict[str, Any]:
        """An account for somebody the site signs in.

        It has no password anybody knows -- a random one is hashed and thrown
        away, and no readable copy is kept -- so it can only ever be reached
        through the site.
        """
        key = clean_site_key(key)
        login = str(login or "").strip()
        _check_role(role)
        salt = secrets.token_bytes(SALT_BYTES)
        digest = _hash(secrets.token_urlsafe(TOKEN_BYTES), salt, ITERATIONS)
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "INSERT INTO users (username, display_name, password_hash, "
                    "salt, iterations, is_admin, role, created_at, site_key, "
                    "site_login) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                    (self._free_username(db, login or display_name),
                     (display_name or "").strip() or login.split("@")[0] or "",
                     digest, salt, ITERATIONS, role, now(), key, login or None),
                )
                user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise AccountError("That person already has an account here.")
        return self.user(user_id)                      # type: ignore[return-value]

    @staticmethod
    def _free_username(db: sqlite3.Connection, wanted: str) -> str:
        """A username nobody has, made from what somebody signs in with."""
        stem = re.sub(r"[^a-z0-9._-]", "", str(wanted).split("@")[0].lower())
        stem = stem.lstrip("._-")[:24]
        if len(stem) < 2:
            stem = "user"
        candidate, n = stem, 1
        while db.execute("SELECT 1 FROM users WHERE username = ?",
                         (candidate,)).fetchone():
            n += 1
            candidate = f"{stem}-{n}"
        return candidate

    def link_site(self, user_id: int, key: Any,
                  login: Optional[str] = None) -> Dict[str, Any]:
        """Say who on the site an account belongs to; ``None`` unlinks it."""
        key = clean_site_key(key) if key not in (None, "") else None
        with self._connect() as db:
            if db.execute("SELECT 1 FROM users WHERE id = ?",
                          (user_id,)).fetchone() is None:
                raise AccountError("That account no longer exists.")
            if key:
                taken = db.execute(
                    "SELECT username FROM users WHERE site_key = ? AND id != ?",
                    (key, user_id)).fetchone()
                if taken:
                    raise AccountError(
                        f"That sign-in is already linked to the account "
                        f"{taken['username']}.")
            db.execute("UPDATE users SET site_key = ?, site_login = ? WHERE id = ?",
                       (key, (str(login or "").strip() or None) if key else None,
                        user_id))
        return self.user(user_id)                      # type: ignore[return-value]

    def set_site_login(self, user_id: int, login: str) -> None:
        """Keep what is shown in step with what they sign in with now."""
        with self._connect() as db:
            db.execute("UPDATE users SET site_login = ? WHERE id = ?",
                       (str(login or "").strip() or None, user_id))

    def set_role(self, user_id: int, role: str) -> None:
        _check_role(role)
        with self._connect() as db:
            db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    def seen(self, user_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE users SET last_seen = ? WHERE id = ?",
                       (now(), user_id))

    def remove_if_empty(self, user_id: int) -> bool:
        """Delete an account that owns nothing and has been shown nothing."""
        with self._connect() as db:
            owns = db.execute("SELECT COUNT(*) AS n FROM units WHERE user_id = ?",
                              (user_id,)).fetchone()["n"]
            shown = db.execute(
                "SELECT COUNT(*) AS n FROM memberships WHERE user_id = ?",
                (user_id,)).fetchone()["n"]
            admin = db.execute("SELECT is_admin FROM users WHERE id = ?",
                               (user_id,)).fetchone()
            if owns or shown or admin is None or admin["is_admin"]:
                return False
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True

    # -- logging in ------------------------------------------------------
    def verify(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """The account, or ``None``.  Takes the same time either way."""
        if not isinstance(password, str):
            password = ""
        try:
            username = clean_username(username)
        except AccountError:
            username = ""
        with self._connect() as db:
            row = db.execute("SELECT * FROM users WHERE username = ?",
                             (username,)).fetchone()
        if row is None:
            # Hash anyway, so a missing account cannot be told from a wrong
            # password by how long the answer took.
            _hash(password, b"decoy-salt-1234", ITERATIONS)
            return None
        expected = bytes(row["password_hash"])
        actual = _hash(password, bytes(row["salt"]), int(row["iterations"]))
        if not hmac.compare_digest(expected, actual):
            return None
        self.seen(row["id"])
        return _public_user(row)

    def start_session(self, user_id: int, *, days: int = SESSION_DAYS) -> str:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        expires = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=days)
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (_token_hash(token), user_id, now(),
                 expires.isoformat(timespec="seconds")),
            )
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
        return token

    def session_user(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.expires_at >= ?",
                (_token_hash(token), now()),
            ).fetchone()
        return _public_user(row) if row else None

    def end_session(self, token: Optional[str]) -> None:
        if not token:
            return
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?",
                       (_token_hash(token),))

    # -- import keys -----------------------------------------------------
    #
    # A session is a person at a browser.  An import key is a scheduled job
    # on that person's PC, which has no browser to sign in with: it carries
    # the key instead, and the key opens exactly one door -- the nightly
    # import into one unit.

    def make_import_key(self, user_id: int, unit_id: str) -> str:
        """A fresh key for this unit, replacing any it had."""
        if self.unit(user_id, unit_id) is None:
            raise AccountError("That unit is not yours.")
        key = "sel_" + secrets.token_urlsafe(TOKEN_BYTES)
        with self._connect() as db:
            db.execute("DELETE FROM import_keys WHERE unit_id = ?", (unit_id,))
            db.execute(
                "INSERT INTO import_keys (unit_id, user_id, key_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (unit_id, user_id, _token_hash(key), now()))
        return key

    def import_key_owner(self, key: Optional[str]) -> Optional[Dict[str, Any]]:
        """``{"user", "unit"}`` for a key that is still good, else None."""
        if not key or not isinstance(key, str):
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT unit_id, user_id FROM import_keys WHERE key_hash = ?",
                (_token_hash(key),)).fetchone()
        if row is None:
            return None
        user = self.user(row["user_id"])
        unit = self.unit(row["user_id"], row["unit_id"])
        if user is None or unit is None:
            return None
        return {"user": user, "unit": unit}

    def import_key_info(self, user_id: int, unit_id: str
                        ) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute(
                "SELECT created_at, last_used, last_result FROM import_keys "
                "WHERE unit_id = ? AND user_id = ?", (unit_id, user_id)).fetchone()
        if row is None:
            return None
        info = dict(row)
        info["last_result"] = json.loads(info["last_result"]) \
            if info["last_result"] else None
        return info

    def record_import(self, unit_id: str, result: Dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE import_keys SET last_used = ?, last_result = ? "
                "WHERE unit_id = ?",
                (now(), json.dumps(result, default=str), unit_id))

    def revoke_import_key(self, user_id: int, unit_id: str) -> bool:
        with self._connect() as db:
            return db.execute(
                "DELETE FROM import_keys WHERE unit_id = ? AND user_id = ?",
                (unit_id, user_id)).rowcount > 0

    # -- notifications ---------------------------------------------------

    def add_push_device(self, user_id: int, *, endpoint: str, auth: str,
                        p256dh: str, label: str = "", site: str = ""
                        ) -> Dict[str, Any]:
        """Keep a phone's subscription; the same phone again replaces it."""
        with self._connect() as db:
            db.execute(
                "INSERT INTO push_devices (user_id, endpoint, auth, p256dh, label, "
                "site, added_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, "
                "auth = excluded.auth, p256dh = excluded.p256dh, label = excluded.label, "
                "site = excluded.site, failures = 0, last_error = NULL",
                (user_id, endpoint, auth, p256dh, label[:80], site[:200], now()))
            device_id = db.execute("SELECT id FROM push_devices WHERE endpoint = ?",
                                   (endpoint,)).fetchone()["id"]
        return next(d for d in self.push_devices(user_id) if d["id"] == device_id)

    def push_devices(self, user_id: Optional[int] = None,
                     *, secrets_too: bool = False) -> List[Dict[str, Any]]:
        """One account's devices, or everybody's; the keys only when asked."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM push_devices"
                + (" WHERE user_id = ?" if user_id is not None else "")
                + " ORDER BY id", (() if user_id is None else (user_id,))).fetchall()
        hidden = () if secrets_too else ("endpoint", "auth", "p256dh")
        return [{k: v for k, v in dict(row).items() if k not in hidden}
                for row in rows]

    def has_push_devices(self, user_ids: List[int]) -> bool:
        """Whether any of these accounts has a phone with notifications on."""
        if not user_ids:
            return False
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM push_devices WHERE user_id IN (%s) LIMIT 1"
                % ",".join("?" * len(user_ids)), list(user_ids)).fetchone() is not None

    def remove_push_device(self, user_id: int, device_id: int) -> bool:
        with self._connect() as db:
            return db.execute("DELETE FROM push_devices WHERE id = ? AND user_id = ?",
                              (device_id, user_id)).rowcount > 0

    def push_result(self, device_id: int, error: Optional[str] = None) -> None:
        with self._connect() as db:
            if error is None:
                db.execute("UPDATE push_devices SET last_ok_at = ?, failures = 0, "
                           "last_error = NULL WHERE id = ?", (now(), device_id))
            else:
                db.execute("UPDATE push_devices SET failures = failures + 1, "
                           "last_error = ? WHERE id = ?", (error[:300], device_id))

    def forget_push_device(self, device_id: int) -> None:
        """The push service says this phone is gone."""
        with self._connect() as db:
            db.execute("DELETE FROM push_devices WHERE id = ?", (device_id,))

    def new_push_messages(self, user_id: int, unit_id: str,
                          messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep these; back come only the ones not sent before."""
        fresh = []
        with self._connect() as db:
            for message in messages:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO push_messages (user_id, unit_id, key, "
                    "title, body, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, unit_id, message["key"], message["title"],
                     message.get("body", ""), message.get("url", ""), now()))
                if cursor.rowcount:
                    fresh.append({**message, "id": cursor.lastrowid})
        return fresh

    def push_messages(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, unit_id, key, title, body, url, created_at "
                "FROM push_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit))]

    # -- units -----------------------------------------------------------
    #
    # A unit is a name and a workbook file, and it belongs to exactly one
    # account.  Every read below is filtered by user_id, which is what keeps
    # one account's work invisible to another.

    def units(self, user_id: int) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM units WHERE user_id = ? "
                "ORDER BY COALESCE(opened_at, created_at) DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_units(self) -> List[Dict[str, Any]]:
        """Every unit of every account, with whose it is: for the site's
        administrator, who looks across every team."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT u.*, COALESCE(NULLIF(o.display_name, ''), o.username) "
                "AS owner_name FROM units u JOIN users o ON o.id = u.user_id "
                "ORDER BY u.name").fetchall()
        return [dict(row) for row in rows]

    def unit(self, user_id: int, unit_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM units WHERE id = ? AND user_id = ?",
                             (unit_id, user_id)).fetchone()
        return dict(row) if row else None

    def create_unit(self, user_id: int, name: str, filename: str) -> Dict[str, Any]:
        name = clean_unit_name(name)
        unit_id = secrets.token_hex(8)
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO units (id, user_id, name, filename, created_at, "
                    "opened_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (unit_id, user_id, name, filename, now(), now()),
                )
        except sqlite3.IntegrityError:
            raise AccountError(f"You already have a unit called {name}.")
        return self.unit(user_id, unit_id)              # type: ignore[return-value]

    def set_unit_filename(self, user_id: int, unit_id: str, filename: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE units SET filename = ? WHERE id = ? AND user_id = ?",
                       (filename, unit_id, user_id))

    def set_open_unit(self, user_id: int, unit_id: Optional[str]) -> None:
        with self._connect() as db:
            db.execute("UPDATE users SET open_unit_id = ? WHERE id = ?",
                       (unit_id, user_id))

    def open_unit_of(self, user_id: int) -> Optional[str]:
        with self._connect() as db:
            row = db.execute("SELECT open_unit_id FROM users WHERE id = ?",
                             (user_id,)).fetchone()
        return row["open_unit_id"] if row else None

    def touch_unit(self, user_id: int, unit_id: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE units SET opened_at = ? WHERE id = ? AND user_id = ?",
                       (now(), unit_id, user_id))

    def rename_unit(self, user_id: int, unit_id: str, name: str) -> Dict[str, Any]:
        name = clean_unit_name(name)
        try:
            with self._connect() as db:
                changed = db.execute(
                    "UPDATE units SET name = ? WHERE id = ? AND user_id = ?",
                    (name, unit_id, user_id),
                ).rowcount
        except sqlite3.IntegrityError:
            raise AccountError(f"You already have a unit called {name}.")
        if not changed:
            raise AccountError("That unit is not yours, or no longer exists.")
        return self.unit(user_id, unit_id)              # type: ignore[return-value]

    def delete_unit(self, user_id: int, unit_id: str) -> Dict[str, Any]:
        unit = self.unit(user_id, unit_id)
        if unit is None:
            raise AccountError("That unit is not yours, or no longer exists.")
        with self._connect() as db:
            db.execute("DELETE FROM units WHERE id = ? AND user_id = ?",
                       (unit_id, user_id))
        return unit

    # -- memberships -----------------------------------------------------
    #
    # A member account sees one engineer, in one unit, and only what belongs to
    # that engineer.  The row below is the whole of that permission: no row, no
    # sight of anything.

    def grant(self, *, user_id: int, unit_id: str, engineer: str,
              granted_by: Optional[int] = None) -> Dict[str, Any]:
        engineer = str(engineer or "").strip()
        if not engineer:
            raise AccountError("Say which engineer this account is.")
        with self._connect() as db:
            row = db.execute("SELECT role FROM users WHERE id = ?",
                             (user_id,)).fetchone()
            if row is None:
                raise AccountError("That account no longer exists.")
            if row["role"] != ROLE_MEMBER:
                raise AccountError(
                    "Only a team member account can be given one person's view. "
                    "A manager already sees the whole unit."
                )
            db.execute(
                "INSERT INTO memberships (user_id, unit_id, engineer, "
                "granted_by, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, unit_id) DO UPDATE SET engineer = ?",
                (user_id, unit_id, engineer, granted_by, now(), engineer),
            )
        return {"user_id": user_id, "unit_id": unit_id, "engineer": engineer}

    def revoke(self, *, user_id: int, unit_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM memberships WHERE user_id = ? AND unit_id = ?",
                       (user_id, unit_id))

    def membership(self, user_id: int, unit_id: str) -> Optional[Dict[str, Any]]:
        """The permission itself, with the unit it points at."""
        with self._connect() as db:
            row = db.execute(
                "SELECT m.*, u.name AS unit_name, u.filename, u.user_id AS owner_id "
                "FROM memberships m JOIN units u ON u.id = m.unit_id "
                "WHERE m.user_id = ? AND m.unit_id = ?",
                (user_id, unit_id),
            ).fetchone()
        return dict(row) if row else None

    def memberships(self, user_id: int) -> List[Dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT m.*, u.name AS unit_name, u.filename, u.user_id AS owner_id, "
                "COALESCE(NULLIF(o.display_name, ''), o.username) AS owner_name "
                "FROM memberships m JOIN units u ON u.id = m.unit_id "
                "JOIN users o ON o.id = u.user_id "
                "WHERE m.user_id = ? ORDER BY u.name",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def unit_members(self, unit_id: str) -> List[Dict[str, Any]]:
        """Who has been given sight of this unit, and as whom."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT m.engineer, m.created_at, u.id AS user_id, u.username, "
                "u.display_name, u.last_seen, u.site_key, u.site_login "
                "FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.unit_id = ? ORDER BY u.username",
                (unit_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rename_engineer_in_memberships(self, unit_id: str, old: str,
                                       new: str) -> None:
        """Follow a rename on the Team tab, so access is not silently lost."""
        with self._connect() as db:
            db.execute("UPDATE memberships SET engineer = ? "
                       "WHERE unit_id = ? AND engineer = ?", (new, unit_id, old))
            db.execute("UPDATE OR REPLACE member_emails SET engineer = ? "
                       "WHERE unit_id = ? AND engineer = ?", (new, unit_id, old))

    # -- linking by email ------------------------------------------------
    #
    # The manager writes each person's email on the Team tab.  The site
    # vouches for the email of whoever it signs in; when the two are the same,
    # that person is linked to that row.  Nobody can claim a row by typing an
    # email: only the manager writes one, and only the site says who has it.

    def member_emails(self, unit_id: str) -> Dict[str, Dict[str, Any]]:
        """engineer -> {email, linked_user} for one unit."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT engineer, email, linked_user FROM member_emails "
                "WHERE unit_id = ?", (unit_id,)).fetchall()
        return {row["engineer"]: {"email": row["email"],
                                  "linked_user": row["linked_user"]}
                for row in rows}

    def set_member_email(self, unit_id: str, engineer: str, email: Any, *,
                         set_by: Optional[int] = None) -> Dict[str, Any]:
        """Write (or, with an empty value, clear) one person's email.

        Returns ``{"email", "unlinked"}``: ``unlinked`` is the account that had
        been linked by the old email, which no longer is -- the caller takes
        its access away, so a corrected email never leaves the wrong person in.
        """
        email = clean_email(email)
        with self._connect() as db:
            old = db.execute(
                "SELECT email, linked_user FROM member_emails "
                "WHERE unit_id = ? AND engineer = ?", (unit_id, engineer)).fetchone()
            if old is not None and old["email"] == email:
                return {"email": email, "unlinked": None}
            if email:
                taken = db.execute(
                    "SELECT engineer FROM member_emails "
                    "WHERE unit_id = ? AND email = ? AND engineer != ?",
                    (unit_id, email, engineer)).fetchone()
                if taken:
                    raise AccountError(
                        f"{taken['engineer']} already has that email in this "
                        f"unit. Each person needs their own.")
            db.execute("DELETE FROM member_emails WHERE unit_id = ? AND engineer = ?",
                       (unit_id, engineer))
            if email:
                db.execute(
                    "INSERT INTO member_emails (unit_id, engineer, email, set_by, "
                    "set_at) VALUES (?, ?, ?, ?, ?)",
                    (unit_id, engineer, email, set_by, now()))
        return {"email": email,
                "unlinked": old["linked_user"] if old is not None else None}

    def forget_member_email(self, unit_id: str, engineer: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM member_emails WHERE unit_id = ? AND engineer = ?",
                       (unit_id, engineer))

    def rows_for_email(self, email: Any, user_id: int) -> List[Dict[str, Any]]:
        """Rows with this email in units the account is not in yet.

        Units the account owns are left out: a manager is never made a member
        of their own unit.
        """
        email = clean_email(email)
        if not email:
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT e.unit_id, e.engineer, e.set_by, u.user_id AS owner_id "
                "FROM member_emails e JOIN units u ON u.id = e.unit_id "
                "WHERE e.email = ? AND u.user_id != ? AND NOT EXISTS ("
                "  SELECT 1 FROM memberships m "
                "  WHERE m.user_id = ? AND m.unit_id = e.unit_id)",
                (email, user_id, user_id)).fetchall()
        return [dict(row) for row in rows]

    def mark_email_linked(self, unit_id: str, engineer: str, user_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE member_emails SET linked_user = ? "
                       "WHERE unit_id = ? AND engineer = ?",
                       (user_id, unit_id, engineer))


# --------------------------------------------------------------------------
# the small print
# --------------------------------------------------------------------------

def _hash(password: str, salt: bytes, iterations: int) -> bytes:
    # surrogatepass: text no keyboard makes (a lone surrogate, sent as JSON)
    # is a wrong password at sign-in, never a crash.  Every real password
    # encodes exactly as before.
    return hashlib.pbkdf2_hmac(
        "sha256", unicodedata.normalize("NFKC", password).encode(
            "utf-8", "surrogatepass"),
        salt, iterations)


def _check_role(role: str) -> None:
    if role not in ROLES:
        raise AccountError(f"An account is a {' or a '.join(ROLES)}.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


def _public_user(row: sqlite3.Row) -> Dict[str, Any]:
    """Everything about an account except the parts that let you become it."""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "is_admin": bool(row["is_admin"]),
        "role": row["role"],
        "created_at": row["created_at"],
        "last_seen": row["last_seen"],
        "units": row["units"] if "units" in row.keys() else None,
        # Whether the Admin tab has a password to show for this account.
        "password_stored": bool(row["password_seal"]),
        "password_at": row["password_at"],
        # Who this is on the surrounding site, if Workload is a tab of one.
        "site_key": row["site_key"],
        "site_login": row["site_login"],
    }


def clean_username(username: str) -> str:
    name = unicodedata.normalize("NFKC", str(username or "")).strip().lower()
    if not USERNAME_RE.match(name):
        raise AccountError(
            "A username is 2 to 32 characters: letters, digits, dot, dash or "
            "underscore, starting with a letter or digit."
        )
    return name


def clean_site_key(key: Any) -> str:
    """The site's identifier for a person, as text.

    Whatever the site uses -- a number, usually.  It is only ever compared
    for equality, so the one rule is that it is something.
    """
    text = unicodedata.normalize("NFKC", str(key if key is not None else "")).strip()
    if not text or len(text) > 190:
        raise AccountError("That is not somebody the site knows.")
    return text


def check_password(password: str, username: str = "") -> None:
    """Long enough to be worth having, and not the username again."""
    password = str(password or "")
    if len(password) < MIN_PASSWORD:
        raise AccountError(
            f"A password has to be at least {MIN_PASSWORD} characters.")
    if username and password.strip().lower() == username.strip().lower():
        raise AccountError("The password cannot be the username.")
    if password.strip() == "":
        raise AccountError("The password cannot be only spaces.")
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        raise AccountError("The password has characters that cannot be typed.")


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_email(email: Any) -> str:
    """An email as kept and compared: trimmed and lower-cased; '' for none."""
    email = str(email or "").strip().lower()
    if not email:
        return ""
    if len(email) > 254 or not EMAIL_PATTERN.match(email):
        raise AccountError(f"{email} is not an email address.")
    return email


def clean_unit_name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise AccountError("A unit needs a name.")
    if len(name) > 60:
        raise AccountError("A unit name has to be 60 characters or fewer.")
    return name


def generated_password(words: int = 4) -> str:
    """A password an administrator can read out over the phone."""
    alphabet = "abcdefghijkmnopqrstuvwxyz23456789"
    return "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(words)
    )


def data_dir() -> Path:
    """Where accounts and workbooks live.

    ``WORKLOAD_DATA_DIR`` decides it; on a host like PythonAnywhere that is a
    folder outside the code, so a deploy never overwrites anyone's data.
    """
    configured = os.environ.get("WORKLOAD_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent.parent / "instance"
