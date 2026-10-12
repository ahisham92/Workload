"""Date history: when a submission's planned day moves, the old day is kept
with the day the move was saved, so a slip shows (Ahmed, 2026-10-12)."""

import datetime as dt
import sqlite3

from workload_app import revisions
from workload_app.unit import Unit

TODAY = dt.date(2026, 10, 9)


def first_open(wb):
    return next(d for d in wb.deliverables() if not wb.issues().get(d.row))


def test_moving_the_planned_day_keeps_the_old_one(wb):
    d = first_open(wb)
    one = wb.start_issue(d.row, {"planned": "2026-10-20"}, today=TODAY)
    assert not wb.date_moves().get(d.row)            # setting it is not a move
    wb.update_issue(one["id"], {"planned": "2026-10-27"})
    wb.update_issue(one["id"], {"planned": "2026-11-03"})
    moves = wb.date_moves()[d.row]
    assert [(m["old_date"], m["new_date"]) for m in moves] == [
        ("2026-10-20", "2026-10-27"), ("2026-10-27", "2026-11-03")]
    assert all(m["issue_id"] == one["id"] and m["rev"] == "0" for m in moves)
    assert all(dt.datetime.strptime(m["saved_at"], "%Y-%m-%dT%H:%M:%SZ") for m in moves)
    slip = revisions.slip(moves, one["id"])
    assert slip == {"first": "2026-10-20", "now": "2026-11-03", "times": 2, "days": 14}


def test_the_same_day_saved_again_or_a_day_once_sent_is_no_move(wb):
    d = first_open(wb)
    one = wb.start_issue(d.row, {"planned": "2026-10-20"}, today=TODAY)
    wb.update_issue(one["id"], {"planned": "2026-10-20", "purpose": "IFA"})
    wb.update_issue(one["id"], {"submitted": "2026-10-19"})
    wb.update_issue(one["id"], {"planned": "2026-10-18"})   # putting the record right
    assert not wb.date_moves().get(d.row)


def test_a_date_typed_on_the_project_is_caught_too(wb):
    d = first_open(wb)
    wb.start_issue(d.row, {"planned": "2026-10-20"}, today=TODAY)
    project = wb.project(d.project_number)
    items = [x.to_dict() for x in wb.deliverables() if x.project_number == project.number]
    for item in items:
        if item["row"] == d.row:
            item["status_date"] = "2026-12-01"
    wb.save_project_with_deliverables(project.number, project.to_dict(), items)
    assert [(m["old_date"], m["new_date"]) for m in wb.date_moves()[d.row]] == [
        ("2026-10-20", "2026-12-01")]


def test_a_unit_from_before_gains_the_history_table(unit_copy):
    db = sqlite3.connect(unit_copy)
    db.execute("DROP TRIGGER IF EXISTS date_moves_planned")
    db.execute("DROP TABLE IF EXISTS date_moves")
    db.commit()
    db.close()
    wb = Unit(unit_copy)
    d = first_open(wb)
    one = wb.start_issue(d.row, {"planned": "2026-10-20"}, today=TODAY)
    wb.update_issue(one["id"], {"planned": "2026-10-22"})
    assert len(wb.date_moves()[d.row]) == 1


def test_removing_the_deliverable_takes_its_history_with_it(wb):
    d = first_open(wb)
    one = wb.start_issue(d.row, {"planned": "2026-10-20"}, today=TODAY)
    wb.update_issue(one["id"], {"planned": "2026-10-21"})
    wb.delete_deliverable(d.row)
    assert d.row not in wb.date_moves()


def test_the_register_and_the_card_carry_the_history():
    text = open(revisions.__file__.replace("revisions.py", "service.py"), encoding="utf-8").read()
    assert '"moves": history' in text and "revisions_module.slip(" in text
    js = open(revisions.__file__.replace("revisions.py", "static/subs.js"), encoding="utf-8").read()
    for bit in ("function slipStrip", "function slipPart", "Has the date moved?", "slipBadge(item"):
        assert bit in js
