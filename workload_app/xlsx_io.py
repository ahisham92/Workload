"""Surgical read/write access to an .xlsx file.

The workload workbook carries 14 charts, drawings, threaded comments, x14
conditional formatting, data validations and a web extension.  Round-tripping
it through a general purpose writer silently drops most of that, so this module
edits the spreadsheet XML in place instead: every zip entry that we do not
explicitly touch is written back byte for byte.

Only two kinds of edit are needed:

* set the value of a single cell that already exists in the template
  (the input rows of ``Inputs``, ``Deliverables`` and ``Deliverable Actuals``
  are pre-formatted all the way down, so the ``<c>`` element and its style are
  already there and we only swap the value);
* replace a whole block of data rows (the three ``TS`` paste targets).
"""

from __future__ import annotations

import datetime as _dt
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

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

def to_serial(value: Union[_dt.date, _dt.datetime]) -> float:
    """Convert a date/datetime to the Excel serial number Excel stores."""
    if isinstance(value, _dt.datetime):
        days = (value.date() - _EPOCH).days
        seconds = value.hour * 3600 + value.minute * 60 + value.second
        return days + seconds / 86400.0
    return float((value - _EPOCH).days)


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


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _xml_unescape(text: str) -> str:
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
    )


def _format_number(value: Union[int, float]) -> str:
    if isinstance(value, bool):  # bool is a subclass of int; guard first
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(float(value))


# --------------------------------------------------------------------------
# building <c> elements
# --------------------------------------------------------------------------

def build_cell(ref: str, value: CellValue, style: Optional[str] = None) -> str:
    """Render a ``<c>`` element holding ``value``.

    Strings are written as inline strings so that the shared string table never
    has to be rewritten -- that table is referenced by every other sheet and is
    the easiest thing in an xlsx to corrupt.
    """
    attrs = f' r="{ref}"'
    if style is not None:
        attrs += f' s="{style}"'
    if value is None or (isinstance(value, str) and value == ""):
        return f"<c{attrs}/>"
    if isinstance(value, (_dt.datetime, _dt.date)):
        return f"<c{attrs}><v>{_format_number(to_serial(value))}</v></c>"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"<c{attrs}><v>{_format_number(value)}</v></c>"
    text = _xml_escape(str(value))
    return f'<c{attrs} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


# --------------------------------------------------------------------------
# sheet XML surgery
# --------------------------------------------------------------------------

