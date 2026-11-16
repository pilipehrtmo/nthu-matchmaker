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

  // ---------- password fields: eye button to show or hide what was typed ----------
  const EYE_OPEN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_SHUT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 5.1A10.9 10.9 0 0 1 12 5c6.4 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.2M6.6 6.6A17.4 17.4 0 0 0 2 12s3.6 7 10 7a10 10 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>';
  const zh = () => document.documentElement.lang.startsWith("zh");
  const eyeLabel = shown => shown ? (zh() ? "隱藏密碼" : "Hide password") : (zh() ? "顯示密碼" : "Show password");
  function addEyes(root) {
    root.querySelectorAll("input[type=password]:not([data-eye])").forEach(inp => {
      inp.dataset.eye = "1";
      const wrap = document.createElement("span"); wrap.className = "pw-wrap";
      inp.parentNode.insertBefore(wrap, inp); wrap.appendChild(inp);
      const b = document.createElement("button");
      b.type = "button"; b.className = "pw-eye"; b.innerHTML = EYE_SHUT;
      b.setAttribute("aria-pressed", "false"); b.setAttribute("aria-label", eyeLabel(false)); b.title = eyeLabel(false);
      if (inp.id) b.setAttribute("aria-controls", inp.id);
      wrap.appendChild(b);
    });
  }
  document.addEventListener("click", e => {
    const b = e.target.closest(".pw-eye"); if (!b) return;
    const inp = b.parentNode.querySelector("input"); if (!inp) return;
    const show = inp.type === "password";
    const at = [inp.selectionStart, inp.selectionEnd];
    inp.type = show ? "text" : "password";
    b.innerHTML = show ? EYE_OPEN : EYE_SHUT;
    b.setAttribute("aria-pressed", String(show)); b.setAttribute("aria-label", eyeLabel(show)); b.title = eyeLabel(show);
    if (document.activeElement === inp) try { inp.setSelectionRange(at[0], at[1]); } catch (err) {}
  });
  // hide again before sending, so the browser's password manager still sees a password field
  document.addEventListener("submit", e => {
    e.target.querySelectorAll("input[data-eye]").forEach(inp => {
      inp.type = "password"; const b = inp.parentNode.querySelector(".pw-eye");
      if (b) { b.innerHTML = EYE_SHUT; b.setAttribute("aria-pressed", "false"); b.setAttribute("aria-label", eyeLabel(false)); b.title = eyeLabel(false); }
    });
  }, true);

  // ---------- admin page: sections that open and close (remembered on this device) ----------
  const foldKey = id => "mm-fold-" + id;
  function setFold(btn, open, instant) {
    const body = document.getElementById(btn.getAttribute("aria-controls")); if (!body) return;
    if (instant) { body.classList.add("noanim"); requestAnimationFrame(() => requestAnimationFrame(() => body.classList.remove("noanim"))); }
    btn.setAttribute("aria-expanded", String(open)); body.classList.toggle("open", open);
    if (open) body.removeAttribute("inert"); else body.setAttribute("inert", "");
  }
  document.addEventListener("click", e => {
    const jump = e.target.closest('a[href^="#"]');   // a shortcut to a closed section opens it
    if (jump) { const fb = document.querySelector(`.foldbtn[data-fold="${jump.getAttribute("href").slice(1)}"]`); if (fb && fb.getAttribute("aria-expanded") !== "true") setFold(fb, true); }
    const b = e.target.closest(".foldbtn"); if (!b) return;
    const open = b.getAttribute("aria-expanded") !== "true"; setFold(b, open);
    try { localStorage.setItem(foldKey(b.dataset.fold), open ? "1" : "0"); } catch (err) {}
  });
  const restoreFolds = root => root.querySelectorAll(".foldbtn").forEach(b => {
    let v = null; try { v = localStorage.getItem(foldKey(b.dataset.fold)); } catch (err) {}
    if (v === "1" || b.dataset.force) setFold(b, true, true);
  });

  // ---------- Save buttons on lists (competitions, funding): no page reload ----------
  // Runs in the capture phase so the site's page-loading (htmx boost) never sends the same form a second time.
  document.addEventListener("submit", async e => {
    const f = e.target.closest && e.target.closest("form.savef"); if (!f) return;
    e.preventDefault(); e.stopPropagation();
    const b = f.querySelector("button"); if (!b || b.dataset.busy) return;
    const was = b.getAttribute("aria-pressed") === "true";
    b.dataset.busy = "1"; b.setAttribute("aria-pressed", String(!was)); b.classList.remove("pop"); void b.offsetWidth; if (!was) b.classList.add("pop");   // show it at once
    try {
      const r = await fetch(f.action, { method: "POST", body: new FormData(f), headers: { "x-fetch": "1" } });
      if (r.status === 401) { location.href = "/login"; return; }
      if (!r.ok) throw 0;
      const j = await r.json(), on = !!j.saved;
      b.setAttribute("aria-pressed", String(on)); b.title = on ? b.dataset.on || "Saved" : b.dataset.off || "Save";
      const card = f.closest("[data-saved]"); if (card) card.dataset.saved = on ? "1" : "0";
      document.dispatchEvent(new CustomEvent("mm:saved", { detail: { form: f, saved: on } }));
    } catch (err) { b.setAttribute("aria-pressed", String(was)); b.classList.remove("pop"); }
    finally { delete b.dataset.busy; }
  }, true);

  // ---------- form helpers: live character counters, "Did you mean ...?" for skills and email ----------
  // The server enforces every limit; these only give quicker feedback. Suggestions are offered, never applied by themselves.
  const VD = () => { try { return JSON.parse(document.getElementById("vdata").textContent); } catch (e) { return null; } };
  const fmt = (s, o) => s.replace(/\{(\w+)\}/g, (_, k) => o[k]);
  const dist = (a, b) => {   // Damerau-Levenshtein, same as app/validate.py
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
    for (let j = 0; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
    }
    return d[a.length][b.length];
  };
  const skillFix = (v, D) => {
    const k = v.trim().toLowerCase(); if (!k) return "";
    const canon = D.canon.map(c => c.toLowerCase()); if (canon.includes(k)) return "";
    if (D.typos[k]) return D.typos[k];
    if (k.length < 4) return "";
    const allow = k.length < 6 ? 1 : 2; let best = "", bd = 99;
    canon.forEach((c, i) => { const x = dist(k, c); if (x < bd || (x === bd && c < best.toLowerCase())) { bd = x; best = D.canon[i]; } });
    return bd <= allow && Math.abs(best.length - k.length) <= allow ? best : "";
  };
  const emailFix = (v, D) => {
    const m = v.trim().match(/^([^@\s]+)@([^@\s]+)$/); if (!m) return "";
    const dom = m[2].toLowerCase(); let fix = D.domain_typos[dom] || "";
    if (!fix && (D.known_domains.includes(dom) || /^[a-z0-9-]+\.nthu\.edu\.tw$/.test(dom))) return "";
    if (!fix && !/\.(edu|ac|gov)(\.[a-z]{2})?$|\.edu\.tw$/.test(dom)) {
      let bd = 99; D.domains.forEach(c => { const x = dist(dom, c); if (x < bd || (x === bd && c < fix)) { bd = x; fix = c; } });
      if (!(bd > 0 && bd <= (dom.length < 8 ? 1 : 2))) fix = "";
    }
    return fix ? m[1] + "@" + fix : "";
  };
  const splitSkills = v => { const seen = new Set(); return v.split(/[,，、;；\n]/).map(t => t.replace(/\s+/g, " ").trim()).filter(t => t && !seen.has(t.toLowerCase()) && seen.add(t.toLowerCase())); };
  const helpBox = (el, cls) => {   // one message area right after a field
    let b = el.nextElementSibling; if (b && b.classList.contains(cls)) return b;
    b = document.createElement("p"); b.className = cls + " muted fine"; b.setAttribute("aria-live", "polite"); el.after(b); return b;
  };
  function counter(el) {
    const D = VD(); if (!D) return;
    const max = +el.getAttribute("maxlength") || 0, min = +el.getAttribute("minlength") || 0, n = el.value.replace(/\r\n/g, "\n").trim().length;
    const b = helpBox(el, "ccount");
    b.textContent = fmt(D.t.count, { n, max }) + (min && n < min ? " · " + fmt(D.t.need, { min }) : "");
    b.classList.toggle("bad", (min && n > 0 && n < min) || (max && n > max)); b.classList.toggle("near", !!max && n >= max * 0.9 && n <= max);
  }
  function skillHelp(el) {
    const D = VD(); if (!D) return;
    const items = splitSkills(el.value), b = helpBox(el, "skillhelp"); b.replaceChildren();
    const long = items.find(t => t.length > D.max_skill_len);
    if (long) { b.append(fmt(D.t.too_long, { x: long.slice(0, 40), max: D.max_skill_len })); b.classList.add("bad"); return; }
    if (items.length > D.max_skills) { b.append(fmt(D.t.too_many, { max: D.max_skills, extra: items.length - D.max_skills })); b.classList.add("bad"); return; }
    b.classList.remove("bad");
    items.map(t => [t, skillFix(t, D)]).filter(([t, f]) => f && f.toLowerCase() !== t.toLowerCase()).slice(0, 3).forEach(([t, f]) => {
      const s = document.createElement("span"); s.className = "sugg"; s.append(fmt(D.t.mean, { x: f }) + " ");
      const u = document.createElement("button"); u.type = "button"; u.className = "linkbtn sm"; u.textContent = fmt(D.t.use, { x: f });
      u.onclick = () => { el.value = splitSkills(el.value).map(x => x.toLowerCase() === t.toLowerCase() ? f : x).join(", "); el.dispatchEvent(new Event("input", { bubbles: true })); el.focus(); };
      s.append(u); b.append(s);
    });
  }
  function emailHelp(el) {
    const D = VD(); if (!D) return;
    const b = helpBox(el, "emailhelp"), fix = el.value && el.dataset.kept !== el.value ? emailFix(el.value, D) : "";
    b.replaceChildren(); b.hidden = !fix; if (!fix) return;
    b.append(fmt(D.t.mean, { x: fix }) + " ");
    const use = document.createElement("button"); use.type = "button"; use.className = "linkbtn sm"; use.textContent = D.t.use_email;
    use.onclick = () => { el.value = fix; b.hidden = true; el.focus(); };
    const keep = document.createElement("button"); keep.type = "button"; keep.className = "linkbtn sm"; keep.textContent = D.t.keep;
    keep.onclick = () => { el.dataset.kept = el.value; b.hidden = true; };
    b.append(use, " · ", keep);
  }
  document.addEventListener("input", e => {
    const el = e.target; if (!el.matches) return;
    if (el.matches("[data-counter]")) counter(el);
    if (el.matches("[data-skills]")) { clearTimeout(el._sk); el._sk = setTimeout(() => skillHelp(el), 250); }
    if (el.matches("input[data-suggest-email]")) { const b = el.nextElementSibling; if (b && b.classList.contains("emailhelp")) b.hidden = true; }
  });
  document.addEventListener("focusout", e => {
    const el = e.target; if (!el.matches) return;
    if (el.matches("input[data-suggest-email]")) emailHelp(el);
    if (el.matches("[data-skills]")) skillHelp(el);
  });

  // ---------- set up each page: first load and every page swapped in ----------
  function setup(root) {
    root.querySelectorAll("[data-counter]").forEach(counter);
    addEyes(root); restoreFolds(root);
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
  const box = f.closest(".filepick"), file0 = f.files && f.files[0];
  if (box) { box.classList.toggle("has", !!file0); const n = box.querySelector(".fp-n"); if (n) { n.dataset.empty = n.dataset.empty || n.textContent; n.textContent = file0 ? file0.name + " · " + (file0.size / 1048576).toFixed(1) + " MB" : n.dataset.empty; } }
  const out = f.form && f.form.querySelector(".fsize"), file = f.files && f.files[0]; if (!out) return;
  const big = file && file.size > +f.dataset.max;
  out.hidden = !file || (box && !big); out.classList.toggle("bad", !!big); if (box) box.classList.toggle("bad", !!big);
  if (file) out.textContent = big ? (f.dataset.toobig || "This file is over 25 MB. Choose a smaller one.") : file.name + " · " + (file.size / 1048576).toFixed(1) + " MB";
  f.setCustomValidity(big ? (f.dataset.toobig || "This file is over 25 MB.") : "");
});

/* Department picker: show the IBP track or the "Other" box only for those choices. */
(function () {
  function sync(sel) {
    const box = sel.closest("[data-deptpick]"); if (!box) return;
    box.querySelectorAll(".dsub").forEach(d => {
      const on = d.dataset.for === sel.value; d.hidden = !on;
      const f = d.querySelector("select, input"); if (f) f.required = on;
    });
  }
  document.addEventListener("change", e => { if (e.target.matches && e.target.matches("[data-deptpick] select[name=dept_sel]")) sync(e.target); });
  const all = () => document.querySelectorAll("[data-deptpick] select[name=dept_sel]").forEach(sync);
  document.addEventListener("DOMContentLoaded", all); document.addEventListener("htmx:afterSettle", all); all();
})();
