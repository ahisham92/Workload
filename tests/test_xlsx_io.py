"""Reading an old unit's workbook cell by cell."""

import datetime as dt
import re

import pytest

from workload_app.xlsx_io import col_to_index, from_serial, index_to_col, split_ref


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
        assert from_serial(serial) == date

    def test_the_time_of_day_is_dropped(self):
        assert from_serial(46204.5) == dt.date(2026, 7, 1)


class TestSheetParsing:
    def test_reads_values_of_every_kind(self, raw):
        assert re.fullmatch(r"[A-Z]+\d+-\d{4}D", raw.get_text("Inputs", "A6"))
        assert raw.get_number("Inputs", "C6") == 2.4
        assert raw.get_date("Inputs", "D6") == dt.date(2026, 7, 1)
        assert raw.get_value("Inputs", "A5") == "Number"      # a header string

    def test_missing_cells_read_as_none(self, raw):
        assert raw.get_value("Inputs", "A60") is None


class TestFormulas:
    def test_a_formula_cell_is_told_apart_from_a_typed_one(self, raw):
        sheet = raw.sheet("Inputs")
        assert sheet.cell_has_formula("G60")
        assert not sheet.cell_has_formula("A6")
