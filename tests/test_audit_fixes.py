"""Regression tests for audit issues #89-#114 (PR #1)."""
import contextlib
import datetime as dt
import io
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from email.message import EmailMessage
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import ragdoll as R  # noqa: E402
import ragdoll_app as A  # noqa: E402
from test_app import OwnBackend  # noqa: E402
from test_group_a import NODE, js  # noqa: E402


class AuditCLIFixes(unittest.TestCase):
    def test_96_mutf7_decode_tolerates_raw_ampersand(self):
        self.assertEqual(R.mutf7_decode("R&D-Team"), "R&D-Team")
        self.assertEqual(R.mutf7_decode("A&B-C"), "A&B-C")
        self.assertEqual(R.mutf7_decode("Sales&-Marketing"), "Sales&Marketing")
        self.assertEqual(R.mutf7_decode(R.mutf7("重要邮件")), "重要邮件")

    def test_92_seg_uid_and_header_row_ignore_untrusted_literals(self):
        # BODY[]<0> larger than 4000 bytes before UID, with spoofed UID inside literal
        body_lit = b"UID 99999\r\n" + (b"x" * 5000)
        seg = [b"1 (BODY[]<0> {5011}", body_lit, b" UID 42)"]
        self.assertEqual(R.seg_uid(seg), 42)

        # BODY[HEADER] before BODYSTRUCTURE, plus spoofed FLAGS/INTERNALDATE/RFC822.SIZE in Subject
        hdr = (
            b"From: a@example.com\r\n"
            b"To: b@example.com\r\n"
            b"Date: Thu, 26 Nov 2026 10:00:00 +0800\r\n"
            b"Subject: FLAGS (\\Seen \\Flagged \\Answered) INTERNALDATE \"01-Jan-2035 00:00:00 +0000\" "
            b"RFC822.SIZE 99999999\r\n"
            b"Message-ID: <spoof@example.com>\r\n\r\n"
        )
        bs = (b' BODYSTRUCTURE (("TEXT" "PLAIN" NIL NIL NIL "7BIT" 10 1) '
              b'("APPLICATION" "PDF" ("NAME" "invoice.pdf") NIL NIL "BASE64" 100 NIL '
              b'("ATTACHMENT" ("FILENAME" "invoice.pdf")))) '
              b'FLAGS () INTERNALDATE "26-Nov-2026 02:00:00 +0000" RFC822.SIZE 512)')
        seg2 = [b"1 (UID 7 BODY[HEADER] {%d}" % len(hdr), hdr, bs]
        row = R.header_row(seg2)
        self.assertEqual(row["atts"], "invoice.pdf")
        self.assertEqual(row["size"], 512)
        self.assertEqual(row["flags"], (0, 0, 0))
        self.assertLess(row["ts"], 2000000000)

    def test_95_and_101_build_message_cid_octet_stream_and_leaf_parts(self):
        # Original mail with cid: application/octet-stream (nameless binary) + attached .eml with hijacking cid:
        orig = EmailMessage()
        orig["From"] = "alice@example.com"
        orig["To"] = "bob@example.com"
        orig["Subject"] = "Hi"
        orig["Message-ID"] = "<orig@example.com>"
        orig.set_content("Hello")
        orig.add_alternative('<p><img src="cid:rawbin@x"><img src="cid:inner@x"></p>', subtype="html")
        hpart = orig.get_body(("html",))
        hpart.add_related(b"\x00\x01\x02\x03", "application", "octet-stream", cid="<rawbin@x>")
        # Attached .eml carrying a different cid:inner@x
        inner = EmailMessage()
        inner["From"] = "evil@example.com"
        inner["Subject"] = "Inner"
        inner.set_content("inner")
        inner.add_alternative('<img src="cid:inner@x">', subtype="html")
        inner.get_body(("html",)).add_related(b"\x89PNG\r\n\x1a\n1234", "image", "png", cid="<inner@x>")
        orig.add_attachment(inner)
        # Must not crash with ValueError on octet-stream, and must not copy inner .eml's cid
        built = R.build_message("<p>Reply</p>", [("", "alice@example.com")], [], "Re: Hi", orig=orig, mode="reply")
        cids = {p.get("Content-ID").strip("<>") for p in R.leaf_parts(built) if p.get("Content-ID")}
        self.assertIn("rawbin@x", cids)
        self.assertNotIn("inner@x", cids)

    def test_99_light_mail_uppercase_content_id(self):
        # Verify is_inline and cid matching are case-insensitive
        p = EmailMessage()
        p.set_content(b"\x89PNG\r\n\x1a\nxxxx", maintype="image", subtype="png", disposition="attachment",
                      cid="<IMAGE001@EXMAIL>")
        self.assertTrue(R.is_inline(p, {"image001@exmail"}))
        self.assertTrue(R.is_inline(p, {"IMAGE001@EXMAIL"}))

    def test_98_clean_quoted_html_preserves_prose_around_body_tag(self):
        html = "<p>Intro mentioning <body> tag</p><p>After </body> prose</p>"
        cleaned = R.clean_quoted_html(html)
        self.assertIn("Intro mentioning", cleaned)
        self.assertIn("prose", cleaned)
        doc = "<!doctype html><html><head><meta charset=gb2312></head><body><p>Real body</p></body></html>"
        self.assertEqual(R.clean_quoted_html(doc).strip(), "<p>Real body</p>")

    def test_97_concurrent_cache_put(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "a", "item.eml")
            errs = []

            def worker(i):
                try:
                    for _ in range(10):
                        R.cache_put(p, ("payload-%d" % i).encode())
                except Exception as e:
                    errs.append(e)
            ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(errs, [])
            self.assertTrue(os.path.isfile(p))

    def test_105_deep_flags_ignores_highestmodseq_zero(self):
        with tempfile.TemporaryDirectory() as td:
            old_home = R.CFG.d["data_dir"]
            R.CFG.d["data_dir"] = td
            try:
                c = R.db()
                c.execute("insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,answered) "
                          "values('INBOX',1,1,'','','',100,'a','b','','s','','',0,0,0)")
                c.commit()
                local = {r["uid"]: r for r in c.execute("select uid,id,seen,flagged,answered from msgs")}
                flags = R.Flags(c, "INBOX", local, None)

                class FakeM:
                    capabilities = (b"CONDSTORE",)
                    untagged_responses = {}
                    calls = []

                    def status(self, folder, what):
                        return "OK", [b'"INBOX" (HIGHESTMODSEQ 0)']

                    def uid(self, cmd, *args):
                        self.calls.append((cmd, args))
                        if cmd == "SEARCH":
                            return "OK", [b""]
                        return "OK", [b""]

                m = FakeM()
                R.deep_flags(m, c, "INBOX", 1, [1], flags)
                R.deep_flags(m, c, "INBOX", 1, [1], flags)
                searches = [x for x in m.calls if x[0] == "SEARCH"]
                self.assertGreaterEqual(len(searches), 4)   # ran sweep on both passes, never stalled on 0==0
                c.close()
            finally:
                R.CFG.d["data_dir"] = old_home

    def test_107_search_nul_byte_and_short_non_ascii_case(self):
        with tempfile.TemporaryDirectory() as td:
            old_home = R.CFG.d["data_dir"]
            R.CFG.d["data_dir"] = td
            c = R.db()
            try:
                c.execute("insert into msgs(folder,uidv,uid,msgid,irt,refs,ts,frm,to_,cc,subject,atts,body,seen,flagged,answered) "
                          "values('INBOX',1,1,'<1>','','',100,'a','b','','Ölpreis steigt','','hello',0,0,0)")
                c.execute("insert into fts(rowid,subject,frm,to_,atts,body) values(1,'Ölpreis steigt','a','b','','hello')")
                c.commit()
                ns = SimpleNamespace(limit=20, offset=0, folder=None, from_=None, to=None, since=None, until=None,
                                     unread=False, starred=False, att=False)
                # NUL byte must not crash FTS5
                rows = R.search_rows(c, ["hello\x00world"], ns)
                self.assertIsInstance(rows, list)
                # 2-char non-ASCII case-insensitive match
                rows2 = R.search_rows(c, ["öl"], ns)
                self.assertEqual(len(rows2), 1)
            finally:
                c.close()
                R.CFG.d["data_dir"] = old_home

    def test_112_empty_rfc822_part(self):
        p = EmailMessage()
        p["Content-Type"] = "message/rfc822"
        p.set_payload([])
        self.assertEqual(R.fname(p), "attached mail.eml")
        self.assertEqual(R.part_bytes(p), b"")

    def test_113_table_problems_and_check_message(self):
        # Single-quoted colspan and single-counted TBC
        html = '<table style="word-break:normal"><tr><td colspan=\'3\'>Header</td></tr><tr><td>TBC</td><td>1</td><td>2</td></tr></table>'
        probs = R.table_problems(html, -1, False)
        self.assertTrue(any("3-column table" in p for p in probs))
        self.assertTrue(any(p.startswith("1 blank/—/TBC") for p in probs), probs)

        # Bcc-only mail should not fail "To is empty"; prose "From:" should not trigger quote_at before signature
        old_marks = R.CFG.d.get("signature_marks", [])
        R.CFG.d["signature_marks"] = ["Best regards"]
        try:
            msg = R.build_message("<p>From: Shanghai to Berlin</p>", [], [], "Notice", bcc=[("", "secret@example.com")],
                                  signature_html="<p>Best regards</p>")
            probs2 = R.check_message(msg, reply=False, required_cc=False)
            self.assertNotIn("To is empty", probs2)
            self.assertFalse(any("signature" in p for p in probs2))
        finally:
            R.CFG.d["signature_marks"] = old_marks

    def test_114_bs_names_prefix_and_print_rows_limit_zero(self):
        blob = (b'("APPLICATION" "PDF" NIL NIL NIL "BASE64" 1 NIL ("ATTACHMENT" ("FILENAME" "Commercial_Invoice_2026.pdf"))) '
                b'("APPLICATION" "OCTET-STREAM" NIL NIL NIL "BASE64" 1 NIL ("ATTACHMENT" ("FILENAME" "Commercial_Invoice_2026.pdf.sig")))')
        self.assertEqual(R.bs_names(blob), ["Commercial_Invoice_2026.pdf", "Commercial_Invoice_2026.pdf.sig"])

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.print_rows([], False, total=5)
        self.assertNotIn("(nothing found)", buf.getvalue())
        self.assertIn("showing the newest 0 of 5", buf.getvalue())


