(() => {
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  // clicking anywhere in a date field opens the calendar, not just the small icon
  document.querySelectorAll("input[type=date]").forEach(el => el.addEventListener("click", () => { try { el.showPicker(); } catch (e) {} }));
  // iOS-style scrollbars: show the thin bar only while something is scrolling, then let CSS fade it out
  const sbTimers = new WeakMap();
  document.addEventListener("scroll", e => {
    const el = e.target === document ? document.documentElement : e.target;
    if (!el.classList) return;
    el.classList.add("sb-on"); clearTimeout(sbTimers.get(el));
    sbTimers.set(el, setTimeout(() => el.classList.remove("sb-on"), 800));
  }, { capture: true, passive: true });
  // scroll reveal with stagger
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: .12 });
  document.querySelectorAll(".card,.seatcard,.steps li,.chip,.reveal,.hero").forEach((el, i) => {
    el.classList.add("rv"); el.style.setProperty("--d", Math.min(i % 8, 7) * 60 + "ms"); io.observe(el);
  });
  if (calm) return;
  // 3D tilt + cursor spotlight (mouse devices only)
  if (matchMedia("(hover: hover)").matches) document.querySelectorAll(".card.link,.card.comp,.seatcard").forEach(el => {
    el.classList.add("tilt");
    el.addEventListener("pointermove", e => {
      const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      el.style.setProperty("--ry", ((x - .5) * 6).toFixed(2) + "deg"); el.style.setProperty("--rx", ((.5 - y) * 6).toFixed(2) + "deg");
      el.style.setProperty("--mx", x * 100 + "%"); el.style.setProperty("--my", y * 100 + "%");
    });
    el.addEventListener("pointerleave", () => { el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg"); });
  });
  // count-up numbers
  document.querySelectorAll("[data-count]").forEach(el => {
    const n = +el.dataset.count, t0 = performance.now();
    (function tick(t) { const p = Math.min((t - t0) / 900, 1); el.textContent = Math.round(n * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); })(t0);
  });
})();
