"""Submissions and their revisions: every time a deliverable goes to the client.

A deliverable is rarely sent once. It is sent (Rev 0), comes back with
comments, goes again as Rev 1, and so on until the client accepts it. Each of
those sendings is an *issue*, kept in ``submission_issues``:

* **planned** -- the day it is meant to go (set when the submission is started);
* **submitted** -- the day it really went;
* **returned** -- the day the client's reply came back, with its **code**
  (A accepted, B approved with comments, C revise and resubmit -- the same
  codes the drawing list reads) and the **reason** given;
* **rev** -- what the office calls it: 0, 1, 2 or A, B, C. The next one
  follows on from the last.

Nothing is overwritten: a new revision is a new issue, so the whole history
stays. The deliverable's own dates (submitted to client, comments received,
resubmitted, completed, status date) are kept in step with its issues, so the
submissions plan, the "waiting for comments" list and the reports all read
the same story.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: The client's codes, and what each means.
CODES = {"A": "Accepted", "B": "Approved with comments", "C": "Revise and resubmit"}
#: How the codes are often written instead: 1 to 4, or in words.
CODE_ALIASES = {"1": "A", "2": "B", "3": "C", "4": "C", "D": "C"}
#: What an issue can be sent for.
PURPOSES = ("IFA", "IFC", "IFT", "IFR", "IFI")
#: A status, in the order a deliverable passes through them, and its words.
STATUSES = {
    "none": "Not started",
    "planned": "Planned",
    "late": "Late to go",
    "with_client": "With the client",
    "returned": "Returned: revise",
    "comments": "Approved with comments",
    "accepted": "Accepted",
}
#: The fields of an issue somebody may change.
FIELDS = ("rev", "purpose", "planned", "submitted", "returned", "code",
          "reason", "ref")
DATE_FIELDS = ("planned", "submitted", "returned")
MAX_TEXT = 300


def clean_code(value: Any) -> str:
    """"A", "a", "Code B", "2" or "approved with comments" as a letter; '' when none."""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = re.sub(r"^CODE\s*[:.\-]?\s*", "", text)
    if text[:1] in CODES and (len(text) == 1 or not text[1].isalpha()):
        return text[:1]
    if text[:1] in CODE_ALIASES and (len(text) == 1 or not text[1].isalnum()):
        return CODE_ALIASES[text[:1]]
    for words, code in (("COMMENT", "B"), ("AS NOTED", "B"), ("REJECT", "C"),
                        ("REVISE", "C"), ("RESUBMIT", "C"), ("APPROV", "A"),
                        ("ACCEPT", "A")):
        if words in text:
            return code
    return "?"


def next_rev(previous: str) -> str:
    """The revision after ``previous``: 0 → 1, A → B, P01 → P02; '0' to start."""
    text = str(previous or "").strip()
    if not text:
        return "0"
    hit = re.search(r"(\d+)$", text)
    if hit:
        digits = hit.group(1)
        return text[:hit.start()] + str(int(digits) + 1).zfill(len(digits))
    if text[-1].isalpha() and text[-1].upper() != "Z":
        bumped = chr(ord(text[-1]) + 1)
        return text[:-1] + bumped
    return text + "1"


def issue_status(issue: Dict[str, Any], today: _dt.date) -> str:
    code = issue.get("code") or ""
    if code == "A":
        return "accepted"
    if issue.get("returned") or code in ("B", "C"):
        return "comments" if code == "B" else "returned"
    if issue.get("submitted"):
        return "with_client"
    planned = issue.get("planned")
    if planned and planned < today.isoformat():
        return "late"
    return "planned"


def describe(issues: Sequence[Dict[str, Any]], today: _dt.date) -> Dict[str, Any]:
    """A deliverable's issues, oldest first, each with its status; and where
    the deliverable stands, which is where its newest issue stands."""
    ordered = sorted(issues, key=lambda i: (i["seq"], i["id"]))
    out = []
    for position, issue in enumerate(ordered):
        status = issue_status(issue, today)
        days = None
        if status == "with_client":
            days = (today - _dt.date.fromisoformat(issue["submitted"])).days
        elif status == "late":
            days = (today - _dt.date.fromisoformat(issue["planned"])).days
        elif status == "planned" and issue.get("planned"):
            days = (_dt.date.fromisoformat(issue["planned"]) - today).days
        out.append({**issue, "status": status, "status_label": STATUSES[status],
                    "code_label": CODES.get(issue.get("code") or "", ""),
                    "days": days, "latest": position == len(ordered) - 1})
    status = out[-1]["status"] if out else "none"
    return {"issues": out, "status": status, "status_label": STATUSES[status],
            "revisions": max(0, sum(1 for i in out if i.get("submitted")) - 1),
            "can_start": not out or status in ("returned", "comments"),
            "next_rev": next_rev(out[-1]["rev"]) if out else "0"}


def dates_for(issues: Sequence[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """The deliverable's own dates, as its issues tell them."""
    ordered = sorted(issues, key=lambda i: (i["seq"], i["id"]))
    sent = [i for i in ordered if i.get("submitted")]
    out: Dict[str, Optional[str]] = {
        "submitted_to_client": sent[0]["submitted"] if sent else None,
        "resubmitted": sent[-1]["submitted"] if len(sent) > 1 else None,
        "comments_received": None,
        "completed": None,
    }
    if sent and (sent[-1].get("returned") or sent[-1].get("code")):
        out["comments_received"] = sent[-1].get("returned")
    accepted = [i for i in ordered if i.get("code") == "A"]
    if accepted:
        out["completed"] = accepted[-1].get("returned") or accepted[-1].get("submitted")
    if ordered and not ordered[-1].get("submitted") and ordered[-1].get("planned"):
        out["status_date"] = ordered[-1]["planned"]
    return out


