"""The weekly report, and notifications on the manager's phone.

The report is put together from what Check-ins, the forecast and the
submissions plan work out; the notifications are sealed for one phone and sent
once each.  The crypto is plain Python (nothing may be installed on the host),
so every piece is checked here against a real crypto library.  Made-up
timesheets; no private workbook.
"""

import base64
import datetime as dt
import json
import os
import urllib.error

import pytest

from workload_app import admin, notify, webpush, weekly

from test_across import SITE, app, ask, unit  # noqa: F401  (fixtures)
from test_checkins import TODAY, booking, export

crypto = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: E402


# --------------------------------------------------------------------------
# a phone, as far as the push protocol goes
# --------------------------------------------------------------------------

class Phone:
    """Keys like a browser's, and the means to open what is sent to it."""

    def __init__(self, endpoint="https://push.example.com/send/abc123"):
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.auth = os.urandom(16)
        self.endpoint = endpoint

    def subscription(self):
        return {"endpoint": self.endpoint,
                "keys": {"p256dh": webpush.b64url(self.public),
                         "auth": webpush.b64url(self.auth)}}

    def open(self, body: bytes) -> dict:
        """RFC 8291 from the receiving end."""
        salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        server_public = body[21:21 + idlen]
        sealed = body[21 + idlen:]
        assert rs == webpush.RECORD_SIZE
        shared = self.private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), server_public))
        ikm = HKDF(hashes.SHA256(), 32, self.auth,
                   b"WebPush: info\x00" + self.public + server_public).derive(shared)
        cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
        nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
        plain = AESGCM(cek).decrypt(nonce, sealed, None)
        assert plain.endswith(b"\x02")
        return json.loads(plain[:-1])


class Service:
    """Stands in for the push services: records what reached each phone."""

    def __init__(self, phones, fail=None):
        self.phones = {p.endpoint: p for p in phones}
        self.got = []
        self.fail = fail or {}

    def __call__(self, keys, device, message, *, contact):
        if device["endpoint"] in self.fail:
            raise self.fail[device["endpoint"]]
        body = webpush.encrypt(json.dumps(message).encode(), device["p256dh"], device["auth"])
        opened = self.phones[device["endpoint"]].open(body)
        self.got.append((device["endpoint"], opened, contact,
                         keys.authorization(device["endpoint"], contact)))
        return 201


# --------------------------------------------------------------------------
# the crypto, against a real library
# --------------------------------------------------------------------------

