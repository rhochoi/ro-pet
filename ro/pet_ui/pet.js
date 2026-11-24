const TOKEN = "__RO_TOKEN__";
// Mac 앱(WKWebView) 안인지. 맨 앞에 둔다: 아래 최상위 코드(크기 복원 등)가 선언 전에 읽으면 스크립트 전체가 멈춘다
const isNativeHost = !!(window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.roHost);
const MOOD_META = {
  idle:      { label: "Idle",      caption: "Ro, as usual." },
  recording: { label: "Recording", caption: "Looks down." },
  focus:     { label: "Focus",     caption: "Sees only one thing." },
  anxious:   { label: "Attention", caption: "Eyes shrink, layers slip." },
  discovery: { label: "Discovery", caption: "Eyes widen, head lifts." },
  resolved:  { label: "Resolved",  caption: "Smiles." },
};
const MOOD_ORDER = ["idle", "recording", "focus", "anxious", "discovery", "resolved"];

const ACTION_META = {
  press:       { label: "Press",       desc: "80 ms flatten, then spring · glad eyes (click/tap)" },
  breathe:     { label: "Breathe",     desc: "Three layers breathe out of phase (3 s loop)" },
  look_around: { label: "Look around", desc: "Eyes lead the glance" },
  walk:        { label: "Walk",        desc: "Steps forward, head first, layers following" },
  thinking:    { label: "Think",       desc: "Head tilts, off-beat pulse" },
  alert:       { label: "Startle",     desc: "Sudden hop, eyes widen" },
  drowsy:      { label: "Drowsy",      desc: "Head sinks, squinting, slow breaths" },
  gaze:        { label: "Gaze",        desc: "Eyes follow the cursor" },
  pet:         { label: "Pet",         desc: "Head presses down, leans in, smiles (rub the head)" },
  drag:        { label: "Drag",        desc: "Stretches tall, base sags" },
  shake:       { label: "Shake",       desc: "Layers sway side to side (quick shake)" },
  drop:        { label: "Land",        desc: "Landing squash and spring" },
  success:     { label: "Success",     desc: "Crouch, happy jump, smiling eyes" },
  failure:     { label: "Failure",     desc: "Layers slip, tremble, tiny eyes" },
};
const ALL_ACTIONS = Object.keys(ACTION_META);

const stage = document.getElementById("stage");
const bubble = document.getElementById("bubble");
const bubbleTop = document.getElementById("bubbleTop");
const petWrap = document.getElementById("petWrap");
const petCaption = document.getElementById("petCaption");
const closeBtn = document.getElementById("closeBtn");

const paneHome = document.getElementById("paneHome");
const paneTimeline = document.getElementById("paneTimeline");
const paneSettings = document.getElementById("paneSettings");
const paneOrganize = document.getElementById("paneOrganize");
const summaryView = document.getElementById("summaryView");
const statsView = document.getElementById("statsView");
const statsList = document.getElementById("statsList");
const statsTotal = document.getElementById("statsTotal");
const activityMoreBtn = document.getElementById("activityMoreBtn");
const timelineMore = document.getElementById("timelineMore");
const writeFiles = document.getElementById("writeFiles");
const sendCard = document.getElementById("sendCard");
const findCard = document.getElementById("findCard");
const sendHead = document.getElementById("sendHead");
const sendText = document.getElementById("sendText");

const greetingTitle = document.getElementById("greetingTitle");
const greetingSub = document.getElementById("greetingSub");
const staleBanner = document.getElementById("staleBanner");
const attentionCard = document.getElementById("attentionCard");
const attentionText = document.getElementById("attentionText");
document.getElementById("metricAttentionItem").addEventListener("click", (e) => {  // 숫자에서 바로 내용으로
  e.stopPropagation();
  const target = [attentionCard, writeCard].find(c => c && c.style.display !== "none");
  if (target) target.scrollIntoView({ block: "nearest" });
});
const filterSummaryBtn = document.getElementById("filterSummaryBtn");
const filterStatsBtn = document.getElementById("filterStatsBtn");

const metricEvents = document.getElementById("metricEvents");
const metricProjects = document.getElementById("metricProjects");
const metricAttention = document.getElementById("metricAttention");

const orgSummary = document.getElementById("orgSummary");
const orgCats = document.getElementById("orgCats");
const orgQuar = document.getElementById("orgQuar");
const orgScanBtn = document.getElementById("orgScanBtn");
const orgUndoBtn = document.getElementById("orgUndoBtn");
const orgMsg = document.getElementById("orgMsg");
let lastActKey = "";
let recallShown = false;   // 회상 답(로컬)을 보는 중에는 직전 엔진 답을 겹쳐 띄우지 않는다
const RECENT_SHOWN = 4;
let lastTlKey = "";
let orgKey = "";
let pendingKind = null;
let pendingId = null;

const writeCard = document.getElementById("writeCard");
const writeText = document.getElementById("writeText");

const logCountBadge = document.getElementById("logCountBadge");
const activityList = document.getElementById("activityList");
const timelineCountText = document.getElementById("timelineCountText");
const timelineList = document.getElementById("timelineList");

const askForm = document.getElementById("askForm");
const askInput = document.getElementById("askInput");
const askSubmit = document.getElementById("askSubmit");
const plusIcon = document.getElementById("plusIcon");
const sendIcon = document.getElementById("sendIcon");

const wanderToggle = document.getElementById("wanderToggle");

const layerHead = document.getElementById("layerHead");
const layerBody = document.getElementById("layerBody");
const layerBase = document.getElementById("layerBase");
const eyesWrap = document.getElementById("eyesWrap");
const eyeL = document.getElementById("eyeL");
const eyeR = document.getElementById("eyeR");

let currentMood = "idle";
let currentAction = null;
let actionTimer = null;
let pickedAction = null;  // Style의 모션 칩에서 직접 고른 동작
let moodFailure = false;  // 불안 표정이 건 failure 동작인지(표정이 풀리면 함께 푼다). 직접 고른 미리보기는 제 시간에 끝난다
let previewLockUntil = 0;
const INITIAL_PREFS = __RO_PREFS__;
const COLOR_CHOICES = ["auto", "light", "dark", "orange"];
const PANEL_CHOICES = ["auto", "light", "dark"];
const ORANGE = "#F3874E";
let colorMode = COLOR_CHOICES.includes(INITIAL_PREFS.color) ? INITIAL_PREFS.color : "auto";
let panelMode = PANEL_CHOICES.includes(INITIAL_PREFS.panel) ? INITIAL_PREFS.panel : "auto";
let materialMode = ["clay", "glass"].includes(INITIAL_PREFS.material) ? INITIAL_PREFS.material : "clay";
let systemDark = !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);

/* 탭 전환 */
function switchTab(tabName) {
  document.querySelectorAll(".nav-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.tab === tabName);
    t.setAttribute("aria-current", t.dataset.tab === tabName ? "page" : "false");  // 화면 읽기 프로그램에 선택 탭을 알린다
  });
  paneHome.classList.toggle("active", tabName === "home");
  paneTimeline.classList.toggle("active", tabName === "timeline");
  paneOrganize.classList.toggle("active", tabName === "organize");
  paneSettings.classList.toggle("active", tabName === "settings");
}

document.querySelectorAll(".nav-tab").forEach(tab => {
  tab.addEventListener("click", (e) => {
    e.stopPropagation();
    switchTab(tab.dataset.tab);
  });
});

if (document.body.classList.contains("edition-mini")) {
  switchTab("settings");
  const chip = (box, key, label, title, fn) => {
    const btn = h("button", { class: "opt-btn", type: "button", text: label, "aria-label": label, "aria-description": title, title,
      onclick: (e) => { e.stopPropagation(); fn(); setTimeout(syncPreviewChips); } });
    btn.dataset.preview = key;
    box.append(btn);
  };
  const moodBox = document.getElementById("moodChips"), actBox = document.getElementById("actionChips");
  /* 지금 재생 중인 표정·모션을 칩에 표시한다. 끝나는 시점이 여러 경로라 주기적으로 맞춘다 */
  const syncPreviewChips = () => {
    const previewing = Date.now() < previewLockUntil;
    const mark = (box, on) => box.querySelectorAll(".opt-btn").forEach(btn => {
      const active = on(btn.dataset.preview);
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-pressed", String(active));
    });
    mark(moodBox, m => previewing && m === currentMood);
    mark(actBox, a => a === pickedAction && a === currentAction);  // 저절로 나온 동작(두리번 등)은 칩에 켜지 않는다
  };
  setInterval(() => { if (!bubble.classList.contains("hidden")) syncPreviewChips(); }, 250);
  MOOD_ORDER.forEach(m => chip(moodBox, m, MOOD_META[m].label, MOOD_META[m].caption, () => window.setMoodPreview(m, 8000)));
  ALL_ACTIONS.filter(a => a !== "gaze").forEach(a => chip(actBox, a, ACTION_META[a].label, ACTION_META[a].desc, () => { pickedAction = a; window.triggerAction(a); }));
}

function setHomeView(stats) {
  filterSummaryBtn.classList.toggle("active", !stats);
  filterStatsBtn.classList.toggle("active", stats);
  filterSummaryBtn.setAttribute("aria-pressed", String(!stats));
  filterStatsBtn.setAttribute("aria-pressed", String(stats));
  summaryView.style.display = stats ? "none" : "flex";
  statsView.style.display = stats ? "flex" : "none";
}
filterSummaryBtn.addEventListener("click", (e) => { e.stopPropagation(); setHomeView(false); });
filterStatsBtn.addEventListener("click", (e) => { e.stopPropagation(); setHomeView(true); });
activityMoreBtn.addEventListener("click", (e) => { e.stopPropagation(); switchTab("timeline"); });

/* 재질 & 테마: 고른 것만 쓴다. 표정·모션·배경 밝기로 바꾸지 않는다.
   색상 "시스템"은 macOS 화면 모드(라이트/다크)만 따른다. */
const MATERIAL_CHOICES = ["clay", "glass"];
let dockCaption = null;  // 메뉴 막대로 끄는 중 원래 캡션 (onHostDockProgress)
function updateMaterialUI() {
  for (const m of MATERIAL_CHOICES) {
    document.body.classList.toggle(`material-${m}`, materialMode === m);
  }
  document.querySelectorAll(".mat-opt").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.mat === materialMode);
    btn.setAttribute("aria-pressed", String(btn.dataset.mat === materialMode));
  });
  updateLookUI();
  updatePetCaption();
}

function updatePetCaption() {
  const moodMeta = MOOD_META[currentMood] || MOOD_META.idle;
  if (dockCaption !== null) return;
  petCaption.textContent = currentAction ? (ACTION_META[currentAction]?.label || currentAction) : moodMeta.label;
}

/* ro 색(colorMode)은 몸통만, 상태창 색(panelMode)은 패널만 바꾼다 */
function panelIsDark() {
  return panelMode === "dark" || (panelMode === "auto" && systemDark);
}

function glassIsDark() {
  return colorMode === "dark" || (colorMode === "auto" && systemDark);
}

function updateLookUI() {
  document.querySelectorAll(".look-opt").forEach(btn => {
    const on = btn.dataset.value === colorMode;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", String(on));
  });
  document.body.classList.toggle("theme-chalk", panelIsDark());
  document.body.classList.toggle("glass-dark", glassIsDark());
  document.body.classList.toggle("color-orange", colorMode === "orange");
  notifyHost({ type: "look", color: colorMode, panel: panelMode });
  notifyHost({ type: "prefs", material: materialMode, lang: RoI18n.lang === "ko" ? "ko" : "en" });  // 메뉴의 재질 체크와 언어
  kickNativeGlass();
}

window.setLookPref = function(key, value) {
  if (key === "lang") {  // 언어는 설정(⋯ 메뉴)에서 고른다. 저장한 뒤 화면을 다시 불러 새 언어로 그린다
    if ((value !== "en" && value !== "ko") || value === RoI18n.lang) return;
    return apiPost("/api/prefs", { lang: value }).then(r => { if (r && r.ok) location.reload(); }).catch(() => {});
  }
  if (key === "color" && COLOR_CHOICES.includes(value)) colorMode = value;
  else if (key === "panel" && PANEL_CHOICES.includes(value)) panelMode = value;
  else return;
  updateLookUI();
  return savePrefs({ [key]: value });
};

/* 재질·색은 ~/.ro/config.json에 저장하고, 페이지를 만들 때 미리 넣어 깜빡이지 않게 한다 */
/* 저장이 확인되기 전에는 화면만 바뀐 상태다: 실패하면 마지막으로 저장된 값으로 되돌리고 알린다 */
const savedPrefs = {
  material: materialMode, color: colorMode, panel: panelMode,
  size: ["small", "medium", "big"].includes(INITIAL_PREFS.size) ? INITIAL_PREFS.size : "medium",
};
async function savePrefs(changes) {
  let r = null;
  try { r = await apiPost("/api/prefs", changes); } catch (err) {}
  if (r && r.ok) { Object.assign(savedPrefs, changes); return; }
  if ("material" in changes) { materialMode = savedPrefs.material; updateMaterialUI(); }
  if ("color" in changes) colorMode = savedPrefs.color;
  if ("panel" in changes) panelMode = savedPrefs.panel;
  updateLookUI();
  const why = r ? (r.error || r.output || "") : "Could not reach the server";
  showToast([h("div", { class: "toast-head", text: "Could not save the setting, so it was reverted. Please try again." }),
    why ? h("div", { class: "block-sub", text: why }) : null], 5000);
}

/* 크기: 창은 호스트가, 캐릭터는 --pet-scale이 같은 배율로 바꾼다. 상태창은 그대로다 */
const PET_SCALES = { small: 0.75, medium: 1, big: 1.3 };
let petScale = 1;
window.setPetSize = function(name) {
  const k = PET_SCALES[name];
  if (!k) return false;
  petScale = k;
  document.documentElement.style.setProperty("--pet-scale", String(k));
  document.querySelectorAll(".size-opt").forEach(btn => {
    const on = btn.dataset.size === name;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", String(on));
  });
  return true;
};
if (!isNativeHost && PET_SCALES[INITIAL_PREFS.size]) window.setPetSize(INITIAL_PREFS.size);
document.querySelectorAll(".size-opt").forEach(btn => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    /* 저장과 창 크기는 호스트 몫이다. 브라우저 모드에서는 화면만 바꾸고 저장하지 않는다 */
    if (isNativeHost) notifyHost({ type: "size", size: btn.dataset.size });
    else window.setPetSize(btn.dataset.size);
  });
});

/* 앱 반응: 새 앱이 열리거나 메일·메시지 앱이 앞에 오면 호스트가 부른다(우클릭 Preview ▸ Reactions도 같은 길).
   사용자가 만든 동작은 지키고, 저절로 도는 동작은 끊고 들어간다. 돌려주는 값으로 호스트가 쿨다운을 쓸지 정한다 */
const REACT_ICONS = {
  open: "",
  mail: '<svg viewBox="0 0 24 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><rect x="2" y="2" width="20" height="12" rx="2.5"/><path d="M3 4l9 6 9-6"/></svg>',
  message: '<svg viewBox="0 0 24 16" fill="currentColor"><circle class="dot" cx="6" cy="8" r="2"/><circle class="dot" cx="12" cy="8" r="2"/><circle class="dot" cx="18" cy="8" r="2"/></svg>',
};
const REACT_MS = { open: 900, mail: 2600, message: 2600 };
const REACT_YIELDS = ["drowsy", "look_around", "breathe", "walk", "thinking"];  // 저절로 도는 동작만 반응에 자리를 내준다
let reactTimer = null;
function clearReact() {
  clearTimeout(reactTimer);
  reactTimer = null;
  petWrap.removeAttribute("data-react");
}
window.petReact = function(kind) {
  if (!Object.prototype.hasOwnProperty.call(REACT_ICONS, kind)) return false;
  if (!bubble.classList.contains("hidden") || isPetHover || RoMotion.busy()) return false;
  if (currentAction && !REACT_YIELDS.includes(currentAction)) return false;
  if (currentAction) window.triggerAction(null);
  isDrowsy = false;                 // 졸던 펫은 깨어난다. 반응도 활동이라 곧바로 다시 졸지 않는다
  lastUserActivity = Date.now();
  clearReact();
  document.getElementById("reactBadge").innerHTML = REACT_ICONS[kind];
  void petWrap.offsetWidth;         // 같은 반응이 다시 와도 처음부터 재생
  petWrap.setAttribute("data-react", kind);
  reactTimer = setTimeout(clearReact, REACT_MS[kind]);
  kickNativeGlass();
  return true;
};
const reactToggle = document.getElementById("reactToggle");
window.setReactState = function(enabled) {
  if (reactToggle) reactToggle.checked = !!enabled;
};
if (reactToggle) reactToggle.addEventListener("change", () => {
  notifyHost({ type: "react", enabled: reactToggle.checked });
});

window.setWanderState = function(enabled) {
  if (wanderToggle) {
    wanderToggle.checked = !!enabled;
  }
};

if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    systemDark = e.matches;
    updateLookUI();
  });
}
updateMaterialUI();

function notifyHost(payload) {
  if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.roHost) {
    window.webkit.messageHandlers.roHost.postMessage(payload);
  }
}

let bubbleOpenedAt = 0;
function setBubbleOpen(open) {
  const opening = open && bubble.classList.contains("hidden");
  if (opening) bubbleOpenedAt = performance.now();
  bubble.classList.toggle("hidden", !open);
  // 다시 열면 지난번 스크롤 자리가 아니라 맨 위부터. 숨은 동안에는 scrollTop이 먹지 않아 보인 뒤에 돌린다
  if (opening) document.querySelectorAll(".tab-pane").forEach(p => { p.scrollTop = 0; });
  if (!open) {  // 패널과 함께 안의 창(연결·팔레트·결제)도 닫는다. 안 닫으면 다시 열 때 떠 있다
    for (const id of ["connWin", "palette", "proModal"]) {
      const el = document.getElementById(id);
      if (el) el.hidden = true;
    }
    if (typeof stopProPendingPoll === "function") stopProPendingPoll();
  }
  if (open && typeof refreshProPlanStatus === "function") refreshProPlanStatus();
  if (open && latestState) renderBubbleState(latestState);
  if (open && !isNativeHost) fitStage();  // 닫힌 채로 펫을 옮겼다면 다시 연 말풍선이 화면 밖으로 잘리지 않게
  notifyHost({ type: "bubble", open: !!open });
  if (window._poll !== undefined) setPollRate(open);
}

window.addEventListener("blur", () => {
  const proModalEl = document.getElementById("proModal");
  if (bubble.classList.contains("hidden") || performance.now() - bubbleOpenedAt < 300 ||
      askInput.value ||
      writeCard.style.display !== "none" || sendCard.style.display !== "none" ||
      (ambient && ambient.focus) || !palette.hidden || (proModalEl && !proModalEl.hidden)) return;
  setBubbleOpen(false);
});

window.toggleBubbleFromHost = function(forceOpen) {
  const isHidden = bubble.classList.contains("hidden");
  setBubbleOpen(forceOpen !== undefined ? forceOpen : isHidden);
};

/* 누를 수 있는 자리(몸통, 열린 상태창)를 호스트에 알린다. 호스트는 그 밖의 투명 여백에서 클릭을 아래 앱으로 흘려보낸다 */
let hitQueued = false;
function reportHit() {
  if (!isNativeHost || hitQueued) return;
  hitQueued = true;
  requestAnimationFrame(() => {
    hitQueued = false;
    const pad = 10;  // 숨쉬기·점프로 몇 px 움직여도 벗어나지 않게
    const rects = [document.getElementById("roBot").getBoundingClientRect()];
    if (!bubble.classList.contains("hidden")) rects.push(bubble.getBoundingClientRect());
    notifyHost({ type: "hit", rects: rects.filter(r => r.width && r.height)
      .map(r => [r.left - pad, r.top - pad, r.width + pad * 2, r.height + pad * 2].map(Math.round)) });
  });
}
window.setBubblePlacement = function(isTop, isLeft) {
  document.body.classList.toggle("place-top", !!isTop);
  document.body.classList.toggle("place-left", !!isLeft);
  reportHit();
};

/* 6가지 표정 프리뷰 */
function setMoodClass(mood) {
  const before = petWrap.className;
  for (const m of MOOD_ORDER) petWrap.classList.toggle(`mood-${m}`, m === mood);
  if (petWrap.className !== before) kickNativeGlass();
}

window.setMoodPreview = function(mood, durationMs) {
  const meta = MOOD_META[mood];
  if (!meta) return;
  previewLockUntil = Date.now() + (durationMs || 8000);
  currentMood = mood;
  eyesWrap.style.transform = "";
  setMoodClass(mood);
  updateMaterialUI();
};

function cycleMoodPreview() {
  const idx = (MOOD_ORDER.indexOf(currentMood) + 1) % MOOD_ORDER.length;
  window.setMoodPreview(MOOD_ORDER[idx], 8000);
}

/* 키보드: 펫과 '확인할 일' 숫자도 Enter·Space로 누를 수 있다 */
petWrap.addEventListener("keydown", (e) => {
  if (e.target !== petWrap || (e.key !== "Enter" && e.key !== " ")) return;
  e.preventDefault();
  setBubbleOpen(bubble.classList.contains("hidden"));
});
document.getElementById("metricAttentionItem").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  e.preventDefault();
  e.currentTarget.click();
});
petWrap.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  if (isNativeHost) notifyHost({ type: "menu" });  // 네이티브 메뉴(표정 미리보기 포함)
  else cycleMoodPreview();
});

