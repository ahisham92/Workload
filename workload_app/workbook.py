"""The Workload workbook as an editable domain model.

The workbook stays the single source of truth: there is no separate database to
fall out of step with it.  This module reads the registers, validates changes
against the workbook's own rules, and writes them back into the input cells.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from . import actuals_block, capacity, config as cfg
from .xlsx_io import (
    CellValue, Workbook, build_cell, col_to_index, from_serial, index_to_col,
)


class ValidationError(ValueError):
    """Raised when a change would break one of the workbook's own rules."""

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# --------------------------------------------------------------------------
# coercion helpers
# --------------------------------------------------------------------------

def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value).strip()


def as_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def as_date(value: Any) -> Optional[_dt.date]:
    """Accept an ISO string, a date, a datetime or an Excel serial number."""
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, (int, float)):
        return from_serial(float(value)) if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y",
                "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    number = as_number(text)
    if number is not None and number > 0:
        return from_serial(number)
    return None


def as_fraction(value: Any) -> Optional[float]:
    """Read a share, accepting either ``0.25`` or ``25`` / ``25%`` for a quarter."""
    number = as_number(value)
    if number is None:
        return None
    if isinstance(value, str) and value.strip().endswith("%"):
        return number
    if number > 1.0000001:
        return number / 100.0
    return number


def iso(value: Optional[_dt.date]) -> Optional[str]:
    return value.isoformat() if value else None


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

@dataclass
class Project:
    row: int
    number: str = ""
    name: str = ""
    budget_mm: Optional[float] = None
    start: Optional[_dt.date] = None
    end: Optional[_dt.date] = None
    status: str = ""
    cac_override: Optional[float] = None
    notes: str = ""
    manual_percent: Optional[float] = None
    #: Fallback split, engineer short name -> fraction.
    manual_shares: Dict[str, Optional[float]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row": self.row,
            "number": self.number,
            "name": self.name,
            "budget_mm": self.budget_mm,
            "start": iso(self.start),
            "end": iso(self.end),
            "status": self.status,
            "cac_override": self.cac_override,
            "notes": self.notes,
            "manual_percent": self.manual_percent,
            "manual_shares": dict(self.manual_shares),
        }


@dataclass
class Deliverable:
    row: int
    project_number: str = ""
    name: str = ""
    type_code: str = ""
    phase_weight: Optional[float] = None
    step_no: Optional[int] = None
    status_date: Optional[_dt.date] = None
    #: Engineer short name -> fraction of this deliverable.
    shares: Dict[str, Optional[float]] = field(default_factory=dict)
    notes: str = ""
    ts_phase: Optional[int] = None
    actual_start: Optional[_dt.date] = None
    actual_finish: Optional[_dt.date] = None
    submitted_to_client: Optional[_dt.date] = None
    comments_received: Optional[_dt.date] = None
    resubmitted: Optional[_dt.date] = None
    completed: Optional[_dt.date] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "row": self.row,
            "project_number": self.project_number,
            "name": self.name,
            "type_code": self.type_code,
            "phase_weight": self.phase_weight,
            "step_no": self.step_no,
            "status_date": iso(self.status_date),
            "shares": dict(self.shares),
            "notes": self.notes,
            "ts_phase": self.ts_phase,
        }
        for name in cfg.ACTUALS_DATE_FIELDS:
            out[name] = iso(getattr(self, name))
        return out


@dataclass
class ProjectType:
    code: str
    name: str
    basis: str = ""
    trigger: str = ""
    portfolio_weight: Optional[float] = None
    include_in_cpi: str = ""
    notes: str = ""


@dataclass
class CreditStep:
    type_code: str
    step_no: int
    step_name: str
    credit: float
    data_source: str = ""


@dataclass
class Engineer:
    short_name: str
    pattern: str
    available_hours: Optional[float]
    availability: Dict[int, float] = field(default_factory=dict)


# --------------------------------------------------------------------------
# the workbook
# --------------------------------------------------------------------------