class Sheet:
    """One worksheet's XML, parsed just far enough to edit cells.

    The sheet is split once into a head, an ordered list of ``<row>`` elements
    and a tail, and every lookup then works on a single row rather than
    re-scanning the whole document.  That matters: the timesheet sheets are
    several megabytes, and the registers are read cell by cell.  Reassembling
    the parts reproduces the original bytes exactly, whitespace included.
    """

    _ATTRS = r'(?:\s+[\w:.-]+="[^"]*")*\s*'
    _ROW_RE = re.compile(r'<row(?:\s+[\w:.-]+="[^"]*")*\s*(?:/>|>.*?</row>)', re.S)
    _ROW_NUM_RE = re.compile(r'<row\s[^>]*?\br="(\d+)"')
    _ROW_OPEN_RE = re.compile(r"<row\s[^>]*?>")
    _CELL_SCAN_RE = re.compile(
        r'<c(?P<attrs>(?:\s+[\w:.-]+="[^"]*")*)\s*(?:/>|>(?P<inner>.*?)</c>)', re.S
    )

    def __init__(self, name: str, xml: str):
        self.name = name
        self._parse(xml)

    # -- parsing ---------------------------------------------------------
    def _parse(self, xml: str) -> None:
        open_at = xml.find("<sheetData>")
        if open_at >= 0:
            body_start = open_at + len("<sheetData>")
            body_end = xml.find("</sheetData>")
            if body_end < 0:
                raise XlsxError(f"{self.name}: unterminated <sheetData>")
            self._head = xml[:body_start]
            self._tail = xml[body_end:]
            body = xml[body_start:body_end]
        else:
            empty_at = xml.find("<sheetData/>")
            if empty_at < 0:
                raise XlsxError(f"{self.name}: no <sheetData> element")
            self._head = xml[:empty_at] + "<sheetData>"
            self._tail = "</sheetData>" + xml[empty_at + len("<sheetData/>"):]
            body = ""

        # Each entry is [row number, row xml, the text that preceded it].
        self._rows: List[List[Any]] = []
        self._index: Dict[int, int] = {}
        position = 0
        for m in self._ROW_RE.finditer(body):
            num_m = self._ROW_NUM_RE.match(m.group(0))
            if num_m is None:
                continue
            number = int(num_m.group(1))
            self._index[number] = len(self._rows)
            self._rows.append([number, m.group(0), body[position:m.start()]])
            position = m.end()
        self._trailing = body[position:]
        self._shared_formulas: Optional[Dict[str, Tuple[str, str]]] = None

    @property
    def xml(self) -> str:
        parts = [self._head]
        for _number, row_xml, gap in self._rows:
            parts.append(gap)
            parts.append(row_xml)
        parts.append(self._trailing)
        parts.append(self._tail)
        return "".join(parts)

    @xml.setter
    def xml(self, value: str) -> None:
        self._parse(value)

    def _reindex(self) -> None:
        self._index = {row[0]: i for i, row in enumerate(self._rows)}

    # -- structure -------------------------------------------------------
    def row_numbers(self) -> List[int]:
        return [row[0] for row in self._rows]

    def row_xml(self, row: int) -> Optional[str]:
        position = self._index.get(row)
        return self._rows[position][1] if position is not None else None

    def _row_parts(self, row_xml: str) -> Tuple[str, str]:
        """Split a row into its opening tag and its body."""
        open_m = self._ROW_OPEN_RE.match(row_xml)
        if open_m is None:                     # self-closing <row .../>
            return row_xml[:-2].rstrip() + ">", ""
        return open_m.group(0), row_xml[open_m.end(): -len("</row>")]

    # -- cells -----------------------------------------------------------
    @classmethod
    def _cell_re(cls, ref: str) -> "re.Pattern":
        return re.compile(
            r'<c\s+r="%s"%s(?:/>|>.*?</c>)' % (re.escape(ref), cls._ATTRS), re.S
        )

    def find_cell(self, ref: str) -> Optional[str]:
        """Return the raw ``<c>`` element for ``ref``, or None."""
        _col, row = split_ref(ref)
        row_xml = self.row_xml(row)
        if row_xml is None:
            return None
        m = self._cell_re(ref).search(row_xml)
        return m.group(0) if m else None

    def cell_style(self, ref: str) -> Optional[str]:
        cell = self.find_cell(ref)
        if cell is None:
            return None
        m = re.search(r'\bs="(\d+)"', cell)
        return m.group(1) if m else None

    def cell_has_formula(self, ref: str) -> bool:
        cell = self.find_cell(ref)
        return bool(cell and "<f" in cell)

    def get_value(self, ref: str) -> CellValue:
        """Read a cell's stored value (the cached result for a formula cell)."""
        cell = self.find_cell(ref)
        return None if cell is None else value_from_cell(cell)

    def set_value(self, ref: str, value: CellValue, *, style: Optional[str] = None,
                  allow_formula_overwrite: bool = False) -> None:
        """Write ``value`` into ``ref``, keeping the cell's existing style.

        Refuses to overwrite a formula cell unless explicitly allowed, so a
        mis-specified column can never silently delete part of the model.
        """
        col, row = split_ref(ref)
        existing = self.find_cell(ref)
        if existing is not None and "<f" in existing and not allow_formula_overwrite:
            raise XlsxError(
                f"{self.name}!{ref} holds a formula; refusing to overwrite it"
            )
        if style is None and existing is not None:
            m = re.search(r'\bs="(\d+)"', existing)
            style = m.group(1) if m else None
        new_cell = build_cell(ref, value, style)

        position = self._index.get(row)
        if position is None:
            self._insert_row(row, new_cell)
            return
        open_tag, body = self._row_parts(self._rows[position][1])
        if existing is not None:
            body = self._cell_re(ref).sub(lambda _m: new_cell, body, count=1)
        else:
            body = self._insert_cell(body, col, new_cell)
        self._rows[position][1] = open_tag + body + "</row>"

    def _insert_cell(self, body: str, col: str, new_cell: str) -> str:
        target = col_to_index(col)
        for m in re.finditer(r'<c\s+r="([A-Z]{1,3})(\d+)"', body):
            if col_to_index(m.group(1)) > target:
                return body[: m.start()] + new_cell + body[m.start():]
        return body + new_cell

    def _insert_row(self, row: int, *cells: str) -> None:
        new_row = f'<row r="{row}">{"".join(cells)}</row>'
        for position, entry in enumerate(self._rows):
            if entry[0] > row:
                self._rows.insert(position, [row, new_row, ""])
                self._reindex()
                return
        self._rows.append([row, new_row, ""])
        self._index[row] = len(self._rows) - 1

    # -- bulk operations -------------------------------------------------
    def iter_cells(self, first_row: int = 1, last_row: Optional[int] = None,
                   columns: Optional[Iterable[str]] = None):
        """Yield ``(row_number, {column: <c> element})`` for a range of rows."""
        wanted = set(columns) if columns is not None else None
        for number, row_xml, _gap in self._rows:
            if number < first_row:
                continue
            if last_row is not None and number > last_row:
                break
            _open_tag, body = self._row_parts(row_xml)
            cells: Dict[str, str] = {}
            for m in self._CELL_SCAN_RE.finditer(body):
                ref_m = re.search(r'\br="([A-Z]{1,3})\d+"', m.group("attrs"))
                if ref_m is None:
                    continue
                col = ref_m.group(1)
                if wanted is not None and col not in wanted:
                    continue
                cells[col] = m.group(0)
            yield number, cells

    def replace_rows_from(self, first_row: int, rows: Sequence[str]) -> None:
        """Drop every row numbered ``first_row`` or higher and write ``rows``."""
        keep = [row for row in self._rows if row[0] < first_row]
        for row_xml in rows:
            num_m = self._ROW_NUM_RE.match(row_xml)
            number = int(num_m.group(1)) if num_m else (
                keep[-1][0] + 1 if keep else first_row)
            keep.append([number, row_xml, ""])
        self._rows = keep
        self._reindex()

    def set_dimension(self, ref: str) -> None:
        self._head = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="{ref}"/>',
                            self._head, count=1)

    # -- shared formulas -------------------------------------------------
    def shared_formula_masters(self) -> Dict[str, Tuple[str, str]]:
        """Map ``si`` -> (origin cell ref, formula text) for shared formulas."""
        if self._shared_formulas is None:
            masters: Dict[str, Tuple[str, str]] = {}
            pattern = re.compile(
                r'<c\s[^>]*?\br="([A-Z]{1,3}\d+)"[^>]*>\s*<f\s[^>]*?\bt="shared"'
                r'[^>]*?\bref="[^"]*"[^>]*?\bsi="(\d+)"[^>]*>(.*?)</f>', re.S
            )
            for _number, row_xml, _gap in self._rows:
                for m in pattern.finditer(row_xml):
                    masters.setdefault(m.group(2), (m.group(1), _xml_unescape(m.group(3))))
            self._shared_formulas = masters
        return self._shared_formulas


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
        self._entries: Dict[str, bytes] = {}
        self._order: List[str] = []
        self._infos: Dict[str, zipfile.ZipInfo] = {}
        with zipfile.ZipFile(self.path) as zf:
            for info in zf.infolist():
                self._order.append(info.filename)
                self._infos[info.filename] = info
                self._entries[info.filename] = zf.read(info.filename)
        self._sheet_paths = self._read_sheet_map()
        self._sheets: Dict[str, Sheet] = {}
        self._shared_strings: Optional[List[str]] = None

    # -- workbook parts --------------------------------------------------
    def _text(self, name: str) -> str:
        return self._entries[name].decode("utf-8")

    def _read_sheet_map(self) -> Dict[str, str]:
        wb = self._text("xl/workbook.xml")
        rels = self._text("xl/_rels/workbook.xml.rels")
        targets = {
            m.group(1): m.group(2)
            for m in re.finditer(r'Id="([^"]+)"[^>]*?Target="([^"]+)"', rels)
        }
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
            has_value = False
            for col in columns:
                cell = cells.get(col)
                record[col] = None
                if cell is None:
                    continue
                value = value_from_cell(cell, self.shared_strings)
                record[col] = value
                if value is not None and value != "":
                    has_value = True
            if has_value:
                out.append(record)
        return out

    # -- adding and removing sheets --------------------------------------
    def add_sheet(self, name: str, template: Optional[str] = None) -> str:
        """Add a worksheet, optionally copying another sheet's head and header.

        A new sheet needs four things registered, not one: the part itself, a
        content-type override for it, a relationship from the workbook, and an
        entry in the workbook's sheet list.
        """
        if name in self._sheet_paths:
            raise XlsxError(f"{self.path.name} already has a sheet called {name!r}")
        if len(name) > 31 or set(name) & set(r"[]:*?/\\"):
            raise XlsxError(
                f"{name!r} is not a usable sheet name (31 characters, and none "
                f"of []:*?/\\)"
            )

        numbers = [
            int(m.group(1))
            for path in self._sheet_paths.values()
            for m in [re.search(r"sheet(\d+)\.xml$", path)] if m
        ]
        target = f"xl/worksheets/sheet{max(numbers) + 1 if numbers else 1}.xml"
        while target in self._entries:
            numbers.append(max(numbers) + 1)
            target = f"xl/worksheets/sheet{max(numbers) + 1}.xml"

        self._entries[target] = self._new_sheet_xml(template).encode("utf-8")
        self._order.append(target)
        self._infos[target] = zipfile.ZipInfo(target, date_time=(1980, 1, 1, 0, 0, 0))

        ct = self._text("[Content_Types].xml")
        override = (
            f'<Override PartName="/{target}" ContentType="application/vnd'
            f'.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        self._entries["[Content_Types].xml"] = ct.replace(
            "</Types>", override + "</Types>").encode("utf-8")

        rels = self._text("xl/_rels/workbook.xml.rels")
        used = {int(m.group(1)) for m in re.finditer(r'Id="rId(\d+)"', rels)}
        rid = f"rId{max(used) + 1 if used else 1}"
        relationship = (
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org'
            f'/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/{target.rsplit("/", 1)[-1]}"/>'
        )
        self._entries["xl/_rels/workbook.xml.rels"] = rels.replace(
            "</Relationships>", relationship + "</Relationships>").encode("utf-8")

        wb = self._text("xl/workbook.xml")
        ids = {int(m.group(1)) for m in re.finditer(r'sheetId="(\d+)"', wb)}
        entry = (
            f'<sheet name="{_xml_escape(name)}" sheetId="{max(ids) + 1 if ids else 1}"'
            f' r:id="{rid}"/>'
        )
        self._entries["xl/workbook.xml"] = wb.replace(
            "</sheets>", entry + "</sheets>").encode("utf-8")

        self._sheet_paths[name] = target
        self._sheets.pop(name, None)
        return name

    def _new_sheet_xml(self, template: Optional[str]) -> str:
        head = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml'
            '/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships">'
        )
        rows = ""
        if template and template in self._sheet_paths:
            source = self.sheet(template)
            kept = [source.row_xml(number) for number in source.row_numbers()
                    if number <= 3]
            rows = "".join(r for r in kept if r)
            # The copied rows carry namespaced display hints (x14ac:dyDescent)
            # that this minimal sheet does not declare; they are decoration, so
            # drop them rather than pull the whole namespace list across.
            rows = re.sub(r'\s+[\w]+:[\w]+="[^"]*"', "", rows)
        return (
            f'{head}<dimension ref="A1"/><sheetViews><sheetView '
            f'workbookViewId="0"><pane ySplit="3" topLeftCell="A4" '
            f'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<sheetFormatPr defaultRowHeight="14.4"/><sheetData>{rows}'
            f'</sheetData><pageMargins left="0.7" right="0.7" top="0.75" '
            f'bottom="0.75" header="0.3" footer="0.3"/></worksheet>'
        )

    def rename_sheet(self, old: str, new: str) -> None:
        """Rename a worksheet and repoint every formula that names it."""
        if old not in self._sheet_paths:
            raise XlsxError(f"no sheet named {old!r}")
        if new in self._sheet_paths:
            raise XlsxError(f"{self.path.name} already has a sheet called {new!r}")
        wb = self._text("xl/workbook.xml")
        pattern = r'(<sheet\b[^>]*\bname=")%s(")' % re.escape(_xml_escape(old))
        wb, count = re.subn(pattern, lambda m: m.group(1) + _xml_escape(new) + m.group(2),
                            wb, count=1)
        if not count:
            raise XlsxError(f"could not find {old!r} in the workbook's sheet list")
        self._entries["xl/workbook.xml"] = wb.encode("utf-8")
        self._sheet_paths[new] = self._sheet_paths.pop(old)
        if old in self._sheets:
            sheet = self._sheets.pop(old)
            sheet.name = new
            self._sheets[new] = sheet

    def remove_sheet(self, name: str) -> None:
        """Remove a worksheet and every registration that points at it."""
        if name not in self._sheet_paths:
            raise XlsxError(f"no sheet named {name!r}")
        target = self._sheet_paths.pop(name)
        self._sheets.pop(name, None)
        self._entries.pop(target, None)
        if target in self._order:
            self._order.remove(target)
        self._infos.pop(target, None)

        ct = self._text("[Content_Types].xml")
        self._entries["[Content_Types].xml"] = re.sub(
            r'<Override PartName="/%s"[^>]*/>' % re.escape(target), "", ct
        ).encode("utf-8")

        wb = self._text("xl/workbook.xml")
        m = re.search(
            r'<sheet\b[^>]*name="%s"[^>]*/>' % re.escape(_xml_escape(name)), wb)
        if m:
            rid = re.search(r'r:id="([^"]+)"', m.group(0))
            wb = wb.replace(m.group(0), "")
            self._entries["xl/workbook.xml"] = wb.encode("utf-8")
            if rid:
                rels = self._text("xl/_rels/workbook.xml.rels")
                self._entries["xl/_rels/workbook.xml.rels"] = re.sub(
                    r'<Relationship Id="%s"[^>]*/>' % re.escape(rid.group(1)),
                    "", rels).encode("utf-8")

    # -- saving ----------------------------------------------------------
    def force_full_recalc(self) -> None:
        """Ask Excel to recalculate everything the next time it opens the file."""
        wb = self._text("xl/workbook.xml")
        if "<calcPr" in wb:
            def _patch(m: re.Match) -> str:
                tag = m.group(0)
                tag = re.sub(r'\s+fullCalcOnLoad="[^"]*"', "", tag)
                return tag[:-2].rstrip() + ' fullCalcOnLoad="1"/>'
            wb = re.sub(r"<calcPr\b[^>]*/>", _patch, wb, count=1)
        else:
            wb = wb.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')
        self._entries["xl/workbook.xml"] = wb.encode("utf-8")

    def drop_calc_chain(self) -> None:
        """Remove the calculation chain so Excel rebuilds it.

        Required whenever formula cells are added or removed: a stale chain
        makes Excel report the file as damaged.
        """
        name = "xl/calcChain.xml"
        if name not in self._entries:
            return
        del self._entries[name]
        self._order.remove(name)
        self._infos.pop(name, None)
        ct = self._text("[Content_Types].xml")
        ct = re.sub(r'<Override PartName="/xl/calcChain\.xml"[^>]*/>', "", ct)
        self._entries["[Content_Types].xml"] = ct.encode("utf-8")
        rels = self._text("xl/_rels/workbook.xml.rels")
        rels = re.sub(r'<Relationship[^>]*Target="calcChain\.xml"[^>]*/>', "", rels)
        self._entries["xl/_rels/workbook.xml.rels"] = rels.encode("utf-8")

    def save(self, path: Optional[Union[str, Path]] = None) -> Path:
        for name, sheet in self._sheets.items():
            self._entries[self._sheet_paths[name]] = sheet.xml.encode("utf-8")
        target = Path(path) if path else self.path
        tmp = target.with_suffix(target.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in self._order:
                info = self._infos[name]
                new_info = zipfile.ZipInfo(name, date_time=info.date_time)
                new_info.compress_type = zipfile.ZIP_DEFLATED
                new_info.external_attr = info.external_attr
                zf.writestr(new_info, self._entries[name])
        tmp.replace(target)
        return target

    def backup(self, backup_dir: Union[str, Path]) -> Path:
        """Copy the file on disk to a timestamped file in ``backup_dir``."""
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = backup_dir / f"{self.path.stem}-{stamp}{self.path.suffix}"
        shutil.copy2(self.path, dest)
        return dest
