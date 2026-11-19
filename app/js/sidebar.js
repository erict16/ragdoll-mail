// The folder list on the left.
import { $, api, el, esc, icon, MOD, t } from "./core.js";
import { FOLDER_ICON, S } from "./state.js";
import { closeLayer, fail, menu, sheet, toast } from "./ui.js";
import { moveMail, openFolder } from "./actions.js";
import { openSettings } from "./settings.js";
import { shortcutsSheet } from "./keys.js";

export function renderNav() {
  const nav = $("#nav");
  nav.replaceChildren();
  const folders = [...S.boot.folders];
  for (const [key, at] of [["flagged", 1], ["scheduled", 3], ["snoozed", 3]]) {
    if (S.folder === key && !folders.some((f) => f.key === key)) folders.splice(Math.min(at, folders.length), 0, { key, total: 0, unread: 0 });
  }
  let own = false;
  for (const f of folders) {
    const n = f.key === "inbox" || f.custom ? f.unread : ["drafts", "scheduled", "flagged", "snoozed"].includes(f.key) ? f.total : 0;
    const name = f.custom ? f.name : t(f.key);
    if (f.custom && !own) { own = true; nav.append(el("div", { class: "nav-sep" })); }
    const b = el("button", { class: "nav-item" + (f.key === S.folder && !S.query ? " on" : ""), "data-folder": f.key, "data-tip": name, "data-rail": "", onclick: () => openFolder(f.key),
      style: f.depth ? `--depth:${f.depth}` : null,
      html: icon(f.custom ? "folder" : FOLDER_ICON[f.key] || "folder-open") + `<span class="label" dir="auto">${esc(name)}</span>` + (n ? `<span class="count">${n}</span>` : "") });
    if (f.key === "archive" || f.key === "trash" || f.key === "inbox" || f.key === "junk" || f.custom) {
      b.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("x-ragdoll/ids")) { e.preventDefault(); b.classList.add("drop"); } });
      b.addEventListener("dragleave", () => b.classList.remove("drop"));
      b.addEventListener("drop", (e) => { b.classList.remove("drop"); const ids = JSON.parse(e.dataTransfer.getData("x-ragdoll/ids") || "[]"); if (ids.length) moveMail(ids, f.key); });
    }
    nav.append(b);
  }
  $("#account-addr").textContent = S.boot.demo ? t("demo") : S.boot.user;
  const up = $("#update");
  up.hidden = !S.update;
  if (S.update) {
    const label = S.update.ready ? t("restart_to_update") : t("update_to", "v" + S.update.version);
    up.innerHTML = icon(S.update.ready ? "refresh-cw" : "download") + `<span>${esc(label)}</span>`;
    up.dataset.tip = label; up.dataset.rail = "";
  }
}

// What the new version brings, and the one button that gets it: Update now for a source clone
// (the app updates itself and restarts), Download for the packaged app.
export function updateSheet() {
  const u = S.update;
  if (!u) return;
  const msg = el("div");
  const main = el("button", { class: "btn primary" });
  const skip = el("button", { class: "btn", onclick: async () => {
    try { await api("update", { do: "skip" }); S.update = null; renderNav(); closeLayer(); } catch (e) { fail(e); }
  } }, t("skip_version"));
  const later = el("button", { class: "btn", onclick: closeLayer }, t("later"));
  const restart = () => { main.disabled = true; api("update", { do: "restart" }).catch((e) => { main.disabled = false; fail(e); }); };
  const ready = () => {
    main.disabled = false; main.textContent = t("restart"); main.onclick = restart;
    skip.hidden = true;
    msg.replaceChildren(el("div", { class: "msg-ok", html: icon("circle-check") + esc(t("updated_restart")) }));
  };
  if (u.ready) ready();
  else if (u.kind === "source") {
    main.textContent = t("update_now");
    main.onclick = async () => {
      main.disabled = skip.disabled = true; main.textContent = t("updating");
      msg.replaceChildren();
      try {
        const r = await api("update", { do: "install" });
        S.update = r.update; renderNav();
        if (r.update?.ready) ready(); else closeLayer();
      } catch (e) {
        main.disabled = skip.disabled = false; main.textContent = t("update_now");
        msg.replaceChildren(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) }));
      }
    };
  } else {
    main.innerHTML = icon("download", "small") + esc(t("get_update"));
    main.onclick = () => {
      api("open_url", { url: u.download || u.url }).then(() => { closeLayer(); toast(t("dl_note"), { ms: 9000 }); }).catch(fail);
    };
  }
  const notes = (u.notes || []).length ? el("ul", {}, ...u.notes.map((x) => el("li", { dir: "auto" }, x))) : null;
  sheet(el("div", {}, el("h2", {}, "ragdoll-mail v" + u.version),
    el("div", { class: "form" }, el("div", { class: "note" }, t("you_have", "v" + S.boot.version)), notes, msg),
    el("div", { class: "sheet-acts" }, skip, el("span", { class: "grow" }), later, main)));
}

export function accountMenu() {
  menu($("#account"), [
    { note: S.boot.demo ? t("demo") : S.boot.user },
    { icon: "settings", label: t("settings"), key: MOD + ",", run: openSettings },
    { icon: "refresh-cw", label: t("sync_now"), run: () => api("sync").then(() => toast(t("syncing"))).catch(fail) },
    { icon: "keyboard", label: t("shortcuts"), key: "?", run: shortcutsSheet },
    "-",
    { note: t("version", S.boot.version) },
  ], { above: true });
}
