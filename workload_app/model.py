"""The records a unit is made of, and the rules for reading values into them.

Nothing here knows where a unit is kept.  ``unit.py`` keeps them in the unit's
own database; ``legacy.py`` reads them once out of an old Workload workbook so
a unit made before the database can be brought across.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence

from . import config as cfg
from .xlsx_io import from_serial


class ValidationError(ValueError):
    """Raised when a change would break one of the unit's own rules."""

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
    if len(text) > 10 and text[4] == "-":
        try:
            return _dt.date.fromisoformat(text[:10])
        except ValueError:
            pass
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


def today() -> _dt.date:
    """Today, which the tests -- and a demo -- can pin with ``WORKLOAD_TODAY``."""
    pinned = os.environ.get("WORKLOAD_TODAY")
    if pinned:
        try:
            return _dt.date.fromisoformat(pinned)
        except ValueError:
            pass
    return _dt.date.today()


def pattern_to_regex(pattern: str) -> "re.Pattern":
    """Turn a wildcard pattern such as ``*Ahmed*`` into a regex."""
    parts = [re.escape(part) for part in pattern.split("*")]
    return re.compile("^" + ".*".join(parts) + "$", re.IGNORECASE)


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

@dataclass
class Project:
    #: The project's id in the unit.  Never reused once a project is deleted.
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
    #: The deliverable's id in the unit.  Tasks, drawings and the submissions
    #: plan all point at it, so it is never handed to another deliverable.
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
    #: Where they come in the team's order, which the screens colour by.
    slot: Optional[int] = None
    sheet: str = ""
    rows: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "short_name": self.short_name, "pattern": self.pattern,
            "available_hours": self.available_hours,
            "availability": self.availability, "slot": self.slot,
            "sheet": self.sheet, "rows": self.rows,
        }
