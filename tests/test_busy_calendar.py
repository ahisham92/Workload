"""Outlook meetings: each person's busy times, from a published calendar link.

Only start and end times are kept; a meeting repeats, moves and is cancelled
the way Outlook says; time zones land where the owner works; and the time
comes off free hours, the planner and the forecast without being counted
twice against the meetings Selecao+ already keeps.  Calendars here are made
up, and no link is ever fetched from the network.
"""

import datetime as dt
import urllib.error
import urllib.request

import pytest

from workload_app import busy_calendar as bc, management, storage
from workload_app.service import WorkloadService

from test_checkins import TODAY, booking, export
from test_roles import call, site, osama, PASSWORD, _sign_in, Client  # noqa: F401

RIYADH = """BEGIN:VTIMEZONE
TZID:Arab Standard Time
BEGIN:STANDARD
DTSTART:16010101T000000
TZOFFSETFROM:+0300
TZOFFSETTO:+0300
END:STANDARD
END:VTIMEZONE
"""
LONDON = """BEGIN:VTIMEZONE
TZID:GMT Standard Time
BEGIN:STANDARD
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0000
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T010000
TZOFFSETFROM:+0000
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
"""


def calendar(*events, zones=RIYADH + LONDON):
    body = "".join(f"BEGIN:VEVENT\n{e.strip()}\nEND:VEVENT\n" for e in events)
    return ("BEGIN:VCALENDAR\nMETHOD:PUBLISH\nPRODID:Microsoft Exchange Server 2010\n"
            "VERSION:2.0\n" + zones + body + "END:VCALENDAR\n").replace("\n", "\r\n")


def event(start, end, *, uid="u1", status="BUSY", extra="", tz="Arab Standard Time"):
    return (f"UID:{uid}\nSUMMARY:Busy\nDTSTART;TZID={tz}:{start}\n"
            f"DTEND;TZID={tz}:{end}\nX-MICROSOFT-CDO-BUSYSTATUS:{status}\n{extra}")


def busy(text, start=dt.date(2026, 10, 1), end=dt.date(2026, 11, 30)):
    return [(a.isoformat(timespec="minutes"), b.isoformat(timespec="minutes"))
            for a, b in bc.busy_times(text, start=start, end=end,
                                      day_start="08:00", day_end="16:30")]


