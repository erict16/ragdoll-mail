"""Offline tests of meeting invitations: reading them (time zones, all-day, repeats, replies, charsets)."""
import calendar, datetime as dt, os, sys, time, unittest
from email.message import EmailMessage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402

OUTLOOK_TZ = "(UTC+01:00) Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna"
VTZ_BERLIN = ('BEGIN:VTIMEZONE\r\nTZID:%s\r\nBEGIN:STANDARD\r\nDTSTART:16010101T030000\r\nTZOFFSETFROM:+0200\r\n'
              'TZOFFSETTO:+0100\r\nRRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10\r\nEND:STANDARD\r\n'
              'BEGIN:DAYLIGHT\r\nDTSTART:16010101T020000\r\nTZOFFSETFROM:+0100\r\nTZOFFSETTO:+0200\r\n'
              'RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n')


def _has_tz():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Berlin")
        return True
    except Exception:       # noqa: BLE001
        return False


HAS_TZ = _has_tz()


def utc(*a):
    return calendar.timegm(dt.datetime(*a).timetuple())


def cal(event, method="REQUEST", zones=""):
    return ("BEGIN:VCALENDAR\r\nPRODID:-//Microsoft Corporation//Outlook 16.0 MIMEDIR//EN\r\nVERSION:2.0\r\n"
            + ("METHOD:%s\r\n" % method if method else "") + zones + "BEGIN:VEVENT\r\n" + event
            + "END:VEVENT\r\nEND:VCALENDAR\r\n")


def mail(ics, charset="utf-8", as_file=False, method="REQUEST", data=None):
    m = EmailMessage()
    m["From"] = "Gerrick Ong <gerrick@contoso.com>"
    m["To"] = "you@example.com"
    m["Subject"] = "Invitation"
    m["Message-ID"] = "<inv-1@contoso.com>"
    m.set_content("See the invitation.")
    raw = data if data is not None else ics.encode(charset)
    if as_file:
        m.add_attachment(raw, "application", "octet-stream", filename="invite.ics")
    else:
        m.add_alternative(raw, "text", "calendar", params={"method": method, "charset": charset}, cte="base64")
    return A.R.to_msg(m.as_bytes())


EVENT = ("UID:040000008200E00074C5B7101A82E008\r\nSEQUENCE:0\r\nDTSTAMP:20261120T080000Z\r\n"
         'DTSTART;TZID="%s":20261124T100000\r\nDTEND;TZID="%s":20261124T110000\r\n'
         "SUMMARY;LANGUAGE=en-US:Supplier sync\r\nLOCATION:Room 4\\, Plant 2\r\n"
         'ORGANIZER;CN="Ong, Gerrick":mailto:gerrick@contoso.com\r\n'
         'ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE;CN="Alex Morgan":mailto:you@example.com\r\n'
         'ATTENDEE;ROLE=OPT-PARTICIPANT;PARTSTAT=ACCEPTED;CN=Li Ming:mailto:li.ming@example.cn\r\n'
         'ATTENDEE;CUTYPE=ROOM;PARTSTAT=ACCEPTED;CN="Room 4":mailto:room4@contoso.com\r\n')


