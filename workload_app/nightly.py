"""The nightly import: timesheets that arrive on their own.

The exports come out of BISpark, which only a browser on the company network
can reach.  So the export runs on the manager's own PC -- a scheduled job that
opens the report, presses Export the way they would, and posts the file here.
This module is the app's side of that: the kit the job is set up from, and the
import it calls, which signs in with a key rather than a session.

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
import zipfile
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Sequence

from .service import ApiError, WorkloadService

#: The files the scheduled job is made of, shipped with the app.
KIT_DIR = Path(__file__).resolve().parent / "data" / "nightly"

#: An export may hold fewer rows than are stored for a person -- a correction
#: in BISpark deletes some -- but not many fewer.  Past this share missing,
#: the night's import is refused and the rows already held are kept.
LARGEST_SHRINK = 0.10


def kit(app_url: str, key: str) -> bytes:
    """The zip the manager unpacks on their PC: the job, and its settings."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(KIT_DIR.iterdir()):
            if path.is_file():
                archive.write(path, f"selecao-nightly/{path.name}")
        archive.writestr(
            "selecao-nightly/settings.ini",
            "[selecao]\r\n"
            "; Where Selecao+ is, and the key that lets this PC import into\r\n"
            "; one unit. Keep this file to yourself: anyone holding the key\r\n"
            "; can replace that unit's timesheets.\r\n"
            f"app_url = {app_url.rstrip('/')}\r\n"
            f"key = {key}\r\n"
            "\r\n"
            "[bispark]\r\n"
            "; The link you open for Detailed Utilization. setup.bat asks for it.\r\n"
            "report_url =\r\n"
            "; The table to export, by the title above it.\r\n"
            "table = Work Breakdown per Project\r\n"
            "; The report page, by the tab name at the bottom.\r\n"
            "page = Detailed Utilization\r\n")
    return buffer.getvalue()


def run(service: WorkloadService, files: Sequence[Dict[str, Any]]
        ) -> Dict[str, Any]:
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
        held = service.store.counts()
        shrinking = []
        for person in staged["people"]:
            before = held.get(person["name"], 0)
            if before and person["rows"] < before * (1 - LARGEST_SHRINK):
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
    }


def encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
