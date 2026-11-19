// What can be done to mail: select several, star, archive, move, snooze, delete.
import { $, $$, api, el, esc, icon, t, TOKEN } from "./core.js";
import { binned, folderName, S } from "./state.js";
import { fail, REDUCED, toast } from "./ui.js";
import { renderNav } from "./sidebar.js";
import { foldRows, loadList, loadMore, markRow, noteShown, renderRows } from "./list.js";
import { syncSearchUI } from "./search.js";
import { dontSend, openScheduled, openThread, renderToolbar, showEmpty, snoozeMail, stopLoads } from "./reader.js";
import { openCompose } from "./compose.js";
import { leaveCompose } from "./editor.js";
import { refreshCounts } from "./status.js";

export const isSel = (id) => (S.multi.size > 1 ? S.multi.has(id) : id === S.sel);
export function syncSel() { for (const n of $$("#rows .row")) n.classList.toggle("on", isSel(n.dataset.id)); }
// the mails the next action works on: the selection, or the open mail
function targets() {
  if (S.multi.size > 1) return [...S.multi];
  const id = S.focus || S.sel;
  return id ? [id] : [];
}
export const rowOf = (id) => S.rows.find((x) => x.id === id) || S.thread?.rows.find((x) => x.id === id);
async function pickRow(id, e) {
  if (!(e.metaKey || e.ctrlKey || e.shiftKey)) return selectRow(id);
  if (S.compose && !(await leaveCompose())) return;
  if (e.shiftKey && (S.anchor || S.sel)) {
    const ids = S.rows.map((x) => x.id);
    let a = ids.indexOf(S.anchor || S.sel), b = ids.indexOf(id);
    if (a < 0) a = b;
    const range = ids.slice(Math.min(a, b), Math.max(a, b) + 1);
    S.multi = new Set(e.metaKey || e.ctrlKey ? [...S.multi, ...range] : range);
  } else {
    if (!S.multi.size && S.sel) S.multi.add(S.sel);
    if (S.multi.has(id)) S.multi.delete(id); else S.multi.add(id);
    S.anchor = id;
  }
  if (S.multi.size === 1) return selectRow([...S.multi][0]);
  if (!S.multi.size) { S.sel = null; syncSel(); return showEmpty(); }
  showMulti();
}
export function selectAll() {
  if (!S.rows.length || S.folder === "scheduled") return;
  S.multi = new Set(S.rows.map((x) => x.id));
  if (S.multi.size === 1) return selectRow(S.rows[0].id);
  showMulti();
}
export function clearMulti() {
  if (S.multi.size < 2) return false;
  const keep = S.sel && S.multi.has(S.sel) ? S.sel : [...S.multi][0];
  S.multi.clear();
  selectRow(keep);
  return true;
}
function showMulti() {
  S.thread = null; S.focus = null; S.sched = null;
  stopLoads();
  syncSel();
  const ids = [...S.multi], rows = ids.map(rowOf).filter(Boolean);
  const anyUnread = rows.some((r) => r.unread), allFlagged = rows.length && rows.every((r) => r.flagged);
  const inTrash = rows.length && rows.every(binned);
  const b = (ic, label, run) => el("button", { class: "btn", onclick: run, html: icon(ic, "small") + esc(label) });
  const stack = el("div", { class: "multi-stack" });
  for (let k = Math.min(3, ids.length) - 1; k >= 0; k--) stack.append(el("span", { class: "multi-card", style: `--k:${k}` }));
  $("#pane").replaceChildren(el("div", { class: "multi" }, stack,
    el("h2", {}, t("n_selected", ids.length)),
    el("div", { class: "multi-acts" },
      inTrash ? b("inbox", t("restore"), () => moveMail(ids, "inbox")) : b("archive", t("archive_it"), () => moveMail(ids, "archive")),
      inTrash ? null : b("trash-2", t("trash_it"), () => moveMail(ids, "trash")),
      b(anyUnread ? "mail-open" : "mail", anyUnread ? t("read") : t("unread"), () => markMail(ids, "seen", anyUnread)),
      b(allFlagged ? "star-off" : "star", allFlagged ? t("unflag") : t("flag"), () => markMail(ids, "flagged", !allFlagged)))));
  renderToolbar();
}

// read / unread and flags, for one mail or many
async function markMail(ids, flag, on) {
  if (!ids.length) return;
  const key = flag === "seen" ? "unread" : "flagged", val = flag === "seen" ? !on : on;
  const before = ids.map((id) => [id, rowOf(id)?.[key]]);
  ids.forEach((id) => markRow(id, { [key]: val }));
  if (S.multi.size > 1) showMulti(); else renderToolbar();
  if (key === "flagged") popToolStar(val);
  try {
    await api("mark", { ids, flag, on });
    refreshCounts();
    if (S.folder === "flagged" && flag === "flagged" && !on) loadList({ quiet: true });
  } catch (e) {
    before.forEach(([id, v]) => markRow(id, { [key]: v }));
    if (S.multi.size > 1) showMulti(); else renderToolbar();
    fail(e);
  }
}
function popToolStar(on) {
  const i = $('#tools .icon-btn[data-key="S"] .i');
  if (!i || REDUCED.matches) return;
  i.animate(on
    ? [{ transform: "scale(.5) rotate(-72deg)" }, { transform: "scale(1.25) rotate(8deg)", offset: 0.6 }, { transform: "none" }]
    : [{ transform: "scale(.82)" }, { transform: "none" }],
  { duration: on ? 440 : 220, easing: "cubic-bezier(.3, .7, .3, 1)" });
}
export function toggleFlag() {
  const ids = targets(), rows = ids.map(rowOf).filter(Boolean);
  if (rows.length) markMail(ids, "flagged", !rows.every((r) => r.flagged));
}

