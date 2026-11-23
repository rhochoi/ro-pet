/* ro, walking around the site.
   One small script, no requests, no dependencies. ro stands on the tops of cards and headings, hops between them,
   follows your cursor with its eyes, and answers questions about this site from what is written here.
   It never speaks first: every word it says is a reaction to something you did.
   Source of truth for the look: "ro pet viz" (ink layers, left aligned, feelings only through eyes and layers). */
(() => {
  "use strict";
  if (window.RO_ROAM) return;

  const doc = document, root = doc.documentElement;
  const script = doc.currentScript || [...doc.scripts].find((s) => /ro-roam\.js/.test(s.src)) || {};
  const BASE = (script.dataset && script.dataset.root) || "";          // "" on /, "../" one folder down
  const PAGE = (script.dataset && script.dataset.page) || "doc";        // home | pro | doc
  const $ = (s, r = doc) => r.querySelector(s);
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, u) => a + (b - a) * u;
  const rand = (a, b) => a + Math.random() * (b - a);
  const ease = (u) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
  const store = {
    get() { try { return JSON.parse(sessionStorage.getItem("ro-roam") || "{}") || {}; } catch (e) { return {}; } },
    set(o) { try { sessionStorage.setItem("ro-roam", JSON.stringify(o)); } catch (e) { /* private mode: fine */ } },
  };
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  let reduced = motionQuery.matches;
  const touchy = matchMedia("(hover: none)").matches;

  /* ---------- the figure ---------- */
  const NS = "http://www.w3.org/2000/svg";
  const mk = (n, a, p) => { const e = doc.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; };
  const ART = 145.67 / 176;           // the mark's width as a share of the element (viewBox is padded for lifted heads and wide bases)
  const PIVOT_X = 0.448, PIVOT_Y = 0.97;

  // feelings, in the mark's own units (head 120.33 x 50.67 at 0,0). Eyes sit in absolute head coordinates.
  const base = { hx: 0, hy: 0, hr: 0, bx: 0, by: 57, bw: 95, sw: 145.67, ra: 1, aa: 0, sa: 0,
    e1x: 57, e1y: 11.08, e1w: 12.67, e1h: 25.33, e1r: 6.33, e2x: 82.33, e2y: 14.25, e2w: 11.08, e2h: 20.58, e2r: 5.54 };
  const X = {
    calm: base,
    focus: { ...base, e1x: 52.25, e1y: 20.58, e1w: 22.17, e1h: 7.92, e1r: 3.96, e2x: 79.17, e2y: 21.38, e2w: 17.42, e2h: 7.13, e2r: 3.56 },
    sleep: { ...base, e1x: 52.25, e1y: 24.5, e1w: 22.17, e1h: 3.4, e1r: 1.7, e2x: 79.17, e2y: 25.3, e2w: 17.42, e2h: 3.2, e2r: 1.6, hy: 3, by: 59 },
    find: { ...base, hy: -6.33, e1x: 52.25, e1y: 4.75, e1w: 20.58, e1h: 20.58, e1r: 10.29, e2x: 79.17, e2y: 7.92, e2w: 15.83, e2h: 15.83, e2r: 7.92 },
    relief: { ...base, sw: 167.83, ra: 0, aa: 1 },
    uneasy: { ...base, hx: -6.33, bx: 7.92, e1x: 38, e1y: 17.42, e1w: 8.71, e1h: 14.25, e1r: 4.35, e2x: 55.42, e2y: 19.79, e2w: 7.92, e2h: 11.08, e2r: 3.96 },
    sulk: { ...base, hy: 0.67, hr: 5, by: 60.34, ra: 0, sa: 1 },
    record: { ...base, bw: 114, e1y: 23.75, e1h: 15.83, e2y: 25.33, e2h: 12.67 },
  };

  const root$ = doc.createElement("div");
  root$.id = "rr-root";
  const ro = doc.createElement("div");
  ro.className = "rr";
  const fig = doc.createElement("div");
  fig.className = "rr-fig";
  const svg = mk("svg", { class: "ro-mark rr-svg", viewBox: "-6 -10 176 154", "aria-hidden": "true", focusable: "false" });
  const gBase = mk("g", {}, svg), gBody = mk("g", {}, svg), gHead = mk("g", {}, svg);
  const rBase = mk("rect", { class: "ro-b", x: 0, y: 101.33, width: 145.67, height: 38, rx: 19 }, gBase);
  const rBody = mk("rect", { class: "ro-b", x: 0, y: 57, width: 95, height: 38, rx: 19 }, gBody);
  const rHead = mk("rect", { class: "ro-b", x: 0, y: 0, width: 120.33, height: 50.67, rx: 25.33 }, gHead);
  const gEyes = mk("g", {}, gHead);
  const gRect = mk("g", {}, gEyes), gArc = mk("g", {}, gEyes), gSulk = mk("g", {}, gEyes);
  const e1 = mk("rect", { class: "ro-e" }, gRect), e2 = mk("rect", { class: "ro-e" }, gRect);
  mk("path", { class: "ro-e", transform: "translate(50.667 15.833)", d: "M25.333 12.667c0-6.996-5.671-12.667-12.666-12.667-6.996 0-12.667 5.671-12.667 12.667h6.333c0-3.498 2.836-6.334 6.334-6.334 3.497 0 6.333 2.836 6.333 6.334z" }, gArc);
  mk("path", { class: "ro-e", transform: "translate(76.79 19)", d: "M22.167 11.083c0-6.121-4.963-11.083-11.084-11.083-6.121 0-11.083 4.962-11.083 11.083h5.542c0-3.06 2.481-5.541 5.541-5.541 3.061 0 5.542 2.481 5.542 5.541z" }, gArc);
  mk("path", { class: "ro-e", transform: "matrix(.996195 .087156 -.087156 .996195 48.2333 32.9667)", d: "M0 4.67v-3.17q0-.298 .114-.574 .114-.276 .325-.487 .211-.211 .487-.325 .276-.114 .574-.114h9.67q.298 0 .574 .114 .276 .114 .487 .325 .211 .211 .325 .487 .114 .276 .114 .574v3.17q0 1.259-.482 2.422-.482 1.164-1.372 2.054-.89 .89-2.054 1.372-1.163 .482-2.422 .482h-.01q-1.259 0-2.422-.482-1.164-.482-2.054-1.372-.89-.89-1.372-2.054-.482-1.163-.482-2.422z" }, gSulk);
  mk("path", { class: "ro-e", transform: "matrix(.996195 .087156 -.087156 .996195 72.4333 36.5667)", d: "M0 3.96v-2.46q0-.298 .114-.574 .114-.276 .325-.487 .211-.211 .487-.325 .276-.114 .574-.114h8.08q.298 0 .574 .114 .276 .114 .487 .325 .211 .211 .325 .487 .114 .276 .114 .574v2.46q0 1.102-.422 2.12-.421 1.018-1.201 1.797-.779 .78-1.797 1.201-1.018 .422-2.12 .422-1.102 0-2.12-.422-1.018-.421-1.797-1.201-.78-.779-1.201-1.797-.422-1.018-.422-2.12z" }, gSulk);

  const body = doc.createElement("button");
  body.type = "button";
  body.className = "rr-body";
  body.setAttribute("aria-label", "ro. Press to ask me about this site.");
  body.setAttribute("aria-haspopup", "dialog");
  body.setAttribute("aria-expanded", "false");
  body.setAttribute("aria-keyshortcuts", "Alt+R");
  fig.append(svg);
  ro.append(fig, body);

  const murmur = doc.createElement("div");
  murmur.className = "rr-murmur";
  murmur.setAttribute("aria-hidden", "true");

  const panel = doc.createElement("div");
  panel.className = "rr-panel";
  panel.hidden = true;
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Ask ro");
  panel.innerHTML =
    '<p class="rr-say" aria-hidden="true"></p><p class="rr-sr" aria-live="polite"></p>' +
    '<div class="rr-chips"></div><div class="rr-links"></div>' +
    '<form class="rr-ask" autocomplete="off"><label class="rr-sr" for="rr-q">Ask ro about this site</label>' +
    '<input id="rr-q" name="q" type="text" maxlength="120" placeholder="Ask ro about this site" enterkeyhint="send">' +
    '<button type="submit" aria-label="Ask">↵</button></form>' +
    '<div class="rr-foot"><button type="button" data-rr="rest">Let ro rest</button><span>⌥R · esc</span></div>';
  const sayEl = $(".rr-say", panel), liveEl = $(".rr-sr", panel), chipsEl = $(".rr-chips", panel), linksEl = $(".rr-links", panel);
  const form = $("form", panel), input = $("input", panel), restBtn = $('[data-rr="rest"]', panel);
  root$.append(ro, murmur, panel);

  /* ---------- state ---------- */
  let W = 64, H = 56, vw = 1280, vh = 800;
  const FLOOR = 10;
  const saved = store.get();
  let rest = !!saved.rest;
  let st = "idle";                      // idle | walk | crouch | hop | fall | drag
  let perch = { kind: "floor" }, tt = 0.85;
  let x = 0, y = 0, s = 1, vy = 0;
  let timer = 2.5, walkTo = 0, walkSpeed = 70, dir = 1, phase = 0, sq = 0, hp = null;
  let ambient = "calm", temp = null, tempUntil = 0;
  let lookX = 0.35, lookY = 0, lookTX = 0.35, lookTY = 0, lookTimer = 2;
  let blink = 0, blinkTimer = 3;
  let asleep = false, lastActive = 0, open = false, hovering = false;
  let ptr = { x: -999, y: -999, t: -99 };
  let now = 0, last = 0, raf = 0, murmurTill = 0, lastMurmur = -99;
  let drag = null, homeEl = null, stage = null, away = false, pendingOpen = false;
  const cur = { ...base };
  let moving = false;

  const measure = () => {
    vw = root.clientWidth; vh = innerHeight;
    W = ro.offsetWidth || 64; H = ro.offsetHeight || 56;
  };

  /* ---------- surfaces ---------- */
  function surf(p, t) {
    if (p.kind === "floor") return { x: t * vw, y: vh - FLOOR, s: 1, ok: true, w: vw };
    const r = p.el.getBoundingClientRect();
    if (p.kind === "home") return { x: r.left + r.width / 2, y: r.bottom, s: r.width / (ART * W), ok: r.width > 0 && r.bottom > H * 0.6 && r.top < vh - 40, w: r.width };
    return { x: r.left + t * r.width, y: r.top, s: 1, ok: p.el.isConnected && r.width > 0 && r.top > H + 22 && r.top < vh - 18, w: r.width };
  }
  const PERCH_SEL = "main h2, .card, .price, .table-card, .demo-stage, .term, .hero-stage, footer.foot";
  function candidates(skip) {
    const out = [];
    doc.querySelectorAll(PERCH_SEL).forEach((el) => {
      if (skip && perch.el === el) return;
      const r = el.getBoundingClientRect();
      if (r.width < 90 || r.top <= H + 22 || r.top >= vh - 18 || r.left > vw - 60 || r.right < 60) return;
      out.push({ p: { kind: "el", el }, r });
    });
    return out;
  }
  const pickT = (el) => (el.matches("h2") ? rand(0.04, 0.96) : el.matches(".card, .price, .table-card") ? rand(0.55, 0.92) : rand(0.12, 0.88));
  const floorT = () => clamp(x / vw, 0.04, 0.96);

  /* ---------- feelings ---------- */
  function emote(name, ms) { temp = name; tempUntil = now + ms / 1000; kick(); }
  const feeling = () => (open && !temp ? (input.value ? "focus" : ambient) : temp && now < tempUntil ? temp : asleep ? "sleep" : ambient);

  /* ---------- movement ---------- */
  function hop(dest, destT, then, quiet) {
    if (reduced) { const f = surf(dest, destT); x = f.x; y = f.y; s = f.s; hp = { then }; land(dest, destT, false); sq = 0; kick(); return; }
    st = "crouch"; timer = quiet ? 0.05 : 0.15; hp = { dest, t: destT, then }; kick();
  }
  function startHop() {
    const f = surf(hp.dest, hp.t);
    const dist = Math.hypot(f.x - x, f.y - y);
    hp.from = { x, y, s }; hp.t0 = now; hp.dur = clamp(0.38 + dist / 1500, 0.4, 0.95); hp.arc = clamp(28 + dist * 0.14, 28, 130);
    dir = f.x >= x ? 1 : -1; st = "hop";
    emote("find", hp.dur * 1000 + 150);
  }
  function land(dest, destT, hard) {
    perch = dest; tt = destT; st = "idle"; timer = rand(2.2, 5); sq = hard ? 1 : 0.7; vy = 0;
    if (perch.kind === "home") { away = false; stage && stage.classList.remove("is-away"); emote("relief", 1600); }
    const cb = hp && hp.then; hp = null; if (cb) cb();
    if (pendingOpen && perch.kind !== "home") { pendingOpen = false; openPanel(); }
  }
  function walkTo_(target, speed) { walkTo = clamp(target, -0.2, 1.2); walkSpeed = speed || 70; st = "walk"; kick(); }
  function fallToFloor() { perch = { kind: "floor" }; tt = clamp(x / vw, 0.04, 0.96); st = "fall"; vy = 0; }
  function leaveHome() {
    if (perch.kind !== "home" && !(st === "hop" && hp && hp.dest.kind === "home")) return;
    const c = candidates(true);
    const pick = c.length ? c[Math.floor(rand(0, Math.min(c.length, 4)))] : null;
    away = true; stage && stage.classList.add("is-away");
    if (pick) hop(pick.p, pickT(pick.p.el)); else hop({ kind: "floor" }, rand(0.3, 0.8));
  }
  function goHome() {
    if (!homeEl) return false;
    const r = homeEl.getBoundingClientRect();
    const go = () => hop({ kind: "home", el: homeEl }, 0.5);
    if (r.top < 40 || r.bottom > vh - 20) {
      scrollToEl(stage || homeEl, 0.45); setTimeout(go, reduced ? 0 : 650);
    } else go();
    return true;
  }
  function scrollToEl(el, at) {
    const r = el.getBoundingClientRect();
    scrollBy({ top: r.top - vh * (at || 0.4), behavior: reduced ? "auto" : "smooth" });
  }

  function think() {
    if (rest || reduced || open || hovering || asleep || st !== "idle" || drag) return;
    timer = rand(2.4, 6);
    const r = Math.random(), c = candidates(true);
    const f = surf(perch, tt);
    if (r < 0.42 && f.w > 200) {
      const span = perch.kind === "floor" ? 0.3 : 0.5;
      let to = tt + rand(-span, span);
      if (Math.abs(to - tt) * f.w < 80) to = tt + (Math.random() < 0.5 ? -1 : 1) * 80 / f.w;
      walkTo_(clamp(to, 0.05, 0.95), rand(55, 90));
    } else if (r < 0.88 && (c.length || perch.kind !== "floor")) {
      if (perch.kind !== "floor" && (!c.length || Math.random() < 0.25)) hop({ kind: "floor" }, rand(0.1, 0.9));
      else {
        c.sort((a, b) => Math.hypot(a.r.left - x, a.r.top - y) - Math.hypot(b.r.left - x, b.r.top - y));
        const pick = c[Math.floor(rand(0, Math.min(c.length, 5)))];
        hop(pick.p, pickT(pick.p.el));
      }
    } else { lookTX = rand(-0.9, 1); lookTY = rand(-0.5, 0.4); }
  }

  /* ---------- per frame ---------- */
  function update(dt) {
    sq += (0 - sq) * (1 - Math.exp(-dt * 13));
    if (st === "idle" || st === "walk") {
      if (st === "walk") {
        const f0 = surf(perch, tt), step = (walkSpeed * dt) / Math.max(f0.w, 1);
        dir = walkTo >= tt ? 1 : -1;
        phase += walkSpeed * dt * 0.11;
        if (Math.abs(walkTo - tt) <= step) { tt = walkTo; st = "idle"; timer = rand(2, 5); }
        else tt += dir * step;
      }
      const f = surf(perch, tt);
      if (!f.ok) { fallToFloor(); }
      else {
        x = f.x; y = f.y; s += (f.s - s) * (1 - Math.exp(-dt * 12)); if (Math.abs(s - f.s) < 0.002) s = f.s;
        if (st === "idle") {
          timer -= dt;
          if (hovering || open) timer = Math.max(timer, 2);
          if (timer <= 0) { if (perch.kind === "home" && !away && !rest && !reduced) leaveHome(); else think(); }
        }
      }
    }
    if (st === "crouch") {
      sq = Math.max(sq, 0.85); timer -= dt;
      if (timer <= 0) startHop();
    }
    if (st === "hop") {
      const u = clamp((now - hp.t0) / hp.dur, 0, 1), f = surf(hp.dest, hp.t);
      if (!f.ok && hp.dest.kind === "el") { hp.dest = { kind: "floor" }; hp.t = clamp(x / vw, 0.05, 0.95); }
      const e = ease(u);
      x = lerp(hp.from.x, f.x, e); y = lerp(hp.from.y, f.y, e) - hp.arc * 4 * u * (1 - u); s = lerp(hp.from.s, f.s, e);
      sq = Math.min(sq, -0.5 * Math.sin(Math.PI * u));
      if (u >= 1) land(hp.dest, hp.t, false);
    }
    if (st === "fall") {
      vy += 2600 * dt; y += vy * dt; s += (1 - s) * (1 - Math.exp(-dt * 8));
      const f = surf(perch, tt);
      if (!f.ok) { perch = { kind: "floor" }; tt = clamp(x / vw, 0.04, 0.96); }
      else {
        x += (f.x - x) * (1 - Math.exp(-dt * 14));
        if (y >= f.y) { y = f.y; land(perch, tt, true); const k = perch.kind; if (k !== "home") murmurSay(k === "floor" ? "thanks." : "good view."); }
      }
    }
    if (st === "drag") { s += (1 - s) * (1 - Math.exp(-dt * 12)); }

    // eyes
    const centered = st === "walk" || st === "hop";
    if (centered) { lookTX = dir * 0.9; lookTY = st === "hop" ? -0.3 : 0; }
    else if (!reduced && now - ptr.t < 4 && !asleep) {
      const cx = x, cy = y - H * s * 0.72;
      lookTX = clamp((ptr.x - cx) / 240, -1, 1); lookTY = clamp((ptr.y - cy) / 240, -1, 1);
    } else if (!reduced) {
      lookTimer -= dt;
      if (lookTimer <= 0 && st === "idle" && !asleep) { lookTimer = rand(2.5, 5); if (Math.random() < 0.4) { lookTX = rand(-0.5, 1); lookTY = rand(-0.4, 0.3); } }
    }
    const k = 1 - Math.exp(-dt * 9);
    lookX += (lookTX - lookX) * k; lookY += (lookTY - lookY) * k;
    blinkTimer -= dt;
    if (blinkTimer <= 0 && !reduced) { blink = 1; blinkTimer = rand(2.8, 6.5); }
    blink = Math.max(0, blink - dt * 7);
    if (asleep && !reduced && Math.random() < 0.0) blink = 0;
  }

  function render(dt) {
    // expression: ease every number toward its target
    const tgt = X[feeling()] || base, kk = 1 - Math.exp(-dt * 16);
    moving = false;
    for (const key in tgt) { const d = tgt[key] - cur[key]; if (Math.abs(d) > 0.01) { cur[key] += reduced ? d : d * kk; moving = true; } else cur[key] = tgt[key]; }
    // body language
    const t = now, walking = st === "walk", dragging = st === "drag";
    const bob = (o, a) => (walking ? -Math.abs(Math.sin(phase - o)) * a : 0);
    const breath = Math.sin(t * (asleep ? 1.1 : 1.7)) * (asleep ? 1.6 : 0.7);
    let hdx = walking ? dir * 3 : 0, bdx = walking ? dir * 1.5 : 0, sdx = 0;
    let hdy = bob(0, 4) + (reduced ? 0 : breath), bdy = bob(0.55, 3) + (reduced ? 0 : breath * 0.5), sdy = bob(1.1, 1.6);
    if (dragging) { hdx = Math.sin(t * 8 + 2) * 4; bdx = Math.sin(t * 8 + 1) * 6; sdx = Math.sin(t * 8) * 4; hdy = Math.sin(t * 11) * 1.5; }
    gHead.setAttribute("transform", `translate(${hdx.toFixed(2)} ${hdy.toFixed(2)})`);
    gBody.setAttribute("transform", `translate(${bdx.toFixed(2)} ${bdy.toFixed(2)})`);
    gBase.setAttribute("transform", `translate(${sdx.toFixed(2)} ${sdy.toFixed(2)})`);
    rHead.setAttribute("transform", `translate(${cur.hx.toFixed(2)} ${cur.hy.toFixed(2)}) rotate(${cur.hr.toFixed(2)})`);
    rBody.setAttribute("x", cur.bx.toFixed(2)); rBody.setAttribute("y", cur.by.toFixed(2)); rBody.setAttribute("width", cur.bw.toFixed(2));
    rBase.setAttribute("width", cur.sw.toFixed(2));
    const bl = 1 - 0.92 * blink;
    for (const [e, n] of [[e1, "e1"], [e2, "e2"]]) {
      const h = cur[n + "h"] * bl, cy = cur[n + "y"] + (cur[n + "h"] - h) / 2;
      e.setAttribute("x", cur[n + "x"].toFixed(2)); e.setAttribute("y", cy.toFixed(2));
      e.setAttribute("width", cur[n + "w"].toFixed(2)); e.setAttribute("height", h.toFixed(2));
      e.setAttribute("rx", Math.min(cur[n + "r"], h / 2, cur[n + "w"] / 2).toFixed(2)); e.setAttribute("ry", Math.min(cur[n + "r"], h / 2, cur[n + "w"] / 2).toFixed(2));
    }
    gRect.setAttribute("opacity", cur.ra.toFixed(2)); gArc.setAttribute("opacity", cur.aa.toFixed(2)); gSulk.setAttribute("opacity", cur.sa.toFixed(2));
    gEyes.setAttribute("transform", `translate(${(lookX * 5.5).toFixed(2)} ${(lookY * 3).toFixed(2)})`);
    // placement
    const ox = PIVOT_X * W, oy = PIVOT_Y * H;
    ro.style.transform = `translate(${(x - ox).toFixed(1)}px, ${(y - oy).toFixed(1)}px) scale(${s.toFixed(3)})`;
    fig.style.transform = `scale(${(1 + 0.1 * sq).toFixed(3)}, ${(1 - 0.12 * sq).toFixed(3)})`;
    ro.classList.toggle("is-drag", dragging);
    // bubble and murmur follow ro
    const roH = H * s * PIVOT_Y;
    if (open) {
      const bw = panel.offsetWidth, bh = panel.offsetHeight;
      let top = y - roH - bh - 12, side = "above";
      if (top < 8) { top = y + 14; side = "below"; if (top + bh > vh - 8) top = Math.max(8, vh - 8 - bh); }
      const left = clamp(x - bw / 2, 8, Math.max(8, vw - bw - 8));
      panel.style.transform = `translate(${left.toFixed(1)}px, ${top.toFixed(1)}px)`;
      panel.dataset.side = side;
      panel.style.setProperty("--tail", clamp(x - left, 24, bw - 24).toFixed(1) + "px");
    }
    const mon = (asleep && !open) || now < murmurTill;
    murmur.classList.toggle("is-on", mon && !open);
    if (mon && !open) {
      const mw = murmur.offsetWidth;
      murmur.style.transform = `translate(${clamp(x - mw / 2, 8, vw - mw - 8).toFixed(1)}px, ${Math.max(6, y - roH - 34).toFixed(1)}px)`;
    }
  }

  function frame(ts) {
    raf = 0;
    const dt = clamp((ts - last) / 1000, 0, 0.05); last = ts; now = ts / 1000;
    measure();
    if (!asleep && !open && !rest && !reduced && st === "idle" && now - lastActive > 50) { asleep = true; murmur.textContent = "z z z"; }
    update(dt); render(dt);
    const settled = (rest || reduced) && st === "idle" && !moving && !open && Math.abs(sq) < 0.01 && now >= murmurTill && !hovering && now >= tempUntil;
    if (!doc.hidden && !settled) raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf && !doc.hidden) { last = performance.now(); raf = requestAnimationFrame(frame); } }

  /* ---------- murmurs (reactions only) ---------- */
  function murmurSay(text, ms) {
    if (open || now - lastMurmur < 0.8) return;
    lastMurmur = now; murmur.textContent = text; murmurTill = now + (ms || 1700) / 1000; kick();
  }
  function wake(msg) {
    lastActive = now;
    if (asleep) { asleep = false; emote("find", 700); if (msg !== false) murmurSay("oh. hi."); }
  }

  /* ---------- talking ---------- */
  const GITHUB = "https://github.com/rhochoi/ro-pet/releases";
  const L = (label, href) => ({ label, href });
  const INTENTS = [
    { re: /\/file|find (a |my )?files?|\bsearch|⌥|option ?r\b|alt ?r\b/, x: "find", at: { pro: "#does" }, go: L("How file search works", "pro/#does"),
      say: "That's a pro thing. On your Mac, press ⌥R and type what you remember, like “the contract PDF from last month”, and I look on this Mac only. The same shortcut wakes me up here.", chips: ["How much is pro?", "Is my data safe?"] },
    { re: /handoff|hand.?off|switch(ing)? (ai|tools?)|tokens/, x: "focus", at: { pro: "#does" }, go: L("See pro", "pro/#does"),
      say: "Out of tokens in one AI tool? /handoff writes a note from the history that tool left on your Mac, hides secrets, and opens the next tool. You paste it. I never send it anywhere.", chips: ["How much is pro?"] },
    { re: /\/connect|connect.*(ai|tools?)/, x: "focus", at: { pro: "#does" }, go: L("See pro", "pro/#does"),
      say: "/connect shows which of your AI tools share the same rules and safety hook. I show the exact changes first and write only the ones you approve.", chips: ["What does pro do?"] },
    { re: /tidy|organi[sz]e|downloads folder|clean ?up|messy/, x: "relief", at: { pro: "#does" }, go: L("See pro", "pro/#does"),
      say: "Tidying starts as a suggestion. I say where each file could go and move only what you approve. Files you don't need go to a holding folder, not the trash, and one step undoes it all.", chips: ["How much is pro?", "Is my data safe?"] },
    { re: /price|pricing|cost|how much|\$|\bpay\b|\bbuy|subscri|yearly|monthly|cheap|\bfree\b/, x: "relief", at: { pro: "#price-h" }, go: L("See pricing", "pro/#pricing"),
      say: "The desktop pet is free to keep. pro is $24 a year or $3 a month, and early supporters pay $19 for the first year. Prices are in USD.", chips: ["What does pro do?", "Can I get a refund?"] },
    { re: /\bpro\b|feature|what can (you|ro)|what does (it|pro)/, x: "find", at: { pro: "#does" }, go: L("See what pro does", "pro/#does"),
      say: "pro finds files when you ask, tidies Downloads with undo, and carries your work from one AI tool to the next. Everything happens on your Mac.", chips: ["How much is pro?", "Can I get a refund?"] },
    { re: /download|install|get (it|ro)|where.*(get|grab)|try (it|ro)|app store/, x: "find", at: { home: ".hero-actions .btn" }, go: L("Go to the download", ""),
      say: "That button is for you. I won't press it. It's a Mac app: Apple Silicon, macOS 13 or later, notarized by Apple, and it updates itself.", chips: ["Does it run on Intel?", "Is my data safe?"] },
    { re: /intel|windows|linux|iphone|android|requirement|macos|apple silicon|\bm[1-4]\b|which mac/, x: "sulk", at: { home: ".hero-actions + p" }, go: L("Back to the front page", ""),
      say: "Apple Silicon Macs with macOS 13 or later. No Intel, no Windows. I'm sorry.", chips: ["Where do I download?"] },
    { re: /offline|wi-?fi|without internet/, x: "relief", at: { pro: "#faq" }, go: L("Read the questions", "pro/#faq"),
      say: "Yes. pro runs on your Mac. I go online only to check for updates and to confirm your purchase and renewals.", chips: ["Is my data safe?"] },
    { re: /privacy|private|safe|secure|data|track|cookie|analytic|spy|upload|cloud|internet|network|local|secret/, x: "relief", at: { home: ".grid--3 .card:nth-child(2)", pro: "#trust" }, links: [L("Read the privacy page", "privacy/")],
      say: "Your files and searches stay on your Mac. This site sets no cookies, runs no analytics and talks to no other site. The only thing I remember is where I was standing, and only until you close this tab.", chips: ["Does it work offline?", "What does pro do?"] },
    { re: /refund|cancel|money back|unsubscribe|trial|guarantee/, x: "relief", at: { pro: "#faq" }, links: [L("Refund policy", "refund/")],
      say: "Yes, within 14 days. If you cancel, pro keeps working until the end of the period you paid for, plus 14 days. Your files and history stay as they are.", chips: ["How much is pro?"] },
    { re: /how many (macs|devices|computers)|multiple macs|devices|share/, x: "relief", at: { pro: "#faq" }, go: L("Read the questions", "pro/#faq"),
      say: "All the Macs you personally use. Please don't share pro with other people.", chips: ["How much is pro?"] },
    { re: /support|contact|help|email|bug|broken|didn'?t turn on|not working|order|invoice/, x: "uneasy", at: { pro: "#faq" }, go: L("Read the questions", "pro/#faq"),
      say: "If pro didn't turn on after you paid, keep ro open and online for a minute. Still free? The support address isn't live yet; it will be on the pro page under Questions.", chips: ["Can I get a refund?"] },
    { re: /who (made|built|created)|team|company|author|github|open source|release notes?|changelog/, x: "calm", links: [L("Release notes", GITHUB)],
      say: "Release notes live on GitHub.", chips: ["What are you?"] },
    { re: /\brest\b|sleep|shh+|shush|quiet|stay (here|put|still)|go away|leave me|calm down|settle|enough|freeze|be still|stop/, act: "rest", x: "sulk",
      say: "Okay. I'll sit still. Click me when you want me." },
    { re: /\b(wake|walk|wander|roam|move|come out|run around|explore|unrest|play outside)\b/, act: "wake", x: "find", say: "Back on my feet." },
    { re: /\bhome\b|go back|where do you live|house|your place/, act: "home", x: "relief", say: PAGE === "home" ? "Home is the big card at the top. It's nice there. I like to go out." : "Home is on the front page. I'll walk there if you click.", go: PAGE === "home" ? null : L("Walk me home", "") },
    { re: /dance|jump|hop|play|trick|flip|spin|wave|show me something|do something/, act: "hop", x: "find", say: "Once. I'm not a toy." },
    { re: /thank|thx|\bty\b|cheers|great|nice|cool|love|cute|awesome|good (boy|girl|ro)|best/, x: "relief", say: "Anytime. Quietly.", chips: ["What are you?", "Is it free?"] },
    { re: /^(hi|hello|hey|yo|hiya|howdy|sup)\b|good (morning|evening|afternoon)/, x: "relief", say: "Hi. I won't bother you. I'm just taking a walk. Ask me something if you like.", chips: ["What are you?", "Is it free?", "Is my data safe?"] },
    { re: /\b(bye|goodbye|see ya|see you|later|cya)\b/, act: "close", x: "relief", say: "Bye. I'll be around." },
    { re: /what (are|is) (you|ro|this)|who (are|is) (you|ro)|about (you|ro)|^ro\??$|tell me about|what do you do|what does ro do/, x: "relief", at: { home: "@home" }, go: L("Meet me on the front page", ""),
      say: "I'm ro. I live on your Mac, wander your desktop, notice what you're doing, and keep quiet. Right now I'm doing the same thing on this page.", chips: ["Is it free?", "What does pro do?"] },
    { re: /[ㄱ-힝]/, x: "relief", say: "안녕하세요. 이 사이트에서는 영어로만 말해요. 앱 안에서는 한국어로도 이야기할 수 있어요.", chips: ["What are you?"] },
  ];
  const FALLBACK = { x: "sulk", say: "I only know what's written on this site, and I'd rather not guess. Try asking about the price, privacy, or the download.", chips: ["Is it free?", "Is my data safe?", "Where do I download?"] };
  const FIRST = { say: "Ask me about this site. I only know what's written here.", chips: ["What are you?", "Is it free?", "Is my data safe?", "Where do I download?"] };

  let typing = 0;
  function say(res) {
    clearInterval(typing);
    const text = res.say || "";
    liveEl.textContent = text; chipsEl.textContent = ""; linksEl.textContent = ""; sayEl.textContent = "";
    const finish = () => {
      sayEl.textContent = text;
      (res.chips || []).forEach((c) => { const b = doc.createElement("button"); b.type = "button"; b.className = "rr-chip"; b.textContent = c; chipsEl.append(b); });
      (res.links || []).forEach((l) => { const a = doc.createElement("a"); a.href = BASE + l.href; a.textContent = l.label + (/^https:/.test(l.href) ? " ↗" : " →"); if (/^https:/.test(l.href)) { a.href = l.href; a.rel = "noopener"; } linksEl.append(a); });
    };
    if (reduced || !text) return finish();
    let i = 0;
    typing = setInterval(() => { i += 2; sayEl.textContent = text.slice(0, i); if (i >= text.length) { clearInterval(typing); finish(); } }, 16);
  }

  function respond(q) {
    const norm = q.toLowerCase().replace(/[^\p{L}\p{N}\s\/$⌥\-']/gu, " ").replace(/\s+/g, " ").trim();
    const it = INTENTS.find((i) => i.re.test(norm)) || FALLBACK;
    const res = { say: it.say, chips: it.chips, links: [...(it.links || [])] };
    const sel = it.at && it.at[PAGE];
    const target = sel === "@home" ? homeEl : sel && $(sel);
    if (it.go && !target) res.links.unshift(it.go);
    emote(it.x || "relief", 2200);
    say(res);
    if (target) showEl(sel);
    if (it.act === "rest") setRest(true);
    if (it.act === "wake") setRest(false);
    if (it.act === "home") { if (homeEl) { closePanelSoon(); goHome(); } }
    if (it.act === "hop") { if (!reduced && st === "idle") { hop(perch, tt, null, true); } }
    if (it.act === "close") closePanelSoon(1100);
  }

  function showEl(sel) {
    if (sel === "@home") { closePanelSoon(1800); return goHome(); }
    const el = $(sel);
    if (!el) return;
    const r = el.getBoundingClientRect();
    const need = r.top < H + 90 || r.top > vh * 0.62;
    if (need) scrollToEl(el, 0.46);
    setTimeout(() => {
      if (st === "drag") return;
      hop({ kind: "el", el }, el.matches("h2, .btn") ? 0.5 : 0.8);
    }, need && !reduced ? 650 : 0);
  }

  let closeT = 0;
  function closePanelSoon(ms) { clearTimeout(closeT); closeT = setTimeout(closePanel, ms || 1400); }

  function openPanel() {
    if (open) { input.focus(); return; }
    if (s > 1.6) { pendingOpen = true; leaveHome(); return; }      // from the big hero card, step out first
    open = true; panel.hidden = false; body.setAttribute("aria-expanded", "true");
    wake(false); clearTimeout(closeT);
    if (!sayEl.textContent && !liveEl.textContent) say(FIRST);
    emote("find", 900);
    input.focus({ preventScroll: true }); kick();
  }
  function closePanel() {
    if (!open) return;
    open = false; panel.hidden = true; body.setAttribute("aria-expanded", "false");
    if (panel.contains(doc.activeElement)) body.focus({ preventScroll: true });
    timer = Math.max(timer, 3); kick();
  }
  const toggle = () => (open ? closePanel() : openPanel());

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim(); if (!q) return;
    input.value = ""; clearTimeout(closeT);
    emote("record", 420);
    setTimeout(() => respond(q), reduced ? 0 : 380);
  });
  input.addEventListener("input", () => kick());
  chipsEl.addEventListener("click", (e) => { const b = e.target.closest(".rr-chip"); if (b) { input.value = ""; emote("record", 420); setTimeout(() => respond(b.textContent), reduced ? 0 : 380); } });
  linksEl.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.origin !== location.origin) return;
    e.preventDefault(); leaveTo(a.href);
  });
  restBtn.addEventListener("click", () => setRest(!rest));

  // walk off the side, then change page. The next page has ro walking in.
  function leaveTo(href) {
    closePanel();
    const sv = store.get(); sv.enter = "left"; store.set(sv);
    if (reduced) { location.href = href; return; }
    if (perch.kind !== "floor") { perch = { kind: "floor" }; tt = clamp(x / vw, 0.04, 0.96); st = "fall"; vy = 0; }
    walkTo_(1.15, 150);
    setTimeout(() => { location.href = href; }, 900);
  }

  /* ---------- rest ---------- */
  const footBtn = doc.createElement("button");
  footBtn.type = "button"; footBtn.className = "rr-toggle"; footBtn.setAttribute("aria-pressed", "false");
  function setRest(v) {
    rest = !!v; const sv = store.get(); sv.rest = rest; store.set(sv);
    restBtn.textContent = rest ? "Wake ro" : "Let ro rest";
    footBtn.textContent = rest ? "Wake ro" : "Let ro rest"; footBtn.setAttribute("aria-pressed", String(rest));
    if (rest) {
      if (homeEl && PAGE === "home") goHome(); else if (perch.kind !== "floor" || st !== "idle") hop({ kind: "floor" }, (vw - 50) / vw); else walkTo_((vw - 50) / vw, 80);
    } else { timer = 0.4; }
    kick();
  }

  /* ---------- input ---------- */
  body.addEventListener("pointerdown", (e) => {
    if (e.button) return;
    drag = { id: e.pointerId, sx: e.clientX, sy: e.clientY, moved: false };
    body.setPointerCapture(e.pointerId); wake(false);
  });
  body.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 6) {
      drag.moved = true; if (open) closePanel(); st = "drag"; hp = null; pendingOpen = false;
      if (perch.kind === "home") { away = true; stage && stage.classList.add("is-away"); }
      emote("uneasy", 99999); murmurSay("oh.");
    }
    if (drag.moved) { x = e.clientX; y = e.clientY + H * s * 0.5; kick(); }
  });
  const endDrag = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag; drag = null;
    try { body.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
    if (d.moved) {
      temp = null; tempUntil = 0;
      const c = candidates(false).filter((c) => x > c.r.left + 10 && x < c.r.right - 10 && c.r.top >= y - 10 && c.r.top - y < 700).sort((a, b) => a.r.top - b.r.top)[0];
      if (c) { perch = c.p; tt = clamp((x - c.r.left) / c.r.width, 0.04, 0.96); } else { perch = { kind: "floor" }; tt = clamp(x / vw, 0.04, 0.96); }
      st = "fall"; vy = 0; sq = -0.4; kick();
    } else if (e.type === "pointerup") toggle();
  };
  body.addEventListener("pointerup", endDrag);
  body.addEventListener("pointercancel", endDrag);
  body.addEventListener("click", (e) => { if (e.detail === 0) toggle(); });          // keyboard: Enter / Space
  body.addEventListener("pointerenter", (e) => {
    if (e.pointerType === "touch" || drag) return;
    hovering = true; wake(false);
    if (!open) { emote("find", 900); murmurSay(lastMurmur < 0 ? "hi." : "mm?"); }
    kick();
  });
  body.addEventListener("pointerleave", () => { hovering = false; kick(); });

  doc.addEventListener("pointermove", (e) => { ptr = { x: e.clientX, y: e.clientY, t: now || performance.now() / 1000 }; if (asleep) wake(); else lastActive = now; kick(); }, { passive: true });
  doc.addEventListener("keydown", (e) => {
    if (e.code === "KeyR" && e.altKey && !e.ctrlKey && !e.metaKey) { e.preventDefault(); toggle(); return; }
    if (e.key === "Escape" && open) { closePanel(); return; }
    lastActive = now;
  });
  doc.addEventListener("pointerdown", (e) => { lastActive = now; if (open && !panel.contains(e.target) && !ro.contains(e.target)) closePanel(); }, true);
  let sy = scrollY, st0 = performance.now();
  addEventListener("scroll", () => {
    const t = performance.now(), v = Math.abs(scrollY - sy) / Math.max(1, t - st0) * 1000;
    sy = scrollY; st0 = t; lastActive = now;
    if (asleep) wake(false);
    if (v > 3200 && !reduced && !drag && st === "idle" && now - lastMurmur > 12) { emote("uneasy", 800); murmurSay("whoa."); }
    kick();
  }, { passive: true });
  addEventListener("resize", () => { measure(); kick(); });
  doc.addEventListener("visibilitychange", () => { if (!doc.hidden) { lastActive = performance.now() / 1000; kick(); } });
  addEventListener("pagehide", () => { const sv = store.get(); sv.x = perch.kind === "floor" ? clamp(tt, 0.05, 0.95) : clamp(x / vw, 0.05, 0.95); store.set(sv); });
  motionQuery.addEventListener("change", () => { reduced = motionQuery.matches; footBtn.hidden = reduced; kick(); });

  /* ---------- start ---------- */
  function init() {
    measure();
    stage = $(".hero-stage");
    homeEl = stage && $(".hero-art", stage);
    if (stage && homeEl) {
      const away$ = doc.createElement("div");
      away$.className = "rr-away";
      away$.innerHTML = "<strong>ro stepped out.</strong><span>It’s somewhere on this page. " + (touchy ? "Tap it to ask something." : "Click it to ask something, or press ⌥R.") + "</span>";
      const call = doc.createElement("button"); call.type = "button"; call.textContent = "Call ro back";
      call.addEventListener("click", () => { goHome(); });
      away$.append(call); stage.append(away$);
    }
    const foot = $("footer.foot nav");
    if (foot) { footBtn.textContent = rest ? "Wake ro" : "Let ro rest"; footBtn.hidden = reduced; footBtn.addEventListener("click", () => setRest(!rest)); foot.append(footBtn); }
    restBtn.textContent = rest ? "Wake ro" : "Let ro rest";
    doc.body.append(root$);
    root.classList.add("rr-live");
    lastActive = now = performance.now() / 1000;

    const sv = store.get(), fromLink = sv.enter === "left";
    if (fromLink) { delete sv.enter; store.set(sv); }
    if (PAGE === "home" && homeEl && !fromLink) {
      perch = { kind: "home", el: homeEl }; tt = 0.5;
      const f = surf(perch, tt); x = f.x; y = f.y; s = f.s; away = false;
      if (rest || reduced) { timer = 9e9; } else timer = 2.6;
    } else {
      const to = clamp(sv.x ?? (rest ? (vw - 50) / vw : 0.82), 0.05, 0.95);
      perch = { kind: "floor" }; tt = to; if (rest || reduced) { tt = (vw - 50) / vw; }
      const f = surf(perch, tt); x = f.x; y = f.y; s = 1;
      if (PAGE === "home") { away = true; stage && stage.classList.add("is-away"); }
      if (!rest && !reduced) { tt = fromLink ? -70 / vw : (vw + 70) / vw; walkTo = to; walkSpeed = 110; dir = fromLink ? 1 : -1; st = "walk"; }
    }
    restBtn.textContent = rest ? "Wake ro" : "Let ro rest";
    kick();
  }

  window.RO_ROAM = {
    state: () => ({ st, perch: perch.kind, x: Math.round(x), y: Math.round(y), s: +s.toFixed(2), rest, open, away, feeling: feeling() }),
    open: openPanel, close: closePanel, rest: setRest, ask: (q) => { openPanel(); respond(q); },
  };
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", init); else init();
})();