stage.addEventListener("mousedown", (e) => {
  if (e.target === stage && !bubble.classList.contains("hidden")) {
    setBubbleOpen(false);
  }
});

/* ⋯: 네이티브 메뉴(데스크톱에 꺼내기 포함). 브라우저에는 호스트가 없어 숨긴다 */
const moreBtn = document.getElementById("moreBtn");
if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.roHost) moreBtn.style.display = "";
moreBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  notifyHost({ type: "menu" });
});

closeBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  setBubbleOpen(false);
});

/* 설정 탭 핸들러 */
document.querySelectorAll(".mat-opt").forEach(btn => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    materialMode = btn.dataset.mat;
    updateMaterialUI();
    savePrefs({ material: materialMode });
  });
});

document.querySelectorAll(".look-opt").forEach(btn => {
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    window.setLookPref(btn.dataset.key, btn.dataset.value);
  });
});

wanderToggle.addEventListener("change", (e) => {
  notifyHost({ type: "toggleWander", enabled: wanderToggle.checked });
});

window.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (typeof proModal !== "undefined" && proModal && !proModal.hidden) { closeProModal(); return; }
  if (!connWin.hidden) { closeConn(); return; }  // 연결 창 안에 포커스가 없어도 Esc는 창부터 닫는다
  if (document.activeElement === askInput && askInput.value) {
    askInput.value = "";  // 입력 중 Esc는 입력만 지우고 창은 둔다
    return;
  }
  setBubbleOpen(false);
});

const MOTION_DEMOS = ["press", "drag", "shake", "drop"];
/* 반복 모션은 한 주기의 배수로 끝나야 중간 자세에서 끊기지 않고, 한 번짜리는 끝나면 바로 돌아온다 */
const ACTION_MS = { breathe: 6000, look_around: 3000, walk: 3900, thinking: 3200, alert: 1100, drowsy: 4800,
                    pet: 2400, success: 1500, failure: 1500 };

/* 모션 상호작용 컨트롤러 */
window.triggerAction = function(name, durationMs) {
  kickNativeGlass();
  moodFailure = false;
  if (actionTimer) {
    clearTimeout(actionTimer);
    actionTimer = null;
  }
  eyesWrap.style.transform = "";
  clearHeadGaze();
  petWrap.style.removeProperty("--walk-dir");   // 돌아다니기 걸음의 방향·박자는 그 걸음에만 쓴다
  petWrap.style.removeProperty("--walk-step");
  walkLean(0, 0);

  for (const act of ALL_ACTIONS) {
    petWrap.classList.remove(`action-${act.replace(/_/g, "-")}`);
  }
  currentAction = name;
  if (name) clearReact();  // 동작이 반응을 끊는다(.ro-bot 애니메이션을 두고 다투지 않게)

  if (!name) {
    currentAction = null;
    const meta = MOOD_META[currentMood] || MOOD_META.idle;
    petCaption.textContent = meta.label;
    return { ok: true, cleared: true };
  }

  if (MOTION_DEMOS.includes(name)) {                  // 누름·잡기·흔들기·놓기는 모션 엔진이 재생한다
    const meta = ACTION_META[name];
    if (meta) petCaption.textContent = meta.label;
    if (RoMotion.busy()) { RoMotion.reset(); RoMotion.clearStyles(); }  // 새로 고른 동작이 앞선 동작을 끊는다
    RoMotion.demo(name);
    return { ok: true, action: name, duration: 0 };
  }
  const cls = `action-${name.replace(/_/g, "-")}`;
  petWrap.classList.add(cls);

  const meta = ACTION_META[name];
  if (meta) petCaption.textContent = meta.label;

  const dur = (durationMs !== undefined) ? durationMs : (ACTION_MS[name] || 4500);
  if (name === "walk") walkLean(2, dur);
  if (dur > 0) {
    actionTimer = setTimeout(() => {
      window.triggerAction(null);
    }, dur);
  }
  return { ok: true, action: name, duration: dur };
};

/* 걷는 쪽으로 기울기: 사이트처럼 출발하며 기울고 서기 직전에 바로 선다(.ro-bot 인라인 transform). deg 0이면 바로 푼다 */
var leanTimer = null;  // var: triggerAction이 이 줄보다 먼저 불려도 된다
function walkLean(deg, ms) {
  clearTimeout(leanTimer);
  const dir = petWrap.style.getPropertyValue("--walk-dir") === "-1" ? -1 : 1;
  if (!deg) { roBot.style.transition = ""; roBot.style.transform = ""; return; }
  roBot.style.transformOrigin = "50% 100%";
  roBot.style.transition = "transform 0.3s cubic-bezier(.22, 1, .36, 1)";
  roBot.style.transform = `skewX(${(-deg * dir).toFixed(2)}deg)`;
  if (ms > 0) leanTimer = setTimeout(() => { roBot.style.transform = ""; }, Math.max(0, ms - 300));
}

/* 돌아다니기: 호스트가 창을 dir 쪽으로 옮기는 ms 동안, 그 속도에 맞춘 박자(stepMs)로 걷고 leanDeg만큼 기운다.
   말풍선·호버·잡기·반응 중이거나 사용자가 만든 동작·졸음 중이면 걷지 않고 false(호스트도 창을 옮기지 않는다) */
const WANDER_YIELDS = ["look_around", "breathe", "walk", "thinking"];
window.wanderStep = function(dir, ms, stepMs, leanDeg) {
  if (!bubble.classList.contains("hidden") || isPetHover || RoMotion.busy() || petWrap.hasAttribute("data-react")) return false;
  if (currentAction && !WANDER_YIELDS.includes(currentAction)) return false;
  window.triggerAction("walk", ms);
  petWrap.style.setProperty("--walk-dir", dir < 0 ? "-1" : "1");
  petWrap.style.setProperty("--walk-step", (stepMs || 390) + "ms");
  walkLean(leanDeg || 2, ms);
  return true;
};
window.wanderStop = function() { if (currentAction === "walk") window.triggerAction(null); };

/* 호스트 드래그 브리지 */
window.onHostDragStart = function(fromPet) {};   /* 누름은 JS mousedown이 시작한다 */
window.onHostDragMove = function(x, y) { RoMotion.move(x, y, performance.now(), true); };
window.onHostDragShake = function() {};          /* 흔들기 감지는 모션 엔진이 속도에서 직접 한다 */
window.onHostDragEnd = function(moved, fallPx) { RoMotion.up(performance.now(), !!moved, fallPx || 0); };
/* 메뉴 막대로 보내기: 위쪽 80px 구역 안에서의 진행률(0~1)을 호스트가 넘긴다 */
window.onHostDockProgress = function(p) {
  petWrap.style.setProperty("--dock", p);
  petWrap.classList.toggle("docking", p > 0);
  if (p > 0 && dockCaption === null) {
    dockCaption = petCaption.textContent;
    petCaption.textContent = "Release to menu bar";
  } else if (p === 0 && dockCaption !== null) {
    petCaption.textContent = dockCaption;
    dockCaption = null;
  }
};

/* 메뉴 막대로 들어가면 호스트가 onHostDragEnd 대신 이걸 부른다. 잡힌 자세를 풀어 다음에 꺼낼 때 깨끗하게 */
window.onHostDocked = function() {
  window.onHostDockProgress(0);
  RoMotion.reset();
  RoMotion.clearStyles();
  window.triggerAction(null);
};

/* 쓰다듬기: 머리 위에서 손을 좌우로 움직여야 한다. 올려 두거나 한 번 지나가는 것은 세지 않는다 */
const STROKE = { minTravelPx: 10, turns: 2, windowMs: 900, idleMs: 450 };
function createStrokeDetector(spec = STROKE) {
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
      turns = turns.filter(at => t - at <= spec.windowMs);
      return turns.length >= spec.turns;
    },
    reset() { lastX = null; dir = 0; travel = 0; turns = []; },
  };
}

/* 쓰다듬기 연결 */
let isPetHover = false;
let strokeIdle = null;
const strokeDetector = createStrokeDetector();
function endStroke() {
  clearTimeout(strokeIdle);
  strokeDetector.reset();
  if (!isPetHover) return;
  isPetHover = false;
  if (currentAction === "pet") window.triggerAction(null);
}
function feedStroke(x) {
  if (RoMotion.busy() || !strokeDetector.move(x, performance.now())) return;
  if (!isPetHover) {
    if (currentAction) return;
    isPetHover = true;
    window.triggerAction("pet", 0);
  }
  clearTimeout(strokeIdle);
  strokeIdle = setTimeout(endStroke, STROKE.idleMs);
}
layerHead.addEventListener("mousemove", (e) => {
  if (!isNativeHost && !e.buttons) feedStroke(e.clientX);
});
layerHead.addEventListener("mouseleave", endStroke);

/* 마우스 시선 추적 */
window.addEventListener("mousemove", (e) => followPointer(e.clientX, e.clientY));
function clearHeadGaze() {
  layerHead.style.removeProperty("--look-x");
  layerHead.style.removeProperty("--look-y");
  delete petWrap.dataset.gaze;
}
function followPointer(x, y) {
  recordActivity();
  if (currentMood === "resolved" || currentMood === "recording" || currentMood === "focus") {
    eyesWrap.style.transform = "";
    clearHeadGaze();
    kickNativeGlass();
    return;
  }
  if (isPetHover || currentAction || RoMotion.busy()) return;
  const rect = layerHead.getBoundingClientRect();
  const cx = rect.left + rect.width * 0.68;
  const cy = rect.top + rect.height * 0.5;
  const dx = Math.max(-3.0, Math.min(3.0, (x - cx) / 32));
  const dy = Math.max(-1.8, Math.min(2.0, (y - cy) / 32));
  petWrap.dataset.gaze = "active";
  eyesWrap.style.transform = `translate(${dx}px, calc(-50% + ${dy}px))`;
  layerHead.style.setProperty("--look-x", `${dx * 0.28}px`);
  layerHead.style.setProperty("--look-y", `${dy * 0.28}px`);
  kickNativeGlass();
}

/* 다른 앱이 앞에 있으면 웹 화면에 마우스 이동이 오지 않는다. 호스트가 창 안의 좌표를 직접 넘긴다 */
window.onHostPointer = function(x, y) {
  if (x === null) { endStroke(); return; }
  followPointer(x, y);
  const r = layerHead.getBoundingClientRect();
  if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) feedStroke(x);
  else endStroke();
};

/* 눈 깜빡임 */
setInterval(() => {
  if (currentMood === "resolved" || currentMood === "focus" || currentAction === "pet" || currentAction === "drowsy") return;
  eyeL.classList.add("blink");
  eyeR.classList.add("blink");
  setTimeout(() => {
    eyeL.classList.remove("blink");
    eyeR.classList.remove("blink");
  }, 130);
}, 3800);

/* 졸음 및 활동 감지 */
let lastUserActivity = Date.now();
let isDrowsy = false;
function recordActivity() {
  lastUserActivity = Date.now();
  if (isDrowsy) wakeUpFromSleep();
}
window.addEventListener("keydown", recordActivity);
window.addEventListener("mousedown", recordActivity);

function wakeUpFromSleep() {
  isDrowsy = false;
  window.triggerAction("alert");
}

setInterval(() => {
  if (isPetHover || currentAction || currentMood !== "idle" || petWrap.hasAttribute("data-react")) return;
  if (!bubble.classList.contains("hidden")) return;
  if (!isDrowsy && (Date.now() - lastUserActivity > 75000)) {
    isDrowsy = true;
    window.triggerAction("drowsy", 0);
  }
}, 4000);

setInterval(() => {
  if (isDrowsy || isPetHover || currentAction || RoMotion.busy() || currentMood !== "idle" || petWrap.hasAttribute("data-react")) return;
  if (Math.random() < 0.40) {
    window.triggerAction("look_around");
  }
}, 16000);

/* 드래그 */
/* 네이티브 유리(Mac 앱): 몸통 세 층 아래에 층마다 시스템 유리를 하나씩 깐다. macOS 26 이상은 굴절하는 유리("liquid"),
   그보다 낮으면 뒤 화면을 실제로 흐리는 유리("blur") — 어느 쪽인지는 Mac 앱이 setNativeGlass로 알려 준다.
   웹 화면은 층마다 자리·기울기·불투명도를 알려 주고, Mac 앱은 유리를 그대로 옮기고 돌린다.
   들거나 흔들 때만 매 프레임, CSS 움직임은 100ms 타이머로 확인해 대기 중 매 프레임 깨어나지 않는다.
   0.5초간 정지하면 1초마다 확인한다. 호스트 사본 숨쉬기 실험(사용자 측정): WebContent 4.9~7.8% → 2.2~2.6%.
   updateMaterialUI가 이 선언보다 먼저 불리므로 var로 둔다(let이면 선언 전 접근 오류). */
var nativeGlassKind = "";
var nativeGlassSent;
var nativeGlassFrame;
var nativeGlassTimer;
var nativeGlassActiveAt;
var nativeGlassPoseAt = -Infinity;
window.setNativeGlass = function(kind) {
  nativeGlassKind = (kind === "liquid" || kind === "blur") ? kind : "";
  nativeGlassSent = "";
  kickNativeGlass();
};
function kickNativeGlass() {
  clearTimeout(nativeGlassTimer);
  nativeGlassTimer = null;
  nativeGlassActiveAt = performance.now();
  nativeGlassPoseAt = -Infinity;
  if (!nativeGlassKind || materialMode !== "glass") {
    cancelAnimationFrame(nativeGlassFrame);
    syncNativeGlass();
  } else if (nativeGlassFrame == null) {
    nativeGlassFrame = requestAnimationFrame(syncNativeGlass);
  }
}
for (const event of ["animationstart", "transitionrun"]) {
  document.addEventListener(event, e => { if (petWrap.contains(e.target)) kickNativeGlass(); }, true);
}
window.addEventListener("resize", kickNativeGlass);
/* 층 하나의 [x, y, 너비, 높이, 기울기(도, 시계 방향), 불투명도]. x·y·너비·높이는 돌리기 전 상자.
   돌린 사각형의 테두리 상자 중심은 원래 중심과 같으므로 중심은 getBoundingClientRect에서, 크기는 레이아웃 크기 × 배율로 구한다.
   층 자신과 조상의 transform(숨쉬기·두리번 등 CSS 애니메이션)과 rotate·scale(모션 엔진)을 모두 합친다. */
function glassPose(el, moving) {
  let rot = 0, sx = 1, sy = 1, op = 1;
  for (let n = el; n && n !== document.body; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.transform && cs.transform !== "none") {
      const m = new DOMMatrixReadOnly(cs.transform);
      rot += Math.atan2(m.b, m.a) * 180 / Math.PI;
      sx *= Math.hypot(m.a, m.b);
      sy *= Math.hypot(m.c, m.d);
    }
    if (cs.rotate && cs.rotate !== "none") rot += parseFloat(cs.rotate) || 0;
    if (cs.scale && cs.scale !== "none") {
      const [a, b = a] = cs.scale.split(" ").map(parseFloat);
      sx *= a || 1; sy *= b || 1;
    }
    op *= parseFloat(cs.opacity);
  }
  const r = el.getBoundingClientRect();
  const w = el.offsetWidth * sx, h = el.offsetHeight * sy;
  const q = (v, k) => Math.round(v * k) / k;
  const k = moving ? 4 : 2;
  return [q(r.left + r.width / 2 - w / 2, k), q(r.top + r.height / 2 - h / 2, k), q(w, k), q(h, k), q(rot, 10), q(op, 50)];
}
function setNativeGlassClass(on) {
  for (const k of ["liquid", "blur"]) document.body.classList.toggle(`native-glass-${k}`, on && nativeGlassKind === k);
}
function syncNativeGlass(now = performance.now()) {
  nativeGlassFrame = null;
  nativeGlassTimer = null;
  if (!nativeGlassKind || materialMode !== "glass") {
    setNativeGlassClass(false);
    if (nativeGlassSent !== "off") { nativeGlassSent = "off"; notifyHost({ type: "glass", on: false }); }
    return;
  }
  const moving = typeof RoMotion !== "undefined" && RoMotion.busy();
  // 정지 판정 직전에는 간격 제한 없이 마지막 위치까지 확인한다.
  if (!moving && now - nativeGlassPoseAt < 100 && now - nativeGlassActiveAt < 500) {
    nativeGlassTimer = setTimeout(syncNativeGlass, 100 - (now - nativeGlassPoseAt));
    return;
  }
  nativeGlassPoseAt = now;
  let rects = [layerHead, layerBody, layerBase].map(el => glassPose(el, moving));
  if (!rects.every(r => r[2] >= 1 && r[3] >= 1 && r[5] > 0.02)) rects = null;  // 숨은 펫
  setNativeGlassClass(!!rects);
  const dark = glassIsDark();
  const tint = colorMode === "orange" ? ORANGE : null;
  const key = rects ? JSON.stringify(rects) + dark + (tint || "") : "off";
  const changed = key !== nativeGlassSent;
  if (changed) {
    nativeGlassSent = key;
    notifyHost(rects ? { type: "glass", on: true, rects, dark, ...(tint ? { tint } : {}) } : { type: "glass", on: false });
  }
  const animating = document.getAnimations().some(a => a.playState === "running" && petWrap.contains(a.effect?.target));
  if (moving || animating || changed) nativeGlassActiveAt = now;
  if (moving) {
    nativeGlassFrame = requestAnimationFrame(syncNativeGlass);
  } else if (now - nativeGlassActiveAt < 500) {
    nativeGlassTimer = setTimeout(syncNativeGlass, 100);
  } else {
    nativeGlassTimer = setTimeout(syncNativeGlass, 1000);
  }
}
let webDragStart = null;
let webDidDrag = false;
let webLastX = 0;
let webLastDxSign = 0;
let webShakeCount = 0;
let webLastReversal = 0;

/* 브라우저 모드: 창을 옮길 수 없으니 펫과 말풍선을 페이지 안에서 옮긴다(둘 다 화면 밖으로 나가지 않게) */
let stageX = 0;
let stageY = 0;
function moveStageBy(dx, dy) {
  const prev = [stageX, stageY];
  stageX += dx;
  stageY += dy;
  stage.style.transform = `translate(${stageX}px, ${stageY}px)`;
  const rects = [petWrap, bubble].filter((el) => !el.classList.contains("hidden")).map((el) => el.getBoundingClientRect());
  if (rects.some((r) => r.left < 0 || r.top < 0 || r.right > window.innerWidth || r.bottom > window.innerHeight)) {
    [stageX, stageY] = prev;
    stage.style.transform = `translate(${stageX}px, ${stageY}px)`;
  }
}

/* 펫과 (열려 있으면) 말풍선이 모두 창 안에 들어오도록 무대를 당긴다 */
function fitStage() {
  const rects = [petWrap, bubble].filter((el) => !el.classList.contains("hidden")).map((el) => el.getBoundingClientRect());
  if (!rects.length) return;
  const left = Math.min(...rects.map(r => r.left)), right = Math.max(...rects.map(r => r.right));
  const top = Math.min(...rects.map(r => r.top)), bottom = Math.max(...rects.map(r => r.bottom));
  let dx = 0, dy = 0;
  if (left < 0) dx = -left; else if (right > window.innerWidth) dx = Math.max(-left, window.innerWidth - right);
  if (top < 0) dy = -top; else if (bottom > window.innerHeight) dy = Math.max(-top, window.innerHeight - bottom);
  if (dx || dy) {
    stageX += dx;
    stageY += dy;
    stage.style.transform = `translate(${stageX}px, ${stageY}px)`;
  }
}

// 브라우저 창을 줄이거나 늘려도 옮겨 둔 펫·말풍선이 화면 밖으로 나가지 않게
window.addEventListener("resize", () => { if (!isNativeHost) fitStage(); });

function beginDrag(e, fromPet) {
  if (e.button !== 0) return;
  if (e.target.closest("button") || e.target.closest("input")) return;
  if (fromPet) {
    endStroke();   // 쓰다듬기와 겹치지 않게
    Lid.reset();
    RoMotion.down(performance.now());
  }
  if (isNativeHost) {
    notifyHost({ type: "dragStart", fromPet: !!fromPet });
    return;
  }
  webDragStart = { x: e.screenX, y: e.screenY };
  webLastX = e.screenX;
  webDidDrag = false;
  webShakeCount = 0;
}

petWrap.addEventListener("mousedown", (e) => { clearReact(); beginDrag(e, true); });
bubbleTop.addEventListener("mousedown", (e) => beginDrag(e, false));

window.addEventListener("mousemove", (e) => {
  if (isNativeHost || !webDragStart) return;
  RoMotion.move(e.screenX, e.screenY, performance.now());
  const dx = e.screenX - webDragStart.x;
  const dy = e.screenY - webDragStart.y;
  if (Math.abs(dx) > 7 || Math.abs(dy) > 7) {
    webDidDrag = true;
    webDragStart = { x: e.screenX, y: e.screenY };
    if (isNativeHost) notifyHost({ type: "moveBy", dx, dy });
    else moveStageBy(dx, dy);
  }
});

window.addEventListener("mouseup", () => {
  if (!isNativeHost && webDragStart) RoMotion.up(performance.now(), webDidDrag, 0);
  webDragStart = null;
});