class TimeZones(unittest.TestCase):
    def test_outlook_display_name_with_its_vtimezone(self):
        """The bug in #69: 10:00 in Berlin is 17:00 in Shanghai, not 10:00."""
        v = A.invite_of(mail(cal(EVENT % (OUTLOOK_TZ, OUTLOOK_TZ), zones=VTZ_BERLIN % OUTLOOK_TZ)))
        self.assertEqual(v["start"], utc(2026, 11, 24, 9, 0))
        self.assertEqual(v["end"] - v["start"], 3600)
        self.assertEqual(v["zone"]["offset"], 3600)
        self.assertEqual(v["zone"]["label"], "Amsterdam")
        self.assertEqual((v["title"], v["where"], v["organizer"]), ("Supplier sync", "Room 4, Plant 2", "Ong, Gerrick"))

    @unittest.skipUnless(HAS_TZ, "no time zone database here (Windows without tzdata)")
    def test_display_name_alone(self):
        for tzid, want in ((OUTLOOK_TZ, utc(2026, 11, 24, 9)), ("W. Europe Standard Time", utc(2026, 11, 24, 9)),
                           ("Europe/Berlin", utc(2026, 11, 24, 9)),
                           ("(UTC+08:00) Beijing, Chongqing, Hong Kong, Urumqi", utc(2026, 11, 24, 2)),
                           ("(UTC-05:00) Eastern Time (US & Canada)", utc(2026, 11, 24, 15)),
                           ("Singapore Standard Time", utc(2026, 11, 24, 2)),
                           ("/mozilla.org/20050126_1/Europe/Berlin", utc(2026, 11, 24, 9))):
            self.assertEqual(A.ics_time("20261124T100000", {"TZID": tzid}), (want, False), tzid)
        # summer time: Berlin is two hours ahead
        self.assertEqual(A.ics_time("20260714T100000", {"TZID": OUTLOOK_TZ})[0], utc(2026, 7, 14, 8))

    def test_vtimezone_for_a_name_nobody_knows(self):
        zones = A.ics_zones(A.ics_parse(cal("", zones=VTZ_BERLIN % "Custom Zone")))
        self.assertEqual(A.ics_time("20261124T100000", {"TZID": "Custom Zone"}, zones)[0], utc(2026, 11, 24, 9))
        self.assertEqual(A.ics_time("20260714T100000", {"TZID": "Custom Zone"}, zones)[0], utc(2026, 7, 14, 8))
        # either side of the change on the last Sunday of March 2026 (the 29th, 02:00)
        self.assertEqual(A.ics_time("20260329T013000", {"TZID": "Custom Zone"}, zones)[0], utc(2026, 3, 29, 0, 30))
        self.assertEqual(A.ics_time("20260329T040000", {"TZID": "Custom Zone"}, zones)[0], utc(2026, 3, 29, 2))

    def test_a_fixed_offset_zone_from_vtimezone(self):
        z = ("BEGIN:VTIMEZONE\r\nTZID:Kolkata Office\r\nBEGIN:STANDARD\r\nDTSTART:16010101T000000\r\n"
             "TZOFFSETFROM:+0530\r\nTZOFFSETTO:+0530\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n")
        zones = A.ics_zones(A.ics_parse(cal("", zones=z)))
        self.assertEqual(A.ics_time("20261124T100000", {"TZID": "Kolkata Office"}, zones)[0], utc(2026, 11, 24, 4, 30))

    def test_unknown_zone_is_said(self):
        ts, all_day, zone = A.ics_when("20261124T100000", {"TZID": "Nowhere Standard Time"}, {})
        self.assertTrue(zone["unknown"])
        v = A.invite_of(mail(cal(EVENT % ("Nowhere", "Nowhere"))))
        self.assertTrue(v["zone"]["unknown"])

    def test_utc_and_floating(self):
        self.assertEqual(A.ics_when("20261125T060000Z", {}, {})[:2], (utc(2026, 11, 25, 6), False))
        self.assertIsNone(A.ics_when("20261125T060000Z", {}, {})[2])
        self.assertIsNone(A.ics_when("20261125T060000", {}, {})[2])

    @unittest.skipUnless(HAS_TZ, "no time zone database here (Windows without tzdata)")
    def test_every_windows_zone_is_known(self):
        from zoneinfo import ZoneInfo
        for win, iana in A.WIN_TZ.items():
            ZoneInfo(iana)


