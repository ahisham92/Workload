"""Front-end bugs found in the third review pass (static/*.js).

Each one is checked by running the piece of the script under Node, with a
small stand-in for the page (skipped when Node is not installed): the
behaviour is what broke, so the behaviour is what is checked.
"""
import json
import re
import shutil
import subprocess

import pytest

from workload_app.app import STATIC_DIR

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _read(name):
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def _function(name, script):
    """A top-level `function name(...)` (or `async function`) of a script."""
    source = _read(script)
    match = re.search(rf"\n((?:async )?function {name}\()", source)
    assert match, f"{script} has no function {name}"
    start = match.start(1)
    end = source.index("\n}\n", start) + 3
    return source[start:end]


def _inner(name, script):
    """A `function name(...)` written one level in, inside a script's IIFE."""
    source = _read(script)
    start = source.index(f"\n  function {name}(") + 1
    end = source.index("\n  }\n", start) + 5
    return source[start:end]


def _const(name, script):
    source = _read(script)
    start = source.index(f"\nconst {name} = ") + 1
    end = source.index(";\n", start) + 2
    return source[start:end]


#: Just enough of a page for app.js's `el` and the forms built with it.
FAKE_DOM = r"""
class FakeNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase(); this.children = []; this.attrs = {};
    this.listeners = {}; this.className = ''; this.hidden = false; this.value = '';
    this.style = { setProperty() {} }; this.textContent = ''; this.checked = false;
    this.dataset = {};
  }
  append(...kids) { for (const k of kids) this.children.push(k); }
  prepend(...kids) { this.children.unshift(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'value') this.value = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  querySelector() { return null; }
  focus() {}
  get classList() { const n = this; return { add() {}, remove() {}, toggle() {},
    contains: (c) => n.className.split(' ').includes(c) }; }
}
global.Node = FakeNode;
global.document = {
  createElement: (t) => new FakeNode(t),
  createTextNode: (t) => { const n = new FakeNode('#text'); n.textContent = String(t); return n; },
  body: new FakeNode('body'),
  querySelector: () => global.pageHost || null,
  querySelectorAll: () => [],
};
global.window = global;
global.location = { href: 'http://localhost/' };
global.requestAnimationFrame = () => 0;
const textOf = (n) => (n.tagName === '#TEXT' ? n.textContent : n.children.map(textOf).join(''));
const findAll = (n, test, out = []) => {
  if (test(n)) out.push(n);
  for (const c of n.children || []) if (c && c.children) findAll(c, test, out);
  return out;
};
const fire = (node, type, event = {}) => (node.listeners[type] || []).map(
  (fn) => fn({ preventDefault() {}, stopPropagation() {}, ...event }));
const tick = () => new Promise((r) => setTimeout(r, 0));
"""


