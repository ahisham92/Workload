"""Timesheet exports chosen together: the same rows twice count once."""

from __future__ import annotations

from tests.test_from_timesheets import D, blank, export, row  # noqa: F401


def _ahmed():
    return [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 2), 8),
            row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 3), 8)]


class TestTheSameExportTwice:
    def test_the_same_file_chosen_twice_counts_its_hours_once(self, blank):
        staged = blank.stage_exports([export(_ahmed(), "export.xlsx"),
                                      export(_ahmed(), "export (1).xlsx")])
        assert staged["rows"] == 2
        assert staged["hours"] == 16

    def test_a_row_a_file_holds_twice_is_still_kept_twice(self, blank):
        twice = _ahmed() + _ahmed()[:1]
        staged = blank.stage_exports([export(twice, "export.xlsx"),
                                      export(_ahmed(), "export (1).xlsx")])
        assert staged["rows"] == 3
        assert staged["hours"] == 24

    def test_files_with_different_days_add_up(self, blank):
        later = [row("Ahmed Mockridge", "T10001-0100D", D(2026, 8, 4), 8)]
        staged = blank.stage_exports([export(_ahmed(), "export.xlsx"),
                                      export(later, "later.xlsx")])
        assert staged["rows"] == 3
