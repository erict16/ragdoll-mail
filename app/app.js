// ragdoll-mail desktop app. Talks to ragdoll_app.py over /api/<name> (JSON, X-Token header).
import { ICONS } from "./icons.js";
import { REMIX } from "./icons-remix.js";
import { FILE_ICONS, FILE_EXT } from "./fileicons.js";
import { LANGS, LANG_NAMES } from "./i18n.js";
import * as K from "./compose-kit.js";

// ---------------------------------------------------------------- basics

const TOKEN = (() => {
  const t = new URLSearchParams(location.hash.slice(1)).get("t");
  try {
    if (t) sessionStorage.setItem("ragdoll-token", t);
    return t || sessionStorage.getItem("ragdoll-token") || "";
  } catch { return t || ""; }
})();
if (location.hash) history.replaceState(null, "", location.pathname);

const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const WIN = /Win/.test(navigator.platform || navigator.userAgent);
const MOD = MAC ? "⌘" : "Ctrl+";
// the app's own shortcuts: Cmd on a Mac (its Ctrl keys stay the system's text keys), Ctrl elsewhere
const isMod = K.modOf(MAC);

// language: a saved choice, or the system's when it is one of ours
let LANG = "en", LOCALE = undefined, TZ = undefined, STR = LANGS.en;
const SYS_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; } })();
function systemLang() {
  for (const l of navigator.languages?.length ? navigator.languages : [navigator.language || "en"]) {
    const x = l.toLowerCase();
    if (x.startsWith("zh")) return /hant|-tw|-hk|-mo/.test(x) ? "zh-Hant" : "zh-Hans";
    const base = x.split("-")[0];
    if (LANGS[base]) return base;
  }
  return "en";
}
function setLocale(prefs = {}) {
  const pick = prefs.lang && prefs.lang !== "system" && LANGS[prefs.lang] ? prefs.lang : systemLang();
  LANG = pick;
  STR = { ...LANGS.en, ...LANGS[pick] };
  // the system's own regional format when it speaks this language (en-GB, es-MX); else the language itself
  const sys = navigator.language || "";
  LOCALE = sys.toLowerCase().startsWith(pick.split("-")[0].toLowerCase()) && !pick.startsWith("zh") ? sys : pick;
  TZ = prefs.tz && prefs.tz !== "system" ? prefs.tz : undefined;
  try { new Intl.DateTimeFormat(LOCALE, { timeZone: TZ }); } catch { TZ = undefined; }
  FMT.clear();
  document.documentElement.lang = pick;
}
const t = (k, ...a) => { let s = STR[k] ?? k; for (const x of a) s = s.replace("%s", x); return s; };

