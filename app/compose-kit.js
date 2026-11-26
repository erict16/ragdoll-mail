// Small helpers for writing mail and for keys, kept free of the page so they can be tested on their own
// (tests/test_group_a.py runs them in node). Nothing here touches the document at load.

// ---------------------------------------------------------------- keys

// A key pressed while an input method (Chinese pinyin, Japanese kana...) still has a candidate open:
// Enter picks the candidate, Esc drops it, Backspace edits it. None of them is meant for the app.
// WebKit sends some of these with isComposing false but keyCode 229.
export const isIME = (e) => !!(e && (e.isComposing || e.keyCode === 229));

// The app's shortcut modifier: Cmd on a Mac, Ctrl elsewhere. On a Mac, Ctrl keys stay the system's own
// text keys (Ctrl+K deletes to the line end, Ctrl+B moves back a letter).
export const modOf = (mac) => (e) => !!(mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey);

// ---------------------------------------------------------------- addresses

export const ADDR_RE = /^[^@\s<>,;，；]+@[^@\s<>,;，；]+\.[^@\s<>,;，；]+$/;
const SEP = /[,;，；\n]/;

// Split a typed or pasted list of addresses. A comma inside quotes or <...> is part of the name or
// address, and a piece with no @ in it ("Wang" in `Wang, Li <li@x.com>`) is the start of a name.
export function splitAddrs(text) {
  const parts = [];
  let cur = "", quote = false, angle = false;
  for (const ch of String(text ?? "")) {
    if (ch === '"' && !angle) quote = !quote;
    else if (ch === "<" && !quote) angle = true;
    else if (ch === ">" && !quote) angle = false;
    if (SEP.test(ch) && !quote && !angle) { parts.push(cur); cur = ""; } else cur += ch;
  }
  parts.push(cur);
  const out = [];
  let lead = "";
  for (const p of parts) {
    const s = p.trim();
    if (!s) continue;
    if (!s.includes("@")) { lead = lead ? lead + ", " + s : s; continue; }
    out.push(lead ? lead + ", " + s : s);
    lead = "";
  }
  if (lead) out.push(lead);
  return out;
}

export function parseAddrs(text) {
  const out = [];
  for (const s of splitAddrs(text)) {
    const m = s.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (m) out.push({ name: m[1].trim(), addr: m[2].trim().replace(/^mailto:/i, "").toLowerCase() });
    else out.push({ name: "", addr: s.replace(/^mailto:/i, "").toLowerCase() });
  }
  return out;
}

// The box should turn its text into chips now: it ends in a separator that is not inside quotes or <...>,
// and every piece before it has an @ (so "Wang," waits for the rest of the name).
export function commitReady(text) {
  const v = String(text ?? "");
  if (!/[,;，；]\s*$/.test(v)) return false;
  let quote = false, angle = false;
  for (const ch of v) {
    if (ch === '"' && !angle) quote = !quote;
    else if (ch === "<" && !quote) angle = true;
    else if (ch === ">" && !quote) angle = false;
  }
  if (quote || angle) return false;
  const parts = splitAddrs(v);
  return parts.length > 0 && parts.every((p) => p.includes("@"));
}

// ---------------------------------------------------------------- colours (pasted text)

