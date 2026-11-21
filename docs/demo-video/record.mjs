// Record one take of the demo: node record.mjs <en|zh> <outdir> [dpr]
// The demo server must hold the mailbox in the same language (ragdoll_app.py --demo --demo-lang <en|zh>).
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
  ? { send: "发送", later: "定时发送", tomorrow: "明天上午", first: "刘洋", q1: "PO-1234", q2: "密封条", who: "张伟",
      ask: "回复张伟：第一批 4 号发货，8 号那周安装没问题。",
      search: "ragdoll search 张伟 PO-1234 --json",
      done: "草稿已经在 Ragdoll Mail 里打开了，你看好了就发。",
      body: "<div>张经理你好，</div><div><br></div><div>第一批 4 号发货，你们现场把安装排在 8 号那一周没有问题。</div>" }
  : { send: "Send", later: "Send later", tomorrow: "Tomorrow morning", first: "Daniel", q1: "PO-1234", q2: "door seal", who: "Jane Doe",
      ask: "Reply to Jane: the first batch ships on the 4th, so the 8th works.",
      search: "ragdoll search jane PO-1234 --json",
      done: "The draft is open in Ragdoll Mail. Send it when you're happy.",
      body: "<div>Hi Jane,</div><div><br></div><div>The first batch ships on the 4th, so your team can plan the installation for the week of the 8th.</div>" };
