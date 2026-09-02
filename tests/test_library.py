"""What counts as a Workload workbook, and what is turned away at the door."""

import pytest

from workload_app import library
from workload_app.library import NotAWorkbook


class TestValidation:
    def test_a_real_workbook_passes(self, workbook_copy):
        assert library.check(workbook_copy) == []
        assert library.validate(workbook_copy) == workbook_copy.resolve()

    def test_a_missing_file_is_named(self, tmp_path):
        with pytest.raises(NotAWorkbook, match="no file at"):
            library.validate(tmp_path / "nope.xlsx")

    def test_a_file_that_is_not_a_spreadsheet_is_refused(self, tmp_path):
        other = tmp_path / "notes.txt"
        other.write_text("hello")
        with pytest.raises(NotAWorkbook, match="not an .xlsx file"):
            library.validate(other)

    def test_something_that_is_not_a_zip_is_refused(self, tmp_path):
        broken = tmp_path / "broken.xlsx"
        broken.write_bytes(b"not a zip at all")
        with pytest.raises(NotAWorkbook, match="not readable as a spreadsheet"):
            library.validate(broken)

    def test_a_different_workbook_is_refused_by_name(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        other = tmp_path / "budget.xlsx"
        book = openpyxl.Workbook()
        book.active.title = "Summary"
        book.save(other)
        with pytest.raises(NotAWorkbook, match="does not look like the Workload"):
            library.validate(other)

    def test_the_missing_sheets_are_listed(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        other = tmp_path / "half.xlsx"
        book = openpyxl.Workbook()
        book.active.title = "Inputs"
        book.create_sheet("Deliverables")
        book.save(other)
        missing = library.check(other)
        assert "Inputs" not in missing
        assert "Timesheet Raw" in missing


class TestWhatIsRefused:
    """A file that is not this workbook must never reach the domain code."""

    def test_a_folder_is_not_a_workbook(self, tmp_path):
        with pytest.raises(NotAWorkbook):
            library.validate(tmp_path)
