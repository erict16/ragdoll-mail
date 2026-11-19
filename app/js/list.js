// The mail list: loading, drawing and keeping the rows.
import { $, $$, api, el, esc, icon, t, tr } from "./core.js";
import { FOLDER_ICON, S } from "./state.js";
import { laterTime, shortTime, who } from "./format.js";
import { fail, REDUCED } from "./ui.js";
import { hidden, isSel } from "./actions.js";

function rowTemplate(r) {
  const outgoing = r.folder === "sent" || r.folder === "drafts";
  let name;
  if (outgoing) {
    const names = r.to.map(who);
    name = names.length ? t("to_x", names.slice(0, 3).join(", ") + (names.length > 3 ? " " + t("recipients_more", names.length - 3) : "")) : (r.folder === "drafts" ? t("draft") : "");
  } else name = who(r.from);
  const clip = r.atts.length ? icon("paperclip", "small") : "";
  const when = r.snooze ? `<span class="sched">${icon("alarm-clock", "small")}${esc(laterTime(r.snooze))}</span>`
    : r.woke ? `<span class="sched">${icon("alarm-clock", "small")}</span>${esc(shortTime(r.ts))}`
    : r.waiting && !r.sched_error ? `<span class="sched">${icon("cloud-off", "small")}${esc(t("waiting"))}</span>` : r.sched ? (r.sched_error ? `<span class="sched err">${icon("triangle-alert", "small")}${esc(laterTime(r.sched))}</span>` : `<span class="sched">${icon("clock", "small")}${esc(laterTime(r.sched))}</span>`) : esc(shortTime(r.ts));
  const tag = (S.query || S.folder === "flagged") && r.folder !== "inbox" ? `<span class="tag">${esc(t(r.folder) || r.folder)}</span>` : "";
  const flag = r.flagged ? `<span class="flag-ic">${icon("star", "small")}</span>` : "";
  const done = r.answered || r.forwarded ? `<span class="done-ic">${r.answered ? icon("reply", "small") : ""}${r.forwarded ? icon("arrow-right", "small") : ""}</span>` : "";
  const acts = r.sched
    ? `<button class="icon-btn tiny" data-act="unschedule" data-tip="${esc(t("dont_send"))}">${icon("calendar-x")}</button>`
    : S.folder === "snoozed" && !S.query
    ? `<button class="icon-btn tiny" data-act="unsnooze" data-tip="${esc(t("restore"))}">${icon("inbox")}</button>`
    : (S.folder === "trash" || S.folder === "junk") && !S.query
    ? `<button class="icon-btn tiny" data-act="inbox" data-tip="${esc(t("restore"))}">${icon("inbox")}</button>`
    : `<button class="icon-btn tiny" data-act="archive" data-tip="${esc(t("archive_it"))}" data-key="E">${icon("archive")}</button>` +
      `<button class="icon-btn tiny" data-act="trash" data-tip="${esc(t("trash_it"))}" data-key="#">${icon("trash-2")}</button>`;
  return `<div class="row${r.unread ? " unread" : ""}${isSel(r.id) ? " on" : ""}" data-id="${esc(r.id)}" draggable="true">` +
    `<span class="dot"></span><span class="who" dir="auto">${done}${esc(name)}</span>` +
    `<span class="meta">${tag}${flag}${clip}${when}</span>` +
    `<span class="subj" dir="auto">${esc(r.subject || t("no_subject"))}</span>` +
    `<span class="snip" dir="auto">${esc(r.snippet) || "&nbsp;"}</span>` +
    `<span class="hover-acts">${acts}</span></div>`;
}

