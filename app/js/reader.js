// The reading pane: a conversation and its mails.
import { $, $$, api, el, esc, icon, iconBtn, LOCALE, MOD, SYS_TZ, t, tr, TZ } from "./core.js";
import { binned, FOLDER_ICON, S } from "./state.js";
import { dayKey, fileIcon, fmt, HM, initials, laterTime, longTime, nameOf, shortTime, size, who, zepoch } from "./format.js";
import { fail, menu, toast } from "./ui.js";
import { loadList, markRow } from "./list.js";
import { moveMail, rowOf, selectRow, syncSel, toggleFlag, toggleUnread } from "./actions.js";
import { mailFrame } from "./frames.js";
import { openCompose } from "./compose.js";
import { closeCompose, discardCompose, fmtBarOn, pickFiles, sendCompose, sendWithUndo, toggleFmtBar } from "./editor.js";
import { templateMenu } from "./templates.js";
import { laterMenu } from "./later.js";
import { refreshCounts } from "./status.js";

function goBack() {
  if (S.compose) closeCompose();
  else { S.sel = null; syncSel(); showEmpty(); $("#rows").focus({ preventScroll: true }); }
}

export function showEmpty() {
  S.thread = null; S.focus = null; S.sched = null; S.multi.clear();
  $("#pane").innerHTML = `<div class="pane-empty"><img src="logo.png" alt=""></div>`;
  renderToolbar();
}

export function renderToolbar() {
  const tools = $("#tools"), end = $("#tools-end");
  tools.replaceChildren(); end.replaceChildren();
  $("#toolbar").classList.toggle("lined", $("#pane").scrollTop > 0);
  $("#app").classList.toggle("reading", !!(S.compose || S.sched || S.thread || S.multi.size > 1));
  tools.append(iconBtn("arrow-left", t("back"), goBack, { key: "Esc", cls: "back-btn" }));
  if (S.compose) {
    tools.append(
      iconBtn("send", t("send"), () => sendCompose(), { key: MOD + "↩", disabled: !!S.compose.busy, cls: "accent" }),
      iconBtn("calendar-clock", t("send_later"), (e) => laterMenu(e.currentTarget), { disabled: !!S.compose.busy }),
      el("span", { class: "sep" }),
      iconBtn("paperclip", t("attach"), () => pickFiles()),
      iconBtn("file-text", t("templates"), (e) => templateMenu(e.currentTarget)),
      iconBtn("type", t("formatting"), toggleFmtBar, { cls: fmtBarOn() ? "on" : "" }),
    );
    end.append(el("span", { class: "compose-status", id: "compose-status" }, S.compose.status || ""),
      iconBtn("trash-2", t("discard"), () => discardCompose()));
    return;
  }
  if (S.sched) {
    const r = S.sched;
    tools.append(
      iconBtn("send", t("send_now"), () => sendNow(r), { cls: "accent" }),
      iconBtn("square-pen", t("edit"), () => editScheduled(r)),
    );
    end.append(iconBtn("calendar-x", t("dont_send"), () => dontSend(r)));
    return;
  }
  if (S.multi.size > 1) {
    const ids = [...S.multi], rows = ids.map(rowOf).filter(Boolean);
    const inTrash = rows.every(binned), anyUnread = rows.some((x) => x.unread), allFlagged = rows.every((x) => x.flagged);
    tools.append(
      inTrash ? iconBtn("inbox", t("restore"), () => moveMail(ids, "inbox"))
        : iconBtn("archive", t("archive_it"), () => moveMail(ids, "archive"), { key: "E" }),
      iconBtn("trash-2", t("trash_it"), () => moveMail(ids, "trash"), { key: "#", disabled: inTrash }),
      moveBtn(ids), snoozeBtn(ids),
      iconBtn(anyUnread ? "mail-open" : "mail", anyUnread ? t("read") : t("unread"), toggleUnread, { key: "U" }),
      iconBtn("star", allFlagged ? t("unflag") : t("flag"), toggleFlag, { key: "S", cls: allFlagged ? "on" : "" }),
    );
    return;
  }
  const has = !!S.thread;
  const id = S.focus || S.sel;
  const r = S.thread?.rows.find((x) => x.id === id);
  const inTrash = binned(r);
  tools.append(
    inTrash
      ? iconBtn("inbox", t("restore"), () => moveMail([id], "inbox"), { disabled: !has })
      : iconBtn("archive", t("archive_it"), () => moveMail([id], "archive"), { key: "E", disabled: !has || r?.folder === "archive" }),
    iconBtn("trash-2", t("trash_it"), () => moveMail([id], "trash"), { key: "#", disabled: !has || inTrash }),
    moveBtn(has ? [id] : []), snoozeBtn(has ? [id] : []),
    iconBtn("star", r?.flagged ? t("unflag") : t("flag"), toggleFlag, { key: "S", disabled: !has, cls: r?.flagged ? "on" : "" }),
  );
  // reply, reply all and forward are on the mail itself (and R, A, F); unread is the U key
}