class Kinds(unittest.TestCase):
    def test_all_day(self):
        e = "UID:a\r\nDTSTART;VALUE=DATE:20261125\r\nDTEND;VALUE=DATE:20261127\r\nSUMMARY:Fair\r\n"
        v = A.invite_of(mail(cal(e)))
        self.assertTrue(v["all_day"])
        self.assertEqual((v["day0"], v["day1"]), ("20261125", "20261126"))      # DTEND is the day after
        v = A.invite_of(mail(cal("UID:a\r\nDTSTART;VALUE=DATE:20261125\r\nSUMMARY:Fair\r\n")))
        self.assertEqual((v["day0"], v["day1"]), ("20261125", "20261125"))
        self.assertEqual(v["end"] - v["start"], 86400)

    def test_duration(self):
        v = A.invite_of(mail(cal("UID:a\r\nDTSTART:20261125T060000Z\r\nDURATION:PT1H30M\r\nSUMMARY:x\r\n")))
        self.assertEqual(v["end"] - v["start"], 5400)
        self.assertEqual(A.ics_duration("P1W"), 7 * 86400)
        self.assertIsNone(A.ics_duration("P"))

    def test_reply(self):
        e = ("UID:a\r\nSEQUENCE:0\r\nDTSTART:20261125T060000Z\r\nSUMMARY:Supplier sync\r\n"
             "ORGANIZER:mailto:you@example.com\r\nCOMMENT:See you there\r\n"
             'ATTENDEE;PARTSTAT=ACCEPTED;CN="Gerrick Ong":mailto:gerrick@contoso.com\r\n')
        v = A.invite_of(mail(cal(e, "REPLY"), method="REPLY"))
        self.assertEqual(v["method"], "REPLY")
        self.assertEqual(v["reply"], {"name": "Gerrick Ong", "addr": "gerrick@contoso.com", "status": "ACCEPTED",
                                      "comment": "See you there"})
        A.invite_for(v, "you@example.com")
        self.assertTrue(v["mine"])
        self.assertFalse(v["can_answer"])

    def test_cancel(self):
        v = A.invite_of(mail(cal(EVENT % ("Europe/Berlin", "Europe/Berlin"), "CANCEL"), method="CANCEL"))
        self.assertTrue(v["cancelled"])
        self.assertFalse(A.invite_for(v, "you@example.com")["can_answer"])
        v = A.invite_of(mail(cal("UID:a\r\nSTATUS:CANCELLED\r\nDTSTART:20261125T060000Z\r\n", "PUBLISH")))
        self.assertTrue(v["cancelled"])

    def test_counter(self):
        e = ("UID:a\r\nDTSTART:20261126T060000Z\r\nSUMMARY:Supplier sync\r\n"
             'ATTENDEE;PARTSTAT=TENTATIVE;CN=Li Ming:mailto:li.ming@example.cn\r\n')
        v = A.invite_of(mail(cal(e, "COUNTER"), method="COUNTER"))
        self.assertEqual((v["method"], v["reply"]["name"], v["start"]), ("COUNTER", "Li Ming", utc(2026, 11, 26, 6)))

    def test_attendees_and_me(self):
        v = A.invite_for(A.invite_of(mail(cal(EVENT % ("Europe/Berlin", "Europe/Berlin")))), "You@Example.com")
        self.assertEqual([a["addr"] for a in v["attendees"]], ["you@example.com", "li.ming@example.cn"])  # no room
        self.assertEqual(v["attendees"][1]["status"], "ACCEPTED")
        self.assertEqual((v["me_status"], v["mine"], v["can_answer"]), ("NEEDS-ACTION", False, True))
        self.assertFalse(A.invite_for(dict(v), "someone@else.com")["can_answer"])      # not asked: no buttons

    def test_quoted_params_with_colons(self):
        e = ('UID:a\r\nDTSTART:20261125T060000Z\r\nORGANIZER;CN="Ong: PM; Plant 2":mailto:gerrick@contoso.com\r\n')
        self.assertEqual(A.invite_of(mail(cal(e)))["organizer"], "Ong: PM; Plant 2")

    def test_changed_occurrence_wins(self):
        series = ("UID:s\r\nSEQUENCE:0\r\nDTSTART:20261123T020000Z\r\nRRULE:FREQ=WEEKLY;BYDAY=MO\r\nSUMMARY:Weekly\r\n")
        one = ("UID:s\r\nSEQUENCE:1\r\nRECURRENCE-ID:20261130T020000Z\r\nDTSTART:20261201T020000Z\r\nSUMMARY:Weekly\r\n")
        text = cal(series)[:-len("END:VEVENT\r\nEND:VCALENDAR\r\n")] + "END:VEVENT\r\nBEGIN:VEVENT\r\n" + one + \
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        v = A.invite_of(mail(text))
        self.assertTrue(v["occurrence"])
        self.assertEqual(v["start"], utc(2026, 12, 1, 2))
        self.assertIsNone(v["repeat"])
        # the series alone, sent again with the same sequence: the series
        v = A.invite_of(mail(cal(series)))
        self.assertFalse(v["occurrence"])

    def test_text_calendar_part_wins_over_a_file(self):
        m = EmailMessage()
        m["From"] = "a@b.c"
        m.set_content("x")
        m.add_attachment(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", "application", "octet-stream", filename="old.ics")
        m.add_attachment(cal("UID:a\r\nDTSTART:20261125T060000Z\r\nSUMMARY:Real\r\n").encode(), "text", "calendar")
        self.assertEqual(A.invite_of(A.R.to_msg(m.as_bytes()))["title"], "Real")
        self.assertEqual(A.invite_of(mail(cal("UID:a\r\nDTSTART:20261125T060000Z\r\nSUMMARY:File\r\n"),
                                          as_file=True))["title"], "File")


class Repeats(unittest.TestCase):
    def test_rule_is_read(self):
        e = ("UID:r\r\nDTSTART;TZID=Asia/Shanghai:20261123T100000\r\nDTEND;TZID=Asia/Shanghai:20261123T110000\r\n"
             "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE;UNTIL=20271230T020000Z\r\nSUMMARY:x\r\n")
        r = A.invite_of(mail(cal(e)))["repeat"]
        self.assertEqual((r["freq"], r["interval"], r["byday"], r["until"]), ("WEEKLY", 2, ["MO", "WE"], utc(2027, 12, 30, 2)))

    @unittest.skipUnless(HAS_TZ, "no time zone database here (Windows without tzdata)")
    def test_next_occurrence_of_a_running_series(self):
        e = ("UID:r\r\nDTSTART;TZID=Asia/Shanghai:20200106T100000\r\nDTEND;TZID=Asia/Shanghai:20200106T110000\r\n"
             "RRULE:FREQ=WEEKLY;BYDAY=MO\r\nSUMMARY:x\r\n")
        v = A.invite_of(mail(cal(e)))
        self.assertGreater(v["end"], time.time())
        self.assertLess(v["start"], time.time() + 8 * 86400)
        self.assertEqual(dt.datetime.fromtimestamp(v["start"], dt.timezone(dt.timedelta(hours=8))).strftime("%a %H:%M"),
                         "Mon 10:00")
        self.assertFalse(v["repeat"]["over"])

    def test_a_series_that_ended(self):
        e = ("UID:r\r\nDTSTART:20200106T020000Z\r\nDTEND:20200106T030000Z\r\n"
             "RRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:x\r\n")
        v = A.invite_of(mail(cal(e)))
        self.assertTrue(v["repeat"]["over"])
        self.assertEqual(v["start"], utc(2020, 1, 6, 2))

    def test_monthly_nth_weekday(self):
        rr = A.rrule_info("FREQ=MONTHLY;BYDAY=2TU", None, dt.datetime(2026, 1, 13, 10))
        nxt = A.rrule_next(dt.datetime(2026, 1, 13, 10), 3600, None, rr, dt.datetime(2026, 3, 1).timestamp())
        self.assertEqual(nxt, dt.datetime(2026, 3, 10, 10))
        rr = A.rrule_info("FREQ=MONTHLY;BYDAY=-1FR", None, dt.datetime(2026, 1, 30, 10))
        self.assertEqual(A.rrule_next(dt.datetime(2026, 1, 30, 10), 3600, None, rr, dt.datetime(2026, 2, 1).timestamp()),
                         dt.datetime(2026, 2, 27, 10))


class Charsets(unittest.TestCase):
    E = ("UID:c\r\nDTSTART;TZID=China Standard Time:20261125T140000\r\nSUMMARY:产品培训\r\nLOCATION:三楼会议室\r\n"
         "ORGANIZER;CN=王芳:mailto:wang.fang@example.cn\r\n")

    def test_declared_gb18030(self):
        v = A.invite_of(mail(cal(self.E), charset="gb18030"))
        self.assertEqual((v["title"], v["where"], v["organizer"]), ("产品培训", "三楼会议室", "王芳"))

    def test_gbk_labelled_utf8_or_not_labelled(self):
        data = cal(self.E).encode("gbk")
        self.assertEqual(A.invite_of(mail("", charset="utf-8", data=data))["title"], "产品培训")
        self.assertEqual(A.invite_of(mail("", as_file=True, data=data))["title"], "产品培训")

    def test_utf8_with_bom(self):
        data = b"\xef\xbb\xbf" + cal(self.E).encode()
        self.assertEqual(A.invite_of(mail("", as_file=True, data=data))["title"], "产品培训")


def calendar_part(msg):
    return next(p for p in msg.walk() if p.get_content_type() == "text/calendar")


class Reply(unittest.TestCase):
    """The iTIP REPLY that Accept / Maybe / Decline sends (RFC 5546 3.2.3)."""

    def build(self, answer="ACCEPTED", note="", event=None):
        orig = mail(cal(event or EVENT % (OUTLOOK_TZ, OUTLOOK_TZ), zones=VTZ_BERLIN % OUTLOOK_TZ))
        msg = A.build_rsvp(orig, answer, "you@example.com", "Alex Morgan", note, "Accepted: %s")
        return orig, A.R.to_msg(msg.as_bytes(policy=A.R.OUT_POLICY))

    def test_headers(self):
        _o, m = self.build()
        self.assertEqual(A.R.hdr(m, "To"), '"Ong, Gerrick" <gerrick@contoso.com>')
        self.assertEqual(A.R.hdr(m, "From"), "Alex Morgan <you@example.com>")
        self.assertEqual(A.R.hdr(m, "Subject"), "Accepted: Supplier sync")
        self.assertEqual(A.R.hdr(m, "In-Reply-To"), "<inv-1@contoso.com>")
        self.assertEqual(m.get_content_type(), "multipart/alternative")
        p = calendar_part(m)
        self.assertEqual(p.get_param("method"), "REPLY")
        self.assertEqual(p.get_content_charset(), "utf-8")

    def test_calendar(self):
        _o, m = self.build("DECLINED", "Sorry, on leave; back Monday")
        text = A.ics_charset_text(calendar_part(m))
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75, line)
        c = A.ics_parse(text)
        vcal = next(A.ics_find(c, "VCALENDAR"))
        self.assertEqual(A.ics_prop(vcal, "METHOD")[0], "REPLY")
        ev = next(A.ics_find(c, "VEVENT"))
        self.assertEqual(A.ics_prop(ev, "UID")[0], "040000008200E00074C5B7101A82E008")
        self.assertEqual(A.ics_prop(ev, "SEQUENCE")[0], "0")
        org_v, org_p = A.ics_prop(ev, "ORGANIZER")
        self.assertEqual((org_v, org_p["CN"]), ("mailto:gerrick@contoso.com", "Ong, Gerrick"))
        atts = [(v, p) for n, p, v, _l in ev["props"] if n == "ATTENDEE"]
        self.assertEqual(len(atts), 1)                              # only the person answering
        self.assertEqual(atts[0][0], "mailto:you@example.com")
        self.assertEqual(atts[0][1]["PARTSTAT"], "DECLINED")
        self.assertEqual(atts[0][1]["CN"], "Alex Morgan")
        self.assertNotIn("RSVP", atts[0][1])
        self.assertRegex(A.ics_prop(ev, "DTSTAMP")[0], r"^\d{8}T\d{6}Z$")
        self.assertEqual(A.ics_text(A.ics_prop(ev, "COMMENT")[0]), "Sorry, on leave; back Monday")
        # the zone the times are in goes along, so the reply reads the same everywhere
        self.assertEqual(len(list(A.ics_find(c, "VTIMEZONE"))), 1)
        self.assertEqual(A.invite_of(m)["start"], utc(2026, 11, 24, 9))
        self.assertEqual(A.invite_of(m)["reply"]["status"], "DECLINED")

    def test_keeps_sequence_and_occurrence(self):
        e = ("UID:s\r\nSEQUENCE:3\r\nRECURRENCE-ID:20261130T020000Z\r\nDTSTART:20261201T020000Z\r\nSUMMARY:W\r\n"
             "ORGANIZER:mailto:o@x.com\r\nATTENDEE:mailto:you@example.com\r\n")
        _o, m = self.build("TENTATIVE", event=e)
        ev = next(A.ics_find(A.ics_parse(A.ics_charset_text(calendar_part(m))), "VEVENT"))
        self.assertEqual(A.ics_prop(ev, "SEQUENCE")[0], "3")
        self.assertEqual(A.ics_prop(ev, "RECURRENCE-ID")[0], "20261130T020000Z")
        self.assertIn("PARTSTAT=TENTATIVE", A.ics_charset_text(calendar_part(m)).replace("\r\n ", ""))
        self.assertEqual(A.R.hdr(m, "To"), "o@x.com")

    def test_refuses_nonsense(self):
        with self.assertRaises(ValueError):
            A.build_rsvp(mail(cal(EVENT % ("Europe/Berlin", "Europe/Berlin"))), "MAYBE", "you@example.com")
        m = EmailMessage()
        m["From"] = "a@b.c"
        m.set_content("x")
        with self.assertRaises(ValueError):
            A.build_rsvp(A.R.to_msg(m.as_bytes()), "ACCEPTED", "you@example.com")

    def test_fold(self):
        line = "DESCRIPTION:" + "会议" * 60
        folded = A.ics_fold(line)
        self.assertTrue(all(len(x.encode()) <= 75 for x in folded.split("\r\n")))
        self.assertEqual(folded.replace("\r\n ", ""), line)


