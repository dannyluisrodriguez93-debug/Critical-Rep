/* ══════════════════════════════════════════════════════════════════════
   Account Hub — Frontend SPA   (Part A: core + dashboard + sidebar)
   ══════════════════════════════════════════════════════════════════════ */
"use strict";

// ── State ─────────────────────────────────────────────────────────────
const STATE = {
  accounts: [], systems: [], alerts: [], unmatched: [],
  lastSync: null,
  currentAccountId: null,
  currentAccountData: null,
};

// ── API ───────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: {"Content-Type":"application/json"}, ...opts });
  if (!r.ok) { const t = await r.text(); throw new Error(`${r.status}: ${t}`); }
  return r.json();
}
const post  = (p, b) => api(p, { method:"POST",   body: JSON.stringify(b) });
const patch = (p, b) => api(p, { method:"PATCH",  body: JSON.stringify(b) });
const del   = (p)    => api(p, { method:"DELETE" });

// ── Formatting ────────────────────────────────────────────────────────
function fmtCurrency(n) {
  if (n == null || isNaN(n)) return "$0";
  return "$" + Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
}
function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s.includes("T") ? s : s + "T00:00:00");
  return d.toLocaleDateString("en-US", { month:"short", day:"numeric", year:"numeric" });
}
function fmtDateShort(s) {
  if (!s) return "—";
  const d = new Date(s.includes("T") ? s : s + "T00:00:00");
  return d.toLocaleDateString("en-US", { month:"short", day:"numeric" });
}
function fmtDateTime(s) {
  if (!s) return "—";
  const d = new Date(s.includes("T") ? s : s + "T00:00:00");
  return d.toLocaleDateString("en-US", { month:"short", day:"numeric", year:"numeric" }) +
         " " + d.toLocaleTimeString("en-US", { hour:"numeric", minute:"2-digit" });
}
function fmtPct(n) { return n == null ? "0%" : Number(n).toFixed(1) + "%"; }
function fmtUnits(n) { return n == null ? "0" : Number(n).toLocaleString(); }
function daysSince(s) {
  if (!s) return Infinity;
  return Math.floor((Date.now() - new Date(s.includes("T") ? s : s+"T00:00:00").getTime()) / 86400000);
}
function fmtDaysAgo(s) {
  const d = daysSince(s);
  if (d === Infinity) return "Never";
  if (d === 0) return "Today";
  if (d === 1) return "Yesterday";
  return `${d}d ago`;
}
function healthDot(rev30, lastOrder) {
  const d = daysSince(lastOrder);
  if (rev30 > 0 && d < 14) return "green";
  if (rev30 > 0 || d < 21) return "yellow";
  if (lastOrder) return "red";
  return "gray";
}
function escHtml(s) {
  const el = document.createElement("div"); el.textContent = s || ""; return el.innerHTML;
}
function initials(name) {
  return (name || "?").split(" ").map(w => w[0]).join("").slice(0,2).toUpperCase();
}
function fileIcon(name, mime) {
  const ext = (name || "").split(".").pop().toLowerCase();
  const m = mime || "";
  if (["pdf"].includes(ext)) return "📄";
  if (["docx","doc"].includes(ext) || m.includes("word")) return "📝";
  if (["xlsx","xls","csv"].includes(ext) || m.includes("spreadsheet") || m.includes("excel")) return "📊";
  if (["pptx","ppt"].includes(ext) || m.includes("presentation")) return "📋";
  if (["one"].includes(ext) || m.includes("onenote")) return "📓";
  if (["msg","eml"].includes(ext)) return "📧";
  return "📁";
}