class TestCrypto:
    @pytest.mark.parametrize("size", [0, 1, 15, 16, 17, 64, 300, 1000])
    def test_aes_gcm_matches(self, size):
        key, nonce, data = os.urandom(16), os.urandom(12), os.urandom(size)
        assert webpush.aes128gcm_encrypt(key, nonce, data) == AESGCM(key).encrypt(nonce, data, None)

    def test_public_key_matches(self):
        private = webpush.new_private()
        theirs = ec.derive_private_key(private, ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        assert webpush.public_bytes(private) == theirs

    def test_signature_verifies(self):
        private = webpush.new_private()
        public = ec.derive_private_key(private, ec.SECP256R1()).public_key()
        for message in (b"", b"hello", os.urandom(200)):
            sig = webpush.sign(private, message)
            public.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"),
                                               int.from_bytes(sig[32:], "big")),
                          message, ec.ECDSA(hashes.SHA256()))

    def test_ecdh_matches(self):
        mine = webpush.new_private()
        theirs = ec.generate_private_key(ec.SECP256R1())
        their_public = theirs.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        expected = theirs.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), webpush.public_bytes(mine)))
        assert webpush.ecdh(mine, their_public) == expected

    def test_a_key_off_the_curve_is_refused(self):
        bad = b"\x04" + (1).to_bytes(32, "big") + (1).to_bytes(32, "big")
        with pytest.raises(ValueError):
            webpush.ecdh(webpush.new_private(), bad)

    def test_a_phone_opens_what_is_sealed_for_it(self):
        phone = Phone()
        sub = phone.subscription()["keys"]
        body = webpush.encrypt(b'{"title": "Hi"}', sub["p256dh"], sub["auth"])
        assert phone.open(body) == {"title": "Hi"}

    def test_vapid_token(self, tmp_path):
        keys = webpush.Keys(tmp_path / "push.key")
        header = keys.authorization("https://web.push.apple.com/abc", "https://example.com")
        token = header.split("t=")[1].split(",")[0]
        k = header.split("k=")[1]
        head, claims, sig = token.split(".")
        claims = json.loads(webpush.unb64url(claims))
        assert claims["aud"] == "https://web.push.apple.com"
        assert claims["sub"] == "https://example.com"
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.unb64url(k))
        raw = webpush.unb64url(sig)
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                           int.from_bytes(raw[32:], "big")),
                      token.rsplit(".", 1)[0].encode(), ec.ECDSA(hashes.SHA256()))
        # The key is made once and kept.
        assert webpush.Keys(tmp_path / "push.key").public == keys.public
        assert oct((tmp_path / "push.key").stat().st_mode & 0o777) == "0o600"

    def test_send_posts_a_sealed_message(self, tmp_path):
        phone = Phone()
        seen = {}

        class Answer:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(request, timeout):
            seen["request"] = request
            return Answer()

        device = {"endpoint": phone.endpoint, **{k: v for k, v in phone.subscription()["keys"].items()}}
        status = webpush.send(webpush.Keys(tmp_path / "k"), device, {"title": "Due"},
                              contact="https://example.com", opener=opener)
        request = seen["request"]
        assert status == 201
        assert request.get_header("Content-encoding") == "aes128gcm"
        assert request.get_header("Ttl")
        assert request.get_header("Authorization").startswith("vapid t=")
        assert phone.open(request.data) == {"title": "Due"}

    def test_a_gone_phone_says_so(self, tmp_path):
        phone = Phone()

        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 410, "Gone", {}, None)

        device = {"endpoint": phone.endpoint, **phone.subscription()["keys"]}
        with pytest.raises(webpush.Gone):
            webpush.send(webpush.Keys(tmp_path / "k"), device, {"title": "x"},
                         contact="https://example.com", opener=opener)


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

def team(app):  # noqa: F811
    unit(app, "Marine Structures", [
        export("amal", booking("Amal Ashdown", "N1-0100D", 6)),
        export("bassem", booking("Bassem Northwind", "N1-0100D", 11, overtime=2.5)),
        export("dina", booking("Dina Ashgrove", "N1-0200D", 3))])


class TestReport:
    def test_report_from_existing_data(self, app):  # noqa: F811
        team(app)
        status, report = ask("GET", "/api/weekly")
        assert status == 200, report
        assert report["unit"] == "Marine Structures"
        assert report["week_start"] <= TODAY.isoformat() <= report["week_end"]
        last = report["last_week"]
        assert {p["name"] for p in last["people"]} == {"Amal", "Bassem", "Dina"}
        assert last["hours"] == round(sum(p["hours"] for p in last["people"]), 1)
        assert last["projects"][0]["number"] == "N1-0100D"
        # Bassem has done 11-hour days for six weeks: first thing on the list.
        assert any("Bassem a lighter week" in t["text"] for t in report["todo"])
        assert any(r["name"] == "Dina" for r in report["this_week"]["room"])
        assert report["headline"]

    def test_download_is_a_page(self, app):  # noqa: F811
        team(app)
        status, result = ask("GET", "/api/weekly/download")
        assert status == 200
        page = base64.b64decode(result["content_base64"]).decode()
        assert result["filename"].endswith(".html")
        assert page.startswith("<!doctype html>") and "Bassem" in page
        assert "<script" not in page

    def test_names_are_escaped(self):
        report = {"unit": "<b>x</b>", "title": "Week", "made": "2026-10-07", "through": None,
                  "headline": "h", "todo": [{"tone": "bad", "view": "x", "text": "<i>"}],
                  "more": 0, "last_week": {"week": None}, "this_week": {
                      "due": [], "ease_off": [], "heavy": [], "room": [], "meetings": 0},
                  "staffing": [], "unstaffed": [], "drawings": None}
        page = weekly.as_html(report)
        assert "<b>x</b>" not in page and "&lt;i&gt;" in page

    def test_late_submissions_collapse_into_one_line(self):
        items = [{"row": i, "name": f"Sub {i}", "project_number": "P", "basis": "overdue",
                  "register_date": "2026-09-01", "date": TODAY.isoformat()} for i in range(5)]
        report = weekly.build(unit_name="U", today=TODAY, config={"work_days": [0, 1, 2, 3, 4]},
                              checkins={"people": [], "weeks": []}, needs={},
                              submissions={"items": items}, rows=[])
        late = [t for t in report["todo"] if "late" in t["text"]]
        assert len(late) == 1 and "5 late submissions" in late[0]["text"]
        assert len(report["this_week"]["due"]) == 5


