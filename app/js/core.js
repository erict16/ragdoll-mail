// The basics every file uses: the language, small DOM helpers, and api() to call the app's server.
import { LANGS } from "../i18n.js";
import { ICONS } from "../icons.js";

export const TOKEN = (() => {
  const t = new URLSearchParams(location.hash.slice(1)).get("t");
  try {
    if (t) sessionStorage.setItem("ragdoll-token", t);
    return t || sessionStorage.getItem("ragdoll-token") || "";
  } catch { return t || ""; }
})();
if (location.hash) history.replaceState(null, "", location.pathname);

export const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const WIN = /Win/.test(navigator.platform || navigator.userAgent);
export const MOD = MAC ? "⌘" : "Ctrl+";

// language: a saved choice, or the system's when it is one of ours
export let LANG = "en", LOCALE = undefined, TZ = undefined, STR = LANGS.en;
export const FMT = new Map();      // date formatters made so far; a new language or time zone empties it
export const SYS_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; } })();
export function systemLang() {
  for (const l of navigator.languages?.length ? navigator.languages : [navigator.language || "en"]) {
    const x = l.toLowerCase();
    if (x.startsWith("zh")) return /hant|-tw|-hk|-mo/.test(x) ? "zh-Hant" : "zh-Hans";
    const base = x.split("-")[0];
    if (LANGS[base]) return base;
  }
  return "en";
}
export function setLocale(prefs = {}) {
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
export const t = (k, ...a) => { let s = STR[k] ?? k; for (const x of a) s = s.replace("%s", x); return s; };

// a sentence from the server or the send check, in the chosen language when we know it
const MSGS = [
  [/^The app's background service/, "err_bg"],
  [/^Sign-in failed\./, "err_signin"], [/^No password saved\./, "err_no_pw"], [/^No account yet\./, "err_no_account"],
  [/^Can't find the mail server\./, "err_dns"], [/^The mail server did not answer in time\./, "err_timeout"],
  [/^Secure connection failed \((.*)\)\. Check/, "err_ssl"], [/^The mail server refused the connection\./, "err_refused"],
  [/^Can't reach the mail server \((.*)\)\.$/, "err_reach"], [/^The mail server said: (.*)$/s, "err_server"],
  [/^This mail is no longer here/, "err_gone"], [/^The draft is gone\./, "err_draft_gone"],
  [/^An attachment is missing: (.*)$/, "err_att_missing"], [/^That time has already passed\./, "err_past"],
  [/^To is empty/, "p_to_empty"], [/^the sender is also a recipient/, "p_self"], [/^(.*) is not in To or Cc/, "p_not_cc"],
  [/^the subject is empty/, "p_no_subject"], [/^garbled characters \(.\) in: (.*)$/, "p_garbled"],
  [/^placeholder\(s\) left in the text: ([^;]*)/, "p_holes"], [/^the text mentions an attachment/, "p_att"],
  [/^(\d+) image\(s\) in the mail have no image part/, "p_img"],
];
export function tr(msg) {
  msg = String(msg ?? "");
  for (const [re, k] of MSGS) { const m = msg.match(re); if (m) return t(k, ...m.slice(1)); }
  return msg;
}

export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const svg = (n) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ""}</svg>`;
export const icon = (n, cls = "") => `<span class="i ${cls}">${svg(n)}</span>`;
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function el(tag, attrs = {}, ...kids) {
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
export function iconBtn(name, tip, onclick, extra = {}) {
  return el("button", { class: "icon-btn" + (extra.cls ? " " + extra.cls : ""), "data-tip": tip, "data-key": extra.key, html: icon(name), onclick, disabled: extra.disabled, "aria-label": tip });
}

export async function api(name, args = {}) {
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