def _node(source):
    out = subprocess.run(["node", "-e", source], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _page(*parts):
    """The fake page, common.js's helpers and app.js's `el`, then ``parts``."""
    return "\n".join([FAKE_DOM, _read("common.js"), _function("el", "app.js"), *parts])


# --------------------------------------------------------------- app.js

@needs_node
def test_a_password_mismatch_keeps_the_account_modal_open():
    # The modal's Save closes the modal whenever its callback returns, so
    # "showModalErrors(...); return;" showed the message and shut it at once.
    code = _page(_function("openAccountModal", "app.js"), r"""
      const state = { me: { username: 'ahmed' } };
      let save = null; let asked = false;
      const openModal = (title, fields, cb) => { save = cb; };
      const modalValues = () => ({ current_password: 'x', new_password: 'abcdefghijk', again: 'abcdefghijx' });
      const showModalErrors = () => {}; const closeModal = () => {}; const toast = () => {};
      const api = async () => { asked = true; return {}; };
      openAccountModal();
      save().then(() => console.log(JSON.stringify({ kept: false, asked })),
        (e) => console.log(JSON.stringify({ kept: true, asked, message: e.message })));
    """)
    assert _node(code) == {"kept": True, "asked": False,
                           "message": "Those two passwords are not the same."}


@needs_node
def test_a_report_table_takes_an_empty_cell():
    # A project with no status gave a null cell, and `cell.wide` threw.
    code = _page(_function("table", "app.js"), r"""
      const t = table(['Project', 'Status'], [{ cells: ['J-1', null] }]);
      console.log(JSON.stringify(findAll(t, (n) => n.tagName === 'TD').length));
    """)
    assert _node(code) == 2


@needs_node
def test_stopping_nightly_imports_says_when_the_server_refuses():
    code = _page(_function("stopNightly", "app.js"), r"""
      const said = [];
      global.confirm = () => true; global.alert = (m) => said.push(m);
      const renderNightly = () => said.push('redrawn');
      const api = async () => { const e = new Error('No'); e.errors = ['Could not stop it.']; throw e; };
      stopNightly().then(() => console.log(JSON.stringify(said)),
        () => console.log(JSON.stringify('unhandled')));
    """)
    assert _node(code) == ["Could not stop it.", "redrawn"]


# ----------------------------------------------------------- planner.js

PLANNER_STUBS = r"""
  const plan = { days: 5, moves: [], team: 'all', whatIfs: [] };
  let save = null; const tried = []; const posted = [];
  const openModal = (title, fields, cb) => { save = cb; };
  const closeModal = () => {}; const toast = () => {}; const showModalErrors = () => {};
  const tryMoves = async (moves) => { tried.push(moves); };
  const loadPlanner = async () => {};
"""


@needs_node
def test_try_new_work_reads_what_was_typed():
    # The modal's Save calls its callback with nothing; this one read
    # `values.project` from an argument that never came, so it always failed.
    code = _page(_function("tryNewWork", "planner.js"), PLANNER_STUBS, r"""
      let typed = { project: 'New berth', to: 'Osama', hours: '20' };
      const modalValues = () => typed;
      tryNewWork({ people: [{ name: 'Osama', capacity: 40, after: { hours: 10 } }] });
      (async () => {
        await save();
        typed = { project: '', to: 'Osama', hours: '' };
        let refused = null;
        try { await save(); } catch (e) { refused = e.message; }
        console.log(JSON.stringify({ tried, refused }));
      })().catch((e) => console.log(JSON.stringify(String(e))));
    """)
    assert _node(code) == {
        "tried": [[{"kind": "extra", "project": "New berth", "to": "Osama", "hours": 20}]],
        "refused": "Say what the work is and roughly how many hours."}


@needs_node
def test_a_refused_what_if_keeps_its_modal_open_and_a_good_one_is_kept():
    code = _page(_function("keepWhatIf", "planner.js"), PLANNER_STUBS, r"""
      const modalValues = () => ({ name: 'Berth tender' });
      let refuse = true;
      const api = async (path, opts) => {
        if (refuse) { const e = new Error('Too many'); e.errors = ['Twelve at most.']; throw e; }
        posted.push(opts.body.name); return {};
      };
      keepWhatIf();
      (async () => {
        let kept = 'resolved';
        try { await save(); } catch (e) { kept = e.errors; }
        refuse = false;
        await save();
        console.log(JSON.stringify({ kept, posted }));
      })();
    """)
    assert _node(code) == {"kept": ["Twelve at most."], "posted": ["Berth tender"]}


@needs_node
def test_todays_team_choice_finds_people_by_their_team_name():
    # /api/day names each person's team_name only: matching on team_id
    # showed nobody at all once a team was chosen.
    code = _page(_function("inChosenTeam", "planner.js"), r"""
      const plan = { team: 't1' };
      const data = { teams: [{ id: 't1', name: 'Ports & Berths' }, { id: 't2', name: 'Coastal' }] };
      const out = [
        inChosenTeam({ name: 'Ahmed', team_name: 'Ports & Berths' }, data),
        inChosenTeam({ name: 'Kirolos', team_name: 'Coastal' }, data),
        inChosenTeam({ name: 'Osama', team_id: 't1' }, data),
      ];
      plan.team = 'all';
      out.push(inChosenTeam({ name: 'Kirolos', team_name: 'Coastal' }, data));
      console.log(JSON.stringify(out));
    """)
    assert _node(code) == [True, False, True, True]
    day = _function("renderDay", "planner.js")
    assert "p.team_id === plan.team" not in day
    assert "p.team_id !== plan.team" not in _function("dayText", "planner.js")


@needs_node
def test_wanted_this_week_is_the_last_working_day_of_this_week():
    # It was today + 7 days: next week, so a request wanted this week was
    # never shown as later than wanted until the week after.
    code = _page(_function("isoDay", "planner.js"), _function("shiftDay", "planner.js"),
                 _function("endOfWorkWeek", "planner.js"), r"""
      console.log(JSON.stringify([
        endOfWorkWeek('2026-10-07', [0, 1, 2, 3, 4]),   // Wed, Mon-Fri: Fri
        endOfWorkWeek('2026-10-07', [6, 0, 1, 2, 3]),   // Wed, Sun-Thu: Thu
        endOfWorkWeek('2026-10-11', [6, 0, 1, 2, 3]),   // Sun, Sun-Thu: Thu
        endOfWorkWeek('2026-10-09', [6, 0, 1, 2, 3]),   // Fri off: next Thu
      ]));
    """)
    assert _node(code) == ["2026-10-09", "2026-10-08", "2026-10-15", "2026-10-15"]
    assert "shiftDay(data.today, 7) }, 'this week'" not in _function("quickAdd", "planner.js")


@needs_node
def test_a_double_tap_on_add_puts_one_request_in():
    code = _page(_function("quickAdd", "planner.js"), r"""
      const plan = {}; const state = {}; let calls = 0; let release;
      const api = (path) => { calls += 1; return new Promise((r) => { release = r; }); };
      const markSaved = () => {}; const toast = () => {};
      const closeModal = () => {}; const loadDay = async () => {}; const slotText = () => '';
      const shiftDay = (d) => d; const endOfWorkWeek = (d) => d; const isoDay = () => '2026-10-07';
      const box = quickAdd({ today: '2026-10-07', people: [], engineers: [], projects: [], holidays: {} });
      const title = box.children[0]; title.value = 'Check the RFI';
      const add = findAll(box, (n) => n.tagName === 'BUTTON' && textOf(n) === 'Add')[0];
      fire(add, 'click'); fire(add, 'click');
      (async () => { await tick(); console.log(JSON.stringify(calls)); release({ person: 'Osama' }); })();
    """)
    assert _node(code) == 1


@needs_node
def test_a_double_tap_on_add_puts_work_coming_in_once():
    code = _page(_function("workComing", "planner.js"), r"""
      const plan = {}; let calls = 0;
      const api = () => { calls += 1; return new Promise(() => {}); };
      const toast = () => {}; const showNeeds = () => {};
      const shortDate = (d) => d; const fmt = { hours: (v) => String(v) };
      const box = workComing({ coming: [], teams: [], today: '2026-10-07' });
      const inputs = findAll(box, (n) => n.tagName === 'INPUT');
      inputs[0].value = 'Safaga berth 3'; inputs[2].value = '200';
      const add = findAll(box, (n) => n.tagName === 'BUTTON' && textOf(n) === 'Add')[0];
      fire(add, 'click'); fire(add, 'click');
      (async () => { await tick(); console.log(JSON.stringify(calls)); })();
    """)
    assert _node(code) == 1


# ------------------------------------------------------------- board.js

@needs_node
def test_a_hand_over_target_on_the_board_answers_the_keyboard():
    # The person chips became role="button" tabindex="0" targets with only a
    # click handler: a keyboard could pick work up but never hand it over.
    code = _page(r"""
      const fmt = { pct0: (v) => `${Math.round((v || 0) * 100)}%`, hours: (v) => String(v) };
      const engineerColor = () => 'red'; const initials = (n) => n[0];
      const loadTone = () => 'ok'; const toast = () => {};
      const plan = { moves: [], team: 'all', data: { open_tasks: [], moves: [] } };
      const tried = [];
      const tryMoves = async (moves) => { tried.push(moves); };
      const suggestMoves = () => {}; const commitMoves = () => {};
      let shown = null;
      const person = (name, items) => ({ name, team_id: null, before: { load: 0.5 }, after: { load: 0.5 }, items });
      const data = {
        summary: {}, people: [
          person('Ahmed', [{ key: 'J-1', project: 'J-1', name: 'Berth', pace_after: 4, hours_after: 20, hours_before: 20 }]),
          person('Kirolos', []),
        ],
      };
      plan.data = data;
      var renderPlanner = () => { shown = window.board.render(data); };
    """, _read("board.js"), r"""
      renderPlanner();
      const token = findAll(shown, (n) => n.className.includes('bd-token'))[0];
      fire(token, 'keydown', { key: 'Enter' });
      const target = findAll(shown, (n) => n.attrs['data-drop-person'] === 'Kirolos'
        && n.className.includes('is-target'))[0];
      fire(target, 'keydown', { key: 'Enter' });
      (async () => { await tick(); console.log(JSON.stringify({
        role: target.attrs.role, tried: tried.map((m) => m.map((x) => [x.from, x.to])) })); })();
    """)
    assert _node(code) == {"role": "button", "tried": [[["Ahmed", "Kirolos"]]]}


# ----------------------------------------------------------- busycal.js

@needs_node
def test_a_double_tap_on_add_meeting_puts_it_in_once():
    # A weekly meeting tapped twice went in twice, every week of it.
    code = _page(_function("meetingForm", "busycal.js"), _const("MEETING_KIND", "busycal.js"),
                 _const("MEETING_REPEAT", "busycal.js"), r"""
      let calls = 0; let release;
      const add = () => { calls += 1; return new Promise((r) => { release = r; }); };
      const form = meetingForm({ day: '2026-10-07', add });
      const go = findAll(form, (n) => n.tagName === 'BUTTON' && textOf(n) === 'Add meeting')[0];
      fire(go, 'click'); fire(go, 'click');
      (async () => {
        await tick(); const first = calls; release(true); await tick(); await tick();
        fire(go, 'click'); await tick();
        console.log(JSON.stringify([first, calls]));
      })();
    """)
    # One for the double tap; the next tap, once that one is in, goes again.
    assert _node(code) == [1, 2]


# ------------------------------------------------------------- myday.js

@needs_node
def test_a_double_tap_on_im_off_puts_the_days_in_once():
    code = _page(_function("renderTimeOff", "myday.js"), r"""
      const myDay = { day: { today: '2026-10-07', off: [] } };
      const host = new FakeNode('section'); global.pageHost = host;
      const mdQuery = () => ''; const toast = () => {};
      const refreshDay = async () => {};
      let calls = 0;
      const api = () => { calls += 1; return new Promise(() => {}); };
      renderTimeOff();
      const add = findAll(host, (n) => n.tagName === 'BUTTON' && textOf(n) === 'Add')[0];
      fire(add, 'click'); fire(add, 'click');
      (async () => { await tick(); console.log(JSON.stringify(calls)); })();
    """)
    assert _node(code) == 1


@needs_node
def test_enter_and_send_together_send_a_note_once():
    code = _page(_function("noteForm", "myday.js"), r"""
      const myDay = {}; const refreshDay = async () => {};
      const renderMyDay = () => {};
      let calls = 0;
      const form = noteForm('What do you need?', true, () => { calls += 1; return new Promise(() => {}); });
      const input = form.children[0]; input.value = 'The pile loads';
      const send = findAll(form, (n) => n.tagName === 'BUTTON' && textOf(n) === 'Send')[0];
      fire(input, 'keydown', { key: 'Enter' }); fire(send, 'click');
      (async () => { await tick(); console.log(JSON.stringify(calls)); })();
    """)
    assert _node(code) == 1


# ----------------------------------------------------------- budgets.js

@needs_node
def test_a_budget_share_or_person_change_refreshes_the_projects_tab():
    # Both put the team's budget on its projects (apply_to_register) and the
    # person change refills the team's days; Overview and Projects kept the
    # old figures until the page was loaded again.
    code = _page(_function("registerChanged", "budgets.js"), _function("editShare", "budgets.js"),
                 _function("editPerson", "budgets.js"), r"""
      const bud = { data: { kinds: [] } }; let save = null; let refreshed = 0;
      const openModal = (title, fields, cb) => { save = cb; };
      const modalValues = () => ({ share_percent: '40', kind: 'loan', from: null, to: null });
      const api = async () => ({ jobs: [] }); const closeModal = () => {}; const toast = () => {};
      const renderBudgets = () => {}; const fmt = { pct0: (v) => String(v) };
      var refreshAll = async () => { refreshed += 1; };
      (async () => {
        editShare({ job_number: 'J-1', share_basis: 'booked', share: 0.5 }); await save();
        editPerson({ name: 'Osama', unit: 'MS', set: false }); await save();
        console.log(JSON.stringify(refreshed));
      })();
    """)
    assert _node(code) == 2
    assert "registerChanged()" in _function("bringInFiles", "budgets.js")


# ---------------------------------------------------------- showcase.js

@needs_node
def test_the_coming_weeks_start_on_the_units_first_working_day():
    # A Sunday-to-Thursday unit: the past weeks from Check-ins start on a
    # Sunday, the coming ones were cut at Monday, so the first coming Sunday
    # sat alone in a "coming week" that had already gone.
    code = _page(_inner("shortWeek", "showcase.js"), _inner("peopleModel", "showcase.js"), r"""
      const engineerColor = () => 'red'; const pct = (v) => String(v); const scape = {};
      const days = ['2026-10-11', '2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15',
        '2026-10-18', '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22']
        .map((date) => ({ date, booked: 6, over: 0 }));
      const model = peopleModel({ weeks: ['2026-09-27', '2026-10-04'], hours_per_day: 8,
        people: [{ name: 'Osama', weeks: [{ week: '2026-10-04', load: 0.9 }], days }] });
      console.log(JSON.stringify(model.cols));
    """)
    assert _node(code) == ["27 Sept", "4 Oct", "11 Oct", "18 Oct"]


# ----------------------------------------------------------- checkins.js

@needs_node
def test_everything_to_ask_shows_dates_day_first():
    # The person cards put each checkpoint through dayFirstText; the table of
    # every checkpoint under them showed the same text with ISO dates.
    code = _page(_function("checkpointTable", "checkins.js"), _const("LEVEL_TONE", "checkins.js"),
                 _const("LEVEL_LABEL", "checkins.js"), r"""
      const engineerColor = () => 'red'; const seenButton = () => null;
      const t = checkpointTable([{ name: 'Osama', checkpoints: [
        { level: 'now', text: 'Asked for help: the loads due 2026-10-12' }] }]);
      console.log(JSON.stringify(findAll(t, (n) => n.className === 'ci-ask').map(textOf)));
    """)
    assert _node(code) == ["Asked for help: the loads due 12/10/2026"]


# --------------------------------------------------------------- tabs.js

def test_the_task_timeline_never_says_null_for_a_task_with_no_project():
    source = _read("tabs.js")
    assert "${t.project_number} ${projectName" not in source
    assert "t.project_number || " in source
