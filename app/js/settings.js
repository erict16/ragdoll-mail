// The settings sheet.
import { LANG_NAMES } from "../i18n.js";
import { $, $$, api, el, esc, icon, iconBtn, setLocale, SYS_TZ, systemLang, t, tr } from "./core.js";
import { FONT_SIZES, fontLabel, FONTS, mailFont, mailSize, PREFS, S, textSize, undoSeconds } from "./state.js";
import { applyTheme } from "./theme.js";
import { closeLayer, fail, sheet, toast } from "./ui.js";
import { renderNav } from "./sidebar.js";
import { loadList, renderRows } from "./list.js";
import { openScheduled, openThread, renderToolbar } from "./reader.js";
import { renderCompose } from "./compose.js";
import { cleanHTML, composeState } from "./editor.js";
import { setTextSize } from "./keys.js";
import { refreshCounts } from "./status.js";

export async function openSettings(first = "account") {
  let s, tpls = [];
  try { s = await api("settings"); tpls = (await api("templates")).templates; } catch (e) { return fail(e); }
  const v = { ...s, password: "", theme: S.theme };
  let tab = typeof first === "string" ? first : "account";
  let tplOpen = null;         // the template in the editor: one of the list, or a new one
  const nav = el("div", { class: "settings-nav" }, el("h3", {}, t("settings")));
  const body = el("div", { class: "settings-body" });
  const msg = el("span", { class: "grow" });
  const saveBtn = el("button", { class: "btn primary", onclick: save }, t("save"));
  const cancelBtn = el("button", { class: "btn", onclick: closeLayer }, t("cancel"));
  const foot = el("div", { class: "settings-foot" }, msg, cancelBtn, saveBtn);
  const tabs = [["account", "circle-user-round", "account"], ["signature", "square-pen", "signature"], ["templates", "file-text", "templates"], ["sending", "type", "composing"],
    ["appearance", "sun", "appearance"], ["notify", "bell", "notifications"], ["region", "languages", "region"]];
  const drawNav = () => {
    nav.replaceChildren(el("h3", {}, t("settings")));
    for (const [k, ic, lab] of tabs) nav.append(el("button", { class: "nav-item" + (k === tab ? " on" : ""), onclick: () => { grab(); tab = k; drawNav(); draw(); }, html: icon(ic) + `<span class="label">${esc(t(lab))}</span>` }));
  };
  const setPref = (patch) => { Object.assign(PREFS, patch); api("prefs", patch).catch(fail); };
  // the whole window speaks the new language at once, this sheet too
  const relabelSheet = () => { saveBtn.textContent = t("save"); cancelBtn.textContent = t("cancel"); drawNav(); draw(); };
  let sigEd = null;
  const grab = () => {
    for (const inp of $$("input[data-k]", body)) v[inp.dataset.k] = inp.value;
    if (sigEd) v.signature = sigEd.innerHTML;
  };
  const draw = () => {
    body.replaceChildren();
    sigEd = null;
    if (tab === "account") {
      const f = el("div", { class: "form" });
      const inp = (k, type = "text", ph = "") => el("input", { type, "data-k": k, value: v[k] ?? "", placeholder: ph, spellcheck: "false", autocomplete: "off" });
      const lab = (text, ...kids) => el("label", {}, el("span", { class: "lab" }, text), ...kids);
      f.append(lab(t("name"), inp("name")), lab(t("email"), inp("user", "email")),
        lab(t("password"), inp("password", "password", s.has_password ? "••••••••  " + t("pw_saved") : "")));
      if (s.password_env) f.append(el("div", { class: "msg-warn" }, t("pw_env", "RAGDOLL_PASSWORD")));
      f.append(lab(t("incoming"), el("div", { class: "two" }, inp("imap_host"), inp("imap_port", "number"))),
        lab(t("outgoing"), el("div", { class: "two" }, inp("smtp_host"), inp("smtp_port", "number"))),
        lab(t("require_cc"), inp("require_cc", "text", "boss@example.com")));
      const res = el("div");
      const testBtn = el("button", { class: "btn", onclick: async () => {
        grab(); testBtn.disabled = true; res.replaceChildren(el("span", { class: "note" }, t("testing")));
        try { const r = await api("test", v); v.folders = r.folders; res.replaceChildren(el("div", { class: "msg-ok", html: icon("circle-check") + esc(t("test_ok")) })); }
        catch (e) { res.replaceChildren(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) })); }
        finally { testBtn.disabled = false; }
      } }, t("test"));
      f.append(el("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" }, testBtn, res));
      body.append(el("h2", {}, t("account")), f);
    } else if (tab === "signature") {
      sigEd = el("div", { class: "sig-edit", contenteditable: "true" });
      sigEd.innerHTML = v.signature || "";
      sigEd.addEventListener("paste", (e) => { const h = e.clipboardData.getData("text/html"); if (h) { e.preventDefault(); document.execCommand("insertHTML", false, cleanHTML(h)); } });
      body.append(el("h2", {}, t("signature")), el("div", { class: "form" }, sigEd));
    } else if (tab === "sending") {
      const seg = el("div", { class: "seg" });
      for (const n of UNDO_CHOICES) {
        seg.append(el("button", { class: undoSeconds() === n ? "on" : "", onclick: () => { setPref({ undo: n }); draw(); } }, n ? t("seconds", n) : t("undo_off")));
      }
      const font = selectBox(FONTS.map(([k]) => [k, fontLabel(k)]), PREFS.font || "system", (val) => { setPref({ font: val }); draw(); });
      const sizes = el("div", { class: "seg" });
      for (const n of FONT_SIZES) sizes.append(el("button", { class: mailSize() === n ? "on" : "", onclick: () => { setPref({ font_size: n }); draw(); } }, String(n)));
      const sample = el("div", { class: "font-sample", style: `font-family:${mailFont()};font-size:${mailSize()}px` }, t("font_sample"));
      body.append(el("h2", {}, t("composing")), el("div", { class: "form" },
        el("label", {}, el("span", { class: "lab" }, t("default_font")), font),
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("default_size")), sizes), sample,
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("undo_send")), seg), el("div", { class: "note" }, t("undo_note"))));
    } else if (tab === "templates") {
      const f = el("div", { class: "form" });
      if (tplOpen) {
        const name = el("input", { type: "text", value: tplOpen.name || "", placeholder: t("template_name"), maxlength: "80" });
        const ed = el("div", { class: "sig-edit", contenteditable: "true" });
        ed.innerHTML = tplOpen.html || "";
        ed.addEventListener("paste", (e) => { const h = e.clipboardData.getData("text/html"); if (h) { e.preventDefault(); document.execCommand("insertHTML", false, cleanHTML(h)); } });
        const err = el("div");
        const keep = async () => {
          try { tpls = (await api("templates", { do: "save", id: tplOpen.id, name: name.value, html: ed.innerHTML })).templates; tplOpen = null; draw(); }
          catch (e) { err.replaceChildren(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(tr(e.message)) })); }
        };
        f.append(name, ed, err, el("div", { style: "display:flex;gap:8px;justify-content:flex-end" },
          el("button", { class: "btn", onclick: () => { tplOpen = null; draw(); } }, t("back")),
          el("button", { class: "btn primary", onclick: keep }, t("save_template"))));
        body.append(el("h2", {}, t("templates")), f);
        (tplOpen.id ? ed : name).focus();
      } else {
        const list = el("div", { class: "tpl-list" });
        for (const x of tpls) {
          list.append(el("div", { class: "tpl-row" },
            el("button", { class: "tpl-name", dir: "auto", onclick: () => { tplOpen = x; draw(); }, html: icon("file-text", "small") + `<span>${esc(x.name)}</span>` }),
            iconBtn("trash-2", t("remove"), async () => { try { tpls = (await api("templates", { do: "delete", id: x.id })).templates; draw(); } catch (e) { fail(e); } }, { cls: "tiny" })));
        }
        f.append(list, el("div", {}, el("button", { class: "btn", onclick: () => { tplOpen = {}; draw(); }, html: icon("square-pen", "small") + esc(t("new_template")) })));
        body.append(el("h2", {}, t("templates")), f);
      }
    } else if (tab === "notify") {
      const onOff = (key, isOn) => {
        const seg = el("div", { class: "seg" });
        for (const on of [true, false]) seg.append(el("button", { class: isOn === on ? "on" : "", onclick: () => { setPref({ [key]: on }); draw(); } }, on ? t("on") : t("undo_off")));
        return seg;
      };
      body.append(el("h2", {}, t("notifications")), el("div", { class: "form" },
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("notify_new")), onOff("notify", PREFS.notify !== false)),
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("notify_badge")), onOff("badge", PREFS.badge === true))));
    } else if (tab === "region") {
      const lang = selectBox([["system", t("system_x", LANG_NAMES.find(([k]) => k === systemLang())[1])], ...LANG_NAMES], PREFS.lang || "system", (val) => {
        setPref({ lang: val }); setLocale(PREFS); relabel(); relabelSheet();
      });
      const tz = selectBox([["system", t("system_x", SYS_TZ.replace(/_/g, " "))], ...zoneChoices()], PREFS.tz && PREFS.tz !== "system" ? PREFS.tz : "system", (val) => {
        setPref({ tz: val }); setLocale(PREFS); relabel(); draw();
      });
      body.append(el("h2", {}, t("region")), el("div", { class: "form" },
        el("label", {}, el("span", { class: "lab" }, t("language")), lang),
        el("label", {}, el("span", { class: "lab" }, t("time_zone")), tz)));
    } else {
      const seg = el("div", { class: "seg" });
      for (const [k, ic] of [["system", "monitor"], ["light", "sun"], ["dark", "moon"]]) {
        seg.append(el("button", { class: v.theme === k ? "on" : "", onclick: () => { v.theme = k; applyTheme(k); api("prefs", { theme: k }).catch(() => {}); draw(); }, html: icon(ic, "small") + esc(t(k)) }));
      }
      const ts = el("div", { class: "seg" });
      for (const n of [13, 14, 16, 18]) ts.append(el("button", { class: textSize() === n ? "on" : "", onclick: () => { setTextSize(n); draw(); } }, String(n)));
      body.append(el("h2", {}, t("appearance")), el("div", { class: "form" }, seg,
        el("div", { class: "stack" }, el("span", { class: "lab" }, t("text_size")), ts)));
    }
  };
  async function save() {
    grab();
    const changed = ["name", "user", "password", "imap_host", "imap_port", "smtp_host", "smtp_port", "require_cc", "signature"].some((k) => String(v[k] ?? "") !== String(s[k] ?? ""));
    if (!changed) return closeLayer();
    saveBtn.disabled = true;
    msg.replaceChildren();
    try {
      const b = await api("save_settings", { ...v, account: true, folders: v.folders });
      S.boot = { ...S.boot, ...b };
      closeLayer();
      renderNav();
      toast(t("saved"));
      loadList({ quiet: true });
    } catch (e) {
      msg.replaceChildren(el("span", { class: "form" }, el("span", { class: "msg-err", html: icon("triangle-alert") + esc(e.message) })));
    } finally { saveBtn.disabled = false; }
  }
  drawNav(); draw();
  sheet(el("div", { class: "settings-wrap" }, el("div", { class: "settings" }, nav, body), foot), { wide: true });
}

