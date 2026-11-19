// Toasts, tooltips, menus and sheets.
import { $, $$, el, esc, icon } from "./core.js";

// motion: everything leaves with a short fade; nothing waits when the system asks for less motion
export const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");
const EASE = "cubic-bezier(.2, .8, .2, 1)";
function leave(node, ms = 150) {
  if (!node || !node.isConnected || node.classList.contains("out")) return;
  if (REDUCED.matches) return node.remove();
  node.classList.add("out");
  setTimeout(() => node.remove(), ms);
}

export function toast(text, opts = {}) {
  const box = $("#toasts");
  // a toast with an id takes the place of the one before it (text size steps, for one)
  if (opts.id) for (const old of $$(`.toast[data-id="${opts.id}"]`, box)) old.replaceWith();
  const node = el("div", { "data-id": opts.id, class: "toast" + (opts.error ? " err" : ""), role: "status" },
    opts.error ? el("span", { class: "toast-ic", html: icon("triangle-alert") }) : null,
    el("span", { class: "toast-text" }, text));
  let done = false;
  const close = () => { if (done) return; done = true; leave(node, 180); };
  if (opts.action) node.append(el("button", { class: "toast-act", onclick: () => { close(); opts.action.run(); } }, opts.action.label));
  if (opts.bar) {
    const bar = el("span", { class: "toast-bar" });
    node.append(bar);
    if (!REDUCED.matches) bar.animate([{ transform: "scaleX(1)" }, { transform: "scaleX(0)" }], { duration: opts.bar, easing: "linear", fill: "forwards" });
  }
  box.append(node);
  const ms = opts.ms ?? (opts.error ? 7000 : 3200);
  if (ms) setTimeout(close, ms);
  return { close, node, set: (s) => { node.querySelector(".toast-text").textContent = s; } };
}
export const fail = (e) => toast(e?.message || String(e), { error: true });

let tipEl = null, tipTimer = null;
// narrow windows: the sidebar turns into an icon rail (see style.css)
const RAIL = matchMedia("(max-width: 860px)");
document.addEventListener("mouseover", (e) => {
  const b = e.target.closest?.("[data-tip]");
  clearTimeout(tipTimer);
  if (tipEl) { tipEl.remove(); tipEl = null; }
  if (!b || b.disabled) return;
  const side = b.dataset.rail != null;
  if (side && !RAIL.matches) return;
  tipTimer = setTimeout(() => {
    const r = b.getBoundingClientRect();
    tipEl = el("div", { class: "tip", html: esc(b.dataset.tip) + (b.dataset.key ? `<kbd>${esc(b.dataset.key)}</kbd>` : "") });
    document.body.append(tipEl);
    const w = tipEl.offsetWidth;
    tipEl.style.left = Math.max(6, Math.min(innerWidth - w - 6, r.left + r.width / 2 - w / 2)) + "px";
    tipEl.style.top = (r.bottom + 6 + 24 > innerHeight ? r.top - 30 : r.bottom + 6) + "px";
    if (side) { tipEl.style.left = r.right + 8 + "px"; tipEl.style.top = r.top + r.height / 2 - tipEl.offsetHeight / 2 + "px"; }
  }, side ? 250 : 550);
});
document.addEventListener("mousedown", () => { clearTimeout(tipTimer); if (tipEl) { tipEl.remove(); tipEl = null; } }, true);

export function closeLayer() { for (const n of [...$("#layer").children]) leave(n, 160); }
export function menu(anchor, items, { above = false } = {}) {
  closeLayer();
  const m = el("div", { class: "menu" + (above ? " above" : ""), role: "menu" });
  for (const it of items) {
    if (it === "-") m.append(el("hr"));
    else if (it.note) m.append(el("div", { class: "menu-note" }, it.note));
    else m.append(el("button", { onclick: () => { closeLayer(); it.run(); }, html: icon(it.icon) + esc(it.label) +
      (it.key ? `<span class="grow"></span><kbd>${esc(it.key)}</kbd>` : it.hint ? `<span class="grow"></span><span class="hint">${esc(it.hint)}</span>` : "") }));
  }
  const catcher = el("div", { style: "position:fixed;inset:0", onmousedown: closeLayer });
  $("#layer").append(catcher, m);
  const r = anchor.getBoundingClientRect();
  m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
  m.style.top = (above ? r.top - m.offsetHeight - 6 : r.bottom + 6) + "px";
}
export function sheet(node, { wide = false, onclose } = {}) {
  closeLayer();
  const box = el("div", { class: "sheet" + (wide ? " wide" : ""), role: "dialog" }, node);
  const scrim = el("div", { class: "scrim", onmousedown: (e) => { if (e.target === scrim) { closeLayer(); onclose?.(); } } }, box);
  $("#layer").append(scrim);
  return box;
}
export const layerOpen = () => !!$("#layer > :not(.out)");
