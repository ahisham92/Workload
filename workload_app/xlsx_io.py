"""Read-only access to an .xlsx file's cells.

Used to bring a unit made in the workbook days across (``legacy.py``).  It
reads the sheet XML directly rather than through openpyxl so a large workbook
opens fast and a formula cell can be told apart from a typed value.
"""

from __future__ import annotations

import datetime as _dt
import re
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

#: Excel's day zero.  Excel wrongly treats 1900 as a leap year, so serials at or
#: above 60 are one higher than a plain day count; anchoring on 1899-12-30 gives
#: the right answer for every date from 1900-03-01 onwards.
_EPOCH = _dt.date(1899, 12, 30)

CellValue = Union[None, str, int, float, _dt.date, _dt.datetime]


class XlsxError(RuntimeError):
    """Raised when the workbook does not look the way the app expects."""


# --------------------------------------------------------------------------
# dates and cell references
# --------------------------------------------------------------------------

def from_serial(serial: float) -> _dt.date:
    """Convert an Excel serial number back to a date."""
    return _EPOCH + _dt.timedelta(days=int(serial))


def col_to_index(col: str) -> int:
    """``A`` -> 1, ``Z`` -> 26, ``AA`` -> 27."""
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def index_to_col(index: int) -> str:
    """1 -> ``A``, 27 -> ``AA``."""
    if index < 1:
        raise ValueError(f"column index out of range: {index}")
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


_REF_RE = re.compile(r"^([A-Z]{1,3})(\d+)$")


def split_ref(ref: str) -> Tuple[str, int]:
    """``AB12`` -> ``("AB", 12)``."""
    m = _REF_RE.match(ref)
    if not m:
        raise ValueError(f"not a cell reference: {ref!r}")
    return m.group(1), int(m.group(2))


def _xml_unescape(text: str) -> str:
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


# --------------------------------------------------------------------------
# sheet XML surgery
# --------------------------------------------------------------------------

class Sheet:
    """One worksheet's XML, split into rows once so a lookup reads one row.

    The timesheet sheets are several megabytes and the registers are read cell
    by cell, so re-scanning the whole document per cell would be slow.
    """

    _ROW_RE = re.compile(r'<row(?:\s+[\w:.-]+="[^"]*")*\s*(?:/>|>.*?</row>)', re.S)
    _ROW_NUM_RE = re.compile(r'<row\s[^>]*?\br="(\d+)"')
    _CELL_SCAN_RE = re.compile(
        r'<c(?P<attrs>(?:\s+[\w:.-]+="[^"]*")*)\s*(?:/>|>(?P<inner>.*?)</c>)', re.S
    )

    def __init__(self, name: str, xml: str):
        self.name = name
        if "<sheetData" not in xml:
            raise XlsxError(f"{name}: no <sheetData> element")
        self._rows: Dict[int, str] = {}
        for m in self._ROW_RE.finditer(xml):
            num_m = self._ROW_NUM_RE.match(m.group(0))
            if num_m is not None:
                self._rows[int(num_m.group(1))] = m.group(0)

    def row_xml(self, row: int) -> Optional[str]:
        return self._rows.get(row)

    def _cells(self, row_xml: str) -> Dict[str, str]:
        """``{column: <c> element}`` for one row."""
        cells: Dict[str, str] = {}
        for m in self._CELL_SCAN_RE.finditer(row_xml):
            ref_m = re.search(r'\br="([A-Z]{1,3})\d+"', m.group("attrs"))
            if ref_m is not None:
                cells[ref_m.group(1)] = m.group(0)
        return cells

    def find_cell(self, ref: str) -> Optional[str]:
        """Return the raw ``<c>`` element for ``ref``, or None."""
        col, row = split_ref(ref)
        row_xml = self.row_xml(row)
        return None if row_xml is None else self._cells(row_xml).get(col)

    def cell_has_formula(self, ref: str) -> bool:
        cell = self.find_cell(ref)
        return bool(cell and "<f" in cell)

    def get_value(self, ref: str) -> CellValue:
        """Read a cell's stored value (the cached result for a formula cell)."""
        cell = self.find_cell(ref)
        return None if cell is None else value_from_cell(cell)

    def iter_cells(self, first_row: int = 1, last_row: Optional[int] = None,
                   columns: Optional[Iterable[str]] = None):
        """Yield ``(row_number, {column: <c> element})`` for a range of rows."""
        wanted = set(columns) if columns is not None else None
        for number in sorted(self._rows):
            if number < first_row:
                continue
            if last_row is not None and number > last_row:
                break
            cells = self._cells(self._rows[number])
            if wanted is not None:
                cells = {c: v for c, v in cells.items() if c in wanted}
            yield number, cells