const UNDO_CHOICES = [0, 5, 10, 20, 30];

// a native select in our own frame, with a chevron
export function selectBox(options, value, onchange) {
  const sel = el("select", {});
  for (const [k, label] of options) sel.append(el("option", { value: k, selected: k === value }, label));
  sel.addEventListener("change", () => onchange(sel.value));
  return el("span", { class: "select" }, sel, el("span", { class: "select-ic", html: icon("chevron-down", "small") }));
}

// every IANA time zone, by UTC offset now, labelled "UTC+08:00  Asia / Shanghai"
let ZONES = null;
function zoneChoices() {
  if (ZONES) return ZONES;
  let names = [];
  try { names = Intl.supportedValuesOf("timeZone"); } catch { names = [SYS_TZ, "UTC"]; }
  if (!names.includes("UTC")) names.push("UTC");
  const now = new Date();
  ZONES = names.map((z) => {
    let off = "GMT";
    try { off = new Intl.DateTimeFormat("en-US", { timeZone: z, timeZoneName: "longOffset" }).formatToParts(now).find((x) => x.type === "timeZoneName")?.value || "GMT"; } catch { /* old engine */ }
    const m = off.match(/GMT([+-])(\d{2}):?(\d{2})?/);
    const mins = m ? (m[1] === "-" ? -1 : 1) * (+m[2] * 60 + +(m[3] || 0)) : 0;
    const label = "UTC" + (m ? m[1] + m[2] + ":" + (m[3] || "00") : "±00:00");
    return { z, mins, text: label + "  " + z.replace(/_/g, " ").replace(/\//g, " / ") };
  }).sort((a, b) => a.mins - b.mins || a.z.localeCompare(b.z)).map((x) => [x.z, x.text]);
  return ZONES;
}

// a new language or time zone: draw everything again in place
function relabel() {
  if (!S.boot) return;
  $("#compose-btn").dataset.tip = t("compose");
  $("#search").placeholder = t("search");
  $("#banner-btn").textContent = t("settings");
  renderNav();
  renderRows();
  if (S.compose) { composeState(); renderCompose(); }
  else if (S.sched) openScheduled(S.sched);
  else if (S.thread) openThread(S.focus || S.sel);
  else renderToolbar();
  refreshCounts();
}
