# Workload Input

An input application for the **Workload & Profit Plan** workbook. It gives the
three monthly jobs a proper front end — pasting each engineer's timesheet,
adding a project, and adding a project's deliverables — while the workbook
itself stays the calculation engine and the place you read results.

The workbook is edited in place. It is not exported, rebuilt or re-saved by a
spreadsheet library: only the cells you change are rewritten, so all 14 charts,
the drawings, the threaded comments, the conditional formatting, the data
validations and every formula come through untouched.

```
pip install -r requirements.txt
python -m workload_app
```

Your browser opens on <http://127.0.0.1:8765/> and asks which **unit** to work
on. Stop the app with Ctrl+C.

The app carries no workbook of its own: it edits the file you point it at, in
place. Close that file in Excel first — Excel keeps its own copy in memory and
would overwrite anything written while it is open.

## Units

A unit is a name and the workbook that belongs to it — Marine Structures and its
file, another discipline and its own. Add one with **Choose file…** (your
operating system's own dialog), give it a name, and it is remembered in
`~/.workload_app.json`. **Switch unit** in the header puts one down and picks up
another; each keeps its own place.

Nothing in the app assumes who the engineers are. The team, the paste-target
sheets and the order they are stacked in all come from the workbook — from
`Work Calendar` rows 20 onwards and the `Timesheet Raw` formula — so a copy set
up for a different discipline, with different people and differently named
sheets, works without a code change. The engineer split on a deliverable is
keyed by name and follows whoever that unit's team is.

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
details, its figures, and **its deliverables edited in place**. The step dropdown
is filtered to the steps `Rules of Credit` defines for the chosen type and shows
the credit each earns; the split columns follow this unit's engineers.

A project and its deliverables are saved as one set, and **the save is blocked
until the phase weights total 100%** — a bar above the table shows how much of
the scope is still unaccounted for. Editing the set as a whole is what makes
that rule workable: a deliverable added on its own would leave the project short
every time. Anything the Overview flags gets a **Fix** button that opens the
project responsible.

**Reference** — the `Project Types` and `Rules of Credit` tables, read-only until
unlocked with a password. These decide how every deliverable earns credit, so a
change here moves the progress and CPI of every project using that type. The
lock is a deterrent against a stray keystroke, not a security control: the same
cells are editable in Excel by anyone who can open the file.

**Overview** — the portfolio position (budget, actual MM, earned MM, profit,
CPI), each engineer's monthly hours against their capacity, the `Work Calendar`
data check, and any register problems.

## The row limit that loses an engineer's hours

`Timesheet Raw` builds itself from the three TS sheets with

```
VSTACK('TS Ahmed'!A4:P6000, 'TS Osama'!A4:P6000, 'TS Kirolos'!A4:P6000)
```

and every formula that reads the result — around 138,000 of them across
`Phasing`, `Timesheet Daily`, `Deliverable Actuals`, `Proposals` and
`Work Calendar` — reads rows 4 to 8000 only. That is 7,997 rows for all three
engineers together.

Once the sheets hold more than that, the surplus rows still appear on
`Timesheet Raw` but reach no calculation at all: no project actuals, no
dashboard, no CPI. Nothing in the workbook says so. And because the stack runs
Ahmed, then Osama, then Kirolos, it is **the last engineer's rows that vanish
first** — you update Kirolos, and nothing moves.

The Timesheets tab shows how much room is left, warns before it runs out, and
will raise the limit for you. Raising it rewrites every one of those references
and extends the per-row helper formulas to match. It is worth knowing that two
of those helper columns cost roughly the square of the limit to recalculate, so
the app suggests a few years of headroom rather than the maximum — and importing
only registered work is usually the cheaper fix.

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
- **Close the workbook in Excel before running the app.** Excel holds its own
  copy in memory and will overwrite whatever the app wrote when you next save.

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
| `workload_app/library.py` | Units: finding, checking and remembering workbooks |
| `workload_app/capacity.py` | The row caps on the consolidated timesheet |
| `workload_app/config.py` | Where every input lives — sheets, rows, columns |
| `workload_app/workbook.py` | The registers as a domain model, and the validation |
| `workload_app/actuals_block.py` | Growing the `Deliverable Actuals` block |
| `workload_app/timesheets.py` | Reading an export and lining it up with the TS sheet |
| `workload_app/metrics.py` | Workload and efficiency, recomputed from raw inputs |
| `workload_app/server.py` | The local HTTP server and JSON API |
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
python -m workload_app [-w WORKBOOK] [--host HOST] [-p PORT]
                       [--no-autosave] [--no-browser] [-q]
```

`--workbook` is optional; without it the app asks in the browser and remembers
what you chose in `~/.workload_app.json`.

The app binds to `127.0.0.1` — it is reachable only from your own machine. It
has no authentication, so do not put it on a shared interface.

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
what happens when they are exceeded, choosing a workbook, the validation rules,
the import — including the stub `<dimension>` that the real export writes — and
the arithmetic, cross-checked against the values the workbook itself last
calculated.

## The monthly routine

1. Close the workbook in Excel.
2. Start the app and choose the workbook.
3. **Timesheets** — upload each engineer's export, check the summary, Replace.
   Leave "only rows for projects in the register" ticked.
4. **Timesheets** — check the room left in the workbook. If it warns, raise the
   limit before going further, or the newest rows will not count.
5. **Overview** — check the data check reads "All rows matched to an engineer",
   and look at what the unknown job numbers are.
6. **Projects** — open each active project and move its deliverables' steps on.
7. Stop the app and open the workbook to read `Delivery Sequence`, `Profit Plan`
   and `Mgmt Review`.

Steps 4 and 5 of the workbook's own routine — retyping actual MM on `Phasing` —
are already automatic; the workbook reads them from the timesheet.


## Still to come

The report views — Dashboard, Engineer KPIs, Team Member, Scorecard and
Management Review — with pie charts and a Print to PDF button, so the workbook
does not have to be opened to show anyone anything.
