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

from .model import stored_date

#: Bumped by every write to the unit's file, by whichever worker makes it, so
#: another worker -- or this one -- knows what it read before is out of date.
REVISION_KEY = "unit.revision"
#: Bumped by the database itself whenever a timesheet row is written.
ROWS_REVISION_KEY = "unit.rows_revision"


def note_change(db: sqlite3.Connection) -> bool:
    """Bump the revision, in the same transaction, if ``db`` changed anything."""
    if not db.total_changes:
        return False
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1",
        (REVISION_KEY,))
    return True


class Row(dict):
    """One timesheet row as the calculations see it, and cannot change.

    The rows are read once per revision and shared by every figure worked out
    from them; a calculation that wrote into one would quietly change the
    next one's answer, so it is refused instead.
    """

    __slots__ = ()

    def _refuse(self, *args, **kwargs):
        raise TypeError("timesheet rows are shared; copy one with dict(row) to change it")

    __setitem__ = __delitem__ = update = pop = popitem = setdefault = clear = _refuse


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
    deliverable     TEXT NOT NULL DEFAULT '',   -- what the phase is called
    job_status      TEXT NOT NULL DEFAULT '',
    grade           TEXT NOT NULL DEFAULT '',
    unit            TEXT NOT NULL DEFAULT '',   -- CurrentUnitDesc: who sits where
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

-- How many drawings a deliverable is.  The one figure no timesheet carries,
-- and the one the work is measured by.  Keyed by the deliverable's row, with
-- its project beside it so a row reused by another project reads as empty.
CREATE TABLE IF NOT EXISTS drawings (
    row            INTEGER PRIMARY KEY,
    project_number TEXT NOT NULL,
    count          INTEGER NOT NULL
);

-- Work handed from one person to another for the coming days: a share of
-- what they have been doing on a project, from one day to another.
CREATE TABLE IF NOT EXISTS plan_moves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL,
    from_person TEXT NOT NULL,
    to_person   TEXT NOT NULL,
    share       REAL NOT NULL,
    start       TEXT NOT NULL,
    end         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Somebody away -- leave, a course, site -- or, with person '*', a day
