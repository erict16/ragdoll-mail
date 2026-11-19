// The compose window.
import { $, api, el, iconBtn, t } from "./core.js";
import { mailFont, mailSize, S } from "./state.js";
import { fail } from "./ui.js";
import { renderToolbar } from "./reader.js";
import { mailFrame } from "./frames.js";
import { addrField, edCmd, fmtBar, fmtSync, leaveCompose, linkSheet, onPaste, renderAtts, touched, uploadFiles } from "./editor.js";

export const ADDR_RE = /^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$/;
export function parseAddrs(text) {
  const out = [];
  for (const part of text.split(/[,;\n]+/)) {
    const s = part.trim();
    if (!s) continue;
    const m = s.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (m) out.push({ name: m[1].trim(), addr: m[2].trim().toLowerCase() });
    else out.push({ name: "", addr: s.replace(/^mailto:/i, "").toLowerCase() });
  }
  return out;
}

export async function openCompose(opts) {
  if (S.compose && !(await leaveCompose())) return;
  let c;
  try {
    c = await api("compose", { mode: opts.mode, id: opts.id });
  } catch (e) { return fail(e); }
  if (opts.to) c.to = [...opts.to, ...c.to];
  if (opts.files) c.pending = opts.files;
  c.showCc = c.cc.length > 0; c.showBcc = c.bcc.length > 0;
  c.dirty = false; c.status = ""; c.busy = false;
  // a draft we wrote before comes back inside our own font wrapper: take it off
  if (c.html) {
    const d = el("div", { html: c.html });
    const w = d.firstElementChild;
    if (w && w.dataset.rdBody && d.childElementCount === 1 && !d.textContent.replace(w.textContent, "").trim()) c.html = w.innerHTML;
  }
  S.compose = c; S.sched = null;
  renderCompose();
}

export function renderCompose() {
  const c = S.compose;
  renderToolbar();
  const box = el("div", { class: "compose" });
  box.append(addrField("to", t("to"), true));
  if (c.showCc) box.append(addrField("cc", t("cc")));
  if (c.showBcc) box.append(addrField("bcc", t("bcc")));
  const subj = el("input", { class: "subject-input", type: "text", placeholder: t("subject"), value: c.subject, spellcheck: "true" });
  subj.addEventListener("input", () => { c.subject = subj.value; touched(); });
  subj.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ed.focus(); } });
  const ed = el("div", { class: "editor", contenteditable: "true", "data-ph": t("write"), spellcheck: "true",
    style: `font-family:${mailFont()};font-size:${mailSize()}px` });
  ed.innerHTML = c.html || "";
  ed.addEventListener("input", () => { c.html = ed.innerHTML; touched(); fmtSync(); });
  ed.addEventListener("paste", onPaste);
  ed.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey, k = e.key.toLowerCase();
    if (!mod || e.altKey) return;
    if (k === "k") { e.preventDefault(); e.stopPropagation(); linkSheet(); }
    else if (k === "b" || k === "i" || k === "u") { e.preventDefault(); edCmd({ b: "bold", i: "italic", u: "underline" }[k]); }
    else if (e.shiftKey && (k === "7" || k === "8")) { e.preventDefault(); edCmd(k === "7" ? "insertOrderedList" : "insertUnorderedList"); }
  });
  box.append(subj, fmtBar(), ed);
  if (c.signature && c.use_signature) {
    const sig = el("div", { class: "sig" });
    sig.append(mailFrame(c.signature, { sig: true }).node, iconBtn("x", t("remove_sig"), () => { c.use_signature = false; touched(); sig.remove(); }, { cls: "tiny" }));
    box.append(sig);
  }
  if (c.quote) {
    const qbox = el("div", { hidden: true });
    const tog = el("button", { class: "quote-toggle", "data-tip": t("show_quote"), "aria-label": t("show_quote") }, "•••");
    tog.addEventListener("click", () => {
      qbox.hidden = !qbox.hidden;
      if (!qbox.firstChild) qbox.append(mailFrame(c.quote, {}).node);
    });
    box.append(el("div", { style: "margin-top:12px" }, tog), qbox);
  }
  box.append(el("div", { class: "atts", id: "compose-atts" }));
  $("#pane").replaceChildren(box);
  $("#pane").scrollTop = 0;
  renderAtts();
  if (c.pending) { const f = c.pending; c.pending = null; uploadFiles(f); }
  requestAnimationFrame(() => {
    if (!c.to.length && c.mode !== "draft") $("#pane .chips input")?.focus();
    else if (c.mode === "forward" || c.mode === "new") (c.subject ? ed : subj).focus();
    else ed.focus();
  });
}