petWrap.addEventListener("click", () => {
  if (isNativeHost || webDidDrag || !RoMotion.consumeClick()) return;
  if (isDrowsy) wakeUpFromSleep();
  setBubbleOpen(bubble.classList.contains("hidden"));
});

window.onPetClickFromHost = function() {
  if (!RoMotion.consumeClick()) return;
  if (isDrowsy) wakeUpFromSleep();
  setBubbleOpen(bubble.classList.contains("hidden"));
};

/* 403(토큰 만료·서버 재시작)은 결과가 아니라 연결 문제다: 빈 결과로 그리지 않도록 예외로 올린다 */
async function apiPost(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Ro-Token": TOKEN },
    body: JSON.stringify(body || {}),
  });
  if (res.status === 401 || res.status === 403) {
    markStale("Please reopen the pet (the server may have restarted).");
    throw new Error("auth");
  }
  let data;
  try { data = await res.json(); } catch (e) { data = { ok: false, error: `Could not read the response (${res.status})` }; }
  if (!res.ok && data.ok === undefined) data.ok = false;
  return data;
}

/* 메뉴 막대의 라이선스 창(네이티브)이 부른다: 키는 서버로만 보내고 화면·로그에 남기지 않는다 */
window.licenseFromHost = async function(body) {
  try { return await apiPost("/api/license", body || {}); }
  catch (e) { return { ok: false, error: "auth" }; }
};

/* 입력 필드 상태에 따른 '+' 아이콘 / 전송 아이콘 전환 */
askInput.addEventListener("input", () => {
  const hasText = askInput.value.trim().length > 0;
  plusIcon.style.display = hasText ? "none" : "block";
  sendIcon.style.display = hasText ? "block" : "none";
});

/* 상태 렌더링 */
let lastHostStatus = "";
let latestState = null;
function applyState(st) {
  latestState = st;
  if (st.pro) applyPro(st.pro, st.hint);
  // 메뉴 막대 메뉴 첫 줄용. 바뀔 때만 보낸다
  const hostStatus = { type: "status", today: (st.counts && st.counts.today_records) || 0 };
  if (JSON.stringify(hostStatus) !== lastHostStatus) {
    lastHostStatus = JSON.stringify(hostStatus);
    notifyHost(hostStatus);
  }
  const locked = Date.now() < previewLockUntil;
  if (!locked) {
    currentMood = st.mood;
    if (currentMood === "recording" || currentMood === "resolved" || currentMood === "focus") {
      eyesWrap.style.transform = "";
    }
    setMoodClass(st.mood);  // 다른 클래스(끌기·집중·메뉴 막대로 보내기 등)는 건드리지 않는다

    updatePetCaption();

    // 불안이 풀렸으면 불안이 건 failure도 푼다. 안 풀면 평소 표정에서도 층이 어긋난 채 남고 성공 동작이 막힌다
    if (moodFailure && st.mood !== "anxious" && currentAction === "failure") window.triggerAction(null);

    if (RoMotion.busy()) {
      // 잡고 흔드는 중에는 상태 폴링이 다른 동작을 끼워 넣지 않는다(모션이 끊기지 않게)
    } else if (st.action && st.action !== currentAction) {
      window.triggerAction(st.action, 4500);
    } else if (!currentAction) {
      if (st.mood === "resolved") {
        window.triggerAction("success", 4000);
      } else if (st.mood === "anxious") {
        window.triggerAction("failure", 0);
        moodFailure = true;
      }
    }
  }

  applyAmbient(st);
  if (!bubble.classList.contains("hidden")) renderBubbleState(st);
}

function renderBubbleState(st) {
  if (st.ambient) {
    focusBtn.setAttribute("aria-pressed", st.ambient.focus ? "true" : "false");
    focusBtn.textContent = st.ambient.focus ? "Turn off focus mode" : "Turn on focus mode";
    focusBtn.classList.toggle("active", !!st.ambient.focus);
  }
  const counts = st.counts || {};
  const logs = st.recent_logs || [];          // 사용자 기록만 (펫 시작·스캔·질문 제외)
  const tl = st.timeline || [];               // 오늘 일어난 모든 일
  const recordCount = counts.today_records || 0;
  const eventCount = counts.today_events || 0;
  const lastTs = logs.length ? (logs[logs.length - 1].ts || "").slice(0, 5) : "";
  const attention = (counts.audit_findings || 0) + (st.write_pending ? 1 : 0);

  // 1. 브리핑
  const health = st.health === "attention" ? "확인할 일이 있어요" : "정상 동작 중";
  if (recordCount > 0) {
    greetingTitle.textContent = `오늘 ${recordCount}건 기록했어요.`;
    greetingSub.textContent = lastTs ? `마지막 기록 ${lastTs} · ${health}` : health;
  } else {
    greetingTitle.textContent = "오늘 새로 시작했어요.";
    greetingSub.textContent = st.health === "attention" ? health : "기록이 시작되면 여기에 요약이 표시됩니다";
  }

  // 2. 메트릭
  metricEvents.textContent = recordCount;
  metricProjects.textContent = counts.projects || 0;
  metricAttention.textContent = attention;

  // 확인할 일: 무엇이 문제이고 무엇을 하면 되는지(같은 내용이면 다시 그리지 않음)
  const attKey = JSON.stringify(st.attention_items || []);
  if (attentionCard.dataset.key !== attKey) {
    attentionCard.dataset.key = attKey;
    const items = st.attention_items || [];
    attentionCard.style.display = items.length ? "flex" : "none";
    attentionText.replaceChildren(...items.map(a => h("div", {},
      h("div", { text: `· ${a.what}` }), h("div", { class: "block-sub" }, "다음: ", h("code", { text: a.do })))));
  }

  renderOrganize(st.organize);
  const wasPending = pendingKind;
  pendingKind = st.write_pending ? (st.write_pending.kind || "write") : null;
  pendingId = st.write_pending ? st.write_pending.id : null;  // 승인은 지금 보이는 이 요청에만 적용된다

  if (st.write_pending) {
    const wp = st.write_pending;
    const appeared = writeCard.style.display === "none";
    writeCard.style.display = "flex";
    if (appeared) writeCard.focus({ preventScroll: true });  // 키보드·화면 읽기 사용자가 카드가 뜬 줄 알게. 승인·취소 어느 쪽도 미리 고르지 않는다
    writeText.textContent = wp.kind && wp.kind.startsWith("organize") ? wp.task : `${wp.engine}: ${wp.task}`;
    const files = wp.files || [];
    const fkey = JSON.stringify(files);
    if (writeFiles.dataset.key !== fkey) {
      writeFiles.dataset.key = fkey;
      writeFiles.replaceChildren(...files.map(f => h("li", { title: f.to ? `${f.from} → ${f.to}` : f.from },
        h("span", { text: f.from }), f.to ? h("span", { class: "arrow", text: "→" }) : null, f.to ? h("span", { text: f.to }) : null)));
      if (wp.more) writeFiles.append(h("li", {}, h("span", { class: "arrow", text: `외 ${wp.more}건` })));
    }
    writeFiles.style.display = files.length ? "block" : "none";
    if (!wasPending) { hideToast(); writeCard.scrollIntoView({ block: "nearest" }); }  // 새 승인 요청이 가려지지 않게
  } else {
    writeCard.style.display = "none";
  }

  // 4. 최근 기록 (홈): 배지는 오늘 기록 수, 목록은 최근 4개 + 전체 보기
  logCountBadge.textContent = `${recordCount}건`;
  const shown = logs.slice().reverse().slice(0, RECENT_SHOWN);
  const actKey = JSON.stringify([recordCount, shown]);
  if (actKey !== lastActKey) {  // 450ms 폴링마다 같은 내용으로 DOM을 다시 만들지 않는다
    lastActKey = actKey;
    activityList.replaceChildren();
    if (shown.length === 0) {
      activityList.append(h("div", { class: "stats-empty", text: "오늘 아직 기록이 없습니다." }));
    } else {
      shown.forEach((item) => {
        activityList.append(h("div", { class: "activity-card" },
          h("span", { class: "act-dot" }),
          h("span", { class: "act-summary", text: item.summary, title: `${item.kind_label} · ${item.summary}` }),
          h("span", { class: "act-time", text: (item.ts || "").slice(0, 5) })));
      });
    }
    activityMoreBtn.style.display = recordCount > shown.length ? "inline-block" : "none";
    activityMoreBtn.textContent = `타임라인에서 전체 보기 (${recordCount}건)`;
  }

  // 5. 통계 (홈의 통계 보기): 오늘 일어난 일을 종류별로
  const stats = st.stats || [];
  statsTotal.textContent = `${eventCount}건`;
  const stKey = JSON.stringify(stats);
  if (statsList.dataset.key !== stKey) {
    statsList.dataset.key = stKey;
    const max = Math.max(1, ...stats.map(x => x[1]));
    statsList.replaceChildren(...(stats.length ? stats.map(([label, n]) => h("div", { class: "stats-row" },
      h("span", { text: label }), h("span", { class: "bar", style: `width:${Math.round(n / max * 100)}%` }),
      h("span", { class: "n", text: n })))
      : [h("div", { class: "stats-empty", text: "오늘 아직 아무 일도 없었어요." })]));
  }

  // 6. 타임라인 (오늘 일어난 모든 일)
  timelineCountText.textContent = `${eventCount}건`;
  const tlKey = JSON.stringify([eventCount, tl]);
  if (tlKey !== lastTlKey) {
    lastTlKey = tlKey;
    timelineList.replaceChildren();
    if (tl.length === 0) {
      timelineList.append(h("div", { class: "stats-empty", text: "기록된 내역이 없습니다." }));
    } else {
      tl.slice().reverse().forEach((item, idx) => {
        const row = h("div", { class: "timeline-row", "data-id": item.id || "" },
          h("span", { class: "step-badge", text: String(eventCount - idx).padStart(2, "0") }),
          h("div", { class: "timeline-body" },
            h("div", { class: "timeline-meta" },
              h("span", { class: "timeline-tag", text: item.kind_label }),
              h("span", { class: "timeline-time", text: (item.ts || "").slice(0, 5) })),
            h("div", { class: "timeline-text", text: item.summary }),
            item.detail ? h("div", { class: "block-sub", text: item.detail }) : null,
            // 첫 줄 밖에 적힌 내용(결정·날짜 등)도 볼 수 있게 저장된 앞부분 요약을 함께 보여 준다
            (item.excerpt || []).length > 1 ? h("div", { class: "block-sub", text: item.excerpt.slice(1).join(" / ") }) : null,
            // 지나간 기록도 분류를 다시 고칠 수 있다(토스트가 닫힌 뒤에도)
            item.kind === "note" ? h("button", { class: "mini-btn", type: "button", text: `분류: ${item.project || "없음"}`,
              "aria-label": "이 기록의 분류 바꾸기", onclick: () => showCaptured({ ok: true, id: item.id, summary: item.summary,
                project: item.project, reopen: true }) }) : null));
        timelineList.appendChild(row);
      });
    }
    const hidden = eventCount - tl.length;
    timelineMore.style.display = hidden > 0 ? "block" : "none";
    timelineMore.textContent = `이전 ${hidden}건은 터미널의 ro log에서 볼 수 있어요`;
  }
}

/* 상태 폴링: 말풍선이 열려 있을 때만 2초(예전 0.45초는 꾸미기 화면에서도 초당 2번 서버를 깨웠다). 닫혀 있으면 롱폴링으로 덜 깨운다.
   서버는 2초마다 변화를 확인하고, 같은 상태의 응답·숨은 말풍선 렌더링은 줄인다. */
let pollGeneration = 0;
let pollController = null;
let stateVersion = null;
const OPEN_POLL_MS = 2000;  // 열려 있을 때 다시 묻는 간격. 내가 한 동작은 그때그때 바로 새로 받으므로 바깥 변화만 이 간격을 탄다
function setPollRate(fast) {
  return refreshState(!fast);
}

/* 상태를 못 받으면 마지막으로 받은 내용을 그대로 두고 '업데이트 실패'만 표시한다(0건 화면으로 바꾸지 않음) */
let lastStateOk = 0;
function markStale(why) {
  const at = lastStateOk ? new Date(lastStateOk).toTimeString().slice(0, 5) : "--:--";
  staleBanner.textContent = `Update failed · showing data as of ${at}. ${why || "Retrying shortly."}`;
  staleBanner.hidden = false;
}
async function refreshState(wait = false) {
  clearTimeout(window._poll);
  window._poll = null;
  const generation = ++pollGeneration;
  if (pollController) pollController.abort();
  pollController = new AbortController();
  let ok = false;
  try {
    const query = wait && stateVersion ? `?wait=${encodeURIComponent(stateVersion)}` : "";
    const res = await fetch("/api/state" + query, {
      headers: { "X-Ro-Token": TOKEN }, signal: pollController.signal
    });
    if (generation !== pollGeneration) return;
    if (!res.ok) {
      markStale(res.status === 403 ? "Please reopen the pet (the server may have restarted)." : `Server error ${res.status}`);
      return;
    }
    const st = await res.json();
    if (generation !== pollGeneration) return;
    stateVersion = st.version;
    lastStateOk = Date.now();
    staleBanner.hidden = true;
    applyState(st);
    ok = true;
  } catch (err) {
    if (generation !== pollGeneration || err.name === "AbortError") return;
    markStale("Could not reach the local server.");
  } finally {
    if (generation === pollGeneration) {
      const closed = bubble.classList.contains("hidden");
      window._poll = setTimeout(() => refreshState(closed), ok ? (closed ? 0 : OPEN_POLL_MS) : 2000);
    }
  }
}

/* 입력창: 기록 회상·파일 찾기는 로컬에서. '/기록 …'은 바로 기록. 그 밖의 입력은 안내 카드(기록으로만 남기기·파일 찾기)로 */
let pendingSend = null;
function resetInput() {
  askInput.value = "";
  hideSlash();  // 값을 코드로 비우면 input 이벤트가 없어 명령 목록이 남는다
  plusIcon.style.display = "block";
  sendIcon.style.display = "none";
}
function hideSendCard() {
  sendCard.style.display = "none";
  pendingSend = null;
}
async function submitInput(q) {
  const p = parsePalette(q);
  const cmd = p.slash ? resolveCommand(p.name) : null;
  if (cmd) {
    if (cmd.arg && !p.arg) { askInput.value = cmd.label + " "; askInput.focus(); return; }  // 내용을 마저 쓰게
    const ok = await runCommand(cmd, p.arg);
    if (ok === false && !askInput.value) { askInput.value = q; askInput.dispatchEvent(new Event("input")); }
    return;
  }
  if (!p.slash && FIND_VERB.test(q) && FIND_NOUN.test(q) && !NOT_FILE.test(q)) { await runFind(q); return; }
  if (!p.slash && RECALL_INTENT.test(q)) { await runRecall(q); return; }
  if (p.slash || ASK_INTENT.test(q)) { showGuide(q); return; }
  hideSendCard();
  const res = await capture("text", "메모", q, 0);
  if (!res && !askInput.value) { askInput.value = q; askInput.dispatchEvent(new Event("input")); }  // 저장 실패: 입력을 돌려준다
}
function showGuide(q) {
  hideSendCard();
  pendingSend = { q };
  fill(sendText, h("div", { text: `“${q}”` }));
  hideToast();
  sendCard.style.display = "flex";
  sendCard.scrollIntoView({ block: "nearest" });
  document.getElementById("sendCancelBtn").focus();  // 기록·찾기는 눌러서 고르고, 기본 포커스는 안전한 '취소'
}
askForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = askInput.value.trim();
  if (!q) {
    askInput.focus();
    return;
  }
  resetInput();
  await submitInput(q);
});
document.getElementById("sendRecordBtn").addEventListener("click", async () => {
  if (!pendingSend) return;
  const q = pendingSend.q;
  hideSendCard();
  await capture("text", "직접 기록", q, q.length);
});
document.getElementById("sendCancelBtn").addEventListener("click", () => {
  if (pendingSend && !askInput.value) askInput.value = pendingSend.q;
  hideSendCard();
  askInput.focus();
});

