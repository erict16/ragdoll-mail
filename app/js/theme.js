// Light and dark.
import { api } from "./core.js";
import { S } from "./state.js";
import { REDUCED } from "./ui.js";
import { refreshFrames } from "./frames.js";

const darkMQ = matchMedia("(prefers-color-scheme: dark)");
export const isDark = () => document.documentElement.dataset.theme === "dark";
export function applyTheme(theme) {
  S.theme = theme || "system";
  const dark = S.theme === "dark" || (S.theme === "system" && darkMQ.matches);
  const root = document.documentElement, was = root.dataset.theme;
  if (was && was !== (dark ? "dark" : "light") && !REDUCED.matches) {
    root.classList.add("theming");
    clearTimeout(applyTheme.timer);
    applyTheme.timer = setTimeout(() => root.classList.remove("theming"), 320);
  }
  root.dataset.theme = dark ? "dark" : "light";
  if (was && was !== document.documentElement.dataset.theme) refreshFrames();
  syncWindowTheme();
}
// the native title bar (Windows caption, macOS traffic lights) follows the app theme, not only the system's
export function syncWindowTheme() {
  if (!window.pywebview) return;
  const css = getComputedStyle(document.documentElement);
  api("window_theme", {
    dark: document.documentElement.dataset.theme === "dark",
    bg: css.getPropertyValue("--bg").trim(),
    text: css.getPropertyValue("--text").trim(),
  }).catch(() => {});
}
darkMQ.addEventListener("change", () => applyTheme(S.theme));
