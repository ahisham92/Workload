"""Front-end bugs found in the review pass, checked against the static files.

Where the behaviour can only be seen by running the script, a small piece of
it is run under Node (skipped when Node is not installed).
"""
import json
import os
import re
import shutil
import subprocess

import pytest

from workload_app.app import STATIC_DIR


def _read(name):
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _scripts(page):
    return re.findall(r'<script src="([a-z0-9]+\.js)"', _read(page))


TOP_LEVEL = re.compile(
    r"^(?:async\s+)?(?:function\*?\s*|const\s+|let\s+|var\s+|class\s+)([A-Za-z_$][\w$]*)",
    re.M)

#: Names a classic script must not take at the top level: each one replaces
#: what the browser itself puts on window under that name.
WINDOW_BUILTINS = {"escape", "unescape", "open", "close", "print", "stop",
                   "alert", "confirm", "prompt", "find", "focus", "blur",
                   "scroll", "status", "name"}


@pytest.mark.parametrize("page", ["index.html", "member.html"])
def test_no_two_scripts_on_a_page_declare_the_same_global(page):
    # Every script on a page shares one global scope: a second
    # `function budgetBars` silently replaced the first for every caller.
    seen = {}
    clashes = []
    for script in _scripts(page):
        for name in set(TOP_LEVEL.findall(_read(script))):
            if name in seen:
                clashes.append(f"{name}: {seen[name]} and {script}")
            seen[name] = script
    assert clashes == []


@pytest.mark.parametrize("page", ["index.html", "member.html"])
def test_no_script_overwrites_a_window_builtin(page):
    taken = []
    for script in _scripts(page):
        for name in set(TOP_LEVEL.findall(_read(script))) & WINDOW_BUILTINS:
            taken.append(f"{script}: {name}")
    assert taken == []


def test_charts_still_offers_its_escape_to_the_other_scripts():
    charts = _read("charts.js")
    assert re.search(r"escape: chartEscape", charts)
    assert "charts.escape" in _read("checkins.js")


def test_a_leaders_view_of_someone_else_hides_their_own_week_too():
    # A lead switching to somebody they lead kept seeing "My week" -- their
    # own -- under that person's name.
    member = _read("member.js")
    hidden = re.search(r"for \(const id of \[([^\]]*)\]\) \{\s*if \(!own", member)
    assert hidden, "the list of own-only panels has moved"
    ids = re.findall(r"'([a-z]+)'", hidden.group(1))
    member_html = _read("member.html")
    own_panels = re.findall(r'class="panel md-panel" id="([a-z]+)"', member_html)
    assert set(own_panels) <= set(ids)


def test_marking_a_task_refreshes_the_task_list_and_my_week():
    # Done / Stuck change the task's status; the page's task table, its
    # open-hours count and My week kept showing the old status until reload.
    myday = _read("myday.js")
    member = _read("member.js")
    assert "window.memberPage = { refresh: refreshFigures }" in member
    mark = myday[myday.index("async function markTask"):myday.index("async function undo")]
    undo = myday[myday.index("async function undo"):myday.index("/* ---", myday.index("async function undo"))]
    assert "refreshAround()" in mark and "refreshAround()" in undo
    around = myday[myday.index("function refreshAround"):]
    assert "memberPage.refresh()" in around and "planReview.mine" in around


def test_the_tasks_tab_does_not_take_today_from_utc():
    app = _read("app.js")
    assert "new Date().toISOString().slice(0, 10)" not in app
    assert "monday.toISOString()" not in app


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node")
def test_today_is_the_local_day_just_after_midnight_in_cairo():
    app = _read("app.js")
    start = app.index("function todayLocal")
    source = app[start:app.index("\n}\n", start) + 3]
    script = source + (
        "const at = new Date(2026, 9, 8, 1, 30);"   # 01:30 local, 8 Oct
        "console.log(JSON.stringify([todayLocal(at), at.toISOString().slice(0, 10)]));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                         env={**os.environ, "TZ": "Africa/Cairo"}, check=True)
    local, utc = json.loads(out.stdout)
    assert utc == "2026-10-07", "the premise: UTC is still the day before"
    assert local == "2026-10-08"


def test_the_task_form_sends_progress_as_a_fraction():
    # The server reads 1 as a whole (tasks._parse_fraction), so "1" typed in
    # the Progress % box saved the task as 100% done.
    from workload_app import tasks
    assert tasks._parse_fraction(1) == 1.0          # the premise
    app = _read("app.js")
    edit = app[app.index("openModal(task ? `Task ${task.id}`"):app.index("async function toggleTaskDone")]
    assert "body.pro_rata = typed / 100" in edit
    assert tasks._parse_fraction(1 / 100) == 0.01


def test_the_timeline_steps_its_weeks_by_the_calendar():
    # 7 x 24 h from a Monday midnight is Sunday 23:00 after the clocks go
    # back, so every later tick was labelled a day early.
    assert "t += 7 * DAY" not in _read("tabs.js")
