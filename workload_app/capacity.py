"""The two row caps on the consolidated timesheet, and how to lift them.

``Timesheet Raw`` builds itself from the three TS sheets with

    VSTACK('TS Ahmed'!A4:P6000, 'TS Osama'!A4:P6000, 'TS Kirolos'!A4:P6000)

filtered down to the rows that carry a date.  Two limits follow from that, and
neither announces itself:

* each engineer's sheet is read only as far as row 6000;
* every formula that consumes the consolidated view -- and there are close to
  ninety thousand of them -- reads ``Timesheet Raw`` rows 4 to 8000 only.

Once the three sheets together hold more rows than the second cap allows, the
surplus still appears on ``Timesheet Raw`` but no longer reaches a single
calculation.  The stack is built in sheet order, so it is the *last* engineer --
Kirolos -- whose rows fall off the end, and nothing in the workbook says so.

This module measures both caps, reports how close the workbook is to them, and
lifts them when asked.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from openpyxl.formula.translate import Translator

from . import config as cfg
from .xlsx_io import Workbook, XlsxError, _xml_escape, _xml_unescape

def stack_order(wb: Workbook) -> List[str]:
    """The TS sheets in the order Timesheet Raw stacks them.

    This is what decides whose rows fall off the end when the cap is exceeded,
    so it is read from the formula rather than assumed.
    """
    formula = _formula(wb, cfg.SHEET_TS_RAW, "A4") or ""
    found = re.findall(r"'([^']+)'!\$[A-Z]{1,2}\$\d+", formula)
    ordered: List[str] = []
    for name in found:
        if name.startswith(cfg.TS_SHEET_PREFIX) and name not in ordered:
            ordered.append(name)
    if ordered:
        return ordered
    return [n for n in wb.sheet_names if n.startswith(cfg.TS_SHEET_PREFIX)]


def source_limit(wb: Workbook) -> int:
    """The last row of each TS sheet that the VSTACK reads."""
    formula = _formula(wb, cfg.SHEET_TS_RAW, "A4")
    if formula:
        ends = [int(n) for n in re.findall(r"!\$[A-Z]{1,2}\$4:\$[A-Z]{1,2}\$(\d+)", formula)]
        if ends:
            return min(ends)
    return cfg.TS_SOURCE_DEFAULT_LAST_ROW


def raw_limit(wb: Workbook) -> int:
    """The last row of ``Timesheet Raw`` that the workbook's formulas read."""
    sheet, ref = cfg.TS_RAW_LIMIT_PROBE
    formula = _formula(wb, sheet, ref)
    if formula:
        m = re.search(
            r"'?%s'?!\$[A-Z]{1,2}\$%d:\$[A-Z]{1,2}\$(\d+)"
            % (re.escape(cfg.SHEET_TS_RAW), cfg.TS_RAW_FIRST_DATA_ROW),
            formula,
        )
        if m:
            return int(m.group(1))
    return cfg.TS_RAW_DEFAULT_LAST_ROW


def _formula(wb: Workbook, sheet: str, ref: str) -> Optional[str]:
    cell = wb.sheet(sheet).find_cell(ref)
    if not cell:
        return None
    m = re.search(r"<f[^>]*>(.*?)</f>", cell, re.S)
    return _xml_unescape(m.group(1)) if m else None