// Snooze: out of the Inbox until a time, then back on top and unread. In Snoozed, the button brings it back now.
function snoozeBtn(ids) {
  if (S.folder === "snoozed" && !S.query) return iconBtn("inbox", t("restore"), () => snoozeMail(ids, 0), { disabled: !ids.length });
  if (!ids.length || !ids.every((i) => rowOf(i)?.folder === "inbox")) return "";
  const b = iconBtn("alarm-clock", t("snooze"), () => laterMenu(b, (ts) => snoozeMail(ids, ts), { snooze: true }), { key: "B" });
  b.dataset.snooze = "";
  return b;
}
export async function snoozeMail(ids, until) {
  try { await api("snooze", { ids, until }); } catch (e) { return fail(e); }
  if (until) {
    toast(t("snoozed_until", laterTime(until)), { ms: 6000, action: { label: t("undo"), run: () => api("snooze", { ids, until: 0 }).then(() => { refreshCounts(); loadList({ quiet: true }); }).catch(fail) } });
  }
  if (ids.includes(S.sel) || ids.some((i) => S.multi.has(i))) { S.sel = null; S.multi.clear(); showEmpty(); }
  refreshCounts();
  loadList({ quiet: true });
}

// Move to…: the Inbox, Archive, Junk and the user's own folders (shown only when there is one of those)
function moveBtn(ids) {
  const own = S.boot.folders.filter((f) => f.custom || f.key === "junk");
  if (!own.length) return "";
  const from = new Set(ids.map((i) => rowOf(i)?.folder));
  const b = iconBtn("folder", t("move_to"), () => menu(b, S.boot.folders
    .filter((f) => ["inbox", "archive", "junk"].includes(f.key) || f.custom)
    .filter((f) => !(from.size === 1 && (from.has(f.key) || from.has(f.key.slice(2)))))
    .map((f) => ({ icon: f.custom ? "folder" : FOLDER_ICON[f.key], label: f.custom ? f.key.slice(2) : t(f.key), run: () => moveMail(ids, f.key) }))), { disabled: !ids.length });
  return b;
}

let threadSeq = 0;
export async function openThread(id) {
  const seq = ++threadSeq;
  S.focus = id; S.sched = null;
  let th;
  try { th = await api("thread", { id }); } catch (e) { if (seq === threadSeq) { fail(e); showEmpty(); } return; }
  if (seq !== threadSeq) return;
  S.thread = th;
  const doc = el("div", { class: "doc" }, el("h1", { class: "doc-subject", dir: "auto" }, th.subject || t("no_subject")));
  // newest on top; the reply buttons sit right under the open message, older mail below
  const rows = [...th.rows].reverse();
  const openId = rows.some((r) => r.id === id) ? id : rows[0]?.id;
  const act = (ic, label, mode) => el("button", { class: "btn", onclick: () => openCompose({ mode, id: S.focus || id }), html: icon(ic, "small") + esc(label) });
  for (const r of rows) {
    doc.append(msgNode(r, r.id === openId));
    if (r.id === openId) doc.append(el("div", { class: "doc-acts" }, act("reply", t("reply"), "reply"), act("reply-all", t("replyall"), "replyall"), act("forward", t("forward"), "forward")));
  }
  $("#pane").replaceChildren(doc);
  $("#pane").scrollTop = 0;
  renderToolbar();
  const open = $(`.msg[data-id="${CSS.escape(id)}"]`);
  if (open && openId !== rows[0].id) requestAnimationFrame(() => { $("#pane").scrollTop = Math.max(0, open.offsetTop - 70); });
}

