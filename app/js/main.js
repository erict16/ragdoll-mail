// Start: ask the server what to show, then draw the app (or the first-run setup).
import { $, api, icon, MAC, setLocale, sleep, svg, t, WIN } from "./core.js";
import { PREFS, S, setPrefs } from "./state.js";
import { applyTheme, syncWindowTheme } from "./theme.js";
import { windowBar } from "./window.js";
import "./format.js";
import "./ui.js";
import { accountMenu, renderNav } from "./sidebar.js";
import { loadList } from "./list.js";
import "./actions.js";
import "./search.js";
import { showEmpty } from "./reader.js";
import "./frames.js";
import { openCompose } from "./compose.js";
import "./editor.js";
import "./templates.js";
import "./later.js";
import "./settings.js";
import { showSetup } from "./setup.js";
import "./keys.js";
import "./splitter.js";
import { refreshCounts, watchStatus } from "./status.js";

document.documentElement.classList.add(MAC ? "mac" : WIN ? "win" : "other");
function fullScreenCheck() {
  document.documentElement.classList.toggle("fullscreen", innerHeight >= screen.height - 1 && innerWidth >= screen.width - 1);
}
addEventListener("resize", fullScreenCheck);
function nativeWindow() {
  document.documentElement.classList.add("native");
  syncWindowTheme();
  windowBar();
}
if (window.pywebview) nativeWindow();
else window.addEventListener("pywebviewready", nativeWindow);

export function start(boot) {
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
  $("#search").placeholder = t("search");
  $("#banner-btn").textContent = t("settings");
  document.querySelectorAll("[data-i]").forEach((n) => { n.innerHTML = svg(n.dataset.i); });
  renderNav();
  showEmpty();
  loadList();
  refreshCounts().then(watchStatus);
}

(async function boot() {
  let b;
  for (let k = 0; ; k++) {
    try { b = await api("boot"); break; }
    catch (e) { if (k > 20) { document.body.textContent = e.message; return; } await sleep(300); }
  }
  applyTheme(b.theme);
  setPrefs(b.prefs || {});
  if (!b.prefs) try { setPrefs(await api("prefs", {})); } catch { /* defaults */ }
  setLocale(PREFS);
  if (PREFS.list_width) document.documentElement.style.setProperty("--list-w", PREFS.list_width + "px");
  if (PREFS.side_width) document.documentElement.style.setProperty("--side-user", PREFS.side_width + "px");
  if (!b.configured) showSetup(); else start(b);
})();
