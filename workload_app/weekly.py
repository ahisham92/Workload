"""The weekly report: last week in figures, this week in things to do.

Nothing here is typed in and nothing is kept.  The report is put together from
what the other tabs already work out -- Check-ins (hours booked, who needs to
ease off, who has room), the staffing forecast (who to ask for), the
submissions plan (what is due) and the timesheet rows -- so it always agrees
with them, and is ready the moment a week starts.

Each section says in plain words what it shows; the list at the top says what
to do about it.
"""

from __future__ import annotations

import datetime as _dt
import html
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .checkins import _hours
from .tasks import week_start

#: How many things to do the report leads with, most pressing first.
TODO_AT_MOST = 7
#: How many projects "where the hours went" lists.
PROJECTS_AT_MOST = 6


def _day(value: Any) -> Optional[_dt.date]:
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _short(day: Optional[_dt.date]) -> str:
    return day.strftime("%a %d %b").replace(" 0", " ") if day else ""


def _pct(load: Optional[float]) -> str:
    return "—" if load is None else f"{round(load * 100)}%"


def _names(names: Sequence[str]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def build(*, unit_name: str, today: _dt.date, config: Dict[str, Any],
          checkins: Mapping[str, Any], needs: Mapping[str, Any],
          submissions: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
          project_names: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """The report for the week ``today`` falls in."""
    start = week_start(today, config)
    end = start + _dt.timedelta(days=6)
    through = _day(checkins.get("through"))
    people = checkins.get("people") or []

    last = _last_week(checkins, people, rows, project_names or {})
    due, late = _due(submissions, start, end)
    ease = [p for p in people if p["signal"]["key"] == "rest"]
    heavy = [p for p in people if p["signal"]["key"] == "busy"]
    room = list(checkins.get("can_take") or [])
    asks = [a for a in needs.get("alerts") or [] if a.get("kind") == "need"]
    unstaffed = list(needs.get("unstaffed") or [])
    meetings = [m for lead in checkins.get("leading") or []
                for m in lead.get("meetings") or []
                if start.isoformat() <= m["date"] <= end.isoformat()]

    todo: List[Dict[str, Any]] = []
    if checkins.get("stale") and through:
        todo.append(_do("bad", "timesheets",
                        f"Upload the latest timesheets: they stop at {_short(through)}, "
                        "so the figures below are behind."))
    if len(late) == 1:
        item = late[0]
        todo.append(_do("bad", "planner",
                        f"Agree a new date for {item['name']} ({item['project']}): "
                        f"it was due {_short(_day(item['was_due']))}."))
    elif late:
        named = [i["name"] for i in late[:2]] + (
            [f"{len(late) - 2} more"] if len(late) > 2 else [])
        todo.append(_do("bad", "planner",
                        f"Agree new dates for the {len(late)} late submissions: "
                        f"{_names(named)}."))
    if len(ease) > 2:
        todo.append(_do("bad", "checkins",
                        f"Give {_names([p['name'] for p in ease])} a lighter week: "
                        "they have been over their hours for weeks."))
    else:
        for person in ease:
            why = (person["signal"].get("reasons") or [""])[0]
            todo.append(_do("bad", "checkins",
                            f"Give {person['name']} a lighter week"
                            + (f" ({why})." if why else ".")))
    for ask in asks:
        if ask.get("severity") == "now":
            todo.append(_do("bad", "resourcing", ask["title"] + "."))
    coming = [i for i in due if not i["late"]]
    for item in coming[:2]:
        todo.append(_do("warn", "planner",
                        f"Check {item['name']} ({item['project']}) is on track "
                        f"for {_short(_day(item['date']))}."))
    if len(coming) > 2:
        todo.append(_do("warn", "planner",
                        f"Check the other {len(coming) - 2} submissions due this week."))
    if unstaffed:
        todo.append(_do("warn", "projects",
                        f"Put someone on {_names([p['name'] for p in unstaffed])}: "
                        "nobody has booked time on "
                        + ("it." if len(unstaffed) == 1 else "them.")))
    for ask in asks:
        if ask.get("severity") != "now":
            todo.append(_do("warn", "resourcing", ask["title"] + "."))
    if room:
        hours = sum(r["free_week"] for r in room)
        todo.append(_do("ok", "planner",
                        f"Give new work to {_names([r['name'] for r in room[:3]])}: "
                        f"{_hours(hours)} free between them this week."))
    more = max(0, len(todo) - TODO_AT_MOST)
    todo = todo[:TODO_AT_MOST]

    urgent = sum(1 for t in todo if t["tone"] == "bad")
    if todo:
        headline = (f"{len(todo) + more} thing{'s' if len(todo) + more != 1 else ''} "
                    f"to act on this week"
                    + (f", {urgent} of them first." if urgent else "."))
    else:
        headline = "Nothing needs you this week: the plan holds."
    if last["load"] is not None:
        headline += (f" The team booked {_pct(last['load'])} of its hours in the "
                     f"week of {_short(_day(last['week']))}.")

    return {
        "unit": unit_name,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "title": f"Week of {_short(start)}",
        "made": today.isoformat(),
        "through": through.isoformat() if through else None,
        "stale": bool(checkins.get("stale")),
        "headline": headline,
        "todo": todo,
        "more": more,
        "last_week": last,
        "this_week": {
            "due": due,
            "meetings": len(meetings),
            "ease_off": [p["name"] for p in ease],
            "heavy": [p["name"] for p in heavy],
            "room": [{"name": r["name"], "free_week": r["free_week"]} for r in room],
            "free_week": checkins.get("free_week", 0.0),
        },
        "staffing": [{"title": a["title"], "detail": a.get("detail", ""),
                      "severity": a.get("severity"), "team_id": a.get("team_id"),
                      "role": a.get("role"), "people": a.get("people")}
                     for a in asks],
        "unstaffed": [{"number": p["number"], "name": p["name"]} for p in unstaffed],
        "drawings": _drawings(needs.get("drawings")),
    }


def _do(tone: str, view: str, text: str) -> Dict[str, Any]:
    return {"tone": tone, "view": view, "text": text}


def _last_week(checkins: Mapping[str, Any], people: Sequence[Mapping[str, Any]],
               rows: Sequence[Mapping[str, Any]],
               project_names: Mapping[str, str]) -> Dict[str, Any]:
    """The latest week the timesheets cover: who booked what, and on which work."""
    weeks = checkins.get("weeks") or []
    if not weeks:
        return {"week": None, "hours": 0.0, "capacity": 0.0, "overtime": 0.0,
                "load": None, "people": [], "projects": []}
    week = weeks[-1]
    first = _day(week)
    last = first + _dt.timedelta(days=6)
    team = []
    for person in people:
        entry = next((w for w in person.get("weeks") or [] if w["week"] == week), None)
        if entry is None:
            continue
        team.append({"name": person["name"], "hours": entry["hours"],
                     "capacity": entry["capacity"], "overtime": entry["overtime"],
                     "load": entry["load"], "days_off": entry.get("days_off", 0),
                     "signal": person["signal"]["key"],
                     "signal_label": person["signal"]["label"]})
    team.sort(key=lambda p: -(p["load"] or 0))
    hours = round(sum(p["hours"] for p in team), 1)
    capacity = round(sum(p["capacity"] for p in team), 1)
    by_project: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"hours": 0.0, "name": ""})
    for row in rows:
        day = row.get("date")
        if not day or not (first <= day <= last):
            continue
        number = row.get("job_number") or ""
        entry = by_project[number]
        entry["hours"] += row.get("hours") or 0.0
        entry["name"] = (entry["name"] or project_names.get(number)
                         or row.get("job_name") or number)
    projects = sorted(({"number": n, "name": p["name"] or n, "hours": round(p["hours"], 1)}
                       for n, p in by_project.items() if p["hours"]),
                      key=lambda p: -p["hours"])
    return {
        "week": week,
        "week_end": last.isoformat(),
        "hours": hours,
        "capacity": capacity,
        "overtime": round(sum(p["overtime"] for p in team), 1),
        "load": round(hours / capacity, 3) if capacity else None,
        "people": team,
        "projects": projects[:PROJECTS_AT_MOST],
        "other_projects": len(projects[PROJECTS_AT_MOST:]),
    }


