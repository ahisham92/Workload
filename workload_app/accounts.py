"""Accounts, sessions and each account's units.

Everything the app knows about who you are lives here, in a SQLite file beside
the workbooks.  There is no public sign-up: an administrator makes an account,
and until they do there is nothing to log in to.

Passwords are stored as PBKDF2-HMAC-SHA256 with a per-account salt, and the
iteration count is stored beside each hash so it can be raised later without
invalidating anyone.  Session tokens are random, and only their SHA-256 digest
is stored -- a stolen database is not a set of usable cookies.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

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
"""


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class Accounts:
    """The account database.  Cheap to construct; a connection per operation."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        # More than one web worker will have this file open at once.
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 15000")
        return db

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
                    display_name: str = "", is_admin: bool = False
                    ) -> Dict[str, Any]:
        username = clean_username(username)
        check_password(password, username)
        salt = secrets.token_bytes(SALT_BYTES)
        digest = _hash(password, salt, ITERATIONS)
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "INSERT INTO users (username, display_name, password_hash, "
                    "salt, iterations, is_admin, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (username, (display_name or "").strip(), digest, salt,
                     ITERATIONS, 1 if is_admin else 0, now()),
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
            check_password(password, row["username"])
            salt = secrets.token_bytes(SALT_BYTES)
            db.execute(
                "UPDATE users SET password_hash = ?, salt = ?, iterations = ? "
                "WHERE id = ?",
                (_hash(password, salt, ITERATIONS), salt, ITERATIONS, user_id),
            )
            # A password change ends every session but the one changing it;
            # the caller re-issues its own.
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def set_admin(self, user_id: int, is_admin: bool) -> None:
        with self._connect() as db:
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

    # -- logging in ------------------------------------------------------
    def verify(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """The account, or ``None``.  Takes the same time either way."""
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
            _hash(password or "", b"decoy-salt-1234", ITERATIONS)
            return None
        expected = bytes(row["password_hash"])
        actual = _hash(password or "", bytes(row["salt"]), int(row["iterations"]))
        if not hmac.compare_digest(expected, actual):
            return None
        with self._connect() as db:
            db.execute("UPDATE users SET last_seen = ? WHERE id = ?",
                       (now(), row["id"]))
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

    def end_all_sessions(self, user_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

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


# --------------------------------------------------------------------------
# the small print
# --------------------------------------------------------------------------

def _hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", unicodedata.normalize("NFKC", password).encode("utf-8"),
        salt, iterations)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_user(row: sqlite3.Row) -> Dict[str, Any]:
    """Everything about an account except the parts that let you become it."""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "is_admin": bool(row["is_admin"]),
        "created_at": row["created_at"],
        "last_seen": row["last_seen"],
        "units": row["units"] if "units" in row.keys() else None,
    }


def clean_username(username: str) -> str:
    name = unicodedata.normalize("NFKC", str(username or "")).strip().lower()
    if not USERNAME_RE.match(name):
        raise AccountError(
            "A username is 2 to 32 characters: letters, digits, dot, dash or "
            "underscore, starting with a letter or digit."
        )
    return name


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
