// Live status from the server: counts, sync state, new mail.
import { $, api, sleep, t, tr } from "./core.js";
import { S } from "./state.js";
import { renderNav, updateSheet } from "./sidebar.js";
import { loadList, renderRows } from "./list.js";
import { openFolder, selectRow } from "./actions.js";
import { openThread } from "./reader.js";
import { openSettings } from "./settings.js";

export async function refreshCounts() {
  try { const st = await api("status"); applyStatus(st); } catch { /* next poll */ }
}
// One call stays open and comes back the moment something changed, so new mail shows at once
// and an idle app does no work at all.
export async function watchStatus() {
  if (watchStatus.on) return;
  watchStatus.on = true;
  for (let fails = 0; ;) {
    try { applyStatus(await api("wait", { tick: S.tick })); fails = 0; }
    catch { await sleep(Math.min(5000, 500 * 2 ** fails++)); }
  }
}
function applyStatus(st) {
  S.boot.folders = st.folders;
  S.update = st.update;
  S.tick = st.tick;
  const wasSyncing = S.syncing;
  S.syncing = st.syncing;
  const shown = JSON.stringify([st.folders, st.update, st.syncing]);
  if (shown !== applyStatus.shown) { applyStatus.shown = shown; renderNav(); }
  const b = $("#banner");
  if (st.error && !S.boot.demo) {
    b.hidden = false;
    $("#banner-text").textContent = tr(st.error);
    $("#banner-btn").textContent = t("settings");
  } else b.hidden = true;
  if (st.open) { S.rev = st.rev; openMail(st.open); }
  else if (st.rev !== S.rev) { S.rev = st.rev; loadList({ quiet: true }); }
  else if (wasSyncing !== S.syncing && !S.rows.length) renderRows();
}
// a click on a desktop notification: show that mail in the Inbox
async function openMail(id) {
  if (S.folder !== "inbox" || S.query) await openFolder("inbox");
  else await loadList({ quiet: true });
  if (S.rows.some((x) => x.id === id)) selectRow(id);
  else openThread(id);
}
addEventListener("focus", () => { if (S.boot) refreshCounts(); });
$("#banner-btn").addEventListener("click", openSettings);
$("#update").addEventListener("click", updateSheet);