# --------------------------------------------------------------------------
# notifications
# --------------------------------------------------------------------------

class TestNotifications:
    def subscribe(self, phone, site="https://ahm.example.com"):
        return ask("POST", "/api/push/devices", {**phone.subscription(),
                                                 "label": "iPhone", "site": site})

    def test_turning_on_and_off(self, app):  # noqa: F811
        team(app)
        phone = Phone()
        status, made = self.subscribe(phone)
        assert status == 200, made
        assert "endpoint" not in made["device"] and "auth" not in made["device"]
        status, view = ask("GET", "/api/push")
        assert view["public_key"] == notify.keys_for(app.data_dir).public
        assert len(view["devices"]) == 1 and "endpoint" not in view["devices"][0]
        assert view["devices"][0]["fingerprint"]
        assert "notify" in view["task"] and str(app.data_dir.resolve()) in view["task"]
        # The same phone again is the same phone, not a second one.
        self.subscribe(phone)
        assert len(ask("GET", "/api/push")[1]["devices"]) == 1
        device = view["devices"][0]["id"]
        assert ask("DELETE", f"/api/push/devices/{device}")[1] == {"removed": True}
        assert ask("GET", "/api/push")[1]["devices"] == []

    def test_bad_subscriptions_are_refused(self, app):  # noqa: F811
        phone = Phone()
        sub = phone.subscription()
        assert ask("POST", "/api/push/devices", {**sub, "endpoint": "http://x"})[0] == 400
        assert ask("POST", "/api/push/devices", {**sub, "keys": {
            "p256dh": webpush.b64url(b"\x04" + bytes(64)), "auth": sub["keys"]["auth"]}})[0] == 400
        assert ask("POST", "/api/push/devices", {**sub, "keys": {
            "p256dh": sub["keys"]["p256dh"], "auth": "AAAA"}})[0] == 400

    def test_one_notification_for_everything_new_then_nothing_twice(self, app):  # noqa: F811
        team(app)
        phone = Phone()
        self.subscribe(phone)
        service = Service([phone])
        first = notify.run(app, sender=service)
        assert first["sent"] == 1 and first["new"] >= 2
        endpoint, message, contact, auth = service.got[0]
        assert contact == "https://ahm.example.com"
        assert message["title"].endswith("things need you")
        assert "Weekly report is ready" in message["body"]
        assert "Bassem needs to ease off" in message["body"]
        # Nothing new: nothing sent.
        again = notify.run(app, sender=service)
        assert again["new"] == 0 and len(service.got) == 1
        listed = ask("GET", "/api/push")[1]["messages"]
        assert {m["title"] for m in listed} >= {"Weekly report is ready", "Bassem needs to ease off"}

    def test_only_one_thing_reads_as_itself(self):
        one = notify.summary([{"key": "k", "title": "Due tomorrow: X", "body": "P1",
                               "url": "./#planner"}])
        assert one == {"title": "Due tomorrow: X", "body": "P1", "url": "./#planner", "tag": "k"}

    def test_test_button_and_gone_phone(self, app):  # noqa: F811
        team(app)
        assert ask("POST", "/api/push/test")[0] == 409
        phone = Phone()
        self.subscribe(phone)
        service = Service([phone], fail={phone.endpoint: webpush.Gone(phone.endpoint)})
        results = notify.test(app, app.accounts.users()[0]["id"], sender=service)
        assert results[0]["gone"] and app.accounts.push_devices() == []

    def test_a_failing_phone_is_counted_then_given_up(self, app):  # noqa: F811
        team(app)
        phone = Phone()
        self.subscribe(phone)
        user = app.accounts.users()[0]["id"]
        error = urllib.error.URLError("no route")
        service = Service([phone], fail={phone.endpoint: error})
        for _ in range(notify.GIVE_UP_AFTER - 1):
            notify.test(app, user, sender=service)
        devices = app.accounts.push_devices(user)
        assert devices[0]["failures"] == notify.GIVE_UP_AFTER - 1
        assert "no route" in devices[0]["last_error"]
        notify.test(app, user, sender=service)
        assert app.accounts.push_devices(user) == []

    def test_several_units_say_which(self, app):  # noqa: F811
        team(app)
        unit(app, "Geotechnics", [export("dina", booking("Dina Ashgrove", "G1-0200D", 3))])
        phone = Phone()
        self.subscribe(phone)
        service = Service([phone])
        notify.run(app, sender=service)
        body = service.got[0][1]["body"] + "".join(
            m["title"] for m in ask("GET", "/api/push")[1]["messages"])
        assert "Geotechnics: Weekly report is ready" in body
        assert "Marine Structures: Weekly report is ready" in body

    def test_admin_command(self, app, monkeypatch, capsys):  # noqa: F811
        team(app)
        phone = Phone()
        self.subscribe(phone)
        service = Service([phone])
        monkeypatch.setattr(webpush, "send", service)
        assert admin.main(["--data-dir", str(app.data_dir), "notify"]) == 0
        assert "sent to 1 phone" in capsys.readouterr().out
        assert len(service.got) == 1

    def test_due_tomorrow_and_late(self):
        report = {"week_start": "2026-10-04", "headline": "h", "stale": False,
                  "staffing": [{"title": "T: ask for 2 more engineers", "detail": "d",
                                "severity": "now", "team_id": "t", "role": "engineering",
                                "people": 2}],
                  "this_week": {"due": [
                      {"row": 1, "name": "Deck GA", "project": "P1", "date": "2026-10-08",
                       "people": ["Amal"], "progress": 0.5, "late": False, "was_due": None},
                      {"row": 2, "name": "Piles", "project": "P2", "date": "2026-10-07",
                       "people": [], "progress": None, "late": True, "was_due": "2026-09-30"}]}}
        found = notify.alerts(report, {"people": [], "days": ["2026-10-07", "2026-10-08"]},
                              today=dt.date(2026, 10, 7))
        keys = {f["key"] for f in found}
        assert {"weekly:2026-10-04", "due:1:2026-10-08", "late:2:2026-09-30",
                "need:t:engineering:2"} <= keys
        due = next(f for f in found if f["key"].startswith("due:"))
        assert due["title"] == "Due tomorrow: Deck GA" and "50% done" in due["body"]


