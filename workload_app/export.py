"""A unit, written out as a spreadsheet to read, keep or send on.

This is a copy of what the unit holds, sheet by sheet -- the team, the
registers, every timesheet row, the task list, the reference tables and the
calendar -- with the figures the app works out beside the registers.  Nothing
reads it back in: the unit is its database, and this is only a way to take
it away.
"""

from __future__ import annotations

import datetime as _dt
import io
from typing import Any, Dict, Iterable, Optional, Sequence

from . import metrics
from .model import stored_date
from .unit import Unit
from .xlsx_io import index_to_col


def unit_workbook(unit: Unit, name: str = "") -> bytes:
    """The whole unit as ``.xlsx`` bytes."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    book = Workbook(write_only=True)
    bold = Font(bold=True)
    index = metrics.TimesheetIndex(unit)

    def sheet(title: str, headers: Sequence[str], rows: Iterable[Sequence[Any]],
              widths: Optional[Dict[int, float]] = None) -> None:
        ws = book.create_sheet(title)
        for column, width in (widths or {}).items():
            ws.column_dimensions[index_to_col(column)].width = width
        ws.freeze_panes = "A2"
        header_cells = []
        for header in headers:
            cell = WriteOnlyCell(ws, value=header)
            cell.font = bold
            header_cells.append(cell)
        ws.append(header_cells)
        for row in rows:
            ws.append([_cell(ws, v) for v in row])

    names = unit.engineer_names()
    years = unit.availability_years()

    about = [
        ("Unit", name),
        ("Written out", _dt.datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Hours per man-month", unit.hours_per_man_month()),
        ("Hours per day", unit.hours_per_day()),
        ("Plan year", unit.plan_year()),
        ("Reports counted to", unit.as_at() or "today"),
        ("People on the team", len(names)),
        ("Projects", len(unit.projects())),
        ("Deliverables", len(unit.deliverables())),
        ("Timesheet rows", len(index.rows)),
        ("Note", "A copy to read. The unit itself lives in Selecao+; changes "
                 "made here are not read back."),
    ]
    sheet("About", ["", ""], about, {1: 24, 2: 60})

    figures = {row["number"]: row for row in metrics.project_rows(unit, index)}
    sheet("Projects",
          ["Project", "Name", "Status", "Budget (MM)", "Start", "End",
           "% complete", "Actual (MM)", "Earned (MM)", "Profit (MM)", "CPI",
           "Remaining (MM)", "First charge", "Last charge", "Notes"],
          ([p.number, p.name, p.status, p.budget_mm, p.start, p.end,
            *[(figures.get(p.number) or {}).get(key) for key in (
                "progress", "actual_mm", "earned_mm", "profit_mm", "cpi",
                "remaining_mm", "first_charge", "last_charge")],
            p.notes] for p in unit.projects()),
          {1: 16, 2: 48, 15: 40})

    computed = {row["row"]: row for row in metrics.deliverable_rows(unit, index)}
    sheet("Deliverables",
          ["Project", "Deliverable", "Type", "Phase weight", "Step",
           "Step name", "Credit", "Status date", "Split", "Timesheet phase",
           "Hours", "Actual start", "Actual finish", "Submitted to client",
           "Comments received", "Resubmitted", "Completed", "Notes"],
          ([d.project_number, d.name, d.type_code, d.phase_weight, d.step_no,
            (computed.get(d.row) or {}).get("step_name"),
            (computed.get(d.row) or {}).get("credit"),
            d.status_date, _split(d.shares), d.ts_phase,
            (computed.get(d.row) or {}).get("actual_hours"),
            d.actual_start, d.actual_finish, d.submitted_to_client,
            d.comments_received, d.resubmitted, d.completed, d.notes]
           for d in unit.deliverables()),
          {1: 16, 2: 40, 9: 30, 18: 40})

    people = {p["name"]: p for p in unit.store.people()}
    teams = {t["id"]: t["name"] for t in unit.store.teams()}
    sheet("Team",
          ["Short name", "Full name pattern", "Hours a month", "Team", "Grade",
           *[f"Availability {year}" for year in years]],
          ([e.short_name, e.pattern, e.available_hours,
            teams.get((people.get(e.short_name) or {}).get("team_id") or "", ""),
            (people.get(e.short_name) or {}).get("grade", ""),
            *[e.availability.get(year) for year in years]]
           for e in unit.engineers()),
          {1: 20, 2: 32})

    sheet("Timesheets",
          ["Person", "Date", "Job number", "Job type", "Phase", "Deliverable",
           "Regular hours", "Overtime hours", "Hours", "Full name", "Grade",
           "Job status"],
          ([r["engineer"], r["date"], r["job_number"], r["job_type"], r["phase"],
            r.get("deliverable", ""), r["regular_hours"], r["overtime_hours"],
            r["hours"], r["full_name"], r.get("grade", ""), r.get("job_status", "")]
           for r in sorted(index.rows, key=lambda r: (r["engineer"],
                                                      r["date"] or _dt.date.min))),
          {1: 18, 3: 16, 6: 30, 10: 28})

    sheet("Tasks",
          ["Id", "Task", "Project", "Deliverable", "Assigned to", "Required hours",
           "Actual hours", "Start", "Due", "Status", "Kind", "Notes"],
          ([t.id, t.name, t.project_number, t.deliverable_name,
            ", ".join(t.assignees), t.required_hours, t.actual_hours, t.start,
            t.due, t.status, t.kind, t.notes] for t in unit.task_records()),
          {2: 40, 5: 24})

    drawn = unit.store.drawings()
    listed = unit.store.drawing_list()
    by_row = {d.row: d for d in unit.deliverables()}
    sheet("Drawings",
          ["Project", "Deliverable", "Drawings", "Issued", "Code A", "Code B",
           "Code C"],
          ([(by_row[row].project_number if row in by_row else entry["project_number"]),
            by_row[row].name if row in by_row else "",
            entry["count"],
            *[(listed.get(row) or {}).get(key)
              for key in ("issued", "code_a", "code_b", "code_c")]]
           for row, entry in sorted(drawn.items())),
          {2: 40})

    # Kept as ISO text; written as dates, like the holidays beside them.
    away = [("Everybody" if a["person"] == "*" else a["person"],
             stored_date(a["start"]) or a["start"], stored_date(a["end"]) or a["end"],
             a.get("note", "")) for a in unit.store.absences()]
    away += [("Everybody", day, day, "Day off typed in") for day in unit.holidays()]
    sheet("Time away", ["Who", "From", "To", "Note"], sorted(
        away, key=lambda a: str(a[1])), {1: 20, 4: 40})

    sheet("Project types",
          ["Code", "Name", "Basis", "Trigger", "Portfolio weight",
           "In CPI", "Notes"],
          ([t.code, t.name, t.basis, t.trigger, t.portfolio_weight,
            t.include_in_cpi, t.notes] for t in unit.project_types()),
          {2: 30, 7: 60})
    sheet("Rules of credit",
          ["Type", "Step", "Step name", "Credit", "Data source"],
          ([s.type_code, s.step_no, s.step_name, s.credit, s.data_source]
           for s in unit.credit_steps()),
          {3: 40})
    sheet("Scorecard", ["Factor", "Weight", "Scoring", "Target", "How"],
          ([f["factor"], f["weight"], f["direction_label"], f["target"], f["how"]]
           for f in unit.scorecard_factors()),
          {1: 34, 5: 60})

    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _split(shares: Dict[str, Optional[float]]) -> str:
    return ", ".join(f"{name} {round(share * 100)}%"
                     for name, share in shares.items() if share)


def _cell(ws: Any, value: Any) -> Any:
    """A value openpyxl will write as it is.

    Text comes from uploaded timesheets, so it is cleaned of the control
    characters an .xlsx cannot hold, and text starting with "=" is written as
    text rather than run as a formula when the copy is opened.
    """
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    if isinstance(value, (list, dict, tuple, set)):
        value = str(value)
    if isinstance(value, _dt.date):
        # Shown day first, whatever the reader's Excel is set to.
        cell = WriteOnlyCell(ws, value=value)
        cell.number_format = ("dd/mm/yyyy hh:mm" if isinstance(value, _dt.datetime)
                              else "dd/mm/yyyy")
        return cell
    if not isinstance(value, str):
        return value
    value = ILLEGAL_CHARACTERS_RE.sub("", value)
    if value.startswith("="):
        cell = WriteOnlyCell(ws, value=value)
        cell.data_type = "s"
        return cell
    return value
