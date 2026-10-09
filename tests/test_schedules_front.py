"""Day-first date boxes, sheets that paste like Excel, and the submissions
sheet: the parts of dates.js, sheet.js and subs.js that can be run under Node."""
import json
import shutil
import subprocess

import pytest

from workload_app.app import STATIC_DIR

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _read(name):
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _function(source, name):
    start = source.index(f"\nfunction {name}(") + 1
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def _node(source):
    out = subprocess.run(["node", "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_every_page_with_dates_loads_the_day_first_boxes():
    for page in ("index.html", "member.html"):
        text = _read(page)
        assert '<script src="dates.js"></script>' in text, page
        assert '<script src="sheet.js"></script>' in text, page
        assert 'href="sheet.css"' in text, page
    assert '<script src="subs.js"></script>' in _read("index.html")


@needs_node
@pytest.mark.parametrize("typed, iso", [
    ("30/08/2026", "2026-08-30"), ("30/8/26", "2026-08-30"), ("30-08-2026", "2026-08-30"),
    ("30.08.2026", "2026-08-30"), ("30082026", "2026-08-30"), ("300826", "2026-08-30"),
    ("30 Aug 2026", "2026-08-30"), ("30 august", "2026-08-30"), ("2026-08-30", "2026-08-30"),
    ("08/09/2026", "2026-09-08"),          # always day first, never 9 August
    ("31/02/2026", ""), ("13/13/2026", ""), ("08/30/2026", ""), ("soon", ""), ("", ""),
])
def test_a_typed_date_is_read_day_first(typed, iso):
    src = _read("dates.js")
    js = ("const DAY_MONTHS = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];\n"
          "const isoOf = (y, m, d) => `${String(y).padStart(4,'0')}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;\n"
          + _function(src, "parseDayFirst")
          + f"\nconsole.log(JSON.stringify(parseDayFirst({json.dumps(typed)}, new Date(2026, 9, 9))));")
    assert _node(js) == iso


@needs_node
def test_a_block_copied_from_excel_is_read_cell_by_cell():
    js = (_function(_read("sheet.js"), "parseBlock")
          + '\nconsole.log(JSON.stringify(parseBlock("A\\t1\\r\\n\\"two\\nlines\\"\\t2\\r\\n")));')
    assert _node(js) == [["A", "1"], ["two\nlines", "2"]]


@needs_node
@pytest.mark.parametrize("before, after", [("", "0"), ("0", "1"), ("A", "B"), ("P01", "P02"), ("Z", "Z1")])
def test_the_screen_names_the_next_revision_as_the_server_does(before, after):
    from workload_app import revisions
    js = _function(_read("subs.js"), "nextRev") + f"\nconsole.log(JSON.stringify(nextRev({json.dumps(before)})));"
    assert _node(js) == after == revisions.next_rev(before)


@needs_node
def test_the_screen_reads_a_status_as_the_server_does():
    import datetime as dt
    from workload_app import revisions
    cases = [{"planned": "2026-10-20"}, {"planned": "2026-10-01"}, {"submitted": "2026-10-01"},
             {"submitted": "2026-10-01", "returned": "2026-10-05"},
             {"submitted": "2026-10-01", "returned": "2026-10-05", "code": "B"},
             {"submitted": "2026-10-01", "returned": "2026-10-05", "code": "A"}]
    js = (_function(_read("subs.js"), "subStatus")
          + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map((c) => subStatus(c, '2026-10-09'))));")
    assert _node(js) == [revisions.issue_status(c, dt.date(2026, 10, 9)) for c in cases]


def test_a_project_saves_itself_and_no_longer_asks_for_save():
    app = _read("app.js")
    assert "function scheduleSave()" in app and "function autoSave()" in app
    assert "'Save project'" not in app
