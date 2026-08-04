const state = {
  cc: { sort: "workers", offset: 0, limit: 50 },
  cp: { sort: "workers", offset: 0, limit: 50 },
};

// ---------- helpers ----------

function fmtDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function entityLabel(side) {
  return side.enterprise ? side.enterprise.name : side.employer_name;
}

function truncateLabel(s, n) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function partyCell(contract, dateField, isProjected) {
  const pill = contract.enterprise
    ? `<span class="pill pill-customer">${escapeHtml(contract.enterprise.name)}</span>`
    : `<span class="pill pill-prospect">Prospect</span>`;
  const projPill = isProjected ? `<span class="pill pill-projected">Projected</span>` : "";
  return `
    <div>${pill} ${projPill}</div>
    <div class="entity-name">${escapeHtml(contract.employer_name)}</div>
    <div class="sub">${escapeHtml(contract.job_title || "")}${contract.job_title ? " &middot; " : ""}${escapeHtml(contract.worksite_city || "")}${contract.worksite_state ? ", " + contract.worksite_state : ""}</div>
    <div class="sub">${fmtDate(contract[dateField])}</div>
  `;
}

function matchRowHtml(m) {
  const dismissBtn = m.dismissable
    ? `<button class="dismiss-btn" data-from="${m.from.id}" data-to="${m.to.id}">Dismiss</button>`
    : "";
  return `
    <tr>
      <td>${partyCell(m.from, "effective_end", m.from.is_projected)}</td>
      <td>${partyCell(m.to, "effective_start", m.to.is_projected)}</td>
      <td>${m.gap_days}</td>
      <td><strong>${m.transferable_workers}</strong></td>
      <td>${dismissBtn}</td>
    </tr>
  `;
}

function renderMatchTable(tableId, matches, append) {
  const table = document.getElementById(tableId);
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  thead.innerHTML = `<tr><th>Ending contract</th><th>Starting contract</th><th>Gap (days)</th><th>Transferable workers</th><th></th></tr>`;
  const rowsHtml = matches.map(matchRowHtml).join("");
  if (append) tbody.insertAdjacentHTML("beforeend", rowsHtml);
  else tbody.innerHTML = rowsHtml || `<tr><td colspan="5" class="muted">No matches found.</td></tr>`;
}

// ---------- SVG chart helpers ----------

function hBarPath(x0, y, w, h, r) {
  if (w <= 0) return `M ${x0},${y} L ${x0},${y + h} Z`;
  r = Math.min(r, h / 2, w);
  const x1 = x0 + w;
  return `M ${x0},${y} L ${x1 - r},${y} A ${r},${r} 0 0 1 ${x1},${y + r} L ${x1},${y + h - r} A ${r},${r} 0 0 1 ${x1 - r},${y + h} L ${x0},${y + h} Z`;
}

function vBarPath(x, y, w, h, r) {
  if (h <= 0) return `M ${x},${y + h} L ${x + w},${y + h} Z`;
  r = Math.min(r, w / 2, h);
  const yb = y + h;
  return `M ${x},${yb} L ${x},${y + r} A ${r},${r} 0 0 1 ${x + r},${y} L ${x + w - r},${y} A ${r},${r} 0 0 1 ${x + w},${y + r} L ${x + w},${yb} Z`;
}