class JoinLinks(unittest.TestCase):
    def test_services(self):
        for kind, text in (("teams", "Join: https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0?context=y"),
                           ("zoom", "https://us02web.zoom.us/j/81234567890?pwd=abc"),
                           ("meet", "Join with Google Meet: https://meet.google.com/abc-defg-hij"),
                           ("tencent", "点击链接入会：https://meeting.tencent.com/dm/AbCd123\\n#腾讯会议：123"),
                           ("webex", "https://acme.webex.com/acme/j.php?MTID=m1234")):
            ev = A.pick_event(A.ics_parse(cal("UID:a\r\nDTSTART:20261125T060000Z\r\nDESCRIPTION:%s\r\n" % text)))
            j = A.join_link(ev)
            self.assertEqual(j["kind"], kind, text)
            self.assertFalse(j["url"].endswith("\\n"))
        ev = A.pick_event(A.ics_parse(cal("UID:a\r\nDTSTART:20261125T060000Z\r\nLOCATION:Room 3\r\n")))
        self.assertIsNone(A.join_link(ev))
        ev = A.pick_event(A.ics_parse(cal("UID:a\r\nDTSTART:20261125T060000Z\r\nX-MICROSOFT-SKYPETEAMSMEETINGURL:"
                                          "https://teams.microsoft.com/l/meetup-join/abc\r\n")))
        self.assertEqual(A.join_link(ev)["kind"], "teams")

    def test_teams_boilerplate_is_left_out(self):
        about = A.ics_about("Agenda: orders\n\n" + "_" * 40 + "\nMicrosoft Teams meeting\nJoin now")
        self.assertEqual(about, "Agenda: orders")


