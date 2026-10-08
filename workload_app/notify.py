"""Notifications on the manager's phone.

What is sent is what the app already flags: the weekly report being ready,
somebody who needs to ease off, a submission that is late or due tomorrow,
people to ask for, timesheets that have stopped coming in.  Each has a key, and
a key is sent once: the same thing is never pushed twice.

A run looks at every unit of every manager who has turned notifications on,
and sends each phone one notification for everything new -- one line when
there is one thing, "3 things need you" when there are several.  It runs

* from the host's scheduled task, ``python -m workload_app.admin notify``
  (the reliable way: once a day, early, before the working day); and
* after a nightly timesheet import, for the unit that was imported into.

Nothing else sends: no emails, no messages outside the app.
"""

from __future__ import annotations

import datetime as _dt
import sys
import traceback
import urllib.error
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import webpush
from .weekly import _short, _day

#: Where a tap on a notification takes the manager.
URL_WEEKLY = "./#weekly"
URL_CHECKINS = "./#checkins"
URL_PLANNER = "./#planner"
URL_RESOURCING = "./#resourcing"
URL_TIMESHEETS = "./#timesheets"
#: Whoever the push service should contact about the sender, when the phone
#: did not say where the app was opened.
FALLBACK_CONTACT = "https://github.com/ahisham92/Workload"
#: A phone whose push service keeps refusing is given up on after this many.
GIVE_UP_AFTER = 10


def keys_for(data_dir: Path) -> webpush.Keys:
    return webpush.Keys(Path(data_dir) / "push.key")


def alerts(report: Dict[str, Any], checkins: Dict[str, Any], *, today: _dt.date,
           prefix: str = "") -> List[Dict[str, Any]]:
    """What is worth a notification today, each with the key it is sent once by."""
    week = report["week_start"]
    out: List[Dict[str, Any]] = [{
        "key": f"weekly:{week}",
        "title": f"{prefix}Weekly report is ready",
        "body": report["headline"],
        "url": URL_WEEKLY,
    }]
    if report.get("stale") and report.get("through"):
        out.append({
            "key": f"stale:{report['through']}",
            "title": f"{prefix}Timesheets have stopped coming in",
            "body": f"The latest are from {_short(_day(report['through']))}. "
                    "Upload this week's so the figures catch up.",
            "url": URL_TIMESHEETS,
        })
    for person in checkins.get("people") or []:
        if person["signal"]["key"] != "rest":
            continue
        reasons = person["signal"].get("reasons") or []
        out.append({
            "key": f"rest:{person['name']}:{week}",
            "title": f"{prefix}{person['name']} needs to ease off",
            "body": (f"{reasons[0].capitalize()}. " if reasons else "")
                    + "Agree what can wait or move to someone with room.",
            "url": URL_CHECKINS,
        })
    tomorrow = _next_working_day(today, checkins)
    for item in report["this_week"]["due"]:
        if item["late"]:
            out.append({
                "key": f"late:{item['row']}:{item['was_due']}",
                "title": f"{prefix}Late: {item['name']}",
                "body": f"{item['project']} was due {_short(_day(item['was_due']))}. "
                        "Agree a new date.",
                "url": URL_PLANNER,
            })
        elif tomorrow and item["date"] == tomorrow:
            out.append({
                "key": f"due:{item['row']}:{item['date']}",
                "title": f"{prefix}Due tomorrow: {item['name']}",
                "body": f"{item['project']}"
                        + (f", {round(item['progress'] * 100)}% done"
                           if item.get("progress") is not None else "")
                        + (f". With {', '.join(item['people'])}." if item["people"] else "."),
                "url": URL_PLANNER,
            })
    for ask in report.get("staffing") or []:
        if ask.get("severity") != "now":
            continue
        out.append({
            "key": f"need:{ask.get('team_id')}:{ask.get('role')}:{ask.get('people')}",
            "title": f"{prefix}{ask['title']}",
            "body": ask.get("detail", ""),
            "url": URL_RESOURCING,
        })
    return out


def _next_working_day(today: _dt.date, checkins: Dict[str, Any]) -> Optional[str]:
    """The day after today that Check-ins plans, which skips weekends and
    holidays the unit keeps."""
    for day in checkins.get("days") or []:
        if day > today.isoformat():
            return day
    return None


