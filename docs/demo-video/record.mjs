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
  ? { inbox: "收件箱", drafts: "草稿箱", sent: "已发送", q1: "密封条", hitWho: "刘洋", who: "张伟",
      ask: "回复张伟：第一批 4 号发货，8 号那周安装没问题。先存草稿。",
      search: "ragdoll search 张伟 PO-1234 --json",
      saved: "草稿存好了，在草稿箱里。",
      yes: "看过了，发吧。",
      done: "发出去了。",
      body: "<div>张经理你好，</div><div><br></div><div>第一批 4 号发货，你们现场把安装排在 8 号那一周没有问题。</div>" }
  : { inbox: "Inbox", drafts: "Drafts", sent: "Sent", q1: "door seal", hitWho: "Daniel", who: "Jane Doe",
      ask: "Reply to Jane: the first batch ships on the 4th, so the 8th works. Save it as a draft.",
      search: "ragdoll search jane PO-1234 --json",
      saved: "The reply is saved in your Drafts.",
      yes: "Looks good. Send it.",
      done: "Sent.",
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
      + ".tw pre{margin:0;color:#d9d7d2;padding:12px 20px 18px;font:14px/1.8 ui-monospace,SFMono-Regular,Menlo,Consolas,'Cascadia Mono','PingFang SC','Microsoft YaHei',monospace;white-space:pre-wrap;min-height:250px}"
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
      clear: () => { lines = []; draw(false); },
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
  await D.record(out + "/frames");
  await sleep(200);
  D.mlog.push([D.now(), D.mouse.x, D.mouse.y]);
  D.mark("start");
  await sleep(700);

  const say = (who, text, ms = 30) => D.js(`__term.line(${JSON.stringify(who === "you" ? '<span class="y">you  </span><span class="c">›</span> ' : '<span class="y">agent</span> <span class="c">›</span> ')}, ${JSON.stringify(text)}, ${ms})`);
  const run = (cmd) => D.js(`__term.line('<span class="p">$</span> ', ${JSON.stringify(cmd)}, 18)`);
  const show = (text) => D.js(`__term.out(${JSON.stringify('  <span class="c">' + text + "</span>")})`);
  const nav = async (label, ms = 800) => { const b = await byText("#nav .nav-item", label); await clickBox(b, ms); };

  // (a) an AI agent in a terminal writes the reply with the ragdoll command and saves it as a draft
  D.mark("term");
  await D.js(`__term.show(true)`);
  await sleep(550);
  await say("you", T.ask, 32);
  await sleep(500);
  await run(T.search);
  await sleep(250);
  await run("ragdoll draft --reply " + mailId + " --body reply.html");
  // the draft lands in the mailbox, as `ragdoll draft` makes it do
  const draftId = await D.js(`(async () => {
    const r = await fetch("/api/demo_ask", { method: "POST", headers: { "X-Token": "devtok", "Content-Type": "application/json" }, body: JSON.stringify({ id: ${JSON.stringify(mailId)}, html: ${JSON.stringify(T.body)}, open: false }) });
    const j = await r.json(); window.ragdollPoll(); return (j.data || j).id;
  })()`);
  console.log("draft", draftId);
  const shortId = "drafts:" + String(draftId).split(":").pop();
  await show(`{"id": "${shortId}"}`);
  await sleep(250);
  await run("ragdoll check " + shortId + " --reply");
  await show('<span class="p">CHECK OK</span>');
  await sleep(300);
  await say("agent", T.saved, 22);
  D.mark("termdone");
  await sleep(1300);
  D.mark("reveal");
  await D.js(`__term.show(false)`);
  await sleep(700);

  // (b) you find it in Drafts and read it
  D.mark("drafts");
  await nav(T.drafts, 900);
  await sleep(700);
  const dr = await D.box("#rows .row");
  await clickBox(dr, 650);
  D.mark("draftopen");
  await sleep(2400);

  // (c) you say yes; the agent sends it
  D.mark("term2");
  await D.js(`__term.clear(); __term.show(true)`);
  await sleep(500);
  await say("you", T.yes, 40);
  await sleep(450);
  await run("ragdoll send " + shortId + " --yes");
  await D.js(`(async () => {
    await fetch("/api/send", { method: "POST", headers: { "X-Token": "devtok", "Content-Type": "application/json" }, body: JSON.stringify({ id: ${JSON.stringify(draftId)} }) });
    window.ragdollPoll();
  })()`);
  await show('{"sent": true}');
  await sleep(250);
  await say("agent", T.done, 30);
  D.mark("termdone2");
  await sleep(1100);
  D.mark("reveal2");
  await D.js(`__term.show(false)`);
  await sleep(600);

  // (d) it is in Sent
  D.mark("sent");
  await nav(T.sent, 900);
  await sleep(700);
  const sr = await D.box("#rows .row");
  await clickBox(sr, 650);
  D.mark("sentopen");
  await sleep(2000);

  // (e) back to the inbox, then search while typing
  D.mark("inbox");
  await nav(T.inbox, 800);
  await sleep(600);
  await remember("searchBtn", "#search-btn");
  await D.clickSel("#search-btn", 650);
  D.mark("type1");
  D.move(700, 112, 450);
  await sleep(250);
  await D.type(T.q1.slice(0, 2), 110); await sleep(450); await D.type(T.q1.slice(2), 95);
  D.mark("typed1");
  await sleep(1000);
  let hit = null;   // the mail with the words, once the list has narrowed to it
  for (let i = 0; i < 20 && !hit; i++) { hit = await byText("#rows .row", T.hitWho); if (!hit) await sleep(150); }
  if (hit) await clickBox(hit, 600);
  D.mark("hit");
  await sleep(1800);
  D.mark("end");
  await D.stop();
  await sleep(200);
  writeFileSync(out + "/take.json", JSON.stringify({ dpr: DPR, w: 1280, h: 800, frames: D.frames.map(([t, f]) => [t, f.split("/").pop()]), mouse: D.mlog, clicks: D.clicks, marks: Object.fromEntries(D.marks), boxes }, null, 1));
  console.log("frames", D.frames.length, "duration", D.now().toFixed(2), JSON.stringify(Object.fromEntries(D.marks.map(([k, v]) => [k, +v.toFixed(2)]))));
} catch (e) { console.log("ERR", e.stack); } finally { D.kill(); process.exit(0); }
