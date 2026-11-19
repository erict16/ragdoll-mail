// Send later, and dropping files onto the window.
import { $, el, esc, icon, SYS_TZ, t, TZ } from "./core.js";
import { S } from "./state.js";
import { fmt, HM, zepoch, zparts } from "./format.js";
import { closeLayer, menu, sheet } from "./ui.js";
import { openCompose } from "./compose.js";
import { sendCompose, uploadFiles } from "./editor.js";

const addDays = (p, n) => { const d = new Date(Date.UTC(p.y, p.m - 1, p.d + n)); return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate() }; };
export function laterMenu(anchor, run = (ts) => sendCompose(false, ts), opts = {}) {
  const now = zparts(Date.now());
  const at = (p, h) => zepoch(p.y, p.m, p.d, h, 0);
  const items = [];
  const pick = (ic, label, ts, hint) => items.push({ icon: ic, label, hint, run: () => run(ts) });
  if (opts.snooze) { const ts = Math.round(Date.now() / 1000) + 3600; pick("clock", t("in_1_hour"), ts, fmt(ts, HM)); }
  if (now.h < 17) pick("sunset", t("this_evening"), at(now, 18), fmt(at(now, 18), HM));
  const tom = addDays(now, 1);
  pick("sunrise", t("tomorrow_morning"), at(tom, 8), fmt(at(tom, 8), HM));
  pick("sun", t("tomorrow_afternoon"), at(tom, 13), fmt(at(tom, 13), HM));
  const toMon = ((8 - now.wd) % 7) || 7;
  if (toMon > 1) { const mon = addDays(now, toMon); pick("calendar", t("monday_morning"), at(mon, 8), fmt(at(mon, 8), { month: "short", day: "numeric", ...HM })); }
  items.push("-", { icon: "calendar-clock", label: t("pick_time"), run: () => pickTimeSheet(run, opts) });
  menu(anchor, items);
}

function pickTimeSheet(run = (ts) => sendCompose(false, ts), opts = {}) {
  const tom = addDays(zparts(Date.now()), 1);
  const pad = (n) => String(n).padStart(2, "0");
  const date = el("input", { type: "date", value: `${tom.y}-${pad(tom.m)}-${pad(tom.d)}` });
  const time = el("input", { type: "time", value: "08:00", step: 300 });
  const err = el("div");
  const go = () => {
    const [y, m, d] = date.value.split("-").map(Number), [h, mi] = time.value.split(":").map(Number);
    const ts = y && h != null && !isNaN(mi) ? zepoch(y, m, d, h, mi) : 0;
    if (!ts || ts * 1000 < Date.now() + 30e3) { err.replaceChildren(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(t("pick_future")) })); return; }
    closeLayer();
    run(ts);
  };
  const box = sheet(el("div", { class: "pick-time" },
    el("h2", { html: icon(opts.snooze ? "alarm-clock" : "calendar-clock") + esc(t(opts.snooze ? "snooze" : "send_later")) }),
    el("div", { class: "form" },
      el("div", { class: "two-even" }, el("label", {}, el("span", { class: "lab" }, t("date")), date), el("label", {}, el("span", { class: "lab" }, t("time")), time)),
      el("div", { class: "note", html: icon("globe", "small") + esc((TZ || SYS_TZ).replace(/_/g, " ")) }), err),
    el("div", { class: "sheet-acts" },
      el("button", { class: "btn", onclick: closeLayer }, t("cancel")),
      el("button", { class: "btn primary", onclick: go }, t(opts.snooze ? "snooze" : "schedule")))));
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  date.focus();
}

// drop files on the reader: attach (opens a new mail when none is open)
let dropZone = null, dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
$("#reader").addEventListener("dragenter", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth++;
  if (!dropZone) { dropZone = el("div", { class: "drop-zone", html: icon("paperclip") + esc(t("drop_files")) }); $("#reader").style.position = "relative"; $("#reader").append(dropZone); }
});
$("#reader").addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
$("#reader").addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; dropZone?.remove(); dropZone = null; } });
$("#reader").addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth = 0; dropZone?.remove(); dropZone = null;
  const files = [...e.dataTransfer.files];
  if (!files.length) return;
  if (S.compose) uploadFiles(files); else openCompose({ mode: "new", files });
});
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", (e) => { if (hasFiles(e)) e.preventDefault(); });
