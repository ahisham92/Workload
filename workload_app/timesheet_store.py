"""Timesheet rows, in a database instead of the workbook.

The workbook consolidates the monthly sheets with ``VSTACK`` and reads the
result up to a fixed row, and every ``SUMIFS`` in the file stops at that row
too.  That design has two ceilings: the stack (raising it rewrites ~138,000
formulas and takes the better part of a minute) and the twelve engineer slots
the calendar and the share columns have room for.  A head of department with
eighty people below him fits in neither.

So the rows live here instead: one SQLite file per unit, beside its workbook.
There is no cap, adding a person costs nothing, and a year of eighty people is
a few hundred thousand rows -- which SQLite considers small.

The workbook keeps everything else, and keeps being the model: projects,
deliverables, project types, rules of credit, the scorecard, the calendar.
This holds only what those formulas used to sum over, and
``metrics.TimesheetIndex`` reads from here instead of from the sheets.  On
export the rows are written back into the TS sheets, as far as they fit, so
the file you download is still a workbook that opens and calculates.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS rows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person          TEXT NOT NULL,       -- whose sheet this row belongs to
    job_type        TEXT NOT NULL DEFAULT '',
    job_number      TEXT NOT NULL DEFAULT '',
    job_name        TEXT NOT NULL DEFAULT '',
    full_name       TEXT NOT NULL DEFAULT '',
    day             TEXT,                -- ISO date, or NULL if the row had none
    phase           INTEGER,
    regular_hours   REAL NOT NULL DEFAULT 0,
    overtime_hours  REAL NOT NULL DEFAULT 0,
    hours           REAL NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT '',   -- the file it came from
    imported_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS rows_person ON rows(person);
CREATE INDEX IF NOT EXISTS rows_job ON rows(job_number);
CREATE INDEX IF NOT EXISTS rows_day ON rows(day);

-- What the app knows about this unit that the workbook has no room for.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- The organisation under a head of department. Not in the workbook, because
-- the workbook has room for twelve people and one flat list of them.
CREATE TABLE IF NOT EXISTS teams (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    lead       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    name       TEXT PRIMARY KEY,     -- the same name the timesheet rows carry
    team_id    TEXT REFERENCES teams(id) ON DELETE SET NULL,
    grade      TEXT NOT NULL DEFAULT 'engineer',
    capacity_hours REAL,             -- a month of this person, if not the default
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS people_team ON people(team_id);
"""

#: The columns a row is made of, in the order ``add`` expects them.
FIELDS = ("person", "job_type", "job_number", "job_name", "full_name", "day",
          "phase", "regular_hours", "overtime_hours", "hours", "source")


#: "leave this column alone", so a save can change one field without being
#: handed the others and getting them wrong.
_KEEP = object()


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _as_date(value: Any) -> Optional[_dt.date]:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return _dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


