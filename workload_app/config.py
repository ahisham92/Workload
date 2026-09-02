"""Where every input lives in the Workload workbook.

Everything the app writes is described here, so re-pointing the app at a
restructured workbook is a matter of editing this file rather than hunting
through the code.  Column letters and row ranges match the workbook as shipped:
blue cells in Excel are the inputs, and only those appear below.
"""

from __future__ import annotations

from typing import Dict, List

# -- sheet names -----------------------------------------------------------
SHEET_INPUTS = "Inputs"
SHEET_DELIVERABLES = "Deliverables"
SHEET_ACTUALS = "Deliverable Actuals"
SHEET_PROJECT_TYPES = "Project Types"
SHEET_RULES = "Rules of Credit"
SHEET_CALENDAR = "Work Calendar"
SHEET_PROFIT_PLAN = "Profit Plan"
SHEET_PHASING = "Phasing"
SHEET_SUPPORT_PLAN = "Support Plan"

#: Paste-target sheets are found by this prefix rather than by name, so a
#: workbook set up for another unit -- different people, different sheet names
#: -- works without a code change.
TS_SHEET_PREFIX = "TS "

# -- Inputs: the project register -----------------------------------------
PROJECT_FIRST_ROW = 6
PROJECT_LAST_ROW = 85          # the register's formulas run to row 85
PROJECT_TOTAL_ROW = 86

#: field name -> column letter, for the cells a user may type into.
PROJECT_INPUT_COLUMNS: Dict[str, str] = {
    "number": "A",
    "name": "B",
    "budget_mm": "C",
    "start": "D",
    "end": "E",
    "status": "F",
    "cac_override": "H",
    "notes": "N",
    "manual_percent": "O",
}

#: The fallback split, one column per engineer in Work Calendar order.  Keyed by
#: position rather than by name so another unit's team lands in the right cells.
PROJECT_MANUAL_SHARE_COLUMNS = ["W", "X", "Y"]
#: Columns for a fourth engineer onwards, in free space to the right.
PROJECT_MANUAL_SHARE_EXTRA_FIRST_COL = "AB"

#: field name -> column letter, for cells the workbook calculates.
PROJECT_CALC_COLUMNS: Dict[str, str] = {
    "percent_complete": "G",
    "share_ahmed": "I",
    "share_osama": "J",
    "share_kirolos": "K",
    "split_check": "L",
    "in_scope": "M",
    "actual_mm": "P",
    "cost_at_completion": "Q",
    "remaining_on_hand": "R",
    "earned_mm": "S",
    "profit_mm": "T",
    "cpi": "U",
}

PROJECT_STATUSES: List[str] = [
    "Active", "Not Started", "On Hold", "Finalized", "Proposal", "Cancelled",
]

#: Statuses that count as work the team still has to deliver (Inputs column M).
PROJECT_IN_SCOPE_STATUSES = {"Active", "Not Started"}

# Team availability block on Inputs.
AVAILABILITY_HEADER_ROW = 90
AVAILABILITY_FIRST_COL = "B"
AVAILABILITY_LAST_COL = "F"
#: The availability block, and the continuation used past the third engineer.
AVAILABILITY_FIRST_ROW = 91
AVAILABILITY_EXTRA_FIRST_ROW = 100
MONTHS_PER_QUARTER_CELL = "B94"
AS_AT_DATE_CELL = "B96"

# -- Deliverables: the deliverable register --------------------------------
DELIVERABLE_FIRST_ROW = 5
DELIVERABLE_LAST_ROW = 204

DELIVERABLE_INPUT_COLUMNS: Dict[str, str] = {
    "project_number": "A",
    "name": "C",
    "type_code": "D",
    "phase_weight": "E",
    "step_no": "F",
    "status_date": "J",
    "notes": "O",
}

#: Each deliverable's split, one column per engineer in Work Calendar order.
DELIVERABLE_SHARE_COLUMNS = ["K", "L", "M"]
#: Columns for a fourth engineer onwards.  The workbook's own formulas only
#: know about the first three; the app reads and writes all of them.
DELIVERABLE_SHARE_EXTRA_FIRST_COL = "AG"

DELIVERABLE_CALC_COLUMNS: Dict[str, str] = {
    "project_name": "B",
    "step_name": "G",
    "credit_percent": "H",
    "weighted_progress": "I",
    "split_check": "N",
    "type_factor": "P",
}