/* 건너뛴 파일과 이유는 사용자가 닫을 때까지(다음 작업 전까지) 남겨 둔다 */
function writeResultText(r) {
  const rows = (r.skipped || []).map(s => `· ${s.name}: ${s.reason}`);
  return [r.output || r.error || "", ...rows].filter(Boolean).join("\n");
}
async function resolveWrite(approve) {
  const kind = pendingKind;
  let r;
  try { r = await apiPost("/api/write_gate", { approve, id: pendingId }); }
  catch (err) { r = { ok: false, output: "서버에 연결하지 못했어요. 실행 여부를 확인한 뒤 다시 시도해 주세요." }; }
  const text = writeResultText(r);
  if (kind && kind.startsWith("organize")) setOrgMsg(text, (r.skipped && r.skipped.length) || !r.ok ? 0 : 6000);
  else if (text) showToast([h("div", { class: "toast-head", text })], 4000);
  await refreshState();
}
document.getElementById("writeApproveBtn").addEventListener("click", () => resolveWrite(true));
document.getElementById("writeRejectBtn").addEventListener("click", () => resolveWrite(false));
/* 파일 정리 카드: 버튼은 바뀔 때만 다시 그린다(폴링 중 클릭이 사라지지 않게) */
function fmtBytes(n) {
  if (n == null) return "";
  if (n <= 0) return "0KB";
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1)}GB` : n >= 1048576 ? `${(n / 1048576).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`;
}

/* 정리 행: 이름을 누르면 그 자리에서 파일 목록이 펼쳐지고(읽기만), 오른쪽 버튼이 승인 요청이다 */
function orgRow(parent, label, action, title, body) {
  const list = h("ul", { class: "gate-files org-files", hidden: true, "aria-label": `${label} 파일 목록` });
  const toggle = h("button", { class: "org-row-name", type: "button", "aria-expanded": "false", title: "파일 목록 보기" },
    h("span", { class: "org-caret", "aria-hidden": "true", text: "›" }), h("span", { text: label }));
  toggle.addEventListener("click", async () => {
    const open = list.hidden;
    list.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (!open || list.childElementCount) return;
    let r = null;
    try { r = await apiPost("/api/organize/files", body); } catch (err) { r = null; }
    fill(list, r && r.ok && r.files.length
      ? r.files.map(f => h("li", { title: f.to ? `${f.from} → ${f.to}` : f.from }, h("span", { text: f.from }),
          f.to ? [h("span", { class: "arrow", text: "→" }), h("span", { text: f.to })] : null))
      : h("li", { text: "목록을 불러오지 못했어요. 정리안을 다시 만들어 주세요." }));
  });
  const go = h("button", { class: "mini-btn org-go", type: "button", text: action, title });
  go.addEventListener("click", async () => {
    const r = await apiPost("/api/organize/apply", body);
    setOrgMsg(r.ok ? "아래 확인 카드에서 승인하면 실행합니다." : (r.output || ""), r.ok ? 0 : 6000);
    await refreshState();
  });
  parent.append(h("div", { class: "org-row" }, toggle, go), list);
}

function renderOrganize(o) {
  const key = JSON.stringify(o || null);
  if (key === orgKey) return;
  orgKey = key;
  orgCats.replaceChildren();
  orgQuar.replaceChildren();
  orgScanBtn.textContent = o ? "정리안 다시 만들기" : "정리안 만들기";
  if (!o) {
    orgSummary.textContent = "정리안이 없습니다. 먼저 정리안을 만드세요.";
    orgUndoBtn.style.display = "none";
    return;
  }
  const total = o.counts.reduce((a, c) => a + c[1], 0);
  const quar = o.quarantine || [];
  const qn = quar.reduce((a, g) => a + g[2], 0);
  const parts = [];
  if (total) parts.push(`옮길 파일 ${total}개`);
  if (qn) parts.push(`치울 후보 ${qn}개(${fmtBytes(o.reclaim)})`);
  const lines = [parts.length ? `${parts.join(" · ")} — 줄을 누르면 파일 목록이 펼쳐져요. 옮기기는 승인 뒤에 실행됩니다.`
                              : "지금은 옮기거나 치울 파일이 없습니다."];
  if (o.recent_skipped) lines.push(`최근 10분 안에 받거나 고친 파일 ${o.recent_skipped}개는 아직 쓰는 중일 수 있어 건너뛰었어요.`);
  const nodes = lines.map(t => h("div", { text: t }));
  if (o.review) {
    nodes.push(h("details", { class: "rc-ev" }, h("summary", { text: `검토가 필요한 ${o.review}개는 옮기지 않아요` }),
      (o.review_names || []).map(n => h("div", { class: "block-sub", text: n })),
      h("div", { class: "block-sub" }, "직접 분류하려면 터미널에서 ", h("code", { text: "ro organize edit" }))));
  }
  if (o.trashed) nodes.push(h("div", {}, `보관함에 ${fmtBytes(o.trashed)} 보관 중. 7일 지난 것은 터미널에서 `,
    h("code", { text: "ro organize trash --empty" }), "로 비울 수 있어요."));
  orgSummary.replaceChildren(...nodes);
  o.counts.forEach(([cat, n]) => orgRow(orgCats, `${cat} ${n}개`, "옮기기", `${cat} ${n}개 옮기기 — 승인 카드에서 한 번 더 확인합니다`, { category: cat }));
  quar.forEach(([kind, label, n, size]) => orgRow(orgQuar, `${label} ${n}개 · ${fmtBytes(size)}`, "보관함으로",
    `${label} ${n}개를 보관함으로(지우지 않음, 되돌리기 가능) — 승인 카드에서 한 번 더 확인합니다`, { kind }));
  if (o.undo) {
    orgUndoBtn.style.display = "inline-block";
    orgUndoBtn.textContent = `되돌리기 · ${o.undo.when} ${o.undo.count}개`;
  } else {
    orgUndoBtn.style.display = "none";
  }
}

let orgMsgTimer = null;
function setOrgMsg(text, ms = 6000) {
  clearTimeout(orgMsgTimer);
  orgMsg.textContent = text || "";
  if (text && ms) orgMsgTimer = setTimeout(() => { orgMsg.textContent = ""; }, ms);
}

orgScanBtn.addEventListener("click", async () => {
  orgScanBtn.disabled = true;
  setOrgMsg("정리안을 만드는 중... (파일은 옮기지 않습니다)", 0);
  try {
    const r = await apiPost("/api/organize/scan", {});
    setOrgMsg(r.ok ? "정리안을 새로 만들었습니다." : (r.output || "정리안을 만들지 못했어요."));
  } catch (err) {  // 처리 중 문구가 남아 있지 않게 실패를 알린다
    setOrgMsg("서버에 연결하지 못해 정리안을 만들지 못했어요. 다시 시도해 주세요.", 0);
  } finally {
    orgScanBtn.disabled = false;
    await refreshState();
  }
});
orgUndoBtn.addEventListener("click", async () => {
  let r;
  try { r = await apiPost("/api/organize/undo", {}); }
  catch (err) { r = { ok: false, output: "서버에 연결하지 못했어요. 다시 시도해 주세요." }; }
  setOrgMsg(r.ok ? "아래 확인 카드에서 승인하면 되돌립니다." : (r.output || ""), r.ok ? 0 : 6000);
  await refreshState();
});

/* 마우스가 창 밖으로 나가면 시선을 가운데로 되돌린다 */
document.documentElement.addEventListener("mouseleave", () => {
  if (currentAction || RoMotion.busy()) return;
  eyesWrap.style.transform = "";
  clearHeadGaze();
  kickNativeGlass();
});

/* ===== 모션 엔진: 07 누름 · 08 잡기·끌기 · 09 흔들기 · 10 놓기 =====
   시간(ms)을 인자로 받는 결정적 상태기계다. 실제 구동은 rAF가, 테스트는 advance(t)가 맡는다. */
const RoMotion = (() => {
  const SPEC = {
    press: { ms: 80, sx: 1.08, sy: 0.86, rel: [600, 15], delay: [60, 30, 0], happyAfter: 240, happyMs: 600, doneMs: 1000 },
    // 세게 흔들어도 몸이 펫 창(176×168) 밖으로 나가 잘리지 않게 움직임을 작게 묶는다
    grab: { holdMs: 300, moveStart: 8, hang: [5, 17], hangSpring: [400, 24], follow: [1.0, 0.35, 0.2], damping: 0.65, tilt: 0.25, tiltMax: 4,
            maxLag: 12, wobbleDeg: 1.4, wobbleHz: 1.5 },
    shake: { reversals: 3, windowMs: 1000, speed: 1200, spring: [180, 8], maxRot: 4, dizzyAfter: Infinity, dizzyMs: 0, landDizzyMs: 1200,
             spinMs: 600, endGap: 450, calmMs: 900, stopSpeed: 150, stopMs: 100, calmDamping: 12, keepRatio: 0.5, slowWindow: 120 },
    /* 놓은 자리에서 크게 떨어지지 않게 낙하는 최대 24px. 짧게 떨어지니 착지도 살짝만 눌린다 */
    drop: { g: 2400, maxFall: 24, stretch: [0.94, 1.08], landMs: 90, land: [1.07, 0.9], bounce: 0.2,
            bounceSpring: [500, 18], stack: [0, 60, 120], restMs: 360, fadeMs: 150 },
    gap: 1,
  };
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const SC = (px) => px * petScale;  // 창 안에서 움직이는 px 진폭은 펫 크기를 따른다(small에서 창 밖으로 잘리지 않게)
  const powerOut = (t, p = 2) => 1 - Math.pow(1 - clamp(t, 0, 1), p);

  /* 질량 1, spring(stiffness, damping)의 단위 스텝 응답(0→1, 오버슈트 포함) */
  function springStep(k, c, sec) {
    if (sec <= 0) return 0;
    const w0 = Math.sqrt(k), z = c / (2 * w0);
    if (z < 1) {
      const wd = w0 * Math.sqrt(1 - z * z);
      return 1 - Math.exp(-z * w0 * sec) * (Math.cos(wd * sec) + (z * w0 / wd) * Math.sin(wd * sec));
    }
    if (z === 1) return 1 - Math.exp(-w0 * sec) * (1 + w0 * sec);
    const s = Math.sqrt(z * z - 1), r1 = -w0 * (z - s), r2 = -w0 * (z + s);
    return 1 - (r2 * Math.exp(r1 * sec) - r1 * Math.exp(r2 * sec)) / (r2 - r1);
  }
  /* 임펄스 응답의 첫 마루를 1로 정규화한 한 번의 튕김(0→1→0) */
  const [BK, BC] = SPEC.drop.bounceSpring;
  const BW0 = Math.sqrt(BK), BZ = BC / (2 * BW0), BWD = BW0 * Math.sqrt(1 - BZ * BZ);
  const BHALF = Math.PI / BWD;
  let BPEAK = 0;
  for (let i = 0; i <= 200; i++) { const s = i / 200 * BHALF; BPEAK = Math.max(BPEAK, Math.exp(-BZ * BW0 * s) * Math.sin(BWD * s)); }
  const bounce1 = (sec) => (sec <= 0 || sec >= BHALF) ? 0 : Math.exp(-BZ * BW0 * sec) * Math.sin(BWD * sec) / BPEAK;

  let S;
  let dims = null;
  let manual = false;
  let raf = null;
  const now = () => performance.now();
  const reducedNow = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  const mkPos = (x, y) => ({ x, y, vx: 0, vy: 0 });
  function reset() {
    S = { phase: "idle", downAt: null, upAt: null, grabAt: null, grabbed: false, tap: false,
          anchor: null, head: { x: 0, y: 0 }, pos: [mkPos(0, 0), mkPos(0, 0), mkPos(0, 0)],
          vx: 0, vy: 0, lastMoveT: null, peak: 0, sign: 0, revs: [], tau: 80,
          shakeActive: false, shakeStart: null, shakeLast: -1e9, shakeEnd: null, dizzyFrom: 0, dizzyUntil: 0, sg: 0, slowSince: null,
          hist: [], osc: [{ th: 0, w: 0 }, { th: 0, w: 0 }, { th: 0, w: 0 }], simT: 0,
          dropAt: null, fall: 0, tFall: 0.1, L0: null, reduced: false };
  }
  reset();

  function measure() {
    const bot = document.getElementById("roBot");
    const els = [layerHead, layerBody, layerBase];
    if (!bot || !els[0]) { dims = null; return; }
    dims = els.map(e => {
      const cs = getComputedStyle(e);
      return { x: e.offsetLeft, y: e.offsetTop, w: parseFloat(cs.width) || e.offsetWidth, h: parseFloat(cs.height) || e.offsetHeight };
    });
  }

  function down(t) {
    reset();
    S.reduced = reducedNow();
    measure();
    S.phase = "press";
    S.downAt = t;
    S.simT = t;
    if (!manual) {
      petWrap.dataset.motion = "press";
      petWrap.dataset.eyes = "squint";
    }
    ensureLoop();
  }

  function enterGrab(t) {
    S.phase = "grab";
    S.grabAt = t;
    S.grabbed = true;
    S.upAt = t;                       // 눌림은 스프링으로 풀린다
    S.pos = S.pos.map(() => mkPos(S.head.x, S.head.y));
  }

  function pushReversal(t) {
    S.revs.push(t);
    S.revs = S.revs.filter(r => t - r <= SPEC.shake.windowMs);
    if (S.revs.length >= 2) {
      const iv = S.revs[S.revs.length - 1] - S.revs[S.revs.length - 2];
      S.tau = clamp(iv * 0.667, 40, 160);   // 층별 위상 120° 차이
    }
    if (S.revs.length >= SPEC.shake.reversals) {
      if (!S.shakeActive) { S.shakeActive = true; S.shakeStart = S.shakeStart ?? t; }
      S.shakeLast = t;
    }
  }

  function move(x, y, t, force = false) {
    if (S.phase === "idle" || S.phase === "drop") return;
    advance(t);
    if (S.phase === "press") {
      if (S.upAt != null) return;
      if (!S.anchor) S.anchor = { x, y };
      S.head = { x, y };
      if (force || Math.hypot(x - S.anchor.x, y - S.anchor.y) > SPEC.grab.moveStart) { enterGrab(t); S.head = { x, y }; S.pos = S.pos.map(() => mkPos(x, y)); S.lastMoveT = t; }
      return;
    }
    const dtm = Math.max(1, t - (S.lastMoveT ?? t - 16));
    const rawX = (x - S.head.x) / dtm * 1000, rawY = (y - S.head.y) / dtm * 1000;
    S.vx = 0.5 * S.vx + 0.5 * rawX;
    S.vy = 0.5 * S.vy + 0.5 * rawY;
    S.head = { x, y };
    S.lastMoveT = t;
    S.hist.push({ t, v: S.vx });
    while (S.hist.length && t - S.hist[0].t > 1500) S.hist.shift();
    const sign = S.vx > 60 ? 1 : S.vx < -60 ? -1 : 0;
    if (sign !== 0) {
      if (S.sign !== 0 && sign !== S.sign) {
        if (S.peak >= SPEC.shake.speed * (S.shakeActive ? SPEC.shake.keepRatio : 1)) pushReversal(t);
        S.peak = 0;
      }
      S.sign = sign;
      S.peak = Math.max(S.peak, Math.abs(S.vx));
    }
  }

  function up(t, moved = false, fall = 0) {
    if (S.phase === "idle") return;
    advance(t);
    if (S.phase === "press") {
      if (S.upAt == null) { S.upAt = t; S.tap = true; }
      return;
    }
    if (S.phase === "grab") startDrop(t, fall);
  }

  function startDrop(t, fall) {
    S.L0 = grabLayers(t);                              // 놓는 순간의 매달린 자세를 기억한다
    // 흔드는 동안은 찡그리기만 하고, 흔들다 놓으면 착지한 순간부터 눈이 돈다
    const shaken = S.shakeActive || (S.shakeEnd != null && t - S.shakeEnd <= SPEC.shake.endGap);
    if (S.shakeActive) { S.shakeActive = false; S.shakeEnd = S.shakeLast; }
    if (S.shakeEnd != null && S.shakeLast - S.shakeStart >= SPEC.shake.dizzyAfter) S.dizzyUntil = Math.max(S.dizzyUntil, t + SPEC.shake.dizzyMs);
    S.phase = "drop";
    S.dropAt = t;
    S.fall = clamp(fall, 0, SPEC.drop.maxFall);
    S.tFall = S.fall > 0.5 ? Math.max(0.04, Math.sqrt(2 * S.fall / SPEC.drop.g)) : 0.1;
    if (shaken) {
      S.dizzyFrom = t + S.tFall * 1000;
      S.dizzyUntil = Math.max(S.dizzyUntil, S.dizzyFrom + SPEC.shake.landDizzyMs);
    }
  }

  function stepSim(cur, dt) {
    // 체인: 프레임당 추종률 k의 정상 지연(τ)을 유지하면서, 멈출 때 관성으로 살짝 넘어가도록 감쇠 스프링으로 푼다
    const f = SPEC.grab.follow, Z = SPEC.grab.damping, sec = dt / 1000;
    for (let i = 1; i < 3; i++) {
      const w = 2 * Z / (0.016667 / -Math.log(1 - f[i]));
      const p = S.pos[i];
      p.vx += (w * w * (S.head.x - p.x) - 2 * Z * w * p.vx) * sec;
      p.vy += (w * w * (S.head.y - p.y) - 2 * Z * w * p.vy) * sec;
      p.x += p.vx * sec;
      p.y += p.vy * sec;
    }
    S.pos[0] = mkPos(S.head.x, S.head.y);
    const gate = S.shakeActive || (S.shakeEnd != null && cur - S.shakeEnd < SPEC.shake.calmMs) ? 1 : 0;
    const [k, c0] = SPEC.shake.spring;
    const c = S.shakeActive ? c0 : SPEC.shake.calmDamping;      // 멈춘 뒤엔 900ms 안에 가라앉도록 조금 더 감쇠
    S.sg += ((S.shakeActive ? 1 : 0) - S.sg) * (1 - Math.exp(-dt / (S.shakeActive ? 40 : 150)));
    for (let i = 0; i < 3; i++) {
      const u = gate ? clamp(velAt(cur - i * S.tau) / SPEC.shake.speed, -1, 1) * SPEC.shake.maxRot : 0;
      const o = S.osc[i];
      o.w += (k * (u - o.th) - c * o.w) * dt / 1000;
      o.th += o.w * dt / 1000;
    }
  }

  /* 최근 slowWindow(ms) 안의 가장 빠른 속도. 방향이 바뀌는 순간 속도가 0을 지나도 멈춘 것으로 보지 않는다 */
  function recentSpeed(t) {
    let m = Math.abs(velAt(t));
    for (let i = S.hist.length - 1; i >= 0 && t - S.hist[i].t <= SPEC.shake.slowWindow; i--) m = Math.max(m, Math.abs(S.hist[i].v));
    return t - (S.lastMoveT ?? -1e9) > SPEC.shake.slowWindow ? Math.abs(velAt(t)) : m;
  }

  function velAt(t) {
    const h = S.hist;
    if (!h.length) return 0;
    if (t >= h[h.length - 1].t) return t - h[h.length - 1].t > 120 ? 0 : h[h.length - 1].v;
    for (let i = h.length - 1; i >= 0; i--) if (h[i].t <= t) return h[i].v;
    return 0;
  }

  function advance(t) {
    if (S.phase === "idle") return;
    if (S.phase === "press" && S.upAt == null && t - S.downAt >= SPEC.grab.holdMs) enterGrab(t);
    if (S.shakeActive) {
      if (recentSpeed(t) < SPEC.shake.stopSpeed) { if (S.slowSince == null) S.slowSince = t; } else S.slowSince = null;
    }
    const stopped = S.shakeActive && S.slowSince != null && t - S.slowSince >= SPEC.shake.stopMs;
    if (S.shakeActive && (stopped || t - S.shakeLast > SPEC.shake.endGap)) {
      S.shakeActive = false;
      S.shakeEnd = S.shakeLast;
      if (S.shakeLast - S.shakeStart >= SPEC.shake.dizzyAfter) S.dizzyUntil = S.shakeEnd + SPEC.shake.dizzyMs;
      S.shakeStart = null; S.revs = [];
    }
    let cur = S.simT;
    while (cur < t) { const dt = Math.min(4, t - cur); cur += dt; stepSim(cur, dt); }
    S.simT = Math.max(S.simT, t);
    const P = SPEC.press, D = SPEC.drop;
    if (S.phase === "press" && S.upAt != null && !S.grabbed && t > S.upAt + P.doneMs) S.phase = "idle";
    if (S.phase === "drop") {
      const end = S.reduced ? D.fadeMs : S.tFall * 1000 + D.landMs + D.restMs;
      if (t > S.dropAt + end && t > S.dizzyUntil) S.phase = "idle";
    }
  }

  /* 누름 스케일: 80ms power2.out → 뗄 때 spring(600,15) (층마다 지연) */
  function pressScale(t, delay) {
    if (S.downAt == null) return [1, 1];
    const tt = t - delay;
    if (tt < S.downAt) return [1, 1];
    const P = SPEC.press;
    const held = (S.upAt == null || tt < S.upAt) ? tt - S.downAt : S.upAt - S.downAt;
    const p = powerOut(held / P.ms);
    const sx = 1 + (P.sx - 1) * p, sy = 1 + (P.sy - 1) * p;
    if (S.upAt == null || tt < S.upAt) return [sx, sy];
    const r = springStep(P.rel[0], P.rel[1], (tt - S.upAt) / 1000);
    return [lerp(sx, 1, r), lerp(sy, 1, r)];
  }

  function grabLayers(t) {
    const G = SPEC.grab;
    const L = [0, 1, 2].map(() => ({ tx: 0, ty: 0, rot: 0 }));
    if (S.reduced) return L;
    const h = springStep(G.hangSpring[0], G.hangSpring[1], (t - S.grabAt) / 1000);
    L[1].ty = SC(G.hang[0]) * h;
    L[2].ty = SC(G.hang[1]) * h;
    for (let i = 1; i < 3; i++) {
      L[i].tx = clamp(S.pos[i].x - S.head.x, -SC(G.maxLag), SC(G.maxLag));
      L[i].ty += clamp(S.pos[i].y - S.head.y, -SC(G.maxLag), SC(G.maxLag));
    }
    const calm = 1 - S.sg;                                        // 흔드는 동안엔 끌기 기울기·매달림 흔들림을 끈다
    const tilt = clamp(L[2].tx / petScale * G.tilt, -G.tiltMax, G.tiltMax) * calm;
    L[2].rot = tilt;
    L[1].rot = tilt * 0.5;
    const wob = G.wobbleDeg * calm * clamp((t - S.grabAt) / 300, 0, 1) * Math.exp(-Math.hypot(S.vx, S.vy) / 600);
    for (let i = 0; i < 3; i++) {
      L[i].rot += wob * Math.sin(2 * Math.PI * G.wobbleHz * (t - S.grabAt) / 1000 + i * 1.3);
      L[i].rot += S.osc[i].th;
      L[i].rot = clamp(L[i].rot, -SPEC.shake.maxRot, SPEC.shake.maxRot);   // 층 회전 최대 4°
    }
    return L;
  }

  function separate(L) {
    if (!dims) return;
    const oy = dims[2].y + dims[2].h;
    const ext = (i) => {                                          // 회전·스케일된 층의 세로 반높이
      const r = Math.abs(L[i].rot) * Math.PI / 180;
      return (dims[i].h * L[i].sy * Math.cos(r) + dims[i].w * L[i].sx * Math.sin(r)) / 2;
    };
    const center = (i) => {                                       // apply()와 같은 변환으로 옮겨진 중심 y
      const cy = dims[i].y + dims[i].h / 2;
      return cy + L[i].ty + (L[i].sy - 1) * (cy - oy);
    };
    for (let i = 1; i < 3; i++) {
      const need = center(i - 1) + ext(i - 1) + ext(i) + SPEC.gap;
      const c = center(i);
      if (c < need) L[i].ty += need - c;
    }
  }

  function eyesAt(t) {
    const D = SPEC.drop, P = SPEC.press, K = SPEC.shake;
    const swirl = (S.shakeActive && S.shakeStart != null && t - S.shakeStart >= K.dizzyAfter) || (t >= S.dizzyFrom && t < S.dizzyUntil);
    if (S.reduced && swirl) return S.shakeActive ? "squint" : "big";
    if (S.phase === "grab") {
      if (swirl) return "swirl";
      if (S.shakeActive) return "squint";
      return "big";
    }
    if (S.phase === "drop") {
      if (swirl) return "swirl";
      const tt = t - S.dropAt, tl = S.tFall * 1000;
      if (S.reduced) return "";
      if (tt < tl) return "big";
      const a = tt - tl;
      return a < 110 ? "squint" : a < 260 ? "" : a < 380 ? "dash" : "";
    }
    if (S.phase === "press") {
      if (t <= S.downAt) return "";
      if (S.upAt == null || t < S.upAt) return "squint";
      if (!S.tap) return "";
      const a = t - S.upAt;
      return a < P.happyAfter ? "big" : (a < P.happyAfter + P.happyMs ? "happy" : "");
    }
    return "";
  }

  function pose(t) {
    const P = { l: [0, 1, 2].map(() => ({ tx: 0, ty: 0, sx: 1, sy: 1, rot: 0 })), op: 1, eyes: { shape: "", lx: 0, ly: 0 }, streak: { o: 0, w: 12, dir: -1 } };
    if (S.phase === "idle") return P;
    const D = SPEC.drop;
    P.eyes.shape = eyesAt(t);
    if (S.phase === "press" || S.phase === "grab") {
      if (!S.reduced) for (let i = 0; i < 3; i++) { const s = pressScale(t, SPEC.press.delay[i]); P.l[i].sx = s[0]; P.l[i].sy = s[1]; }
      if (S.phase === "grab") {
        const L = grabLayers(t);
        for (let i = 0; i < 3; i++) Object.assign(P.l[i], L[i]);
        separate(P.l);
        if (P.eyes.shape === "big") { P.eyes.lx = clamp(S.vx / 900, -1, 1) * 3; P.eyes.ly = clamp(S.vy / 900, -1, 1) * 2; }
      }
      return P;
    }
    // drop
    const tt = (t - S.dropAt) / 1000;
    if (S.reduced) { P.op = lerp(0.4, 1, clamp(tt * 1000 / D.fadeMs, 0, 1)); return P; }
    if (tt < S.tFall) {
      const h = 1 - Math.pow(tt / S.tFall, 2);                 // 중력: 거리 ∝ t²
      const b = powerOut(tt * 1000 / 60);
      for (let i = 0; i < 3; i++) {
        P.l[i].tx = S.L0[i].tx * h; P.l[i].ty = S.L0[i].ty * h; P.l[i].rot = S.L0[i].rot * h;
        P.l[i].sx = lerp(1, D.stretch[0], b); P.l[i].sy = lerp(1, D.stretch[1], b);
      }
      return P;
    }
    const a = tt - S.tFall;                                   // 착지 후 경과(초)
    const hop = D.bounce * Math.max(S.fall, 24);
    for (let i = 0; i < 3; i++) {
      if (a * 1000 < D.landMs) {
        const p = powerOut(a * 1000 / D.landMs);
        P.l[i].sx = lerp(D.stretch[0], D.land[0], p); P.l[i].sy = lerp(D.stretch[1], D.land[1], p);
      } else {
        const ab = a - D.landMs / 1000;
        const r = springStep(BK, BC, ab - D.stack[i] / 1000);
        P.l[i].sx = lerp(D.land[0], 1, r); P.l[i].sy = lerp(D.land[1], 1, r);
        P.l[i].ty = -hop * bounce1(ab - Math.max(0, D.stack[i] / 1000 - 0.0));
      }
    }
    return P;
  }

  function apply(P) {
    if (!dims) measure();
    const bot = document.getElementById("roBot");
    if (!bot || !dims) return;
    const els = [layerHead, layerBody, layerBase];
    const ox = dims[2].x + dims[2].w / 2, oy = dims[2].y + dims[2].h;
    els.forEach((el, i) => {
      const l = P.l[i], d = dims[i];
      const cx = d.x + d.w / 2, cy = d.y + d.h / 2;
      const tx = l.tx + (l.sx - 1) * (cx - ox), ty = l.ty + (l.sy - 1) * (cy - oy);
      el.style.translate = `${tx.toFixed(2)}px ${ty.toFixed(2)}px`;
      el.style.rotate = `${l.rot.toFixed(2)}deg`;
      el.style.scale = `${l.sx.toFixed(4)} ${l.sy.toFixed(4)}`;
      // 유리 속 풍경은 몸이 가는 반대쪽으로 밀리고, 기울면 옆으로, 눌리면 위아래로 출렁인다
      el.style.setProperty("--gx", `${clamp(-0.6 * tx - 1.2 * l.rot, -10, 10).toFixed(2)}px`);
      el.style.setProperty("--gy", `${clamp(-0.6 * ty + 30 * (1 - l.sy), -8, 8).toFixed(2)}px`);
    });
    bot.style.opacity = P.op === 1 ? "" : String(P.op);
    const st = document.getElementById("streak");
    if (st) {
      st.style.opacity = P.streak.o.toFixed(2);
      st.style.width = P.streak.w.toFixed(1) + "px";
      const hx = dims[0].x + P.l[0].tx, hy = dims[0].y + dims[0].h * 0.38 + P.l[0].ty;
      st.style.left = (P.streak.dir < 0 ? hx - P.streak.w - 6 : hx + dims[0].w + 6).toFixed(1) + "px";
      st.style.top = hy.toFixed(1) + "px";
    }
    petWrap.dataset.eyes = P.eyes.shape;
    eyesWrap.style.translate = (P.eyes.lx || P.eyes.ly) ? `${P.eyes.lx.toFixed(2)}px ${P.eyes.ly.toFixed(2)}px` : "";
    petWrap.dataset.motion = S.phase;
    kickNativeGlass();
  }

  function clearStyles() {
    [layerHead, layerBody, layerBase].forEach(el => {
      el.style.translate = ""; el.style.rotate = ""; el.style.scale = "";
      el.style.removeProperty("--gx"); el.style.removeProperty("--gy");
    });
    const bot = document.getElementById("roBot");
    if (bot) bot.style.opacity = "";
    const st = document.getElementById("streak");
    if (st) st.style.opacity = "";
    eyesWrap.style.translate = "";
    delete petWrap.dataset.eyes;
    delete petWrap.dataset.motion;
    kickNativeGlass();
  }

  function loop() {
    const t = now();
    advance(t);
    apply(pose(t));
    if (S.phase !== "idle") raf = requestAnimationFrame(loop);
    else { raf = null; clearStyles(); if (api.onIdle) api.onIdle(); }
  }
  function ensureLoop() {
    kickNativeGlass();
    if (!manual && raf == null) raf = requestAnimationFrame(loop);
  }

  /* 네이티브 메뉴의 미리보기용 합성 입력 */
  let demoTimer = null;
  function demo(name, done) {
    clearInterval(demoTimer);
    const t0 = now();
    down(t0);
    const plan = {
      press: { upAt: 90, end: 90 },
      drag: { moveFrom: 340, upAt: 1900, path: (s) => ({ x: 150 * Math.sin(s * 2.2), y: 18 * Math.sin(s * 1.1) }) },
      shake: { moveFrom: 340, upAt: 2600, path: (s) => ({ x: 60 * Math.sin(s * 2 * Math.PI * 4), y: 0 }) },
      drop: { moveFrom: 1e9, upAt: 450, fall: 60 },
    }[name];
    if (!plan) return false;
    demoTimer = setInterval(() => {
      const t = now(), e = t - t0;
      if (plan.moveFrom != null && e >= plan.moveFrom) { const p = plan.path ? plan.path((e - plan.moveFrom) / 1000) : { x: 0, y: 0 }; move(p.x, p.y, t); }
      if (e >= plan.upAt) { clearInterval(demoTimer); up(t, true, plan.fall || 0); if (done) done(); }
    }, 8);
    return true;
  }

  const api = {
    SPEC, springStep, bounce1, down, move, up, advance, pose, apply, demo, reset, clearStyles,
    get state() { return S; },
    set manual(v) { manual = !!v; },
    busy: () => S.phase !== "idle",
    consumeClick: () => { const g = S.grabbed; S.grabbed = false; return !g; },
  };
  return api;
})();

RoMotion.onIdle = () => { if (MOTION_DEMOS.includes(currentAction)) window.triggerAction(null); };

/* ===== UX 확장: 앰비언트(E) · 근거 있는 답(C) · 정리(D) · ⌥R 팔레트(B) · 끌어다 놓기(A) ===== */
const attnDot = document.getElementById("attnDot");
const muteBadge = document.getElementById("muteBadge");
const toastEl = document.getElementById("toast");
const recallCard = document.getElementById("recallCard");
const recOrgCard = document.getElementById("recOrgCard");
const palette = document.getElementById("palette");
const palInput = document.getElementById("palInput");
const palList = document.getElementById("palList");
const focusBtn = document.getElementById("focusBtn");
let ambient = null;
let dropActive = false;
let projectNames = [];

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  kids.flat().forEach(c => c != null && el.append(c));
  return el;
}
/* replaceChildren은 null을 "null" 글자로 그린다: 빈 자리는 걸러서 넣는다 */
function fill(el, ...kids) {
  el.replaceChildren(...kids.flat().filter(c => c != null && c !== false));
  return el;
}
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* E · 앰비언트 몸 */
function applyAmbient(st) {
  projectNames = st.project_names || projectNames;
  ambient = st.ambient || null;
  if (!ambient) return;
  petWrap.classList.toggle("focus-mode", ambient.focus);
  petWrap.classList.toggle("drop-ready", dropActive);
  attnDot.hidden = !ambient.attention;
  muteBadge.hidden = !(ambient.focus && ambient.held > 0);
  muteBadge.querySelector("span").textContent = ambient.held;
  muteBadge.setAttribute("aria-label", `알림 ${ambient.held}건 모아둠`);
  petWrap.setAttribute("aria-label", `ro · ${ambient.focus ? "Focus mode" : ambient.label}${ambient.attention ? " · Attention" : ""}`);
  if (!currentAction && Date.now() >= previewLockUntil) {
    petCaption.textContent = dropActive ? "놓으면 기록해요" : (ambient.focus ? "집중 모드" : ambient.label);
  }
}
focusBtn.addEventListener("click", async () => {
  await apiPost("/api/focus", { on: !(ambient && ambient.focus) });
  await refreshState();
});

/* A · 토스트 */
let toastTimer = null;
function hideToast() {
  clearTimeout(toastTimer);
  toastEl.style.display = "none";
  toastEl.replaceChildren();
}
let toastMs = 0;
function showToast(nodes, ms) {
  clearTimeout(toastTimer);
  fill(toastEl, nodes);
  toastEl.style.display = "flex";
  toastMs = ms || 0;
  if (ms) toastTimer = setTimeout(hideToast, ms);
}
/* 읽거나 고르는 동안(마우스·키보드 포커스)에는 닫지 않는다. 벗어나면 다시 센다 */
function holdToast() { clearTimeout(toastTimer); }
function resumeToast() {
  if (toastMs && !toastEl.matches(":hover") && !toastEl.contains(document.activeElement)) {
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, toastMs);
  }
}
toastEl.addEventListener("mouseenter", holdToast);
toastEl.addEventListener("focusin", holdToast);
toastEl.addEventListener("mouseleave", resumeToast);
toastEl.addEventListener("focusout", () => setTimeout(resumeToast, 0));
function showCaptured(res) {
  if (!res.ok) {
    showToast([h("div", { class: "toast-head", text: res.error || "기록하지 못했어요" })], 4000);
    return;
  }
  const sel = h("select", { "aria-label": "프로젝트 분류" },
    h("option", { value: "", text: "분류 없음" }),
    projectNames.map(n => h("option", { value: n, text: n })));
  sel.value = res.project || "";
  sel.addEventListener("change", async () => {  // '분류 없음'도 실제로 저장한다
    let r;
    try { r = await apiPost("/api/capture_project", { id: res.id, project: sel.value }); }
    catch (err) { r = { ok: false }; }
    note.textContent = r.ok ? (sel.value ? `${sel.value}(으)로 저장했어요` : "분류 없음으로 저장했어요")
                            : "저장하지 못했어요 — 다시 골라 주세요";
  });
  const note = h("span", { text: res.project ? "내용을 보고 Ro가 골랐어요" : "분류를 골라주세요" });
  const undo = h("button", { class: "mini-btn", type: "button", text: "되돌리기", onclick: async () => {
    const r = await apiPost("/api/capture_undo", { id: res.id });
    showToast([h("div", { class: "toast-head", text: r.ok ? "되돌렸어요" : (r.error || "되돌리지 못했어요") })], 2200);
    await refreshState();
  } });
  showToast([
    h("div", { class: "toast-head" }, h("span", { text: res.reopen ? "분류 바꾸기" : "기록했어요" }), undo),
    h("div", { class: "toast-file", text: res.summary }),
    projectNames.length || res.project ? h("div", { class: "toast-row" }, h("span", { text: "분류" }), sel, note) : null,
    h("div", { class: "toast-bar", "aria-hidden": "true" }),
  ], 6000);
}
async function capture(kind, name, text, size) {
  let res;
  try {
    res = await apiPost("/api/capture", { kind, name, text: String(text || "").slice(0, 4000), size });
  } catch (err) {  // 저장됐는지 알 수 없으면 입력을 돌려주고 그렇게 알린다(호출한 쪽이 입력창에 복원)
    showToast([h("div", { class: "toast-head", text: "기록하지 못했어요(서버 연결 실패). 입력은 그대로 남겨 두었어요." })], 6000);
    return false;
  }
  setBubbleOpen(true);
  switchTab("home");
  showCaptured(res);
  await refreshState();
  return !!(res && res.ok);
}
const TEXT_EXT = /\.(md|txt|csv|json|py|js|ts|tsx|log|ya?ml|toml|html|css|swift|sh|rs|go)$/i;
async function handleDrop(dt) {
  const file = dt.files && dt.files[0];
  if (file) {
    const readable = file.type.startsWith("text/") || TEXT_EXT.test(file.name);
    const text = readable ? await file.slice(0, 20000).text() : `${file.name} (${Math.round(file.size / 1024)}KB)`;
    return capture("file", file.name, text, file.size);
  }
  const uri = (dt.getData("text/uri-list") || "").split("\n").find(l => l && !l.startsWith("#"));
  const plain = (dt.getData("text/plain") || "").trim();
  const link = uri || (/^https?:\/\/\S+$/.test(plain) ? plain : "");
  if (link) {
    let host = "링크";
    try { host = new URL(link).host; } catch (e) {}
    return capture("link", host, link, 0);
  }
  if (plain) return capture("text", "끌어다 놓은 텍스트", plain, plain.length);
}
/* 파일 먹기: 끌어온 파일을 펫 위에 두면 머리가 살짝 틀어지고, 2초 머무르면 뚜껑처럼 18°까지 열린다.
   놓으면 입이 탁 닫히고(120ms) 눈을 깜빡인다. 중간에 벗어나면 되돌아간다. 줄이기 설정이면 각도 없이 눈만 깜빡인다. */
const Lid = (() => {
  const TILT = 6, OPEN = 18, DWELL_MS = 2000;
  let angle = 0, raf = 0, dwell = 0, state = "idle";   // idle | tilt | open | chomp
  const reduced = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  function paint(a) {
    angle = a;
    petWrap.classList.toggle("lid-on", a > 0);
    layerHead.style.rotate = a > 0 ? `${-a.toFixed(2)}deg` : "";   // 오른쪽이 올라가야 하니 시계 반대 방향
    kickNativeGlass();
  }
  function tween(to, ms, ease, done) {
    cancelAnimationFrame(raf);
    const from = angle, t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      paint(from + (to - from) * ease(k));
      if (k < 1) raf = requestAnimationFrame(step); else if (done) done();
    };
    raf = requestAnimationFrame(step);
  }
  const easeOut = (k) => 1 - Math.pow(1 - k, 3), easeIn = (k) => k * k;
  function blink() {
    eyeL.classList.add("blink"); eyeR.classList.add("blink");
    setTimeout(() => { eyeL.classList.remove("blink"); eyeR.classList.remove("blink"); }, 300);
  }
  return {
    hover() {
      if (state !== "idle" || reduced() || RoMotion.busy()) return;
      state = "tilt";
      tween(TILT, 120, easeOut);
      dwell = setTimeout(() => { if (state === "tilt") { state = "open"; tween(OPEN, 300, easeOut); } }, DWELL_MS);
    },
    leave() {
      if (state === "chomp") return;
      clearTimeout(dwell);
      if (state === "idle") return;
      state = "idle";
      tween(0, 200, easeOut);
    },
    chomp() {
      clearTimeout(dwell);
      if (reduced() || state === "idle") { state = "idle"; blink(); return; }
      state = "chomp";
      tween(0, 120, easeIn, () => { state = "idle"; blink(); });
    },
    reset() { clearTimeout(dwell); cancelAnimationFrame(raf); state = "idle"; paint(0); },
  };
})();
function setDropActive(on) {
  if (dropActive === on) return;
  dropActive = on;
  petWrap.classList.toggle("drop-ready", on);
  if (on) { petCaption.textContent = "놓으면 기록해요"; Lid.hover(); } else Lid.leave();
}
window.addEventListener("dragenter", (e) => { e.preventDefault(); setDropActive(true); });
window.addEventListener("dragover", (e) => { e.preventDefault(); setDropActive(true); });
window.addEventListener("dragleave", (e) => { if (!e.relatedTarget) setDropActive(false); });
window.addEventListener("drop", (e) => { e.preventDefault(); Lid.chomp(); setDropActive(false); handleDrop(e.dataTransfer); });

/* C · 근거 붙은 답 */
function openRecord(id, day) {
  const row = timelineList.querySelector(`[data-id="${CSS.escape(id)}"]`);
  if (!row) {  // 타임라인은 오늘 것만 보여 준다: 엉뚱한 탭으로 옮기지 말고 이유와 찾는 방법을 알린다
    showToast([h("div", { class: "toast-head", text: `${day || "다른 날"} 기록이라 오늘 타임라인에는 없어요.` }),
      h("div", { class: "block-sub", text: `근거 줄에 저장된 내용이 모두 보여요. 그날 요약: 터미널에서 ro log summary --date ${day || "YYYY-MM-DD"}` })], 6000);
    return;
  }
  switchTab("timeline");
  row.scrollIntoView({ block: "center" });
  row.classList.add("flash");
  setTimeout(() => row.classList.remove("flash"), 1600);
}
/* 답·찾기 카드 맨 위 줄: 질문 칩과 닫기(×). 닫기가 없으면 카드가 홈의 인사말·지표를 계속 가린다 */
function cardTop(card, q) {
  return h("div", { class: "rc-top" }, q ? h("div", { class: "rc-q", text: q }) : null,
    h("button", { class: "close-x-btn", type: "button", "aria-label": "닫기", title: "닫기", text: "×",
      onclick: () => { card.style.display = "none"; recallShown = false; paneHome.scrollTop = 0; askInput.focus(); } }));
}
async function runRecall(q) {
  pushRecent(q);
  const r = await apiPost("/api/recall", { question: q });
  setBubbleOpen(true);
  switchTab("home");
  recOrgCard.style.display = "none";
  findCard.style.display = "none";
  const items = (r.items || []).map(i => h("li", {}, h("span", { text: i.text }), h("sup", { class: "rc-n", text: i.n })));
  const ev = (r.evidence || []).length ? h("details", { class: "rc-ev" },
    h("summary", { text: `근거 · 기록 ${r.evidence.length}건` }),
    r.evidence.map(e => h("div", { class: "rc-row" },
      h("span", { class: "rc-n", text: e.n }),
      h("span", { class: "t" }, h("span", { text: e.summary }),
        (e.excerpt || []).length ? h("span", { class: "block-sub", text: ` — ${e.excerpt.join(" / ")}` }) : null),
      h("span", { class: "d", text: e.ts }),
      h("button", { class: "mini-btn", type: "button", "aria-label": `기록 ${e.n} 열기`, text: "↗",
        onclick: () => openRecord(e.id, e.day) })))) : null;
  const chips = h("div", { class: "chip-row" },
    (r.followups || []).filter(f => f !== q).map(f => h("button", { class: "mini-btn", type: "button", text: f,
      onclick: () => runRecall(f) })),
    r.found ? h("button", { class: "mini-btn", type: "button", text: "메모로 저장", onclick: () =>
      capture("text", "답변 메모", [r.headline, ...r.items.map(i => `${i.text} [${i.n}]`)].join("\n"), 0) }) : null);
  fill(recallCard,
    cardTop(recallCard, q), h("div", { class: "rc-head", text: r.headline }),
    items.length ? h("ul", { class: "rc-list" }, items) : null, ev, chips,
    r.note ? h("div", { class: "rc-foot", text: r.note }) : null);
  recallCard.style.display = "flex";
  recallShown = true;
  hideSendCard();
}

/* F · 파일 찾기: 결과 경로는 서버만 쥐고 화면에는 번호만 오간다 */
let findRes = null, findSel = 1, findMissing = false, findBusy = false, findAll = false;
const FIND_FOLD = 5;  // 처음엔 5개만: 나머지는 눌러서 펼친다
function fdRow(it) {
  const sel = it.rank === findSel;
  const why = [...(it.reasons || []), ...(it.flags || []).filter(f => f !== "내려받기 필요")].join(" · ");
  return h("div", { class: "fd-item" },
    h("button", { class: "fd-row" + (sel ? " sel" : ""), type: "button", role: "option", "aria-selected": sel ? "true" : "false",
        "data-rank": it.rank, onclick: () => { findSel = it.rank; renderFind(); },
        ondblclick: () => findOpen(it.rank, it.dataless) },
      h("span", { class: "fd-glyph", "aria-hidden": "true", text: it.ext }),
      h("span", { class: "fd-copy" },
        h("span", { class: "fd-name", text: it.name }),
        h("span", { class: "fd-where", text: it.where }),
        why ? h("span", { class: "fd-why", text: why }) : null,
        it.dataless ? h("span", { class: "fd-flag", text: "내려받기 필요" }) : null,
        it.snippet ? h("span", { class: "fd-snip", text: it.snippet }) : null),
      h("span", { class: "fd-n", text: it.rank })),
    (it.siblings || []).map(s => h("div", { class: "fd-sib", text: `↳ 비슷한 파일 · ${s.name}${s.modified ? " · 수정 " + s.modified : ""}` })),
    sel ? h("div", { class: "fd-actions fd-row-actions" },
      it.dataless
        ? h("button", { class: "mini-btn primary", type: "button", text: "Finder에서 보기", onclick: () => findOpen(it.rank, true) })
        : [h("button", { class: "mini-btn primary", type: "button", text: "열기  ↵", onclick: () => findOpen(it.rank, false) }),
           h("button", { class: "mini-btn", type: "button", text: "Finder에서 보기", onclick: () => findOpen(it.rank, true) })]) : null);
}
async function runFind(q, body) {
  q = String(q || "").trim();
  if (!q) { askInput.value = "/파일 "; askInput.focus(); return; }
  pushRecent(q);
  setBubbleOpen(true);
  switchTab("home");
  recallCard.style.display = "none";
  recOrgCard.style.display = "none";
  recallShown = false;
  hideSendCard();
  findRes = null; findSel = 1; findMissing = false; findBusy = true; findAll = false;
  fill(findCard, cardTop(findCard, q), h("div", { class: "rc-head", text: "찾는 중…" }),
    h("div", { class: "block-sub", text: "이름·종류·기간을 먼저 보고, 없으면 내용까지 봐요." }));
  findCard.style.display = "flex";
  findCard.scrollIntoView({ block: "start" });  // 홈 위쪽 통계 대신 결과가 먼저 보이게
  let r = null;
  try { r = await apiPost("/api/find", body === undefined ? { question: q } : { question: q, body }); } catch (err) { r = null; }
  findBusy = false;
  findRes = r || { ok: false, error: "서버에 연결하지 못했어요." };
  if (findRes.ok && findRes.items.length) findSel = findRes.items[0].rank;
  else if (findRes.ok && findRes.relaxed.length) findSel = findRes.relaxed[0].items[0].rank;
  findMissing = !!(findRes.ok && !findRes.items.length);
  renderFind();
  findCard.scrollIntoView({ block: "start" });  // 결과가 길어도 맨 위(제목·첫 결과)부터
}
function renderFind() {
  const r = findRes;
  if (!r) return;
  if (!r.ok) {
    fill(findCard, cardTop(findCard), h("div", { class: "rc-head", text: "찾지 못했어요" }), h("div", { class: "block-sub", text: r.error || "다시 시도해 주세요." }));
    return;
  }
  const groups = r.relaxed || [];
  const all = [...r.items, ...groups.flatMap(g => g.items)];
  const sel = all.find(i => i.rank === findSel) || null;
  const head = r.items.length
    ? (r.body ? "내용까지 보고 찾았어요" : `후보 ${r.n}개를 찾았어요`)
    : (r.body ? "이름도 내용도 못 찾았어요" : "못 찾았어요");
  const shown = findAll ? r.items : r.items.filter(i => i.rank <= FIND_FOLD || i.rank === findSel);
  const hidden = r.items.length - shown.length;
  const moreBtn = !r.body
    ? h("button", { class: "mini-btn", type: "button", text: "내용까지 보기", onclick: () => runFind(r.query, true) }) : null;
  fill(findCard,
    cardTop(findCard, r.query),
    h("div", { class: "rc-head", text: head }),
    (r.notes || []).slice(0, 3).map(n => h("div", { class: "fd-note" }, h("span", { "aria-hidden": "true", text: "ⓘ" }), h("span", { text: n }))),
    r.items.length ? h("div", { class: "fd-list", role: "listbox", "aria-label": "찾은 파일" }, shown.map(fdRow)) : null,
    hidden > 0 ? h("button", { class: "link-btn", type: "button", text: `나머지 ${hidden}개 보기`, onclick: () => { findAll = true; renderFind(); } }) : null,
    groups.map(g => h("div", { class: "fd-list" },
      h("div", { class: "fd-sub", text: g.message }), h("div", { role: "listbox", "aria-label": g.message }, g.items.map(fdRow)))),
    moreBtn ? h("div", { class: "fd-actions" }, moreBtn) : null,
    findMissing || !all.length ? findMissingBlock(r) : h("button", { class: "link-btn", type: "button", text: "원하는 파일이 없어요",
      onclick: () => { findMissing = true; renderFind(); } }),
    r.consent && all.length ? findConsentCard() : null,
    h("div", { class: "rc-foot", text: `${r.ms}ms · Downloads · Documents · Desktop · iCloud Drive 안에서만 찾아요. 비밀 파일은 보지 않아요.` }));
  findCard.style.display = "flex";
}
function findMissingBlock(r) {
  const box = h("div", { class: "fd-consent" });
  box.append(h("div", { class: "fd-sub", text: "원하는 파일이 없었나요?" }));
  if (r.recording) {
    const input = h("input", { class: "fd-input", type: "text", "aria-label": "찾던 파일 경로", autocomplete: "off",
      placeholder: "찾던 파일 경로 (Finder에서 선택 후 ⌥⌘C로 복사)" });
    const send = h("button", { class: "mini-btn primary", type: "button", text: "알려 주기", onclick: async () => {
      const path = input.value.trim();
      if (!path) { input.focus(); return; }
      let res = null;
      try { res = await apiPost("/api/find/pick", { rank: null, answer: path }); } catch (err) { res = null; }
      const msg = !res ? "서버에 연결하지 못했어요." : !res.ok ? res.error
        : res.found_rank ? `목록 ${res.found_rank}번에 있었어요. 기억했어요.` : "목록에 없던 파일이에요. 기억했어요.";
      showToast([h("div", { class: "toast-head", text: msg })], 4500);
      if (res && res.ok) { input.value = ""; findMissing = false; renderFind(); }
    } });
    box.append(h("div", { class: "block-sub", text: "알려 주시면 다음부터 더 잘 찾아요. 기록은 이 컴퓨터에만 남아요." }),
      h("div", { class: "fd-input-row" }, input, send));
  } else {
    box.append(h("div", { class: "block-sub", text: "고른 걸 기억하면 찾던 파일을 알려 줄 수 있어요. (지금은 꺼져 있어요)" }),
      h("div", { class: "fd-actions" }, h("button", { class: "mini-btn primary", type: "button", text: "기억하기 켜기", onclick: () => findSignals(true) })));
  }
  return box;
}
function findConsentCard() {
  return h("div", { class: "fd-consent", role: "region", "aria-label": "고른 걸 기억할까요?" },
    h("div", { class: "rc-head", text: "고른 걸 기억할까요?" }),
    h("div", { class: "block-sub", text: "찾은 뒤 어떤 결과를 열었는지만 기록해서, 자주 쓰는 폴더나 내가 부르는 말을 배워요." }),
    h("ul", {}, h("li", { text: "질문 원문과 파일 내용은 저장하지 않아요" }), h("li", { text: "이 컴퓨터 밖으로 나가지 않아요" }),
      h("li", { text: "언제든 끄고 지울 수 있어요 (ro find-signals off · clear)" })),
    h("div", { class: "fd-actions" },
      h("button", { class: "mini-btn primary", type: "button", text: "기억하기 켜기", onclick: () => findSignals(true) }),
      h("button", { class: "mini-btn", type: "button", text: "나중에", onclick: () => findSignals(null) })),
    h("div", { class: "block-sub", text: "배운 건 제안으로만 보여 줘요. 승인한 것만 반영돼요." }));
}
async function findSignals(on) {
  let r = null;
  try { r = await apiPost("/api/find/signals", on === null ? { later: true } : { on }); } catch (err) { r = null; }
  if (findRes && findRes.ok && r && r.ok) { findRes.consent = false; findRes.recording = on === true ? true : findRes.recording; renderFind(); }
  if (on === true) showToast([h("div", { class: "toast-head", text: r && r.ok ? "기억하기를 켰어요" : "켜지 못했어요" }),
    h("div", { class: "block-sub", text: "끄기: ro find-signals off · 지우기: ro find-signals clear" })], 4500);
}
async function findOpen(rank, reveal) {
  let r = null;
  try { r = await apiPost("/api/find/open", { rank, reveal: !!reveal }); } catch (err) { r = null; }
  showToast([h("div", { class: "toast-head", text: !r ? "서버에 연결하지 못했어요." : !r.ok ? r.error
    : reveal ? "Finder에서 보여 드렸어요" : "열었어요" })], r && r.ok ? 2200 : 5500);
}
window.addEventListener("keydown", (e) => {
  if (findCard.style.display === "none" || !findRes || !findRes.ok || !palette.hidden || e.metaKey || e.ctrlKey || e.altKey) return;
  const a = document.activeElement;
  if (a && a !== document.body && !(a === askInput && !askInput.value) && !(a.classList && a.classList.contains("fd-row"))) return;
  const ranks = [...findRes.items, ...(findRes.relaxed || []).flatMap(g => g.items)].map(i => i.rank);
  const at = ranks.indexOf(findSel);
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!ranks.length) return;
    e.preventDefault();
    findSel = ranks[Math.max(0, Math.min(ranks.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
    renderFind();
  } else if (e.key === "Enter" && ranks.length && !(a && a.tagName === "BUTTON" && !a.classList.contains("fd-row"))) {
    const it = [...findRes.items, ...(findRes.relaxed || []).flatMap(g => g.items)].find(i => i.rank === findSel);
    if (it) { e.preventDefault(); findOpen(it.rank, it.dataless); }
  }
});
document.getElementById("sendFindBtn").addEventListener("click", () => {
  const q = pendingSend && pendingSend.q;
  hideSendCard();
  if (q) runFind(q);
});

/* D · 미리 보고 되돌리는 정리 */
async function showRecordOrganize() {
  const p = await apiPost("/api/records/plan", {});
  setBubbleOpen(true);
  switchTab("home");
  recallCard.style.display = "none";
  const max = Math.max(1, ...p.groups.map(g => g.count));
  const picks = {};
  const amb = p.ambiguous.length ? h("div", { class: "rec-org-amb" },
    h("div", { class: "rec-org-line" }, h("span", {}, h("i", { class: "rec-org-dot" }), `확인 필요`), h("span", { text: `${p.ambiguous.length}건 골라주기` })),
    p.ambiguous.slice(0, 8).map(a => {
      const s = h("select", { "aria-label": `${a.summary} 분류` }, h("option", { value: "", text: "고르기" }),
        a.candidates.map(c => h("option", { value: c, text: c })));
      s.addEventListener("change", () => { picks[a.id] = s.value; });
      return h("label", {}, h("div", { text: a.summary }), s);
    })) : null;
  const apply = h("button", { class: "mini-btn primary", type: "button", text: "적용하기", onclick: async () => {
    const r = await apiPost("/api/records/apply", { picks });
    if (!r.ok) { recOrgCard.replaceChildren(h("div", { class: "rc-head", text: r.error || "적용하지 못했어요" })); return; }
    recOrgCard.replaceChildren(h("div", { class: "rc-head", text: `적용했어요 · ${r.applied}건` }),
      h("button", { class: "mini-btn", type: "button", text: "되돌리기", onclick: async () => {
        const u = await apiPost("/api/records/undo", {});
        recOrgCard.replaceChildren(h("div", { class: "rc-head", text: u.ok ? `되돌렸어요 · ${u.reverted}건` : (u.error || "되돌리지 못했어요") }));
      } }),
      h("div", { class: "rc-foot", text: "적용해도 24시간 안에 한 번에 되돌릴 수 있어요" }));
  } });
  const cancel = h("button", { class: "mini-btn", type: "button", text: "취소", onclick: () => { recOrgCard.style.display = "none"; } });
  fill(recOrgCard,
    h("div", { class: "rc-head", text: "이렇게 묶을게요" }),
    h("div", { class: "rc-foot", text: `기록 ${p.total}건 → 프로젝트 ${p.groups.length}개. 아직 아무것도 바뀌지 않았어요.` }),
    ...p.groups.map(g => h("div", { class: "rec-org-row" },
      h("div", { class: "rec-org-line" }, h("span", { text: g.project }), h("span", { text: `${g.count}건` })),
      h("div", { class: "rec-org-bar", style: `width:${Math.round(g.count / max * 100)}%` }))),
    amb,
    h("div", { class: "chip-row" }, apply, cancel),
    h("div", { class: "rc-foot", text: "적용해도 24시간 안에 한 번에 되돌릴 수 있어요" }));
  recOrgCard.style.display = "flex";
}

/* B · ⌥R 팔레트 */
// arg: 내용이 꼭 필요함 · hint: 뒤에 쓸 내용(있으면 고를 때 '/명령 '까지만 채운다) · aliases: 다른 이름(영문·한글)
const COMMANDS = [
  { id: "record", label: "/기록", desc: "지금 한 일 한 줄로 남기기", arg: true, hint: "내용", aliases: ["record", "note"] },
  { id: "file", label: "/파일", desc: "내 파일 찾기 (이름·내용·기간)", arg: true, hint: "검색어", aliases: ["file"] },
  { id: "find", label: "/찾기", desc: "지난 기록에서 검색", arg: true, hint: "검색어", aliases: ["find", "search"] },
  { id: "today", label: "/오늘", desc: "오늘 요약 보기", aliases: ["today"] },
  { id: "organize", label: "/분류", desc: "흩어진 기록을 프로젝트별로 분류 (파일 정리는 '정리' 탭)", aliases: ["organize", "정리"] },
  { id: "focus", label: "/집중", desc: "집중 모드 켜고 끄기", aliases: ["focus"] },
  { id: "activity", label: "/활동기록", desc: "활동 기록 켜기·끄기·상태 (앞 앱·웹 AI 탭 제목만)", aliases: ["activity", "기록켜기"] },
  { id: "learned", label: "/배운것", desc: "ro가 배운 것 보기·고정·끄기·지우기, 학습·먼저 알림 동의", aliases: ["learned", "학습", "배운 것"] },
  { id: "space", label: "/용량", desc: "죽은 빌드 폴더·남은 설치 파일·iCloud 사본 정리 카드 열기", aliases: ["space", "builds", "용량정리"] },
  { id: "fileorg", label: "/파일정리", desc: "다운로드 파일 정리 확인 카드 열기(C안 · 저널 V2 되돌리기)", aliases: ["fileorg", "카드정리"] },
  { id: "connect", label: "/연결", desc: "Claude·Codex·Antigravity 연결 상태", aliases: ["connect", "ai"] },
  { id: "relay", label: "/이어가기", desc: "하던 작업을 다른 AI로 인수인계 (예: /이어가기 agy claude)", hint: "원래 도구 받을 도구", aliases: ["handoff", "갈아타기", "인수인계"] },
  { id: "claude", label: "/claude", desc: "Claude Code로 넘기기 (클립보드 + 앱 열기)", hint: "질문", engine: true, aliases: ["클로드"] },
  { id: "codex", label: "/codex", desc: "Codex로 넘기기 (클립보드 + 앱 열기)", hint: "질문", engine: true, aliases: ["코덱스"] },
  { id: "agy", label: "/agy", desc: "Antigravity로 넘기기 (클립보드 + 앱 열기)", hint: "질문", engine: true, aliases: ["antigravity", "안티그래비티", "안티"] },
];
/* 영어 화면에서는 명령 이름도 영어로 보인다. 한글 이름은 별칭으로 남아 그대로 통한다 */
if (RoI18n.lang === "en") {
  const EN = { record: "/log", file: "/file", find: "/find", today: "/today", organize: "/sort", focus: "/focus",
               activity: "/activity", learned: "/learned", space: "/space", fileorg: "/tidycard", connect: "/connect", relay: "/handoff" };
  for (const c of COMMANDS) {
    if (!EN[c.id]) continue;
    c.aliases = [c.label.slice(1), ...(c.aliases || [])];
    c.label = EN[c.id];
  }
}
/* 한글 명령은 초성(ㄱㄹ → 기록)과 조합 중인 글자(기로 → 기록)로도 찾는다 */
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
function syl(ch) {
  const c = ch.charCodeAt(0) - 0xAC00;
  return c >= 0 && c < 11172 ? { cho: Math.floor(c / 588), jung: Math.floor(c / 28) % 21, jong: c % 28 } : null;
}
function namePrefix(q, name) {
  if (q.length > name.length) return false;
  for (let i = 0; i < q.length; i++) {
    const a = q[i], b = name[i];
    if (a === b) continue;
    const sb = syl(b), sa = syl(a);
    if (sb && CHO.indexOf(a) === sb.cho) continue;
    if (i === q.length - 1 && sa && sb && !sa.jong && sa.cho === sb.cho && sa.jung === sb.jung) continue;
    return false;
  }
  return true;
}
function cmdNames(c) { return [c.label.slice(1), ...(c.aliases || [])].map(n => n.toLowerCase()); }
function matchCommands(name) {
  const q = (name || "").toLowerCase();
  if (!q) return COMMANDS.slice();
  return COMMANDS.filter(c => cmdNames(c).some(n => namePrefix(q, n)))
    .sort((a, b) => (cmdNames(b).includes(q) ? 1 : 0) - (cmdNames(a).includes(q) ? 1 : 0));
}
function resolveCommand(name) {
  const q = (name || "").toLowerCase();
  return COMMANDS.find(c => cmdNames(c).includes(q)) || null;
}
// 내 기록을 묻는 말만 로컬 회상으로 보낸다. '오늘'·'어제'만 붙은 일반 요청("오늘 alpha 구조 설명해줘")은 질문이다
// 파일을 찾는 말: 찾는 동사와 파일 명사가 함께 있을 때만. "이 파일 설명해줘" 같은 질문은 그대로 엔진 확인으로 간다
const FIND_VERB = /(찾아\s*줘|찾아줘|찾아\s*봐|찾고\s*있|찾는|어디\s*(있|갔|에\s*있)|어딨|있더라|뭐였더라|\bfind\b|\blocate\b|look(ing)?\s+for|where('s|\s+is|\s+are|\s+did))/i;
const FIND_NOUN = /(파일|문서|자료|보고서|계약서|사진|이미지|스크린샷|pdf|xlsx?|docx?|pptx?|hwpx?|엑셀|ppt|한글|files?|documents?|docs?|reports?|contracts?|photos?|images?|screenshots?|spreadsheets?|slides?)/i;
const NOT_FILE = /(기록|로그|커밋|한\s*일|\blogs?\b|\bcommits?\b|\bnotes?\b)/i;
/* 질문·부탁으로 읽히는 입력만 안내 카드로 보낸다. 그 밖의 평문은 바로 기록한다(토스트에서 되돌릴 수 있다) */
const ASK_INTENT = /[?？]\s*$|(뭐|무엇|무슨|어떻게|어떡|왜|언제|어디|누구|누가|몇|얼마)|(알려\s*줘|알려\s*주|설명해|해\s*줘|해\s*주세요|해\s*줄래|할\s*수\s*있)|^\s*(what|why|how|when|where|who|which|can|could|would|should|is|are|do|does|did|please|explain|tell me|show me|help)\b/i;
const RECALL_INTENT = /(뭐\s*했|무엇을\s*했|했[어지니나]\s*\??$|한\s*일|기록(에서|을|\s*찾|\s*보)|찾아\s*줘|찾기|what did i\b|did i (do|work|log)|(in|search) my (logs?|notes?|records?))/i;
let palIndex = 0, palRows = [], lastFocus = null;
function recentList() {
  try { return JSON.parse(localStorage.getItem("ro.recent") || "[]"); } catch (e) { return []; }
}
function pushRecent(q) {
  try { localStorage.setItem("ro.recent", JSON.stringify([q, ...recentList().filter(x => x !== q)].slice(0, 5))); } catch (e) {}
}
function parsePalette(raw) {
  const t = raw.replace(/^\s+/, "");
  const m = t.match(/^\/(\S*)\s*(.*)$/s);
  return m ? { slash: true, name: m[1], arg: m[2].trim() } : { slash: false, text: t.trim() };
}
function buildRows() {
  const p = parsePalette(palInput.value);
  const rows = [];
  if (p.slash) {
    matchCommands(p.name).forEach(c => rows.push({ sec: "명령", cmd: c, arg: p.arg }));
  } else if (!p.text) {
    COMMANDS.forEach(c => rows.push({ sec: "명령", cmd: c }));
    recentList().forEach(q => rows.push({ sec: "최근 입력", ask: q }));
  } else {
    rows.push({ sec: "입력", ask: p.text });
  }
  return rows;
}
function renderPalette() {
  palRows = buildRows();
  palIndex = Math.min(palIndex, Math.max(0, palRows.length - 1));
  palList.replaceChildren();
  let sec = null;
  palRows.forEach((r, i) => {
    if (r.sec !== sec) { sec = r.sec; palList.append(h("div", { class: "pal-sec", role: "presentation", text: sec })); }
    const item = h("div", { class: "pal-item", role: "option", id: `palOpt${i}`, "aria-selected": i === palIndex ? "true" : "false",
      onmousedown: (e) => { e.preventDefault(); palIndex = i; runPalette(); } },
      r.cmd ? [h("b", { text: r.cmd.label }), h("span", { text: r.cmd.desc })] : [h("b", { text: r.sec === "입력" ? "입력" : "다시" }), h("span", { text: r.ask })]);
    palList.append(item);
  });
  palInput.setAttribute("aria-activedescendant", palRows.length ? `palOpt${palIndex}` : "");
}
function openPalette() {
  if (!palette.hidden) return;
  lastFocus = document.activeElement;
  palette.hidden = false;
  palInput.value = "";
  palIndex = 0;
  renderPalette();
  palInput.focus();
}
function closePalette() {
  if (palette.hidden) return;
  palette.hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}
window.openPaletteFromHost = function() {
  setBubbleOpen(true);
  if (!document.body.classList.contains("edition-mini")) openPalette();  // 꾸미기 에디션에는 팔레트가 없다
};
/* 팔레트와 하단 입력창이 같은 명령 해석·실행을 쓴다. 반환: 처리 성공 여부 */
async function runCommand(c, arg) {
  if (c.id === "record") return capture("text", "직접 기록", arg, arg.length);
  if (c.id === "organize") await showRecordOrganize();
  else if (c.id === "today") await runRecall("오늘 뭐 했지?");
  else if (c.id === "find") await runRecall(`${arg} 기록 찾아줘`);
  else if (c.id === "file") await runFind(arg);
  else if (c.id === "focus") { await apiPost("/api/focus", { on: !(ambient && ambient.focus) }); await refreshState(); }
  else if (c.id === "connect") await openConn(arg || "");
  else if (c.id === "activity") await activityCard("status");
  else if (c.id === "learned") await learnedCard({ op: "list" });
  else if (c.id === "space") await openStageOp("disk");
  else if (c.id === "fileorg") await openStageOp("organize");
  else if (c.id === "relay") return relayPlan(arg || "");
  else if (c.engine) return handoffTo(c.id, arg || "");
  return true;
}
async function runPalette() {
  const r = palRows[palIndex];
  if (!r) return;
  if (r.cmd) {
    const c = r.cmd;
    if (c.arg && !r.arg) { palInput.value = c.label + " "; renderPalette(); return; }
    closePalette();
    await runCommand(c, r.arg);
    return;
  }
  closePalette();
  pushRecent(r.ask);
  await submitInput(r.ask);
}
palInput.addEventListener("input", () => { palIndex = 0; renderPalette(); });
window.addEventListener("keydown", (e) => {
  if (e.altKey && e.code === "KeyR" && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    e.stopImmediatePropagation();
    if (palette.hidden) window.openPaletteFromHost(); else closePalette();
    return;
  }
  if (palette.hidden) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); closePalette(); }
  else if (e.key === "ArrowDown") { e.preventDefault(); palIndex = (palIndex + 1) % Math.max(1, palRows.length); renderPalette(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); palIndex = (palIndex - 1 + palRows.length) % Math.max(1, palRows.length); renderPalette(); }
  else if (e.key === "Enter") { e.preventDefault(); if (!e.isComposing && e.keyCode !== 229) runPalette(); }
  else if (e.key === "Tab") { e.preventDefault(); }
}, true);

/* 입력창 '/' 자동완성: 팔레트와 같은 명령 목록·실행. 이름을 쓰는 동안 목록, 내용을 쓰는 동안 그 명령 한 줄 */
const slashPop = document.getElementById("slashPop");
let slashRows = [], slashSel = 0;
function slashState() {
  const v = askInput.value;
  if (!/^\s*\//.test(v)) return null;
  const p = parsePalette(v);
  const naming = !/^\s*\/\S*\s/.test(v);
  const rows = naming ? matchCommands(p.name) : [resolveCommand(p.name)].filter(Boolean);
  return { naming, rows, arg: p.arg };
}
function hideSlash() {
  if (slashPop.hidden) return;
  slashPop.hidden = true;
  askInput.setAttribute("aria-expanded", "false");
  askInput.removeAttribute("aria-activedescendant");
}
function renderSlash() {
  const st = document.activeElement === askInput ? slashState() : null;
  if (!st || !st.rows.length) {
    if (st && st.naming) {  // 맞는 명령이 없으면 그렇다고 알린다(입력은 그대로 일반 입력으로 처리된다)
      fill(slashPop, h("div", { class: "pal-item", role: "option", "aria-disabled": "true" },
        h("span", { text: "맞는 명령이 없어요 · ↵ 그대로 보내기" })));
      slashPop.hidden = false;
      askInput.setAttribute("aria-expanded", "true");
      return;
    }
    hideSlash();
    return;
  }
  slashRows = st.rows;
  slashSel = Math.min(slashSel, slashRows.length - 1);
  fill(slashPop, slashRows.map((c, i) => h("div", { class: "pal-item", role: "option", id: `slashOpt${i}`,
      "aria-selected": i === slashSel ? "true" : "false",
      onmousedown: (e) => { e.preventDefault(); slashSel = i; pickSlash(false); } },
    h("b", { text: c.label }), h("span", { text: c.desc }),
    c.hint && !(st.arg && !st.naming) ? h("i", { text: `+ ${c.hint}` }) : null)),
    h("div", { class: "pal-foot", "aria-hidden": "true" },
      st.naming ? [h("span", {}, h("kbd", { text: "↑↓" }), " 고르기"), h("span", {}, h("kbd", { text: "tab" }), " 완성"),
                   h("span", {}, h("kbd", { text: "↵" }), " 실행"), h("span", {}, h("kbd", { text: "esc" }), " 닫기")]
               : [h("span", {}, h("kbd", { text: "↵" }), slashRows[0].arg && !st.arg ? ` ${slashRows[0].hint}을(를) 써 주세요` : " 실행")]));
  slashPop.hidden = false;
  askInput.setAttribute("aria-expanded", "true");
  askInput.setAttribute("aria-activedescendant", `slashOpt${slashSel}`);
  const sel = document.getElementById(`slashOpt${slashSel}`);
  if (sel) {  // 목록 안에서만 스크롤한다(scrollIntoView는 열리는 중인 말풍선까지 움직여 목록이 맨 아래로 가기도 했다)
    const foot = slashPop.querySelector(".pal-foot");
    const view = slashPop.clientHeight - (foot ? foot.offsetHeight : 0);
    if (sel.offsetTop < slashPop.scrollTop) slashPop.scrollTop = sel.offsetTop - 4;
    else if (sel.offsetTop + sel.offsetHeight > slashPop.scrollTop + view) slashPop.scrollTop = sel.offsetTop + sel.offsetHeight - view;
  }
}
function setAsk(v) {
  askInput.value = v;
  askInput.dispatchEvent(new Event("input"));
  askInput.setSelectionRange(v.length, v.length);
}
/* run=false: 완성만(Tab·클릭) · run=true: 내용이 필요 없으면 바로 실행(↵) */
async function pickSlash(run) {
  const st = slashState();
  const c = slashRows[slashSel];
  if (!st || !c) return;
  if (!st.naming) return;
  if (c.hint || !run) { setAsk(c.label + " "); askInput.focus(); return; }
  resetInput();
  hideSlash();
  await runCommand(c, "");
}
askInput.addEventListener("input", () => { slashSel = 0; slashPop.scrollTop = 0; renderSlash(); });
askInput.addEventListener("focus", renderSlash);
askInput.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== askInput) hideSlash(); }, 0));
askInput.addEventListener("keydown", (e) => {
  if (slashPop.hidden || e.isComposing || e.keyCode === 229 || e.altKey || e.metaKey || e.ctrlKey) return;
  const st = slashState();
  if (!st) return;
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); hideSlash(); return; }
  if (!st.naming || !slashRows.length || !st.rows.length) return;  // 내용을 쓰는 중: ↵는 보통 제출
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault(); e.stopPropagation();
    slashSel = (slashSel + (e.key === "ArrowDown" ? 1 : -1) + slashRows.length) % slashRows.length;
    renderSlash();
  } else if (e.key === "Tab") {
    e.preventDefault(); e.stopPropagation(); pickSlash(false);
  } else if (e.key === "Enter") {
    e.preventDefault(); e.stopPropagation(); pickSlash(true);
  }
});

/* AI 도구 연결 창 */
const connWin = document.getElementById("connWin");
const connList = document.getElementById("connList");
const connPending = document.getElementById("connPending");
let connText = "", connFocus = null;
function connChip(on, text, title) {
  return h("span", { class: on ? "conn-chip on" : "conn-chip", title, text: `${on ? "✓" : "–"} ${text}` });
}
const RULES_TEXT = { source: "규칙 원본", linked: "규칙 연결", other: "따로 쓰는 규칙", missing: "규칙 없음" };
const HOOK_TEXT = { on: "안전 훅", missing: "안전 훅 없음", stale: "안전 훅 갱신 필요", broken: "안전 훅 작동 안 함" };
/* 연결할 항목이 있으면 설정 탭과 연결 버튼에 숫자를 단다(알림은 띄우지 않는다) */
function setConnBadge(n) {
  for (const el of [document.getElementById("tabBtnSettings"), document.getElementById("connOpenBtn")]) {
    let b = el.querySelector(".conn-badge");
    if (!el.dataset.label) el.dataset.label = el.textContent.trim();
    if (!n) { if (b) b.remove(); el.removeAttribute("aria-label"); continue; }
    if (!b) { b = h("span", { class: "conn-badge", "aria-hidden": "true" }); el.append(b); }
    b.textContent = n;
    el.setAttribute("aria-label", `${el.dataset.label}, 연결할 항목 ${n}개`);  // 숫자만 붙여 "설정1"로 읽히지 않게
  }
}
async function checkConnect() {
  if (document.body.classList.contains("edition-mini")) return null;  // 꾸미기 에디션은 서버가 연결 기능을 닫아 둔다
  let p = null;
  try { p = await apiPost("/api/engines/plan", {}); } catch (err) { p = null; }
  setConnBadge(p && p.ok ? p.items.length : 0);
  return p && p.ok ? p : null;
}
/* 서버 안내문의 `명령`은 백틱째 보이지 않게 코드 글씨로 바꾼다 */
function codeText(s) {
  return String(s).split("`").map((part, i) => i % 2 ? h("code", { text: part }) : part);
}
function connPlanBox(p) {
  if (!p) return null;
  const src = p.source ? h("div", { class: "conn-note" }, `공통 규칙 원본: `, h("code", { text: p.source }),
    ` · 바꾸려면 터미널에서 `, h("code", { text: "ro connect --source 파일" })) : null;
  if (!p.items.length) {
    return h("div", { class: "conn-note" }, p.notes.length ? p.notes.map(n => h("div", {}, codeText(n))) :
      h("div", { text: "설치된 도구는 모두 연결돼 있어요." }), src);
  }
  const go = h("button", { class: "mini-btn primary", type: "button", text: "승인하고 연결", onclick: async () => {
    go.disabled = true;
    let r = null;
    try { r = await apiPost("/api/engines/connect", { id: p.id, approve: true }); } catch (err) { r = null; }
    if (!r || !r.ok) {
      showToast([h("div", { class: "toast-head", text: r ? (r.error || "연결하지 못했어요") : "서버에 연결하지 못했어요." })], 5500);
      await openConn(connText);  // 바뀐 상태로 다시 보여 준다
      return;
    }
    closeConn();  // 창이 토스트의 되돌리기를 가리지 않게
    await checkConnect();
    showToast([h("div", { class: "toast-head", text: `연결했어요 · ${r.applied}건` }),
      h("div", { class: "block-sub", text: "/연결에서 상태를 다시 볼 수 있어요" }),
      h("div", { class: "chip-row" }, h("button", { class: "mini-btn", type: "button", text: "되돌리기", onclick: undoConnect }))], 8000);
  } });
  return h("div", { class: "conn-plan", role: "region", "aria-label": "연결할 항목" },
    h("div", { class: "conn-name", text: `연결할 항목 ${p.items.length}개 · 아직 아무것도 바뀌지 않았어요` }),
    h("ul", {}, p.items.map(it => h("li", { title: it.path, text: it.desc }))),
    p.notes.map(n => h("div", { class: "conn-note" }, codeText(n))), src,
    h("div", { class: "conn-note", text: "되돌리기는 ro가 넣은 줄·훅·링크만 빼요. 그 뒤에 바뀐 설정은 그대로 둬요." }),
    h("div", { class: "chip-row" }, go));
}
async function undoConnect() {
  let r = null;
  try { r = await apiPost("/api/engines/undo", {}); } catch (err) { r = null; }
  const kept = r && r.kept && r.kept.length ? ` · 그사이 바뀐 ${r.kept.length}개는 그대로 둠` : "";
  showToast([h("div", { class: "toast-head", text: !r ? "서버에 연결하지 못했어요." : r.ok ? `되돌렸어요 · ${r.reverted}건${kept}` : r.error })], 5500);
  if (!connWin.hidden) await openConn(connText); else await checkConnect();
}
async function openConn(text) {
  connText = (text || "").trim();
  if (connWin.hidden) connFocus = document.activeElement;
  setBubbleOpen(true);
  hideSlash();
  connWin.hidden = false;
  connPending.hidden = !connText;
  connPending.textContent = connText ? `넘길 내용: “${connText}”` : "";
  fill(connList, h("div", { class: "rc-foot", text: "확인하는 중…" }));
  let r = null;
  try { r = await apiPost("/api/engines", {}); } catch (err) { r = null; }
  if (!r || !r.ok) { fill(connList, h("div", { class: "rc-head", text: "서버에 연결하지 못했어요." })); return; }
  const plan = await checkConnect();
  fill(connList, connPlanBox(plan), r.engines.map(e => {
    const usable = e.app || e.cli;
    const btn = h("button", { class: connText ? "mini-btn primary" : "mini-btn", type: "button", disabled: !usable,
      "aria-label": `${e.name} ${connText ? "로 넘기기" : "열기"}`,
      text: !usable ? "없음" : connText ? "넘기기" : (e.app ? "열기" : "명령 복사"),
      onclick: async () => { closeConn(); await handoffTo(e.id, connText); } });
    return h("div", { class: "conn-row" },
      h("div", { class: "conn-main" },
        h("div", { class: "conn-name", text: e.name }),
        h("div", { class: "conn-chips" },
          connChip(e.app, e.app ? "앱" : "앱 없음", e.app || "응용 프로그램 폴더에 없음"),
          connChip(e.cli, `CLI ${e.cli_name}`, e.cli ? "터미널에서 실행 가능" : "PATH에 없음"),
          connChip(e.rules, RULES_TEXT[e.rules_state] || "규칙", e.rules_path),
          e.hook === null ? null : connChip(e.hook, HOOK_TEXT[e.hook_state] || "안전 훅",
            "위험한 명령 문자열을 찾아 승인을 묻는 보조 장치(모든 우회를 막지는 못함)"))),
      btn);
  }));
  const first = connList.querySelector(".conn-plan button") || connList.querySelector("button:not([disabled])");
  if (first) first.focus();
}
document.getElementById("connCloseBtn").addEventListener("click", (e) => { e.stopPropagation(); closeConn(); });
function closeConn() {
  if (connWin.hidden) return;
  connWin.hidden = true;
  if (connFocus && connFocus.focus) connFocus.focus();
}
async function handoffTo(id, text) {
  let r = null;
  try { r = await apiPost("/api/engines/handoff", { id, text }); } catch (err) { r = null; }
  if (!r || !r.ok) {
    showToast([h("div", { class: "toast-head", text: r ? (r.error || "넘기지 못했어요") : "서버에 연결하지 못했어요." })], 5500);
    return false;
  }
  const head = r.mode === "cli" ? "터미널에 붙여 넣을 명령을 복사했어요" : `${r.name}을(를) 열었어요`;
  const sub = (r.mode === "cli" ? "터미널에서 ⌘V 후 ↵" : r.copied ? "입력을 복사했어요 · ⌘V로 붙여 넣으세요" : "")
    + (r.masked ? " · 비밀값으로 보이는 부분은 가렸어요" : "");
  showToast([h("div", { class: "toast-head", text: head }), sub ? h("div", { class: "block-sub", text: sub.replace(/^ · /, "") }) : null], 4000);
  return true;
}
/* 활동 기록 시험판: 켜기·끄기·멈춤과 상태. 무엇을 남기고 안 남기는지 카드에 적는다 */
async function activityCard(action) {
  let r = null;
  try { r = await apiPost("/api/activity", { action }); } catch (err) { r = null; }
  if (!r || !r.ok) { showToast([h("div", { class: "toast-head", text: "활동 기록 상태를 읽지 못했어요." })], 4000); return; }
  const paused = r.on && r.paused_until * 1000 > Date.now();
  const state = !r.on ? "꺼짐" : paused ? "멈춤" : r.stalled ? "켜짐 · 멈춰 있음" : "켜짐";
  const btn = (text, act) => h("button", { class: "mini-btn", type: "button", text, onclick: () => activityCard(act) });
  showToast([
    h("div", { class: "toast-head", text: `활동 기록 · ${state}` }),
    h("div", { class: "block-sub", text: "앞 앱과 웹 AI 탭 제목만 이 Mac에 7일 남겨요. 키 입력·화면·메신저·비밀번호 앱은 남기지 않아요." }),
    r.on ? h("div", { class: "block-sub", text: `시험 ${r.days}일째 / 14일 · 최근 활동이 들어간 인수인계 ${r.handoffs_with_activity}번 · 평가 ok ${r.rated_ok} / miss ${r.rated_miss}` }) : null,
    r.browser === "denied" ? h("div", { class: "block-sub", text: "브라우저 탭을 못 읽어요: 시스템 설정 > 개인정보 보호 및 보안 > 자동화에서 허용하세요." }) : null,
    h("div", { class: "toast-row" }, ...(r.on ? [btn("끄기", "off"), paused ? btn("다시 켜기", "on") : btn("1시간 멈춤", "pause")] : [btn("켜기", "on")])),
  ], 12000);
}
/* ro pro 확인 카드(C안): 확실한 것은 접어서 기본 선택, '아마도요'는 펼쳐서 직접 고른다. 승인한 것만 옮긴다 */
let lastProCard = null, lastProNotice = null, lastHintKey = "", lastProConsentKey = "";
const proHintCard = document.getElementById("proHintCard");
const proOnboardCard = document.getElementById("proOnboardCard");
const proConsentStatus = document.getElementById("proConsentStatus");
const proLearnToggleBtn = document.getElementById("proLearnToggleBtn");
const proNudgeToggleBtn = document.getElementById("proNudgeToggleBtn");
const proLearnedOpenBtn = document.getElementById("proLearnedOpenBtn");
const orgStageBtn = document.getElementById("orgStageBtn");
const orgDiskBtn = document.getElementById("orgDiskBtn");