// a sentence from the server or the send check, in the chosen language when we know it
const MSGS = [
  [/^The app's background service/, "err_bg"],
  [/^Sign-in failed\./, "err_signin"], [/^No password saved\./, "err_no_pw"], [/^No account yet\./, "err_no_account"],
  [/^Can't find the mail server\./, "err_dns"], [/^The mail server did not answer in time\./, "err_timeout"],
  [/^Secure connection failed \((.*)\)\. Check/, "err_ssl"], [/^The mail server refused the connection\./, "err_refused"],
  [/^Can't reach the mail server \((.*)\)\.$/, "err_reach"], [/^The mail server said: (.*)$/s, "err_server"],
  [/^This mail is no longer here/, "err_gone"], [/^The folder (.*) is no longer on the server\.$/, "err_no_folder"], [/^The draft is gone\./, "err_draft_gone"],
  [/^Give the folder a name\./, "err_folder_name"], [/^That folder name is too long\./, "err_folder_long"],
  [/^A folder name can't have (.*) in it\.$/, "err_folder_char"], [/^There is already a folder called (.*)\.$/, "err_folder_exists"],
  [/^(.*) still has mail in it\./, "err_folder_mail"], [/^(.*) has folders inside it\./, "err_folder_kids"],
  [/^An attachment is missing: (.*)$/, "err_att_missing"], [/^That time has already passed\./, "err_past"],
  [/^To is empty/, "p_to_empty"], [/^the sender is also a recipient/, "p_self"], [/^(.*) is not in To or Cc/, "p_not_cc"],
  [/^the subject is empty/, "p_no_subject"], [/^garbled characters \(.\) in: (.*)$/, "p_garbled"],
  [/^placeholder\(s\) left in the text: ([^;]*)/, "p_holes"], [/^the text mentions an attachment/, "p_att"],
  [/^(\d+) image\(s\) in the mail have no image part/, "p_img"],
  [/^(.*) is a program, so it was not opened\./, "att_program"],
  [/^The connection broke while the mail was going out/, "err_maybe_sent"],
  [/^This mail is going out right now, so the change was not saved\./, "err_going_out_unsaved"],
  [/^This mail is going out right now\./, "err_going_out"],
];
// 0.11 group D_SYNC: sync, connection, sign-in and settings messages
MSGS.push(
  [/^Waiting for another sync to finish\./, "err_busy"], [/^The settings file can't be read\. Sign in/, "err_cfg"],
  [/^The settings file (.*) can't be read, and no copy/s, "err_cfg_nocopy"],
  [/^Secure connection failed\. Check/, "err_ssl2"], [/^Can't reach the mail server\. Check/, "err_reach2"],
  [/^The connection to the mail server dropped\./, "err_dropped"], [/^The mail server refused the request\./, "err_refused_req"],
  [/^Can't open the folder (.*) on the server\.$/s, "err_folder_open"],
  [/^The server refused to move the mail \((\d+) moved/, "err_move_refused"],
  [/^Enter a full email address\./, "err_need_addr"], [/^Enter the password\./, "err_need_pw"],
  [/^Incoming server: sign-in failed\./, "err_in_signin"], [/^Outgoing server: sign-in failed\./, "err_out_signin"],
  [/^Incoming server: (.*)$/s, "err_in"], [/^Outgoing server: (.*)$/s, "err_out"],
);
function tr(msg) {
  msg = String(msg ?? "");
  // a part it holds ("Incoming server: <a known sentence>") is put in the chosen language too
  for (const [re, k] of MSGS) { const m = msg.match(re); if (m) return t(k, ...m.slice(1).map((x) => (x && x.length < msg.length ? tr(x) : x ?? ""))); }
  return msg;
}

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Reply, reply all and forward: Remix arrow shapes drawn as a hollow, rounded outline (Apple Mail style); every other icon is Lucide.
// Each arrow's frame holds the whole shape, its sharp tip and the outline's half width included, so nothing
// is drawn outside the frame (WebKit cuts off what is); reply and forward share one size.
// reply all is wider than tall: its frame keeps reply's height, and its box is wider (style.css .i-wide), so its
// arrows are drawn at the very size of reply's
const ARROW_BOX = { "reply": "0.1 1.1 21.8 21.8", "forward": "2.1 1.1 21.8 21.8", "reply-all": "-1.9 1.1 25.3 21.8" };
const svg = (n) => REMIX[n] ? `<svg xmlns="http://www.w3.org/2000/svg" class="arrowshape" viewBox="${ARROW_BOX[n]}" fill="none" stroke="currentColor" stroke-linejoin="round" aria-hidden="true">${REMIX[n]}</svg>`
  : `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ""}</svg>`;
const icon = (n, cls = "") => `<span class="i ${cls}${n === "reply-all" ? " i-wide" : ""}">${svg(n)}</span>`;
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
// a box's scrollbar shows while it scrolls and goes 0.8s after it stops (style.css: .scrolling)
const scrollQuiet = new WeakMap();
addEventListener("scroll", (e) => {
  const n = e.target === document ? document.scrollingElement : e.target;
  if (!n?.classList) return;
  n.classList.add("scrolling");
  clearTimeout(scrollQuiet.get(n));
  scrollQuiet.set(n, setTimeout(() => n.classList.toggle("scrolling", false), 800));
}, { capture: true, passive: true });

function iconBtn(name, tip, onclick, extra = {}) {
  return el("button", { class: "icon-btn" + (extra.cls ? " " + extra.cls : ""), "data-tip": tip, "data-key": extra.key, html: icon(name), onclick, disabled: extra.disabled, "aria-label": tip });
}

async function api(name, args = {}) {
  let r;
  try {
    r = await fetch("/api/" + name, { method: "POST", headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(args) });
  } catch {
    throw new Error(t("err_bg"));
  }
  let j;
  try { j = await r.json(); } catch { throw new Error(t("error")); }
  if (!j.ok) throw new Error(tr(j.error) || t("error"));
  return j.data;
}

// ---------------------------------------------------------------- state

const S = {
  boot: null, folder: "inbox", rows: [], more: false, query: "", loadingMore: false,
  sel: null, thread: null, focus: null, compose: null, rev: 0, update: null, error: null,
  theme: "system", showImages: new Set(), syncing: false, sched: null, multi: new Set(), anchor: null,
  filter: {}, newsN: 0,
};
let PREFS = {};
const undoSeconds = () => (Number.isInteger(PREFS.undo) ? PREFS.undo : 5);
// reading text size and the default font for new mail
const TEXT_SIZES = [12, 13, 14, 15, 16, 18, 20];
const textSize = () => (TEXT_SIZES.includes(PREFS.text_size) ? PREFS.text_size : 14);
const FONT_SIZES = [12, 13, 14, 16, 18];
const FONTS = [
  ["system", ""], ["arial", "Arial, Helvetica, sans-serif"], ["helvetica", "Helvetica, Arial, sans-serif"],
  ["georgia", "Georgia, serif"], ["times", "'Times New Roman', Times, serif"], ["verdana", "Verdana, Geneva, sans-serif"],
  ["courier", "'Courier New', Courier, monospace"], ["yahei", "'Microsoft YaHei', 微软雅黑, sans-serif"],
  ["pingfang", "'PingFang SC', 苹方, sans-serif"], ["simsun", "SimSun, 宋体, serif"],
];
const FONT_NAMES = { arial: "Arial", helvetica: "Helvetica", georgia: "Georgia", times: "Times New Roman", verdana: "Verdana",
  courier: "Courier New", yahei: "Microsoft YaHei", pingfang: "PingFang SC", simsun: "SimSun" };
const SAFE_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', Helvetica, Arial, sans-serif";
const fontStack = (k) => FONTS.find(([x]) => x === k)?.[1] || SAFE_FONT;
const fontLabel = (k) => FONT_NAMES[k] || t("system");
const mailFont = () => fontStack(PREFS.font || "system");
const mailSize = () => (FONT_SIZES.includes(PREFS.font_size) ? PREFS.font_size : 14);
const savePref = (patch) => { Object.assign(PREFS, patch); api("prefs", patch).catch(() => {}); };
const FOLDER_ICON = { inbox: "inbox", flagged: "star", drafts: "file", scheduled: "clock", sent: "send", archive: "archive", junk: "archive-x", trash: "trash-2" };
// the server's other folders keep their own names; only the built-in ones are translated
const otherFolder = (key) => S.boot?.folders.find((f) => f.key === key && f.other);
const folderName = (key) => otherFolder(key)?.label || (FOLDER_ICON[key] ? t(key) : key);
const backLabel = (folder) => t(folder === "junk" ? "not_junk" : "restore");

// ---------------------------------------------------------------- theme

const darkMQ = matchMedia("(prefers-color-scheme: dark)");
const isDark = () => document.documentElement.dataset.theme === "dark";
function applyTheme(theme) {
  S.theme = theme || "system";
  const dark = S.theme === "dark" || (S.theme === "system" && darkMQ.matches);
  const root = document.documentElement, was = root.dataset.theme, now = dark ? "dark" : "light";
  const swap = () => {
    root.dataset.theme = now;
    if (was && was !== now) restyleFrames();
    syncWindowTheme();
  };
  if (!was || was === now || REDUCED.matches || document.hidden) return swap();
  // the whole window, open mails included, cross-fades from one picture to the other (WebKit on macOS 15+,
  // WebView2); elsewhere the colours ease over (.theming)
  if (document.startViewTransition) {
    try { document.startViewTransition(swap); return; } catch { /* the fade below */ }
  }
  root.classList.add("theming");
  clearTimeout(applyTheme.timer);
  applyTheme.timer = setTimeout(() => root.classList.remove("theming"), 320);
  swap();
}
// the native title bar (Windows caption, macOS traffic lights) follows the app theme, not only the system's
function syncWindowTheme() {
  if (!window.pywebview) return;
  const css = getComputedStyle(document.documentElement);
  api("window_theme", {
    dark: document.documentElement.dataset.theme === "dark",
    // System: the window follows macOS again, so the page hears it switch (darkMQ below)
    system: S.theme === "system",
    bg: css.getPropertyValue("--bg").trim(),
    text: css.getPropertyValue("--text").trim(),
  }).catch(() => {});
}
darkMQ.addEventListener("change", () => applyTheme(S.theme));

// ---------------------------------------------------------------- time and size

const FMT = new Map();
function fmt(ts, opts) {
  const key = JSON.stringify(opts);
  let f = FMT.get(key);
  if (!f) {
    try { f = new Intl.DateTimeFormat(LOCALE, { ...opts, timeZone: TZ }); } catch { f = new Intl.DateTimeFormat(undefined, opts); }
    FMT.set(key, f);
  }
  return f.format(new Date(ts * 1000));
}
// the wall clock in the chosen time zone: {y, m, d, h, mi, wd (0 = Sunday)}
function zparts(ms) {
  const key = "parts";
  let f = FMT.get(key);
  if (!f) { f = new Intl.DateTimeFormat("en-US", { timeZone: TZ || SYS_TZ, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", weekday: "short" }); FMT.set(key, f); }
  const p = Object.fromEntries(f.formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
  return { y: +p.year, m: +p.month, d: +p.day, h: +p.hour % 24, mi: +p.minute, wd: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(p.weekday) };
}
// Unix seconds for a wall-clock time in the chosen time zone
function zepoch(y, m, d, h, mi) {
  const want = Date.UTC(y, m - 1, d, h, mi);
  let guess = want;
  for (let k = 0; k < 3; k++) {
    const p = zparts(guess);
    guess = want - (Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi) - guess);
  }
  return Math.round(guess / 1000);
}
const dayKey = (ms) => { const p = zparts(ms); return p.y * 10000 + p.m * 100 + p.d; };
const HM = { hour: "2-digit", minute: "2-digit" };
function shortTime(ts) {
  if (!ts) return "";
  const ms = ts * 1000, now = Date.now(), k = dayKey(ms);
  if (k === dayKey(now)) return fmt(ts, HM);
  if (k === dayKey(now - 86400e3)) return t("yesterday");
  if (now - ms < 6 * 86400e3 && ms < now) return fmt(ts, { weekday: "short" });
  if (zparts(ms).y === zparts(now).y) return fmt(ts, { month: "short", day: "numeric" });
  return fmt(ts, { year: "numeric", month: "numeric", day: "numeric" });
}
// a time to come (a scheduled send): "18:00", "Tomorrow 08:00", "Mon 08:00", "12 Dec 08:00"
function laterTime(ts) {
  const ms = ts * 1000, now = Date.now(), k = dayKey(ms);
  if (k === dayKey(now)) return fmt(ts, HM);
  if (k === dayKey(now + 86400e3)) return t("tomorrow") + " " + fmt(ts, HM);
  if (ms - now < 6 * 86400e3) return fmt(ts, { weekday: "short", ...HM });
  return fmt(ts, { month: "short", day: "numeric", ...HM });
}
// an open message shows the full date, or the short one when its header is narrow (see .d-short in style.css)
const openDate = (ts) => `<span class="d-long">${esc(longTime(ts))}</span><span class="d-short">${esc(shortTime(ts))}</span>`;
function longTime(ts) {
  if (!ts) return "";
  return fmt(ts, { weekday: "short", year: "numeric", month: "short", day: "numeric", ...HM });
}
function size(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB";
}
// an attachment's icon: Word, Excel, PowerPoint, PDF, drawings, pictures, archives and more each have
// their own coloured file icon (Material Design Icons, in fileicons.js)
function fileTile(name) {
  const x = (name.includes(".") ? name.split(".").pop() : "").toLowerCase();
  return { class: "att-icon file", html: FILE_ICONS[Object.hasOwn(FILE_EXT, x) ? FILE_EXT[x] : "file"] };
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

// motion: everything leaves with a short fade; nothing waits when the system asks for less motion
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");
const EASE = "cubic-bezier(.2, .8, .2, 1)";
function leave(node, ms = 150) {
  if (!node || !node.isConnected || node.classList.contains("out")) return;
  if (REDUCED.matches) return node.remove();
  node.classList.add("out");
  setTimeout(() => node.remove(), ms);
}

// toasts sit at the foot of the reading pane, centered in it; on a narrow window, centered in the window
function placeToasts() {
  const box = $("#toasts"), r = $("#reader")?.getBoundingClientRect();
  box.style.left = r && r.width >= 360 && r.left > 0 ? r.left + r.width / 2 + "px" : "";
}
addEventListener("resize", () => placeToasts());
function toast(text, opts = {}) {
  const box = $("#toasts");
  placeToasts();
  // a toast with an id takes the place of the one before it (text size steps, for one)
  if (opts.id) for (const old of $$(`.toast[data-id="${opts.id}"]`, box)) old.replaceWith();
  const node = el("div", { "data-id": opts.id, class: "toast" + (opts.error ? " err" : ""), role: "status" },
    opts.error ? el("span", { class: "toast-ic", html: icon("triangle-alert") }) : null,
    el("span", { class: "toast-text" }, text));
  let done = false;
  const close = () => { if (done) return; done = true; leave(node, 180); };
  if (opts.action) node.append(el("button", { class: "toast-act", onclick: () => { close(); opts.action.run(); } }, opts.action.label));
  // the bar drains for as long as the toast stays: a toast that closes by itself always has one
  const ms = opts.ms ?? (opts.error ? 7000 : 3200);
  const barMs = opts.bar || ms;
  if (barMs) {
    const bar = el("span", { class: "toast-bar" });
    node.append(bar);
    if (!REDUCED.matches) bar.animate([{ transform: "scaleX(1)" }, { transform: "scaleX(0)" }], { duration: barMs, easing: "linear", fill: "forwards" });
  }
  box.append(node);
  if (ms) setTimeout(close, ms);
  return { close, node, set: (s) => { node.querySelector(".toast-text").textContent = s; } };
}
const fail = (e) => toast(e?.message || String(e), { error: true });

let tipEl = null, tipTimer = null;
// narrow windows: the sidebar is a drawer, opened from the folder button in the list header (see style.css)
const RAIL = matchMedia("(max-width: 860px)");
const sideOpen = (on) => { $("#app").classList.add("side-moves"); $("#app").classList.toggle("side-open", on); };
function placeCompose() {
  const app = $("#app"), drawer = RAIL.matches;
  app.classList.remove("side-open", "side-moves");     // no slide when the window only changes width
  app.classList.toggle("drawer", drawer);
  if (drawer) $(".list-head").append($("#compose-btn")); else $(".side-top").append($("#compose-btn"));
}
RAIL.addEventListener("change", placeCompose);
document.addEventListener("mouseover", (e) => {
  const b = e.target.closest?.("[data-tip]");
  clearTimeout(tipTimer);
  if (tipEl) { tipEl.remove(); tipEl = null; }
  if (!b || b.disabled) return;
  const side = b.dataset.rail != null;
  if (side) return;
  tipTimer = setTimeout(() => {
    const r = b.getBoundingClientRect();
    tipEl = el("div", { class: "tip" + (b.dataset.tip ? "" : " key-only"), html: esc(b.dataset.tip) + (b.dataset.key ? `<kbd>${esc(b.dataset.key)}</kbd>` : "") });
    document.body.append(tipEl);
    const w = tipEl.offsetWidth;
    tipEl.style.left = Math.max(6, Math.min(innerWidth - w - 6, r.left + r.width / 2 - w / 2)) + "px";
    tipEl.style.top = (r.bottom + 6 + 24 > innerHeight ? r.top - 30 : r.bottom + 6) + "px";
    if (side) { tipEl.style.left = r.right + 8 + "px"; tipEl.style.top = r.top + r.height / 2 - tipEl.offsetHeight / 2 + "px"; }
  }, side ? 250 : 550);
});
document.addEventListener("mousedown", () => { clearTimeout(tipTimer); if (tipEl) { tipEl.remove(); tipEl = null; } }, true);

function closeLayer() {
  for (const n of [...$("#layer").children]) leave(n, 160);
  for (const n of $$(".row.ctx")) n.classList.remove("ctx");
}
// keys while a menu is open: arrows walk it, Enter runs the item, and the letter shown beside an item runs that item
function menuKey(e) {
  const m = $("#layer .menu:not(.out)");
  if (!m) return false;
  const items = $$("button", m), k = items.indexOf(document.activeElement);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const d = e.key === "ArrowDown" ? 1 : -1;
    items[k < 0 ? (d > 0 ? 0 : items.length - 1) : (k + d + items.length) % items.length]?.focus();
    return true;
  }
  if (e.key === "Home" || e.key === "End") { e.preventDefault(); items[e.key === "Home" ? 0 : items.length - 1]?.focus(); return true; }
  if (e.metaKey || e.ctrlKey || e.altKey || e.key.length !== 1) return false;
  const hit = items.find((b) => b.dataset.k === e.key.toUpperCase());
  if (hit) { e.preventDefault(); hit.click(); return true; }
  return false;
}
function menu(anchor, items, { above = false } = {}) {
  closeLayer();
  const m = el("div", { class: "menu" + (above ? " above" : ""), role: "menu" });
  for (const it of items) {
    if (it === "-") m.append(el("hr"));
    else if (it.note) m.append(el("div", { class: "menu-note" }, it.note));
    else m.append(el("button", { role: "menuitem", "data-k": it.key && it.key.length === 1 ? it.key : null, onclick: () => { closeLayer(); it.run(); }, html: icon(it.icon) + `<span class="label">${esc(it.label)}</span>` +
      (it.on ? icon("check", "small on-mark") : it.key ? `<span class="grow"></span><kbd>${esc(it.key)}</kbd>` : it.hint ? `<span class="grow"></span><span class="hint">${esc(it.hint)}</span>` : "") }));
  }
  const catcher = el("div", { style: "position:fixed;inset:0", onmousedown: closeLayer });
  $("#layer").append(catcher, m);
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
  const top = above ? r.top - m.offsetHeight - 6 : r.bottom + 6;
  m.style.top = Math.max(8, Math.min(top, innerHeight - m.offsetHeight - 8)) + "px";
}
// a menu that opens where the mouse is (right-click)
const atPoint = (e) => ({ getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY - 6 }) });
function sheet(node, { wide = false, onclose } = {}) {
  closeLayer();
  const box = el("div", { class: "sheet" + (wide ? " wide" : ""), role: "dialog" }, node);
  const scrim = el("div", { class: "scrim", onmousedown: (e) => { if (e.target === scrim) { closeLayer(); onclose?.(); } } }, box);
  $("#layer").append(scrim);
  return box;
}
const layerOpen = () => !!$("#layer > :not(.out)");

// ---------------------------------------------------------------- sidebar

let navSig = "", navKeys = null;
function renderNav() {
  const nav = $("#nav");
  const own = ownFolders();
  const folders = [...S.boot.folders.filter((f) => !f.other), ...own];
  for (const [key, at] of [["flagged", 1], ["scheduled", 3]]) {
    if (S.folder === key && !folders.some((f) => f.key === key)) folders.splice(Math.min(at, folders.length), 0, { key, total: 0, unread: 0 });
  }
  // most calls come from the 5 second check and change nothing: leave the page alone then
  const sig = JSON.stringify([folders, S.folder, !!S.query, t("inbox"), S.boot.user, S.update?.version]);
  if (sig === navSig) return;
  navSig = sig;
  const was = navKeys;
  navKeys = new Set(folders.map((f) => f.key));
  nav.replaceChildren();
  const here = folders.find((f) => f.key === S.folder);
  const unread = folders.find((f) => f.key === "inbox")?.unread;
  $("#here-btn").className = "here-btn" + (unread && S.folder !== "inbox" ? " dot" : "");
  $("#here-btn").innerHTML = icon(here?.other ? "folder-open" : FOLDER_ICON[S.folder] || "folder-open") + `<span class="label" dir="auto">${esc(folderName(S.folder))}</span>`;
  $("#head-title").textContent = folderName(S.folder);
  emptyBtn(here);
  let seenOther = false;
  for (const [i, f] of folders.entries()) {
    if (f.other && !seenOther) nav.append(navSection());
    const kids = f.other && folders[i + 1]?.other && folders[i + 1].depth > (f.depth || 0);
    const n = f.key === "inbox" || f.other ? f.unread : ["drafts", "scheduled", "flagged"].includes(f.key) ? f.total : 0;
    const name = f.other ? f.label : t(f.key);
    const b = el("button", { class: "nav-item" + (f.other ? " other" : "") + (f.key === S.folder && !S.query ? " on" : "") + (was && !was.has(f.key) && f.other ? " new" : ""),
      style: f.other && f.depth ? `--depth:${f.depth}` : null, "data-folder": f.key, "data-tip": f.other ? f.key : name, "data-rail": "", onclick: () => { sideOpen(false); openFolder(f.key); },
      "data-depth": f.other ? f.depth || 0 : null, "data-n": f.other ? n || 0 : null,
      html: icon(f.other ? "folder-open" : FOLDER_ICON[f.key] || "folder-open") + `<span class="label" dir="auto">${esc(name)}</span>` + (n || f.other ? `<span class="count">${n || ""}</span>` : "") +
        (f.other ? `<span class="nav-more" role="button" aria-label="${esc(t("folder_menu"))}">${icon("ellipsis", "small")}</span>` : "") +
        (kids ? `<span class="nav-fold" role="button" aria-label="${esc(t("fold"))}">${icon("chevron-right", "small")}</span>` : "") });
    if (kids) $(".nav-fold", b).addEventListener("click", (e) => { e.stopPropagation(); toggleFold(f.key); });
    if (f.other) {
      seenOther = true;
      b.addEventListener("contextmenu", (e) => { e.preventDefault(); folderMenu(b, f); });
      $(".nav-more", b).addEventListener("click", (e) => { e.stopPropagation(); folderMenu(b, f); });
      folderDrag(b, f, own);
    } else if (READ_ALL_IN.includes(f.key)) {
      b.addEventListener("contextmenu", (e) => { e.preventDefault(); folderMenu(b, f); });
    }
    if (["archive", "trash", "inbox", "junk"].includes(f.key) || f.other) {
      b.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("x-ragdoll/ids")) { e.preventDefault(); b.classList.add("drop"); } });
      b.addEventListener("dragleave", () => b.classList.remove("drop"));
      b.addEventListener("drop", (e) => { b.classList.remove("drop"); const ids = JSON.parse(e.dataTransfer.getData("x-ragdoll/ids") || "[]").filter((i) => rowOf(i)?.folder !== f.key); if (ids.length) moveMail(ids, f.key); });
    }
    nav.append(b);
  }
  applyFold();
  const who_ = S.boot.demo ? t("demo") : S.boot.user, acct = $("#account");
  acct.dataset.tip = who_; acct.setAttribute("aria-label", who_);
  const up = $("#update");
  up.hidden = !S.update;
  if (S.update) up.innerHTML = icon("download") + `<span>${esc(t("update_to", "v" + S.update.version))}</span>`;
}

// the owner's own folders sit under a heading that folds them away; a folder with folders inside has
// its own arrow. A folded folder adds the unread mail inside it to its own count. The open folder stays.
// A folder dropped on the heading goes to the top level, first in it.
function navSection() {
  const sec = el("div", { class: "nav-sec" },
    el("button", { class: "nav-sec-btn", "aria-label": t("fold"), onclick: () => toggleFold("@mine"),
      html: `<span class="label">${esc(t("my_folders"))}</span>` + icon("chevron-right", "small") + `<span class="count"></span>` }),
    el("button", { class: "icon-btn tiny nav-sec-add", "data-tip": t("new_folder"), "aria-label": t("new_folder"), onclick: () => newFolder(), html: icon("plus", "small") }));
  sec.addEventListener("dragover", (e) => { if (!dragF) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; clearDrop(); sec.classList.add("drop"); });
  sec.addEventListener("dragleave", (e) => { if (!sec.contains(e.relatedTarget)) sec.classList.remove("drop"); });
  sec.addEventListener("drop", (e) => {
    if (!dragF) return;
    e.preventDefault();
    const g = dragF.f;
    dragF = null; clearDrop();
    const first = ownFolders().find((x) => !x.up && x.key !== g.key);
    if (g.up) moveFolder(g, null, { at: (key) => first && placeFolder(key, first.key, "before") });
    else if (first) { const snap = navRects(); placeFolder(g.key, first.key, "before"); renderNav(); flipNav(snap); }
  });
  return sec;
}
function toggleFold(key) {
  const s = new Set(PREFS.folded || []);
  if (s.has(key)) s.delete(key); else s.add(key);
  savePref({ folded: [...s] });
  applyFold();
}
function unfold(key) {
  if (PREFS.folded?.includes(key)) savePref({ folded: PREFS.folded.filter((k) => k !== key) });
}
function applyFold() {
  const folded = new Set(PREFS.folded || []), all = folded.has("@mine");
  const items = $$("#nav .nav-item.other"), sum = new Map(items.map((b) => [b, +b.dataset.n]));
  const stack = [];
  let secSum = 0;
  for (const b of items) {
    const d = +b.dataset.depth;
    while (stack.length && +stack.at(-1).dataset.depth >= d) stack.pop();
    const up = stack.find((x) => folded.has(x.dataset.folder));
    if (up) sum.set(up, sum.get(up) + +b.dataset.n);
    if (all) secSum += +b.dataset.n;
    b.classList.toggle("gone", (all || !!up) && !b.classList.contains("on"));
    b.classList.toggle("folded", folded.has(b.dataset.folder));
    stack.push(b);
  }
  for (const [b, n] of sum) $(".count", b).textContent = n || "";
  const sec = $("#nav .nav-sec");
  if (sec) { sec.classList.toggle("folded", all); $(".count", sec).textContent = all && secSum ? secSum : ""; }
}

// The owner's own folders in the sidebar's order: each folder's own folders right under it. At each level the
// order the owner dragged them into comes first (PREFS.folder_order), the rest A-Z as the chosen language sorts
// (Chinese by pinyin, 2 before 10). Each comes with `up`, the folder it is in (null at the top level).
let collator = null;
function ownFolders() {
  if (collator?.lang !== LOCALE) collator = { lang: LOCALE, c: new Intl.Collator(LOCALE, { numeric: true, sensitivity: "base" }) };
  const order = new Map((PREFS.folder_order || []).map((k, i) => [k, i]));
  const cmp = (a, b) => order.has(a.key) && order.has(b.key) ? order.get(a.key) - order.get(b.key)
    : order.has(a.key) ? -1 : order.has(b.key) ? 1 : collator.c.compare(a.label, b.label) || (a.key < b.key ? -1 : 1);
  const root = [], stack = [];
  for (const f of S.boot.folders) {
    if (!f.other) continue;
    const d = f.depth || 0;
    while (stack.length && (stack.at(-1).depth || 0) >= d) stack.pop();
    const n = { ...f, up: stack.at(-1)?.key ?? null, kids: [] };
    (stack.at(-1)?.kids || root).push(n);
    stack.push(n);
  }
  const out = [];
  const walk = (list) => { for (const { kids, ...f } of list.sort(cmp)) { out.push(f); walk(kids); } };
  walk(root);
  return out;
}
// a folder and the folders inside it, from ownFolders()
function subtreeOf(list, key) {
  const i = list.findIndex((f) => f.key === key);
  if (i < 0) return [];
  let j = i + 1;
  while (j < list.length && (list[j].depth || 0) > (list[i].depth || 0)) j++;
  return list.slice(i, j);
}
// "Projects / Acme": the folders a folder is in, for the search in the move menus
function whereOf(f, list) {
  const by = new Map(list.map((x) => [x.key, x])), out = [];
  for (let up = by.get(f.up); up; up = by.get(up.up)) out.unshift(up.label);
  return out.join(" / ");
}

// A renamed or moved folder: the open folder, the selection, the fold state, the order and the recent
// folders follow it to its new name, and so do the folders inside it (old + sep + ...).
function followFolder(old, nu, sep) {
  if (old === nu) return false;
  const map = (k) => (k === old ? nu : typeof k === "string" && k.startsWith(old + sep) ? nu + k.slice(old.length) : k);
  const mapId = (i) => { const c = i.lastIndexOf(":"); return c < 0 ? i : map(i.slice(0, c)) + i.slice(c); };
  const was = S.folder;
  S.folder = map(S.folder);
  if (S.sel) S.sel = mapId(S.sel);
  if (S.anchor) S.anchor = mapId(S.anchor);
  if (S.focus) S.focus = mapId(S.focus);
  S.multi = new Set([...S.multi].map(mapId));
  const patch = {};
  for (const k of ["folded", "folder_order", "folder_recent"]) if (PREFS[k]?.some((x) => map(x) !== x)) patch[k] = [...new Set(PREFS[k].map(map))];
  if (Object.keys(patch).length) savePref(patch);
  return S.folder !== was || !!S.thread?.rows.some((r) => mapId(r.id) !== r.id);
}
// deleted folders leave nothing behind in the prefs
function forgetFolders(keys) {
  const gone = new Set(keys), patch = {};
  for (const k of ["folded", "folder_order", "folder_recent"]) if (PREFS[k]?.some((x) => gone.has(x))) patch[k] = PREFS[k].filter((x) => !gone.has(x));
  if (Object.keys(patch).length) savePref(patch);
}
// after a rename or move that reached the open folder or the open mail: the list and the mail are shown
// again under their new names, the selection kept
async function showMoved() {
  await loadList({ quiet: true });
  if (S.thread && !S.compose && S.focus) openThread(S.focus);
}

// the sidebar's rows glide from where they were to where they are now (a folder moved, renamed or reordered)
function navRects() {
  return new Map($$("#nav .nav-item.other").map((b) => [b.dataset.folder, b.getBoundingClientRect().top]));
}
function flipNav(snap, rename = (k) => k) {
  if (REDUCED.matches) return;
  const was = new Map([...snap].map(([k, y]) => [rename(k), y]));
  for (const b of $$("#nav .nav-item.other")) {
    const y = was.get(b.dataset.folder);
    if (y == null || b.classList.contains("gone")) continue;
    const dy = y - b.getBoundingClientRect().top;
    if (Math.abs(dy) < 1) continue;
    b.classList.remove("new");
    b.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 280, easing: EASE });
  }
}
const renamer = (old, nu, sep) => (k) => (k === old ? nu : k.startsWith(old + sep) ? nu + k.slice(old.length) : k);

// The owner's own order: `key` goes right before or after `target` among the folders beside it.
function placeFolder(key, target, where) {
  const keys = ownFolders().map((f) => f.key).filter((k) => k !== key);
  const at = keys.indexOf(target);
  if (at < 0) return;
  keys.splice(where === "after" ? at + 1 : at, 0, key);
  savePref({ folder_order: keys });
}
// Put a folder in another one (parent null: the top level). It is a rename on the server: the mail and the
// folders inside go along; the open folder, the selection and the fold state follow. at(newKey) places it
// among its new neighbours. Undo puts it back.
async function moveFolder(f, parent, { at } = {}) {
  const snap = navRects();
  let r;
  try { r = await api("folder_move", parent == null ? { key: f.key, top: true } : { key: f.key, parent }); } catch (e) { fail(e); return; }
  const shown = followFolder(f.key, r.key, r.sep);
  if (parent != null) unfold(parent);
  at?.(r.key);
  await refreshCounts();
  renderNav();
  flipNav(snap, renamer(f.key, r.key, r.sep));
  if (shown) showMoved();
  if (r.key === f.key) return;
  toast(parent == null ? t("moved_top") : t("moved_to", folderName(parent)), { ms: 6000, action: { label: t("undo"), run: async () => {
    const back = navRects();
    try { await api("folder_move", { key: r.key, parent: r.was }); } catch (e) { return fail(e); }
    const again = followFolder(r.key, f.key, r.sep);
    await refreshCounts();
    renderNav();
    flipNav(back, renamer(r.key, f.key, r.sep));
    if (again) showMoved();
  } } });
}

// Dragging an own folder: onto another one puts it inside (the folder lights up as for mail); near the top
// or bottom edge of one puts it before or after it (a line shows where). Not into itself or a folder inside
// it, and not onto the built-in folders (they take mail only). The heading takes it to the top level.
let dragF = null;
function clearDrop() {
  for (const n of $$("#nav .drop, #nav .drop-before, #nav .drop-after")) n.classList.remove("drop", "drop-before", "drop-after");
}
function folderZone(b, f, e, list) {
  if (!dragF || dragF.inside.has(f.key)) return null;
  const r = b.getBoundingClientRect(), y = (e.clientY - r.top) / r.height;
  const open = list[list.findIndex((x) => x.key === f.key) + 1]?.up === f.key && !PREFS.folded?.includes(f.key);
  const z = y < 0.3 ? "before" : y > 0.7 && !open ? "after" : "inside";
  return z === "inside" && dragF.f.up === f.key ? null : z;
}
function folderDrag(b, f, list) {
  b.draggable = true;
  b.addEventListener("dragstart", (e) => {
    dragF = { f, inside: new Set(subtreeOf(list, f.key).map((x) => x.key)) };
    e.dataTransfer.setData("x-ragdoll/folder", f.key);
    e.dataTransfer.effectAllowed = "move";
    requestAnimationFrame(() => { for (const x of $$("#nav .nav-item.other")) x.classList.toggle("dragging", !!dragF?.inside.has(x.dataset.folder)); });
  });
  b.addEventListener("dragend", () => { dragF = null; clearDrop(); for (const x of $$("#nav .dragging")) x.classList.remove("dragging"); });
  b.addEventListener("dragover", (e) => {
    if (!dragF) return;
    const z = folderZone(b, f, e, list);
    if (!z) return clearDrop();
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const cls = z === "inside" ? "drop" : "drop-" + z;
    if (!b.classList.contains(cls)) { clearDrop(); b.classList.add(cls); }
  });
  b.addEventListener("dragleave", (e) => { if (!b.contains(e.relatedTarget)) b.classList.remove("drop-before", "drop-after"); });
  b.addEventListener("drop", (e) => {
    if (!dragF) return;
    e.preventDefault();
    const z = folderZone(b, f, e, list), g = dragF.f;
    dragF = null; clearDrop();
    if (!z) return;
    const parent = z === "inside" ? f.key : f.up;
    const at = z === "inside" ? null : (key) => placeFolder(key, f.key, z);
    if (parent !== g.up) return moveFolder(g, parent, { at });
    const snap = navRects();
    at(g.key);
    renderNav();
    flipNav(snap);
  });
}

// A menu of folders with a box on top to find one: typing narrows it (Chinese too, once the input method is
// done), arrows walk it, Enter takes the first one found. entries: "-" or {key, label, depth, icon, run, on (a
// tick), off (shown, can't be picked), where (the folders it is in), find: false (left out of a search)}.
// make(name): the "New folder" that ends a search, with the words typed.
function pickMenu(anchor, entries, { make } = {}) {
  closeLayer();
  const input = el("input", { type: "text", spellcheck: "false", autocomplete: "off", dir: "auto", placeholder: t("search"), "aria-label": t("search") });
  const list = el("div", { class: "pick-list" });
  const m = el("div", { class: "menu pick", role: "menu" }, el("label", { class: "pick-find", html: icon("search", "small") }, input), list);
  const item = (x, hint) => el("button", { role: "menuitem", disabled: !!x.off, style: x.depth ? `--depth:${x.depth}` : null,
    onclick: () => { closeLayer(); x.run(); },
    html: icon(x.icon || "folder-open") + `<span class="label" dir="auto">${esc(x.label)}</span>` +
      (x.on ? icon("check", "small on-mark") : hint ? `<span class="grow"></span><span class="hint" dir="auto">${esc(hint)}</span>` : "") });
  const draw = () => {
    const q = input.value.trim().toLocaleLowerCase();
    list.replaceChildren();
    if (!q) { for (const x of entries) list.append(x === "-" ? el("hr") : item(x)); return; }
    const seen = new Set();
    const hits = entries.filter((x) => x !== "-" && x.find !== false && !x.off && !seen.has(x.key) && seen.add(x.key) &&
      x.label.toLocaleLowerCase().includes(q));
    for (const x of hits) list.append(item({ ...x, depth: 0 }, x.where));
    if (!hits.length) list.append(el("div", { class: "menu-note" }, t("no_results")));
    if (make) list.append(el("hr"), item({ icon: "folder-plus", label: t("new_folder"), run: () => make(input.value.trim()) }));
  };
  input.addEventListener("input", draw);
  // the keys stay in the menu: the page's own shortcuts don't see them (Escape still closes it)
  m.addEventListener("keydown", (e) => {
    if (e.isComposing || e.keyCode === 229) return e.stopPropagation();
    if (e.key === "Escape") return;
    e.stopPropagation();
    const items = $$("button:not(:disabled)", list), k = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const d = e.key === "ArrowDown" ? 1 : -1;
      if (k < 0) items[d > 0 ? 0 : items.length - 1]?.focus();
      else if (k + d < 0) input.focus();
      else items[(k + d) % items.length]?.focus();
    } else if (e.target === input && e.key === "Enter") {
      e.preventDefault();
      items[0]?.click();
    } else if (e.target !== input && (e.key === "Home" || e.key === "End")) {
      e.preventDefault();
      items[e.key === "Home" ? 0 : items.length - 1]?.focus();
    } else if (e.target !== input && (e.key === "Backspace" || (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey))) {
      input.focus();      // typing on an item goes on in the box
    }
  });
  draw();
  const catcher = el("div", { style: "position:fixed;inset:0", onmousedown: closeLayer });
  $("#layer").append(catcher, m);
  m.style.width = Math.min(360, Math.max(240, m.offsetWidth)) + "px";      // the menu keeps its width while it narrows
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
  const top = Math.max(8, Math.min(r.bottom + 6, innerHeight - m.offsetHeight - 8));
  m.style.top = top + "px";
  m.style.maxHeight = innerHeight - top - 8 + "px";
  input.focus();
}

// the folders mail was moved to last come first in the move menu
function noteRecent(key) {
  savePref({ folder_recent: [key, ...(PREFS.folder_recent || []).filter((k) => k !== key)].slice(0, 5) });
}

// a question before something that can't be taken back, or that moves a lot of mail
function confirmSheet({ title, text, ok, run, safe = false }) {
  const go = el("button", { class: "btn primary danger", onclick: async () => {
    go.disabled = true;
    go.innerHTML = icon("loader-circle", "small spin") + esc(ok);
    try { await run(); closeLayer(); } catch (e) { go.disabled = false; go.textContent = ok; fail(e); }
  } }, ok);
  const no = el("button", { class: "btn", onclick: closeLayer }, t("cancel"));
  sheet(el("div", {}, el("h2", {}, title), el("p", { class: "sheet-sub" }, text), el("div", { class: "sheet-acts" }, no, go)));
  (safe ? no : go).focus();
}

// the owner's own folders: make one (inside another too), rename, move, delete one with its mail going to Trash
function nameSheet(title, value, run) {
  const input = el("input", { type: "text", value, maxlength: "60", dir: "auto", spellcheck: "false", autocomplete: "off", "aria-label": title });
  let busy = false;
  const go = async () => {
    const name = input.value.trim();
    if (!name || busy) return input.focus();
    busy = true;
    try { await run(name); closeLayer(); } catch (e) { fail(e); input.focus(); }
    busy = false;
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !K.isIME(e)) { e.preventDefault(); go(); } });
  sheet(el("div", {}, el("h2", {}, title), el("div", { class: "form" }, input),
    el("div", { class: "sheet-acts" }, el("button", { class: "btn", onclick: closeLayer }, t("cancel")),
      el("button", { class: "btn primary", onclick: go }, t("ok")))));
  requestAnimationFrame(() => { input.focus(); input.select(); });
}
// then: what to do with the new folder (the move menu puts the mail in it); parent: the folder to make it in
function newFolder(then, parent = null, value = "") {
  nameSheet(t(parent ? "new_subfolder" : "new_folder"), value, async (name) => {
    const r = await api("folder_new", parent ? { name, parent } : { name });
    if (parent) unfold(parent);
    await refreshCounts();
    then?.(r.key);
  });
}
function renameFolder(f) {
  nameSheet(t("rename_folder"), f.label, async (name) => {
    const snap = navRects();
    const r = await api("folder_rename", { key: f.key, name });
    const shown = followFolder(f.key, r.key, r.sep);
    await refreshCounts();
    flipNav(snap, renamer(f.key, r.key, r.sep));
    if (shown) showMoved(); else loadList({ quiet: true });
  });
}
// an empty folder goes at once; one with mail or folders inside asks first, then its mail (and the mail of
// the folders inside) goes to Trash, never deleted for good, and the folders go
async function deleteFolder(f) {
  let use;
  try { use = await api("folder_delete", { key: f.key, check: true }); } catch (e) { return fail(e); }
  const go = async (trash) => {
    const r = await api("folder_delete", trash ? { key: f.key, trash } : { key: f.key });
    const gone = r.deleted || [f.key];
    forgetFolders(gone);
    if (gone.includes(S.folder)) await openFolder("inbox");
    await refreshCounts();
    if (trash) toast(t("folder_gone_trash", f.label));
  };
  if (!use.mails && !use.folders) return go(false).catch(fail);
  const text = [use.mails ? t(use.mails === 1 ? "del_mails_1" : "del_mails_n", use.mails) : "",
    use.folders ? t(use.folders === 1 ? "del_kids_1" : "del_kids_n", use.folders) : ""].filter(Boolean).join(" ");
  confirmSheet({ title: t("del_folder_q", f.label), text, ok: t("delete_folder"), run: () => go(true) });
}
// every mail in Trash or Junk deleted for good, after a question that says how many
async function emptyFolder(key) {
  for (const job of [...pendingMoves]) if (job.to === key) await job.commit();
  let n;
  try { n = (await api("folder_empty", { key, check: true })).count; } catch (e) { return fail(e); }
  if (!n) return toast(t("empty_none"));
  confirmSheet({ title: t("empty_q_" + key), text: t(n === 1 ? "empty_text_1" : "empty_text_n", n), ok: t("empty_" + key), safe: true, run: async () => {
    await api("folder_empty", { key });
    if (S.sel?.startsWith(key + ":") || S.thread?.rows.some((r) => r.folder === key)) { S.sel = null; S.thread = null; showEmpty(); }
    if (S.folder === key && !S.query) await loadList({ quiet: true });
    await refreshCounts();
    toast(t("emptied_" + key));
  } });
}
// the list header of Trash and Junk has a button for it
function emptyBtn(here) {
  const on = (S.folder === "trash" || S.folder === "junk") && !S.query;
  let b = $("#empty-btn");
  if (!b) {
    if (!on) return;
    b = el("button", { class: "icon-btn", id: "empty-btn", onclick: () => emptyFolder(S.folder) });
    $("#filter-btn").before(b);
  }
  b.hidden = !on;
  if (!on) return;
  b.innerHTML = icon("trash-2");
  b.dataset.tip = t("empty_" + S.folder);
  b.setAttribute("aria-label", b.dataset.tip);
  b.disabled = !here?.total;
}
// every unread mail of a folder becomes read; the list on screen follows at once
async function readAll(key) {
  try {
    await api("mark_all_read", { folder: key });
    if (S.folder === key && !S.query) await loadList({ quiet: true });
    await refreshCounts();
  } catch (e) { fail(e); }
}
const READ_ALL_IN = ["inbox", "flagged", "archive", "junk", "trash"];
function folderMenu(anchor, f) {
  const all = { icon: "mail-open", label: t("read_all"), run: () => readAll(f.key) };
  if (f.key === "trash" || f.key === "junk") {
    return menu(anchor, f.total ? [all, "-", { icon: "trash-2", label: t("empty_" + f.key), run: () => emptyFolder(f.key) }] : [all]);
  }
  if (!f.other) return menu(anchor, [all]);
  const me = ownFolders().find((x) => x.key === f.key) || f;
  menu(anchor, [
    all,
    "-",
    { icon: "folder-plus", label: t("new_subfolder"), run: () => newFolder(null, f.key) },
    { icon: "pencil", label: t("rename_folder"), run: () => renameFolder(f) },
    { icon: "folder-input", label: t("move_to"), run: () => moveFolderMenu(anchor, me) },
    { icon: "trash-2", label: t("delete_folder"), run: () => deleteFolder(f) },
    "-",
    { icon: "folder-plus", label: t("new_folder"), run: () => newFolder() },
  ]);
}
// where a folder can go: the top level or any own folder but itself and the folders inside it
function moveFolderMenu(anchor, f) {
  const own = ownFolders(), inside = new Set(subtreeOf(own, f.key).map((x) => x.key));
  const entries = [{ key: "@top", label: t("top_level"), icon: "layers", on: !f.up, run: () => f.up && moveFolder(f, null) }, "-"];
  for (const x of own) {
    entries.push({ key: x.key, label: x.label, depth: x.depth, where: whereOf(x, own), off: inside.has(x.key), on: x.key === f.up,
      run: () => x.key !== f.up && moveFolder(f, x.key) });
  }
  pickMenu(anchor, entries);
}
// a sentence from the server about folders, in the chosen language
MSGS.push([/^This invitation can't be answered from here\./, "err_rsvp_here"]);
MSGS.push([/^Can't check for updates right now\./, "err_upd"]);
MSGS.push([/^A folder can't go inside itself\./, "err_folder_self"], [/^A folder can't go inside (.*)\.$/, "err_folder_into"]);

const syncNow = () => api("sync").then(() => toast(t("syncing"), { id: "sync" })).catch(fail);
function accountMenu() {
  menu($("#account"), [
    { note: S.boot.demo ? t("demo") : S.boot.user },
    { icon: "settings", label: t("settings"), key: MOD + ",", run: openSettings },
    { icon: "refresh-cw", label: t("sync_now"), key: MOD + "R", run: syncNow },
    { icon: "folder-plus", label: t("new_folder"), run: () => newFolder() },
    { icon: "keyboard", label: t("shortcuts"), key: MOD + "/", run: shortcutsSheet },
    { icon: "download", label: t("upd_check"), run: checkUpdates },
    "-",
    { note: t("version", S.boot.version) },
  ], { above: true });
}

// ---- C1 pure: start (no page, no app state: tests/test_group_c1.py runs this part in node)
// the words of a search, as the server reads them (ragdoll_app.api_search), without its operators (from:, in:,
// is:unread...): these are what the list and the open mail mark; longest first, so "price list" wins over "price"
function searchTerms(q) {
  const strip = (s) => s.replace(/^"+|"+$/g, "");
  const out = [], seen = new Set();
  for (const w of String(q || "").match(/[\p{L}\p{N}_]+:"[^"]*"|"[^"]*"|\S+/gu) || []) {
    const i = w.indexOf(":"), k = i < 0 ? w : w.slice(0, i), v = i < 0 ? "" : strip(w.slice(i + 1));
    if (v && ["from", "to", "in", "folder"].includes(k.toLowerCase())) continue;
    if (["is:unread", "has:attachment", "has:file"].includes(w.toLowerCase())) continue;
    const term = strip(w).trim();
    if (term && !seen.has(term.toLowerCase())) { seen.add(term.toLowerCase()); out.push(term); }
  }
  return out.sort((a, b) => b.length - a.length).slice(0, 30);
}
// one pattern for all the words: any case, Chinese and Japanese inside a longer run of text (no word edges),
// the space in a quoted phrase matches a line break too
function termsRe(terms) {
  if (!terms?.length) return null;
  return new RegExp(terms.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+")).join("|"), "giu");
}
// [text before, the match] pairs; the last pair holds the rest and an empty match
function splitHits(text, re) {
  const out = [];
  let at = 0;
  if (re) for (const m of String(text).matchAll(re)) {
    if (!m[0]) continue;
    out.push([text.slice(at, m.index), m[0]]);
    at = m.index + m[0].length;
  }
  out.push([String(text).slice(at), ""]);
  return out;
}
const escHit = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// text as HTML with the words marked
function hlText(text, re) {
  return splitHits(String(text ?? ""), re).map(([a, m]) => escHit(a) + (m ? `<mark>${escHit(m)}</mark>` : "")).join("");
}
// a key pressed inside an open mail: "keep" lets the mail have it (select its text, scroll a wide table sideways),
// a direction scrolls the reading pane, null hands it on to the app's own keys (J, K, E, R...)
function frameKey(e) {
  const mod = e.metaKey || e.ctrlKey, k = e.key;
  if (mod && ["a", "c"].includes(k.toLowerCase())) return "keep";
  if (k === "ArrowLeft" || k === "ArrowRight") return "keep";
  if (k === "ArrowDown") return mod ? "end" : e.altKey ? "page" : "down";
  if (k === "ArrowUp") return mod ? "home" : e.altKey ? "pageup" : "up";
  if (k === " " && !mod) return e.shiftKey ? "pageup" : "page";
  return { PageDown: "page", PageUp: "pageup", Home: "home", End: "end" }[k] || null;
}
// the mail to open after moving ids: the one beside the open mail (sel), or beside the moved block when several
// selected ones moved (sel null); null when the open mail did not move or nothing is left
function nextAfter(rows, ids, sel) {
  const gone = new Set(ids), at = (id) => rows.findIndex((x) => x.id === id);
  let lo, hi;
  if (sel != null) {
    if (!gone.has(sel) || (lo = hi = at(sel)) < 0) return null;
  } else {
    const ks = ids.map(at).filter((k) => k >= 0);
    if (!ks.length) return null;
    lo = Math.min(...ks); hi = Math.max(...ks);
  }
  const r = rows.slice(hi + 1).find((x) => !gone.has(x.id)) || rows.slice(0, lo).reverse().find((x) => !gone.has(x.id));
  return r ? r.id : null;
}
// how far to scroll after the list was drawn again so the row under the eye stays where it was: a = {id, off,
// after} (off: its distance from the top of the view before; after: the rows below it, in case it went), offs: the
// distances now
function anchorShift(a, ids, offs) {
  if (!a) return null;
  const have = new Set(ids);
  const id = have.has(a.id) ? a.id : (a.after || []).find((x) => have.has(x));
  return id == null ? null : offs[id] - a.off;
}
// ---- C1 pure: end

// ---------------------------------------------------------------- list

// the searched words, ready to mark (one pattern per search)
let hitCache = { q: null, re: null };
function hitRe() {
  if (hitCache.q !== S.query) hitCache = { q: S.query, re: S.query ? termsRe(searchTerms(S.query)) : null };
  return hitCache.re;
}
const hl = (s) => hlText(s, hitRe());

function rowTemplate(r) {
  const outgoing = r.folder === "sent" || r.folder === "drafts";
  let name;
  if (outgoing) {
    const names = r.to.map(who);
    name = names.length ? t("to_x", names.slice(0, 3).join(", ") + (names.length > 3 ? " " + t("recipients_more", names.length - 3) : "")) : (r.folder === "drafts" ? t("draft") : "");
  } else name = who(r.from);
  const clip = r.atts.length ? icon("paperclip", "small") : "";
  const when = r.sched ? (r.sched_error ? `<span class="sched err">${icon("triangle-alert", "small")}${esc(laterTime(r.sched))}</span>` : `<span class="sched">${icon("clock", "small")}${esc(laterTime(r.sched))}</span>`) : esc(shortTime(r.ts));
  const tag = (S.query || S.folder === "flagged") && r.folder !== "inbox" ? `<span class="tag">${esc(folderName(r.folder))}</span>` : "";
  const flag = r.flagged ? `<span class="flag-ic">${icon("star", "small")}</span>` : "";
  const done = (r.answered ? `<span class="mk mk-a">${icon("reply", "small")}</span>` : "") +
    (r.forwarded ? `<span class="mk mk-f">${icon("forward", "small")}</span>` : "");
  const acts = r.sched
    ? `<button class="icon-btn tiny" tabindex="-1" data-act="unschedule" data-tip="${esc(t("dont_send"))}">${icon("calendar-x")}</button>`
    : (S.folder === "trash" || S.folder === "junk") && !S.query
    ? `<button class="icon-btn tiny" tabindex="-1" data-act="inbox" data-tip="${esc(backLabel(S.folder))}">${icon("inbox")}</button>`
    : `<button class="icon-btn tiny" tabindex="-1" data-act="archive" data-tip="${esc(t("archive_it"))}" data-key="E">${icon("archive")}</button>` +
      `<button class="icon-btn tiny" tabindex="-1" data-act="trash" data-tip="${esc(t("trash_it"))}" data-key="#">${icon("trash-2")}</button>`;
  // the selection is not part of the row's text (syncSel marks it), so a row is drawn again only when it changed
  return `<div class="row${r.unread ? " unread" : ""}${r.answered ? " has-a" : ""}" data-id="${esc(r.id)}" draggable="true">` +
    `<span class="dot"></span>${done}<span class="who" dir="auto">${hl(name)}</span>` +
    `<span class="meta">${tag}${flag}${clip}${when}</span>` +
    `<span class="subj" dir="auto">${hl(r.subject || t("no_subject"))}</span>` +
    `<span class="snip" dir="auto">${hl(r.snippet) || "&nbsp;"}</span>` +
    `<span class="hover-acts">${acts}</span></div>`;
}

// rows that were not in the list a moment ago (new mail, an undo) fade in; a new folder fades in as a whole
let shownIds = new Set(), shownKey = null, shownMarks = new Map();
const marksOf = (r) => ({ a: !!r.answered, f: !!r.forwarded, s: !!r.flagged });
function renderRows() {
  const box = $("#rows");
  const key = S.folder + "\n" + S.query + "\n" + JSON.stringify(filterArgs());
  const same = key === shownKey && shownIds.size > 0;
  const oldMarks = same ? shownMarks : new Map();
  shownIds = new Set(S.rows.map((x) => x.id)); shownKey = key;
  shownMarks = new Map(S.rows.map((x) => [x.id, marksOf(x)]));
  if (!S.rows.length) {
    if (S.loading) { box.replaceChildren(); return; }
    const filtered = filterOn();
    const msg = S.query || filtered ? t("no_results") : (S.syncing && S.folder === "inbox" ? t("syncing") : t("no_mail"));
    box.innerHTML = `<div class="rows-empty">${S.syncing && !S.query && !filtered ? icon("loader-circle", "big spin") : icon(S.query ? "search" : filtered ? "list-filter" : FOLDER_ICON[S.folder] || "folder-open", "big")}<span>${esc(msg)}</span></div>`;
    return;
  }
  const html = S.rows.map(rowTemplate);
  const more = S.more ? `<div class="rows-more">${icon("loader-circle", "spin")}</div>` : "";
  if (!same || !$(".row", box)) {
    box.innerHTML = html.join("") + more;
    $$(".row", box).forEach((n, k) => { n._h = html[k]; });
    syncSel();
    measureRow(box);
    if (!REDUCED.matches) box.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: "ease-out" });
    return;
  }
  // the same list again: only the rows that came, went or changed are touched, the others stay as they are
  // (drawing every row again counted the rows out of sight at a guessed height, and the view jumped)
  const anchor = takeAnchor(box);
  const old = new Map($$(".row", box).map((n) => [n.dataset.id, n]));
  const want = [], added = [], changed = [];
  S.rows.forEach((r, k) => {
    const n = old.get(r.id);
    if (n && n._h === html[k]) { want.push(n); old.delete(r.id); return; }
    const m = rowNode(html[k]);
    if (n) { if (n.classList.contains("ctx")) m.classList.add("ctx"); changed.push(m); } else added.push(m);
    want.push(m);
  });
  const drop = [...old.values(), ...$$(":scope > :not(.row)", box)];
  for (const n of drop) n.remove();
  let cur = box.firstElementChild;
  for (const n of want) {
    if (n === cur) { cur = cur.nextElementSibling; continue; }
    box.insertBefore(n, cur);
  }
  if (more) box.insertAdjacentHTML("beforeend", more);
  syncSel();
  keepAnchor(box, anchor);
  if (REDUCED.matches) return;
  // a row that came in above the one held would push it while it opens: that one is simply there
  const at = anchor ? want.findIndex((n) => n.dataset.id === anchor.id) : -1;
  growRows(added.filter((n) => want.indexOf(n) > at));
  for (const n of changed) {
    const was = oldMarks.get(n.dataset.id), now = shownMarks.get(n.dataset.id);
    if (!was || !now) continue;
    if ((now.a && !was.a) || (now.f && !was.f)) showDone(n, now.a && !was.a, now.f && !was.f);
    if (now.s && !was.s) popStar($(".flag-ic", n));
  }
}
const rowTpl = document.createElement("template");
function rowNode(html) {
  rowTpl.innerHTML = html;
  const n = rowTpl.content.firstElementChild;
  n._h = html;
  return n;
}
// the row the eye is on: the one under the pointer, else the open one when it is in view, else the first in view.
// At the very top, with the pointer elsewhere, nothing is held: new mail shows at the top.
function takeAnchor(box) {
  const nodes = $$(".row", box);
  if (!nodes.length) return null;
  const hover = box.matches(":hover") ? nodes.find((n) => n.matches(":hover")) : null;
  if (!hover && box.scrollTop <= 0) return null;
  const view = box.getBoundingClientRect();
  const inView = (n) => { const r = n.getBoundingClientRect(); return r.bottom > view.top && r.top < view.bottom; };
  const n = hover || nodes.find((x) => x.classList.contains("on") && inView(x)) || nodes[firstInView(box, nodes)];
  const k = nodes.indexOf(n);
  return { id: n.dataset.id, off: n.getBoundingClientRect().top - view.top, after: nodes.slice(k + 1, k + 30).map((x) => x.dataset.id) };
}
function keepAnchor(box, a) {
  if (!a) return;
  const top = box.getBoundingClientRect().top, offs = {};
  for (const id of [a.id, ...a.after]) {
    const n = box.querySelector(`:scope > .row[data-id="${CSS.escape(id)}"]`);
    if (n) offs[id] = n.getBoundingClientRect().top - top;
  }
  const d = anchorShift(a, Object.keys(offs), offs);
  if (d) box.scrollTop += d;
}
// a row's real height, so the rows not drawn yet (content-visibility) are counted at their true size
// the first row in view, by halving: rows are in order
function firstInView(box, nodes) {
  const top = box.getBoundingClientRect().top;
  let lo = 0, hi = nodes.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (nodes[mid].getBoundingClientRect().bottom > top) hi = mid; else lo = mid + 1; }
  return lo;
}
// (the size given is the row's content box: padding and border come on top)
function measureRow(box) {
  if (box.style.getPropertyValue("--row-h")) return;
  const n = $(":scope > .row:not(.leaving)", box);
  if (!n) return;
  n.style.contentVisibility = "visible";        // laid out for real, whether in view or not
  const cs = getComputedStyle(n);
  const h = n.getBoundingClientRect().height - ["paddingTop", "paddingBottom", "borderTopWidth", "borderBottomWidth"].reduce((s, k) => s + parseFloat(cs[k]), 0);
  n.style.contentVisibility = "";
  if (h > 20) box.style.setProperty("--row-h", h.toFixed(2) + "px");
}

// the next page goes after the rows already shown, without drawing those again
function appendRows(add) {
  const box = $("#rows"), more = $(".rows-more", box);
  if (!$(".row", box)) return renderRows();
  for (const x of add) { shownIds.add(x.id); shownMarks.set(x.id, marksOf(x)); }
  const nodes = add.map((x) => rowNode(rowTemplate(x)));
  if (more) more.before(...nodes); else box.append(...nodes);
  if (more && !S.more) more.remove();
  syncSel();
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

// a new replied / forwarded arrow comes in the way it points
function showDone(node, replied, forwarded) {
  if (REDUCED.matches) return;
  const come = (n, dx) => n?.animate([{ opacity: 0, transform: `translateX(${dx}px) scale(.7)` }, { opacity: 1, transform: "none" }],
    { duration: 320, easing: "cubic-bezier(.2, .8, .2, 1)" });
  if (replied) come($(".mk-a", node), 5);
  if (forwarded) come($(".mk-f", node), -5);
}

// rows going away fold up before they are dropped
const SMOOTH = "cubic-bezier(.4, 0, .2, 1)";
function foldRows(nodes) {
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
  for (const n of nodes) {
    const h = n.offsetHeight + "px";
    n.classList.add("leaving");
    const a = n.animate([
      { height: "0px", opacity: 0, transform: "translateY(-4px)", paddingTop: "0px", paddingBottom: "0px" },
      { height: h, opacity: 0, transform: "translateY(-4px)", offset: 0.55 },
      { height: h, opacity: 1, transform: "none" },
    ], { duration: 340, easing: SMOOTH });
    a.finished.finally(() => n.classList.toggle("leaving", false)).catch(() => {});
  }
}

// ---------------------------------------------------------------- filter

const filterArgs = () => {
  const f = S.filter;
  if (S.query || S.folder === "scheduled") return {};
  return { unread: f.unread || undefined, att: f.att || undefined, from: f.from || undefined, starred: (f.starred && S.folder !== "flagged") || undefined };
};
const filterOn = () => Object.values(filterArgs()).some(Boolean);
function syncFilterUI() {
  const b = $("#filter-btn");
  b.disabled = !!S.query || S.folder === "scheduled";
  b.classList.toggle("on", filterOn());
  b.dataset.tip = t("filter");
  b.setAttribute("aria-label", t("filter"));
}
function setFilter(patch) {
  S.filter = patch ? { ...S.filter, ...patch } : {};
  S.rows = []; S.more = false; S.loading = true;
  renderRows();
  loadList();
}
async function filterMenu() {
  const folder = S.folder, f = S.filter;
  let people = [];
  try { people = (await api("senders", { folder })).people; } catch { /* the marks still work */ }
  if (folder !== S.folder || S.query) return;
  // the person of the mail that is open comes first, then who writes most
  const cur = rowOf(S.focus || S.sel), out = folder === "sent" || folder === "drafts";
  const first = cur && (out ? cur.to?.[0] : cur.from);
  if (first?.addr && first.addr !== S.boot.user) people = [first, ...people.filter((p) => p.addr !== first.addr)].slice(0, 6);
  if (f.from && !people.some((p) => p.addr === f.from)) people.unshift({ name: f.fromName, addr: f.from });
  const items = [{ icon: "mail", label: t("f_unread"), on: !!f.unread, run: () => setFilter({ unread: !f.unread }) }];
  if (folder !== "flagged") items.push({ icon: "star", label: t("flagged"), on: !!f.starred, run: () => setFilter({ starred: !f.starred }) });
  items.push({ icon: "paperclip", label: t("f_att"), on: !!f.att, run: () => setFilter({ att: !f.att }) });
  if (people.length) items.push("-");
  for (const p of people) {
    const on = f.from === p.addr;
    items.push({ icon: "circle-user-round", label: p.name || p.addr, on, run: () => setFilter(on ? { from: "", fromName: "" } : { from: p.addr, fromName: p.name || "" }) });
  }
  if (filterOn()) items.push("-", { icon: "x", label: t("f_clear"), run: () => setFilter(null) });
  menu($("#filter-btn"), items);
}
$("#filter-btn").innerHTML = icon("list-filter");
$("#filter-btn").addEventListener("click", filterMenu);

let listSeq = 0;
// one page of the list on screen: a folder (with its filter) or a search; the server gives at most 500 at once
const PAGE = 100, MAX_PAGE = 500;
const fetchRows = (offset, limit) => (S.query
  ? api("search", { q: S.query, limit, offset })
  : api("list", { folder: S.folder, limit, offset, ...filterArgs() }));
let moreJob = null;
async function loadList({ quiet = false } = {}) {
  const seq = ++listSeq;
  syncFilterUI();
  if (!quiet) { S.loading = true; moreLater = false; }
  refreshAt = quiet ? seq : 0;
  try {
    // a page being added is part of what a refresh keeps
    if (quiet && moreJob) { await moreJob; if (seq !== listSeq) return; }
    // a refresh asks again for every row already loaded, in pages, and for the open mail's row if it slid further
    // down (new mail on top): the list never shrinks under the reader and the open mail stays in it
    const want = quiet ? Math.max(PAGE, S.rows.length + hidden.size) : PAGE;
    // and the last row loaded, so new mail on top does not push rows off the end
    const keep = quiet && !S.filter.unread ? [S.sel && S.rows.some((x) => x.id === S.sel) ? S.sel : null, S.rows.at(-1)?.id].filter(Boolean) : [];
    let rows = [], more = true, offset = 0;
    const have = new Set();
    while (more && (rows.length < want || (keep.some((id) => !have.has(id)) && rows.length < want + MAX_PAGE))) {
      const r = await fetchRows(offset, Math.min(MAX_PAGE, Math.max(PAGE, want - rows.length)));
      if (seq !== listSeq) return;
      offset += r.rows.length;
      for (const x of r.rows) if (!have.has(x.id)) { have.add(x.id); rows.push(x); }
      more = !!r.more && r.rows.length > 0;
    }
    if (seq !== listSeq) return;
    S.loading = false;
    rows = rows.filter((x) => !hidden.has(x.id));
    // with "unread" on, the mail being read stays in the list until another one is opened
    if (quiet && S.filter.unread && filterOn()) {
      const cur = S.rows.find((x) => x.id === S.sel);
      if (cur && !rows.some((x) => x.id === cur.id)) {
        const at = rows.findIndex((x) => x.ts < cur.ts);
        rows.splice(at < 0 ? rows.length : at, 0, cur);
      }
    }
    if (quiet && JSON.stringify(rows) === JSON.stringify(S.rows) && more === S.more) return;
    S.rows = rows; S.more = more;
    renderRows();                       // a refresh keeps the row under the eye in place (renderRows)
    if (!quiet) $("#rows").scrollTop = 0;
  } catch (e) { if (seq === listSeq && S.loading) { S.loading = false; renderRows(); } if (!quiet) fail(e); }
  finally {
    if (refreshAt === seq) refreshAt = 0;
    // the end of the list was reached while the refresh was on its way: the next page comes now
    if (seq === listSeq && moreLater) { moreLater = false; loadMore(); }
  }
}

// the next page, when the list is scrolled near its end; a page for an older list (another folder, another
// search) is dropped, and during a refresh it waits for it
let moreLater = false;
async function loadMore() {
  if (!S.more || S.loadingMore || S.loading) return;
  if (refreshing()) { moreLater = true; return; }
  const seq = listSeq;
  S.loadingMore = true;
  const job = (async () => {
    try {
      const r = await fetchRows(S.rows.length, PAGE);
      if (seq !== listSeq) return;
      const have = new Set(S.rows.map((x) => x.id));
      const add = r.rows.filter((x) => !have.has(x.id) && !hidden.has(x.id));
      S.rows.push(...add);
      S.more = !!r.more && r.rows.length > 0;
      appendRows(add);
    } catch (e) { if (seq === listSeq) fail(e); }
  })();
  moreJob = job;
  try { await job; } finally { S.loadingMore = false; if (moreJob === job) moreJob = null; }
}
// the newest loadList is a quiet refresh still on its way
let refreshAt = 0;
const refreshing = () => refreshAt !== 0 && refreshAt === listSeq;

function markRow(id, patch) {
  const r = S.rows.find((x) => x.id === id);
  if (r) Object.assign(r, patch);
  const tr = S.thread?.rows.find((x) => x.id === id);
  if (tr) Object.assign(tr, patch);
  const node = $(`.row[data-id="${CSS.escape(id)}"]`);
  if (!node || !r) return;
  if ("flagged" in patch) setStar(node, r.flagged);
  else if ("unread" in patch) node.classList.toggle("unread", patch.unread);
}

// ---------------------------------------------------------------- several mails at once

const isSel = (id) => (S.multi.size > 1 ? S.multi.has(id) : id === S.sel);
function syncSel() {
  let prev = null;
  const joined = [];
  for (const n of $$("#rows .row")) {
    const on = isSel(n.dataset.id);
    if (on && S.multi.size > 1 && !n.classList.contains("on") && n._h) joined.push(n);
    n.classList.toggle("on", on);
    prev?.classList.toggle("on-next", on);
    prev = n;
  }
  prev?.classList.remove("on-next");
  joinRows(joined);
}
// a row that joins a selection of several: its grey grows out from inside the row to the block's edges, with the
// corners it shares with a selected neighbour already square, so the rows read as merging into one block
function joinRows(nodes) {
  if (REDUCED.matches || nodes.length > 40) return;
  for (const n of nodes) {
    const up = n.previousElementSibling?.classList.contains("on"), down = n.classList.contains("on-next");
    const r = (a, b) => `${a ? 0 : 9}px ${a ? 0 : 9}px ${b ? 0 : 9}px ${b ? 0 : 9}px`;
    n.animate([{ clipPath: `inset(${up ? 0 : 5}px 5px ${down ? 0 : 5}px 5px round ${r(up, down)})` },
      { clipPath: `inset(0px 0px 0px 0px round ${r(up, down)})` }], { duration: 180, easing: "cubic-bezier(.2, .8, .2, 1)" });
  }
}
// the mail E, # and V (and their toolbar buttons) move: the row selected in the list, not an older message of
// its conversation that was opened in the pane
const moveId = () => (S.sel && S.thread?.rows.some((x) => x.id === S.sel) ? S.sel : S.focus || S.sel);
// the mails the next action works on: the selection, or the open mail
function targets() {
  if (S.multi.size > 1) return [...S.multi];
  const id = S.focus || S.sel;
  return id ? [id] : [];
}
const rowOf = (id) => S.rows.find((x) => x.id === id) || S.thread?.rows.find((x) => x.id === id);
async function pickRow(id, e) {
  if (!(isMod(e) || e.shiftKey)) return selectRow(id);
  if (S.compose && !(await leaveCompose())) return;
  if (e.shiftKey && (S.anchor || S.sel)) {
    const ids = S.rows.map((x) => x.id);
    let a = ids.indexOf(S.anchor || S.sel), b = ids.indexOf(id);
    if (a < 0) a = b;
    const range = ids.slice(Math.min(a, b), Math.max(a, b) + 1);
    S.multi = new Set(isMod(e) ? [...S.multi, ...range] : range);
  } else {
    if (!S.multi.size && S.sel) S.multi.add(S.sel);
    if (S.multi.has(id)) S.multi.delete(id); else S.multi.add(id);
    S.anchor = id;
  }
  if (S.multi.size === 1) return selectRow([...S.multi][0]);
  if (!S.multi.size) { S.sel = null; syncSel(); return showEmpty(); }
  showMulti();
}
function selectAll() {
  if (!S.rows.length || S.folder === "scheduled") return;
  S.multi = new Set(S.rows.map((x) => x.id));
  if (S.multi.size === 1) return selectRow(S.rows[0].id);
  showMulti();
}
function clearMulti() {
  if (S.multi.size < 2) return false;
  const keep = S.sel && S.multi.has(S.sel) ? S.sel : [...S.multi][0];
  S.multi.clear();
  selectRow(keep);
  return true;
}
function showMulti() {
  S.thread = null; S.focus = null; S.sched = null;
  threadSeq++; schedSeq++;
  syncSel();
  const ids = [...S.multi], rows = ids.map(rowOf).filter(Boolean);
  const anyUnread = rows.some((r) => r.unread), allFlagged = rows.length && rows.every((r) => r.flagged);
  const inTrash = rows.length && rows.every((r) => r.folder === "trash");
  const inJunk = rows.length && rows.every((r) => r.folder === "junk");
  // moves first, as equal buttons on one line; the marks below them, quieter; the key shows on hover
  const b = (ic, label, run, key, cls = "btn") => el("button", { class: cls, onclick: run, "data-tip": key ? "" : null, "data-key": key,
    html: icon(ic, "small") + `<span>${esc(label)}</span>` });
  const acts = el("div", { class: "multi-acts" },
    el("div", { class: "multi-moves" },
      inTrash || inJunk ? b("inbox", backLabel(inJunk ? "junk" : "trash"), () => moveMail(ids, "inbox")) : b("archive", t("archive_it"), () => moveMail(ids, "archive"), "E"),
      inTrash ? null : b("trash-2", t("trash_it"), () => moveMail(ids, "trash"), "#"),
      b("folder-input", t("move_to"), (e) => moveMenu(e.currentTarget, ids), "V")),
    el("div", { class: "multi-marks" },
      b(anyUnread ? "mail-open" : "mail", anyUnread ? t("read") : t("unread"), () => markMail(ids, "seen", anyUnread), "U", "btn quiet"),
      b(allFlagged ? "star-off" : "star", allFlagged ? t("unflag") : t("flag"), () => markMail(ids, "flagged", !allFlagged), "S", "btn quiet")));
  const title = t("n_selected", ids.length), cards = Math.min(3, ids.length);
  const was = $("#pane > .multi:not(.pane-ghost)");
  if (was) {
    // more or fewer selected: the count ticks and a card joins or leaves the stack; the rest stays
    const h2 = $("h2", was), stack = $(".multi-stack", was);
    if (h2.textContent !== title) {
      const up = ids.length > (parseInt(h2.dataset.n, 10) || 0);
      h2.textContent = title; h2.dataset.n = ids.length;
      if (!REDUCED.matches) h2.animate([{ opacity: 0.2, transform: `translateY(${up ? 5 : -5}px)` }, { opacity: 1, transform: "none" }], { duration: 200, easing: "cubic-bezier(.2, .8, .2, 1)" });
    }
    for (let k = stack.children.length; k < cards; k++) stack.prepend(el("span", { class: "multi-card", style: `--k:${k}` }));
    while (stack.children.length > cards) stack.firstElementChild.remove();
    $(".multi-acts", was).replaceWith(acts);
  } else {
    const stack = el("div", { class: "multi-stack" });
    for (let k = cards - 1; k >= 0; k--) stack.append(el("span", { class: "multi-card", style: `--k:${k}` }));
    swapPane(el("div", { class: "multi" }, stack, el("h2", { "data-n": ids.length }, title), acts));
  }
  fitMoves();
  renderToolbar();
}
// the three move buttons stand side by side, all as wide as the widest; when the pane is too narrow for that line
// in this language they stand one above the other, full width
function fitMoves() {
  const box = $("#pane > .multi:not(.pane-ghost)"), moves = box && $(".multi-moves", box);
  if (!moves) return;
  moves.classList.remove("stack");
  moves.style.width = "max-content";
  const w = moves.offsetWidth;
  moves.style.width = "";
  moves.classList.toggle("stack", w > box.clientWidth - 48);
}
new ResizeObserver(() => fitMoves()).observe($("#pane"));
// the reading pane changes between one mail and several selected: the old view fades and draws back a little
// while the new one comes in (only the fade with reduced motion). The old view keeps its place in the page (an
// open mail's frames would load again if they were moved) and goes once it has faded.
function swapPane(node) {
  const pane = $("#pane"), old = [...pane.children].find((n) => !n.classList.contains("pane-ghost"));
  const kind = (n) => (n?.classList.contains("multi") ? "multi" : n?.classList.contains("doc") ? "doc" : null);
  const a = kind(old), b = kind(node);
  if (!a || !b || a === b) { pane.replaceChildren(node); return; }
  const top = pane.scrollTop;
  for (const g of $$(":scope > .pane-ghost", pane)) g.remove();
  old.classList.add("pane-ghost");
  old.style.top = -top + "px";
  old.style.transformOrigin = `50% ${top + pane.clientHeight / 2}px`;
  pane.insertBefore(node, old);
  pane.scrollTop = 0;
  old.animate(REDUCED.matches ? [{ opacity: 1 }, { opacity: 0 }] : [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "scale(.97)" }],
    { duration: 180, easing: "cubic-bezier(.4, 0, .2, 1)", fill: "forwards" }).finished.then(() => old.remove(), () => old.remove());
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
function toggleFlag() {
  const ids = targets(), rows = ids.map(rowOf).filter(Boolean);
  if (rows.length) markMail(ids, "flagged", !rows.every((r) => r.flagged));
}

async function openFolder(key) {
  if (!(await leaveCompose())) return;
  S.folder = key; S.query = ""; $("#search").value = ""; syncSearchUI();
  S.filter = {};
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
    const id = row.dataset.id;
    return moveMail(S.multi.size > 1 && S.multi.has(id) ? [...S.multi] : [id], act.dataset.act);
  }
  pickRow(row.dataset.id, e);
});
// right-click on a row: the actions of the toolbar, for that row (or the selection it is part of)
$("#rows").addEventListener("contextmenu", (e) => {
  const row = e.target.closest(".row");
  if (!row) return;
  e.preventDefault();
  const id = row.dataset.id, at = atPoint(e);
  const ids = S.multi.size > 1 && S.multi.has(id) ? [...S.multi] : [id];
  // the menu is about this row; it is not opened (that would mark it read and close a mail being written)
  const mark = () => { if (!isSel(id)) row.classList.add("ctx"); };
  const rows = ids.map(rowOf).filter(Boolean);
  if (!rows.length) return;
  const one = rows.length === 1 ? rows[0] : null;
  if (one?.sched) { menu(at, [{ icon: "calendar-x", label: t("dont_send"), run: () => dontSend(one) }]); return mark(); }
  const items = [];
  if (one && one.folder !== "drafts") items.push(
    { icon: "reply", label: t("reply"), key: "R", run: () => openCompose({ mode: "reply", id }) },
    { icon: "reply-all", label: t("replyall"), key: "A", run: () => openCompose({ mode: "replyall", id }) },
    { icon: "forward", label: t("forward"), key: "F", run: () => openCompose({ mode: "forward", id }) }, "-");
  const anyUnread = rows.some((x) => x.unread), allFlagged = rows.every((x) => x.flagged);
  const back = rows.every((x) => x.folder === "trash") ? "trash" : rows.every((x) => x.folder === "junk") ? "junk" : null;
  items.push(
    { icon: anyUnread ? "mail-open" : "mail", label: anyUnread ? t("read") : t("unread"), key: "U", run: () => markMail(ids, "seen", anyUnread) },
    { icon: allFlagged ? "star-off" : "star", label: allFlagged ? t("unflag") : t("flag"), key: "S", run: () => markMail(ids, "flagged", !allFlagged) }, "-",
    back ? { icon: "inbox", label: backLabel(back), run: () => moveMail(ids, "inbox") }
      : { icon: "archive", label: t("archive_it"), key: "E", run: () => moveMail(ids, "archive") });
  if (back !== "trash") items.push({ icon: "trash-2", label: t("trash_it"), key: "#", run: () => moveMail(ids, "trash") });
  items.push({ icon: "folder-input", label: t("move_to"), key: "V", run: () => moveMenu(at, ids) });
  menu(at, items);
  mark();
});
// a Shift-click picks a range, not text
$("#rows").addEventListener("mousedown", (e) => { if (e.shiftKey && e.target.closest(".row")) e.preventDefault(); });
// near the bottom, the next page loads; checked once per frame, not on every scroll event
let scrollTick = 0;
$("#rows").addEventListener("scroll", () => {
  if (scrollTick) return;
  scrollTick = requestAnimationFrame(() => {
    scrollTick = 0;
    const b = $("#rows");
    if (b.scrollTop + b.clientHeight > b.scrollHeight - 600) loadMore();
  });
}, { passive: true });
$("#rows").addEventListener("dragstart", (e) => {
  const row = e.target.closest(".row");
  if (!row) return;
  const id = row.dataset.id;
  e.dataTransfer.setData("x-ragdoll/ids", JSON.stringify(S.multi.size > 1 && S.multi.has(id) ? [...S.multi] : [id]));
  e.dataTransfer.effectAllowed = "move";
});

async function selectRow(id, { keepFocus = false } = {}) {
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

function step(d) {
  if (!S.rows.length) return;
  let k = S.rows.findIndex((x) => x.id === S.sel);
  k = k < 0 ? 0 : Math.max(0, Math.min(S.rows.length - 1, k + d));
  selectRow(S.rows[k].id);
}

// "Move to…": the inbox, the server's other folders, and junk
// where mail can go: Inbox, the owner's folders nested as in the sidebar (the ones used last on top when
// there are many), Junk, a new folder; a box on top finds one by name
function moveMenu(anchor, ids) {
  if (!anchor || !ids.length) return;
  const from = new Set(ids.map((i) => rowOf(i)?.folder));
  const here = (key) => from.size === 1 && from.has(key);
  const go = (key) => { noteRecent(key); moveMail(ids, key); };
  const own = ownFolders(), hasJunk = S.boot.folders.some((f) => f.key === "junk");
  const entry = (key) => key === "inbox" ? { key, label: t("inbox"), icon: "inbox", run: () => go(key) }
    : { key, label: t("junk"), icon: "archive-x", run: () => go(key) };
  const tree = [];
  if (!here("inbox")) tree.push(entry("inbox"));
  for (const f of own) tree.push({ key: f.key, label: f.label, depth: f.depth, where: whereOf(f, own), off: here(f.key), run: () => go(f.key) });
  const recent = own.length > 5 ? (PREFS.folder_recent || []).filter((k) => !here(k) && (k === "inbox" || (k === "junk" && hasJunk) || own.some((f) => f.key === k)))
    .slice(0, 3).map((k) => { const f = own.find((x) => x.key === k); return f ? { key: k, label: f.label, where: whereOf(f, own), run: () => go(k) } : entry(k); }) : [];
  const items = [...recent, ...(recent.length ? ["-"] : []), ...tree];
  if (hasJunk && !here("junk")) items.push(...(items.length ? ["-"] : []), entry("junk"));
  if (items.length) items.push("-");
  items.push({ key: "@new", icon: "folder-plus", label: t("new_folder"), find: false, run: () => newFolder(go) });
  pickMenu(anchor, items, { make: (name) => newFolder(go, null, name) });
}
const moveKey = (ids) => moveMenu($('#tools .icon-btn[data-key="V"]:not(:disabled)'), ids);

// Moves wait a few seconds so Undo is free; until then the rows are only hidden.
const hidden = new Set();
const pendingMoves = new Set();
function moveMail(ids, to) {
  if (!ids.length) return;
  // the pane changes only when what it shows moved: the open mail's own row, or the several selected ones. The
  // next mail is the one beside the open row (or beside the moved block). Another mail of the open conversation
  // that moved only leaves the conversation; mails moved outside a selection of several leave the selection.
  const sel = S.sel, many = S.multi.size > 1;
  const allSel = many && ids.every((i) => S.multi.has(i));
  const rest = many && !allSel ? [...S.multi].filter((i) => !ids.includes(i)) : null;
  const wasSel = allSel || (!many && ids.includes(sel));
  const next = wasSel ? nextAfter(S.rows, ids, allSel ? null : sel) : null;
  S.multi.clear();
  ids.forEach((i) => hidden.add(i));
  S.rows = S.rows.filter((x) => !ids.includes(x.id));
  shownIds = new Set(S.rows.map((x) => x.id));
  const gone = ids.map((i) => $(`.row[data-id="${CSS.escape(i)}"]`));
  foldRows(gone).then(() => { gone.forEach((n) => n?.remove()); if (!S.rows.length) renderRows(); });
  let leftThread = false;
  if (wasSel) { if (next) selectRow(next); else { S.sel = null; syncSel(); showEmpty(); } }
  else if (rest) { S.multi = new Set(rest); if (rest.length > 1) showMulti(); else if (rest.length) selectRow(rest[0]); else { S.sel = null; syncSel(); showEmpty(); } }
  else if (S.thread && ids.some((i) => S.thread.rows.some((r) => r.id === i))) {
    leftThread = true;
    S.thread.rows = S.thread.rows.filter((r) => !ids.includes(r.id));
    if (ids.includes(S.focus)) S.focus = sel;
    for (const n of $$("#pane > .doc:not(.pane-ghost) > .msg").filter((x) => ids.includes(x.dataset.id))) {
      if (REDUCED.matches) { n.remove(); continue; }
      n.style.overflow = "hidden";
      n.animate([{ height: n.offsetHeight + "px", opacity: 1 }, { height: "0px", opacity: 0, marginTop: "0px", marginBottom: "0px", paddingTop: "0px", paddingBottom: "0px" }],
        { duration: 260, easing: SMOOTH, fill: "forwards" }).finished.then(() => n.remove(), () => n.remove());
    }
    renderToolbar();
  }
  const job = { ids, to, done: false };
  const unhide = () => { ids.forEach((i) => hidden.delete(i)); pendingMoves.delete(job); };
  job.commit = async () => {
    if (job.done) return;
    job.done = true; clearTimeout(job.timer);
    // the server's answer names the move, so Cmd+Z can still bring it back later (undoMove)
    job.sent = api("move", { ids, to }).then((r) => { job.token = r?.undo; refreshCounts(); }, fail);
    await job.sent;
    unhide(); loadList({ quiet: true });
  };
  job.timer = setTimeout(job.commit, 5000);
  pendingMoves.add(job);
  job.undo = async () => {
    if (job.done) return;
    job.done = true; clearTimeout(job.timer); unhide();
    await loadList({ quiet: true });
    if (wasSel && sel && S.rows.some((x) => x.id === sel)) selectRow(sel);
    else if (leftThread && S.sel === sel && S.thread) openThread(sel);
  };
  UNDO.push(job);
  if (UNDO.length > 10) UNDO.shift();
  job.toast = toast(to === "archive" ? t("archived") : to === "trash" ? t("trashed") : to === "inbox" ? t("restored") : t("moved_to", folderName(to)), {
    ms: 5000,
    action: { label: t("undo"), run: () => { UNDO.splice(UNDO.indexOf(job) >>> 0, 1); job.undo(); } },
  });
}
// Cmd+Z (Ctrl+Z): the last move. While it waits it is called off; once on the server it is moved back.
const UNDO = [];                // the last 10 moves, newest last
async function undoMove() {
  const job = UNDO.pop();
  if (!job) return toast(t("nothing_undo"), { id: "undo" });
  if (!job.done) { job.toast?.close(); return job.undo(); }
  await job.sent;
  if (!job.token) return toast(t("nothing_undo"), { id: "undo" });
  try { await api("unmove", { token: job.token }); } catch (e) { return fail(e); }
  toast(t("moved_back"), { id: "undo" });
  refreshCounts();
  loadList({ quiet: true });
}
// The window is closing: send the waiting moves now.
window.addEventListener("pagehide", () => {
  for (const job of pendingMoves) {
    if (job.done) continue;
    job.done = true;
    fetch("/api/move", { method: "POST", keepalive: true, headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify({ ids: job.ids, to: job.to }) });
  }
});

function toggleUnread() {
  const ids = targets(), rows = ids.map(rowOf).filter(Boolean);
  if (rows.length) markMail(ids, "seen", rows.some((r) => r.unread));
}

// ---------------------------------------------------------------- search

let searchTimer = null;
// the list's header names the folder; the search box takes its place while it is in use or holds words
// the box shows while it has focus or words; closing plays the shrink (style.css) before it goes
let searchShut = 0;
function showSearch(on) {
  const head = $(".list-head");
  if (on) { clearTimeout(searchShut); searchShut = 0; head.classList.remove("closing"); head.classList.add("searching"); return; }
  if (!head.classList.contains("searching") || searchShut) return;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return head.classList.remove("searching");
  head.classList.add("closing");
  searchShut = setTimeout(() => { searchShut = 0; head.classList.remove("searching", "closing"); }, 160);
}
function syncSearchUI() {
  if (dragFocus.held) return;         // a column is being dragged: the search stays as it is
  const v = $("#search").value;
  $("#search-clear").hidden = !v;
  showSearch(!!v || document.activeElement === $("#search"));
}
function openSearch() {
  showSearch(true);
  $("#search").focus(); $("#search").select();
}
$("#search").addEventListener("focus", syncSearchUI);
$("#search").addEventListener("blur", syncSearchUI);
$("#search-btn").innerHTML = icon("search");
$("#search-btn").addEventListener("click", openSearch);
$("#search").placeholder = t("search");
$("#search-clear").innerHTML = icon("x");
$("#search-clear").addEventListener("click", () => { $("#search").value = ""; onSearch(true); $("#search").focus(); });
// while an input method still has letters open ("bao jia" before it becomes 报价) nothing is searched;
// the search runs when the words are picked
$("#search").addEventListener("input", (e) => { if (e.isComposing) syncSearchUI(); else onSearch(); });
$("#search").addEventListener("compositionend", () => onSearch());
$("#search").addEventListener("keydown", async (e) => {
  if (K.isIME(e)) return;
  if (e.key === "Escape") { e.preventDefault(); $("#search").value = ""; onSearch(true); $("#search").blur(); $("#rows").focus(); }
  if (e.key === "ArrowDown" || e.key === "Enter") {
    e.preventDefault();
    // the words typed may not have been searched yet: wait for their results, never open the list before
    const q = $("#search").value.trim();
    await runSearch();
    if (S.query !== q || $("#search").value.trim() !== q) return;
    $("#rows").focus();
    if (S.rows.length) selectRow(S.rows[0].id);
  }
});
let searchRun = null;         // the search on its way: [query, promise]
function runSearch() {
  clearTimeout(searchTimer);
  const q = $("#search").value.trim();
  if (q === S.query) return searchRun && searchRun[0] === q ? searchRun[1] : Promise.resolve();
  S.query = q;
  renderNav();
  const job = [q, loadList().finally(() => { if (searchRun === job) searchRun = null; })];
  searchRun = job;
  markOpen();
  return job[1];
}
function onSearch(now = false) {
  syncSearchUI();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, now ? 0 : 220);
}

// ---------------------------------------------------------------- reader

function goBack() {
  if (S.compose) closeCompose();
  else { S.sel = null; syncSel(); showEmpty(); $("#rows").focus({ preventScroll: true }); }
}

function showEmpty() {
  S.thread = null; S.focus = null; S.sched = null; S.multi.clear();
  threadSeq++; schedSeq++;            // a mail or a scheduled one still on its way stays out of the empty pane
  $("#pane").innerHTML = `<div class="pane-empty"><img src="logo.png" alt=""></div>`;
  renderToolbar();
}

function renderToolbar() {
  const tools = $("#tools"), end = $("#tools-end");
  const wasU = unreadState();
  tools.replaceChildren(); end.replaceChildren();
  queueMicrotask(() => easeUnread(wasU));
  $("#toolbar").classList.toggle("lined", $("#pane").scrollTop > 0);
  $("#app").classList.toggle("reading", !!(S.compose || S.sched || S.thread || S.multi.size > 1));
  tools.append(iconBtn("arrow-left", t("back"), goBack, { key: "Esc", cls: "back-btn" }));
  if (S.compose) {
    tools.append(
      iconBtn("send", t("send"), () => sendCompose(), { key: MOD + "↩", disabled: !!S.compose.busy, cls: "accent" }),
      iconBtn("calendar-clock", t("send_later"), (e) => laterMenu(e.currentTarget), { disabled: !!S.compose.busy }),
      el("span", { class: "sep" }),
      iconBtn("paperclip", t("attach"), () => pickFiles()),
      iconBtn("baseline", t("formatting"), toggleFmtBar, { cls: fmtBarOn() ? "on" : "" }),
    );
    end.append(el("span", { class: "compose-status", id: "compose-status" }, S.compose.status || ""),
      iconBtn("trash-2", t("discard"), () => discardCompose(), { disabled: !!S.compose.busy }));
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
    const inTrash = rows.every((x) => x.folder === "trash"), anyUnread = rows.some((x) => x.unread), allFlagged = rows.every((x) => x.flagged);
    const inJunk = rows.every((x) => x.folder === "junk");
    tools.append(
      inTrash || inJunk ? iconBtn("inbox", backLabel(inJunk ? "junk" : "trash"), () => moveMail(ids, "inbox"))
        : iconBtn("archive", t("archive_it"), () => moveMail(ids, "archive"), { key: "E" }),
      iconBtn("trash-2", t("trash_it"), () => moveMail(ids, "trash"), { key: "#", disabled: inTrash }),
      iconBtn("folder-input", t("move_to"), (e) => moveMenu(e.currentTarget, ids), { key: "V" }),
      iconBtn(anyUnread ? "mail-open" : "mail", anyUnread ? t("read") : t("unread"), toggleUnread, { key: "U", cls: anyUnread ? "" : "unread-mark" }),
      iconBtn("star", allFlagged ? t("unflag") : t("flag"), toggleFlag, { key: "S", cls: allFlagged ? "on fill" : "" }),
    );
    return;
  }
  const has = !!S.thread;
  const id = S.focus || S.sel;
  const r = S.thread?.rows.find((x) => x.id === id);
  // moves act on the mail selected in the list (read and star on the message opened last)
  const mv = moveId(), rm = S.thread?.rows.find((x) => x.id === mv);
  const inTrash = rm?.folder === "trash", inJunk = rm?.folder === "junk";
  tools.append(
    inTrash || inJunk
      ? iconBtn("inbox", backLabel(rm.folder), () => moveMail([mv], "inbox"), { disabled: !has })
      : iconBtn("archive", t("archive_it"), () => moveMail([mv], "archive"), { key: "E", disabled: !has || rm?.folder === "archive" }),
    iconBtn("trash-2", t("trash_it"), () => moveMail([mv], "trash"), { key: "#", disabled: !has || inTrash }),
    iconBtn("folder-input", t("move_to"), (e) => moveMenu(e.currentTarget, [mv]), { key: "V", disabled: !has || !rm }),
    iconBtn(r && r.unread ? "mail-open" : "mail", r && r.unread ? t("read") : t("unread"), toggleUnread, { key: "U", disabled: !has, cls: r && r.unread ? "" : "unread-mark" }),
    iconBtn("star", r?.flagged ? t("unflag") : t("flag"), toggleFlag, { key: "S", disabled: !has, cls: r?.flagged ? "on fill" : "" }),
  );
}

// "Mark as unread" carries a dot on the envelope's corner; "Mark as read" has none. When the button turns from one
// into the other, the new button starts as the old one looked and the dot (and the cut round it) grows or shrinks
// away, with the envelope settling, instead of the toolbar swapping it in one frame (style.css, group C1).
function unreadState() {
  const b = $('#tools .icon-btn[data-key="U"]');
  return b ? { dot: b.classList.contains("unread-mark"), multi: S.multi.size > 1, id: S.focus || S.sel } : null;
}
function easeUnread(was) {
  const b = $('#tools .icon-btn[data-key="U"]');
  const now = b && b.classList.contains("unread-mark");
  // only the same mail (or the same selection) changing its mark: a new mail opening just shows its button
  if (!b || !was || was.dot === now || was.multi !== S.multi.size > 1 || (!was.multi && was.id !== (S.focus || S.sel))) return;
  b.classList.toggle("unread-mark", was.dot);
  void b.offsetWidth;
  b.classList.toggle("unread-mark", now);
  if (!REDUCED.matches) $(".i", b)?.animate([{ opacity: 0.4, transform: "scale(.86)" }, { opacity: 1, transform: "none" }], { duration: 200, easing: "cubic-bezier(.2, .8, .2, 1)" });
}

let threadSeq = 0;
async function openThread(id) {
  const seq = ++threadSeq;
  S.focus = id; S.sched = null;
  let th;
  try { th = await api("thread", { id }); } catch (e) { if (seq === threadSeq) { fail(e); showEmpty(); } return; }
  if (seq !== threadSeq) return;
  S.thread = th;
  hitScroll = S.query ? seq : 0;
  const doc = el("div", { class: "doc" }, el("h1", { class: "doc-subject", dir: "auto", html: hl(th.subject || t("no_subject")) }));
  // newest on top; the reply buttons sit right under the open message, older mail below
  const rows = [...th.rows].reverse();
  const openId = rows.some((r) => r.id === id) ? id : rows[0]?.id;
  const act = (ic, label, mode) => el("button", { class: "btn", onclick: () => openCompose({ mode, id: S.focus || id }), html: icon(ic, "small") + esc(label) });
  for (const r of rows) {
    doc.append(msgNode(r, r.id === openId));
    if (r.id === openId) doc.append(el("div", { class: "doc-acts" }, act("reply", t("reply"), "reply"), act("reply-all", t("replyall"), "replyall"), act("forward", t("forward"), "forward")));
  }
  swapPane(doc);
  $("#pane").scrollTop = 0;
  renderToolbar();
  const open = $(`.msg[data-id="${CSS.escape(id)}"]`, doc);
  if (open && openId !== rows[0].id) requestAnimationFrame(() => { $("#pane").scrollTop = Math.max(0, open.offsetTop - 70); });
}

// a draft waiting to go out: when, and what can still be done with it
let schedSeq = 0;
async function openScheduled(r) {
  const seq = ++schedSeq;
  threadSeq++;
  S.thread = null; S.focus = r.id; S.sched = r;
  const zone = TZ || SYS_TZ;
  const card = el("div", { class: "sched-card" + (r.sched_error ? " err" : "") },
    el("span", { class: "sched-ic", html: icon(r.sched_error ? "triangle-alert" : "calendar-clock") }),
    el("div", { class: "sched-text" },
      el("div", { class: "sched-when" }, t("sends_at", longTime(r.sched))),
      el("div", { class: "sched-sub" }, r.sched_error ? t("not_sent", tr(r.sched_error))
        : r.sched_retry ? t("sched_retry", tr(r.sched_note || ""), shortTime(r.sched_retry)) : zone.replace(/_/g, " ") + " · " + t("keep_open"))),
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
    const m = await api("message", { id: r.id });
    if (seq === schedSeq && body.isConnected) renderBody(body, m);
  } catch (e) { if (seq === schedSeq) body.replaceChildren(el("div", { class: "form" }, el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) }))); }
}