# --------------------------------------------------------------------------
# the team's own phones
# --------------------------------------------------------------------------

class TestTeamPhones:
    def member(self, app, username, engineer):  # noqa: F811
        from workload_app.accounts import ROLE_MEMBER
        unit_id = app.accounts.units(app.accounts.users()[0]["id"])[0]["id"]
        user = app.accounts.create_user(username, "a long password 123", role=ROLE_MEMBER)
        app.accounts.grant(user_id=user["id"], unit_id=unit_id, engineer=engineer)
        phone = Phone(f"https://fcm.googleapis.com/fcm/send/{username}")
        keys = phone.subscription()["keys"]
        app.accounts.add_push_device(user["id"], endpoint=phone.endpoint, auth=keys["auth"],
                                     p256dh=keys["p256dh"], label="Android phone, Chrome")
        return user, phone

    def test_a_team_lead_hears_about_their_team(self, app):  # noqa: F811
        team(app)
        ask("PUT", "/api/people/Amal", {"grade": "manager"})
        amal, amal_phone = self.member(app, "amal", "Amal")
        dina, dina_phone = self.member(app, "dina", "Dina")
        service = Service([amal_phone, dina_phone])
        result = notify.run(app, sender=service)
        assert result["sent"] == 2, result
        got = {endpoint: message for endpoint, message, *_ in service.got}
        lead = got[amal_phone.endpoint]
        assert "Your week and your team's" in lead["body"]
        assert lead["url"] == "./"          # their own page; they have no Weekly tab
        titles = {m["title"] for m in app.accounts.push_messages(amal["id"])}
        assert "Bassem needs to ease off" in titles
        assert "Your week and your team's" in titles
        # Dina leads nobody: her own week, and nobody else's name.
        mine = app.accounts.push_messages(dina["id"])
        assert [m["title"] for m in mine] == ["Your week"]
        assert "Bassem" not in json.dumps(mine) and "Amal" not in json.dumps(mine)
        # Nothing twice.
        assert notify.run(app, sender=service)["new"] == 0

    def test_a_member_turns_it_on_from_their_page(self, app, monkeypatch):  # noqa: F811
        team(app)
        from workload_app.accounts import ROLE_MEMBER
        me = ask("GET", "/api/auth/me")[1]["user"]["id"]
        app.accounts.set_role(me, ROLE_MEMBER)
        monkeypatch.setattr(app.accounts, "set_role", lambda *a, **k: None)
        status, view = ask("GET", "/api/push")
        assert status == 200
        assert view["task"] is None and "your week" in view["about"]
        phone = Phone()
        status, _ = ask("POST", "/api/push/devices", phone.subscription())
        assert status == 200
        assert ask("GET", "/api/weekly")[0] == 403

    def test_a_nightly_import_tells_the_team_too(self, app):  # noqa: F811
        team(app)
        amal, phone = self.member(app, "amal", "Amal")
        owner = app.accounts.users()[0]["id"]
        unit_id = app.accounts.units(owner)[0]["id"]
        assert amal["id"] in notify.people_of_unit(app, owner, unit_id)


