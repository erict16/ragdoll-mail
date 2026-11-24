// Render the overlay pieces with the site's own type: captions, the cursor, the end card layers.
// node assets.mjs <en|zh> <outdir>
import { launch, sleep } from "./drv.mjs";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";

const [lang = "en", out = "assets-" + lang] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const WT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");   // the repository
const C = {
  en: { caps: ["Ask your AI agent to answer a mail", "It saves the reply in your Drafts", "Read it in the app",
               "Say yes, and the agent sends it", "Done. It's in Sent.", "Search every mail as you type"],
        name: "Ragdoll Mail", tag: "The mail app your AI agent can use", sub: "Free and open source · Mac and Windows · Your mail stays on your computer" },
  zh: { caps: ["让 AI 助手帮你回邮件", "回复存进草稿箱", "在软件里先看一眼",
               "你说可以，AI 就发出去", "发好了，在“已发送”里", "边打字，边出结果"],
        name: "Ragdoll Mail", tag: "AI 助手也能用的邮件软件", sub: "免费开源 · Mac 和 Windows · 邮件只在你的电脑上" },
}[lang];

const FONT = `-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif`;
const D = await launch({ width: 1920, height: 1200, dpr: 1, transparent: true, lang: lang === "zh" ? "zh-CN" : "en-US" });
try {
  const page = `<!doctype html><html lang="${lang === "zh" ? "zh-Hans" : "en"}"><head><meta charset="utf-8"><style>
    html,body{margin:0;background:transparent;font-family:${FONT};-webkit-font-smoothing:antialiased}
    .cap{position:absolute;left:100px;top:100px;display:inline-block;padding:22px 44px 24px;border-radius:999px;background:rgba(29,29,31,.86);
      color:#fff;font-size:54px;font-weight:600;letter-spacing:-.01em;line-height:1.2;white-space:nowrap;
      box-shadow:0 10px 30px rgba(0,0,0,.18)}
    :lang(zh-Hans) .cap{letter-spacing:.02em}
    .cursor{position:absolute;left:100px;top:200px;width:160px;height:240px}
    .icon{position:absolute;left:100px;top:500px;width:300px;height:300px;filter:drop-shadow(0 18px 40px rgba(60,40,20,.20))}
    .name{position:absolute;left:100px;top:850px;font-size:112px;font-weight:700;letter-spacing:-.035em;color:#1d1d1f;white-space:nowrap;line-height:1.1;padding:0 4px 10px}
    .tag{position:absolute;left:100px;top:1000px;font-size:54px;font-weight:600;color:#2f7671;white-space:nowrap;letter-spacing:-.01em;padding:0 4px 8px;line-height:1.2}
    :lang(zh-Hans) .tag{letter-spacing:.02em}
    .sub{position:absolute;left:100px;top:1100px;font-size:34px;color:#5f5e5a;white-space:nowrap;padding:0 4px 8px;line-height:1.3}
    </style></head><body>
    <div class="cursor"><svg viewBox="-2 -2 20 30" width="160" height="240"><path d="M0 0 L0 22.5 L5.4 17.4 L9 25.6 L12.6 24 L9.1 16.1 L16.2 16.1 Z"
      fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg></div>
    <img class="icon" src="${pathToFileURL(WT + "/assets/icon.png").href}">
    <div class="name">${C.name}</div><div class="tag">${C.tag}</div><div class="sub">${C.sub}</div>
    ${C.caps.map((c, i) => `<div class="cap" id="c${i}" style="top:${i * 0}px;visibility:hidden">${c}</div>`).join("")}
    </body></html>`;
  writeFileSync(out + "/page.html", page);
  await D.goto(pathToFileURL(resolve(out, "page.html")).href, 1200);
  await D.js("document.fonts.ready.then(() => 1)");
  // each piece alone, on a transparent page
  const solo = async (sel, file) => {
    await D.js(`document.querySelectorAll("body > *").forEach(n => n.style.visibility = n.matches(${JSON.stringify(sel)}) ? "visible" : "hidden")`);
    const b = await D.box(sel);
    const pad = 40;
    await D.shot(`${out}/${file}`, { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad), width: b.w + 2 * pad, height: b.h + 2 * pad });
  };
  for (let i = 0; i < C.caps.length; i++) await solo(`#c${i}`, `cap${i}.png`);
  await solo(".cursor", "cursor.png");
  await solo(".icon", "icon.png");
  await solo(".name", "name.png");
  await solo(".tag", "tag.png");
  await solo(".sub", "sub.png");
  console.log("ok");
} catch (e) { console.log("ERR", e.stack); } finally { D.kill(); process.exit(0); }
