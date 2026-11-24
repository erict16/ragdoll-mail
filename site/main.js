// Ragdoll Mail site: the right download first, the demo that stands up as you scroll,
// the agent that types its draft, and the search race with its one big number.
(() => {
  const $ = (s, n = document) => n.querySelector(s);
  const $$ = (s, n = document) => [...n.querySelectorAll(s)];
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const watch = (el, fn, threshold = 0.35) => {
    if (el) new IntersectionObserver((es) => es.forEach((e) => fn(e.isIntersecting)), { threshold }).observe(el);
  };

  // ---- the download for this computer goes first
  if (/Windows/i.test(navigator.userAgent)) {
    $$(".cta").forEach((cta) => {
      const [mac, w] = [$("[data-os=mac]", cta), $("[data-os=win]", cta)];
      if (mac && w) { mac.classList.remove("primary"); w.classList.add("primary"); cta.prepend(w); }
    });
    const top = $(".top [data-dl]"), w = $("[data-os=win]");
    if (top && w) top.href = w.href;
  }

  // ---- GitHub stars beside the GitHub link (kept for an hour so the API is asked rarely)
  (async () => {
    const spots = $$("[data-stars]");
    if (!spots.length) return;
    const KEY = "rd-stars";
    const fmt = (n) => (n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n));
    const show = (n) => spots.forEach((s) => {
      $("b", s).textContent = fmt(n);
      s.hidden = false;
      s.parentElement.setAttribute("aria-label", `GitHub, ${n} stars`);
    });
    let kept = null;
    try { kept = JSON.parse(localStorage.getItem(KEY)); } catch {}
    if (kept && Number.isFinite(kept.n)) show(kept.n);
    if (kept && Date.now() - kept.t < 36e5) return;
    try {
      const r = await fetch("https://api.github.com/repos/erict16/ragdoll-mail");
      if (!r.ok) return;
      const n = (await r.json()).stargazers_count;
      if (!Number.isFinite(n)) return;
      show(n);
      try { localStorage.setItem(KEY, JSON.stringify({ n, t: Date.now() })); } catch {}
    } catch {}
  })();

  // ---- the language menu closes on a click outside it, or Escape
  const langs = $$(".top .lang");
  addEventListener("click", (ev) => langs.forEach((d) => { if (!d.contains(ev.target)) d.open = false; }));
  addEventListener("keydown", (ev) => { if (ev.key === "Escape") langs.forEach((d) => { d.open = false; }); });

  // ---- a line under the bar, sections that rise in
  const bar = $(".top");
  const onScroll = () => bar && bar.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -10% 0px" });
  $$(".reveal").forEach((n) => io.observe(n));

  // ---- hero: the window lies back and stands up as you scroll
  const shot = $(".shot");
  if (shot) {
    const tilt = () => {
      const r = shot.getBoundingClientRect();
      const t = still ? 0 : Math.min(1, Math.max(0, (r.top - innerHeight * 0.12) / (innerHeight * 0.55)));
      shot.style.setProperty("--t", t.toFixed(3));
    };
    let raf = 0;
    addEventListener("scroll", () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; tilt(); }); }, { passive: true });
    addEventListener("resize", tilt);
    tilt();
  }

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
  const snd = $(".shot .sound");
  if (demo && snd) snd.addEventListener("click", () => {
    const on = demo.muted;
    demo.muted = !on;
    if (on) { demo.volume = 0.6; demo.play().catch(() => {}); }
    snd.setAttribute("aria-pressed", String(on));
    snd.setAttribute("aria-label", on ? snd.dataset.off : snd.dataset.on);
  });

  // ---- the agent: the ask and the commands type out, then the draft lands; it plays again while in view
  const duo = $(".duo");
  if (duo) {
    const lines = $$(".term .ln", duo);
    if (still) { lines.forEach((l) => l.classList.add("in")); duo.classList.add("done"); }
    else {
      let vis = false, running = false;
      const play = async () => {
        running = true;
        duo.classList.remove("done");
        lines.forEach((l) => { l.classList.remove("in", "cur"); const t = $(".tx", l); if (t) t.textContent = ""; });
        await sleep(350);
        for (const l of lines) {
          l.classList.add("in", "cur");
          const t = $(".tx", l);
          if (t) {
            const full = t.dataset.t, gap = full.length > 44 ? 14 : 24;
            for (let i = 1; i <= full.length; i++) { t.textContent = full.slice(0, i); await sleep(gap); }
            await sleep(260);
          } else await sleep(l.classList.contains("say") ? 600 : 300);
          l.classList.remove("cur");
          if (l.classList.contains("land")) duo.classList.add("done");
        }
        duo.classList.add("done");
        await sleep(7000);
        running = false;
        if (vis) play();
      };
      watch(duo, (v) => { vis = v; if (v && !running) play(); }, 0.35);
    }
  }

  // ---- the big number counts up the first time it is seen
  const mega = $(".mega b[data-n]");
  if (mega && !still) {
    const n = +mega.dataset.n, suf = mega.textContent.replace(/^[\d.,]+/, "");
    mega.textContent = "1" + suf;
    let done = false;
    watch(mega, (v) => {
      if (!v || done) return;
      done = true;
      const t0 = performance.now();
      const step = (now) => {
        const p = Math.min(1, (now - t0) / 1400);
        mega.textContent = Math.max(1, Math.round(n * (1 - (1 - p) ** 3))) + suf;
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }, 0.6);
  }

  // ---- the race: both searches, in real time, again on request
  const race = $(".race");
  if (race) {
    const [ro, rs] = $$(".race-row", race);
    const ours = +race.dataset.ours, srv = +race.dataset.srv, split = +race.dataset.split, unit = race.dataset.unit;
    const so = $(".seg", ro), [s1, s2] = $$(".seg", rs), vo = $(".race-val b", ro), vs = $(".race-val b", rs);
    let id = 0;
    const set = (seg, p) => { seg.style.transform = "scaleX(" + p + ")"; };
    const run = () => {
      const my = ++id;
      race.classList.remove("done");
      [ro, rs].forEach((r) => r.classList.remove("fin"));
      if (still) {
        [so, s1, s2].forEach((g) => set(g, 1));
        vo.textContent = vo.dataset.f; vs.textContent = vs.dataset.f;
        ro.classList.add("fin"); rs.classList.add("fin"); race.classList.add("done");
        return;
      }
      [so, s1, s2].forEach((g) => set(g, 0));
      const t0 = performance.now();
      const frame = (now) => {
        if (my !== id) return;
        const el = (now - t0) / 1000;
        const po = Math.min(1, el / ours);
        set(so, po);
        vo.textContent = po < 1 ? el.toFixed(3) + unit : vo.dataset.f;
        ro.classList.toggle("fin", po >= 1);
        const p1 = Math.min(1, el / split), p2 = Math.min(1, Math.max(0, (el - split) / (srv - split)));
        set(s1, p1); set(s2, p2);
        vs.textContent = p2 < 1 ? Math.min(el, srv).toFixed(2) + unit : vs.dataset.f;
        if (p2 < 1) requestAnimationFrame(frame);
        else { rs.classList.add("fin"); race.classList.add("done"); }
      };
      requestAnimationFrame(frame);
    };
    let ran = false;
    watch(race, (v) => { if (v && !ran) { ran = true; setTimeout(run, 450); } }, 0.5);
    const again = $(".rerun", race);
    if (again) again.addEventListener("click", run);
  }
})();