class TimesheetStore:
    """One unit's timesheet rows.  Cheap to construct; a connection per call."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        # More than one web worker may have this open at once.
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 15000")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # -- writing ---------------------------------------------------------
    def replace(self, person: str, rows: Sequence[Dict[str, Any]], *,
                source: str = "") -> int:
        """The monthly routine: this person's rows, instead of what was there."""
        with self._connect() as db:
            db.execute("DELETE FROM rows WHERE person = ?", (person,))
            return self._insert(db, person, rows, source)

    def append(self, person: str, rows: Sequence[Dict[str, Any]], *,
               source: str = "") -> int:
        with self._connect() as db:
            return self._insert(db, person, rows, source)

    def _insert(self, db: sqlite3.Connection, person: str,
                rows: Sequence[Dict[str, Any]], source: str) -> int:
        stamp = now()
        payload = []
        for row in rows:
            day = _as_date(row.get("date") if "date" in row else row.get("day"))
            phase = row.get("phase")
            payload.append((
                person,
                str(row.get("job_type") or ""),
                str(row.get("job_number") or "").strip(),
                str(row.get("job_name") or ""),
                str(row.get("full_name") or ""),
                day.isoformat() if day else None,
                int(phase) if isinstance(phase, (int, float)) else None,
                float(row.get("regular_hours") or 0.0),
                float(row.get("overtime_hours") or 0.0),
                float(row.get("hours") or 0.0),
                str(row.get("source") or source),
                stamp,
            ))
        db.executemany(
            "INSERT INTO rows (person, job_type, job_number, job_name, "
            "full_name, day, phase, regular_hours, overtime_hours, hours, "
            "source, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            payload)
        return len(payload)

    def forget(self, person: str) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM rows WHERE person = ?",
                              (person,)).rowcount

    def rename_person(self, old: str, new: str) -> int:
        with self._connect() as db:
            return db.execute("UPDATE rows SET person = ? WHERE person = ?",
                              (new, old)).rowcount

    # -- reading ---------------------------------------------------------
    def all_rows(self) -> List[Dict[str, Any]]:
        """Every row, shaped the way the calculations expect them."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT person, job_type, job_number, job_name, full_name, "
                "day, phase, regular_hours, overtime_hours, hours FROM rows"
            ).fetchall()
        return [{
            "engineer": row["person"],
            "job_type": row["job_type"],
            "job_number": row["job_number"],
            "job_name": row["job_name"],
            "full_name": row["full_name"],
            "date": _as_date(row["day"]),
            "phase": row["phase"],
            "regular_hours": row["regular_hours"],
            "overtime_hours": row["overtime_hours"],
            "hours": row["hours"],
        } for row in rows]

    def rows_for(self, person: str) -> List[Dict[str, Any]]:
        return [row for row in self.all_rows() if row["engineer"] == person]

    def is_empty(self) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM rows LIMIT 1").fetchone() is None

    def count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) AS n FROM rows").fetchone()["n"]

    def counts(self) -> Dict[str, int]:
        with self._connect() as db:
            return {row["person"]: row["n"] for row in db.execute(
                "SELECT person, COUNT(*) AS n FROM rows GROUP BY person")}

    def people_with_rows(self) -> List[str]:
        """Everybody the timesheets know about, team or no team."""
        with self._connect() as db:
            return [row["person"] for row in db.execute(
                "SELECT DISTINCT person FROM rows ORDER BY person")]

    def date_range(self) -> Tuple[Optional[_dt.date], Optional[_dt.date]]:
        with self._connect() as db:
            row = db.execute(
                "SELECT MIN(day) AS lo, MAX(day) AS hi FROM rows "
                "WHERE day IS NOT NULL").fetchone()
        return _as_date(row["lo"]), _as_date(row["hi"])

    def jobs_seen(self) -> List[Dict[str, Any]]:
        """Every job number in the rows, with the name and effort behind it.

        This is what turns a batch of exports into a project register: the
        numbers people actually charged to, ranked by the hours behind them.
        """
        with self._connect() as db:
            rows = db.execute(
                "SELECT job_number, job_type, SUM(hours) AS hours, "
                "COUNT(*) AS entries, COUNT(DISTINCT person) AS people, "
                "MIN(day) AS first_day, MAX(day) AS last_day "
                "FROM rows WHERE job_number <> '' "
                "GROUP BY job_number ORDER BY hours DESC").fetchall()
            names = defaultdict(list)
            for row in db.execute(
                    "SELECT job_number, job_name, COUNT(*) AS n FROM rows "
                    "WHERE job_name <> '' GROUP BY job_number, job_name "
                    "ORDER BY n DESC"):
                names[row["job_number"]].append(row["job_name"])
        return [{
            "job_number": row["job_number"],
            "job_type": row["job_type"],
            # The name people typed most often for this number wins.
            "job_name": (names.get(row["job_number"]) or [""])[0],
            "hours": round(row["hours"] or 0.0, 2),
            "entries": row["entries"],
            "people": row["people"],
            "first_day": row["first_day"],
            "last_day": row["last_day"],
        } for row in rows]

    # -- who is who ------------------------------------------------------
    def teams(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM teams ORDER BY name")]

    def add_team(self, team_id: str, name: str, lead: str = "") -> Dict[str, Any]:
        with self._connect() as db:
            db.execute("INSERT INTO teams (id, name, lead, created_at) "
                       "VALUES (?, ?, ?, ?)", (team_id, name, lead, now()))
        return {"id": team_id, "name": name, "lead": lead}

    def update_team(self, team_id: str, *, name: Optional[str] = None,
                    lead: Optional[str] = None) -> None:
        with self._connect() as db:
            if name is not None:
                db.execute("UPDATE teams SET name = ? WHERE id = ?", (name, team_id))
            if lead is not None:
                db.execute("UPDATE teams SET lead = ? WHERE id = ?", (lead, team_id))

    def remove_team(self, team_id: str) -> None:
        """The team goes; its people stay, without a team."""
        with self._connect() as db:
            db.execute("UPDATE people SET team_id = NULL WHERE team_id = ?",
                       (team_id,))
            db.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    def people(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM people ORDER BY name")]

    def save_person(self, name: str, *, team_id: Any = _KEEP,
                    grade: Any = _KEEP, capacity_hours: Any = _KEEP,
                    active: Any = _KEEP) -> None:
        """Add or change one person. Anything not passed is left as it was."""
        with self._connect() as db:
            db.execute(
                "INSERT INTO people (name, created_at) VALUES (?, ?) "
                "ON CONFLICT(name) DO NOTHING", (name, now()))
            for column, value in (("team_id", team_id), ("grade", grade),
                                  ("capacity_hours", capacity_hours),
                                  ("active", active)):
                if value is not _KEEP:
                    db.execute(f"UPDATE people SET {column} = ? WHERE name = ?",
                               (value, name))

    def move_people(self, names: Sequence[str], team_id: Optional[str]) -> int:
        """Put several people in a team at once, which is the whole point."""
        moved = 0
        with self._connect() as db:
            for name in names:
                db.execute(
                    "INSERT INTO people (name, created_at) VALUES (?, ?) "
                    "ON CONFLICT(name) DO NOTHING", (name, now()))
                moved += db.execute(
                    "UPDATE people SET team_id = ? WHERE name = ?",
                    (team_id, name)).rowcount
        return moved

    def remove_person(self, name: str) -> None:
        """Forget who they were. Their timesheet rows are not theirs to delete."""
        with self._connect() as db:
            db.execute("DELETE FROM people WHERE name = ?", (name,))

    def rename_person_everywhere(self, old: str, new: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE OR REPLACE people SET name = ? WHERE name = ?",
                       (new, old))
            db.execute("UPDATE rows SET person = ? WHERE person = ?", (new, old))

    # -- settings --------------------------------------------------------
    def setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?",
                             (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: Optional[str]) -> None:
        with self._connect() as db:
            if value is None:
                db.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                db.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)))

    def settings(self) -> Dict[str, str]:
        with self._connect() as db:
            return {row["key"]: row["value"]
                    for row in db.execute("SELECT key, value FROM settings")}
