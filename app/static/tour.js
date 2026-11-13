/* Guided tour: highlights a real element and waits for the person to use it. Data comes from app/tour.py. */
(() => {
  const KEY = "mm-tour";
  const get = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (_) { return null; } };
  const put = v => { try { v === null ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, JSON.stringify(v)); } catch (_) {} };
  let D = null, cur = -1, layer = null, raf = 0, cleanup = [];

  const data = () => { const el = document.getElementById("tourdata"); if (!el) return null; try { return JSON.parse(el.textContent); } catch (_) { return null; } };
  const fits = (s) => {
    if (!new RegExp(s.path).test(location.pathname)) return false;
    if (s.q && !location.search.includes(s.q)) return false;
    if (s.unless && location.search.includes(s.unless)) return false;
    if (s.need) { try { if (!document.querySelector(s.need)) return false; } catch (_) { return false; } }
    return true;
  };
  const pick = (i) => {   // the step for this page: the current one, else the nearest after it, else the nearest before it
    const S = D.steps;
    for (let j = i; j < S.length; j++) if (fits(S[j])) return j;
    for (let j = i - 1; j >= 0; j--) if (fits(S[j])) return j;
    return -1;
  };
  const target = (s) => {   // selectors separated by "|" are tried in order: the first visible match wins
    if (!s.sel) return null;
    for (const one of s.sel.split("|")) { try { const t = [...document.querySelectorAll(one)].find(e => e.getClientRects().length); if (t) return t; } catch (_) {} }
    return null;
  };

  function clear() { cancelAnimationFrame(raf); cleanup.forEach(f => f()); cleanup = []; if (layer) layer.remove(); layer = null; }
  function end() { put(null); clear(); }
  function goStep(i) { put({ i }); show(); }

  function place(t, spot, tip) {
    const narrow = innerWidth < 640;
    if (!t) { spot.hidden = true; tip.classList.add("t-center"); return; }
    const r = t.getBoundingClientRect(), pad = 6;
    spot.hidden = false;
    Object.assign(spot.style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
    if (narrow) { tip.classList.add("t-sheet"); tip.classList.toggle("t-top", r.top > innerHeight * 0.55); return; }
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let top = r.bottom + 14, left = Math.min(Math.max(12, r.left + r.width / 2 - tw / 2), innerWidth - tw - 12);
    if (top + th > innerHeight - 12) top = Math.max(12, r.top - th - 14);
    Object.assign(tip.style, { top: top + "px", left: left + "px" });
  }

  function show() {
    clear();
    D = D || data(); const st = get(); if (!D || !st) return;
    const S = D.steps, L = D.labels;
    const i = pick(st.i);
    if (i < 0) return resume(S[st.i], L);
    if (i !== st.i) put({ i });
    cur = i; const s = S[i], t = target(s), main = S.filter(x => !x.alt), n = main.length, num = S.slice(0, i + 1).filter(x => !x.alt).length || 1;
    layer = document.createElement("div"); layer.className = "tour";
    layer.innerHTML = `<div class="t-spot" aria-hidden="true"></div><div class="t-tip" role="dialog" aria-live="polite" aria-labelledby="t-h">
      <div class="t-bar"><span class="t-step"></span><button type="button" class="t-x linkbtn sm"></button></div>
      <div class="t-prog" aria-hidden="true"><i style="width:${Math.round(num / n * 100)}%"></i></div>
      <h2 id="t-h"></h2><p class="t-text"></p><p class="t-hint muted fine"></p><div class="t-acts"></div></div>`;
    document.body.appendChild(layer);
    const tip = layer.querySelector(".t-tip"), spot = layer.querySelector(".t-spot"), acts = layer.querySelector(".t-acts"), hint = layer.querySelector(".t-hint");
    layer.querySelector(".t-step").textContent = L.step.replace("{0}", num).replace("{1}", n);
    layer.querySelector("#t-h").textContent = s.title; layer.querySelector(".t-text").textContent = s.text;
    const x = layer.querySelector(".t-x"); x.textContent = L.skip; x.onclick = end;
    const btn = (label, cls, fn) => { const b = document.createElement(cls === "a" ? "a" : "button"); if (cls !== "a") { b.type = "button"; b.className = cls; } else { b.className = "btn sm"; b.href = fn; } b.textContent = label; if (cls !== "a") b.onclick = fn; acts.appendChild(b); return b; };
    if (i > 0 && fits(S[i - 1]) && S[i - 1].act !== "submit") btn(L.back, "ghost sm", () => goStep(i - 1));

    const next = () => goStep(i + 1);
    if (s.act === "next") { if (s.back) btn(L.back2, "a", s.back); else btn(L.next, "sm", next); }
    else if (s.act === "done") btn(L.done, "sm", end);
    else if (s.act === "input" && t) {
      const b = btn(L.next, "sm", next), ok = () => { b.disabled = !t.value.trim(); hint.textContent = b.disabled ? L.fill : ""; };
      ok(); t.addEventListener("input", ok); cleanup.push(() => t.removeEventListener("input", ok));
      const enter = e => { if (e.key === "Enter" && t.value.trim() && t.tagName !== "TEXTAREA") { e.preventDefault(); next(); } };
      t.addEventListener("keydown", enter); cleanup.push(() => t.removeEventListener("keydown", enter));
      setTimeout(() => { try { t.focus({ preventScroll: true }); } catch (_) {} }, 350);
    } else if (s.act === "check" && t) {
      const box = t.querySelector("input[type=checkbox]") || t, b = btn(L.next, "sm", next);
      const ok = () => { b.disabled = !box.checked; hint.textContent = b.disabled ? L.tick : ""; };
      ok(); box.addEventListener("change", ok); cleanup.push(() => box.removeEventListener("change", ok));
    } else if (s.act === "click" && t) {
      hint.textContent = L.press;
      const on = () => { if (!/^(A)$/.test(t.tagName) && !t.closest("a,.pcard")) setTimeout(next, 60); else put({ i: i + 1 }); };
      t.addEventListener("click", on, true); cleanup.push(() => t.removeEventListener("click", on, true));
    } else if (s.act === "submit" && t) {
      hint.textContent = L.press;   // the next page moves the tour on; a form with an error stays on this step
    }

    t && t.scrollIntoView({ block: "center", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    const loop = () => { place(target(s) || t, spot, tip); raf = requestAnimationFrame(loop); }; loop();
  }

  function resume(s, L) {   // on a page the tour has no step for: a small pill back to where it was
    if (!s) return end();
    layer = document.createElement("div"); layer.className = "tour t-pill";
    const a = document.createElement("a"); a.className = "btn sm"; a.href = s.go || "/"; a.textContent = L.resume;
    const x = document.createElement("button"); x.type = "button"; x.className = "linkbtn sm"; x.textContent = L.skip; x.onclick = end;
    layer.append(a, x); document.body.appendChild(layer);
  }

  document.addEventListener("click", e => {   // any [data-tour="key"] button starts the tour at that step
    const b = e.target.closest("[data-tour]"); if (!b) return;
    e.preventDefault(); D = D || data(); if (!D) return;
    const i = Math.max(0, D.steps.findIndex(s => s.key === b.dataset.tour)); put({ i });
    if (fits(D.steps[i])) show(); else location.href = D.steps[i].go || "/";
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && layer) end(); });
  const boot = () => { D = data(); if (get()) show(); };
  document.addEventListener("DOMContentLoaded", boot);
  document.addEventListener("htmx:afterSettle", boot);
  addEventListener("pageshow", e => { if (e.persisted) boot(); });
})();
