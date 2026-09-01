"""Turn a monthly timesheet export into rows for a TS sheet.

The workbook's own instruction is to delete the old rows and paste the export
into cell A4 of ``TS Ahmed`` / ``TS Osama`` / ``TS Kirolos``, columns in exactly
the order of row 3.  Doing that by hand is where the month goes wrong: a column
shifts, a header row sneaks in, or one person's export lands on another's sheet.

This module reads the export, lines its columns up with row 3 by header name
rather than by position, coerces each value to the type the workbook's formulas
expect, and reports what it found before anything is written.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config as cfg
from .xlsx_io import CellValue, from_serial

#: How far into the file to look for the header row.
_HEADER_SEARCH_ROWS = 15

#: Headers that identify the export beyond doubt.
_SIGNATURE_HEADERS = {"jobnumber", "fullname", "totalhours", "date"}


def _normalise(header: Any) -> str:
    """Fold a header down to something comparable across exports."""
    return re.sub(r"[^a-z0-9]", "", str(header or "").lower())


class ImportError_(ValueError):
    """Raised when the uploaded file is not a timesheet export."""


@dataclass
class ParsedTimesheet:
    engineer: str
    source_name: str
    headers: List[str]
    rows: List[List[CellValue]]           # in TS sheet column order
    mapped: Dict[str, str] = field(default_factory=dict)   # export -> TS header
    unmapped_export_headers: List[str] = field(default_factory=list)
    missing_ts_headers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.rows)

    def preview(self, limit: int = 15) -> List[Dict[str, Any]]:
        """The first few rows, keyed by the columns a reviewer cares about."""
        wanted = ["Job Type", "JobNumber", "FullName", "Date", "Phase",
                  "RegularHours", "OvertimeHours", "TotalHours"]
        index = {h: i for i, h in enumerate(self.headers)}
        out: List[Dict[str, Any]] = []
        for row in self.rows[:limit]:
            record: Dict[str, Any] = {}
            for header in wanted:
                position = index.get(header)
                value = row[position] if position is not None and position < len(row) else None
                if isinstance(value, _dt.date):
                    value = value.isoformat()
                record[header] = value
            out.append(record)
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engineer": self.engineer,
            "source_name": self.source_name,
            "row_count": len(self.rows),
            "mapped_columns": len(self.mapped),
            "unmapped_export_headers": self.unmapped_export_headers,
            "missing_ts_headers": self.missing_ts_headers,
            "warnings": self.warnings,
            "errors": self.errors,
            "summary": self.summary,
            "preview": self.preview(),
        }


# --------------------------------------------------------------------------
# reading the uploaded file
# --------------------------------------------------------------------------

def _read_xlsx(data: bytes) -> List[List[Any]]:
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=True
        )
        try:
            sheet = book.worksheets[0]
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            book.close()


def _read_delimited(data: bytes) -> List[List[Any]]:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [list(row) for row in csv.reader(io.StringIO(text), dialect)]
    raise ImportError_("Could not decode the file as text.")


def read_grid(filename: str, data: bytes) -> List[List[Any]]:
    """Read an uploaded export into a plain grid of values."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if data[:2] == b"PK" or suffix in {"xlsx", "xlsm"}:
        return _read_xlsx(data)
    if suffix in {"csv", "tsv", "txt"} or b"," in data[:4096] or b"\t" in data[:4096]:
        return _read_delimited(data)
    raise ImportError_(
        f"{filename!r} is neither a spreadsheet nor a delimited text file."
    )


def find_header_row(grid: Sequence[Sequence[Any]]) -> int:
    """Locate the export's own header row, which may sit below a title block."""
    best_index, best_score = -1, 0
    for index, row in enumerate(grid[:_HEADER_SEARCH_ROWS]):
        cells = {_normalise(cell) for cell in row if cell not in (None, "")}
        score = len(cells & _SIGNATURE_HEADERS)
        if score > best_score:
            best_index, best_score = index, score
    if best_score < 2:
        raise ImportError_(
            "No header row found. The export needs its own column headings "
            "(JobNumber, FullName, Date, TotalHours) somewhere in the first "
            f"{_HEADER_SEARCH_ROWS} rows."
        )
    return best_index


