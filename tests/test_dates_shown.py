"""Every date the app shows is day-first, whatever the phone's locale.

The owner reads the app on an iPhone that may be set to US English, where
`toLocaleDateString()` with no locale gives "10/8/2026" and "Oct 8". The front
end therefore names 'en-GB' wherever it lets the browser write a date, and
shows full dates as DD/MM/YYYY. Where the behaviour can only be seen by
running the script, a small piece of it is run under Node (skipped when Node
is not installed).
"""
import json
import re
import shutil
import subprocess

import pytest

from workload_app.app import STATIC_DIR

#: Our own scripts; vendor/ is third-party and voyage.js shows no dates.
SCRIPTS = sorted(p for p in STATIC_DIR.glob("*.js") if p.name not in ("voyage.js", "sw.js"))
PAGES = sorted(STATIC_DIR.glob("*.html"))

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _read(name):
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _node(source):
    out = subprocess.run(["node", "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _function(source, name):
    """The text of a top-level `function name(...) { ... }` in a script."""
    start = source.index(f"\nfunction {name}(") + 1
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def _const(source, name):
    start = source.index(f"\nconst {name} = ") + 1
    end = source.index(";\n", start) + 2
    return source[start:end]


# ------------------------------------------------------------ static checks

@pytest.mark.parametrize("path", SCRIPTS + PAGES, ids=lambda p: p.name)
def test_no_date_is_written_in_the_browsers_own_locale(path):
    text = path.read_text(encoding="utf-8")
    # toLocaleDateString() / toLocaleDateString(undefined, ...) / ([], ...)
    bad = re.findall(r"toLocale(?:Date|Time)String\(\s*(?:\)|undefined|\[\])", text)
    assert not bad, f"{path.name}: dates must name 'en-GB', found {bad}"
    bad = re.findall(r"Intl\.DateTimeFormat\(\s*(?:\)|undefined|\[\]|navigator)", text)
    assert not bad, f"{path.name}: dates must name 'en-GB', found {bad}"
    # new Date(...).toLocaleString() would print the date month-first in the US
    assert not re.search(r"new Date\([^)]*\)\.toLocaleString\(\s*(?:\)|undefined|\[\])", text), path.name


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_no_iso_date_is_cut_out_for_the_screen(path):
    # "2026-10-08T..." sliced to "2026-10-08" and shown as it is; fmt.date
    # takes the whole value now. "MM-DD" sliced off a date reads month-first.
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"\.(?:week|date|due|day)\.slice\(5\)", text), path.name
    assert not re.search(r"el\('td', \{\}, [^)]*String\([^)]*\)\.slice\(0, 10\)", text), path.name


def test_both_fmt_dates_go_through_the_day_first_helper():
    for name in ("app.js", "member.js"):
        source = _read(name)
        assert "date: (v) => dayFirst(v)" in source, name
        assert "function dayFirst(" in source, name


# ------------------------------------------------------------ run under Node

@needs_node
@pytest.mark.parametrize("script", ["app.js", "member.js"])
def test_fmt_date_is_dd_mm_yyyy(script):
    source = _read(script)
    code = _function(source, "dayFirst") + """
    console.log(JSON.stringify([
      dayFirst('2026-10-08'), dayFirst('2026-10-08T16:43:15+00:00'),
      dayFirst(''), dayFirst(null), dayFirst(undefined), dayFirst('not a date'),
    ]));"""
    assert _node(code) == ["08/10/2026", "08/10/2026", "—", "—", "—", "not a date"]


@needs_node
def test_months_and_server_sentences_are_day_first():
    source = _read("app.js")
    code = "\n".join([
        _const(source, "MONTH_NAMES"),
        _function(source, "monthLabel"),
        _function(source, "dayFirstText"),
        _function(source, "shortMonth"),
    ]) + """
    console.log(JSON.stringify([
      monthLabel('2026-10'), monthLabel('Q4 2026'), shortMonth('2026-03'),
      dayFirstText('At 120% of capacity since 2026-06, about 0.6 people short'),
      dayFirstText('Pile check: not done, due 2026-10-05'),
      dayFirstText('Job 2026-0412 and 25-0412 stay as they are'),
      dayFirstText(null),
    ]));"""
    assert _node(code) == [
        "Oct 2026", "Q4 2026", "Mar ’26",
        "At 120% of capacity since Jun 2026, about 0.6 people short",
        "Pile check: not done, due 05/10/2026",
        "Job 2026-0412 and 25-0412 stay as they are",
        None,
    ]


@needs_node
def test_member_page_sentences_are_day_first_too():
    source = _read("member.js")
    code = "\n".join([_const(source, "MONTH_NAMES"), _function(source, "dayFirstText")]) + """
    console.log(JSON.stringify(dayFirstText('Timesheets stop at 2026-09-30, since 2026-06.')));"""
    assert _node(code) == "Timesheets stop at 30/09/2026, since Jun 2026."


@needs_node
def test_en_gb_gives_day_before_month():
    code = """
    const d = new Date('2026-10-08T00:00:00');
    console.log(JSON.stringify([
      d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }),
      d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
    ]));"""
    assert _node(code) == ["8 Oct", "8 Oct 2026"]


@needs_node
def test_tables_sort_day_first_dates_by_the_real_date():
    stub = """
    global.window = {};
    global.document = { readyState: 'complete', body: {},
      querySelectorAll: () => [], addEventListener: () => {} };
    global.MutationObserver = class { observe() {} };
    global.requestAnimationFrame = () => {};
    """
    code = stub + _read("tables.js") + """
    const key = window.tablesDateKey;
    const shown = ['05/11/2026', '30/09/2026', '08/10/2026 overdue', '01/01/2027', '31/12/2025'];
    const sorted = shown.slice().sort((a, b) => key(a) - key(b));
    console.log(JSON.stringify({
      sorted,
      words: ['8 Oct 2026', 'Thu 8 Oct 2026', '28 Sept 2026', 'Oct 2026', 'Mar ’26', '2026-10-08', '2026-06']
        .map(key),
      notDates: [key('12.5'), key('Osama'), key('2026')],
    }));"""
    result = _node(code)
    assert result["sorted"] == ["31/12/2025", "30/09/2026", "08/10/2026 overdue",
                                "05/11/2026", "01/01/2027"]
    assert result["words"] == [20261008, 20261008, 20260928, 20261000, 20260300,
                               20261008, 20260600]
    assert result["notDates"] == [None, None, None]