// rows that were not in the list a moment ago (new mail, an undo) fade in; a new folder fades in as a whole
let shownIds = new Set(), shownKey = null, shownMarks = new Map();
export function noteShown() { shownIds = new Set(S.rows.map((x) => x.id)); }
const marksOf = (r) => ({ a: !!r.answered, f: !!r.forwarded, s: !!r.flagged });
// The same folder again (new mail, a sync, more rows) keeps the rows that did not change, so a long
// list stays cheap to update, and the row at the top of the view stays where it is.
const rowHTML = new WeakMap();
function rowNode(r) {
  const html = rowTemplate(r);
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const n = tpl.content.firstChild;
  rowHTML.set(n, html);
  return n;
}
export function renderRows({ grow = true } = {}) {
  const box = $("#rows");
  const key = S.folder + "\n" + S.query;
  const same = key === shownKey && shownIds.size > 0;
  const oldMarks = same ? shownMarks : new Map();
  shownIds = new Set(S.rows.map((x) => x.id)); shownKey = key;
  shownMarks = new Map(S.rows.map((x) => [x.id, marksOf(x)]));
  if (!S.rows.length) {
    if (S.loading) { box.replaceChildren(); return; }
    const msg = S.query ? t("no_results") : (S.syncing && S.folder === "inbox" ? t("syncing") : t("no_mail"));
    box.innerHTML = `<div class="rows-empty">${S.syncing && !S.query ? icon("loader-circle", "big spin") : icon(S.query ? "search" : FOLDER_ICON[S.folder] || "inbox", "big")}<span>${esc(msg)}</span></div>`;
    return;
  }
  const more = () => el("div", { class: "rows-more", html: icon("loader-circle", "spin") });
  if (!same) {
    box.innerHTML = S.rows.map(rowTemplate).join("");
    if (S.more) box.append(more());
    if (!REDUCED.matches) box.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: "ease-out" });
    return;
  }
  // the row at the top of the view, and how far into the view it sits
  const old = new Map($$(".row", box).map((n) => [n.dataset.id, n]));
  let anchor = null, gap = 0;
  if (box.scrollTop > 0) {
    for (const n of old.values()) if (n.offsetTop + n.offsetHeight > box.scrollTop) { anchor = n; gap = n.offsetTop - box.scrollTop; break; }
  }
  const fresh = [];
  const want = S.rows.map((r) => {
    const n = old.get(r.id);
    if (n && rowHTML.get(n) === rowTemplate(r)) {
      n.classList.toggle("unread", !!r.unread); n.classList.toggle("on", isSel(r.id));
      return n;
    }
    const m = rowNode(r);
    if (!n) fresh.push(m);
    else if (n === anchor) anchor = m;
    return m;
  });
  if (S.more) want.push($(".rows-more", box) || more());
  const keep = new Set(want);
  for (const n of [...box.children]) if (!keep.has(n)) n.remove();
  let cur = box.firstChild;
  for (const n of want) {
    if (n === cur) cur = cur.nextSibling;
    else box.insertBefore(n, cur);
  }
  if (anchor && anchor.isConnected) box.scrollTop = anchor.offsetTop - gap;
  if (REDUCED.matches) return;
  // only rows in or below the view open their space; one above it would push the view down
  if (grow) growRows(fresh.filter((n) => n.offsetTop + n.offsetHeight > box.scrollTop));
  for (const n of want) {
    const was = oldMarks.get(n.dataset?.id), now = shownMarks.get(n.dataset?.id);
    if (!was || !now) continue;
    if ((now.a && !was.a) || (now.f && !was.f)) showDone(n, now.a && !was.a, now.f && !was.f);
    if (now.s && !was.s) popStar($(".flag-ic", n));
  }
}

// the star in a row: grows in with a small spin and settles; shrinks away when taken off
const STAR_W = "13px";
function popStar(s) {
  if (!s || REDUCED.matches) return;
  s.animate([
    { width: "0px", marginInlineEnd: "-5px", opacity: 0 },
    { width: STAR_W, marginInlineEnd: "0px", opacity: 1, offset: 0.45 },
    { width: STAR_W, marginInlineEnd: "0px", opacity: 1 },
  ], { duration: 460, easing: SMOOTH });
  $(".i", s)?.animate([
    { transform: "scale(.2) rotate(-90deg)" },
    { transform: "scale(1.22) rotate(10deg)", offset: 0.6 },
    { transform: "scale(.96) rotate(-2deg)", offset: 0.82 },
    { transform: "none" },
  ], { duration: 460, easing: "cubic-bezier(.3, .7, .3, 1)" });
}
function setStar(node, on) {
  const meta = $(".meta", node);
  const s = $(".flag-ic:not(.out)", meta);
  if (on && !s) {
    const n = el("span", { class: "flag-ic", html: icon("star", "small") });
    const tag = $(".tag", meta);
    if (tag) tag.after(n); else meta.prepend(n);
    popStar(n);
  } else if (!on && s) {
    s.classList.add("out");
    if (REDUCED.matches) { s.replaceWith(); return; }
    s.animate([
      { width: STAR_W, marginInlineEnd: "0px", opacity: 1, transform: "none" },
      { width: "0px", marginInlineEnd: "-5px", opacity: 0, transform: "scale(.4) rotate(45deg)" },
    ], { duration: 240, easing: SMOOTH, fill: "forwards" }).finished.then(() => s.replaceWith(), () => {});
  }
}

// a new replied / forwarded mark opens its space before the name, the arrow sliding the way it points
function showDone(node, replied, forwarded) {
  const d = $(".done-ic", node);
  if (!d || REDUCED.matches) return;
  const w = d.offsetWidth + "px";
  d.animate([
    { width: "0px", marginInlineEnd: "0px", opacity: 0 },
    { width: w, marginInlineEnd: "5px", opacity: 0, offset: 0.35 },
    { width: w, marginInlineEnd: "5px", opacity: 1 },
  ], { duration: 420, easing: SMOOTH });
  const icons = $$(".i", d);
  const slide = (n, dx) => n?.animate([{ transform: `translateX(${dx}px)` }, { transform: "none" }],
    { duration: 420, easing: "cubic-bezier(.2, .8, .2, 1)" });
  if (replied) slide(icons[0], 7);
  if (forwarded) slide(icons[icons.length - 1], -7);
}