class TestReading:
    def test_a_single_meeting(self):
        assert busy(calendar(event("20261012T100000", "20261012T110000"))) == [
            ("2026-10-12T10:00", "2026-10-12T11:00")]

    def test_free_and_working_elsewhere_are_not_meetings(self):
        text = calendar(event("20261012T100000", "20261012T110000", status="FREE"),
                        event("20261013T100000", "20261013T110000", uid="u2",
                              status="WORKINGELSEWHERE"),
                        event("20261014T100000", "20261014T110000", uid="u3",
                              status="TENTATIVE"))
        assert busy(text) == [("2026-10-14T10:00", "2026-10-14T11:00")]

    def test_cancelled_is_not_a_meeting(self):
        assert busy(calendar(event("20261012T100000", "20261012T110000",
                                   extra="STATUS:CANCELLED"))) == []

    def test_only_times_come_out_whatever_the_file_holds(self):
        text = calendar(event("20261012T100000", "20261012T110000",
                              extra="LOCATION:Board room\nDESCRIPTION:Secret client"))
        out = bc.busy_times(text, start=dt.date(2026, 10, 1), end=dt.date(2026, 10, 30))
        assert out == [(dt.datetime(2026, 10, 12, 10), dt.datetime(2026, 10, 12, 11))]

    def test_another_zone_lands_at_the_owners_hour(self):
        # 10:00 in London in British summer time is 12:00 in Riyadh; after the
        # clocks go back on 25 October it is 13:00.
        text = calendar(event("20261012T090000", "20261012T093000"),
                        event("20261020T100000", "20261020T110000", uid="u2",
                              tz="GMT Standard Time"),
                        event("20261027T100000", "20261027T110000", uid="u3",
                              tz="GMT Standard Time"))
        got = [(a.isoformat(timespec="minutes"), b.isoformat(timespec="minutes"))
               for a, b in bc.busy_times(text, start=dt.date(2026, 10, 1),
                                         end=dt.date(2026, 10, 30), home="Asia/Riyadh")]
        assert got == [("2026-10-12T09:00", "2026-10-12T09:30"),
                       ("2026-10-20T12:00", "2026-10-20T13:00"),
                       ("2026-10-27T13:00", "2026-10-27T14:00")]

    def test_without_a_country_the_calendars_own_zone(self):
        # Most entries are in the Riyadh zone, so that is where the owner is.
        text = calendar(event("20261012T090000", "20261012T093000"),
                        event("20261013T090000", "20261013T093000", uid="u4"),
                        event("20261020T100000", "20261020T110000", uid="u2",
                              tz="GMT Standard Time"))
        assert busy(text)[-1] == ("2026-10-20T12:00", "2026-10-20T13:00")

    def test_utc_times_are_moved_home(self):
        text = calendar(event("20261012T090000", "20261012T093000"),
                        event("20261013T090000", "20261013T093000", uid="u4"),
                        "UID:u2\nDTSTART:20261014T080000Z\nDTEND:20261014T090000Z\n"
                        "SUMMARY:Busy")
        assert ("2026-10-14T11:00", "2026-10-14T12:00") in busy(text)

    def test_a_weekly_meeting_with_a_day_moved_and_a_day_cancelled(self):
        text = calendar(
            event("20250105T090000", "20250105T093000", uid="s",
                  extra="RRULE:FREQ=WEEKLY;UNTIL=20270101T060000Z;INTERVAL=1;"
                        "BYDAY=SU,TU;WKST=SU\n"
                        "EXDATE;TZID=Arab Standard Time:20261013T090000"),
            event("20261011T140000", "20261011T150000", uid="s",
                  extra="RECURRENCE-ID;TZID=Arab Standard Time:20261011T090000"))
        got = busy(text, dt.date(2026, 10, 8), dt.date(2026, 10, 21))
        assert got == [("2026-10-11T14:00", "2026-10-11T15:00"),
                       ("2026-10-18T09:00", "2026-10-18T09:30"),
                       ("2026-10-20T09:00", "2026-10-20T09:30")]

    def test_a_daily_meeting_from_years_ago_still_shows(self):
        text = calendar(event("20150101T083000", "20150101T084500",
                              extra="RRULE:FREQ=DAILY;INTERVAL=1"))
        got = busy(text, dt.date(2026, 10, 12), dt.date(2026, 10, 13))
        assert got == [("2026-10-12T08:30", "2026-10-12T08:45"),
                       ("2026-10-13T08:30", "2026-10-13T08:45")]

    def test_a_count_ends_the_series(self):
        text = calendar(event("20261012T100000", "20261012T110000",
                              extra="RRULE:FREQ=DAILY;COUNT=2"))
        assert len(busy(text)) == 2

    def test_monthly_second_tuesday_and_last_weekday(self):
        text = calendar(
            event("20261013T100000", "20261013T110000", uid="a",
                  extra="RRULE:FREQ=MONTHLY;BYDAY=2TU;COUNT=2"),
            event("20261030T150000", "20261030T160000", uid="b",
                  extra="RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=2"))
        assert busy(text) == [("2026-10-13T10:00", "2026-10-13T11:00"),
                              ("2026-10-30T15:00", "2026-10-30T16:00"),
                              ("2026-11-10T10:00", "2026-11-10T11:00"),
                              ("2026-11-30T15:00", "2026-11-30T16:00")]

    def test_out_of_office_all_day_fills_the_working_day(self):
        text = calendar("UID:o\nDTSTART;VALUE=DATE:20261015\nDTEND;VALUE=DATE:20261016\n"
                        "X-MICROSOFT-CDO-BUSYSTATUS:OOF",
                        "UID:r\nDTSTART;VALUE=DATE:20261016\nDTEND;VALUE=DATE:20261017\n"
                        "X-MICROSOFT-CDO-BUSYSTATUS:FREE")
        assert busy(text) == [("2026-10-15T08:00", "2026-10-15T16:30")]

    def test_overlaps_are_one_stretch(self):
        text = calendar(event("20261012T100000", "20261012T110000"),
                        event("20261012T103000", "20261012T120000", uid="u2"))
        assert busy(text) == [("2026-10-12T10:00", "2026-10-12T12:00")]

    def test_folded_lines_and_a_broken_entry(self):
        text = calendar(event("20261012T100000", "20261012T110000",
                              extra="DESCRIPTION:a long\r\n  line"),
                        "UID:bad\nDTSTART:garbage\nDTEND:20261012T110000")
        assert busy(text) == [("2026-10-12T10:00", "2026-10-12T11:00")]

    def test_minus_leaves_what_is_not_already_held(self):
        at = lambda h, m=0: dt.datetime(2026, 10, 12, h, m)   # noqa: E731
        assert bc.minus([(at(9), at(12))], [(at(10), at(10, 30)), (at(11), at(13))]) \
            == [(at(9), at(10)), (at(10, 30), at(11))]


