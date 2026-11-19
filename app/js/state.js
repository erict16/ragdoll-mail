// The one object that holds what is on screen, and the saved preferences.
import { api, t } from "./core.js";

export const S = {
  boot: null, folder: "inbox", rows: [], more: false, query: "", loadingMore: false,
  sel: null, thread: null, focus: null, compose: null, rev: 0, update: null, error: null,
  theme: "system", showImages: new Set(), syncing: false, sched: null, multi: new Set(), anchor: null,
};
export let PREFS = {};
export function setPrefs(p) { PREFS = p; }
export const undoSeconds = () => (Number.isInteger(PREFS.undo) ? PREFS.undo : 5);
// reading text size and the default font for new mail
export const TEXT_SIZES = [12, 13, 14, 15, 16, 18, 20];
export const textSize = () => (TEXT_SIZES.includes(PREFS.text_size) ? PREFS.text_size : 14);
export const FONT_SIZES = [12, 13, 14, 16, 18];
export const FONTS = [
  ["system", ""], ["arial", "Arial, Helvetica, sans-serif"], ["helvetica", "Helvetica, Arial, sans-serif"],
  ["georgia", "Georgia, serif"], ["times", "'Times New Roman', Times, serif"], ["verdana", "Verdana, Geneva, sans-serif"],
  ["courier", "'Courier New', Courier, monospace"], ["yahei", "'Microsoft YaHei', 微软雅黑, sans-serif"],
  ["pingfang", "'PingFang SC', 苹方, sans-serif"], ["simsun", "SimSun, 宋体, serif"],
];
const FONT_NAMES = { arial: "Arial", helvetica: "Helvetica", georgia: "Georgia", times: "Times New Roman", verdana: "Verdana",
  courier: "Courier New", yahei: "Microsoft YaHei", pingfang: "PingFang SC", simsun: "SimSun" };
const SAFE_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', Helvetica, Arial, sans-serif";
export const fontStack = (k) => FONTS.find(([x]) => x === k)?.[1] || SAFE_FONT;
export const fontLabel = (k) => FONT_NAMES[k] || t("system");
export const mailFont = () => fontStack(PREFS.font || "system");
export const mailSize = () => (FONT_SIZES.includes(PREFS.font_size) ? PREFS.font_size : 14);
export const savePref = (patch) => { Object.assign(PREFS, patch); api("prefs", patch).catch(() => {}); };
export const FOLDER_ICON = { inbox: "inbox", flagged: "star", drafts: "file", scheduled: "clock", sent: "send", archive: "archive", trash: "trash-2", junk: "octagon-alert", snoozed: "alarm-clock" };
// the name of a folder in the sidebar: a fixed one in the user's language, one of the user's own as it is
const folderOf = (key) => S.boot?.folders.find((f) => f.key === key);
export const folderName = (key) => folderOf(key)?.name || t(key);
export const binned = (r) => r?.folder === "trash" || r?.folder === "junk";
