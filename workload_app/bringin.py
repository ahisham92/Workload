"""Bring in data: one place to drop every file, each sent where it belongs.

Four files feed the app, and each already has an importer of its own:

* **timesheet exports** (BISpark, one per person or many at once): the
  people, the projects, their phases and every hour;
* **the Projects list** (BISpark > Projects): each job's budget and spend;
* **a job's staff expenditure** (BISpark > Project Detail > MH Expenditure):
  who booked to it, from which unit;
* **the drawing list**: drawing counts, issues and review codes.

Nobody should have to know which tab takes which, so a mix of them is read
here, each is told apart by its own column headings, and the importers run in
the order they lean on each other: timesheets first, since they set up the
team and the projects; then the budgets, which read who is on the team; then
the drawing list, which is matched to the deliverables the timesheets made.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from . import budgets, drawing_list, timesheets

#: In the order they are brought in.
KINDS = ("timesheets", "projects", "spend", "drawings")

#: What each kind is, in the words the screen uses.
LABELS = {
    "timesheets": "Timesheet export",
    "projects": "Projects list (budgets)",
    "spend": "Staff expenditure (who spent a job's hours)",
    "drawings": "Drawing list",
}

#: Where each kind ends up, for the line under it.
FILLS = {
    "timesheets": "the team, the projects, their phases and every hour",
    "projects": "each job's budget, spend and what is left on Budgets and Projects",
    "spend": "how much of a job is this team's, on Budgets",
    "drawings": "drawing counts, issues and review codes on Projects and Planner",
}

#: Headings only a staff expenditure carries, never a timesheet export.
_SPEND_ONLY = {"employeename", "mmspent"}
_ROWS_LOOKED_AT = 20


def _is_timesheet(grid) -> bool:
    for row in grid[:_ROWS_LOOKED_AT]:
        names = {timesheets._normalise(c) for c in row if c not in (None, "")}
        if names & _SPEND_ONLY:
            return False
        if "fullname" in names and (
                "jobtype" in names
                or len(names & timesheets._SIGNATURE_HEADERS) >= 3):
            return True
    return False


def classify(filename: str, data: bytes) -> Tuple[Optional[str], Any]:
    """What one file is, and what reading it gave, or ``(None, why)``.

    A budget file comes back already read (the importer takes it as is); a
    drawing list comes back as its drawings, for the count; a timesheet export
    comes back as ``None``, since the timesheet importer reads it itself.
    """
    try:
        grid = timesheets.read_grid(filename, data)
    except timesheets.ImportError_:
        grid = None
    if grid and _is_timesheet(grid):
        return "timesheets", None
    if grid:
        try:
            parsed = budgets.parse(filename, data)
            return parsed["kind"], parsed
        except budgets.BudgetError:
            pass
    try:
        return "drawings", drawing_list.read(data, filename)
    except drawing_list.DrawingListError:
        pass
    return None, (f"{filename}: not a file the app knows. It takes BISpark "
                  "timesheet exports, the Projects list, a job's staff "
                  "expenditure and the drawing list.")