// ── Toast ─────────────────────────────────────────────────────────────
function toast(msg, type="info") {
  const c = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`; el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => { el.style.opacity="0"; el.style.transition="opacity 0.3s";
    setTimeout(() => el.remove(), 300); }, 3500);
}

// ── Modal ─────────────────────────────────────────────────────────────
function openModal(title, bodyHtml) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  document.getElementById("modal-overlay").classList.remove("hidden");
}
function closeModal(e) {
  if (e && e.target !== document.getElementById("modal-overlay")) return;
  document.getElementById("modal-overlay").classList.add("hidden");
}

// ── Sidebar ───────────────────────────────────────────────────────────
function renderSidebar() {
  const el = document.getElementById("account-list");
  const search = document.getElementById("account-search").value.toLowerCase().trim();
  const grouped = {}, ungrouped = [];

  for (const a of STATE.accounts) {
    const hit = !search ||
      (a.name||"").toLowerCase().includes(search) ||
      (a.system_name||"").toLowerCase().includes(search) ||
      (a.aliases||[]).some(x => x.toLowerCase().includes(search));
    if (!hit) continue;
    if (a.system_name) { (grouped[a.system_name] = grouped[a.system_name]||[]).push(a); }
    else ungrouped.push(a);
  }

  let html = "";
  for (const sys of Object.keys(grouped).sort()) {
    html += `<div class="system-group">
      <div class="system-label" onclick="toggleSystem(this)">
        <span class="chevron">▾</span>${escHtml(sys)}<span style="color:var(--text-muted);margin-left:auto;font-size:0.7rem">${grouped[sys].length}</span>
      </div><div class="system-accounts">`;
    for (const a of grouped[sys]) html += sidebarItem(a);
    html += "</div></div>";
  }
  if (ungrouped.length) {
    html += `<div class="system-group"><div class="system-label" onclick="toggleSystem(this)">
      <span class="chevron">▾</span>Ungrouped<span style="color:var(--text-muted);margin-left:auto;font-size:0.7rem">${ungrouped.length}</span>
      </div><div class="system-accounts">`;
    for (const a of ungrouped) html += sidebarItem(a);
    html += "</div></div>";
  }
  el.innerHTML = html || `<div class="empty-state">No accounts found</div>`;
}

function sidebarItem(a) {
  const dot = healthDot(a.revenue_30d, a.last_order);
  const active = a.id === STATE.currentAccountId ? " active" : "";
  const rev = a.revenue_30d ? fmtCurrency(a.revenue_30d) : "";
  const tegs = a.teg_count ? `<span style="font-size:0.65rem;color:#2dd4bf;margin-left:2px">${a.teg_count}T</span>` : "";
  return `<div class="account-item${active}" onclick="selectAccount(${a.id})" title="${escHtml(a.name)}">
    <span class="dot ${dot}"></span>
    <span class="acct-name">${escHtml(a.name)}</span>
    ${tegs}
    <span class="acct-rev">${rev}</span>
  </div>`;
}

function toggleSystem(el) {
  el.classList.toggle("collapsed");
  el.nextElementSibling.classList.toggle("collapsed");
}

document.getElementById("account-search").addEventListener("input", renderSidebar);
document.getElementById("sidebar-toggle").addEventListener("click", () =>
  document.getElementById("sidebar").classList.toggle("collapsed"));

// ── Dashboard ─────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    STATE.accounts  = data.accounts  || [];
    STATE.systems   = data.systems   || [];
    STATE.alerts    = data.alerts    || [];
    STATE.unmatched = data.unmatched || [];
    STATE.lastSync  = data.last_sync;
    renderSidebar();
    renderDashboardView();
    renderAlertBanner();
    renderSyncLabel();
  } catch(e) { toast("Failed to load dashboard: " + e.message, "error"); }
}

function renderDashboardView() {
  const totalRev = STATE.accounts.reduce((s,a) => s+(a.revenue_30d||0), 0);
  const active   = STATE.accounts.filter(a => a.revenue_30d > 0).length;
  const crit     = STATE.alerts.filter(a => a.level === "critical").length;
  const totalTegs= STATE.accounts.reduce((s,a) => s+(a.teg_count||0), 0);

  document.getElementById("kpi-row").innerHTML =
    kpiCard("Accounts",       STATE.accounts.length, `${active} active`, "") +
    kpiCard("30-Day Revenue", fmtCurrency(totalRev), `${active} purchasing accounts`, "green") +
    kpiCard("TEGs in Field",  totalTegs,  "across all accounts", "teal-kpi") +
    kpiCard("Active Alerts",  STATE.alerts.length, `${crit} critical`, STATE.alerts.length ? "red" : "green");

  const aC = document.getElementById("alert-count");
  aC.textContent = STATE.alerts.length;
  aC.className = "badge" + (STATE.alerts.length ? " red" : "");
  document.getElementById("alerts-list").innerHTML = STATE.alerts.length
    ? STATE.alerts.map(a => `<div class="alert-item" onclick="selectAccount(${a.account_id})">
        <span class="alert-icon ${a.level}"></span>
        <div><div class="alert-msg">${escHtml(a.message)}</div>
        <div class="alert-type">${escHtml(a.type)}</div></div></div>`).join("")
    : `<div class="empty-state">No active alerts 🎉</div>`;

  const uC = document.getElementById("unmatched-count");
  uC.textContent = STATE.unmatched.length;
  uC.className = "badge" + (STATE.unmatched.length ? " yellow" : "");
  document.getElementById("unmatched-list").innerHTML = STATE.unmatched.length
    ? STATE.unmatched.map(u => `<div class="unmatched-item">
        <span class="unmatched-name">${escHtml(u.raw_name)}</span>
        <span class="unmatched-date">${fmtDate(u.first_seen)}</span>
        <button class="btn btn-sm btn-primary" onclick="showResolveUnmatched('${escHtml(u.raw_name).replace(/'/g,"\\'")}')">Resolve</button>
      </div>`).join("")
    : `<div class="empty-state">All names matched ✓</div>`;

  const sorted = [...STATE.accounts].filter(a=>a.revenue_30d>0)
    .sort((a,b)=>(b.revenue_30d||0)-(a.revenue_30d||0)).slice(0,20);
  document.getElementById("top-accounts-table").innerHTML = sorted.length
    ? `<table><thead><tr><th>Account</th><th>System</th>
        <th class="right">30-Day Rev</th><th class="right">TEGs</th>
        <th class="right">Last Order</th><th>Health</th></tr></thead><tbody>` +
      sorted.map(a => `<tr style="cursor:pointer" onclick="selectAccount(${a.id})">
        <td>${escHtml(a.name)}</td>
        <td class="subtitle">${escHtml(a.system_name||"—")}</td>
        <td class="right mono green">${fmtCurrency(a.revenue_30d)}</td>
        <td class="right">${a.teg_count ? `<span style="color:#2dd4bf;font-weight:700">${a.teg_count}</span>` : "—"}</td>
        <td class="right mono">${fmtDate(a.last_order)}</td>
        <td><span class="dot ${healthDot(a.revenue_30d,a.last_order)}"></span></td>
      </tr>`).join("") + "</tbody></table>"
    : `<div class="empty-state">No sales data yet — click Email to sync reports.</div>`;
}

function kpiCard(label, value, sub, color) {
  const cls = color === "teal-kpi" ? "" : (color ? ` ${color}` : "");
  const style = color === "teal-kpi" ? ' style="color:#2dd4bf"' : "";
  return `<div class="kpi-card">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value${cls}"${style}>${value}</div>
    ${sub ? `<div class="kpi-sub">${sub}</div>` : ""}
  </div>`;
}

function renderAlertBanner() {
  const b = document.getElementById("alert-banner");
  const crit = STATE.alerts.filter(a=>a.level==="critical");
  if (crit.length) {
    b.className = "alert-banner critical";
    b.textContent = `${crit.length} critical alert${crit.length>1?"s":""}: ${crit[0].message}`;
    b.classList.remove("hidden");
  } else if (STATE.alerts.length) {
    b.className = "alert-banner warning";
    b.textContent = `${STATE.alerts.length} active alert${STATE.alerts.length>1?"s":""}`;
    b.classList.remove("hidden");
  } else { b.classList.add("hidden"); }
}

function renderSyncLabel() {
  document.getElementById("last-sync").textContent =
    STATE.lastSync ? "Last sync: " + fmtDate(STATE.lastSync) : "Not synced yet";
}

// ── View switching ─────────────────────────────────────────────────────
function showDashboard() {
  STATE.currentAccountId = null; STATE.currentAccountData = null;
  document.getElementById("view-dashboard").classList.add("active");
  document.getElementById("view-account").classList.remove("active");
  renderSidebar();
}
function showAccountView() {
  document.getElementById("view-dashboard").classList.remove("active");
  document.getElementById("view-account").classList.add("active");
  activateTab("tab-overview");
}
function activateTab(id) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelector(`.tab[data-tab="${id}"]`)?.classList.add("active");
  document.getElementById(id)?.classList.add("active");
}
document.querySelectorAll(".tab").forEach(t =>
  t.addEventListener("click", () => activateTab(t.dataset.tab)));

// ── Account selection ─────────────────────────────────────────────────
async function selectAccount(id) {
  STATE.currentAccountId = id;
  renderSidebar();
  try {
    const days = document.getElementById("sales-days")?.value || 90;
    const data = await api(`/api/accounts/${id}?days=${days}`);
    STATE.currentAccountData = data;
    renderAccountHomepage(data);
    showAccountView();
  } catch(e) { toast("Failed to load account: " + e.message, "error"); }
}
async function reloadAccountDetail() {
  if (STATE.currentAccountId) await selectAccount(STATE.currentAccountId);
}

/* ══════════════════════════════════════════════════════════════════════
   Part B: Account Homepage — hero, TEG, tally, comms, tabs
   ══════════════════════════════════════════════════════════════════════ */

// ── Account Homepage Master Renderer ─────────────────────────────────
function renderAccountHomepage(data) {
  const a     = data.account;
  const sales = data.sales_summary      || [];
  const cs    = data.cartridge_summary  || {};
  const tgts  = data.targets            || {};
  const ords  = data.recent_orders      || [];
  const ctcts = data.contacts           || [];
  const notes = data.notes              || [];
  const tegs  = data.tegs               || [];
  const comms = data.comms              || [];
  const cstats= data.comm_stats         || [];
  const files = data.files              || [];

  renderHero(a, tgts, ords, tegs, data);
  renderTEGInventory(tegs);
  renderCartridgeTally(cs);
  renderCommActivity(cstats);
  renderTargets(tgts);
  renderRecentOrders(ords);
  renderSalesTable(sales);
  renderContacts(ctcts, cstats);
  renderNotes(notes);
  renderFiles(files);
  renderActivityLog(comms, ctcts);
}

// ── Hero ──────────────────────────────────────────────────────────────
function renderHero(a, tgts, ords, tegs, data) {
  document.getElementById("acct-name").textContent    = a.name;
  document.getElementById("acct-system").textContent  = a.system_name || "";
  const loc = [a.city, a.state].filter(Boolean).join(", ");
  document.getElementById("acct-location").textContent = loc;

  const setHeroBadge = (id, text, show) => {
    const el = document.getElementById(id);
    el.textContent = text;
    el.classList.toggle("hidden", !show);
  };
  setHeroBadge("acct-territory",  a.territory || "",                              !!a.territory);
  setHeroBadge("acct-teg-count",  `${tegs.length} TEG${tegs.length!==1?"s":""}`, tegs.length > 0);

  const lastOrder = ords.length ? ords[0].report_date : null;
  const d = daysSince(lastOrder);
  if (lastOrder) {
    const el = document.getElementById("acct-last-order");
    el.textContent = `Last order: ${fmtDaysAgo(lastOrder)}`;
    el.className = `hero-badge ${d < 14 ? "green" : d < 21 ? "orange" : "red"}`;
    el.classList.remove("hidden");
  } else { document.getElementById("acct-last-order").classList.add("hidden"); }

  const mth = tgts.month;
  if (mth && mth.target > 0) {
    const pct = mth.pct_of_target || 0;
    const el = document.getElementById("acct-target-pct");
    el.textContent = `MTD ${fmtPct(pct)}`;
    el.className = `hero-badge ${pct >= 80 ? "green" : pct >= 50 ? "orange" : "red"}`;
    el.classList.remove("hidden");
  } else { document.getElementById("acct-target-pct").classList.add("hidden"); }

  // KPI strip
  const totalRev = (data?.sales_summary || []).reduce((s,r)=>s+(r.total_revenue||0),0);
  const cartRev  = (data?.cartridge_summary?.total_cartridge_revenue || 0);
  const qcRev    = (data?.cartridge_summary?.total_qc_revenue || 0);
  const cartUnits= (data?.cartridge_summary?.total_cartridge_units || 0);
  const qcUnits  = (data?.cartridge_summary?.total_qc_units || 0);

  document.getElementById("acct-kpi-row").innerHTML =
    kpiCard("Period Revenue",    fmtCurrency(totalRev), `${(document.getElementById("sales-days")?.value||90)}d window`, "green") +
    kpiCard("Cartridge Revenue", fmtCurrency(cartRev),  `${fmtUnits(cartUnits)} units`, "green") +
    kpiCard("QC Revenue",        fmtCurrency(qcRev),    `${fmtUnits(qcUnits)} units`, "") +
    kpiCard("TEG Machines",      tegs.length,           `${tegs.filter(t=>t.cartridge_types.length).length} configured`, "teal-kpi");
}

// ── TEG Inventory ─────────────────────────────────────────────────────
function renderTEGInventory(tegs) {
  const el = document.getElementById("teg-list");
  document.getElementById("teg-total-count").textContent = tegs.length;

  if (!tegs.length) {
    el.innerHTML = `<div class="teg-empty">
      <div style="font-size:2rem;margin-bottom:8px">🔬</div>
      <div>No TEG machines registered</div>
      <div style="font-size:0.75rem;margin-top:4px;color:var(--text-muted)">Add machines to track location and cartridge types</div>
    </div>`; return;
  }

  el.innerHTML = tegs.map(t => `
    <div class="teg-card">
      <div class="teg-card-header">
        <div>
          <div class="teg-dept">${escHtml(t.department||"—")}</div>
          <div class="teg-location">${escHtml(t.location)}</div>
          <div class="teg-model">${escHtml(t.model||"TEG Analyzer")}</div>
          ${t.serial_number ? `<div class="teg-serial">S/N: ${escHtml(t.serial_number)}</div>` : ""}
        </div>
        <div class="teg-actions">
          <button class="icon-btn" title="Edit" onclick="showEditTEG(${t.id})">✏️</button>
          <button class="icon-btn" title="Remove" onclick="deleteTEG(${t.id})">🗑️</button>
        </div>
      </div>
      ${t.cartridge_types.length ? `
        <div class="teg-cartridges">
          ${t.cartridge_types.map(c=>`<span class="cart-chip">${escHtml(c)}</span>`).join("")}
        </div>` : `<div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px">No cartridges configured</div>`}
      ${t.notes ? `<div style="font-size:0.75rem;color:var(--text-muted);margin-top:6px">${escHtml(t.notes)}</div>` : ""}
    </div>`).join("");
}

// ── Cartridge & QC Tally ──────────────────────────────────────────────
function renderCartridgeTally(cs) {
  const el = document.getElementById("tally-body");
  const cartridges = cs.cartridges || [];
  const qc = cs.qc || [];
  const other = cs.other || [];

  if (!cartridges.length && !qc.length && !other.length) {
    el.innerHTML = `<div class="empty-state" style="padding:24px">No sales data for this period</div>`; return;
  }

  const maxCart = cartridges.reduce((m,r)=>Math.max(m,r.total_units||0),0) || 1;
  const maxQC   = qc.reduce((m,r)=>Math.max(m,r.total_units||0),0) || 1;

  let html = "";

  if (cartridges.length) {
    html += `<div class="tally-section">
      <div class="tally-section-label cartridges">
        &#9670; Cartridges
        <span class="tally-total">${fmtUnits(cs.total_cartridge_units)} units · ${fmtCurrency(cs.total_cartridge_revenue)}</span>
      </div>`;
    for (const r of cartridges) {
      const pct = ((r.total_units||0)/maxCart*100).toFixed(1);
      html += `<div class="tally-row">
        <span class="tally-name" title="${escHtml(r.description)}">${escHtml(r.description)}</span>
        <div class="tally-bar-wrap"><div class="tally-bar-fill" style="width:${pct}%;background:var(--accent)"></div></div>
        <span class="tally-units">${fmtUnits(r.total_units)}</span>
        <span class="tally-rev">${fmtCurrency(r.total_revenue)}</span>
      </div>`;
    }
    html += "</div>";
  }

  if (qc.length) {
    if (cartridges.length) html += `<hr class="tally-section-divider">`;
    html += `<div class="tally-section">
      <div class="tally-section-label qc">
        &#9670; QC Material
        <span class="tally-total">${fmtUnits(cs.total_qc_units)} units · ${fmtCurrency(cs.total_qc_revenue)}</span>
      </div>`;
    for (const r of qc) {
      const pct = ((r.total_units||0)/maxQC*100).toFixed(1);
      html += `<div class="tally-row">
        <span class="tally-name" title="${escHtml(r.description)}">${escHtml(r.description)}</span>
        <div class="tally-bar-wrap"><div class="tally-bar-fill" style="width:${pct}%;background:var(--yellow)"></div></div>
        <span class="tally-units">${fmtUnits(r.total_units)}</span>
        <span class="tally-rev">${fmtCurrency(r.total_revenue)}</span>
      </div>`;
    }
    html += "</div>";
  }

  if (other.length) {
    html += `<hr class="tally-section-divider"><div class="tally-section">
      <div class="tally-section-label other">&#9670; Other</div>`;
    const maxO = other.reduce((m,r)=>Math.max(m,r.total_units||0),0)||1;
    for (const r of other) {
      const pct = ((r.total_units||0)/maxO*100).toFixed(1);
      html += `<div class="tally-row">
        <span class="tally-name">${escHtml(r.description)}</span>
        <div class="tally-bar-wrap"><div class="tally-bar-fill" style="width:${pct}%;background:var(--text-muted)"></div></div>
        <span class="tally-units">${fmtUnits(r.total_units)}</span>
        <span class="tally-rev">${fmtCurrency(r.total_revenue)}</span>
      </div>`;
    }
    html += "</div>";
  }
  el.innerHTML = html;
}

