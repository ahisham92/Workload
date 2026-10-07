"""Export Detailed Utilization from BISpark and send it to Selecao+.

Runs on your own PC, as you, every night (schedule.ps1 sets that up). It opens
the report in Microsoft Edge with a profile of its own, exports the table the
way you would by hand -- More options, Export data, Underlying data -- and
posts the file to Selecao+, which imports it.

Nothing here stores your password. BISpark signs you in with your Windows
login, as it does in your own browser; if it ever asks for a sign-in instead,
run ``pull.py --show`` once and sign in in the window that opens, and the
profile remembers it.

    pull.py              the nightly run, with no window
    pull.py --show       the same, in a window you can watch
    pull.py --setup      ask for the report link and save it
    pull.py --file X     send an export you already have, without BISpark
"""

from __future__ import annotations

import argparse
import base64
import configparser
import datetime as dt
import json
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "settings.ini"
PROFILE = HERE / "browser-profile"
EXPORTS = HERE / "exports"
LOGS = HERE / "logs"
LOG = LOGS / "last-run.txt"

#: How long to give BISpark to draw the report, and the export to arrive.
LOAD_MS = 120_000
EXPORT_MS = 300_000


def log(message: str) -> None:
    LOGS.mkdir(exist_ok=True)
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    try:
        print(line)
    except Exception:          # pythonw has no console to print to
        pass


def settings() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(SETTINGS, encoding="utf-8")
    return config


def setup() -> None:
    config = settings()
    link = input("Paste the BISpark Detailed Utilization link and press Enter:\n> ").strip()
    if not link.startswith(("http://", "https://")):
        sys.exit("That is not a web link. Copy it from the address bar in Edge.")
    config["bispark"]["report_url"] = link
    with SETTINGS.open("w", encoding="utf-8") as handle:
        config.write(handle)
    print("Saved.")


# -- BISpark -----------------------------------------------------------------

def export_from_bispark(config: configparser.ConfigParser, show: bool) -> Path:
    from playwright.sync_api import sync_playwright

    report = config["bispark"].get("report_url", "").strip()
    if not report:
        raise SystemExit("No report link yet. Run setup.bat, or pull.py --setup.")
    table = config["bispark"].get("table", "Work Breakdown per Project").strip()
    page_name = config["bispark"].get("page", "Detailed Utilization").strip()
    host = urllib.parse.urlparse(report).hostname or "*"
    channel = config["bispark"].get("browser", "msedge").strip() or None

    EXPORTS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(PROFILE), channel=None if channel == "chromium" else channel,
            headless=not show,
            accept_downloads=True, viewport={"width": 1600, "height": 1000},
            # Sign in with the Windows login, as Edge does on the intranet.
            args=[f"--auth-server-allowlist={host}",
                  f"--auth-negotiate-delegate-allowlist={host}"])
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            log(f"Opening {report}")
            page.goto(report, wait_until="domcontentloaded", timeout=LOAD_MS)
            frame = _find_report(page, table, page_name)
            visual = _visual(frame, table)
            log("Exporting the table")
            with page.expect_download(timeout=EXPORT_MS) as download:
                _export(frame, visual)
            target = EXPORTS / f"bispark-{dt.date.today():%Y-%m-%d}{_suffix(download.value.suggested_filename)}"
            download.value.save_as(str(target))
            log(f"Saved {target.name}")
            _keep_last(EXPORTS, 14)
            return target
        except Exception:
            shot = LOGS / "last-failure.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
                log(f"A picture of the page is in {shot}")
            except Exception:
                pass
            raise
        finally:
            browser.close()


def _find_report(page, table: str, page_name: str):
    """The frame the report is drawn in, on the right report page."""
    deadline = dt.datetime.now() + dt.timedelta(milliseconds=LOAD_MS)
    tab_clicked = False
    while dt.datetime.now() < deadline:
        for frame in page.frames:
            try:
                if _shown(frame.get_by_text(table, exact=False)):
                    return frame
                if not tab_clicked and page_name:
                    tab = frame.get_by_text(page_name, exact=True)
                    if tab.count():
                        tab.first.click()
                        tab_clicked = True
            except Exception:
                continue
        page.wait_for_timeout(2000)
    raise RuntimeError(
        f"BISpark opened, but no table called '{table}' appeared. If a "
        f"sign-in page showed instead, run pull.py --show and sign in once.")


