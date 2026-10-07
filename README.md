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
public sign-up: an administrator makes each account, from the **Admin** tab in
the app or with `python -m workload_app.admin add`.

There are two kinds:

**A manager** runs a team. They create units from their team's timesheets, import
each month's, confirm the projects and deliverables those turn up, plan tasks,
and read every report. This is the account the site starts with.

**A team member** — Osama, Kirolos — signs in to **one page: their own**. Their
man-months, their earned value, their CPI and utilisation, the projects they
hold a share of, their own timesheet rows, their own tasks. Nobody else's name,
score or hours is in what the server sends them, and there is nothing on the
page to press: a member account has no write route anywhere in the app, and no
read route into the rest of the unit either. It is not a hidden button, it is a
missing route, and `tests/test_roles.py` is a list of the things a member
account is refused.

## How far along a task is

A task is measured one of two ways, and which one says something real about
the work.

**Pro rata** — the fraction of the effort that is done. Right for work with no
gate in it: a study, a calculation, a model to build.

**Workflow** — the stage the deliverable has reached, which is what a client
and a project manager both recognise:

| Stage | |
| --- | ---: |
| Design started | 10% |
| IDC sent | 40% |
| Internal comments addressed | 60% |
| Submitted | 80% |

The last twenty points are not withheld to be pessimistic. They are the
review: until the comments come back, a submitted deliverable is not finished
work, it is work waiting to find out. What comes back decides where it lands:

| Code | | |
| --- | --- | --- |
| **A** | approved | 100% |
| **B** | approved with comments | 90%, then +1% a resubmission, to 99% |
| **C** | revise and resubmit | 80%, then +1% a resubmission, to 89% |

The 1% is deliberately small. Nothing new is being designed on a
resubmission — but a deliverable on its fourth is not in the same place as one
that has just come back, and a number that never moves hides that. The caps
are asymptotes, not milestones: a resubmission can never be worth as much as
an approval.

Marking a task **Done** beats all of it. Whoever pressed the button knows
something the stage does not.

### Rework in the KPIs

Hours say how much was done. They never say how much of it had to be done
again, and a deliverable that came back Code C three times cost the same hours
as one approved first time. So the engineer KPIs carry **submissions made**,
**resubmissions to finalise**, **resubmissions per submission** and **right
first time**. A shared submission counts for everyone on it — they submitted
it together and the rework is a cost they carry together — and somebody who
has submitted nothing scores `—` rather than perfect, because the absence of
rework is not the same as the absence of submitting.

## The Planner

The everyday tab, and on a phone the second button on the bar. It is filled
in by the app: the only thing anybody types is a request that came in.

**Today** is everybody's day, hour by hour, laid out from what is already
known: the requests that came in at the time they were given, the tasks dated
that day (submission run-ups, meetings), and then each person's usual project
work at the pace their newest two weeks of timesheets set. Whatever does not
fit before the end of the working day shows as *over*. **Week** is the same,
a column a day. **Share** sends the plan as plain text (or copies it), and
**Print** prints it.

**A request** is one line: what it is, roughly how long, when it is wanted,
and a project if there is one. It goes to whoever doing that kind of work has
the most room over the days until it is due, unless you pick somebody, and
gets the first free time in their day from now on, after the requests they
already have. It becomes a task of kind *Request*, so it is in the load, the
task list and the staffing forecast like any other work, and it adds to the
day rather than standing in for part of it.

**Away** keeps people off the plan on days they are not in. Leave booked on a
timesheet (a leave or holiday code, a half day or more) is read by itself,
ahead or past; anything else is one line — who, from, to — or *Everybody* for
a public holiday. Somebody away has an empty day, gets no requests, and is
left out of the coming days and the staffing forecast for those days; their
pace is read over the days they were in.

**Public holidays** are built in for Egypt, Saudi Arabia, the UAE, Qatar,
Kuwait, Jordan, Lebanon, Oman, Bahrain and the UK: fixed days, Easter worked
out for the year, and the expected dates of the Islamic holidays to 2030. The
Planner asks once which country the unit keeps (guessing from a city in its
name), and can take that country's working week with it; a team somewhere
else picks its own under *Change*. A holiday announced for another day is
taken off with *Not a holiday*, and the right day added for everybody.

