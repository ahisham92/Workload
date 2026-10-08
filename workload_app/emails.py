"""Emails that come in, turned into draft tasks for the senior to hand out.

Each senior's own Outlook sends each new email here, by itself (a flow on
their own Microsoft 365 account) or by a paste from the phone.  Nothing is
read from a mailbox by the app: only what is sent to it.

An email is one of two things:

* **a draft**: it asks for something.  The project, rough hours, when it is
  wanted and whether it is engineering or drafting are guessed from its words,
  so the senior only picks who and taps Assign, and it becomes a request like
  any other (a time slot, the load, the forecast, the alerts);
* **no action**: an automatic reply, a meeting answer, a newsletter, a
  thank-you, something sent "for information", or an email the senior was only
  copied on that asks nothing.  It never becomes a task, and is kept out of
  the way for a while in case the guess was wrong.

Replies in the same conversation join the open draft instead of making
another one, and a reply about something already handed out says so.

Only a short opening of each email is kept, and only for a month.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import people as people_module
from .model import ValidationError

#: How much of an email is kept: enough to know what it asks.
SNIPPET_CHARS = 800
SUBJECT_CHARS = 300
SENDER_CHARS = 200
#: The most one email may bring in, all fields together (bytes of JSON).
LARGEST_EMAIL = 256 * 1024
#: Emails judged no action, or put aside, are forgotten after this long; the
#: opening of one handed out is blanked after it too.
KEEP_DAYS = 30

STATUS_DRAFT = "draft"
STATUS_NO_ACTION = "no_action"
STATUS_ASSIGNED = "assigned"
STATUS_DISMISSED = "dismissed"
STATUSES = (STATUS_DRAFT, STATUS_NO_ACTION, STATUS_ASSIGNED, STATUS_DISMISSED)


class EmailError(ValidationError):
    pass


# -- reading what was sent ------------------------------------------------

_HTML = re.compile(r"<(html|body|div|p|br|span|table|style|font|b|i)\b[^>]*>", re.I)
_TAGS = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.I | re.S)
_SPACE = re.compile(r"[ \t\r\f\v ]+")
_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|wg|tr|rv)\s*(\[\d+\])?\s*:\s*)+", re.I)
_ADDRESS = re.compile(r"[\w.+'-]+@[\w-]+(\.[\w-]+)+")


def plain(text: Any) -> str:
    """Text out of whatever came: plain text, or an HTML body."""
    text = str(text or "")
    if _HTML.search(text):
        text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", text, flags=re.I)
        text = _TAGS.sub(" ", text)
        text = html.unescape(text)
    lines = [_SPACE.sub(" ", line).strip() for line in text.splitlines()]
    out: List[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def topic(subject: str) -> str:
    """The subject without RE:/FW:, the same for every reply in a conversation."""
    return " ".join(_PREFIX.sub("", subject or "").split()).lower()


def _addresses(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        value = ";".join(str(v.get("address") if isinstance(v, dict) else v)
                         for v in value)
    return [m.group(0).lower() for m in _ADDRESS.finditer(str(value or ""))]


def _sender(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("address") or value.get("emailAddress") or ""
        if isinstance(value, dict):
            value = value.get("address") or ""
    return " ".join(str(value or "").split())[:SENDER_CHARS]


def sender_address(sender: str) -> str:
    found = _addresses(sender)
    return found[0] if found else sender.strip().lower()


def received(body: Mapping[str, Any]) -> Optional[str]:
    raw = str(body.get("received") or body.get("receivedDateTime") or "").strip()
    if not raw:
        return None
    try:
        moment = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.isoformat(timespec="minutes")


def clean(body: Mapping[str, Any]) -> Dict[str, Any]:
    """One email as Outlook sent it, as the app keeps it."""
    if len(json.dumps(body, default=str)) > LARGEST_EMAIL:
        raise EmailError(["That email is too large; only its first part is needed."])
    subject = " ".join(plain(body.get("subject")).split())[:SUBJECT_CHARS]
    text = plain(body.get("body") or body.get("preview") or body.get("bodyPreview"))
    sender = _sender(body.get("from") or body.get("sender"))
    if not subject and not text:
        raise EmailError(["The email has no subject and nothing in it."])
    identity = str(body.get("id") or body.get("message_id")
                   or body.get("internetMessageId") or "").strip()
    if not identity:
        identity = "h:" + hashlib.sha256(
            f"{sender}\n{subject}\n{text[:2000]}\n{body.get('received') or ''}"
            .encode("utf-8")).hexdigest()[:32]
    return {
        "message_key": identity[:300],
        "sender": sender,
        "subject": subject,
        "text": text,
        "snippet": text[:SNIPPET_CHARS],
        "received_at": received(body),
        "to": _addresses(body.get("to") or body.get("toRecipients")),
        "cc": _addresses(body.get("cc") or body.get("ccRecipients")),
        "me": str(body.get("me") or "").strip().lower(),
        "importance": str(body.get("importance") or "").strip().lower(),
    }


_HEADER = re.compile(r"^\s*(from|sent|date|to|cc|subject)\s*:\s*(.*)$", re.I)


def from_paste(text: Any) -> Dict[str, Any]:
    """An email copied on the phone or the PC and pasted in.

    A copy from Outlook on a PC carries From:/Subject: lines; a copy of the
    text alone on a phone does not, and its first line stands for the subject.
    """
    text = plain(text)
    if not text:
        raise EmailError(["Paste the email first."])
    fields: Dict[str, str] = {}
    rest: List[str] = []
    for line in text.splitlines():
        match = _HEADER.match(line)
        if match and match.group(1).lower() not in fields and not rest:
            fields[match.group(1).lower()] = match.group(2).strip()
        elif line or rest:
            rest.append(line)
    content = "\n".join(rest).strip()
    subject = fields.get("subject") or ""
    if not subject:
        first = next((line for line in content.splitlines() if line.strip()), "")
        subject = first[:120]
    return {"subject": subject, "body": content or subject,
            "from": fields.get("from", "")}


# -- does it ask for anything ------------------------------------------------

_SYSTEM_SENDER = re.compile(
    r"(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|"
    r"notifications?@|alerts?@|newsletter|bounce)", re.I)
_AUTOMATIC_SUBJECT = re.compile(
    r"^\s*(automatic reply|auto(matic)?[- ]?reply|out of (the )?office|"
    r"undeliverable|delivery (status )?notification|delivery has failed|"
    r"read:|not read:|recall:|accepted:|declined:|tentative:|"
    r"(updated )?invitation:|canceled:|cancelled:|meeting forward notification)",
    re.I)
_THANKS = re.compile(
    r"^\s*(many |big )?(thanks?|thank you|noted|well received|received( with thanks)?|"
    r"ok(ay)?|great|perfect|appreciated|cheers)\b[\s\S]{0,60}$", re.I)
_FOR_INFORMATION = re.compile(
    r"\b(fyi|for your (information|info|records?|reference)|for info(rmation)?|"
    r"no action (is )?(needed|required))\b", re.I)
_ACTION = re.compile(
    r"\b(please|pls|kindly|could you|can you|would you|will you|need(ed|s)?|"
    r"required?|requested?|review|check|comment|submit|send|share|issue|"
    r"prepare|update|revise|amend|approve|confirm|respond|reply|advise|"
    r"urgent|asap|deadline|due|rfi|action)\b|\?", re.I)


def judge(email: Mapping[str, Any], *, quiet: Iterable[str] = ()) -> Optional[str]:
    """Why an email needs no task, or None when it should be a draft."""
    sender = sender_address(email.get("sender") or "")
    subject = email.get("subject") or ""
    text = email.get("text") or email.get("snippet") or ""
    quiet = {q.strip().lower() for q in quiet if q}
    if sender and sender in quiet:
        return "You said emails from this sender never need a task."
    if _AUTOMATIC_SUBJECT.match(subject):
        return "An automatic reply or a meeting answer."
    if _SYSTEM_SENDER.search(sender):
        return "Sent by a system, not a person."
    if re.search(r"\bunsubscribe\b", text, re.I):
        return "A newsletter or a mailing list."
    words = f"{topic(subject)}\n{text}"
    asks = bool(_ACTION.search(words))
    opening = text.split("\n\n")[0] if text else ""
    if len(text) < 140 and _THANKS.match(text or subject) and "?" not in text:
        return "Just a thank-you or an acknowledgement."
    if _FOR_INFORMATION.search(f"{subject}\n{opening}") and not re.search(
            r"\b(please|kindly|could you|can you|urgent|asap)\b", words, re.I):
        return "Sent for information."
    me = email.get("me") or ""
    if me and email.get("cc") and me in email["cc"] and me not in (email.get("to") or []) \
            and not asks:
        return "You were only copied in, and it asks nothing."
    return None


# -- the guesses beside a draft ---------------------------------------------

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"]
_MONTHS = {name[:3]: i for i, name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}


def _squash(text: str) -> str:
    return re.sub(r"[\s\-_/.]", "", text).upper()


def guess_project(words: str, projects: Mapping[str, str]) -> str:
    """A project the email names, by its number or by its name."""
    squashed = _squash(words)
    lowered = words.lower()
    best = ""
    for number, name in projects.items():
        key = _squash(number)
        if len(key) >= 3 and key in squashed and len(number) > len(best):
            best = number
    if best:
        return best
    # The job alone, without its part ("T10001" for "T10001-0100D"), when
    # only one project has it.
    heads: Dict[str, List[str]] = {}
    for number in projects:
        head = _squash(str(number).split("-")[0])
        if len(head) >= 5:
            heads.setdefault(head, []).append(number)
    for head, numbers in heads.items():
        if len(numbers) == 1 and re.search(
                r"(?<![A-Z0-9])" + re.escape(head) + r"(?![0-9])", words.upper()):
            return numbers[0]
    for number, name in projects.items():
        name = (name or "").strip().lower()
        if len(name) >= 5 and name != str(number).lower() and re.search(
                r"\b" + re.escape(name) + r"\b", lowered):
            return number
    return ""


def guess_due(words: str, today: _dt.date, *, importance: str = "") -> Optional[_dt.date]:
    """When it is wanted, if the email says."""
    text = words.lower()
    if re.search(r"\b(today|tonight|eod|end of (the )?day|asap|urgent(ly)?|"
                 r"immediately|right away)\b", text) or importance == "high":
        return today
    if re.search(r"\btomorrow\b", text):
        return today + _dt.timedelta(days=1)
    if re.search(r"\bnext week\b", text):
        return today + _dt.timedelta(days=7 - today.weekday() + 0)
    match = re.search(r"\b(by|before|on|until|due)\s+(this\s+|next\s+)?(" +
                      "|".join(_WEEKDAYS) + r")\b", text)
    if match:
        target = _WEEKDAYS.index(match.group(3))
        ahead = (target - today.weekday()) % 7 or 7
        if match.group(2) and match.group(2).strip() == "next" and ahead < 7:
            ahead += 7
        return today + _dt.timedelta(days=ahead)
    match = re.search(r"\b(\d{1,2})(st|nd|rd|th)?\s+(of\s+)?(" +
                      "|".join(_MONTHS) + r")[a-z]*\b", text)
    if match:
        return _future(today, int(match.group(1)), _MONTHS[match.group(4)])
    match = re.search(r"\b(" + "|".join(_MONTHS) + r")[a-z]*\s+(\d{1,2})(st|nd|rd|th)?\b",
                      text)
    if match:
        return _future(today, int(match.group(2)), _MONTHS[match.group(1)])
    match = re.search(r"\b(by|before|on|until|due)\s+(\d{1,2})/(\d{1,2})\b", text)
    if match:
        return _future(today, int(match.group(2)), int(match.group(3)))
    if re.search(r"\b(this week|end of (the )?week|eow)\b", text):
        return today + _dt.timedelta(days=max(0, 3 - today.weekday()) or 1)
    return None


def _future(today: _dt.date, day: int, month: int) -> Optional[_dt.date]:
    for year in (today.year, today.year + 1):
        try:
            found = _dt.date(year, month, day)
        except ValueError:
            return None
        if found >= today - _dt.timedelta(days=7):
            return found
    return None


def guess_hours(words: str) -> float:
    text = words.lower()
    if re.search(r"\b(design|calculation|calcs?|model|report|prepare|drawings? set|"
                 r"revise (the )?drawings?)\b", text):
        return 4.0
    if re.search(r"\b(review|check|comment|markup|mark-up|rfi|query)\b", text):
        return 2.0
    return 1.0


def guess_role(words: str) -> str:
    if re.search(r"\b(drafting|draftsm[ae]n|cad|revit|autocad|redlines?|"
                 r"title blocks?|sheet set)\b", words, re.I):
        return people_module.ROLE_DRAFTING
    return people_module.ROLE_ENGINEERING


def guess(email: Mapping[str, Any], *, projects: Mapping[str, str],
          today: _dt.date) -> Dict[str, Any]:
    words = f"{email.get('subject') or ''}\n{email.get('text') or email.get('snippet') or ''}"
    due = guess_due(words, today, importance=email.get("importance") or "")
    return {
        "title": title_of(email),
        "project_number": guess_project(words, projects),
        "hours": guess_hours(words),
        "due": due.isoformat() if due else None,
        "role": guess_role(words),
    }


def title_of(email: Mapping[str, Any]) -> str:
    subject = _PREFIX.sub("", email.get("subject") or "").strip()
    if subject:
        return subject[:120]
    who = sender_address(email.get("sender") or "") or "somebody"
    return f"Email from {who}"[:120]


# -- what the app shows ------------------------------------------------------

def view(item: Mapping[str, Any]) -> Dict[str, Any]:
    out = {k: item[k] for k in ("id", "sender", "subject", "snippet", "status",
                                "reason", "received_at", "task_id", "decided_at",
                                "replies", "created_at")}
    try:
        out["guess"] = json.loads(item.get("guess") or "{}")
    except ValueError:
        out["guess"] = {}
    return out


def quiet_key(user_id: int) -> str:
    return f"inbox_quiet_senders:{int(user_id)}"


def me_key(user_id: int) -> str:
    """The senior's own work address: an email they were only copied on is
    told apart by it."""
    return f"inbox_me:{int(user_id)}"


def read_quiet(value: Optional[str]) -> List[str]:
    try:
        found = json.loads(value or "[]")
    except ValueError:
        return []
    return [str(x) for x in found if x] if isinstance(found, list) else []


def flow_body(key: str) -> str:
    """What a Power Automate flow sends for each new email, ready to paste."""
    return json.dumps({
        "key": key,
        "id": "@{triggerOutputs()?['body/internetMessageId']}",
        "from": "@{triggerOutputs()?['body/from']}",
        "to": "@{triggerOutputs()?['body/toRecipients']}",
        "cc": "@{triggerOutputs()?['body/ccRecipients']}",
        "subject": "@{triggerOutputs()?['body/subject']}",
        "preview": "@{triggerOutputs()?['body/bodyPreview']}",
        "received": "@{triggerOutputs()?['body/receivedDateTime']}",
        "importance": "@{triggerOutputs()?['body/importance']}",
    }, indent=2)


def sorted_items(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return sorted((view(i) for i in items),
                  key=lambda i: (i["received_at"] or i["created_at"] or ""), reverse=True)