class AuditAppFixes(OwnBackend):
    def test_89_unmove_exmail_verifies_message_id_and_preserves_token_on_error(self):
        r = self.b.q("select uid, msgid from msgs where folder='INBOX' and msgid != '' limit 1")[0]
        i, mid = A.R.make_id("INBOX", r["uid"]), r["msgid"]
        self.online()

        class ExmailSrv(type(self.server)):
            def __init__(self):
                super().__init__()
                self.fail_once = True

            def uid(self, *args):
                self.calls.append(("uid",) + args)
                if args[0] == "SEARCH":
                    # Exmail ignores HEADER filter and returns every UID in Archive
                    return "OK", [b"1 2 3 4 5"]
                if args[0] == "FETCH":
                    if self.fail_once:
                        self.fail_once = False
                        raise OSError("dropped")
                    return "OK", [
                        (b"1 (UID 1 BODY[HEADER.FIELDS (MESSAGE-ID)] {30}", b"Message-ID: <other1@x>\r\n\r\n"),
                        b")",
                        (b"5 (UID 5 BODY[HEADER.FIELDS (MESSAGE-ID)] {%d}" % (len(mid) + 16),
                         ("Message-ID: %s\r\n\r\n" % mid).encode()),
                        b")",
                    ]
                return "OK", [b""]

        srv = ExmailSrv()
        self.server = srv
        self.b.imap = lambda fn: fn(srv)
        self.b.folders = lambda m: [A.R.CFG.folders["archive"], "INBOX"]
        self.patch(A.R, "has_cap", lambda m, c: True)
        self.patch(A.R, "use", lambda m, f, write=False: None)
        out = self.b.api_move({"ids": [i], "to": "archive"})
        # First unmove attempt fails transiently -> undo token must NOT be lost
        with self.assertRaises(OSError):
            self.b.api_unmove({"token": out["undo"]})
        # Second attempt succeeds and moves ONLY UID 5 (not 1..4)
        res = self.b.api_unmove({"token": out["undo"]})
        self.assertEqual(res["moved"], 1)
        moves = [c for c in srv.calls if c[:2] == ("uid", "MOVE")]
        self.assertEqual(moves[-1][2:], ("5", A.R.q("INBOX")))

    def test_90_cancelled_send_cannot_be_sent_by_send_wait(self):
        d = self.b.api_save_draft({"to": ["a@example.com"], "subject": "Hold", "html": "<p>x</p>"})["id"]
        self.b.api_send({"id": d, "delay": 30})
        self.assertEqual(self.b.api_send_cancel({"id": d}), {"cancelled": True})
        res = self.b.api_send_wait({"id": d})
        self.assertFalse(res.get("sent"))
        self.assertTrue(res.get("cancelled"))

    def test_91_ssrf_blocked_in_unsubscribe(self):
        with self.assertRaises(A.ApiError):
            A.check_public_url("https://127.0.0.1/unsub", https_only=True)
        with self.assertRaises(A.ApiError):
            A.check_public_url("https://169.254.169.254/latest", https_only=True)
        with self.assertRaises(A.ApiError):
            A.check_public_url("http://127.0.0.1/unsub", https_only=True)
        with mock.patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]):
            A.check_public_url("https://example.com/unsub", https_only=True)

    def test_93_reopen_draft_recovers_missing_upload_attachments(self):
        up = self.b.keep_file("report.txt", b"important data")
        d = self.b.api_save_draft({"to": ["a@example.com"], "subject": "With file", "html": "<p>hi</p>",
                                   "atts": [up]})["id"]
        os.remove(up["path"])   # simulate cleaned uploads/ or another machine
        reopened = self.b.api_compose({"mode": "draft", "id": d})
        self.assertEqual(len(reopened["atts"]), 1)
        self.assertEqual(reopened["atts"][0]["name"], "report.txt")
        self.assertTrue(os.path.isfile(reopened["atts"][0]["path"]))

    def test_94_and_106_ics_malformed_and_vtimezone(self):
        # Malformed DTEND, huge INTERVAL, pre-1970 DTSTART must never crash invite_of
        for ics in (
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20260228\r\nDTEND;VALUE=DATE:20260230\r\nSUMMARY:Bad end\r\nEND:VEVENT\r\nEND:VCALENDAR",
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20200101T100000Z\r\nRRULE:FREQ=DAILY;INTERVAL=999999999\r\nSUMMARY:Huge\r\nEND:VEVENT\r\nEND:VCALENDAR",
            "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:19600101T100000\r\nSUMMARY:Old\r\nEND:VEVENT\r\nEND:VCALENDAR",
        ):
            m = EmailMessage()
            m.set_content(ics, subtype="calendar")
            out = A.invite_of(m)
            self.assertIsNotNone(out)

        # VTimezone without RRULE after >1 year must return TZOFFSETTO, not TZOFFSETFROM
        cal = A.ics_parse(
            "BEGIN:VCALENDAR\r\nBEGIN:VTIMEZONE\r\nTZID:Custom/Perm\r\n"
            "BEGIN:STANDARD\r\nDTSTART:20141026T020000\r\nTZOFFSETFROM:+0400\r\nTZOFFSETTO:+0300\r\nEND:STANDARD\r\n"
            "END:VTIMEZONE\r\nEND:VCALENDAR"
        )
        vt = A.ics_zones(cal)["Custom/Perm"]
        self.assertEqual(vt.offset_at(dt.datetime(2026, 6, 1, 12, 0))[0], 3 * 3600)

    def test_98_and_102_page_html_embed_events_and_multi_url_css(self):
        out = A.page_html('<p>Before</p><embed src="x.swf"><p>After</p><img/onerror=alert(1)>'
                          '<a href="https://example.com/?a=1 onclick=2">link</a>', {})
        self.assertIn("Before", out)
        self.assertIn("After", out)
        self.assertNotIn("onerror", out.lower())
        self.assertIn("https://example.com/?a=1", out)

        bad = "background: url(https://ok.com/a.png), url(data:image/svg+xml;base64,PHN2Zz4=); color: red"
        self.assertEqual(A.clean_style(bad), "color: red")
        if NODE:
            self.assertEqual(js("K.cleanStyle(%s)" % json.dumps(bad)), "color: red")

    def test_100_search_in_junk_and_empty_quotes(self):
        junk = A.R.CFG.folders["junk"]
        raw = A.demo_message("junk", int(time.time()), ("Spam", "s@example.com"), [("Me", "me@example.com")],
                             [], "SpecialJunkToken", "body", [], "<j1@example.com>", None, None)
        self.b.demo_insert(junk, raw, int(time.time()), 0, 0)
        self.assertEqual(len(self.b.api_search({"q": "in:junk SpecialJunkToken"})["rows"]), 1)
        self.assertEqual(self.b.api_search({"q": '""'})["rows"], [])

    def test_101_attached_eml_does_not_hijack_parent_invite(self):
        parent = EmailMessage()
        parent["From"] = "a@example.com"
        parent["Subject"] = "Forwarding old mail"
        parent.set_content("See attached.")
        inner = EmailMessage()
        inner["From"] = "org@example.com"
        inner["Subject"] = "Old meeting"
        inner.set_content("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART:20261201T100000Z\r\nSUMMARY:Hijack\r\nEND:VEVENT\r\nEND:VCALENDAR",
                          subtype="calendar")
        parent.add_attachment(inner)
        self.assertIsNone(A.invite_of(parent))

    def test_104_reserved_folder_name_rejected(self):
        for bad in ("Scheduled", "Flagged", "Trash"):
            with self.assertRaises(A.ApiError):
                self.b.api_folder_new({"name": bad})

    def test_108_plain_html_nbsp_and_signature_data_image(self):
        self.assertNotIn("&nbsp;", A.plain_html("Hi&nbsp;there"))
        png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        self.b.api_save_signatures({"signatures": [{"id": "s1", "name": "Logo", "html": '<img src="%s">' % png}],
                                    "sig_new": "s1", "sig_reply": "s1"})
        msg = self.b.build({"to": ["a@example.com"], "subject": "Sig", "html": "<p>Hi</p>", "sig_id": "s1"})
        html = A.R.bodies(msg)[1]
        self.assertNotIn("data:image/png", html)
        self.assertIn("cid:", html)

    def test_109_validation_and_prefs(self):
        self.assertEqual(self.b.call("mark", {"ids": ["inbox:1"], "flag": "bogus"})[0], 200)
        self.assertFalse(self.b.call("mark", {"ids": ["inbox:1"], "flag": "bogus"})[1]["ok"])
        self.assertEqual(self.b.call("attachment", {"id": "inbox:1", "i": "abc"})[0], 200)
        self.assertFalse(self.b.call("attachment", {"id": "inbox:1", "i": "abc"})[1]["ok"])
        self.assertEqual(self.b.call("save_draft", {"to": 123})[0], 200)
        self.assertFalse(self.b.call("save_draft", {"to": 123})[1]["ok"])
        p = self.b.api_prefs({"theme": {"evil": 1}, "sidebar": [1, 2]})
        self.assertNotEqual(p.get("theme"), {"evil": 1})
        self.assertNotEqual(p.get("sidebar"), [1, 2])


if __name__ == "__main__":
    unittest.main()
