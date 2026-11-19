// Dragging the line between the list and the reader, and the sidebar's right edge.
import { $, api } from "./core.js";

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
  const root = document.documentElement, grip = $("#side-grip"), side = grip.parentElement;
  grip.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const x0 = e.clientX, w0 = side.offsetWidth;
    const move = (ev) => root.style.setProperty("--side-user", Math.max(180, Math.min(360, w0 + ev.clientX - x0)) + "px");
    const up = () => {
      removeEventListener("mousemove", move); removeEventListener("mouseup", up);
      api("prefs", { side_width: side.offsetWidth }).catch(() => {});
    };
    addEventListener("mousemove", move); addEventListener("mouseup", up);
  });
  grip.addEventListener("dblclick", () => { root.style.removeProperty("--side-user"); api("prefs", { side_width: 0 }).catch(() => {}); });
})();