**Next days** is each person's next few working days against a full load.
**Hand over** part of somebody's work — a share of their time on a project, or
a task — and every figure shows the effect before anything changes.
**Suggest handovers** does it for you: like for like only (an engineer's work
to an engineer, a draftsman's to a draftsman), to somebody who knows the
project first, then somebody in the same team, never filling anyone past 90%.
**Commit** makes it real: a task is reassigned, a share of a project is kept
for those days and then lapses by itself.

**Submissions** is the submissions plan, drafted by the app: a date for every
deliverable not yet submitted. On a confirmed project it is the effort left to
the *Submitted* step (80% of the credit) at the pace that phase is being
worked. On one the timesheets set up and nobody has confirmed, progress is a
placeholder, so it is the phase's first booking plus how long this unit's
phases usually take. Tick, adjust, **Confirm**: the date goes on the
deliverable and its run-up goes onto the task list, so it is in people's days.

**Work coming** (under More people) is one line for a project just
assigned, before anybody books to it: a name or job number, the team, rough
hours, start and end. The hours are spread over its working days, less
whatever is booked to the job number, and counted in the forecast until the
project is confirmed on Projects or the hours are used up. A team short for
a single week, because somebody is away, is told to hand work over in Next
days rather than to ask for people.

**More people** says, team by team and for engineers and draftsmen apart,
when to ask for more people, how many, from when and for how long — and says
outright when a team needs nobody. Each team's forecast work (confirmed
projects' effort to complete spread to their end dates; unconfirmed ones at
their recent pace; requests on top) is set against the people it has, week by
week for twelve weeks. Short by half a person or more for a run of weeks is an
ask, timed two weeks ahead so they arrive in time; a whole person spare for
three weeks or more is room. The Overview carries the same alerts under
*Staffing ahead*.

## Teams and draftsmen

One manager can run one team or several. When a unit's timesheets name more
than one `CurrentUnitDesc`, each becomes a team and its people go into it, once
— a move made on Resourcing afterwards is never undone by the next import.
When every row names the same one, the unit is the team. Teams are the lanes
of the formation on the Overview and the groups everywhere in the Planner.

Draftsmen are a grade of their own (*Draftsman*, read from a `Grade` that says
draft or CAD), and drafting is counted apart from engineering wherever
capacity is: a team short of draftsmen is not helped by a spare engineer.

## Drawings

The one number no timesheet carries. The simplest way in is the team's own
**drawing list** (Projects → *Drawing list*): one row a drawing, with its job
number, deliverable, number or title, status, issue date and the client's
code. Any list with headings like those is read; *Download the template* gives
one with a starter row per live deliverable. From it:

* each deliverable's **drawing count** is its rows (superseded ones aside);
* **done** is the drawings that have gone to the client (an issue date, or a
  status of IFA, IFC, IFT or issued) — a real count, so **hours a drawing** is
  measured from it even on a project nobody has confirmed yet;
* the **codes** that came back (A, B, C, or 1 to 4) move the register on:
  when every drawing has gone, the deliverable is offered as *sent* on the
  date of the last, at the Rules of Credit step for issue to the client; when
  they come back, comments received; when every one is code A, accepted.
  One *Apply* (in the upload, or above the submissions plan) writes them, and
  **Waiting for comments** lists what is with the client, oldest first.

A count can still be typed per deliverable in the project's deliverable table
(the **Drawings** column), and where there is no list, done is the count times
how far along the deliverable is. A person's drawings are their share of each
deliverable; the Projects register shows done of total, the Overview and the
Planner show the unit's, each team's and each person's drawings, and drawings
in somebody's hands move with the work when it is handed over. Counts and the
list's figures live in the unit's database, not the workbook.

## Resourcing

A head of department has teams under him, and the workbook has room for twelve
engineers in one flat list. So the establishment lives in the unit's own
database instead: a person has a **grade** — Senior, Engineer, Junior, BIM
modeller — and a team; a team has a lead; and moving somebody is one row
changing. Nobody is invisible for want of being set up: anyone the timesheets
know about is on the roster whether or not they have been given a team.

The **Resourcing** tab puts that beside the hours. Timesheets say where the
work went, the establishment says where the people are, and the difference is
the answer:

- **Which team is over its capacity, and since which month** — not "at some
  point": the run of over-capacity months that is still going, so a spike last
  spring does not masquerade as today's problem.
