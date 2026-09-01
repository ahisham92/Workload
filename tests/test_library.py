"""Choosing a workbook: what counts as one, and remembering the choice."""


import pytest

from workload_app import library
from workload_app.library import NotAWorkbook


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the tests away from the real ~/.workload_app.json."""
    monkeypatch.setattr(library, "SETTINGS_FILE", tmp_path / "settings.json")


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


class TestUnits:
    """A unit is a name and the workbook that belongs to it."""

    def test_a_unit_keeps_the_name_it_was_given(self, workbook_copy):
        library.save_unit("Marine Structures", workbook_copy)
        unit = library.units()[0]
        assert unit["name"] == "Marine Structures"
        assert unit["workbook"] == str(workbook_copy)
        assert unit["file_name"] == workbook_copy.name
        assert unit["exists"] is True

    def test_several_units_sit_side_by_side(self, workbook_copy, tmp_path):
        second = tmp_path / "Ports.xlsx"
        second.write_bytes(workbook_copy.read_bytes())
        library.save_unit("Marine Structures", workbook_copy)
        library.save_unit("Ports and Coastal", second)
        assert {u["name"] for u in library.units()} == {
            "Marine Structures", "Ports and Coastal"}

    def test_the_most_recently_opened_comes_first(self, workbook_copy, tmp_path):
        second = tmp_path / "Ports.xlsx"
        second.write_bytes(workbook_copy.read_bytes())
        library.save_unit("Marine Structures", workbook_copy)
        library.save_unit("Ports and Coastal", second)
        assert library.units()[0]["name"] == "Ports and Coastal"
        library.touch_unit(library.units()[-1]["id"])
        assert library.units()[0]["name"] == "Marine Structures"

    def test_saving_the_same_unit_twice_does_not_duplicate_it(self, workbook_copy):
        library.save_unit("Marine Structures", workbook_copy)
        library.save_unit("Marine Structures", workbook_copy)
        assert len(library.units()) == 1

    def test_a_unit_whose_file_has_gone_is_kept_but_flagged(self, tmp_path):
        gone = tmp_path / "gone.xlsx"
        gone.write_bytes(b"x")
        library.save_unit("Gone", gone)
        gone.unlink()
        unit = library.units()[0]
        assert unit["exists"] is False
        assert unit["name"] == "Gone"

    def test_forgetting_a_unit_leaves_the_workbook_alone(self, workbook_copy):
        unit = library.save_unit("Marine Structures", workbook_copy)
        library.forget_unit(unit["id"])
        assert library.units() == []
        assert workbook_copy.is_file()

    def test_a_unit_can_be_renamed(self, workbook_copy):
        unit = library.save_unit("Marnie Structures", workbook_copy)
        library.rename_unit(unit["id"], "Marine Structures")
        assert library.units()[0]["name"] == "Marine Structures"

    def test_find_unit(self, workbook_copy):
        unit = library.save_unit("Marine Structures", workbook_copy)
        assert library.find_unit(unit["id"])["name"] == "Marine Structures"
        assert library.find_unit("nope") is None


class TestLookingAround:
    def test_spreadsheets_nearby_are_found_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "sub").mkdir()
        (tmp_path / "one.xlsx").write_bytes(b"x")
        (tmp_path / "sub" / "two.xlsx").write_bytes(b"x")
        names = {c["name"] for c in library.candidates()}
        assert {"one.xlsx", "two.xlsx"} <= names

    def test_excel_lock_files_and_backups_are_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "~$open.xlsx").write_bytes(b"x")
        (tmp_path / "backups").mkdir()
        (tmp_path / "backups" / "old.xlsx").write_bytes(b"x")
        names = {c["name"] for c in library.candidates()}
        assert "~$open.xlsx" not in names
        assert "old.xlsx" not in names

    def test_browse_lists_folders_and_spreadsheets(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "book.xlsx").write_bytes(b"x")
        (tmp_path / "notes.txt").write_text("x")
        listing = library.browse(str(tmp_path))
        assert [f["name"] for f in listing["folders"]] == ["sub"]
        assert [f["name"] for f in listing["files"]] == ["book.xlsx"]
        assert listing["parent"] == str(tmp_path.parent)

    def test_browsing_nowhere_is_refused(self, tmp_path):
        with pytest.raises(NotAWorkbook, match="no folder at"):
            library.browse(str(tmp_path / "missing"))
