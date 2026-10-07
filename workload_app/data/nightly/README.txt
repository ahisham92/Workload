Selecao+ nightly timesheets
===========================

Every night at 12:00 am this PC asks BISpark for the Detailed Utilization
export (Underlying data) and sends it to Selecao+, which imports it. It uses
only what Windows already has: nothing is installed, and no administrator is
needed. It runs without a window and does not touch the mouse, keyboard or
browser, so the PC can be in use while it runs.

Set up (once, on each PC)
  1. Unzip this folder somewhere that stays, e.g. Documents\selecao-nightly.
  2. Double-click setup.bat. If Windows says it protected your PC, choose
     More info, then Run anyway.
  3. It exports once while you watch, then schedules itself.

Your team
  BISpark gives each person only their own timesheets. Send this same folder
  to each engineer and ask them to double-click setup.bat on their own PC.
  Their rows go into your unit every night too.

Stopping it
  pause.bat     stops it until resume.bat is run
  remove.bat    removes it from this PC for good; then delete the folder
  Selecao+      "Stop nightly imports" on the Timesheets tab cancels the key,
                so every PC with this kit stops at once
  It is also listed in Task Scheduler as "Selecao+ nightly timesheets".

Good to know
  - Nothing here is hidden. The task is listed under its own name, and its
    requests go to BISpark and to Selecao+ like any other web request.
  - No password is stored. BISpark signs in with the Windows login, as it
    does in the browser.
  - The PC has to be on or asleep at midnight. If it was off, the export runs
    at the next sign-in.
  - The Timesheets tab in Selecao+ shows when the last import ran and whether
    it worked. Details of the last run are in logs\last-run.txt here.
  - If an export has far fewer rows than Selecao+ already holds, it is refused
    and nothing is lost.
  - run-now.bat runs it straight away.
  - settings.ini holds the key that lets a PC import into your unit, so keep
    the folder inside your team. Downloading a new kit cancels the old key on
    every PC.
