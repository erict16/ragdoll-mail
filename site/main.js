// Ragdoll Mail site: the right download first, the demo that stands up as you scroll, the agent tasks that play out,
// the search race, a search box and key caps that work, numbers that count up.
(() => {
  const $ = (s, n = document) => n.querySelector(s);
  const $$ = (s, n = document) => [...n.querySelectorAll(s)];
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(pointer: fine)").matches;
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

  // ---- a line under the bar, sections that rise in
  const bar = $(".top");
  const onScroll = () => bar && bar.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -10% 0px" });
  $$(".reveal").forEach((n) => io.observe(n));

  // ---- hero: the window lies back and stands up as you scroll; the light follows the pointer a little
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
  const hero = $(".hero");
  if (hero && fine && !still) hero.addEventListener("pointermove", (ev) => {
    const r = hero.getBoundingClientRect();
    hero.style.setProperty("--px", ((ev.clientX - r.left) / r.width * 2 - 1).toFixed(3));
    hero.style.setProperty("--py", ((ev.clientY - r.top) / r.height * 2 - 1).toFixed(3));
  });

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

  // ---- numbers that count up the first time they are seen
  $$(".num b[data-n]").forEach((b) => {
    const n = +b.dataset.n, pre = b.dataset.pre, suf = b.dataset.suf;
    if (!n || still) return;
    b.textContent = pre + 0 + suf;
    let done = false;
    watch(b, (vis) => {
      if (!vis || done) return;
      done = true;
      const t0 = performance.now();
      const step = (now) => {
        const p = Math.min(1, (now - t0) / 1100);
        b.textContent = pre + Math.round(n * (1 - (1 - p) ** 3)) + suf;
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    }, 0.6);
  });

  // ---- the agent tasks: the prompt and commands type, the result lands; they take turns until one is picked
  const ag = $(".agent-demo");
  if (ag) {
    const tabs = $$(".tabs button", ag), terms = $$(".term.scene", ag), cards = $$(".card.scene", ag), hand = $(".handoff", ag);
    let token = 0, auto = true, vis = false, started = false;
    const select = (k) => {
      tabs.forEach((b, i) => b.setAttribute("aria-selected", String(i === k)));
      [terms, cards].forEach((list) => list.forEach((n, i) => { n.classList.toggle("on", i === k); n.setAttribute("aria-hidden", String(i !== k)); }));
    };
    const play = async (k) => {
      const my = ++token;
      select(k);
      const lines = $$(".ln", terms[k]), card = cards[k];
      card.classList.remove("in");
      hand.classList.remove("in");
      if (still) { lines.forEach((l) => l.classList.add("in")); hand.classList.add("in"); card.classList.add("in"); return; }
      lines.forEach((l) => { l.classList.remove("in", "cur"); const t = $(".tx", l); if (t) t.textContent = ""; });
      await sleep(250);
      for (const l of lines) {
        if (my !== token) return;
        l.classList.add("in", "cur");
        const t = $(".tx", l);
        if (t) {
          const full = t.dataset.t, gap = full.length > 44 ? 9 : 17;
          for (let i = 1; i <= full.length; i++) { if (my !== token) return; t.textContent = full.slice(0, i); await sleep(gap); }
          await sleep(220);
        } else await sleep(l.classList.contains("say") ? 520 : 220);
        l.classList.remove("cur");
      }
      if (my !== token) return;
      hand.classList.add("in");
      await sleep(300);
      card.classList.add("in");
      await sleep(4600);
      while (!vis) { if (my !== token) return; await sleep(400); }
      if (auto && my === token) play((k + 1) % terms.length);
    };
    tabs.forEach((b, i) => b.addEventListener("click", () => { auto = false; play(i); }));
    ag.querySelector(".tabs").addEventListener("keydown", (ev) => {
      const k = tabs.indexOf(document.activeElement);
      if (k < 0 || !/^Arrow(Left|Right)$/.test(ev.key)) return;
      const n = (k + (ev.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[n].focus(); auto = false; play(n);
    });
    watch(ag, (v) => { vis = v; if (v && !started) { started = true; play(0); } }, 0.3);
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

  // ---- the search tile: a box that really filters, and types its own example until someone uses it
  const ms = $(".msearch");
  if (ms) {
    const inp = $("input", ms), items = $$("li[data-s]", ms), none = $(".none", ms);
    const esc = (t) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const hl = (t, q) => {
      const i = q ? t.toLowerCase().indexOf(q) : -1;
      return i < 0 ? esc(t) : esc(t.slice(0, i)) + "<mark>" + esc(t.slice(i, i + q.length)) + "</mark>" + esc(t.slice(i + q.length));
    };
    items.forEach((li) => { li._t = [...li.children].map((c) => c.textContent); });
    const filter = () => {
      const q = inp.value.trim().toLowerCase();
      let n = 0;
      items.forEach((li) => {
        const show = (!q || li.dataset.s.includes(q)) && n < 5;
        if (show) {
          n++;
          if (li.hidden) { li.hidden = false; li.classList.remove("pop"); void li.offsetWidth; li.classList.add("pop"); }
          [...li.children].forEach((c, i) => { c.innerHTML = hl(li._t[i], q); });
        } else li.hidden = true;
      });
      none.hidden = n > 0;
    };
    let touched = false;
    inp.addEventListener("input", () => { touched = true; filter(); });
    inp.addEventListener("focus", () => { touched = true; });
    filter();
    let typed = false;
    watch(ms, async (v) => {
      if (!v || typed || touched || still) return;
      typed = true;
      await sleep(600);
      for (const ch of inp.dataset.q) { if (touched) return; inp.value += ch; filter(); await sleep(150); }
    }, 0.6);
  }

  // ---- key caps that answer the real keys; they show themselves until someone presses one
  const keys = $(".keys");
  if (keys) {
    const caps = new Map($$(".key", keys).map((k) => [k.dataset.key, k]));
    const order = [...caps.keys()];
    let user = false, vis = false, i = 0;
    const press = (k) => {
      const c = caps.get(k);
      if (!c) return;
      c.classList.remove("down"); void c.offsetWidth; c.classList.add("down");
      clearTimeout(c._t); c._t = setTimeout(() => c.classList.remove("down"), 240);
    };
    document.addEventListener("keydown", (ev) => {
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      const tg = ev.target;
      if (/^(input|textarea|select)$/i.test(tg.tagName) || tg.isContentEditable) return;
      const k = ev.key.toLowerCase();
      if (caps.has(k)) { user = true; press(k); }
    });
    watch(keys, (v) => { vis = v; }, 0.6);
    if (!still) setInterval(() => { if (vis && !user) press(order[i++ % order.length]); }, 1300);
  }

  // ---- tiles light up where the pointer is
  if (fine && !still) document.addEventListener("pointermove", (ev) => {
    const t = ev.target.closest && ev.target.closest(".tile");
    if (!t) return;
    const r = t.getBoundingClientRect();
    t.style.setProperty("--mx", ev.clientX - r.left + "px");
    t.style.setProperty("--my", ev.clientY - r.top + "px");
  }, { passive: true });
})();