// rows going away fold up before they are dropped
const SMOOTH = "cubic-bezier(.4, 0, .2, 1)";
export function foldRows(nodes) {
  nodes = nodes.filter(Boolean);
  if (!nodes.length || REDUCED.matches) return Promise.resolve();
  return Promise.all(nodes.map((n) => {
    const h = n.offsetHeight + "px";
    n.classList.add("leaving");
    return n.animate([
      { height: h, opacity: 1, transform: "none" },
      { height: h, opacity: 0, transform: "translateX(-10px)", offset: 0.4 },
      { height: "0px", opacity: 0, transform: "translateX(-10px)", paddingTop: "0px", paddingBottom: "0px" },
    ], { duration: 320, easing: SMOOTH, fill: "forwards" }).finished.catch(() => {});
  }));
}

// a row that arrives (undo, new mail) opens its space first, then fades in
function growRows(nodes) {
  if (REDUCED.matches) return;
  const hs = nodes.map((n) => n.offsetHeight + "px");      // read every height before the first change
  for (const [k, n] of nodes.entries()) {
    const h = hs[k];
    n.classList.add("leaving");
    const a = n.animate([
      { height: "0px", opacity: 0, transform: "translateY(-4px)", paddingTop: "0px", paddingBottom: "0px" },
      { height: h, opacity: 0, transform: "translateY(-4px)", offset: 0.55 },
      { height: h, opacity: 1, transform: "none" },
    ], { duration: 340, easing: SMOOTH });
    a.finished.finally(() => n.classList.toggle("leaving", false)).catch(() => {});
  }
}

let listSeq = 0;
export async function loadList({ quiet = false } = {}) {
  const seq = ++listSeq;
  if (!quiet) S.loading = true;
  try {
    let rows, more = false;
    if (S.query) {
      const r = await api("search", { q: S.query, limit: quiet ? Math.min(2000, Math.max(100, S.searchNext || 0)) : 100 });
      rows = r.rows; more = r.more; S.searchNext = r.next;
    } else {
      // a quiet reload gets back as many rows as are on screen (the server gives at most 500 a call)
      const want = quiet ? Math.max(100, S.rows.length) : 100;
      rows = [];
      for (;;) {
        const r = await api("list", { folder: S.folder, limit: Math.min(500, want - rows.length), offset: rows.length });
        if (seq !== listSeq) return;
        const have = new Set(rows.map((x) => x.id));
        rows.push(...r.rows.filter((x) => !have.has(x.id)));
        more = r.more;
        if (!more || !r.rows.length || rows.length >= want) break;
      }
    }
    if (seq !== listSeq) return;
    S.loading = false;
    rows = rows.filter((x) => !hidden.has(x.id));
    if (quiet && JSON.stringify(rows) === JSON.stringify(S.rows) && more === S.more) return;
    S.rows = rows; S.more = more;
    renderRows();
    if (!quiet) $("#rows").scrollTop = 0;
  } catch (e) { if (seq === listSeq && S.loading) { S.loading = false; renderRows(); } if (!quiet) fail(e); }
}

export async function loadMore() {
  if (!S.more || S.loadingMore) return;
  S.loadingMore = true;
  const key = S.folder + "\n" + S.query;
  try {
    const r = S.query ? await api("search", { q: S.query, limit: 100, offset: S.searchNext || 0 })
      : await api("list", { folder: S.folder, limit: 100, offset: S.rows.length });
    if (key !== S.folder + "\n" + S.query) return;         // another folder or search was opened meanwhile
    if (S.query) S.searchNext = r.next;
    const have = new Set(S.rows.map((x) => x.id));
    S.rows.push(...r.rows.filter((x) => !have.has(x.id) && !hidden.has(x.id)));
    S.more = r.more;
    const top = $("#rows").scrollTop;
    renderRows({ grow: false });
    $("#rows").scrollTop = top;
  } catch (e) { fail(e); } finally { S.loadingMore = false; }
}

export function markRow(id, patch) {
  const r = S.rows.find((x) => x.id === id);
  if (r) Object.assign(r, patch);
  const tr = S.thread?.rows.find((x) => x.id === id);
  if (tr) Object.assign(tr, patch);
  const node = $(`.row[data-id="${CSS.escape(id)}"]`);
  if (!node || !r) return;
  if ("flagged" in patch) setStar(node, r.flagged);
  else if ("unread" in patch) node.classList.toggle("unread", patch.unread);
}
