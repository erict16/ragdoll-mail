// Record one take of the demo: node record.mjs <en|zh> <outdir> [dpr]
// Saves screencast frames, frames.json (times), mouse log, clicks, beat marks and element boxes.
import { launch, sleep } from "./drv.mjs";
import { writeFileSync } from "node:fs";

const [lang = "en", out = "take-" + lang, dprArg] = process.argv.slice(2);
const DPR = +(dprArg || 2.5);
const D = await launch({ width: 1280, height: 800, dpr: DPR, lang: lang === "zh" ? "zh-CN" : "en-US" });
const boxes = {};
const remember = async (name, sel) => { boxes[name] = await D.box(sel); return boxes[name]; };
const byText = async (sel, text) => D.js(`(() => { const x = [...document.querySelectorAll(${JSON.stringify(sel)})].find(b => b.innerText.trim().includes(${JSON.stringify(text)})); if (!x) return null; const r = x.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; })()`);
const clickBox = (b, ms) => D.click(b.x + b.w / 2, b.y + b.h / 2, ms);
const T = lang === "zh"
  ? { reply: "回复", send: "发送", later: "定时发送", tomorrow: "明天上午" }
  : { reply: "Reply", send: "Send", later: "Send later", tomorrow: "Tomorrow morning" };
try {
  await D.goto(`http://127.0.0.1:${process.env.PORT || 8795}/#t=devtok`, 3000);
  // the Mac app's window: traffic lights over the sidebar, as in the native shell
  await D.js(`(() => {
    document.documentElement.classList.add("native", "mac");
    const s = document.createElement("style");
    s.textContent = ".tl{position:fixed;left:20px;top:0;height:var(--head-h,52px);display:flex;align-items:center;gap:8px;z-index:99;pointer-events:none}.tl i{width:12px;height:12px;border-radius:50%;box-shadow:inset 0 0 0 .5px rgba(0,0,0,.12)}";
    document.head.append(s);
    const tl = document.createElement("div"); tl.className = "tl";
    tl.innerHTML = '<i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i>';
    document.body.append(tl);
  })()`);
  await sleep(300);
  // open the mail with the site photo first, so the opening frame is a full, real mailbox
  const rows = await D.js(`[...document.querySelectorAll("#rows .row")].map(r => r.innerText.split("\\n")[0])`);
  const dan = rows.findIndex((x) => x.includes("Daniel"));
  await D.clickSel(`#rows .row:nth-child(${dan + 1})`, 50);
  await sleep(1200);
  D.mouse = { x: 760, y: 250 };
  await D.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: D.mouse.x, y: D.mouse.y });
  await sleep(600);
  await D.record(out + "/frames");
  await sleep(200);
  D.mlog.push([D.now(), D.mouse.x, D.mouse.y]);
  D.mark("start");
  await sleep(500);

  // (a) search while typing
  await remember("searchBtn", "#search-btn");
  await D.clickSel("#search-btn", 520);
  D.mark("type1");
  D.move(700, 112, 450);          // out of the way of the words, while they are typed
  await sleep(250);
  const [q1, q2] = lang === "zh" ? ["图纸", "PO-1234"] : ["PO-1234", "图纸"];
  // a pause in the middle, so the list narrows while the words are typed
  const half = (q) => (q.length > 2 ? [q.slice(0, 2), q.slice(2)] : [q.slice(0, 1), q.slice(1)]);
  const typeIn = async (q) => { const [a, b] = half(q); await D.type(a, 110); await sleep(480); await D.type(b, 95); };
  await typeIn(q1);
  D.mark("typed1");
  await sleep(1150);
  D.mark("type2");
  await D.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 4, commands: ["selectAll"] });
  await D.send("Input.dispatchKeyEvent", { type: "keyUp", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 4 });
  await sleep(150);
  await typeIn(q2);
  D.mark("typed2");
  await sleep(1150);
  if (lang !== "zh") {
    // back to the whole inbox, then the mail from Jane
    await D.clickSel("#search-clear", 650);
    await sleep(500);
  }
  const jane = await byText("#rows .row", "Jane Doe");
  D.mark("open");
  await clickBox(jane, 700);
  await sleep(300);
  D.mark("read");
  // (b) read: let the eye travel over the header and the attachments
  await sleep(500);
  await remember("atts", "#pane .atts, #pane [class*=att]");
  const att = await D.js(`(() => { const x = [...document.querySelectorAll("#pane *")].filter(n => !n.children.length && /\\.pdf$/.test(n.textContent.trim()))[0]; if (!x) return null; const r = x.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; })()`);
  if (att) await D.move(att.x + att.w * 0.6, att.y + att.h / 2 + 4, 900); else console.log('no pdf');
  await sleep(900);
  // (c) reply
  const rb = await byText("#pane button.btn", T.reply);
  D.mark("toreply");
  await D.move(rb.x + rb.w / 2, rb.y + rb.h / 2, 800);
  await sleep(250);
  await clickBox(rb, 120);
  await sleep(700);
  D.mark("compose");
  await D.move(1010, 330, 500);
  await D.type("Hi Jane, the first batch ships on the 4th.", 22);
  D.mark("typedReply");
  await sleep(500);
  // (d) undo send
  const sb = await D.box(`#toolbar button[data-tip="${T.send}"]`);
  await clickBox(sb, 650);
  D.mark("sent");
  await sleep(250);
  const ub = await D.box("#toasts .toast-act");
  boxes.toast = await D.box("#toasts .toast");
  await D.move(ub.x + ub.w / 2, ub.y + ub.h / 2, 750);
  await sleep(450);
  D.mark("undo");
  await clickBox(ub, 100);
  await sleep(900);
  D.mark("back");
  // (e) send later
  const lb = await D.box(`#toolbar button[data-tip="${T.later}"]`);
  await clickBox(lb, 700);
  D.mark("menu");
  await sleep(500);
  boxes.menu = await D.box("#layer .menu");
  const tb = await byText("#layer .menu button", T.tomorrow);
  await D.move(tb.x + 60, tb.y + tb.h / 2, 600);
  await sleep(650);
  await clickBox(tb, 100);
  D.mark("scheduled");
  await sleep(250);
  boxes.toast2 = await D.box("#toasts .toast");
  await sleep(1700);
  D.mark("end");
  await D.stop();
  await sleep(200);
  writeFileSync(out + "/take.json", JSON.stringify({ dpr: DPR, w: 1280, h: 800, frames: D.frames.map(([t, f]) => [t, f.split("/").pop()]), mouse: D.mlog, clicks: D.clicks, marks: Object.fromEntries(D.marks), boxes }, null, 1));
  console.log("frames", D.frames.length, "duration", D.now().toFixed(2), JSON.stringify(Object.fromEntries(D.marks.map(([k, v]) => [k, +v.toFixed(2)]))));
} catch (e) { console.log("ERR", e.stack); } finally { D.kill(); process.exit(0); }