function buildTopMatchesChart(matches) {
  if (!matches.length) return `<div class="viz-empty">No matches yet.</div>`;
  const rowH = 34, barH = 16, leftPad = 8, labelW = 190, barAreaX = labelW + 10, rightPad = 46, width = 620;
  const barMaxW = width - barAreaX - rightPad;
  const maxVal = Math.max(...matches.map((m) => m.transferable_workers));
  const height = matches.length * rowH + 12;

  const rows = matches.map((m, i) => {
    const y = i * rowH + 6;
    const w = maxVal > 0 ? (m.transferable_workers / maxVal) * barMaxW : 0;
    const color = m.is_projected ? "var(--series-2)" : "var(--series-1)";
    const fromLabel = entityLabel(m.from);
    const toLabel = entityLabel(m.to);
    const label = `${truncateLabel(fromLabel, 13)} → ${truncateLabel(toLabel, 13)}`;
    const path = hBarPath(barAreaX, y, w, barH, 4);
    const titleText = `${fromLabel} → ${toLabel}: ${m.transferable_workers} workers, ${m.gap_days}-day gap${m.is_projected ? " (projected)" : ""}`;
    return `
      <g class="viz-bar-row">
        <title>${escapeHtml(titleText)}</title>
        <text x="${leftPad}" y="${y + barH / 2 + 4}" class="viz-bar-label">${escapeHtml(label)}</text>
        <path d="${path}" fill="${color}" class="viz-bar-fill"></path>
        <text x="${barAreaX + w + 6}" y="${y + barH / 2 + 4}" class="viz-value-label">${m.transferable_workers}</text>
      </g>
    `;
  }).join("");

  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="Top matches by transferable workers">${rows}</svg>`;
}

function buildGapHistogram(buckets) {
  const width = 320, height = 210, padBottom = 30, padTop = 20, colGap = 22;
  const n = buckets.length || 1;
  const colW = Math.min(56, (width - colGap * (n + 1)) / n);
  const maxVal = Math.max(1, ...buckets.map((b) => b.count));
  const plotH = height - padBottom - padTop;
  const totalColsW = n * colW + (n + 1) * colGap;
  const startX = (width - totalColsW) / 2 + colGap;

  const gridLines = [0, 0.5, 1].map((f) => {
    const y = padTop + plotH * (1 - f);
    return `<line x1="0" y1="${y}" x2="${width}" y2="${y}" class="viz-gridline"></line>`;
  }).join("");

  const cols = buckets.map((b, i) => {
    const x = startX + i * (colW + colGap);
    const h = maxVal > 0 ? (b.count / maxVal) * plotH : 0;
    const y = padTop + plotH - h;
    const path = vBarPath(x, y, colW, h, 4);
    return `
      <g class="viz-bar-row">
        <title>${escapeHtml(b.bucket)}: ${b.count} matches</title>
        <path d="${path}" fill="var(--series-1)" class="viz-bar-fill"></path>
        <text x="${x + colW / 2}" y="${y - 6}" text-anchor="middle" class="viz-value-label">${b.count}</text>
        <text x="${x + colW / 2}" y="${height - 8}" text-anchor="middle" class="viz-axis-label">${escapeHtml(b.bucket)}</text>
      </g>
    `;
  }).join("");

  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img" aria-label="Matches by gap in days">
    ${gridLines}
    <line x1="0" y1="${padTop + plotH}" x2="${width}" y2="${padTop + plotH}" class="viz-baseline"></line>
    ${cols}
  </svg>`;
}

// ---------- stats ----------

async function loadStats() {
  const r = await fetch("/api/stats");
  const s = await r.json();
  const bar = document.getElementById("stats-bar");
  bar.innerHTML = `
    <div class="stat"><div class="value">${s.total_contracts}</div><div class="label">Contracts loaded</div></div>
    <div class="stat"><div class="value">${s.enterprises}</div><div class="label">Seso customers</div></div>
    <div class="stat"><div class="value">${s.customer_contracts}</div><div class="label">Matched to a customer</div></div>
    <div class="stat"><div class="value">${s.prospect_contracts}</div><div class="label">Prospect contracts</div></div>
    <div class="stat"><div class="value">${s.pending_review}</div><div class="label">Pending review</div></div>
  `;
  const badge = document.getElementById("review-badge");
  const reviewCount = document.getElementById("review-count");
  if (s.pending_review > 0) {
    badge.textContent = s.pending_review;
    badge.classList.remove("hidden");
    reviewCount.textContent = `(${s.pending_review} pending)`;
  } else {
    badge.classList.add("hidden");
    reviewCount.textContent = "";
  }
}

async function loadSummary() {
  const r = await fetch("/api/matches/summary");
  const data = await r.json();
  const k = data.kpis;
  const tiles = [
    { label: "Open matches", value: k.total_open_matches.toLocaleString() },
    { label: "Workers with a live transfer option", value: k.total_transferable_workers.toLocaleString() },
    { label: "Customers involved", value: k.customers_with_opportunity.toLocaleString() },
    { label: "Avg. transfer-window gap", value: `${k.avg_gap_days} days` },
  ];
  document.getElementById("kpi-row").innerHTML = tiles.map((t) => `
    <div class="kpi-tile"><div class="kpi-value">${t.value}</div><div class="kpi-label">${t.label}</div></div>
  `).join("");

  document.getElementById("top-matches-legend").innerHTML = `
    <div class="legend-item"><span class="legend-swatch" style="background:var(--series-1)"></span>Confirmed</div>
    <div class="legend-item"><span class="legend-swatch" style="background:var(--series-2)"></span>Projected</div>
  `;
  document.getElementById("top-matches-chart").innerHTML = buildTopMatchesChart(data.top_matches);
  document.getElementById("gap-histogram-chart").innerHTML = buildGapHistogram(data.gap_histogram);
}

