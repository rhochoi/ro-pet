/* Interactive Web Pet for site/index.html — 100% local, 0 network requests.
   Mirrors ro's 3-layer (19u / 15u / 23u) + 2-eye construction, gaze tracking,
   click squash & spring, head-rubbing stroke detector, Clay/Glass materials,
   color/size/expression switching, and prefers-reduced-motion / manual pause. */
(function () {
  const MOODS = {
    idle:      { label: "Idle",      note: "Follows your cursor, blinks, and breathes quietly." },
    focus:     { label: "Focus",     note: "Eyes narrow to a single line and notifications wait." },
    discovery: { label: "Discovery", note: "Eyes widen and head lifts when something matches." },
    resolved:  { label: "Resolved",  note: "Smiling arches after a task is done or undone." },
    anxious:   { label: "Attention", note: "Layers slip out of alignment when an item needs review." },
    recording: { label: "Recording", note: "Glances down while logging a note." },
  };
  const SIZES = { small: 0.78, medium: 1.0, big: 1.24 };
  const MATERIALS = ["clay", "glass"];
  const COLORS = ["auto", "light", "dark", "orange"];

  function createStrokeDetector() {
    const spec = { minTravelPx: 10, turns: 2, windowMs: 900 };
    let lastX = null, dir = 0, travel = 0, turns = [];
    return {
      move(x, t) {
        const dx = lastX === null ? 0 : x - lastX;
        lastX = x;
        if (dx) {
          const next = Math.sign(dx);
          if (next !== dir) {
            if (dir && travel >= spec.minTravelPx) turns.push(t);
            dir = next;
            travel = 0;
          }
          travel += Math.abs(dx);
        }
        turns = turns.filter((at) => t - at <= spec.windowMs);
        return turns.length >= spec.turns;
      },
      reset() { lastX = null; dir = 0; travel = 0; turns = []; },
    };
  }

  function initWebPet(root) {
    if (!root) return null;
    const stage = root.querySelector("#webPetStage") || root;
    const wrap = root.querySelector("#webPetWrap");
    const head = root.querySelector("#webPetHead");
    const body = root.querySelector("#webPetBody");
    const base = root.querySelector("#webPetBase");
    const eyes = root.querySelector("#webPetEyes");
    const eyeL = root.querySelector("#webPetEyeL");
    const eyeR = root.querySelector("#webPetEyeR");
    const statusEl = root.querySelector("#webPetStatus");
    const pauseBtn = root.querySelector("#webPetPauseBtn");

    const osReduced = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const state = {
      material: "clay",
      color: "auto",
      size: "medium",
      mood: "idle",
      action: null,
      paused: osReduced,
      gaze: { dx: 0, dy: 0 },
      interactions: 0,
      lastLatencyMs: 0,
    };

    let actionTimer = null;
    let strokeTimer = null;
    const stroke = createStrokeDetector();

    function syncControls() {
      root.querySelectorAll("[data-wp-mat]").forEach((btn) => {
        const on = btn.getAttribute("data-wp-mat") === state.material;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-pressed", String(on));
      });
      root.querySelectorAll("[data-wp-color]").forEach((btn) => {
        const on = btn.getAttribute("data-wp-color") === state.color;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-pressed", String(on));
      });
      root.querySelectorAll("[data-wp-size]").forEach((btn) => {
        const on = btn.getAttribute("data-wp-size") === state.size;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-pressed", String(on));
      });
      root.querySelectorAll("[data-wp-mood]").forEach((btn) => {
        const on = btn.getAttribute("data-wp-mood") === state.mood;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-pressed", String(on));
      });
      if (pauseBtn) {
        pauseBtn.setAttribute("aria-pressed", String(state.paused));
        pauseBtn.textContent = state.paused ? "Resume motion" : "Pause motion";
      }
    }

    function updateStatus(customText) {
      if (!statusEl) return;
      if (customText) {
        statusEl.textContent = customText;
        return;
      }
      const meta = MOODS[state.mood] || MOODS.idle;
      statusEl.textContent = `${meta.label} · ${state.material === "glass" ? "Glass" : "Clay"} · ${meta.note}`;
    }

    function applyClasses() {
      if (!stage || !wrap) return;
      MATERIALS.forEach((m) => stage.classList.toggle(`wp-mat-${m}`, state.material === m));
      COLORS.forEach((c) => stage.classList.toggle(`wp-color-${c}`, state.color === c));
      Object.keys(SIZES).forEach((s) => stage.classList.toggle(`wp-size-${s}`, state.size === s));
      stage.style.setProperty("--wp-scale", String(SIZES[state.size] || 1));
      stage.classList.toggle("is-paused", state.paused);
      Object.keys(MOODS).forEach((m) => wrap.classList.toggle(`wp-mood-${m}`, state.mood === m));
      wrap.classList.toggle("wp-act-press", state.action === "press");
      wrap.classList.toggle("wp-act-pet", state.action === "pet");
      wrap.setAttribute("data-mood", state.mood);
      wrap.setAttribute("data-material", state.material);
      wrap.setAttribute("data-color", state.color);
      wrap.setAttribute("data-size", state.size);
      if (state.action) wrap.setAttribute("data-action", state.action);
      else wrap.removeAttribute("data-action");
      syncControls();
    }

    function clearGaze() {
      state.gaze = { dx: 0, dy: 0 };
      if (eyes) eyes.style.transform = "";
      if (head) {
        head.style.removeProperty("--look-x");
        head.style.removeProperty("--look-y");
      }
      [head, body, base].forEach((el) => {
        if (!el) return;
        el.style.removeProperty("--gx");
        el.style.removeProperty("--gy");
      });
    }

    function setMaterial(mat) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (!MATERIALS.includes(mat)) return false;
      state.material = mat;
      state.interactions += 1;
      applyClasses();
      updateStatus();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return true;
    }

    function setColor(color) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (!COLORS.includes(color)) return false;
      state.color = color;
      state.interactions += 1;
      applyClasses();
      updateStatus();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return true;
    }

    function setSize(size) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (!Object.prototype.hasOwnProperty.call(SIZES, size)) return false;
      state.size = size;
      state.interactions += 1;
      applyClasses();
      updateStatus();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return true;
    }

    function setMood(mood) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (!Object.prototype.hasOwnProperty.call(MOODS, mood)) return false;
      state.mood = mood;
      state.action = null;
      if (actionTimer) { clearTimeout(actionTimer); actionTimer = null; }
      if (mood === "focus" || mood === "resolved" || mood === "recording") clearGaze();
      state.interactions += 1;
      applyClasses();
      updateStatus();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return true;
    }

    function triggerAction(act, durationMs) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (actionTimer) { clearTimeout(actionTimer); actionTimer = null; }
      state.action = act;
      state.interactions += 1;
      applyClasses();
      if (act === "press") {
        updateStatus("Press · 80ms squash & spring with glad eyes.");
      } else if (act === "pet") {
        updateStatus("Petting · Head leans into your hand and smiles.");
      } else {
        updateStatus();
      }
      if (act && durationMs > 0) {
        actionTimer = setTimeout(() => {
          state.action = null;
          applyClasses();
          updateStatus();
        }, durationMs);
        if (actionTimer && typeof actionTimer.unref === "function") actionTimer.unref();
      }
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return true;
    }

    function press() {
      return triggerAction("press", 820);
    }

    function feedStroke(x, nowMs) {
      const t = nowMs !== undefined ? nowMs : (typeof performance !== "undefined" ? performance.now() : Date.now());
      if (!stroke.move(x, t)) return false;
      triggerAction("pet", 0);
      if (strokeTimer) clearTimeout(strokeTimer);
      strokeTimer = setTimeout(() => {
        stroke.reset();
        if (state.action === "pet") {
          state.action = null;
          applyClasses();
          updateStatus();
        }
      }, 500);
      if (strokeTimer && typeof strokeTimer.unref === "function") strokeTimer.unref();
      return true;
    }

    function gazeAt(clientX, clientY) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (state.paused || state.action || state.mood === "focus" || state.mood === "resolved" || state.mood === "recording") {
        return false;
      }
      const rect = head && head.getBoundingClientRect ? head.getBoundingClientRect() : { left: 100, top: 100, width: 72, height: 30 };
      const cx = rect.left + (rect.width || 72) * 0.65;
      const cy = rect.top + (rect.height || 30) * 0.5;
      const dx = Math.max(-3.6, Math.min(3.6, (clientX - cx) / 28));
      const dy = Math.max(-2.0, Math.min(2.2, (clientY - cy) / 28));
      state.gaze = { dx: Number(dx.toFixed(2)), dy: Number(dy.toFixed(2)) };
      if (eyes) eyes.style.transform = `translate(${dx.toFixed(2)}px, calc(-50% + ${dy.toFixed(2)}px))`;
      if (head) {
        head.style.setProperty("--look-x", `${(dx * 0.32).toFixed(2)}px`);
        head.style.setProperty("--look-y", `${(dy * 0.32).toFixed(2)}px`);
      }
      [head, body, base].forEach((el, idx) => {
        if (!el) return;
        const factor = 1 - idx * 0.25;
        el.style.setProperty("--gx", `${(-dx * 1.4 * factor).toFixed(2)}px`);
        el.style.setProperty("--gy", `${(-dy * 1.4 * factor).toFixed(2)}px`);
      });
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return true;
    }

    function togglePause(force) {
      state.paused = typeof force === "boolean" ? force : !state.paused;
      if (state.paused) clearGaze();
      applyClasses();
      updateStatus(state.paused ? "Motion paused · Click any control to preview." : null);
      return state.paused;
    }

    // Wire DOM listeners
    root.querySelectorAll("[data-wp-mat]").forEach((btn) => {
      btn.addEventListener("click", () => setMaterial(btn.getAttribute("data-wp-mat")));
    });
    root.querySelectorAll("[data-wp-color]").forEach((btn) => {
      btn.addEventListener("click", () => setColor(btn.getAttribute("data-wp-color")));
    });
    root.querySelectorAll("[data-wp-size]").forEach((btn) => {
      btn.addEventListener("click", () => setSize(btn.getAttribute("data-wp-size")));
    });
    root.querySelectorAll("[data-wp-mood]").forEach((btn) => {
      btn.addEventListener("click", () => setMood(btn.getAttribute("data-wp-mood")));
    });
    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => togglePause());
    }
    if (wrap) {
      wrap.addEventListener("click", () => press());
      wrap.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          press();
        }
      });
    }
    if (head) {
      head.addEventListener("mousemove", (e) => {
        if (!state.paused) feedStroke(e.clientX);
      });
      head.addEventListener("mouseleave", () => stroke.reset());
    }
    if (stage) {
      stage.addEventListener("mousemove", (e) => gazeAt(e.clientX, e.clientY));
      stage.addEventListener("mouseleave", () => clearGaze());
    }

    // Periodic blink when not paused (unref in Node so unit tests exit immediately)
    if (typeof setInterval === "function") {
      const blinkTimer = setInterval(() => {
        if (state.paused || state.action || state.mood === "resolved" || state.mood === "focus") return;
        if (eyeL && eyeR) {
          eyeL.classList.add("blink");
          eyeR.classList.add("blink");
          const unblink = setTimeout(() => {
            eyeL.classList.remove("blink");
            eyeR.classList.remove("blink");
          }, 130);
          if (unblink && typeof unblink.unref === "function") unblink.unref();
        }
      }, 3800);
      if (blinkTimer && typeof blinkTimer.unref === "function") blinkTimer.unref();
    }

    applyClasses();
    updateStatus();

    return {
      state,
      setMaterial,
      setColor,
      setSize,
      setMood,
      press,
      feedStroke,
      gazeAt,
      togglePause,
    };
  }

  function boot() {
    const root = document.getElementById("web-pet-playground");
    if (root) {
      window.RoWebPet = initWebPet(root);
    }
  }

  window.initRoWebPet = initWebPet;
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
  }
})();