async function refreshTally() {
  if (!STATE.currentAccountId) return;
  const days = document.getElementById("tally-days").value;
  try {
    const data = await api(`/api/accounts/${STATE.currentAccountId}?days=${days}`);
    renderCartridgeTally(data.cartridge_summary || {});
  } catch(e) { toast("Failed to refresh: " + e.message, "error"); }
}

// ── Communication Activity ────────────────────────────────────────────
function renderCommActivity(stats) {
  const el = document.getElementById("comm-activity-body");
  if (!stats.length) {
    el.innerHTML = `<div class="empty-state">
      <div>No communication data yet</div>
      <div style="font-size:0.75rem;margin-top:6px;color:var(--text-muted)">Sync iMessage or log interactions manually</div>
    </div>`; return;
  }

  el.innerHTML = stats.map(s => {
    const lastD = daysSince(s.last_contact);
    const freqClass = s.comms_30d >= 8 ? "freq-high" : s.comms_30d >= 3 ? "freq-medium"
                    : s.comms_30d >= 1 ? "freq-low" : "freq-none";
    const freqLabel = s.comms_30d >= 8 ? "Active" : s.comms_30d >= 3 ? "Regular"
                    : s.comms_30d >= 1 ? "Occasional" : "No contact";

    const statCls = lastD < 7 ? "active" : lastD < 21 ? "stale" : lastD < 45 ? "cold" : "none";

    const textLine = s.last_text
      ? `<span class="comm-stat ${statCls}"><span class="icon">💬</span>${fmtDaysAgo(s.last_text)}</span>` : "";
    const callLine = s.last_call
      ? `<span class="comm-stat"><span class="icon">📞</span>${fmtDaysAgo(s.last_call)}</span>` : "";
    const visitLine = s.last_visit
      ? `<span class="comm-stat"><span class="icon">🤝</span>${fmtDaysAgo(s.last_visit)}</span>` : "";
    const totalLine = `<span class="comm-stat"><span class="icon">📊</span>${s.total_comms||0} total</span>`;

    return `<div class="comm-contact-row" onclick="showLogComm(${s.contact_id})">
      <div class="comm-avatar">${escHtml(initials(s.contact_name))}</div>
      <div class="comm-contact-info">
        <div class="comm-contact-name">${escHtml(s.contact_name||"Unknown")}</div>
        <div class="comm-contact-role">${escHtml(s.contact_role||"")}</div>
        <div class="comm-contact-stats">
          ${textLine}${callLine}${visitLine}${totalLine}
        </div>
      </div>
      <span class="comm-freq-badge ${freqClass}">${freqLabel}</span>
    </div>`;
  }).join("");
}