async function openStageOp(op) {
  let r = null;
  try { r = await apiPost("/api/stage", { op }); } catch (err) { r = null; }
  if (!r || !r.ok || !r.card) {
    showToast([h("div", { class: "toast-head", text: (r && r.error) || "카드를 열지 못했어요." })], 4500);
    return;
  }
  setBubbleOpen(true);
  stageCard(r.card.id);
}
if (orgStageBtn) orgStageBtn.addEventListener("click", () => openStageOp("organize"));
if (orgDiskBtn) orgDiskBtn.addEventListener("click", () => openStageOp("disk"));
if (proLearnedOpenBtn) proLearnedOpenBtn.addEventListener("click", () => learnedCard({ op: "list" }));
if (proLearnToggleBtn) proLearnToggleBtn.addEventListener("click", async () => {
  const on = !(latestState && latestState.pro && latestState.pro.learning);
  await apiPost("/api/memory", { op: "consent", on });
  await refreshState();
});
if (proNudgeToggleBtn) proNudgeToggleBtn.addEventListener("click", async () => {
  const on = !(latestState && latestState.pro && latestState.pro.nudges);
  await apiPost("/api/memory", { op: "nudges", on });
  await refreshState();
});

function renderProHint(hint) {
  if (!proHintCard) return;
  const key = JSON.stringify(hint || null);
  if (key === lastHintKey) return;
  lastHintKey = key;
  if (!hint) { proHintCard.style.display = "none"; proHintCard.replaceChildren(); return; }
  proHintCard.style.display = "block";
  const go = h("button", { class: "mini-btn primary", type: "button", text: hint.verb || "보기", onclick: async () => {
    let r = null;
    try { r = await apiPost("/api/stage", { op: "hint_accept" }); } catch (err) { r = null; }
    await refreshState();
    if (r && r.ok && r.card) stageCard(r.card.id);
    else if (r && r.notice) showToast([h("div", { class: "toast-head", text: r.notice })], 4500);
  } });
  const close = h("button", { class: "mini-btn", type: "button", text: "닫기", onclick: async () => {
    try { await apiPost("/api/stage", { op: "hint_dismiss" }); } catch (err) {}
    await refreshState();
  } });
  proHintCard.replaceChildren(
    h("div", { class: "gate-head", text: "알림 힌트" }),
    h("div", { class: "gate-body", text: hint.text }),
    h("div", { class: "gate-actions" }, go, close),
  );
}