class DemoAnswer(unittest.TestCase):
    """Accept in the demo: the reply goes through the app's own draft-and-send path, and nothing leaves."""

    def setUp(self):
        self.cfg = A.R.CFG
        self.smtp, self.web = A.R.smtp_open, A.webbrowser.open

        def no(*a, **k):
            raise AssertionError("the demo must not reach the network")
        A.R.smtp_open = A.webbrowser.open = no

    def tearDown(self):
        A.R.smtp_open, A.webbrowser.open = self.smtp, self.web
        A.R.CFG = self.cfg

    def row(self, b, subject, folder="inbox"):
        return next(r for r in b.api_list({"folder": folder})["rows"] if r["subject"] == subject)

    def test_accept_then_change(self):
        b = A.Backend(demo=True, demo_lang="en")
        try:
            r = self.row(b, "Weekly supplier sync")
            v = b.api_message({"id": r["id"]})["invite"]
            self.assertTrue(v["can_answer"])
            self.assertEqual(v["repeat"]["freq"], "WEEKLY")
            self.assertEqual(v["join"]["kind"], "teams")
            self.assertEqual(v["zone"]["label"], "Amsterdam")
            self.assertIn(("jane.doe@acme-industrial.com", "ACCEPTED"), [(a["addr"], a["status"]) for a in v["attendees"]])
            self.assertIsNone(v["answer"])
            self.assertEqual(b.api_join({"id": r["id"]})["url"], v["join"]["url"])

            # Undo: the draft goes, nothing is sent, nothing is remembered
            d = b.api_rsvp({"id": r["id"], "answer": "ACCEPTED", "note": "Thanks", "subject": "Accepted: %s"})["draft"]
            self.assertEqual(self.row(b, "Accepted: Weekly supplier sync", "drafts")["id"], d)
            b.api_delete_draft({"id": d})
            self.assertFalse([x for x in b.api_list({"folder": "drafts"})["rows"] if x["subject"].startswith("Accepted")])
            self.assertIsNone(b.api_message({"id": r["id"]})["invite"]["answer"])

            d = b.api_rsvp({"id": r["id"], "answer": "ACCEPTED", "note": "Thanks", "subject": "Accepted: %s"})["draft"]
            out = b.api_rsvp_send({"id": r["id"], "draft": d, "answer": "ACCEPTED"})
            self.assertEqual(out, {"answer": "ACCEPTED", "problems_after_sending": []})
            self.assertEqual(b.api_message({"id": r["id"]})["invite"]["answer"], "ACCEPTED")
            sent = self.row(b, "Accepted: Weekly supplier sync", "sent")
            m = A.R.to_msg(b.view(sent["id"])[0])
            self.assertEqual(A.R.hdr(m, "To"), "Daniel Ruiz <d.ruiz@contoso.com>")
            self.assertEqual(calendar_part(m).get_param("method"), "REPLY")
            self.assertIn("PARTSTAT=ACCEPTED", A.ics_charset_text(calendar_part(m)).replace("\r\n ", ""))

            # Change: a later answer replaces it
            d = b.api_rsvp({"id": r["id"], "answer": "DECLINED"})["draft"]
            b.api_rsvp_send({"id": r["id"], "draft": d, "answer": "DECLINED"})
            self.assertEqual(b.api_message({"id": r["id"]})["invite"]["answer"], "DECLINED")
            self.assertEqual(self.row(b, "Declined: Weekly supplier sync", "sent")["subject"], "Declined: Weekly supplier sync")
        finally:
            b.close()

    @unittest.skipUnless(HAS_TZ, "no time zone database here (Windows without tzdata)")
    def test_not_asked_cannot_answer(self):
        b = A.Backend(demo=True, demo_lang="zh")
        try:
            r = self.row(b, "项目周会（腾讯会议）")
            v = b.api_message({"id": r["id"]})["invite"]
            self.assertEqual((v["join"]["kind"], v["where"], v["zone"]), ("tencent", "腾讯会议", {"iana": "Asia/Shanghai",
                             "offset": 28800, "label": "Shanghai"}))
            self.assertTrue(v["can_answer"])
            sub = self.row(b, "[ragdoll-mail] 新版本 v0.5.0 已发布")
            with self.assertRaises(A.ApiError):
                b.api_rsvp({"id": sub["id"], "answer": "ACCEPTED"})
            with self.assertRaises(A.ApiError):
                b.api_rsvp({"id": r["id"], "answer": "PERHAPS"})
        finally:
            b.close()

    @unittest.skipUnless(HAS_TZ, "no time zone database here (Windows without tzdata)")
    def test_updated_invitation_says_what_changed(self):
        b = A.Backend(demo=True, demo_lang="en")
        try:
            e0 = EVENT % ("Europe/Berlin", "Europe/Berlin")
            e1 = e0.replace("SEQUENCE:0", "SEQUENCE:1").replace("T100000", "T140000").replace("T110000", "T150000")
            out0 = {"invite": A.invite_of(mail(cal(e0)))}
            b.invite_state(out0)
            self.assertFalse(out0["invite"]["updated"])
            out1 = {"invite": A.invite_of(mail(cal(e1)))}
            b.invite_state(out1)
            v = out1["invite"]
            self.assertTrue(v["updated"])
            self.assertEqual((v["was"]["start"], v["was"]["end"]), (utc(2026, 11, 24, 9), utc(2026, 11, 24, 10)))
            self.assertNotIn("where", v["was"])
            # an answer to the old time does not count for the new one
            store = b.invites_load()
            store[A.Backend.invite_key(v)]["answer"] = {"status": "ACCEPTED", "seq": 0}
            b.invites_save(store)
            b.invite_state(out1)
            self.assertIsNone(out1["invite"]["answer"])
            b.invite_state(out0)
            self.assertEqual(out0["invite"]["answer"], "ACCEPTED")
        finally:
            b.close()


if __name__ == "__main__":
    unittest.main()