// ── Overview Tab: Targets ─────────────────────────────────────────────
function renderTargets(tgts) {
  const el = document.getElementById("acct-targets");
  const periods = [
    { key:"month",   label:"Month-to-Date" },
    { key:"quarter", label:"Quarter-to-Date" },
    { key:"year",    label:"Year-to-Date" },
  ];
  let html = '<div class="target-grid">';
  let any = false;
  for (const { key, label } of periods) {
    const t = tgts[key];
    if (!t) continue; any = true;
    const pct = t.pct_of_target || 0;
    const barColor = pct >= 80 ? "green" : pct >= 50 ? "yellow" : "red";
    const barW = Math.min(pct, 100).toFixed(1);
    html += `<div class="target-card">
      <div class="tc-period">${label}</div>
      <div class="tc-pct ${barColor}">${fmtPct(pct)}</div>
      <div class="tc-bar-wrap"><div class="tc-bar ${barColor}" style="width:${barW}%"></div></div>
      <div class="tc-values">
        <span class="tc-actual">${fmtCurrency(t.actual)}</span>
        <span class="tc-target">/ ${fmtCurrency(t.target)}</span>
      </div>
      ${t.rr_actual ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px">Run-rate: ${fmtCurrency(t.rr_actual)}</div>` : ""}
      ${t.py_revenue ? `<div style="font-size:0.72rem;color:var(--text-muted)">PY: ${fmtCurrency(t.py_revenue)}</div>` : ""}
    </div>`;
  }
  html += "</div>";
  el.innerHTML = any ? html : `<div class="empty-state">No revenue targets loaded. Targets are parsed from PDF attachments in email reports.</div>`;
}

// ── Overview Tab: Recent Orders ───────────────────────────────────────
function renderRecentOrders(ords) {
  const el = document.getElementById("acct-recent-orders");
  document.getElementById("recent-orders-sub").textContent =
    ords.length ? `${ords.length} most recent shipments` : "";
  if (!ords.length) { el.innerHTML = `<div class="empty-state">No orders found</div>`; return; }
  el.innerHTML = `<table><thead><tr>
    <th>Date</th><th>Product</th><th>Item #</th><th>Category</th>
    <th class="right">Units</th><th class="right">Revenue</th><th>Tracking</th>
  </tr></thead><tbody>` +
  ords.map(o => `<tr>
    <td class="mono">${fmtDate(o.report_date)}</td>
    <td>${escHtml(o.description)}</td>
    <td class="mono">${escHtml(o.item_number||"")}</td>
    <td><span class="tag muted">${escHtml(o.category||"—")}</span></td>
    <td class="right mono">${fmtUnits(o.units)}</td>
    <td class="right mono green">${fmtCurrency(o.revenue)}</td>
    <td class="mono" style="font-size:0.72rem">${o.tracking?escHtml(o.tracking):"—"}</td>
  </tr>`).join("") + "</tbody></table>";
}

// ── Sales Tab ─────────────────────────────────────────────────────────
function renderSalesTable(sales) {
  const el = document.getElementById("acct-sales-table");
  if (!sales.length) { el.innerHTML = `<div class="empty-state">No sales data for this period</div>`; return; }
  el.innerHTML = `<table><thead><tr>
    <th>Product</th><th>Line</th><th>Category</th><th>Item #</th>
    <th class="right">Units</th><th class="right">Revenue</th><th>Last Order</th>
  </tr></thead><tbody>` +
  sales.map(s => `<tr>
    <td>${escHtml(s.description)}</td>
    <td><span class="tag muted">${escHtml(s.prod_line||"—")}</span></td>
    <td><span class="tag muted">${escHtml(s.category||"—")}</span></td>
    <td class="mono">${escHtml(s.item_number||"")}</td>
    <td class="right mono">${fmtUnits(s.total_units)}</td>
    <td class="right mono green">${fmtCurrency(s.total_revenue)}</td>
    <td class="mono">${fmtDate(s.last_order_date)}</td>
  </tr>`).join("") + "</tbody></table>";
}

// ── Contacts Tab ──────────────────────────────────────────────────────
function renderContacts(contacts, commStats) {
  const el = document.getElementById("acct-contacts");
  if (!contacts.length) {
    el.innerHTML = `<div class="empty-state">No contacts yet.</div>`; return;
  }
  const statMap = {};
  for (const s of (commStats||[])) statMap[s.contact_id] = s;

  el.innerHTML = `<div class="contact-grid">` +
  contacts.map(c => {
    const s = statMap[c.id];
    const commHtml = s ? `<div class="cc-comm">
      ${s.last_text  ? `<span class="cc-comm-stat">💬 <strong>${fmtDaysAgo(s.last_text)}</strong></span>` : ""}
      ${s.last_call  ? `<span class="cc-comm-stat">📞 <strong>${fmtDaysAgo(s.last_call)}</strong></span>` : ""}
      ${s.last_visit ? `<span class="cc-comm-stat">🤝 <strong>${fmtDaysAgo(s.last_visit)}</strong></span>` : ""}
      <span class="cc-comm-stat" style="margin-left:auto">${s.comms_30d||0} this month</span>
    </div>` : "";
    return `<div class="contact-card">
      <div class="cc-name">${escHtml(c.name)}</div>
      ${c.role  ? `<div class="cc-role">${escHtml(c.role)}</div>` : ""}
      <div class="cc-info">
        ${c.phone ? `<div>📞 ${escHtml(c.phone)}</div>` : ""}
        ${c.email ? `<div>✉️ ${escHtml(c.email)}</div>` : ""}
        ${c.imessage_handle ? `<div style="color:var(--accent);font-size:0.72rem">iMsg: ${escHtml(c.imessage_handle)}</div>` : ""}
        ${c.notes ? `<div style="margin-top:6px;color:var(--text-muted)">${escHtml(c.notes)}</div>` : ""}
      </div>
      ${commHtml}
      <div class="cc-actions">
        <button class="btn btn-sm btn-ghost" onclick="showEditContact(${c.id})">Edit</button>
        <button class="btn btn-sm btn-ghost btn-danger" onclick="deleteContact(${c.id})">Delete</button>
        <button class="btn btn-sm btn-ghost" onclick="showLogComm(${c.id})" style="margin-left:auto">+ Log</button>
      </div>
    </div>`;
  }).join("") + "</div>";
}

// ── Notes Tab ─────────────────────────────────────────────────────────
function renderNotes(notes) {
  const el = document.getElementById("acct-notes");
  const sources = [...new Set(notes.map(n=>n.source))];
  document.getElementById("notes-sources").textContent =
    sources.length ? `Sources: ${sources.join(", ")}` : "";
  if (!notes.length) { el.innerHTML = `<div class="empty-state">No notes yet.</div>`; return; }
  el.innerHTML = notes.map(n => `<div class="note-item">
    <div class="note-header">
      <span class="note-title">${escHtml(n.title||"Untitled")}</span>
      <span class="note-source">${escHtml(n.source)}</span>
      <span class="note-date">${fmtDate(n.note_date||n.updated_at)}</span>
    </div>
    <div class="note-content">${escHtml(n.content||"")}</div>
  </div>`).join("");
}

// ── Files Tab ─────────────────────────────────────────────────────────
function renderFiles(files) {
  const el = document.getElementById("acct-files");
  if (!files.length) {
    el.innerHTML = `<div class="empty-state">
      <div>No OneDrive files linked</div>
      <div style="font-size:0.75rem;margin-top:6px;color:var(--text-muted)">Click "Sync Drive" to find files matching this account</div>
    </div>`; return;
  }
  el.innerHTML = `<div class="file-grid">` +
  files.map(f => `<a class="file-card" href="${escHtml(f.web_url||"#")}" target="_blank" rel="noopener">
    <span class="file-icon">${fileIcon(f.name, f.mime_type)}</span>
    <div class="file-name">${escHtml(f.name)}</div>
    <div class="file-meta">
      ${f.modified_at ? fmtDate(f.modified_at) : ""}
      ${f.size ? " · " + fmtFileSize(f.size) : ""}
    </div>
  </a>`).join("") + "</div>";
}

function fmtFileSize(b) {
  if (b > 1048576) return (b/1048576).toFixed(1) + " MB";
  if (b > 1024)    return (b/1024).toFixed(0) + " KB";
  return b + " B";
}

// ── Activity Log Tab ──────────────────────────────────────────────────
function renderActivityLog(comms, contacts) {
  const el = document.getElementById("acct-activity");
  if (!comms.length) {
    el.innerHTML = `<div class="empty-state">No communication history yet.</div>`; return;
  }
  const contactMap = {};
  for (const c of (contacts||[])) contactMap[c.id] = c;

  el.innerHTML = `<div class="activity-timeline">` +
  comms.map(c => {
    const typ = (c.type||"").toLowerCase();
    const who = c.contact_name || (contactMap[c.contact_id]?.name) || "Unknown";
    const preview = c.message_preview || c.notes || "";
    return `<div class="activity-item">
      <span class="activity-dot ${typ}"></span>
      <div class="activity-header">
        <span class="activity-type ${typ}">${escHtml(c.type||"—")}</span>
        <span class="activity-contact">${escHtml(who)}</span>
        ${c.duration_sec ? `<span class="subtitle">${Math.round(c.duration_sec/60)}m</span>` : ""}
        <span class="activity-date">${fmtDateTime(c.occurred_at)}</span>
      </div>
      ${preview ? `<div class="activity-preview">${escHtml(preview.slice(0,200))}</div>` : ""}
    </div>`;
  }).join("") + "</div>";
}

/* ══════════════════════════════════════════════════════════════════════
   Part C: Modals — Account, Contact, Note, TEG, Comm Log, Resolve
   ══════════════════════════════════════════════════════════════════════ */

// ── TEG Modals ────────────────────────────────────────────────────────
const TEG_MODELS = ["TEG 5000", "TEG 6s", "TEGfunctional"];
const TEG_DEPTS  = ["OR","CVICU","ICU","Cath Lab","ED","NICU","PACU","Labor & Delivery","Other"];
const CART_TYPES = [
  "Kaolin (K)","Kaolin + Heparinase (KH)","RapidTEG (RT)","Platelet Mapping (PM)",
  "Functional Fibrinogen (FF)","Citrated Kaolin (CK)","CKH","CKHF","CFF-TEG",
  "EG-TBI","Delta","QC - Normal","QC - High","QC - Low"
];

function cartridgeCheckboxes(selected) {
  return CART_TYPES.map(ct => {
    const chk = (selected||[]).includes(ct) ? "checked" : "";
    return `<label style="display:flex;align-items:center;gap:6px;padding:4px 0;cursor:pointer">
      <input type="checkbox" value="${escHtml(ct)}" ${chk} style="accent-color:var(--accent)">
      <span style="font-size:0.82rem">${escHtml(ct)}</span>
    </label>`;
  }).join("");
}

function getCheckedCartridges(containerId) {
  return [...document.querySelectorAll(`#${containerId} input[type=checkbox]:checked`)]
    .map(cb => cb.value);
}

