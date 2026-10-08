"""Emails in: draft tasks for the senior, and the ones that need nothing."""

import datetime as _dt

import pytest

from workload_app import emails

TODAY = _dt.date(2026, 10, 8)        # a Thursday


def email(subject="", text="", sender="Sam Client <sam@client.example>", **more):
    return emails.clean({"subject": subject, "body": text, "from": sender, **more})


class TestNeedsNothing:
    @pytest.mark.parametrize("subject,text,sender", [
        ("Automatic reply: Pile caps", "I am out of the office until Monday.", "a@b.example"),
        ("Accepted: Design review", "", "a@b.example"),
        ("Undeliverable: Drawings", "Delivery has failed.", "postmaster@b.example"),
        ("Your weekly digest", "Read more. Unsubscribe here.", "news@b.example"),
        ("Password expiry", "Your password expires soon. Please change it.",
         "no-reply@b.example"),
        ("RE: Quay wall", "Thanks, well received.", "a@b.example"),
        ("FYI: minutes of meeting", "Attached are the minutes for your records.",
         "a@b.example"),
    ])
    def test_is_no_action(self, subject, text, sender):
        assert emails.judge(email(subject, text, sender)) is not None

    def test_only_copied_in_and_asking_nothing(self):
        mail = email("Site photos", "Photos from today's visit attached.",
                     to="lee@x.example", cc="me@dar.example; other@x.example",
                     me="me@dar.example")
        assert "copied" in emails.judge(mail)

    def test_copied_in_but_asked_is_a_draft(self):
        mail = email("Site photos", "Please check the crack in photo 3.",
                     to="lee@x.example", cc="me@dar.example", me="me@dar.example")
        assert emails.judge(mail) is None

    def test_a_quiet_sender(self):
        mail = email("Update", "Please review.", "Bulk <bulk@x.example>")
        assert emails.judge(mail, quiet=["bulk@x.example"]) is not None

    @pytest.mark.parametrize("subject,text", [
        ("Comments on the jetty drawings", "Could you review the attached by Sunday?"),
        ("RFI 12 - fender loads", "Please confirm the berthing energy."),
        ("Quick question", "Is the deck level +4.5?"),
        ("FYI: revised loads", "Please update the model with these urgently."),
    ])
    def test_is_a_draft(self, subject, text):
        assert emails.judge(email(subject, text)) is None


class TestGuesses:
    PROJECTS = {"T10001-0100D": "Northern Quay", "T10004-0100D": "T10004-0100D"}

    def test_project_by_number_with_spaces(self):
        assert emails.guess_project("Ref T10004 - 0100D comments", self.PROJECTS) \
            == "T10004-0100D"

    def test_project_by_job_alone(self):
        assert emails.guess_project("About T10001 fenders", self.PROJECTS) == "T10001-0100D"
        assert emails.guess_project("About T100012", self.PROJECTS) == ""

    def test_project_by_name(self):
        assert emails.guess_project("Northern Quay fenders", self.PROJECTS) == "T10001-0100D"

    def test_no_project(self):
        assert emails.guess_project("Lunch on Friday", self.PROJECTS) == ""

    @pytest.mark.parametrize("words,due", [
        ("needed today please", TODAY),
        ("ASAP", TODAY),
        ("by tomorrow", _dt.date(2026, 10, 9)),
        ("by Sunday", _dt.date(2026, 10, 11)),
        ("by Thursday", _dt.date(2026, 10, 15)),
        ("before 14 Oct", _dt.date(2026, 10, 14)),
        ("due October 20th", _dt.date(2026, 10, 20)),
        ("by 3 January", _dt.date(2027, 1, 3)),
        ("whenever you can", None),
    ])
    def test_due(self, words, due):
        assert emails.guess_due(words, TODAY) == due

    def test_high_importance_is_today(self):
        assert emails.guess_due("no date", TODAY, importance="high") == TODAY

    def test_hours_and_role(self):
        assert emails.guess_hours("please review the report") == 4.0
        assert emails.guess_hours("please check the RFI") == 2.0
        assert emails.guess_hours("call me") == 1.0
        assert emails.guess_role("update the CAD sheets") == "drafting"
        assert emails.guess_role("review the client's markups") == "engineering"
        assert emails.guess_role("check the pile loads") == "engineering"

    def test_title_drops_re_and_fw(self):
        assert emails.title_of({"subject": "RE: FW: Re: Pile caps"}) == "Pile caps"
        assert emails.topic("RE: FW: Pile  caps") == emails.topic("pile caps")