function renderProConsent(pro) {
  const key = JSON.stringify({ l: !!pro.learning, n: !!pro.nudges, ax: pro.ax });
  if (key === lastProConsentKey) return;
  lastProConsentKey = key;
  if (proConsentStatus) {
    proConsentStatus.textContent = `학습 ${pro.learning ? "켜짐" : "꺼짐"} · 먼저 알림 ${pro.nudges ? "켜짐" : "꺼짐"}${pro.ax === false ? " · 손쉬운 사용 권한 필요" : ""}`;
  }
  if (proLearnToggleBtn) proLearnToggleBtn.textContent = pro.learning ? "학습 끄기" : "학습 켜기";
  if (proNudgeToggleBtn) proNudgeToggleBtn.textContent = pro.nudges ? "먼저 알림 끄기" : "먼저 알림 켜기";
  if (proOnboardCard) {
    proOnboardCard.style.display = "none";
    proOnboardCard.replaceChildren();
  }
}

function applyPro(pro, hint) {
  if (pro.card && pro.card !== lastProCard) { lastProCard = pro.card; setBubbleOpen(true); stageCard(pro.card); }
  if (pro.notice && pro.notice !== lastProNotice) {
    lastProNotice = pro.notice;
    if (!pro.card) showToast([h("div", { class: "toast-head", text: pro.notice })], 5000);
  }
  renderProHint(hint || null);
  renderProConsent(pro);
}
const STAGE_OPS = { quarantine: "격리", evict: "이 Mac 사본 내보내기", move: "옮기기" };
async function stageCard(id, done) {
  let r = null;
  try { r = await apiPost("/api/stage", { op: "view", id }); } catch (err) { r = null; }
  if (!r || !r.ok) { showToast([h("div", { class: "toast-head", text: (r && r.error) || "카드를 열지 못했어요." })], 4000); return; }
  const c = r.card;
  const checks = new Map();
  const row = (it) => {
    const box = h("input", { type: "checkbox", "aria-label": it.name });
    box.checked = it.sure && !c.applied;
    box.disabled = c.applied;
    checks.set(it.id, box);
    // 파일 이름은 번역하지 않는 칸(.stage-name)에 두고, 동작·이유만 화면 언어로 바꾼다
    return h("label", { class: "block-sub stage-row" }, box,
      h("span", {}, h("span", { text: STAGE_OPS[it.op] || it.op }), " · ",
        h("span", { class: "stage-name", text: `${it.name}${it.dest ? " → " + it.dest : ""}` }),
        ` · ${fmtBytes(it.bytes)} · `, h("span", { text: it.reason })));
  };
  const sure = c.items.filter((it) => it.sure), maybe = c.items.filter((it) => !it.sure);
  const sureBox = h("details", {}, h("summary", { class: "block-sub", text: c.applied ? `확실한 것 ${sure.length}개` : `확실한 것 ${sure.length}개 (선택됨)` }), ...sure.map(row));
  const total = c.items.reduce((a, it) => a + (it.bytes || 0), 0);
  const apply = h("button", { class: "mini-btn primary", type: "button", text: "고른 것 적용", onclick: async () => {
    const picks = [...checks].filter(([, b]) => b.checked).map(([k]) => k);
    if (!picks.length) return;
    let a = null;
    try { a = await apiPost("/api/stage", { op: "apply", id, picks, approve: true }); } catch (err) { a = null; }
    const msg = !a ? "서버에 연결하지 못했어요." : !a.ok ? a.error
      : `옮김 ${a.moved}건 · 사본 내보냄 ${a.evicted}건${a.skipped.length ? ` · 건너뜀 ${a.skipped.length}건` : ""}`;
    stageCard(id, msg);
  } });
  const undo = h("button", { class: "mini-btn", type: "button", text: "되돌리기", onclick: async () => {
    let u = null;
    try { u = await apiPost("/api/stage", { op: "undo", id }); } catch (err) { u = null; }
    stageCard(id, u && u.ok ? `되돌렸어요 · 파일 ${u.files}개 제자리로${u.skipped ? ` · 바뀐 것 ${u.skipped}개는 그대로` : ""}` : (u && u.error) || "되돌리지 못했어요.");
  } });
  const dismiss = h("button", { class: "mini-btn", type: "button", text: c.applied ? "닫기" : "취소", onclick: () => hideToast() });
  showToast([
    h("div", { class: "toast-head", text: `${c.title} · ${c.items.length}개 · ${fmtBytes(total)}` }),
    done ? h("div", { class: "block-sub", text: done }) : null,
    sure.length ? sureBox : null,
    ...(maybe.length ? [h("div", { class: "block-sub", text: `아마도요 ${maybe.length}개 — 직접 골라 주세요` }), ...maybe.map(row)] : []),
    h("div", { class: "block-sub", text: "격리한 것은 ~/.ro/cleanup/trash에 있고 되돌릴 수 있어요. 이 Mac 사본 내보내기는 iCloud에 남고 다시 내려받을 수 있어요." }),
    h("div", { class: "toast-row" }, c.applied ? undo : apply, dismiss),
  ], 0);
}
/* ro가 배운 것(원칙 6): 무엇을 배웠는지 한 화면에서 보고 고정·끄기·지우기. 이름·경로·본문은 배우지 않는다 */
const LEARNED_STATE = { learned: "배움", watching: "보는 중", pinned: "고정됨", off: "꺼 둠" };  // '고정'은 버튼 말이라 상태는 '고정됨'
const LEARNED_KIND = { ext_home: ["확장자", "폴더"], pick_folder: ["찾는 종류", "폴더"], app_band: ["시간대", "앱"] };
const NUDGE_NAMES = {
  find_lost: "찾기 헤맴", old_version: "옛 판본", disk_low: "용량 부족", dmg_installed: "설치 파일",
  archive_unpacked: "풀린 압축", duplicate_found: "중복 파일", download_burst: "다운로드 묶음", context_switch: "도구 전환",
};
async function learnedCard(req, confirmWipe) {
  let r = null;
  try { r = await apiPost("/api/memory", req); } catch (err) { r = null; }
  if (!r || !r.ok) { showToast([h("div", { class: "toast-head", text: (r && r.error) || "배운 것을 읽지 못했어요." })], 4000); return; }
  const btn = (text, next, cls) => h("button", { class: "mini-btn" + (cls ? " " + cls : ""), type: "button", text, onclick: () => learnedCard(next) });
  // 폴더·앱 이름(사용자 것)은 번역하지 않는 칸에, 상태·종류 말은 따로 둬서 화면 언어로 바뀌게 한다
  const what = (it) => {
    const k = LEARNED_KIND[it.kind];
    if (!k) return [h("span", { class: "stage-name", text: it.what })];
    return [h("span", { text: k[0] }), " ", h("span", { text: String(it.key) }), " → ", h("span", { text: k[1] }), " ",
      h("span", { class: "stage-name", text: String(it.value) })];
  };
  const rows = r.items.slice(0, 12).map((it) => h("div", { class: "block-sub" },
    h("span", { text: LEARNED_STATE[it.status] || it.status }), " · ", ...what(it), " · ", h("span", { text: `${it.days}일` }), " ",
    it.status === "pinned" ? btn("고정 풀기", { op: "unpin", id: it.id }) : it.status !== "off" ? btn("고정", { op: "pin", id: it.id }) : null,
    it.status === "off" ? btn("다시 켜기", { op: "on", id: it.id }) : btn("끄기", { op: "off", id: it.id }),
    btn("지우기", { op: "forget", id: it.id })));
  const m = r.metrics || {};
  const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);
  const metricLine = m.shown ? h("div", { class: "block-sub", text: `먼저 알림 30일: ${m.shown}번 · 도움 ${pct(m.help)} · 끄기 ${pct(m.off)} · ${m.overall}${m.demoted && m.demoted.length ? ` · 1단계로 낮춘 유형 ${m.demoted.map((t) => NUDGE_NAMES[t] || t).join(", ")}` : ""}` }) : null;
  const offTypes = r.nudges_off.map((t) => btn(`${NUDGE_NAMES[t] || t} 다시 켜기`, { op: "type_on", trigger: t }));
  showToast([
    h("div", { class: "toast-head", text: `ro가 배운 것 · 학습 ${r.learning ? "켜짐" : "꺼짐"} · 먼저 알림 ${r.nudges ? "켜짐" : "꺼짐"}` }),
    h("div", { class: "block-sub", text: "확장자·시간대·폴더 위치 같은 통계만 이 Mac(~/.ro)에 남겨요. 파일 이름·경로·내용은 남기지 않고, 서로 다른 3일에 보인 것만 배워요." }),
    metricLine,
    ...(rows.length ? rows : [h("div", { class: "block-sub", text: r.learning ? "아직 배운 것이 없어요." : "학습을 켜기 전에는 아무것도 배우지 않아요." })]),
    offTypes.length ? h("div", { class: "toast-row" }, ...offTypes) : null,
    h("div", { class: "toast-row" },
      btn(r.learning ? "학습 끄기" : "학습 켜기", { op: "consent", on: !r.learning }, r.learning ? "" : "primary"),
      btn(r.nudges ? "먼저 알림 끄기" : "먼저 알림 켜기", { op: "nudges", on: !r.nudges }),
      confirmWipe ? btn("정말 모두 지우기", { op: "wipe", approve: true })
        : h("button", { class: "mini-btn", type: "button", text: "모두 지우기", onclick: () => learnedCard({ op: "list" }, true) })),
  ], 20000);
}
/* AI 갈아타기: 미리 보기(요약, 원하면 본문) → 넘기기를 눌러야 저장·클립보드·앱 열기 */
async function relayPlan(arg, session) {
  let r = null;
  try { r = await apiPost("/api/handoff/plan", { arg, session: session || "" }); } catch (err) { r = null; }
  if (!r || !r.ok) {
    showToast([h("div", { class: "toast-head", text: r ? (r.error || "인수인계를 만들지 못했어요") : "서버에 연결하지 못했어요." })], 5500);
    return false;
  }
  const c = r.counts;
  const go = h("button", { class: "mini-btn primary", type: "button", text: `${r.dst_name}로 넘기기`, onclick: async () => {
    let a = null;
    try { a = await apiPost("/api/handoff/apply", { id: r.id, approve: true }); } catch (err) { a = null; }
    const head = !a ? "서버에 연결하지 못했어요." : !a.ok ? (a.error || "넘기지 못했어요")
      : a.mode === "cli" ? "터미널에 붙여 넣을 명령을 복사했어요" : a.opened ? `${a.name} 앱을 열었어요` : `${a.name} 앱을 열지 못했어요`;
    const sub = a && a.ok ? (a.relay ? "이 폴더로 새 세션을 열면 자동으로 이어받아요 · 채팅이면 ⌘V"
      : a.mode === "cli" ? "작업 폴더에서 ⌘V 후 ↵" : "인수인계 문서를 복사했어요 · 새 대화에 ⌘V") : "";
    showToast([h("div", { class: "toast-head", text: head }), sub ? h("div", { class: "block-sub", text: sub }) : null], 5000);
  } });
  const body = h("pre", { class: "relay-doc", hidden: true, tabindex: "0", "aria-label": "넘길 문서 본문" });
  const bodyToggle = h("button", { class: "mini-btn", type: "button", text: "내용 보기", "aria-expanded": "false", onclick: async () => {
    if (!body.textContent) {
      let v = null;
      try { v = await apiPost("/api/handoff/preview", { id: r.id }); } catch (err) { v = null; }
      body.textContent = v && v.ok ? v.doc : "본문을 불러오지 못했어요.";
    }
    body.hidden = !body.hidden;
    bodyToggle.textContent = body.hidden ? "내용 보기" : "내용 접기";
    bodyToggle.setAttribute("aria-expanded", String(!body.hidden));
  } });
  // 본문·다른 세션까지 펼쳐도 창을 넘지 않게 가운데만 스크롤하고, 넘기기 버튼은 늘 보인다
  showToast([
    h("div", { class: "toast-head", text: `${r.src_name} → ${r.dst_name} 인수인계` }),
    h("div", { class: "relay-scroll" },
    ...(r.why || []).map(w => h("div", { class: "block-sub", text: `자동 선택 · ${w}` })),
    h("div", { class: "toast-file", text: r.title }),
    h("div", { class: "block-sub", text: `마지막 활동 ${r.updated} · ${r.cwd || "작업 폴더 모름"}` }),
    h("div", { class: "block-sub", text: `남은 할 일 ${c.todos || 0} · 요청 ${c.requests} · 바꾼 파일 ${c.files} · 명령 ${c.commands} · 산출물 ${c.artifacts} · ${r.chars}자`
      + (r.masked ? " · 비밀값은 가림" : "") }),
    ...(r.notes || []).map(n => h("div", { class: "block-sub", text: n })),
    body,
    (r.others || []).length ? h("div", { class: "block-sub", text: "이 작업이 아니면 다른 세션:" }) : null,
    ...(r.others || []).map(o => h("button", { class: "mini-btn", type: "button",
      "aria-label": `${o.engine_name} ${o.updated} 세션으로 바꾸기: ${o.title}`,
      text: `${o.engine_name} · ${o.updated.slice(5)} · ${o.title} (요청 ${o.requests})`,
      onclick: () => relayPlan(`${o.engine} ${r.dst}`, o.id) }))),
    h("div", { class: "toast-row" }, go, bodyToggle,
      h("button", { class: "mini-btn", type: "button", text: "반대로", "aria-label": `${r.dst_name} → ${r.src_name}로 바꾸기`,
        onclick: () => relayPlan(`${r.dst} ${r.src}`) })),
  ], 20000);
  go.focus();
  return true;
}
document.getElementById("connOpenBtn").addEventListener("click", () => openConn(""));
setTimeout(checkConnect, 1200);  // 새로 설치한 도구도 시작할 때 알아챈다
connWin.addEventListener("mousedown", (e) => { if (e.target === connWin) closeConn(); });
connWin.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeConn(); return; }
  if (e.key !== "Tab") return;  // 창 안에서만 포커스가 돈다
  const f = [...connWin.querySelectorAll("button:not([disabled])")];
  if (!f.length) { e.preventDefault(); return; }
  const i = f.indexOf(document.activeElement);
  if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
  else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
});
document.getElementById("sendEngineBtn").addEventListener("click", () => {
  const q = pendingSend && pendingSend.q;
  hideSendCard();
  openConn(q || "");
});