function showAddTEG() {
  if (!STATE.currentAccountId) return;
  openModal("Add TEG Machine", `
    <div class="form-row">
      <div class="form-group">
        <label>Location / Room *</label>
        <input type="text" id="teg-loc" placeholder="e.g. OR Suite 2, CVICU Bed 4">
      </div>
      <div class="form-group">
        <label>Department</label>
        <select id="teg-dept">${TEG_DEPTS.map(d=>`<option>${d}</option>`).join("")}</select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Model</label>
        <select id="teg-model">${TEG_MODELS.map(m=>`<option>${m}</option>`).join("")}</select>
      </div>
      <div class="form-group">
        <label>Serial Number</label>
        <input type="text" id="teg-serial" placeholder="Optional">
      </div>
    </div>
    <div class="form-group">
      <label>Cartridge Types Run on This Machine</label>
      <div id="teg-cart-checks" style="display:grid;grid-template-columns:1fr 1fr;gap:0 12px;max-height:240px;overflow-y:auto;padding:8px;background:var(--bg-input);border:1px solid var(--border);border-radius:var(--radius)">
        ${cartridgeCheckboxes([])}
      </div>
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="teg-notes" placeholder="e.g. shared with PACU, awaiting calibration…"></textarea>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="addTEG()">Add Machine</button>
    </div>`);
  setTimeout(() => document.getElementById("teg-loc")?.focus(), 100);
}

