"""The Workload workbook as an editable domain model.

The workbook stays the single source of truth: there is no separate database to
fall out of step with it.  This module reads the registers, validates changes
against the workbook's own rules, and writes them back into the input cells.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from . import actuals_block, config as cfg
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
    manual_share_ahmed: Optional[float] = None
    manual_share_osama: Optional[float] = None
    manual_share_kirolos: Optional[float] = None

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
            "manual_share_ahmed": self.manual_share_ahmed,
            "manual_share_osama": self.manual_share_osama,
            "manual_share_kirolos": self.manual_share_kirolos,
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
    share_ahmed: Optional[float] = None
    share_osama: Optional[float] = None
    share_kirolos: Optional[float] = None
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
            "share_ahmed": self.share_ahmed,
            "share_osama": self.share_osama,
            "share_kirolos": self.share_kirolos,
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
        cols = cfg.ENGINEER_COLUMNS
        years = self._availability_years()
        out: List[Engineer] = []
        for short_name, row in cfg.ENGINEER_ROWS.items():
            name = self._wb.get_text(cfg.SHEET_CALENDAR, f"{cols['short_name']}{row}")
            out.append(Engineer(
                short_name=name or short_name,
                pattern=self._wb.get_text(cfg.SHEET_CALENDAR, f"{cols['pattern']}{row}"),
                available_hours=self._wb.get_number(
                    cfg.SHEET_CALENDAR, f"{cols['available_hours']}{row}"),
                availability=self._availability_for(short_name, years),
            ))
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

    def _availability_for(self, short_name: str, years: Dict[str, int]) -> Dict[int, float]:
        row = cfg.AVAILABILITY_ROWS.get(short_name)
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
            },
        }

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
                manual_share_ahmed=self._wb.get_number(
                    cfg.SHEET_INPUTS, f"{cols['manual_share_ahmed']}{row}"),
                manual_share_osama=self._wb.get_number(
                    cfg.SHEET_INPUTS, f"{cols['manual_share_osama']}{row}"),
                manual_share_kirolos=self._wb.get_number(
                    cfg.SHEET_INPUTS, f"{cols['manual_share_kirolos']}{row}"),
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

        shares = {
            key: as_fraction(data.get(f"manual_share_{key}"))
            for key in ("ahmed", "osama", "kirolos")
        }
        for key, value in shares.items():
            if value is not None and not 0 <= value <= 1:
                errors.append(f"{key.title()}'s fallback share must be 0-100%.")
        given = [v for v in shares.values() if v]
        if given and abs(sum(given) - 1.0) > 1e-4:
            errors.append(
                "The fallback split must total 100% (it is used only while the "
                "deliverables carry no split of their own)."
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
            manual_share_ahmed=shares["ahmed"],
            manual_share_osama=shares["osama"],
            manual_share_kirolos=shares["kirolos"],
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
            "manual_share_ahmed": project.manual_share_ahmed,
            "manual_share_osama": project.manual_share_osama,
            "manual_share_kirolos": project.manual_share_kirolos,
        }
        for name, col in cols.items():
            self._set(cfg.SHEET_INPUTS, f"{col}{row}", values[name])

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
                share_ahmed=self._wb.get_number(
                    cfg.SHEET_DELIVERABLES, f"{cols['share_ahmed']}{row}"),
                share_osama=self._wb.get_number(
                    cfg.SHEET_DELIVERABLES, f"{cols['share_osama']}{row}"),
                share_kirolos=self._wb.get_number(
                    cfg.SHEET_DELIVERABLES, f"{cols['share_kirolos']}{row}"),
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

    def validate_deliverable(self, data: Dict[str, Any], *, row: Optional[int] = None
                             ) -> Tuple[Deliverable, List[str]]:
        errors: List[str] = []
        project_number = as_text(data.get("project_number"))
        if not project_number:
            errors.append("Pick the project this deliverable belongs to.")
        elif self.project(project_number) is None:
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

        shares = {
            key: as_fraction(data.get(f"share_{key}"))
            for key in ("ahmed", "osama", "kirolos")
        }
        for key, value in shares.items():
            if value is not None and not 0 <= value <= 1:
                errors.append(f"{key.title()}'s share must be between 0% and 100%.")
        total = sum(v for v in shares.values() if v)
        if total and abs(total - 1.0) > 1e-4:
            errors.append(
                f"Ahmed / Osama / Kirolos must total 100% on a deliverable "
                f"(they total {total * 100:.1f}%)."
            )

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
            share_ahmed=shares["ahmed"],
            share_osama=shares["osama"],
            share_kirolos=shares["kirolos"],
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
            "share_ahmed": deliverable.share_ahmed,
            "share_osama": deliverable.share_osama,
            "share_kirolos": deliverable.share_kirolos,
            "notes": deliverable.notes,
        }
        for name, col in cols.items():
            self._set(cfg.SHEET_DELIVERABLES, f"{col}{row}", values[name])

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
        if row <= self.actuals_last_row():
            for col in cfg.ACTUALS_INPUT_COLUMNS.values():
                self._set(cfg.SHEET_ACTUALS, f"{col}{row}", None)

    def delete_deliverable(self, row: int) -> Dict[str, Any]:
        if self.deliverable(row) is None:
            raise ValidationError([f"No deliverable on Deliverables row {row}."])
        self._clear_deliverable_row(row)
        return {"row": row}

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
        sheet = cfg.TS_SHEETS[engineer]
        headers: List[str] = []
        for index in range(1, col_to_index(cfg.TS_LAST_COLUMN) + 1):
            col = index_to_col(index)
            headers.append(self._wb.get_text(sheet, f"{col}{cfg.TS_HEADER_ROW}"))
        return headers

    def timesheet_rows(self, engineer: str,
                       columns: Optional[Iterable[str]] = None
                       ) -> List[Dict[str, CellValue]]:
        """Read one engineer's pasted export."""
        sheet = cfg.TS_SHEETS[engineer]
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
        if engineer not in cfg.TS_SHEETS:
            raise ValidationError([f"{engineer!r} is not one of the three engineers."])
        width = col_to_index(cfg.TS_LAST_COLUMN)
        limit = cfg.TS_MAX_DATA_ROW - cfg.TS_FIRST_DATA_ROW + 1
        if len(rows) > limit:
            raise ValidationError([
                f"{len(rows):,} rows is more than the {limit:,} that Timesheet Raw "
                f"reads from each engineer's sheet."
            ])
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
        sheet = self._wb.sheet(cfg.TS_SHEETS[engineer])
        sheet.replace_rows_from(cfg.TS_FIRST_DATA_ROW, xml_rows)
        last_row = cfg.TS_FIRST_DATA_ROW + len(xml_rows) - 1
        sheet.set_dimension(
            f"A1:{cfg.TS_LAST_COLUMN}{max(last_row, cfg.TS_HEADER_ROW)}")
        self._dirty = True
        self._timesheet_cache.clear()
        return {"engineer": engineer, "rows": len(xml_rows)}

    def _date_column_index(self, engineer: str) -> int:
        headers = self.timesheet_headers(engineer)
        for index, header in enumerate(headers, start=1):
            if header == cfg.TS_KEY_FIELDS["date"]:
                return index
        return 12  # column L, where the workbook's own formulas look

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

        for short_name, sheet in cfg.TS_SHEETS.items():
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
        for short_name in cfg.TS_SHEETS:
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

        return {
            "rows": total_rows,
            "hours": round(total_hours, 2),
            "first_date": iso(first_date),
            "last_date": iso(last_date),
            "rows_not_matching_pattern": unmatched,
            "verdict": verdict,
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
            total = sum(
                v for v in (deliverable.share_ahmed, deliverable.share_osama,
                            deliverable.share_kirolos) if v
            )
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
