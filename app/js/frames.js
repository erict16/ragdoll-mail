// The sandboxed frames that show a mail's own HTML.
import { api, el, t } from "./core.js";
import { textSize } from "./state.js";
import { isDark } from "./theme.js";
import { fail } from "./ui.js";
import { openCompose } from "./compose.js";
import { onKey } from "./keys.js";

const FRAME_FONT = getComputedStyle(document.documentElement).getPropertyValue("--font");
const QUOTE_SEL = ".gmail_quote, .gmail_extra, #divRplyFwdMsg, blockquote[type=cite], .rd-quote, #appendonsend, .yahoo_quoted, " +
  "#mail-editor-reference-message-container, .moz-cite-prefix, #isForwardContent, #origbody, .protonmail_quote, div[id^=reply-intro]";
const QUOTE_TEXT = /^\s*(-{2,}\s*(原始邮件|原始郵件|Original Message|Forwarded message|转发邮件)|发件人[:：]|寄件者[:：]|From:\s|Von:\s|De\s?:\s|Từ:\s|在\s?.{3,80}写道[:：]|On .{5,160} wrote:)/i;
const frames = new Set();

function frameDoc(html, { plain, remote, dark }) {
  const csp = `default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:${remote ? " https: http:" : ""}; media-src data:`;
  const fg = dark ? "#e6e6e6" : "#1d1d1f";
  let css = `:root{color-scheme:${dark ? "dark" : "light"}}html,body{background:transparent}body{margin:0;font:${textSize()}px/1.6 ${FRAME_FONT};color:${fg};overflow-wrap:anywhere;overflow-x:auto;overflow-y:hidden}
img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap}a{color:${dark ? "#8fb8ff" : "#1a5fb4"}}
blockquote{margin:0 0 0 4px;padding-left:10px;border-left:2px solid ${dark ? "#444" : "#ddd"}}
.rd-plain{white-space:pre-wrap;font-size:${textSize()}px}.rd-quote{color:${dark ? "#9a9a9a" : "#6e6e73"};margin-top:14px;padding-left:10px;border-left:2px solid ${dark ? "#444" : "#ddd"}}`;
  if (dark && !plain) {
    css += `html,body{background:transparent!important}.rd-root{background:#e6e6e6;color:#1d1d1f;filter:invert(1) hue-rotate(180deg);padding:1px 0}
.rd-root img,.rd-root video,.rd-root picture,.rd-root [background],.rd-root [style*="url("]{filter:invert(1) hue-rotate(180deg)}.rd-root a{color:#1a5fb4}`;
  }
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><style>${css}</style></head><body><div class="rd-root">${html}</div></body></html>`;
}

export function mailFrame(html, { plain = false, remote = false, quote = false, sig = false } = {}) {
  const wrap = el("div");
  const frame = el("iframe", { class: "frame" + (sig ? " sig-frame" : ""), sandbox: "allow-same-origin allow-popups allow-popups-to-escape-sandbox", referrerpolicy: "no-referrer", title: "mail" });
  wrap.append(frame);
  const st = { html, plain, remote, quote, frame, wrap, hidden: [], toggle: null };
  frames.add(st);
  const fit = () => {
    const d = frame.contentDocument;
    if (!d || !d.documentElement) return;
    if (!d.body) return;
    // the body's own height: the document's grows with the frame and would never shrink
    const root = d.querySelector(".rd-root") || d.body;
    const h = Math.ceil(Math.max(d.body.scrollHeight, root.getBoundingClientRect().bottom + (d.defaultView?.scrollY || 0)));
    if (frame.style.height !== h + "px") frame.style.height = h + "px";
  };
  st.fit = fit;
  frame.addEventListener("load", () => {
    const d = frame.contentDocument;
    if (!d) return;
    if (quote) collapseQuote(st);
    fit();
    // the frame's own observer: it goes away with the frame; one fit per frame at most
    try {
      let q = 0;
      const ro = new d.defaultView.ResizeObserver(() => {
        if (!frame.isConnected) { ro.disconnect(); return; }
        if (!q) q = requestAnimationFrame(() => { q = 0; fit(); });
      });
      ro.observe(d.body);
    } catch { /* old engine */ }
    for (const img of d.images) if (!img.complete) img.addEventListener("load", fit);
    d.addEventListener("click", (e) => {
      const a = e.target.closest?.("a[href]");
      if (!a) return;
      e.preventDefault();
      const href = a.getAttribute("href") || "";
      if (/^mailto:/i.test(href)) {
        const addr = decodeURIComponent(href.slice(7).split("?")[0]);
        openCompose({ mode: "new", to: addr.split(",").filter(Boolean).map((x) => ({ name: "", addr: x.trim().toLowerCase() })) });
      } else if (/^https?:/i.test(href)) api("open_url", { url: a.href }).catch(fail);
    });
    d.addEventListener("keydown", (e) => onKey(e));
  });
  setTimeout(fit, 400);
  frame.srcdoc = frameDoc(html, { plain, remote, dark: isDark() });
  const obs = new MutationObserver(() => { if (!wrap.isConnected) { frames.delete(st); obs.disconnect(); } });
  requestAnimationFrame(() => obs.observe(document.body, { childList: true, subtree: true }));
  return { node: wrap, frame, st };
}

export function refreshFrames() {
  for (const st of frames) {
    if (!st.wrap.isConnected) { frames.delete(st); continue; }
    st.toggle?.remove(); st.toggle = null; st.hidden = [];
    st.frame.srcdoc = frameDoc(st.html, { plain: st.plain, remote: st.remote, dark: isDark() });
  }
}

function collapseQuote(st) {
  const d = st.frame.contentDocument, root = d.querySelector(".rd-root") || d.body;
  let q = root.querySelector(QUOTE_SEL);
  if (!q) {
    const w = d.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (QUOTE_TEXT.test(n.nodeValue)) {
        q = n.parentElement.closest("div,p,table,blockquote,tr,section,font,span") || n.parentElement;
        break;
      }
    }
  }
  if (!q || q === root) return;
  const r = d.createRange();
  r.setStart(root, 0); r.setEndBefore(q);
  const before = r.cloneContents();
  if (!before.textContent.trim() && !before.querySelector?.("img")) return;
  // the quote and everything after it, at every level up to the root
  const hide = [];
  for (let n = q; n && n !== root; n = n.parentElement) {
    for (let s = n === q ? n : n.nextElementSibling; s; s = s.nextElementSibling) hide.push(s);
  }
  const uniq = [...new Set(hide)].filter((x) => x.style);
  if (!uniq.length) return;
  for (const x of uniq) { x.dataset.rdDisplay = x.style.display; x.style.display = "none"; }
  st.hidden = uniq;
  const btn = el("button", { class: "quote-toggle", "data-tip": t("show_quote"), "aria-label": t("show_quote") }, "•••");
  btn.addEventListener("click", () => {
    const on = btn.classList.toggle("open");
    for (const x of uniq) x.style.display = on ? x.dataset.rdDisplay : "none";
    st.fit();
  });
  st.toggle = btn;
  st.wrap.append(btn);
}