def summary(messages: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """One notification for everything new."""
    if len(messages) == 1:
        only = messages[0]
        return {"title": only["title"], "body": only.get("body", ""),
                "url": only.get("url") or URL_WEEKLY, "tag": only["key"]}
    titles = [m["title"] for m in messages]
    body = "\n".join(titles[:4]) + (f"\nand {len(titles) - 4} more" if len(titles) > 4 else "")
    return {"title": f"{len(messages)} things need you", "body": body,
            "url": URL_WEEKLY, "tag": "selecao-summary"}


Sender = Callable[..., int]


def deliver(accounts, keys: webpush.Keys, user_id: int, message: Dict[str, Any],
            *, sender: Optional[Sender] = None) -> List[Dict[str, Any]]:
    """Send one notification to each of the account's phones; how each went."""
    sender = sender or webpush.send
    results = []
    for device in accounts.push_devices(user_id, secrets_too=True):
        outcome = {"id": device["id"], "label": device["label"], "ok": False}
        try:
            sender(keys, device, message,
                   contact=device.get("site") or FALLBACK_CONTACT)
        except webpush.Gone:
            accounts.forget_push_device(device["id"])
            outcome["error"] = "This phone has turned notifications off."
            outcome["gone"] = True
        except (urllib.error.URLError, OSError, ValueError) as error:
            reason = _reason(error)
            accounts.push_result(device["id"], reason)
            outcome["error"] = reason
            if device["failures"] + 1 >= GIVE_UP_AFTER:
                accounts.forget_push_device(device["id"])
        else:
            accounts.push_result(device["id"])
            outcome["ok"] = True
        results.append(outcome)
    return results


def _reason(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        detail = ""
        try:
            detail = error.read().decode("utf-8", "replace")[:200]
        except Exception:                      # pragma: no cover - best effort
            pass
        return f"The push service said {error.code}" + (f": {detail}" if detail else ".")
    if isinstance(error, urllib.error.URLError):
        return f"Could not reach the push service ({error.reason})."
    return str(error) or type(error).__name__


def check_unit(app, user_id: int, unit: Dict[str, Any], *, several: bool,
               today: Optional[_dt.date] = None) -> List[Dict[str, Any]]:
    """The new alerts of one unit, kept so they are not sent again."""
    from .service import WorkloadService, _today

    service = WorkloadService(autosave=app.autosave)
    try:
        app._open(service, user_id, unit["id"])
        report = service.weekly()
        view = service.checkins()
    finally:
        service.close()
    prefix = f"{unit['name']}: " if several else ""
    found = alerts(report, view, today=today or _today(), prefix=prefix)
    return app.accounts.new_push_messages(user_id, unit["id"], found)


def run(app, *, user_ids: Optional[Sequence[int]] = None,
        unit_ids: Optional[Sequence[str]] = None,
        sender: Optional[Sender] = None, log=None) -> Dict[str, Any]:
    """Look at every unit of every manager with a phone, and send what is new."""
    keys = keys_for(app.data_dir)
    owners = sorted({d["user_id"] for d in app.accounts.push_devices()})
    if user_ids is not None:
        owners = [o for o in owners if o in set(user_ids)]
    report = {"accounts": 0, "sent": 0, "new": 0, "failed": 0, "errors": []}
    for user_id in owners:
        user = app.accounts.user(user_id)
        if user is None or user.get("role") != "manager":
            continue
        units = app.accounts.units(user_id)
        fresh: List[Dict[str, Any]] = []
        for unit in units:
            if unit_ids is not None and unit["id"] not in unit_ids:
                continue
            try:
                fresh += check_unit(app, user_id, unit, several=len(units) > 1)
            except Exception as error:         # one bad unit never stops the rest
                report["errors"].append(f"{unit['name']}: {error}")
                if log:
                    traceback.print_exc(file=log)
        report["accounts"] += 1
        report["new"] += len(fresh)
        if not fresh:
            continue
        for outcome in deliver(app.accounts, keys, user_id, summary(fresh),
                               sender=sender):
            if outcome["ok"]:
                report["sent"] += 1
            else:
                report["failed"] += 1
                report["errors"].append(f"{outcome['label'] or 'a phone'}: "
                                        f"{outcome.get('error')}")
    return report


def test(app, user_id: int, *, sender: Optional[Sender] = None) -> List[Dict[str, Any]]:
    """A notification now, to every phone of the account, to show it works."""
    return deliver(app.accounts, keys_for(app.data_dir), user_id, {
        "title": "Notifications are on",
        "body": "Selecao+ will tell you here when the weekly report is ready "
                "and when something needs you.",
        "url": URL_WEEKLY, "tag": "selecao-test"}, sender=sender)


def task_command(app) -> str:
    """The line to give the host's scheduled task, for this installation."""
    code = Path(__file__).resolve().parent.parent
    prefix = Path(sys.prefix)
    python = prefix / "bin" / "python"
    if not python.exists() or sys.prefix == sys.base_prefix:
        python = Path(f"python{sys.version_info.major}.{sys.version_info.minor}")
    return (f"cd {code} && {python} -m workload_app.admin "
            f"--data-dir {Path(app.data_dir).resolve()} notify")
