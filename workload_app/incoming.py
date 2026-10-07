"""Work coming: a project just assigned, before anybody books to it.

The staffing forecast reads the work ahead from the timesheets and the
projects' own figures, so a project that has only just been given to the unit
is invisible to it until somebody books an hour.  That is exactly when a lead
needs to know whether to ask for people.

So a new project goes in as one line -- a name, the job number if there is
one yet, which team, rough hours, from when to when -- and the forecast counts
it from its start:

* its hours are spread over its working days, less whatever has already been
  booked to its job number, so the estimate is used up as the work is done;
* the split between engineers and draftsmen is the team's own recent split,
  once anybody books to it, the split of whoever is booking;
* when the project is confirmed with its own budget, or its rough hours are
  used up, the forecast goes back to reading it the usual way, and the line
  says so.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .model import ValidationError

#: The most rough hours one line may carry: past that it is a programme.
LONGEST_HOURS = 100_000.0
#: How long a project with no end date is spread over.
DEFAULT_MONTHS = 3


class IncomingError(ValidationError):
    pass


def _date(value: Any, fallback: Optional[_dt.date]) -> Optional[_dt.date]:
    text = str(value or "").strip()
    if not text:
        return fallback
    return _dt.date.fromisoformat(text[:10])


def clean(body: Mapping[str, Any], *, teams: Iterable[str],
          today: _dt.date) -> Dict[str, Any]:
    errors: List[str] = []
    name = " ".join(str(body.get("name") or "").split())[:120]
    job_number = " ".join(str(body.get("job_number") or "").split()).upper()[:40]
    if not name and not job_number:
        errors.append("Give the project a name or its job number.")
    team_id = str(body.get("team_id") or "").strip()
    if team_id and team_id not in set(teams):
        errors.append("There is no such team.")
    try:
        hours = float(str(body.get("hours") or "").replace(",", ""))
    except ValueError:
        hours = 0.0
    if not 0 < hours <= LONGEST_HOURS:
        errors.append("Give the rough hours, more than none.")
    try:
        start = _date(body.get("start"), today)
        end = _date(body.get("end"), None)
    except ValueError:
        raise IncomingError(["Give the dates as dates."])
    if end is None:
        month = start.month - 1 + DEFAULT_MONTHS
        end = _dt.date(start.year + month // 12, month % 12 + 1, 1) - _dt.timedelta(days=1)
    if end < start:
        errors.append("It ends before it starts.")
    if errors:
        raise IncomingError(errors)
    return {"job_number": job_number, "name": name or job_number, "team_id": team_id,
            "hours": round(hours, 1), "start": start.isoformat(), "end": end.isoformat()}
