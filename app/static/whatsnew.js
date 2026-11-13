/* What's new: shown once per release to people who joined before it (data from app/whatsnew.py).
   Never over a running tour, never on the login or sign-up page. Reopen from the menu under your name. */
(() => {
  const ICONS = {
    compass: '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    checklist: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3.5 6 1.5 1.5L7.5 5M3.5 12l1.5 1.5L7.5 11M3.5 18l1.5 1.5L7.5 17"/>',
    shield: '<path d="M12 3 5 6v5c0 4.6 3 8.4 7 10 4-1.6 7-5.4 7-10V6z"/><path d="m9.2 12 2 2 3.8-4"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/><path d="m9 15 2 2 4-4"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.2a2.5 2.5 0 0 1 4.8 1c0 1.7-2.4 2.2-2.4 3.6"/><path d="M12 17.2h.01"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>'
  };
  const data = () => { try { return JSON.parse(document.getElementById("wndata")?.textContent || "null"); } catch (_) { return null; } };
  const seenKey = d => "mm-wn-" + d.uid;
  const seen = d => { try { return new Set(JSON.parse(localStorage.getItem(seenKey(d)) || "[]")); } catch (_) { return new Set(); } };
  const markSeen = (d, items) => { try { const s = seen(d); items.forEach(i => s.add(i.release + ":" + i.key)); localStorage.setItem(seenKey(d), JSON.stringify([...s])); } catch (_) {} };
  let open = null;

  function show(d, items) {
    if (!items.length || open) return;
    const L = d.labels; let i = 0; const prevFocus = document.activeElement;
    const el = document.createElement("div"); el.className = "wn-back"; open = el;
    el.innerHTML = `<div class="wn" role="dialog" aria-modal="true" aria-labelledby="wn-h">
      <div class="wn-head"><div><h2 id="wn-h"></h2><p class="wn-sub muted"></p></div><button type="button" class="wn-x" aria-label=""><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
      <div class="wn-art" aria-hidden="true"><span class="wn-glow g1"></span><span class="wn-glow g2"></span><span class="wn-ic"><svg viewBox="0 0 24 24"></svg></span></div>
      <div class="wn-meta"><span class="pill wn-kind"></span><span class="wn-n muted"></span></div>
      <h3 class="wn-t"></h3><p class="wn-p"></p>
      <div class="wn-cta"><a class="btn wn-go"></a><button type="button" class="ghost wn-show"></button></div>
      <div class="wn-foot"><div class="wn-dots" aria-hidden="true"></div><div class="wn-nav"><button type="button" class="ghost sm wn-prev"></button><button type="button" class="sm wn-next"></button></div></div></div>`;
    document.body.appendChild(el);
    const $ = q => el.querySelector(q);
    $("#wn-h").textContent = L.title; $(".wn-sub").textContent = L.sub; $(".wn-x").setAttribute("aria-label", L.close);
    $(".wn-prev").textContent = L.prev; $(".wn-show").textContent = L.show;
    $(".wn-dots").innerHTML = items.map(() => "<i></i>").join("");
    const close = () => { markSeen(d, items); el.remove(); open = null; document.removeEventListener("keydown", key); try { prevFocus && prevFocus.focus(); } catch (_) {} };
    const render = () => {
      const it = items[i];
      $(".wn-ic svg").innerHTML = ICONS[it.icon] || ICONS.spark;
      $(".wn-kind").textContent = it.kind; $(".wn-kind").classList.toggle("feat", /Feature|新功能/.test(it.kind));
      $(".wn-n").textContent = `${i + 1} / ${items.length}`; $(".wn-t").textContent = it.title; $(".wn-p").textContent = it.text;
      const go = $(".wn-go"); go.textContent = it.cta;
      if (it.href === "replay") { go.removeAttribute("href"); go.setAttribute("role", "button"); go.dataset.tour = "replay"; } else { go.href = it.href; delete go.dataset.tour; go.removeAttribute("role"); }
      const sh = $(".wn-show"); sh.hidden = !it.tour || it.href === "replay"; if (it.tour) sh.dataset.tour = it.tour;
      $(".wn-prev").disabled = i === 0; $(".wn-next").textContent = i === items.length - 1 ? L.done : L.next;
      [...$(".wn-dots").children].forEach((d, j) => d.classList.toggle("on", j === i));
    };
    const key = e => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight" && i < items.length - 1) { i++; render(); }
      else if (e.key === "ArrowLeft" && i > 0) { i--; render(); }
      else if (e.key === "Tab") {   // keep focus inside the dialog
        const f = [...el.querySelectorAll("a[href],button:not([disabled]):not([hidden]),[role=button]")].filter(x => x.offsetParent);
        if (!f.length) return; const a = f[0], z = f[f.length - 1];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); } else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    $(".wn-x").onclick = close;
    el.addEventListener("click", e => { if (e.target === el) close(); });
    $(".wn-prev").onclick = () => { if (i > 0) { i--; render(); } };
    $(".wn-next").onclick = () => { if (i < items.length - 1) { i++; render(); } else close(); };
    $(".wn-go").addEventListener("click", () => close());          // the link or the tour starts; this release counts as seen
    $(".wn-show").addEventListener("click", () => close());
    render(); setTimeout(() => $(".wn-next").focus(), 30);
  }

  function auto() {
    const d = data(); if (!d || !d.items.length) return;
    if (/^\/(login|signup|reset|verify)/.test(location.pathname)) return;
    try { if (localStorage.getItem("mm-tour")) return; } catch (_) {}   // a tour is running: don't cover it
    const s = seen(d), fresh = d.items.filter(i => i.fresh && !s.has(i.release + ":" + i.key));
    if (fresh.length) setTimeout(() => show(d, fresh), 600);
  }
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-wn]"); if (!b) return;
    e.preventDefault(); const d = data(); if (!d) return;
    const latest = d.items.filter(i => i.release === d.latest);
    show(d, latest.length ? latest : d.items);
  });
  document.addEventListener("DOMContentLoaded", auto);
  document.addEventListener("htmx:afterSettle", () => { if (!open) auto(); });
})();
