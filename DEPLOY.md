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
everyone's units with it. `WORKLOAD_DATA_DIR` is what keeps them apart, and
`python -m workload_app.admin check` complains if they are not.

## As a tab of another site, rather than a site of its own

Workload can also be mounted inside a larger site -- Project Control mounts it at
`/workload`, beside its other applications, behind its own sign-in. Then none of
the above is needed: there is no second web app, no second address and no
second password.

* **The site signs people in** and tells Workload who is asking. Workload's own
  login page is never shown, and a username and password made here are not
  used to sign in.
* **Everybody starts with nothing.** Somebody who opens the tab for the first
  time gets an account of their own with no units in it. They cannot see
  anybody else's: a unit is still its owner's alone.
* **Access is given by sign-in.** On the **Team** tab, *Give access* beside an
  engineer picks one of the people who sign in to the site. They need nothing
  new; they open Workload and land on their own page.
* **Units from before the move come across.** Point `WORKLOAD_DATA_DIR` at the
  folder this installation already uses, then, in the tab, *Bring my units
  across* asks once for the old Workload username and password and ties that
  account to the sign-in used now. If the old password is forgotten, set a new
  one first with `python -m workload_app.admin password <old-username>`.
* **Or copy them from the old folder, leaving it as it was.** When the tab keeps
  its own folder and the old site kept another, open the tab once, then run
  `python -m workload_app.admin --data-dir <tab's folder> bring <old folder>`.
  It copies the old folder aside, brings each unit across from the copy (old
  workbooks included) into the tab's account, and changes nothing in the old
  folder. Running it twice brings nothing twice. With several accounts on
  either side, `--from <old-username>` and `--to <sign-in>` say which.
* **The units follow the person, not the address.** An account is tied to the
  site's own identifier for somebody, so correcting the email or username they
  sign in with does not lose them anything.

Run on its own, as described above, nothing about it has changed.

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

   # Accounts and units live outside the code, so a deploy never touches
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
   | `/tables.js` | `/home/<you>/Workload/workload_app/static/tables.js` |
   | `/pocket.js` | `/home/<you>/Workload/workload_app/static/pocket.js` |

7. **Force HTTPS**: on. The session cookie is marked `Secure` as soon as the
   request arrives over HTTPS, and `HttpOnly` and `SameSite=Lax` always.
8. **Reload** the web app.

Open `https://workload-<you>.pythonanywhere.com/` and sign in.

If it does not come up, the Web tab's **error log** has the reason on its last
few lines; nine times in ten it is a path in the WSGI file, or the virtualenv
without `openpyxl` in it.

## 4. Units, and old workbooks

A unit is its own database; a new one starts from the team's timesheet exports
on the unit screen, with the reference tables built into the app.

A unit made in the workbook days needs nothing done to it. The first time it
is opened it is brought across into its own database — registers, team,
reference tables, tasks and every timesheet row — and the old workbook and its
timesheet file are moved into that account's `backups/` folder, untouched, as
`<unit>-before-database-<date>.xlsx` and `.timesheets.db`.

An old workbook that is only on disk can be made into a unit, or put in place
of what a unit holds, from a console:

```bash
python -m workload_app.admin import <username> ~/Workload.xlsx --name "Marine Structures"
python -m workload_app.admin restore <username> "Marine Structures" ~/Workload.xlsx
```

You can always take a copy away: the ⭳ button on a unit downloads everything it
holds as a spreadsheet.

## Updating

```bash
cd ~/Workload && git pull
```

Then **Reload** on the Web tab. The data directory is untouched. Run
`python -m workload_app.admin check` afterwards if you want it confirmed; it
also says how many units are still on an old workbook, waiting to be brought
across the next time they are opened.

## What to keep an eye on

**Memory.** A unit is read from its database as it is needed, so a worker
holds very little: each keeps the open unit of up to sixteen signed-in accounts
(`OPEN_WORKBOOK_LIMIT` in `workload_app/app.py`), and the least recently used
is dropped.

**Disk.** A dated copy of a unit is kept when it is opened (at most every
twelve hours) and before a Replace import, the nightly import or taking
somebody off the team. The last twenty of each unit are kept and older ones
are let go on their own. To see what an account is using:

```bash
du -sh ~/workload-data/users/*
python -m workload_app.admin units
```

To put a copy back: `python -m workload_app.admin restore <username> <unit>
~/workload-data/users/<id>/backups/<copy>.db` — what the unit had is kept first.

**Two workers, one unit.** PythonAnywhere may run more than one worker
process. Every change is a database transaction, and every worker sees it the
moment it is written: a change moves the unit's revision on, and a worker that
finds it moved re-reads before answering.

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