// a draft waiting to go out: when, and what can still be done with it
let schedSeq = 0;
// whatever is still loading for the reader no longer counts
export function stopLoads() { threadSeq++; schedSeq++; }
export async function openScheduled(r) {
  const seq = ++schedSeq;
  S.thread = null; S.focus = r.id; S.sched = r;
  const zone = TZ || SYS_TZ;
  const card = el("div", { class: "sched-card" + (r.sched_error ? " err" : "") },
    el("span", { class: "sched-ic", html: icon(r.sched_error ? "triangle-alert" : r.waiting ? "cloud-off" : "calendar-clock") }),
    el("div", { class: "sched-text" },
      el("div", { class: "sched-when" }, r.waiting ? t("waiting_long") : t("sends_at", longTime(r.sched))),
      el("div", { class: "sched-sub" }, r.sched_error ? t("not_sent", tr(r.sched_error)) : r.waiting ? t("keep_open") : zone.replace(/_/g, " ") + " · " + t("keep_open"))),
    el("div", { class: "sched-acts" },
      el("button", { class: "btn", onclick: () => editScheduled(r), html: icon("square-pen", "small") + esc(t("edit")) }),
      el("button", { class: "btn primary", onclick: () => sendNow(r), html: icon("send", "small") + esc(t("send_now")) })));
  const to = [...r.to, ...(r.cc || [])];
  const doc = el("div", { class: "doc" }, el("h1", { class: "doc-subject", dir: "auto" }, r.subject || t("no_subject")), card,
    el("div", { class: "sched-to" }, t("to") + " " + to.map(who).join(", ")));
  const body = el("div", { class: "msg-body" }, el("div", { class: "rows-more" }, el("span", { html: icon("loader-circle", "spin") })));
  doc.append(body);
  $("#pane").replaceChildren(doc);
  $("#pane").scrollTop = 0;
  renderToolbar();
  try {
    const m = r.id.startsWith("outbox:") ? await api("outbox", { do: "message", id: r.id }) : await api("message", { id: r.id });
    if (seq === schedSeq && body.isConnected) renderBody(body, m);
  } catch (e) { if (seq === schedSeq) body.replaceChildren(el("div", { class: "form" }, el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) }))); }
}

export async function afterSchedule() {
  refreshCounts();
  if (["drafts", "scheduled"].includes(S.folder) || S.query) await loadList({ quiet: true });
}

export async function dontSend(r) {
  if (!r) return;
  if (r.id.startsWith("outbox:")) return editScheduled(r);       // it has no draft yet: back to the editor, nothing is lost
  try { await api("unschedule", { id: r.id }); } catch (e) { return fail(e); }
  if (S.sched?.id === r.id || S.sel === r.id) { S.sel = null; showEmpty(); }
  toast(t("moved_to_drafts"), { action: { label: t("undo"), run: () => api("schedule", { id: r.id, at: r.sched }).then(afterSchedule).catch(fail) } });
  afterSchedule();
}

async function editScheduled(r) {
  if (r.id.startsWith("outbox:")) { await openCompose({ mode: "outbox", id: r.id }); return afterSchedule(); }
  try { await api("unschedule", { id: r.id }); } catch (e) { return fail(e); }
  afterSchedule();
  openCompose({ mode: "draft", id: r.id });
}

async function sendNow(r) {
  if (r.waiting) {
    try {
      const res = await api("outbox", { do: "retry" });
      if (res.sent) { toast(t("sent_ok")); if (S.sched?.id === r.id) { S.sel = null; showEmpty(); } } else toast(t("queued_offline"));
    } catch (e) { fail(e); }
    return afterSchedule();
  }
  if (S.sched?.id === r.id) { S.sel = null; showEmpty(); }
  const back = () => { const row = S.rows.find((x) => x.id === r.id); if (row) selectRow(row.id); };
  await sendWithUndo(r.id, back);
}

