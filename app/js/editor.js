// The text editor inside compose: formatting, attachments, saving and sending.
import { $, $$, api, el, esc, icon, iconBtn, MOD, sleep, t, TOKEN, tr } from "./core.js";
import { fontLabel, FONTS, fontStack, mailFont, mailSize, PREFS, S, savePref, undoSeconds } from "./state.js";
import { fileIcon, laterTime, size } from "./format.js";
import { closeLayer, fail, sheet, toast } from "./ui.js";
import { loadList } from "./list.js";
import { syncSel } from "./actions.js";
import { afterSchedule, openThread, renderToolbar, showEmpty } from "./reader.js";
import { ADDR_RE, parseAddrs, renderCompose } from "./compose.js";
import { selectBox } from "./settings.js";
import { refreshCounts } from "./status.js";

export const fmtBarOn = () => PREFS.fmt_bar !== false;
export function toggleFmtBar() {
  savePref({ fmt_bar: !fmtBarOn() });
  const bar = $(".fmt-bar");
  if (bar) bar.classList.toggle("shut", !fmtBarOn());
  renderToolbar();
}
// the editor loses its caret when a select or the link sheet takes focus: keep the last one
let edRange = null;
document.addEventListener("selectionchange", () => {
  const ed = $(".compose .editor"), sel = getSelection();
  if (ed && sel.rangeCount && ed.contains(sel.anchorNode)) { edRange = sel.getRangeAt(0).cloneRange(); fmtSync(); }
});
export function edFocus() {
  const ed = $(".compose .editor");
  if (!ed) return null;
  const sel = getSelection();
  const inside = document.activeElement === ed && sel.rangeCount && ed.contains(sel.anchorNode);
  ed.focus();
  if (!inside && edRange && ed.contains(edRange.startContainer)) { sel.removeAllRanges(); sel.addRange(edRange); }
  return ed;
}
export function edChanged() {
  const ed = $(".compose .editor");
  if (!ed || !S.compose) return;
  S.compose.html = ed.innerHTML; touched(); fmtSync();
}
export function edCmd(cmd, val = null) {
  if (!edFocus()) return;
  document.execCommand("styleWithCSS", false, cmd === "fontName" || cmd === "foreColor");
  if (cmd === "blockquote") {
    const inQuote = getSelection().anchorNode?.parentElement?.closest(".editor blockquote");
    document.execCommand("formatBlock", false, inQuote ? "div" : "blockquote");
  } else if (cmd === "clear") {
    document.execCommand("removeFormat"); document.execCommand("unlink");
  } else document.execCommand(cmd, false, val);
  edChanged();
}
function fmtSize(px) {
  if (!edFocus()) return;
  document.execCommand("styleWithCSS", false, false);
  document.execCommand("fontSize", false, "7");
  for (const f of $$(".compose .editor font[size='7']")) {
    const sp = el("span", { style: `font-size:${px}px` });
    sp.append(...f.childNodes); f.replaceWith(sp);
  }
  edChanged();
}
const FMT_SIZES = [["12", "size_small"], ["14", "size_normal"], ["18", "size_large"], ["24", "size_huge"]];
export function fmtBar() {
  const b = (ic, tip, cmd, key) => {
    const n = iconBtn(ic, tip, () => (cmd === "link" ? linkSheet() : edCmd(cmd)), { key, cls: "tiny" });
    n.dataset.cmd = cmd;
    n.addEventListener("mousedown", (e) => e.preventDefault());
    return n;
  };
  const font = selectBox([["", t("font")], ...FONTS.map(([k]) => [k, fontLabel(k)])], "", (v) => { if (v) edCmd("fontName", fontStack(v)); font.firstChild.value = ""; });
  const size = selectBox([["", t("font_size")], ...FMT_SIZES.map(([px, k]) => [px, t(k)])], "", (v) => { if (v) fmtSize(+v); size.firstChild.value = ""; });
  font.classList.add("mini"); size.classList.add("mini");
  return el("div", { class: "fmt-bar" + (fmtBarOn() ? "" : " shut") }, el("div", { class: "fmt-in" },
    font, size, el("span", { class: "sep" }),
    b("bold", t("bold"), "bold", MOD + "B"), b("italic", t("italic"), "italic", MOD + "I"),
    b("underline", t("underline"), "underline", MOD + "U"), b("strikethrough", t("strike"), "strikeThrough"),
    el("span", { class: "sep" }),
    b("list", t("bullets"), "insertUnorderedList"), b("list-ordered", t("numbers"), "insertOrderedList"),
    b("text-quote", t("quote_block"), "blockquote"),
    el("span", { class: "sep" }),
    b("link", t("link"), "link", MOD + "K"), b("remove-formatting", t("clear_fmt"), "clear")));
}
export function fmtSync() {
  for (const n of $$(".fmt-bar [data-cmd]")) {
    const c = n.dataset.cmd;
    let on = false;
    try {
      if (c === "blockquote") on = !!getSelection().anchorNode?.parentElement?.closest(".editor blockquote");
      else if (!["link", "clear"].includes(c)) on = document.queryCommandState(c);
    } catch { /* not supported */ }
    n.classList.toggle("on", on);
  }
}
export function linkSheet() {
  const ed = $(".compose .editor");
  if (!ed) return;
  const range = edRange && ed.contains(edRange.startContainer) ? edRange.cloneRange() : null;
  const text = range ? range.toString() : "";
  const url = el("input", { type: "text", placeholder: "https://", spellcheck: "false", autocomplete: "off" });
  const label = el("input", { type: "text", value: text, placeholder: t("link"), spellcheck: "false" });
  const go = () => {
    let href = url.value.trim();
    if (!href) return closeLayer();
    if (!/^(https?:|mailto:)/i.test(href)) href = (/^[^\s/]+@[^\s/]+\.[^\s/]+$/.test(href) ? "mailto:" : "https://") + href;
    closeLayer();
    edRange = range;
    if (!edFocus()) return;
    const words = label.value.trim() || href.replace(/^mailto:/, "");
    if (range && !range.collapsed && words === text) document.execCommand("createLink", false, href);
    else document.execCommand("insertHTML", false, `<a href="${esc(href)}">${esc(words)}</a>`);
    edChanged();
  };
  for (const i of [url, label]) i.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  sheet(el("div", {}, el("h2", {}, t("link")), el("div", { class: "form" },
    el("label", {}, el("span", { class: "lab" }, t("link_url")), url),
    el("label", {}, el("span", { class: "lab" }, t("link")), label)),
    el("div", { class: "sheet-acts" }, el("button", { class: "btn", onclick: () => { closeLayer(); edFocus(); } }, t("cancel")),
      el("button", { class: "btn primary", onclick: go }, t("ok")))), { onclose: () => edFocus() });
  requestAnimationFrame(() => url.focus());
}

