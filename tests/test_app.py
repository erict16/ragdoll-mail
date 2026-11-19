"""Offline tests of the desktop app's local server, in demo mode (no account, no network)."""
import http.client, json, os, shutil, sys, threading, time, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ragdoll_app as A  # noqa: E402

TOKEN = "test-token"


class AppServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = A.R.CFG                       # demo mode swaps the config; the CLI tests need it back
        cls.backend = A.Backend(demo=True)
        cls.srv = A.Server(("127.0.0.1", 0), A.make_handler(cls.backend, TOKEN))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.close()
        cls.srv.shutdown()
        shutil.rmtree(A.R.CFG.home, ignore_errors=True)
        A.R.CFG = cls.cfg

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port}
        h.update(headers or {})
        c.request(method, path, body, h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def api(self, name, args=None, token=TOKEN):
        code, data = self.req("POST", "/api/" + name, json.dumps(args or {}), {"X-Token": token})
        return code, json.loads(data)

    def test_page_and_assets(self):
        code, body = self.req("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"app.js", body)
        self.assertEqual(self.req("GET", "/style.css")[0], 200)

    def test_no_path_escape(self):
        self.assertEqual(self.req("GET", "/../ragdoll.py")[0], 404)
        self.assertEqual(self.req("GET", "/%2e%2e/ragdoll.py")[0], 404)

    def test_token_required(self):
        self.assertEqual(self.api("boot", token="wrong")[0], 403)
        self.assertEqual(self.api("boot", token="")[0], 403)

    def test_foreign_host_refused(self):
        code, _ = self.req("POST", "/api/boot", "{}", {"X-Token": TOKEN, "Host": "evil.example:80"})
        self.assertEqual(code, 403)

    def test_boot_and_list(self):
        code, out = self.api("boot")
        self.assertEqual(code, 200)
        self.assertTrue(out["ok"])
        self.assertTrue(out["data"]["demo"])
        code, out = self.api("list", {"folder": "inbox"})
        self.assertTrue(out["ok"])
        self.assertTrue(out["data"]["rows"])

    def test_refused_post_does_not_break_the_connection(self):
        # a refused POST must not leave its body behind for the next request on a kept-alive connection
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json"}
        c.request("POST", "/api/boot", "{}", dict(h, **{"X-Token": "wrong"}))
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 403)
        c.request("POST", "/api/boot", "{}", dict(h, **{"X-Token": TOKEN}))
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertTrue(json.loads(r.read())["ok"])
        c.request("POST", "/api/boot", "{}", dict(h, **{"X-Token": TOKEN}))
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        r.read()
        c.close()

    def draft(self, subject):
        _, out = self.api("prepare_send", {"mode": "new", "to": [{"name": "", "addr": "pat@example.com"}],
                                           "subject": subject, "html": "<p>Hello Pat</p>", "atts": []})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["problems"], [])
        return out["data"]["id"]

    def test_scheduled_send(self):
        import time
        i = self.draft("Scheduled hello")
        at = int(time.time()) + 3600
        self.assertTrue(self.api("schedule", {"id": i, "at": at})[1]["ok"])
        rows = self.api("list", {"folder": "scheduled"})[1]["data"]["rows"]
        self.assertEqual([(r["id"], r["sched"]) for r in rows], [(i, at)])
        drafts = self.api("list", {"folder": "drafts"})[1]["data"]["rows"]
        self.assertEqual([r.get("sched") for r in drafts if r["id"] == i], [at])
        keys = [f["key"] for f in self.api("status")[1]["data"]["folders"]]
        self.assertIn("scheduled", keys)
        self.assertEqual(self.backend.send_due(now=at - 10), 0)
        self.assertEqual(self.backend.send_due(now=at + 1), 1)
        self.assertEqual(self.api("list", {"folder": "scheduled"})[1]["data"]["rows"], [])
        sent = self.api("list", {"folder": "sent"})[1]["data"]["rows"]
        self.assertIn("Scheduled hello", [r["subject"] for r in sent])

    def test_unschedule_keeps_the_draft(self):
        import time
        i = self.draft("Not yet")
        self.api("schedule", {"id": i, "at": int(time.time()) + 600})
        self.assertTrue(self.api("unschedule", {"id": i})[1]["ok"])
        self.assertEqual(self.api("list", {"folder": "scheduled"})[1]["data"]["rows"], [])
        self.assertEqual(self.backend.send_due(now=time.time() + 7200), 0)
        drafts = self.api("list", {"folder": "drafts"})[1]["data"]["rows"]
        self.assertIn(i, [r["id"] for r in drafts])
        self.api("delete_draft", {"id": i})

    def test_schedule_refuses_the_past(self):
        i = self.draft("Too late")
        _, out = self.api("schedule", {"id": i, "at": 1000})
        self.assertFalse(out["ok"])
        self.api("delete_draft", {"id": i})

    def test_failed_scheduled_send_is_kept_with_its_reason(self):
        import time
        i = self.draft("Gone")
        self.api("schedule", {"id": i, "at": int(time.time()) + 60})
        self.backend.demo_delete(i)            # the draft vanished (deleted in another mail app)
        self.assertEqual(self.backend.send_due(now=time.time() + 120), 0)
        left = [x for x in self.backend.sched_list() if x["id"] == i]
        self.assertTrue(left and left[0].get("error"))
        self.assertEqual(self.backend.send_due(now=time.time() + 240), 0)   # not tried again by itself
        self.api("unschedule", {"id": i})

    def test_prefs_are_checked(self):
        out = self.api("prefs", {"lang": "zh-Hant", "tz": "Asia/Taipei", "undo": 10})[1]["data"]
        self.assertEqual((out["lang"], out["tz"], out["undo"]), ("zh-Hant", "Asia/Taipei", 10))
        out = self.api("prefs", {"lang": "xx", "tz": "../../etc", "undo": 7})[1]["data"]
        self.assertEqual((out["lang"], out["tz"], out["undo"]), ("zh-Hant", "Asia/Taipei", 10))
        self.assertEqual(self.api("boot")[1]["data"]["prefs"]["lang"], "zh-Hant")
        self.api("prefs", {"lang": "system", "tz": "system", "undo": 5})

    def test_look_prefs_are_checked(self):
        out = self.api("prefs", {"font": "georgia", "font_size": 16, "text_size": 15, "fmt_bar": True})[1]["data"]
        self.assertEqual((out["font"], out["font_size"], out["text_size"], out["fmt_bar"]), ("georgia", 16, 15, True))
        out = self.api("prefs", {"font": "comic; x", "font_size": 99, "text_size": "15", "fmt_bar": "yes"})[1]["data"]
        self.assertEqual((out["font"], out["font_size"], out["text_size"], out["fmt_bar"]), ("georgia", 16, 15, True))
        self.api("prefs", {"font": "system", "font_size": 14, "text_size": 14, "fmt_bar": False})

    def test_new_mail_notification(self):
        b, said = self.backend, []
        real = A.desktop.desktop_notify
        A.desktop.desktop_notify = lambda title, text, click: said.append((title, text, click))
        try:
            b.note_mark = None
            self.assertIsNone(b.notify_new(b.c))            # the first pass only marks the Inbox
            self.assertFalse(said)
            inbox, now = A.R.CFG.folders["inbox"], int(time.time())
            for k, who in enumerate(("Old Friend", "New Friend")):
                raw = A.demo.demo_message("inbox", now + k, (who, "f%d@example.com" % k), [A.demo.ME], [], "Hello %d" % k,
                                     "Hi", [], "<note-%d@example.com>" % k, None, None)
                uid = b.demo_insert(inbox, raw, now + k, 0, 0)
            mine = A.demo.demo_message("inbox", now + 5, A.demo.ME, [A.demo.ME], [], "Note to self", "x", [], "<note-me@example.com>",
                                  None, None)
            b.demo_insert(inbox, mine, now + 5, 0, 0)       # mail from me is left out
            i = b.notify_new(b.c)
            self.assertEqual(i, A.R.make_id(inbox, uid))
            self.assertEqual(said[0][:2], ("New Friend +1", "Hello 1"))
            self.assertIsNone(b.notify_new(b.c))            # told once
            said[0][2]()                                    # the click
            st = self.api("status")[1]["data"]
            self.assertEqual(st["open"], i)
            self.assertIsNone(self.api("status")[1]["data"]["open"])
            out = self.api("prefs", {"notify": False})[1]["data"]
            self.assertIs(out["notify"], False)
            raw = A.demo.demo_message("inbox", now + 9, ("Third", "t@example.com"), [A.demo.ME], [], "Quiet", "x", [],
                                 "<note-3@example.com>", None, None)
            b.demo_insert(inbox, raw, now + 9, 0, 0)
            self.assertIsNone(b.notify_new(b.c))            # switched off
            self.assertEqual(len(said), 1)
        finally:
            A.desktop.desktop_notify = real
            self.api("prefs", {"notify": True})

    def test_flagged_list_and_count(self):
        rows = self.api("list", {"folder": "inbox"})[1]["data"]["rows"]
        i = next(r["id"] for r in rows if not r["flagged"])

        def flagged():
            ids = [r["id"] for r in self.api("list", {"folder": "flagged"})[1]["data"]["rows"]]
            n = {f["key"]: f for f in self.api("status")[1]["data"]["folders"]}["flagged"]
            return ids, n
        before, _ = flagged()
        self.assertTrue(self.api("mark", {"ids": [i], "flag": "flagged", "on": True})[1]["ok"])
        after, _ = flagged()
        self.assertEqual(set(after) - set(before), {i})
        self.api("mark", {"ids": [i], "flag": "flagged", "on": False})
        self.assertNotIn(i, flagged()[0])

    def test_bad_input_gets_a_message(self):
        for name, args in (("mark", {"ids": 5}), ("mark", {"ids": [1, 2]}), ("move", {"to": "trash", "ids": {"a": 1}}),
                           ("list", {"folder": "inbox", "limit": "lots", "offset": 1e300}),
                           ("search", {"q": ["x"]}), ("contacts", {"q": 7}), ("schedule", {"id": "x", "at": 1e400})):
            code, out = self.api(name, args)
            self.assertIn(code, (200, 400, 500), name)
            self.assertIn("ok", out, name)
        code, out = self.req("POST", "/api/list", json.dumps([1, 2]), {"X-Token": TOKEN})
        self.assertEqual(code, 400)
        rows = self.api("list", {"folder": "inbox", "limit": "lots"})[1]["data"]["rows"]
        self.assertTrue(rows)

    def test_moved_draft_is_no_longer_scheduled(self):
        import time
        i = self.draft("Move me")
        self.api("schedule", {"id": i, "at": int(time.time()) + 600})
        self.assertTrue(self.api("move", {"ids": [i], "to": "trash"})[1]["ok"])
        self.assertNotIn(i, [x["id"] for x in self.backend.sched_list()])
        self.assertEqual(self.backend.send_due(now=time.time() + 7200), 0)

    def test_demo_ids_are_not_reused(self):
        a = self.draft("First")
        self.api("delete_draft", {"id": a})
        b = self.draft("Second")
        self.assertNotEqual(a, b)
        self.api("delete_draft", {"id": b})

    def test_unknown_call(self):
        code, out = self.api("nope")
        self.assertEqual(code, 404)
        self.assertFalse(out["ok"])


