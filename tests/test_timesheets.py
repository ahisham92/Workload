"""Reading a monthly export and lining it up with the TS sheet."""

import datetime as dt
import io

import pytest

from workload_app import config as cfg, timesheets
from workload_app.timesheets import ImportError_


@pytest.fixture(scope="session")
def ts_headers(readonly_wb):
    return readonly_wb.timesheet_headers("Ahmed")


def make_export(headers, rows, *, title_block=True, shuffled=False):
    """Build an .xlsx export in memory, optionally with junk above the header."""
    openpyxl = pytest.importorskip("openpyxl")
    order = list(headers)
    if shuffled:
        order = order[::-1]
    book = openpyxl.Workbook()
    sheet = book.active
    if title_block:
        sheet.append(["Timesheet export"])
        sheet.append(["Generated 2026-09-01"])
        sheet.append([])
    sheet.append(order)
    for row in rows:
        sheet.append([row.get(header) for header in order])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def a_row(**overrides):
    row = {
        "Job Type": "1-Projects", "JobNumber": "N25185-0100D",
        "FullName": "Ahmed Mitwally", "Date": dt.date(2026, 9, 1), "Phase": 4,
        "RegularHours": 8.5, "OvertimeHours": 1.0, "TotalHours": 9.5,
        "WorkScope": "HO Design",
    }
    row.update(overrides)
    return row


def stub_dimension(data: bytes) -> bytes:
    """Rewrite a workbook's sheet dimension to the stub the real export uses."""
    import io
    import re
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                blob = source.read(info.filename)
                if info.filename.startswith("xl/worksheets/sheet"):
                    blob = re.sub(rb'<dimension ref="[^"]*"/>',
                                  b'<dimension ref="A1"/>', blob)
                target.writestr(info, blob)
    return out.getvalue()


class TestReadingFiles:
    def test_a_stub_dimension_does_not_hide_the_data(self, ts_headers):
        """The reporting tool writes `<dimension ref="A1"/>`.

        openpyxl's read-only mode trusts that and returns a single row, which
        made a real 923-row export look like a file with no header.
        """
        rows = [a_row(Date=dt.date(2026, 9, day)) for day in range(1, 21)]
        data = stub_dimension(make_export(ts_headers, rows))
        parsed = timesheets.parse("Ahmed", "export.xlsx", data, ts_headers)
        assert parsed.errors == []
        assert len(parsed.rows) == 20

    def test_a_title_block_above_the_headers_is_skipped(self, ts_headers):
        data = make_export(ts_headers, [a_row()])
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        assert parsed.errors == []
        assert len(parsed.rows) == 1

    def test_columns_are_matched_by_name_not_position(self, ts_headers):
        data = make_export(ts_headers, [a_row()], shuffled=True)
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        index = {h: i for i, h in enumerate(parsed.headers)}
        assert parsed.rows[0][index["JobNumber"]] == "N25185-0100D"
        assert parsed.rows[0][index["TotalHours"]] == 9.5

    def test_csv_is_accepted(self, ts_headers):
        body = ",".join(ts_headers) + "\n"
        row = a_row()
        body += ",".join(
            "" if row.get(h) is None else str(row.get(h)) for h in ts_headers) + "\n"
        parsed = timesheets.parse("Ahmed", "e.csv", body.encode(), ts_headers)
        assert parsed.errors == []
        index = {h: i for i, h in enumerate(parsed.headers)}
        assert parsed.rows[0][index["Date"]] == dt.date(2026, 9, 1)

    def test_a_file_without_headers_is_refused(self, ts_headers):
        with pytest.raises(ImportError_, match="No header row"):
            timesheets.parse("Ahmed", "e.csv", b"a,b,c\n1,2,3\n", ts_headers)

    def test_a_file_missing_a_needed_column_is_refused(self, ts_headers):
        headers = [h for h in ts_headers if h != "TotalHours"]
        data = make_export(headers, [a_row()], title_block=False)
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        assert any("TotalHours" in message for message in parsed.errors)


class TestCoercion:
    def test_dates_become_dates_and_hours_become_numbers(self, ts_headers):
        data = make_export(ts_headers, [a_row(Date="2026-09-05", TotalHours="9.5")])
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        index = {h: i for i, h in enumerate(parsed.headers)}
        assert parsed.rows[0][index["Date"]] == dt.date(2026, 9, 5)
        assert parsed.rows[0][index["TotalHours"]] == 9.5

    def test_blank_cells_stay_blank(self, ts_headers):
        data = make_export(ts_headers, [a_row(OvertimeHours=None)])
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        index = {h: i for i, h in enumerate(parsed.headers)}
        assert parsed.rows[0][index["OvertimeHours"]] is None


