(() => {
  // light / dark theme: saved in a cookie so the server renders the right one on the next page
  const applyTheme = t => {
    const h = document.documentElement; h.dataset.theme = t;
    h.dataset.mode = t === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : t;
    document.cookie = "theme=" + t + "; path=/; max-age=31536000; samesite=lax";
    document.querySelectorAll("input[name=theme]").forEach(r => r.checked = r.value === t);
  };
  document.querySelectorAll("input[name=theme]").forEach(r => r.addEventListener("change", () => applyTheme(r.value)));
  document.querySelectorAll("#themetoggle,.themebtn").forEach(b => b.addEventListener("click", () => applyTheme(document.documentElement.dataset.mode === "dark" ? "light" : "dark")));
  // name menu in the top bar: close it when clicking elsewhere or pressing Escape
  const menu = document.querySelector("details.nme");
  if (menu) {
    document.addEventListener("click", e => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
    document.addEventListener("keydown", e => { if (e.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); } });
  }
  // one-time notice that full names are now shown
  const nn = document.getElementById("namenote");
  if (nn) nn.querySelector("button").addEventListener("click", () => { document.cookie = "namenote=1; path=/; max-age=31536000; samesite=lax"; nn.remove(); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (document.documentElement.dataset.theme === "system") applyTheme("system"); });
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
