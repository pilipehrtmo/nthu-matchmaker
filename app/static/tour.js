/* Guided tours (student and professor). Data comes from app/tour.py.
   The tour only highlights and explains: it never blocks the page, never clicks or submits anything itself,
   and every step can be skipped. Progress is kept in localStorage, so it survives page changes and leaving the site. */
(() => {
  const KEY = "mm-tour", MAX_AGE = 14 * 864e5;
  const read = () => { try { const v = JSON.parse(localStorage.getItem(KEY) || "null"); return v && Date.now() - (v.ts || 0) < MAX_AGE ? v : null; } catch (_) { return null; } };
  const write = v => { try { v ? localStorage.setItem(KEY, JSON.stringify({ ...v, ts: Date.now() })) : localStorage.removeItem(KEY); } catch (_) {} };
  let D = null, layer = null, raf = 0, cleanup = [];

  const data = () => { const el = document.getElementById("tourdata"); try { return el ? JSON.parse(el.textContent) : null; } catch (_) { return null; } };
  const steps = st => (D && D.tours[st.t]) || [];
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
  function target(s) {   // "a|b": the first selector with a visible match wins
    if (!s.sel) return null;
    for (const one of s.sel.split("|")) { try { const t = [...document.querySelectorAll(one)].find(e => e.getClientRects().length); if (t) return t; } catch (_) {} }
    return null;
  }
  function goPage(S, i) {   // where to send someone who is on a page with no step: this step's page, or an earlier one's
    for (let j = i; j >= 0; j--) if (S[j] && S[j].go) return S[j].go;
    return "/";
  }
  const clear = () => { cancelAnimationFrame(raf); cleanup.forEach(f => f()); cleanup = []; if (layer) layer.remove(); layer = null; };
  const end = () => { write(null); clear(); };

  function place(t, spot, tip) {
    if (!t) { spot.hidden = true; tip.classList.add("t-center"); return; }
    const r = t.getBoundingClientRect(), pad = 6;
    spot.hidden = false;
    Object.assign(spot.style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
    if (innerWidth < 640) {   // phone: a sheet at the top or bottom, whichever leaves the element visible; scroll once if neither does
      tip.classList.add("t-sheet");
      const th = tip.offsetHeight, topEdge = 76 + th, botEdge = innerHeight - 76 - th;
      const below = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, botEdge)), above = Math.max(0, Math.min(r.bottom, topEdge) - Math.max(r.top, 0));
      tip.classList.toggle("t-top", above < below || (above === below && r.top + r.height / 2 > innerHeight / 2));
      if (Math.min(above, below) > 0 && !tip.dataset.moved && r.height < botEdge - 70) { tip.dataset.moved = 1; scrollBy({ top: r.top - (botEdge - r.height) / 2 + 30, behavior: "auto" }); }
      return;
    }
    const tw = tip.offsetWidth, th = tip.offsetHeight, m = 10, W = innerWidth, H = innerHeight;
    const cx = Math.min(Math.max(m, r.left + r.width / 2 - tw / 2), W - tw - m), cy = Math.min(Math.max(m, r.top), H - th - m);
    const spots = [[cx, r.bottom + 14], [cx, r.top - th - 14], [r.right + 14, cy], [r.left - tw - 14, cy]];   // below, above, right, left
    const cover = ([x, y]) => { const X = Math.min(Math.max(m, x), W - tw - m), Y = Math.min(Math.max(m, y), H - th - m);
      return [Math.max(0, Math.min(X + tw, r.right) - Math.max(X, r.left)) * Math.max(0, Math.min(Y + th, r.bottom) - Math.max(Y, r.top)), X, Y]; };
    let best = null; for (const c of spots) { const v = cover(c); if (!best || v[0] < best[0]) best = v; if (v[0] === 0) break; }   // the first place that covers nothing, else the least covering
    let [, left, top] = best;
    Object.assign(tip.style, { top: top + "px", left: left + "px" });
  }

  function show() {
    clear();
    D = D || data(); const st = read(); if (!D || !st || !D.tours[st.t]) return;
    if (st.uid && D.uid && st.uid !== D.uid) return end();   // another person logged in on this browser
    if (!st.uid && D.uid) write({ ...st, uid: D.uid });
    const S = steps(st), L = D.labels, i = pick(st);
    if (i < 0) return resume(st, S, L);
    if (i !== st.i) write({ ...read(), i, via: st.via === S[i].key ? st.via : null });
    const s = S[i], t = target(s), main = S.filter(x => !x.alt), num = Math.max(1, S.slice(0, i + 1).filter(x => !x.alt).length), last = s.act === "done";
    layer = document.createElement("div"); layer.className = "tour"; layer.dataset.key = s.key;
    layer.innerHTML = `<div class="t-spot" aria-hidden="true"></div><div class="t-tip" role="dialog" aria-modal="false" aria-labelledby="t-h">
      <div class="t-bar"><span class="t-step"></span><button type="button" class="t-x linkbtn sm"></button></div>
      <div class="t-prog" aria-hidden="true"><i></i></div><h2 id="t-h"></h2><p class="t-text"></p>
      <p class="t-warn" role="note" hidden><b></b> <span></span></p><p class="t-hint muted fine"></p>
      <div class="t-acts"><button type="button" class="t-skip linkbtn sm"></button><span class="t-gap"></span></div></div>`;
    document.body.appendChild(layer);
    const $ = q => layer.querySelector(q), tip = $(".t-tip"), spot = $(".t-spot"), acts = $(".t-acts"), hint = $(".t-hint");
    $(".t-step").textContent = s.alt ? "" : L.step.replace("{0}", Math.min(num, main.length)).replace("{1}", main.length);
    $(".t-prog i").style.width = Math.round(Math.min(num, main.length) / main.length * 100) + "%";
    $("#t-h").textContent = s.title; $(".t-text").textContent = s.text;
    if (s.warn) { const w = $(".t-warn"); w.hidden = false; w.querySelector("b").textContent = L.warn; w.querySelector("span").textContent = s.warn; }
    const x = $(".t-x"); x.textContent = L.end; x.onclick = end;

    const jump = (j, via) => {   // the next step is on another page: go there, instead of leaving a Continue button behind
      const st2 = { ...read(), i: j, floor: j, via: via || null }; write(st2);
      const T = S[j]; let elsewhere = false;
      try { elsewhere = T && !fits(T, st2) && T.go && new URL(T.go, location.href).pathname !== location.pathname; } catch (_) {}
      if (elsewhere) location.href = T.go; else show();
    };
    const nextIdx = i + 1;
    const skip = $(".t-skip");
    if (last) skip.remove();
    else { skip.textContent = L.skip; skip.onclick = () => { if (s.skip) jump(S.findIndex(z => z.key === s.skip), s.skip); else jump(nextIdx); }; }
    const btn = (label, cls, fn) => { const b = document.createElement("button"); b.type = "button"; b.className = cls; b.textContent = label; b.onclick = fn; acts.appendChild(b); return b; };
    if (i > 0 && !S[i - 1].via && fits(S[i - 1], { via: null }) && S[i - 1].act !== "submit" && !s.via) btn(L.back, "ghost sm", () => { const st2 = read(); write({ ...st2, i: i - 1, floor: Math.min(st2.floor || 0, i - 1) }); show(); });

    const next = () => jump(nextIdx);
    if (s.act === "next") { if (s.back) btn(L.back2, "sm", () => { write({ ...read(), i: S.findIndex(z => z.key === "pick") }); location.href = s.back; }); else btn(L.next, "sm", next); }
    else if (s.act === "done") btn(L.done, "sm", end);
    else if (s.act === "go") btn(L.go, "sm", () => { write({ ...read(), i: nextIdx, floor: nextIdx, via: null }); location.href = s.href; });
    else if (s.act === "input" && t) {
      const b = btn(L.next, "sm", next), ok = () => { b.disabled = !t.value.trim(); hint.textContent = b.disabled ? L.fill : ""; };
      ok(); t.addEventListener("input", ok); cleanup.push(() => t.removeEventListener("input", ok));
      const enter = e => { if (e.key === "Enter" && t.value.trim() && t.tagName !== "TEXTAREA") { e.preventDefault(); next(); } };
      t.addEventListener("keydown", enter); cleanup.push(() => t.removeEventListener("keydown", enter));
      setTimeout(() => { try { if (!t.value) t.focus({ preventScroll: true }); } catch (_) {} }, 350);
    } else if (s.act === "check" && t) {
      const box = t.querySelector("input[type=checkbox],input[type=radio]") || t, b = btn(L.next, "sm", next);
      const ok = () => { b.disabled = !box.checked; hint.textContent = b.disabled ? L.tick : ""; };
      ok(); const on = () => setTimeout(ok, 0); t.addEventListener("change", on); cleanup.push(() => t.removeEventListener("change", on));
    } else if (s.act === "click" && t) {
      hint.textContent = L.press;
      const on = () => { if (t.closest("a,.pcard")) write({ ...read(), i: nextIdx }); else setTimeout(next, 60); };
      t.addEventListener("click", on, true); cleanup.push(() => t.removeEventListener("click", on, true));
    } else if (s.act === "submit" && t) {
      hint.textContent = L.press;   // the next page moves the tour on; a form with an error stays on this step
    } else if (!t) btn(L.next, "sm", next);   // the element isn't on the page: never get stuck

    if (t) t.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    const loop = () => { place(target(s) || t, spot, tip); raf = requestAnimationFrame(loop); }; loop();
  }

  function resume(st, S, L) {   // on a page the tour has no step for: a small pill, never in the way
    layer = document.createElement("div"); layer.className = "tour t-pill";
    const a = document.createElement("a"); a.className = "btn sm"; a.href = goPage(S, st.i); a.textContent = L.resume;
    const x = document.createElement("button"); x.type = "button"; x.className = "linkbtn sm"; x.textContent = L.end; x.onclick = end;
    layer.append(a, x); document.body.appendChild(layer);
  }

  document.addEventListener("click", e => {   // data-tour="student:skills" / "prof:p_status" / "replay"
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
  const boot = () => { D = data(); if (read()) show(); else clear(); };
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