# --------------------------------------------------------------------------
# coercion
# --------------------------------------------------------------------------

def _coerce(value: Any, header: str) -> CellValue:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    if header in cfg.TS_DATE_HEADERS:
        return _coerce_date(value)
    if header in cfg.TS_NUMERIC_HEADERS:
        return _coerce_number(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _coerce_date(value: Any) -> Optional[_dt.date]:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, (int, float)):
        return from_serial(float(value)) if value > 0 else None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S",
                "%d-%b-%Y", "%d-%b-%y", "%d.%m.%Y", "%m/%d/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M:%S", "%Y/%m/%d"):
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100.0
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# the import itself
# --------------------------------------------------------------------------

def parse(engineer: str, filename: str, data: bytes, ts_headers: Sequence[str],
          *, name_pattern: Optional[str] = None,
          known_job_numbers: Optional[Iterable[str]] = None) -> ParsedTimesheet:
    """Parse an export and line it up with the TS sheet's own column order."""
    grid = read_grid(filename, data)
    if not grid:
        raise ImportError_(f"{filename!r} is empty.")
    header_index = find_header_row(grid)
    export_headers = [str(cell).strip() if cell is not None else ""
                      for cell in grid[header_index]]

    ts_headers = list(ts_headers)
    ts_lookup = {_normalise(h): i for i, h in enumerate(ts_headers) if h}

    mapped: Dict[str, str] = {}
    positions: Dict[int, int] = {}          # export column -> TS column
    unmapped: List[str] = []
    for source_index, header in enumerate(export_headers):
        if not header:
            continue
        target = ts_lookup.get(_normalise(header))
        if target is None:
            unmapped.append(header)
            continue
        positions[source_index] = target
        mapped[header] = ts_headers[target]

    result = ParsedTimesheet(
        engineer=engineer,
        source_name=filename,
        headers=ts_headers,
        rows=[],
        mapped=mapped,
        unmapped_export_headers=unmapped,
        missing_ts_headers=[
            h for h in ts_headers if h and h not in set(mapped.values())
        ],
    )

    required = [cfg.TS_KEY_FIELDS[key] for key in
                ("job_number", "full_name", "date", "total_hours")]
    absent = [h for h in required if h not in set(mapped.values())]
    if absent:
        result.errors.append(
            "The export is missing column(s) the workbook needs: "
            + ", ".join(absent)
        )
        return result

    width = len(ts_headers)
    rows: List[List[CellValue]] = []
    blank_rows = 0
    for source_row in grid[header_index + 1:]:
        if not any(cell not in (None, "") for cell in source_row):
            blank_rows += 1
            continue
        row: List[CellValue] = [None] * width
        for source_index, target in positions.items():
            if source_index >= len(source_row):
                continue
            row[target] = _coerce(source_row[source_index], ts_headers[target])
        rows.append(row)
    result.rows = rows

    if not rows:
        result.errors.append("No data rows found below the header row.")
        return result

    _summarise(result, name_pattern, known_job_numbers)
    return result


