"""Submissions and revisions: planned, really sent, returned with a reason,
and the next revision, with the whole history kept (revisions.py)."""

import datetime as dt
import sqlite3

import pytest

from workload_app import revisions
from workload_app.model import ValidationError, as_date
from workload_app.unit import Unit

TODAY = dt.date(2026, 10, 9)


# ------------------------------------------------------------ the rules

@pytest.mark.parametrize("before, after", [
    ("", "0"), ("0", "1"), ("9", "10"), ("A", "B"), ("P01", "P02"), ("Z", "Z1"),
])
def test_the_next_revision_follows_on_from_the_last(before, after):
    assert revisions.next_rev(before) == after


@pytest.mark.parametrize("typed, code", [
    ("A", "A"), ("b", "B"), ("Code C", "C"), ("2", "B"), ("4", "C"),
    ("approved with comments", "B"), ("Rejected", "C"), ("", ""), ("banana", "?"),
])
def test_client_codes_are_read_however_they_are_written(typed, code):
    assert revisions.clean_code(typed) == code


def issue(**kw):
    base = {"id": 1, "seq": 1, "rev": "0", "purpose": "", "planned": None,
            "submitted": None, "returned": None, "code": "", "reason": "", "ref": ""}
    return {**base, **kw}


@pytest.mark.parametrize("kw, status", [
    ({"planned": "2026-10-20"}, "planned"),
    ({"planned": "2026-10-01"}, "late"),
    ({"submitted": "2026-10-01"}, "with_client"),
    ({"submitted": "2026-10-01", "returned": "2026-10-05", "code": "C"}, "returned"),
    ({"submitted": "2026-10-01", "returned": "2026-10-05"}, "returned"),
    ({"submitted": "2026-10-01", "returned": "2026-10-05", "code": "B"}, "comments"),
    ({"submitted": "2026-10-01", "returned": "2026-10-05", "code": "A"}, "accepted"),
])
def test_each_submission_says_where_it_stands(kw, status):
    assert revisions.issue_status(issue(**kw), TODAY) == status


def test_a_returned_submission_can_go_again_but_one_on_its_way_cannot():
    sent = revisions.describe([issue(submitted="2026-10-01")], TODAY)
    assert not sent["can_start"]
    back = revisions.describe([issue(submitted="2026-10-01", returned="2026-10-05",
                                     code="C", reason="Piles to be resized")], TODAY)
    assert back["can_start"] and back["next_rev"] == "1"
    assert back["status_label"] == "Returned: revise"


def test_the_deliverable_dates_follow_its_submissions():
    history = [issue(id=1, seq=1, submitted="2026-08-01", returned="2026-08-20", code="C"),
               issue(id=2, seq=2, rev="1", submitted="2026-09-10")]
    dates = revisions.dates_for(history)
    assert dates["submitted_to_client"] == "2026-08-01"
    assert dates["resubmitted"] == "2026-09-10"
    # Rev 1 is with the client, so it is waiting for comments again.
    assert dates["comments_received"] is None and dates["completed"] is None
    history[1].update(returned="2026-10-01", code="A")
    dates = revisions.dates_for(history)
    assert dates["comments_received"] == "2026-10-01" and dates["completed"] == "2026-10-01"


def test_dates_are_checked_and_read_day_first():
    merged, errors = revisions.check(issue(), {"submitted": "30/08/2026"}, as_date)
    assert not errors and merged["submitted"] == "2026-08-30"
    _, errors = revisions.check(issue(), {"returned": "01/09/2026"}, as_date)
    assert errors      # nothing comes back before it went
    _, errors = revisions.check(issue(submitted="2026-09-10"), {"returned": "01/09/2026"}, as_date)
    assert errors      # nor before the day it went
    _, errors = revisions.check(issue(submitted="2026-09-10"), {"code": "Z9"}, as_date)
    assert errors


# ------------------------------------------------------------ on a unit

def first_open(wb):
    return next(d for d in wb.deliverables() if not wb.issues().get(d.row))


