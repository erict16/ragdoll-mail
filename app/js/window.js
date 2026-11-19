// The window's top bar on Windows. There is no system title bar there: the page runs to the top edge and this
// file draws the minimise, maximise and close buttons. (On the Mac the system's own three buttons stay.)
import { $, api, el, sleep, svg, t, WIN } from "./core.js";

export async function windowBar() {
  if (!WIN || windowBar.on) return;
  windowBar.on = true;
  // the app says whether it took the title bar away; if it could not, the system's bar and buttons are still there
  let own = false;
  for (let k = 0; k < 12 && !own; k++) {
    try { own = (await api("window", { do: "state" })).own; } catch { /* the server is not up yet */ }
    if (!own) await sleep(250);
  }
  if (!own) return;
  const ask = (what) => api("window", { do: what }).catch(() => {});
  const btn = (what, ic, label, cls) => el("button", { class: cls, "aria-label": t(label), html: svg(ic), onclick: () => ask(what) });
  const max = btn("max", "square", "win_max");
  $("#win-ctl").append(btn("min", "minus", "win_min"), max, btn("close", "x", "close", "close"));
  $("#win-ctl").hidden = false;
  // the top edge still resizes the window
  $("#win-edge").hidden = false;
  $("#win-edge").addEventListener("mousedown", (e) => { if (e.button === 0) { e.preventDefault(); ask("top"); } });
  // the empty parts of the top bar move the window; a double click makes it fill the screen or go back.
  // Windows does the move itself (so snapping works); it starts once the mouse really moves.
  document.addEventListener("mousedown", (e) => {
    const bar = e.target.closest(".toolbar, .side-top, .list-head") || (e.clientY < 40 && e.target.matches("#setup, #setup > *"));
    if (e.button !== 0 || !bar || e.target.closest("button, input, a, select, label, [role=button]")) return;
    e.preventDefault();
    if (e.detail > 1) return void ask("max");
    const x = e.screenX, y = e.screenY;
    const move = (ev) => { if (Math.abs(ev.screenX - x) + Math.abs(ev.screenY - y) > 3) { stop(); ask("drag"); } };
    const stop = () => { removeEventListener("mousemove", move); removeEventListener("mouseup", stop); };
    addEventListener("mousemove", move); addEventListener("mouseup", stop);
  });
  const sync = async () => {
    let full = false;
    try { full = !!(await api("window", { do: "state" })).max; } catch { /* keeps the plain picture */ }
    document.documentElement.classList.toggle("maxed", full);
    max.innerHTML = svg(full ? "copy" : "square");
    max.setAttribute("aria-label", t(full ? "win_restore" : "win_max"));
  };
  addEventListener("resize", sync);
  sync();
  document.documentElement.classList.add("own-bar");
}