export function touched() {
  const c = S.compose;
  if (!c) return;
  c.dirty = true;
  setStatus("");
  clearTimeout(c.autosave);
  c.autosave = setTimeout(() => { if (S.compose === c && c.dirty) saveDraft(c).catch(() => {}); }, 15000);
}
function setStatus(s) {
  if (S.compose) S.compose.status = s;
  const n = $("#compose-status");
  if (n) n.textContent = s;
}

export function addrField(key, label, first = false) {
  const c = S.compose;
  const f = el("div", { class: "field" }, el("span", { class: "label" }, label));
  const chips = el("div", { class: "chips" });
  const input = el("input", { type: "text", autocomplete: "off", spellcheck: "false", "aria-label": label });
  let sug = null, sugItems = [], sugOn = 0, sugTimer = null;
  const draw = () => {
    chips.replaceChildren();
    c[key].forEach((p, k) => {
      const chip = el("span", { class: "chip" + (ADDR_RE.test(p.addr) ? "" : " bad"), title: p.addr },
        el("span", {}, p.name || p.addr),
        el("button", { tabindex: "-1", html: icon("x"), "aria-label": t("remove"), onclick: () => { c[key].splice(k, 1); draw(); touched(); input.focus(); } }));
      chips.append(chip);
    });
    chips.append(input);
    if (sug) chips.append(sug);
  };
  const closeSug = () => { sug?.remove(); sug = null; sugItems = []; };
  const add = (list) => {
    const have = new Set([...c.to, ...c.cc, ...c.bcc].map((x) => x.addr));
    for (const p of list) if (p.addr && !have.has(p.addr)) { c[key].push(p); have.add(p.addr); }
    input.value = ""; closeSug(); draw(); touched(); input.focus();
  };
  const commit = () => { const v = input.value.trim(); if (v) add(parseAddrs(v)); };
  const showSug = async () => {
    const q = input.value.trim();
    if (!q) return closeSug();
    let list = [];
    try { list = await api("contacts", { q }); } catch { return; }
    if (input.value.trim() !== q) return;
    const have = new Set([...c.to, ...c.cc, ...c.bcc].map((x) => x.addr));
    list = list.filter((p) => !have.has(p.addr));
    closeSug();
    if (!list.length) return;
    sugItems = list; sugOn = 0;
    sug = el("div", { class: "suggest" });
    list.forEach((p, k) => sug.append(el("button", { class: k === 0 ? "on" : "", onmousedown: (e) => { e.preventDefault(); add([p]); } },
      el("span", { class: "n" }, p.name || p.addr), p.name ? el("span", { class: "a" }, p.addr) : null)));
    chips.append(sug);
  };
  input.addEventListener("input", () => { clearTimeout(sugTimer); sugTimer = setTimeout(showSug, 120); if (/[,;]\s*$/.test(input.value)) commit(); });
  input.addEventListener("keydown", (e) => {
    if (sug && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      sugOn = (sugOn + (e.key === "ArrowDown" ? 1 : -1) + sugItems.length) % sugItems.length;
      [...sug.children].forEach((b, k) => b.classList.toggle("on", k === sugOn));
    } else if (e.key === "Enter" || (e.key === "Tab" && input.value.trim())) {
      if (sug && sugItems[sugOn]) { e.preventDefault(); add([sugItems[sugOn]]); }
      else if (input.value.trim()) { e.preventDefault(); commit(); }
    } else if (e.key === "Backspace" && !input.value && c[key].length) {
      c[key].pop(); draw(); touched();
    } else if (e.key === "Escape" && sug) { e.stopPropagation(); closeSug(); }
  });
  input.addEventListener("paste", (e) => {
    const txt = e.clipboardData.getData("text");
    if (/[,;\n]/.test(txt) || /@/.test(txt)) { e.preventDefault(); add(parseAddrs(input.value + txt)); }
  });
  input.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== input) { commit(); closeSug(); } }, 150));
  chips.addEventListener("mousedown", (e) => { if (e.target === chips) { e.preventDefault(); input.focus(); } });
  draw();
  f.append(chips);
  if (first) {
    const acts = el("div", { class: "field-acts" });
    if (!c.showCc) acts.append(el("button", { class: "text-btn", onclick: () => { c.showCc = true; rerenderFields(); $$(".compose .field")[1]?.querySelector("input")?.focus(); } }, t("cc")));
    if (!c.showBcc) acts.append(el("button", { class: "text-btn", onclick: () => { c.showBcc = true; rerenderFields(); $$(".compose .field").at(-1)?.querySelector("input")?.focus(); } }, t("bcc")));
    f.append(acts);
  }
  return f;
}
function rerenderFields() {
  const c = S.compose, box = $(".compose");
  $$(".compose .field").forEach((n) => n.remove());
  const nodes = [addrField("to", t("to"), true)];
  if (c.showCc) nodes.push(addrField("cc", t("cc")));
  if (c.showBcc) nodes.push(addrField("bcc", t("bcc")));
  box.prepend(...nodes);
}