# -- Deliverable Actuals ---------------------------------------------------
#: Row aligned one-for-one with the deliverable register.
ACTUALS_FIRST_ROW = 5
#: The last row the sheet ships with.  The register itself runs to row 204, so
#: the block is grown on demand when a 65th deliverable is added.
ACTUALS_DEFAULT_LAST_ROW = 68
#: Row that the extension clones (formulas are translated down from here).
ACTUALS_TEMPLATE_ROW = 68

ACTUALS_INPUT_COLUMNS: Dict[str, str] = {
    "ts_phase": "E",
    "actual_start": "W",
    "actual_finish": "X",
    "submitted_to_client": "Y",
    "comments_received": "Z",
    "resubmitted": "AA",
    "completed": "AB",
}

ACTUALS_DATE_FIELDS = [
    "actual_start", "actual_finish", "submitted_to_client",
    "comments_received", "resubmitted", "completed",
]

#: Columns whose ``$X$5:$X$68`` ranges must grow with the block.
ACTUALS_RANGE_END = ACTUALS_DEFAULT_LAST_ROW

#: Proposal effort is kept on import even though no project number covers it:
#: the Proposals sheet and the utilisation figures both need it.
PROPOSAL_JOB_TYPES = ["2-Proposals Chargeable", "3-Proposals Regular"]

# -- Reference tables ------------------------------------------------------
PROJECT_TYPES_FIRST_ROW = 5
PROJECT_TYPES_LAST_ROW = 13
PROJECT_TYPE_COLUMNS = {
    "code": "A", "name": "B", "basis": "C", "trigger": "D",
    "portfolio_weight": "E", "include_in_cpi": "F", "notes": "G",
}

RULES_FIRST_ROW = 5
RULES_LAST_ROW = 38
RULES_COLUMNS = {
    "type_code": "A", "step_no": "B", "step_name": "C",
    "credit": "D", "data_source": "E",
}

# -- Work Calendar ---------------------------------------------------------
WORKING_WEEK_ROWS = list(range(6, 13))     # Sunday .. Saturday
WORKING_WEEK_COLUMNS = {"weekday": "A", "day": "B", "working": "C"}
HOURS_PER_DAY_CELL = "B14"
ANALYSIS_START_CELL = "B15"
ANALYSIS_END_CELL = "B16"
#: The engineer block on Work Calendar, as the workbook ships it: three rows,
#: with the next heading immediately below.
ENGINEER_FIRST_ROW = 20
ENGINEER_BUILT_IN_SLOTS = 3
#: A fourth engineer onwards goes here instead, well clear of everything the
#: workbook uses, so nothing has to be inserted and no formula shifts.
ENGINEER_EXTRA_FIRST_ROW = 100
ENGINEER_COLUMNS = {"short_name": "A", "pattern": "B", "available_hours": "C"}
HOLIDAY_FIRST_ROW = 6
HOLIDAY_LAST_ROW = 200
HOLIDAY_COLUMNS = {"date": "E", "name": "F"}
NON_PROJECT_CODE_ROWS = list(range(26, 30))
NON_PROJECT_CODE_COLUMNS = {"code": "A", "meaning": "B", "treat_as": "C"}
STOPPAGE_GAP_CELL = "B32"

# -- Profit Plan -----------------------------------------------------------
HOURS_PER_MAN_MONTH_CELL = "B5"
PLAN_YEAR_CELL = "B6"

# -- Timesheet sheets ------------------------------------------------------
TS_HEADER_ROW = 3
TS_FIRST_DATA_ROW = 4
#: Columns A..BT.  Timesheet Raw reads each sheet from row 4 to row 6000.
TS_LAST_COLUMN = "BT"
#: Fallback only; the real limit is read from the VSTACK in the workbook.
TS_MAX_DATA_ROW = 25000

#: Columns of the export that the workbook actually reads, by header name.
TS_KEY_FIELDS = {
    "job_type": "Job Type",
    "job_number": "JobNumber",
    "full_name": "FullName",
    "total_mm": "Total MM",
    "regular_hours": "RegularHours",
    "overtime_hours": "OvertimeHours",
    "date": "Date",
    "phase": "Phase",
    "total_hours": "TotalHours",
}

#: Header names whose values are dates rather than text or numbers.
TS_DATE_HEADERS = {"Date"}