class TestTheLink:
    @pytest.mark.parametrize("link", [
        "https://outlook.office365.com/owa/calendar/abc@example.com/def/calendar.ics",
        "webcal://outlook.office365.com/owa/calendar/abc/def/calendar.ics",
        " https://outlook.office.com/owa/calendar/abc/def/reachcalendar.ics "])
    def test_outlook_links(self, link):
        assert bc.clean_link(link).startswith("https://outlook.office")

    @pytest.mark.parametrize("link", [
        "", "http://outlook.office365.com/owa/calendar/a/b/calendar.ics",
        "https://example.com/calendar.ics",
        "https://outlook.office365.com.example.com/calendar.ics",
        "https://outlook.office365.com/owa/calendar/a/b/calendar.html",
        "file:///etc/passwd"])
    def test_anything_else_is_refused(self, link):
        with pytest.raises(bc.CalendarLinkError):
            bc.clean_link(link)


class TestRefusals:
    def test_the_hosts_proxy_is_not_outlook(self, monkeypatch):
        def refused(self, request, timeout=None):
            raise urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        monkeypatch.setattr(urllib.request.OpenerDirector, "open", refused)
        with pytest.raises(bc.CalendarLinkError) as caught:
            bc.fetch("https://outlook.office365.com/owa/calendar/a/b/calendar.ics")
        assert caught.value.errors == [bc.HOST_REFUSED]

    def test_outlook_saying_no_is_outlook(self, monkeypatch):
        def gone(self, request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        monkeypatch.setattr(urllib.request.OpenerDirector, "open", gone)
        with pytest.raises(bc.CalendarLinkError) as caught:
            bc.fetch("https://outlook.office365.com/owa/calendar/a/b/calendar.ics")
        assert "Outlook did not give" in caught.value.errors[0]

    def test_no_network_at_all(self, monkeypatch):
        def down(self, request, timeout=None):
            raise urllib.error.URLError(OSError("Name or service not known"))
        monkeypatch.setattr(urllib.request.OpenerDirector, "open", down)
        with pytest.raises(bc.CalendarLinkError) as caught:
            bc.fetch("https://outlook.office365.com/owa/calendar/a/b/calendar.ics")
        assert "Could not reach Outlook" in caught.value.errors[0]


CONFIG = {"work_days": [0, 1, 2, 3, 4], "day_start": "08:00", "day_end": "16:30",
          "hours_per_day": 8.5, "holidays": set(), "away": {}}
MONDAY = dt.date(2026, 10, 12)


def roster(*people):
    return [{"name": n, "grade": g, "team_id": None, "active": True} for n, g in people]


class TestInThePlan:
    def at(self, h, m=0, day=MONDAY):
        return dt.datetime.combine(day, dt.time(h, m))

    def test_outlook_meetings_take_the_time_once(self):
        people = roster(("Amal", "manager"), ("Bassem", "junior"))
        # Amal's team meeting is 08:00-08:35 on the Monday; Outlook has 08:15-09:00.
        plan = management.Plan(people, [], CONFIG, outlook={
            "Amal": [(self.at(8, 15), self.at(9))],
            "Bassem": [("2026-10-12T13:00", "2026-10-12T14:00")]}, today=MONDAY)
        team = next(m for m in plan.meetings_on(MONDAY) if m["kind"] == "team")
        assert (team["start"], team["end"]) == (self.at(8), self.at(8, 35))
        blocks = plan.for_day(MONDAY)["meetings"]
        outlook = [(m["leader"], m["start"], m["end"]) for m in blocks
                   if m["kind"] == "outlook"]
        assert outlook == [("Amal", self.at(8, 35), self.at(9)),
                           ("Bassem", self.at(13), self.at(14))]
        assert (self.at(13), self.at(14)) in plan.busy("Bassem", MONDAY, 1)

    def test_hours_a_day_for_the_planner_and_forecast(self):
        people = roster(("Dina", "engineer"))
        week = [MONDAY + dt.timedelta(days=i) for i in range(14)]
        spans = [(dt.datetime.combine(d, dt.time(10)), dt.datetime.combine(d, dt.time(12)))
                 for d in week]
        without = management.Plan(people, [], CONFIG, today=MONDAY).taken_a_day()["Dina"]
        plan = management.Plan(people, [], CONFIG, outlook={"Dina": spans}, today=MONDAY)
        # Two hours on every working day; Saturday and Sunday do not count.
        assert plan.outlook_a_day() == {"Dina": 2.0}
        assert plan.taken_a_day()["Dina"] == pytest.approx(without + 2.0)

    def test_away_means_no_meetings(self):
        config = {**CONFIG, "away": {"Dina": {MONDAY.isoformat()}}}
        plan = management.Plan(roster(("Dina", "engineer")), [], config, outlook={
            "Dina": [(self.at(10), self.at(11))]}, today=MONDAY)
        assert plan.outlook_on(MONDAY) == []

    def test_development_time_moves_off_an_outlook_meeting(self):
        friday = MONDAY + dt.timedelta(days=4)
        plan = management.Plan(roster(("Dina", "engineer")), [], CONFIG, outlook={
            "Dina": [(self.at(15, day=friday), self.at(16, 30, day=friday))]},
            today=MONDAY)
        _meetings, development, outlook = plan.day_blocks(friday)
        assert development[0]["end"] == self.at(15, day=friday)
        assert [(o["start"], o["end"]) for o in outlook] == [
            (self.at(15, day=friday), self.at(16, 30, day=friday))]


class TestTheUnit:
    @pytest.fixture
    def unit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
        service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
        service.import_exports([
            export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
            export("dina", booking("Dina Ashgrove", "N2-0100D", 4)),
        ])
        return service

    def dina(self, unit):
        day = unit.day_plan({})["days"][0]
        return next(p for p in day["people"] if p["name"] == "Dina")

    def test_meetings_come_off_free_hours_and_go_again(self, unit):
        before = self.dina(unit)
        unit.set_calendar_link("Dina", "sealed", "self")
        today = TODAY.isoformat()
        assert unit.record_calendar("Dina", busy=[
            (dt.datetime.fromisoformat(f"{today}T10:00"),
             dt.datetime.fromisoformat(f"{today}T11:30"))])
        after = self.dina(unit)
        assert after["free_hours"] == pytest.approx(max(0, before["free_hours"] - 1.5)) \
            or after["hours"] > before["hours"]
        meeting = [b for b in after["blocks"] if b.get("source") == "outlook"]
        assert [(b["start"], b["end"]) for b in meeting] == [("10:00", "11:30")]
        assert meeting[0]["title"] == "In a meeting (from Outlook)"
        status = unit.calendars()
        dina = next(p for p in status["people"] if p["person"] == "Dina")
        assert dina["linked"] and dina["meetings"] == 1 and dina["hours_next_7_days"] == 1.5
        assert "link" not in dina and "link_seal" not in dina

        unit.remove_calendar_link("Dina")
        assert not [b for b in self.dina(unit)["blocks"] if b.get("source") == "outlook"]

    def test_the_same_times_again_write_nothing(self, unit):
        unit.set_calendar_link("Dina", "sealed", "self")
        times = [(dt.datetime(2026, 10, 7, 10), dt.datetime(2026, 10, 7, 11))]
        assert unit.record_calendar("Dina", busy=times) is True
        revision = unit.workbook.revision
        assert unit.record_calendar("Dina", busy=times) is False
        assert unit.workbook.revision == revision

    def test_a_problem_keeps_the_last_times(self, unit):
        unit.set_calendar_link("Dina", "sealed", "self")
        unit.record_calendar("Dina", busy=[(dt.datetime(2026, 10, 7, 10),
                                            dt.datetime(2026, 10, 7, 11))])
        unit.record_calendar("Dina", problem="Outlook did not give the calendar.")
        dina = next(p for p in unit.calendars()["people"] if p["person"] == "Dina")
        assert dina["problem"] and dina["meetings"] == 1

    def test_only_the_coming_weeks_are_kept(self, unit):
        unit.set_calendar_link("Dina", "sealed", "self")
        unit.record_calendar("Dina", busy=[
            (dt.datetime(2026, 9, 1, 10), dt.datetime(2026, 9, 1, 11)),
            (dt.datetime(2026, 10, 7, 10), dt.datetime(2026, 10, 7, 11)),
            (dt.datetime(2027, 3, 1, 10), dt.datetime(2027, 3, 1, 11))])
        assert unit.store.calendar_busy()["Dina"] == [("2026-10-07T10:00", "2026-10-07T11:00")]

    def test_only_people_on_the_team(self, unit):
        with pytest.raises(Exception):
            unit.set_calendar_link("Nobody Here", "sealed", "manager")


ICS = calendar(event("20261012T100000", "20261012T110000"))


@pytest.fixture
def outlook(site):
    """No network: every link reads the same made-up calendar."""
    seen = []
    site.app.calendar_fetch = lambda link: seen.append(link) or ICS
    return seen


class TestRoutes:
    LINK = "https://outlook.office365.com/owa/calendar/x@example.com/y/calendar.ics"

    def test_a_manager_links_somebody_and_the_link_is_sealed(self, site, outlook):
        status, body = call(site, "/api/calendars", "PUT",
                            {"person": "Osama", "link": self.LINK})
        assert status == 200, body
        assert outlook == [self.LINK]
        osama_ = next(p for p in body["people"] if p["person"] == "Osama")
        assert osama_["linked"] and osama_["added_by"] == "manager"
        assert self.LINK not in str(body)
        service = site.app.service_for(1)
        links = service.store.calendar_links()
        assert self.LINK not in links["Osama"]["link_seal"]
        assert site.app.accounts.unseal(links["Osama"]["link_seal"]) == self.LINK

    def test_a_bad_link_is_refused_before_anything_is_fetched(self, site, outlook):
        status, body = call(site, "/api/calendars", "PUT",
                            {"person": "Osama", "link": "https://example.com/x.ics"})
        assert status == 422 and outlook == []

    def test_reading_again_waits_unless_asked(self, site, outlook):
        call(site, "/api/calendars", "PUT", {"person": "Osama", "link": self.LINK})
        _s, body = call(site, "/api/calendars/refresh", "POST", {})
        assert body["result"]["read"] == 0 and len(outlook) == 1
        _s, body = call(site, "/api/calendars/refresh", "POST", {"force": True})
        assert body["result"]["read"] == 1 and len(outlook) == 2

    def test_a_link_that_stopped_working_says_so(self, site, outlook):
        call(site, "/api/calendars", "PUT", {"person": "Osama", "link": self.LINK})

        def stopped(link):
            raise bc.CalendarLinkError(["Outlook did not give the calendar."])
        site.app.calendar_fetch = stopped
        _s, body = call(site, "/api/calendars/refresh", "POST", {"force": True})
        osama_ = next(p for p in body["people"] if p["person"] == "Osama")
        assert "did not give" in osama_["problem"]

    def test_a_member_links_only_their_own(self, site, osama, outlook):
        status, body = call(osama, "/api/me/calendar", "PUT",
                            {"link": self.LINK, "person": "Kirolos"})
        assert status == 200, body
        assert [p["person"] for p in body["people"]] == ["Osama"]
        assert body["people"][0]["added_by"] == "self"
        _s, everybody = call(site, "/api/calendars")
        linked = [p["person"] for p in everybody["people"] if p["linked"]]
        assert linked == ["Osama"]
        status, body = call(osama, "/api/me/calendar/remove", "POST", {"person": "Kirolos"})
        assert status == 200 and not body["people"][0]["linked"]

    def test_a_member_cannot_reach_everybodys(self, site, osama, outlook):
        for method, path in (("GET", "/api/calendars"), ("PUT", "/api/calendars"),
                             ("POST", "/api/calendars/refresh"),
                             ("POST", "/api/calendars/remove")):
            status, _ = call(osama, path, method, {"person": "Kirolos", "link": self.LINK})
            assert status == 403, path

    def test_nothing_is_open_without_signing_in(self, site, outlook):
        anonymous = Client(str(site))
        for method, path in (("GET", "/api/calendars"), ("GET", "/api/me/calendar"),
                             ("PUT", "/api/me/calendar")):
            status, _ = call(anonymous, path, method, {"link": self.LINK})
            assert status == 401, path


class TestMeetingsTypedIn:
    """Meetings put in by hand: a client, another trade, internal."""

    def body(self, **extra):
        return {"title": "Design review", "kind": "client", "day": "2026-10-12",
                "start": "10:00", "end": "11:30", "people": ["Dina"], **extra}

    def test_checked_as_typed(self):
        from workload_app import meetings
        with pytest.raises(meetings.MeetingError) as caught:
            meetings.clean(self.body(end="09:00", people=["Nobody"], kind="party"),
                           people=["Dina"], today=TODAY)
        assert len(caught.value.errors) == 3
        made = meetings.clean(self.body(repeat="weekly", until="2026-11-02"),
                              people=["Dina"], today=TODAY)
        assert made["until"] == "2026-11-02" and made["people"] == ["Dina"]

    def test_a_weekly_meeting_falls_each_week(self):
        from workload_app import meetings
        row = {"id": 1, **meetings.clean(self.body(repeat="weekly", until="2026-11-02"),
                                         people=["Dina"], today=TODAY)}
        days = [m["start"].date().isoformat() for m in meetings.occurrences(
            [row], dt.date(2026, 10, 15), dt.date(2026, 12, 31))]
        assert days == ["2026-10-19", "2026-10-26", "2026-11-02"]

    def test_in_the_plan_once_with_outlook(self):
        at = lambda h, m=0: dt.datetime.combine(MONDAY, dt.time(h, m))   # noqa: E731
        plan = management.Plan(roster(("Dina", "engineer")), [], CONFIG, today=MONDAY,
                               outlook={"Dina": [(at(11), at(12))]},
                               typed=[{"id": 1, "title": "Design review", "kind": "client",
                                       "people": ["Dina"], "start": at(10), "end": at(11, 30)}])
        blocks = plan.day_blocks(MONDAY)[2]
        assert [(b["kind"], b["start"], b["end"]) for b in blocks] == [
            ("typed", at(10), at(11, 30)), ("outlook", at(11, 30), at(12))]

    @pytest.fixture
    def unit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKLOAD_TODAY", TODAY.isoformat())
        service = WorkloadService(storage.new_unit(tmp_path, 1, "unit-one"))
        service.import_exports([
            export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
            export("dina", booking("Dina Ashgrove", "N2-0100D", 4)),
        ])
        return service

    def test_on_the_day_with_its_title(self, unit):
        made = unit.add_meeting(self.body(day=TODAY.isoformat(), people=["Dina", "Amal"],
                                          kind="trade", title="MEP coordination"))
        day = unit.day_plan({})["days"][0]
        for name in ("Dina", "Amal"):
            person = next(p for p in day["people"] if p["name"] == name)
            block = next(b for b in person["blocks"] if b.get("source") == "typed")
            assert (block["start"], block["end"]) == ("10:00", "11:30")
            assert block["title"] == "Meeting with another trade: MEP coordination"
        assert unit.meetings()["meetings"][0]["people"] == ["Dina", "Amal"]
        unit.remove_meeting(made["id"])
        assert unit.meetings()["meetings"] == []

    def test_renaming_a_person_follows_into_their_meetings(self, unit):
        unit.add_meeting(self.body(day=TODAY.isoformat()))
        unit.store.rename_person_everywhere("Dina", "Dina A")
        assert unit.store.meetings()[0]["people"] == ["Dina A"]


class TestMeetingRoutes:
    BODY = {"title": "Client review", "kind": "client", "start": "10:00",
            "end": "11:00"}

    def day(self):
        return (dt.date.today() + dt.timedelta(days=1)).isoformat()

    def test_a_member_puts_in_only_their_own(self, site, osama):
        status, made = call(osama, "/api/me/meetings", "POST",
                            {**self.BODY, "day": self.day(), "people": ["Kirolos"]})
        assert status == 200, made
        assert made["people"] == ["Osama"]
        _s, mine = call(osama, "/api/me/meetings")
        assert [m["id"] for m in mine["meetings"]] == [made["id"]]

    def test_a_member_cannot_take_off_the_managers(self, site, osama):
        status, made = call(site, "/api/meetings", "POST",
                            {**self.BODY, "day": self.day(), "people": ["Osama", "Kirolos"]})
        assert status == 200, made
        _s, mine = call(osama, "/api/me/meetings")
        assert [m["id"] for m in mine["meetings"]] == [made["id"]]
        status, _ = call(osama, f"/api/me/meetings/{made['id']}/remove", "POST")
        assert status == 404
        status, _ = call(osama, "/api/meetings", "POST",
                         {**self.BODY, "day": self.day(), "people": ["Kirolos"]})
        assert status == 403
        status, _ = call(site, f"/api/meetings/{made['id']}/remove", "POST")
        assert status == 200