async function afterSchedule() {
  refreshCounts();
  if (["drafts", "scheduled"].includes(S.folder) || S.query) await loadList({ quiet: true });
}

async function dontSend(r) {
  if (!r) return;
  try { await api("unschedule", { id: r.id }); } catch (e) { return fail(e); }
  if (S.sched?.id === r.id || S.sel === r.id) { S.sel = null; showEmpty(); }
  toast(t("moved_to_drafts"), { action: { label: t("undo"), run: () => api("schedule", { id: r.id, at: r.sched }).then(afterSchedule).catch(fail) } });
  afterSchedule();
}

// the mail stays scheduled while it is changed: what is saved goes out at the time set
function editScheduled(r) {
  openCompose({ mode: "draft", id: r.id });
  toast(t("still_sched", longTime(r.sched)), { ms: 5000 });
}

async function sendNow(r) {
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
  // reply / reply all / forward sit on each open message's own header (the top right of the window stays free for
  // the window buttons on Windows); the keys R, A and F act on the message clicked last
  const acts = () => el("div", { class: "msg-acts" },
    iconBtn("reply", t("reply"), () => openCompose({ mode: "reply", id: r.id }), { key: "R" }),
    iconBtn("reply-all", t("replyall"), () => openCompose({ mode: "replyall", id: r.id }), { key: "A" }),
    iconBtn("forward", t("forward"), () => openCompose({ mode: "forward", id: r.id }), { key: "F" }));
  head.append(el("div", { class: "avatar" }, initials(r.from)), whoBox, el("div", { class: "msg-date", title: longTime(r.ts), html: expanded ? openDate(r.ts) : esc(shortTime(r.ts)) }));
  if (expanded) head.append(acts());
  node.append(head);
  head.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    if (node.classList.contains("collapsed")) {
      node.classList.remove("collapsed");
      whoBox.replaceChildren(whoBox.firstChild, toLine);
      head.querySelector(".msg-date").innerHTML = openDate(r.ts);
      head.append(acts());
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
  // read the moment it opens: the server marks it at once, even while a big mail is still coming in
  const wasUnread = r.unread;
  if (wasUnread) { r.unread = false; markRow(r.id, { unread: false }); if (S.focus === r.id) renderToolbar(); }
  const req = api("message", { id: r.id });
  if (wasUnread) setTimeout(refreshCounts, 150);
  let m;
  try { m = await req; }
  catch (e) {
    if (wasUnread) { r.unread = true; markRow(r.id, { unread: true }); refreshCounts(); if (S.focus === r.id) renderToolbar(); }
    body.replaceChildren(el("div", { class: "form" }, el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) }))); return;
  }
  if (wasUnread) refreshCounts();
  body.replaceChildren();
  node._msg = m;
  renderBody(body, m);
}

