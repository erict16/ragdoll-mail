// The search box.
import { $, icon, t } from "./core.js";
import { S } from "./state.js";
import { renderNav } from "./sidebar.js";
import { loadList } from "./list.js";
import { selectRow } from "./actions.js";

let searchTimer = null;
export function syncSearchUI() {
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
export function onSearch(now = false) {
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
