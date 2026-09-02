# Workload

An application for the **Workload & Profit Plan** workbook. It gives the monthly
jobs a proper front end — pasting each engineer's timesheet, adding a project,
adding its deliverables, planning tasks — and its own reports, while the
workbook stays the model everything is calculated from.

The workbook is edited surgically. It is not exported, rebuilt or re-saved by a
spreadsheet library: only the cells that change are rewritten, so all 14 charts,
the drawings, the threaded comments, the conditional formatting, the data
validations and every formula come through untouched.

**It runs the same way on your own machine and on a host.** Same login, same
storage, same code — see [DEPLOY.md](DEPLOY.md) for PythonAnywhere.

```
pip install -r requirements.txt
python -m workload_app.admin add <username> --admin     # once: make an account
python -m workload_app
```

Your browser opens on <http://127.0.0.1:8765/> and asks you to sign in. Stop the
app with Ctrl+C.

## Accounts

Every visitor signs in, and an account sees only its own work. There is no
public sign-up: an administrator makes each account, from the **Accounts**
panel in the app or with `python -m workload_app.admin add`. Passwords are
stored as salted PBKDF2-HMAC-SHA256 (240,000 rounds), never as text; a session
is a random token whose digest alone is stored, in a cookie that is `HttpOnly`,
`SameSite=Lax`, and `Secure` as soon as the site is served over HTTPS. Changing
a password ends every other session.

Two accounts cannot see each other. Each has its own folder of workbooks and its
own rows in the database, and every request is filtered by the account it came
from — the tests in `tests/test_server.py::TestPrivacy` are the ones that hold
that down.

## Units

A unit is a name and the workbook behind it — Marine Structures and its file,
another discipline and its own. One account can hold up to twelve. **Switch
unit** in the header puts one down and picks up another; each keeps its place.

A unit starts in one of two ways:

- **Start blank** — from the template that ships with the app: the whole model,
  formulas, charts, project types, rules of credit, the scorecard and the
  glossary, with no projects, no deliverables, no hours and generic engineer
  names. Build `workload_app/data/template.xlsx` with
  `python tools/build_template.py <your workbook>`.
- **Upload** a Workload workbook you already have.

The app owns the file from then on: it lives in that account's folder and is
saved after every change, with a timestamped backup beside it. **⭳ on a unit
downloads the workbook as it stands**, so the data is never trapped — that is
the way to open it in Excel, and the way to take it somewhere else.

## The team

A unit has whoever it has. The **Team** tab adds, renames and removes engineers,
and everything follows: a paste-target sheet of their own, a place in the stack
that builds `Timesheet Raw`, a column for their share of every deliverable, a
row in the availability table, and their own line in every report and the
scorecard.

The workbook ships with room for exactly three, in fixed positions — Deliverables
K/L/M for the split, Work Calendar rows 20-22, Inputs rows 91-93 — and about
ninety formulas address those positions directly. So a fourth engineer onwards is
written into free space rather than inserted: nothing shifts, and not one of
those formulas has to be repaired. The trade-off is that the workbook's *own*
Mgmt Review, Engineer KPIs and Team Member sheets stay three columns wide and
know only the first three people. The app's versions of those reports handle any
number, which is where you read them now.

Nothing in the app assumes who the engineers are or how many there are. The
team, the paste-target sheets and the order they are stacked in all come from
the workbook, so a copy set up for a different discipline works without a code
change, and the split on a deliverable is keyed by name.

## What it does:

**Timesheets** — upload each engineer's monthly export (`.xlsx` or `.csv`).
Columns are matched to the TS sheet by heading name rather than by position, so
the export's own column order does not matter and a title block above the
headings is skipped. Before anything is written you see the row count, the date
range, the total hours, and warnings for rows with no date, no hours or no
Phase. An export belonging to someone else is refused outright rather than
landing on the wrong sheet. Then choose **Replace** (the monthly routine) or
**Append**.

**Only rows for projects in the register** is on by default, and it matters more
than it sounds: work charged to job numbers the workbook has no project for
would never roll up to anything anyway, and leaving it out is what keeps the
consolidated sheet inside the row limit described below. On the workbook as it
stands it takes 7,682 rows down to 5,271. Absence codes and proposal effort are
kept — utilisation and the Proposals sheet both need them.

**Projects** — the register, and behind each row the project's own page: its
details, its figures, and **its deliverables edited in place**. Every column
sorts — number, name, status, budget, progress, actual, earned, profit, CPI,
deliverables — numbers opening on their largest, blanks always sinking to the
bottom, and the row numbers following the order on screen. The `#` header puts
the register's own order back. The step dropdown
is filtered to the steps `Rules of Credit` defines for the chosen type and shows
the credit each earns; the split columns follow this unit's engineers.

