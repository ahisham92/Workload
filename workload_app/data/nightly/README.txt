Selecao+ nightly timesheets
===========================

Every night at 12:00 am this PC opens BISpark, exports the Work Breakdown per
Project table from Detailed Utilization (Underlying data), and sends it to
Selecao+, which imports it. You do nothing after the first setup.

Set up (once)
  1. Unzip this folder somewhere that stays, e.g. Documents\selecao-nightly.
  2. Double-click setup.bat and paste your BISpark report link when asked.
  3. Watch the first run in the Edge window it opens. Sign in if BISpark asks.

Good to know
  - Your password is never stored. BISpark signs in with your Windows login.
  - The PC has to be on or asleep at midnight. If it was off, the export runs
    when you next sign in.
  - The Timesheets tab in Selecao+ shows when the last import ran and whether
    it worked. Details of the last run are in logs\last-run.txt here.
  - If tonight's export has far fewer rows than Selecao+ already holds (say
    the report's date filter changed), it is refused and nothing is lost.
  - run-now.bat runs it immediately. remove.bat stops it.
  - settings.ini holds the key that lets this PC import into your unit. Keep
    it to yourself. Making a new kit in Selecao+ cancels the old key.

If it stops working
  BISpark's page may have changed. Run run-now.bat to watch where it stops;
  logs\last-failure.png is a picture of the page when it did.