function renderBody(body, m) {
  body.replaceChildren();
  if (m.unsub) unsubLink(body.closest(".msg"), m);
  if (m.invite) body.append(inviteCard(m));
  // attachments sit right under the mail's header, above the text; an invitation's .ics is the card above
  const files = m.invite ? m.atts.filter((a) => !/\.ics$/i.test(a.name)) : m.atts;
  if (files.length) {
    const atts = el("div", { class: "atts" });
    for (const a of files) atts.append(attNode(a, m.id));
    body.append(atts);
    if (files.length > 1) {
      const all = el("button", { class: "link-btn atts-all", html: icon("download", "small") + `<span>${esc(t("save_all"))}</span>`, onclick: async () => {
        all.disabled = true;
        try {
          const r = await api("save_all", { id: m.id });
          toast(t("saved_n", r.count), { action: { label: t("show"), run: () => api("reveal", { path: r.path }).catch(fail) }, ms: 5000 });
        } catch (e) { fail(e); } finally { all.disabled = false; }
      } });
      body.append(all);
    }
  }
  // images from the web load unless Settings > Privacy says no (then a sender can be trusted for good);
  // mail in Junk never loads them by itself
  const junk = m.id.slice(0, m.id.lastIndexOf(":")) === "junk", addr = (m.from?.addr || "").toLowerCase();
  const remote = m.remote && (S.showImages.has(m.id) || (!junk && (PREFS.remote_images !== false || imgSenders().includes(addr))));
  if (m.remote && !remote) {
    body.append(el("div", { class: "imgs-bar" }, el("span", { html: icon("image", "small") }), el("span", {}, t("images_hidden")), el("span", { class: "grow" }),
      el("button", { class: "link-btn", onclick: () => { S.showImages.add(m.id); renderBody(body, m); } }, t("show_images")),
      junk || !addr ? null : el("button", { class: "link-btn", onclick: () => {
        savePref({ img_senders: [...imgSenders(), addr].slice(-2000) });
        rerenderBodies();
      } }, t("img_always"))));
  }
  const frame = mailFrame(m.html, { plain: m.plain, remote, quote: true });
  body.append(frame.node);
}