def _shown(locator) -> bool:
    """Whether any of what the locator finds is on screen, not just in the page."""
    return any(locator.nth(i).is_visible() for i in range(min(locator.count(), 20)))


def _visual(frame, table: str):
    """The visual whose title is the table's name."""
    for selector in ("visual-container", ".visual-container",
                     ".visualContainerHost", "[data-testid='visual-container']"):
        hits = frame.locator(selector).filter(has_text=table)
        if hits.count():
            return hits.last
    return frame.get_by_text(table, exact=False).first.locator(
        "xpath=ancestor::*[contains(@class,'visual')][1]")


def _export(frame, visual) -> None:
    """More options, Export data, Underlying data, Export."""
    visual.scroll_into_view_if_needed()
    visual.hover()
    more = visual.locator("button[aria-label*='More options'], "
                          "button[title*='More options'], .vcMenuBtn")
    if more.count():
        more.first.click()
    else:
        # The keyboard way into a visual's menu, which every report supports.
        visual.click()
        frame.page.keyboard.press("Alt+Shift+F10")
    frame.get_by_text("Export data", exact=False).first.click()
    for label in ("Underlying data", "Data with current layout"):
        option = frame.get_by_text(label, exact=False)
        if option.count():
            option.first.click()
            break
    frame.get_by_role("button", name="Export", exact=True).first.click()


def _suffix(name: str) -> str:
    suffix = Path(name or "").suffix.lower()
    return suffix if suffix in {".xlsx", ".csv"} else ".xlsx"


def _keep_last(folder: Path, count: int) -> None:
    files = sorted(folder.glob("bispark-*"), key=lambda f: f.stat().st_mtime)
    for old in files[:-count]:
        old.unlink(missing_ok=True)


# -- Selecao+ ----------------------------------------------------------------

def send(config: configparser.ConfigParser, export: Path) -> dict:
    app = config["selecao"]["app_url"].rstrip("/")
    body = json.dumps({
        "key": config["selecao"]["key"],
        "files": [{"filename": export.name,
                   "content_base64": base64.b64encode(export.read_bytes()).decode()}],
    }).encode()
    request = urllib.request.Request(
        app + "/api/nightly/timesheets", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = json.load(error)
        except Exception:
            detail = {"error": str(error)}
        raise RuntimeError(
            f"Selecao+ refused the import: {detail.get('error')} "
            + "; ".join(detail.get("errors") or [])) from None


def report_failure(config: configparser.ConfigParser, message: str) -> None:
    """Tell Selecao+ the night went wrong, so the Timesheets tab says so."""
    try:
        app = config["selecao"]["app_url"].rstrip("/")
        request = urllib.request.Request(
            app + "/api/nightly/timesheets", method="POST",
            data=json.dumps({"key": config["selecao"]["key"],
                             "failed": message}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=60).close()
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true",
                        help="run in a window you can watch")
    parser.add_argument("--setup", action="store_true",
                        help="ask for the report link and save it")
    parser.add_argument("--file", type=Path,
                        help="send this export instead of pulling one")
    args = parser.parse_args()
    if args.setup:
        setup()
        return 0
    LOGS.mkdir(exist_ok=True)
    LOG.write_text("", encoding="utf-8")
    config = settings()
    try:
        export = args.file or export_from_bispark(config, args.show)
        log(f"Sending {export.name} to Selecao+")
        result = send(config, export)
        log(f"Imported {result.get('rows')} rows, {result.get('hours')} hours, "
            f"{result.get('first_date')} to {result.get('last_date')}.")
        return 0
    except SystemExit as stop:
        log(str(stop))
        report_failure(config, str(stop))
        return 1
    except Exception as error:
        log(f"Stopped: {error}")
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc())
        if not str(error).startswith("Selecao+ refused"):
            report_failure(config, f"The PC could not export from BISpark: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
