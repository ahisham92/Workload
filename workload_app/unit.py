"""One unit, kept in its own database.

A unit is its people, its projects and their deliverables, the reference
tables its figures are worked out with, and its task list.  All of it lives in
one SQLite file per unit, beside the timesheet rows the store keeps in the same
file (see ``timesheet_store``), so a unit is a single file on disk and nothing
about it is bounded by a spreadsheet: any number of people, projects,
deliverables, project types or credit steps.

The methods are the ones the rest of the app has always called on a unit, and
they return the same records (see ``model``), so the screens, the reports and
the planner do not need to know where a unit is kept.

Every write commits at once.  ``save`` is kept for the callers that still ask
for it and does nothing; ``refresh`` notices a write made by another worker
process, through a revision number every write bumps.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import sqlite3
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import config as cfg, tasks as task_list
from .model import (CreditStep, Deliverable, Engineer, Project, ProjectType,
                    ValidationError, as_date, as_fraction, as_number, as_text,
                    iso, pattern_to_regex, stored_date)
from .timesheet_store import (REVISION_KEY, ROWS_REVISION_KEY, TimesheetStore,
                              note_change)

SCHEMA = """
-- The team: everybody whose effort is measured here.  No limit on how many.
CREATE TABLE IF NOT EXISTS engineers (
    name            TEXT PRIMARY KEY,   -- the short name used everywhere
    pattern         TEXT NOT NULL DEFAULT '',   -- how their full name reads
    available_hours REAL,               -- a month of them, in hours
    position        INTEGER NOT NULL DEFAULT 0
);

-- How much of each year somebody is here for: 1.0 is all of it.
CREATE TABLE IF NOT EXISTS availability (
    engineer TEXT NOT NULL,
    year     INTEGER NOT NULL,
    share    REAL NOT NULL,
    PRIMARY KEY (engineer, year)
);

-- The project register.  ``row`` is the project's id: it is never reused.
CREATE TABLE IF NOT EXISTS projects (
    row            INTEGER PRIMARY KEY AUTOINCREMENT,
    number         TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL DEFAULT '',
    budget_mm      REAL,
    start          TEXT,
    end            TEXT,
    status         TEXT NOT NULL DEFAULT '',
    cac_override   REAL,
    notes          TEXT NOT NULL DEFAULT '',
    manual_percent REAL
);

-- A project's fallback split, used while its deliverables carry none.
CREATE TABLE IF NOT EXISTS project_shares (
    project_row INTEGER NOT NULL,
    engineer    TEXT NOT NULL,
    share       REAL NOT NULL,
    PRIMARY KEY (project_row, engineer)
);

-- The deliverable register.  ``row`` is the deliverable's id, which tasks,
-- drawing counts and the submissions plan all point at, so it is never handed
-- to another deliverable.
CREATE TABLE IF NOT EXISTS deliverables (
    row                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_number      TEXT NOT NULL,
    name                TEXT NOT NULL DEFAULT '',
    type_code           TEXT NOT NULL DEFAULT '',
    phase_weight        REAL,
    step_no             INTEGER,
    status_date         TEXT,
    notes               TEXT NOT NULL DEFAULT '',
    ts_phase            INTEGER,
    actual_start        TEXT,
    actual_finish       TEXT,
    submitted_to_client TEXT,
    comments_received   TEXT,
    resubmitted         TEXT,
    completed           TEXT
);
CREATE INDEX IF NOT EXISTS deliverables_project ON deliverables(project_number);

CREATE TABLE IF NOT EXISTS deliverable_shares (
    deliverable_row INTEGER NOT NULL,
    engineer        TEXT NOT NULL,
    share           REAL NOT NULL,
    PRIMARY KEY (deliverable_row, engineer)
);