// ---------- dashboard ----------

async function loadSection(kind) {
  const s = state[kind];
  const url = `/api/matches/${kind === "cc" ? "customer-customer" : "customer-prospect"}?sort=${s.sort}&limit=${s.limit}&offset=${s.offset}`;
  const r = await fetch(url);
  const data = await r.json();
  document.getElementById(`${kind}-total`).textContent = `${data.total} match${data.total === 1 ? "" : "es"}`;
  renderMatchTable(`${kind}-table`, data.results, s.offset > 0);
  const moreBtn = document.getElementById(`${kind}-more`);
  if (s.offset + s.limit < data.total) moreBtn.classList.remove("hidden");
  else moreBtn.classList.add("hidden");
}

async function dismissMatch(fromId, toId) {
  await fetch("/api/matches/dismiss", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_contract_id: Number(fromId), to_contract_id: Number(toId) }),
  });
}

function wireDismissDelegation(tableId, kind) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  tbody.addEventListener("click", async (e) => {
    const btn = e.target.closest(".dismiss-btn");
    if (!btn) return;
    btn.disabled = true;
    await dismissMatch(btn.dataset.from, btn.dataset.to);
    state[kind].offset = 0;
    await Promise.all([loadSection(kind), loadSummary()]);
  });
}

function wireDashboard() {
  document.getElementById("cc-sort").addEventListener("change", (e) => {
    state.cc.sort = e.target.value; state.cc.offset = 0; loadSection("cc");
  });
  document.getElementById("cp-sort").addEventListener("change", (e) => {
    state.cp.sort = e.target.value; state.cp.offset = 0; loadSection("cp");
  });
  document.getElementById("cc-more").addEventListener("click", () => {
    state.cc.offset += state.cc.limit; loadSection("cc");
  });
  document.getElementById("cp-more").addEventListener("click", () => {
    state.cp.offset += state.cp.limit; loadSection("cp");
  });
  wireDismissDelegation("cc-table", "cc");
  wireDismissDelegation("cp-table", "cp");
}

// ---------- search (quick-match by date + worker count) ----------

let searchDebounce = null;

function updateDateFieldLabel() {
  const mode = document.querySelector('input[name="mode"]:checked').value;
  document.getElementById("date-field-label").textContent =
    mode === "needs_workers" ? "Contract start date" : "Contract end date";
}

function wireSearch() {
  const input = document.getElementById("prospect-input");
  const suggestionsBox = document.getElementById("prospect-suggestions");

  input.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    const q = input.value.trim();
    if (q.length < 2) { suggestionsBox.classList.add("hidden"); return; }
    searchDebounce = setTimeout(async () => {
      const r = await fetch(`/api/search/employers?q=${encodeURIComponent(q)}`);
      const items = await r.json();
      if (!items.length) { suggestionsBox.classList.add("hidden"); return; }
      suggestionsBox.innerHTML = items.map((it) => `
        <div class="suggestion-item" data-name="${escapeHtml(it.employer_name)}">
          <span>${escapeHtml(it.employer_name)}</span>
          ${it.is_customer ? '<span class="pill pill-customer">Customer</span>' : '<span class="pill pill-prospect">Prospect</span>'}
        </div>
      `).join("");
      suggestionsBox.classList.remove("hidden");
    }, 250);
  });

  suggestionsBox.addEventListener("click", async (e) => {
    const item = e.target.closest(".suggestion-item");
    if (!item) return;
    const name = item.dataset.name;
    input.value = name;
    suggestionsBox.classList.add("hidden");
    document.getElementById("search-results").classList.add("hidden");
    await loadEmployerContracts(name);
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-row")) suggestionsBox.classList.add("hidden");
  });

  document.querySelectorAll('input[name="mode"]').forEach((radio) => {
    radio.addEventListener("change", updateDateFieldLabel);
  });
  updateDateFieldLabel();

  document.getElementById("run-search").addEventListener("click", runSearch);
}