class TestReading:
    def test_html_body_becomes_text(self):
        mail = email("Hi", "<html><style>p{}</style><p>Please&nbsp;check</p><br>the deck</html>")
        assert mail["text"] == "Please check\n\nthe deck"

    def test_outlook_from_object(self):
        mail = emails.clean({"subject": "x", "body": "y",
                             "from": {"emailAddress": {"address": "a@b.example"}}})
        assert mail["sender"] == "a@b.example"

    def test_the_same_email_twice_has_the_same_key(self):
        assert email("x", "y")["message_key"] == email("x", "y")["message_key"]

    def test_a_paste_from_a_pc_keeps_its_headers(self):
        found = emails.from_paste("From: Sam <sam@client.example>\nSent: Thursday\n"
                                  "Subject: Fender loads\n\nPlease confirm the loads.")
        assert found["subject"] == "Fender loads"
        assert found["from"] == "Sam <sam@client.example>"
        assert found["body"] == "Please confirm the loads."

    def test_a_paste_from_a_phone_is_its_first_line(self):
        found = emails.from_paste("Please confirm the loads by Sunday.\nThanks")
        assert found["subject"] == "Please confirm the loads by Sunday."

    def test_too_large_is_refused(self):
        with pytest.raises(emails.EmailError):
            emails.clean({"subject": "x", "body": "y" * (emails.LARGEST_EMAIL + 1)})

    def test_empty_is_refused(self):
        with pytest.raises(emails.EmailError):
            emails.clean({"subject": "", "body": ""})


# -- through the app ---------------------------------------------------------

pytest.importorskip("openpyxl")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from test_server import _account, _serve
    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "instance"))
    monkeypatch.setenv("WORKLOAD_TODAY", "2026-10-08")
    httpd = _serve(tmp_path / "instance")
    try:
        yield _account(httpd, f"http://127.0.0.1:{httpd.server_address[1]}")
    finally:
        httpd.app.close_all()
        httpd.shutdown()
        httpd.server_close()


def call(*args, **kwargs):
    from test_server import call as server_call
    return server_call(*args, **kwargs)


def anonymous(client):
    return type(client)(str(client))


def ready(client):
    from test_from_timesheets import team_exports
    status, body = call(client, "/api/units/from-timesheets", "POST",
                        {"files": team_exports()})
    assert status == 200, body
    status, body = call(client, "/api/inbox-key", "POST", {})
    assert status == 200, body
    assert '"subject": "@{triggerOutputs()' in body["flow_body"]
    return body["key_value"]


def send(client, key, **mail):
    return call(anonymous(client), "/api/inbox/email", "POST", {"key": key, **mail})