/* In-app Pro checkout & license screen */
const proModal = document.getElementById("proModal");
const proStatusPill = document.getElementById("proStatusPill");
const proPlanSub = document.getElementById("proPlanSub");
const proOpenBuyBtn = document.getElementById("proOpenBuyBtn");
const proOpenKeyBtn = document.getElementById("proOpenKeyBtn");
const proModalCloseBtn = document.getElementById("proModalCloseBtn");
const proTabBuy = document.getElementById("proTabBuy");
const proTabKey = document.getElementById("proTabKey");
const proBuyView = document.getElementById("proBuyView");
const proKeyView = document.getElementById("proKeyView");
const proPlanOpts = [...document.querySelectorAll(".pro-plan-opt")];
const proCheckoutBtn = document.getElementById("proCheckoutBtn");
const proCheckoutMsg = document.getElementById("proCheckoutMsg");
const proPendingRow = document.getElementById("proPendingRow");
const proCheckNowBtn = document.getElementById("proCheckNowBtn");
const proKeyStatus = document.getElementById("proKeyStatus");
const proKeyFeedback = document.getElementById("proKeyFeedback");
const proRestartBar = document.getElementById("proRestartBar");
const proRestartBtn = document.getElementById("proRestartBtn");
const proAutoRow = document.getElementById("proAutoRow");
const proAutoToggle = document.getElementById("proAutoToggle");