const imgSenders = () => (Array.isArray(PREFS.img_senders) ? PREFS.img_senders : []);
// the open mails again, after the images setting changed
function rerenderBodies() {
  for (const n of $$(".msg")) { const b = n.querySelector(".msg-body"); if (n._msg && b) renderBody(b, n._msg); }
}

// a mailing list's way out, beside the sender's address, as in Gmail and Apple Mail
function unsubLink(node, m) {
  const from = node?.querySelector(".msg-from");
  if (!from || from.querySelector(".unsub")) return;
  const name = nameOf(m.from);
  from.append(el("button", { class: "unsub", onclick: (e) => {
    e.stopPropagation();
    const box = sheet(el("div", {},
      el("h2", {}, t("unsub_title", name)),
      el("p", { class: "sheet-sub" }, t(m.unsub.one_click ? "unsub_one" : m.unsub.url ? "unsub_web" : "unsub_mail")),
      el("div", { class: "sheet-acts" },
        el("button", { class: "btn", onclick: closeLayer }, t("cancel")),
        el("button", { class: "btn primary", onclick: async (ev) => {
          ev.target.disabled = true;
          try {
            const r = await api("unsubscribe", { id: m.id });
            closeLayer();
            if (r.done) { toast(t("unsub_done", name)); from.querySelector(".unsub")?.remove(); }
            else if (r.mailto) openCompose({ mode: "new", to: [{ name: "", addr: r.mailto.toLowerCase() }], subject: r.subject });
          } catch (err) { ev.target.disabled = false; fail(err); }
        } }, t("unsub")))));
    box.querySelector(".btn.primary").focus();
  } }, t("unsub")));
}

// a meeting invitation: when and where, and a way into the system's calendar. A reply to one says who
// answered and how; a new time proposed says the time. Only an invitation still to come can be added.
// an all-day event's days are the invitation's own dates, the same wherever the reader is
const dayTs = (s) => Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)) / 1000;
function fmtUTC(ts, opts) {
  const key = "utc" + JSON.stringify(opts);
  let f = FMT.get(key);
  if (!f) {
    try { f = new Intl.DateTimeFormat(LOCALE, { ...opts, timeZone: "UTC" }); } catch { f = new Intl.DateTimeFormat(undefined, { ...opts, timeZone: "UTC" }); }
    FMT.set(key, f);
  }
  return f.format(new Date(ts * 1000));
}
// seconds the reader's clock is ahead of UTC at ts
function myOffset(ts) {
  const p = zparts(ts * 1000);
  return (Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi) - Math.floor(ts / 60) * 60000) / 1000;
}
const INV_DAY = { weekday: "short", month: "short", day: "numeric" };
// "Wed 25 Nov · 17:00–18:00 · 10:00–11:00 Amsterdam": the reader's time first, the event's own when it differs
function inviteWhen(v) {
  if (v.all_day) {
    const a = fmtUTC(dayTs(v.day0), INV_DAY);
    return (v.day1 && v.day1 !== v.day0 ? a + "–" + fmtUTC(dayTs(v.day1), INV_DAY) : a) + " · " + t("all_day");
  }
  const same = v.end && dayKey(v.end * 1000) === dayKey(v.start * 1000);
  let s = fmt(v.start, INV_DAY) + " · " + fmt(v.start, HM) + (v.end ? "–" + (same ? fmt(v.end, HM) : fmt(v.end, INV_DAY) + " " + fmt(v.end, HM)) : "");
  const z = v.zone;
  if (z?.unknown) s += " · " + t("inv_tz_unknown");
  else if (z && z.offset != null && z.offset !== myOffset(v.start))
    s += " · " + fmtUTC(v.start + z.offset, HM) + (v.end && same ? "–" + fmtUTC(v.end + z.offset, HM) : "") + " " + z.label;
  return s;
}
// "Every Monday · until 30 Dec", from the invitation's RRULE
const WD = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"];
function weekdayName(code) {
  const f = new Intl.DateTimeFormat(LOCALE, { weekday: LANG.startsWith("zh") ? "short" : "long", timeZone: "UTC" });
  return f.format(new Date(Date.UTC(2024, 0, 1 + WD.indexOf(code))));       // 1 Jan 2024 was a Monday
}
function listOf(xs) {
  try { return new Intl.ListFormat(LOCALE, { type: "conjunction" }).format(xs); } catch { return xs.join(", "); }
}
function repeatText(v) {
  const r = v.repeat;
  if (!r) return "";
  const n = r.interval || 1;
  const local = v.all_day ? dayTs(v.day0) : v.start + (v.zone?.offset ?? myOffset(v.start));   // the event's own day
  const startWd = WD[(new Date(local * 1000).getUTCDay() + 6) % 7];
  let s;
  if (r.freq === "DAILY") s = n > 1 ? t("rr_days", n) : t("rr_daily");
  else if (r.freq === "WEEKLY") {
    const days = (r.byday.length ? r.byday.map((d) => d.slice(-2)) : [startWd]);
    const sorted = WD.filter((d) => days.includes(d));
    if (n === 1 && sorted.join() === "MO,TU,WE,TH,FR") s = t("rr_weekdays");
    else s = n > 1 ? t("rr_weeks", n, listOf(sorted.map(weekdayName))) : t("rr_weekly", listOf(sorted.map(weekdayName)));
  } else if (r.freq === "MONTHLY") {
    const nth = r.byday.map((d) => d.match(/^([+-]?\d)(MO|TU|WE|TH|FR|SA|SU)$/)).find(Boolean);
    if (n > 1) s = t("rr_months", n);
    else if (nth) s = t("rr_monthly_nth", +nth[1] < 0 ? t("rr_last") : (t("rr_ord").split(",")[+nth[1] - 1] || nth[1]), weekdayName(nth[2]));
    else s = t("rr_monthly_day", r.bymonthday[0] || new Date(local * 1000).getUTCDate());
  } else s = n > 1 ? t("rr_years", n) : t("rr_yearly");
  if (r.until_day) s += " · " + t("rr_until", fmtUTC(dayTs(r.until_day), { month: "short", day: "numeric", year: "numeric" }));
  else if (r.until) s += " · " + t("rr_until", fmt(r.until, { month: "short", day: "numeric", year: "numeric" }));
  else if (r.count) s += " · " + t("rr_count", r.count);
  return s;
}
const REPLY_SAID = { ACCEPTED: "inv_r_accepted", DECLINED: "inv_r_declined", TENTATIVE: "inv_r_tentative", DELEGATED: "inv_r_delegated" };
const invWho = (x) => (x && (x.addr === S.boot?.user ? t("me") : x.name || x.addr)) || "";
function inviteCard(m) {
  const v = m.invite;
  const leafTs = v.all_day ? dayTs(v.day0) : v.start;
  const leafFmt = v.all_day ? fmtUTC : fmt;
  const past = (v.end || v.start) * 1000 < Date.now();
  const kind = v.method === "REPLY" ? "reply" : v.method === "COUNTER" ? "counter" : ["REFRESH", "DECLINECOUNTER"].includes(v.method) ? "note" : "invite";
  const lines = [];
  if (kind === "reply") {
    lines.push(el("b", {}, t(REPLY_SAID[v.reply?.status] || "inv_r_replied", invWho(v.reply))),
      el("span", {}, v.title || t("invite")), el("span", {}, inviteWhen(v)));
    if (v.reply?.comment) lines.push(el("span", { class: "inv-note" }, "“" + v.reply.comment + "”"));
  } else if (kind === "counter") {
    lines.push(el("b", {}, t("inv_counter", invWho(v.reply))), el("span", {}, v.title || t("invite")),
      el("span", {}, t("inv_new_time", inviteWhen(v))));
  } else {
    const tag = v.updated ? t("inv_updated") : v.occurrence && !v.cancelled ? t("inv_one") : "";
    lines.push(el("b", {}, v.title || t("invite"), tag ? el("span", { class: "inv-tag" }, tag) : null),
      el("span", {}, (v.cancelled ? t("inv_cancelled") + " · " : "") + inviteWhen(v)));
    const rep = repeatText(v);
    if (rep) lines.push(el("span", {}, rep));
    if (v.was && v.was.start) lines.push(el("span", { class: "inv-was" }, t("inv_was", wasWhen(v.was))));
    if (v.where) lines.push(el("span", {}, v.where));
    if (v.was && "where" in v.was && v.was.where !== v.where) lines.push(el("span", { class: "inv-was" }, t("inv_was", v.was.where || "—")));
    if (v.organizer) lines.push(el("span", { class: "inv-org" }, t("inv_from", v.organizer)));
    const people = invitePeople(v);
    if (people) lines.push(people);
    if (v.about) lines.push(inviteAbout(v.about));
  }
  // Add for an invitation still to come; a cancelled one leaves the calendar the same way
  const canAdd = kind === "invite" && !past && ["REQUEST", "PUBLISH", "ADD", "CANCEL"].includes(v.method);
  const soon = v.start * 1000 - Date.now() < 15 * 60e3;
  const side = el("div", { class: "inv-side" },
    v.join && kind === "invite" && !past && !v.cancelled ? el("button", { class: "btn" + (soon ? " primary" : ""), html: icon("video", "small") + `<span>${esc(t("inv_join"))}</span>`, onclick: async (e) => {
      e.currentTarget.disabled = true;
      const b = e.currentTarget;
      try { await api("join", { id: m.id }); } catch (err) { fail(err); } finally { b.disabled = false; }
    } }) : null,
    canAdd ? el("button", { class: "btn", onclick: async (e) => {
      e.target.disabled = true;
      try { await api("open_invite", { id: m.id }); } catch (err) { fail(err); } finally { e.target.disabled = false; }
    } }, t(v.cancelled ? "inv_remove_cal" : "add_cal")) : null);
  const card = el("div", { class: "invite" + (v.cancelled ? " cancelled" : "") + (past ? " past" : "") + (kind !== "invite" ? " inv-" + kind : "") },
    el("div", { class: "inv-day" }, el("span", {}, leafFmt(leafTs, { month: "short" })), el("b", {}, leafFmt(leafTs, { day: "numeric" }).replace(/\D+$/, ""))),
    el("div", { class: "inv-text" }, lines),
    side.childElementCount ? side : el("span"));
  if (kind === "invite" && v.can_answer && !past) card.append(rsvpRow(m, card));
  return card;
}
function wasWhen(w) {
  if (w.all_day) return fmt(w.start, INV_DAY);
  const same = w.end && dayKey(w.end * 1000) === dayKey(w.start * 1000);
  return fmt(w.start, INV_DAY) + " · " + fmt(w.start, HM) + (w.end && same ? "–" + fmt(w.end, HM) : "");
}
// "You, Li Ming, Gerrick Ong +3": opens into everyone with their answer
const PART = { ACCEPTED: ["check", "att_yes"], DECLINED: ["x", "att_no"], TENTATIVE: ["circle-help", "att_maybe"] };
function invitePeople(v) {
  const me = (S.boot?.user || "").toLowerCase();
  const all = (v.attendees || []).filter((a) => a.addr !== v.organizer_addr);
  if (!all.length || (all.length === 1 && all[0].addr === me)) return null;
  const sorted = [...all.filter((a) => a.addr === me), ...all.filter((a) => a.addr !== me)];
  const name = (a) => (a.addr === me ? t("inv_you") : a.name || a.addr);
  const shown = sorted.slice(0, 3).map(name).join(", ") + (sorted.length > 3 ? " " + t("inv_more_n", sorted.length - 3) : "");
  const list = el("div", { class: "inv-list" });
  // drawn when it opens: the reader's own answer from here counts too
  const fill = () => list.replaceChildren(...sorted.map((a) => {
    const st = a.addr === me && v.answer ? v.answer : a.status;
    const [ic, word] = PART[st] || [null, "att_none"];
    return el("div", { class: "inv-person" + (st === "ACCEPTED" ? " yes" : "") },
      el("span", { class: "inv-pmark", html: ic ? icon(ic, "small") : "" }), el("span", { class: "inv-pname" }, name(a)),
      el("span", { class: "inv-pst" }, t(word)));
  }));
  const wrap = el("div", { class: "inv-people" });
  const btn = el("button", { class: "inv-ptoggle", "aria-expanded": "false", html: `<span>${esc(shown)}</span>` + icon("chevron-down", "small"), onclick: () => {
    const open = !wrap.classList.contains("open");
    if (open) fill();
    wrap.classList.toggle("open", open);
    btn.setAttribute("aria-expanded", String(open));
  } });
  wrap.append(btn, list);
  return wrap;
}
// the first lines of the description; the rest on a click
function inviteAbout(text) {
  const box = el("div", { class: "inv-about" }, el("div", { class: "inv-about-t" }, text));
  if (text.length > 140 || text.split("\n").length > 2) {
    const more = el("button", { class: "link-btn inv-more", onclick: () => {
      const open = box.classList.toggle("open");
      more.textContent = t(open ? "inv_less" : "inv_more");
    } }, t("inv_more"));
    box.append(more);
  }
  return box;
}
// Accept / Maybe / Decline. The chosen button fills in and spins while the reply waits out the undo pause and
// goes; then the buttons fold into one line ("You accepted · Change") in the same place, so nothing below moves.
// Nothing says "You accepted" before the server took the reply; a reply that fails brings the buttons back.
const RSVP = [["ACCEPTED", "check", "rsvp_accept", "accept"], ["TENTATIVE", "circle-help", "rsvp_maybe", "maybe"], ["DECLINED", "x", "rsvp_decline", "decline"]];
function rsvpRow(m, card) {
  const v = m.invite;
  const row = el("div", { class: "inv-rsvp" });
  const note = el("input", { class: "inv-note-in", type: "text", maxlength: "300", placeholder: t("rsvp_note"), "aria-label": t("rsvp_note") });
  const btns = el("div", { class: "inv-btns" });
  const done = el("div", { class: "inv-done", "aria-live": "polite" });
  let busy = false;
  const mark = (ans) => {
    card.classList.remove("ans-accepted", "ans-tentative", "ans-declined");
    if (ans) card.classList.add("ans-" + ans.toLowerCase());
  };
  const show = (ans, still) => {
    const [, ic] = RSVP.find((x) => x[0] === ans);
    done.replaceChildren(el("span", { class: "inv-mark " + ans.toLowerCase() + (ans !== "TENTATIVE" ? " draw" : ""), html: icon(ic) }),
      el("span", { class: "inv-said" }, t("rsvp_did_" + ans.toLowerCase())),
      el("button", { class: "link-btn inv-change", onclick: change }, t("rsvp_change")));
    if (still) row.classList.add("still");
    row.classList.add("done");
    btns.inert = true;
    done.inert = false;
    mark(ans);
    if (still) requestAnimationFrame(() => requestAnimationFrame(() => row.classList.remove("still")));
  };
  const change = () => {
    row.classList.remove("done");
    btns.inert = false;
    done.inert = true;
    mark(null);
    btns.querySelector(".rsvp-btn")?.focus({ preventScroll: true });
  };
  const settle = (b, html, shake) => {
    busy = false;
    btns.classList.remove("busy");
    b.classList.remove("chosen", "press");
    b.innerHTML = html;
    if (shake && !REDUCED.matches) {
      btns.classList.remove("shake");
      void btns.offsetWidth;
      btns.classList.add("shake");
    }
  };
  const answer = async (ans, b) => {
    if (busy) return;
    busy = true;
    const html = b.innerHTML;
    btns.classList.remove("shake");
    btns.classList.add("busy");
    b.classList.add("chosen", "press");
    b.querySelector(".i").outerHTML = icon("loader-circle", "small spin");
    let r;
    try { r = await api("rsvp", { id: m.id, answer: ans, note: note.value.trim(), subject: t("rsvp_subj_" + ans.toLowerCase()) }); }
    catch (e) { settle(b, html, true); return fail(e); }
    const wait = undoSeconds() * 1000;
    let undone = false;
    const tt = toast(t("rsvp_sending"), wait ? { action: { label: t("undo"), run: () => { undone = true; } }, ms: 0, bar: wait } : { ms: 0 });
    for (let k = 0; k < wait / 100 && !undone; k++) await sleep(100);
    if (undone) {
      tt.close();
      settle(b, html, false);
      api("delete_draft", { id: r.draft }).catch(fail);
      return;
    }
    tt.node.querySelector(".toast-act")?.remove();
    tt.node.querySelector(".toast-bar")?.remove();
    try {
      const res = await api("rsvp_send", { id: m.id, draft: r.draft, answer: ans });
      tt.close();
      const after = res.problems_after_sending || [];
      if (after.length) toast(after.map(tr).join(" "), { error: true, ms: 12000 });
      else toast(t("rsvp_sent"));
      settle(b, html, false);
      v.answer = ans;
      note.value = "";
      show(ans, false);
      if (ans !== "DECLINED") api("open_invite", { id: m.id }).catch(fail);     // into the calendar with the same click
      refreshCounts();
      if (["sent", "drafts"].includes(S.folder)) loadList({ quiet: true });
    } catch (e) {
      tt.close();
      settle(b, html, true);
      fail(e);
    }
  };
  for (const [ans, ic, label, cls] of RSVP) {
    const b = el("button", { class: "btn rsvp-btn " + cls, html: icon(ic, "small") + `<span>${esc(t(label))}</span>` });
    b.addEventListener("click", () => answer(ans, b));
    btns.append(b);
  }
  btns.append(note);
  done.inert = true;
  row.append(btns, done);
  if (v.answer) show(v.answer, true);
  return row;
}

function attNode(a, id) {
  // one click at a time: a second one while the first is still on its way only opened a second copy
  const open = async () => {
    if (node.classList.contains("busy")) return;
    node.classList.add("busy");
    try {
      const r = await api("attachment", { id, i: a.i, name: a.name, action: "open" });
      // a program would run if opened: it is never opened, its folder is offered instead
      if (r.program) toast(t("att_program", r.name), { error: true, ms: 10000, action: { label: t("show_in_folder"), run: () => api("attachment", { id, i: a.i, name: a.name, action: "show" }).catch(fail) } });
    } catch (e) { fail(e); } finally { node.classList.remove("busy"); }
  };
  const save = async (e) => {
    e.stopPropagation();
    if (node.classList.contains("busy")) return;
    node.classList.add("busy");
    try {
      const r = await api("attachment", { id, i: a.i, name: a.name, action: "save" });
      toast(t("saved_to") + " · " + r.name, { action: { label: t("show"), run: () => api("reveal", { path: r.path }).catch(fail) }, ms: 5000 });
    } catch (err) { fail(err); } finally { node.classList.remove("busy"); }
  };
  let dragged = false;
  const node = el("div", { class: "att" + (a.program ? " att-program" : ""), role: "button", tabindex: "0", title: a.name,
    onclick: () => { if (dragged) { dragged = false; return; } open(); }, onkeydown: (e) => { if (e.key === "Enter" && !K.isIME(e)) open(); } },
    el("div", fileTile(a.name)),
    el("div", { class: "att-text" }, el("div", { class: "att-name", html: hl(a.name) }),
      a.program ? el("div", { class: "att-size att-warn", html: icon("triangle-alert", "small") + esc(t("program_file") + " · " + size(a.size)) })
        : el("div", { class: "att-size" }, size(a.size))),
    el("div", { class: "att-acts" }, iconBtn("download", t("download"), save)));
  // drag the card out of the window (Mac app): past a few pixels the app hands Finder the file itself
  if (MAC && S.boot.window) {
    node.addEventListener("mousedown", (e) => {
      if (e.button !== 0 || e.target.closest(".att-acts")) return;
      e.preventDefault();                 // no text selection, no drag of the card's picture
      const x0 = e.clientX, y0 = e.clientY;
      const move = (ev) => {
        if (Math.hypot(ev.clientX - x0, ev.clientY - y0) < 5) return;
        stop();
        dragged = true;
        node.classList.add("busy");
        api("attachment", { id, i: a.i, name: a.name, action: "drag" })
          .then((r) => { if (!r.dragging) dragged = false; }, fail)
          .finally(() => node.classList.toggle("busy", false));
      };
      const stop = () => { removeEventListener("mousemove", move); removeEventListener("mouseup", stop); };
      addEventListener("mousemove", move); addEventListener("mouseup", stop);
    });
  }
  return node;
}

// ---------------------------------------------------------------- mail frames

const FRAME_FONT = getComputedStyle(document.documentElement).getPropertyValue("--font");
const QUOTE_SEL = ".gmail_quote, .gmail_extra, #divRplyFwdMsg, blockquote[type=cite], .rd-quote, #appendonsend, .yahoo_quoted, " +
  "#mail-editor-reference-message-container, .moz-cite-prefix, #isForwardContent, #origbody, .protonmail_quote, div[id^=reply-intro]";
// Quoted history in a mail without known quote markup, line by line (ragdoll.py quote_line has the same rules).
// A separator line or "On ... wrote:" always starts it. A "From:" line starts it only as the head of a real header
// block: a separator line just above it, or the next lines carry Sent:, or Subject: with Date:/To:/Cc:, or Date: and
// To: under a From: with an address. A mail's own "From: Shanghai / To: Singapore" is text, not history.
const QUOTE_SEP = /^\s*(-{2,}\s*(原始邮件|原始郵件|Original Message|Forwarded message|转发邮件|轉寄郵件|Ursprüngliche Nachricht|Message d'origine|Mensaje original)|On .{5,160} wrote:|在\s?.{3,80}写道[:：])/i;
const QUOTE_FROM = /^\s*\*?(From|发件人|寄件者|寄件人|Von|De|Từ|差出人|보낸 사람)\*?\s*[:：]/i;
const QUOTE_HEAD = /^\s*\*?(?:(?<sent>Sent|发送时间|發送時間|寄件日期|Gesendet|Envoyé|Enviado|送信日時|보낸 날짜|Gửi lúc)|(?<date>Date|日期|时间|時間|Datum|Fecha|Ngày|日付|날짜)|(?<to>To|收件人|收件者|An|À|Para|Đến|宛先|받는 사람)|(?<cc>Cc|抄送|副本|Kopie|Copie)|(?<subject>Subject|主题|主題|主旨|Betreff|Objet|Asunto|Chủ đề|件名|제목))\*?\s*[:：]/i;
const QUOTE_LINE = /^\s*([-_=*]\s*){5,}$/;
function quoteLine(lines) {
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (QUOTE_SEP.test(line)) return i;
    if (!QUOTE_FROM.test(line)) continue;
    let above = -1;
    for (let k = i - 1; k >= 0 && k >= i - 2; k--) if (lines[k].trim()) { above = k; break; }
    if (above >= 0 && QUOTE_LINE.test(lines[above])) return above;
    const keys = new Set();
    for (const l of lines.slice(i + 1, i + 8)) {
      if (!l.trim() || QUOTE_FROM.test(l)) break;     // the block ends at an empty line or the next block
      const m = l.match(QUOTE_HEAD);
      if (m) keys.add(Object.keys(m.groups).find((g) => m.groups[g] !== undefined));
    }
    if (keys.has("sent") || (keys.has("subject") && (keys.has("date") || keys.has("to") || keys.has("cc"))) ||
        (keys.has("date") && keys.has("to") && line.includes("@"))) return i;
  }
  return -1;
}
// a mail's text as the lines a reader sees, each with the first node on it: a block or a <br> ends a line,
// an <hr> is a separator line; source line breaks count only where the text keeps them (plain text, <pre>)
const LINE_BLOCK = /^(P|DIV|TR|LI|UL|OL|DL|DT|DD|TABLE|TBODY|THEAD|H[1-6]|BLOCKQUOTE|SECTION|ARTICLE|HEADER|FOOTER|PRE|CENTER)$/;
function textLines(root) {
  const lines = [{ text: "", node: null }];
  const cut = () => { const l = lines[lines.length - 1]; if (l.text || l.node) lines.push({ text: "", node: null }); };
  const add = (text, node) => { const l = lines[lines.length - 1]; if (!l.node && text.trim()) l.node = node; l.text += text; };
  const walk = (n, pre) => {
    for (let c = n.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) {
        if (!pre) { add(c.nodeValue.replace(/\s+/g, " "), c); continue; }
        c.nodeValue.split("\n").forEach((part, k) => { if (k) cut(); add(part, c); });
      } else if (c.nodeType === 1) {
        const tag = c.tagName;
        if (tag === "BR") { cut(); continue; }
        if (tag === "HR") { cut(); add("-----", c); cut(); continue; }
        if (/^(STYLE|SCRIPT|TITLE|HEAD|TEMPLATE)$/.test(tag)) continue;
        const block = LINE_BLOCK.test(tag);
        if (block) cut();
        walk(c, pre || tag === "PRE" || c.classList.contains("rd-plain"));
        if (block) cut();
        else if (tag === "TD" || tag === "TH") add(" ", null);
      }
    }
  };
  walk(root, false);
  return lines;
}
const frames = new Set();
// WebKit (the Mac app) runs no listener inside a sandboxed frame that lacks allow-scripts, not even one this page
// attaches: a click on a link or a picture did nothing there. The mail's own scripts stay off either way: the
// backend strips them (page_html) and the frame's policy has script-src 'none'.
const WEBKIT = /AppleWebKit/.test(navigator.userAgent) && !/Chrome|Chromium|Edg\//.test(navigator.userAgent);
const SANDBOX = "allow-same-origin allow-popups allow-popups-to-escape-sandbox" + (WEBKIT ? " allow-scripts" : "");

