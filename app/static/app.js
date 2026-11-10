(() => {
  // ---------- set up once per browser tab ----------
  const applyTheme = t => {
    const h = document.documentElement; h.dataset.theme = t;
    h.dataset.mode = t === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : t;
    document.cookie = "theme=" + t + "; path=/; max-age=31536000; samesite=lax";
    document.querySelectorAll("input[name=theme]").forEach(r => r.checked = r.value === t);
  };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (document.documentElement.dataset.theme === "system") applyTheme("system"); });
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // clicks are handled on the whole document, so they keep working after a page is swapped in
  document.addEventListener("click", e => {
    if (e.target.closest("#themetoggle,.themebtn")) applyTheme(document.documentElement.dataset.mode === "dark" ? "light" : "dark");
    const menu = document.querySelector("details.nme");   // name menu: close when clicking elsewhere
    if (menu && menu.open && !menu.contains(e.target)) menu.open = false;
    const nn = e.target.closest("#namenote button");      // one-time notice that full names are shown
    if (nn) { document.cookie = "namenote=1; path=/; max-age=31536000; samesite=lax"; nn.closest("#namenote").remove(); }
    const d = e.target.closest("input[type=date]");       // clicking anywhere in a date field opens the calendar
    if (d) { try { d.showPicker(); } catch (err) {} }
  });
  document.addEventListener("change", e => { if (e.target.matches("input[name=theme]")) applyTheme(e.target.value); });
  document.addEventListener("keydown", e => {
    const menu = document.querySelector("details.nme");
    if (e.key === "Escape" && menu && menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
  });
  // iOS-style scrollbars: show the thin bar only while something is scrolling
  const sbTimers = new WeakMap();
  document.addEventListener("scroll", e => {
    const el = e.target === document ? document.documentElement : e.target;
    if (!el.classList) return;
    el.classList.add("sb-on"); clearTimeout(sbTimers.get(el));
    sbTimers.set(el, setTimeout(() => el.classList.remove("sb-on"), 800));
  }, { capture: true, passive: true });

  // ---------- pages load in place (htmx boost): no white flash; same-page actions keep the scroll position ----------
  let before = null;
  document.addEventListener("htmx:beforeRequest", e => {
    if (!e.detail.boosted) return;
    before = { path: location.pathname, y: scrollY, post: (e.detail.requestConfig.verb || "get") !== "get" };
    document.documentElement.classList.add("loading");
  });
  document.addEventListener("htmx:afterRequest", () => document.documentElement.classList.remove("loading"));
  document.addEventListener("htmx:beforeSwap", e => {   // show our friendly error pages (404, 429...) instead of doing nothing
    if (e.detail.xhr.status >= 400) { e.detail.shouldSwap = true; e.detail.isError = false; }
  });
  document.addEventListener("htmx:afterSettle", () => {
    if (before && before.post && location.pathname === before.path) scrollTo(0, before.y);
    before = null;
  });
  // if the network fails, fall back to a normal page load
  document.addEventListener("htmx:sendError", () => { document.documentElement.classList.remove("loading"); location.reload(); });

  // ---------- set up each page: first load and every page swapped in ----------
  function setup(root) {
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: .12 });
    root.querySelectorAll(".card,.seatcard,.steps li,.chip,.reveal,.hero").forEach((el, i) => {
      if (el.classList.contains("rv")) return;
      el.classList.add("rv"); el.style.setProperty("--d", Math.min(i % 8, 7) * 60 + "ms"); io.observe(el);
    });
    if (calm) return;
    if (matchMedia("(hover: hover)").matches) root.querySelectorAll(".card.link,.card.comp,.seatcard").forEach(el => {
      if (el.classList.contains("tilt")) return;
      el.classList.add("tilt");
      el.addEventListener("pointermove", e => {
        const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
        el.style.setProperty("--ry", ((x - .5) * 6).toFixed(2) + "deg"); el.style.setProperty("--rx", ((.5 - y) * 6).toFixed(2) + "deg");
        el.style.setProperty("--mx", x * 100 + "%"); el.style.setProperty("--my", y * 100 + "%");
      });
      el.addEventListener("pointerleave", () => { el.style.setProperty("--rx", "0deg"); el.style.setProperty("--ry", "0deg"); });
    });
    root.querySelectorAll("[data-count]:not([data-counted])").forEach(el => {
      el.dataset.counted = "1"; const n = +el.dataset.count, t0 = performance.now();
      (function tick(t) { const p = Math.min((t - t0) / 900, 1); el.textContent = Math.round(n * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); })(t0);
    });
  }
  setup(document);
  document.addEventListener("htmx:load", e => setup(e.detail.elt.querySelectorAll ? e.detail.elt : document));
})();
// research files: say right away when a file is too big, before a 25 MB upload is wasted
document.addEventListener("change", e => {
  const f = e.target; if (!f.matches || !f.matches("input[type=file][data-max]")) return;
  const out = f.form && f.form.querySelector(".fsize"), file = f.files && f.files[0]; if (!out) return;
  const big = file && file.size > +f.dataset.max;
  out.hidden = !file; out.classList.toggle("bad", !!big);
  if (file) out.textContent = big ? (f.dataset.toobig || "This file is over 25 MB. Choose a smaller one.") : file.name + " · " + (file.size / 1048576).toFixed(1) + " MB";
  f.setCustomValidity(big ? (f.dataset.toobig || "This file is over 25 MB.") : "");
});