function msgNode(r, expanded) {
  const node = el("div", { class: "msg" + (expanded ? "" : " collapsed"), "data-id": r.id });
  const head = el("div", { class: "msg-head" });
  const whoBox = el("div", { class: "msg-who" },
    el("div", { class: "msg-from", html: `<b>${esc(nameOf(r.from))}</b>` + (r.from.name ? `<span class="addr">&lt;${esc(r.from.addr)}&gt;</span>` : "") }));
  const to = [...r.to, ...r.cc];
  const toLine = el("div", { class: "msg-to" }, (t("to") + " ") + to.map(who).join(", "));
  const snip = el("div", { class: "msg-snip" }, r.snippet);
  whoBox.append(expanded ? toLine : snip);
  head.append(el("div", { class: "avatar" }, initials(r.from)), whoBox, el("div", { class: "msg-date", title: longTime(r.ts) }, expanded ? longTime(r.ts) : shortTime(r.ts)));
  const acts = el("div", { class: "msg-acts" },
    iconBtn("reply", t("reply"), (e) => { e.stopPropagation(); openCompose({ mode: "reply", id: r.id }); }),
    iconBtn("reply-all", t("replyall"), (e) => { e.stopPropagation(); openCompose({ mode: "replyall", id: r.id }); }),
    iconBtn("forward", t("forward"), (e) => { e.stopPropagation(); openCompose({ mode: "forward", id: r.id }); }));
  head.append(acts);
  node.append(head);
  head.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    if (node.classList.contains("collapsed")) {
      node.classList.remove("collapsed");
      whoBox.replaceChildren(whoBox.firstChild, toLine);
      head.querySelector(".msg-date").textContent = longTime(r.ts);
      loadBody(node, r);
      S.focus = r.id; renderToolbar();
    } else if (e.target.closest(".msg-to")) {
      if (toLine.classList.toggle("open")) {
        // one person per chip, so a name and its address never break apart
        const line = (lab, list) => list.length ? `<span class="pl">${esc(lab)}</span><span>` +
          list.map((p) => `<span class="pp">${esc(p.name || p.addr)}${p.name ? ` <span class="addr">${esc(p.addr)}</span>` : ""}</span>`).join("") + "</span>" : "";
        toLine.innerHTML = line(t("to"), r.to) + line(t("cc"), r.cc);
      } else toLine.textContent = t("to") + " " + to.map(who).join(", ");
    } else { S.focus = r.id; renderToolbar(); }
  });
  if (expanded) loadBody(node, r);
  return node;
}

async function loadBody(node, r) {
  let body = node.querySelector(".msg-body");
  if (body) return;
  body = el("div", { class: "msg-body" }, el("div", { class: "rows-more" }, el("span", { html: icon("loader-circle", "spin") })));
  node.append(body);
  let m;
  try { m = await api("message", { id: r.id }); }
  catch (e) { body.replaceChildren(el("div", { class: "form" }, el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) }))); return; }
  if (r.unread) { r.unread = false; markRow(r.id, { unread: false }); refreshCounts(); if (S.focus === r.id) renderToolbar(); }
  body.replaceChildren();
  node._msg = m;
  renderBody(body, m);
}

