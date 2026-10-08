"""The nightly import: timesheets that arrive on their own.

The exports come out of BISpark, which only a PC on the company network can
reach.  So the export runs on each person's own PC: a scheduled PowerShell job
that sends BISpark the request the Export button sends, signed in with the
Windows login, and posts the file here.  This module is the app's side of that:
the request, pasted once from the browser; the kit the job is set up from; and
the import it calls, which signs in with a key rather than a session.

The request stays with the unit, never in this repository: it names the
company's server and its report, and the code is public.

The import is the Timesheets tab's own (``stage_exports`` then
``apply_exports``, replacing each person's rows), with one guard in front of
it.  Nobody is watching at midnight, so an export that would quietly take
rows away -- a date filter narrower than usual, a report that came back half
empty -- is refused rather than written, and the refusal is what the tab
shows the next morning.
"""

from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from urllib.parse import urlparse
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from . import budgets
from .service import ApiError, WorkloadService

#: The files the scheduled job is made of, shipped with the app.
KIT_DIR = Path(__file__).resolve().parent / "data" / "nightly"

#: An export may hold fewer rows than are stored for a person -- a correction
#: in BISpark deletes some -- but not many fewer.  Past this share missing,
#: the night's import is refused and the rows already held are kept.
LARGEST_SHRINK = 0.10
# A row or two fewer is a correction, not a lost date filter, even for
# somebody who has only a handful of rows so far.
SMALL_SHRINK = 2

#: Where the unit keeps the pasted request, in its own settings.
SOURCE_SETTING = "nightly_request"


def parse_capture(text: str) -> Dict[str, str]:
    """The export request out of what the browser copied.

    Chrome's and Edge's *Copy as PowerShell* gives an ``Invoke-WebRequest``
    call; only its address and its body are kept.  The cookies and headers
    in it belong to that browser session and are left behind -- the job signs
    in afresh with the Windows login every night.
    """
    text = str(text or "")
    uri = re.search(r'-Uri\s+"([^"]+)"', text)
    body = (re.search(r'-Body\s+"(.*)"\s*$', text.strip(), re.S)
            # Non-ASCII bodies come wrapped: -Body ([...]::UTF8.GetBytes("..."))
            or re.search(r'GetBytes\("(.*)"\)\)\s*$', text.strip(), re.S))
    if not uri or not body:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "That is not a copied export request. In the browser's Network "
            "tab, right-click the export entry and choose Copy, then Copy as "
            "PowerShell.")
    address = uri.group(1)
    parsed = urlparse(address)
    if parsed.scheme != "https" or "/export" not in parsed.path:
        raise ApiError(HTTPStatus.BAD_REQUEST,
                       "That request is not an export. Copy the one that "
                       "appears when Export is pressed.")
    # PowerShell escapes with a backtick inside double quotes.
    payload = re.sub(r"`(.)", r"\1", body.group(1))
    try:
        json.loads(payload)
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST,
                       "The request's body did not come through whole. Copy "
                       "it again.") from None
    return {"uri": address, "body": payload}


#: Where the team's PCs leave their exports for the manager's PC to send.
FOLDER_SETTING = "nightly_shared_folder"


def source(service: WorkloadService) -> Dict[str, Any]:
    """What the unit has for a request, without handing the request out."""
    raw = service.store.setting(SOURCE_SETTING)
    folder = service.store.setting(FOLDER_SETTING) or ""
    if not raw:
        return {"set": False, "shared_folder": folder}
    request = json.loads(raw)
    return {"set": True, "host": urlparse(request["uri"]).hostname,
            "shared_folder": folder}


def save_source(service: WorkloadService, body: Dict[str, Any]) -> Dict[str, Any]:
    """Keep a newly pasted request, the shared folder, or both."""
    if str(body.get("capture") or "").strip():
        service.store.set_setting(
            SOURCE_SETTING, json.dumps(parse_capture(body["capture"])))
    if "shared_folder" in body:
        folder = " ".join(str(body.get("shared_folder") or "").split())
        if folder and not re.match(r"^(\\\\[^\\]+\\[^\\]+|[A-Za-z]:\\)", folder):
            raise ApiError(HTTPStatus.BAD_REQUEST,
                           "Give the shared folder as a network path like "
                           "\\\\server\\share\\folder, or a drive like S:\\folder.")
        service.store.set_setting(FOLDER_SETTING, folder or None)
    return source(service)


def request_for(service: WorkloadService) -> Dict[str, str]:
    raw = service.store.setting(SOURCE_SETTING)
    if not raw:
        raise ApiError(HTTPStatus.CONFLICT,
                       "Paste the export request from BISpark first.")
    return json.loads(raw)