def from_dates(deliverable: Any) -> List[Dict[str, Any]]:
    """The issues a deliverable's own dates already say happened, for one
    that has dates but no issues yet (a unit from before issues were kept).
    Read only: the dates themselves are left exactly as they are."""
    sent = deliverable.submitted_to_client
    back = deliverable.comments_received
    again = deliverable.resubmitted
    done = deliverable.completed
    first_sent = sent or again or (None if back else done)
    if not (first_sent or back or done):
        return []
    iso = lambda d: d.isoformat() if d else None   # noqa: E731
    issues = []
    if again and (sent or back):
        issues.append({"rev": "0", "submitted": iso(sent), "returned": iso(back),
                       "code": "", "reason": "Comments received" if back else ""})
        issues.append({"rev": "1", "submitted": iso(again), "returned": iso(done),
                       "code": "A" if done else "", "reason": ""})
    else:
        returned = back or done
        issues.append({"rev": "0", "submitted": iso(first_sent),
                       "returned": iso(returned),
                       "code": "A" if done else "",
                       "reason": "" if done or not back else "Comments received"})
    return issues


def check(current: Dict[str, Any], change: Dict[str, Any],
          parse_date) -> Tuple[Dict[str, Any], List[str]]:
    """``current`` with ``change`` laid over it, and what is wrong with it."""
    errors: List[str] = []
    merged = dict(current)
    for key in FIELDS:
        if key not in change:
            continue
        value = change[key]
        if key in DATE_FIELDS:
            day = parse_date(value)
            if value not in (None, "") and day is None:
                errors.append(f"{value!r} is not a date (type it day first, 30/08/2026).")
                continue
            merged[key] = day.isoformat() if day else None
        elif key == "code":
            code = clean_code(value)
            if code == "?":
                errors.append(f"{value!r} is not a client code: use A, B or C.")
                continue
            merged[key] = code
        else:
            merged[key] = str(value or "").strip()[:MAX_TEXT]
    if merged.get("returned") and not merged.get("submitted"):
        errors.append("Give the day it was submitted before the day it came back.")
    if merged.get("code") and not merged.get("submitted"):
        errors.append("A code comes back only after it has been submitted.")
    if merged.get("returned") and merged.get("submitted") \
            and merged["returned"] < merged["submitted"]:
        errors.append("It cannot come back before the day it was submitted.")
    return merged, errors
