Selecao+ nightly timesheets
===========================

Once a day this PC asks BISpark for the Detailed Utilization export
(Underlying data) and it ends up in Selecao+. It uses
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
                so nothing more reaches Selecao+ from any PC
  It is also listed in Task Scheduler as "Selecao+ nightly timesheets".

When a PC goes back to IT
  - A team member's PC holds no key and only ever writes its own export to the
    shared folder. The task runs only under that person's Windows account, so
    once IT resets the PC or the account is closed, it simply stops. After two
    weeks without a fresh export, their file is no longer sent to Selecao+.
  - The manager's PC holds the key. If it goes back without remove.bat, press
    "Stop nightly imports" on the Timesheets tab: the key stops working at
    once, wherever it is. Then download a new kit on the new PC.

Good to know
  - Nothing here is hidden. The task is listed under its own name, and its
    requests go to BISpark and to Selecao+ like any other web request.
  - No password is stored. BISpark signs in with the Windows login, as it
    does in the browser.
  - It tries at night, then every hour, at sign-in, and a minute after the PC
    connects to a network, FortiClient included. Off the Dar network it just
    waits; the first time BISpark can be reached that day, it exports.
  - The manager's PC uploads at most every 6 hours, and only when the shared
    folder has something new. An engineer whose PC was off at midnight exports
    when they next sign in, and goes up with the next upload.
  - The Timesheets tab in Selecao+ shows when the last import ran and whether
    it worked. Details of the last run are in logs\last-run.txt here.
  - If an export has far fewer rows than Selecao+ already holds, it is refused
    and nothing is lost.
  - run-now.bat runs it straight away.
  - settings.ini holds the key that lets a PC import into your unit, so keep
    the folder inside your team. Downloading a new kit cancels the old key on
    every PC.
