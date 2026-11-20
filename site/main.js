// Ragdoll Mail site: the demo video, the search race, the right download first, a line under the bar, sections that rise in.
(() => {
  const $ = (s, n = document) => n.querySelector(s);
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // the download for this computer goes first
  const win = /Windows/i.test(navigator.userAgent);
  if (win) {
    document.querySelectorAll(".cta").forEach((cta) => {
      const [mac, w] = [$("[data-os=mac]", cta), $("[data-os=win]", cta)];
      if (mac && w) { mac.classList.remove("primary"); w.classList.add("primary"); cta.prepend(w); }
    });
    const top = $(".top [data-dl]"), w = $("[data-os=win]");
    if (top && w) top.href = w.href;
  }

  const bar = $(".top");
  const onScroll = () => bar && bar.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -10% 0px" });
  document.querySelectorAll(".reveal").forEach((n) => io.observe(n));

  // ---- the demo video: loads after the page, plays while on screen; with reduced motion it waits for a click
  const demo = $(".shot .demo");
  if (demo && demo.dataset.src) {
    demo.muted = true;
    demo.src = demo.dataset.src;
    if (still) demo.controls = true;
    else {
      demo.preload = "auto";
      const play = () => demo.play().catch(() => { demo.controls = true; });
      new IntersectionObserver((es) => { if (es[0].intersectionRatio >= 0.5) play(); else demo.pause(); }, { threshold: 0.5 }).observe(demo);
    }
  }

  // ---- the search race: the same words in the mailbox's own search and in Ragdoll Mail
  const race = $(".race");
  const data = $("#race-data");
  if (!race || !data) return;
  const D = JSON.parse(data.textContent);
  const typed = $(".typed", race), tc = $(".theirs .count", race), tn = $(".theirs .count-note", race),
    tr = $(".theirs .rows", race), oc = $(".ours .count", race), on = $(".ours .count-note", race), or = $(".ours .rows", race);
  const fmt = (n) => n.toLocaleString("en-US");
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const hl = (s, w) => { const i = s.toLowerCase().indexOf(w.toLowerCase()); return i < 0 ? esc(s) : esc(s.slice(0, i)) + "<mark>" + esc(s.slice(i, i + w.length)) + "</mark>" + esc(s.slice(i + w.length)); };
  const rowHTML = (r, w) => `<div class="row"><b>${hl(r[0], w)}</b><span>${hl(r[1], w)}</span></div>`;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let visible = false;
  new IntersectionObserver((es) => { visible = es[0].isIntersecting; }).observe(race);

  function show(q, done) {
    typed.textContent = q.word;
    oc.textContent = fmt(q.rows.length);
    on.textContent = q.rows.length ? D.fast : D.none;
    or.innerHTML = q.rows.map((r) => rowHTML(r, q.word)).join("");
    tc.textContent = done ? fmt(D.theirs) : "…";
    tn.textContent = done ? D.theirsNote : D.searching;
    tr.innerHTML = done ? D.noise.map((r) => rowHTML(r, "")).join("") : "";
  }
  if (still) { show(D.words[0], true); return; }

  async function count(to, ms) {
    const t0 = performance.now();
    for (;;) {
      const k = Math.min(1, (performance.now() - t0) / ms);
      tc.textContent = fmt(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k >= 1) return;
      await new Promise(requestAnimationFrame);
    }
  }
  (async function loop() {
    for (let i = 0; ; i = (i + 1) % D.words.length) {
      while (!visible) await sleep(300);
      const q = D.words[i];
      typed.textContent = ""; or.innerHTML = ""; tr.innerHTML = ""; oc.textContent = "\u00a0"; tc.textContent = "\u00a0";
      on.textContent = ""; tn.textContent = "";
      for (const ch of q.word) { typed.textContent += ch; await sleep(110 + Math.random() * 70); }
      await sleep(120);
      // Ragdoll Mail answers at once
      oc.textContent = fmt(q.rows.length);
      on.textContent = q.rows.length ? D.fast : D.none;
      or.innerHTML = q.rows.map((r, j) => rowHTML(r, q.word).replace('class="row"', `class="row" style="animation-delay:${j * 60}ms"`)).join("");
      // the mailbox's own search takes its time, and gives back everything
      tn.textContent = D.searching;
      await sleep(900);
      await count(D.theirs, 1400);
      tn.textContent = D.theirsNote;
      tr.innerHTML = D.noise.map((r) => rowHTML(r, "")).join("");
      await sleep(3600);
    }
  })();
})();