def report(wb: Workbook, rows_per_engineer: Dict[str, int],
           order: Optional[List[str]] = None) -> Dict[str, Any]:
    """How much of each cap is used, and who loses rows if it is exceeded."""
    order = order or [
        name[len(cfg.TS_SHEET_PREFIX):] for name in stack_order(wb)
    ]
    order = [name for name in order if name in rows_per_engineer] + [
        name for name in rows_per_engineer if name not in order
    ]
    source = source_limit(wb)
    raw = raw_limit(wb)
    per_sheet_capacity = source - cfg.TS_FIRST_DATA_ROW + 1
    total_capacity = raw - cfg.TS_RAW_FIRST_DATA_ROW + 1
    used = sum(rows_per_engineer.get(name, 0) for name in order)

    # Walk the stack in order to see whose rows fall past the cap.
    running = 0
    cut_off: List[Dict[str, Any]] = []
    for name in order:
        count = rows_per_engineer.get(name, 0)
        if running + count > total_capacity:
            lost = min(count, running + count - total_capacity)
            cut_off.append({"engineer": name, "rows_lost": lost, "rows": count})
        running += count

    per_sheet = {
        name: {
            "rows": rows_per_engineer.get(name, 0),
            "capacity": per_sheet_capacity,
            "headroom": per_sheet_capacity - rows_per_engineer.get(name, 0),
            "over": rows_per_engineer.get(name, 0) > per_sheet_capacity,
        }
        for name in order
    }

    headroom = total_capacity - used
    return {
        "source_last_row": source,
        "raw_last_row": raw,
        "per_sheet_capacity": per_sheet_capacity,
        "total_capacity": total_capacity,
        "rows_used": used,
        "headroom": headroom,
        "over_capacity": headroom < 0,
        "low_headroom": 0 <= headroom < cfg.TS_RAW_HEADROOM_WARNING,
        "cut_off": cut_off,
        "per_sheet": per_sheet,
        "stack_order": list(order),
        "suggested_raw_last_row": suggest_raw_last_row(used, raw),
        "suggested_source_last_row": max(source, cfg.TS_SOURCE_TARGET_LAST_ROW),
        "source_is_short": source < cfg.TS_SOURCE_TARGET_LAST_ROW,
        "max_raw_last_row": (cfg.TS_RAW_FIRST_DATA_ROW
                             + len(order) * per_sheet_capacity - 1),
    }


def suggest_raw_last_row(rows_used: int, current: int, *, years: int = 3) -> int:
    """A cap with a few years of headroom, rounded to a tidy number.

    The helper columns on ``Timesheet Raw`` cost roughly the square of the cap
    to recalculate, so this deliberately does not reach for the maximum.
    """
    growth_per_year = 1500        # ~500 rows a year each, for three engineers
    wanted = rows_used + years * growth_per_year + cfg.TS_RAW_FIRST_DATA_ROW
    return max(current, int(round(wanted / 1000.0)) * 1000)