async function addTEG() {
  const loc = document.getElementById("teg-loc").value.trim();
  if (!loc) { toast("Location is required", "error"); return; }
  try {
    await post(`/api/accounts/${STATE.currentAccountId}/tegs`, {
      location: loc,
      department: document.getElementById("teg-dept").value,
      model: document.getElementById("teg-model").value,
      serial_number: document.getElementById("teg-serial").value.trim()||null,
      notes: document.getElementById("teg-notes").value.trim()||null,
      cartridge_types: getCheckedCartridges("teg-cart-checks"),
    });
    closeModal(); toast("TEG machine added", "success");
    await reloadAccountDetail();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

function showEditTEG(tegId) {
  const teg = (STATE.currentAccountData?.tegs||[]).find(t=>t.id===tegId);
  if (!teg) return;
  openModal("Edit TEG Machine", `
    <div class="form-row">
      <div class="form-group">
        <label>Location / Room *</label>
        <input type="text" id="teg-loc" value="${escHtml(teg.location)}">
      </div>
      <div class="form-group">
        <label>Department</label>
        <select id="teg-dept">${TEG_DEPTS.map(d=>`<option ${d===teg.department?"selected":""}>${d}</option>`).join("")}</select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Model</label>
        <select id="teg-model">${TEG_MODELS.map(m=>`<option ${m===teg.model?"selected":""}>${m}</option>`).join("")}</select>
      </div>
      <div class="form-group">
        <label>Serial Number</label>
        <input type="text" id="teg-serial" value="${escHtml(teg.serial_number||"")}">
      </div>
    </div>
    <div class="form-group">
      <label>Cartridge Types</label>
      <div id="teg-cart-checks" style="display:grid;grid-template-columns:1fr 1fr;gap:0 12px;max-height:240px;overflow-y:auto;padding:8px;background:var(--bg-input);border:1px solid var(--border);border-radius:var(--radius)">
        ${cartridgeCheckboxes(teg.cartridge_types||[])}
      </div>
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="teg-notes">${escHtml(teg.notes||"")}</textarea>
    </div>
    <div class="form-actions">
      <button class="btn btn-ghost btn-danger" onclick="deleteTEG(${tegId})">Remove Machine</button>
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="updateTEG(${tegId})">Save</button>
    </div>`);
}

async function updateTEG(tegId) {
  try {
    await patch(`/api/tegs/${tegId}`, {
      location: document.getElementById("teg-loc").value.trim(),
      department: document.getElementById("teg-dept").value,
      model: document.getElementById("teg-model").value,
      serial_number: document.getElementById("teg-serial").value.trim()||null,
      notes: document.getElementById("teg-notes").value.trim()||null,
      cartridge_types: getCheckedCartridges("teg-cart-checks"),
    });
    closeModal(); toast("TEG updated", "success");
    await reloadAccountDetail();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

async function deleteTEG(tegId) {
  if (!confirm("Remove this TEG machine?")) return;
  try {
    await del(`/api/tegs/${tegId}`);
    closeModal(); toast("TEG removed", "success");
    await reloadAccountDetail();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

// ── Contact Modals ────────────────────────────────────────────────────
function showAddContact() {
  openModal("Add Contact", `
    <div class="form-group"><label>Name *</label>
      <input type="text" id="contact-name" placeholder="Full name"></div>
    <div class="form-group"><label>Role / Title</label>
      <input type="text" id="contact-role" placeholder="e.g. Perfusionist, OR Director, Lab Manager"></div>
    <div class="form-row">
      <div class="form-group"><label>Phone</label>
        <input type="tel" id="contact-phone" placeholder="(555) 123-4567"></div>
      <div class="form-group"><label>Email</label>
        <input type="email" id="contact-email" placeholder="name@hospital.org"></div>
    </div>
    <div class="form-group"><label>iMessage Handle</label>
      <input type="text" id="contact-imsg" placeholder="Phone # or email used in iMessage (for comm tracking)"></div>
    <div class="form-group"><label>Notes</label>
      <textarea id="contact-notes" placeholder="Preferences, context, scheduling…"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="addContact()">Add Contact</button>
    </div>`);
  setTimeout(() => document.getElementById("contact-name")?.focus(), 100);
}

async function addContact() {
  const name = document.getElementById("contact-name").value.trim();
  if (!name) { toast("Name required", "error"); return; }
  try {
    await post(`/api/accounts/${STATE.currentAccountId}/contacts`, {
      name, role: v("contact-role"), phone: v("contact-phone"),
      email: v("contact-email"), notes: v("contact-notes"),
      imessage_handle: v("contact-imsg"),
    });
    closeModal(); toast(`Contact "${name}" added`, "success");
    await reloadAccountDetail();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

function showEditContact(contactId) {
  const c = (STATE.currentAccountData?.contacts||[]).find(x=>x.id===contactId);
  if (!c) return;
  openModal("Edit Contact", `
    <div class="form-group"><label>Name *</label>
      <input type="text" id="contact-name" value="${escHtml(c.name)}"></div>
    <div class="form-group"><label>Role / Title</label>
      <input type="text" id="contact-role" value="${escHtml(c.role||"")}"></div>
    <div class="form-row">
      <div class="form-group"><label>Phone</label>
        <input type="tel" id="contact-phone" value="${escHtml(c.phone||"")}"></div>
      <div class="form-group"><label>Email</label>
        <input type="email" id="contact-email" value="${escHtml(c.email||"")}"></div>
    </div>
    <div class="form-group"><label>iMessage Handle</label>
      <input type="text" id="contact-imsg" value="${escHtml(c.imessage_handle||"")}"></div>
    <div class="form-group"><label>Notes</label>
      <textarea id="contact-notes">${escHtml(c.notes||"")}</textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="updateContact(${contactId})">Save</button>
    </div>`);
}

async function updateContact(id) {
  try {
    await patch(`/api/contacts/${id}`, {
      name: v("contact-name"), role: v("contact-role"),
      phone: v("contact-phone"), email: v("contact-email"),
      notes: v("contact-notes"), imessage_handle: v("contact-imsg"),
    });
    closeModal(); toast("Contact updated", "success");
    await reloadAccountDetail();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

async function deleteContact(id) {
  if (!confirm("Delete this contact?")) return;
  try { await del(`/api/contacts/${id}`); toast("Deleted", "success"); await reloadAccountDetail(); }
  catch(e) { toast("Failed: " + e.message, "error"); }
}

// ── Note Modal ────────────────────────────────────────────────────────
function showAddNote() {
  openModal("Add Note", `
    <div class="form-group"><label>Title</label>
      <input type="text" id="note-title" placeholder="e.g. Visit Notes ${new Date().toLocaleDateString()}"></div>
    <div class="form-group"><label>Content *</label>
      <textarea id="note-content" style="min-height:160px" placeholder="Write your note here…"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="addNote()">Save Note</button>
    </div>`);
  setTimeout(() => document.getElementById("note-title")?.focus(), 100);
}

async function addNote() {
  const content = document.getElementById("note-content").value.trim();
  if (!content) { toast("Content required", "error"); return; }
  try {
    await post(`/api/accounts/${STATE.currentAccountId}/notes`, { content, title: v("note-title") });
    closeModal(); toast("Note saved", "success");
    await reloadAccountDetail();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

// ── Communication Log Modal ───────────────────────────────────────────
function showLogComm(preContactId) {
  if (!STATE.currentAccountId) return;
  const contacts = STATE.currentAccountData?.contacts || [];
  const contactOpts = contacts.map(c =>
    `<option value="${c.id}" ${c.id===preContactId?"selected":""}>${escHtml(c.name)}${c.role?" — "+escHtml(c.role):""}</option>`
  ).join("");

  const now = new Date();
  const localISO = new Date(now - now.getTimezoneOffset()*60000).toISOString().slice(0,16);

  openModal("Log Interaction", `
    <div class="form-row">
      <div class="form-group"><label>Type *</label>
        <select id="comm-type">
          <option value="call">📞 Phone Call</option>
          <option value="visit">🤝 In-Person Visit</option>
          <option value="text">💬 Text Message</option>
          <option value="email">✉️ Email</option>
          <option value="imessage">💬 iMessage</option>
        </select></div>
      <div class="form-group"><label>Date &amp; Time *</label>
        <input type="datetime-local" id="comm-date" value="${localISO}"></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>Contact</label>
        <select id="comm-contact"><option value="">— No specific contact —</option>${contactOpts}</select></div>
      <div class="form-group"><label>Duration (min, calls only)</label>
        <input type="number" id="comm-dur" placeholder="e.g. 15" min="0"></div>
    </div>
    <div class="form-group"><label>Notes</label>
      <textarea id="comm-notes" placeholder="What was discussed? Any follow-ups?"></textarea></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="logComm()">Save</button>
    </div>`);
}

async function logComm() {
  const type = document.getElementById("comm-type").value;
  const dateVal = document.getElementById("comm-date").value;
  if (!type || !dateVal) { toast("Type and date required", "error"); return; }
  const dur = parseInt(document.getElementById("comm-dur").value)||null;
  const cid = parseInt(document.getElementById("comm-contact").value)||null;
  try {
    await post(`/api/accounts/${STATE.currentAccountId}/comms`, {
      type, occurred_at: new Date(dateVal).toISOString(),
      contact_id: cid,
      duration_sec: dur ? dur * 60 : null,
      notes: v("comm-notes"),
    });
    closeModal(); toast("Interaction logged", "success");
    await reloadAccountDetail();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

// ── Add Account Modal ─────────────────────────────────────────────────
document.getElementById("btn-add-account").addEventListener("click", () => {
  openModal("New Account", `
    <div class="form-group"><label>Account Name *</label>
      <input type="text" id="new-acct-name" placeholder="e.g. Baptist Hospital Miami"></div>
    <div class="form-group"><label>Hospital System</label>
      <select id="new-acct-system">
        <option value="">— None —</option>
        ${STATE.systems.map(s=>`<option value="${s.id}">${escHtml(s.name)}</option>`).join("")}
      </select></div>
    <div class="form-row">
      <div class="form-group"><label>City</label><input type="text" id="new-acct-city"></div>
      <div class="form-group"><label>State</label><input type="text" id="new-acct-state"></div>
    </div>
    <div class="form-group"><label>Territory</label><input type="text" id="new-acct-territory"></div>
    <div class="form-group"><label>Aliases (comma-separated)</label>
      <input type="text" id="new-acct-aliases" placeholder="e.g. Baptist Hosp, BHM"></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="createAccount()">Create</button>
    </div>`);
  setTimeout(() => document.getElementById("new-acct-name")?.focus(), 100);
});

async function createAccount() {
  const name = document.getElementById("new-acct-name").value.trim();
  if (!name) { toast("Name required", "error"); return; }
  const sysId = document.getElementById("new-acct-system").value;
  const aliasStr = document.getElementById("new-acct-aliases").value;
  try {
    await post("/api/accounts", {
      name, system_id: sysId ? parseInt(sysId) : null,
      city: v("new-acct-city"), state: v("new-acct-state"),
      territory: v("new-acct-territory"),
      aliases: aliasStr ? aliasStr.split(",").map(x=>x.trim()).filter(Boolean) : [],
    });
    closeModal(); toast(`Account "${name}" created`, "success");
    await loadDashboard();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

// ── Resolve Unmatched ─────────────────────────────────────────────────
function showResolveUnmatched(rawName) {
  const opts = STATE.accounts.map(a =>
    `<option value="${a.id}">${escHtml(a.name)}${a.system_name?" ("+escHtml(a.system_name)+")":""}</option>`
  ).join("");
  openModal("Resolve Unmatched Account", `
    <p style="margin-bottom:14px;color:var(--text-secondary);font-size:0.85rem">
      <strong>"${escHtml(rawName)}"</strong> appeared in a report but couldn't be matched.
      Select the correct account to add it as an alias.
    </p>
    <div class="form-group"><label>Map to Account</label>
      <select id="resolve-account">${opts}</select></div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="resolveUnmatched('${escHtml(rawName).replace(/'/g,"\\'")}')">Resolve &amp; Add Alias</button>
    </div>`);
}

async function resolveUnmatched(rawName) {
  const acctId = document.getElementById("resolve-account").value;
  if (!acctId) return;
  try {
    await post("/api/unmatched/resolve", { raw_name: rawName, account_id: parseInt(acctId) });
    closeModal(); toast(`"${rawName}" resolved`, "success");
    await loadDashboard();
  } catch(e) { toast("Failed: " + e.message, "error"); }
}

// ── Sync Actions ──────────────────────────────────────────────────────
async function syncEmail() {
  try { const r = await post("/api/sync/email", {days_back:7}); toast(r.message,"info"); }
  catch(e) { toast("Sync failed: "+e.message,"error"); }
}
async function syncNotes() {
  try { const r = await post("/api/sync/notes",{}); toast(r.message,"info"); }
  catch(e) { toast("Sync failed: "+e.message,"error"); }
}
async function syncOneDrive() {
  try { const r = await post("/api/sync/onedrive",{}); toast(r.message,"info"); }
  catch(e) { toast("Sync failed: "+e.message,"error"); }
}
async function synciMessage() {
  try { const r = await post("/api/sync/imessage",{}); toast(r.message,"info"); }
  catch(e) { toast("Sync failed: "+e.message,"error"); }
}
async function syncSalesforce() {
  try { const r = await post("/api/sync/salesforce",{}); toast(r.message,"info"); }
  catch(e) { toast("Sync failed: "+e.message,"error"); }
}

// ── Helpers ───────────────────────────────────────────────────────────
function v(id) { return (document.getElementById(id)?.value||"").trim()||null; }

// ── Keyboard shortcuts ────────────────────────────────────────────────
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeModal();
  if ((e.ctrlKey||e.metaKey) && e.key === "k") { e.preventDefault(); document.getElementById("account-search").focus(); }
  if ((e.ctrlKey||e.metaKey) && e.key === "b") { e.preventDefault(); document.getElementById("sidebar").classList.toggle("collapsed"); }
});

// ── Boot ──────────────────────────────────────────────────────────────
loadDashboard();