A project and its deliverables are saved as one set, and **the save is blocked
until the phase weights total 100%** — a bar above the table shows how much of
the scope is still unaccounted for. Editing the set as a whole is what makes
that rule workable: a deliverable added on its own would leave the project short
every time. Anything the Overview flags gets a **Fix** button that opens the
project responsible.

**Reports** — five of the workbook's report sheets, rebuilt here so the file does
not have to be opened to show anyone anything: **Dashboard**, **Engineer KPIs**,
**Team Member**, **Scorecard** and **Management Review**. Pick a full year, a
single quarter or all time. **Print / Save as PDF** prints the view you are on —
just the report, with a header naming the unit, the view, the period and the
as-at date, and nothing breaking across a page.

Every figure is computed **once** into a single result set and shared between
the views, so the same actual MM cannot say two different things on two tabs.
The definitions are the workbook's own — planned MM is the budget spread across
the project's dates (unless a Phasing override says otherwise), a period earns
in proportion to the effort spent in it, capacity is pro-rated to the as-at
date, per-engineer figures are each project's value times that engineer's share,
and the scorecard weights six factors exactly as the sheet does. The test suite
holds all of it against the values Excel last calculated.

**Anything below target reads red, everywhere.** A negative profit, a CPI or
plan adherence under 1.00, utilisation short of the target, progress behind
where it should be — all of it is coloured on the same scale on every tab, so a
problem looks like a problem without reading the number first. The colour
survives **Print / Save as PDF**. The engineer KPI tables — on Engineer KPIs and
on Management Review — close with the **weighted score out of 100** and a star
against the best of it, which is the one row a manager reads first. Anything
counted over time, the delivery mix included, follows the period you picked
rather than quietly showing every year at once.

**Tasks** — task management, and the one tab that stands apart: nothing on it
is read by the workbook. No actual MM, no progress, no CPI. It is the plan
beside the record, not part of it.

A task carries a name, a definition, the hours it needs, the deliverable it
feeds, and who it belongs to. **More than one person can share a task**, and
its hours are then split between them, so two people on a six-hour job are
three hours each rather than six. **Actual hours are typed in here** — this tab
never reads the timesheet. Done tasks are hidden until you ask for them.

**Who is loaded, and who is not** sits at the top: each person's open work
against the hours a working day actually holds. The day is 09:00–17:30 by
default, so 8.5 hours; anything past that is overtime, which is exactly why it
is not counted as capacity — a person over 100% is one who has to stay late or
hand something over. Overdue work counts against the window, work further out
does not, and undated work is listed separately. The working day, the working
week (Sunday-to-Thursday is two clicks away) and the window are all editable.

Two buttons exist so nobody types the same thing fifty times:

- **Submission tasks** — a deliverable's date pulls a task onto every working
  day of the week before it, assigned to whoever holds a share of that
  deliverable. Run it again and it only fills the gaps.
- **Weekly meeting** — a standing meeting for a project or for the unit, every
  week for as long as it runs, in one click. Running it again extends the
  series rather than doubling it.

The list lives on a `Tasks` sheet the app creates in the workbook, so it
travels with the file — but no formula in the workbook so much as sees it.

**Reference** — the `Project Types` and `Rules of Credit` tables **and the
scorecard factors**, read-only until unlocked with a password. The factors are
what the team ranking is built from: what counts, how much each weighs, and
whether it scores against the best performer or against a target. The weights
have to total 100%, or one period's ranking could not be read against another's. These decide how every deliverable earns credit, so a
change here moves the progress and CPI of every project using that type. The
lock is a deterrent against a stray keystroke, not a security control: the same
cells are editable in Excel by anyone who can open the file.

**Overview** — the whole page is for one chosen year: the budget in hand, what
has been planned and booked against it, earned value, profit, utilisation and
CPI. Each engineer is shown in the workbook's own measures — man-months against
capacity, earned against actual, plan adherence — rather than a count of hours,
which on its own says very little. Every measure carries its definition from the
`Definitions` sheet, and the glossary sits at the foot of the page. The data
check follows the same year — rows, hours and job numbers charged but not in
the register are all counted for that year, with the whole-file totals beside
them, so the year's problems are not buried in a decade of history.

**Project of the year** sits beside them: the finished project that earned the
most for what it cost — the best CPI among the projects finalized and worked on
in the chosen year. A project has to carry at least a quarter of a man-month of
effort in the period to qualify, because two hours of touch-up on a completed
job would otherwise win every year on a ratio.

**Hero of the month and Hero of the year** sit at the top. The month's hero is
whoever scored highest on the team scorecard in the last *completed* month — in
September you see August, because ranking a month still in progress just rewards
whoever booked first. The year's hero tops the scorecard for the period, with a
tally of months won beside it, so a steady month-by-month winner is visible even
when someone else leads on total value delivered.

## The two row limits that lose an engineer's hours