#: Header names the workbook treats as numeric.
TS_NUMERIC_HEADERS = {
    "Total MM", "%", "RegularHours", "OvertimeHours", "Phase", "Task",
    "TotalHours", "DCNID", "Budget", "PercentProgress", "ProgressDepBudget",
    "RegularHoursSubmitted", "OvertimeHoursSubmitted", "SourceID",
    "TimesheetStatusId", "TotalTimesheetHours", "EAC", "ETC",
    "BudgetAtProgressDate", "SpentAtProgressDate", "CPI_New", "EAC1_New",
    "EAC2_New", "ETC1_New", "ETC2_New", "EV_New", "MaximumEAC", "MinimumEAC",
    "PercentPlanedWork_New", "PV_New", "SPI_New", "EV_New_MM", "EV_without99",
    "EAC1without99", "ETC1Without99", "CumulativeSpent", "CumulativeSpentMM",
    "EAC1 Based on CumulativeSpent", "ETC1 Based on CumulativeSpent",
    "EAC2 Based on Cumulative Spent", "IsLatestProgressDate", "IsMaximumdate",
}

#: Style index of the ``yyyy-mm-dd`` number format used by the Date column.
TS_DATE_STYLE = "371"

BACKUP_DIRNAME = "backups"

# -- Timesheet Raw: the consolidated view, and the two caps on it ----------
SHEET_TS_RAW = "Timesheet Raw"
TS_RAW_FIRST_DATA_ROW = 4

#: ``Timesheet Raw!A4`` stacks the TS sheets with VSTACK and filters the blanks
#: out.  The stack is read from each sheet up to this row, so it caps any one
#: engineer's sheet.  The workbook shipped with 6000; the app raises it so an
#: engineer's own sheet stops being the thing that runs out first.
TS_SOURCE_DEFAULT_LAST_ROW = 6000
TS_SOURCE_TARGET_LAST_ROW = 25000

#: Every SUMIFS / MINIFS / MAXIFS that reads the consolidated view stops at this
#: row.  Rows spilled beyond it are invisible to the whole workbook, and because
#: the stack runs Ahmed, Osama, Kirolos, it is the last engineer's rows that
#: silently drop off the end first.
TS_RAW_DEFAULT_LAST_ROW = 8000
#: What the app raises it to when asked: the same 25,000 entries the stack
#: reads from each sheet, so one number covers the whole timesheet and nobody
#: has to think about two limits again.
TS_RAW_TARGET_LAST_ROW = 25000
#: Never leave less than this much room when raising the limit for an import,
#: so the next month's import does not have to raise it again.
TS_RAW_GROWTH_HEADROOM = 5000
#: Raising the limit is rounded up to a tidy multiple of this.
TS_RAW_GROWTH_STEP = 5000
#: How far the app will raise the limit on its own during an import.  Past this
#: the workbook becomes slow enough in Excel that it is a decision rather than
#: a detail, so the import is refused and says so.
TS_RAW_AUTO_MAX = 60000

#: Per-row helper formulas on the consolidated view; they have to reach as far
#: as the cap does.
TS_RAW_HELPER_COLUMNS = ["BU", "BV", "BW", "BX"]

#: A cell whose formula names the consolidated range, used to read the cap back
#: out of the workbook rather than assuming it.
TS_RAW_LIMIT_PROBE = (SHEET_CALENDAR, "B34")

#: Warn once free rows fall below this.
TS_RAW_HEADROOM_WARNING = 500


#: Proposal effort is kept on import even though no project number covers it:
#: the Proposals sheet and the utilisation figures both need it.
PROPOSAL_JOB_TYPES = ["2-Proposals Chargeable", "3-Proposals Regular"]

# -- Reference tables ------------------------------------------------------
#: Guards the Project Types and Rules of Credit tables against a stray edit.
#: Not a security control -- the same cells are editable in Excel by anyone who
#: can open the file -- so it is deliberately kept simple and in plain sight.
REFERENCE_PASSWORD = "2026"


# -- Phasing: the quarter grid the reports are built on --------------------
#: Row holding each column's year, its quarter label, and the period bounds.
PHASING_YEAR_ROW = 3
PHASING_QUARTER_ROW = 4
PHASING_START_ROW = 5
PHASING_END_ROW = 6
#: Columns D..X: an opening balance column, then one per quarter.
PHASING_FIRST_COL = "D"
PHASING_LAST_COL = "X"

