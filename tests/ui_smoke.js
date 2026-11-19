// Click through the app on the demo mailbox and note what breaks. Run by tests/ui_smoke.py (it can also be
// pasted into a browser console on  python -m ragdoll_app --demo --browser).  Result: window.__smoke
(async () => {
  const errors = [], steps = [];
  addEventListener("error", (e) => errors.push("error: " + (e.message || e.error)));
  addEventListener("unhandledrejection", (e) => errors.push("rejection: " + (e.reason?.message || e.reason)));
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const until = async (fn, what, ms = 5000) => {
    for (const end = Date.now() + ms; ;) {
      let v; try { v = fn(); } catch { /* not yet */ }
      if (v) return v;
      if (Date.now() > end) throw new Error("waited for " + what);
      await sleep(30);
    }
  };
  const key = (k, o = {}) => document.body.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...o }));
  const step = async (name, fn) => {
    const before = errors.length;
    try { await fn(); steps.push((errors.length > before ? "FAIL " : "ok   ") + name + (errors.length > before ? ": " + errors.slice(before).join("; ") : "")); }
    catch (e) { steps.push("FAIL " + name + ": " + e.message); }
  };
  const rows = () => $$("#rows .row");
  const row = (text) => rows().find((n) => n.textContent.includes(text));
  const tools = () => $$("#tools .icon-btn");
  const noLayer = () => until(() => !$(".menu") && !$(".sheet"), "the menu or sheet to close");
  const inbox = async () => { $(".nav .nav-item").click(); await until(() => rows().length > 5, "the Inbox"); };

  await step("the list shows mail", () => until(() => rows().length > 5, "rows"));
  await step("every folder opens", async () => {
    const n = $$(".nav .nav-item").length;
    if (n < 8) throw new Error("only " + n + " folders in the sidebar");
    for (let k = 0; k < n; k++) { $$(".nav .nav-item")[k].click(); await sleep(150); }
    await inbox();
  });
  await step("a mail opens with its text", async () => {
    row("Quote for PO-1234").click();
    await until(() => $("#pane .msg"), "the mail");
    await until(() => $("#pane iframe") || $("#pane .msg-body")?.textContent.trim(), "the mail's text");
    await until(() => $("#pane .msg-body > .atts.top:first-child .att"), "its files, on top of the text");
  });
  await step("a meeting invite shows its card", async () => {
    row("PO-1234 delivery review").click();
    await until(() => $("#pane .invite .inv-acts"), "the invite card");
  });
  await step("keys: next, previous, star, unread", async () => {
    for (const k of ["j", "k", "s", "s", "u", "u"]) { key(k); await sleep(120); }
  });
  await step("snooze menu", async () => {
    key("b");
    await until(() => $(".menu"), "the snooze menu");
    key("Escape"); await noLayer();
  });
  await step("shortcuts sheet", async () => {
    key("?");
    await until(() => $(".sheet.keys-sheet"), "the sheet");
    key("Escape"); await noLayer();
  });
  await step("reply opens with the quoted mail, then is dropped", async () => {
    key("r");
    await until(() => $(".compose .editor"), "the reply");
    await until(() => $(".compose iframe") || $(".compose .quote-toggle"), "the quoted mail");
    $("#tools-end .icon-btn").click();
    await until(() => !$(".compose"), "compose to close");
  });
  await step("new mail: templates, send later, formatting bar", async () => {
    key("c");
    await until(() => $(".compose .editor"), "compose");
    $(".compose .subject-input").value = "Smoke test";
    $(".compose .subject-input").dispatchEvent(new Event("input", { bubbles: true }));
    tools()[4].click(); await until(() => $(".menu"), "the template menu"); key("Escape"); await noLayer();
    tools()[2].click(); await until(() => $(".menu"), "the send-later menu"); key("Escape"); await noLayer();
    const shut = () => $(".fmt-bar").classList.contains("shut"), was = shut();
    tools()[5].click(); await until(() => shut() !== was, "the formatting bar to toggle");
    tools()[5].click(); await until(() => shut() === was, "the formatting bar to toggle back");
    $("#tools-end .icon-btn").click();
    await until(() => !$(".compose"), "compose to close");
  });
  await step("search finds mail and clears", async () => {
    const s = $("#search");
    s.value = "invoice"; s.dispatchEvent(new Event("input", { bubbles: true }));
    await until(() => rows().length > 0 && rows().length < 8 && row("INV-"), "the results");
    s.value = ""; s.dispatchEvent(new Event("input", { bubbles: true }));
    await until(() => rows().length > 8, "the full list again");
  });
  await step("select all, then clear", async () => {
    key("a", { ctrlKey: true });
    await until(() => $$("#rows .row.sel, #rows .row.multi, #rows .row.on").length > 5 || tools().length >= 3, "the selection");
    key("Escape"); await sleep(200);
  });
  await step("settings: every tab", async () => {
    key(",", { ctrlKey: true });
    await until(() => $(".settings-nav .nav-item"), "settings");
    const n = $$(".settings-nav .nav-item").length;
    if (n < 6) throw new Error("only " + n + " tabs");
    for (let k = 0; k < n; k++) {
      $$(".settings-nav .nav-item")[k].click();
      await until(() => $(".settings-body")?.children.length, "tab " + k);
      await sleep(80);
    }
    key("Escape"); await noLayer();
  });
  await step("settings has the icon-number switch, off by default", async () => {
    key(",", { ctrlKey: true });
    await until(() => $(".settings-nav .nav-item"), "settings");
    $$(".settings-nav .nav-item")[5].click();
    const segs = await until(() => $$(".settings-body .seg").length === 2 && $$(".settings-body .seg"), "two switches");
    if (!segs[1].lastElementChild.classList.contains("on")) throw new Error("the icon number is not off by default");
    key("Escape"); await noLayer();
  });
  await step("account menu", async () => {
    $("#account").click();
    await until(() => $(".menu"), "the menu");
    key("Escape"); await noLayer();
  });
  await step("the page waits for changes instead of asking again and again", async () => {
    const waits = () => performance.getEntriesByType("resource").filter((e) => e.name.endsWith("/api/status")).length;
    const n = waits();
    await sleep(1500);
    if (waits() !== n) throw new Error("status was asked again while idle");
  });
  window.__smoke = { ok: !steps.some((s) => s.startsWith("FAIL")) && !errors.length, steps, errors };
  return window.__smoke;
})();
