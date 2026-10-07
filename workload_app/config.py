"""The app's fixed settings, and where things lived in the old workbook.

A unit is its own database now; the cell addresses below are only read when a
unit made in the workbook days is brought across (``legacy.py``) and by the
downloadable copy.  The rest -- statuses, task defaults, the timesheet
export's columns -- is what the app itself runs on.
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

#: Paste-target sheets are found by this prefix rather than by name, so a
#: workbook set up for another unit -- different people, different sheet names
#: -- works without a code change.
TS_SHEET_PREFIX = "TS "

# -- Inputs: the project register -----------------------------------------
PROJECT_FIRST_ROW = 6
PROJECT_LAST_ROW = 85          # the register's formulas run to row 85

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

PROJECT_STATUSES: List[str] = [
    "Active", "Not Started", "On Hold", "Finalized", "Proposal", "Cancelled",
]

#: Statuses that count as work the team still has to deliver (Inputs column M).
PROJECT_IN_SCOPE_STATUSES = {"Active", "Not Started"}

# Team availability block on Inputs.
AVAILABILITY_HEADER_ROW = 90
AVAILABILITY_FIRST_COL = "B"
AVAILABILITY_LAST_COL = "F"
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

# -- Deliverable Actuals ---------------------------------------------------
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
HOURS_PER_DAY_CELL = "B14"
ENGINEER_COLUMNS = {"short_name": "A", "pattern": "B", "available_hours": "C"}
HOLIDAY_FIRST_ROW = 6
HOLIDAY_LAST_ROW = 200
HOLIDAY_COLUMNS = {"date": "E", "name": "F"}
NON_PROJECT_CODE_ROWS = list(range(26, 30))
NON_PROJECT_CODE_COLUMNS = {"code": "A", "meaning": "B", "treat_as": "C"}

# -- Profit Plan -----------------------------------------------------------
HOURS_PER_MAN_MONTH_CELL = "B5"
PLAN_YEAR_CELL = "B6"

# -- Timesheet sheets ------------------------------------------------------
TS_FIRST_DATA_ROW = 4

#: The columns of a BISpark timesheet export, in the order it gives them.
#: An upload is read by header name against this list, so a column the
#: export adds or moves later is noticed rather than misread.
TS_HEADERS: List[str] = [
    "Job Type", "JobNumber", "FullName", "Total MM", "%", "WorkAreaCode",
    "EmployeeAreaCode", "DepartmentABR", "EmployeeID", "RegularHours",
    "OvertimeHours", "Date", "Phase", "Task", "WorkScope", "TotalHours",
    "MappedDepartmentABR", "Grade", "DCNID", "Budget", "BudgetStatus",
    "PercentProgress", "ProgressDepBudget", "JobDept", "BudgetedDeptABR",
    "OfficeCode", "AreaDept", "EmployeeOffice", "CurrentUnitDesc",
    "CurrentUnitId", "JobDeptUnit", "JobStatus", "RegularHoursSubmitted",
    "OvertimeHoursSubmitted", "SourceID", "TimesheetStatusId",
    "TotalTimesheetHours", "EmployeeWeek", "EmployeeDay", "Expenditure Type",
    "DeliverableID", "InOut", "EAC", "ETC", "BudgetAtProgressDate",
    "SpentAtProgressDate", "InOutSourcing", "WkSummarykey", "WKeyOffice",
    "DeliverableDescription", "CPI_New", "EAC1_New", "EAC2_New", "ETC1_New",
    "ETC2_New", "EV_New", "MaximumEAC", "MinimumEAC", "PercentPlanedWork_New",
    "PV_New", "SPI_New", "EV_New_MM", "EV_without99", "EAC1without99",
    "ETC1Without99", "CumulativeSpent", "CumulativeSpentMM",
    "EAC1 Based on CumulativeSpent", "ETC1 Based on CumulativeSpent",
    "EAC2 Based on Cumulative Spent", "IsLatestProgressDate", "IsMaximumdate",
]

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

#: Columns of the export that carry no weight in the workbook's formulas but
#: are what lets a unit be set up from timesheets alone: what each phase of a
#: job is called, whether the job is still live, what grade somebody is, and
#: which unit they sit in.
TS_SETUP_FIELDS = {
    "deliverable": "DeliverableDescription",
    "job_status": "JobStatus",
    "grade": "Grade",
    "unit": "CurrentUnitDesc",
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

BACKUP_DIRNAME = "backups"

SHEET_TS_RAW = "Timesheet Raw"

#: Guards the Project Types and Rules of Credit tables against a stray edit.
#: Not a security control -- the same cells are editable in Excel by anyone who
#: can open the file -- so it is deliberately kept simple and in plain sight.
REFERENCE_PASSWORD = "2026"


# -- Phasing: the quarter grid the reports are built on --------------------
PHASING_START_ROW = 5
#: Columns D..X: an opening balance column, then one per quarter.
PHASING_FIRST_COL = "D"
PHASING_LAST_COL = "X"

#: Planned MM per project per quarter is spread from the project's dates unless
#: a value is typed into the override block, which starts here (one row per
#: project, aligned with Inputs).
PHASING_OVERRIDE_FIRST_ROW = 95


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
TASKS_SETTINGS_CELL = "S1"
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
    # How far along, and how that number is arrived at. See progress.py.
    "progress_mode": "P",
    "stage": "Q",
    "review_code": "R",
    "revisions": "S",
    "pro_rata": "T",
}


TASK_STATUSES = ["Not started", "In progress", "Blocked", "Done"]
TASK_DONE_STATUS = "Done"
TASK_KINDS = ["Task", "Submission", "Meeting", "Request"]
#: Work that came in during the day, on top of whatever was already planned.
TASK_REQUEST_KIND = "Request"

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