// Chinese mail often names Windows fonts (宋体, 等线, 微软雅黑...). A Mac has none of them, and the text fell back to
// the browser's serif. These names are read as the system's Chinese sans font instead (PingFang on a Mac, YaHei on
// Windows): the same shapes as the rest of the app, and no thin serif in long Chinese text.
const CJK_FONTS = ["宋体", "SimSun", "新宋体", "NSimSun", "等线", "DengXian", "等线 Light", "DengXian Light", "微软雅黑", "Microsoft YaHei",
  "黑体", "SimHei", "仿宋", "FangSong", "仿宋_GB2312", "FangSong_GB2312"];
const CJK_FACES = CJK_FONTS.map((n) =>
  `@font-face{font-family:"${n}";font-weight:100 500;src:local("PingFangSC-Regular"),local("PingFang SC Regular"),local("Microsoft YaHei"),local("Noto Sans CJK SC Regular")}` +
  `@font-face{font-family:"${n}";font-weight:600 900;src:local("PingFangSC-Semibold"),local("PingFang SC Semibold"),local("Microsoft YaHei Bold"),local("Noto Sans CJK SC Bold")}`).join("");
// long lines are hard to follow: the text column stops at about 44 characters' width (.rd-root), unless the mail
// needs more room (a wide table or picture, a layout wider than that); then it gets the reader's whole width
function fitColumn(d) {
  const root = d.querySelector(".rd-root");
  if (!root || root.classList.contains("rd-wide")) return;
  const cap = root.clientWidth;
  const cols = (tb) => Math.max(0, ...[...tb.rows].slice(0, 8).map((r) => r.cells.length));
  if (root.scrollWidth > cap + 1 ||
      [...root.querySelectorAll("table")].some((tb) => tb.offsetWidth >= cap - 1 && cols(tb) > 3) ||
      [...d.images].some((i) => i.naturalWidth > cap && i.offsetWidth >= cap - 1)) root.classList.add("rd-wide");
}

function frameDoc(html, { plain, remote, dark }) {
  const csp = `default-src 'none'; script-src 'none'; object-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:${remote ? " https: http:" : ""}; media-src data:`;
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><style id="rd-style">${frameCss({ plain, dark })}</style></head><body><div class="rd-root">${html}</div></body></html>`;
}
// the frame's own look; a new theme changes it in place (restyleFrames), without loading the mail again
function frameCss({ plain, dark }) {
  const fg = dark ? "#e6e6e6" : "#1d1d1f";
  let css = CJK_FACES + `:root{color-scheme:${dark ? "dark" : "light"}}html,body{background:transparent}body{margin:0;font:${textSize()}px/1.6 ${FRAME_FONT};color:${fg};overflow-wrap:anywhere;overflow-x:auto;overflow-y:hidden}
.rd-root{max-width:44em}.rd-root.rd-wide{max-width:none}p,li{text-wrap:pretty}
img{max-width:100%!important;height:auto}table{max-width:100%}pre{white-space:pre-wrap}a{color:${dark ? "#8fb8ff" : "#1a5fb4"}}
blockquote{margin:0 0 0 4px;padding-left:10px;border-left:2px solid ${dark ? "#444" : "#ddd"}}
.rd-plain{white-space:pre-wrap;font-size:${textSize()}px}.rd-quote{color:${dark ? "#9a9a9a" : "#6e6e73"};margin-top:14px;padding-left:10px;border-left:2px solid ${dark ? "#444" : "#ddd"}}`;
  if (dark && !plain) {
    // #191919 is the reader's dark background and what #e6e6e6 turns into, so the space beside the capped column matches
    css += `html{background:#191919!important}body{background:transparent!important}.rd-root{background:#e6e6e6;color:#1d1d1f;filter:invert(1) hue-rotate(180deg);padding:1px 0}
.rd-root img,.rd-root video,.rd-root picture,.rd-root [background],.rd-root [style*="url("]{filter:invert(1) hue-rotate(180deg)}.rd-root a{color:#1a5fb4}`;
  }
  return css + hitCss(dark, plain);
}

// a searched word in a mail: a soft amber behind the text. A dark HTML mail is shown inverted (.rd-root's filter),
// so there the light amber is given and the filter turns it into the dark one.
const hitCss = (dark, plain) => `mark.rd-hit{color:inherit;border-radius:3px;padding:0 1px;margin:0 -1px;-webkit-box-decoration-break:clone;box-decoration-break:clone;` +
  `background:${dark && plain ? "rgba(240,190,70,.30)" : "rgba(250,204,80,.42)"}}`;

// a picture worth enlarging: not an icon, a spacer or a tracking pixel
const bigImg = (img) => img.naturalWidth >= 48 && img.naturalHeight >= 32;
// Mail often gives a picture a fixed height (width="900" height="500", or a style in inches); when the reader is
// narrower, max-width shrinks only the width and the picture is squashed. Let the height follow the width again.
function shapeImg(img) {
  if (!img.complete || !bigImg(img)) return;
  img.style.cursor = img.closest("a[href]") ? "" : "zoom-in";
  const w = img.clientWidth, h = img.clientHeight;
  if (!w || !h) return;
  const want = img.naturalWidth / img.naturalHeight;
  if (Math.abs(w / h - want) / want > 0.03) img.style.setProperty("height", "auto", "important");
}
function shapeImgs(d) { for (const img of d.images) shapeImg(img); }
// Mail often sets its own text very small (8pt notes, 7pt tables). Nothing in a mail is shown smaller than this:
// 12px, or the reader's own text size when that is set smaller. Text under 6px is left alone: mail hides lines that way.
function minText(d) {
  const min = Math.min(12, textSize()), seen = new Set(), view = d.defaultView;
  if (!d.body || !view) return;
  const tw = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    const e = n.parentElement;
    if (!e || seen.has(e) || !n.nodeValue.trim()) continue;
    seen.add(e);
    if (e.closest("sub,sup")) continue;
    const cs = view.getComputedStyle(e), px = parseFloat(cs.fontSize);
    if (!(px >= 6 && px < min)) continue;
    e.style.setProperty("font-size", min + "px", "important");
    // a line height set for the small text would now cut the larger text
    if (parseFloat(cs.lineHeight) < min * 1.25) e.style.setProperty("line-height", "1.4", "important");
  }
}
// a picture at full size over the app: click or Esc closes it; a picture larger than the window opens fitted,
// a click on it shows it at its real size (scroll to look around)
function viewImage(src) {
  if (!src) return;
  const img = el("img", { src, alt: "" });
  const born = Date.now();
  const box = el("div", { class: "img-view", onclick: (e) => {
    if (Date.now() - born < 350) return; // the release of the press that opened it
    if (e.target === img && (img.naturalWidth > innerWidth - 48 || img.naturalHeight > innerHeight - 48)) box.classList.toggle("full");
    else closeLayer();
  } }, img);
  const sync = () => { if (img.naturalWidth <= innerWidth - 48 && img.naturalHeight <= innerHeight - 48) img.style.cursor = "zoom-out"; };
  if (img.complete) sync(); else img.addEventListener("load", sync);
  closeLayer();
  $("#layer").append(box);
}
function mailFrame(html, { plain = false, remote = false, quote = false, sig = false } = {}) {
  const wrap = el("div");
  const frame = el("iframe", { class: "frame" + (sig ? " sig-frame" : ""), sandbox: SANDBOX, referrerpolicy: "no-referrer", title: "mail" });
  wrap.append(frame);
  const st = { html, plain, remote, quote, frame, wrap, hidden: [], toggle: null };
  frames.add(st);
  const fit = () => {
    const d = frame.contentDocument;
    if (!d || !d.documentElement) return;
    if (!d.body) return;
    // the body's own height: the document's grows with the frame and would never shrink
    const root = d.querySelector(".rd-root") || d.body, view = d.defaultView;
    // a wide mail scrolls sideways: its scrollbar (shown always on Windows, and on a Mac with a mouse) takes room
    // at the bottom, so the frame is that much taller and the last line is not under it
    const bar = view ? Math.max(0, view.innerHeight - d.documentElement.clientHeight, d.body.offsetHeight - d.body.clientHeight) : 0;
    const h = Math.ceil(Math.max(d.body.scrollHeight, root.getBoundingClientRect().bottom + (view?.scrollY || 0)) + bar);
    if (frame.style.height !== h + "px") frame.style.height = h + "px";
  };
  st.fit = fit;
  frame.addEventListener("load", () => {
    const d = frame.contentDocument;
    if (!d) return;
    minText(d);
    if (quote) collapseQuote(st);
    if (quote) markFrame(st);
    fitColumn(d);
    fit();
    if (quote) scrollToHit(st);
    // the frame's own observer: it goes away with the frame; one fit per frame at most
    try {
      let q = 0;
      const ro = new d.defaultView.ResizeObserver(() => {
        if (!frame.isConnected) { ro.disconnect(); return; }
        if (!q) q = requestAnimationFrame(() => { q = 0; shapeImgs(d); fitColumn(d); fit(); });
      });
      ro.observe(d.body);
    } catch { /* old engine */ }
    for (const img of d.images) img.addEventListener("load", () => { shapeImg(img); fitColumn(d); fit(); });
    shapeImgs(d);
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
    // keys for reading stay in the mail (select its text, scroll it); the app's own keys still work from here
    d.addEventListener("keydown", (e) => {
      const k = frameKey(e);
      if (k === "keep") return;
      if (k) { e.preventDefault(); scrollReader(frame, k); return; }
      onKey(e);
    });
    const linkOf = (e) => {
      const a = e.target.closest?.("a[href]"), href = a?.getAttribute("href") || "";
      if (/^mailto:/i.test(href)) return { mail: decodeURIComponent(href.slice(7).split("?")[0]) };
      return /^https?:/i.test(href) ? { url: a.href } : null;
    };
    d.addEventListener("mouseover", (e) => { const l = linkOf(e); linkTip(frame, l ? l.url || l.mail : ""); });
    d.documentElement.addEventListener("mouseleave", () => linkTip(frame, ""));
    d.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      const l = linkOf(e), img = e.target.tagName === "IMG" && bigImg(e.target) ? e.target : null;
      const sel = String(d.getSelection?.() || "").trim();
      const items = [];
      if (l?.url) items.push({ icon: "external-link", label: t("open_link"), run: () => api("open_url", { url: l.url }).catch(fail) },
        { icon: "copy", label: t("copy_link"), run: () => copyText(l.url) });
      if (l?.mail) items.push({ icon: "square-pen", label: t("compose"), run: () => openCompose({ mode: "new", to: [{ name: "", addr: l.mail.split(",")[0].trim().toLowerCase() }] }) },
        { icon: "copy", label: t("copy_addr"), run: () => copyText(l.mail) });
      if (img) items.push({ icon: "image", label: t("open_picture"), run: () => viewImage(img.currentSrc || img.src) });
      if (sel) items.push({ icon: "copy", label: t("copy"), run: () => copyText(sel) });
      if (!items.length) return;
      const r = frame.getBoundingClientRect();
      linkTip(frame, "");
      menu(atPoint({ clientX: r.left + e.clientX, clientY: r.top + e.clientY }), items);
    });
    // a picture opens on the press: the release inside the frame does not always arrive, so a click would be lost
    d.addEventListener("mousedown", (e) => {
      const img = e.target;
      if (e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || img.tagName !== "IMG" || !bigImg(img) || img.closest("a[href]")) return;
      e.preventDefault();
      viewImage(img.currentSrc || img.src);
    });
  });
  setTimeout(fit, 400);
  frame.srcdoc = frameDoc(html, { plain, remote, dark: isDark() });
  const obs = new MutationObserver(() => { if (!wrap.isConnected) { frames.delete(st); obs.disconnect(); } });
  requestAnimationFrame(() => obs.observe(document.body, { childList: true, subtree: true }));
  return { node: wrap, frame, st };
}

// a key for reading pressed inside a mail: the reading pane scrolls (the frame itself is as tall as the mail)
function scrollReader(frame, k) {
  const pane = frame.closest(".pane") || $("#pane"), h = pane.clientHeight;
  const by = { down: 48, up: -48, page: h * 0.85, pageup: -h * 0.85 }[k];
  const how = REDUCED.matches || k === "down" || k === "up" ? "auto" : "smooth";
  if (by != null) pane.scrollBy({ top: by, behavior: how });
  else pane.scrollTo({ top: k === "home" ? 0 : pane.scrollHeight, behavior: how });
}

// the searched words in an open mail, marked for the eye only: replies and forwards are built from the server's
// copy, never from what is on screen. Only text is touched (a mark around a run of text), never the mail's tags.
function markFrame(st) {
  const d = st.frame.contentDocument;
  if (!d?.body) return;
  for (const m of d.querySelectorAll("mark.rd-hit")) { const p = m.parentNode; m.replaceWith(...m.childNodes); p.normalize(); }
  st.hits = [];
  const re = hitRe();
  if (!re) return;
  const root = d.querySelector(".rd-root") || d.body;
  const skip = "style,script,title,textarea,noscript,mark";
  const tw = d.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  for (let n = tw.nextNode(); n && nodes.length < 20000; n = tw.nextNode()) if (n.nodeValue.trim() && !n.parentElement?.closest(skip)) nodes.push(n);
  for (const n of nodes) {
    const parts = splitHits(n.nodeValue, re);
    if (parts.length < 2) continue;
    const frag = d.createDocumentFragment();
    for (const [a, m] of parts) {
      if (a) frag.append(a);
      if (!m) continue;
      const k = d.createElement("mark");
      k.className = "rd-hit"; k.textContent = m;
      frag.append(k); st.hits.push(k);
    }
    n.replaceWith(frag);
    if (st.hits.length > 2000) break;
  }
  // the only match is in the quoted older mail: the quote opens
  if (st.hits.length && st.toggle && !st.toggle.classList.contains("open") && st.hits.every((h) => st.hidden.some((x) => x.contains(h)))) st.toggle.click();
}
// the first match comes into view once, when a mail is opened from a search
let hitScroll = 0;
function scrollToHit(st) {
  if (!hitScroll || hitScroll !== threadSeq || !st.hits?.length || !st.frame.isConnected) return;
  hitScroll = 0;
  requestAnimationFrame(() => {
    const pane = st.frame.closest(".pane");
    const h = st.hits.find((x) => x.getClientRects().length);
    if (!pane || !h) return;
    const p = pane.getBoundingClientRect(), y = st.frame.getBoundingClientRect().top + h.getBoundingClientRect().top;
    if (y < p.top + 60 || y > p.bottom - 60) pane.scrollTo({ top: Math.max(0, pane.scrollTop + y - p.top - p.height / 3), behavior: REDUCED.matches ? "auto" : "smooth" });
  });
}
// the search changed: the marks in what is open follow it, and go when the search is cleared
function markOpen() {
  for (const st of frames) if (st.quote && st.wrap.isConnected) { markFrame(st); st.fit?.(); }
  for (const n of $$("#pane .doc-subject, #pane .att-name")) n.innerHTML = hl(n.textContent);
}

// where a link goes, shown at the foot of the reader while the pointer is on it
let linkTipEl = null;
function linkTip(frame, text) {
  if (linkTipEl) { linkTipEl.remove(); linkTipEl = null; }
  if (!text || !frame?.isConnected) return;
  const r = frame.getBoundingClientRect();
  linkTipEl = el("div", { class: "tip link-tip", style: `left:${Math.max(8, r.left)}px;max-width:${Math.max(160, Math.min(r.width, 620))}px` }, text);
  document.body.append(linkTipEl);
}
document.addEventListener("mousemove", () => { if (linkTipEl) linkTip(null, ""); }, { passive: true });
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = el("textarea", { style: "position:fixed;opacity:0" });
    ta.value = text; document.body.append(ta); ta.select();
    try { document.execCommand("copy"); } finally { ta.remove(); }
  }
  toast(t("copied"));
}

function refreshFrames() {
  for (const st of frames) {
    if (!st.wrap.isConnected) { frames.delete(st); continue; }
    st.toggle?.remove(); st.toggle = null; st.hidden = [];
    st.frame.srcdoc = frameDoc(st.html, { plain: st.plain, remote: st.remote, dark: isDark() });
  }
}
// a new theme: every open mail takes the new colours where it is (no blank frame, the folded quote stays folded);
// a frame not loaded yet is loaded again
function restyleFrames() {
  for (const st of frames) {
    if (!st.wrap.isConnected) { frames.delete(st); continue; }
    const s = st.frame.contentDocument?.getElementById("rd-style");
    if (s) s.textContent = frameCss({ plain: st.plain, dark: isDark() });
    else { st.toggle?.remove(); st.toggle = null; st.hidden = []; st.frame.srcdoc = frameDoc(st.html, { plain: st.plain, remote: st.remote, dark: isDark() }); }
  }
}

