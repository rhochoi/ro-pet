/* Interactive Local Sandbox for site/pro/index.html — 100% in-browser, 0 network requests.
   Lets visitors experience:
   1. ⌥R natural-language file search across 20 realistic virtual Mac files (by name, kind/date, and OCR/body text).
   2. Downloads tidying with preview confirm card, selective approval, Journal V2 batch commit, and 1-click undo. */
(function () {
  const INITIAL_FILES = [
    {
      id: 1, name: "contract_final_v2.pdf", ext: "PDF", folder: "~/Downloads", ageDays: 14, size: "420 KB", bytes: 430080,
      tags: ["contract", "agreement", "pdf", "last month", "november", "signed", "acme"],
      snippet: "Master Service Agreement signed with Acme Corp · payment net 30 · renewal clause §4.",
      tidy: { op: "move", category: "Contracts", dest: "~/Documents/Sorted/Contracts/2026-11_contract_final_v2.pdf", reason: "Contract document", sure: true }
    },
    {
      id: 2, name: "service_contract_signed.pdf", ext: "PDF", folder: "~/Documents/Legal", ageDays: 22, size: "380 KB", bytes: 389120,
      tags: ["contract", "service", "pdf", "last month", "legal", "nda"],
      snippet: "Consulting service agreement and mutual NDA addendum for Q4 rollout.",
      tidy: null
    },
    {
      id: 3, name: "Q3 contract review.pdf", ext: "PDF", folder: "~/Documents/Work", ageDays: 35, size: "290 KB", bytes: 296960,
      tags: ["contract", "q3", "review", "pdf", "redline"],
      snippet: "Legal review notes on indemnification, limitation of liability, and IP terms.",
      tidy: null
    },
    {
      id: 4, name: "invoice_2026_10_polar.pdf", ext: "PDF", folder: "~/Downloads", ageDays: 18, size: "156 KB", bytes: 159744,
      tags: ["invoice", "receipt", "october", "polar", "tax", "finance", "pdf", "last month"],
      snippet: "Tax invoice #4821 for annual software subscription · $24.00 USD paid.",
      tidy: { op: "move", category: "Finance", dest: "~/Documents/Sorted/Finance/2026-10_invoice_polar.pdf", reason: "Invoice / receipt", sure: true }
    },
    {
      id: 5, name: "october_expense_receipts.xlsx", ext: "XLSX", folder: "~/Downloads", ageDays: 12, size: "1.2 MB", bytes: 1258291,
      tags: ["october", "expense", "receipt", "spreadsheet", "excel", "xlsx", "finance", "reimbursement"],
      snippet: "Flight, hotel, and cloud hosting receipts for October team reimbursement.",
      tidy: { op: "move", category: "Finance", dest: "~/Documents/Sorted/Finance/2026-10_october_expense_receipts.xlsx", reason: "Finance spreadsheet", sure: true }
    },
    {
      id: 6, name: "october_expense_receipts (1).xlsx", ext: "XLSX", folder: "~/Downloads", ageDays: 12, size: "1.2 MB", bytes: 1258291,
      tags: ["october", "expense", "duplicate", "xlsx"],
      snippet: "Identical byte-for-byte duplicate of october_expense_receipts.xlsx.",
      tidy: { op: "quarantine", category: "Holding", dest: "~/.ro/cleanup/trash/october_expense_receipts (1).xlsx", reason: "Duplicates", sure: true }
    },
    {
      id: 7, name: "IMG_4092_whiteboard_scan.png", ext: "PNG", folder: "~/Downloads", ageDays: 5, size: "3.4 MB", bytes: 3565158,
      tags: ["whiteboard", "ocr", "diagram", "scan", "image", "png", "photo", "tactgate", "journal"],
      snippet: "Vision OCR: Architecture pipeline — TactGate → Confirm Card → Journal V2 → 1-click Undo.",
      tidy: { op: "move", category: "Screenshots", dest: "~/Documents/Sorted/Screenshots/2026-11_IMG_4092_whiteboard_scan.png", reason: "Scanned image", sure: true }
    },
    {
      id: 8, name: "Screenshot 2026-11-14 at 10.22.png", ext: "PNG", folder: "~/Downloads", ageDays: 8, size: "1.8 MB", bytes: 1887436,
      tags: ["screenshot", "ocr", "benchmark", "recall", "image", "png"],
      snippet: "Vision OCR: Local search evaluation — 89.4% top-3 recall, 14ms median latency.",
      tidy: { op: "move", category: "Screenshots", dest: "~/Documents/Sorted/Screenshots/2026-11_Screenshot_10.22.png", reason: "Screenshot", sure: true }
    },
    {
      id: 9, name: "Firefox 132.0-arm64.dmg", ext: "DMG", folder: "~/Downloads", ageDays: 9, size: "142 MB", bytes: 148897792,
      tags: ["firefox", "dmg", "installer", "app"],
      snippet: "Disk image installer · Firefox.app is already installed in /Applications.",
      tidy: { op: "quarantine", category: "Holding", dest: "~/.ro/cleanup/trash/Firefox 132.0-arm64.dmg", reason: "An app with a matching name is installed", sure: true }
    },
    {
      id: 10, name: "Raycast_v1.84_Universal.dmg", ext: "DMG", folder: "~/Downloads", ageDays: 15, size: "88 MB", bytes: 92274688,
      tags: ["raycast", "dmg", "installer", "app"],
      snippet: "Disk image installer · Raycast.app is already installed in /Applications.",
      tidy: { op: "quarantine", category: "Holding", dest: "~/.ro/cleanup/trash/Raycast_v1.84_Universal.dmg", reason: "An app with a matching name is installed", sure: true }
    },
    {
      id: 11, name: "brand_assets.zip", ext: "ZIP", folder: "~/Downloads", ageDays: 11, size: "34 MB", bytes: 35651584,
      tags: ["brand", "assets", "zip", "archive", "icon"],
      snippet: "Archive already unpacked next to ~/Downloads/brand_assets/.",
      tidy: { op: "quarantine", category: "Holding", dest: "~/.ro/cleanup/trash/brand_assets.zip", reason: "Unpacked archives", sure: true }
    },
    {
      id: 12, name: "design_tokens_v1.json", ext: "JSON", folder: "~/Downloads", ageDays: 20, size: "18 KB", bytes: 18432,
      tags: ["design", "tokens", "json", "old", "v1"],
      snippet: "Superseded v1 token draft; newer design_tokens_v2_final.json is in the same folder.",
      tidy: { op: "quarantine", category: "Holding", dest: "~/.ro/cleanup/trash/design_tokens_v1.json", reason: "Old versions", sure: true }
    },
    {
      id: 13, name: "design_tokens_v2_final.json", ext: "JSON", folder: "~/Downloads", ageDays: 4, size: "22 KB", bytes: 22528,
      tags: ["design", "tokens", "json", "v2", "final", "ink", "cream"],
      snippet: "Final v2 tokens: ink #1A1917, chalk #F5F2EB, font sizes 11 / 13 / 15 / 20px.",
      tidy: { op: "move", category: "Docs", dest: "~/Documents/Sorted/Docs/2026-11_design_tokens_v2_final.json", reason: "Spec document", sure: true }
    },
    {
      id: 14, name: "api_latency_benchmark.csv", ext: "CSV", folder: "~/Downloads", ageDays: 7, size: "64 KB", bytes: 65536,
      tags: ["benchmark", "latency", "csv", "data", "sheet", "sqlite"],
      snippet: "p50=12ms, p95=38ms across 12,400 local files indexed on Apple Silicon.",
      tidy: { op: "move", category: "Sheets and data", dest: "~/Documents/Sorted/Sheets and data/2026-11_api_latency_benchmark.csv", reason: "Data table", sure: true }
    },
    {
      id: 15, name: "ro_architecture_handoff.md", ext: "MD", folder: "~/Desktop", ageDays: 2, size: "14 KB", bytes: 14336,
      tags: ["handoff", "claude", "codex", "antigravity", "note", "markdown", "journal"],
      snippet: "AI handoff note (secrets masked): Journal V2 atomic rename and inode verification.",
      tidy: null
    },
    {
      id: 16, name: "tax_withholding_2026.pdf", ext: "PDF", folder: "~/Documents/Finance", ageDays: 40, size: "510 KB", bytes: 522240,
      tags: ["tax", "withholding", "2026", "finance", "pdf", "certificate"],
      snippet: "Annual tax withholding certificate and contractor 1099 summary for 2026.",
      tidy: null
    },
    {
      id: 17, name: "board_meeting_minutes_nov.pdf", ext: "PDF", folder: "~/Documents/Notes", ageDays: 6, size: "240 KB", bytes: 245760,
      tags: ["board", "meeting", "minutes", "november", "notes", "pdf", "privacy"],
      snippet: "November product review: verified 0 outbound network calls during file search.",
      tidy: null
    },
    {
      id: 18, name: "quarterly_roadmap_2027.key", ext: "KEY", folder: "~/iCloud Drive/Decks", ageDays: 16, size: "24 MB", bytes: 25165824,
      tags: ["roadmap", "2027", "slides", "keynote", "icloud", "deck"],
      snippet: "iCloud Drive presentation package (metadata indexed without downloading 24 MB).",
      tidy: null
    },
    {
      id: 19, name: "mac_release_checklist.md", ext: "MD", folder: "~/Desktop", ageDays: 3, size: "9 KB", bytes: 9216,
      tags: ["release", "checklist", "dmg", "notarize", "sparkle", "mac"],
      snippet: "Release checklist: Developer ID codesign, Apple notarization, Sparkle appcast.",
      tidy: null
    },
    {
      id: 20, name: "apartment_lease_renewal.pdf", ext: "PDF", folder: "~/Downloads", ageDays: 1, size: "610 KB", bytes: 624640,
      tags: ["lease", "apartment", "renewal", "contract", "pdf"],
      snippet: "Residential lease renewal draft — needs manual review before filing.",
      tidy: { op: "move", category: "Contracts", dest: "~/Documents/Sorted/Contracts/2026-11_apartment_lease_renewal.pdf", reason: "Maybe — pick yourself", sure: false }
    }
  ];

  const STOP_WORDS = new Set(["the", "a", "an", "i", "got", "from", "in", "on", "my", "for", "of", "to", "by", "with", "file", "files", "/file", "find", "where", "is", "that"]);

  function cloneFiles() {
    return INITIAL_FILES.map((f) => ({
      ...f,
      currentFolder: f.folder,
      currentName: f.name,
      tidy: f.tidy ? { ...f.tidy } : null,
    }));
  }

  function matchWhy(file, tokens, rawQuery) {
    const lowerName = file.name.toLowerCase();
    const stem = lowerName.replace(/\.[^.]+$/, "");
    const cleanQ = rawQuery.replace(/^\/file\s+/i, "").trim().toLowerCase();
    if (cleanQ && stem === cleanQ) {
      return { score: 120, why: `Whole name matches '${cleanQ}'` };
    }
    for (const tok of tokens) {
      if (lowerName.startsWith(tok)) {
        return { score: 100, why: `Name starts with '${tok}'` };
      }
    }
    for (const tok of tokens) {
      if (lowerName.includes(tok)) {
        return { score: 85, why: `Name contains '${tok}'` };
      }
    }
    for (const tok of tokens) {
      if (file.snippet.toLowerCase().includes(tok) || file.tags.some((t) => t.includes(tok))) {
        return { score: 70, why: `Found '${tok}' inside document / OCR text` };
      }
    }
    return null;
  }

  function initSandbox(root) {
    if (!root) return null;
    let files = cloneFiles();
    const tidyItems = files.filter((f) => f.tidy);
    const selectedIds = new Set(tidyItems.filter((f) => f.tidy.sure).map((f) => f.id));

    const state = {
      mode: "search",          // "search" | "tidy"
      query: "contract pdf last month",
      results: [],
      selectedRank: 1,
      openedFile: null,
      appliedBatch: null,      // { id, movedCount, heldCount, heldMB, snapshot }
      statusText: "Nothing moves until you approve.",
      lastLatencyMs: 0,
    };

    const tabSearch = root.querySelector("#sandboxTabSearch");
    const tabTidy = root.querySelector("#sandboxTabTidy");
    const viewSearch = root.querySelector("#sandboxSearchView");
    const viewTidy = root.querySelector("#sandboxTidyView");
    const searchInput = root.querySelector("#sandboxSearchInput");
    const resultsBox = root.querySelector("#sandboxResults");
    const previewBox = root.querySelector("#sandboxPreview");
    const metaBox = root.querySelector("#sandboxSearchMeta");
    const tidyListBox = root.querySelector("#sandboxTidyList");
    const tidyStatusBox = root.querySelector("#sandboxTidyStatus");
    const approveBtn = root.querySelector("#sandboxApproveBtn");
    const undoBtn = root.querySelector("#sandboxUndoBtn");
    const resetBtn = root.querySelector("#sandboxResetBtn");
    const petEl = root.querySelector("#sandboxPet");

    function setPetMood(mood) {
      if (!petEl) return;
      petEl.setAttribute("data-mood", mood);
    }

    function setMode(mode) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      state.mode = mode === "tidy" ? "tidy" : "search";
      if (tabSearch && tabTidy) {
        const isSearch = state.mode === "search";
        tabSearch.classList.toggle("active", isSearch);
        tabSearch.setAttribute("aria-selected", String(isSearch));
        tabTidy.classList.toggle("active", !isSearch);
        tabTidy.setAttribute("aria-selected", String(!isSearch));
      }
      if (viewSearch) viewSearch.hidden = state.mode !== "search";
      if (viewTidy) viewTidy.hidden = state.mode !== "tidy";
      if (state.mode === "search") renderSearch();
      else renderTidy();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return state.mode;
    }

    function search(query) {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      state.query = String(query == null ? "" : query);
      if (searchInput && searchInput.value !== state.query) {
        searchInput.value = state.query;
      }
      const raw = state.query.trim();
      const tokens = raw
        .toLowerCase()
        .replace(/[^a-z0-9가-힣._-]+/g, " ")
        .split(/\s+/)
        .filter((t) => t && !STOP_WORDS.has(t));

      const scored = [];
      for (const f of files) {
        if (!tokens.length) {
          scored.push({ file: f, score: 50 - f.ageDays, why: `Name contains '${f.ext.toLowerCase()}'` });
          continue;
        }
        let hits = 0;
        let totalScore = 0;
        let primaryWhy = null;
        for (const tok of tokens) {
          const m = matchWhy(f, [tok], raw);
          if (m) {
            hits += 1;
            totalScore += m.score;
            if (!primaryWhy) primaryWhy = m.why;
          }
        }
        if (hits > 0) {
          scored.push({
            file: f,
            score: totalScore + hits * 45 - f.ageDays * 0.2,
            why: primaryWhy,
          });
        }
      }
      scored.sort((a, b) => b.score - a.score);
      state.results = scored.slice(0, 6).map((item, idx) => ({
        rank: idx + 1,
        id: item.file.id,
        name: item.file.currentName,
        folder: item.file.currentFolder,
        ext: item.file.ext,
        size: item.file.size,
        ageDays: item.file.ageDays,
        snippet: item.file.snippet,
        why: item.why,
      }));
      state.selectedRank = state.results.length ? 1 : 0;
      state.openedFile = state.results[0] || null;
      setPetMood(state.results.length ? "found" : "focus");
      renderSearch();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return state.results;
    }

    function openResult(rank) {
      const hit = state.results.find((r) => r.rank === rank);
      if (!hit) return null;
      state.selectedRank = rank;
      state.openedFile = hit;
      setPetMood("resolved");
      renderSearch();
      return hit;
    }

    function renderSearch() {
      if (metaBox) {
        metaBox.textContent = `${state.results.length} found among ${files.length} virtual files on this Mac · 0 network requests`;
      }
      if (resultsBox) {
        resultsBox.innerHTML = "";
        if (!state.results.length) {
          const empty = document.createElement("div");
          empty.className = "sb-empty";
          empty.textContent = "No match in the sandbox. Try 'contract pdf', 'october invoice', 'whiteboard OCR', or 'handoff'.";
          resultsBox.appendChild(empty);
        } else {
          state.results.forEach((r) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "sb-row" + (r.rank === state.selectedRank ? " is-selected" : "");
            btn.setAttribute("data-rank", String(r.rank));
            btn.innerHTML =
              `<span class="sb-ext">${r.ext}</span>` +
              `<span class="sb-row-main">` +
                `<strong class="sb-name">${r.name}</strong>` +
                `<span class="sb-where">${r.folder} · ${r.size} · ${r.ageDays}d ago</span>` +
                `<span class="sb-why">${r.why}</span>` +
              `</span>` +
              `<span class="sb-rank">#${r.rank}</span>`;
            btn.addEventListener("click", () => openResult(r.rank));
            resultsBox.appendChild(btn);
          });
        }
      }
      if (previewBox) {
        if (!state.openedFile) {
          previewBox.innerHTML = `<div class="sb-preview-empty">Select a result to inspect its local preview.</div>`;
        } else {
          const f = state.openedFile;
          previewBox.innerHTML =
            `<div class="sb-preview-head">` +
              `<span class="sb-ext">${f.ext}</span>` +
              `<div><strong>${f.name}</strong><div class="sb-where">${f.folder} · ${f.size}</div></div>` +
            `</div>` +
            `<div class="sb-preview-body">${f.snippet}</div>` +
            `<div class="sb-preview-foot">Matched because: <code>${f.why}</code> · Checked locally (0 bytes sent)</div>`;
        }
      }
    }

    function togglePick(id, checked) {
      const numId = Number(id);
      if (checked === undefined) {
        if (selectedIds.has(numId)) selectedIds.delete(numId);
        else selectedIds.add(numId);
      } else if (checked) {
        selectedIds.add(numId);
      } else {
        selectedIds.delete(numId);
      }
      renderTidy();
      return selectedIds.has(numId);
    }

    function applyTidy() {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (state.appliedBatch || selectedIds.size === 0) return false;
      const snapshot = files.map((f) => ({ id: f.id, folder: f.currentFolder, name: f.currentName }));
      let movedCount = 0;
      let heldCount = 0;
      let heldBytes = 0;
      for (const f of files) {
        if (!f.tidy || !selectedIds.has(f.id)) continue;
        const parts = f.tidy.dest.split("/");
        f.currentName = parts.pop();
        f.currentFolder = parts.join("/");
        if (f.tidy.op === "quarantine") {
          heldCount += 1;
          heldBytes += f.bytes || 0;
        } else {
          movedCount += 1;
        }
      }
      const heldMB = Math.round(heldBytes / (1024 * 1024));
      state.appliedBatch = {
        id: "20261122-v2-sandbox",
        movedCount,
        heldCount,
        heldMB,
        snapshot,
      };
      state.statusText = `Journal V2 committed (${state.appliedBatch.id}) · Moved ${movedCount} · Sent ${heldCount} to holding (${heldMB} MB) · 0 deleted`;
      setPetMood("resolved");
      renderTidy();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return state.appliedBatch;
    }

    function undoTidy() {
      const t0 = typeof performance !== "undefined" ? performance.now() : 0;
      if (!state.appliedBatch) return false;
      const snapMap = new Map(state.appliedBatch.snapshot.map((s) => [s.id, s]));
      let restored = 0;
      for (const f of files) {
        const prev = snapMap.get(f.id);
        if (prev && (f.currentFolder !== prev.folder || f.currentName !== prev.name)) {
          f.currentFolder = prev.folder;
          f.currentName = prev.name;
          restored += 1;
        }
      }
      state.appliedBatch = null;
      state.statusText = `Undone · ${restored} files restored back to ~/Downloads with original names and inodes.`;
      setPetMood("resolved");
      renderTidy();
      state.lastLatencyMs = (typeof performance !== "undefined" ? performance.now() : 0) - t0;
      return restored;
    }

    function resetSandbox() {
      files = cloneFiles();
      selectedIds.clear();
      files.filter((f) => f.tidy && f.tidy.sure).forEach((f) => selectedIds.add(f.id));
      state.appliedBatch = null;
      state.statusText = "Nothing moves until you approve.";
      setPetMood("rest");
      renderTidy();
      renderSearch();
      return true;
    }

    function renderTidy() {
      const applied = !!state.appliedBatch;
      if (tidyStatusBox) {
        tidyStatusBox.textContent = state.statusText;
      }
      if (approveBtn) {
        approveBtn.disabled = applied || selectedIds.size === 0;
      }
      if (undoBtn) {
        undoBtn.disabled = !applied;
      }
      if (tidyListBox) {
        tidyListBox.innerHTML = "";
        files.filter((f) => f.tidy).forEach((f) => {
          const checked = selectedIds.has(f.id);
          const row = document.createElement("label");
          row.className = "sb-tidy-row" + (applied && checked ? " is-applied" : "");
          const opBadge = f.tidy.op === "quarantine" ? "To holding" : `Move → ${f.tidy.category}`;
          const destText = applied && checked
            ? `Now at ${f.currentFolder}/${f.currentName}`
            : `${f.folder}/${f.name} → ${f.tidy.dest}`;
          row.innerHTML =
            `<input type="checkbox" data-tidy-id="${f.id}" ${checked ? "checked" : ""} ${applied ? "disabled" : ""}>` +
            `<span class="sb-tidy-main">` +
              `<span class="sb-tidy-top"><strong>${f.name}</strong><span class="sb-badge">${opBadge}</span><span class="sb-where">${f.size}</span></span>` +
              `<span class="sb-where">${destText} · ${f.tidy.reason}</span>` +
            `</span>`;
          const box = row.querySelector("input");
          if (box) {
            box.addEventListener("change", () => togglePick(f.id, box.checked));
          }
          tidyListBox.appendChild(row);
        });
      }
    }

    if (tabSearch) tabSearch.addEventListener("click", () => setMode("search"));
    if (tabTidy) tabTidy.addEventListener("click", () => setMode("tidy"));
    if (searchInput) {
      searchInput.addEventListener("input", () => search(searchInput.value));
    }
    root.querySelectorAll("[data-sandbox-query]").forEach((chip) => {
      chip.addEventListener("click", () => {
        setMode("search");
        search(chip.getAttribute("data-sandbox-query"));
      });
    });
    if (approveBtn) approveBtn.addEventListener("click", () => applyTidy());
    if (undoBtn) undoBtn.addEventListener("click", () => undoTidy());
    if (resetBtn) resetBtn.addEventListener("click", () => resetSandbox());

    if (typeof window !== "undefined" && window.addEventListener) {
      window.addEventListener("keydown", (e) => {
        if (e.altKey && e.code === "KeyR" && !e.metaKey && !e.ctrlKey) {
          e.preventDefault();
          setMode("search");
          if (searchInput && searchInput.focus) searchInput.focus();
        }
      });
    }

    search(state.query);
    renderTidy();

    return {
      state,
      getFiles: () => files.map((f) => ({ id: f.id, name: f.currentName, folder: f.currentFolder, origName: f.name, origFolder: f.folder })),
      setMode,
      search,
      openResult,
      togglePick,
      applyTidy,
      undoTidy,
      resetSandbox,
    };
  }

  function boot() {
    const root = document.getElementById("pro-sandbox");
    if (root) {
      window.RoProSandbox = initSandbox(root);
    }
  }

  window.initRoProSandbox = initSandbox;
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
  }
})();