export function renderAtts() {
  const box = $("#compose-atts");
  if (!box || !S.compose) return;
  box.replaceChildren();
  for (const a of S.compose.atts) {
    box.append(el("div", { class: "att" + (a.uploading ? " busy" : ""), title: a.name },
      el("div", { class: "att-icon", html: icon(a.uploading ? "loader-circle" : fileIcon(a.name), a.uploading ? "spin" : "") }),
      el("div", { class: "att-text" }, el("div", { class: "att-name" }, a.name), el("div", { class: "att-size" }, a.uploading ? t("uploading") : size(a.size))),
      a.uploading ? null : iconBtn("x", t("remove"), () => { S.compose.atts = S.compose.atts.filter((x) => x !== a); renderAtts(); touched(); }, { cls: "tiny" })));
  }
}

export function pickFiles() {
  const inp = el("input", { type: "file", multiple: true, style: "display:none" });
  inp.addEventListener("change", () => { uploadFiles([...inp.files]); inp.remove(); });
  document.body.append(inp);
  inp.click();
}

export async function uploadFiles(files) {
  const c = S.compose;
  if (!c) return;
  for (const f of files) {
    const a = { name: f.name, size: f.size, uploading: true };
    c.atts.push(a);
    renderAtts();
    try {
      const r = await fetch("/upload", { method: "POST", headers: { "X-Token": TOKEN, "X-Name": encodeURIComponent(f.name) }, body: f });
      const j = await r.json();
      if (!j.ok) throw new Error(tr(j.error) || t("error"));
      Object.assign(a, j.data, { uploading: false });
      touched();
    } catch (e) {
      c.atts = c.atts.filter((x) => x !== a);
      fail(e);
    }
    if (S.compose === c) renderAtts();
  }
}