try {
  await D.goto(`http://127.0.0.1:${process.env.PORT || 8795}/#t=devtok`, 3000);
  // the Mac app's window: traffic lights over the sidebar, as in the native shell; and a terminal to bring in later
  await D.js(`(() => {
    document.documentElement.classList.add("native", "mac");
    const s = document.createElement("style");
    s.textContent = ".tl{position:fixed;left:20px;top:0;height:var(--head-h,52px);display:flex;align-items:center;gap:8px;z-index:99;pointer-events:none}.tl i{width:12px;height:12px;border-radius:50%;box-shadow:inset 0 0 0 .5px rgba(0,0,0,.12)}"
      + ".tw{position:fixed;left:250px;top:118px;width:700px;background:#1b1b1a;border-radius:12px;box-shadow:0 24px 70px rgba(0,0,0,.30),0 0 0 .5px rgba(0,0,0,.4);z-index:98;overflow:hidden;opacity:0;transform:translateY(24px) scale(.97);transition:opacity .35s ease,transform .45s cubic-bezier(.2,.8,.2,1)}"
      + ".tw.on{opacity:1;transform:none}.tw .bar{display:flex;gap:7px;padding:11px 14px 0}.tw .bar b{width:11px;height:11px;border-radius:50%;background:#3a3936}"
      + ".tw pre{margin:0;color:#d9d7d2;padding:12px 20px 18px;font:14px/1.8 ui-monospace,SFMono-Regular,Menlo,'PingFang SC',monospace;white-space:pre-wrap;min-height:250px}"
      + ".tw .p{color:#7fbab5}.tw .y{color:#e3b366}.tw .c{color:#8b8983}.tw .k{display:inline-block;width:8px;height:16px;background:#d9d7d2;vertical-align:-3px;margin-left:1px}";
    document.head.append(s);
    const tl = document.createElement("div"); tl.className = "tl";
    tl.innerHTML = '<i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i>';
    document.body.append(tl);
    const tw = document.createElement("div"); tw.className = "tw";
    tw.innerHTML = '<div class="bar"><b></b><b></b><b></b></div><pre></pre>';
    document.body.append(tw);
    const pre = tw.querySelector("pre"), esc = (x) => x.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
    let lines = [];
    const draw = (cur) => { pre.innerHTML = lines.join("\\n") + (cur ? '<span class="k"></span>' : ""); };
    window.__term = {
      show: (on) => tw.classList.toggle("on", on),
      // one line: a prefix, then the text typed a character at a time
      line: (pre_, text, ms) => new Promise((done) => {
        const i0 = lines.length; let n = 0;
        const step = () => { lines[i0] = pre_ + esc(text.slice(0, n)); draw(n < text.length); if (n++ < text.length) setTimeout(step, ms); else done(); };
        step();
      }),
      out: (html) => { lines.push(html); draw(false); },
    };
  })()`);
  await sleep(300);
  // open the mail with the quote: the opening frame is a full, real mailbox
  const jane = await byText("#rows .row", T.who);
  await clickBox(jane, 50);
  await sleep(1200);
  D.mouse = { x: 980, y: 640 };
  await D.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: D.mouse.x, y: D.mouse.y });
  await sleep(600);
  const mailId = await D.js(`(async () => {
    const call = async (n, a) => (await (await fetch("/api/" + n, { method: "POST", headers: { "X-Token": "devtok", "Content-Type": "application/json" }, body: JSON.stringify(a || {}) })).json());
    const l = await call("list", { folder: "inbox" });
    const r = (l.data || l).rows.find((x) => JSON.stringify(x).includes(${JSON.stringify(T.who)}));
    return r ? r.id : "inbox:1";
  })()`);
  const draftId = "drafts:2";
  await D.record(out + "/frames");
  await sleep(200);
  D.mlog.push([D.now(), D.mouse.x, D.mouse.y]);
  D.mark("start");
  await sleep(700);

  // (a) an AI agent in a terminal writes the reply with the ragdoll command; the draft opens in the app
  D.mark("term");
  await D.js(`__term.show(true)`);
  await sleep(550);
  await D.js(`__term.line('<span class="y">you  </span><span class="c">›</span> ', ${JSON.stringify(T.ask)}, 34)`);
  await sleep(550);
  await D.js(`__term.line('<span class="p">$</span> ', ${JSON.stringify(T.search)}, 20)`);
  await sleep(250);
  await D.js(`__term.line('<span class="p">$</span> ', ${JSON.stringify("ragdoll draft --reply " + mailId + " --body reply.html")}, 20)`);
  await sleep(250);
  await D.js(`__term.line('<span class="p">$</span> ', ${JSON.stringify("ragdoll check " + draftId + " --reply")}, 20)`);
  await sleep(200);
  await D.js(`__term.out('  <span class="p">CHECK OK</span>')`);
  await sleep(350);
  await D.js(`__term.line('<span class="p">$</span> ', ${JSON.stringify("ragdoll open " + draftId)}, 20)`);
  // the app opens the draft behind the terminal, as `ragdoll open` makes it do
  const got = await D.js(`(async () => {
    const r = await fetch("/api/demo_ask", { method: "POST", headers: { "X-Token": "devtok", "Content-Type": "application/json" }, body: JSON.stringify({ id: ${JSON.stringify(mailId)}, html: ${JSON.stringify(T.body)} }) });
    const j = await r.json(); window.ragdollPoll(); return JSON.stringify(j);
  })()`);
  console.log("draft", got);
  await sleep(300);
  await D.js(`__term.line('<span class="y">agent</span> <span class="c">›</span> ', ${JSON.stringify(T.done)}, 20)`);
  D.mark("termdone");
  await sleep(1500);
  D.mark("reveal");
  await D.js(`__term.show(false)`);
  await sleep(1000);
  // (b) you read it and press Send; undo
  const sb = await D.box(`#toolbar button[data-tip="${T.send}"]`);
  await D.move(sb.x + sb.w / 2, sb.y + sb.h / 2, 900);
  await sleep(350);
  await clickBox(sb, 120);
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
  // (c) send later
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
  await sleep(1300);
  // back to the inbox for the search
  const ib = await D.box("#nav .nav-item");
  if (ib) await clickBox(ib, 600);
  await sleep(500);

  // (d) search while typing: a number from the subject, then words from deep in a mail's text
  await remember("searchBtn", "#search-btn");
  await D.clickSel("#search-btn", 650);
  D.mark("type1");
  D.move(700, 112, 450);          // out of the way of the words, while they are typed
  await sleep(250);
  // a pause in the middle, so the list narrows while the words are typed
  const half = (q) => (q.length > 2 ? [q.slice(0, 2), q.slice(2)] : [q.slice(0, 1), q.slice(1)]);
  const typeIn = async (q) => { const [a, b] = half(q); await D.type(a, 110); await sleep(480); await D.type(b, 95); };
  await typeIn(T.q1);
  D.mark("typed1");
  await sleep(1150);
  D.mark("type2");
  await D.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 4, commands: ["selectAll"] });
  await D.send("Input.dispatchKeyEvent", { type: "keyUp", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 4 });
  await sleep(150);
  await typeIn(T.q2);
  D.mark("typed2");
  await sleep(700);
  const hit = await D.box("#rows .row");
  if (hit) await clickBox(hit, 600);
  D.mark("hit");
  await sleep(1800);
  D.mark("end");
  await D.stop();
  await sleep(200);
  writeFileSync(out + "/take.json", JSON.stringify({ dpr: DPR, w: 1280, h: 800, frames: D.frames.map(([t, f]) => [t, f.split("/").pop()]), mouse: D.mlog, clicks: D.clicks, marks: Object.fromEntries(D.marks), boxes }, null, 1));
  console.log("frames", D.frames.length, "duration", D.now().toFixed(2), JSON.stringify(Object.fromEntries(D.marks.map(([k, v]) => [k, +v.toFixed(2)]))));
} catch (e) { console.log("ERR", e.stack); } finally { D.kill(); process.exit(0); }