const NAMED = {
  white: [255, 255, 255], black: [0, 0, 0], snow: [255, 250, 250], ivory: [255, 255, 240], whitesmoke: [245, 245, 245],
  ghostwhite: [248, 248, 255], gainsboro: [220, 220, 220], lightgray: [211, 211, 211], lightgrey: [211, 211, 211],
  silver: [192, 192, 192], gray: [128, 128, 128], grey: [128, 128, 128], dimgray: [105, 105, 105], dimgrey: [105, 105, 105],
  red: [255, 0, 0], green: [0, 128, 0], blue: [0, 0, 255], navy: [0, 0, 128], maroon: [128, 0, 0], purple: [128, 0, 128],
  teal: [0, 128, 128], olive: [128, 128, 0], yellow: [255, 255, 0], aqua: [0, 255, 255], cyan: [0, 255, 255],
  lime: [0, 255, 0], fuchsia: [255, 0, 255], magenta: [255, 0, 255], orange: [255, 165, 0], windowtext: [0, 0, 0],
  window: [255, 255, 255], canvas: [255, 255, 255], canvastext: [0, 0, 0], transparent: null,
};
// [r, g, b, alpha] of a CSS colour, or null when it is not one we can read
export function parseColor(v) {
  const s = String(v ?? "").trim().toLowerCase().replace(/\s*!important$/, "");
  let m;
  if ((m = s.match(/^#([0-9a-f]{3,8})$/))) {
    let h = m[1];
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
    if (h.length !== 6 && h.length !== 8) return null;
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16), h.length === 8 ? parseInt(h.slice(6), 16) / 255 : 1];
  }
  if ((m = s.match(/^rgba?\(([^)]*)\)$/))) {
    const p = m[1].split(/[\s,/]+/).filter(Boolean);
    if (p.length < 3) return null;
    const ch = (x) => (x.endsWith("%") ? parseFloat(x) * 2.55 : parseFloat(x));
    const a = p[3] == null ? 1 : p[3].endsWith("%") ? parseFloat(p[3]) / 100 : parseFloat(p[3]);
    const rgb = p.slice(0, 3).map(ch);
    return rgb.some(isNaN) ? null : [...rgb, isNaN(a) ? 1 : a];
  }
  if (s === "transparent") return [0, 0, 0, 0];
  if (Object.hasOwn(NAMED, s) && NAMED[s]) return [...NAMED[s], 1];
  return null;
}
// relative luminance, 0 (black) to 1 (white); null when the colour is unknown or see-through
export function luminance(v) {
  const c = parseColor(v);
  if (!c || c[3] < 0.2) return null;
  const lin = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
}
// text this light can't be read on a white mail; a background this dark came from a dark theme
export const lightText = (v) => { const l = luminance(v); return l != null && l > 0.6; };
export const darkBack = (v) => { const l = luminance(v); return l != null && l < 0.3; };

// ---------------------------------------------------------------- inline styles

