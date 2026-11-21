// The site's feature screenshots, from the demo mailbox in one language: node shots.mjs <en|zh> <outdir>
// The demo server must hold the mailbox in the same language (ragdoll_app.py --demo --demo-lang <en|zh>).
// Writes hero.png, search.png and compose.png (the app at 1280x800, 2x), framed later by frame.py.
import { launch, sleep } from "./drv.mjs";

const [lang = "en", out = "."] = process.argv.slice(2);
const T = lang === "zh"
  ? { q: "报价", who: "张伟",
      body: "<div>张经理你好，</div><div><br></div><div>第一批的安排如下：</div><ul><li>4 号从工厂发货</li><li>7 号前到你们现场</li><li>8 号起我们的工程师在现场</li></ul><div><b>麻烦周五前确认收货地址。</b></div>" }
  : { q: "PO-1234", who: "Jane Doe",
      body: "<div>Hi Jane,</div><div><br></div><div>Here is the plan for the first batch:</div><ul><li>Ships from our factory on the 4th</li><li>Arrives at your site by the 7th</li><li>Our engineer is on site from the 8th</li></ul><div><b>Please confirm the delivery address</b> by Friday.</div>" };
const D = await launch({ width: 1280, height: 800, dpr: 2, lang: lang === "zh" ? "zh-CN" : "en-US" });
const port = process.env.PORT || 8795;
const call = (n, a) => D.js(`fetch("/api/${n}", { method: "POST", headers: { "X-Token": "devtok", "Content-Type": "application/json" }, body: ${JSON.stringify(JSON.stringify(a || {}))} }).then(r => r.json())`);
try {
  await D.goto(`http://127.0.0.1:${port}/#t=devtok`, 3000);
  await D.js(`document.documentElement.classList.add("native", "mac")`);
  // the inbox with the quote open
  const first = await D.js(`[...document.querySelectorAll("#rows .row")].findIndex(r => r.innerText.includes(${JSON.stringify(T.who)}))`);
  await D.clickSel(`#rows .row:nth-child(${first + 1})`, 50);
  await sleep(1200);
  await D.move(640, 790, 10);
  await sleep(400);
  await D.shot(out + "/hero.png");
  // search: the words typed, the first hit open
  await D.clickSel("#search-btn", 50);
  await sleep(300);
  await D.type(T.q, 30);
  await sleep(900);
  await D.clickSel("#rows .row", 50);
  await sleep(1200);
  await D.move(640, 790, 10);
  await sleep(400);
  await D.shot(out + "/search.png");
  // compose: a reply the agent drafted, opened in the app
  await D.clickSel("#search-clear", 50);
  await sleep(500);
  const l = await call("list", { folder: "inbox" });
  const row = (l.data || l).rows.find((x) => JSON.stringify(x).includes(T.who));
  await call("demo_ask", { id: row.id, html: T.body });
  await D.js("window.ragdollPoll()");
  await sleep(1800);
  await D.move(640, 790, 10);
  await sleep(600);
  await D.shot(out + "/compose.png");
  console.log("ok");
} catch (e) { console.log("ERR", e.stack); } finally { D.kill(); process.exit(0); }