def test_start_send_return_and_revise_keeps_the_whole_history(wb):
    d = first_open(wb)
    one = wb.start_issue(d.row, {"planned": "2026-10-20", "purpose": "IFA"}, today=TODAY)
    assert one["rev"] == "0"
    assert wb.deliverable(d.row).status_date == dt.date(2026, 10, 20)
    with pytest.raises(ValidationError):      # one is already on its way
        wb.start_issue(d.row, {}, today=TODAY)
    wb.update_issue(one["id"], {"submitted": "21/10/2026"})
    assert wb.deliverable(d.row).submitted_to_client == dt.date(2026, 10, 21)
    wb.update_issue(one["id"], {"returned": "2026-11-02", "code": "C",
                                "reason": "Bearing piles to be resized"})
    assert wb.deliverable(d.row).comments_received == dt.date(2026, 11, 2)
    two = wb.start_issue(d.row, {"planned": "2026-11-15"}, today=TODAY)
    assert two["rev"] == "1" and two["purpose"] == "IFA"
    wb.update_issue(two["id"], {"submitted": "2026-11-14"})
    got = wb.deliverable(d.row)
    assert got.resubmitted == dt.date(2026, 11, 14) and got.comments_received is None
    history = wb.issues()[d.row]
    assert [h["rev"] for h in history] == ["0", "1"]
    assert history[0]["reason"] == "Bearing piles to be resized"


def test_removing_the_only_submission_clears_the_sent_dates(wb):
    d = first_open(wb)
    one = wb.start_issue(d.row, {"submitted": "2026-10-01"}, today=TODAY)
    assert wb.deliverable(d.row).submitted_to_client
    wb.delete_issue(one["id"])
    assert wb.deliverable(d.row).submitted_to_client is None
    assert not wb.issues().get(d.row)


def test_saving_the_project_does_not_undo_its_submissions(wb):
    d = first_open(wb)
    project = wb.project(d.project_number)
    stale = [x.to_dict() for x in wb.deliverables() if x.project_number == project.number]
    wb.start_issue(d.row, {"submitted": "2026-10-01"}, today=TODAY)
    wb.save_project_with_deliverables(project.number, project.to_dict(), stale)
    assert wb.deliverable(d.row).submitted_to_client == dt.date(2026, 10, 1)


def test_a_status_date_typed_on_the_project_moves_the_planned_revision(wb):
    d = first_open(wb)
    one = wb.start_issue(d.row, {"planned": "2026-10-20"}, today=TODAY)
    project = wb.project(d.project_number)
    items = [x.to_dict() for x in wb.deliverables() if x.project_number == project.number]
    for item in items:
        if item["row"] == d.row:
            item["status_date"] = "2026-12-01"
    wb.save_project_with_deliverables(project.number, project.to_dict(), items)
    assert wb._issue(one["id"])["planned"] == "2026-12-01"


def test_a_unit_from_before_keeps_its_dates_and_gains_their_history(unit_copy):
    wb = Unit(unit_copy)
    d = first_open(wb)
    data = d.to_dict()
    data.update(submitted_to_client="2026-07-01", comments_received="2026-07-20",
                resubmitted="2026-08-05", completed="2026-08-30")
    # Written straight in, as a unit from before issues were kept would hold it.
    db = sqlite3.connect(unit_copy)
    db.execute("UPDATE deliverables SET submitted_to_client = ?, comments_received = ?, "
               "resubmitted = ?, completed = ? WHERE row = ?",
               ("2026-07-01", "2026-07-20", "2026-08-05", "2026-08-30", d.row))
    db.commit()
    db.close()
    again = Unit(unit_copy)
    history = again.issues()[d.row]
    assert [(h["rev"], h["submitted"], h["returned"], h["code"]) for h in history] == [
        ("0", "2026-07-01", "2026-07-20", ""), ("1", "2026-08-05", "2026-08-30", "A")]
    got = again.deliverable(d.row)
    # The dates themselves are left exactly as they were.
    assert (got.submitted_to_client, got.comments_received, got.resubmitted, got.completed) == (
        dt.date(2026, 7, 1), dt.date(2026, 7, 20), dt.date(2026, 8, 5), dt.date(2026, 8, 30))


def test_the_routes_are_there():
    text = open(revisions.__file__.replace("revisions.py", "app.py"), encoding="utf-8").read()
    for route in ('("GET", "/api/submission-issues"', '("POST", "/api/submission-issues"',
                  '("PUT", "/api/submission-issues/{}"', '("DELETE", "/api/submission-issues/{}"'):
        assert route in text
