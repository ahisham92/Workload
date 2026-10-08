"""Uploads and stored files that are a little unusual, but real."""

import io
import os
import re
import sqlite3
import time
import zipfile

import pytest

from workload_app import config as cfg, export, legacy, storage, timesheets
from workload_app.timesheet_store import TimesheetStore
from workload_app.model import ValidationError
from workload_app.unit import Unit

openpyxl = pytest.importorskip("openpyxl")


class TestTimesheetText:
    def test_a_windows_1252_csv_is_read_as_such(self):
        text = "JobNumber,FullName,Date,TotalHours,Note\r\nJ-001,José Exemplo,2026-03-02,8\r\n"
        data = text.encode("cp1252")
        assert len(data) % 2 == 0          # would "decode" as UTF-16 too
        parsed = timesheets.parse("Jose", "export.csv", data, cfg.TS_HEADERS)
        assert len(parsed.rows) == 1

    def test_a_utf16_csv_with_its_mark_still_reads(self):
        data = "JobNumber,FullName,Date,TotalHours\r\nJ-001,Pat,2026-03-02,8\r\n".encode("utf-16")
        assert len(timesheets.parse("Pat", "e.csv", data, cfg.TS_HEADERS).rows) == 1

    @pytest.mark.parametrize("text", [
        "2026-03-02T00:00:00", "2026-03-02 00:00:00.000", "2/3/2026 12:00:00 AM",
    ])
    def test_dates_with_a_time_keep_their_day(self, text):
        assert str(timesheets._coerce_date(text)) == "2026-03-02"

    @pytest.mark.parametrize("text", ["NaN", "inf", "-Infinity"])
    def test_not_a_number_is_blank_rather_than_a_crash(self, text):
        assert timesheets._coerce_number(text) is None
        csv = f"JobNumber,FullName,Date,TotalHours,Phase\r\nJ-1,Pat,2026-03-02,8,{text}\r\n"
        parsed = timesheets.parse("Pat", "e.csv", csv.encode(), cfg.TS_HEADERS)
        parsed.records()


class TestCopyToTakeAway:
    def _unit(self, tmp_path, job_type):
        unit = Unit(tmp_path / "u.db")
        unit.add_engineer({"short_name": "Pat", "available_hours": 185})
        csv = f"Job Type,JobNumber,FullName,Date,TotalHours\r\n{job_type},J-001,Pat,2026-03-02,8\r\n"
        parsed = timesheets.parse("Pat", "e.csv", csv.encode(), cfg.TS_HEADERS)
        unit.store.replace("Pat", parsed.records(), source="e.csv")
        return unit

    def test_control_characters_do_not_stop_the_download(self, tmp_path):
        assert export.unit_workbook(self._unit(tmp_path, "Design\x07"), "Unit")

    def test_text_starting_with_equals_is_kept_as_text(self, tmp_path):
        data = export.unit_workbook(self._unit(tmp_path, '=HYPERLINK("x")'), "Unit")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            sheets = [zf.read(n).decode() for n in zf.namelist()
                      if n.startswith("xl/worksheets/")]
        assert any('=HYPERLINK' in s for s in sheets)
        assert not any("<f>" in s for s in sheets)


class TestDrawingList:
    def test_a_stub_dimension_does_not_hide_the_drawings(self):
        from workload_app import drawing_list
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "Drawing list"
        sheet.append(["Job Number", "Deliverable", "Drawing No.", "Title", "Status"])
        for i in range(5):
            sheet.append(["J-001", "Design", f"D-{i}", f"Sheet {i}", "IFA"])
        buf = io.BytesIO()
        book.save(buf)
        src, out = zipfile.ZipFile(io.BytesIO(buf.getvalue())), io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for name in src.namelist():
                body = src.read(name)
                if name.startswith("xl/worksheets/"):
                    body = re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1"/>', body)
                zf.writestr(name, body)
        assert len(drawing_list.read(out.getvalue(), "list.xlsx")) == 5


class TestStoredUnits:
    def test_a_damaged_database_is_not_taken_as_a_unit(self, tmp_path):
        path = tmp_path / "x.db"
        db = sqlite3.connect(path)
        for table in ("projects", "deliverables", "engineers"):
            db.execute(f"CREATE TABLE {table}(a)")
        db.execute("CREATE TABLE rows(id INTEGER PRIMARY KEY, person TEXT, pad TEXT)")
        db.execute("CREATE INDEX rows_person ON rows(person)")
        db.executemany("INSERT INTO rows(person, pad) VALUES (?, ?)",
                       [(f"p{i}", "x" * 200) for i in range(3000)])
        db.commit()
        db.close()
        data = bytearray(path.read_bytes())
        at = (len(data) // 4096 - 1) * 4096 + 2000
        data[at:at + 200] = bytes(range(200))
        path.write_bytes(bytes(data))
        with pytest.raises(storage.NotAUnit):
            storage._check_unit_database(path)

    def test_the_old_files_kept_on_moving_across_are_not_a_recent_copy(
            self, source_path, tmp_path):
        unit_id = "a1b2c3d4e5f60718"
        folder = storage.user_dir(tmp_path, 1)
        (folder / f"{unit_id}.xlsx").write_bytes(source_path.read_bytes())
        old = folder / f"{unit_id}.timesheets.db"
        TimesheetStore(old)
        past = time.time() - 3 * 86400
        os.utime(old, (past, past))
        moved = storage.bring_across(tmp_path, 1, unit_id, f"{unit_id}.xlsx")
        for _ in range(3):
            storage.backup_if_due(tmp_path, 1, moved["path"])
        copies = storage.backups_of(tmp_path, 1, unit_id)
        assert len(copies) == 1
        assert "before-database" not in copies[0].name


class TestOldWorkbooks:
    def test_relationships_written_with_the_id_last_still_open(self, source_path, tmp_path):
        out = io.BytesIO()
        with zipfile.ZipFile(source_path) as src, zipfile.ZipFile(out, "w") as zf:
            for name in src.namelist():
                body = src.read(name)
                if name == "xl/_rels/workbook.xml.rels":
                    body = re.sub(rb'<Relationship Id="([^"]+)" ([^>]*?)/>',
                                  rb'<Relationship \2 Id="\1"/>', body)
                zf.writestr(name, body)
        result = storage.import_workbook(tmp_path, 1, "abcd1234abcd1234", out.getvalue())
        assert result["moved"]["projects"] > 0

    def test_a_number_typed_twice_keeps_the_first(self):
        rows = [{"number": "P1", "name": "first"}, {"number": "P2", "name": "x"},
                {"number": "P1", "name": "again"}]
        kept = legacy._first_of_each(rows, ("number",))
        assert [r["name"] for r in kept] == ["first", "x"]


class TestMeetings:
    def test_a_start_that_is_not_a_date_is_refused_plainly(self, tmp_path):
        unit = Unit(tmp_path / "u.db")
        with pytest.raises(ValidationError):
            unit.generate_weekly_meetings({"start": "07/10/2026"})
