// Small CDP driver: headless Chromium, real input, screencast to frames with timestamps.
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
// any Chromium with H.264 works; set CHROME to its binary (default: Playwright's headless shell on an Apple silicon Mac)
const CH = process.env.CHROME || `${process.env.HOME}/Library/Caches/ms-playwright/chromium_headless_shell-1255/chrome-headless-shell-mac-arm64/chrome-headless-shell`;
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export async function launch({ width = 1280, height = 800, dpr = 2, theme = "light", lang, transparent } = {}) {
  const port = 20000 + Math.floor(Math.random() * 20000);
  const args = ["--headless", `--remote-debugging-port=${port}`, "--hide-scrollbars", `--force-device-scale-factor=${dpr}`,
    `--window-size=${width},${height}`, "--autoplay-policy=no-user-gesture-required", "about:blank"];
  if (lang) args.unshift(`--lang=${lang}`);
  const proc = spawn(CH, args, { stdio: "ignore" });
  const kill = () => { try { proc.kill("SIGKILL"); } catch {} };
  process.on("exit", kill);
  let ws;
  for (let i = 0; i < 60 && !ws; i++) {
    await sleep(200);
    try {
      const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((p) => p.type === "page");
      if (page) ws = new WebSocket(page.webSocketDebuggerUrl);
    } catch {}
  }
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0; const waiting = new Map(); const handlers = {};
  ws.addEventListener("message", (m) => {
    const d = JSON.parse(m.data);
    if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); }
    else if (d.method && handlers[d.method]) handlers[d.method](d.params);
  });
  const send = (method, params = {}) => new Promise((r) => { const n = ++id; waiting.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  const js = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || JSON.stringify(r.result.exceptionDetails));
    return r.result?.result?.value;
  };
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: dpr, mobile: false });
  if (theme) await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }] });
  if (lang) {
    const ua = (await send("Browser.getVersion")).result.userAgent.replace("HeadlessChrome", "Chrome");
    await send("Emulation.setUserAgentOverride", { userAgent: ua, acceptLanguage: lang, platform: "MacIntel" });
    await send("Emulation.setLocaleOverride", { locale: lang });
  }
  if (transparent)await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
  const D = { send, js, kill, handlers, width, height, dpr, mouse: { x: width * 0.62, y: height * 0.7 }, mlog: [], clicks: [], marks: [], t0: null };
  D.now = () => (D.t0 == null ? 0 : (performance.now() - D.t0) / 1000);
  D.mark = (name) => { D.marks.push([name, D.now()]); };
  D.goto = async (url, wait = 2500) => { await send("Page.navigate", { url }); await sleep(wait); };
  D.shot = async (out, clip, omitBackground) => {
    const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: !!clip, ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
    writeFileSync(out, Buffer.from(r.result.data, "base64"));
  };
  D.box = async (sel) => js(`(() => { const n = document.querySelector(${JSON.stringify(sel)}); if (!n) return null; const b = n.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height }; })()`);
  // move the mouse smoothly (eased), logging positions for the drawn cursor
  D.move = async (x, y, ms = 600) => {
    const { x: x0, y: y0 } = D.mouse; const steps = Math.max(2, Math.round(ms / 16));
    for (let i = 1; i <= steps; i++) {
      const k = i / steps, e = k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      const nx = x0 + (x - x0) * e, ny = y0 + (y - y0) * e;
      D.mouse = { x: nx, y: ny }; D.mlog.push([D.now(), nx, ny]);
      await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: nx, y: ny });
      await sleep(ms / steps);
    }
  };
  D.click = async (x, y, ms = 600) => {
    await D.move(x, y, ms); await sleep(90);
    D.clicks.push([D.now(), x, y]);
    await send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await sleep(70);
    await send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  };
  D.clickSel = async (sel, ms = 600, dx = 0.5, dy = 0.5) => { const b = await D.box(sel); if (!b) throw new Error("no " + sel); return D.click(b.x + b.w * dx, b.y + b.h * dy, ms); };
  D.type = async (text, per = 85) => { for (const ch of text) { await send("Input.insertText", { text: ch }); await sleep(per + Math.random() * 40); } };
  D.key = async (key, code, vk, mods = 0) => {
    await send("Input.dispatchKeyEvent", { type: "rawKeyDown", key, code, windowsVirtualKeyCode: vk, modifiers: mods });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: vk, modifiers: mods });
  };
  // screencast: every frame saved with its time
  D.record = async (dir) => {
    mkdirSync(dir, { recursive: true }); D.frames = []; let n = 0;
    handlers["Page.screencastFrame"] = async (p) => {
      send("Page.screencastFrameAck", { sessionId: p.sessionId });
      if (D.t0 == null) return;
      const f = `${dir}/f${String(n++).padStart(5, "0")}.jpg`;
      writeFileSync(f, Buffer.from(p.data, "base64"));
      D.frames.push([D.now(), f]);
    };
    D.t0 = performance.now();
    await send("Page.startScreencast", { format: "jpeg", quality: 96, maxWidth: width * dpr, maxHeight: height * dpr, everyNthFrame: 1 });
  };
  D.stop = async () => { await send("Page.stopScreencast"); };
  return D;
}
