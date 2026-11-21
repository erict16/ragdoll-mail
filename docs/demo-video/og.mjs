// The site's share cards (1200 x 630): node og.mjs  (from this folder; writes site/img/og.png and og-zh.png)
// Uses docs/hero-light.png and docs/hero-zh.png (made by shots.mjs + frame.py) for the app on the right.
import { launch, sleep } from "./drv.mjs";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const C = {
  en: { lang: "en", out: "og.png", shot: "hero-light.png", h: 'The mail app your <em>AI agent</em> can use.',
        p: "Free for Mac and Windows. A command line for Claude Code and Codex, and search that runs on your computer.",
        tags: ["Free", "Open source", "Any IMAP mailbox"] },
  zh: { lang: "zh-Hans", out: "og-zh.png", shot: "hero-zh.png", h: '<em>AI 助手</em>也能用的<br>邮件软件',
        p: "免费，支持 Mac 和 Windows。自带命令行，Claude Code、Codex 都能用；搜索在你自己的电脑上完成。",
        tags: ["免费", "开源", "任何 IMAP 邮箱"] },
};
const D = await launch({ width: 1200, height: 630, dpr: 1 });
try {
  for (const k of ["en", "zh"]) {
    const c = C[k];
    const page = `<!doctype html><html lang="${c.lang}"><head><meta charset="utf-8"><style>
      html,body{margin:0;width:1200px;height:630px;overflow:hidden;background:#fbf9f6;
        font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",sans-serif;-webkit-font-smoothing:antialiased;color:#1d1d1f}
      .glow{position:absolute;inset:0;background:radial-gradient(50% 60% at 30% 20%,rgba(181,131,90,.16),transparent 70%),radial-gradient(40% 50% at 80% 80%,rgba(47,118,113,.10),transparent 70%)}
      .l{position:absolute;left:72px;top:100px;width:520px}
      .brand{display:flex;align-items:center;gap:16px;font-size:26px;font-weight:600}
      .brand img{width:56px;height:56px;border-radius:13px}
      h1{font-size:${k === "zh" ? 58 : 62}px;line-height:1.08;letter-spacing:${k === "zh" ? "0" : "-.035em"};margin:34px 0 0;font-weight:700}
      h1 em{font-style:normal;color:#2f7671}
      p{font-size:22px;line-height:1.5;color:#5f5e5a;margin:22px 0 0}
      .tags{display:flex;gap:10px;margin-top:28px}.tags span{padding:9px 16px;border-radius:99px;background:#e4efed;color:#2f7671;font-size:17px;font-weight:500}
      .shot{position:absolute;left:640px;top:70px;width:800px}
      </style></head><body><div class="glow"></div>
      <div class="l"><div class="brand"><img src="file://${REPO}/assets/icon-256.png">Ragdoll Mail</div>
      <h1>${c.h}</h1><p>${c.p}</p><div class="tags">${c.tags.map((t) => `<span>${t}</span>`).join("")}</div></div>
      <img class="shot" src="file://${REPO}/docs/${c.shot}"></body></html>`;
    const f = `${process.env.TMPDIR || "/tmp"}/ragdoll-og-${k}.html`;
    writeFileSync(f, page);
    await D.goto("file://" + f, 1500);
    await D.js("document.fonts.ready.then(() => 1)");
    await sleep(300);
    await D.shot(`${REPO}/site/img/${c.out}`, { x: 0, y: 0, width: 1200, height: 630 });
  }
  console.log("ok");
} catch (e) { console.log("ERR", e.stack); } finally { D.kill(); process.exit(0); }