def kit(request: Dict[str, str], *, shared_folder: str = "",
        app_url: str = "", key: str = "",
        budget_requests: Optional[Dict[str, Any]] = None) -> bytes:
    """The zip each PC unpacks: the job, its settings and the request.

    With a key it is the manager's kit, which sends to Selecao+ at 1:00 am.
    Without one it is a team member's, which only leaves its export in the
    shared folder at midnight: it holds no key and talks to nothing outside
    the company.
    """
    manager = bool(key)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(KIT_DIR.iterdir()):
            if path.is_file():
                archive.write(path, f"selecao-nightly/{path.name}")
        lines = ["[selecao]",
                 f"role = {'manager' if manager else 'team'}",
                 f"run_at = {'1:00 AM' if manager else '12:00 AM'}",
                 "; Where every PC on the team leaves its export.",
                 f"shared_folder = {shared_folder}"]
        if manager:
            lines += ["; Where Selecao+ is, and the key that lets this PC import",
                      "; into one unit. Keep it to yourself: anyone holding the",
                      "; key can replace that unit's timesheets.",
                      f"app_url = {app_url.rstrip('/')}",
                      f"key = {key}"]
        archive.writestr("selecao-nightly/settings.ini",
                         "\r\n".join(lines) + "\r\n")
        archive.writestr("selecao-nightly/request.json",
                         json.dumps(request, indent=1))
        if manager and budget_requests:
            # The Projects list and each job's staff expenditure, once a day.
            archive.writestr("selecao-nightly/budgets.json",
                             json.dumps(budget_requests, indent=1))
    return buffer.getvalue()


def run(service: WorkloadService, files: Sequence[Dict[str, Any]],
        late: Sequence[str] = ()) -> Dict[str, Any]:
    """Import tonight's exports into the open unit, or refuse and say why."""
    if not files:
        raise ApiError(HTTPStatus.BAD_REQUEST, "No export came with the import.")
    staged = service.stage_exports(files)
    token = staged["token"]
    try:
        if staged["errors"]:
            raise ApiError(HTTPStatus.BAD_REQUEST,
                           "The export could not be read as a timesheet.",
                           staged["errors"])
        # Rows a staff expenditure filled in are not the person's own export.
        held = service.store.counts(without_source=budgets.SPEND_SOURCE)
        shrinking = []
        for person in staged["people"]:
            before = held.get(person["name"], 0)
            if (before - person["rows"] > SMALL_SHRINK
                    and person["rows"] < before * (1 - LARGEST_SHRINK)):
                shrinking.append(
                    f"{person['full_name']}: {person['rows']} rows in tonight's "
                    f"export, {before} already held")
        if shrinking:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "Tonight's export has far fewer rows than the app already "
                "holds, so nothing was replaced. Check that the report's date "
                "filter still starts at the beginning.", shrinking)
    except ApiError:
        service.discard_timesheet(token)
        raise
    result = service.apply_exports(token, "replace")
    return {
        "rows": staged["rows"],
        "hours": staged["hours"],
        "first_date": staged["first_date"],
        "last_date": staged["last_date"],
        "people": [p["full_name"] for p in staged["people"]],
        "people_added": result.get("people_added", []),
        "projects_added": result.get("projects_added", []),
        "warnings": staged["warnings"][:20],
        "late": [str(name) for name in late][:50],
    }


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def run_budgets(service: WorkloadService, kind: str,
                files: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The budgets step of the night: the Projects list, then staff lists.

    The answer to the Projects list names the jobs whose staff expenditure
    the PC should ask for next, so the PC never has to read a spreadsheet.
    """
    if kind not in {"budgets", "spend"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"Nothing imports {kind!r}.")
    if not files:
        raise ApiError(HTTPStatus.BAD_REQUEST, "No export came with the import.")
    result = service.import_budgets(files)
    wanted = "projects" if kind == "budgets" else "spend"
    if not any(f["kind"] == wanted for f in result["files"]):
        raise ApiError(HTTPStatus.BAD_REQUEST,
                       "That export is not the one this step asks for.",
                       result.get("errors") or [])
    out = {
        "kind": kind,
        "jobs_listed": result["jobs_listed"],
        "spend_jobs": result["spend_jobs"],
        "rows_filled": result["rows_filled"],
        "projects_updated": result["projects_updated"],
        "warnings": (result["warnings"] + result["errors"])[:20],
    }
    if kind == "budgets":
        out["jobs"] = budgets.jobs_to_fetch(service)
    return out