async function loadEmployerContracts(name) {
  const r = await fetch(`/api/search/employer-contracts?employer_name=${encodeURIComponent(name)}`);
  const contracts = await r.json();
  const box = document.getElementById("prospect-contracts");
  const list = document.getElementById("contract-list");
  if (!contracts.length) {
    list.innerHTML = `<p class="muted">No filed contracts with 25+ workers found for this name &mdash; just fill in the date and worker count below.</p>`;
    box.classList.remove("hidden");
    return;
  }
  list.innerHTML = contracts.map((c) => `
    <div class="contract-option" data-start="${c.contract_start}" data-end="${c.contract_end}" data-workers="${c.worker_count}">
      <div class="title">${escapeHtml(c.job_title || "Contract")} &mdash; ${escapeHtml(c.worksite_city || "")}${c.worksite_state ? ", " + c.worksite_state : ""}</div>
      <div class="sub">${fmtDate(c.contract_start)} &rarr; ${fmtDate(c.contract_end)} &middot; ${c.worker_count} workers</div>
    </div>
  `).join("");
  box.classList.remove("hidden");

  list.querySelectorAll(".contract-option").forEach((el) => {
    el.addEventListener("click", () => {
      list.querySelectorAll(".contract-option").forEach((x) => x.classList.remove("selected"));
      el.classList.add("selected");
      const mode = document.querySelector('input[name="mode"]:checked').value;
      document.getElementById("quick-date").value = mode === "needs_workers" ? el.dataset.start : el.dataset.end;
      document.getElementById("quick-workers").value = el.dataset.workers;
    });
  });
}

async function runSearch() {
  const errBox = document.getElementById("quick-match-error");
  errBox.classList.add("hidden");

  const dateVal = document.getElementById("quick-date").value;
  const workersVal = document.getElementById("quick-workers").value;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const employerName = document.getElementById("prospect-input").value.trim();

  if (!dateVal || !workersVal) {
    errBox.textContent = "Enter both a date and a worker count.";
    errBox.classList.remove("hidden");
    return;
  }
  if (Number(workersVal) < 25) {
    errBox.textContent = "H-2A transfer matches only apply to contracts of 25+ workers.";
    errBox.classList.remove("hidden");
    return;
  }

  const params = new URLSearchParams({ worker_count: workersVal, contract_date: dateVal, mode });
  if (employerName) params.set("employer_name", employerName);

  const r = await fetch(`/api/search/quick-match?${params.toString()}`);
  const data = await r.json();
  if (!r.ok) {
    errBox.textContent = data.detail || "Search failed.";
    errBox.classList.remove("hidden");
    return;
  }

  const label = escapeHtml(data.prospect.employer_name);
  const title = mode === "needs_workers"
    ? `Seso customers whose workers could transfer into ${label}'s contract`
    : `Seso customers who could take ${label}'s workers next, saving outbound transportation`;
  document.getElementById("search-results-title").innerHTML = title;
  renderMatchTable("search-table", data.results, false);
  document.getElementById("search-results").classList.remove("hidden");
}

// ---------- admin ----------

async function postFile(url, file, { timeoutMs = 90000 } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let r;
  try {
    r = await fetch(url, { method: "POST", body: fd, signal: controller.signal });
  } catch (err) {
    clearTimeout(timer);
    if (err.name === "AbortError") {
      return { ok: false, message: `Timed out waiting ${Math.round(timeoutMs / 1000)}s for a response. Check the Vercel project's function logs to see what actually happened server-side.` };
    }
    return { ok: false, message: `Network error: ${err.message}` };
  }
  clearTimeout(timer);

  const raw = await r.text();
  let data = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch (parseErr) {
    // Platform-level errors (timeout, payload-too-large, etc.) often come back
    // as HTML/plain-text, not JSON - surface that instead of failing silently.
    return { ok: false, message: `Server returned ${r.status} ${r.statusText || ""} (non-JSON response)${raw ? ": " + raw.slice(0, 300) : ""}` };
  }
  if (!r.ok) {
    return { ok: false, message: `Error ${r.status}: ${(data && data.detail) || r.statusText}` };
  }
  return { ok: true, data };
}

