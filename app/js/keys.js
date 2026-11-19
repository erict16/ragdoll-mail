// Keyboard shortcuts.
import { $, el, MOD, t } from "./core.js";
import { S, savePref, TEXT_SIZES, textSize } from "./state.js";
import { closeLayer, fail, layerOpen, sheet, toast } from "./ui.js";
import { clearMulti, moveMail, rowOf, selectAll, step, toggleFlag, toggleUnread } from "./actions.js";
import { onSearch } from "./search.js";
import { refreshFrames } from "./frames.js";
import { openCompose } from "./compose.js";
import { closeCompose, saveDraft, sendCompose } from "./editor.js";
import { openSettings } from "./settings.js";

export function setTextSize(n) {
  if (!TEXT_SIZES.includes(n) || n === textSize()) return;
  savePref({ text_size: n });
  refreshFrames();
}
function stepTextSize(d) {
  if (!d) return setTextSize(14);
  const k = TEXT_SIZES.indexOf(textSize());
  const n = TEXT_SIZES[Math.max(0, Math.min(TEXT_SIZES.length - 1, k + d))];
  if (n !== textSize()) { setTextSize(n); toast(t("text_size") + " " + n, { id: "zoom", ms: 1400 }); }
}

export function shortcutsSheet() {
  const groups = [
    ["mailbox", [["J  K", "next_mail"], ["C", "compose"], ["/", "search"], [MOD + "A", "select_all"], [MOD + "Click", "add_select"], ["⇧Click", "range_select"], ["Esc", "close_clear"]]],
    ["reading", [["R", "reply"], ["A", "replyall"], ["F", "forward"], ["E", "archive_it"], ["#", "trash_it"], ["U", "unread"], ["S", "flag"], ["B", "snooze"], [MOD + "+  " + MOD + "−", "text_size"], [MOD + "0", "actual_size"]]],
    ["writing", [[MOD + "↩", "send"], [MOD + "S", "save_draft"], [MOD + "B", "bold"], [MOD + "I", "italic"], [MOD + "U", "underline"], [MOD + "K", "link"], ["Esc", "close"]]],
  ];
  const grid = el("div", { class: "keys-grid" });
  for (const [g, rows] of groups) {
    const col = el("div", { class: "keys-col" }, el("h3", {}, t(g)));
    for (const [keys, label] of rows) {
      col.append(el("div", { class: "keys-row" }, el("span", {}, t(label)),
        el("span", { class: "keys" }, ...keys.split(/\s{2}/).map((k) => el("kbd", {}, k)))));
    }
    grid.append(col);
  }
  sheet(el("div", {}, el("h2", {}, t("shortcuts")), grid)).classList.add("keys-sheet");
}

function typing(e) {
  const n = e.target;
  return n && (n.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(n.tagName));
}
export function onKey(e) {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); $("#search").focus(); $("#search").select(); return; }
  if (mod && e.key === ",") { e.preventDefault(); openSettings(); return; }
  if (mod && !e.altKey && (e.key === "=" || e.key === "+" || e.key === "-" || e.key === "0")) {
    e.preventDefault(); stepTextSize(e.key === "0" ? 0 : e.key === "-" ? -1 : 1); return;
  }
  if (layerOpen()) { if (e.key === "Escape") { closeLayer(); } return; }
  if (S.compose) {
    if (mod && e.key === "Enter") { e.preventDefault(); sendCompose(); return; }
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveDraft().catch(fail); return; }
    if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); closeCompose(); return; }
  }
  if (mod && e.key.toLowerCase() === "a" && !typing(e) && !S.compose) { e.preventDefault(); selectAll(); return; }
  if (typing(e) || mod || e.altKey) return;
  const id = S.focus || S.sel;
  const k = e.key;
  if (k === "?") { e.preventDefault(); shortcutsSheet(); return; }
  if (S.multi.size > 1) {
    const ids = [...S.multi];
    if (k === "Escape") { e.preventDefault(); clearMulti(); }
    else if (k === "e") { e.preventDefault(); moveMail(ids, "archive"); }
    else if (k === "#" || k === "Delete" || k === "Backspace") { e.preventDefault(); if (!ids.map(rowOf).every((r) => r?.folder === "trash")) moveMail(ids, "trash"); }
    else if (k === "u") { e.preventDefault(); toggleUnread(); }
    else if (k === "s") { e.preventDefault(); toggleFlag(); }
    else if (k === "b") { e.preventDefault(); $("#toolbar [data-snooze]")?.click(); }
    else if (k === "j" || k === "ArrowDown" || k === "k" || k === "ArrowUp") { e.preventDefault(); S.multi.clear(); step(k === "j" || k === "ArrowDown" ? 1 : -1); }
    else if (k === "c") { e.preventDefault(); openCompose({ mode: "new" }); }
    else if (k === "/") { e.preventDefault(); $("#search").focus(); }
    return;
  }
  if (k === "j" || k === "ArrowDown") { e.preventDefault(); step(1); }
  else if (k === "k" || k === "ArrowUp") { e.preventDefault(); step(-1); }
  else if (k === "c") { e.preventDefault(); openCompose({ mode: "new" }); }
  else if (k === "/") { e.preventDefault(); $("#search").focus(); }
  else if (!S.thread) return;
  else if (k === "r") { e.preventDefault(); openCompose({ mode: "reply", id }); }
  else if (k === "a") { e.preventDefault(); openCompose({ mode: "replyall", id }); }
  else if (k === "f") { e.preventDefault(); openCompose({ mode: "forward", id }); }
  else if (k === "e") { e.preventDefault(); if (S.thread.rows.find((x) => x.id === id)?.folder !== "archive") moveMail([id], "archive"); }
  else if (k === "#" || k === "Delete" || k === "Backspace") { e.preventDefault(); if (S.thread.rows.find((x) => x.id === id)?.folder !== "trash") moveMail([id], "trash"); }
  else if (k === "u") { e.preventDefault(); toggleUnread(); }
  else if (k === "s") { e.preventDefault(); toggleFlag(); }
  else if (k === "b") { e.preventDefault(); $("#toolbar [data-snooze]")?.click(); }
  else if (k === "Escape" && S.query) { $("#search").value = ""; onSearch(true); }
}
document.addEventListener("keydown", onKey);
$("#pane").addEventListener("scroll", (e) => $("#toolbar").classList.toggle("lined", e.target.scrollTop > 0), { passive: true });