- **Who to move, and from where** — but only from a team that can lose a whole
  person and stay inside its own capacity. A move that overloads the lender has
  solved nothing, and the tab says so instead, naming the team it considered
  and the number it would have left them at.
- **Who to move** is the least loaded, never the lead, and on a tie the least
  senior — seniority holds a team's work together and costs the lender more
  than the hours say. It is a suggestion with a button beside it.
- **Who is carrying more than the people beside them** — only when they are
  meaningfully worse off than their own team, because when a whole team is
  over, saying it once is the finding and saying it per member buries the
  person who is genuinely drowning.
- **Which teams carry which project**, since a project already split across
  teams is where a move costs least.

Everything is measured against booked hours over the last three months. One
month is a holiday or a deadline; three is a pattern. Booked hours are history,
not a forecast, and the tab says so where the findings are.

### The map

The **Map** subtab is the same unit drawn rather than tabulated.

Every **circle is a project**, and its area is the effort still to spend to
finish it — the forecast cost to complete, which on an overrunning project is
more than the budget ever was. So the big circles are the work ahead and the
finished ones shrink away, which is the right way round for a picture whose
job is to say where to put people.

Its **colour** is resourcing, not efficiency: a project taking a fifth of the
team's recent hours while holding a twentieth of the work left is **crowded**;
the other way round is **starved**. A project with budget left and nobody
charging to it is starved too — the one nobody has noticed, which is the whole
reason to draw this.

Every **dot is a person**, coloured by their team, sitting at the centre of
gravity of the projects they charge to. Projects that share people pull
towards each other, so their circles overlap and anyone on both ends up in the
overlap, where set theory says they belong. Somebody on more than one project
is ringed, because that is the thing worth spotting.

Membership is who **charged time**, not who was assigned: the timesheet is
evidence, an assignment is an intention.

Drag any circle or person and the layout rearranges around it live. Clicking
one opens its figures underneath. The layout is deterministic — the same
portfolio comes out looking the same way twice, so it can be recognised
between visits. Everything you change updates the picture at once; a change
somebody *else* makes needs a refresh.

There is no charting library behind it. The force layout is about forty lines
of Verlet integration in `static/map.js`, for the same reason as the rest of
the front end: this app loads nothing from a CDN.

### The Admin tab

An administrator gets an eighth tab that nobody else does: every account, what
kind it is, how many units it has, when it was last seen — and its password.

**Passwords are readable there, deliberately.** *Show passwords* fetches them;
the account list itself never carries them, so they cross the wire only when
somebody presses the button, and every route behind the tab refuses an account
that is not an administrator. Sign-in still goes through PBKDF2 as it always
did — the readable copy is never consulted to let anyone in.

What makes it readable is a second, sealed copy of the password, written
whenever one is set. It is sealed under `secret.key`, a 32-byte file created
mode 0600 beside `accounts.db` and never stored inside it, so a stray copy of
the database — a backup that went astray, a downloaded data folder — is not a
list of everyone's passwords. Whoever holds both files can read them, which is
the point of the tab.

Two things follow, and the app says both where they matter:

- Tell your team the administrator can see the password on their account, so
  nobody reuses a personal one. The *Change password* dialog says so too.
- Accounts made before this existed show **not stored** — nothing can recover a
  password from a PBKDF2 hash. Reset one and it shows from then on.

A manager gives someone that access from the **Team** tab: *Give access* beside
an engineer creates their sign-in (with a password shown once) and points it at
that person. Renaming the engineer keeps the access pointed at them; removing
the engineer takes the access away with them.

Passwords are stored as salted PBKDF2-HMAC-SHA256 (240,000 rounds), never as
text; a session is a random token whose digest alone is stored, in a cookie that
is `HttpOnly`, `SameSite=Lax`, and `Secure` as soon as the site is served over
HTTPS. Changing a password ends every other session.

Two accounts cannot see each other. Each manager has their own folder of
workbooks and their own rows in the database, and every request is filtered by
the account it came from — the tests in `tests/test_server.py::TestPrivacy` are
the ones that hold that down.

## Units

A unit is a name and the workbook behind it — Marine Structures and its file,
another discipline and its own. One account can hold up to twelve. **Switch
unit** in the header puts one down and picks up another; each keeps its place.

