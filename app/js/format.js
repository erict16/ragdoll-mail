// Dates, times and sizes, in the user's language and time zone.
import { FMT, LOCALE, SYS_TZ, t, TZ } from "./core.js";
import { S } from "./state.js";

export function fmt(ts, opts) {
  const key = JSON.stringify(opts);
  let f = FMT.get(key);
  if (!f) {
    try { f = new Intl.DateTimeFormat(LOCALE, { ...opts, timeZone: TZ }); } catch { f = new Intl.DateTimeFormat(undefined, opts); }
    FMT.set(key, f);
  }
  return f.format(new Date(ts * 1000));
}
// the wall clock in the chosen time zone: {y, m, d, h, mi, wd (0 = Sunday)}
export function zparts(ms) {
  const key = "parts";
  let f = FMT.get(key);
  if (!f) { f = new Intl.DateTimeFormat("en-US", { timeZone: TZ || SYS_TZ, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", weekday: "short" }); FMT.set(key, f); }
  const p = Object.fromEntries(f.formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
  return { y: +p.year, m: +p.month, d: +p.day, h: +p.hour % 24, mi: +p.minute, wd: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(p.weekday) };
}
// Unix seconds for a wall-clock time in the chosen time zone
export function zepoch(y, m, d, h, mi) {
  const want = Date.UTC(y, m - 1, d, h, mi);
  let guess = want;
  for (let k = 0; k < 3; k++) {
    const p = zparts(guess);
    guess = want - (Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi) - guess);
  }
  return Math.round(guess / 1000);
}
export const dayKey = (ms) => { const p = zparts(ms); return p.y * 10000 + p.m * 100 + p.d; };
export const HM = { hour: "2-digit", minute: "2-digit" };
export function shortTime(ts) {
  if (!ts) return "";
  const ms = ts * 1000, now = Date.now(), k = dayKey(ms);
  if (k === dayKey(now)) return fmt(ts, HM);
  if (k === dayKey(now - 86400e3)) return t("yesterday");
  if (now - ms < 6 * 86400e3 && ms < now) return fmt(ts, { weekday: "short" });
  if (zparts(ms).y === zparts(now).y) return fmt(ts, { month: "short", day: "numeric" });
  return fmt(ts, { year: "numeric", month: "numeric", day: "numeric" });
}
// a time to come (a scheduled send): "18:00", "Tomorrow 08:00", "Mon 08:00", "12 Dec 08:00"
export function laterTime(ts) {
  const ms = ts * 1000, now = Date.now(), k = dayKey(ms);
  if (k === dayKey(now)) return fmt(ts, HM);
  if (k === dayKey(now + 86400e3)) return t("tomorrow") + " " + fmt(ts, HM);
  if (ms - now < 6 * 86400e3) return fmt(ts, { weekday: "short", ...HM });
  return fmt(ts, { month: "short", day: "numeric", ...HM });
}
export function longTime(ts) {
  if (!ts) return "";
  return fmt(ts, { weekday: "short", year: "numeric", month: "short", day: "numeric", ...HM });
}
export function size(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return Math.round(n / 1024) + " KB";
  return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + " MB";
}
export function fileIcon(name) {
  const x = (name.split(".").pop() || "").toLowerCase();
  if (["pdf", "doc", "docx", "txt", "rtf", "odt", "md", "pages"].includes(x)) return "file-text";
  if (["xls", "xlsx", "csv", "numbers", "ods"].includes(x)) return "file-spreadsheet";
  if (["png", "jpg", "jpeg", "gif", "webp", "heic", "bmp", "tif", "tiff", "svg"].includes(x)) return "file-image";
  if (["zip", "rar", "7z", "gz", "tar", "tgz"].includes(x)) return "file-archive";
  return "file";
}
export const nameOf = (p) => (p && (p.name || p.addr)) || "";
export function who(p) { return p && p.addr === S.boot?.user ? t("me") : nameOf(p); }
export function initials(p) {
  const s = (p?.name || p?.addr || "?").trim();
  if (/^[㐀-鿿]/.test(s)) return s[0];
  const parts = s.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}