def messages(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Plain-language warnings for the report above."""
    out: List[Dict[str, str]] = []
    if data["over_capacity"]:
        lost = ", ".join(
            f"{c['engineer']} ({c['rows_lost']:,} of {c['rows']:,} rows)"
            for c in data["cut_off"]
        )
        out.append({
            "level": "error",
            "message": (
                f"The timesheet has outgrown the workbook. Every calculation "
                f"reads {cfg.SHEET_TS_RAW} rows "
                f"{cfg.TS_RAW_FIRST_DATA_ROW}-{data['raw_last_row']:,} "
                f"({data['total_capacity']:,} rows) but the sheets hold "
                f"{data['rows_used']:,}, so the surplus belongs to {lost}. "
                f"Those hours are on the sheet but reach nothing — no project, "
                f"no dashboard, no CPI. Raise the limit to at least "
                f"{data['suggested_raw_last_row']:,}."
            ),
        })
    elif data["low_headroom"]:
        out.append({
            "level": "warning",
            "message": (
                f"Only {data['headroom']:,} rows left before the timesheet "
                f"outgrows the workbook ({data['rows_used']:,} of "
                f"{data['total_capacity']:,} used). Past that point the newest "
                f"rows stop counting. Raise the limit to "
                f"{data['suggested_raw_last_row']:,} before the next import."
            ),
        })
    for name, sheet in data["per_sheet"].items():
        if sheet["over"]:
            out.append({
                "level": "error",
                "message": (
                    f"TS {name} holds {sheet['rows']:,} rows but the stack "
                    f"reads only {sheet['capacity']:,} from each sheet."
                ),
            })
        elif 0 <= sheet["headroom"] < cfg.TS_RAW_HEADROOM_WARNING:
            out.append({
                "level": "warning",
                "message": (
                    f"TS {name} has {sheet['headroom']:,} rows left of the "
                    f"{sheet['capacity']:,} the stack reads from each sheet."
                ),
            })
    return out


# --------------------------------------------------------------------------
# lifting the caps
# --------------------------------------------------------------------------

def extend(wb: Workbook, *, raw_last_row: Optional[int] = None,
           source_last_row: Optional[int] = None) -> Dict[str, Any]:
    """Raise either cap, rewriting every range that depends on it.

    Returns what changed.  The caller is responsible for dropping the
    calculation chain, since this adds formula cells.
    """
    current_raw = raw_limit(wb)
    current_source = source_limit(wb)
    result: Dict[str, Any] = {
        "raw_last_row": current_raw,
        "source_last_row": current_source,
        "sheets_changed": [],
        "helper_rows_added": 0,
    }

    if source_last_row and source_last_row > current_source:
        _rewrite_source_range(wb, current_source, source_last_row)
        result["source_last_row"] = source_last_row

    if raw_last_row and raw_last_row > current_raw:
        changed = _rewrite_raw_ranges(wb, current_raw, raw_last_row)
        result["raw_last_row"] = raw_last_row
        result["sheets_changed"] = changed
        result["helper_rows_added"] = _fill_helper_columns(
            wb, current_raw, raw_last_row)
    return result


def _rewrite_source_range(wb: Workbook, old: int, new: int) -> None:
    """Widen the VSTACK so each TS sheet is read further down."""
    sheet = wb.sheet(cfg.SHEET_TS_RAW)
    pattern = re.compile(r"(!\$[A-Z]{1,2}\$%d:\$[A-Z]{1,2}\$)%d\b"
                         % (cfg.TS_FIRST_DATA_ROW, old))
    sheet.xml = pattern.sub(lambda m: f"{m.group(1)}{new}", sheet.xml)


def _rewrite_raw_ranges(wb: Workbook, old: int, new: int) -> List[str]:
    """Point every consumer of the consolidated view at the new last row."""
    first = cfg.TS_RAW_FIRST_DATA_ROW
    qualified = re.compile(
        r"('?%s'?!\$[A-Z]{1,2}\$%d:\$[A-Z]{1,2}\$)%d\b"
        % (re.escape(cfg.SHEET_TS_RAW), first, old)
    )
    unqualified = re.compile(r"(?<![!\w])(\$[A-Z]{1,2}\$%d:\$[A-Z]{1,2}\$)%d\b"
                             % (first, old))
    changed: List[str] = []
    for name in wb.sheet_names:
        sheet = wb.sheet(name)
        before = sheet.xml
        after = qualified.sub(lambda m: f"{m.group(1)}{new}", before)
        if name == cfg.SHEET_TS_RAW:
            # Its own helper formulas name the range without a sheet prefix.
            after = unqualified.sub(lambda m: f"{m.group(1)}{new}", after)
        if after != before:
            sheet.xml = after
            changed.append(name)
    return changed


def _fill_helper_columns(wb: Workbook, old_last: int, new_last: int) -> int:
    """Copy the per-row helper formulas down to the new last row."""
    sheet = wb.sheet(cfg.SHEET_TS_RAW)
    first = cfg.TS_RAW_FIRST_DATA_ROW
    templates: Dict[str, str] = {}
    styles: Dict[str, Optional[str]] = {}
    for col in cfg.TS_RAW_HELPER_COLUMNS:
        cell = sheet.find_cell(f"{col}{first}")
        if not cell:
            continue
        m = re.search(r"<f[^>]*>(.*?)</f>", cell, re.S)
        if not m:
            continue
        templates[col] = _xml_unescape(m.group(1))
        style_m = re.search(r'\bs="(\d+)"', cell)
        styles[col] = style_m.group(1) if style_m else None
    if not templates:
        raise XlsxError(
            f"{cfg.SHEET_TS_RAW}: no helper formulas found on row {first}"
        )

    added = 0
    for row in range(old_last + 1, new_last + 1):
        for col, text in templates.items():
            ref = f"{col}{row}"
            formula = Translator(
                "=" + text, origin=f"{col}{first}"
            ).translate_formula(ref)
            style = styles.get(col)
            attrs = f' r="{ref}"' + (f' s="{style}"' if style else "")
            cell = f"<c{attrs}><f>{_xml_escape(formula[1:])}</f></c>"
            _put_cell(sheet, ref, cell)
        added += 1
    sheet.set_dimension(f"A1:{cfg.TS_RAW_HELPER_COLUMNS[-1]}{new_last}")
    return added


def _put_cell(sheet, ref: str, cell_xml: str) -> None:
    """Insert or replace a raw ``<c>`` element, creating the row if needed."""
    from .xlsx_io import split_ref

    col, row = split_ref(ref)
    position = sheet._index.get(row)
    if position is None:
        sheet._rows.append([row, f'<row r="{row}">{cell_xml}</row>', ""])
        sheet._rows.sort(key=lambda entry: entry[0])
        sheet._reindex()
        return
    open_tag, body = sheet._row_parts(sheet._rows[position][1])
    existing = sheet._cell_re(ref).search(body)
    if existing:
        body = body[: existing.start()] + cell_xml + body[existing.end():]
    else:
        body = sheet._insert_cell(body, col, cell_xml)
    sheet._rows[position][1] = open_tag + body + "</row>"


# --------------------------------------------------------------------------
# the stack itself
# --------------------------------------------------------------------------

def _rewrite_stack(wb: Workbook, rewrite) -> None:
    """Apply ``rewrite`` to the VSTACK formula that builds the consolidated view."""
    sheet = wb.sheet(cfg.SHEET_TS_RAW)
    cell = sheet.find_cell("A4")
    if not cell:
        raise XlsxError(f"{cfg.SHEET_TS_RAW}!A4 is empty; nothing builds the stack")
    m = re.search(r"(<f[^>]*>)(.*?)(</f>)", cell, re.S)
    if not m:
        raise XlsxError(f"{cfg.SHEET_TS_RAW}!A4 holds no formula")
    formula = rewrite(_xml_unescape(m.group(2)))
    updated = cell[:m.start(2)] + _xml_escape(formula) + cell[m.end(2):]
    # Written straight into the row: set_value would refuse to touch a formula.
    row = sheet.row_xml(4)
    sheet.replace_rows_from(4, [row.replace(cell, updated)])


def add_to_stack(wb: Workbook, sheet_name: str) -> None:
    """Include a new paste-target sheet in the consolidated view."""
    order = stack_order(wb)
    if sheet_name in order:
        return
    last = order[-1]

    def rewrite(formula: str) -> str:
        m = re.search(
            r"'%s'!(\$[A-Z]{1,2}\$\d+:\$[A-Z]{1,2}\$\d+)" % re.escape(last),
            formula,
        )
        if not m:
            raise XlsxError(
                f"cannot see how {cfg.SHEET_TS_RAW} stacks its sheets, so a new "
                f"one cannot be added automatically"
            )
        block = m.group(0)
        addition = f"'{sheet_name}'!{m.group(1)}"
        return formula.replace(block, f"{block},{addition}", 1)

    _rewrite_stack(wb, rewrite)


def remove_from_stack(wb: Workbook, sheet_name: str) -> None:
    """Drop a paste-target sheet from the consolidated view."""
    def rewrite(formula: str) -> str:
        pattern = re.compile(
            r",?\s*'%s'!\$[A-Z]{1,2}\$\d+:\$[A-Z]{1,2}\$\d+"
            % re.escape(sheet_name)
        )
        return pattern.sub("", formula, count=1)

    _rewrite_stack(wb, rewrite)


def rename_in_stack(wb: Workbook, old: str, new: str) -> None:
    _rewrite_stack(wb, lambda formula: formula.replace(f"'{old}'!", f"'{new}'!"))