#: Planned MM per project per quarter is spread from the project's dates unless
#: a value is typed into the override block, which starts here (one row per
#: project, aligned with Inputs).
PHASING_OVERRIDE_FIRST_ROW = 95


#: How many engineers a unit may have.  Well past any real team, and bounded so
#: a typo cannot walk the slots off the end of the sheet.
MAX_ENGINEERS = 12

# -- Scorecard: the factors the ranking is built from ----------------------
SHEET_SCORECARD = "Scorecard"
SCORECARD_FIRST_ROW = 6
SCORECARD_LAST_ROW = 11
#: A project has to have had real effort booked to it in the period before its
#: CPI means anything -- a quarter of a man-month is about forty hours.  Below
#: that, two hours of touch-up on a finished job would win the year.
CHAMPION_MIN_ACTUAL_MM = 0.25

SCORECARD_COLUMNS = {
    "factor": "A", "weight": "B", "direction": "C", "target": "D",
    "how": "E",
}
#: What each factor is measured on.  The sheet names the factor in words; this
#: is the figure behind it, matched in row order.
SCORECARD_KEYS = [
    "type_weighted_cpi", "utilisation", "plan_adherence",
    "type_weighted_earned_mm", "actual_mm", "projects_worked",
]
SCORECARD_DIRECTION_HIGHER = "Higher is better"
SCORECARD_DIRECTION_TARGET = "Target band"

# -- Definitions: the glossary shown beside the measures -------------------
SHEET_DEFINITIONS = "Definitions"
DEFINITIONS_COLUMNS = {"field": "A", "where": "B", "means": "C", "how": "D"}
DEFINITIONS_LAST_ROW = 40

# -- Task Management -------------------------------------------------------
#: A sheet of the app's own, created on demand.  Nothing in the workbook reads
#: it: the task list is a planning aid that sits beside the model rather than
#: inside it, so nothing here can move a project's figures.
SHEET_TASKS = "Tasks"
TASKS_TITLE_CELL = "A1"
TASKS_SETTINGS_LABEL_CELL = "R1"
TASKS_SETTINGS_CELL = "S1"
TASKS_HEADER_ROW = 2
TASKS_FIRST_ROW = 3
#: Well past a year of daily tasks for a team of this size.
TASKS_LAST_ROW = 5000

TASK_COLUMNS: Dict[str, str] = {
    "id": "A",
    "name": "B",
    "definition": "C",
    "project_number": "D",
    "deliverable_row": "E",
    "deliverable_name": "F",
    "assignees": "G",
    "required_hours": "H",
    "actual_hours": "I",
    "start": "J",
    "due": "K",
    "status": "L",
    "kind": "M",
    "series": "N",
    "notes": "O",
}

TASK_HEADERS = [
    "ID", "Task", "Definition", "Project", "Deliverable row", "Deliverable",
    "Assigned to", "Required hours", "Actual hours", "Start", "Due", "Status",
    "Kind", "Series", "Notes",
]

TASK_STATUSES = ["Not started", "In progress", "Blocked", "Done"]
TASK_DONE_STATUS = "Done"
TASK_KINDS = ["Task", "Submission", "Meeting"]

#: The working day the load is measured against.  The team starts at 09:00 and
#: is meant to finish at 17:30; anything past that is the overtime the stats
#: exist to make visible, so it is not built into the capacity.
TASK_DEFAULT_SETTINGS: Dict[str, object] = {
    "day_start": "09:00",
    "day_end": "17:30",
    #: Monday is 0, Sunday is 6 -- Python's own weekday numbering.
    "work_days": [0, 1, 2, 3, 4],
    "horizon_weeks": 4,
    #: A deliverable's date pulls a week of daily preparation before it.
    "submission_lead_days": 7,
    "submission_hours_per_day": 2.0,
    "meeting_hours": 1.0,
    "meeting_weekday": 0,
    "meeting_weeks": 12,
}

#: Load against capacity: past this someone is working overtime to finish.
TASK_OVERLOADED_AT = 1.0
#: Below this there is real room for more work.  The band between the two is
#: deliberately wide: a plan that fills every hour is a plan with no slack in
#: it, and one that fills two thirds of them is not somebody idle.
TASK_UNDERLOADED_AT = 0.7