// Unix seconds for a wall-clock time in a named zone (an invite says "14:00 in Shanghai")
function wallEpoch(y, m, d, h, mi, tz) {
  const f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" });
  const want = Date.UTC(y, m - 1, d, h, mi);
  let guess = want;
  for (let k = 0; k < 3; k++) {
    const q = Object.fromEntries(f.formatToParts(new Date(guess)).map((x) => [x.type, x.value]));
    guess = want - (Date.UTC(+q.year, +q.month - 1, +q.day, +q.hour % 24, +q.minute) - guess);
  }
  return Math.round(guess / 1000);
}
function inviteEpoch(x) {
  if (!x || x.day) return null;
  const [y, m, d, h, mi] = x.wall;
  if (x.tz) { try { return wallEpoch(y, m, d, h, mi, x.tz); } catch { /* a zone this computer does not know */ } }
  if (x.offset != null) return Date.UTC(y, m - 1, d, h, mi) / 1000 - x.offset * 60;
  return zepoch(y, m, d, h, mi);
}
function inviteWhen(v) {
  if (v.start?.day) {
    const day = (w, back = 0) => new Intl.DateTimeFormat(LOCALE, { weekday: "short", year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(w[0], w[1] - 1, w[2] - back)));
    const a = day(v.start.wall), b = v.end?.day ? day(v.end.wall, 1) : a;      // an all-day end is the day after
    return (a === b ? a : a + " – " + b) + " · " + t("all_day");
  }
  const a = inviteEpoch(v.start), b = inviteEpoch(v.end);
  if (!a) return "";
  return longTime(a) + (b ? " – " + (dayKey(a * 1000) === dayKey(b * 1000) ? fmt(b, HM) : longTime(b)) : "");
}
// A meeting invite: what, when, where, who, and the answer buttons
function inviteCard(m) {
  const v = m.invite;
  const line = (ic, text) => text ? el("div", { class: "inv-line" }, el("span", { html: icon(ic, "small") }), el("span", { dir: "auto" }, text)) : null;
  const names = [v.organizer, ...v.attendees.filter((x) => x.addr !== v.organizer?.addr)].filter(Boolean).map(who);
  const acts = el("div", { class: "inv-acts" });
  const card = el("div", { class: "invite" + (v.cancelled ? " off" : "") },
    el("span", { class: "sched-ic", html: icon(v.cancelled ? "calendar-x" : "calendar") }),
    el("div", { class: "inv-text" },
      el("div", { class: "inv-title", dir: "auto" }, v.summary || m.subject),
      line("clock", [inviteWhen(v), v.repeats ? t("repeats") : ""].filter(Boolean).join(" · ")),
      line("map-pin", v.location),
      line("users", names.slice(0, 6).join(", ") + (names.length > 6 ? " " + t("recipients_more", names.length - 6) : ""))),
    acts);
  const draw = () => {
    acts.replaceChildren();
    if (v.cancelled) return acts.append(el("span", { class: "inv-state" }, t("invite_cancelled")));
    if (v.method === "REPLY") {
      const a = v.attendees[0];
      const k = { ACCEPTED: "x_accepted", TENTATIVE: "x_tentative", DECLINED: "x_declined" }[a?.status];
      if (k) acts.append(el("span", { class: "inv-state" }, t(k, nameOf(a))));
      return;
    }
    if (v.can_answer) {
      const seg = el("div", { class: "seg" });
      for (const [k, st, ic] of [["accepted", "ACCEPTED", "check"], ["tentative", "TENTATIVE", "circle-help"], ["declined", "DECLINED", "x"]]) {
        seg.append(el("button", { class: v.mine === st ? "on" : "", html: icon(ic, "small") + esc(t("inv_" + k)), onclick: async () => {
          if (v.mine === st) return;
          for (const b of $$("button", seg)) b.disabled = true;
          try {
            const r = await api("invite", { id: m.id, answer: k });
            v.mine = r.mine;
            toast(r.queued ? t("queued_offline") : t("reply_sent_to", nameOf(v.organizer)));
            refreshCounts();
          } catch (e) { fail(e); }
          draw();
        } }));
      }
      acts.append(seg);
    }
    acts.append(el("button", { class: "btn", html: icon("calendar-check", "small") + esc(t("add_to_calendar")), onclick: () => api("invite", { id: m.id, do: "open" }).catch(fail) }));
  };
  draw();
  return card;
}

function renderBody(body, m) {
  body.replaceChildren();
  // the files first, right under the mail's header: nobody should scroll past a long mail to find them
  if (m.atts.length) {
    const atts = el("div", { class: "atts top" });
    for (const a of m.atts) atts.append(attNode(a, m.id));
    body.append(atts);
  }
  if (m.invite) body.append(inviteCard(m));
  const remote = m.remote && S.showImages.has(m.id);
  if (m.remote && !remote) {
    body.append(el("div", { class: "imgs-bar" }, el("span", { html: icon("image", "small") }), el("span", {}, t("images_hidden")), el("span", { class: "grow" }),
      el("button", { class: "link-btn", onclick: () => { S.showImages.add(m.id); renderBody(body, m); } }, t("show_images"))));
  }
  const frame = mailFrame(m.html, { plain: m.plain, remote, quote: true });
  body.append(frame.node);
}

function attNode(a, id) {
  const open = async () => {
    node.classList.add("busy");
    try { await api("attachment", { id, i: a.i, action: "open" }); } catch (e) { fail(e); } finally { node.classList.remove("busy"); }
  };
  const save = async (e) => {
    e.stopPropagation();
    node.classList.add("busy");
    try {
      const r = await api("attachment", { id, i: a.i, action: "save" });
      toast(t("saved_to") + " · " + r.name, { action: { label: t("show"), run: () => api("reveal", { path: r.path }).catch(fail) }, ms: 5000 });
    } catch (err) { fail(err); } finally { node.classList.remove("busy"); }
  };
  const node = el("div", { class: "att", role: "button", tabindex: "0", title: a.name, onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
    el("div", { class: "att-icon", html: icon(fileIcon(a.name)) }),
    el("div", { class: "att-text" }, el("div", { class: "att-name" }, a.name), el("div", { class: "att-size" }, size(a.size))),
    el("div", { class: "att-acts" }, iconBtn("download", t("download"), save)));
  return node;
}
