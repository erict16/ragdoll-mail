// First run: adding the account.
import { LANG_NAMES } from "../i18n.js";
import { $, $$, api, el, esc, icon, setLocale, systemLang, t } from "./core.js";
import { PREFS } from "./state.js";
import { selectBox } from "./settings.js";
import { start } from "./main.js";

export function showSetup() {
  $("#app").hidden = true;
  const box = $("#setup");
  box.hidden = false;
  const v = { name: "", user: "", password: "", imap_host: "", imap_port: 993, smtp_host: "", smtp_port: 465 };
  let open = false, busy = false, err = "", guessed = "";
  const draw = () => {
    const f = el("div", { class: "form" });
    const inp = (k, type = "text", attrs = {}) => {
      const i = el("input", { type, value: v[k] ?? "", spellcheck: "false", autocomplete: "off", ...attrs });
      i.addEventListener("input", () => { v[k] = i.value; });
      return i;
    };
    const lab = (text, ...kids) => el("label", {}, el("span", { class: "lab" }, text), ...kids);
    const email = inp("user", "email", { autofocus: true });
    email.addEventListener("change", async () => {
      if (!v.user.includes("@") || guessed === v.user) return;
      guessed = v.user;
      try { const g = await api("guess_servers", { user: v.user }); v.imap_host = g.imap_host; v.smtp_host = g.smtp_host; const n = $$("#setup input[data-host]"); n.forEach((x) => { x.value = v[x.dataset.host]; }); } catch { /* typed by hand */ }
    });
    f.append(lab(t("name"), inp("name")), lab(t("email"), email), lab(t("password"), inp("password", "password")));
    const dis = el("button", { class: "disclose" + (open ? " open" : ""), onclick: () => { open = !open; draw(); }, html: icon("chevron-right", "small") + esc(t("servers")) });
    f.append(dis);
    if (open) {
      f.append(lab(t("incoming"), el("div", { class: "two" }, inp("imap_host", "text", { "data-host": "imap_host" }), inp("imap_port", "number"))),
        lab(t("outgoing"), el("div", { class: "two" }, inp("smtp_host", "text", { "data-host": "smtp_host" }), inp("smtp_port", "number"))));
    }
    if (err) f.append(el("div", { class: "msg-err", html: icon("triangle-alert") + esc(err) }));
    const go = el("button", { class: "btn primary", disabled: busy, onclick: signIn }, busy ? t("signing_in") : t("sign_in"));
    f.append(go);
    f.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.tagName === "INPUT") signIn(); });
    const lang = selectBox([["system", t("system_x", LANG_NAMES.find(([k]) => k === systemLang())[1])], ...LANG_NAMES], PREFS.lang || "system", (val) => {
      PREFS.lang = val; api("prefs", { lang: val }).catch(() => {}); setLocale(PREFS); draw();
    });
    lang.classList.add("setup-lang");
    lang.prepend(el("span", { class: "select-lead", html: icon("languages", "small") }));
    box.replaceChildren(el("div", { class: "setup-drag pywebview-drag-region" }), lang,
      el("div", { class: "setup-card" }, el("img", { class: "logo", src: "logo.png", alt: "" }), el("h1", {}, t("setup_title")), f));
  };
  async function signIn() {
    if (busy) return;
    if (!v.imap_host && v.user.includes("@")) {
      try { const g = await api("guess_servers", { user: v.user }); v.imap_host = g.imap_host; v.smtp_host = g.smtp_host; } catch { /* below */ }
    }
    busy = true; err = ""; draw();
    try {
      const r = await api("test", v);
      const b = await api("save_settings", { ...v, account: true, folders: r.folders });
      box.hidden = true;
      start(b);
    } catch (e) { err = e.message; busy = false; open = open || /server|服务器|port|端口/i.test(e.message); draw(); }
  }
  draw();
}