def _summarise(result: ParsedTimesheet, name_pattern: Optional[str],
               known_job_numbers: Optional[Iterable[str]]) -> None:
    index = {h: i for i, h in enumerate(result.headers)}
    col_date = index[cfg.TS_KEY_FIELDS["date"]]
    col_hours = index[cfg.TS_KEY_FIELDS["total_hours"]]
    col_name = index[cfg.TS_KEY_FIELDS["full_name"]]
    col_job = index[cfg.TS_KEY_FIELDS["job_number"]]
    col_phase = index.get(cfg.TS_KEY_FIELDS["phase"])

    dates: List[_dt.date] = []
    hours = 0.0
    no_date = 0
    no_hours = 0
    wrong_person: Dict[str, int] = {}
    job_numbers: Dict[str, int] = {}
    people: Dict[str, int] = {}
    missing_phase = 0

    pattern = _wildcard(name_pattern) if name_pattern else None
    for row in result.rows:
        value = row[col_date]
        if isinstance(value, _dt.date):
            dates.append(value)
        else:
            no_date += 1
        total = row[col_hours]
        if isinstance(total, (int, float)):
            hours += float(total)
        else:
            no_hours += 1
        person = row[col_name]
        if isinstance(person, str) and person:
            people[person] = people.get(person, 0) + 1
            if pattern and not pattern.match(person):
                wrong_person[person] = wrong_person.get(person, 0) + 1
        job = row[col_job]
        if isinstance(job, str) and job:
            job_numbers[job] = job_numbers.get(job, 0) + 1
        if col_phase is not None and row[col_phase] is None:
            missing_phase += 1

    known = set(known_job_numbers or ())
    unknown = sorted(
        ({"code": code, "rows": count} for code, count in job_numbers.items()
         if code not in known),
        key=lambda item: -item["rows"],
    )

    result.summary = {
        "rows": len(result.rows),
        "hours": round(hours, 2),
        "first_date": min(dates).isoformat() if dates else None,
        "last_date": max(dates).isoformat() if dates else None,
        "months": sorted({d.strftime("%Y-%m") for d in dates}),
        "people": sorted(
            ({"name": n, "rows": c} for n, c in people.items()),
            key=lambda item: -item["rows"],
        ),
        "unknown_job_numbers": unknown,
        "rows_without_date": no_date,
        "rows_without_hours": no_hours,
        "rows_without_phase": missing_phase,
    }

    if wrong_person:
        listed = ", ".join(f"{name} ({count} rows)"
                           for name, count in sorted(wrong_person.items()))
        result.errors.append(
            f"This export contains rows for {listed}, which do not match "
            f"{result.engineer}'s pattern {name_pattern!r} on Work Calendar. "
            f"Each engineer's sheet must hold only their own rows."
        )
    if no_date:
        result.warnings.append(
            f"{no_date:,} row(s) have no usable date; the day-by-day and "
            f"dormancy calculations will ignore them."
        )
    if no_hours:
        result.warnings.append(f"{no_hours:,} row(s) have no TotalHours.")
    if missing_phase:
        result.warnings.append(
            f"{missing_phase:,} row(s) have no Phase, so they cannot be matched "
            f"to a deliverable on Deliverable Actuals."
        )
    if unknown:
        top = ", ".join(f"{item['code']} ({item['rows']})" for item in unknown[:6])
        more = "" if len(unknown) <= 6 else f", and {len(unknown) - 6} more"
        result.warnings.append(
            f"Job numbers charged but not in the project register: {top}{more}. "
            f"Their hours will not roll up to any project."
        )
    if result.unmapped_export_headers:
        result.warnings.append(
            f"{len(result.unmapped_export_headers)} export column(s) have no "
            f"matching column on the TS sheet and were skipped: "
            + ", ".join(result.unmapped_export_headers[:8])
        )


def _wildcard(pattern: str) -> "re.Pattern":
    parts = [re.escape(part) for part in pattern.split("*")]
    return re.compile("^" + ".*".join(parts) + "$", re.IGNORECASE)


def find_duplicates(existing: Sequence[Sequence[CellValue]],
                    incoming: Sequence[Sequence[CellValue]],
                    headers: Sequence[str]) -> int:
    """Count incoming rows that already appear in ``existing``.

    Only meaningful when appending; the monthly routine replaces instead.
    """
    index = {h: i for i, h in enumerate(headers)}
    keys = [index[cfg.TS_KEY_FIELDS[k]] for k in
            ("job_number", "date", "total_hours") if cfg.TS_KEY_FIELDS[k] in index]
    if cfg.TS_KEY_FIELDS["phase"] in index:
        keys.append(index[cfg.TS_KEY_FIELDS["phase"]])

    def key_of(row: Sequence[CellValue]) -> Tuple:
        return tuple(
            row[i].isoformat() if isinstance(row[i], _dt.date) else row[i]
            for i in keys if i < len(row)
        )

    seen = {key_of(row) for row in existing}
    return sum(1 for row in incoming if key_of(row) in seen)