function collapseQuote(st) {
  const d = st.frame.contentDocument, root = d.querySelector(".rd-root") || d.body;
  let q = root.querySelector(QUOTE_SEL);
  if (!q) {
    const lines = textLines(root), at = quoteLine(lines.map((l) => l.text));
    const n = at >= 0 && lines.slice(at).find((l) => l.node)?.node;
    if (n) q = n.nodeType === 1 && n.tagName === "HR" ? n : n.parentElement.closest("div,p,table,blockquote,tr,section,font,span") || n.parentElement;
    // the box the header block opens (Outlook's line above it) goes with it
    const first = (x) => { let p = x.previousSibling; while (p && !p.textContent.trim() && !p.querySelector?.("img")) p = p.previousSibling; return !p; };
    while (q && q.parentElement && q.parentElement !== root && first(q)) q = q.parentElement;
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

// addresses: commas in quoted names and the full-width ，； of a Chinese input method (compose-kit.js)
const { ADDR_RE, parseAddrs } = K;

async function openCompose(opts) {
  if (S.compose && !(await leaveCompose())) return;
  const seq = ++threadSeq;            // a mail still loading does not replace the compose view, nor this a later choice
  let c;
  try {
    c = await api("compose", { mode: opts.mode, id: opts.id });
  } catch (e) { return fail(e); }
  if (seq !== threadSeq) return;
  if (opts.to) c.to = [...opts.to, ...c.to];
  if (opts.subject) c.subject = opts.subject;
  if (opts.files) c.pending = opts.files;
  c.showCc = c.cc.length > 0; c.showBcc = c.bcc.length > 0;
  c.dirty = false; c.status = ""; c.busy = false;
  // a draft made elsewhere carries the mail's own HTML: only plain content goes into the editor
  c.html = cleanHTML(c.html || "");
  // a draft we wrote before comes back inside our own font wrapper: take it off
  if (c.html) {
    const d = el("div", { html: c.html });
    const w = d.firstElementChild;
    if (w && w.dataset.rdBody && d.childElementCount === 1 && !d.textContent.replace(w.textContent, "").trim()) c.html = w.innerHTML;
  }
  S.compose = c; S.sched = null;
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
  subj.addEventListener("keydown", (e) => { if (e.key === "Enter" && !K.isIME(e)) { e.preventDefault(); ed.focus(); } });
  const ed = el("div", { class: "editor", contenteditable: "true", "data-ph": t("write"), spellcheck: "true",
    style: `font-family:${mailFont()};font-size:${mailSize()}px;--p-gap:${K.paraGap(mailSize())}px` });
  ed.innerHTML = cleanHTML(c.html || "");
  ed.addEventListener("input", () => { c.html = ed.innerHTML; touched(); fmtSync(); });
  ed.addEventListener("paste", onPaste);
  // Return starts a paragraph (<p>, a small gap below the one before), Shift+Return a line inside it (<br>)
  ed.addEventListener("focus", () => document.execCommand("defaultParagraphSeparator", false, "p"));
  ed.addEventListener("keydown", (e) => {
    if (K.isIME(e)) return;
    if (e.key === "Enter" && !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey) {
      document.execCommand("defaultParagraphSeparator", false, "p");
      // a first line typed straight into the box has no paragraph of its own yet: give it one, so it
      // keeps the same gap below it (an editing command, so Undo still works)
      if (blockOf(getSelection().anchorNode, ed) === ed) document.execCommand("formatBlock", false, "p");
      return;
    }
    const mod = isMod(e), k = e.key.toLowerCase();
    if (!mod || e.altKey) return;
    if (k === "k") { e.preventDefault(); e.stopPropagation(); linkSheet(); }
    else if (k === "b" || k === "i" || k === "u") { e.preventDefault(); edCmd({ b: "bold", i: "italic", u: "underline" }[k]); }
    // with Shift held e.key is "&" or "*" on many layouts: the key's place says which it is
    else if (e.shiftKey && (e.code === "Digit7" || e.code === "Digit8")) { e.preventDefault(); edCmd(e.code === "Digit7" ? "insertOrderedList" : "insertUnorderedList"); }
  });
  box.append(subj, fmtBar(), ed);
  if (c.signature && c.use_signature) box.append(sigBox(c));
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

// the signature under the text: a click on it picks another one (when there are more), × leaves it out
const sigName = (x, k) => x.name || t("sig_n", k + 1);
function sigBox(c) {
  const many = (c.signatures || []).filter((x) => x.html.trim()).length > 1;
  const sig = el("div", { class: "sig" + (many ? " pick" : ""), "data-tip": many ? t("sig_change") : null });
  sig.append(mailFrame(c.signature, { sig: true }).node, iconBtn("x", t("remove_sig"), (e) => { e.stopPropagation(); c.use_signature = false; touched(c); sig.remove(); }, { cls: "tiny" }));
  if (many) sig.addEventListener("click", () => menu(sig, c.signatures.map((x, k) => ({ icon: "square-pen", label: sigName(x, k), on: x.id === c.sig_id,
    run: () => {
      if (x.id === c.sig_id) return;
      c.sig_id = x.id; c.signature = x.html; touched(c);
      sig.replaceWith(sigBox(c));
    } })).filter((it, k) => c.signatures[k].html.trim())));
  return sig;
}

// ---------------------------------------------------------------- formatting

// the paragraph-like box a node is in, or the editor itself when it sits straight in it
const BLOCKS = /^(P|DIV|LI|BLOCKQUOTE|H[1-6]|PRE|TD|TH|UL|OL|TABLE)$/;
function blockOf(node, ed) {
  for (let n = node; n && n !== ed; n = n.parentNode) if (n.nodeType === 1 && BLOCKS.test(n.tagName)) return n;
  return ed;
}

const fmtBarOn = () => PREFS.fmt_bar !== false;
function toggleFmtBar() {
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
function edFocus() {
  const ed = $(".compose .editor");
  if (!ed) return null;
  const sel = getSelection();
  const inside = document.activeElement === ed && sel.rangeCount && ed.contains(sel.anchorNode);
  ed.focus();
  if (!inside && edRange && ed.contains(edRange.startContainer)) { sel.removeAllRanges(); sel.addRange(edRange); }
  return ed;
}
function edChanged() {
  const ed = $(".compose .editor");
  if (!ed || !S.compose) return;
  S.compose.html = ed.innerHTML; touched(); fmtSync();
}
function edCmd(cmd, val = null) {
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
  // the browser's own sizes 1-7, left as they are so Undo works and a bare caret gets the size it shows;
  // style.css draws them at K.FONT_PX and outHTML sends those pixels
  document.execCommand("styleWithCSS", false, false);
  document.execCommand("fontSize", false, K.sizeKey(px));
  edChanged();
}
const FMT_SIZES = [["12", "size_small"], ["14", "size_normal"], ["18", "size_large"], ["24", "size_huge"]];
function fmtBar() {
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
function fmtSync() {
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
function linkSheet() {
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
  for (const i of [url, label]) i.addEventListener("keydown", (e) => { if (e.key === "Enter" && !K.isIME(e)) { e.preventDefault(); go(); } });
  sheet(el("div", {}, el("h2", {}, t("link")), el("div", { class: "form" },
    el("label", {}, el("span", { class: "lab" }, t("link_url")), url),
    el("label", {}, el("span", { class: "lab" }, t("link")), label)),
    el("div", { class: "sheet-acts" }, el("button", { class: "btn", onclick: () => { closeLayer(); edFocus(); } }, t("cancel")),
      el("button", { class: "btn primary", onclick: go }, t("ok")))), { onclose: () => edFocus() });
  requestAnimationFrame(() => url.focus());
}

// a change to the compose: it counts edits, so a save knows whether more came in while it ran
function touched(c = S.compose) {
  if (!c) return;
  c.dirty = true;
  c.edits = (c.edits || 0) + 1;
  if (S.compose === c) setStatus("");
  clearTimeout(c.autosave);
  c.autosave = setTimeout(() => { if (S.compose === c && c.dirty && !c.busy) saveDraft(c, { auto: true }).catch(() => {}); }, 15000);
}
// while Send checks and saves the mail, the compose can't change under it
function lockCompose(c, on) {
  c.busy = on;
  const box = $(".compose");
  if (box && S.compose === c) box.inert = on;
  renderToolbar();
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
  const add = (list, focus = true) => {
    const have = new Set([...c.to, ...c.cc, ...c.bcc].map((x) => x.addr));
    for (const p of list) if (p.addr && !have.has(p.addr)) { c[key].push(p); have.add(p.addr); }
    input.value = ""; closeSug(); draw(); touched(); if (focus) input.focus();
  };
  const commit = (focus = true) => { const v = input.value.trim(); if (v) add(parseAddrs(v), focus); };
  // Send turns what is still typed into chips, shown (composeState)
  input.rdCommit = () => commit(false);
  input.dataset.k = key;
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
  // typing counts as a change (Esc saves it); a separator after a whole address makes the chip
  input.addEventListener("input", (e) => {
    clearTimeout(sugTimer); sugTimer = setTimeout(showSug, 120); touched();
    if (!e.isComposing && K.commitReady(input.value)) commit();
  });
  input.addEventListener("compositionend", () => { if (K.commitReady(input.value)) commit(); });
  input.addEventListener("keydown", (e) => {
    if (K.isIME(e)) return;
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
    if (/[,;，；\n]/.test(txt) || /@/.test(txt)) { e.preventDefault(); add(parseAddrs(input.value + txt)); }
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
      el("div", a.uploading ? { class: "att-icon", html: icon("loader-circle", "spin") } : fileTile(a.name)),
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
      if (!j.ok) throw new Error(tr(j.error) || t("error"));
      Object.assign(a, j.data, { uploading: false });
      if (S.compose === c) touched(c); else c.dirty = true;
    } catch (e) {
      c.atts = c.atts.filter((x) => x !== a);
      fail(e);
    }
    if (S.compose === c) renderAtts();
  }
}

const readURL = (f) => new Promise((ok) => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.onerror = () => ok(null); rd.readAsDataURL(f); });
const LOCAL_SRC = /^\s*(file|blob|webkit-fake-url):/i;
async function onPaste(e) {
  const dt = e.clipboardData;
  // what the clipboard holds is read now: it is gone once this event ends
  const imgs = [...dt.files].filter((f) => f.type.startsWith("image/"));
  const html = dt.getData("text/html"), plain = dt.getData("text/plain");
  if (!html && !imgs.length) return;
  e.preventDefault();
  // Excel and Word put a picture of the table on the clipboard as well: the table itself is what is meant
  if (html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    // a picture the HTML points to on this computer can't go out with the mail: the clipboard's own
    // pictures take those places in turn; any left over are dropped
    const local = [...doc.querySelectorAll("img")].filter((i) => LOCAL_SRC.test(i.getAttribute("src") || ""));
    const data = await Promise.all(imgs.slice(0, local.length).map(readURL));
    local.forEach((img, k) => { if (data[k]) img.setAttribute("src", data[k]); });
    // white text from a dark page or app would not show on the white mail
    const body = K.sanitizeBody(doc.body, { paste: true });
    if (body.textContent.trim() || body.querySelector("img, table, hr")) {
      document.execCommand("insertHTML", false, body.innerHTML);
      return;
    }
    if (!imgs.length) { if (plain) document.execCommand("insertText", false, plain); return; }
  }
  for (const src of await Promise.all(imgs.map(readURL))) {
    if (src && K.safeURL(src, "src")) document.execCommand("insertHTML", false, `<img src="${esc(src)}" alt="">`);
  }
}

// HTML for the editor, which sits in the app's own window: an allow-list of plain content (compose-kit.js).
// DOMParser's document runs nothing and loads nothing while it is cleaned.
function cleanHTML(html, opts = {}) {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  return K.sanitizeBody(doc.body, opts).innerHTML;
}

function composeState(opts = {}) {
  const c = S.compose;
  const ed = $(".compose .editor");
  if (ed) c.html = ed.innerHTML;
  // an address still being typed counts. Send turns it into a chip; a save only reads it and leaves the
  // box as it is (an autosave in the middle of typing takes whole addresses only)
  const typed = { to: [], cc: [], bcc: [] };
  for (const inp of $$(".compose .chips input")) {
    const k = inp.dataset.k;
    if (!typed[k] || !inp.value.trim()) continue;
    if (opts.commit) inp.rdCommit?.();
    else typed[k] = parseAddrs(inp.value).filter((p) => !opts.auto || ADDR_RE.test(p.addr));
  }
  const have = new Set([...c.to, ...c.cc, ...c.bcc].map((x) => x.addr));
  const list = (k) => [...c[k], ...typed[k].filter((p) => !have.has(p.addr))];
  return {
    mode: c.mode, orig: c.orig, replace: c.replace, to: list("to"), cc: list("cc"), bcc: list("bcc"), subject: c.subject,
    html: wrapBody(c.html), atts: c.atts.filter((a) => !a.uploading).map(({ path, name, size }) => ({ path, name, size })),
    use_signature: c.use_signature, sig_id: c.sig_id, irt: c.irt, refs: c.refs, fwd: c.fwd,
  };
}

// Outlook shows unstyled mail in Times: always say which font the body is in
function wrapBody(html) {
  if (!html || !html.replace(/<br\s*\/?>|<\/?(div|p)>|&nbsp;|\s/gi, "")) return html || "";
  return `<div data-rd-body="1" style="font-family:${mailFont().replace(/"/g, "'")};font-size:${mailSize()}px">${outHTML(html)}</div>`;
}
// the editor's HTML as it goes out: the gap under each paragraph is written on it (the editor shows it
// with style.css), so Outlook, Gmail and phones show it too
function outHTML(html) {
  const box = document.createElement("template");
  box.innerHTML = html;
  const gap = `margin:0 0 ${K.paraGap(mailSize())}px`;
  for (const p of box.content.querySelectorAll("p")) {
    const st = p.getAttribute("style") || "";
    if (!/(^|;)\s*margin(-bottom)?\s*:/i.test(st)) p.setAttribute("style", st ? `${gap};${st}` : gap);
  }
  for (const f of box.content.querySelectorAll("font[size]")) {
    const px = K.FONT_PX[f.getAttribute("size").trim()];
    if (px) { f.style.fontSize = px + "px"; f.removeAttribute("size"); }
  }
  return box.innerHTML;
}

let saving = Promise.resolve();
function saveDraft(c = S.compose, opts = {}) {
  const job = saving.then(async () => {
    if (!c || c.busy) return;         // Send has it: a second copy would stay in Drafts
    const edits = c.edits;
    const st = S.compose === c ? composeState(opts) : c.lastState;
    if (!st) return;
    if (S.compose === c) setStatus(t("saving"));
    try {
      const r = await api("save_draft", st);
      c.replace = r.id; c.lastState = { ...st, replace: r.id };
      // words typed while it saved are not in this copy: they still need saving
      if (c.edits === edits) c.dirty = false;
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
  // a draft saved now would go without the file still uploading
  if (c.atts.some((a) => a.uploading)) { toast(t("att_wait"), { id: "att-wait" }); return false; }
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
  if (!(await leaveCompose())) return;
  // a draft gets a new id each time it is saved: never reopen the old one
  if (S.sel && S.folder !== "drafts" && S.rows.some((x) => x.id === S.sel && x.folder !== "drafts")) openThread(S.sel);
  else { S.sel = null; syncSel(); showEmpty(); }
}

async function discardCompose() {
  const c = S.compose;
  if (!c || c.busy) return;           // Send is checking it: Discard waits for that to end
  clearTimeout(c.autosave);
  c.busy = true;
  await saving;
  S.compose = null;
  if (c.replace) {
    try { await api("delete_draft", { id: c.replace }); toast(t("draft_deleted")); } catch (e) { fail(e); }
    refreshCounts();
    if (S.folder === "drafts") { S.sel = null; loadList({ quiet: true }); }
  }
  if (S.sel && S.folder !== "drafts") openThread(S.sel); else showEmpty();
}

async function sendCompose(force = false, at = null) {
  const c = S.compose;
  if (!c || c.busy) return;
  if (c.atts.some((a) => a.uploading)) return toast(t("att_wait"), { id: "att-wait" });
  clearTimeout(c.autosave);
  // busy before the first wait: a second Send, Discard or Cmd+S in the meantime does nothing
  lockCompose(c, true);
  await saving;
  const st = composeState({ commit: true });
  let r;
  try { r = await api("prepare_send", { ...st, force }); }
  catch (e) { lockCompose(c, false); return fail(e); }
  if (r.problems && r.problems.length) {
    lockCompose(c, false);
    return problemsSheet(r.problems, at);
  }
  c.busy = false;
  c.replace = r.id; c.dirty = false; c.lastState = { ...st, replace: r.id };
  const reopen = async () => { if (S.compose && !(await leaveCompose())) return; S.compose = c; renderCompose(); };
  // out of the way while it waits
  S.compose = null;
  if (S.sel && S.folder !== "drafts" && S.folder !== "scheduled") openThread(S.sel); else showEmpty();
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
// The backend holds the mail through the pause as well (api send with a delay), so closing the window or
// the page does not drop it: the window asks first (ragdollClosing), a page that is gone still sends.
const HELD = new Map();         // id -> the mail in its pause: { undo, now, quiet, ok, done }
async function sendWithUndo(id, onUndo) {
  const wait = undoSeconds() * 1000;
  if (wait) {
    try { await api("send", { id, delay: wait / 1000 }); }
    catch (e) { fail(e); return onUndo?.(); }
  }
  let undone = false, rush = false, finish;
  const held = { undo: () => { undone = true; }, now: () => { rush = true; }, quiet: false, ok: false, done: new Promise((r) => { finish = r; }) };
  HELD.set(id, held);
  const tt = toast(t("sending"), wait ? { action: { label: t("undo"), run: held.undo }, ms: 0, bar: wait } : { ms: 0 });
  const end = Date.now() + wait;
  try {
    while (wait && Date.now() < end && !undone && !rush) await sleep(100);
    if (undone) {
      const r = await api("send_cancel", { id }).catch(() => ({ cancelled: false }));
      // too late: it had started to go out, so it is waited for below like any other send
      if (r.cancelled) { tt.close(); if (!held.quiet) onUndo?.(); return; }
    }
    tt.node.querySelector(".toast-act")?.remove();
    tt.node.querySelector(".toast-bar")?.remove();
    await sendHeld(id, tt, onUndo, held, wait);
  } finally { HELD.delete(id); finish(); }
}
async function sendHeld(id, tt, onUndo, held, wait) {
  try {
    const res = await api(wait ? "send_wait" : "send", { id });
    if (res.cancelled) { tt.close(); return; }
    held.ok = true;
    tt.close();
    const after = res.problems_after_sending || [];
    if (after.length) toast(after.map(tr).join(" "), { error: true, ms: 12000 });
    else toast(t("sent_ok"));
    refreshCounts();
    if (["sent", "drafts", "scheduled"].includes(S.folder)) loadList({ quiet: true });
    if (S.thread && !S.compose) openThread(S.focus || S.sel);
  } catch (e) {
    tt.close();
    fail(e);
    onUndo?.();
  }
}
// the window is being closed while a mail waits out its pause (ragdoll_app.py window_closing)
window.ragdollClosing = () => {
  if (!HELD.size) return api("quit_window").catch(() => {});
  api("close_asked", { open: true }).catch(() => {});
  let leaving = false;
  const away = () => { if (!leaving) api("close_asked", { open: false }).catch(() => {}); };
  const go = async (send) => {
    leaving = true;
    closeLayer();
    const all = [...HELD.values()];
    for (const h of all) { h.quiet = !send; if (send) h.now(); else h.undo(); }
    await Promise.all(all.map((h) => h.done));
    // a mail that could not go out stays open in the window, with its reason
    if (send && all.some((h) => !h.ok)) return api("close_asked", { open: false }).catch(() => {});
    api("quit_window").catch(() => {});
  };
  const box = sheet(el("div", {},
    el("h2", { html: icon("send") + esc(t("closing_sending")) }),
    el("div", { class: "sheet-acts" },
      el("button", { class: "btn", onclick: () => { closeLayer(); away(); } }, t("keep_window")),
      el("button", { class: "btn", onclick: () => go(false) }, t("cancel_sending")),
      el("button", { class: "btn primary", onclick: () => go(true) }, t("send_now")))), { onclose: away });
  box.querySelector(".btn.primary").focus();
};

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

// ---------------------------------------------------------------- send later

const addDays = (p, n) => { const d = new Date(Date.UTC(p.y, p.m - 1, p.d + n)); return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate() }; };
function laterMenu(anchor) {
  const now = zparts(Date.now());
  const at = (p, h) => zepoch(p.y, p.m, p.d, h, 0);
  const items = [];
  const pick = (ic, label, ts, hint) => items.push({ icon: ic, label, hint, run: () => sendCompose(false, ts) });
  if (now.h < 17) pick("sunset", t("this_evening"), at(now, 18), fmt(at(now, 18), HM));
  const tom = addDays(now, 1);
  pick("sunrise", t("tomorrow_morning"), at(tom, 8), fmt(at(tom, 8), HM));
  pick("sun", t("tomorrow_afternoon"), at(tom, 13), fmt(at(tom, 13), HM));
  const toMon = ((8 - now.wd) % 7) || 7;
  if (toMon > 1) { const mon = addDays(now, toMon); pick("calendar", t("monday_morning"), at(mon, 8), fmt(at(mon, 8), { month: "short", day: "numeric", ...HM })); }
  items.push("-", { icon: "calendar-clock", label: t("pick_time"), run: pickTimeSheet });
  menu(anchor, items);
}

function pickTimeSheet() {
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
    sendCompose(false, ts);
  };
  const box = sheet(el("div", { class: "pick-time" },
    el("h2", { html: icon("calendar-clock") + esc(t("send_later")) }),
    el("div", { class: "form" },
      el("div", { class: "two-even" }, el("label", {}, el("span", { class: "lab" }, t("date")), date), el("label", {}, el("span", { class: "lab" }, t("time")), time)),
      el("div", { class: "note", html: icon("globe", "small") + esc((TZ || SYS_TZ).replace(/_/g, " ")) }), err),
    el("div", { class: "sheet-acts" },
      el("button", { class: "btn", onclick: closeLayer }, t("cancel")),
      el("button", { class: "btn primary", onclick: go }, t("schedule")))));
  box.addEventListener("keydown", (e) => { if (e.key === "Enter" && !K.isIME(e)) { e.preventDefault(); go(); } });
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

// ---------------------------------------------------------------- settings

// opts (all optional): tab, the page to open on; focus, the account field to put the cursor in
async function openSettings(opts) {
  opts = opts && !(opts instanceof Event) ? opts : {};
  let s;
  try { s = await api("settings"); } catch (e) { return fail(e); }
  const v = { ...s, password: "", theme: S.theme, signatures: (s.signatures || []).map((x) => ({ ...x })) };
  let tab = opts.tab || "account", sigOn = 0;
  const nav = el("div", { class: "settings-nav" }, el("h3", {}, t("settings")));
  const body = el("div", { class: "settings-body" });
  const msg = el("span", { class: "grow" });
  const saveBtn = el("button", { class: "btn primary", onclick: save }, t("save"));
  const cancelBtn = el("button", { class: "btn", onclick: closeLayer }, t("cancel"));
  const foot = el("div", { class: "settings-foot" }, msg, cancelBtn, saveBtn);
  const tabs = [["account", "circle-user-round", "account"], ["signature", "square-pen", "signature"], ["sending", "type", "composing"],
    ["notify", "bell", "notifications"], ["appearance", "sun", "appearance"], ["privacy", "shield", "privacy"], ["region", "languages", "region"],
    ...(s.demo ? [] : [["cli", "terminal", "cli"]])];
  const drawNav = () => {
    nav.replaceChildren(el("h3", {}, t("settings")));
    for (const [k, ic, lab] of tabs) nav.append(el("button", { class: "nav-item" + (k === tab ? " on" : ""), onclick: () => { grab(); tab = k; drawNav(); draw(); }, html: icon(ic) + `<span class="label">${esc(t(lab))}</span>` }));
  };
  const setPref = (patch) => { Object.assign(PREFS, patch); api("prefs", patch).catch(fail); };
  // the whole window speaks the new language at once, this sheet too
  const relabelSheet = () => { saveBtn.textContent = t("save"); cancelBtn.textContent = t("cancel"); drawNav(); draw(); };
  let sigEd = null;
  const grab = () => {
    for (const inp of $$("input[data-k]", body)) v[inp.dataset.k] = inp.value;
    const cur = v.signatures[sigOn];
    if (sigEd && cur) { cur.html = sigEd.innerHTML; cur.name = $("input[data-sig-name]", body)?.value.trim() || ""; }
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
      if (s.password_env) f.append(el("div", { class: "msg-warn" }, t("pw_env", s.password_env)));
      f.append(lab(t("incoming"), el("div", { class: "two" }, inp("imap_host"), inp("imap_port", "number"))),
        lab(t("outgoing"), el("div", { class: "two" }, inp("smtp_host"), inp("smtp_port", "number", { "data-host": "smtp_port" }))));
      const res = el("div");
      const testBtn = el("button", { class: "btn", onclick: async () => {
        grab(); testBtn.disabled = true; res.replaceChildren(el("span", { class: "note" }, t("testing")));
        try { const r = await api("test", v); v.folders = r.folders; res.replaceChildren(el("div", { class: "msg-ok", html: icon("circle-check") + esc(t("test_ok")) })); }
        catch (e) { res.replaceChildren(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) })); }
        finally { testBtn.disabled = false; }
      } }, t("test"));
      f.append(el("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" }, testBtn, res));
      f.append(storageLine());
      body.append(el("h2", {}, t("account")), f);
    } else if (tab === "signature") {
      // a list of signatures, each with a name; one is the default for new mail, one for replies
      const sigs = v.signatures;
      sigOn = Math.min(sigOn, Math.max(0, sigs.length - 1));
      const list = el("div", { class: "seg sig-list" });
      sigs.forEach((x, k) => list.append(el("button", { class: k === sigOn ? "on" : "", onclick: () => { grab(); sigOn = k; draw(); } }, sigName(x, k))));
      const add = iconBtn("plus", t("sig_add"), () => {
        grab();
        sigs.push({ id: "s" + Date.now().toString(36), name: "", html: "" });
        sigOn = sigs.length - 1;
        if (sigs.length === 1) { v.sig_new = v.sig_new || sigs[0].id; v.sig_reply = v.sig_reply || sigs[0].id; }
        draw();
        $("input[data-sig-name]", body)?.focus();
      }, { cls: "tiny" });
      const head = el("div", { class: "sig-head" }, list, add);
      const pick = (k) => selectBox([["", t("sig_none")], ...sigs.map((x, n) => [x.id, sigName(x, n)])], v[k] || "", (val) => { grab(); v[k] = val; draw(); });
      const defaults = el("div", { class: "two-even" },
        el("label", {}, el("span", { class: "lab" }, t("sig_for_new")), pick("sig_new")),
        el("label", {}, el("span", { class: "lab" }, t("sig_for_reply")), pick("sig_reply")));
      if (!sigs.length) {
        body.append(el("h2", {}, t("signature")), el("div", { class: "form" }, head));
        return;
      }
      const cur = sigs[sigOn];
      const name = el("input", { type: "text", "data-sig-name": "", value: cur.name, placeholder: sigName({}, sigOn), maxlength: "60", spellcheck: "false", autocomplete: "off" });
      name.addEventListener("input", () => { const b = list.children[sigOn]; if (b) b.textContent = name.value.trim() || sigName({}, sigOn); });
      const del = el("button", { class: "btn", onclick: () => {
        sigs.splice(sigOn, 1);
        for (const k of ["sig_new", "sig_reply"]) if (v[k] === cur.id) v[k] = "";
        sigOn = Math.max(0, sigOn - 1);
        sigEd = null;
        draw();
      }, html: icon("trash-2", "small") + esc(t("sig_delete")) });
      sigEd = el("div", { class: "sig-edit", contenteditable: "true" });
      sigEd.innerHTML = cleanHTML(cur.html || "");
      sigEd.addEventListener("focus", () => document.execCommand("defaultParagraphSeparator", false, "div"));
      sigEd.addEventListener("paste", (e) => { const h = e.clipboardData.getData("text/html"); if (h) { e.preventDefault(); document.execCommand("insertHTML", false, cleanHTML(h, { paste: true })); } });
      body.append(el("h2", {}, t("signature")), el("div", { class: "form" }, head,
        el("label", {}, el("span", { class: "lab" }, t("sig_name")), name), sigEd,
        el("div", {}, del), defaults));
    } else if (tab === "sending") {
      const seg = segmented(UNDO_CHOICES.map((n) => [n, n ? t("seconds", n) : t("undo_off")]), undoSeconds(), (n) => setPref({ undo: n }));
      const font = selectBox(FONTS.map(([k]) => [k, fontLabel(k)]), PREFS.font || "system", (val) => { setPref({ font: val }); draw(); });
      const sample = el("div", { class: "font-sample", style: `font-family:${mailFont()};font-size:${mailSize()}px` }, t("font_sample"));
      const sizes = segmented(FONT_SIZES.map((n) => [n, String(n)]), mailSize(), (n) => { setPref({ font_size: n }); sample.style.fontSize = n + "px"; });
      body.append(el("h2", {}, t("composing")), el("div", { class: "form" },
        el("label", {}, el("span", { class: "lab" }, t("default_font")), font),
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("default_size")), sizes), sample,
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("undo_send")), seg), el("div", { class: "note" }, t("undo_note"))));
    } else if (tab === "notify") {
      const seg = segmented([[true, t("on")], [false, t("undo_off")]], PREFS.notify !== false, (on) => {
        setPref({ notify: on });
        if (!on) { $(".notice-off", form)?.remove(); return; }
        askNotice();
        if (window.pywebview) { noticeAsked = true; api("notice_on", { body: t("notifications") + ": " + t("on") }).catch(() => {}); }
        setTimeout(check, noticeAsked ? 1500 : 0);
        noticeAsked = false;
      });
      const form = el("div", { class: "form" }, el("div", { class: "stack" }, el("span", { class: "lab" }, t("new_mail")), seg));
      body.append(el("h2", {}, t("notifications")), form);
      // macOS keeps its own switch for the app; when it is off, say so and lead to it
      const check = async () => {
        if (!window.pywebview || PREFS.notify === false) return;
        const r = await api("notice_state").catch(() => null);
        if (!form.isConnected) return;
        const old = $(".notice-off", form);
        if (r?.state !== "off") { old?.remove(); return; }
        if (old) return;
        form.append(el("div", { class: "msg-warn notice-off" }, el("span", {}, t("notice_off")),
          el("button", { class: "btn", onclick: () => api("notice_settings").catch(fail) }, t("notice_open"))));
        // back from System Settings: the line goes once the switch is on
        const back = () => { if (!form.isConnected) { window.removeEventListener("focus", back); return; } check(); };
        window.addEventListener("focus", back);
      };
      // a moment after the switch here: macOS may be asking its question right now
      setTimeout(check, noticeAsked ? 1500 : 0);
      noticeAsked = false;
    } else if (tab === "privacy") {
      const seg = segmented([[true, t("on")], [false, t("undo_off")]], PREFS.remote_images !== false, (on) => {
        setPref({ remote_images: on });
        rerenderBodies();
      });
      const form = el("div", { class: "form" }, el("div", { class: "stack" }, el("span", { class: "lab" }, t("remote_images")), seg),
        el("div", { class: "note" }, t("remote_note")));
      if (imgSenders().length) {
        const row = el("div", { class: "img-senders" }, el("span", {}, t("img_senders_n", imgSenders().length)),
          el("button", { class: "btn", onclick: () => { setPref({ img_senders: [] }); row.remove(); rerenderBodies(); } }, t("img_forget")));
        form.append(row);
      }
      body.append(el("h2", {}, t("privacy")), form);
    } else if (tab === "cli") {
      const form = el("div", { class: "form" });
      body.append(el("h2", {}, t("cli")), form);
      const drawCli = async () => {
        const st = await api("cli_state").catch(fail);
        if (!st || !form.isConnected) return;
        const res = el("div");
        const btn = el("button", { class: "btn", onclick: async () => {
          btn.disabled = true;
          try {
            const r = await api("install_cli");
            const lines = [r.kept ? t("cli_kept", r.path) : t("cli_done", r.path)];
            if (r.path_added) lines.push(t("cli_new_terminal"));
            res.replaceChildren(el("div", { class: r.kept ? "msg-warn" : "msg-ok", html: (r.kept ? "" : icon("circle-check")) + esc(lines.join(" ")) }));
          } catch (e) { res.replaceChildren(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) })); }
          finally { btn.disabled = false; }
        } }, st.installed ? t("cli_reinstall") : t("cli_install"));
        form.replaceChildren(el("div", { class: "stack" }, el("span", { class: "lab" }, t("cli_command")),
          el("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" }, btn, res)));
      };
      drawCli();
    } else if (tab === "region") {
      const lang = selectBox([["system", t("system_x", LANG_NAMES.find(([k]) => k === systemLang())[1])], ...LANG_NAMES], PREFS.lang || "system", (val) => {
        setPref({ lang: val }); setLocale(PREFS); relabel(); relabelSheet();
      });
      const tz = selectBox([["system", t("system_x", SYS_TZ.replace(/_/g, " "))], ...zoneChoices()], PREFS.tz && PREFS.tz !== "system" ? PREFS.tz : "system", (val) => {
        setPref({ tz: val }); setLocale(PREFS); relabel(); draw();
      });
      body.append(el("h2", {}, t("region")), el("div", { class: "form" },
        el("label", {}, el("span", { class: "lab" }, t("language")), lang),
        el("label", {}, el("span", { class: "lab" }, t("time_zone")), tz)));
    } else {
      // the sheet stays as it is: the picked item slides over and the whole window fades to the new theme
      const seg = segmented([["system", t("system"), "monitor"], ["light", t("light"), "sun"], ["dark", t("dark"), "moon"]], v.theme,
        (k) => { v.theme = k; applyTheme(k); api("prefs", { theme: k }).catch(() => {}); });
      const ts = segmented([13, 14, 16, 18].map((n) => [n, String(n)]), textSize(), (n) => setTextSize(n));
      body.append(el("h2", {}, t("appearance")), el("div", { class: "form" }, seg,
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("text_size")), ts)));
    }
  };
  async function save() {
    grab();
    const changed = ["name", "user", "password", "imap_host", "imap_port", "smtp_host", "smtp_port"].some((k) => String(v[k] ?? "") !== String(s[k] ?? ""));
    const sigKey = (o) => JSON.stringify([(o.signatures || []).map(({ id, name, html }) => [id, name, html]), o.sig_new || "", o.sig_reply || ""]);
    const sigChanged = sigKey(v) !== sigKey(s);
    if (!changed && !sigChanged) return closeLayer();
    saveBtn.disabled = true;
    msg.replaceChildren();
    try {
      if (sigChanged) {
        Object.assign(s, await api("save_signatures", { signatures: v.signatures, sig_new: v.sig_new, sig_reply: v.sig_reply }));
        if (!changed) { closeLayer(); toast(t("saved")); return; }
      }
      const { signature, signatures, sig_new, sig_reply, ...acct } = v;
      const b = await api("save_settings", { ...acct, account: true, folders: v.folders });
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
  if (opts.focus) $(`input[data-k="${opts.focus}"]`, body)?.focus();
}

// how much downloaded mail this computer keeps, and a button that clears it (it is fetched again when opened)
function storageLine() {
  const gb = (n) => (n >= 1024 ** 3 ? (n / 1024 ** 3).toFixed(1) + " GB" : size(n));
  const val = el("span", { class: "storage-size" });
  const btn = el("button", { class: "btn", onclick: async () => {
    btn.disabled = true;
    try { val.textContent = gb((await api("clear_storage")).bytes); toast(t("storage_cleared")); } catch (e) { fail(e); } finally { btn.disabled = false; }
  } }, t("clear"));
  api("storage").then((r) => { val.textContent = gb(r.bytes); }).catch(() => {});
  return el("div", { class: "stack" }, el("span", { class: "lab" }, t("downloaded_mail")), el("div", { class: "storage-line" }, val, btn));
}

const UNDO_CHOICES = [0, 5, 10, 20, 30];

// a segmented control: [value, label, icon?] items; the picked one sits on a thumb that slides to the next pick
// (the control is changed in place, never drawn again, so the slide can be seen)
function segmented(items, value, pick) {
  const thumb = el("span", { class: "seg-thumb", "aria-hidden": "true" });
  const seg = el("div", { class: "seg", role: "radiogroup" }, thumb);
  const place = (slide) => {
    const on = $("button.on", seg);
    if (!on || !on.offsetWidth) return;
    seg.classList.toggle("seg-slide", slide && !REDUCED.matches);
    const a = seg.getBoundingClientRect(), b = on.getBoundingClientRect();     // exact, not rounded like offsetLeft
    seg.style.setProperty("--seg-x", b.left - a.left - seg.clientLeft + "px");
    seg.style.setProperty("--seg-w", b.width + "px");
    seg.classList.add("seg-ready");
  };
  for (const [v, label, ic] of items) {
    const b = el("button", { class: v === value ? "on" : "", role: "radio", "aria-checked": String(v === value),
      html: (ic ? icon(ic, "small") : "") + esc(label), onclick: () => {
        if (b.classList.contains("on")) return;
        for (const x of $$("button", seg)) { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", String(x === b)); }
        place(true);
        pick(v);
      } });
    seg.append(b);
  }
  // placed once it is laid out (it is made before it is shown), and again when its size changes
  if (window.ResizeObserver) new ResizeObserver(() => place(false)).observe(seg);
  return seg;
}

// a native select in our own frame, with a chevron
function selectBox(options, value, onchange) {
  const sel = el("select", {});
  for (const [k, label] of options) sel.append(el("option", { value: k, selected: k === value }, label));
  sel.addEventListener("change", () => onchange(sel.value));
  return el("span", { class: "select" }, sel, el("span", { class: "select-ic", html: icon("chevron-down", "small") }));
}

// every IANA time zone, by UTC offset now, labelled "UTC+08:00  Asia / Shanghai"
let ZONES = null;
function zoneChoices() {
  if (ZONES) return ZONES;
  let names = [];
  try { names = Intl.supportedValuesOf("timeZone"); } catch { names = [SYS_TZ, "UTC"]; }
  if (!names.includes("UTC")) names.push("UTC");
  const now = new Date();
  ZONES = names.map((z) => {
    let off = "GMT";
    try { off = new Intl.DateTimeFormat("en-US", { timeZone: z, timeZoneName: "longOffset" }).formatToParts(now).find((x) => x.type === "timeZoneName")?.value || "GMT"; } catch { /* old engine */ }
    const m = off.match(/GMT([+-])(\d{2}):?(\d{2})?/);
    const mins = m ? (m[1] === "-" ? -1 : 1) * (+m[2] * 60 + +(m[3] || 0)) : 0;
    const label = "UTC" + (m ? m[1] + m[2] + ":" + (m[3] || "00") : "±00:00");
    return { z, mins, text: label + "  " + z.replace(/_/g, " ").replace(/\//g, " / ") };
  }).sort((a, b) => a.mins - b.mins || a.z.localeCompare(b.z)).map((x) => [x.z, x.text]);
  return ZONES;
}

// a new language or time zone: draw everything again in place
function relabel() {
  if (!S.boot) return;
  $("#compose-btn").dataset.tip = t("compose");
  placeCompose();
  $("#search").placeholder = t("search");
  $("#search-btn").dataset.tip = t("search");
  syncFilterUI();
  renderNav();
  renderRows();
  if (S.compose) { composeState({ commit: true }); renderCompose(); }
  else if (S.sched) openScheduled(S.sched);
  else if (S.thread) openThread(S.focus || S.sel);
  else renderToolbar();
  refreshCounts();
}

// ---------------------------------------------------------------- setup (no account yet)

function showSetup(boot = {}) {
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
      try { Object.assign(v, await api("guess_servers", { user: v.user })); $$("#setup input[data-host]").forEach((x) => { x.value = v[x.dataset.host] ?? ""; }); } catch { /* typed by hand */ }
    });
    f.append(lab(t("name"), inp("name")), lab(t("email"), email), lab(t("password"), inp("password", "password")));
    const dis = el("button", { class: "disclose" + (open ? " open" : ""), onclick: () => { open = !open; draw(); }, html: icon("chevron-right", "small") + esc(t("servers")) });
    f.append(dis);
    if (open) {
      f.append(lab(t("incoming"), el("div", { class: "two" }, inp("imap_host", "text", { "data-host": "imap_host" }), inp("imap_port", "number"))),
        lab(t("outgoing"), el("div", { class: "two" }, inp("smtp_host", "text", { "data-host": "smtp_host" }), inp("smtp_port", "number"))));
    }
    if (err) f.append(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(err) }));
    const bad = boot.config_error;     // the settings file has a typo: say so, and where it is (#49)
    if (bad && !err) {
      f.append(el("div", { class: "msg-err cfg-broken" }, el("span", { html: icon("triangle-alert") }),
        el("span", {}, t("cfg_broken", bad.path), " ",
          el("button", { class: "link", onclick: () => api("reveal", { path: bad.path }).catch(fail) }, t("cfg_show")))));
    }
    const go = el("button", { class: "btn primary", disabled: busy, onclick: signIn }, busy ? t("signing_in") : t("sign_in"));
    f.append(go);
    f.addEventListener("keydown", (e) => { if (e.key === "Enter" && !K.isIME(e) && e.target.tagName === "INPUT") signIn(); });
    const lang = selectBox([["system", t("system_x", LANG_NAMES.find(([k]) => k === systemLang())[1])], ...LANG_NAMES], PREFS.lang || "system", (val) => {
      PREFS.lang = val; api("prefs", { lang: val }).catch(() => {}); setLocale(PREFS); draw();
    });
    lang.classList.add("setup-lang");
    lang.prepend(el("span", { class: "select-lead", html: icon("languages", "small") }));
    box.replaceChildren(el("div", { class: "setup-drag pywebview-drag-region" }), lang,
      el("div", { class: "setup-card" }, el("img", { class: "logo", src: "logo.png", alt: "" }), el("h1", {}, t("setup_title")), f));
  };
  async function signIn() {
    if (busy) return;
    if (!v.imap_host && v.user.includes("@")) {
      try { Object.assign(v, await api("guess_servers", { user: v.user })); } catch { /* below */ }
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

function setTextSize(n) {
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

function shortcutsSheet() {
  const groups = [
    ["mailbox", [["J  K", "next_mail"], ["C", "compose"], ["/", "search"], [MOD + "R", "sync_now"], [MOD + "Z", "undo"], [MOD + "A", "select_all"], [MOD + "Click", "add_select"], ["⇧Click", "range_select"], ["Esc", "close_clear"]]],
    ["reading", [["R", "reply"], ["A", "replyall"], ["F", "forward"], ["E", "archive_it"], ["#", "trash_it"], ["V", "move_to"], ["U", "unread"], ["S", "flag"], [MOD + "+  " + MOD + "−", "text_size"], [MOD + "0", "actual_size"]]],
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
function onKey(e) {
  if (K.isIME(e)) return;             // Esc, Enter and Backspace belong to the input method's candidate
  const mod = isMod(e);
  // Sync now; the web view would otherwise reload the whole page and drop what is open, a compose too
  if ((mod && !e.altKey && e.key.toLowerCase() === "r") || e.key === "F5") { e.preventDefault(); syncNow(); return; }
  if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); openSearch(); return; }
  if (mod && e.key === ",") { e.preventDefault(); openSettings(); return; }
  if (mod && e.key === "/") { e.preventDefault(); if ($(".keys-sheet")) closeLayer(); else shortcutsSheet(); return; }
  if (mod && !e.altKey && (e.key === "=" || e.key === "+" || e.key === "-" || e.key === "0")) {
    e.preventDefault(); stepTextSize(e.key === "0" ? 0 : e.key === "-" ? -1 : 1); return;
  }
  if (layerOpen()) { if (e.key === "Escape") closeLayer(); else menuKey(e); return; }
  if (e.key === "Escape" && $("#app").classList.contains("side-open")) { e.preventDefault(); sideOpen(false); return; }
  if (S.compose) {
    if (mod && e.key === "Enter") { e.preventDefault(); sendCompose(); return; }
    if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); if (!S.compose.busy) saveDraft().catch(fail); return; }
    if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); closeCompose(); return; }
    // the mailbox's single keys (Backspace, R, J...) never act while a mail is being written, even when
    // focus fell to the page after a click on a button
    return;
  }
  // in a text box Cmd+Z stays the text's own undo; a compose never gets here
  if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "z" && !typing(e)) { e.preventDefault(); undoMove(); return; }
  if (mod && e.key.toLowerCase() === "a" && !typing(e) && !S.compose) { e.preventDefault(); selectAll(); return; }
  if (typing(e) || mod || e.altKey) return;
  const id = S.focus || S.sel;
  const k = e.key;
  if (S.multi.size > 1) {
    const ids = [...S.multi];
    if (k === "Escape") { e.preventDefault(); clearMulti(); }
    else if (k === "e") { e.preventDefault(); moveMail(ids, "archive"); }
    else if (k === "#" || k === "Delete" || k === "Backspace") { e.preventDefault(); if (!ids.map(rowOf).every((r) => r?.folder === "trash")) moveMail(ids, "trash"); }
    else if (k === "v") { e.preventDefault(); moveKey(ids); }
    else if (k === "u") { e.preventDefault(); toggleUnread(); }
    else if (k === "s") { e.preventDefault(); toggleFlag(); }
    else if (k === "j" || k === "ArrowDown" || k === "k" || k === "ArrowUp") { e.preventDefault(); S.multi.clear(); step(k === "j" || k === "ArrowDown" ? 1 : -1); }
    else if (k === "c") { e.preventDefault(); openCompose({ mode: "new" }); }
    else if (k === "/") { e.preventDefault(); openSearch(); }
    return;
  }
  if (k === "j" || k === "ArrowDown") { e.preventDefault(); step(1); }
  else if (k === "k" || k === "ArrowUp") { e.preventDefault(); step(-1); }
  else if (k === "c") { e.preventDefault(); openCompose({ mode: "new" }); }
  else if (k === "/") { e.preventDefault(); openSearch(); }
  else if (!S.thread) return;
  else if (k === "r") { e.preventDefault(); openCompose({ mode: "reply", id }); }
  else if (k === "a") { e.preventDefault(); openCompose({ mode: "replyall", id }); }
  else if (k === "f") { e.preventDefault(); openCompose({ mode: "forward", id }); }
  else if (k === "e") { e.preventDefault(); const mv = moveId(); if (S.thread.rows.find((x) => x.id === mv)?.folder !== "archive") moveMail([mv], "archive"); }
  else if (k === "#" || k === "Delete" || k === "Backspace") { e.preventDefault(); const mv = moveId(); if (S.thread.rows.find((x) => x.id === mv)?.folder !== "trash") moveMail([mv], "trash"); }
  else if (k === "v") { e.preventDefault(); moveKey([moveId()]); }
  else if (k === "u") { e.preventDefault(); toggleUnread(); }
  else if (k === "s") { e.preventDefault(); toggleFlag(); }
  else if (k === "Escape" && S.query) { $("#search").value = ""; onSearch(true); }
}
document.addEventListener("keydown", onKey);
$("#pane").addEventListener("scroll", (e) => $("#toolbar").classList.toggle("lined", e.target.scrollTop > 0), { passive: true });

