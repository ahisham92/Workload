"""Grow the ``Deliverable Actuals`` calculation block.

``Deliverable Actuals`` is aligned row-for-row with the deliverable register but
ships only as far as row 68, which is exactly the 64 deliverables already in the
workbook.  Adding a 65th therefore needs the block extended first, otherwise the
new deliverable has no actual hours, no first/last charge date and no dormancy.

The extension clones the last data row, translating its formulas down, and grows
every range that is anchored to the old last row -- formulas, conditional
formatting and the x14 extension list alike.  Nothing else on the sheet moves.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from openpyxl.formula.translate import Translator

from .xlsx_io import Sheet, XlsxError, _xml_escape, _xml_unescape

#: Ranges written as ``$A$5:$A$68``.  The lookbehind keeps qualified references
#: such as ``'Work Calendar'!$E$6:$E$200`` out of the rewrite.
_BLOCK_RANGE_RE_TEMPLATE = r"(?<![!\w])\$([A-Z]{{1,3}})\$(\d+):\$\1\$({last})(?!\d)"

_CELL_RE = re.compile(
    r'<c(?P<attrs>(?:\s+[\w:.-]+="[^"]*")*)\s*(?:/>|>(?P<inner>.*?)</c>)', re.S
)
_ATTR_RE = re.compile(r'([\w:.-]+)="([^"]*)"')
_F_RE = re.compile(r"<f(?P<attrs>(?:\s+[\w:.-]+=\"[^\"]*\")*)\s*(?:/>|>(?P<text>.*?)</f>)", re.S)


def detect_last_row(sheet: Sheet, first_row: int) -> int:
    """Find the row the block's own ranges currently stop at."""
    ends = [
        int(m.group(2))
        for m in re.finditer(
            r"(?<![!\w])\$([A-Z]{1,3})\$%d:\$\1\$(\d+)" % first_row, sheet.xml
        )
    ]
    if not ends:
        raise XlsxError(f"{sheet.name}: cannot tell where the block ends")
    # Every range in the block shares the same end row; a stray outlier loses
    # to the majority.
    return max(set(ends), key=ends.count)


def _split_attrs(attrs: str) -> List[Tuple[str, str]]:
    return _ATTR_RE.findall(attrs)


def _clone_row(sheet: Sheet, template_row: int, target_row: int,
               blank_columns: set) -> str:
    """Render ``template_row`` as ``target_row``, translating every formula."""
    raw = sheet.row_xml(template_row)
    if raw is None:
        raise XlsxError(f"{sheet.name}: template row {template_row} is missing")
    masters = sheet.shared_formula_masters()

    open_m = re.match(r"<row(?:\s+[\w:.-]+=\"[^\"]*\")*\s*>", raw)
    if open_m is None:
        raise XlsxError(f"{sheet.name}: row {template_row} is empty")
    open_tag = open_m.group(0)
    open_tag = re.sub(r'\br="\d+"', f'r="{target_row}"', open_tag)
    open_tag = re.sub(r'\s+x14ac:dyDescent="[^"]*"', "", open_tag)
    body = raw[open_m.end(): -len("</row>")]

    cells: List[str] = []
    for m in _CELL_RE.finditer(body):
        attrs = dict(_split_attrs(m.group("attrs")))
        ref = attrs.get("r")
        if not ref:
            continue
        col = re.match(r"([A-Z]{1,3})", ref).group(1)
        new_ref = f"{col}{target_row}"
        style = attrs.get("s")
        keep = f' r="{new_ref}"' + (f' s="{style}"' if style else "")

        inner = m.group("inner") or ""
        f_m = _F_RE.search(inner)
        if f_m is None or col in blank_columns:
            # A typed-in cell: carry the formatting down but leave it empty.
            cells.append(f"<c{keep}/>")
            continue

        f_attrs = dict(_split_attrs(f_m.group("attrs")))
        text = f_m.group("text") or ""
        kind = f_attrs.get("t")

        if kind == "shared":
            si = f_attrs.get("si")
            if si is None or si not in masters:
                raise XlsxError(
                    f"{sheet.name}!{ref}: shared formula si={si} has no master"
                )
            origin, master_text = masters[si]
            formula = Translator("=" + master_text, origin=origin).translate_formula(
                new_ref
            )
            new_f = f"<f>{_xml_escape(formula[1:])}</f>"
        elif kind == "array":
            formula = Translator(
                "=" + _xml_unescape(text), origin=ref
            ).translate_formula(new_ref)
            extra = ' ca="1"' if f_attrs.get("ca") == "1" else ""
            new_f = (
                f'<f t="array" ref="{new_ref}"{extra}>'
                f"{_xml_escape(formula[1:])}</f>"
            )
        else:
            formula = Translator(
                "=" + _xml_unescape(text), origin=ref
            ).translate_formula(new_ref)
            extra = ' ca="1"' if f_attrs.get("ca") == "1" else ""
            new_f = f"<f{extra}>{_xml_escape(formula[1:])}</f>"

        cm = attrs.get("cm")
        if cm:
            keep += f' cm="{cm}"'
        # The cached <v> is deliberately dropped; the workbook is saved with
        # fullCalcOnLoad so Excel fills these in when the file is opened.
        cells.append(f"<c{keep}>{new_f}</c>")

    return open_tag + "".join(cells) + "</row>"


def extend(sheet: Sheet, *, first_row: int, template_row: int, new_last_row: int,
           blank_columns: set, last_row: Optional[int] = None) -> int:
    """Grow the block so it reaches ``new_last_row``.  Returns the new last row."""
    current = last_row if last_row is not None else detect_last_row(sheet, first_row)
    if new_last_row <= current:
        return current

    rows = [
        _clone_row(sheet, template_row, row, blank_columns)
        for row in range(current + 1, new_last_row + 1)
    ]
    sheet.replace_rows_from(current + 1, rows)

    # Grow every range anchored to the old end row: formulas first...
    pattern = re.compile(_BLOCK_RANGE_RE_TEMPLATE.format(last=current))
    sheet.xml = pattern.sub(
        lambda m: f"${m.group(1)}${m.group(2)}:${m.group(1)}${new_last_row}", sheet.xml
    )
    # ...then conditional formatting and the x14 extension list, which use
    # unanchored A1-style ranges such as ``R5:R68``.
    sqref = re.compile(
        r"\b([A-Z]{1,3})(%d):\1(%d)\b" % (first_row, current)
    )
    sheet.xml = sqref.sub(
        lambda m: f"{m.group(1)}{first_row}:{m.group(1)}{new_last_row}", sheet.xml
    )

    m = re.search(r'<dimension ref="([A-Z]+\d+):([A-Z]+)\d+"/>', sheet.xml)
    if m:
        sheet.set_dimension(f"{m.group(1)}:{m.group(2)}{new_last_row}")
    return new_last_row
