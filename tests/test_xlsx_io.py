"""The xlsx layer must not disturb anything it was not asked to change."""

import datetime as dt
import zipfile

import pytest

from workload_app.xlsx_io import (
    XlsxError, build_cell, col_to_index, from_serial, index_to_col, split_ref,
    to_serial,
)


class TestReferences:
    @pytest.mark.parametrize("col,index", [
        ("A", 1), ("Z", 26), ("AA", 27), ("AZ", 52), ("BT", 72), ("XFD", 16384),
    ])
    def test_column_letters_round_trip(self, col, index):
        assert col_to_index(col) == index
        assert index_to_col(index) == col

    def test_split_ref(self):
        assert split_ref("AB12") == ("AB", 12)
        with pytest.raises(ValueError):
            split_ref("12AB")


class TestDates:
    @pytest.mark.parametrize("date,serial", [
        (dt.date(2026, 7, 1), 46204),
        (dt.date(2024, 8, 28), 45532),
        (dt.date(1900, 3, 1), 61),
    ])
    def test_serials_match_excel(self, date, serial):
        assert to_serial(date) == serial
        assert from_serial(serial) == date

    def test_datetime_keeps_the_time_of_day(self):
        assert to_serial(dt.datetime(2026, 7, 1, 12, 0)) == pytest.approx(46204.5)


class TestBuildCell:
    def test_blank_cell_keeps_its_style(self):
        assert build_cell("A1", None, "34") == '<c r="A1" s="34"/>'

    def test_text_is_written_inline_so_shared_strings_stay_untouched(self):
        assert build_cell("A1", "hi", "3") == (
            '<c r="A1" s="3" t="inlineStr"><is><t xml:space="preserve">hi</t></is></c>'
        )

    def test_markup_in_text_is_escaped(self):
        cell = build_cell("A1", 'a & b <c> "d"')
        assert "a &amp; b &lt;c&gt;" in cell

    def test_whole_numbers_do_not_gain_a_decimal_point(self):
        assert build_cell("A1", 5.0) == "<c r=\"A1\"><v>5</v></c>"


class TestSheetParsing:
    def test_every_sheet_reassembles_byte_for_byte(self, raw, workbook_copy):
        with zipfile.ZipFile(workbook_copy) as zf:
            for name, path in raw._sheet_paths.items():
                assert raw.sheet(name).xml == zf.read(path).decode("utf-8"), name

    def test_reads_values_of_every_kind(self, raw):
        assert raw.get_text("Inputs", "A6") == "N25178-0100D"
        assert raw.get_number("Inputs", "C6") == 2.4
        assert raw.get_date("Inputs", "D6") == dt.date(2026, 7, 1)
        assert raw.get_value("Inputs", "A5") == "Number"      # a header string

    def test_missing_cells_read_as_none(self, raw):
        assert raw.get_value("Inputs", "A60") is None


class TestWriting:
    def test_writing_keeps_the_template_style(self, raw):
        sheet = raw.sheet("Inputs")
        assert sheet.cell_style("A60") == "34"
        sheet.set_value("A60", "NEW-0001D")
        assert sheet.cell_style("A60") == "34"
        assert raw.get_text("Inputs", "A60") == "NEW-0001D"

    def test_formula_cells_are_protected(self, raw):
        sheet = raw.sheet("Inputs")
        assert sheet.cell_has_formula("G60")
        with pytest.raises(XlsxError, match="holds a formula"):
            sheet.set_value("G60", 1)

    def test_a_cell_can_be_cleared_again(self, raw):
        sheet = raw.sheet("Inputs")
        sheet.set_value("A60", "TEMP")
        sheet.set_value("A60", None)
        assert raw.get_value("Inputs", "A60") is None

    def test_inserting_a_cell_keeps_column_order(self, raw):
        sheet = raw.sheet("Deliverable Actuals")
        sheet.set_value("W5", dt.date(2026, 1, 1))
        row = sheet.row_xml(5)
        assert row.index('r="W5"') < row.index('r="AC5"')

    def test_replacing_a_row_block_drops_the_old_rows(self, raw):
        sheet = raw.sheet("TS Osama")
        header_rows = [n for n in sheet.row_numbers() if n < 4]
        assert len(sheet.row_numbers()) > 900
        sheet.replace_rows_from(4, ['<row r="4"><c r="A4"><v>1</v></c></row>'])
        assert sheet.row_numbers() == header_rows + [4]


class TestSaving:
    def test_only_the_edited_parts_change(self, raw, workbook_copy, source_path):
        raw.sheet("Inputs").set_value("A60", "NEW-0001D")
        raw.force_full_recalc()
        raw.save()
        with zipfile.ZipFile(source_path) as before, zipfile.ZipFile(workbook_copy) as after:
            names_before, names_after = set(before.namelist()), set(after.namelist())
            assert names_before == names_after
            changed = {n for n in names_before if before.read(n) != after.read(n)}
        assert changed == {"xl/workbook.xml", "xl/worksheets/sheet9.xml"}

    def test_charts_drawings_and_comments_survive(self, raw, workbook_copy):
        raw.sheet("Inputs").set_value("A60", "NEW-0001D")
        raw.save()
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.load_workbook(workbook_copy)
        assert sum(len(book[name]._charts) for name in book.sheetnames) == 14
        with zipfile.ZipFile(workbook_copy) as zf:
            names = set(zf.namelist())
        assert "xl/comments1.xml" in names
        assert "xl/webextensions/webextension1.xml" in names

    def test_full_recalc_is_requested(self, raw, workbook_copy):
        raw.sheet("Inputs").set_value("A60", "X")
        raw.force_full_recalc()
        raw.save()
        with zipfile.ZipFile(workbook_copy) as zf:
            assert 'fullCalcOnLoad="1"' in zf.read("xl/workbook.xml").decode()

    def test_dropping_the_calc_chain_also_clears_its_references(self, raw, workbook_copy):
        raw.drop_calc_chain()
        raw.save()
        with zipfile.ZipFile(workbook_copy) as zf:
            names = zf.namelist()
            assert "xl/calcChain.xml" not in names
            assert "calcChain" not in zf.read("[Content_Types].xml").decode()
            assert "calcChain" not in zf.read("xl/_rels/workbook.xml.rels").decode()

    def test_backup_is_a_copy_of_what_was_on_disk(self, raw, tmp_path, source_path):
        backup = raw.backup(tmp_path / "backups")
        assert backup.is_file()
        assert backup.read_bytes() == source_path.read_bytes()