let proSelectedPlan = "yearly";
let proLicenseState = null;
let proPendingTimer = null;

function stopProPendingPoll() {
  if (proPendingTimer) { clearInterval(proPendingTimer); proPendingTimer = null; }
}

function setProModalTab(tab) {
  const isBuy = tab !== "key";
  proTabBuy.classList.toggle("active", isBuy);
  proTabBuy.setAttribute("aria-selected", String(isBuy));
  proTabKey.classList.toggle("active", !isBuy);
  proTabKey.setAttribute("aria-selected", String(!isBuy));
  proBuyView.hidden = !isBuy;
  proKeyView.hidden = isBuy;
}

function selectProPlan(plan) {
  proSelectedPlan = plan === "monthly" ? "monthly" : "yearly";
  proPlanOpts.forEach((btn) => {
    const on = btn.dataset.plan === proSelectedPlan;
    btn.classList.toggle("selected", on);
    btn.setAttribute("aria-checked", String(on));
  });
}

function renderProLicenseState(st) {
  if (!st || typeof st !== "object") return;
  proLicenseState = st;
  const activePro = st.state === "valid" || st.edition === "pro";
  if (proStatusPill) {
    proStatusPill.textContent = activePro ? "Pro" : "Free";
    proStatusPill.classList.toggle("active", activePro);
  }
  if (proPlanSub) {
    proPlanSub.textContent = activePro
      ? (st.message || "Pro active on this Mac.")
      : "Find files by asking, tidy Downloads with undo, and hand off between AI tools — all on this Mac.";
  }
  if (proOpenKeyBtn) {
    proOpenKeyBtn.textContent = activePro ? "Manage license" : "License";
  }
  if (proKeyStatus) {
    proKeyStatus.textContent = st.message || (activePro ? "Pro active" : "Free (mini)");
  }
  if (proAutoRow && proAutoToggle) {
    proAutoRow.hidden = !st.autoReady;
    proAutoToggle.checked = st.auto !== false;
  }
  if (proRestartBar && st.restart) proRestartBar.hidden = false;
  if (st.pending && !activePro && proCheckoutMsg && proPendingRow) {
    proCheckoutMsg.textContent = "Checkout opened in your browser. Once payment completes, ro activates Pro automatically.";
    proCheckoutMsg.hidden = false;
    proPendingRow.hidden = false;
  }
}

async function refreshProPlanStatus() {
  try {
    const st = await apiPost("/api/license", { action: "status" });
    if (st && st.ok) renderProLicenseState(st);
    return st;
  } catch (e) {
    return null;
  }
}

async function openProModal(tab) {
  if (!proModal) return;
  if (bubble.classList.contains("hidden")) setBubbleOpen(true);
  proModal.hidden = false;
  if (proKeyFeedback) { proKeyFeedback.textContent = ""; proKeyFeedback.classList.remove("err"); }
  if (proCheckoutMsg) { proCheckoutMsg.textContent = ""; proCheckoutMsg.hidden = true; }
  if (proPendingRow) proPendingRow.hidden = true;
  if (proRestartBar) proRestartBar.hidden = true;
  setProModalTab(tab || (document.body.classList.contains("edition-pro") ? "key" : "buy"));
  const st = await refreshProPlanStatus();
  if (st && st.pending && st.state !== "valid") startProPendingPoll();
}
window.openProModal = openProModal;

function closeProModal() {
  stopProPendingPoll();
  if (proModal) proModal.hidden = true;
}

function openExternalHttps(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return false;
  } catch (e) {
    return false;
  }
  if (isNativeHost) {
    notifyHost({ type: "openCheckout", url });
  } else {
    window.open(url, "_blank", "noopener,noreferrer");
  }
  return true;
}

function startProPendingPoll() {
  stopProPendingPoll();
  proPendingTimer = setInterval(async () => {
    if (!proModal || proModal.hidden) { stopProPendingPoll(); return; }
    const res = await checkProActivation(true);
    if (res && res.state === "valid") stopProPendingPoll();
  }, 8000);
}

async function checkProActivation(silent) {
  try {
    const res = await apiPost("/api/license", { action: "check" });
    if (res && res.ok) {
      renderProLicenseState(res);
      if (res.state === "valid") {
        stopProPendingPoll();
        if (proCheckoutMsg) {
          proCheckoutMsg.textContent = res.message || "Pro license active!";
          proCheckoutMsg.hidden = false;
        }
        if (proPendingRow) proPendingRow.hidden = true;
        if (res.restart) {
          setProModalTab("key");
          proRestartBar.hidden = false;
        }
      } else if (!silent && proCheckoutMsg) {
        proCheckoutMsg.textContent = "Still waiting for payment confirmation.";
        proCheckoutMsg.hidden = false;
      }
    }
    return res;
  } catch (e) {
    return null;
  }
}

if (proOpenBuyBtn) proOpenBuyBtn.addEventListener("click", () => openProModal("buy"));
if (proOpenKeyBtn) proOpenKeyBtn.addEventListener("click", () => openProModal("key"));
if (proModalCloseBtn) proModalCloseBtn.addEventListener("click", closeProModal);
if (proModal) {
  proModal.addEventListener("mousedown", (e) => { if (e.target === proModal) closeProModal(); });
  proModal.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeProModal(); }
  });
}
if (proTabBuy) proTabBuy.addEventListener("click", () => setProModalTab("buy"));
if (proTabKey) proTabKey.addEventListener("click", () => setProModalTab("key"));
proPlanOpts.forEach((btn) => btn.addEventListener("click", () => selectProPlan(btn.dataset.plan)));

if (proCheckoutBtn) {
  proCheckoutBtn.addEventListener("click", async () => {
    proCheckoutBtn.disabled = true;
    try {
      const res = await apiPost("/api/license", { action: "buy", plan: proSelectedPlan });
      if (res && res.ok && res.url && openExternalHttps(res.url)) {
        proCheckoutMsg.textContent = "Checkout opened in your browser. Once payment completes, ro activates Pro automatically.";
        proCheckoutMsg.hidden = false;
        proPendingRow.hidden = false;
        startProPendingPoll();
      } else {
        proCheckoutMsg.textContent = (res && res.error)
          || "Online checkout opens soon.";
        proCheckoutMsg.hidden = false;
        proPendingRow.hidden = false;
        if (proCheckNowBtn) proCheckNowBtn.hidden = !(proLicenseState && proLicenseState.autoReady);
      }
    } catch (e) {
      proCheckoutMsg.textContent = "Could not reach the server";
      proCheckoutMsg.hidden = false;
    } finally {
      proCheckoutBtn.disabled = false;
    }
  });
}

if (proCheckNowBtn) proCheckNowBtn.addEventListener("click", () => checkProActivation(false));


if (proAutoToggle) {
  proAutoToggle.addEventListener("change", async () => {
    try {
      const res = await apiPost("/api/license", { action: "auto", on: proAutoToggle.checked });
      if (res && res.ok) renderProLicenseState(res);
    } catch (e) {
      proAutoToggle.checked = !proAutoToggle.checked;
    }
  });
}


if (proRestartBtn) {
  proRestartBtn.addEventListener("click", () => {
    if (isNativeHost) {
      notifyHost({ type: "restartLicense" });
    } else {
      window.location.reload();
    }
  });
}

refreshProPlanStatus();

if (!isNativeHost) {
  // 브라우저에서는 처음부터 대화창을 연다: 봇만 덩그러니 있으면 무엇을 할지 알기 어렵다
  document.body.classList.add("web");
  setBubbleOpen(true);
}
setPollRate(!bubble.classList.contains("hidden"));

/* 크기·배치가 바뀔 때마다 누를 수 있는 자리를 다시 알린다(상태창 열고 닫기, 펫 크기, 창 크기) */
if (isNativeHost) {
  const hitWatch = new ResizeObserver(reportHit);
  hitWatch.observe(bubble);
  hitWatch.observe(document.getElementById("roBot"));
  window.addEventListener("resize", reportHit);
  reportHit();
}