A unit starts from **timesheets, and nothing else**. Choose everyone's monthly
export at once on the start page — a file per person, or one file holding the
whole team — and the app reads the rest out of them:

| From the timesheets | How |
| --- | --- |
| The team | everyone who booked, by `FullName`; first name as the short name |
| Grades | each person's latest `Grade` (Lead/P3 Senior, P1/P2 Engineer, Professional Junior) |
| The project register | every `1-Projects` job number |
| Project dates | the first and last day anybody booked to it |
| Project status | the latest `JobStatus`; **Finalized** once nobody has booked to it for six months |
| Deliverables | one per phase booked, named by its `DeliverableDescription` |
| Phase weights | each phase's share of the job's hours |
| The engineer split | each person's share of the phase's hours |
| Deliverable type | read from the phase's name — Concept, Tender, Review, Site… |
| Actual start / finish | the first and last booking to the phase |
| Proposal effort | a *Proposals* and a *Chargeable Proposals* project for each of the last three years |
| The unit's name | `CurrentUnitDesc`, unless you type one |

Three things are in no timesheet, so they start as estimates and the project is
marked **to confirm** on Projects until somebody opens it and saves it:

- **the project's name** — the export has no job-name column, so it is named by
  its number;
- **the budget** — the export's Budget column is empty, so it starts as the
  effort already spent;
- **how far along it is** — a phase somebody has booked to is at its first step
  (*started*), a finished project at its last. Until the real step is set, a
  live project's CPI and profit say nothing, which is why they read red.

The model itself — project types, rules of credit, the scorecard, the glossary —
comes from the template that ships with the app
(`python tools/build_template.py <your workbook>` rebuilds it).

Nothing derived ever overwrites the register: a job number that is already a
project is left exactly as it is, so a corrected name or budget stays corrected,
and next month's import adds only what is new.

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

A workbook takes up to twelve people. An import with more than that still
imports everybody: the rest are on the roster and in Resourcing, and their hours
count toward every project they booked to, but they have no KPI line and no
share of a deliverable. Nobody past the twelve goes unmentioned: the import
names them before anything is written, marks them **no place yet**, and the
data check on Timesheets keeps naming them until the limit is raised.

Nothing in the app assumes who the engineers are or how many there are. The
team, the paste-target sheets and the order they are stacked in all come from
the workbook, so a copy set up for a different discipline works without a code
change, and the split on a deliverable is keyed by name.

## What it does:

**Timesheets** — choose this month's exports, any number at once. There is no
engineer to pick: every row goes to whoever booked it, matched by the pattern on
Work Calendar. Before anything is written you see each person, their rows and
hours, who is new, and which projects will be set up. Then choose **Replace**
(the monthly routine — each person in the files gets exactly the rows the files
hold for them) or **Append**. Somebody new joins the team; a job number with no
project becomes one, for you to confirm. Columns are matched by heading name, so
the export's own column order does not matter and a title block above the
headings is skipped.

The register holds 80 projects and 200 deliverables. If the timesheets imply
more, the most recently worked come first and the oldest are listed as left
out; their hours still count for the people who booked them.

**Every night, on its own** — the exports come out of BISpark, which only a
PC on the company network can reach, so they are fetched there, with nothing
installed: PowerShell and Task Scheduler come with Windows. The manager pastes
the export request once (the browser's *Copy as PowerShell* of the Export
click) and names the team's shared folder; the request is kept with the unit,
never in this repository. *Kit for the team's PCs* is a zip with no key: at
12:00 am each PC sends BISpark that request, signed in with its own Windows
login, and copies the spreadsheet to the shared folder. *Kit for my PC* also
holds the unit's import key: at 1:00 am it does the same and then posts every
export in the folder to `/api/nightly/timesheets`. The import is the tab's own
replace, with one guard: an export holding over 10% fewer rows for someone than
are stored is refused. The tab shows when the last import ran, whether it
worked, and whose export was not refreshed. `pause.bat`, `resume.bat` and
`remove.bat` in each kit stop it; *Stop nightly imports* cancels the key. See
`workload_app/nightly.py` and `workload_app/data/nightly/`.

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

## The row limits, and why they can no longer lose an hour

`Timesheet Raw` builds itself by stacking the monthly sheets:

```
VSTACK('TS Ahmed'!A4:P6000, 'TS Osama'!A4:P6000, 'TS Kirolos'!A4:P6000)
```