function wireAdmin() {
  document.getElementById("upload-disclosure").addEventListener("click", async () => {
    const input = document.getElementById("disclosure-file");
    const out = document.getElementById("disclosure-result");
    if (!input.files.length) { out.textContent = "Choose a file first."; return; }
    out.textContent = "Uploading and matching… (large files can take up to a minute)";
    const result = await postFile("/api/upload/disclosure", input.files[0]);
    if (!result.ok) { out.textContent = result.message; return; }
    const data = result.data;
    out.textContent = `Inserted ${data.ingest.inserted}, updated ${data.ingest.updated} ` +
      `(skipped ${data.ingest.skipped_invalid_status} non-certified, ${data.ingest.skipped_missing_data} incomplete, ${data.ingest.skipped_duplicate_rows} duplicate rows).\n` +
      `Matching: ${data.rematch.auto} auto-matched, ${data.rematch.review} queued for review, ${data.rematch.prospect} prospects.`;
    await refreshAll();
  });

  document.getElementById("upload-customers").addEventListener("click", async () => {
    const input = document.getElementById("customers-file");
    const out = document.getElementById("customers-result");
    if (!input.files.length) { out.textContent = "Choose a file first."; return; }
    out.textContent = "Uploading and matching…";
    const result = await postFile("/api/upload/customers", input.files[0]);
    if (!result.ok) { out.textContent = result.message; return; }
    const data = result.data;
    out.textContent = `Enterprises created: ${data.ingest.enterprises_created}, aliases created: ${data.ingest.aliases_created}, updated: ${data.ingest.aliases_updated}.\n` +
      `Matching: ${data.rematch.auto} auto-matched, ${data.rematch.review} queued for review, ${data.rematch.prospect} prospects.`;
    await refreshAll();
  });

  document.getElementById("reset-dismissed").addEventListener("click", async () => {
    if (!confirm("Restore all dismissed matches?")) return;
    await fetch("/api/matches/dismissed/reset", { method: "POST" });
    state.cc.offset = 0; state.cp.offset = 0;
    await Promise.all([loadDismissedList(), loadSummary(), loadSection("cc"), loadSection("cp")]);
  });
}

async function loadReviewQueue() {
  const r = await fetch("/api/review-queue");
  const items = await r.json();
  const table = document.getElementById("review-table");
  table.querySelector("thead").innerHTML = `<tr><th>Disclosure employer</th><th>Suggested customer match</th><th>Confidence</th><th>Contract</th><th></th></tr>`;
  const tbody = table.querySelector("tbody");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">Nothing pending review.</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((c) => `
    <tr data-id="${c.id}">
      <td class="entity-name">${escapeHtml(c.employer_name)}</td>
      <td>${c.candidate_enterprise ? escapeHtml(c.candidate_enterprise.name) : ""}</td>
      <td>${c.match_confidence ? c.match_confidence.toFixed(0) + "%" : ""}</td>
      <td class="sub">${escapeHtml(c.job_title || "")}, ${escapeHtml(c.worksite_city || "")} ${escapeHtml(c.worksite_state || "")} &middot; ${fmtDate(c.contract_start)}&ndash;${fmtDate(c.contract_end)} &middot; ${c.worker_count} workers</td>
      <td>
        <button class="small-btn approve" data-action="approve">Approve</button>
        <button class="small-btn reject" data-action="reject">Reject</button>
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("tr");
      const id = row.dataset.id;
      const action = btn.dataset.action;
      await fetch(`/api/review-queue/${id}/${action}`, { method: "POST" });
      await loadReviewQueue();
      await loadStats();
    });
  });
}

async function loadDismissedList() {
  const r = await fetch("/api/matches/dismissed");
  const items = await r.json();
  document.getElementById("dismissed-count").textContent = items.length ? `(${items.length})` : "";
  const table = document.getElementById("dismissed-table");
  table.querySelector("thead").innerHTML = `<tr><th>Ending contract</th><th>Starting contract</th><th>Dismissed</th><th></th></tr>`;
  const tbody = table.querySelector("tbody");
  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="muted">Nothing dismissed.</td></tr>`;
    return;
  }
  tbody.innerHTML = items.map((d) => `
    <tr data-id="${d.id}">
      <td>
        <div class="entity-name">${escapeHtml(entityLabel(d.from_contract))}</div>
        <div class="sub">Ends ${fmtDate(d.from_contract.contract_end)}</div>
      </td>
      <td>
        <div class="entity-name">${escapeHtml(entityLabel(d.to_contract))}</div>
        <div class="sub">Starts ${fmtDate(d.to_contract.contract_start)}</div>
      </td>
      <td class="sub">${fmtDate(d.dismissed_at.slice(0, 10))}</td>
      <td><button class="small-btn approve" data-action="restore">Restore</button></td>
    </tr>
  `).join("");

  tbody.querySelectorAll('button[data-action="restore"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.closest("tr").dataset.id;
      await fetch(`/api/matches/dismissed/${id}/restore`, { method: "POST" });
      state.cc.offset = 0; state.cp.offset = 0;
      await Promise.all([loadDismissedList(), loadSummary(), loadSection("cc"), loadSection("cp")]);
    });
  });
}

// ---------- tabs ----------

function wireTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });
}

async function refreshAll() {
  await Promise.all([
    loadStats(), loadSummary(), loadSection("cc"), loadSection("cp"),
    loadReviewQueue(), loadDismissedList(),
  ]);
}

wireTabs();
wireDashboard();
wireSearch();
wireAdmin();
refreshAll();
