// ragdoll-mail desktop app. Talks to ragdoll_app.py over /api/<name> (JSON, X-Token header).
import { ICONS } from "./icons.js";

// ---------------------------------------------------------------- basics

const TOKEN = (() => {
  const t = new URLSearchParams(location.hash.slice(1)).get("t");
  try {
    if (t) sessionStorage.setItem("ragdoll-token", t);
    return t || sessionStorage.getItem("ragdoll-token") || "";
  } catch { return t || ""; }
})();
if (location.hash) history.replaceState(null, "", location.pathname);

const ZH = (navigator.language || "").toLowerCase().startsWith("zh");
const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const WIN = /Win/.test(navigator.platform || navigator.userAgent);
const MOD = MAC ? "⌘" : "Ctrl+";

const EN = {
  inbox: "Inbox", drafts: "Drafts", sent: "Sent", archive: "Archive", trash: "Trash",
  compose: "New mail", search: "Search", reply: "Reply", replyall: "Reply all", forward: "Forward",
  archive_it: "Archive", trash_it: "Move to Trash", restore: "Move to Inbox", unread: "Mark as unread",
  read: "Mark as read", send: "Send", attach: "Attach files", discard: "Delete draft",
  to: "To", cc: "Cc", bcc: "Bcc", subject: "Subject", write: "Write your message…",
  no_mail: "No mail here", no_results: "Nothing found", syncing: "Getting your mail…",
  loading: "Loading…", me: "me", to_x: "To: %s", draft: "Draft", no_subject: "(no subject)",
  saved: "Saved", saving: "Saving…", draft_saved: "Draft saved", draft_deleted: "Draft deleted",
  sending: "Sending…", sent_ok: "Sent", undo: "Undo", archived: "Archived", trashed: "Moved to Trash",
  restored: "Moved to Inbox", saved_to: "Saved to Downloads", show: "Show", images_hidden: "Images from the web are hidden.",
  show_images: "Show images", problems: "Check before sending", send_anyway: "Send anyway",
  keep_editing: "Keep editing", settings: "Settings", sync_now: "Sync now", demo: "Demo mailbox",
  account: "Account", signature: "Signature", appearance: "Appearance", name: "Your name",
  email: "Email address", password: "Password", pw_saved: "Saved in the system keychain",
  incoming: "Incoming server (IMAP)", outgoing: "Outgoing server (SMTP)", port: "Port",
  require_cc: "Always Cc", test: "Test connection", testing: "Testing…", test_ok: "Signed in to both servers.",
  save: "Save", cancel: "Cancel", system: "System", light: "Light", dark: "Dark",
  setup_title: "Add your mail account", servers: "Server settings", sign_in: "Sign in", signing_in: "Signing in…",
  update_to: "Update to %s", run_update: "Run in a terminal: ragdoll update", yesterday: "Yesterday",
  pw_env: "The password comes from the %s environment variable. A password saved here is used only when that variable is not set.",
  remove: "Remove", open: "Open", download: "Save to Downloads", drop_files: "Drop files to attach",
  sig_none: "No signature", remove_sig: "Leave out the signature", conn_lost: "Can't reach the server",
  error: "Something went wrong", recipients_more: "and %s more", version: "Version %s", uploading: "Uploading…",
  show_quote: "Show quoted text", copy: "Copy",
};
const ZHS = {
  inbox: "收件箱", drafts: "草稿箱", sent: "已发送", archive: "归档", trash: "已删除",
  compose: "写邮件", search: "搜索", reply: "回复", replyall: "回复全部", forward: "转发",
  archive_it: "归档", trash_it: "删除", restore: "移回收件箱", unread: "标为未读", read: "标为已读",
  send: "发送", attach: "添加附件", discard: "删除草稿", to: "收件人", cc: "抄送", bcc: "密送",
  subject: "主题", write: "写点什么…", no_mail: "这里没有邮件", no_results: "没有找到",
  syncing: "正在收取邮件…", loading: "加载中…", me: "我", to_x: "致：%s", draft: "草稿",
  no_subject: "（无主题）", saved: "已保存", saving: "保存中…", draft_saved: "草稿已保存",
  draft_deleted: "草稿已删除", sending: "正在发送…", sent_ok: "已发送", undo: "撤销", archived: "已归档",
  trashed: "已删除", restored: "已移回收件箱", saved_to: "已存到“下载”", show: "显示",
  images_hidden: "已隐藏网络图片。", show_images: "显示图片", problems: "发送前请检查",
  send_anyway: "仍然发送", keep_editing: "继续编辑", settings: "设置", sync_now: "立即同步",
  demo: "演示邮箱", account: "账户", signature: "签名", appearance: "外观", name: "你的名字",
  email: "邮箱地址", password: "密码", pw_saved: "已存在系统钥匙串", incoming: "收信服务器（IMAP）",
  outgoing: "发信服务器（SMTP）", port: "端口", require_cc: "总是抄送", test: "测试连接",
  testing: "测试中…", test_ok: "两个服务器都登录成功。", save: "保存", cancel: "取消", system: "跟随系统",
  light: "浅色", dark: "深色", setup_title: "添加邮箱账户", servers: "服务器设置", sign_in: "登录",
  signing_in: "登录中…", update_to: "更新到 %s", run_update: "在终端运行：ragdoll update",
  yesterday: "昨天", pw_env: "密码来自环境变量 %s。只有这个变量没设置时，才会用这里保存的密码。",
  remove: "移除", open: "打开", download: "存到“下载”", drop_files: "松开即可添加附件",
  sig_none: "没有签名", remove_sig: "这封不带签名", conn_lost: "连不上服务器", error: "出错了",
  recipients_more: "等 %s 人", version: "版本 %s", uploading: "上传中…", show_quote: "显示引用内容",
  copy: "复制",
};
const STR = ZH ? { ...EN, ...ZHS } : EN;
const t = (k, ...a) => { let s = STR[k] ?? k; for (const x of a) s = s.replace("%s", x); return s; };

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const svg = (n) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ""}</svg>`;
const icon = (n, cls = "") => `<span class="i ${cls}">${svg(n)}</span>`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}
function iconBtn(name, tip, onclick, extra = {}) {
  return el("button", { class: "icon-btn" + (extra.cls ? " " + extra.cls : ""), "data-tip": tip, "data-key": extra.key, html: icon(name), onclick, disabled: extra.disabled, "aria-label": tip });
}

async function api(name, args = {}) {
  let r;
  try {
    r = await fetch("/api/" + name, { method: "POST", headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(args) });
  } catch {
    throw new Error(ZH ? "app 的后台没有响应。请重新打开 ragdoll-mail。" : "The app's background service is not answering. Reopen ragdoll-mail.");
  }
  let j;
  try { j = await r.json(); } catch { throw new Error(t("error")); }
  if (!j.ok) throw new Error(j.error || t("error"));
  return j.data;
}

// ---------------------------------------------------------------- state

const S = {
  boot: null, folder: "inbox", rows: [], more: false, query: "", loadingMore: false,
  sel: null, thread: null, focus: null, compose: null, rev: 0, update: null, error: null,
  theme: "system", showImages: new Set(), syncing: false,
};
const FOLDER_ICON = { inbox: "inbox", drafts: "file", sent: "send", archive: "archive", trash: "trash-2" };

// ---------------------------------------------------------------- theme

const darkMQ = matchMedia("(prefers-color-scheme: dark)");
const isDark = () => document.documentElement.dataset.theme === "dark";
function applyTheme(theme) {
  S.theme = theme || "system";
  const dark = S.theme === "dark" || (S.theme === "system" && darkMQ.matches);
  const was = document.documentElement.dataset.theme;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  if (was && was !== document.documentElement.dataset.theme) refreshFrames();
  syncWindowTheme();
}
// the native title bar (Windows caption, macOS traffic lights) follows the app theme, not only the system's
function syncWindowTheme() {
  if (!window.pywebview) return;
  const css = getComputedStyle(document.documentElement);
  api("window_theme", {
    dark: document.documentElement.dataset.theme === "dark",
    bg: css.getPropertyValue("--bg").trim(),
    text: css.getPropertyValue("--text").trim(),
  }).catch(() => {});
}
darkMQ.addEventListener("change", () => applyTheme(S.theme));

// ---------------------------------------------------------------- time and size

const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
function shortTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), now = new Date();
  if (sameDay(d, now)) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (sameDay(d, y)) return t("yesterday");
  if (now - d < 6 * 86400e3 && d < now) return d.toLocaleDateString([], { weekday: "short" });
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString([], { month: "short", day: "numeric" });
  return d.toLocaleDateString([], { year: "numeric", month: "numeric", day: "numeric" });
}
function longTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString([], { weekday: "short", year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function size(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB";
}
function fileIcon(name) {
  const x = (name.split(".").pop() || "").toLowerCase();
  if (["pdf", "doc", "docx", "txt", "rtf", "odt", "md", "pages"].includes(x)) return "file-text";
  if (["xls", "xlsx", "csv", "numbers", "ods"].includes(x)) return "file-spreadsheet";
  if (["png", "jpg", "jpeg", "gif", "webp", "heic", "bmp", "tif", "tiff", "svg"].includes(x)) return "file-image";
  if (["zip", "rar", "7z", "gz", "tar", "tgz"].includes(x)) return "file-archive";
  return "file";
}
const nameOf = (p) => (p && (p.name || p.addr)) || "";
function who(p) { return p && p.addr === S.boot?.user ? t("me") : nameOf(p); }
function initials(p) {
  const s = (p?.name || p?.addr || "?").trim();
  if (/^[㐀-鿿]/.test(s)) return s[0];
  const parts = s.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

// ---------------------------------------------------------------- toasts, tips, menus, sheets

function toast(text, opts = {}) {
  const box = $("#toasts");
  const node = el("div", { class: "toast" + (opts.error ? " err" : "") + (opts.action ? "" : " solo"), role: "status" }, el("span", {}, text));
  let done = false;
  const close = () => { if (done) return; done = true; node.remove(); };
  if (opts.action) node.append(el("button", { onclick: () => { close(); opts.action.run(); } }, opts.action.label));
  box.append(node);
  const ms = opts.ms ?? (opts.error ? 7000 : 3200);
  if (ms) setTimeout(close, ms);
  return { close, node, set: (s) => { node.firstChild.textContent = s; } };
}
const fail = (e) => toast(e?.message || String(e), { error: true });

let tipEl = null, tipTimer = null;
document.addEventListener("mouseover", (e) => {
  const b = e.target.closest?.("[data-tip]");
  clearTimeout(tipTimer);
  if (tipEl) { tipEl.remove(); tipEl = null; }
  if (!b || b.disabled) return;
  tipTimer = setTimeout(() => {
    const r = b.getBoundingClientRect();
    tipEl = el("div", { class: "tip", html: esc(b.dataset.tip) + (b.dataset.key ? `<kbd>${esc(b.dataset.key)}</kbd>` : "") });
    document.body.append(tipEl);
    const w = tipEl.offsetWidth;
    tipEl.style.left = Math.max(6, Math.min(innerWidth - w - 6, r.left + r.width / 2 - w / 2)) + "px";
    tipEl.style.top = (r.bottom + 6 + 24 > innerHeight ? r.top - 30 : r.bottom + 6) + "px";
  }, 550);
});
document.addEventListener("mousedown", () => { clearTimeout(tipTimer); if (tipEl) { tipEl.remove(); tipEl = null; } }, true);

function closeLayer() { $("#layer").replaceChildren(); }
function menu(anchor, items, { above = false } = {}) {
  closeLayer();
  const m = el("div", { class: "menu", role: "menu" });
  for (const it of items) {
    if (it === "-") m.append(el("hr"));
    else if (it.note) m.append(el("div", { class: "menu-note" }, it.note));
    else m.append(el("button", { onclick: () => { closeLayer(); it.run(); }, html: icon(it.icon) + esc(it.label) + (it.key ? `<span class="grow"></span><kbd>${esc(it.key)}</kbd>` : "") }));
  }
  const catcher = el("div", { style: "position:fixed;inset:0", onmousedown: closeLayer });
  $("#layer").append(catcher, m);
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.min(r.left, innerWidth - m.offsetWidth - 8) + "px";
  m.style.top = (above ? r.top - m.offsetHeight - 6 : r.bottom + 6) + "px";
}
function sheet(node, { wide = false, onclose } = {}) {
  closeLayer();
  const box = el("div", { class: "sheet" + (wide ? " wide" : ""), role: "dialog" }, node);
  const scrim = el("div", { class: "scrim", onmousedown: (e) => { if (e.target === scrim) { closeLayer(); onclose?.(); } } }, box);
  $("#layer").append(scrim);
  return box;
}
const layerOpen = () => $("#layer").children.length > 0;

// ---------------------------------------------------------------- sidebar

function renderNav() {
  const nav = $("#nav");
  nav.replaceChildren();
  for (const f of S.boot.folders) {
    const n = f.key === "inbox" ? f.unread : f.key === "drafts" ? f.total : 0;
    const b = el("button", { class: "nav-item" + (f.key === S.folder && !S.query ? " on" : ""), "data-folder": f.key, onclick: () => openFolder(f.key),
      html: icon(FOLDER_ICON[f.key] || "folder-open") + `<span class="label">${esc(t(f.key))}</span>` + (n ? `<span class="count">${n}</span>` : "") });
    if (f.key === "archive" || f.key === "trash" || f.key === "inbox") {
      b.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("x-ragdoll/ids")) { e.preventDefault(); b.classList.add("drop"); } });
      b.addEventListener("dragleave", () => b.classList.remove("drop"));
      b.addEventListener("drop", (e) => { b.classList.remove("drop"); const ids = JSON.parse(e.dataTransfer.getData("x-ragdoll/ids") || "[]"); if (ids.length) moveMail(ids, f.key); });
    }
    nav.append(b);
  }
  $("#account-addr").textContent = S.boot.demo ? t("demo") : S.boot.user;
  const up = $("#update");
  up.hidden = !S.update;
  if (S.update) up.innerHTML = icon("download") + `<span>${esc(t("update_to", "v" + S.update.version))}</span>`;
}

function accountMenu() {
  menu($("#account"), [
    { note: S.boot.demo ? t("demo") : S.boot.user },
    { icon: "settings", label: t("settings"), key: MOD + ",", run: openSettings },
    { icon: "refresh-cw", label: t("sync_now"), run: () => api("sync").then(() => toast(t("syncing"))).catch(fail) },
    "-",
    { note: t("version", S.boot.version) },
  ], { above: true });
}

// ---------------------------------------------------------------- list

function rowTemplate(r) {
  const outgoing = r.folder === "sent" || r.folder === "drafts";
  let name;
  if (outgoing) {
    const names = r.to.map(who);
    name = names.length ? t("to_x", names.slice(0, 3).join(", ") + (names.length > 3 ? " " + t("recipients_more", names.length - 3) : "")) : (r.folder === "drafts" ? t("draft") : "");
  } else name = who(r.from);
  const clip = r.atts.length ? icon("paperclip", "small") : "";
  const tag = S.query && r.folder !== "inbox" ? `<span class="tag">${esc(t(r.folder) || r.folder)}</span>` : "";
  const acts = S.folder === "trash" && !S.query
    ? `<button class="icon-btn tiny" data-act="inbox" data-tip="${esc(t("restore"))}">${icon("inbox")}</button>`
    : `<button class="icon-btn tiny" data-act="archive" data-tip="${esc(t("archive_it"))}" data-key="E">${icon("archive")}</button>` +
      `<button class="icon-btn tiny" data-act="trash" data-tip="${esc(t("trash_it"))}" data-key="#">${icon("trash-2")}</button>`;
  return `<div class="row${r.unread ? " unread" : ""}${r.id === S.sel ? " on" : ""}" data-id="${esc(r.id)}" draggable="true">` +
    `<span class="dot"></span><span class="who">${esc(name)}</span>` +
    `<span class="meta">${tag}${clip}${esc(shortTime(r.ts))}</span>` +
    `<span class="subj">${esc(r.subject || t("no_subject"))}</span>` +
    `<span class="snip">${esc(r.snippet) || "&nbsp;"}</span>` +
    `<span class="hover-acts">${acts}</span></div>`;
}

function renderRows() {
  const box = $("#rows");
  if (!S.rows.length) {
    const msg = S.query ? t("no_results") : (S.syncing && S.folder === "inbox" ? t("syncing") : t("no_mail"));
    box.innerHTML = `<div class="rows-empty">${S.syncing && !S.query ? icon("loader-circle", "big spin") : ""}<span>${esc(msg)}</span></div>`;
    return;
  }
  box.innerHTML = S.rows.map(rowTemplate).join("") + (S.more ? `<div class="rows-more">${icon("loader-circle", "spin")}</div>` : "");
}

let listSeq = 0;
async function loadList({ quiet = false } = {}) {
  const seq = ++listSeq;
  try {
    let rows, more = false;
    if (S.query) rows = (await api("search", { q: S.query })).rows;
    else {
      const limit = quiet ? Math.max(100, S.rows.length) : 100;
      const r = await api("list", { folder: S.folder, limit, offset: 0 });
      rows = r.rows; more = r.more;
    }
    if (seq !== listSeq) return;
    rows = rows.filter((x) => !hidden.has(x.id));
    if (quiet && JSON.stringify(rows) === JSON.stringify(S.rows) && more === S.more) return;
    const box = $("#rows"), top = box.scrollTop;
    S.rows = rows; S.more = more;
    renderRows();
    if (quiet) box.scrollTop = top; else box.scrollTop = 0;
  } catch (e) { if (!quiet) fail(e); }
}

async function loadMore() {
  if (!S.more || S.loadingMore || S.query) return;
  S.loadingMore = true;
  try {
    const r = await api("list", { folder: S.folder, limit: 100, offset: S.rows.length });
    const have = new Set(S.rows.map((x) => x.id));
    S.rows.push(...r.rows.filter((x) => !have.has(x.id) && !hidden.has(x.id)));
    S.more = r.more;
    const top = $("#rows").scrollTop;
    renderRows();
    $("#rows").scrollTop = top;
  } catch (e) { fail(e); } finally { S.loadingMore = false; }
}

function markRow(id, patch) {
  const r = S.rows.find((x) => x.id === id);
  if (r) Object.assign(r, patch);
  const node = $(`.row[data-id="${CSS.escape(id)}"]`);
  if (node && "unread" in patch) node.classList.toggle("unread", patch.unread);
}

async function openFolder(key) {
  if (!(await leaveCompose())) return;
  S.folder = key; S.query = ""; $("#search").value = ""; syncSearchUI();
  S.sel = null; S.rows = []; S.more = false;
  renderNav(); renderRows(); showEmpty();
  await loadList();
}

$("#rows").addEventListener("click", async (e) => {
  const row = e.target.closest(".row");
  if (!row) return;
  const act = e.target.closest("[data-act]");
  if (act) { e.stopPropagation(); return moveMail([row.dataset.id], act.dataset.act); }
  selectRow(row.dataset.id);
});
$("#rows").addEventListener("scroll", () => {
  const b = $("#rows");
  if (b.scrollTop + b.clientHeight > b.scrollHeight - 400) loadMore();
});
$("#rows").addEventListener("dragstart", (e) => {
  const row = e.target.closest(".row");
  if (!row) return;
  e.dataTransfer.setData("x-ragdoll/ids", JSON.stringify([row.dataset.id]));
  e.dataTransfer.effectAllowed = "move";
});

async function selectRow(id, { keepFocus = false } = {}) {
  if (S.compose && !(await leaveCompose())) return;
  S.sel = id;
  $$(".row.on").forEach((n) => n.classList.remove("on"));
  const node = $(`.row[data-id="${CSS.escape(id)}"]`);
  node?.classList.add("on");
  node?.scrollIntoView({ block: "nearest" });
  if (!keepFocus) $("#rows").focus({ preventScroll: true });
  const r = S.rows.find((x) => x.id === id);
  if (r && r.folder === "drafts") return openCompose({ mode: "draft", id });
  openThread(id);
}

function step(d) {
  if (!S.rows.length) return;
  let k = S.rows.findIndex((x) => x.id === S.sel);
  k = k < 0 ? 0 : Math.max(0, Math.min(S.rows.length - 1, k + d));
  selectRow(S.rows[k].id);
}

// Moves wait a few seconds so Undo is free; until then the rows are only hidden.
const hidden = new Set();
const pendingMoves = new Set();
function moveMail(ids, to) {
  const k = S.rows.findIndex((x) => x.id === ids[0]);
  const next = S.rows.slice(k + 1).find((x) => !ids.includes(x.id)) || S.rows.slice(0, k).reverse().find((x) => !ids.includes(x.id));
  const wasSel = ids.includes(S.sel) || (S.thread && ids.some((i) => S.thread.rows.some((r) => r.id === i)));
  const sel = S.sel;
  ids.forEach((i) => hidden.add(i));
  S.rows = S.rows.filter((x) => !ids.includes(x.id));
  renderRows();
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
  toast(t(to === "archive" ? "archived" : to === "trash" ? "trashed" : "restored"), {
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

async function toggleUnread() {
  const id = S.focus || S.sel;
  const r = S.rows.find((x) => x.id === id) || S.thread?.rows.find((x) => x.id === id);
  if (!r) return;
  const unread = !r.unread;
  try {
    await api("mark", { ids: [id], flag: "seen", on: !unread });
    markRow(id, { unread });
    if (S.thread) { const tr = S.thread.rows.find((x) => x.id === id); if (tr) tr.unread = unread; }
    renderToolbar();
    refreshCounts();
  } catch (e) { fail(e); }
}

// ---------------------------------------------------------------- search

let searchTimer = null;
function syncSearchUI() {
  const v = $("#search").value;
  $("#search-clear").hidden = !v;
  $("#search-kbd").hidden = !!v;
}
$("#search").placeholder = t("search");
$("#search-clear").innerHTML = icon("x");
$("#search-clear").addEventListener("click", () => { $("#search").value = ""; onSearch(true); $("#search").focus(); });
$("#search").addEventListener("input", () => onSearch());
$("#search").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.preventDefault(); $("#search").value = ""; onSearch(true); $("#search").blur(); $("#rows").focus(); }
  if (e.key === "ArrowDown" || e.key === "Enter") { e.preventDefault(); $("#rows").focus(); if (S.rows.length) selectRow(S.rows[0].id); }
});
function onSearch(now = false) {
  syncSearchUI();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const q = $("#search").value.trim();
    if (q === S.query) return;
    S.query = q;
    renderNav();
    loadList();
  }, now ? 0 : 220);
}

// ---------------------------------------------------------------- reader

function showEmpty() {
  S.thread = null; S.focus = null;
  $("#pane").innerHTML = `<div class="pane-empty"><img src="logo.png" alt=""></div>`;
  renderToolbar();
}

function renderToolbar() {
  const tools = $("#tools"), prim = $("#primary");
  tools.replaceChildren();
  $("#toolbar").classList.toggle("lined", !!S.compose);
  if (S.compose) {
    tools.append(
      iconBtn("paperclip", t("attach"), () => pickFiles()),
      iconBtn("trash-2", t("discard"), () => discardCompose()),
    );
    const st = el("span", { class: "compose-status", id: "compose-status" }, S.compose.status || "");
    prim.hidden = false;
    prim.disabled = !!S.compose.busy;
    prim.innerHTML = esc(t("send")) + `<kbd>${MOD}↩</kbd>`;
    prim.onclick = () => sendCompose();
    prim.before(st);
    $$(".compose-status").forEach((n) => { if (n !== st) n.remove(); });
    return;
  }
  $$(".compose-status").forEach((n) => n.remove());
  const has = !!S.thread;
  const id = S.focus || S.sel;
  const r = S.thread?.rows.find((x) => x.id === id);
  const inTrash = r?.folder === "trash";
  tools.append(
    iconBtn("reply", t("reply"), () => openCompose({ mode: "reply", id }), { key: "R", disabled: !has }),
    iconBtn("reply-all", t("replyall"), () => openCompose({ mode: "replyall", id }), { key: "A", disabled: !has }),
    iconBtn("forward", t("forward"), () => openCompose({ mode: "forward", id }), { key: "F", disabled: !has }),
    el("span", { class: "sep" }),
    inTrash
      ? iconBtn("inbox", t("restore"), () => moveMail([id], "inbox"), { disabled: !has })
      : iconBtn("archive", t("archive_it"), () => moveMail([id], "archive"), { key: "E", disabled: !has || r?.folder === "archive" }),
    iconBtn("trash-2", t("trash_it"), () => moveMail([id], "trash"), { key: "#", disabled: !has || inTrash }),
    iconBtn(r && r.unread ? "mail-open" : "mail", r && r.unread ? t("read") : t("unread"), toggleUnread, { key: "U", disabled: !has }),
  );
  prim.hidden = !has;
  prim.disabled = false;
  prim.innerHTML = esc(t("reply"));
  prim.onclick = () => openCompose({ mode: "reply", id: S.focus || S.sel });
}

let threadSeq = 0;
async function openThread(id) {
  const seq = ++threadSeq;
  S.focus = id;
  let th;
  try { th = await api("thread", { id }); } catch (e) { if (seq === threadSeq) { fail(e); showEmpty(); } return; }
  if (seq !== threadSeq) return;
  S.thread = th;
  const doc = el("div", { class: "doc" }, el("h1", { class: "doc-subject" }, th.subject || t("no_subject")));
  for (const r of th.rows) doc.append(msgNode(r, r.id === id));
  $("#pane").replaceChildren(doc);
  $("#pane").scrollTop = 0;
  renderToolbar();
  const open = $(`.msg[data-id="${CSS.escape(id)}"]`);
  if (open && th.rows.length > 1) requestAnimationFrame(() => { $("#pane").scrollTop = Math.max(0, open.offsetTop - 70); });
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
      toLine.classList.toggle("open");
      if (toLine.classList.contains("open")) toLine.textContent = [t("to") + " " + r.to.map((p) => p.name ? `${p.name} <${p.addr}>` : p.addr).join(", "), r.cc.length ? t("cc") + " " + r.cc.map((p) => p.name ? `${p.name} <${p.addr}>` : p.addr).join(", ") : ""].filter(Boolean).join("\n");
      else toLine.textContent = t("to") + " " + to.map(who).join(", ");
      toLine.style.whiteSpace = toLine.classList.contains("open") ? "pre-wrap" : "";
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

function renderBody(body, m) {
  body.replaceChildren();
  const remote = m.remote && S.showImages.has(m.id);
  if (m.remote && !remote) {
    body.append(el("div", { class: "imgs-bar" }, el("span", { html: icon("image", "small") }), el("span", {}, t("images_hidden")), el("span", { class: "grow" }),
      el("button", { class: "link-btn", onclick: () => { S.showImages.add(m.id); renderBody(body, m); } }, t("show_images"))));
  }
  const frame = mailFrame(m.html, { plain: m.plain, remote, quote: true });
  body.append(frame.node);
  if (m.atts.length) {
    const atts = el("div", { class: "atts" });
    for (const a of m.atts) atts.append(attNode(a, m.id));
    body.append(atts);
  }
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

// ---------------------------------------------------------------- mail frames

const FRAME_FONT = getComputedStyle(document.documentElement).getPropertyValue("--font");
const QUOTE_SEL = ".gmail_quote, .gmail_extra, #divRplyFwdMsg, blockquote[type=cite], .rd-quote, #appendonsend, .yahoo_quoted, " +
  "#mail-editor-reference-message-container, .moz-cite-prefix, #isForwardContent, #origbody, .protonmail_quote, div[id^=reply-intro]";
const QUOTE_TEXT = /^\s*(-{2,}\s*(原始邮件|原始郵件|Original Message|Forwarded message|转发邮件)|发件人[:：]|寄件者[:：]|From:\s|Von:\s|De\s?:\s|Từ:\s|在\s?.{3,80}写道[:：]|On .{5,160} wrote:)/i;
const frames = new Set();

function frameDoc(html, { plain, remote, dark }) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:${remote ? " https: http:" : ""}; media-src data:`;
  const fg = dark ? "#e6e6e6" : "#1d1d1f";
  let css = `:root{color-scheme:${dark ? "dark" : "light"}}html,body{background:transparent}body{margin:0;font:14px/1.6 ${FRAME_FONT};color:${fg};overflow-wrap:anywhere;overflow-x:auto;overflow-y:hidden}
img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap}a{color:${dark ? "#8fb8ff" : "#1a5fb4"}}
blockquote{margin:0 0 0 4px;padding-left:10px;border-left:2px solid ${dark ? "#444" : "#ddd"}}
.rd-plain{white-space:pre-wrap;font-size:14px}.rd-quote{color:${dark ? "#9a9a9a" : "#6e6e73"};margin-top:14px;padding-left:10px;border-left:2px solid ${dark ? "#444" : "#ddd"}}`;
  if (dark && !plain) {
    css += `html,body{background:transparent!important}.rd-root{background:#e6e6e6;color:#1d1d1f;filter:invert(1) hue-rotate(180deg);padding:1px 0}
.rd-root img,.rd-root video,.rd-root picture,.rd-root [background],.rd-root [style*="url("]{filter:invert(1) hue-rotate(180deg)}.rd-root a{color:#1a5fb4}`;
  }
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><style>${css}</style></head><body><div class="rd-root">${html}</div></body></html>`;
}

function mailFrame(html, { plain = false, remote = false, quote = false, sig = false } = {}) {
  const wrap = el("div");
  const frame = el("iframe", { class: "frame" + (sig ? " sig-frame" : ""), sandbox: "allow-same-origin allow-popups allow-popups-to-escape-sandbox", referrerpolicy: "no-referrer", title: "mail" });
  wrap.append(frame);
  const st = { html, plain, remote, quote, frame, wrap, hidden: [], toggle: null };
  frames.add(st);
  const fit = () => {
    const d = frame.contentDocument;
    if (!d || !d.documentElement) return;
    if (!d.body) return;
    // the body's own height: the document's grows with the frame and would never shrink
    const root = d.querySelector(".rd-root") || d.body;
    const h = Math.ceil(Math.max(d.body.scrollHeight, root.getBoundingClientRect().bottom + (d.defaultView?.scrollY || 0)));
    if (frame.style.height !== h + "px") frame.style.height = h + "px";
  };
  st.fit = fit;
  frame.addEventListener("load", () => {
    const d = frame.contentDocument;
    if (!d) return;
    if (quote) collapseQuote(st);
    fit();
    try { new ResizeObserver(fit).observe(d.body); } catch { /* old engine */ }
    for (const img of d.images) if (!img.complete) img.addEventListener("load", fit);
    d.addEventListener("click", (e) => {
      const a = e.target.closest?.("a[href]");
      if (!a) return;
      e.preventDefault();
      const href = a.getAttribute("href") || "";
      if (/^mailto:/i.test(href)) {
        const addr = decodeURIComponent(href.slice(7).split("?")[0]);
        openCompose({ mode: "new", to: addr.split(",").filter(Boolean).map((x) => ({ name: "", addr: x.trim().toLowerCase() })) });
      } else if (/^https?:/i.test(href)) api("open_url", { url: a.href }).catch(fail);
    });
    d.addEventListener("keydown", (e) => onKey(e));
  });
  setTimeout(fit, 400);
  frame.srcdoc = frameDoc(html, { plain, remote, dark: isDark() });
  const obs = new MutationObserver(() => { if (!wrap.isConnected) { frames.delete(st); obs.disconnect(); } });
  requestAnimationFrame(() => obs.observe(document.body, { childList: true, subtree: true }));
  return { node: wrap, frame, st };
}

function refreshFrames() {
  for (const st of frames) {
    if (!st.wrap.isConnected) { frames.delete(st); continue; }
    st.toggle?.remove(); st.toggle = null; st.hidden = [];
    st.frame.srcdoc = frameDoc(st.html, { plain: st.plain, remote: st.remote, dark: isDark() });
  }
}

function collapseQuote(st) {
  const d = st.frame.contentDocument, root = d.querySelector(".rd-root") || d.body;
  let q = root.querySelector(QUOTE_SEL);
  if (!q) {
    const w = d.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (QUOTE_TEXT.test(n.nodeValue)) {
        q = n.parentElement.closest("div,p,table,blockquote,tr,section,font,span") || n.parentElement;
        break;
      }
    }
  }
  if (!q || q === root) return;
  const r = d.createRange();
  r.setStart(root, 0); r.setEndBefore(q);
  const before = r.cloneContents();
  if (!before.textContent.trim() && !before.querySelector?.("img")) return;
  // the quote and everything after it, at every level up to the root
  const hide = [];
  for (let n = q; n && n !== root; n = n.parentElement) {
    for (let s = n === q ? n : n.nextElementSibling; s; s = s.nextElementSibling) hide.push(s);
  }
  const uniq = [...new Set(hide)].filter((x) => x.style);
  if (!uniq.length) return;
  for (const x of uniq) { x.dataset.rdDisplay = x.style.display; x.style.display = "none"; }
  st.hidden = uniq;
  const btn = el("button", { class: "quote-toggle", "data-tip": t("show_quote"), "aria-label": t("show_quote") }, "•••");
  btn.addEventListener("click", () => {
    const on = btn.classList.toggle("open");
    for (const x of uniq) x.style.display = on ? x.dataset.rdDisplay : "none";
    st.fit();
  });
  st.toggle = btn;
  st.wrap.append(btn);
}

// ---------------------------------------------------------------- compose

const ADDR_RE = /^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$/;
function parseAddrs(text) {
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

async function openCompose(opts) {
  if (S.compose && !(await leaveCompose())) return;
  let c;
  try {
    c = await api("compose", { mode: opts.mode, id: opts.id });
  } catch (e) { return fail(e); }
  if (opts.to) c.to = [...opts.to, ...c.to];
  if (opts.files) c.pending = opts.files;
  c.showCc = c.cc.length > 0; c.showBcc = c.bcc.length > 0;
  c.dirty = false; c.status = ""; c.busy = false;
  S.compose = c;
  renderCompose();
}

function renderCompose() {
  const c = S.compose;
  renderToolbar();
  const box = el("div", { class: "compose" });
  box.append(addrField("to", t("to"), true));
  if (c.showCc) box.append(addrField("cc", t("cc")));
  if (c.showBcc) box.append(addrField("bcc", t("bcc")));
  const subj = el("input", { class: "subject-input", type: "text", placeholder: t("subject"), value: c.subject, spellcheck: "true" });
  subj.addEventListener("input", () => { c.subject = subj.value; touched(); });
  subj.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ed.focus(); } });
  const ed = el("div", { class: "editor", contenteditable: "true", "data-ph": t("write"), spellcheck: "true" });
  ed.innerHTML = c.html || "";
  ed.addEventListener("input", () => { c.html = ed.innerHTML; touched(); });
  ed.addEventListener("paste", onPaste);
  box.append(subj, ed);
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

function touched() {
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

function addrField(key, label, first = false) {
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

function renderAtts() {
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

function pickFiles() {
  const inp = el("input", { type: "file", multiple: true, style: "display:none" });
  inp.addEventListener("change", () => { uploadFiles([...inp.files]); inp.remove(); });
  document.body.append(inp);
  inp.click();
}

async function uploadFiles(files) {
  const c = S.compose;
  if (!c) return;
  for (const f of files) {
    const a = { name: f.name, size: f.size, uploading: true };
    c.atts.push(a);
    renderAtts();
    try {
      const r = await fetch("/upload", { method: "POST", headers: { "X-Token": TOKEN, "X-Name": encodeURIComponent(f.name) }, body: f });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || t("error"));
      Object.assign(a, j.data, { uploading: false });
      touched();
    } catch (e) {
      c.atts = c.atts.filter((x) => x !== a);
      fail(e);
    }
    if (S.compose === c) renderAtts();
  }
}

function onPaste(e) {
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

function cleanHTML(html) {
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

function composeState() {
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
    html: c.html, atts: c.atts.filter((a) => !a.uploading).map(({ path, name, size }) => ({ path, name, size })),
    use_signature: c.use_signature, irt: c.irt, refs: c.refs,
  };
}

let saving = Promise.resolve();
function saveDraft(c = S.compose) {
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
async function leaveCompose() {
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

async function closeCompose() {
  if (await leaveCompose()) { if (S.sel && S.rows.find((x) => x.id === S.sel)?.folder !== "drafts") openThread(S.sel); else showEmpty(); }
}

async function discardCompose() {
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

async function sendCompose(force = false) {
  const c = S.compose;
  if (!c || c.busy) return;
  clearTimeout(c.autosave);
  if (c.atts.some((a) => a.uploading)) return toast(t("uploading"));
  await saving;
  const st = composeState();
  c.busy = true; renderToolbar();
  let r;
  try { r = await api("prepare_send", { ...st, force }); }
  catch (e) { c.busy = false; renderToolbar(); return fail(e); }
  c.busy = false;
  if (r.problems && r.problems.length) {
    renderToolbar();
    return problemsSheet(r.problems);
  }
  c.replace = r.id; c.dirty = false; c.lastState = { ...st, replace: r.id };
  // out of the way while the undo pause runs
  S.compose = null;
  if (S.sel && S.folder !== "drafts") openThread(S.sel); else showEmpty();
  let undone = false;
  const tt = toast(t("sending"), { action: { label: t("undo"), run: () => { undone = true; } }, ms: 0 });
  for (let k = 0; k < 40 && !undone; k++) await sleep(100);
  if (undone) {
    if (S.compose && !(await leaveCompose())) return;
    S.compose = c; renderCompose(); return;
  }
  tt.node.querySelector("button")?.remove();
  tt.node.classList.add("solo");
  try {
    const res = await api("send", { id: r.id });
    tt.close();
    const after = res.problems_after_sending || [];
    if (after.length) toast(after.join(" "), { error: true, ms: 12000 });
    else toast(t("sent_ok"));
    refreshCounts();
    if (S.folder === "sent" || S.folder === "drafts") loadList({ quiet: true });
    if (S.thread) openThread(S.focus || S.sel);
  } catch (e) {
    tt.close();
    fail(e);
    if (!S.compose) { S.compose = c; renderCompose(); }
  }
}

function problemsSheet(problems) {
  const box = sheet(el("div", {},
    el("h2", { html: icon("triangle-alert") + esc(t("problems")) }),
    el("ul", {}, problems.map((p) => el("li", {}, p.charAt(0).toUpperCase() + p.slice(1)))),
    el("div", { class: "sheet-acts" },
      el("button", { class: "ghost-btn", onclick: () => { closeLayer(); $(".compose .editor")?.focus(); } }, t("keep_editing")),
      el("button", { class: "pill-btn", onclick: () => { closeLayer(); sendCompose(true); } }, t("send_anyway")))));
  box.querySelector(".ghost-btn").focus();
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

// ---------------------------------------------------------------- settings

async function openSettings() {
  let s;
  try { s = await api("settings"); } catch (e) { return fail(e); }
  const v = { ...s, password: "", theme: S.theme };
  let tab = "account";
  const nav = el("div", { class: "settings-nav" }, el("h3", {}, t("settings")));
  const body = el("div", { class: "settings-body" });
  const msg = el("span", { class: "grow" });
  const saveBtn = el("button", { class: "pill-btn", onclick: save }, t("save"));
  const foot = el("div", { class: "settings-foot" }, msg, el("button", { class: "ghost-btn", onclick: closeLayer }, t("cancel")), saveBtn);
  const tabs = [["account", "circle-user-round"], ["signature", "square-pen"], ["appearance", "sun"]];
  const drawNav = () => {
    nav.replaceChildren(el("h3", {}, t("settings")));
    for (const [k, ic] of tabs) nav.append(el("button", { class: "nav-item" + (k === tab ? " on" : ""), onclick: () => { grab(); tab = k; drawNav(); draw(); }, html: icon(ic) + `<span class="label">${esc(t(k))}</span>` }));
  };
  let sigEd = null;
  const grab = () => {
    for (const inp of $$("input[data-k]", body)) v[inp.dataset.k] = inp.value;
    if (sigEd) v.signature = sigEd.innerHTML;
  };
  const draw = () => {
    body.replaceChildren();
    sigEd = null;
    if (tab === "account") {
      const f = el("div", { class: "form" });
      const inp = (k, type = "text", ph = "") => el("input", { type, "data-k": k, value: v[k] ?? "", placeholder: ph, spellcheck: "false", autocomplete: "off" });
      const lab = (text, ...kids) => el("label", {}, el("span", { class: "lab" }, text), ...kids);
      f.append(lab(t("name"), inp("name")), lab(t("email"), inp("user", "email")),
        lab(t("password"), inp("password", "password", s.has_password ? "••••••••  " + t("pw_saved") : "")));
      if (s.password_env) f.append(el("div", { class: "msg-warn" }, t("pw_env", "RAGDOLL_PASSWORD")));
      f.append(lab(t("incoming"), el("div", { class: "two" }, inp("imap_host"), inp("imap_port", "number"))),
        lab(t("outgoing"), el("div", { class: "two" }, inp("smtp_host"), inp("smtp_port", "number"))),
        lab(t("require_cc"), inp("require_cc", "text", "boss@example.com")));
      const res = el("div");
      const testBtn = el("button", { class: "ghost-btn", onclick: async () => {
        grab(); testBtn.disabled = true; res.replaceChildren(el("span", { class: "note" }, t("testing")));
        try { const r = await api("test", v); v.folders = r.folders; res.replaceChildren(el("div", { class: "msg-ok", html: icon("circle-check") + esc(t("test_ok")) })); }
        catch (e) { res.replaceChildren(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) })); }
        finally { testBtn.disabled = false; }
      } }, t("test"));
      f.append(el("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" }, testBtn, res));
      body.append(el("h2", {}, t("account")), f);
    } else if (tab === "signature") {
      sigEd = el("div", { class: "sig-edit", contenteditable: "true" });
      sigEd.innerHTML = v.signature || "";
      sigEd.addEventListener("paste", (e) => { const h = e.clipboardData.getData("text/html"); if (h) { e.preventDefault(); document.execCommand("insertHTML", false, cleanHTML(h)); } });
      body.append(el("h2", {}, t("signature")), el("div", { class: "form" }, sigEd));
    } else {
      const seg = el("div", { class: "seg" });
      for (const [k, ic] of [["system", "monitor"], ["light", "sun"], ["dark", "moon"]]) {
        seg.append(el("button", { class: v.theme === k ? "on" : "", onclick: () => { v.theme = k; applyTheme(k); api("prefs", { theme: k }).catch(() => {}); draw(); }, html: icon(ic, "small") + esc(t(k)) }));
      }
      body.append(el("h2", {}, t("appearance")), el("div", { class: "form" }, seg));
    }
  };
  async function save() {
    grab();
    const changed = ["name", "user", "password", "imap_host", "imap_port", "smtp_host", "smtp_port", "require_cc", "signature"].some((k) => String(v[k] ?? "") !== String(s[k] ?? ""));
    if (!changed) return closeLayer();
    saveBtn.disabled = true;
    msg.replaceChildren();
    try {
      const b = await api("save_settings", { ...v, account: true, folders: v.folders });
      S.boot = { ...S.boot, ...b };
      closeLayer();
      renderNav();
      toast(t("saved"));
      loadList({ quiet: true });
    } catch (e) {
      msg.replaceChildren(el("span", { class: "form" }, el("span", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) })));
    } finally { saveBtn.disabled = false; }
  }
  drawNav(); draw();
  sheet(el("div", { class: "settings-wrap" }, el("div", { class: "settings" }, nav, body), foot), { wide: true });
}

// ---------------------------------------------------------------- setup (no account yet)

function showSetup() {
  $("#app").hidden = true;
  const box = $("#setup");
  box.hidden = false;
  const v = { name: "", user: "", password: "", imap_host: "", imap_port: 993, smtp_host: "", smtp_port: 465 };
  let open = false, busy = false, err = "", guessed = "";
  const draw = () => {
    const f = el("div", { class: "form" });
    const inp = (k, type = "text", attrs = {}) => {
      const i = el("input", { type, value: v[k] ?? "", spellcheck: "false", autocomplete: "off", ...attrs });
      i.addEventListener("input", () => { v[k] = i.value; });
      return i;
    };
    const lab = (text, ...kids) => el("label", {}, el("span", { class: "lab" }, text), ...kids);
    const email = inp("user", "email", { autofocus: true });
    email.addEventListener("change", async () => {
      if (!v.user.includes("@") || guessed === v.user) return;
      guessed = v.user;
      try { const g = await api("guess_servers", { user: v.user }); v.imap_host = g.imap_host; v.smtp_host = g.smtp_host; const n = $$("#setup input[data-host]"); n.forEach((x) => { x.value = v[x.dataset.host]; }); } catch { /* typed by hand */ }
    });
    f.append(lab(t("name"), inp("name")), lab(t("email"), email), lab(t("password"), inp("password", "password")));
    const dis = el("button", { class: "disclose" + (open ? " open" : ""), onclick: () => { open = !open; draw(); }, html: icon("chevron-right", "small") + esc(t("servers")) });
    f.append(dis);
    if (open) {
      f.append(lab(t("incoming"), el("div", { class: "two" }, inp("imap_host", "text", { "data-host": "imap_host" }), inp("imap_port", "number"))),
        lab(t("outgoing"), el("div", { class: "two" }, inp("smtp_host", "text", { "data-host": "smtp_host" }), inp("smtp_port", "number"))));
    }
    if (err) f.append(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(err) }));
    const go = el("button", { class: "pill-btn", disabled: busy, onclick: signIn }, busy ? t("signing_in") : t("sign_in"));
    f.append(go);
    f.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") signIn(); });
    box.replaceChildren(el("div", { class: "setup-drag pywebview-drag-region" }),
      el("div", { class: "setup-card" }, el("img", { class: "logo", src: "logo.png", alt: "" }), el("h1", {}, t("setup_title")), f));
  };
  async function signIn() {
    if (busy) return;
    if (!v.imap_host && v.user.includes("@")) {
      try { const g = await api("guess_servers", { user: v.user }); v.imap_host = g.imap_host; v.smtp_host = g.smtp_host; } catch { /* below */ }
    }
    busy = true; err = ""; draw();
    try {
      const r = await api("test", v);
      const b = await api("save_settings", { ...v, account: true, folders: r.folders });
      box.hidden = true;
      start(b);
    } catch (e) { err = e.message; busy = false; open = open || /server|服务器|port|端口/i.test(e.message); draw(); }
  }
  draw();
}

// ---------------------------------------------------------------- keys

function typing(e) {
  const n = e.target;
  return n && (n.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(n.tagName));
}
function onKey(e) {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); $("#search").focus(); $("#search").select(); return; }
  if (mod && e.key === ",") { e.preventDefault(); openSettings(); return; }
  if (layerOpen()) { if (e.key === "Escape") { closeLayer(); } return; }
  if (S.compose) {
    if (mod && e.key === "Enter") { e.preventDefault(); sendCompose(); return; }
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveDraft().catch(fail); return; }
    if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); closeCompose(); return; }
  }
  if (typing(e) || mod || e.altKey) return;
  const id = S.focus || S.sel;
  const k = e.key;
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
  else if (k === "Escape" && S.query) { $("#search").value = ""; onSearch(true); }
}
document.addEventListener("keydown", onKey);

// ---------------------------------------------------------------- list width

(() => {
  const sp = $("#splitter");
  sp.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const x0 = e.clientX, w0 = $("#list-col").offsetWidth;
    const move = (ev) => { const w = Math.max(280, Math.min(600, w0 + ev.clientX - x0)); document.documentElement.style.setProperty("--list-w", w + "px"); };
    const up = () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      api("prefs", { list_width: $("#list-col").offsetWidth }).catch(() => {});
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  });
})();

// ---------------------------------------------------------------- status

async function refreshCounts() {
  try { const st = await api("status"); applyStatus(st); } catch { /* next poll */ }
}
function applyStatus(st) {
  S.boot.folders = st.folders;
  S.update = st.update;
  const wasSyncing = S.syncing;
  S.syncing = st.syncing;
  renderNav();
  const b = $("#banner");
  if (st.error && !S.boot.demo) {
    b.hidden = false;
    $("#banner-text").textContent = st.error;
    $("#banner-btn").textContent = t("settings");
  } else b.hidden = true;
  if (st.rev !== S.rev) { S.rev = st.rev; loadList({ quiet: true }); }
  else if (wasSyncing !== S.syncing && !S.rows.length) renderRows();
}
$("#banner-btn").addEventListener("click", openSettings);
$("#update").addEventListener("click", () => {
  if (S.update?.url) api("open_url", { url: S.update.url }).catch(fail);
  else toast(t("run_update"), { ms: 8000 });
});

// ---------------------------------------------------------------- start

document.documentElement.classList.add(MAC ? "mac" : WIN ? "win" : "other");
function fullScreenCheck() {
  document.documentElement.classList.toggle("fullscreen", innerHeight >= screen.height - 1 && innerWidth >= screen.width - 1);
}
addEventListener("resize", fullScreenCheck);
function nativeWindow() {
  document.documentElement.classList.add("native");
  syncWindowTheme();
}
if (window.pywebview) nativeWindow();
else window.addEventListener("pywebviewready", nativeWindow);

function start(boot) {
  S.boot = boot;
  applyTheme(boot.theme);
  $("#app").hidden = false;
  $("#setup").hidden = true;
  document.title = "ragdoll-mail";
  $("#compose-btn").innerHTML = icon("square-pen");
  $("#compose-btn").dataset.tip = t("compose");
  $("#compose-btn").dataset.key = "C";
  $("#compose-btn").onclick = () => openCompose({ mode: "new" });
  $("#account").onclick = accountMenu;
  $("#search-kbd").textContent = MAC ? "⌘K" : "Ctrl K";
  document.querySelectorAll("[data-i]").forEach((n) => { n.innerHTML = svg(n.dataset.i); });
  renderNav();
  showEmpty();
  loadList();
  refreshCounts();
  if (!start.timer) start.timer = setInterval(() => { if (!document.hidden) refreshCounts(); }, 5000);
}

(async function boot() {
  let b;
  for (let k = 0; ; k++) {
    try { b = await api("boot"); break; }
    catch (e) { if (k > 20) { document.body.textContent = e.message; return; } await sleep(300); }
  }
  applyTheme(b.theme);
  try { const p = await api("prefs", {}); if (p.list_width) document.documentElement.style.setProperty("--list-w", p.list_width + "px"); } catch { /* defaults */ }
  if (!b.configured) showSetup(); else start(b);
})();
