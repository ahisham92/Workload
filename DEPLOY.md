# Putting Workload on PythonAnywhere

The app is a WSGI application with no framework and one dependency
(`openpyxl`), so a free PythonAnywhere account is enough to run it for a team.
Everything below is done once.

## Before you start

Decide where the data lives. It must be **outside** the code:

```
/home/<you>/workload-data      <- accounts.db, and one folder per account
/home/<you>/Workload           <- this repository
```

A deploy replaces the code. If the data sat inside it, a deploy would take
everyone's workbooks with it.

## 1. Get the code onto the server

In a **Bash console** on PythonAnywhere:

```bash
git clone https://github.com/<you>/Workload.git
cd Workload
python3 -m venv ~/.virtualenvs/workload
source ~/.virtualenvs/workload/bin/activate
pip install -r requirements.txt
mkdir -p ~/workload-data
```

## 2. Make the first account

There is no public sign-up: an administrator makes every account, and the first
one has to be made here.

```bash
export WORKLOAD_DATA_DIR=~/workload-data
python -m workload_app.admin add <username> --admin
```

It asks for a password twice, or generates one if you press Enter. Write it
down — it cannot be read back. Later accounts can be made from the app's own
**Accounts** panel, or with the same command.

Accounts come in two kinds. A **manager** runs a team: they own units and edit
them. A **team member** signs in to a read-only page of their own figures, and
is given that by their manager from the **Team** tab (*Give access* beside an
engineer). To make one from the console instead:

```bash
python -m workload_app.admin add osama --member
```

## 3. Create the web app

On the **Web** tab:

1. **Add a new web app** → **Manual configuration** → **Python 3.11** (or
   whatever version the console's `python3 --version` reports).
2. **Virtualenv**: `/home/<you>/.virtualenvs/workload`
3. **Source code**: `/home/<you>/Workload`
4. **WSGI configuration file**: click it and replace everything with:

```python
import os
import sys

path = '/home/<you>/Workload'
if path not in sys.path:
    sys.path.insert(0, path)

# Accounts and workbooks live outside the code, so a deploy never touches them.
os.environ['WORKLOAD_DATA_DIR'] = '/home/<you>/workload-data'

from workload_app.wsgi import application       # noqa: E402,F401
```

5. **Static files** (optional but worth it — it serves the CSS and JS without
   waking Python):

   | URL | Directory |
   | --- | --- |
   | `/app.css` | `/home/<you>/Workload/workload_app/static/app.css` |
   | `/app.js` | `/home/<you>/Workload/workload_app/static/app.js` |
   | `/member.js` | `/home/<you>/Workload/workload_app/static/member.js` |
   | `/charts.js` | `/home/<you>/Workload/workload_app/static/charts.js` |

6. **Force HTTPS**: on. The session cookie is marked `Secure` as soon as the
   request arrives over HTTPS, and `HttpOnly` and `SameSite=Lax` always.
7. **Reload** the web app.

Open `https://<you>.pythonanywhere.com/` and sign in.

## 4. Bring your own workbook

Two ways, and both leave the file in that account only:

- **In the app** — *Upload a Workload workbook* on the unit screen.
- **From a console** — if the file is already on the server:

  ```bash
  python -m workload_app.admin import <username> ~/Workload.xlsx --name "Marine Structures"
  ```

A unit started with **Start blank** uses the template that ships with the app:
the whole model — formulas, charts, project types, rules of credit, the
scorecard — with no projects, no deliverables, no hours and generic engineer
names.

You can always take a copy back: the ⭳ button on a unit downloads the workbook
as it stands.

## Updating

```bash
cd ~/Workload && git pull
```

Then **Reload** on the Web tab. The data directory is untouched.

## What to keep an eye on

**Memory.** A parsed workbook is tens of megabytes, and each worker process
holds up to four of them (`OPEN_WORKBOOK_LIMIT` in `workload_app/app.py`);
the least recently used is saved and dropped. A free account has a small
allowance — if you see the worker being killed, lower that number to 2.

**Disk.** Every save writes a timestamped backup beside the workbook, in that
account's own folder. They are the reason a bad import is recoverable, and they
do add up. To see what an account is using and prune the oldest:

```bash
du -sh ~/workload-data/users/*
ls -t ~/workload-data/users/1/backups | tail -n +30 | xargs -I{} rm ~/workload-data/users/1/backups/{}
```

**Two workers, one workbook.** PythonAnywhere may run more than one worker
process. Each holds its own copy, takes an exclusive lock on the file while
writing, and re-reads the file when it finds it changed underneath. That is
safe for one person working in one place at a time, which is how this is used.
Two people editing the *same unit* at the same second is not something to
attempt.

**Back it up.** The whole application state is one folder:

```bash
tar czf ~/workload-backup-$(date +%F).tar.gz ~/workload-data
```

## Running it on your own machine

Exactly the same app, same login, same storage:

```bash
python -m workload_app.admin add <username> --admin
python -m workload_app
```

It opens `http://127.0.0.1:8765/`. Data goes to `./instance` unless
`WORKLOAD_DATA_DIR` says otherwise.

## Rebuilding the blank template

If the workbook's structure changes and the template should follow:

```bash
python tools/build_template.py path/to/Workload.xlsx
```

It clears the registers, the timesheets and the tasks, renames the engineers to
`Engineer 1..3`, and then opens the result the way the app does and prints what
is in it. The output is `workload_app/data/template.xlsx`, which is committed.
