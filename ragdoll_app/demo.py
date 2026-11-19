"""The made-up mailbox behind --demo (also what the tests and the screenshots use)."""

import atexit
import datetime as dt
import json
import os
import shutil
import tempfile
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate

import ragdoll as R
from .message import index_raw


# ------------------------------------------------------------------ demo mailbox

def demo_png(rgb, w=240, h=120):
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def demo_pdf(title):
    text = "BT /F1 18 Tf 72 720 Td (%s) Tj ET" % title.replace("(", "").replace(")", "")
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            "<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for k, o in enumerate(objs, 1):
        offs.append(len(out))
        out += "%d 0 obj\n%s\nendobj\n" % (k, o)
    xref = len(out)
    out += "xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + "".join("%010d 00000 n \n" % x for x in offs)
    out += "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out.encode()


ME = ("Alex Morgan", "you@example.com")


DEMO_FLAGGED = ("Quote for PO-1234",)


DEMO = [
    # (folder, minutes ago, from, to, cc, subject, body, attachments, seen, thread key, reply-to key)
    ("inbox", 14, ("Jane Doe", "jane.doe@acme-industrial.com"), [ME], [("Tom Becker", "tom.becker@acme-industrial.com")],
     "Quote for PO-1234",
     "Hi Alex,\n\nThanks for the quick turnaround. I've attached the signed quote for PO-1234 and the updated "
     "delivery schedule.\n\nCould you confirm the ship date for the first batch? Our site team would like to plan "
     "the installation for the week of the 8th.\n\nBest regards,\nJane Doe\nProcurement Manager, Acme Industrial"
     "\n\nOn Monday, Alex Morgan <you@example.com> wrote:\n> Hi Jane,\n>\n> Please find our quote for PO-1234 "
     "attached. Lead time is 6 weeks from order.\n>\n> Best regards,\n> Alex",
     [("Quote_PO-1234_signed.pdf", "pdf"), ("Delivery_schedule.xlsx", "bin")], False, "po", "po1"),
    ("inbox", 52, ("Li Ming", "li.ming@example.cn"), [ME], [],
     "北京ABC项目 — 图纸确认",
     "Alex 你好，\n\n附件是北京ABC项目的最新图纸，请在周五前确认尺寸和接线方式。如有问题请随时联系我。\n\n谢谢！\n李明",
     [("ABC项目_总装图_rev3.pdf", "pdf")], False, None, None),
    ("inbox", 130, ("GitHub", "noreply@github.com"), [ME], [],
     "[ragdoll-mail] Release v0.5.0 published",
     "A new release is out.\n\nragdoll-mail v0.5.0: the desktop app.\n\nView it on GitHub: "
     "https://github.com/", [], True, None, None),
    ("inbox", 60 * 5, ("Sara Kim", "sara.kim@northwind.io"), [ME], [],
     "Lunch on Thursday?",
     "Hey Alex,\n\nAre you around on Thursday? There's a new ramen place near the office I've been meaning to try.\n\n"
     "Sara", [], False, "lunch", None),
    ("inbox", 60 * 9, ("Daniel Ruiz", "d.ruiz@contoso.com"), [ME], [],
     "Re: Site visit photos",
     "Photos from yesterday's visit are below. The cabinet on the left needs a new door seal.\n\nDaniel",
     [], True, None, None),
    ("inbox", 60 * 26, ("Northwind Billing", "billing@northwind.io"), [ME], [],
     "Your invoice INV-0006 is ready",
     "Hello,\n\nYour invoice INV-0006 for November is attached. The amount will be charged on the 30th.\n\n"
     "Northwind Billing", [("INV-0006.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 30, ("Tom Becker", "tom.becker@acme-industrial.com"), [ME], [],
     "Packing list for the November shipment",
     "Hi Alex,\n\nPlease find the packing list attached. Gross weight is 1,240 kg across 3 crates.\n\nTom",
     [("Packing_list_Nov.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 50, ("Priya Natarajan", "priya@fabrikam.com"), [ME], [("Jane Doe", "jane.doe@acme-industrial.com")],
     "Meeting notes — Q4 planning",
     "Hi all,\n\nNotes from today:\n\n1. Q4 targets confirmed.\n2. New supplier onboarding starts in December.\n"
     "3. Next review on the 2nd.\n\nPriya", [], True, None, None),
    ("inbox", 60 * 75, ("Sara Kim", "sara.kim@northwind.io"), [ME], [],
     "Slides for Friday",
     "Here are the slides for Friday's review. Feedback welcome before Thursday noon.",
     [("Friday_review.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 100, ("Hannah Weber", "h.weber@example.de"), [ME], [],
     "Certificate of origin",
     "Dear Alex,\n\nCould you send the certificate of origin for order 4471? Customs is asking for it.\n\n"
     "Kind regards,\nHannah Weber", [], True, None, None),
    ("inbox", 60 * 140, ("王芳", "wang.fang@example.cn"), [ME], [],
     "下周培训安排",
     "各位好，\n\n下周三下午两点在三楼会议室进行产品培训，请准时参加。\n\n王芳", [], True, None, None),
    ("inbox", 60 * 200, ("Marco Rossi", "marco.rossi@example.it"), [ME], [],
     "Spare parts list",
     "Ciao Alex,\n\nAttached is the list of spare parts we need for next year.\n\nMarco",
     [("spare_parts_2027.pdf", "pdf")], True, None, None),
    ("inbox", 60 * 260, ("Jane Doe", "jane.doe@acme-industrial.com"), [ME], [],
     "Welcome to the Acme supplier portal",
     "Hi Alex,\n\nYour supplier portal account is ready. You can upload invoices and certificates there.\n\nJane",
     [], True, None, None),
    ("sent", 60 * 28, ME, [("Jane Doe", "jane.doe@acme-industrial.com")], [],
     "Quote for PO-1234",
     "Hi Jane,\n\nPlease find our quote for PO-1234 attached. Lead time is 6 weeks from order.\n\n"
     "Best regards,\nAlex", [("Quote_PO-1234.pdf", "pdf")], True, "po", "po0"),
    ("sent", 60 * 4, ME, [("Sara Kim", "sara.kim@northwind.io")], [],
     "Re: Lunch on Thursday?", "Sounds great, 12:30 works for me.\n\nAlex", [], True, "lunch", None),
    ("sent", 60 * 98, ME, [("Hannah Weber", "h.weber@example.de")], [],
     "Re: Certificate of origin", "Dear Hannah,\n\nThe certificate is attached.\n\nBest regards,\nAlex",
     [("CO_order_4471.pdf", "pdf")], True, None, None),
    ("drafts", 40, ME, [("Li Ming", "li.ming@example.cn")], [],
     "Re: 北京ABC项目 — 图纸确认", "李明你好，\n\n图纸已收到，尺寸没有问题。接线方式我们明天确认后回复。\n\nAlex",
     [], True, None, None),
    ("archive", 60 * 24 * 12, ("Acme Industrial", "news@acme-industrial.com"), [ME], [],
     "Acme Industrial newsletter — October", "Our October news: new plant, new products, and a new website.",
     [], True, None, None),
    ("archive", 60 * 24 * 20, ("Tom Becker", "tom.becker@acme-industrial.com"), [ME], [],
     "Shipping marks", "Hi Alex, please use the attached shipping marks on every crate.\n\nTom",
     [("shipping_marks.pdf", "pdf")], True, None, None),
    ("trash", 60 * 24 * 3, ("Deals Daily", "offers@example.net"), [ME], [],
     "50% off everything this weekend", "Don't miss out!", [], True, None, None),
]


def demo_message(folder, ts, frm, to, cc, subject, body, atts, mid, irt, refs, inline=False):
    msg = EmailMessage()
    msg["From"] = formataddr(frm)
    msg["To"] = ", ".join(formataddr(x) for x in to)
    if cc:
        msg["Cc"] = ", ".join(formataddr(x) for x in cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(ts, localtime=True)
    msg["Message-ID"] = mid
    if irt:
        msg["In-Reply-To"] = irt
        msg["References"] = refs
    msg.set_content(body)
    html = R.text_to_html(body)
    if inline:
        html += '<div><br></div><div><img src="cid:photo1@demo" width="240" height="120" alt="site photo"></div>'
    msg.add_alternative('<div style="font-family:Helvetica,Arial,sans-serif;font-size:14px">%s</div>' % html,
                        subtype="html")
    if inline:
        msg.get_body(("html",)).add_related(demo_png((46, 125, 120)), "image", "png", cid="<photo1@demo>")
    for name, kind in atts:
        if kind == "pdf":
            msg.add_attachment(demo_pdf(name), "application", "pdf", filename=name)
        else:
            msg.add_attachment(b"PK\x03\x04 demo", "application", "octet-stream", filename=name)
    return msg.as_bytes(policy=R.OUT_POLICY)


# ------------------------------------------------------------------ backend

def demo_invite(now):
    """A meeting invite as Outlook sends it: a text part and a text/calendar part with METHOD:REQUEST."""
    day = dt.datetime.fromtimestamp(now + 3 * 86400, dt.timezone.utc).strftime("%Y%m%d")
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "PRODID:-//Example//EN", "VERSION:2.0", "METHOD:REQUEST",
        "BEGIN:VTIMEZONE", "TZID:China Standard Time", "BEGIN:STANDARD", "DTSTART:16010101T000000",
        "TZOFFSETFROM:+0800", "TZOFFSETTO:+0800", "END:STANDARD", "END:VTIMEZONE",
        "BEGIN:VEVENT", "UID:demo-invite-1@acme-industrial.com", "SEQUENCE:0", "DTSTAMP:%sT000000Z" % day,
        'DTSTART;TZID="China Standard Time":%sT140000' % day, 'DTEND;TZID="China Standard Time":%sT150000' % day,
        "SUMMARY:PO-1234 delivery review", "LOCATION:Meeting room 3\\, Building A",
        'ORGANIZER;CN="Jane Doe":mailto:jane.doe@acme-industrial.com',
        'ATTENDEE;CN="Alex Morgan";ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:%s' % ME[1],
        'ATTENDEE;CN="Tom Becker";ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED:mailto:tom.becker@acme-industrial.com',
        "END:VEVENT", "END:VCALENDAR", ""])
    msg = EmailMessage(policy=R.OUT_POLICY)
    msg["From"] = formataddr(("Jane Doe", "jane.doe@acme-industrial.com"))
    msg["To"] = formataddr(ME)
    msg["Subject"] = "PO-1234 delivery review"
    msg["Date"] = formatdate(now - 25 * 60, localtime=True)
    msg["Message-ID"] = "<demo-invite@example.com>"
    msg.set_content("Hi Alex,\n\nLet's go through the delivery plan for PO-1234.\n\nJane")
    msg.add_alternative(ics, subtype="calendar", params={"method": "REQUEST"})
    return msg.as_bytes(policy=R.OUT_POLICY)


class Demo:
    """The demo mailbox. (Part of Backend.)"""

    # ---- demo

    def make_demo(self):
        home = tempfile.mkdtemp(prefix="ragdoll-demo-")
        self.demo_uids = {}
        atexit.register(shutil.rmtree, home, True)
        d = json.loads(json.dumps(R.DEFAULTS))
        d.update({"user": ME[1], "name": ME[0], "data_dir": home, "imap": {"host": "demo", "port": 993},
                  "smtp": {"host": "demo", "port": 465}})
        sig = os.path.join(home, "signature.html")
        with open(sig, "w", encoding="utf-8") as f:
            f.write('<div style="color:#6b6b6b;font-size:13px">Alex Morgan<br>Sales Engineer · Example Co.'
                    '<br>+1 555 0100</div>')
        d["signature"] = sig
        R.CFG = R.Cfg(d)
        self.c = R.db()
        now = int(time.time())
        mids = {}
        for k, (fk, ago, frm, to, cc, subj, body, atts, seen, thread, key) in enumerate(DEMO):
            ts = now - ago * 60
            mid = "<demo-%d@example.com>" % k
            irt = refs = None
            if thread and thread in mids:
                irt = mids[thread]
                refs = irt
            if thread:
                mids[thread] = mid
            raw = demo_message(fk, ts, frm, to, cc, subj, body, atts, mid, irt, refs,
                               inline=subj.startswith("Re: Site visit"))
            self.demo_insert(R.CFG.folders[fk], raw, ts, int(seen), int(fk == "inbox" and thread == "lunch"),
                             int(subj in DEMO_FLAGGED))
        self.demo_order_threads()
        # the user's own folders, and Junk
        self.listed = [(v, "/") for v in R.CFG.folders.values()] + [("Customers", "/"), ("Customers/Acme", "/"),
                                                                     ("Receipts", "/")]
        extra = [("Customers/Acme", 3 * 1440, ("Jane Doe", "jane.doe@acme-industrial.com"), "Site access for the 8th",
                  "Hi Alex,\n\nGate 3 is open from 07:00. Ask for Tom at the desk.\n\nJane", 1),
                 ("Receipts", 5 * 1440, ("Northwind Billing", "billing@northwind.example"), "Receipt for INV-0005",
                  "Thank you. We received your payment for INV-0005.", 1),
                 ("Receipts", 1440, ("City Parking", "noreply@cityparking.example"), "Your parking receipt",
                  "Receipt P-20391. Paid by card.", 0),
                 (R.CFG.folders["junk"], 2 * 1440, ("Prize Team", "win@lucky-draw.example"), "You have won!",
                  "Claim your prize today.", 0)]
        for k, (folder, ago, frm, subj, body, seen) in enumerate(extra):
            raw = demo_message("inbox", now - ago * 60, frm, [ME], [], subj, body, [], "<demo-x%d@example.com>" % k,
                               None, None)
            self.demo_insert(folder, raw, now - ago * 60, seen, 0)

        self.demo_insert(R.CFG.folders["inbox"], demo_invite(now), now - 25 * 60, 0, 0)

    def demo_order_threads(self):
        # the demo list is made oldest-thread-first above; nothing else to do, kept for clarity
        return

    def demo_insert(self, folder, raw, ts, seen, answered, flagged=0):
        with self.dblock:
            r = self.c.execute("select coalesce(max(uid),0)+1 from msgs where folder=?", (folder,)).fetchone()
            uid = max(r[0], self.demo_uids.get(folder, 0) + 1)
            self.demo_uids[folder] = uid
            index_raw(self.c, folder, 1, uid, raw, ts, seen, answered, flagged)
        self.demo_raw[(folder, uid)] = raw
        return uid

    def demo_delete(self, i):
        f, u = self.parse(i)
        self.demo_raw.pop((f, u), None)
        with self.dblock:
            self.db_delete(i)