export async function openFolder(key) {
  if (!(await leaveCompose())) return;
  S.folder = key; S.query = ""; $("#search").value = ""; syncSearchUI();
  S.sel = null; S.rows = []; S.more = false; S.loading = true;
  renderNav(); renderRows(); showEmpty();
  await loadList();
}

$("#rows").addEventListener("click", async (e) => {
  const row = e.target.closest(".row");
  if (!row) return;
  const act = e.target.closest("[data-act]");
  if (act) {
    e.stopPropagation();
    if (act.dataset.act === "unschedule") return dontSend(S.rows.find((x) => x.id === row.dataset.id));
    if (act.dataset.act === "unsnooze") return snoozeMail([row.dataset.id], 0);
    const id = row.dataset.id;
    return moveMail(S.multi.size > 1 && S.multi.has(id) ? [...S.multi] : [id], act.dataset.act);
  }
  pickRow(row.dataset.id, e);
});
// a Shift-click picks a range, not text
$("#rows").addEventListener("mousedown", (e) => { if (e.shiftKey && e.target.closest(".row")) e.preventDefault(); });
$("#rows").addEventListener("scroll", () => {
  const b = $("#rows");
  if (b.scrollTop + b.clientHeight > b.scrollHeight - 400) loadMore();
});
$("#rows").addEventListener("dragstart", (e) => {
  const row = e.target.closest(".row");
  if (!row) return;
  const id = row.dataset.id;
  e.dataTransfer.setData("x-ragdoll/ids", JSON.stringify(S.multi.size > 1 && S.multi.has(id) ? [...S.multi] : [id]));
  e.dataTransfer.effectAllowed = "move";
});

export async function selectRow(id, { keepFocus = false } = {}) {
  if (S.compose && !(await leaveCompose())) return;
  S.sel = id; S.anchor = id; S.multi.clear();
  syncSel();
  const node = $(`.row[data-id="${CSS.escape(id)}"]`);
  node?.scrollIntoView({ block: "nearest" });
  if (!keepFocus) $("#rows").focus({ preventScroll: true });
  const r = S.rows.find((x) => x.id === id);
  if (r && r.sched) return openScheduled(r);
  if (r && r.folder === "drafts") return openCompose({ mode: "draft", id });
  openThread(id);
}

export function step(d) {
  if (!S.rows.length) return;
  let k = S.rows.findIndex((x) => x.id === S.sel);
  k = k < 0 ? 0 : Math.max(0, Math.min(S.rows.length - 1, k + d));
  selectRow(S.rows[k].id);
}

// Moves wait a few seconds so Undo is free; until then the rows are only hidden.
export const hidden = new Set();
const pendingMoves = new Set();
export function moveMail(ids, to) {
  if (!ids.length) return;
  S.multi.clear();
  const k = Math.max(...ids.map((i) => S.rows.findIndex((x) => x.id === i)));
  const next = S.rows.slice(k + 1).find((x) => !ids.includes(x.id)) || S.rows.slice(0, k).reverse().find((x) => !ids.includes(x.id));
  const wasSel = ids.includes(S.sel) || (S.thread && ids.some((i) => S.thread.rows.some((r) => r.id === i)));
  const sel = S.sel;
  ids.forEach((i) => hidden.add(i));
  S.rows = S.rows.filter((x) => !ids.includes(x.id));
  noteShown();
  const gone = ids.map((i) => $(`.row[data-id="${CSS.escape(i)}"]`));
  foldRows(gone).then(() => { gone.forEach((n) => n?.remove()); if (!S.rows.length) renderRows(); });
  if (wasSel) { if (next) selectRow(next.id); else { S.sel = null; showEmpty(); } }
  const job = { ids, to, done: false };
  const unhide = () => { ids.forEach((i) => hidden.delete(i)); pendingMoves.delete(job); };
  job.commit = async () => {
    if (job.done) return;
    job.done = true; clearTimeout(job.timer);
    try { await api("move", { ids, to }); refreshCounts(); } catch (e) { fail(e); }
    unhide(); loadList({ quiet: true });
  };
  job.timer = setTimeout(job.commit, 5000);
  pendingMoves.add(job);
  toast(to === "archive" ? t("archived") : to === "trash" ? t("trashed") : to === "inbox" ? t("restored") : t("moved_to", folderName(to)), {
    ms: 5000,
    action: { label: t("undo"), run: async () => {
      if (job.done) return;
      job.done = true; clearTimeout(job.timer); unhide();
      await loadList({ quiet: true });
      if (wasSel && sel && S.rows.some((x) => x.id === sel)) selectRow(sel);
    } },
  });
}
// The window is closing: send the waiting moves now.
window.addEventListener("pagehide", () => {
  for (const job of pendingMoves) {
    if (job.done) continue;
    job.done = true;
    fetch("/api/move", { method: "POST", keepalive: true, headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ ids: job.ids, to: job.to }) });
  }
});

export function toggleUnread() {
  const ids = targets(), rows = ids.map(rowOf).filter(Boolean);
  if (rows.length) markMail(ids, "seen", rows.some((r) => r.unread));
}