class AppFeatures(unittest.TestCase):
    """Folders, search pages, invites, the outbox, snooze, templates and the update sheet, on a demo mailbox of its own."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = A.R.CFG
        cls.b = A.Backend(demo=True)
        cls.said = []
        cls.notify = A.desktop.desktop_notify
        A.desktop.desktop_notify = lambda title, text, click: cls.said.append((title, text, click))

    @classmethod
    def tearDownClass(cls):
        A.desktop.desktop_notify = cls.notify
        cls.b.close()
        shutil.rmtree(A.R.CFG.home, ignore_errors=True)
        A.R.CFG = cls.cfg

    def compose(self, subject):
        return {"mode": "new", "to": [{"name": "Jane", "addr": "jane@example.com"}], "cc": [], "bcc": [],
                "subject": subject, "html": "<p>Hello.</p>", "atts": [], "use_signature": True, "force": True}

    def test_own_folders_and_junk(self):
        b = self.b
        keys = [f["key"] for f in b.folder_counts()]
        self.assertIn("junk", keys)
        self.assertIn("f:Customers/Acme", keys)
        acme = next(f for f in b.folder_counts() if f["key"] == "f:Customers/Acme")
        self.assertEqual((acme["name"], acme["depth"], acme["custom"]), ("Acme", 1, True))
        self.assertEqual(len(b.api_list({"folder": "f:Receipts"})["rows"]), 2)
        i = b.api_list({"folder": "f:Receipts"})["rows"][0]["id"]
        b.api_move({"ids": [i], "to": "f:Customers"})
        self.assertEqual(len(b.api_list({"folder": "f:Customers"})["rows"]), 1)
        with self.assertRaises(A.ApiError):
            b.api_list({"folder": "f:No such folder"})

    def test_folder_list_parsing(self):
        class M:
            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Noselect) "/" "[Gmail]"',
                              b'(\\HasNoChildren) "." "Projects.Site A"', b'() NIL Plain', (b'() "/" {8}', b'Odd "one')]
        self.assertEqual(A.folders.list_folders_full(M()), [
            ("INBOX", "\\hasnochildren", "/"), ("[Gmail]", "\\noselect", "/"),
            ("Projects.Site A", "\\hasnochildren", "."), ("Plain", "", ""), ('Odd "one', "", "/")])
        self.assertEqual(A.folders.list_folders(M())[0], ("INBOX", "\\hasnochildren"))

    def test_search_pages(self):
        b, now = self.b, int(time.time())
        inbox = A.R.CFG.folders["inbox"]
        with b.dblock:
            for k in range(230):
                cur = b.c.execute(
                    "insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
                    "answered,size,has_body,fwd) values(?,1,?,?,null,null,?,?,?,'',?,'',?,1,0,0,100,1,0)",
                    (inbox, 5000 + k, "<pg-%d@x>" % k, now - 9 * 86400 - k * 60, "Sender <s@example.com>",
                     "you@example.com", "Zebracrossing note %d" % k, "Body %d." % k))
                b.c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(?,?,?,'','',?)",
                            (cur.lastrowid, "Zebracrossing note %d" % k, "Sender", "Body %d." % k))
            b.c.commit()
        seen, off, pages = [], 0, 0
        while True:
            r = b.api_search({"q": "zebracrossing", "offset": off})
            seen += [x["id"] for x in r["rows"]]
            off, pages = r["next"], pages + 1
            if not r["more"]:
                break
        self.assertEqual((pages, len(seen), len(set(seen))), (3, 230, 230))
        self.assertEqual(len(b.api_search({"q": "zebracrossing", "limit": 2000})["rows"]), 230)
        # the Inbox list still pages through all of them
        got, off = [], 0
        while True:
            r = b.api_list({"folder": "inbox", "limit": 100, "offset": off})
            got += r["rows"]
            off = len(got)
            if not r["more"] or not r["rows"]:
                break
        self.assertEqual(len({x["id"] for x in got}), len(got))
        self.assertGreaterEqual(len(got), 230)

    def test_invite_is_shown_and_answered(self):
        b = self.b
        r = next(x for x in b.api_list({"folder": "inbox"})["rows"] if x["subject"] == "PO-1234 delivery review")
        v = b.api_message({"id": r["id"], "mark": False})["invite"]
        self.assertEqual((v["method"], v["summary"], v["location"]), ("REQUEST", "PO-1234 delivery review",
                                                                     "Meeting room 3, Building A"))
        self.assertEqual((v["start"]["wall"][3:], v["start"]["tz"], v["start"]["offset"]), ([14, 0], "Asia/Shanghai", 480))
        self.assertTrue(v["can_answer"])
        self.assertEqual(v["mine"], "NEEDS-ACTION")
        out = b.api_invite({"id": r["id"], "answer": "declined"})
        self.assertEqual((out["mine"], out["queued"]), ("DECLINED", False))
        sent = b.api_list({"folder": "sent"})["rows"][0]
        self.assertEqual(sent["subject"], "Declined: PO-1234 delivery review")
        cal = next(p for p in A.R.leaf_parts(A.R.to_msg(b.raw(sent["id"]))) if p.get_content_type() == "text/calendar")
        self.assertEqual(cal.get_param("method"), "REPLY")
        text = cal.get_payload(decode=True).decode()
        self.assertIn("METHOD:REPLY", text)
        self.assertIn("UID:demo-invite-1@acme-industrial.com", text)
        self.assertIn('ATTENDEE;PARTSTAT=DECLINED;CN="Alex Morgan":mailto:you@example.com', text)
        self.assertIn("TZID:China Standard Time", text)         # the zone it names comes along
        self.assertEqual(b.api_message({"id": r["id"], "mark": False})["invite"]["mine"], "DECLINED")
        with self.assertRaises(A.ApiError):
            b.api_invite({"id": b.api_list({"folder": "inbox"})["rows"][-1]["id"], "answer": "accepted"})

    def test_ics_times_and_folding(self):
        ev = A.invites.ics_parse("BEGIN:VCALENDAR\nMETHOD:CANCEL\nBEGIN:VEVENT\nUID:u1\nDTSTART;VALUE=DATE:20261201\n"
                         "DTEND;VALUE=DATE:20261202\nSUMMARY:Off\\, all day\nRRULE:FREQ=WEEKLY\n"
                         "ATTENDEE;CN=\"Doe, Jane\";PARTSTAT=ACCEPTED:MAILTO:Jane@Example.com\n"
                         "BEGIN:VALARM\nDESCRIPTION:not the event\nEND:VALARM\nEND:VEVENT\nEND:VCALENDAR")
        self.assertEqual((ev["method"], ev["summary"], ev["start"]["day"], ev["start"]["wall"][:3], ev["repeats"]),
                         ("CANCEL", "Off, all day", True, [2026, 12, 1], True))
        self.assertEqual(ev["attendees"][0], {"name": "Doe, Jane", "addr": "jane@example.com", "status": "ACCEPTED"})
        self.assertNotIn("description", ev)
        utc = A.invites.ics_parse("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:u2\nDTSTART:20261201T0\n 90000Z\nEND:VEVENT\nEND:VCALENDAR")
        self.assertEqual((utc["start"]["wall"], utc["start"]["tz"]), ([2026, 12, 1, 9, 0], "UTC"))
        self.assertIsNone(A.invites.ics_parse("BEGIN:VCALENDAR\nEND:VCALENDAR"))
        long = A.invites.ics_fold("SUMMARY:" + "长" * 60)
        self.assertTrue(all(len(x.encode()) <= 75 for x in long.split("\r\n")))
        self.assertEqual(long.replace("\r\n ", ""), "SUMMARY:" + "长" * 60)

    def test_outbox_waits_for_a_connection(self):
        b = self.b
        b.fake_offline = True
        try:
            q = b.api_prepare_send(self.compose("Written offline"))
            self.assertTrue(q["queued"])
            row = next(x for x in b.scheduled_rows() if x["id"] == q["id"])
            self.assertEqual((row["subject"], row["waiting"]), ("Written offline", True))
            self.assertEqual(b.api_outbox({"do": "message", "id": q["id"]})["subject"], "Written offline")
            self.assertEqual(b.flush_outbox(), 0)                   # still no connection: it stays
            self.assertEqual(len(b.outbox_list()), 1)
        finally:
            b.fake_offline = False
        self.assertEqual(b.flush_outbox(), 1)
        self.assertEqual(b.outbox_list(), [])
        self.assertEqual(b.api_list({"folder": "sent"})["rows"][0]["subject"], "Written offline")
        # a saved draft whose send meets no connection waits too, once
        i = b.api_save_draft(self.compose("Second try"))["id"]
        b.fake_offline = True
        try:
            self.assertEqual(b.api_send({"id": i}), {"queued": True})
            self.assertEqual(b.api_send({"id": i}), {"queued": True})
            self.assertEqual([x.get("id") for x in b.outbox_list()], [i])
        finally:
            b.fake_offline = False
        self.assertEqual(b.api_outbox({"do": "retry"}), {"sent": 1, "waiting": 0})
        # back to the editor: nothing is lost, and it no longer waits
        b.fake_offline = True
        try:
            q = b.api_prepare_send(self.compose("Third"))
        finally:
            b.fake_offline = False
        c = b.api_compose({"mode": "outbox", "id": q["id"]})
        self.assertEqual((c["subject"], c["to"][0]["addr"], c["mode"]), ("Third", "jane@example.com", "new"))
        self.assertEqual(b.outbox_list(), [])

    def test_only_connection_errors_wait(self):
        import smtplib, socket
        self.assertTrue(A.R.not_connected(socket.gaierror()))
        self.assertTrue(A.R.not_connected(TimeoutError()))
        self.assertTrue(A.R.not_connected(A.R.NotConnected("x")))
        self.assertFalse(A.R.not_connected(smtplib.SMTPAuthenticationError(535, b"no")))
        self.assertFalse(A.R.not_connected(smtplib.SMTPRecipientsRefused({})))
        self.assertFalse(A.R.not_connected(ValueError()))

    def test_snooze_hides_then_brings_back_on_top(self):
        b, now = self.b, int(time.time())
        rows = b.api_list({"folder": "inbox"})["rows"]
        i = next(x["id"] for x in rows if x["subject"] == "Lunch on Thursday?")
        with self.assertRaises(A.ApiError):
            b.api_snooze({"ids": [i], "until": now - 5})
        b.api_snooze({"ids": [i], "until": now + 3600})
        self.assertNotIn(i, [x["id"] for x in b.api_list({"folder": "inbox"})["rows"]])
        self.assertEqual([x["id"] for x in b.api_list({"folder": "snoozed"})["rows"]], [i])
        self.assertIn("snoozed", [f["key"] for f in b.folder_counts()])
        self.assertEqual(b.wake_due(now + 60), 0)
        del self.said[:]
        self.assertEqual(b.wake_due(now + 3601), 1)
        top = b.api_list({"folder": "inbox"})["rows"][0]
        self.assertEqual((top["id"], top["woke"], top["unread"]), (i, True, True))
        self.assertEqual(self.said[0][1], "Lunch on Thursday?")
        all_ids = [x["id"] for x in b.api_list({"folder": "inbox", "limit": 500})["rows"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        b.api_message({"id": i})                                    # read: an ordinary mail again
        self.assertNotIn("woke", b.api_list({"folder": "inbox"})["rows"][0])
        self.assertEqual(b.snooze_state(), ([], []))
        b.api_snooze({"ids": [i], "until": now + 3600})
        b.api_snooze({"ids": [i], "until": 0})
        self.assertIn(i, [x["id"] for x in b.api_list({"folder": "inbox"})["rows"]])

    def test_templates(self):
        b = self.b
        with self.assertRaises(A.ApiError):
            b.api_templates({"do": "save", "name": " ", "html": "<p>x</p>"})
        with self.assertRaises(A.ApiError):
            b.api_templates({"do": "save", "name": "Empty", "html": "<p> </p>"})
        t = b.api_templates({"do": "save", "name": "Thanks", "html": "<p>Thank you.</p>"})["templates"]
        self.assertEqual([x["name"] for x in t], ["Thanks"])
        t = b.api_templates({"do": "save", "id": t[0]["id"], "name": "Thanks a lot", "html": "<p>Many thanks.</p>"})["templates"]
        self.assertEqual([(x["name"], x["html"]) for x in t], [("Thanks a lot", "<p>Many thanks.</p>")])
        self.assertEqual(b.api_templates({})["templates"], t)
        self.assertEqual(b.api_templates({"do": "delete", "id": t[0]["id"]})["templates"], [])

    def test_update_offer_notes_and_skip(self):
        b = self.b
        b.update = {"version": "9.9.9", "id": "9.9.9", "kind": "download", "url": A.updates.RELEASES_PAGE, "download": None,
                    "notes": ["One", "Two"]}
        try:
            self.assertEqual(b.api_status({})["update"]["notes"], ["One", "Two"])
            with self.assertRaises(A.ApiError):
                b.api_update({"do": "install"})                     # a packaged or demo app does not update itself
            b.api_update({"do": "skip"})
            self.assertIsNone(b.api_status({})["update"])
            b.update = dict(b.update, version="10.0.0", id="10.0.0")   # a newer one is offered again
            self.assertEqual(b.api_status({})["update"]["version"], "10.0.0")
        finally:
            b.update = None
        self.assertEqual(A.updates.release_notes("## What's new\n- **Fast** list\n- See [the docs](http://x)\n"),
                         ["Fast list", "See the docs"])
        assets = [{"name": "ragdoll-mail.exe", "browser_download_url": "https://x/a.exe"},
                  {"name": "ragdoll-mail-mac.zip", "browser_download_url": "https://x/a.zip"},
                  {"name": "bad.exe", "browser_download_url": "http://x/b.exe"}]
        want = {"win32": "https://x/a.exe", "darwin": "https://x/a.zip"}.get(sys.platform)
        self.assertEqual(A.updates.release_asset(assets), want)

    def test_wait_answers_when_something_changes(self):
        b = self.b
        st = b.api_status({})
        t0 = time.time()
        self.assertEqual(b.api_wait({"tick": st["tick"], "max": 0})["tick"], st["tick"])     # nothing new: comes back as it is
        self.assertLess(time.time() - t0, 1)
        got = {}
        th = threading.Thread(target=lambda: got.update(b.api_wait({"tick": st["tick"], "max": 20})))
        th.start()
        time.sleep(0.2)
        self.assertTrue(th.is_alive())                                  # it waits
        i = b.api_list({"folder": "inbox"})["rows"][0]["id"]
        t0 = time.time()
        b.api_mark({"ids": [i], "flag": "flagged", "on": True})
        th.join(3)
        self.assertFalse(th.is_alive())
        self.assertLess(time.time() - t0, 1)                            # and answers at once
        self.assertGreater(got["tick"], st["tick"])
        b.api_mark({"ids": [i], "flag": "flagged", "on": False})

    def test_counts_follow_a_change_made_by_another_program(self):
        b = self.b
        unread = lambda: next(f for f in b.folder_counts() if f["key"] == "inbox")["unread"]    # noqa: E731
        n = unread()
        self.assertEqual(unread(), n)                                   # the second read comes from memory
        c = A.R.db()                                                    # as the command line would write
        row = c.execute("select id, seen from msgs where folder=? and seen=1 limit 1", (A.R.CFG.folders["inbox"],)).fetchone()
        c.execute("update msgs set seen=0 where id=?", (row["id"],))
        c.commit()
        self.assertEqual(unread(), n + 1)
        c.execute("update msgs set seen=1 where id=?", (row["id"],))
        c.commit()
        c.close()
        self.assertEqual(unread(), n)

    def test_a_reply_sent_from_the_command_line_shows_in_the_list(self):
        b = self.b
        st = b.api_status({})
        inbox = A.R.CFG.folders["inbox"]
        got = {}
        th = threading.Thread(target=lambda: got.update(b.api_wait({"tick": st["tick"], "max": 20})))
        th.start()
        time.sleep(0.2)
        c = A.R.db()                                                    # as the command line does after sending
        row = c.execute("select id, folder, uid from msgs where folder=? and answered=0 limit 1", (inbox,)).fetchone()
        c.execute("update msgs set answered=1 where id=?", (row["id"],))
        c.commit()
        th.join(5)
        self.assertFalse(th.is_alive())
        self.assertGreater(got["rev"], st["rev"])                       # the page loads its list again
        i = A.R.make_id(row["folder"], row["uid"])
        self.assertTrue(next(r for r in b.api_list({"folder": "inbox"})["rows"] if r["id"] == i)["answered"])
        c.execute("update msgs set answered=0 where id=?", (row["id"],))
        c.commit()
        c.close()

    def test_conversation_by_subject_keeps_odd_characters(self):
        """Mails with no References join by subject; the quick SQL filter must not lose look-alike letters."""
        b, now = self.b, int(time.time())
        kelvin, dotted = chr(0x212A), chr(0x130)                        # both turn into plain k / i when cleaned
        subjects = ["Zeta-Kappa review", "RE: zeta-kappa  review", "Fwd: Zeta-" + kelvin + "appa review",
                    "Zeta-Kappa rev" + dotted + "ew", "Zeta-Kappa reviews"]
        inbox = A.R.CFG.folders["inbox"]
        with b.dblock:
            for k, subj in enumerate(subjects):
                b.c.execute("insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,"
                            "answered,size,has_body,fwd) values(?,1,?,?,'','',?,'a@example.com','you@example.com','',?,'','x',1,0,0,1,1,'')",
                            (inbox, 7000 + k, "<zk-%d@x>" % k, now - 3600 - k, subj))
            b.c.commit()
            row = b.c.execute("select * from msgs where uid=7000 and folder=?", (inbox,)).fetchone()
            got = sorted(r["uid"] for r in A.R.thread_rows(b.c, row))
            want = sorted(7000 + k for k, subj in enumerate(subjects)
                          if A.R.bare_subject(subj) == A.R.bare_subject(subjects[0]))
            b.c.execute("delete from msgs where uid between 7000 and 7010 and folder=?", (inbox,))
            b.c.commit()
        self.assertEqual(got, want)
        self.assertEqual(want, [7000, 7001, 7002])

    def test_icon_number_is_off_until_turned_on(self):
        b = self.b
        b.bump()
        self.assertEqual(A.desktop.BADGE.n, 0)                          # off by default
        b.api_prefs({"badge": True})
        unread = next(f for f in b.folder_counts() if f["key"] == "inbox")["unread"]
        self.assertGreater(unread, 0)
        self.assertEqual(A.desktop.BADGE.n, unread)
        b.api_prefs({"badge": False})
        self.assertEqual(A.desktop.BADGE.n, 0)

    def test_sidebar_width_and_window_calls(self):
        b = self.b
        self.assertEqual(b.api_prefs({"side_width": 300})["side_width"], 300)
        self.assertEqual(b.api_prefs({"side_width": 5000})["side_width"], 0)     # out of range: the usual width
        self.assertEqual(b.api_window({"do": "state"}), {"own": False, "max": False})    # no window in the tests
        self.assertEqual(b.api_window({"do": "max"}), {})
        with self.assertRaises(A.ApiError):
            b.api_window({"do": "something-else"})

    def test_badge_text(self):
        self.assertEqual([A.desktop.badge_text(n) for n in (0, 7, 99, 100, 4321)], ["", "7", "99", "99+", "99+"])


if __name__ == "__main__":
    unittest.main()