def _due(submissions: Mapping[str, Any], start: _dt.date, end: _dt.date):
    """What is due this week, and what is already late."""
    due, late = [], []
    for item in submissions.get("items") or []:
        if item.get("prepared"):
            continue
        entry = {"row": item.get("row"), "name": item["name"],
                 "project": item.get("project_number") or "",
                 "project_name": item.get("project_name") or "",
                 "date": item.get("date"), "people": item.get("people") or [],
                 "progress": item.get("progress"),
                 "late": item.get("basis") == "overdue",
                 "was_due": item.get("register_date")}
        if entry["late"]:
            late.append(entry)
            due.append(entry)
        elif entry["date"] and start.isoformat() <= entry["date"] <= end.isoformat():
            due.append(entry)
    due.sort(key=lambda e: (not e["late"], e["date"] or ""))
    return due, late


def _drawings(drawn: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not drawn or not drawn.get("known"):
        return None
    return {k: drawn.get(k) for k in ("total", "done", "left", "progress")}


# --------------------------------------------------------------------------
# the copy to keep
# --------------------------------------------------------------------------

_TONE = {"bad": "#c0392b", "warn": "#b7791f", "ok": "#2f855a", "info": "#2b6cb0"}


def as_html(report: Mapping[str, Any]) -> str:
    """The report as one page that opens anywhere and prints to PDF."""
    e = html.escape
    last = report["last_week"]
    this = report["this_week"]
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{e(report['unit'])} weekly report, {e(report['title'])}</title>",
        "<style>body{font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;"
        "color:#1a202c;max-width:760px;margin:0 auto;padding:24px 16px}"
        "h1{font-size:22px;margin:0}h2{font-size:16px;margin:28px 0 6px;"
        "border-bottom:2px solid #101B2D;padding-bottom:4px}"
        ".muted{color:#5a6475}table{border-collapse:collapse;width:100%}"
        "td,th{padding:5px 6px;border-bottom:1px solid #e2e8f0;text-align:left}"
        "th{font-size:12px;color:#5a6475;text-transform:uppercase}"
        "td.n{text-align:right;font-variant-numeric:tabular-nums}"
        "li{margin:4px 0}.dot{display:inline-block;width:9px;height:9px;"
        "border-radius:50%;margin-right:8px}</style></head><body>",
        f"<h1>{e(report['unit'])}: weekly report</h1>",
        f"<p class='muted'>{e(report['title'])} · made {e(report['made'])}"
        + (f" · timesheets up to {e(report['through'])}" if report.get("through") else "")
        + "</p>",
        f"<p><b>{e(report['headline'])}</b></p>",
        "<h2>What to do this week</h2>",
    ]
    if report["todo"]:
        parts.append("<ol>" + "".join(
            f"<li><span class='dot' style='background:{_TONE[t['tone']]}'></span>"
            f"{e(t['text'])}</li>" for t in report["todo"]) + "</ol>")
        if report.get("more"):
            parts.append(f"<p class='muted'>And {report['more']} more in the app.</p>")
    else:
        parts.append("<p>Nothing needs you this week.</p>")

    parts.append("<h2>Last week</h2>")
    if last["week"]:
        parts.append(
            f"<p class='muted'>Week of {e(_short(_day(last['week'])))}: the team booked "
            f"{_hours(last['hours'])} of the {_hours(last['capacity'])} it had "
            f"({_pct(last['load'])}), with {_hours(last['overtime'])} overtime.</p>")
        parts.append("<table><tr><th>Person</th><th>Booked</th><th>Had</th>"
                     "<th>Load</th><th>Overtime</th><th>How they are</th></tr>"
                     + "".join(
                         f"<tr><td>{e(p['name'])}</td><td class='n'>{_hours(p['hours'])}</td>"
                         f"<td class='n'>{_hours(p['capacity'])}</td>"
                         f"<td class='n'>{_pct(p['load'])}</td>"
                         f"<td class='n'>{_hours(p['overtime'])}</td>"
                         f"<td>{e(p['signal_label'])}</td></tr>" for p in last["people"])
                     + "</table>")
        if last["projects"]:
            parts.append("<p class='muted'>Where the hours went:</p><table>" + "".join(
                f"<tr><td>{e(p['name'])} <span class='muted'>{e(p['number'])}</span></td>"
                f"<td class='n'>{_hours(p['hours'])}</td></tr>" for p in last["projects"])
                + "</table>")
    else:
        parts.append("<p>No timesheets yet.</p>")

    parts.append("<h2>This week</h2>")
    if this["due"]:
        parts.append("<table><tr><th>Due</th><th>Submission</th><th>Project</th>"
                     "<th>Who</th></tr>" + "".join(
                         f"<tr><td>{'Late' if d['late'] else e(_short(_day(d['date'])))}</td>"
                         f"<td>{e(d['name'])}</td><td>{e(d['project'])}</td>"
                         f"<td>{e(', '.join(d['people']))}</td></tr>" for d in this["due"])
                     + "</table>")
    else:
        parts.append("<p>No submissions due.</p>")
    lines = []
    if this["ease_off"]:
        lines.append(f"Needs to ease off: {_names(this['ease_off'])}.")
    if this["heavy"]:
        lines.append(f"Heavy, keep an eye: {_names(this['heavy'])}.")
    if this["room"]:
        lines.append("Has room: " + _names(
            [f"{r['name']} ({_hours(r['free_week'])})" for r in this["room"]]) + ".")
    if this["meetings"]:
        lines.append(f"{this['meetings']} team meeting"
                     f"{'s' if this['meetings'] != 1 else ''} and one-to-ones in the diary.")
    parts.append("".join(f"<p>{e(line)}</p>" for line in lines))

    if report["staffing"] or report["unstaffed"]:
        parts.append("<h2>People to ask for</h2>")
        parts.append("".join(f"<p><b>{e(s['title'])}</b><br>"
                             f"<span class='muted'>{e(s['detail'])}</span></p>"
                             for s in report["staffing"]))
        if report["unstaffed"]:
            parts.append("<p>Nobody booked on: " + e(_names(
                [p["name"] for p in report["unstaffed"]])) + ".</p>")
    if report.get("drawings"):
        d = report["drawings"]
        parts.append("<h2>Drawings</h2>"
                     f"<p>{d['done']:,.0f} of {d['total']:,.0f} done, {d['left']:,.0f} left.</p>")
    parts.append("<p class='muted' style='margin-top:32px'>Made by Selecao+ "
                 "from the timesheets, the task list and the submissions plan.</p>"
                 "</body></html>")
    return "".join(parts)
