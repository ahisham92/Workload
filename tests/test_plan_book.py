"""Projects and submissions out to Excel and back in, with every change shown
before it is saved (Ahmed, 2026-10-12). Synthetic exports only."""

import base64
import datetime as dt
import io

import pytest

from test_bring_in import blank  # noqa: F401
from test_from_timesheets import team_exports
from workload_app import bringin, plan_book

openpyxl = pytest.importorskip("openpyxl")


def _filled(blank):
    blank.bring_in_apply(blank.bring_in_check(team_exports())["token"])
    register = blank.submission_register({"all": ["1"]})
    assert register["items"], "the exports set up deliverables"
    return register["items"]


def _book(blank):
    file = blank.plan_book_download()
    assert file["filename"].endswith(".xlsx")
    return openpyxl.load_workbook(io.BytesIO(base64.b64decode(file["content_base64"])))


def _as_file(book, name="Plan back.xlsx"):
    out = io.BytesIO()
    book.save(out)
    return {"filename": name, "content_base64": base64.b64encode(out.getvalue()).decode()}


def _column(sheet, label):
    return next(c.column for c in sheet[1] if c.value == label)


def test_the_workbook_goes_out_with_both_sheets_and_is_known_coming_back(blank):
    items = _filled(blank)
    book = _book(blank)
    assert book.sheetnames == ["Read me", "Projects", "Submissions"]
    subs = book["Submissions"]
    assert [c.value for c in subs[1]][:3] == ["Ref", "Job no.", "Deliverable"]
    assert subs.max_row - 1 == len(blank.submission_register()["items"])
    file = _as_file(book)
    found, read = bringin.classify(file["filename"], base64.b64decode(file["content_base64"]))
    assert found == "plan" and len(read["submissions"]) == subs.max_row - 1
    # Brought straight back, it changes nothing.
    check = blank.bring_in_check([file])
    assert check["plan"]["changes"] == [] and not check["ready"]
    assert items


def test_changes_are_shown_first_and_only_they_are_saved(blank):
    items = _filled(blank)
    first = items[0]
    blank.start_submission({"row": first["row"], "planned": "2026-11-10"})
    book = _book(blank)
    subs, projects = book["Submissions"], book["Projects"]
    planned = _column(subs, "Planned to go")
    code_col = _column(subs, "Client code (A/B/C)")
    row = next(r for r in range(2, subs.max_row + 1) if subs.cell(r, 1).value == first["row"])
    subs.cell(row, planned).value = dt.datetime(2026, 11, 24)
    subs.cell(row, _column(subs, "Reason or comments")).value = "Waiting for the soil report"
    # One project's budget, and a brand new job.
    budget = _column(projects, "Budget (MM)")
    number = projects.cell(2, 1).value
    projects.cell(2, budget).value = 12.5
    projects.append(["NEW-0001", "New quay", "Not Started", 3, None, None, ""])
    check = blank.bring_in_check([_as_file(book)])
    plan = check["plan"]
    assert check["ready"] and plan["errors"] == []
    by = {(c["kind"], c["key"]): c for c in plan["changes"]}
    sub = by[("submission", str(first["row"]))]
    assert {f["field"]: (f["old"], f["new"]) for f in sub["fields"]} == {
        "planned": ("2026-11-10", "2026-11-24"),
        "reason": ("", "Waiting for the soil report")}
    assert by[("project", number)]["fields"][0]["new"] == 12.5
    assert ("new_project", "NEW-0001") in by
    # Nothing written yet.
    assert blank.workbook.project(number).budget_mm != 12.5
    done = blank.bring_in_apply(check["token"])
    step = done["steps"][-1]
    assert step["kind"] == "plan" and step["ok"], step
    assert step["result"]["changed"] == 3 and not step["result"]["failed"]
    assert blank.workbook.project(number).budget_mm == 12.5
    assert blank.workbook.project("NEW-0001").name == "New quay"
    issue = blank.workbook.issues()[first["row"]][-1]
    assert issue["planned"] == "2026-11-24" and issue["reason"] == "Waiting for the soil report"
    # The move is in the date history, as any other move is.
    moves = blank.workbook.date_moves()[first["row"]]
    assert [(m["old_date"], m["new_date"]) for m in moves] == [("2026-11-10", "2026-11-24")]
    assert code_col


def test_what_cannot_be_read_is_said_and_the_rest_still_comes_in(blank):
    items = _filled(blank)
    book = _book(blank)
    subs = book["Submissions"]
    subs.cell(2, _column(subs, "Planned to go")).value = "next Tuesday"
    subs.cell(2, _column(subs, "Who prepares it")).value = "Nobody Known"
    subs.append([99999, "X", "Not a deliverable"])
    projects = book["Projects"]
    projects.cell(2, _column(projects, "Status")).value = "Sort of done"
    plan = blank.bring_in_check([_as_file(book)])["plan"]
    text = " ".join(plan["errors"])
    assert "is not a date" in text and "not on the team" in text
    assert "not a submission in the app" in text and "is not one of" in text
    assert plan["changes"] == []
    assert items


def test_a_row_taken_out_removes_nothing(blank):
    _filled(blank)
    before = len(blank.workbook.projects())
    book = _book(blank)
    book["Projects"].delete_rows(2, book["Projects"].max_row)
    book["Submissions"].delete_rows(2, book["Submissions"].max_row)
    check = blank.bring_in_check([_as_file(book)])
    assert check["plan"]["changes"] == []
    assert len(blank.workbook.projects()) == before


def test_starting_a_submission_and_setting_its_work_from_excel(blank):
    items = _filled(blank)
    fresh = next(i for i in items if not i["issues"])
    book = _book(blank)
    subs = book["Submissions"]
    row = next(r for r in range(2, subs.max_row + 1) if subs.cell(r, 1).value == fresh["row"])
    subs.cell(row, _column(subs, "Planned to go")).value = "15/12/2026"
    subs.cell(row, _column(subs, "Work starts")).value = "01/12/2026"
    who = next(n for n in blank.workbook.engineer_names() if n not in fresh["people"])
    subs.cell(row, _column(subs, "Who prepares it")).value = who
    check = blank.bring_in_check([_as_file(book)])
    change = check["plan"]["changes"][0]
    assert change["start"] and change["prep"] == {"starts": "2026-12-01", "people": [who]}
    done = blank.bring_in_apply(check["token"])
    assert done["steps"][-1]["result"]["changed"] == 1, done["steps"][-1]
    assert blank.workbook.issues()[fresh["row"]][-1]["planned"] == "2026-12-15"
    assert blank.workbook.work_starts()[fresh["row"]] == dt.date(2026, 12, 1)
    assert blank.submission_register({"all": ["1"]})["items"][
        [i["row"] for i in items].index(fresh["row"])]["people"] == [who]


def test_the_route_and_the_screen_are_there():
    import pathlib
    root = pathlib.Path(plan_book.__file__).parent
    assert '("GET", "/api/plan-book", s("plan_book_download"), "manager")' in (
        root / "app.py").read_text(encoding="utf-8")
    js = (root / "static" / "bringin.js").read_text(encoding="utf-8")
    assert "function planPreview" in js and "function excelPanel" in js