class TestThroughTheApp:
    def test_an_email_becomes_a_draft_and_then_a_request(self, client):
        key = ready(client)
        status, body = send(client, key, id="<m1@x>", subject="Comments on T10003-0100D",
                            preview="Please review the attached by tomorrow.",
                            **{"from": "Sam <sam@client.example>"})
        assert status == 200, body
        assert body["status"] == "draft"
        _status, inbox = call(client, "/api/inbox")
        draft = inbox["drafts"][0]
        assert draft["guess"]["project_number"] == "T10003-0100D"
        assert draft["guess"]["due"] == "2026-10-09"
        assert inbox["key"]["last_result"]["ok"] is True
        status, result = call(client, f"/api/inbox/{draft['id']}/assign", "POST", {
            **draft["guess"], "person": "Osama", "now": "2026-10-08T09:00"})
        assert status == 200, result
        assert result["person"] == "Osama"
        assert "sam@client.example" in result["task"]["definition"]
        _status, inbox = call(client, "/api/inbox")
        assert not inbox["drafts"]
        assert inbox["assigned"][0]["task_id"] == result["task"]["id"]
        _status, day = call(client, "/api/day")
        assert any(r["id"] == result["task"]["id"] for r in day["requests"])
        # A reply while it is with Osama needs no second task.
        _status, body = send(client, key, id="<m2@x>", subject="RE: Comments on T10003-0100D",
                             preview="Any news? Please send today.")
        assert body["status"] == "no_action"
        _status, inbox = call(client, "/api/inbox")
        assert "Already a task" in inbox["no_action"][0]["reason"]

    def test_no_action_emails_stay_out_and_can_come_back(self, client):
        key = ready(client)
        _status, body = send(client, key, id="<m1@x>", subject="Automatic reply: Deck",
                             preview="I am away.")
        assert body["status"] == "no_action"
        _status, inbox = call(client, "/api/inbox")
        assert not inbox["drafts"]
        item = inbox["no_action"][0]
        _status, inbox = call(client, f"/api/inbox/{item['id']}/status", "POST",
                              {"status": "draft"})
        assert inbox["drafts"][0]["id"] == item["id"]
        _status, inbox = call(client, f"/api/inbox/{item['id']}/status", "POST",
                              {"status": "dismissed"})
        assert not inbox["drafts"] and inbox["dismissed"]

    def test_the_same_email_twice_and_replies_join(self, client):
        key = ready(client)
        send(client, key, id="<m1@x>", subject="Pile caps", preview="Please check.")
        _status, again = send(client, key, id="<m1@x>", subject="Pile caps",
                              preview="Please check.")
        assert again["status"] == "already"
        _status, reply = send(client, key, id="<m2@x>", subject="RE: Pile caps",
                              preview="Also the cover, please.")
        assert reply["status"] == "draft"
        _status, inbox = call(client, "/api/inbox")
        assert len(inbox["drafts"]) == 1
        assert inbox["drafts"][0]["replies"] == 1
        assert "cover" in inbox["drafts"][0]["snippet"]

    def test_quiet_senders_and_own_address(self, client):
        key = ready(client)
        send(client, key, id="<m1@x>", subject="Report", preview="Please read.",
             **{"from": "bulk@x.example"})
        status, inbox = call(client, "/api/inbox/settings", "POST",
                             {"quiet_add": ["Bulk <bulk@x.example>"], "me": "me@dar.example"})
        assert status == 200, inbox
        assert inbox["quiet"] == ["bulk@x.example"] and inbox["me"] == "me@dar.example"
        assert not inbox["drafts"]
        _status, body = send(client, key, id="<m2@x>", subject="Again", preview="Please.",
                             **{"from": "bulk@x.example"})
        assert body["status"] == "no_action"
        _status, body = send(client, key, id="<m3@x>", subject="Photos", preview="Attached.",
                             to="a@x.example", cc="me@dar.example")
        assert body["status"] == "no_action"

    def test_a_pasted_email_is_always_a_draft(self, client):
        ready(client)
        status, body = call(client, "/api/inbox/paste", "POST",
                            {"text": "Thanks\nSee you"})
        assert status == 200, body
        assert body["status"] == "draft" and body["drafts"]

    def test_a_wrong_or_stopped_key_is_refused(self, client):
        key = ready(client)
        assert send(client, "selmail_nope", subject="x", preview="y")[0] == 401
        assert call(client, "/api/inbox-key", "DELETE")[1]["revoked"] is True
        assert send(client, key, subject="x", preview="y")[0] == 401

    def test_drafts_are_the_seniors_own(self, client):
        key = ready(client)
        send(client, key, id="<m1@x>", subject="Pile caps", preview="Please check.")
        service = client.app.service_for(client.user["id"])
        assert service.inbox(client.user["id"] + 1)["drafts"] == []
        assert len(service.inbox(client.user["id"])["drafts"]) == 1