export function onPaste(e) {
  const dt = e.clipboardData;
  const imgs = [...dt.files].filter((f) => f.type.startsWith("image/"));
  if (imgs.length) {
    e.preventDefault();
    for (const f of imgs) {
      const rd = new FileReader();
      rd.onload = () => { document.execCommand("insertHTML", false, `<img src="${rd.result}" alt="">`); };
      rd.readAsDataURL(f);
    }
    return;
  }
  const html = dt.getData("text/html");
  if (html) {
    e.preventDefault();
    document.execCommand("insertHTML", false, cleanHTML(html));
  }
}

export function cleanHTML(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("script,style,meta,link,title,iframe,object,embed,form,input,button,select,textarea,svg,video,audio").forEach((n) => n.remove());
  const keep = { href: 1, src: 1, alt: 1, colspan: 1, rowspan: 1, width: 1, height: 1, style: 1, align: 1, valign: 1 };
  for (const n of doc.body.querySelectorAll("*")) {
    for (const a of [...n.attributes]) {
      const k = a.name.toLowerCase();
      if (!keep[k]) n.removeAttribute(a.name);
      else if ((k === "href" || k === "src") && /^\s*(javascript|vbscript|data:text)/i.test(a.value)) n.removeAttribute(a.name);
      else if (k === "style") n.setAttribute("style", a.value.replace(/(position|z-index|behavior|expression)\s*:[^;]*;?/gi, ""));
    }
  }
  return doc.body.innerHTML;
}

export function composeState() {
  const c = S.compose;
  const ed = $(".compose .editor");
  if (ed) c.html = ed.innerHTML;
  const inputs = $$(".compose .chips input");
  // an address still being typed counts
  ["to", "cc", "bcc"].filter((k) => k === "to" || (k === "cc" ? c.showCc : c.showBcc)).forEach((k, idx) => {
    const v = inputs[idx]?.value.trim();
    if (v) { c[k].push(...parseAddrs(v)); inputs[idx].value = ""; }
  });
  return {
    mode: c.mode, orig: c.orig, replace: c.replace, to: c.to, cc: c.cc, bcc: c.bcc, subject: c.subject,
    html: wrapBody(c.html), atts: c.atts.filter((a) => !a.uploading).map(({ path, name, size }) => ({ path, name, size })),
    use_signature: c.use_signature, irt: c.irt, refs: c.refs,
  };
}

// Outlook shows unstyled mail in Times: always say which font the body is in
function wrapBody(html) {
  if (!html || !html.replace(/<br\s*\/?>|<\/?div>|&nbsp;|\s/gi, "")) return html || "";
  return `<div data-rd-body="1" style="font-family:${mailFont().replace(/"/g, "'")};font-size:${mailSize()}px">${html}</div>`;
}

let saving = Promise.resolve();
export function saveDraft(c = S.compose) {
  const job = saving.then(async () => {
    if (!c) return;
    const st = S.compose === c ? composeState() : c.lastState;
    if (!st) return;
    if (S.compose === c) setStatus(t("saving"));
    try {
      const r = await api("save_draft", st);
      c.replace = r.id; c.dirty = false; c.lastState = { ...st, replace: r.id };
      if (S.compose === c) setStatus(t("saved"));
      refreshCounts();
    } catch (e) {
      if (S.compose === c) setStatus("");
      throw e;
    }
  });
  saving = job.catch(() => {});
  return job;
}

// close the compose (saving it when it was changed). false when the save failed and it stays open.
export async function leaveCompose() {
  const c = S.compose;
  if (!c) return true;
  clearTimeout(c.autosave);
  if (c.busy) return false;
  if (c.dirty) {
    try { await saveDraft(c); toast(t("draft_saved")); }
    catch (e) { fail(e); return false; }
  }
  S.compose = null;
  renderToolbar();
  if (S.folder === "drafts") loadList({ quiet: true });
  return true;
}