class WorkloadWorkbook:
    """Read and edit the input sheets of a Workload workbook."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._wb = Workbook(self.path)
        self._dirty = False
        self._formulas_changed = False
        self._timesheet_cache: Dict[str, List[Dict[str, CellValue]]] = {}
        #: Bumped on every write so the register caches below fall away.
        self._version = 0
        self._cache: Dict[str, Any] = {}

    # -- plumbing --------------------------------------------------------
    @property
    def raw(self) -> Workbook:
        return self._wb

    @property
    def dirty(self) -> bool:
        return self._dirty

    def reload(self) -> None:
        self._wb = Workbook(self.path)
        self._dirty = False
        self._formulas_changed = False
        self._timesheet_cache.clear()
        self._version += 1
        self._cache.clear()

    def _set(self, sheet: str, ref: str, value: CellValue, **kw) -> None:
        self._wb.sheet(sheet).set_value(ref, value, **kw)
        self._dirty = True
        self._version += 1
        self._cache.clear()

    def _cached(self, key: str, build):
        """Memoise a register read until the next write."""
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    def save(self, *, backup: bool = True) -> Dict[str, Any]:
        """Write the workbook back to disk, taking a backup copy first."""
        result: Dict[str, Any] = {"saved": False, "backup": None}
        if not self._dirty:
            return result
        if backup:
            result["backup"] = str(
                self._wb.backup(self.path.parent / cfg.BACKUP_DIRNAME)
            )
        if self._formulas_changed:
            self._wb.drop_calc_chain()
        self._wb.force_full_recalc()
        self._wb.save()
        self._dirty = False
        self._formulas_changed = False
        self._timesheet_cache.clear()
        result["saved"] = True
        result["path"] = str(self.path)
        return result

    # -- reference tables ------------------------------------------------
    def project_types(self) -> List[ProjectType]:
        return self._cached("project_types", self._read_project_types)

    def _read_project_types(self) -> List[ProjectType]:
        out: List[ProjectType] = []
        cols = cfg.PROJECT_TYPE_COLUMNS
        for row in range(cfg.PROJECT_TYPES_FIRST_ROW, cfg.PROJECT_TYPES_LAST_ROW + 1):
            code = self._wb.get_text(cfg.SHEET_PROJECT_TYPES, f"{cols['code']}{row}")
            if not code:
                continue
            out.append(ProjectType(
                code=code,
                name=self._wb.get_text(cfg.SHEET_PROJECT_TYPES, f"{cols['name']}{row}"),
                basis=self._wb.get_text(cfg.SHEET_PROJECT_TYPES, f"{cols['basis']}{row}"),
                trigger=self._wb.get_text(cfg.SHEET_PROJECT_TYPES, f"{cols['trigger']}{row}"),
                portfolio_weight=self._wb.get_number(
                    cfg.SHEET_PROJECT_TYPES, f"{cols['portfolio_weight']}{row}"),
                include_in_cpi=self._wb.get_text(
                    cfg.SHEET_PROJECT_TYPES, f"{cols['include_in_cpi']}{row}"),
                notes=self._wb.get_text(cfg.SHEET_PROJECT_TYPES, f"{cols['notes']}{row}"),
            ))
        return out

    def credit_steps(self) -> List[CreditStep]:
        return self._cached("credit_steps", self._read_credit_steps)

    def _read_credit_steps(self) -> List[CreditStep]:
        out: List[CreditStep] = []
        cols = cfg.RULES_COLUMNS
        for row in range(cfg.RULES_FIRST_ROW, cfg.RULES_LAST_ROW + 1):
            code = self._wb.get_text(cfg.SHEET_RULES, f"{cols['type_code']}{row}")
            step = self._wb.get_number(cfg.SHEET_RULES, f"{cols['step_no']}{row}")
            if not code or step is None:
                continue
            out.append(CreditStep(
                type_code=code,
                step_no=int(step),
                step_name=self._wb.get_text(cfg.SHEET_RULES, f"{cols['step_name']}{row}"),
                credit=self._wb.get_number(cfg.SHEET_RULES, f"{cols['credit']}{row}") or 0.0,
                data_source=self._wb.get_text(
                    cfg.SHEET_RULES, f"{cols['data_source']}{row}"),
            ))
        return out

    def credit_for(self, type_code: str, step_no: Optional[int]) -> Optional[float]:
        if not type_code or step_no is None:
            return None
        lookup = self._cached(
            "credit_lookup",
            lambda: {(s.type_code, s.step_no): s.credit for s in self.credit_steps()},
        )
        return lookup.get((type_code, step_no))

    def engineers(self) -> List[Engineer]:
        """The team, read from Work Calendar rather than assumed.

        A workbook set up for another unit names different people, so nothing
        here may depend on who they are or how many of them there are.
        """
        return self._cached("engineers", self._read_engineers)

    def _read_engineers(self) -> List[Engineer]:
        cols = cfg.ENGINEER_COLUMNS
        years = self._availability_years()
        availability_rows = self._availability_rows()
        out: List[Engineer] = []
        for offset in range(cfg.ENGINEER_MAX_ROWS):
            row = cfg.ENGINEER_FIRST_ROW + offset
            name = self._wb.get_text(cfg.SHEET_CALENDAR, f"{cols['short_name']}{row}")
            if not name:
                break
            out.append(Engineer(
                short_name=name,
                pattern=self._wb.get_text(cfg.SHEET_CALENDAR, f"{cols['pattern']}{row}")
                or f"*{name}*",
                available_hours=self._wb.get_number(
                    cfg.SHEET_CALENDAR, f"{cols['available_hours']}{row}"),
                availability=self._availability_for(
                    availability_rows.get(name), years),
            ))
        return out

    def engineer_names(self) -> List[str]:
        return [e.short_name for e in self.engineers()]

    def ts_sheets(self) -> "OrderedDict[str, str]":
        """Short name -> paste-target sheet, in the order they are stacked.

        Matched by name where the sheet is called ``TS <short name>``, and
        otherwise by position, so a renamed sheet still lines up.
        """
        return self._cached("ts_sheets", self._read_ts_sheets)

    def _read_ts_sheets(self) -> "OrderedDict[str, str]":
        available = [name for name in self._wb.sheet_names
                     if name.startswith(cfg.TS_SHEET_PREFIX)]
        stacked = [name for name in capacity.stack_order(self._wb)
                   if name in available]
        ordered = stacked + [n for n in available if n not in stacked]
        mapping: "OrderedDict[str, str]" = OrderedDict()
        spare = list(ordered)
        for engineer in self.engineers():
            wanted = f"{cfg.TS_SHEET_PREFIX}{engineer.short_name}"
            if wanted in spare:
                mapping[engineer.short_name] = wanted
                spare.remove(wanted)
            else:
                mapping[engineer.short_name] = None      # filled in below
        for short_name, sheet in list(mapping.items()):
            if sheet is None:
                mapping[short_name] = spare.pop(0) if spare else None
        return OrderedDict(
            (name, sheet) for name, sheet in mapping.items() if sheet
        )

    def ts_sheet(self, engineer: str) -> str:
        sheets = self.ts_sheets()
        if engineer not in sheets:
            raise ValidationError([
                f"{engineer!r} is not one of this workbook's engineers "
                f"({', '.join(sheets) or 'none found'})."
            ])
        return sheets[engineer]

    def _availability_rows(self) -> Dict[str, int]:
        """Name -> its row in the team availability block on Inputs."""
        out: Dict[str, int] = {}
        for offset in range(cfg.AVAILABILITY_MAX_ROWS):
            row = cfg.AVAILABILITY_FIRST_ROW + offset
            name = self._wb.get_text(cfg.SHEET_INPUTS, f"A{row}")
            if not name:
                break
            out[name] = row
        return out

    def _availability_years(self) -> Dict[str, int]:
        """Column letter -> year, from the team availability header row."""
        years: Dict[str, int] = {}
        first = cfg.AVAILABILITY_FIRST_COL
        last = cfg.AVAILABILITY_LAST_COL
        for index in range(ord(first) - 64, ord(last) - 64 + 1):
            col = index_to_col(index)
            value = self._wb.get_number(
                cfg.SHEET_INPUTS, f"{col}{cfg.AVAILABILITY_HEADER_ROW}")
            if value:
                years[col] = int(value)
        return years

    def _availability_for(self, row: Optional[int], years: Dict[str, int]
                          ) -> Dict[int, float]:
        if row is None:
            return {}
        out: Dict[int, float] = {}
        for col, year in years.items():
            value = self._wb.get_number(cfg.SHEET_INPUTS, f"{col}{row}")
            if value is not None:
                out[year] = value
        return out

    def hours_per_man_month(self) -> float:
        value = self._wb.get_number(
            cfg.SHEET_PROFIT_PLAN, cfg.HOURS_PER_MAN_MONTH_CELL)
        return value or 185.0

    def hours_per_day(self) -> float:
        return self._wb.get_number(cfg.SHEET_CALENDAR, cfg.HOURS_PER_DAY_CELL) or 8.5

    def plan_year(self) -> int:
        value = self._wb.get_number(cfg.SHEET_PROFIT_PLAN, cfg.PLAN_YEAR_CELL)
        return int(value) if value else _dt.date.today().year

    def non_project_codes(self) -> Dict[str, str]:
        cols = cfg.NON_PROJECT_CODE_COLUMNS
        out: Dict[str, str] = {}
        for row in cfg.NON_PROJECT_CODE_ROWS:
            code = self._wb.get_text(cfg.SHEET_CALENDAR, f"{cols['code']}{row}")
            if code:
                out[code] = self._wb.get_text(
                    cfg.SHEET_CALENDAR, f"{cols['treat_as']}{row}")
        return out

    def reference(self) -> Dict[str, Any]:
        """Everything the UI needs to render its dropdowns and hints."""
        steps: Dict[str, List[Dict[str, Any]]] = {}
        for step in self.credit_steps():
            steps.setdefault(step.type_code, []).append({
                "step_no": step.step_no,
                "step_name": step.step_name,
                "credit": step.credit,
                "data_source": step.data_source,
            })
        return {
            "project_types": [t.__dict__ for t in self.project_types()],
            "credit_steps": steps,
            "statuses": cfg.PROJECT_STATUSES,
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
            "capacity": {
                "projects": cfg.PROJECT_LAST_ROW - cfg.PROJECT_FIRST_ROW + 1,
                "deliverables": cfg.DELIVERABLE_LAST_ROW - cfg.DELIVERABLE_FIRST_ROW + 1,
                "project_types": (cfg.PROJECT_TYPES_LAST_ROW
                                  - cfg.PROJECT_TYPES_FIRST_ROW + 1),
                "credit_steps": cfg.RULES_LAST_ROW - cfg.RULES_FIRST_ROW + 1,
            },
        }

    # -- engineer splits -------------------------------------------------
    def _read_shares(self, sheet: str, row: int, columns: Sequence[str]
                     ) -> Dict[str, Optional[float]]:
        """Read a split into ``{engineer: fraction}``, by column position."""
        names = self.engineer_names()
        out: Dict[str, Optional[float]] = {}
        for name, col in zip(names, columns):
            out[name] = self._wb.get_number(sheet, f"{col}{row}")
        return out

    def _write_shares(self, sheet: str, row: int, columns: Sequence[str],
                      shares: Dict[str, Optional[float]]) -> None:
        for name, col in zip(self.engineer_names(), columns):
            self._set(sheet, f"{col}{row}", shares.get(name))

    def _validate_shares(self, data: Dict[str, Any], label: str,
                         errors: List[str]) -> Dict[str, Optional[float]]:
        """Coerce a submitted split and check it adds up.

        Accepts ``{"shares": {...}}`` or a flat ``share_<name>`` per engineer,
        so the same payload shape works whoever the team happens to be.
        """
        raw = data.get("shares") if isinstance(data.get("shares"), dict) else {}
        out: Dict[str, Optional[float]] = {}
        for name in self.engineer_names():
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
                f"{label} must total 100% across "
                f"{', '.join(self.engineer_names())} "
                f"(it totals {total * 100:.1f}%)."
            )
        return out

    # -- projects --------------------------------------------------------
    def projects(self) -> List[Project]:
        return self._cached("projects", self._read_projects)

    def _read_projects(self) -> List[Project]:
        cols = cfg.PROJECT_INPUT_COLUMNS
        out: List[Project] = []
        for row in range(cfg.PROJECT_FIRST_ROW, cfg.PROJECT_LAST_ROW + 1):
            number = self._wb.get_text(cfg.SHEET_INPUTS, f"{cols['number']}{row}")
            if not number:
                continue
            out.append(Project(
                row=row,
                number=number,
                name=self._wb.get_text(cfg.SHEET_INPUTS, f"{cols['name']}{row}"),
                budget_mm=self._wb.get_number(cfg.SHEET_INPUTS, f"{cols['budget_mm']}{row}"),
                start=self._wb.get_date(cfg.SHEET_INPUTS, f"{cols['start']}{row}"),
                end=self._wb.get_date(cfg.SHEET_INPUTS, f"{cols['end']}{row}"),
                status=self._wb.get_text(cfg.SHEET_INPUTS, f"{cols['status']}{row}"),
                cac_override=self._wb.get_number(
                    cfg.SHEET_INPUTS, f"{cols['cac_override']}{row}"),
                notes=self._wb.get_text(cfg.SHEET_INPUTS, f"{cols['notes']}{row}"),
                manual_percent=self._wb.get_number(
                    cfg.SHEET_INPUTS, f"{cols['manual_percent']}{row}"),
                manual_shares=self._read_shares(
                    cfg.SHEET_INPUTS, row, cfg.PROJECT_MANUAL_SHARE_COLUMNS),
            ))
        return out

    def project(self, number: str) -> Optional[Project]:
        wanted = as_text(number)
        for project in self.projects():
            if project.number == wanted:
                return project
        return None

    def _next_project_row(self) -> int:
        used = {p.row for p in self.projects()}
        for row in range(cfg.PROJECT_FIRST_ROW, cfg.PROJECT_LAST_ROW + 1):
            if row not in used:
                return row
        raise ValidationError([
            "The project register is full: rows 6-85 of Inputs all hold a project. "
            "Free a row, or extend the register in Excel first."
        ])

    def validate_project(self, data: Dict[str, Any], *, row: Optional[int] = None
                         ) -> Tuple[Project, List[str]]:
        """Coerce a submitted project and check it against the register's rules."""
        errors: List[str] = []
        number = as_text(data.get("number"))
        if not number:
            errors.append("Project number is required.")
        for other in self.projects():
            if other.number == number and other.row != row:
                errors.append(
                    f"Project number {number!r} is already on Inputs row {other.row}."
                )
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

    def _write_project(self, project: Project) -> None:
        cols = cfg.PROJECT_INPUT_COLUMNS
        row = project.row
        values: Dict[str, CellValue] = {
            "number": project.number,
            "name": project.name,
            "budget_mm": project.budget_mm,
            "start": project.start,
            "end": project.end,
            "status": project.status,
            "cac_override": project.cac_override,
            "notes": project.notes,
            "manual_percent": project.manual_percent,
        }
        for name, col in cols.items():
            self._set(cfg.SHEET_INPUTS, f"{col}{row}", values[name])
        self._write_shares(cfg.SHEET_INPUTS, row,
                           cfg.PROJECT_MANUAL_SHARE_COLUMNS, project.manual_shares)

    def add_project(self, data: Dict[str, Any]) -> Project:
        row = self._next_project_row()
        project, errors = self.validate_project(data, row=row)
        if errors:
            raise ValidationError(errors)
        project.row = row
        self._write_project(project)
        return project

    def update_project(self, number: str, data: Dict[str, Any]) -> Project:
        existing = self.project(number)
        if existing is None:
            raise ValidationError([f"No project numbered {number!r} in the register."])
        project, errors = self.validate_project(data, row=existing.row)
        if errors:
            raise ValidationError(errors)
        project.row = existing.row
        self._write_project(project)
        if project.number != existing.number:
            # Deliverables key off the project number, so keep them in step.
            for deliverable in self.deliverables():
                if deliverable.project_number == existing.number:
                    self._set(
                        cfg.SHEET_DELIVERABLES,
                        f"{cfg.DELIVERABLE_INPUT_COLUMNS['project_number']}"
                        f"{deliverable.row}",
                        project.number,
                    )
        return project

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
        for deliverable in attached:
            self._clear_deliverable_row(deliverable.row)
        for col in cfg.PROJECT_INPUT_COLUMNS.values():
            self._set(cfg.SHEET_INPUTS, f"{col}{existing.row}", None)
        for col in cfg.PROJECT_MANUAL_SHARE_COLUMNS:
            self._set(cfg.SHEET_INPUTS, f"{col}{existing.row}", None)
        return {"row": existing.row, "deliverables_removed": len(attached)}

    # -- deliverables ----------------------------------------------------
    def actuals_last_row(self) -> int:
        return actuals_block.detect_last_row(
            self._wb.sheet(cfg.SHEET_ACTUALS), cfg.ACTUALS_FIRST_ROW
        )

    def deliverables(self) -> List[Deliverable]:
        return self._cached("deliverables", self._read_deliverables)

    def _read_deliverables(self) -> List[Deliverable]:
        cols = cfg.DELIVERABLE_INPUT_COLUMNS
        acols = cfg.ACTUALS_INPUT_COLUMNS
        actuals_end = self.actuals_last_row()
        out: List[Deliverable] = []
        for row in range(cfg.DELIVERABLE_FIRST_ROW, cfg.DELIVERABLE_LAST_ROW + 1):
            number = self._wb.get_text(
                cfg.SHEET_DELIVERABLES, f"{cols['project_number']}{row}")
            if not number:
                continue
            step = self._wb.get_number(cfg.SHEET_DELIVERABLES, f"{cols['step_no']}{row}")
            deliverable = Deliverable(
                row=row,
                project_number=number,
                name=self._wb.get_text(cfg.SHEET_DELIVERABLES, f"{cols['name']}{row}"),
                type_code=self._wb.get_text(
                    cfg.SHEET_DELIVERABLES, f"{cols['type_code']}{row}"),
                phase_weight=self._wb.get_number(
                    cfg.SHEET_DELIVERABLES, f"{cols['phase_weight']}{row}"),
                step_no=int(step) if step is not None else None,
                status_date=self._wb.get_date(
                    cfg.SHEET_DELIVERABLES, f"{cols['status_date']}{row}"),
                shares=self._read_shares(
                    cfg.SHEET_DELIVERABLES, row, cfg.DELIVERABLE_SHARE_COLUMNS),
                notes=self._wb.get_text(cfg.SHEET_DELIVERABLES, f"{cols['notes']}{row}"),
            )
            if row <= actuals_end:
                phase = self._wb.get_number(cfg.SHEET_ACTUALS, f"{acols['ts_phase']}{row}")
                deliverable.ts_phase = int(phase) if phase is not None else None
                for name in cfg.ACTUALS_DATE_FIELDS:
                    setattr(deliverable, name,
                            self._wb.get_date(cfg.SHEET_ACTUALS, f"{acols[name]}{row}"))
            out.append(deliverable)
        return out

    def deliverable(self, row: int) -> Optional[Deliverable]:
        for item in self.deliverables():
            if item.row == row:
                return item
        return None

    def _next_deliverable_row(self) -> int:
        used = {d.row for d in self.deliverables()}
        for row in range(cfg.DELIVERABLE_FIRST_ROW, cfg.DELIVERABLE_LAST_ROW + 1):
            if row not in used:
                return row
        raise ValidationError([
            "The deliverable register is full: rows 5-204 of Deliverables are all "
            "in use."
        ])

    def ensure_actuals_capacity(self, row: int) -> int:
        """Grow ``Deliverable Actuals`` so it covers register row ``row``."""
        sheet = self._wb.sheet(cfg.SHEET_ACTUALS)
        current = actuals_block.detect_last_row(sheet, cfg.ACTUALS_FIRST_ROW)
        if row <= current:
            return current
        new_last = actuals_block.extend(
            sheet,
            first_row=cfg.ACTUALS_FIRST_ROW,
            template_row=cfg.ACTUALS_TEMPLATE_ROW,
            new_last_row=row,
            blank_columns=set(cfg.ACTUALS_INPUT_COLUMNS.values()),
            last_row=current,
        )
        self._dirty = True
        self._formulas_changed = True
        self._version += 1
        self._cache.clear()
        return new_last

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

    def _write_deliverable(self, deliverable: Deliverable) -> None:
        cols = cfg.DELIVERABLE_INPUT_COLUMNS
        row = deliverable.row
        values: Dict[str, CellValue] = {
            "project_number": deliverable.project_number,
            "name": deliverable.name,
            "type_code": deliverable.type_code,
            "phase_weight": deliverable.phase_weight,
            "step_no": deliverable.step_no,
            "status_date": deliverable.status_date,
            "notes": deliverable.notes,
        }
        for name, col in cols.items():
            self._set(cfg.SHEET_DELIVERABLES, f"{col}{row}", values[name])
        self._write_shares(cfg.SHEET_DELIVERABLES, row,
                           cfg.DELIVERABLE_SHARE_COLUMNS, deliverable.shares)

        self.ensure_actuals_capacity(row)
        acols = cfg.ACTUALS_INPUT_COLUMNS
        self._set(cfg.SHEET_ACTUALS, f"{acols['ts_phase']}{row}", deliverable.ts_phase)
        for name in cfg.ACTUALS_DATE_FIELDS:
            self._set(cfg.SHEET_ACTUALS, f"{acols[name]}{row}",
                      getattr(deliverable, name))

    def add_deliverable(self, data: Dict[str, Any]) -> Deliverable:
        row = self._next_deliverable_row()
        deliverable, errors = self.validate_deliverable(data, row=row)
        if errors:
            raise ValidationError(errors)
        deliverable.row = row
        self._write_deliverable(deliverable)
        return deliverable

    def update_deliverable(self, row: int, data: Dict[str, Any]) -> Deliverable:
        if self.deliverable(row) is None:
            raise ValidationError([f"No deliverable on Deliverables row {row}."])
        deliverable, errors = self.validate_deliverable(data, row=row)
        if errors:
            raise ValidationError(errors)
        deliverable.row = row
        self._write_deliverable(deliverable)
        return deliverable

    def _clear_deliverable_row(self, row: int) -> None:
        for col in cfg.DELIVERABLE_INPUT_COLUMNS.values():
            self._set(cfg.SHEET_DELIVERABLES, f"{col}{row}", None)
        for col in cfg.DELIVERABLE_SHARE_COLUMNS:
            self._set(cfg.SHEET_DELIVERABLES, f"{col}{row}", None)
        if row <= self.actuals_last_row():
            for col in cfg.ACTUALS_INPUT_COLUMNS.values():
                self._set(cfg.SHEET_ACTUALS, f"{col}{row}", None)

    def delete_deliverable(self, row: int) -> Dict[str, Any]:
        if self.deliverable(row) is None:
            raise ValidationError([f"No deliverable on Deliverables row {row}."])
        self._clear_deliverable_row(row)
        return {"row": row}

    # -- a project and its deliverables, saved together ------------------
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

        # Deliverables are validated against the project number being saved,
        # which may differ from the one on the sheet if it is being renamed.
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

        # Write the project first so the deliverables have somewhere to point.
        if existing is None:
            project.row = self._next_project_row()
        else:
            project.row = existing.row
        self._write_project(project)

        # Rows matter beyond tidiness: Deliverable Actuals is aligned to them,
        # so a deliverable that moved rows would inherit another one's
        # milestone dates.  Keep the row it already has wherever possible.
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
                deliverable.row = None

        removed = 0
        for row in current_rows:
            if row not in taken:
                self._clear_deliverable_row(row)
                removed += 1

        written: List[Deliverable] = []
        for deliverable in checked:
            if not deliverable.row:
                deliverable.row = self._next_deliverable_row()
            self._write_deliverable(deliverable)
            written.append(deliverable)

        return {
            "project": project.to_dict(),
            "deliverables": [d.to_dict() for d in written],
            "removed": removed,
            "weight_total": round(total_weight, 6),
        }

    # -- reference tables ------------------------------------------------
    def save_reference(self, project_types: Optional[Sequence[Dict[str, Any]]],
                       credit_steps: Optional[Sequence[Dict[str, Any]]]
                       ) -> Dict[str, Any]:
        """Rewrite Project Types and Rules of Credit from the app."""
        errors: List[str] = []
        types = list(project_types or [])
        steps = list(credit_steps or [])

        capacity_types = cfg.PROJECT_TYPES_LAST_ROW - cfg.PROJECT_TYPES_FIRST_ROW + 1
        capacity_steps = cfg.RULES_LAST_ROW - cfg.RULES_FIRST_ROW + 1
        if len(types) > capacity_types:
            errors.append(
                f"Project Types has room for {capacity_types} rows, not {len(types)}.")
        if len(steps) > capacity_steps:
            errors.append(
                f"Rules of Credit has room for {capacity_steps} rows, not "
                f"{len(steps)}.")

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

        cols = cfg.PROJECT_TYPE_COLUMNS
        for offset in range(capacity_types):
            row = cfg.PROJECT_TYPES_FIRST_ROW + offset
            item = types[offset] if offset < len(types) else {}
            values = {
                "code": as_text(item.get("code")) or None,
                "name": as_text(item.get("name")) or None,
                "basis": as_text(item.get("basis")) or None,
                "trigger": as_text(item.get("trigger")) or None,
                "portfolio_weight": as_number(item.get("portfolio_weight")),
                "include_in_cpi": as_text(item.get("include_in_cpi")) or None,
                "notes": as_text(item.get("notes")) or None,
            }
            for field_name, col in cols.items():
                self._set(cfg.SHEET_PROJECT_TYPES, f"{col}{row}", values[field_name])

        cols = cfg.RULES_COLUMNS
        for offset in range(capacity_steps):
            row = cfg.RULES_FIRST_ROW + offset
            item = steps[offset] if offset < len(steps) else {}
            step_raw = as_number(item.get("step_no"))
            values = {
                "type_code": as_text(item.get("type_code")) or None,
                "step_no": int(step_raw) if step_raw is not None else None,
                "step_name": as_text(item.get("step_name")) or None,
                "credit": as_fraction(item.get("credit")),
                "data_source": as_text(item.get("data_source")) or None,
            }
            for field_name, col in cols.items():
                self._set(cfg.SHEET_RULES, f"{col}{row}", values[field_name])

        return {"project_types": len(types), "credit_steps": len(steps)}

    # -- phase weight helper ---------------------------------------------
    def weight_by_project(self) -> Dict[str, float]:
        """Total phase weight per project -- the workbook wants 100% each."""
        totals: Dict[str, float] = {}
        for deliverable in self.deliverables():
            totals[deliverable.project_number] = (
                totals.get(deliverable.project_number, 0.0)
                + (deliverable.phase_weight or 0.0)
            )
        return totals

    # -- timesheets ------------------------------------------------------
    def timesheet_headers(self, engineer: str) -> List[str]:
        sheet = self.ts_sheet(engineer)
        headers: List[str] = []
        for index in range(1, col_to_index(cfg.TS_LAST_COLUMN) + 1):
            col = index_to_col(index)
            headers.append(self._wb.get_text(sheet, f"{col}{cfg.TS_HEADER_ROW}"))
        return headers

    def timesheet_rows(self, engineer: str,
                       columns: Optional[Iterable[str]] = None
                       ) -> List[Dict[str, CellValue]]:
        """Read one engineer's pasted export."""
        sheet = self.ts_sheet(engineer)
        cols = list(columns) if columns is not None else [
            index_to_col(i) for i in range(1, col_to_index(cfg.TS_LAST_COLUMN) + 1)
        ]
        key = f"{engineer}:{','.join(cols)}"
        if key not in self._timesheet_cache:
            self._timesheet_cache[key] = self._wb.read_table(
                sheet, cfg.TS_FIRST_DATA_ROW, None, cols
            )
        return self._timesheet_cache[key]

    def replace_timesheet(self, engineer: str, rows: Sequence[Sequence[CellValue]]
                          ) -> Dict[str, Any]:
        """Replace every data row on an engineer's sheet with ``rows``."""
        sheet_name = self.ts_sheet(engineer)
        width = col_to_index(cfg.TS_LAST_COLUMN)
        limit = cfg.TS_MAX_DATA_ROW - cfg.TS_FIRST_DATA_ROW + 1
        if len(rows) > limit:
            raise ValidationError([
                f"{len(rows):,} rows is more than the {limit:,} that Timesheet Raw "
                f"reads from each engineer's sheet."
            ])
        overflow = self._capacity_after(engineer, rows)
        date_col_index = self._date_column_index(engineer)
        xml_rows: List[str] = []
        for offset, values in enumerate(rows):
            row_no = cfg.TS_FIRST_DATA_ROW + offset
            cells: List[str] = []
            for index in range(1, width + 1):
                value = values[index - 1] if index - 1 < len(values) else None
                if value is None or value == "":
                    continue
                col = index_to_col(index)
                style = cfg.TS_DATE_STYLE if index == date_col_index else None
                cells.append(build_cell(f"{col}{row_no}", value, style))
            xml_rows.append(f'<row r="{row_no}" spans="1:{width}">{"".join(cells)}</row>')
        sheet = self._wb.sheet(sheet_name)
        sheet.replace_rows_from(cfg.TS_FIRST_DATA_ROW, xml_rows)
        last_row = cfg.TS_FIRST_DATA_ROW + len(xml_rows) - 1
        sheet.set_dimension(
            f"A1:{cfg.TS_LAST_COLUMN}{max(last_row, cfg.TS_HEADER_ROW)}")
        self._dirty = True
        self._timesheet_cache.clear()
        self._version += 1
        self._cache.clear()
        return {"engineer": engineer, "rows": len(xml_rows),
                "capacity_warnings": overflow}

    def _capacity_after(self, engineer: str, rows: Sequence[Sequence[CellValue]]
                        ) -> List[Dict[str, str]]:
        """What the caps would say once ``rows`` replace this engineer's sheet."""
        counts = dict(self.rows_per_engineer())
        counts[engineer] = len(rows)
        return capacity.messages(capacity.report(self._wb, counts))

    def _date_column_index(self, engineer: str) -> int:
        headers = self.timesheet_headers(engineer)
        for index, header in enumerate(headers, start=1):
            if header == cfg.TS_KEY_FIELDS["date"]:
                return index
        return 12  # column L, where the workbook's own formulas look

    # -- timesheet capacity ----------------------------------------------
    def rows_per_engineer(self) -> Dict[str, int]:
        """Dated rows on each TS sheet -- what the VSTACK actually stacks."""
        counts: Dict[str, int] = {}
        for short_name in self.ts_sheets():
            counts[short_name] = sum(
                1 for row in self.timesheet_rows(short_name, ["L"])
                if isinstance(row.get("L"), (int, float)) and row["L"] > 0
            )
        return counts

    def timesheet_capacity(self) -> Dict[str, Any]:
        """How close the timesheet is to the caps built into the workbook."""
        return self._cached(
            "capacity",
            lambda: capacity.report(self._wb, self.rows_per_engineer()),
        )

    def capacity_messages(self) -> List[Dict[str, str]]:
        return capacity.messages(self.timesheet_capacity())

    def extend_timesheet_capacity(self, *, raw_last_row: Optional[int] = None,
                                  source_last_row: Optional[int] = None
                                  ) -> Dict[str, Any]:
        """Raise the caps so every row reaches the calculations again."""
        current = self.timesheet_capacity()
        ceiling = current["max_raw_last_row"]
        if raw_last_row and raw_last_row > ceiling:
            raise ValidationError([
                f"{raw_last_row:,} is beyond what the stack can produce. The "
                f"three sheets can supply at most {ceiling:,} rows unless the "
                f"per-sheet limit is raised too."
            ])
        result = capacity.extend(self._wb, raw_last_row=raw_last_row,
                                 source_last_row=source_last_row)
        self._dirty = True
        self._formulas_changed = True
        self._version += 1
        self._cache.clear()
        return result

    # -- health ----------------------------------------------------------
    def data_check(self) -> Dict[str, Any]:
        """The equivalent of the Work Calendar DATA CHECK block, computed live."""
        engineers = {e.short_name: e for e in self.engineers()}
        per_engineer: Dict[str, Any] = {}
        total_rows = 0
        total_hours = 0.0
        first_date: Optional[_dt.date] = None
        last_date: Optional[_dt.date] = None
        unmatched = 0

        for short_name, sheet in self.ts_sheets().items():
            rows = self.timesheet_rows(short_name, ["B", "C", "L", "P"])
            hours = 0.0
            dates: List[_dt.date] = []
            bad_names = 0
            pattern = engineers.get(short_name)
            regex = _pattern_to_regex(pattern.pattern if pattern else f"*{short_name}*")
            for row in rows:
                value = row.get("P")
                if isinstance(value, (int, float)):
                    hours += float(value)
                serial = row.get("L")
                if isinstance(serial, (int, float)) and serial > 0:
                    dates.append(from_serial(float(serial)))
                name = row.get("C")
                if not (isinstance(name, str) and regex.match(name)):
                    bad_names += 1
            total_rows += len(rows)
            total_hours += hours
            unmatched += bad_names
            if dates:
                low, high = min(dates), max(dates)
                first_date = low if first_date is None else min(first_date, low)
                last_date = high if last_date is None else max(last_date, high)
            per_engineer[short_name] = {
                "sheet": sheet,
                "rows": len(rows),
                "hours": round(hours, 2),
                "first_date": iso(min(dates)) if dates else None,
                "last_date": iso(max(dates)) if dates else None,
                "rows_not_matching_pattern": bad_names,
            }

        known = {p.number for p in self.projects()} | set(self.non_project_codes())
        unknown_codes: Dict[str, int] = {}
        for short_name in self.ts_sheets():
            for row in self.timesheet_rows(short_name, ["B"]):
                code = as_text(row.get("B"))
                if code and code not in known:
                    unknown_codes[code] = unknown_codes.get(code, 0) + 1

        if total_rows == 0:
            verdict = "No timesheet data - import each engineer's export."
        elif unmatched:
            verdict = (
                f"Check names: {unmatched:,} row(s) do not match the engineer "
                "patterns on Work Calendar."
            )
        else:
            verdict = "All rows matched to an engineer."

        capacity_report = self.timesheet_capacity()
        capacity_warnings = capacity.messages(capacity_report)
        if any(w["level"] == "error" for w in capacity_warnings):
            verdict = capacity_warnings[0]["message"]

        return {
            "rows": total_rows,
            "hours": round(total_hours, 2),
            "first_date": iso(first_date),
            "last_date": iso(last_date),
            "rows_not_matching_pattern": unmatched,
            "verdict": verdict,
            "capacity": capacity_report,
            "capacity_warnings": capacity_warnings,
            "per_engineer": per_engineer,
            "unknown_job_numbers": sorted(
                ({"code": k, "rows": v} for k, v in unknown_codes.items()),
                key=lambda item: -item["rows"],
            ),
        }

    def register_issues(self) -> List[Dict[str, str]]:
        """Problems the workbook would flag in its own check columns."""
        issues: List[Dict[str, str]] = []
        numbers = {p.number for p in self.projects()}
        weights = self.weight_by_project()
        counts: Dict[str, int] = {}
        for deliverable in self.deliverables():
            counts[deliverable.project_number] = counts.get(
                deliverable.project_number, 0) + 1

        for project in self.projects():
            total = weights.get(project.number)
            if total is None:
                issues.append({
                    "level": "info",
                    "where": f"Inputs row {project.row}",
                    "message": (
                        f"{project.number} has no deliverables, so its progress "
                        f"falls back to the manual % on column O."
                    ),
                })
            elif abs(total - 1.0) > 1e-4:
                issues.append({
                    "level": "error",
                    "where": f"Deliverables ({project.number})",
                    "message": (
                        f"Phase weights for {project.number} total "
                        f"{total * 100:.1f}%, not 100%. Progress for this project "
                        f"is not meaningful until they do."
                    ),
                })

        for deliverable in self.deliverables():
            if deliverable.project_number not in numbers:
                issues.append({
                    "level": "error",
                    "where": f"Deliverables row {deliverable.row}",
                    "message": (
                        f"{deliverable.project_number} is not in the project "
                        f"register."
                    ),
                })
            total = sum(v for v in deliverable.shares.values() if v)
            if total and abs(total - 1.0) > 1e-4:
                issues.append({
                    "level": "error",
                    "where": f"Deliverables row {deliverable.row}",
                    "message": (
                        f"{deliverable.name or 'deliverable'}: the engineer split "
                        f"totals {total * 100:.1f}%, not 100%."
                    ),
                })
            elif not total:
                issues.append({
                    "level": "warning",
                    "where": f"Deliverables row {deliverable.row}",
                    "message": (
                        f"{deliverable.name or 'deliverable'} has no engineer "
                        f"split, so it earns nobody any credit."
                    ),
                })
            if deliverable.type_code and deliverable.step_no is not None:
                if self.credit_for(deliverable.type_code, deliverable.step_no) is None:
                    issues.append({
                        "level": "error",
                        "where": f"Deliverables row {deliverable.row}",
                        "message": (
                            f"Step {deliverable.step_no} is not valid for type "
                            f"{deliverable.type_code}."
                        ),
                    })
            if deliverable.ts_phase is None:
                issues.append({
                    "level": "warning",
                    "where": f"Deliverable Actuals row {deliverable.row}",
                    "message": (
                        f"{deliverable.name or 'deliverable'} has no TS Phase, so "
                        f"no timesheet hours can be attributed to it."
                    ),
                })
        return issues


def _pattern_to_regex(pattern: str) -> "re.Pattern":
    """Turn an Excel wildcard pattern such as ``*Ahmed*`` into a regex."""
    parts = [re.escape(part) for part in pattern.split("*")]
    return re.compile("^" + ".*".join(parts) + "$", re.IGNORECASE)