// "a: b; c: url(data:x;y)" as [[prop, value]], with ; inside brackets or quotes left alone
export function styleDecls(style) {
  const out = [];
  let cur = "", depth = 0, q = "";
  for (const ch of String(style ?? "")) {
    if (q) { if (ch === q) q = ""; }
    else if (ch === '"' || ch === "'") q = ch;
    else if (ch === "(") depth++;
    else if (ch === ")") depth = Math.max(0, depth - 1);
    if (ch === ";" && !depth && !q) { out.push(cur); cur = ""; } else cur += ch;
  }
  out.push(cur);
  return out.map((d) => { const k = d.indexOf(":"); return k < 0 ? null : [d.slice(0, k).trim().toLowerCase(), d.slice(k + 1).trim()]; })
    .filter((d) => d && d[0] && d[1]);
}
const BAD_PROPS = new Set(["position", "z-index", "behavior", "-moz-binding", "-webkit-user-modify", "user-modify", "content", "inset"]);
const BAD_VALUE = /expression\s*\(|javascript:|vbscript:|-moz-binding|@import/i;
const SAFE_CSS_URL = /^\s*(https?:|data:image\/(png|jpe?g|gif|webp|bmp)[;,]|cid:)/i;
// Every url(...) call in a CSS value must be complete and carry an allowed URL scheme.
function urlsSafe(v) {
  const hits = v.match(/url\s*\(/gi);
  if (!hits) return true;
  const re = /url\s*\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s"']*))\s*\)/gi;
  let n = 0, m;
  while ((m = re.exec(v))) {
    const arg = m[1] ?? m[2] ?? m[3] ?? "";
    if (!SAFE_CSS_URL.test(arg)) return false;
    n++;
  }
  return n === hits.length;
}
// an inline style that can't reach outside its box in the app's own window (no position: fixed over the
// toolbar, no script urls). paste: light text and dark backgrounds from a dark theme are dropped too.
export function cleanStyle(style, { paste = false } = {}) {
  const keep = [];
  for (const [p, v] of styleDecls(style)) {
    if (BAD_PROPS.has(p) || BAD_VALUE.test(v)) continue;
    if (!urlsSafe(v)) continue;
    if (paste) {
      if (p === "color" && lightText(v)) continue;
      const back = p === "background" ? v.match(/^(#[0-9a-f]+|rgba?\([^)]*\)|[a-z]+)/i)?.[0] : v;
      if ((p === "background-color" || p === "background") && darkBack(back)) continue;
      if (p === "background" && /url\s*\(/i.test(v)) continue;
    }
    keep.push(p + ": " + v);
  }
  return keep.join("; ");
}

// ---------------------------------------------------------------- HTML allow-list

// Mail HTML goes into the editor in the app's own window, which holds the app's key: only plain content
// tags and attributes pass. Tags not listed lose their tag and keep their text; these go with what is in them:
export const DROP_TAGS = "script,style,meta,link,title,base,head,iframe,frame,frameset,object,embed,applet,form,input,button," +
  "select,option,textarea,svg,math,video,audio,source,track,canvas,template,noscript,portal,dialog,marquee,param,xml";
export const KEEP_TAGS = new Set(("a abbr address article aside b bdi bdo big blockquote br caption center cite code col colgroup " +
  "dd del dfn div dl dt em figcaption figure font footer h1 h2 h3 h4 h5 h6 header hr i img ins kbd li main mark nav ol p pre q s " +
  "samp section small span strike strong sub sup table tbody td tfoot th thead tr tt u ul var wbr").split(" "));
const KEEP_ATTRS = new Set(["href", "src", "alt", "title", "colspan", "rowspan", "width", "height", "style", "align", "valign",
  "border", "cellpadding", "cellspacing", "bgcolor", "color", "face", "size", "dir", "start", "type", "data-rd-body"]);
const ATTR_ON = { href: "a", src: "img", start: "ol", type: "ol ul li", "data-rd-body": "div", face: "font", size: "font", color: "font" };
// a link or picture address that is safe to keep; file:, blob:, javascript:, data:text and webkit-fake-url are not
export function safeURL(v, attr) {
  const s = String(v ?? "").replace(/[\u0000- \u007f-\u009f]/g, "").toLowerCase();
  if (attr === "src") return /^(https?:|cid:|data:image\/(png|jpe?g|gif|webp|bmp)[;,])/.test(s);
  return /^(https?:|mailto:|tel:|#)/.test(s);
}

// Clean a parsed document's body in place. paste: also light text and dark backgrounds.
export function sanitizeBody(body, { paste = false } = {}) {
  body.querySelectorAll(DROP_TAGS).forEach((n) => n.remove());
  const doc = body.ownerDocument;
  const walk = doc.createTreeWalker(body, 128 /* comments */);
  const notes = [];
  while (walk.nextNode()) notes.push(walk.currentNode);
  notes.forEach((n) => n.remove());
  for (const n of [...body.querySelectorAll("*")]) {
    const tag = n.localName;
    if (!KEEP_TAGS.has(tag)) { n.replaceWith(...n.childNodes); continue; }
    for (const a of [...n.attributes]) {
      const k = a.name.toLowerCase();
      if (!KEEP_ATTRS.has(k) || (ATTR_ON[k] && !ATTR_ON[k].split(" ").includes(tag))) n.removeAttribute(a.name);
      else if ((k === "href" || k === "src") && !safeURL(a.value, k)) n.removeAttribute(a.name);
      else if (k === "style") { const s = cleanStyle(a.value, { paste }); if (s) n.setAttribute("style", s); else n.removeAttribute("style"); }
      else if (paste && k === "color" && lightText(a.value)) n.removeAttribute(a.name);
      else if (paste && k === "bgcolor" && darkBack(a.value)) n.removeAttribute(a.name);
    }
    if (tag === "img" && !n.getAttribute("src")) n.remove();
  }
  return body;
}

// ---------------------------------------------------------------- sizes and paragraphs

// The size menu uses the browser's own font sizes 1-7 in the editor (so Undo works); the editor shows them at
// these pixel sizes, and the mail that goes out carries the pixels.
export const FONT_PX = { 1: 10, 2: 12, 3: 14, 4: 16, 5: 18, 6: 24, 7: 32 };
export const sizeKey = (px) => String(Object.entries(FONT_PX).find(([, v]) => v === px)?.[0] || 3);
// the gap under a paragraph (Return), for a body text size
export const paraGap = (px) => Math.round(px * 0.75);