export async function closeCompose() {
  if (!(await leaveCompose())) return;
  // a draft gets a new id each time it is saved: never reopen the old one
  if (S.sel && S.folder !== "drafts" && S.rows.some((x) => x.id === S.sel && x.folder !== "drafts")) openThread(S.sel);
  else { S.sel = null; syncSel(); showEmpty(); }
}

export async function discardCompose() {
  const c = S.compose;
  if (!c) return;
  clearTimeout(c.autosave);
  await saving;
  S.compose = null;
  if (c.replace) {
    try { await api("delete_draft", { id: c.replace }); toast(t("draft_deleted")); } catch (e) { fail(e); }
    refreshCounts();
    if (S.folder === "drafts") { S.sel = null; loadList({ quiet: true }); }
  }
  if (S.sel && S.folder !== "drafts") openThread(S.sel); else showEmpty();
}

export async function sendCompose(force = false, at = null) {
  const c = S.compose;
  if (!c || c.busy) return;
  clearTimeout(c.autosave);
  if (c.atts.some((a) => a.uploading)) return toast(t("uploading"));
  await saving;
  const st = composeState();
  c.busy = true; renderToolbar();
  let r;
  try { r = await api("prepare_send", { ...st, force, at }); }
  catch (e) { c.busy = false; renderToolbar(); return fail(e); }
  c.busy = false;
  if (r.problems && r.problems.length) {
    renderToolbar();
    return problemsSheet(r.problems, at);
  }
  c.replace = r.id; c.dirty = false; c.lastState = { ...st, replace: r.id };
  const reopen = async () => { if (S.compose && !(await leaveCompose())) return; S.compose = c; renderCompose(); };
  // out of the way while it waits
  S.compose = null;
  if (S.sel && S.folder !== "drafts" && S.folder !== "scheduled") openThread(S.sel); else showEmpty();
  if (r.queued) { toast(t("queued_offline"), { ms: 7000 }); return afterSchedule(); }
  if (at) {
    try { await api("schedule", { id: r.id, at }); }
    catch (e) { fail(e); return reopen(); }
    toast(t("scheduled_for", laterTime(at)), { ms: 6000, action: { label: t("undo"), run: async () => {
      try { await api("unschedule", { id: r.id }); } catch (e) { return fail(e); }
      afterSchedule(); reopen();
    } } });
    afterSchedule();
    return;
  }
  await sendWithUndo(r.id, reopen);
}

// the pause after Send: Undo stops the mail before it leaves; after that it can't be called back
export async function sendWithUndo(id, onUndo) {
  const wait = undoSeconds() * 1000;
  let undone = false;
  const tt = toast(t("sending"), wait ? { action: { label: t("undo"), run: () => { undone = true; } }, ms: 0, bar: wait } : { ms: 0 });
  for (let k = 0; k < wait / 100 && !undone; k++) await sleep(100);
  if (undone) { tt.close(); return onUndo?.(); }
  tt.node.querySelector(".toast-act")?.remove();
  tt.node.querySelector(".toast-bar")?.remove();
  try {
    const res = await api("send", { id });
    tt.close();
    if (res.queued) { toast(t("queued_offline"), { ms: 7000 }); return afterSchedule(); }
    const after = res.problems_after_sending || [];
    if (after.length) toast(after.map(tr).join(" "), { error: true, ms: 12000 });
    else toast(t("sent_ok"));
    refreshCounts();
    if (["sent", "drafts", "scheduled"].includes(S.folder)) loadList({ quiet: true });
    if (S.thread) openThread(S.focus || S.sel);
  } catch (e) {
    tt.close();
    fail(e);
    onUndo?.();
  }
}

function problemsSheet(problems, at = null) {
  const cap = (x) => x.charAt(0).toUpperCase() + x.slice(1);
  const box = sheet(el("div", {},
    el("h2", { html: icon("triangle-alert") + esc(t("problems")) }),
    el("ul", {}, problems.map((p) => el("li", {}, cap(tr(p))))),
    el("div", { class: "sheet-acts" },
      el("button", { class: "btn", onclick: () => { closeLayer(); $(".compose .editor")?.focus(); } }, t("keep_editing")),
      el("button", { class: "btn primary", onclick: () => { closeLayer(); sendCompose(true, at); } }, t(at ? "schedule" : "send_anyway")))));
  box.querySelector(".btn").focus();
}