`Timesheet Raw` builds itself by stacking the monthly sheets:

```
VSTACK('TS Ahmed'!A4:P6000, 'TS Osama'!A4:P6000, 'TS Kirolos'!A4:P6000)
```

There are two limits in that one line. Each sheet is read only as far as
row 6,000, and every formula that reads the result — around 138,000 of them
across `Phasing`, `Timesheet Daily`, `Deliverable Actuals`, `Proposals` and
`Work Calendar` — reads rows 4 to 8,000 of the consolidated sheet: 7,997 rows
for the whole team together.

Once either limit is passed, the surplus rows still appear on the sheet but
reach no calculation at all: no project actuals, no dashboard, no CPI. Nothing
in the workbook says so. Because the sheets stack in order, it is the rows at
the bottom of the stack that stop counting first — you update the last
engineer, and nothing moves.

**The app widens the per-sheet limit to 25,000 the moment it opens a
workbook.** That is a one-line change to the `VSTACK` with no recalculation
cost, so there was never a reason to leave it at 6,000 or to make it a button
somebody had to find. The Timesheets tab shows how much room is left against
both limits and warns before either runs out.

Raising the consolidated limit is the heavier of the two, and stays a decision:
it rewrites every one of those 138,000 references and extends the per-row
helper formulas to match, and two of those helper columns cost roughly the
square of the limit to recalculate. So the app suggests a few years of headroom
rather than the maximum — and importing only registered work is usually the
cheaper fix.

## Rules it enforces

These are the workbook's own rules, checked before a cell is written rather than
found later in a red cell:

- project numbers are unique, budget MM is positive, the end date is not before
  the start, and the status is one the register allows;
- a deliverable belongs to a project that exists — or to the one being created
  in the same save;
- its type code is in `Project Types`, and its step number is a step
  `Rules of Credit` defines *for that type*;
- the engineer split totals 100% on each deliverable;
- **phase weights total 100% per project — the save is refused otherwise**;
- an engineer's sheet only ever holds that engineer's rows.

## Safety

- **Every write is preceded by a timestamped backup** in `backups/` beside the
  workbook. Nothing is overwritten in place without one.
- Formula cells are protected: a write aimed at one raises rather than silently
  deleting part of the model.
- The workbook is saved with a full-recalculation flag, so Excel recomputes
  everything the next time it is opened.
- The app owns its copy of each workbook, so nothing you have open in Excel can
  overwrite it. To read one in Excel, download it (⭳ on the unit); to bring
  changes back, upload it as a unit again.
- On a host with more than one worker process, a writer takes an exclusive lock
  on the file and a reader that finds the file changed underneath re-reads it
  before answering.

Run with `--no-autosave` to hold changes in memory and write them only when you
press **Save now**.

## Growing the Deliverable Actuals block