class TestSummaryAndGuards:
    def test_one_persons_export_on_another_persons_sheet_is_refused(self, ts_headers):
        data = make_export(ts_headers, [a_row()])
        parsed = timesheets.parse("Kirolos", "e.xlsx", data, ts_headers,
                                  name_pattern="*Kirolos*")
        assert parsed.ok is False
        assert any("Ahmed Mitwally" in message for message in parsed.errors)

    def test_the_right_persons_export_passes(self, ts_headers):
        data = make_export(ts_headers, [a_row()])
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers,
                                  name_pattern="*Ahmed*")
        assert parsed.ok

    def test_job_numbers_outside_the_register_are_flagged(self, ts_headers):
        data = make_export(ts_headers, [a_row(JobNumber="MYSTERY-0100D")])
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers,
                                  known_job_numbers={"N25185-0100D"})
        assert parsed.summary["unknown_job_numbers"][0]["code"] == "MYSTERY-0100D"
        assert any("not in the project register" in w for w in parsed.warnings)

    def test_rows_without_a_date_or_phase_are_reported(self, ts_headers):
        data = make_export(ts_headers, [a_row(Date=None), a_row(Phase=None)])
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        assert parsed.summary["rows_without_date"] == 1
        assert parsed.summary["rows_without_phase"] == 1

    def test_the_summary_totals_the_period(self, ts_headers):
        rows = [a_row(Date=dt.date(2026, 9, day), TotalHours=8.0) for day in (1, 2, 30)]
        data = make_export(ts_headers, rows)
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        assert parsed.summary["rows"] == 3
        assert parsed.summary["hours"] == 24.0
        assert parsed.summary["first_date"] == "2026-09-01"
        assert parsed.summary["last_date"] == "2026-09-30"
        assert parsed.summary["months"] == ["2026-09"]

    def test_duplicates_are_counted_before_an_append(self, ts_headers):
        data = make_export(ts_headers, [a_row(), a_row(Date=dt.date(2026, 9, 2))])
        parsed = timesheets.parse("Ahmed", "e.xlsx", data, ts_headers)
        assert timesheets.find_duplicates(
            parsed.rows[:1], parsed.rows, parsed.headers) == 1


class TestWritingBack:
    def _rows(self, wb, count=5):
        headers = wb.timesheet_headers("Kirolos")
        rows = [a_row(FullName="Kirolos Nabil", Date=dt.date(2026, 9, day))
                for day in range(1, count + 1)]
        data = make_export(headers, rows)
        return timesheets.parse("Kirolos", "e.xlsx", data, headers,
                                name_pattern="*Kirolos*")

    def test_replace_writes_exactly_the_new_rows(self, wb):
        parsed = self._rows(wb)
        result = wb.replace_timesheet("Kirolos", parsed.rows)
        assert result["rows"] == 5
        stored = wb.timesheet_rows("Kirolos", ["B", "C", "L", "P"])
        assert len(stored) == 5
        assert stored[0]["C"] == "Kirolos Nabil"

    def test_written_rows_read_back_as_the_right_types(self, wb, workbook_copy):
        parsed = self._rows(wb, 3)
        wb.replace_timesheet("Kirolos", parsed.rows)
        wb.save()
        openpyxl = pytest.importorskip("openpyxl")
        sheet = openpyxl.load_workbook(workbook_copy)["TS Kirolos"]
        assert sheet["L4"].value == dt.datetime(2026, 9, 1)
        assert sheet["L4"].number_format == "yyyy\\-mm\\-dd"
        assert sheet["P4"].value == 9.5
        assert sheet.max_row == cfg.TS_FIRST_DATA_ROW + 2

    def test_the_header_row_is_never_touched(self, wb):
        before = wb.timesheet_headers("Kirolos")
        wb.replace_timesheet("Kirolos", self._rows(wb).rows)
        assert wb.timesheet_headers("Kirolos") == before

    def test_the_other_engineers_sheets_are_left_alone(self, wb):
        before = len(wb.timesheet_rows("Ahmed", ["B"]))
        wb.replace_timesheet("Kirolos", self._rows(wb).rows)
        assert len(wb.timesheet_rows("Ahmed", ["B"])) == before

    def test_more_rows_than_the_workbook_reads_are_refused(self, wb):
        from workload_app.workbook import ValidationError
        # The limit is whatever the stack actually reads from each sheet,
        # not a constant -- raising the stack raises this too.
        reads = wb.timesheet_capacity()["per_sheet_capacity"]
        too_many = [[None] * 72] * (reads + 1)
        with pytest.raises(ValidationError, match="more than the"):
            wb.replace_timesheet("Kirolos", too_many)

    def test_an_unknown_engineer_is_refused(self, wb):
        from workload_app.workbook import ValidationError
        with pytest.raises(ValidationError, match="not one of this workbook"):
            wb.replace_timesheet("Someone", [])