# --------------------------------------------------------------------------
# told when something changes, not only at the scheduled run
# --------------------------------------------------------------------------

class TestToldOnChange:
    def test_a_managers_change_reaches_the_phone_at_once(self, app, monkeypatch):  # noqa: F811
        team(app)
        phone = Phone()
        ask("POST", "/api/push/devices", phone.subscription())
        service = Service([phone])
        monkeypatch.setattr(webpush, "send", service)
        app.tell_in_background = False
        notify.run(app)                           # what is there already
        seen = len(service.got)
        # A new task due tomorrow for Amal: a write to the unit.
        status, _ = ask("POST", "/api/tasks", {
            "name": "Check deck GA", "assignees": ["Amal"],
            "due": "2026-10-08", "hours": 4})
        assert status == 200
        status, _ = ask("GET", "/api/weekly")      # a read tells nobody
        assert len(service.got) >= seen

    def test_reads_and_no_phones_do_nothing(self, app, monkeypatch):  # noqa: F811
        team(app)
        calls = []
        monkeypatch.setattr(notify, "run", lambda *a, **k: calls.append(k) or {})
        app.tell_in_background = False
        ask("POST", "/api/tasks", {"name": "X", "assignees": ["Amal"], "due": "2026-10-09"})
        assert calls == []                        # nobody has a phone on
        ask("POST", "/api/push/devices", Phone().subscription())
        ask("GET", "/api/weekly")
        assert calls == []                        # a read is not a change
        ask("POST", "/api/tasks", {"name": "Y", "assignees": ["Amal"], "due": "2026-10-09"})
        assert len(calls) == 1 and calls[0]["unit_ids"]

    def test_under_wsgi_it_waits_for_the_response_to_go(self, app, monkeypatch):  # noqa: F811
        from workload_app import wsgi
        team(app)
        ask("POST", "/api/push/devices", Phone().subscription())
        calls = []
        monkeypatch.setattr(notify, "run", lambda *a, **k: calls.append(k) or {})
        app.tell_in_background = True
        raw = json.dumps({"name": "Z", "assignees": ["Amal"], "due": "2026-10-09"}).encode()
        import io
        environ = {"REQUEST_METHOD": "POST", "SCRIPT_NAME": "/workload", "PATH_INFO": "/api/tasks",
                   "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
                   "CONTENT_TYPE": "application/json", "wsgi.input": io.BytesIO(raw),
                   "wsgi.url_scheme": "https", wsgi.SITE_KEY: SITE}
        body = wsgi.application(environ, lambda s, h: None)
        b"".join(body)
        assert calls == []                        # not while answering
        body.close()                              # the server is done sending
        assert len(calls) == 1