`Deliverable Actuals` ships covering rows 5–68 — exactly the 64 deliverables the
workbook already has, so there is no room for a 65th. When you add one, the app
extends the block: it clones the last data row, translates its formulas down
(resolving Excel's shared and array formulas into explicit ones), and grows
every range anchored to the old last row, including the conditional-formatting
ranges and the x14 extension list. The calculation chain is dropped so Excel
rebuilds it. This happens automatically; there is nothing to do by hand.

## Layout

| Path | What it is |
| --- | --- |
| `workload_app/xlsx_io.py` | Reads and writes cells directly in the spreadsheet XML |
| `workload_app/accounts.py` | Accounts, passwords, sessions and each account's units |
| `workload_app/storage.py` | Where an account's workbooks live, and the template |
| `workload_app/app.py` | The application: routes, access, and who is asking |
| `workload_app/service.py` | One open workbook, and every change that can be made |
| `workload_app/library.py` | Checking that a file really is a Workload workbook |
| `workload_app/capacity.py` | The row caps on the consolidated timesheet |
| `workload_app/config.py` | Where every input lives — sheets, rows, columns |
| `workload_app/workbook.py` | The registers as a domain model, and the validation |
| `workload_app/actuals_block.py` | Growing the `Deliverable Actuals` block |
| `workload_app/timesheets.py` | Reading an export and lining it up with the TS sheet |
| `workload_app/metrics.py` | Workload and efficiency, recomputed from raw inputs |
| `workload_app/reports.py` | The five report views and the heroes, once per period |
| `workload_app/tasks.py` | The task list, the working day, and who is overloaded |
| `workload_app/static/charts.js` | Inline-SVG charts — donut, bars, columns |
| `workload_app/server.py` | The local HTTP transport |
| `workload_app/wsgi.py` | The transport a host uses (PythonAnywhere) |
| `workload_app/admin.py` | Making accounts from a console |
| `tools/build_template.py` | Building the blank workbook that ships with the app |
| `workload_app/static/` | The single-page front end (no build step) |

If the workbook is restructured, `config.py` is the file to edit — the code
reads its sheet names, row ranges and column letters from there.

### Why the figures are recomputed rather than read

The workbook caches the result of every formula, and those caches go stale the
moment the app writes a change — they only refresh when Excel next opens the
file. Reading them would show you yesterday's answer. So `metrics.py`
recomputes from the timesheet rows and the registers, following the workbook's
own definitions: actual MM is timesheet hours over hours-per-MM, progress is
phase weight times rules-of-credit credit, earned MM is budget times progress,
CPI is earned over actual. The test suite checks these against the values Excel
last calculated, so the two stay in step.

## Command line

```
python -m workload_app [-d DATA_DIR] [--host HOST] [-p PORT]
                       [--no-autosave] [--no-browser] [-q]

python -m workload_app.admin add <username> [--admin] [--name NAME]
python -m workload_app.admin list
python -m workload_app.admin password <username>
python -m workload_app.admin remove <username>
python -m workload_app.admin import <username> <workbook.xlsx> [--name NAME]
```

Accounts and workbooks live in `$WORKLOAD_DATA_DIR`, or `./instance` if that is
not set. The local server binds to `127.0.0.1`, so it is reachable only from
your own machine; to put it on the open internet use the WSGI entry point and
HTTPS, which is what [DEPLOY.md](DEPLOY.md) describes.

## Tests

The tests need a workbook to run against, and none is committed — the
repository holds no project data. Point them at yours:

```
pip install -r requirements-dev.txt
export WORKLOAD_TEST_WORKBOOK=/path/to/Workload.xlsx   # or drop a copy at data/
python -m pytest
```

They work on a throw-away copy, never your file. Without one they skip
themselves and say so.

The suite covers the XML surgery (including that every sheet reassembles byte
for byte and that only the intended parts of the file change), the row caps and
what happens when they are exceeded, the validation rules, the import —
including the stub `<dimension>` that the real export writes — and the
arithmetic, cross-checked against the values the workbook itself last
calculated.

It also covers what makes the site safe to put on the internet: that a password
never reaches the database as text, that a session token is stored only as a
digest, that every endpoint refuses a request with no session, that one account
cannot open, download, rename or delete another's unit, and that the same
application answers correctly through the WSGI entry point a host uses.

## The monthly routine

1. Sign in and open the unit.
2. **Timesheets** — upload each engineer's export, check the summary, Replace.
   Leave "only rows for projects in the register" ticked.
3. **Timesheets** — check the room left in the workbook. If it warns, raise the
   limit before going further, or the newest rows will not count.
4. **Overview** — check the data check reads "All rows matched to an engineer",
   and look at what the unknown job numbers are.
5. **Projects** — open each active project and move its deliverables' steps on.
   **Team** — only when someone joins or leaves.
6. **Tasks** — check who is overloaded for the weeks ahead, and let a new
   deliverable date fill in its week of preparation.
7. **Reports** — read the Dashboard and Management Review, and print whichever
   view you need for the meeting.
8. Download the workbook (⭳) when you want `Delivery Sequence` or `Profit Plan`,
   which are not yet in the app.

Steps 4 and 5 of the workbook's own routine — retyping actual MM on `Phasing` —
are already automatic; the workbook reads them from the timesheet.


## About the charts

The series colours are a fixed, validated palette, checked against this app's
own light and dark surfaces for colour-blind separation and contrast rather than
picked by eye. A colour belongs to a thing, not to its position: "Finalized"
is the same colour on every chart and in every period, even when a status is
missing from one of them. Three of the light-mode steps sit below 3:1 contrast,
which is why every chart carries direct labels and the numbers appear in a table
underneath it — the colour never has to carry the meaning on its own.

Donuts are used where the question really is part-to-whole and there are few
enough segments to read at a glance. Comparing planned against actual against
earned is a bar chart, because that is a comparison of magnitudes, and a pie
would make it harder to read rather than easier.

## Where the data is

```
$WORKLOAD_DATA_DIR/            (or ./instance)
├── accounts.db                accounts, sessions, and each account's units
└── users/
    └── 7/                     one folder per account
        ├── 3f2b….xlsx         one workbook per unit
        └── backups/           a timestamped copy before every write
```

That folder is the whole application state. Back it up and you have backed up
everything; move it to another machine and everyone signs in to find their work
where they left it. The code carries only the blank template.

## Still to come

`Delivery Sequence` and `Profit Plan` — the ranking of what to deliver next and
the year-end projection — are still read in the workbook.

The task tab is deliberately not wired to anything yet: its hours are typed,
not read from the timesheet, and nothing it holds reaches a project's figures.
Connecting the two — actual hours per task coming from the timesheet, a
deliverable's progress moving when its tasks close — is the obvious next step,
and is a decision to take rather than a gap to fill in quietly.