-- nobody works.  Known ahead, so the plan and the forecast do not count
-- people who will not be there.
CREATE TABLE IF NOT EXISTS absences (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person     TEXT NOT NULL,
    start      TEXT NOT NULL,
    end        TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- What the uploaded drawing list says, a deliverable a row: how many
-- drawings, how many have gone to the client, and the codes come back.
CREATE TABLE IF NOT EXISTS drawing_list (
    row            INTEGER PRIMARY KEY,
    project_number TEXT NOT NULL,
    total          INTEGER NOT NULL,
    issued         INTEGER NOT NULL,
    code_a         INTEGER NOT NULL DEFAULT 0,
    code_b         INTEGER NOT NULL DEFAULT 0,
    code_c         INTEGER NOT NULL DEFAULT 0,
    last_issued    TEXT,
    last_returned  TEXT,
    updated_at     TEXT NOT NULL
);

-- Work coming: a project just assigned, before anybody has booked to it.
-- Rough hours between two dates, for the staffing forecast, until the
-- timesheets or the project's own figures take over.
CREATE TABLE IF NOT EXISTS planned_work (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_number  TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    team_id     TEXT NOT NULL DEFAULT '',
    hours       REAL NOT NULL,
    start       TEXT NOT NULL,
    end         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- When in the day a request that came in is being done: the task itself is
-- on the workbook's task list, its time of day has nowhere to go there.
CREATE TABLE IF NOT EXISTS slots (
    task_id    INTEGER PRIMARY KEY,
    person     TEXT NOT NULL,
    start      TEXT NOT NULL,       -- ISO date and time, local to the team
    end        TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- What a team member said from their own My day: a task done, stuck, help
-- needed, or days off.  Only ever written for the person signed in; the lead
-- sees the open ones in Check-ins and marks them seen.
CREATE TABLE IF NOT EXISTS member_marks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person      TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- done | stuck | help | off
    task_id     INTEGER,
    absence_id  INTEGER,
    note        TEXT NOT NULL DEFAULT '',
    before      TEXT NOT NULL DEFAULT '',  -- the task's status before, to undo
    created_at  TEXT NOT NULL,
    cleared_at  TEXT,
    cleared_by  TEXT NOT NULL DEFAULT ''   -- undone | lead | done
);
CREATE INDEX IF NOT EXISTS member_marks_person ON member_marks(person, cleared_at);

-- Each person's development goals for a quarter ("2026-Q4"): set by the
-- manager at the start, marked met, partly or not met at the review.
CREATE TABLE IF NOT EXISTS development_goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person      TEXT NOT NULL,
    quarter     TEXT NOT NULL,
    goal        TEXT NOT NULL,
    measure     TEXT NOT NULL DEFAULT '',  -- how we will know it is done
    result      TEXT NOT NULL DEFAULT '',  -- '' | met | partly | not_met
    review_note TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX IF NOT EXISTS development_goals_quarter ON development_goals(quarter, person);

-- What BISpark's Projects list says each job has, for the department, and the
-- share of it that is this team's.  The share is the manager's own (NULL: work
-- it out from who booked the hours); it is kept through every import.
CREATE TABLE IF NOT EXISTS job_budgets (
    job_number        TEXT PRIMARY KEY,
    title             TEXT NOT NULL DEFAULT '',
    lead              TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT '',
    dept              TEXT NOT NULL DEFAULT '',
    budget_mm         REAL,
    spent_mm          REAL,
    remaining_mm      REAL,
    eac_mm            REAL,
    ev_mm             REAL,
    progress          REAL,
    start             TEXT,
    end               TEXT,
    needs_more        INTEGER NOT NULL DEFAULT 0,
    listed            INTEGER NOT NULL DEFAULT 1,  -- in the latest Projects list
    team_share        REAL,
    applied_budget_mm REAL,      -- the project budget this last set, if any
    source            TEXT NOT NULL DEFAULT '',
    imported_at       TEXT
);

-- Who spent a job's man-months, from BISpark's staff expenditure: a name,
-- the unit and department they sit in, and the hours.  Nothing else about
-- them is kept.  A job's rows are replaced only by a new export of that job.
CREATE TABLE IF NOT EXISTS job_spend (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_number  TEXT NOT NULL,
    full_name   TEXT NOT NULL DEFAULT '',
    unit        TEXT NOT NULL DEFAULT '',
    dept        TEXT NOT NULL DEFAULT '',
    day         TEXT,
    phase       INTEGER,
    deliverable TEXT NOT NULL DEFAULT '',
    hours       REAL NOT NULL DEFAULT 0,
    overtime    REAL NOT NULL DEFAULT 0,   -- of those hours
    mm          REAL NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS job_spend_job ON job_spend(job_number);

-- What the manager says each person on the staff expenditures is to the
-- team, where the unit they sit in does not say it: team | draftsman |
-- other | left (counted up to to_day) | loan (counted from_day to to_day).
-- Nobody listed here is "team" if they sit in the team's unit, else "other".
CREATE TABLE IF NOT EXISTS spend_people (
    full_name TEXT NOT NULL,
    unit      TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL,
    from_day  TEXT,
    to_day    TEXT,
    set_at    TEXT NOT NULL,
    PRIMARY KEY (full_name, unit)
);

-- Each person's Outlook calendar, published "Can view when I'm busy": the
-- link, sealed (see secretbox), and whether it was last read cleanly.  Added
-- by the person themselves (self) or by their manager.
CREATE TABLE IF NOT EXISTS calendar_links (
    person     TEXT PRIMARY KEY,
    link_seal  TEXT NOT NULL,
    added_by   TEXT NOT NULL DEFAULT 'self',   -- self | manager
    added_at   TEXT NOT NULL,
    read_at    TEXT,                -- when the busy times below last changed
    problem    TEXT NOT NULL DEFAULT '',
    digest     TEXT NOT NULL DEFAULT ''
);

-- When each of them is busy in the coming weeks, from that calendar: a start
-- and an end, local to them, and nothing else -- no titles, no attendees.
CREATE TABLE IF NOT EXISTS calendar_busy (
    person TEXT NOT NULL,
    start  TEXT NOT NULL,
    end    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS calendar_busy_person ON calendar_busy(person, start);
""" + "".join(f"""
-- Counts the writes to the timesheet rows alone, whoever makes them, so the
-- rows read before can be kept through every other kind of change.
CREATE TRIGGER IF NOT EXISTS rows_written_{event.lower()} AFTER {event} ON rows
BEGIN
    INSERT OR REPLACE INTO settings (key, value) VALUES ('{ROWS_REVISION_KEY}',
        COALESCE((SELECT CAST(value AS INTEGER) FROM settings
                  WHERE key = '{ROWS_REVISION_KEY}'), 0) + 1);
END;
""" for event in ("INSERT", "UPDATE", "DELETE"))

#: Columns added after the first stores were made, and so added to those on
#: open.  A store from before them simply has them blank.
_LATER_COLUMNS = {
    "deliverable": "TEXT NOT NULL DEFAULT ''",
    "job_status": "TEXT NOT NULL DEFAULT ''",
    "grade": "TEXT NOT NULL DEFAULT ''",
    "unit": "TEXT NOT NULL DEFAULT ''",
}


#: "leave this column alone", so a save can change one field without being
#: handed the others and getting them wrong.
_KEEP = object()


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class TimesheetStore:
    """One unit's timesheet rows.  Cheap to construct; a connection per call."""

    def __init__(self, path: Path):
        self.path = Path(path)
        #: Set by the unit this store belongs to: ``memo(key, build)`` keeps a
        #: value until the next write, and ``changed()`` is told of each write.
        self.memo = None
        self.changed = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
            have = {row["name"] for row in db.execute("PRAGMA table_info(rows)")}
            for column, kind in _LATER_COLUMNS.items():
                if column not in have:
                    db.execute(f"ALTER TABLE rows ADD COLUMN {column} {kind}")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        # More than one web worker may have this open at once.
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 15000")
        wrote = False
        try:
            yield db
            wrote = note_change(db)
            db.commit()
        finally:
            db.close()
        if wrote and self.changed is not None:
            self.changed()

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
            day = stored_date(row.get("date") if "date" in row else row.get("day"))
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
                str(row.get("deliverable") or ""),
                str(row.get("job_status") or ""),
                str(row.get("grade") or ""),
                str(row.get("unit") or ""),
                str(row.get("source") or source),
                stamp,
            ))
        db.executemany(
            "INSERT INTO rows (person, job_type, job_number, job_name, "
            "full_name, day, phase, regular_hours, overtime_hours, hours, "
            "deliverable, job_status, grade, unit, source, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        """Every row, shaped the way the calculations expect them.

        Read once until the next write when the store belongs to a unit; the
        rows themselves cannot be changed (see :class:`Row`).
        """
        if self.memo is None:
            return list(self._read_rows())
        return list(self.memo("rows", self._read_rows))

    def _read_rows(self) -> Tuple[Row, ...]:
        with self._connect() as db:
            db.row_factory = None
            rows = db.execute(
                "SELECT person, job_type, job_number, job_name, full_name, "
                "day, phase, regular_hours, overtime_hours, hours, "
                "deliverable, job_status, grade FROM rows"
            ).fetchall()
        dates: Dict[Any, Optional[_dt.date]] = {}
        out = []
        for (person, job_type, job_number, job_name, full_name, day, phase,
             regular, overtime, hours, deliverable, job_status, grade) in rows:
            # A few hundred distinct days stand for thousands of rows.
            try:
                date = dates[day]
            except KeyError:
                date = dates[day] = stored_date(day)
            out.append(Row(
                engineer=person, job_type=job_type, job_number=job_number,
                job_name=job_name, full_name=full_name, date=date, phase=phase,
                regular_hours=regular, overtime_hours=overtime, hours=hours,
                deliverable=deliverable, job_status=job_status, grade=grade))
        return tuple(out)

    def rows_for(self, person: str) -> List[Dict[str, Any]]:
        return [row for row in self.all_rows() if row["engineer"] == person]

    def is_empty(self) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM rows LIMIT 1").fetchone() is None

    def count(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) AS n FROM rows").fetchone()["n"]

    def counts(self, *, without_source: str = "") -> Dict[str, int]:
        """Rows per person, leaving out the rows one source added if asked."""
        with self._connect() as db:
            if not without_source:
                found = db.execute(
                    "SELECT person, COUNT(*) AS n FROM rows GROUP BY person")
            else:
                found = db.execute(
                    "SELECT person, COUNT(*) AS n FROM rows WHERE source <> ? "
                    "GROUP BY person", (without_source,))
            return {row["person"]: row["n"] for row in found}

    def people_with_rows(self) -> List[str]:
        """Everybody the timesheets know about, team or no team."""
        with self._connect() as db:
            return [row["person"] for row in db.execute(
                "SELECT DISTINCT person FROM rows ORDER BY person")]

    def names_by_full_name(self) -> Dict[str, str]:
        """Whose rows each full name on an export has gone to so far."""
        with self._connect() as db:
            return {row["full_name"]: row["person"] for row in db.execute(
                "SELECT full_name, person, COUNT(*) AS n FROM rows "
                "WHERE full_name <> '' GROUP BY full_name, person ORDER BY n")}

    def date_range(self) -> Tuple[Optional[_dt.date], Optional[_dt.date]]:
        with self._connect() as db:
            row = db.execute(
                "SELECT MIN(day) AS lo, MAX(day) AS hi FROM rows "
                "WHERE day IS NOT NULL").fetchone()
        return stored_date(row["lo"]), stored_date(row["hi"])

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
            db.execute("UPDATE planned_work SET team_id = '' WHERE team_id = ?",
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
            db.execute("DELETE FROM calendar_busy WHERE person = ?", (name,))
            db.execute("DELETE FROM calendar_links WHERE person = ?", (name,))

    def rename_person_everywhere(self, old: str, new: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE OR REPLACE people SET name = ? WHERE name = ?",
                       (new, old))
            db.execute("UPDATE rows SET person = ? WHERE person = ?", (new, old))
            db.execute("UPDATE plan_moves SET from_person = ? "
                       "WHERE from_person = ?", (new, old))
            db.execute("UPDATE plan_moves SET to_person = ? "
                       "WHERE to_person = ?", (new, old))
            db.execute("UPDATE absences SET person = ? WHERE person = ?",
                       (new, old))
            db.execute("UPDATE member_marks SET person = ? WHERE person = ?",
                       (new, old))
            db.execute("UPDATE development_goals SET person = ? WHERE person = ?",
                       (new, old))
            db.execute("UPDATE OR REPLACE calendar_links SET person = ? "
                       "WHERE person = ?", (new, old))
            db.execute("UPDATE calendar_busy SET person = ? WHERE person = ?",
                       (new, old))
            # "This is me" (service.me_key) follows the person it names.
            db.execute("UPDATE settings SET value = ? "
                       "WHERE key LIKE 'team\\_me:%' ESCAPE '\\' AND value = ?",
                       (new, old))

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

    # -- where people sit, by their own timesheets -------------------------
    def latest_units(self) -> Dict[str, str]:
        """Each person's ``CurrentUnitDesc`` on the latest day they booked."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT person, unit FROM rows WHERE unit <> '' "
                "ORDER BY day IS NULL DESC, day, id").fetchall()
        out: Dict[str, str] = {}
        for row in rows:
            out[row["person"]] = row["unit"]
        return out

    # -- drawings ----------------------------------------------------------
    def drawings(self) -> Dict[int, Dict[str, Any]]:
        with self._connect() as db:
            return {row["row"]: dict(row) for row in db.execute(
                "SELECT row, project_number, count FROM drawings")}

    def set_drawings(self, row: int, project_number: str,
                     count: Optional[int]) -> None:
        with self._connect() as db:
            if count is None:
                db.execute("DELETE FROM drawings WHERE row = ?", (row,))
            else:
                db.execute(
                    "INSERT INTO drawings (row, project_number, count) "
                    "VALUES (?, ?, ?) ON CONFLICT(row) DO UPDATE SET "
                    "project_number = excluded.project_number, "
                    "count = excluded.count", (row, project_number, int(count)))

    # -- work handed over for the coming days ------------------------------
    def plan_moves(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM plan_moves ORDER BY id")]

    def add_plan_move(self, *, project: str, from_person: str, to_person: str,
                      share: float, start: str, end: str) -> int:
        with self._connect() as db:
            return db.execute(
                "INSERT INTO plan_moves (project, from_person, to_person, share, "
                "start, end, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project, from_person, to_person, float(share), start, end,
                 now())).lastrowid

    def remove_plan_move(self, move_id: int) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM plan_moves WHERE id = ?",
                              (int(move_id),)).rowcount

    # -- time slots for requests -------------------------------------------
    def slots(self) -> Dict[int, Dict[str, Any]]:
        with self._connect() as db:
            return {row["task_id"]: dict(row) for row in db.execute(
                "SELECT * FROM slots ORDER BY start")}

    def set_slot(self, task_id: int, person: str, start: str, end: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO slots (task_id, person, start, end, created_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
                "person = excluded.person, start = excluded.start, "
                "end = excluded.end", (int(task_id), person, start, end, now()))

    def remove_slot(self, task_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM slots WHERE task_id = ?", (int(task_id),))

    # -- Outlook calendars, busy times only ---------------------------------
    def calendar_links(self) -> Dict[str, Dict[str, Any]]:
        with self._connect() as db:
            return {row["person"]: dict(row) for row in db.execute(
                "SELECT * FROM calendar_links ORDER BY person")}

    def set_calendar_link(self, person: str, link_seal: str, added_by: str) -> None:
        """A new link starts clean: the old one's busy times go with it."""
        with self._connect() as db:
            db.execute("DELETE FROM calendar_busy WHERE person = ?", (person,))
            db.execute(
                "INSERT INTO calendar_links (person, link_seal, added_by, added_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(person) DO UPDATE SET "
                "link_seal = excluded.link_seal, added_by = excluded.added_by, "
                "added_at = excluded.added_at, read_at = NULL, problem = '', "
                "digest = ''", (person, link_seal, added_by, now()))

    def remove_calendar_link(self, person: str) -> int:
        with self._connect() as db:
            db.execute("DELETE FROM calendar_busy WHERE person = ?", (person,))
            return db.execute("DELETE FROM calendar_links WHERE person = ?",
                              (person,)).rowcount

    def calendar_read(self, person: str, *, digest: str = "",
                      busy: Optional[Sequence[Tuple[str, str]]] = None,
                      problem: str = "", keep_from: Optional[str] = None) -> bool:
        """What reading the calendar gave: new busy times, or a problem.
        Nothing is written when nothing changed, so the figures worked out
        from the unit are kept.  Busy times ending before ``keep_from`` go
        whatever came back.  True when something was written."""
        with self._connect() as db:
            if keep_from:
                db.execute("DELETE FROM calendar_busy WHERE person = ? AND end < ?",
                           (person, keep_from))
            row = db.execute("SELECT digest, problem FROM calendar_links "
                             "WHERE person = ?", (person,)).fetchone()
            if row is None:
                return False
            if problem:
                if row["problem"] == problem:
                    return False
                db.execute("UPDATE calendar_links SET problem = ? WHERE person = ?",
                           (problem, person))
                return True
            if row["digest"] == digest and not row["problem"]:
                return False
            db.execute("DELETE FROM calendar_busy WHERE person = ?", (person,))
            db.executemany(
                "INSERT INTO calendar_busy (person, start, end) VALUES (?, ?, ?)",
                [(person, first, last) for first, last in (busy or ())])
            db.execute("UPDATE calendar_links SET digest = ?, problem = '', "
                       "read_at = ? WHERE person = ?", (digest, now(), person))
            return True

    def calendar_busy(self) -> Dict[str, List[Tuple[str, str]]]:
        with self._connect() as db:
            out: Dict[str, List[Tuple[str, str]]] = {}
            for row in db.execute(
                    "SELECT person, start, end FROM calendar_busy "
                    "ORDER BY person, start"):
                out.setdefault(row["person"], []).append((row["start"], row["end"]))
            return out

    # -- time away ---------------------------------------------------------
    def absences(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM absences ORDER BY start, person")]

    def add_absence(self, person: str, start: str, end: str, note: str = "") -> int:
        with self._connect() as db:
            return db.execute(
                "INSERT INTO absences (person, start, end, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)", (person, start, end, note, now())).lastrowid

    def remove_absence(self, absence_id: int) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM absences WHERE id = ?",
                              (int(absence_id),)).rowcount

    # -- what team members said from My day -----------------------------------
    def marks(self, *, person: Optional[str] = None, open_only: bool = False,
              since: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, args = "SELECT * FROM member_marks WHERE 1 = 1", []
        if person is not None:
            sql += " AND person = ?"
            args.append(person)
        if open_only:
            sql += " AND cleared_at IS NULL"
        if since is not None:
            sql += " AND created_at >= ?"
            args.append(since)
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql + " ORDER BY id", args)]

    def mark(self, mark_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM member_marks WHERE id = ?",
                             (int(mark_id),)).fetchone()
            return dict(row) if row else None

    def add_mark(self, person: str, kind: str, *, task_id: Optional[int] = None,
                 absence_id: Optional[int] = None, note: str = "",
                 before: str = "") -> int:
        with self._connect() as db:
            return db.execute(
                "INSERT INTO member_marks (person, kind, task_id, absence_id, note, "
                "before, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (person, kind, task_id, absence_id, note, before, now())).lastrowid

    def clear_mark(self, mark_id: int, by: str) -> int:
        with self._connect() as db:
            return db.execute(
                "UPDATE member_marks SET cleared_at = ?, cleared_by = ? "
                "WHERE id = ? AND cleared_at IS NULL", (now(), by, int(mark_id))).rowcount

    # -- development goals -----------------------------------------------------
    def goals(self, *, quarter: Optional[str] = None,
              person: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, args = "SELECT * FROM development_goals WHERE 1 = 1", []
        if quarter is not None:
            sql += " AND quarter = ?"
            args.append(quarter)
        if person is not None:
            sql += " AND person = ?"
            args.append(person)
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql + " ORDER BY quarter, person, id",
                                                    args)]

    def goal(self, goal_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM development_goals WHERE id = ?",
                             (int(goal_id),)).fetchone()
            return dict(row) if row else None

    def add_goal(self, person: str, quarter: str, goal: str, measure: str = "") -> int:
        with self._connect() as db:
            return db.execute(
                "INSERT INTO development_goals (person, quarter, goal, measure, "
                "created_at) VALUES (?, ?, ?, ?, ?)",
                (person, quarter, goal, measure, now())).lastrowid

    def edit_goal(self, goal_id: int, goal: str, measure: str) -> int:
        with self._connect() as db:
            return db.execute(
                "UPDATE development_goals SET goal = ?, measure = ? WHERE id = ?",
                (goal, measure, int(goal_id))).rowcount

    def review_goal(self, goal_id: int, result: str, note: str) -> int:
        with self._connect() as db:
            return db.execute(
                "UPDATE development_goals SET result = ?, review_note = ?, "
                "reviewed_at = ? WHERE id = ?",
                (result, note, now() if result else None, int(goal_id))).rowcount

    def remove_goal(self, goal_id: int) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM development_goals WHERE id = ?",
                              (int(goal_id),)).rowcount

    # -- the drawing list ------------------------------------------------------
    def drawing_list(self) -> Dict[int, Dict[str, Any]]:
        with self._connect() as db:
            return {row["row"]: dict(row) for row in db.execute(
                "SELECT * FROM drawing_list")}

    def save_drawing_list(self, entries: Sequence[Dict[str, Any]],
                          projects: Iterable[str]) -> None:
        """The list's figures, replacing what an earlier list said of the
        same projects; other projects keep theirs."""
        stamp = now()
        with self._connect() as db:
            for number in set(projects):
                db.execute("DELETE FROM drawing_list WHERE "
                           "REPLACE(UPPER(project_number), ' ', '') = ?", (number,))
            for e in entries:
                db.execute(
                    "INSERT OR REPLACE INTO drawing_list (row, project_number, total, "
                    "issued, code_a, code_b, code_c, last_issued, last_returned, "
                    "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (int(e["row"]), e["project_number"], int(e["total"]),
                     int(e["issued"]), int(e["code_a"]), int(e["code_b"]),
                     int(e["code_c"]), e["last_issued"], e["last_returned"], stamp))

    def clear_drawing_list_row(self, row: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM drawing_list WHERE row = ?", (int(row),))

    # -- work coming ---------------------------------------------------------
    def planned_work(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM planned_work ORDER BY start, name")]

    def add_planned_work(self, *, job_number: str, name: str, team_id: str,
                         hours: float, start: str, end: str) -> int:
        with self._connect() as db:
            return db.execute(
                "INSERT INTO planned_work (job_number, name, team_id, hours, start, "
                "end, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_number, name, team_id, float(hours), start, end, now())).lastrowid

    def remove_planned_work(self, item_id: int) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM planned_work WHERE id = ?",
                              (int(item_id),)).rowcount

    # -- budgets -------------------------------------------------------------
    _BUDGET_FIELDS = ("title", "lead", "status", "dept", "budget_mm",
                      "spent_mm", "remaining_mm", "eac_mm", "ev_mm",
                      "progress", "start", "end", "needs_more", "source")

    def job_budgets(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM job_budgets ORDER BY job_number")]

    def save_job_budgets(self, jobs: Sequence[Dict[str, Any]]) -> int:
        """A new Projects list: these jobs, and only these, are listed now.

        A job missing from it is kept, unlisted, so the share set for it is
        there again if it comes back.
        """
        stamp = now()
        fields = self._BUDGET_FIELDS
        with self._connect() as db:
            db.execute("UPDATE job_budgets SET listed = 0 WHERE listed <> 0")
            for job in jobs:
                values = [job.get(f) for f in fields]
                db.execute(
                    f"INSERT INTO job_budgets (job_number, {', '.join(fields)}, "
                    "listed, imported_at) VALUES "
                    f"(?, {', '.join('?' for _ in fields)}, 1, ?) "
                    "ON CONFLICT(job_number) DO UPDATE SET "
                    + ", ".join(f"{f} = excluded.{f}" for f in fields)
                    + ", listed = 1, imported_at = excluded.imported_at",
                    [job["job_number"], *values, stamp])
            return len(jobs)

    def set_job_share(self, job_number: str, share: Optional[float]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO job_budgets (job_number, team_share, listed) "
                "VALUES (?, ?, 0) ON CONFLICT(job_number) DO UPDATE SET "
                "team_share = excluded.team_share", (job_number, share))

    def set_applied_budget(self, job_number: str, budget: Optional[float]) -> None:
        with self._connect() as db:
            db.execute("UPDATE job_budgets SET applied_budget_mm = ? "
                       "WHERE job_number = ?", (budget, job_number))

    def job_spend(self) -> List[Dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT job_number, full_name, unit, dept, day, phase, "
                "deliverable, hours, overtime, mm, imported_at FROM job_spend")]

    def spend_people(self) -> Dict[Tuple[str, str], Dict[str, Any]]:
        with self._connect() as db:
            return {(row["full_name"], row["unit"]): dict(row) for row in
                    db.execute("SELECT * FROM spend_people")}

    def set_spend_person(self, full_name: str, unit: str, kind: Optional[str],
                         from_day: Optional[str] = None,
                         to_day: Optional[str] = None) -> None:
        """What somebody is to the team; ``kind=None`` goes back to the default."""
        with self._connect() as db:
            if kind is None:
                db.execute("DELETE FROM spend_people WHERE full_name = ? AND unit = ?",
                           (full_name, unit))
                return
            db.execute(
                "INSERT INTO spend_people (full_name, unit, kind, from_day, to_day, "
                "set_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(full_name, unit) "
                "DO UPDATE SET kind = excluded.kind, from_day = excluded.from_day, "
                "to_day = excluded.to_day, set_at = excluded.set_at",
                (full_name, unit, kind, from_day, to_day, now()))

    def own_days(self, job_number: str, source: str) -> set:
        """``(person, day, phase)`` each person's own rows already cover."""
        with self._connect() as db:
            return {(row["person"], row["day"], row["phase"]) for row in db.execute(
                "SELECT DISTINCT person, day, phase FROM rows "
                "WHERE job_number = ? AND source <> ?", (job_number, source))}

    def replace_job_spend(self, job_number: str,
                          entries: Sequence[Dict[str, Any]],
                          gaps: Dict[str, Sequence[Dict[str, Any]]],
                          source: str) -> int:
        """One job's staff expenditure, and the gap rows it fills, at once.

        The gap rows ``source`` added before for this job go first, so a
        second import never counts the same hours twice; nobody's own rows
        are touched.
        """
        stamp = now()
        with self._connect() as db:
            db.execute("DELETE FROM job_spend WHERE job_number = ?", (job_number,))
            db.executemany(
                "INSERT INTO job_spend (job_number, full_name, unit, dept, "
                "day, phase, deliverable, hours, overtime, mm, imported_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(job_number, e.get("full_name") or "", e.get("unit") or "",
                  e.get("dept") or "", e.get("day"), e.get("phase"),
                  e.get("deliverable") or "", float(e.get("hours") or 0),
                  float(e.get("overtime") or 0), float(e.get("mm") or 0), stamp)
                 for e in entries])
            db.execute("DELETE FROM rows WHERE job_number = ? AND source = ?",
                       (job_number, source))
            added = 0
            for person, rows in gaps.items():
                added += self._insert(db, person, rows, source)
            return added

