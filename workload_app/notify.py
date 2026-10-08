"""Notifications on the phones of the manager and the team.

What is sent is what the app already flags.  A manager hears that the weekly
report is ready, somebody needs to ease off, a submission is late or due
tomorrow, people should be asked for, timesheets have stopped coming in.  A
team member hears about their own week and deadlines and, when they lead
people, about their team: who needs to ease off and what of theirs is due.
Any phone works: Android in the browser, an iPhone from the home-screen app.  Each has a key, and
a key is sent once: the same thing is never pushed twice.

A run looks at every unit of everybody who has turned notifications on, and
sends each phone one notification for everything new -- one line when
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
#: A team member's own page.
URL_MINE = "./"
#: Whoever the push service should contact about the sender, when the phone
#: did not say where the app was opened.
FALLBACK_CONTACT = "https://github.com/ahisham92/Workload"
#: What each kind of account is told about, as the app says it.
ABOUT_MANAGER = ("Your phone is told when the weekly report is ready, and when something "
                 "needs you: someone stuck or asking for help, someone who needs to ease off, "
                 "a late submission or one due tomorrow, people to ask for, timesheets "
                 "that stopped coming in.")
ABOUT_MEMBER = ("Your phone is told about your week at its start, and when a submission "
                "of yours is late or due tomorrow. If you lead people, you also hear who "
                "in your team is stuck, needs help or needs to ease off, and what of theirs is due.")
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
    out += said_alerts(checkins.get("people") or [], prefix=prefix, url=URL_CHECKINS)
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
    out += _due_alerts(report["this_week"]["due"], _next_working_day(today, checkins),
                       prefix=prefix, url=URL_PLANNER)
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


def said_alerts(people: Sequence[Dict[str, Any]], *, prefix: str,
                url: str) -> List[Dict[str, Any]]:
    """What people said from their My day: stuck, help needed, days off."""
    out = []
    for person in people:
        name = person["name"]
        for ask in person.get("asks") or []:
            what = ask["task"] or ""
            out.append({
                "key": f"ask:{ask['id']}",
                "title": (f"{prefix}{name} is stuck" if ask["kind"] == "stuck"
                          else f"{prefix}{name} needs help"),
                "body": "; ".join(filter(None, [what, ask["note"]])) or "Ask them what they need.",
                "url": url,
            })
        for off in person.get("off_news") or []:
            first, last = _day(off["start"]), _day(off["end"])
            when = _short(first) if first == last else f"{_short(first)} to {_short(last)}"
            out.append({
                "key": f"off:{off['id']}",
                "title": f"{prefix}{name} is off {when}",
                "body": off["note"] or "Entered from their My day. The plan leaves them out.",
                "url": url,
            })
    return out


def _due_alerts(items: Sequence[Dict[str, Any]], tomorrow: Optional[str], *,
                prefix: str, url: str) -> List[Dict[str, Any]]:
    """A late submission, or one due on the next working day."""
    out = []
    for item in items:
        if item["late"]:
            out.append({
                "key": f"late:{item['row']}:{item['was_due']}",
                "title": f"{prefix}Late: {item['name']}",
                "body": f"{item['project']} was due {_short(_day(item['was_due']))}. "
                        "Agree a new date.",
                "url": url,
            })
        elif tomorrow and item["date"] == tomorrow:
            out.append({
                "key": f"due:{item['row']}:{item['date']}",
                "title": f"{prefix}Due tomorrow: {item['name']}",
                "body": f"{item['project']}"
                        + (f", {round(item['progress'] * 100)}% done"
                           if item.get("progress") is not None else "")
                        + (f". With {', '.join(item['people'])}." if item["people"] else "."),
                "url": url,
            })
    return out


def member_alerts(report: Dict[str, Any], checkins: Dict[str, Any], engineer: str, *,
                  today: _dt.date, prefix: str = "") -> List[Dict[str, Any]]:
    """What a team member is told: their own deadlines, and -- when they lead
    people -- their team's: who needs to ease off, what is late or due.

    Nobody outside their own team is named, and none of the manager's other
    figures are in it.
    """
    week = report["week_start"]
    led = next((l["people"] for l in checkins.get("leading") or []
                if l["name"] == engineer), [])
    team = set(led)
    people = {p["name"]: p for p in checkins.get("people") or []}
    mine = [d for d in report["this_week"]["due"] if engineer in d["people"]]
    theirs = [d for d in report["this_week"]["due"]
              if engineer not in d["people"] and team & set(d["people"])]
    ease = [n for n in led if people.get(n, {}).get("signal", {}).get("key") == "rest"]
    me = people.get(engineer) or {}

    lines = []
    if mine:
        late = sum(1 for d in mine if d["late"])
        lines.append(f"{len(mine)} submission{'s' if len(mine) != 1 else ''} with you this week"
                     + (f", {late} late." if late else "."))
    else:
        lines.append("No submissions due with you this week.")
    if me.get("free_week") is not None:
        lines.append(f"{me['free_week']:g} h free in your week.")
    if led:
        lines.append(f"Your team: {len(theirs)} due"
                     + (f", {', '.join(ease)} need{'s' if len(ease) == 1 else ''} to ease off."
                        if ease else "."))
    out: List[Dict[str, Any]] = [{
        "key": f"week:{engineer}:{week}",
        "title": f"{prefix}Your week" + (" and your team's" if led else ""),
        "body": " ".join(lines),
        "url": URL_MINE,
    }]
    for name in ease:
        reasons = people[name]["signal"].get("reasons") or []
        out.append({
            "key": f"rest:{name}:{week}",
            "title": f"{prefix}{name} needs to ease off",
            "body": (f"{reasons[0].capitalize()}. " if reasons else "")
                    + "Agree with them what can wait, and tell your manager.",
            "url": URL_MINE,
        })
    out += said_alerts([people[n] for n in led if n in people and n != engineer],
                       prefix=prefix, url=URL_MINE)
    out += _due_alerts(mine + theirs, _next_working_day(today, checkins),
                       prefix=prefix, url=URL_MINE)
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
    urls = {m.get("url") for m in messages}
    return {"title": f"{len(messages)} things need you", "body": body,
            "url": urls.pop() if len(urls) == 1 else URL_WEEKLY,
            "tag": "selecao-summary"}


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


class _Views:
    """Each unit's report and Check-ins, worked out once per run however
    many people are told about it."""

    def __init__(self, app):
        self.app = app
        self._seen: Dict[str, Any] = {}

    def of(self, owner_id: int, unit_id: str):
        if unit_id not in self._seen:
            from .service import WorkloadService

            service = WorkloadService(autosave=self.app.autosave)
            try:
                self.app._open(service, owner_id, unit_id)
                # The week's plan is kept the first time the week is seen.
                try:
                    service.lock_week_if_due()
                except Exception:          # pragma: no cover - never stops a run
                    traceback.print_exc()
                self._seen[unit_id] = (service.weekly(), service.checkins())
            finally:
                service.close()
        return self._seen[unit_id]


def _new_for_manager(app, views: _Views, user_id: int, unit_ids, today, errors, log):
    units = app.accounts.units(user_id)
    fresh: List[Dict[str, Any]] = []
    for unit in units:
        if unit_ids is not None and unit["id"] not in unit_ids:
            continue
        try:
            report, view = views.of(user_id, unit["id"])
        except Exception as error:             # one bad unit never stops the rest
            errors.append(f"{unit['name']}: {error}")
            if log:
                traceback.print_exc(file=log)
            continue
        prefix = f"{unit['name']}: " if len(units) > 1 else ""
        fresh += app.accounts.new_push_messages(
            user_id, unit["id"], alerts(report, view, today=today, prefix=prefix))
    return fresh


def _new_for_member(app, views: _Views, user_id: int, unit_ids, today, errors, log):
    granted = app.accounts.memberships(user_id)
    fresh: List[Dict[str, Any]] = []
    for row in granted:
        if unit_ids is not None and row["unit_id"] not in unit_ids:
            continue
        try:
            report, view = views.of(row["owner_id"], row["unit_id"])
        except Exception as error:
            errors.append(f"{row['unit_name']}: {error}")
            if log:
                traceback.print_exc(file=log)
            continue
        prefix = f"{row['unit_name']}: " if len(granted) > 1 else ""
        fresh += app.accounts.new_push_messages(
            user_id, row["unit_id"],
            member_alerts(report, view, row["engineer"], today=today, prefix=prefix))
    return fresh


def run(app, *, user_ids: Optional[Sequence[int]] = None,
        unit_ids: Optional[Sequence[str]] = None,
        sender: Optional[Sender] = None, log=None) -> Dict[str, Any]:
    """Look at every unit of everybody with a phone, and send what is new.

    A manager hears about each of their units; a team member about their own
    deadlines and, if they lead people, their team's.
    """
    from .service import _today

    keys = keys_for(app.data_dir)
    owners = sorted({d["user_id"] for d in app.accounts.push_devices()})
    if user_ids is not None:
        owners = [o for o in owners if o in set(user_ids)]
    views = _Views(app)
    today = _today()
    report = {"accounts": 0, "sent": 0, "new": 0, "failed": 0, "errors": []}
    for user_id in owners:
        user = app.accounts.user(user_id)
        if user is None:
            continue
        find = _new_for_manager if user.get("role") == "manager" else _new_for_member
        fresh = find(app, views, user_id, unit_ids, today, report["errors"], log)
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


def people_of_unit(app, owner_id: int, unit_id: str) -> List[int]:
    """Everybody to tell when this unit changes: its manager, and the people
    who were given access to it."""
    return [owner_id] + [m["user_id"] for m in app.accounts.unit_members(unit_id)]


def test(app, user_id: int, *, sender: Optional[Sender] = None) -> List[Dict[str, Any]]:
    """A notification now, to every phone of the account, to show it works."""
    return deliver(app.accounts, keys_for(app.data_dir), user_id, {
        "title": "Notifications are on",
        "body": "Selecao+ will tell you here when something needs you.",
        "url": "./", "tag": "selecao-test"}, sender=sender)


def task_command(app) -> str:
    """The line to give the host's scheduled task, for this installation."""
    code = Path(__file__).resolve().parent.parent
    prefix = Path(sys.prefix)
    python = prefix / "bin" / "python"
    if not python.exists() or sys.prefix == sys.base_prefix:
        python = Path(f"python{sys.version_info.major}.{sys.version_info.minor}")
    return (f"cd {code} && {python} -m workload_app.admin "
            f"--data-dir {Path(app.data_dir).resolve()} notify")
