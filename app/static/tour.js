/* Guided tours (student, professor, what's new). Data comes from app/tour.py.

   Each step runs in order: wait for its element -> scroll it into the safe area (below the top bar, above the panel
   or phone tab bar; no scroll if it's already visible) and wait until scrolling stops -> fade in the highlight and the
   panel -> move the guide cursor to it -> play the step's demonstration, if any.
   Everything is anchored to real elements and re-measured every frame, so resizing and late-loading content are fine.

   Safety: the tour never submits a form or sends anything. A demonstration may only click interface toggles
   (filter chips, Details/Apply disclosures, or elements marked data-tour-safe) and type sample text, which is removed
   when the step ends; a form with sample text in it can't be submitted. The person's own mouse is never touched.
   Progress is kept in localStorage, so it survives page changes and leaving the site. */
(() => {
  const KEY = "mm-tour", MAX_AGE = 14 * 864e5, POS = "mm-tour-cur";
  const read = () => { try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); return v && Date.now() - (v.ts || 0) < MAX_AGE ? v : null; } catch (_) { return null; } };
  const write = v => { try { v ? localStorage.setItem(KEY, JSON.stringify({ ...v, ts: Date.now() })) : localStorage.removeItem(KEY); } catch (_) {} };
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const phone = () => innerWidth < 640;
  const touch = () => phone() || matchMedia("(pointer: coarse)").matches;
  const T = { move: [420, 880], settle: 1200, fade: 220, press: 170, pause: 650, type: 26 };   // one set of timings for everything
  let D = null, layer = null, raf = 0, cleanup = [], gen = 0, spot = null, cur = null, focusEl = null, mainEl = null, moving = false, paused = false, track = null;

  const data = () => { const el = document.getElementById("tourdata"); try { return el ? JSON.parse(el.textContent) : null; } catch (_) { return null; } };
  const steps = st => (D && D.tours[st.t]) || [];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  async function hold(g) { while (paused && g === gen) await sleep(120); }        // a paused demonstration waits here
  const wait = async (ms, g) => { await sleep(ms); await hold(g); };
  function fits(s, st) {
    if (!new RegExp(s.path).test(location.pathname)) return false;
    const skipped = st.via === s.key;   // reached by "Skip this step": the result of the skipped action isn't required
    if (s.q && !skipped && !location.search.includes(s.q)) return false;
    if (s.unless && !skipped && location.search.includes(s.unless)) return false;
    if (s.via && st.via !== s.key) return false;          // reached only by skipping to it
    if (s.locked && D.verified) return false;
    if (s.need) { try { if (!document.querySelector(s.need)) return false; } catch (_) { return false; } }
    return true;
  }
  function pick(st) {   // this page's step: the saved one, else the next one that fits, else an earlier one (never below the floor)
    const S = steps(st);
    for (let j = st.i; j < S.length; j++) if (fits(S[j], st)) return j;
    for (let j = st.i - 1; j >= (st.floor || 0); j--) if (fits(S[j], st) && !S[j].via) return j;
    return -1;
  }
  const visible = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden";
  function find(sel) {   // "a|b": the first selector with a visible match wins
    if (!sel) return null;
    for (const one of sel.split("|")) { try { const t = [...document.querySelectorAll(one)].find(visible); if (t) return t; } catch (_) {} }
    return null;
  }
  function waitFor(fn, ms, g) {   // for elements that appear after navigation, a click or a slow load: re-checked only when the page changes
    const v = fn(); if (v || g !== gen) return Promise.resolve(v);
    return new Promise(res => {
      let done = false, queued = false;
      const fin = x => { if (done) return; done = true; mo.disconnect(); clearTimeout(to); res(x); };
      const mo = new MutationObserver(() => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; if (g !== gen) return fin(null); const x = fn(); if (x) fin(x); }); });
      mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "open", "hidden", "style"] });
      const to = setTimeout(() => fin(g === gen ? fn() : null), ms);
    });
  }
  function goPage(S, i) { for (let j = i; j >= 0; j--) if (S[j] && S[j].go) return S[j].go; return "/"; }

  // ---------- safe area and scrolling ----------
  function area(sheetH) {
    const bar = document.querySelector(".top"), top = (bar ? Math.max(0, bar.getBoundingClientRect().bottom) : 0) + 14;
    const tab = document.querySelector(".tabbar"), tabH = tab && visible(tab) ? tab.getBoundingClientRect().height : 0;
    const bottom = phone() ? innerHeight - tabH - sheetH - 22 : innerHeight - 18;
    return { top, bottom: Math.max(top + 60, bottom) };
  }
  async function reveal(el, g, sheetH = 0) {
    if (!el) return;
    const r = el.getBoundingClientRect(), a = area(sheetH);
    if (r.top >= a.top && r.bottom <= a.bottom) return;            // already comfortably visible: don't move the page
    const room = a.bottom - a.top;
    const y = r.height > room ? scrollY + r.top - a.top : scrollY + r.top - a.top - (room - r.height) * (phone() ? 0.45 : 0.3);
    scrollTo({ top: Math.max(0, y), behavior: reduced() ? "auto" : "smooth" });
    let last = -1, still = 0; const t0 = performance.now();          // wait until scrolling has really stopped
    while (still < 4 && performance.now() - t0 < T.settle && g === gen) { await new Promise(r => requestAnimationFrame(r)); if (scrollY === last) still++; else { still = 0; last = scrollY; } }
  }

  // ---------- guide cursor ----------
  function cursor() {
    if (cur && document.body.contains(cur)) return cur;
    cur = document.createElement("div"); cur.className = "t-cur"; cur.setAttribute("aria-hidden", "true");
    cur.innerHTML = `<svg class="t-arrow" viewBox="0 0 24 24"><path d="M5 3.2 19 12l-6.3 1.6L9.4 20z"/></svg><span class="t-finger"></span><span class="t-cap"></span>`;
    document.body.appendChild(cur);
    let p = null; try { p = JSON.parse(sessionStorage.getItem(POS) || "null"); } catch (_) {}
    cur._x = p ? p.x : innerWidth * 0.5; cur._y = p ? p.y : innerHeight * 0.9; place(cur);
    return cur;
  }
  function place(c) { c.style.transform = `translate3d(${c._x}px, ${c._y}px, 0)`; try { sessionStorage.setItem(POS, JSON.stringify({ x: c._x, y: c._y })); } catch (_) {} }
  function aim(el) {   // the pointer's tip rests on the element's lower edge, so the arrow (or fingertip) sits below it and never hides its text
    const r = el.getBoundingClientRect(), a = area(sheetH()), small = r.width < 220;
    const x = small ? r.left + r.width * 0.72 : r.left + Math.min(46, r.width * 0.18);
    let y = r.bottom - 2;
    if (y > a.bottom - 8) y = Math.max(r.top + 10, Math.min(a.bottom - 8, r.top + 40));   // tall blocks: rest near the top instead
    return { x: Math.min(innerWidth - 30, Math.max(8, x)), y: Math.min(innerHeight - 30, Math.max(8, y)) };
  }
  async function moveTo(el, g) {
    const c = cursor(); c.classList.toggle("touch", touch()); c.classList.add("on"); focusEl = el;
    if (reduced()) { const p = aim(el); c._x = p.x; c._y = p.y; place(c); return; }
    const sx = c._x, sy = c._y, p0 = aim(el), dx = p0.x - sx, dy = p0.y - sy, dist = Math.hypot(dx, dy);
    if (dist < 2) { flipCap(c); return; }
    // like a hand: a slight arc (not a ruler-straight line), fast start and a gentle landing (minimum-jerk profile),
    // and a duration that grows with distance the way real pointing does (Fitts), within T.move
    const dur = Math.min(T.move[1], Math.max(T.move[0], 260 + 150 * Math.log2(1 + dist / 36)));
    const bow = Math.min(60, dist * 0.12) * (dx >= 0 ? 1 : -1), nx = -dy / dist, ny = dx / dist;
    let t0 = performance.now(); moving = true;
    while (g === gen) {   // re-aimed every frame so it lands on the element even if the page moves
      if (paused) { const w0 = performance.now(); await hold(g); t0 += performance.now() - w0; continue; }
      const k = Math.min(1, (performance.now() - t0) / dur), e = k * k * k * (10 - 15 * k + 6 * k * k), p = aim(el), arc = 4 * e * (1 - e) * bow;
      c._x = sx + (p.x - sx) * e + nx * arc; c._y = sy + (p.y - sy) * e + ny * arc; place(c);
      if (k >= 1) break; await new Promise(r => requestAnimationFrame(r));
    }
    moving = false; flipCap(c);
  }
  function flipCap(c) { c.classList.toggle("flip", c._x > innerWidth - 220); }   // keep the caption on screen
  const hideCursor = () => { if (cur) { cur.classList.remove("on"); caption(""); } };
  function caption(text) { if (!cur) return; const cap = cur.querySelector(".t-cap"); cap.textContent = text || ""; cap.classList.toggle("on", !!text); placeCap(); }
  function placeCap() {   // the label sits beside what's being shown (in the free space to its right), not on top of the next line of text
    const cap = cur && cur.querySelector(".t-cap"); if (!cap) return;
    if (!focusEl || !cap.textContent || moving) { cap.style.left = cap.style.top = ""; return; }
    const r = focusEl.getBoundingClientRect(), w = cap.offsetWidth, h = cap.offsetHeight;
    if (r.width < 260 && r.right + 12 + w < innerWidth - 8) { cap.style.left = (r.right + 12 - cur._x) + "px"; cap.style.top = (r.top + r.height / 2 - h / 2 - cur._y) + "px"; }
    else { cap.style.left = cap.style.top = ""; }
  }
  async function press(g) {
    const c = cursor(); c.classList.add("press");
    const rip = document.createElement("span"); rip.className = "t-ripple"; rip.style.transform = `translate3d(${c._x}px, ${c._y}px, 0)`; document.body.appendChild(rip);
    await sleep(T.press); c.classList.remove("press"); setTimeout(() => rip.remove(), 600);
  }
  const SAFE = "details:not(:has(form)) > summary, #kinds .chip, [data-tour-safe]";   // the only things a demonstration may click (never a disclosure that holds a form)

  // ---------- sample text and previews (never sent) ----------
  async function typeInto(el, text, g) {
    if (!/^(INPUT|TEXTAREA)$/.test(el.tagName)) {   // the example form's note box: just text on screen
      el.textContent = ""; for (const ch of text) { if (g !== gen) return; el.textContent += ch; await wait(reduced() ? 0 : T.type, g); } return;
    }
    if (!("tourOrig" in el.dataset)) el.dataset.tourOrig = el.value;
    el.value = "";
    for (const ch of text) { if (g !== gen) return; el.value += ch; el.dispatchEvent(new Event("input", { bubbles: true })); await wait(reduced() ? 0 : T.type, g); }
  }
  function restore(el) {
    const list = el ? [el] : [...document.querySelectorAll("[data-tour-orig]")];
    list.forEach(x => { if (!("tourOrig" in x.dataset)) return; x.value = x.dataset.tourOrig; delete x.dataset.tourOrig; x.dispatchEvent(new Event("input", { bubbles: true })); });
  }
  document.addEventListener("submit", e => {   // sample text in a form: never let it be sent
    if (e.target.querySelector && e.target.querySelector("[data-tour-orig]")) { e.preventDefault(); e.stopImmediatePropagation(); restore(); }
  }, true);
  document.addEventListener("keydown", e => {     // a key in a field holding sample text: the sample goes away first, so Enter can't send it
    const t = e.target; if (t && t.dataset && "tourOrig" in t.dataset) { restore(t); if (e.key === "Enter") e.preventDefault(); }
  }, true);

  // ---------- the example application form: a picture of the form, not a form ----------
  // No <form>, no inputs, no buttons: it can't be submitted by a click, Enter or any script that looks for forms.
  function mock(el, L) {
    document.querySelectorAll(".t-mock").forEach(m => m.remove());
    const real = el.closest("details") || el, form = real.querySelector("form");
    const m = document.createElement("div"); m.className = "t-mock"; m.setAttribute("role", "img"); m.setAttribute("aria-label", L.mock);
    m.innerHTML = `<span class="t-mock-tag"></span><span class="t-mock-l"></span><div class="t-mock-ta"></div><span class="t-mock-btn"></span>`;
    m.querySelector(".t-mock-tag").textContent = L.mock;
    m.querySelector(".t-mock-l").textContent = (form && form.querySelector("label")?.firstChild?.textContent || L.mock_l).trim();
    m.querySelector(".t-mock-btn").textContent = (form && form.querySelector("button")?.textContent || L.mock_b).trim();
    real.insertAdjacentElement("afterend", m); cleanup.push(() => m.remove());
    return m;
  }
  function preview(el, L) {
    const r = el.getBoundingClientRect(), pv = document.createElement("div"); pv.className = "t-preview";
    pv.innerHTML = `<span class="t-pv-tag"></span><b></b><p></p>`;
    pv.querySelector(".t-pv-tag").textContent = L.pv_tag; pv.querySelector("b").textContent = L.pv_t; pv.querySelector("p").textContent = L.pv_b;
    (layer || document.body).appendChild(pv);
    const w = Math.min(300, innerWidth - 24); pv.style.width = w + "px";
    const h = pv.offsetHeight, a = area(sheetH()), tip = layer && layer.querySelector(".t-tip"), tr = tip ? tip.getBoundingClientRect() : null;
    const hit = (x, y, b) => b ? Math.max(0, Math.min(x + w, b.right + 8) - Math.max(x, b.left - 8)) * Math.max(0, Math.min(y + h, b.bottom + 8) - Math.max(y, b.top - 8)) : 0;
    let best = null;   // next to the button, never on top of the tutorial panel or the button itself
    const spots = [[r.right + 14, r.top + r.height / 2 - h / 2], ...(tr ? [[Math.max(r.right, tr.right) + 16, Math.min(r.bottom, tr.bottom) - h]] : []), [r.left, r.top - h - 14], [r.left, r.bottom + 14], [r.left - w - 14, r.top + r.height / 2 - h / 2]];
    if (phone()) spots.unshift([r.left, r.bottom + 30]);   // phones: below the button, where the page is free
    for (const [x0, y0] of spots) {
      const x = Math.min(innerWidth - w - 12, Math.max(12, x0)), y = Math.min(a.bottom - h - 8, Math.max(a.top + 8, y0));
      const v = hit(x, y, tr) * 2 + hit(x, y, r); if (!best || v < best[0]) best = [v, x, y]; if (v === 0) break;
    }
    Object.assign(pv.style, { left: best[1] + "px", top: best[2] + "px" });
    return pv;
  }

  async function demo(s, g, L) {
    for (const a of s.demo || []) {
      if (g !== gen) return;
      if (a.when && !document.querySelector(a.when)) continue;
      await hold(g); if (g !== gen) return;
      if (a.do === "clear") { const el = find(a.sel); if (el) restore(el); continue; }
      if (a.do === "mock") { const base = find(a.sel); if (!base) continue; mock(base, L); await wait(120, g); continue; }
      const el = await waitFor(() => find(a.sel), 1500, g); if (!el || g !== gen) continue;   // a part this project doesn't have: skip it
      await reveal(el, g, sheetH()); if (g !== gen) return;
      await moveTo(el, g); if (g !== gen) return;
      caption(a.do === "preview" ? "" : a.text);   // the preview card carries its own "Preview — not sent" label
      if (a.do === "click" && el.matches(SAFE)) { await press(g); if (g !== gen) return; el.click(); await wait(260, g); }
      else if (a.do === "press") await press(g);   // shows the click, doesn't click
      else if (a.do === "type" && (/^(INPUT|TEXTAREA)$/.test(el.tagName) || el.matches(".t-mock-ta"))) { await press(g); await typeInto(el, a.value || "", g); }
      else if (a.do === "preview") { const pv = preview(el, L); await wait(T.pause * 3.4, g); if (g !== gen) return; pv.classList.add("out"); setTimeout(() => pv.remove(), 300); }
      await wait(T.pause, g); kick();
    }
    caption("");
    if (g === gen && mainEl) { focusEl = mainEl; await reveal(mainEl, g, sheetH()); if (g !== gen) return; await moveTo(mainEl, g); kick(); }   // back to the step's own element
  }

  // ---------- panel placement ----------
  const sheetH = () => { const t = layer && layer.querySelector(".t-tip"); return phone() && t ? t.offsetHeight : 0; };
  function placeTip(t, tip, main) {
    if (phone()) { tip.classList.add("t-sheet"); tip.classList.remove("t-center"); return; }   // phone: always a bottom sheet; the page scrolls above it
    if (!t) { tip.classList.add("t-center"); return; }
    tip.classList.remove("t-center");
    let r = t.getBoundingClientRect(); const mk = document.querySelector(".t-mock");
    const grow = m => { r = { left: Math.min(r.left, m.left), top: Math.min(r.top, m.top), right: Math.max(r.right, m.right), bottom: Math.max(r.bottom, m.bottom) }; r.width = r.right - r.left; r.height = r.bottom - r.top; };
    if (main && main !== t && document.body.contains(main)) {   // keep the whole thing being explained in view, not only the part the cursor is on
      const m = main.getBoundingClientRect(); if (Math.max(r.bottom, m.bottom) - Math.min(r.top, m.top) < innerHeight * 0.6) grow(m);
    }
    if (mk) grow(mk.getBoundingClientRect());   // and the example form
    const tw = tip.offsetWidth, th = tip.offsetHeight, m = 12, W = innerWidth, H = innerHeight, top0 = area(0).top - 6;
    const cx = Math.min(Math.max(m, r.left + r.width / 2 - tw / 2), W - tw - m), cy = Math.min(Math.max(top0, r.top), H - th - m);
    const spots = [[cx, r.bottom + 16], [cx, r.top - th - 16], [r.right + 16, cy], [r.left - tw - 16, cy]];
    const cover = ([x, y]) => { const X = Math.min(Math.max(m, x), W - tw - m), Y = Math.min(Math.max(top0, y), H - th - m);
      return [Math.max(0, Math.min(X + tw, r.right + 8) - Math.max(X, r.left - 8)) * Math.max(0, Math.min(Y + th, r.bottom + 8) - Math.max(Y, r.top - 8)), X, Y]; };
    let best = null; for (const c of spots) { const v = cover(c); if (!best || v[0] < best[0]) best = v; if (v[0] === 0) break; }
    tip.style.left = best[1] + "px"; tip.style.top = best[2] + "px";
  }
  function spotOn(el) {
    if (!spot || !document.body.contains(spot)) { spot = document.createElement("div"); spot.className = "t-spot"; spot.setAttribute("aria-hidden", "true"); document.body.appendChild(spot); }
    spot.classList.add("on");
    if (!el) { spot.classList.add("none"); return; }
    spot.classList.remove("none");
    const r = el.getBoundingClientRect(), pad = 6;
    spot.style.left = r.left - pad + "px"; spot.style.top = r.top - pad + "px"; spot.style.width = r.width + pad * 2 + "px"; spot.style.height = r.height + pad * 2 + "px";
  }

  let follow = null, until = 0;
  function tick() { raf = 0; if (follow) follow(); if (follow && (moving || performance.now() < until)) raf = requestAnimationFrame(tick); }
  function kick(ms = 450) { until = Math.max(until, performance.now() + ms); if (!raf) raf = requestAnimationFrame(tick); }

  function clear(all) {
    gen++; cancelAnimationFrame(raf); raf = 0; follow = null; paused = false; if (track) track(); track = null; cleanup.forEach(f => f()); cleanup = []; restore();
    document.querySelectorAll(".t-mock").forEach(m => m.remove());
    if (layer) { const old = layer; old.classList.remove("in"); setTimeout(() => old.remove(), T.fade); } layer = null;
    document.querySelectorAll(".t-preview").forEach(p => p.remove());
    if (all) { if (spot) spot.classList.remove("on"); hideCursor(); }
    focusEl = mainEl = null;
  }
  const end = () => { write(null); clear(true); };

  async function show() {
    clear(false); const g = gen;
    D = D || data(); let st = read(); if (!D || !st || !D.tours[st.t]) return clear(true);
    if (st.uid && D.uid && st.uid !== D.uid) return end();   // another person logged in on this browser
    if (!st.uid && D.uid) write({ ...st, uid: D.uid });
    const S = steps(st), L = D.labels;
    let i = pick(st);
    if (i < 0) i = await waitFor(() => { const k = pick(read() || st); return k >= 0 ? k : null; }, 1500, g) ?? -1;   // content that loads late
    if (g !== gen) return;
    if (i < 0) { if (spot) spot.classList.remove("on"); hideCursor(); return resume(st, S, L); }
    if (i !== st.i) { st = { ...read(), i, via: st.via === S[i].key ? st.via : null }; write(st); }
    const s = S[i], main = S.filter(x => !x.alt), num = Math.max(1, S.slice(0, i + 1).filter(x => !x.alt).length), last = s.act === "done";
    const t = s.sel ? await waitFor(() => find(s.sel), 2500, g) : null;
    if (g !== gen) return;
    mainEl = focusEl = t;

    layer = document.createElement("div"); layer.className = "tour"; layer.dataset.key = s.key;
    layer.innerHTML = `<div class="t-tip" role="dialog" aria-modal="false" aria-labelledby="t-h" aria-describedby="t-d">
      <div class="t-bar"><span class="t-step"></span><span class="t-bar-r"><button type="button" class="t-again linkbtn sm" hidden></button><button type="button" class="t-x linkbtn sm"></button></span></div>
      <div class="t-prog" aria-hidden="true"><i></i></div><p class="t-sim" hidden></p><h2 id="t-h"></h2><p class="t-text" id="t-d"></p>
      <p class="t-warn" role="note" hidden><b></b> <span></span></p><p class="t-hint muted fine"></p>
      <div class="t-acts"><button type="button" class="t-skip linkbtn sm"></button><span class="t-gap"></span></div></div>`;
    document.body.appendChild(layer);
    const $ = q => layer.querySelector(q), tip = $(".t-tip"), acts = $(".t-acts"), hint = $(".t-hint");
    $(".t-step").textContent = s.alt ? "" : L.step.replace("{0}", Math.min(num, main.length)).replace("{1}", main.length);
    $(".t-prog i").style.width = Math.round(Math.min(num, main.length) / main.length * 100) + "%";
    $("#t-h").textContent = s.title; $(".t-text").textContent = s.text;
    if (s.simulated) { const b = $(".t-sim"); b.hidden = false; b.textContent = L.sim; }
    if (s.warn) { const w = $(".t-warn"); w.hidden = false; w.querySelector("b").textContent = L.warn; w.querySelector("span").textContent = s.warn; }
    const x = $(".t-x"); x.textContent = L.end; x.onclick = end;

    const jump = (j, via) => {   // the next step is on another page: go there, instead of leaving a Continue button behind
      const st2 = { ...read(), i: j, floor: j, via: via || null }; write(st2);
      const Tn = S[j]; let elsewhere = false;
      try { elsewhere = Tn && !fits(Tn, st2) && Tn.go && new URL(Tn.go, location.href).pathname !== location.pathname; } catch (_) {}
      if (elsewhere) { restore(); location.href = Tn.go; } else show();
    };
    const nextIdx = i + 1, next = () => jump(nextIdx);
    const skip = $(".t-skip");
    if (last) skip.remove();
    else { skip.textContent = L.skip; skip.onclick = () => { if (s.skip) jump(S.findIndex(z => z.key === s.skip), s.skip); else jump(nextIdx); }; }
    const btn = (label, cls, fn) => { const b = document.createElement("button"); b.type = "button"; b.className = cls; b.textContent = label; b.onclick = fn; acts.appendChild(b); return b; };
    if (i > 0 && !S[i - 1].via && fits(S[i - 1], { via: null }) && S[i - 1].act !== "submit" && !s.via) btn(L.back, "ghost sm", () => { const st2 = read(); write({ ...st2, i: i - 1, floor: Math.min(st2.floor || 0, i - 1) }); show(); });
    const again = $(".t-again");   // while the demonstration plays: Pause / Resume; afterwards: Show again
    const setPause = v => { paused = v; if (layer) layer.dataset.paused = v ? "1" : ""; label(); };
    const label = () => { if (!layer) return; const running = layer.dataset.demo === "running"; again.textContent = running ? (paused ? "▶ " + L.resume_demo : "❚❚ " + L.pause) : "↻ " + L.again;
      again.setAttribute("aria-pressed", running && paused ? "true" : "false"); };
    if (s.demo && s.demo.length) { again.hidden = false; again.onclick = () => { if (layer.dataset.demo === "running") setPause(!paused); else { restore(); run(true); } }; }
    // the person takes over (scrolls, clicks, types on the page): the demonstration pauses instead of fighting them
    const takeover = e => { if (!layer || layer.dataset.demo !== "running" || paused) return; if (e.target && e.target.closest && e.target.closest(".t-tip")) return;
      if (e.type === "keydown" && (e.key === "Escape" || e.key === "Tab" || e.key === "Shift")) return; setPause(true); };
    ["wheel", "touchmove", "pointerdown", "keydown"].forEach(ev => { addEventListener(ev, takeover, { capture: true, passive: true }); cleanup.push(() => removeEventListener(ev, takeover, { capture: true })); });

    if (s.sect) {   // already know this page: jump to the step that matters
      const j = S.findIndex(z => z.key === s.sect);
      if (j > i) { const b = document.createElement("button"); b.type = "button"; b.className = "linkbtn sm t-sect"; b.textContent = s.sect_label || L.knowpage; b.onclick = () => jump(j); hint.before(b); }
    }
    if (s.sel && !t) hint.textContent = L.missing;   // the element isn't here (hidden, removed, not loaded): say so, never get stuck
    if (s.act === "next") { if (s.back) btn(L.back2, "sm", () => { write({ ...read(), i: S.findIndex(z => z.key === "pick") }); location.href = s.back; }); else btn(L.next, "sm", next); }
    else if (s.act === "done") btn(L.done, "sm", end);
    else if (s.act === "go") btn(L.go, "sm", () => { write({ ...read(), i: nextIdx, floor: nextIdx, via: null }); restore(); location.href = s.href; });
    else if (s.act === "input" && t) {
      const b = btn(L.next, "sm", next), ok = () => { b.disabled = !t.value.trim(); hint.textContent = b.disabled ? L.fill : ""; };
      ok(); t.addEventListener("input", ok); cleanup.push(() => t.removeEventListener("input", ok));
      const enter = e => { if (e.key === "Enter" && t.value.trim() && t.tagName !== "TEXTAREA") { e.preventDefault(); next(); } };
      t.addEventListener("keydown", enter); cleanup.push(() => t.removeEventListener("keydown", enter));
    } else if (s.act === "check" && t) {
      const box = t.querySelector("input[type=checkbox],input[type=radio]") || t, b = btn(L.next, "sm", next);
      const ok = () => { b.disabled = !box.checked; hint.textContent = b.disabled ? L.tick : ""; };
      ok(); const on = () => setTimeout(ok, 0); t.addEventListener("change", on); cleanup.push(() => t.removeEventListener("change", on));
    } else if (s.act === "click" && t) {
      hint.textContent = L.press;
      const on = () => { if (t.closest("a,.pcard")) write({ ...read(), i: nextIdx }); else setTimeout(next, 60); };
      t.addEventListener("click", on, true); cleanup.push(() => t.removeEventListener("click", on, true));
      if (t.matches("a[href]") || t.matches(SAFE)) btn(L.doit, "sm", async () => { const g2 = gen; await moveTo(t, g2); await press(g2); if (g2 === gen) t.click(); });
    } else if (s.act === "submit" && t) {
      hint.textContent = L.press;   // the next page moves the tour on; a form with an error stays on this step
    } else if (!t) btn(L.next, "sm", next);   // the element isn't on the page: never get stuck

    // 1) scroll the element into the safe area and wait  2) fade in  3) cursor  4) demonstration
    spotOn(null); spot.classList.add("none");
    await reveal(t, g, sheetH()); if (g !== gen) return;
    spot.classList.add("t-anim"); spotOn(t); placeTip(t, tip); setTimeout(() => spot && spot.classList.remove("t-anim"), 380);
    requestAnimationFrame(() => layer && layer.classList.add("in"));
    let lastW = innerWidth, lastH = innerHeight, lastF = mainEl, glide = 0;
    follow = () => {   // re-measure the real elements; runs only in short bursts after scrolling, resizing, layout changes or cursor moves
      if (g !== gen) return;
      if (innerWidth !== lastW || innerHeight !== lastH) { lastW = innerWidth; lastH = innerHeight; if (focusEl && !paused) reveal(focusEl, g, sheetH()); }
      spotOn(focusEl && document.body.contains(focusEl) ? focusEl : (mainEl = find(s.sel), focusEl = mainEl));
      const f = focusEl || mainEl;   // the panel stays next to what the cursor is showing; it glides only when that changes
      if (f !== lastF) { tip.classList.add("t-glide"); clearTimeout(glide); glide = setTimeout(() => tip.classList.remove("t-glide"), 420); lastF = f; }
      placeTip(f, tip, mainEl);
      if (!moving && cur && cur.classList.contains("on") && focusEl) { const p = aim(focusEl); cur._x = p.x; cur._y = p.y; place(cur); placeCap(); }
    };
    const onMove = () => kick(), ro = new ResizeObserver(onMove); ro.observe(document.body); if (t) ro.observe(t);
    addEventListener("scroll", onMove, { capture: true, passive: true }); addEventListener("resize", onMove, { passive: true });
    track = () => { ro.disconnect(); removeEventListener("scroll", onMove, { capture: true }); removeEventListener("resize", onMove); };
    kick(600);
    // keyboard: the panel's main button gets focus, unless the person is typing in the page (form steps keep their focus)
    if (!/^(input|check)$/.test(s.act)) { const a = document.activeElement; if (!a || a === document.body || (a.closest && a.closest(".t-tip"))) { const b = acts.querySelector("button:not(.t-skip):not(.ghost)") || acts.querySelector("button"); b && b.focus({ preventScroll: true }); } }
    const run = async () => {   // data-demo tells tests (and styles) whether the demonstration is still playing
      const g2 = gen; if (!t) return hideCursor(); if (layer) { layer.dataset.demo = s.demo ? "running" : "done"; label(); }
      await moveTo(t, g2); kick(); if (s.demo) await demo(s, g2, L); if (g2 === gen && layer) { layer.dataset.demo = "done"; paused = false; label(); }
    };
    if (t) run(); else hideCursor();
  }

  function resume(st, S, L) {   // on a page the tour has no step for: a small pill, never in the way
    layer = document.createElement("div"); layer.className = "tour t-pill in";
    const a = document.createElement("a"); a.className = "btn sm"; a.href = goPage(S, st.i); a.textContent = L.resume;
    const x = document.createElement("button"); x.type = "button"; x.className = "linkbtn sm"; x.textContent = L.end; x.onclick = end;
    layer.append(a, x); document.body.appendChild(layer);
  }

  document.addEventListener("click", e => {   // data-tour="student:skills" / "prof:p_status" / "new:wn_x" / "replay"
    const b = e.target.closest("[data-tour]"); if (!b) return;
    e.preventDefault(); D = D || data(); if (!D) return;
    let [t, key] = b.dataset.tour.split(":");
    if (t === "replay") { t = document.body.dataset.role === "prof" ? "prof" : "student"; key = t === "prof" ? "p_status" : "skills"; }
    if (!key) { key = t; t = "student"; }
    const S = D.tours[t]; if (!S) return;
    const i = Math.max(0, S.findIndex(s => s.key === key)), st = { t, i, floor: i, via: null, uid: D.uid };
    write(st);
    if (fits(S[i], st)) show(); else location.href = S[i].go || "/";
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && layer && !layer.classList.contains("t-pill")) end(); });
  addEventListener("beforeunload", () => restore());
  const boot = () => { D = data(); if (read()) show(); else clear(true); };
  document.addEventListener("DOMContentLoaded", boot);
  document.addEventListener("htmx:afterSettle", boot);
  addEventListener("pageshow", e => { if (e.persisted) boot(); });
})();
/* checklist: Hide list / Show list, remembered per browser */
(() => {
  const apply = () => document.querySelectorAll(".onb").forEach(c => {
    let off = false; try { off = localStorage.getItem("onb-hide-" + c.dataset.kind) === "1"; } catch (_) {}
    c.classList.toggle("collapsed", off); const b = c.querySelector(".onb-tog"); if (b) b.setAttribute("aria-expanded", off ? "false" : "true");
  });
  document.addEventListener("click", e => {
    const b = e.target.closest(".onb-tog"); if (!b) return; const c = b.closest(".onb"), off = !c.classList.contains("collapsed");
    try { localStorage.setItem("onb-hide-" + c.dataset.kind, off ? "1" : "0"); } catch (_) {} apply();
  });
  document.addEventListener("DOMContentLoaded", apply); document.addEventListener("htmx:afterSettle", apply);
})();