// ---------------------------------------------------------------- list width

// While a column edge is dragged, a text field with the caret in it is let go and given back on release.
// In the Mac app (WebKit) a focused field has its caret placed again, and the input method asked where it
// is, on every frame the layout changes: dragging with the search open was very slow (21st Nov 2026).
const dragFocus = {
  held: null, start: 0, end: 0,
  take() {
    const a = document.activeElement;
    if (!a || !a.matches?.("input, textarea")) return;
    this.held = a; this.start = a.selectionStart; this.end = a.selectionEnd;
    a.blur();
  },
  give() {
    const a = this.held;
    this.held = null;
    if (!a || !a.isConnected) return;
    a.focus({ preventScroll: true });
    try { a.setSelectionRange(this.start, this.end); } catch { /* not a text field */ }
  },
};

(() => {
  const sp = $("#splitter"), app = $("#app");
  // one width per screen frame; the open mail keeps its width while the line moves (laying a long mail out
  // again on every mouse move is what made this slow) and fits the new width once, on release
  sp.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const x0 = e.clientX, w0 = $("#list-col").offsetWidth;
    let x = x0, q = 0;
    const kids = [...$("#pane").children];
    for (const k of kids) k.style.width = k.offsetWidth + "px";
    dragFocus.take();
    app.classList.add("resizing");
    const apply = () => { q = 0; app.style.setProperty("--list-w", Math.max(280, Math.min(600, w0 + x - x0)) + "px"); };
    const move = (ev) => { x = ev.clientX; if (!q) q = requestAnimationFrame(apply); };
    const up = () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      if (q) { cancelAnimationFrame(q); apply(); }
      app.classList.remove("resizing");
      for (const k of kids) k.style.width = "";
      dragFocus.give();
      api("prefs", { list_width: $("#list-col").offsetWidth }).catch(() => {});
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  });
})();

// the sidebar's width: drag its right edge (180 to 360 pixels); a double-click goes back to the default width
(() => {
  const grip = $("#side-grip"), app = $("#app");
  const SIDE_MIN = 180, SIDE_MAX = 360;
  grip.addEventListener("mousedown", (e) => {
    if (e.button) return;
    e.preventDefault();
    const x0 = e.clientX, w0 = $(".side").offsetWidth;
    let x = x0, q = 0;
    const kids = [...$("#pane").children];
    for (const k of kids) k.style.width = k.offsetWidth + "px";
    dragFocus.take();
    app.classList.add("side-sizing");
    const apply = () => { q = 0; app.style.setProperty("--side-pick", Math.round(Math.max(SIDE_MIN, Math.min(SIDE_MAX, w0 + x - x0))) + "px"); };
    const move = (ev) => { x = ev.clientX; if (!q) q = requestAnimationFrame(apply); };
    const up = () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      if (q) { cancelAnimationFrame(q); apply(); }
      app.classList.remove("side-sizing");
      for (const k of kids) k.style.width = "";
      dragFocus.give();
      if (x === x0) return;
      PREFS.side_width = $(".side").offsetWidth;
      api("prefs", { side_width: PREFS.side_width }).catch(() => {});
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  });
  grip.addEventListener("dblclick", () => {
    app.style.removeProperty("--side-pick");
    PREFS.side_width = 0;
    api("prefs", { side_width: 0 }).catch(() => {});
  });
})();

// ---------------------------------------------------------------- status

// new mail while the window is not in front: the browser's own notice, and a click on it opens the mail
let noticeAsked = false; // Settings just switched notices on
const canNotice = () => "Notification" in window && Notification.permission === "granted" && PREFS.notify !== false;
function askNotice() {
  if (!("Notification" in window) || Notification.permission !== "default" || PREFS.notify === false) return;
  try { Notification.requestPermission()?.catch?.(() => {}); } catch { /* not in this window */ }
}
const inFront = () => document.hasFocus() && !document.hidden;
async function openNews(one) {
  await openFolder("inbox");
  if (one && rowOf(one.id)) selectRow(one.id);
}
function notice(live, one) {
  try {
    const names = [...new Set(live.map((x) => who(x.from)))];
    const n = new Notification(one ? who(one.from) : t("n_new_mail", live.length),
      { body: one ? one.subject || t("no_subject") : names.slice(0, 3).join(", "), tag: "ragdoll-news" });
    n.onclick = () => { window.focus(); n.close(); openNews(one); };
  } catch { /* the line at the bottom still shows */ }
}
async function refreshCounts() {
  try { const st = await api("status", { focus: inFront(), web_notice: canNotice() }); applyStatus(st); } catch { /* next poll */ }
}
// new mail: one short line at the bottom, with a way to open it
function showNews(news) {
  const fresh = (news || []).filter((x) => x.n > S.newsN);
  if (!fresh.length) return;
  S.newsN = Math.max(...fresh.map((x) => x.n));
  const now = Date.now() / 1000, live = fresh.filter((x) => now - x.at < 90);
  if (PREFS.notify === false || !live.length) return;
  const one = live.length === 1 ? live[0] : null;
  toast(one ? `${who(one.from)}: ${one.subject || t("no_subject")}` : t("n_new_mail", live.length), {
    id: "news", ms: 8000,
    action: { label: t("open"), run: () => openNews(one) },
  });
  if (!inFront() && canNotice()) notice(live, one);
}
// a hand-off from ragdoll in a terminal or an assistant: show this mail, or a draft is ready
async function openMail(id) {
  const key = id.slice(0, id.lastIndexOf(":"));
  await openFolder(key);
  if (rowOf(id)) selectRow(id); else openThread(id);
}
async function showAsks(asks) {
  const now = Date.now() / 1000;
  const fresh = (asks || []).filter((x) => x.n > S.asksN);
  if (!fresh.length) return;
  S.asksN = Math.max(...fresh.map((x) => x.n));
  for (const x of fresh.filter((x) => now - x.at < 600)) {
    if (x.kind === "open") await openMail(x.id);
    else toast(t("draft_ready", x.subject || t("no_subject")), { id: "ask", ms: 12000, action: { label: t("open"), run: () => openMail(x.id) } });
  }
}
window.ragdollPoll = () => refreshCounts();
function applyStatus(st) {
  S.boot.folders = st.folders;
  S.update = st.update;
  const wasSyncing = S.syncing;
  S.syncing = st.syncing;
  renderNav();
  S.status = st;
  drawProblem();
  if (st.rev !== S.rev) { S.rev = st.rev; loadList({ quiet: true }); }
  else if (wasSyncing !== S.syncing && !S.rows.length) renderRows();
  showNews(st.news);
  showAsks(st.asks);
}

// ---- a problem with the mailbox: a small card floating at the foot of the list (it never pushes the list),
// shaped by what the person can do about it:
//   offline / server not answering (fixes itself): a quiet line, when mail last came in, the next try, "Try now"
//   sign-in, no password, no account (needs the person): what is wrong and one button straight to the field
//   anything else the server said: a neutral card, "Retry" and "Copy details" (the server's own words)
// The backend's status says which (error_kind), when mail last came in (last_sync) and the next try (retry_at).
const PROBLEM_KIND = [[/^(Sign-in failed)/, "auth"], [/^(No password saved|No account yet)/, "config"],
  [/^(Can't find the mail server|The mail server did not answer|Can't reach the mail server)/, "offline"]];
const problemKind = (st) => st.error_kind || PROBLEM_KIND.find(([re]) => re.test(st.error))?.[1] || "server";
const prob = { key: null, dismissed: null, tryAt: 0, timer: 0 };
function syncedAt(ts) { return dayKey(ts * 1000) === dayKey(Date.now()) ? fmt(ts, HM) : shortTime(ts); }
function retryNow() {
  prob.tryAt = Date.now();
  drawProblem();
  api("sync").catch(() => {});
  setTimeout(refreshCounts, 1500);
  setTimeout(refreshCounts, 4000);
}
function drawProblem() {
  const st = S.status || {}, b = $("#banner"), col = $("#list-col");
  const kind = st.error ? problemKind(st) : null;
  const key = st.error ? kind + "|" + st.error : null;
  $("#account").classList.toggle("alert", !!key);
  clearTimeout(prob.timer);
  if (!key || prob.dismissed === key) {
    if (!b.hidden && !b.classList.contains("out")) {
      b.classList.add("out");
      col.classList.remove("has-banner");
      setTimeout(() => { if (b.classList.contains("out")) { b.hidden = true; b.classList.remove("out"); } }, REDUCED.matches ? 0 : 180);
    }
    prob.key = prob.sig = null;
    return;
  }
  // the next try, counted down; a spinner while it runs
  const busy = st.syncing || Date.now() - prob.tryAt < 2500;
  const left = st.retry_at ? Math.ceil(st.retry_at - Date.now() / 1000) : null;
  const next = busy ? t("st_retrying") : left > 0 ? t("st_retry_in", left) : left != null ? t("st_retrying") : "";
  const meta = [st.last_sync ? t("st_last", syncedAt(st.last_sync)) : "", kind === "offline" || kind === "server" ? next : ""].filter(Boolean).join(" · ");
  let ic, tone = "", title, sub = "", acts = [];
  const settingsAt = (focus) => () => openSettings({ tab: "account", focus });
  if (kind === "offline") {
    const net = !navigator.onLine || /^Can't find the mail server/.test(st.error);
    ic = net ? "wifi-off" : "cloud-off"; tone = "quiet";
    title = t(net ? "st_offline" : "st_noreply"); sub = t("st_still");
    acts = [el("button", { class: "link-btn", onclick: retryNow, disabled: busy }, t("st_try_now"))];
  } else if (kind === "auth" || kind === "config") {
    const k = /^No account yet/.test(st.error) ? "b_acct" : /^No password saved/.test(st.error) ? "b_pw" : "b_signin";
    ic = k === "b_acct" ? "circle-user-round" : "key-round"; tone = "warn";
    title = t(k + "_title"); sub = STR[k + "_sub"] || "";
    acts = [el("button", { class: "btn primary", onclick: settingsAt(k === "b_acct" ? "user" : "password") }, k === "b_acct" ? t("b_acct_btn") : t("st_enter_pw"))];
  } else {
    ic = "triangle-alert";
    title = t("st_server"); sub = tr(st.error);
    acts = [el("button", { class: "btn", onclick: retryNow, disabled: busy }, t("st_retry")),
      iconBtn("copy", t("st_details"), () => copyText(st.error), { cls: "tiny" })];
  }
  if (st.retry_at || busy) prob.timer = setTimeout(drawProblem, 1000);
  // drawn again only when more than the countdown changed (a hovered button stays as it is)
  const sig = JSON.stringify([key, title, sub, !!meta, busy, LANG]);
  if (sig === prob.sig && !b.hidden && !b.classList.contains("out")) {
    const m = $(".banner-meta", b);
    if (m) m.textContent = " · " + meta;
    col.style.setProperty("--banner-h", b.offsetHeight + "px");
    return;
  }
  prob.sig = sig;
  b.className = "banner" + (tone ? " " + tone : "");
  b.replaceChildren(
    el("span", { class: "banner-ic", html: icon(busy && kind !== "auth" && kind !== "config" ? "loader-circle" : ic, busy && kind !== "auth" && kind !== "config" ? "spin" : "") }),
    el("div", { class: "banner-text", title: kind === "server" ? tr(st.error) : null },
      el("div", { class: "banner-title" }, el("b", {}, title), meta ? el("span", { class: "banner-meta" }, " · " + meta) : null),
      sub ? el("span", { class: "banner-sub" }, sub) : null),
    el("div", { class: "banner-acts" }, ...acts),
    iconBtn("x", t("st_dismiss"), () => { prob.dismissed = key; drawProblem(); }, { cls: "tiny banner-x" }));
  if (b.hidden) { b.hidden = false; if (!REDUCED.matches) b.classList.add("in"); setTimeout(() => b.classList.remove("in"), 260); }
  prob.key = key;
  // the list keeps room for the card at its foot, so the last mail can scroll out from under it
  col.classList.add("has-banner");
  col.style.setProperty("--banner-h", b.offsetHeight + "px");
}
// Homebrew and a clone update from a terminal; the app from the download page (#76)
function offerUpdate(up) {
  if (up.command) toast(t("run_cmd", up.command), { ms: 10000, action: { label: t("copy"), run: () => copyText(up.command) } });
  else api("open_url", { url: up.url }).catch(fail);
}
$("#update").addEventListener("click", () => { if (S.update) offerUpdate(S.update); });
async function checkUpdates() {
  toast(t("upd_checking"), { id: "upd" });
  let r;
  try { r = await api("check_update"); } catch (e) { for (const n of $$('.toast[data-id="upd"]', $("#toasts"))) n.replaceWith(); return fail(e); }
  S.update = r.update;
  renderNav();
  if (r.update) toast(t("upd_found", "v" + r.update.version), { id: "upd", ms: 10000, action: { label: t("upd_get"), run: () => offerUpdate(r.update) } });
  else toast(t("upd_latest", "v" + r.version), { id: "upd" });
}

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
  S.newsN = Math.max(0, ...(boot.news || []).map((x) => x.n));
  S.asksN = 0;        // a mail asked for before the app was open is still shown
  applyTheme(boot.theme);
  $("#app").hidden = false;
  $("#setup").hidden = true;
  document.title = "Ragdoll Mail";
  $("#compose-btn").innerHTML = icon("square-pen");
  $("#compose-btn").dataset.tip = t("compose");
  $("#compose-btn").dataset.key = "C";
  $("#compose-btn").onclick = () => { sideOpen(false); openCompose({ mode: "new" }); };
  $("#here-btn").onclick = () => sideOpen(true);
  $("#side-scrim").onclick = () => sideOpen(false);
  placeCompose();
  $("#account").onclick = accountMenu;
  $("#search").placeholder = t("search");
  Object.assign($("#search-btn").dataset, { tip: t("search"), key: MAC ? "⌘K" : "Ctrl K" });
  $("#search-btn").setAttribute("aria-label", t("search"));
  document.querySelectorAll("[data-i]").forEach((n) => { n.innerHTML = svg(n.dataset.i); });
  renderNav();
  showEmpty();
  loadList();
  refreshCounts();
  // a hidden page still asks now and then, so its notice can show
  let ticks = 0;
  if (!start.timer) start.timer = setInterval(() => { if (!document.hidden || (canNotice() && ++ticks % 4 === 0)) refreshCounts(); }, 5000);
  addEventListener("pointerdown", askNotice, { once: true });
}

(async function boot() {
  let b;
  for (let k = 0; ; k++) {
    try { b = await api("boot"); break; }
    catch (e) { if (k > 20) { document.body.textContent = e.message; return; } await sleep(300); }
  }
  applyTheme(b.theme);
  PREFS = b.prefs || {};
  if (!b.prefs) try { PREFS = await api("prefs", {}); } catch { /* defaults */ }
  setLocale(PREFS);
  if (PREFS.list_width) $("#app").style.setProperty("--list-w", PREFS.list_width + "px");
  if (PREFS.side_width) $("#app").style.setProperty("--side-pick", PREFS.side_width + "px");
  if (!b.configured) showSetup(b); else start(b);
})();