There are two limits in that one line. Each sheet is read only as far as
row 6,000, and every formula that reads the result — around 138,000 of them
across `Phasing`, `Timesheet Daily`, `Deliverable Actuals`, `Proposals` and
`Work Calendar` — reads rows 4 to 8,000 of the consolidated sheet: **7,997
entries** for the whole team together, which is what the workbook ships with.

Past either limit a row still appears on the sheet but reaches no calculation
at all: no project actuals, no dashboard, no CPI. Nothing in the workbook says
so. It is the one failure in this app nobody would notice, which is why it is
handled three ways:

1. **The per-sheet limit goes to 25,000 the moment the app opens a workbook.**
   It is a one-line change to the `VSTACK` with no recalculation cost.
2. **An import that would not fit raises the limit before writing anything.**
   The app works out what the timesheet will hold once the import lands; if
   that is more than the workbook reads, it widens both limits to fit — with
   years of room to spare — and the import result says so. Rows are never
   written past what is read.
3. **The Timesheets tab shows how much room is left** and offers the same
   raise as a button, for doing it at a quiet moment rather than mid-import.

Raising the consolidated limit is the heavy one: it rewrites every one of those
138,000 references and extends the per-row helper formulas to match, which
takes about a minute, and Excel then takes a little longer to recalculate the
file. That is why it is not done on the way in, and why the app will only go so
far on its own — past 60,000 entries an import is **refused, before a single
row is written**, with a message saying to import only registered work or
archive the earliest years. Refusing loudly is the one thing that is always
better than dropping rows quietly.

The limit follows the timesheet from there: 25,000 entries until the timesheet
itself is bigger than that, and then the rows in hand plus room for a few more
years, rounded up.

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
  overwrite it. To read one in Excel, download it (⭳ on the unit). A workbook
  is never an input in the app; an administrator can still restore one from
  the console (`python -m workload_app.admin restore`).
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
| `workload_app/secretbox.py` | The sealed copy of a password the Admin tab reads back |
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
| `workload_app/member.py` | What one engineer is allowed to see of their unit |
| `workload_app/people.py` | Teams, grades, and where the work is not where the people are |
| `workload_app/progress.py` | Pro rata or workflow, review codes, and what rework costs |
| `workload_app/timesheet_store.py` | A unit's timesheet rows and its establishment |
| `workload_app/tasks.py` | The task list, the working day, and who is overloaded |
| `workload_app/static/charts.js` | Inline-SVG charts — donut, bars, columns |
| `workload_app/static/tables.js` | Every table sorts by its headings and starts short |
| `workload_app/static/pocket.js` | On a phone: the tabs as a bar along the bottom, and adding the app to the home screen |
| `workload_app/static/manifest.json`, `sw.js`, `offline.html` | What lets a phone keep Selecao+ on its home screen and open it full screen |
| `workload_app/server.py` | The local HTTP transport |
| `workload_app/wsgi.py` | The transport a host uses (PythonAnywhere) |
| `workload_app/admin.py` | Making accounts from a console |
| `workload_app/deployment.py` | The deployment check, and the host's WSGI file |
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

python -m workload_app.admin add <username> [--admin] [--member] [--name NAME]
python -m workload_app.admin list
python -m workload_app.admin password <username>
python -m workload_app.admin remove <username>
python -m workload_app.admin import <username> <workbook.xlsx> [--name NAME]
python -m workload_app.admin check [--wsgi-only]
```

`check` is the one to run on a host: it says whether this installation can
serve, whether the data directory is somewhere a deploy would overwrite, and
prints the WSGI file and static mappings with this checkout's real paths in
them.

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
2. **Timesheets** — choose everyone's export, check the summary, Replace.
3. **Overview** — check the data check reads "All rows matched to an engineer".
4. **Projects** — open anything marked *to confirm* and give it its name,
   budget and step; open each active project and move its deliverables' steps on.
   **Team** — only to set someone's availability; joiners arrive with their timesheets.
5. **Tasks** — check who is overloaded for the weeks ahead, and let a new
   deliverable date fill in its week of preparation.
6. **Reports** — read the Dashboard and Management Review, and print whichever
   view you need for the meeting.
7. Download the workbook (⭳) when you want `Delivery Sequence` or `Profit Plan`,
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