def value_from_cell(cell: str, shared_strings: Optional[Sequence[str]] = None
                    ) -> CellValue:
    """Decode one ``<c>`` element.

    Without ``shared_strings`` a shared-string cell yields its raw index, which
    is why :meth:`Workbook.get_value` is the one to reach for outside this
    module.
    """
    inline = re.search(r"<is>.*?<t[^>]*>(.*?)</t>.*?</is>", cell, re.S)
    if inline:
        return _xml_unescape(inline.group(1))
    m = re.search(r"<v>(.*?)</v>", cell, re.S)
    if not m:
        return None
    raw = _xml_unescape(m.group(1))
    if raw == "":
        return None
    if 't="s"' in cell:
        if shared_strings is None:
            return raw
        try:
            return shared_strings[int(float(raw))]
        except (ValueError, IndexError):
            return None
    if 't="str"' in cell or 't="e"' in cell or 't="inlineStr"' in cell:
        return raw
    try:
        return float(raw)
    except ValueError:
        return raw


class Workbook:
    """An xlsx file held in memory as its zip entries."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as zf:
            self._entries: Dict[str, bytes] = {
                name: zf.read(name) for name in zf.namelist()}
        self._sheet_paths = self._read_sheet_map()
        self._sheets: Dict[str, Sheet] = {}
        self._shared_strings: Optional[List[str]] = None

    # -- workbook parts --------------------------------------------------
    def _text(self, name: str) -> str:
        return self._entries[name].decode("utf-8")

    def _read_sheet_map(self) -> Dict[str, str]:
        wb = self._text("xl/workbook.xml")
        rels = self._text("xl/_rels/workbook.xml.rels")
        targets = {}
        for m in re.finditer(r"<Relationship\b[^>]*>", rels):
            rid = re.search(r'\bId="([^"]+)"', m.group(0))
            target = re.search(r'\bTarget="([^"]+)"', m.group(0))
            if rid and target:
                targets[rid.group(1)] = target.group(1)
        sheets: Dict[str, str] = {}
        for m in re.finditer(r"<sheet\b[^>]*/>", wb):
            tag = m.group(0)
            name = re.search(r'name="([^"]*)"', tag)
            rid = re.search(r'r:id="([^"]*)"', tag)
            if not (name and rid):
                continue
            target = targets[rid.group(1)].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            sheets[_xml_unescape(name.group(1))] = target
        return sheets

    @property
    def sheet_names(self) -> List[str]:
        return list(self._sheet_paths)

    def sheet(self, name: str) -> Sheet:
        if name not in self._sheets:
            if name not in self._sheet_paths:
                raise XlsxError(f"no sheet named {name!r} in {self.path.name}")
            self._sheets[name] = Sheet(name, self._text(self._sheet_paths[name]))
        return self._sheets[name]

    # -- shared strings --------------------------------------------------
    @property
    def shared_strings(self) -> List[str]:
        if self._shared_strings is None:
            if "xl/sharedStrings.xml" not in self._entries:
                self._shared_strings = []
            else:
                xml = self._text("xl/sharedStrings.xml")
                out: List[str] = []
                for si in re.finditer(r"<si>(.*?)</si>", xml, re.S):
                    parts = re.findall(r"<t[^>]*>(.*?)</t>", si.group(1), re.S)
                    out.append(_xml_unescape("".join(parts)))
                self._shared_strings = out
        return self._shared_strings

    def get_value(self, sheet: str, ref: str) -> CellValue:
        """Read a cell, resolving shared-string indexes to real text."""
        cell = self.sheet(sheet).find_cell(ref)
        if cell is None:
            return None
        return value_from_cell(cell, self.shared_strings)

    def get_text(self, sheet: str, ref: str) -> str:
        value = self.get_value(sheet, ref)
        if value is None:
            return ""
        if isinstance(value, float) and value == int(value):
            return str(int(value))
        return str(value)

    def get_number(self, sheet: str, ref: str) -> Optional[float]:
        value = self.get_value(sheet, ref)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None

    def get_date(self, sheet: str, ref: str) -> Optional[_dt.date]:
        value = self.get_number(sheet, ref)
        if value is None or value <= 0:
            return None
        return from_serial(value)

    def read_table(self, sheet: str, first_row: int, last_row: Optional[int],
                   columns: Iterable[str]) -> List[Dict[str, CellValue]]:
        """Read a rectangular block as ``[{"__row__": n, "A": value, ...}]``.

        Blank rows are skipped.  Values are resolved the same way
        :meth:`get_value` resolves them, shared strings included.
        """
        columns = list(columns)
        out: List[Dict[str, CellValue]] = []
        sh = self.sheet(sheet)
        for number, cells in sh.iter_cells(first_row, last_row, columns):
            record: Dict[str, CellValue] = {"__row__": number}
            for col in columns:
                cell = cells.get(col)
                record[col] = (None if cell is None
                               else value_from_cell(cell, self.shared_strings))
            if any(record[col] not in (None, "") for col in columns):
                out.append(record)
        return out