-- Reference tables: what a type of work is worth, and how it is credited.
CREATE TABLE IF NOT EXISTS project_types (
    code             TEXT PRIMARY KEY,
    name             TEXT NOT NULL DEFAULT '',
    basis            TEXT NOT NULL DEFAULT '',
    trigger_event    TEXT NOT NULL DEFAULT '',
    portfolio_weight REAL,
    include_in_cpi   TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    position         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS credit_steps (
    type_code   TEXT NOT NULL,
    step_no     INTEGER NOT NULL,
    step_name   TEXT NOT NULL DEFAULT '',
    credit      REAL NOT NULL DEFAULT 0,
    data_source TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (type_code, step_no)
);

CREATE TABLE IF NOT EXISTS scorecard_factors (
    position  INTEGER PRIMARY KEY,
    key       TEXT,
    factor    TEXT NOT NULL,
    weight    REAL NOT NULL DEFAULT 0,
    direction TEXT NOT NULL DEFAULT 'higher',
    target    REAL,
    how       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS definitions (
    position INTEGER PRIMARY KEY,
    field    TEXT NOT NULL,
    means    TEXT NOT NULL DEFAULT '',
    how      TEXT NOT NULL DEFAULT ''
);

-- Charge codes that are not projects: holidays, leave and the like.
CREATE TABLE IF NOT EXISTS non_project_codes (
    code     TEXT PRIMARY KEY,
    meaning  TEXT NOT NULL DEFAULT '',
    treat_as TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0
);

-- Days off the unit typed in itself, on top of the built-in public holidays.
CREATE TABLE IF NOT EXISTS holidays (
    day  TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT ''
);

-- The task list: the plan beside the timesheets, never part of the figures.
CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY,
    position         INTEGER NOT NULL DEFAULT 0,
    name             TEXT NOT NULL DEFAULT '',
    definition       TEXT NOT NULL DEFAULT '',
    project_number   TEXT NOT NULL DEFAULT '',
    deliverable_row  INTEGER,
    deliverable_name TEXT NOT NULL DEFAULT '',
    assignees        TEXT NOT NULL DEFAULT '[]',
    required_hours   REAL,
    actual_hours     REAL,
    start            TEXT,
    due              TEXT,
    status           TEXT NOT NULL DEFAULT '',
    kind             TEXT NOT NULL DEFAULT '',
    series           TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    progress_mode    TEXT NOT NULL DEFAULT '',
    stage            TEXT NOT NULL DEFAULT '',
    review_code      TEXT NOT NULL DEFAULT '',
    revisions        INTEGER NOT NULL DEFAULT 0,
    pro_rata         REAL
);

-- Planned man-months typed in for a project and a quarter, instead of the
-- straight-line spread of its budget.
CREATE TABLE IF NOT EXISTS phasing (
    project_number TEXT NOT NULL,
    quarter_start  TEXT NOT NULL,
    mm             REAL NOT NULL,
    PRIMARY KEY (project_number, quarter_start)
);
"""

#: Settings this module keeps in the store's ``settings`` table.
_PREFIX = "unit."
_MODEL = _PREFIX + "model"
_REVISION = REVISION_KEY

#: Cached values worked out from the timesheet rows and nothing else.
ROW_KEYS = frozenset({"rows", "index", "leave"})

#: How many years either side of the plan year a new unit has availability for.
YEARS_EITHER_SIDE = 2

#: How long a short name may be.
MAX_SHORT_NAME = 60


def defaults_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "defaults.json"


def load_defaults() -> Dict[str, Any]:
    with open(defaults_path(), encoding="utf-8") as handle:
        return json.load(handle)


class Unit:
    """Read and change one unit."""

    def __init__(self, path: Union[str, Path], *, seed: bool = True):
        self.path = Path(path)
        #: The timesheet rows and everything else the planner keeps, in the
        #: same file.  Making it first makes the file and its settings table.
        self.store = TimesheetStore(self.path)
        self._cache: Dict[str, Any] = {}
        #: What is read from the timesheet rows alone (``ROW_KEYS``), kept
        #: through writes to anything else.
        self._row_cache: Dict[str, Any] = {}
        self._revision: Any = None
        with self._connect() as db:
            db.executescript(SCHEMA)
        # What the store reads is kept with the rest, and forgotten with it.
        self.store.memo = self._cached
        self.store.changed = self.reload
        if seed and not self.is_set_up():
            self.seed(load_defaults())
        self._revision = self._read_revision()

    # -- plumbing --------------------------------------------------------
    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA busy_timeout = 15000")
        wrote = False
        try:
            yield db
            wrote = note_change(db)
            db.commit()
        finally:
            db.close()
        if wrote:
            self.reload()

    @contextmanager
    def _write(self):
        """A change, committed whole or not at all, that other readers notice.

        Any write through ``_connect`` bumps the revision (``note_change``);
        this is the name the writers use.
        """
        with self._connect() as db:
            yield db

    def _read_revision(self) -> Tuple[Any, str, str]:
        """Which version of the file this is: the file itself, its count of
        writes, and its count of writes to the timesheet rows.  A copy put
        back in place is a different file even when it happens to carry the
        same counts."""
        with self._connect() as db:
            counts = dict(db.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?)",
                (_REVISION, ROWS_REVISION_KEY)).fetchall())
        return (_identity(self.path), counts.get(_REVISION, "0"),
                counts.get(ROWS_REVISION_KEY, "0"))

    @property
    def revision(self) -> Tuple[Any, str, str]:
        """The version of the unit everything cached was read from."""
        return self._revision

    def _forget(self, current) -> None:
        """Drop what was read before ``current``; the rows only if they changed."""
        before = self._revision
        self._cache.clear()
        if (before is None or current[0] != before[0]
                or current[2] != before[2]):
            self._row_cache.clear()
        self._revision = current

    def _cached(self, key: Any, build):
        """``build()``, kept until the unit is next written.

        What comes from the timesheet rows alone (``ROW_KEYS``) is kept until
        the rows are next written.  Anything built while a write happened --
        here or seen from another worker -- is handed back but not kept, so
        nothing older than the last write is ever served.
        """
        name = key[0] if isinstance(key, tuple) else key
        cache = self._row_cache if name in ROW_KEYS else self._cache
        try:
            return cache[key]
        except KeyError:
            pass
        before = self._revision
        value = build()
        if self._revision == before:
            cache[key] = value
        return value

    def _setting(self, key: str, default: Any = None) -> Any:
        return self._settings().get(_PREFIX + key, default)

    def _settings(self) -> Dict[str, str]:
        return self._cached("settings", self.store.settings)

    def _set_setting(self, db: sqlite3.Connection, key: str, value: Any) -> None:
        if value is None:
            db.execute("DELETE FROM settings WHERE key = ?", (_PREFIX + key,))
        else:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (_PREFIX + key, str(value)))

    @property
    def dirty(self) -> bool:
        """Never: every change is written as it is made."""
        return False

    def save(self, *, backup: bool = True) -> Dict[str, Any]:
        return {"saved": True, "backup": None, "path": str(self.path)}

    def reload(self) -> None:
        self._forget(self._read_revision())

    def refresh(self) -> bool:
        """Forget what was read if another worker has written since."""
        current = self._read_revision()
        if current != self._revision:
            self._forget(current)
            return True
        return False

    def is_set_up(self) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM settings WHERE key = ?",
                              (_MODEL,)).fetchone() is not None

    # -- setting a unit up -------------------------------------------------
    def seed(self, data: Dict[str, Any]) -> None:
        """Fill the reference tables and settings, as a new unit starts.

        ``data`` is shaped like ``data/defaults.json``; ``legacy`` hands over
        what an old workbook held in the same shape.
        """
        with self._write() as db:
            for key in ("hours_per_man_month", "hours_per_day", "plan_year",
                        "as_at"):
                if data.get(key) is not None:
                    self._set_setting(db, key, data[key])
            if data.get("availability_years"):
                self._set_setting(db, "availability_years",
                                  json.dumps(sorted(int(y) for y in
                                                    data["availability_years"])))
            if data.get("task_settings"):
                self._set_setting(db, "task_settings",
                                  json.dumps(data["task_settings"]))
            self._replace_project_types(db, data.get("project_types") or [])
            self._replace_credit_steps(db, data.get("credit_steps") or [])
            self._replace_scorecard(db, data.get("scorecard_factors") or [])
            db.execute("DELETE FROM definitions")
            for position, item in enumerate(data.get("definitions") or []):
                db.execute(
                    "INSERT INTO definitions (position, field, means, how) "
                    "VALUES (?, ?, ?, ?)",
                    (position, as_text(item.get("field")),
                     as_text(item.get("means")), as_text(item.get("how"))))
            db.execute("DELETE FROM non_project_codes")
            for position, item in enumerate(data.get("non_project_codes") or []):
                db.execute(
                    "INSERT OR REPLACE INTO non_project_codes "
                    "(code, meaning, treat_as, position) VALUES (?, ?, ?, ?)",
                    (as_text(item.get("code")), as_text(item.get("meaning")),
                     as_text(item.get("treat_as")), position))
            for item in data.get("holidays") or []:
                day = as_date(item.get("day") if isinstance(item, dict) else item)
                if day:
                    db.execute("INSERT OR REPLACE INTO holidays (day, name) "
                               "VALUES (?, ?)",
                               (day.isoformat(),
                                as_text(item.get("name"))
                                if isinstance(item, dict) else ""))
            self._set_setting(db, "model", "1")

    # -- settings ----------------------------------------------------------
    def hours_per_man_month(self) -> float:
        value = as_number(self._setting("hours_per_man_month"))
        return value or 185.0

    def hours_per_day(self) -> float:
        value = as_number(self._setting("hours_per_day"))
        return value or 8.5

    def plan_year(self) -> int:
        value = as_number(self._setting("plan_year"))
        return int(value) if value else _dt.date.today().year

    def as_at(self) -> Optional[_dt.date]:
        """The date the reports are frozen at, if somebody froze them."""
        return stored_date(self._setting("as_at"))

    def availability_years(self) -> List[int]:
        """The years each person's availability is kept for."""
        def build() -> List[int]:
            stored = self._setting("availability_years")
            years = set()
            if stored:
                try:
                    years = {int(y) for y in json.loads(stored)}
                except (TypeError, ValueError):
                    years = set()
            if not years:
                plan = self.plan_year()
                years = set(range(plan - YEARS_EITHER_SIDE,
                                  plan + YEARS_EITHER_SIDE + 1))
            with self._connect() as db:
                years |= {row["year"] for row in db.execute(
                    "SELECT DISTINCT year FROM availability")}
            return sorted(years)
        return list(self._cached("availability_years", build))

    def _availability_years(self) -> Dict[str, int]:
        """The old shape (column -> year), for callers that still use it."""
        return OrderedDict((str(year), year) for year in self.availability_years())

    def save_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Change the unit's own numbers: hours per man-month, plan year..."""
        errors: List[str] = []
        changes: Dict[str, Any] = {}
        if "hours_per_man_month" in data:
            value = as_number(data["hours_per_man_month"])
            if value is None or value <= 0:
                errors.append("Hours per man-month must be more than zero.")
            changes["hours_per_man_month"] = value
        if "hours_per_day" in data:
            value = as_number(data["hours_per_day"])
            if value is None or not 0 < value <= 24:
                errors.append("Hours per day must be between 0 and 24.")
            changes["hours_per_day"] = value
        if "plan_year" in data:
            value = as_number(data["plan_year"])
            if value is None or not 2000 <= value <= 2100:
                errors.append("The plan year must be a year.")
            changes["plan_year"] = int(value) if value else None
        if "as_at" in data:
            raw = data["as_at"]
            value = as_date(raw)
            if raw and value is None:
                errors.append("The report date is not a date.")
            changes["as_at"] = value.isoformat() if value else None
        if "availability_years" in data:
            try:
                years = sorted({int(y) for y in data["availability_years"] or []})
            except (TypeError, ValueError):
                years = []
                errors.append("Availability years must be years.")
            changes["availability_years"] = json.dumps(years) if years else None
        if errors:
            raise ValidationError(errors)
        with self._write() as db:
            for key, value in changes.items():
                self._set_setting(db, key, value)
        return {key: self._setting(key) for key in changes}

    # -- the team ----------------------------------------------------------
    def engineers(self) -> List[Engineer]:
        return self._cached("engineers", self._read_engineers)

    def _read_engineers(self) -> List[Engineer]:
        with self._connect() as db:
            people = db.execute(
                "SELECT * FROM engineers ORDER BY position, name").fetchall()
            shares: Dict[str, Dict[int, float]] = {}
            for row in db.execute("SELECT * FROM availability ORDER BY year"):
                shares.setdefault(row["engineer"], {})[row["year"]] = row["share"]
        return [Engineer(
            short_name=row["name"],
            pattern=row["pattern"] or f"*{row['name']}*",
            available_hours=row["available_hours"],
            availability=dict(shares.get(row["name"], {})),
            slot=index,
        ) for index, row in enumerate(people)]

    def engineer_names(self) -> List[str]:
        return [e.short_name for e in self.engineers()]

    def ts_sheets(self) -> "OrderedDict[str, str]":
        """Everybody on the team, keyed to themselves.

        A unit once had a sheet per person and code still asks for the map
        from person to sheet when it wants the team in order; there are no
        sheets any more, so each person stands for their own.
        """
        return OrderedDict((name, name) for name in self.engineer_names())

    def rows_per_engineer(self) -> Dict[str, int]:
        with self._connect() as db:
            return {row["person"]: row["n"] for row in db.execute(
                "SELECT person, COUNT(*) AS n FROM rows WHERE day IS NOT NULL "
                "GROUP BY person")}

    def team(self) -> List[Dict[str, Any]]:
        """The engineers, with how many timesheet rows each of them has."""
        rows = self.rows_per_engineer()
        out = []
        for person in self.engineers():
            record = person.to_dict()
            record["rows"] = rows.get(person.short_name, 0)
            out.append(record)
        return out

    def _validate_engineer(self, name: Any, data: Dict[str, Any], *,
                           existing: Optional[str] = None) -> Dict[str, Any]:
        errors: List[str] = []
        name = " ".join(as_text(name).split())
        if not name:
            errors.append("The engineer needs a short name.")
        if "/" in name:
            # It goes into the address the app reaches the engineer by.
            errors.append("A short name cannot contain a slash (/).")
        if len(name) > MAX_SHORT_NAME:
            errors.append(f"Keep the short name under {MAX_SHORT_NAME} characters.")
        taken = {e.short_name.lower() for e in self.engineers()} - (
            {existing.lower()} if existing else set())
        if name and name.lower() in taken:
            errors.append(f"There is already an engineer called {name!r}.")

        hours = as_number(data.get("available_hours"))
        if hours is not None and hours <= 0:
            errors.append("Available hours per month must be greater than zero.")

        availability: Dict[int, float] = {}
        for year, value in (data.get("availability") or {}).items():
            share = as_fraction(value)
            if share is None:
                continue
            try:
                year = int(year)
            except (TypeError, ValueError):
                errors.append(f"{year!r} is not a year.")
                continue
            if not 0 <= share <= 2:
                errors.append(f"Availability for {year} must be between 0% and 200%.")
            availability[year] = share
        if errors:
            raise ValidationError(errors)
        return {
            "name": name,
            "pattern": as_text(data.get("pattern")) or f"*{name}*",
            "available_hours": hours,
            "availability": availability,
        }

    def add_engineer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add somebody to the team.  There is no limit to how many."""
        values = self._validate_engineer(data.get("short_name", ""), data)
        with self._write() as db:
            position = db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM engineers"
            ).fetchone()["n"]
            db.execute(
                "INSERT INTO engineers (name, pattern, available_hours, position) "
                "VALUES (?, ?, ?, ?)",
                (values["name"], values["pattern"], values["available_hours"],
                 position))
            self._write_availability(db, values["name"], values["availability"])
        return {"engineer": values["name"], "slot": position, "sheet": ""}

    def add_engineers(self, people: Sequence[Dict[str, Any]]) -> List[str]:
        """Add several people in one go, as a timesheet import does."""
        checked = []
        names = {name.lower() for name in self.engineer_names()}
        for data in people:
            if " ".join(as_text(data.get("short_name")).split()).lower() in names:
                continue                   # already on the team
            values = self._validate_engineer(data.get("short_name", ""), data)
            names.add(values["name"].lower())
            checked.append(values)
        with self._write() as db:
            position = db.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM engineers"
            ).fetchone()["n"]
            for offset, values in enumerate(checked):
                db.execute(
                    "INSERT INTO engineers (name, pattern, available_hours, "
                    "position) VALUES (?, ?, ?, ?)",
                    (values["name"], values["pattern"], values["available_hours"],
                     position + offset))
                self._write_availability(db, values["name"], values["availability"])
        return [values["name"] for values in checked]

    def _write_availability(self, db: sqlite3.Connection, name: str,
                            availability: Dict[int, float]) -> None:
        db.execute("DELETE FROM availability WHERE engineer = ?", (name,))
        for year, share in availability.items():
            db.execute("INSERT INTO availability (engineer, year, share) "
                       "VALUES (?, ?, ?)", (name, int(year), float(share)))

    def _require_engineer(self, engineer: str) -> Engineer:
        for person in self.engineers():
            if person.short_name == engineer:
                return person
        raise ValidationError([
            f"{engineer!r} is not on this unit's team "
            f"({', '.join(self.engineer_names()) or 'nobody yet'})."
        ])

    def update_engineer(self, engineer: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Rename somebody, or change their hours and availability.

        A new name follows them everywhere: their splits, their tasks, their
        timesheet rows, their team and their time away.
        """
        self._require_engineer(engineer)
        values = self._validate_engineer(
            data.get("short_name", engineer), data, existing=engineer)
        new = values["name"]
        renamed = new != engineer
        if renamed:
            tasks = self.read_tasks()
        with self._write() as db:
            db.execute(
                "UPDATE engineers SET name = ?, pattern = ?, available_hours = ? "
                "WHERE name = ?",
                (new, values["pattern"], values["available_hours"], engineer))
            if renamed:
                db.execute("DELETE FROM availability WHERE engineer = ?", (engineer,))
                for table in ("project_shares", "deliverable_shares"):
                    db.execute(f"UPDATE {table} SET engineer = ? WHERE engineer = ?",
                               (new, engineer))
                for task in tasks:
                    if engineer in task.assignees:
                        task.assignees = list(dict.fromkeys(
                            new if name == engineer else name
                            for name in task.assignees))
                        db.execute("UPDATE tasks SET assignees = ? WHERE id = ?",
                                   (json.dumps(task.assignees), task.id))
            self._write_availability(db, new, values["availability"])
        if renamed:
            self.store.rename_person_everywhere(engineer, new)
            with self._connect() as db:
                db.execute("UPDATE slots SET person = ? WHERE person = ?",
                           (new, engineer))
        return {"engineer": new, "renamed": renamed}

    def remove_engineer(self, engineer: str) -> Dict[str, Any]:
        """Take somebody off the team, and out of every split.

        Their timesheet rows stay: the hours were spent, and still count
        toward the projects they were booked to.
        """
        self._require_engineer(engineer)
        if len(self.engineers()) <= 1:
            raise ValidationError([
                "A unit needs at least one engineer; add their replacement first."
            ])
        cleared = sum(1 for d in self.deliverables() if d.shares.get(engineer))
        with self._write() as db:
            db.execute("DELETE FROM engineers WHERE name = ?", (engineer,))
            for table in ("availability",):
                db.execute(f"DELETE FROM {table} WHERE engineer = ?", (engineer,))
            for table in ("project_shares", "deliverable_shares"):
                db.execute(f"DELETE FROM {table} WHERE engineer = ?", (engineer,))
        return {"engineer": engineer, "deliverables_cleared": cleared,
                "sheet_removed": None}

    # -- reference tables --------------------------------------------------
    def project_types(self) -> List[ProjectType]:
        def build() -> List[ProjectType]:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM project_types ORDER BY position, code").fetchall()
            return [ProjectType(
                code=row["code"], name=row["name"], basis=row["basis"],
                trigger=row["trigger_event"],
                portfolio_weight=row["portfolio_weight"],
                include_in_cpi=row["include_in_cpi"], notes=row["notes"],
            ) for row in rows]
        return self._cached("project_types", build)

    def credit_steps(self) -> List[CreditStep]:
        def build() -> List[CreditStep]:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM credit_steps ORDER BY position, type_code, "
                    "step_no").fetchall()
            return [CreditStep(
                type_code=row["type_code"], step_no=int(row["step_no"]),
                step_name=row["step_name"], credit=row["credit"] or 0.0,
                data_source=row["data_source"],
            ) for row in rows]
        return self._cached("credit_steps", build)

    def credit_for(self, type_code: str, step_no: Optional[int]) -> Optional[float]:
        if not type_code or step_no is None:
            return None
        lookup = self._cached(
            "credit_lookup",
            lambda: {(s.type_code, s.step_no): s.credit for s in self.credit_steps()},
        )
        return lookup.get((type_code, step_no))

    def non_project_codes(self) -> Dict[str, str]:
        """Charge code -> how a day booked to it is treated."""
        def build() -> Dict[str, str]:
            with self._connect() as db:
                return OrderedDict((row["code"], row["treat_as"]) for row in db.execute(
                    "SELECT code, treat_as FROM non_project_codes "
                    "ORDER BY position, code"))
        return self._cached("non_project_codes", build)

    def holidays(self) -> List[_dt.date]:
        """Days off the unit typed in itself."""
        def build() -> List[_dt.date]:
            with self._connect() as db:
                days = [stored_date(row["day"]) for row in db.execute(
                    "SELECT day FROM holidays ORDER BY day")]
            return [d for d in days if d]
        return list(self._cached("holidays", build))

    def scorecard_factors(self) -> List[Dict[str, Any]]:
        def build() -> List[Dict[str, Any]]:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM scorecard_factors ORDER BY position").fetchall()
            return [{
                "factor": row["factor"],
                "key": row["key"],
                "weight": row["weight"] or 0.0,
                "direction": "higher" if row["direction"] == "higher" else "target",
                "direction_label": (cfg.SCORECARD_DIRECTION_HIGHER
                                    if row["direction"] == "higher"
                                    else cfg.SCORECARD_DIRECTION_TARGET),
                "target": row["target"],
                "how": row["how"],
                "row": row["position"] + 1,
            } for row in rows]
        return [dict(f) for f in self._cached("scorecard_factors", build)]

    def save_scorecard_factors(self, factors: Sequence[Dict[str, Any]]
                               ) -> Dict[str, Any]:
        """Rewrite the scorecard factors, weights, directions and targets."""
        errors: List[str] = []
        items = list(factors)
        measures = len(cfg.SCORECARD_KEYS)
        if len(items) > measures:
            errors.append(
                f"The scorecard weighs {measures} measures, so it takes "
                f"{measures} factors, not {len(items)}.")
        total = 0.0
        for position, item in enumerate(items, start=1):
            if not as_text(item.get("factor")):
                errors.append(f"Factor {position} has no name.")
            weight = as_fraction(item.get("weight"))
            if weight is None:
                errors.append(f"Factor {position} has no weight.")
            elif not 0 <= weight <= 1:
                errors.append(f"Factor {position}: weight must be between 0% and 100%.")
            else:
                total += weight
            direction = as_text(item.get("direction")).lower()
            if direction not in {"higher", "target"}:
                errors.append(
                    f"Factor {position}: scoring must be 'higher' or 'target'.")
            if direction == "target":
                target = as_number(item.get("target"))
                if target is None or target == 0:
                    errors.append(
                        f"Factor {position} is scored against a target, so it "
                        f"needs one that is not zero.")
        if items and abs(total - 1.0) > 1e-4:
            errors.append(
                f"The weights total {total * 100:.1f}%, not 100%. A ranking whose "
                f"weights do not add up cannot be read against another period."
            )
        if errors:
            raise ValidationError(errors)
        current = {f["row"] - 1: f for f in self.scorecard_factors()}
        rows = []
        for offset, item in enumerate(items):
            direction = as_text(item.get("direction")).lower()
            rows.append({
                "key": cfg.SCORECARD_KEYS[offset],
                "factor": as_text(item.get("factor")),
                "weight": as_fraction(item.get("weight")),
                "direction": direction,
                "target": as_number(item.get("target")) if direction == "target"
                else None,
                "how": (as_text(item.get("how")) if item.get("how")
                        else (current.get(offset) or {}).get("how", "")),
            })
        with self._write() as db:
            self._replace_scorecard(db, rows)
        return {"factors": len(items)}

    def _replace_scorecard(self, db: sqlite3.Connection,
                           rows: Sequence[Dict[str, Any]]) -> None:
        db.execute("DELETE FROM scorecard_factors")
        for position, item in enumerate(rows):
            direction = as_text(item.get("direction")).lower()
            db.execute(
                "INSERT INTO scorecard_factors (position, key, factor, weight, "
                "direction, target, how) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (position,
                 item.get("key") or (cfg.SCORECARD_KEYS[position]
                                     if position < len(cfg.SCORECARD_KEYS) else None),
                 as_text(item.get("factor")), as_fraction(item.get("weight")) or 0.0,
                 "higher" if direction == "higher" else "target",
                 as_number(item.get("target")), as_text(item.get("how"))))

    def definitions(self) -> List[Dict[str, str]]:
        def build() -> List[Dict[str, str]]:
            with self._connect() as db:
                return [{"field": row["field"], "means": row["means"],
                         "how": row["how"]} for row in db.execute(
                    "SELECT * FROM definitions ORDER BY position")]
        return [dict(d) for d in self._cached("definitions", build)]

    def save_reference(self, project_types: Optional[Sequence[Dict[str, Any]]],
                       credit_steps: Optional[Sequence[Dict[str, Any]]]
                       ) -> Dict[str, Any]:
        """Rewrite the project types and rules of credit.  Any number of each."""
        errors: List[str] = []
        types = list(project_types or [])
        steps = list(credit_steps or [])

        codes: List[str] = []
        for position, item in enumerate(types, start=1):
            code = as_text(item.get("code"))
            if not code:
                errors.append(f"Project type {position} has no type code.")
            elif code in codes:
                errors.append(f"Type code {code!r} appears more than once.")
            else:
                codes.append(code)
            weight = as_number(item.get("portfolio_weight"))
            if weight is not None and weight < 0:
                errors.append(f"{code or position}: portfolio weight cannot be negative.")

        seen: set = set()
        for position, item in enumerate(steps, start=1):
            code = as_text(item.get("type_code"))
            step_raw = as_number(item.get("step_no"))
            if not code:
                errors.append(f"Credit step {position} has no type code.")
            elif codes and code not in codes:
                errors.append(
                    f"Credit step {position} is for type {code!r}, which is not "
                    f"in Project Types.")
            if step_raw is None:
                errors.append(f"Credit step {position} has no step number.")
            else:
                key = (code, int(step_raw))
                if key in seen:
                    errors.append(f"{code} step {int(step_raw)} appears twice.")
                seen.add(key)
            credit = as_fraction(item.get("credit"))
            if credit is None:
                errors.append(f"Credit step {position} has no credit percentage.")
            elif not 0 <= credit <= 1:
                errors.append(
                    f"{code} step {position}: credit must be between 0% and 100%.")
        if errors:
            raise ValidationError(errors)

        with self._write() as db:
            self._replace_project_types(db, types)
            self._replace_credit_steps(db, steps)
        return {"project_types": len(types), "credit_steps": len(steps)}

    def _replace_project_types(self, db: sqlite3.Connection,
                               types: Sequence[Dict[str, Any]]) -> None:
        db.execute("DELETE FROM project_types")
        for position, item in enumerate(types):
            db.execute(
                "INSERT INTO project_types (code, name, basis, trigger_event, "
                "portfolio_weight, include_in_cpi, notes, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (as_text(item.get("code")), as_text(item.get("name")),
                 as_text(item.get("basis")), as_text(item.get("trigger")),
                 as_number(item.get("portfolio_weight")),
                 as_text(item.get("include_in_cpi")), as_text(item.get("notes")),
                 position))

    def _replace_credit_steps(self, db: sqlite3.Connection,
                              steps: Sequence[Dict[str, Any]]) -> None:
        db.execute("DELETE FROM credit_steps")
        for position, item in enumerate(steps):
            step_raw = as_number(item.get("step_no"))
            db.execute(
                "INSERT INTO credit_steps (type_code, step_no, step_name, credit, "
                "data_source, position) VALUES (?, ?, ?, ?, ?, ?)",
                (as_text(item.get("type_code")), int(step_raw or 0),
                 as_text(item.get("step_name")),
                 as_fraction(item.get("credit")) or 0.0,
                 as_text(item.get("data_source")), position))

    def reference(self) -> Dict[str, Any]:
        """Everything the screens need for their dropdowns and hints."""
        steps: Dict[str, List[Dict[str, Any]]] = {}
        for step in self.credit_steps():
            steps.setdefault(step.type_code, []).append({
                "step_no": step.step_no,
                "step_name": step.step_name,
                "credit": step.credit,
                "data_source": step.data_source,
            })
        return {
            "project_types": [dict(t.__dict__) for t in self.project_types()],
            "credit_steps": steps,
            "statuses": cfg.PROJECT_STATUSES,
            "scorecard_factors": self.scorecard_factors(),
            "definitions": self.definitions(),
            "engineers": [
                {
                    "short_name": e.short_name,
                    "pattern": e.pattern,
                    "available_hours": e.available_hours,
                    "availability": e.availability,
                }
                for e in self.engineers()
            ],
            "hours_per_man_month": self.hours_per_man_month(),
            "hours_per_day": self.hours_per_day(),
            "plan_year": self.plan_year(),
            "non_project_codes": self.non_project_codes(),
        }

    # -- splits ------------------------------------------------------------
    def _validate_shares(self, data: Dict[str, Any], label: str,
                         errors: List[str]) -> Dict[str, Optional[float]]:
        """Coerce a submitted split and check it adds up.

        Accepts ``{"shares": {...}}`` or a flat ``share_<name>`` per engineer,
        so the same payload shape works whoever the team happens to be.
        """
        raw = data.get("shares") if isinstance(data.get("shares"), dict) else {}
        names = self.engineer_names()
        unknown = [name for name, value in raw.items()
                   if name not in names and as_fraction(value)]
        if unknown:
            errors.append(f"{', '.join(unknown)} {'is' if len(unknown) == 1 else 'are'} "
                          f"not on this unit's team.")
        out: Dict[str, Optional[float]] = {}
        for name in names:
            value = raw.get(name)
            if value is None:
                value = data.get(f"share_{name.lower()}")
            share = as_fraction(value)
            if share is not None and not 0 <= share <= 1:
                errors.append(f"{name}'s share must be between 0% and 100%.")
            out[name] = share
        total = sum(v for v in out.values() if v)
        if total and abs(total - 1.0) > 1e-4:
            errors.append(
                f"{label} must total 100% across the people sharing it "
                f"(it totals {total * 100:.1f}%)."
            )
        return out

    def _shares_by(self, db: sqlite3.Connection, table: str, key: str
                   ) -> Dict[int, Dict[str, float]]:
        out: Dict[int, Dict[str, float]] = {}
        for row in db.execute(f"SELECT {key} AS k, engineer, share FROM {table}"):
            out.setdefault(row["k"], {})[row["engineer"]] = row["share"]
        return out

    def _full_split(self, stored: Dict[str, float]) -> Dict[str, Optional[float]]:
        """Every engineer in the split, with ``None`` for anybody not in it."""
        return {name: stored.get(name) for name in self.engineer_names()}

    @staticmethod
    def _write_shares(db: sqlite3.Connection, table: str, key: str, row: int,
                      shares: Dict[str, Optional[float]]) -> None:
        db.execute(f"DELETE FROM {table} WHERE {key} = ?", (row,))
        for name, share in shares.items():
            if share is not None:
                db.execute(f"INSERT INTO {table} ({key}, engineer, share) "
                           f"VALUES (?, ?, ?)", (row, name, float(share)))

    # -- projects ----------------------------------------------------------
    def projects(self) -> List[Project]:
        return self._cached("projects", self._read_projects)

    def _read_projects(self) -> List[Project]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM projects ORDER BY row").fetchall()
            shares = self._shares_by(db, "project_shares", "project_row")
        return [Project(
            row=row["row"],
            number=row["number"],
            name=row["name"],
            budget_mm=row["budget_mm"],
            start=stored_date(row["start"]),
            end=stored_date(row["end"]),
            status=row["status"],
            cac_override=row["cac_override"],
            notes=row["notes"],
            manual_percent=row["manual_percent"],
            manual_shares=self._full_split(shares.get(row["row"], {})),
        ) for row in rows]

    def project(self, number: str) -> Optional[Project]:
        wanted = as_text(number)
        for project in self.projects():
            if project.number == wanted:
                return project
        return None

    def validate_project(self, data: Dict[str, Any], *, row: Optional[int] = None
                         ) -> Tuple[Project, List[str]]:
        """Coerce a submitted project and check it against the register's rules."""
        errors: List[str] = []
        number = as_text(data.get("number"))
        if not number:
            errors.append("Project number is required.")
        if "/" in number:
            errors.append("A project number cannot contain a slash (/).")
        for other in self.projects():
            if other.number == number and other.row != row:
                errors.append(f"Project number {number!r} is already in the register.")
                break

        name = as_text(data.get("name"))
        if not name:
            errors.append("Project name is required.")

        budget = as_number(data.get("budget_mm"))
        if budget is None:
            errors.append("Budget (MM) is required.")
        elif budget <= 0:
            errors.append("Budget (MM) must be greater than zero.")

        start = as_date(data.get("start"))
        end = as_date(data.get("end"))
        if data.get("start") and start is None:
            errors.append("Start date is not a date the app recognises.")
        if data.get("end") and end is None:
            errors.append("End date is not a date the app recognises.")
        if start and end and end < start:
            errors.append("End date falls before the start date.")

        status = as_text(data.get("status")) or "Not Started"
        if status not in cfg.PROJECT_STATUSES:
            errors.append(
                f"Status must be one of: {', '.join(cfg.PROJECT_STATUSES)}."
            )

        manual_percent = as_fraction(data.get("manual_percent"))
        if manual_percent is not None and not 0 <= manual_percent <= 1:
            errors.append("Manual % complete must be between 0% and 100%.")

        manual = dict(data)
        if isinstance(data.get("manual_shares"), dict):
            manual["shares"] = data["manual_shares"]
        else:
            manual["shares"] = {
                name: data.get(f"manual_share_{name.lower()}")
                for name in self.engineer_names()
            }
        shares = self._validate_shares(
            manual,
            "The fallback split (used only while the deliverables carry none)",
            errors,
        )

        project = Project(
            row=row or 0,
            number=number,
            name=name,
            budget_mm=budget,
            start=start,
            end=end,
            status=status,
            cac_override=as_number(data.get("cac_override")),
            notes=as_text(data.get("notes")),
            manual_percent=manual_percent,
            manual_shares=shares,
        )
        return project, errors

    def _write_project(self, db: sqlite3.Connection, project: Project) -> int:
        values = (project.number, project.name, project.budget_mm,
                  iso(project.start), iso(project.end), project.status,
                  project.cac_override, project.notes, project.manual_percent)
        if project.row:
            db.execute(
                "UPDATE projects SET number = ?, name = ?, budget_mm = ?, "
                "start = ?, end = ?, status = ?, cac_override = ?, notes = ?, "
                "manual_percent = ? WHERE row = ?", values + (project.row,))
        else:
            project.row = db.execute(
                "INSERT INTO projects (number, name, budget_mm, start, end, "
                "status, cac_override, notes, manual_percent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values).lastrowid
        self._write_shares(db, "project_shares", "project_row", project.row,
                           project.manual_shares)
        return project.row

    def add_project(self, data: Dict[str, Any]) -> Project:
        project, errors = self.validate_project(data)
        if errors:
            raise ValidationError(errors)
        project.row = 0
        with self._write() as db:
            self._write_project(db, project)
        return project

    def update_project(self, number: str, data: Dict[str, Any]) -> Project:
        existing = self.project(number)
        if existing is None:
            raise ValidationError([f"No project numbered {number!r} in the register."])
        project, errors = self.validate_project(data, row=existing.row)
        if errors:
            raise ValidationError(errors)
        project.row = existing.row
        with self._write() as db:
            self._write_project(db, project)
            if project.number != existing.number:
                self._renumber(db, existing.number, project.number)
        return project

    @staticmethod
    def _renumber(db: sqlite3.Connection, old: str, new: str) -> None:
        """A project's new number, wherever the old one was written down."""
        for table, column in (("deliverables", "project_number"),
                              ("tasks", "project_number"),
                              ("phasing", "project_number"),
                              ("drawings", "project_number"),
                              ("drawing_list", "project_number"),
                              ("planned_work", "job_number"),
                              ("plan_moves", "project")):
            db.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                       (new, old))

    def delete_project(self, number: str, *, cascade: bool = False) -> Dict[str, Any]:
        existing = self.project(number)
        if existing is None:
            raise ValidationError([f"No project numbered {number!r} in the register."])
        attached = [d for d in self.deliverables() if d.project_number == existing.number]
        if attached and not cascade:
            raise ValidationError([
                f"{len(attached)} deliverable(s) still point at {existing.number}. "
                "Remove them first, or confirm removing them along with the project."
            ])
        with self._write() as db:
            for deliverable in attached:
                self._delete_deliverable(db, deliverable.row)
            db.execute("DELETE FROM project_shares WHERE project_row = ?",
                       (existing.row,))
            db.execute("DELETE FROM phasing WHERE project_number = ?",
                       (existing.number,))
            db.execute("DELETE FROM projects WHERE row = ?", (existing.row,))
        return {"row": existing.row, "deliverables_removed": len(attached)}

    # -- deliverables ------------------------------------------------------
    def deliverables(self) -> List[Deliverable]:
        return self._cached("deliverables", self._read_deliverables)

    def _read_deliverables(self) -> List[Deliverable]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM deliverables ORDER BY row").fetchall()
            shares = self._shares_by(db, "deliverable_shares", "deliverable_row")
        out: List[Deliverable] = []
        for row in rows:
            deliverable = Deliverable(
                row=row["row"],
                project_number=row["project_number"],
                name=row["name"],
                type_code=row["type_code"],
                phase_weight=row["phase_weight"],
                step_no=row["step_no"],
                status_date=stored_date(row["status_date"]),
                shares=self._full_split(shares.get(row["row"], {})),
                notes=row["notes"],
                ts_phase=row["ts_phase"],
            )
            for name in cfg.ACTUALS_DATE_FIELDS:
                setattr(deliverable, name, stored_date(row[name]))
            out.append(deliverable)
        return out

    def deliverable(self, row: int) -> Optional[Deliverable]:
        for item in self.deliverables():
            if item.row == row:
                return item
        return None

    def validate_deliverable(self, data: Dict[str, Any], *,
                             row: Optional[int] = None,
                             pending_project: Optional[str] = None
                             ) -> Tuple[Deliverable, List[str]]:
        """Check a deliverable.

        ``pending_project`` names a project being created in the same call, so
        its deliverables are not rejected for belonging to a project that is
        not in the register yet.
        """
        errors: List[str] = []
        project_number = as_text(data.get("project_number"))
        if not project_number:
            errors.append("Pick the project this deliverable belongs to.")
        elif project_number != pending_project and self.project(project_number) is None:
            errors.append(
                f"{project_number!r} is not in the project register; add the "
                "project first."
            )

        name = as_text(data.get("name"))
        if not name:
            errors.append("Deliverable / phase name is required.")

        type_code = as_text(data.get("type_code"))
        codes = {t.code for t in self.project_types()}
        if not type_code:
            errors.append("Type code is required.")
        elif type_code not in codes:
            errors.append(
                f"Type code {type_code!r} is not in Project Types "
                f"({', '.join(sorted(codes))})."
            )

        weight = as_fraction(data.get("phase_weight"))
        if weight is None:
            errors.append("Phase weight is required.")
        elif not 0 <= weight <= 1:
            errors.append("Phase weight must be between 0% and 100%.")

        step_raw = as_number(data.get("step_no"))
        step_no = int(step_raw) if step_raw is not None else None
        if step_no is not None and type_code:
            if self.credit_for(type_code, step_no) is None:
                allowed = sorted(
                    s.step_no for s in self.credit_steps() if s.type_code == type_code
                )
                errors.append(
                    f"Step {step_no} is not a Rules of Credit step for type "
                    f"{type_code} (valid steps: "
                    f"{', '.join(str(s) for s in allowed) or 'none'})."
                )

        shares = self._validate_shares(data, "The engineer split", errors)

        status_date = as_date(data.get("status_date"))
        if data.get("status_date") and status_date is None:
            errors.append("Status date is not a date the app recognises.")

        ts_phase_raw = as_number(data.get("ts_phase"))
        ts_phase = int(ts_phase_raw) if ts_phase_raw is not None else None

        deliverable = Deliverable(
            row=row or 0,
            project_number=project_number,
            name=name,
            type_code=type_code,
            phase_weight=weight,
            step_no=step_no,
            status_date=status_date,
            shares=shares,
            notes=as_text(data.get("notes")),
            ts_phase=ts_phase,
        )
        for name_ in cfg.ACTUALS_DATE_FIELDS:
            value = data.get(name_)
            parsed = as_date(value)
            if value and parsed is None:
                errors.append(f"{name_.replace('_', ' ').capitalize()} is not a date.")
            setattr(deliverable, name_, parsed)
        return deliverable, errors

    def _write_deliverable(self, db: sqlite3.Connection,
                           deliverable: Deliverable) -> int:
        values = [deliverable.project_number, deliverable.name,
                  deliverable.type_code, deliverable.phase_weight,
                  deliverable.step_no, iso(deliverable.status_date),
                  deliverable.notes, deliverable.ts_phase]
        values += [iso(getattr(deliverable, name)) for name in cfg.ACTUALS_DATE_FIELDS]
        columns = ["project_number", "name", "type_code", "phase_weight",
                   "step_no", "status_date", "notes", "ts_phase",
                   *cfg.ACTUALS_DATE_FIELDS]
        if deliverable.row:
            db.execute(
                f"UPDATE deliverables SET {', '.join(c + ' = ?' for c in columns)} "
                f"WHERE row = ?", values + [deliverable.row])
        else:
            deliverable.row = db.execute(
                f"INSERT INTO deliverables ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})", values).lastrowid
        self._write_shares(db, "deliverable_shares", "deliverable_row",
                           deliverable.row, deliverable.shares)
        return deliverable.row

    def add_deliverable(self, data: Dict[str, Any]) -> Deliverable:
        deliverable, errors = self.validate_deliverable(data)
        if errors:
            raise ValidationError(errors)
        deliverable.row = 0
        with self._write() as db:
            self._write_deliverable(db, deliverable)
        return deliverable

    def update_deliverable(self, row: int, data: Dict[str, Any]) -> Deliverable:
        if self.deliverable(row) is None:
            raise ValidationError([f"There is no deliverable {row}."])
        deliverable, errors = self.validate_deliverable(data, row=row)
        if errors:
            raise ValidationError(errors)
        deliverable.row = row
        with self._write() as db:
            self._write_deliverable(db, deliverable)
        return deliverable

    @staticmethod
    def _delete_deliverable(db: sqlite3.Connection, row: int) -> None:
        db.execute("DELETE FROM deliverable_shares WHERE deliverable_row = ?", (row,))
        db.execute("DELETE FROM deliverables WHERE row = ?", (row,))
        db.execute("DELETE FROM drawings WHERE row = ?", (row,))
        db.execute("DELETE FROM drawing_list WHERE row = ?", (row,))

    def delete_deliverable(self, row: int) -> Dict[str, Any]:
        if self.deliverable(row) is None:
            raise ValidationError([f"There is no deliverable {row}."])
        with self._write() as db:
            self._delete_deliverable(db, row)
        return {"row": row}

    # -- a project and its deliverables, saved together --------------------
    def save_project_with_deliverables(
        self, number: Optional[str], project_data: Dict[str, Any],
        deliverables: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Save a project together with its whole deliverable set.

        Editing the set as a whole is what makes the 100% rule workable: a
        deliverable added on its own would leave the project short of 100%
        every time, whereas a set can be checked before any of it is written.
        """
        errors: List[str] = []
        existing = self.project(number) if number else None
        if number and existing is None:
            raise ValidationError([f"No project numbered {number!r} in the register."])

        project, project_errors = self.validate_project(
            project_data, row=existing.row if existing else None)
        errors.extend(project_errors)

        checked: List[Deliverable] = []
        for position, item in enumerate(deliverables, start=1):
            data = dict(item)
            data["project_number"] = project.number
            deliverable, item_errors = self.validate_deliverable(
                data, row=item.get("row"), pending_project=project.number)
            label = as_text(item.get("name")) or f"deliverable {position}"
            errors.extend(f"{label}: {message}" for message in item_errors)
            checked.append(deliverable)

        total_weight = sum(d.phase_weight or 0.0 for d in checked)
        if checked and abs(total_weight - 1.0) > 1e-4:
            errors.append(
                f"The phase weights total {total_weight * 100:.1f}%, not 100%. "
                f"A project's deliverables have to account for all of its scope "
                f"before it can be saved."
            )
        if errors:
            raise ValidationError(errors)

        # A deliverable keeps the id it already has wherever it can -- by id,
        # or else by name -- because tasks, drawing counts and the
        # submissions plan all point at it.
        owners = {project.number, existing.number if existing else project.number}
        current_rows = {
            d.row: d for d in self.deliverables() if d.project_number in owners
        }
        by_name = {
            (d.name or "").strip().lower(): d.row
            for d in current_rows.values() if (d.name or "").strip()
        }
        taken: set = set()
        for deliverable in checked:
            if deliverable.row in current_rows and deliverable.row not in taken:
                taken.add(deliverable.row)
                continue
            matched = by_name.get((deliverable.name or "").strip().lower())
            if matched and matched not in taken:
                deliverable.row = matched
                taken.add(matched)
            else:
                deliverable.row = 0

        removed = 0
        with self._write() as db:
            project.row = existing.row if existing else 0
            self._write_project(db, project)
            if existing and project.number != existing.number:
                self._renumber(db, existing.number, project.number)
            for row in current_rows:
                if row not in taken:
                    self._delete_deliverable(db, row)
                    removed += 1
            for deliverable in checked:
                self._write_deliverable(db, deliverable)

        return {
            "project": project.to_dict(),
            "deliverables": [d.to_dict() for d in checked],
            "removed": removed,
            "weight_total": round(total_weight, 6),
        }

    def weight_by_project(self) -> Dict[str, float]:
        """Total phase weight per project -- each should come to 100%."""
        totals: Dict[str, float] = {}
        for deliverable in self.deliverables():
            totals[deliverable.project_number] = (
                totals.get(deliverable.project_number, 0.0)
                + (deliverable.phase_weight or 0.0)
            )
        return totals

    # -- planned man-months typed in per quarter -----------------------------
    def phasing_overrides(self) -> Dict[str, Dict[str, float]]:
        """Project number -> quarter start (ISO) -> planned MM typed in."""
        def build() -> Dict[str, Dict[str, float]]:
            out: Dict[str, Dict[str, float]] = {}
            with self._connect() as db:
                for row in db.execute("SELECT * FROM phasing"):
                    out.setdefault(row["project_number"], {})[
                        row["quarter_start"]] = row["mm"]
            return out
        return self._cached("phasing", build)

    def set_phasing(self, project_number: str,
                    values: Dict[str, Optional[float]]) -> None:
        with self._write() as db:
            for quarter, mm in values.items():
                day = as_date(quarter)
                if day is None:
                    continue
                if mm is None:
                    db.execute("DELETE FROM phasing WHERE project_number = ? "
                               "AND quarter_start = ?",
                               (project_number, day.isoformat()))
                else:
                    db.execute(
                        "INSERT OR REPLACE INTO phasing (project_number, "
                        "quarter_start, mm) VALUES (?, ?, ?)",
                        (project_number, day.isoformat(), float(mm)))

    # -- timesheets ----------------------------------------------------------
    def timesheet_headers(self, engineer: Optional[str] = None) -> List[str]:
        """The columns of a timesheet export, which an upload is read against."""
        return list(cfg.TS_HEADERS)

    def data_check(self, year: Optional[int] = None, *,
                   store: Any = None) -> Dict[str, Any]:
        """How the timesheet rows line up with the team and the projects.

        ``year`` narrows the counts to one year, the way the Overview does with
        everything else on the page.
        """
        store = store if store is not None else self.store
        engineers = {e.short_name: e for e in self.engineers()}
        held: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict(
            (name, []) for name in engineers)
        for row in store.all_rows():
            held.setdefault(row["engineer"], []).append(row)

        per_engineer: Dict[str, Any] = {}
        total_rows = 0
        total_hours = 0.0
        year_rows = 0
        year_hours = 0.0
        first_date: Optional[_dt.date] = None
        last_date: Optional[_dt.date] = None
        unmatched = 0

        for short_name, rows in held.items():
            hours = 0.0
            in_year_rows = 0
            in_year_hours = 0.0
            dates: List[_dt.date] = []
            bad_names = 0
            person = engineers.get(short_name)
            # Somebody with rows but not on the team was matched by their
            # full name when they were imported; there is no pattern to hold
            # them to, and they are listed below rather than counted here.
            regex = pattern_to_regex(person.pattern) if person else None
            matches: Dict[Any, bool] = {}
            for row in rows:
                booked = row["hours"]
                hours += booked
                date = row["date"]
                if date:
                    dates.append(date)
                if year is not None and date and date.year == year:
                    in_year_rows += 1
                    in_year_hours += booked
                if regex is not None:
                    # One person's rows carry one or two spellings of a name.
                    name = row["full_name"]
                    fits = matches.get(name)
                    if fits is None:
                        fits = matches[name] = bool(isinstance(name, str)
                                                    and regex.match(name))
                    if not fits:
                        bad_names += 1
            total_rows += len(rows)
            total_hours += hours
            year_rows += in_year_rows
            year_hours += in_year_hours
            unmatched += bad_names
            if dates:
                low, high = min(dates), max(dates)
                first_date = low if first_date is None else min(first_date, low)
                last_date = high if last_date is None else max(last_date, high)
            per_engineer[short_name] = {
                "sheet": "",
                "rows": in_year_rows if year is not None else len(rows),
                "hours": round(in_year_hours if year is not None else hours, 2),
                "all_time_rows": len(rows),
                "all_time_hours": round(hours, 2),
                "first_date": iso(min(dates)) if dates else None,
                "last_date": iso(max(dates)) if dates else None,
                "rows_not_matching_pattern": bad_names,
            }

        known = {p.number for p in self.projects()} | set(self.non_project_codes())
        unknown_codes: Dict[str, int] = {}
        for rows in held.values():
            for row in rows:
                code = row["job_number"]
                if not code or code in known:
                    continue
                if year is not None and (row["date"] is None
                                         or row["date"].year != year):
                    continue
                unknown_codes[code] = unknown_codes.get(code, 0) + 1

        outside = [name for name, rows in held.items()
                   if rows and name not in engineers]
        if total_rows == 0:
            verdict = "No timesheet data yet - upload the timesheet exports."
        elif unmatched:
            verdict = (
                f"Check names: {unmatched:,} row(s) do not match the name "
                "patterns on Team."
            )
        elif outside:
            verdict = outside_message(outside)
        else:
            verdict = "All rows matched to somebody on the team."

        return {
            "year": year,
            "source": "database",
            "rows": year_rows if year is not None else total_rows,
            "hours": round(year_hours if year is not None else total_hours, 2),
            "all_time_rows": total_rows,
            "all_time_hours": round(total_hours, 2),
            "first_date": iso(first_date),
            "last_date": iso(last_date),
            "rows_not_matching_pattern": unmatched,
            "verdict": verdict,
            "capacity": None,
            "capacity_warnings": [],
            "per_engineer": per_engineer,
            "people_outside_workbook": outside,
            "unknown_job_numbers": sorted(
                ({"code": k, "rows": v} for k, v in unknown_codes.items()),
                key=lambda item: -item["rows"],
            ),
        }

    # -- tasks -------------------------------------------------------------
    #
    # ``tasks`` holds the rules; these four are how it reads and writes the
    # list and its settings, and the rest pass straight through to it.

    def read_tasks(self) -> List["task_list.Task"]:
        def build() -> List[task_list.Task]:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM tasks ORDER BY position, id").fetchall()
            out = []
            for row in rows:
                try:
                    assignees = [str(a) for a in json.loads(row["assignees"] or "[]")]
                except ValueError:
                    assignees = []
                out.append(task_list.Task(
                    id=int(row["id"]),
                    name=row["name"],
                    definition=row["definition"],
                    project_number=row["project_number"],
                    deliverable_row=row["deliverable_row"],
                    deliverable_name=row["deliverable_name"],
                    assignees=assignees,
                    required_hours=row["required_hours"],
                    actual_hours=row["actual_hours"],
                    start=stored_date(row["start"]),
                    due=stored_date(row["due"]),
                    status=row["status"] or cfg.TASK_STATUSES[0],
                    kind=row["kind"] or cfg.TASK_KINDS[0],
                    series=row["series"],
                    notes=row["notes"],
                    progress_mode=row["progress_mode"] or task_list.progress.MODE_PRO_RATA,
                    stage=row["stage"] or task_list.progress.STAGE_KEYS[0],
                    review_code=(row["review_code"] or "").upper(),
                    revisions=int(row["revisions"] or 0),
                    pro_rata=row["pro_rata"],
                ))
            return out
        # Callers change the tasks they are handed, so each gets its own.
        return [task_list.Task(**{**t.__dict__, "assignees": list(t.assignees)})
                for t in self._cached("tasks", build)]

    def write_tasks(self, tasks: Sequence["task_list.Task"]) -> None:
        with self._write() as db:
            db.execute("DELETE FROM tasks")
            for position, task in enumerate(tasks):
                db.execute(
                    "INSERT INTO tasks (id, position, name, definition, "
                    "project_number, deliverable_row, deliverable_name, assignees, "
                    "required_hours, actual_hours, start, due, status, kind, series, "
                    "notes, progress_mode, stage, review_code, revisions, pro_rata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?)",
                    (int(task.id), position, task.name, task.definition,
                     task.project_number, task.deliverable_row,
                     task.deliverable_name, json.dumps(list(task.assignees)),
                     task.required_hours, task.actual_hours, iso(task.start),
                     iso(task.due), task.status, task.kind, task.series,
                     task.notes, task.progress_mode, task.stage, task.review_code,
                     int(task.revisions or 0), task.pro_rata))

    def read_task_settings(self) -> Optional[Dict[str, Any]]:
        stored = self._setting("task_settings")
        if not stored:
            return None
        try:
            value = json.loads(stored)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def write_task_settings(self, values: Dict[str, Any]) -> None:
        with self._write() as db:
            self._set_setting(db, "task_settings",
                              json.dumps(values, separators=(",", ":")))

    def tasks(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in task_list.read(self)]

    def task_records(self) -> List["task_list.Task"]:
        return task_list.read(self)

    def task_settings(self) -> Dict[str, Any]:
        return task_list.settings(self)

    def save_task_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return task_list.save_settings(self, data)

    def task_load(self, *, weeks: Optional[int] = None,
                  today: Optional[_dt.date] = None) -> Dict[str, Any]:
        return task_list.load(
            task_list.read(self), self.engineer_names(),
            self.task_settings(), today=today, weeks=weeks)

    def save_task(self, data: Dict[str, Any],
                  task_id: Optional[int] = None) -> Dict[str, Any]:
        task = task_list.save(
            self, data, engineers=self.engineer_names(),
            projects=[p.number for p in self.projects()], task_id=task_id)
        return task.to_dict()

    def delete_task(self, task_id: int) -> Dict[str, Any]:
        return task_list.delete(self, task_id)

    def delete_task_series(self, series: str) -> Dict[str, Any]:
        return task_list.delete_series(self, series)

    def generate_submission_tasks(self, *, only_row: Optional[int] = None,
                                  today: Optional[_dt.date] = None,
                                  include_past: bool = False) -> Dict[str, Any]:
        """Fill in the run-up to every dated deliverable."""
        deliverables = []
        for source in self.deliverables():
            item = source.to_dict()
            item["shares"] = source.shares
            deliverables.append(item)
        return task_list.generate_submissions(
            self, deliverables, engineers=self.engineer_names(),
            only_row=only_row, today=today, include_past=include_past)

    def generate_weekly_meetings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        number = str(data.get("project_number") or "").strip()
        name = ""
        if number:
            project = self.project(number)
            if project is None:
                raise ValidationError([f"{number} is not a project in the register."])
            name = project.name
        start = data.get("start")
        try:
            start = _dt.date.fromisoformat(str(start)) if start else None
        except ValueError:
            raise ValidationError(["The start is not a date."])
        return task_list.generate_meetings(
            self, engineers=self.engineer_names(),
            project_number=number, project_name=name,
            start=start,
            weeks=data.get("weeks"), weekday=data.get("weekday"),
            hours=data.get("hours"))

    # -- health ------------------------------------------------------------
    def register_issues(self) -> List[Dict[str, str]]:
        """What is missing or does not add up in the registers."""
        issues: List[Dict[str, str]] = []
        numbers = {p.number for p in self.projects()}
        weights = self.weight_by_project()

        for project in self.projects():
            total = weights.get(project.number)
            if total is None:
                issues.append({
                    "level": "info",
                    "where": f"Project {project.number}",
                    "message": (
                        f"{project.number} has no deliverables, so its progress "
                        f"falls back to its manual % complete."
                    ),
                })
            elif abs(total - 1.0) > 1e-4:
                issues.append({
                    "level": "error",
                    "where": f"Deliverables of {project.number}",
                    "message": (
                        f"Phase weights for {project.number} total "
                        f"{total * 100:.1f}%, not 100%. Progress for this project "
                        f"is not meaningful until they do."
                    ),
                })

        for deliverable in self.deliverables():
            where = (f"{deliverable.project_number} · "
                     f"{deliverable.name or 'deliverable'}")
            if deliverable.project_number not in numbers:
                issues.append({
                    "level": "error",
                    "where": where,
                    "message": (
                        f"{deliverable.project_number} is not in the project "
                        f"register."
                    ),
                })
            total = sum(v for v in deliverable.shares.values() if v)
            if total and abs(total - 1.0) > 1e-4:
                issues.append({
                    "level": "error",
                    "where": where,
                    "message": (
                        f"{deliverable.name or 'deliverable'}: the engineer split "
                        f"totals {total * 100:.1f}%, not 100%."
                    ),
                })
            elif not total:
                issues.append({
                    "level": "warning",
                    "where": where,
                    "message": (
                        f"{deliverable.name or 'deliverable'} has no engineer "
                        f"split, so it earns nobody any credit."
                    ),
                })
            if deliverable.type_code and deliverable.step_no is not None:
                if self.credit_for(deliverable.type_code, deliverable.step_no) is None:
                    issues.append({
                        "level": "error",
                        "where": where,
                        "message": (
                            f"Step {deliverable.step_no} is not valid for type "
                            f"{deliverable.type_code}."
                        ),
                    })
            if deliverable.ts_phase is None:
                issues.append({
                    "level": "warning",
                    "where": where,
                    "message": (
                        f"{deliverable.name or 'deliverable'} has no timesheet "
                        f"phase, so no timesheet hours can be attributed to it."
                    ),
                })
        return issues

    # -- counts, for the unit list ----------------------------------------
    def summary(self) -> Dict[str, Any]:
        with self._connect() as db:
            def count(table: str) -> int:
                return db.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            return {"engineers": count("engineers"), "projects": count("projects"),
                    "deliverables": count("deliverables"), "rows": count("rows"),
                    "tasks": count("tasks")}


def outside_message(names: Sequence[str]) -> str:
    """What it means to have hours here but no place on the team, in a line."""
    who = ", ".join(names)
    many = len(names) != 1
    return (
        f"{len(names)} {'people have' if many else 'person has'} hours here but "
        f"{'are' if many else 'is'} not on the team: {who}. Their hours count "
        "toward the projects and in Resourcing; add them on Team to give them "
        "a KPI line and a share of a deliverable."
    )


# -- one Unit per file, per worker ---------------------------------------

def fresh_copy(value: Any) -> Any:
    """A copy of a kept answer that its caller may change freely.

    The answers are JSON-shaped -- dicts and lists of plain values -- so this
    copies those itself, which is several times quicker than ``deepcopy``;
    anything else that can change is handed to ``deepcopy``.
    """
    kind = type(value)
    if kind is dict:
        return {k: fresh_copy(v) for k, v in value.items()}
    if kind is list:
        return [fresh_copy(v) for v in value]
    if kind in _UNCHANGING:
        return value
    return copy.deepcopy(value)


_UNCHANGING = frozenset({str, int, float, bool, type(None), _dt.date,
                         _dt.datetime})


def _identity(path: Path) -> int:
    """Which file is at ``path``: a copy put in its place is another file.

    (Not its times: SQLite writes the file itself whenever the last
    connection closes, which is after nearly every change.)
    """
    try:
        return path.stat().st_ino
    except OSError:                        # pragma: no cover - gone underneath
        return 0


#: How many units a worker keeps what it has read of.
KEPT_OPEN = 8
_open_units: "OrderedDict[Path, Unit]" = OrderedDict()
_open_lock = threading.Lock()


def shared(path: Union[str, Path]) -> Unit:
    """The worker's one :class:`Unit` for this file, with what it has read.

    Opening a unit again -- after switching away and back, or to put several
    side by side -- starts from what was already worked out, as long as the
    file has not been written since (``refresh``).  A file put in its place
    is a new file, and starts afresh.
    """
    key = Path(path).resolve()
    with _open_lock:
        unit = _open_units.pop(key, None)
    if unit is None or unit.revision is None or unit.revision[0] != _identity(key):
        unit = Unit(key)
    else:
        unit.refresh()
    with _open_lock:
        _open_units[key] = unit
        while len(_open_units) > KEPT_OPEN:
            _open_units.popitem(last=False)
    return unit

