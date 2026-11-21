// Ragdoll Mail site: the demo video and its sound, the right download first, a line under the bar, sections that rise in.
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

  // ---- the video's music: off until the visitor turns it on
  const snd = $(".shot .sound");
  if (demo && snd) snd.addEventListener("click", () => {
    const on = demo.muted;
    demo.muted = !on;
    if (on) { demo.volume = 0.6; demo.play().catch(() => {}); }
    snd.setAttribute("aria-pressed", String(on));
    snd.setAttribute("aria-label", on ? snd.dataset.off : snd.dataset.on);
  });
})();
