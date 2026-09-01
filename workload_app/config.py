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

#: Short name -> the per-engineer paste target sheet.
TS_SHEETS: Dict[str, str] = {
    "Ahmed": "TS Ahmed",
    "Osama": "TS Osama",
    "Kirolos": "TS Kirolos",
}

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
    "manual_share_ahmed": "W",
    "manual_share_osama": "X",
    "manual_share_kirolos": "Y",
}

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
AVAILABILITY_ROWS: Dict[str, int] = {"Ahmed": 91, "Osama": 92, "Kirolos": 93}
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
    "share_ahmed": "K",
    "share_osama": "L",
    "share_kirolos": "M",
    "notes": "O",
}

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
ENGINEER_ROWS: Dict[str, int] = {"Ahmed": 20, "Osama": 21, "Kirolos": 22}
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
TS_MAX_DATA_ROW = 6000

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

#: ``Timesheet Raw!A4`` stacks the three TS sheets with VSTACK and filters the
#: blanks out.  The stack is read from each sheet up to this row, so it is the
#: cap on any one engineer's sheet.
TS_SOURCE_DEFAULT_LAST_ROW = 6000

#: Every SUMIFS / MINIFS / MAXIFS that reads the consolidated view stops at this
#: row.  Rows spilled beyond it are invisible to the whole workbook, and because
#: the stack runs Ahmed, Osama, Kirolos, it is the last engineer's rows that
#: silently drop off the end first.
TS_RAW_DEFAULT_LAST_ROW = 8000

#: Per-row helper formulas on the consolidated view; they have to reach as far
#: as the cap does.
TS_RAW_HELPER_COLUMNS = ["BU", "BV", "BW", "BX"]

#: A cell whose formula names the consolidated range, used to read the cap back
#: out of the workbook rather than assuming it.
TS_RAW_LIMIT_PROBE = (SHEET_CALENDAR, "B34")

#: Warn once free rows fall below this.
TS_RAW_HEADROOM_WARNING = 500
