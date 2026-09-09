# Putting Workload on PythonAnywhere

The app is a WSGI application with no framework and one dependency
(`openpyxl`). It runs happily beside whatever else you already host: a
PythonAnywhere account can serve several web apps, each with its own domain,
its own code, its own virtualenv and its own data.

Everything below is done once.

## The one rule

Nothing this app owns may live inside the code:

```
/home/<you>/Workload           <- this repository        (replaced by a deploy)
/home/<you>/workload-data      <- accounts.db, and one folder per account
```

A deploy replaces the code. If the data sat inside it, a deploy would take
everyone's workbooks with it. `WORKLOAD_DATA_DIR` is what keeps them apart, and
`python -m workload_app.admin check` complains if they are not.

## A second website beside the one you already have

A **paid** PythonAnywhere account may host more than one web app. Only your
main `<you>.pythonanywhere.com` is special — there is exactly one of those, and
it is presumably taken by your existing app. The new one gets a name of its
own:

* `workload-<you>.pythonanywhere.com` — a **custom PythonAnywhere subdomain**.
  Free, no DNS to configure, available on paid accounts. Anything in place of
  `workload` works, as long as it ends in `-<you>.pythonanywhere.com`.
  (On the EU servers it is `workload-<you>.eu.pythonanywhere.com`.)
* `workload.your-company.com` — your **own domain**, if you have one. That one
  needs a CNAME at your DNS provider pointing at the address PythonAnywhere
  shows on the Web tab after you create the app.

Whichever you pick, the two apps stay entirely separate: separate source
directory, separate virtualenv, separate WSGI file, separate
`WORKLOAD_DATA_DIR`. Nothing you do here touches the app you already run.

## 1. Get the code onto the server

In a **Bash console**:

```bash
git clone https://github.com/<you>/Workload.git
cd Workload
python3 -m venv ~/.virtualenvs/workload      # its own, not the other app's
source ~/.virtualenvs/workload/bin/activate
pip install -r requirements.txt
mkdir -p ~/workload-data
export WORKLOAD_DATA_DIR=~/workload-data
python -m workload_app.admin check
```

The check tells you what this installation is, whether it can run, and prints
the exact WSGI file and static-file mappings for **these** paths. Keep the
console open — step 3 is mostly copying from it.

## 2. Make the first account

There is no public sign-up: an administrator makes every account, and the first
one has to be made here.

```bash
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

On the **Web** tab, **Add a new web app**. Then:

1. **Domain.** On a paid account you are asked for the domain name rather than
   being given `<you>.pythonanywhere.com`. Enter
   `workload-<you>.pythonanywhere.com` (or your own domain — then follow the
   CNAME instructions it shows afterwards).
2. **Manual configuration** — *not* Flask/Django. Then **Python 3.11**, or
   whatever `python3 --version` reported in the console.
3. **Virtualenv**: `/home/<you>/.virtualenvs/workload`
4. **Source code**: `/home/<you>/Workload`
5. **WSGI configuration file**: click it and replace everything with the block
   the check printed. It is `deploy/pythonanywhere_wsgi.py` with your paths
   already filled in; to get just that block:

   ```bash
   python -m workload_app.admin check --wsgi-only
   ```

   ```python
   import os
   import sys

   path = '/home/<you>/Workload'
   if path not in sys.path:
       sys.path.insert(0, path)

   # Accounts and workbooks live outside the code, so a deploy never touches
   # them, and no other web app on this account shares them.
   os.environ['WORKLOAD_DATA_DIR'] = '/home/<you>/workload-data'

   from workload_app.wsgi import application       # noqa: E402,F401
   ```

   Check both paths against the other web app's WSGI file. They must not
   match.

6. **Static files** (optional, but it serves the CSS and JS without waking
   Python):

   | URL | Path |
   | --- | --- |
   | `/app.css` | `/home/<you>/Workload/workload_app/static/app.css` |
   | `/app.js` | `/home/<you>/Workload/workload_app/static/app.js` |
   | `/member.js` | `/home/<you>/Workload/workload_app/static/member.js` |
   | `/charts.js` | `/home/<you>/Workload/workload_app/static/charts.js` |

7. **Force HTTPS**: on. The session cookie is marked `Secure` as soon as the
   request arrives over HTTPS, and `HttpOnly` and `SameSite=Lax` always.
8. **Reload** the web app.

Open `https://workload-<you>.pythonanywhere.com/` and sign in.

If it does not come up, the Web tab's **error log** has the reason on its last
few lines; nine times in ten it is a path in the WSGI file, or the virtualenv
without `openpyxl` in it.

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

Then **Reload** on the Web tab. The data directory is untouched. Run
`python -m workload_app.admin check` afterwards if you want it confirmed.

## What to keep an eye on

**Memory.** A parsed workbook is tens of megabytes, and each worker process
holds up to four of them (`OPEN_WORKBOOK_LIMIT` in `workload_app/app.py`);
the least recently used is saved and dropped. Two web apps on one account share
the account's allowance — if you see a worker being killed, lower that number
to 2.

**Long requests.** Raising the timesheet limit rewrites every formula in the
consolidated sheet and takes the better part of a minute on a full workbook.
It happens only when you press the button on the **Timesheets** tab, or when an
import needs the room. PythonAnywhere's web workers will cut off a request that
runs past their limit; if that happens, do it from a console instead, where
nothing is watching the clock:

```bash
python -m workload_app.admin check      # confirms which data directory
```

then open the unit and re-run the import — the limit only has to be raised once.

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

**Back it up.** The whole application state is one folder — and that includes
`secret.key`, without which the Admin tab can no longer read passwords back
(everyone can still sign in; the passwords just stop being visible). Keep the
archive somewhere private: it holds the key *and* the database, which together
are the readable passwords.

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
