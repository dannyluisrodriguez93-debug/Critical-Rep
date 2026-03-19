/* ══════════════════════════════════════════════════════════════════════
   Account Hub — Frontend Application
   Single-page app powered by vanilla JS + the Flask REST API
   ══════════════════════════════════════════════════════════════════════ */

"use strict";

// ── State ─────────────────────────────────────────────────────────────
let STATE = {
  accounts: [],
  systems: [],
  alerts: [],
  unmatched: [],
  lastSync: null,
  currentAccountId: null,
  currentAccountData: null,
};

// ── API helpers ───────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

function post(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function patch(path, body) {
  return api(path, { method: "PATCH", body: JSON.stringify(body) });
}

function del(path) {
  return api(path, { method: "DELETE" });
}

// ── Formatting ────────────────────────────────────────────────────────

function fmtCurrency(n) {
  if (n == null || isNaN(n)) return "$0";
  return "$" + Number(n).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(s + (s.includes("T") ? "" : "T00:00:00"));
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtPct(n) {
  if (n == null || isNaN(n)) return "0%";
  return Number(n).toFixed(1) + "%";
}

function daysSince(dateStr) {
  if (!dateStr) return Infinity;
  const d = new Date(dateStr + (dateStr.includes("T") ? "" : "T00:00:00"));
  return Math.floor((Date.now() - d.getTime()) / 86400000);
}

function healthDot(revenue30d, lastOrder) {
  const days = daysSince(lastOrder);
  if (revenue30d > 0 && days < 14) return "green";
  if (revenue30d > 0 || days < 21) return "yellow";
  if (lastOrder) return "red";
  return "gray";
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

// ── Toast notifications ───────────────────────────────────────────────

function toast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity 0.3s";
    setTimeout(() => el.remove(), 300);
  }, 3500);
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

// ── Dashboard loading ─────────────────────────────────────────────────

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    STATE.accounts = data.accounts || [];
    STATE.systems = data.systems || [];
    STATE.alerts = data.alerts || [];
    STATE.unmatched = data.unmatched || [];
    STATE.lastSync = data.last_sync;

    renderSidebar();
    renderDashboardView();
    renderAlertBanner();
    renderSyncLabel();
  } catch (err) {
    console.error("Failed to load dashboard:", err);
    toast("Failed to load dashboard data", "error");
  }
}

// ── Sidebar ───────────────────────────────────────────────────────────

function renderSidebar() {
  const el = document.getElementById("account-list");
  const search = document.getElementById("account-search").value.toLowerCase().trim();

  // Group by system
  const grouped = {};
  const ungrouped = [];

  for (const acct of STATE.accounts) {
    const name = (acct.name || "").toLowerCase();
    const sysName = (acct.system_name || "").toLowerCase();
    const aliases = (acct.aliases || []).join(" ").toLowerCase();
    if (search && !name.includes(search) && !sysName.includes(search) && !aliases.includes(search)) {
      continue;
    }
    if (acct.system_name) {
      if (!grouped[acct.system_name]) grouped[acct.system_name] = [];
      grouped[acct.system_name].push(acct);
    } else {
      ungrouped.push(acct);
    }
  }

  let html = "";

  // Systems
  const systemNames = Object.keys(grouped).sort();
  for (const sysName of systemNames) {
    const accounts = grouped[sysName];
    html += `<div class="system-group">
      <div class="system-label" onclick="toggleSystem(this)">
        <span class="chevron">&#9662;</span> ${escHtml(sysName)} (${accounts.length})
      </div>
      <div class="system-accounts">`;
    for (const acct of accounts) {
      html += renderAccountItem(acct);
    }
    html += `</div></div>`;
  }

  // Ungrouped
  if (ungrouped.length) {
    html += `<div class="system-group">
      <div class="system-label" onclick="toggleSystem(this)">
        <span class="chevron">&#9662;</span> Ungrouped (${ungrouped.length})
      </div>
      <div class="system-accounts">`;
    for (const acct of ungrouped) {
      html += renderAccountItem(acct);
    }
    html += `</div></div>`;
  }

  if (!html) {
    html = `<div class="empty-state">No accounts found</div>`;
  }

  el.innerHTML = html;
}

function renderAccountItem(acct) {
  const dot = healthDot(acct.revenue_30d, acct.last_order);
  const active = acct.id === STATE.currentAccountId ? " active" : "";
  const rev = acct.revenue_30d ? fmtCurrency(acct.revenue_30d) : "";
  return `<div class="account-item${active}" onclick="selectAccount(${acct.id})" title="${escHtml(acct.name)}">
    <span class="dot ${dot}"></span>
    <span class="acct-name">${escHtml(acct.name)}</span>
    <span class="acct-rev">${rev}</span>
  </div>`;
}

function toggleSystem(labelEl) {
  labelEl.classList.toggle("collapsed");
  const accounts = labelEl.nextElementSibling;
  accounts.classList.toggle("collapsed");
}

// ── Search ────────────────────────────────────────────────────────────

document.getElementById("account-search").addEventListener("input", () => {
  renderSidebar();
});

// ── Sidebar toggle ────────────────────────────────────────────────────

document.getElementById("sidebar-toggle").addEventListener("click", () => {
  document.getElementById("sidebar").classList.toggle("collapsed");
});

// ── Dashboard View ────────────────────────────────────────────────────

function renderDashboardView() {
  // KPIs
  const totalAccounts = STATE.accounts.length;
  const totalRevenue30d = STATE.accounts.reduce((s, a) => s + (a.revenue_30d || 0), 0);
  const activeAccounts = STATE.accounts.filter(a => a.revenue_30d > 0).length;
  const critAlerts = STATE.alerts.filter(a => a.level === "critical").length;

  document.getElementById("kpi-row").innerHTML = `
    ${kpiCard("Total Accounts", totalAccounts, "")}
    ${kpiCard("30-Day Revenue", fmtCurrency(totalRevenue30d), `${activeAccounts} active accounts`, "green")}
    ${kpiCard("Active Alerts", STATE.alerts.length, `${critAlerts} critical`, STATE.alerts.length > 0 ? "red" : "green")}
    ${kpiCard("Unmatched", STATE.unmatched.length, "Needs resolution", STATE.unmatched.length > 0 ? "yellow" : "green")}
  `;

  // Alerts
  document.getElementById("alert-count").textContent = STATE.alerts.length;
  document.getElementById("alert-count").className = "badge" + (STATE.alerts.length > 0 ? " red" : "");
  const alertsHtml = STATE.alerts.length
    ? STATE.alerts.map(a => `
      <div class="alert-item" onclick="selectAccount(${a.account_id})">
        <span class="alert-icon ${a.level}"></span>
        <div>
          <div class="alert-msg">${escHtml(a.message)}</div>
          <div class="alert-type">${escHtml(a.type)}</div>
        </div>
      </div>`).join("")
    : `<div class="empty-state">No active alerts</div>`;
  document.getElementById("alerts-list").innerHTML = alertsHtml;

  // Unmatched
  document.getElementById("unmatched-count").textContent = STATE.unmatched.length;
  document.getElementById("unmatched-count").className = "badge" + (STATE.unmatched.length > 0 ? " yellow" : "");
  const unmatchedHtml = STATE.unmatched.length
    ? STATE.unmatched.map(u => `
      <div class="unmatched-item">
        <span class="unmatched-name">${escHtml(u.raw_name)}</span>
        <span class="unmatched-date">${fmtDate(u.first_seen)}</span>
        <button class="btn btn-sm btn-primary" onclick="showResolveUnmatched('${escHtml(u.raw_name)}')">Resolve</button>
      </div>`).join("")
    : `<div class="empty-state">All accounts matched</div>`;
  document.getElementById("unmatched-list").innerHTML = unmatchedHtml;

  // Top accounts table
  const sorted = [...STATE.accounts]
    .filter(a => a.revenue_30d > 0)
    .sort((a, b) => (b.revenue_30d || 0) - (a.revenue_30d || 0))
    .slice(0, 15);

  let tableHtml = "";
  if (sorted.length) {
    tableHtml = `<table>
      <thead><tr>
        <th>Account</th><th>System</th><th class="right">30-Day Revenue</th>
        <th class="right">Last Order</th><th>Status</th>
      </tr></thead><tbody>`;
    for (const a of sorted) {
      const dot = healthDot(a.revenue_30d, a.last_order);
      tableHtml += `<tr style="cursor:pointer" onclick="selectAccount(${a.id})">
        <td>${escHtml(a.name)}</td>
        <td class="subtitle">${escHtml(a.system_name || "—")}</td>
        <td class="right mono green">${fmtCurrency(a.revenue_30d)}</td>
        <td class="right mono">${fmtDate(a.last_order)}</td>
        <td><span class="dot ${dot}"></span></td>
      </tr>`;
    }
    tableHtml += `</tbody></table>`;
  } else {
    tableHtml = `<div class="empty-state">No sales data yet. Sync emails to import reports.</div>`;
  }
  document.getElementById("top-accounts-table").innerHTML = tableHtml;
}

function kpiCard(label, value, sub, color) {
  const cls = color ? ` ${color}` : "";
  return `<div class="kpi-card">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value${cls}">${value}</div>
    ${sub ? `<div class="kpi-sub">${sub}</div>` : ""}
  </div>`;
}

function renderAlertBanner() {
  const banner = document.getElementById("alert-banner");
  const crit = STATE.alerts.filter(a => a.level === "critical");
  if (crit.length > 0) {
    banner.className = "alert-banner critical";
    banner.textContent = `${crit.length} critical alert${crit.length > 1 ? "s" : ""}: ${crit[0].message}`;
    banner.classList.remove("hidden");
  } else if (STATE.alerts.length > 0) {
    banner.className = "alert-banner warning";
    banner.textContent = `${STATE.alerts.length} active alert${STATE.alerts.length > 1 ? "s" : ""}`;
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

function renderSyncLabel() {
  const el = document.getElementById("last-sync");
  if (STATE.lastSync) {
    el.textContent = `Last sync: ${fmtDate(STATE.lastSync)}`;
  } else {
    el.textContent = "Not synced yet";
  }
}

// ── View switching ────────────────────────────────────────────────────

function showDashboard() {
  STATE.currentAccountId = null;
  STATE.currentAccountData = null;
  document.getElementById("view-dashboard").classList.add("active");
  document.getElementById("view-account").classList.remove("active");
  renderSidebar();
}

function showAccountView() {
  document.getElementById("view-dashboard").classList.remove("active");
  document.getElementById("view-account").classList.add("active");
  // Reset to overview tab
  activateTab("tab-overview");
}

// ── Account selection ─────────────────────────────────────────────────

async function selectAccount(id) {
  STATE.currentAccountId = id;
  renderSidebar(); // highlight active

  try {
    const days = document.getElementById("sales-days")?.value || 90;
    const data = await api(`/api/accounts/${id}?days=${days}`);
    STATE.currentAccountData = data;
    renderAccountDetail(data);
    showAccountView();
  } catch (err) {
    console.error("Failed to load account:", err);
    toast("Failed to load account details", "error");
  }
}

async function reloadAccountDetail() {
  if (STATE.currentAccountId) {
    await selectAccount(STATE.currentAccountId);
  }
}

function renderAccountDetail(data) {
  const acct = data.account;
  const sales = data.sales_summary || [];
  const orders = data.recent_orders || [];
  const targets = data.targets || {};
  const contacts = data.contacts || [];
  const notes = data.notes || [];

  // Header
  document.getElementById("acct-name").textContent = acct.name;
  document.getElementById("acct-system").textContent = acct.system_name || "";
  document.getElementById("acct-territory").textContent = acct.territory || "";
  document.getElementById("acct-territory").className = "tag" + (acct.territory ? "" : " hidden");

  const loc = [acct.city, acct.state].filter(Boolean).join(", ");
  document.getElementById("acct-location").textContent = loc;

  // KPIs
  const totalRev = sales.reduce((s, r) => s + (r.total_revenue || 0), 0);
  const totalUnits = sales.reduce((s, r) => s + (r.total_units || 0), 0);
  const lastOrderDate = orders.length ? orders[0].report_date : null;
  const daysSinceOrder = daysSince(lastOrderDate);

  document.getElementById("acct-kpi-row").innerHTML = `
    ${kpiCard("Period Revenue", fmtCurrency(totalRev), `${sales.length} products`, "green")}
    ${kpiCard("Units Shipped", totalUnits.toLocaleString(), "", "")}
    ${kpiCard("Last Order", lastOrderDate ? fmtDate(lastOrderDate) : "N/A",
      lastOrderDate ? `${daysSinceOrder} days ago` : "", daysSinceOrder > 20 ? "red" : "green")}
    ${kpiCard("Products", sales.length, "", "")}
  `;

  // Targets
  renderTargets(targets);

  // Recent orders
  renderRecentOrders(orders);

  // Sales table
  renderSalesTable(sales);

  // Contacts
  renderContacts(contacts);

  // Notes
  renderNotes(notes);
}

// ── Targets ───────────────────────────────────────────────────────────

function renderTargets(targets) {
  const el = document.getElementById("acct-targets");
  const periods = ["month", "quarter", "year"];
  const labels = { month: "Month-to-Date", quarter: "Quarter-to-Date", year: "Year-to-Date" };
  let html = '<div class="target-grid">';

  let hasAny = false;
  for (const p of periods) {
    const t = targets[p];
    if (!t) continue;
    hasAny = true;
    const pct = t.pct_of_target || 0;
    const barColor = pct >= 80 ? "green" : pct >= 50 ? "yellow" : "red";
    const barWidth = Math.min(pct, 100);

    html += `<div class="target-card">
      <div class="tc-period">${labels[p]}</div>
      <div class="tc-pct ${barColor}">${fmtPct(pct)}</div>
      <div class="tc-bar-wrap"><div class="tc-bar ${barColor}" style="width:${barWidth}%"></div></div>
      <div class="tc-values">
        <span class="tc-actual">${fmtCurrency(t.actual)}</span>
        <span class="tc-target">/ ${fmtCurrency(t.target)}</span>
      </div>
      ${t.py_revenue ? `<div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px">PY: ${fmtCurrency(t.py_revenue)}</div>` : ""}
    </div>`;
  }

  html += "</div>";
  el.innerHTML = hasAny ? html : `<div class="empty-state">No revenue targets loaded yet</div>`;
}

// ── Recent Orders ─────────────────────────────────────────────────────

function renderRecentOrders(orders) {
  const el = document.getElementById("acct-recent-orders");
  if (!orders.length) {
    el.innerHTML = `<div class="empty-state">No recent orders</div>`;
    return;
  }

  let html = `<table>
    <thead><tr>
      <th>Date</th><th>Product</th><th>Item #</th>
      <th class="right">Units</th><th class="right">Revenue</th>
      <th>Tracking</th>
    </tr></thead><tbody>`;

  for (const o of orders) {
    html += `<tr>
      <td class="mono">${fmtDate(o.report_date)}</td>
      <td>${escHtml(o.description)}</td>
      <td class="mono">${escHtml(o.item_number || "")}</td>
      <td class="right mono">${(o.units || 0).toLocaleString()}</td>
      <td class="right mono green">${fmtCurrency(o.revenue)}</td>
      <td class="mono" style="font-size:0.75rem">${o.tracking ? escHtml(o.tracking) : "—"}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  el.innerHTML = html;
}

// ── Sales table ───────────────────────────────────────────────────────

function renderSalesTable(sales) {
  const el = document.getElementById("acct-sales-table");
  if (!sales.length) {
    el.innerHTML = `<div class="empty-state">No sales data for this period</div>`;
    return;
  }

  let html = `<table>
    <thead><tr>
      <th>Product</th><th>Line</th><th>Item #</th>
      <th class="right">Units</th><th class="right">Revenue</th>
      <th>Last Order</th>
    </tr></thead><tbody>`;

  for (const s of sales) {
    html += `<tr>
      <td>${escHtml(s.description)}</td>
      <td><span class="tag muted">${escHtml(s.prod_line || "—")}</span></td>
      <td class="mono">${escHtml(s.item_number || "")}</td>
      <td class="right mono">${(s.total_units || 0).toLocaleString()}</td>
      <td class="right mono green">${fmtCurrency(s.total_revenue)}</td>
      <td class="mono">${fmtDate(s.last_order_date)}</td>
    </tr>`;
  }
  html += `</tbody></table>`;
  el.innerHTML = html;
}

// ── Contacts ──────────────────────────────────────────────────────────

function renderContacts(contacts) {
  const el = document.getElementById("acct-contacts");
  if (!contacts.length) {
    el.innerHTML = `<div class="empty-state">No contacts yet. Add one to get started.</div>`;
    return;
  }

  let html = '<div class="contact-grid">';
  for (const c of contacts) {
    html += `<div class="contact-card">
      <div class="cc-name">${escHtml(c.name)}</div>
      ${c.role ? `<div class="cc-role">${escHtml(c.role)}</div>` : ""}
      <div class="cc-info">
        ${c.phone ? `<div>&#9743; ${escHtml(c.phone)}</div>` : ""}
        ${c.email ? `<div>&#9993; ${escHtml(c.email)}</div>` : ""}
        ${c.notes ? `<div style="margin-top:6px;color:var(--text-muted)">${escHtml(c.notes)}</div>` : ""}
      </div>
      <div class="cc-actions">
        <button class="btn btn-sm btn-ghost" onclick="showEditContact(${c.id})">Edit</button>
        <button class="btn btn-sm btn-ghost btn-danger" onclick="deleteContact(${c.id})">Delete</button>
      </div>
    </div>`;
  }
  html += "</div>";
  el.innerHTML = html;
}

// ── Notes ─────────────────────────────────────────────────────────────

function renderNotes(notes) {
  const el = document.getElementById("acct-notes");
  if (!notes.length) {
    el.innerHTML = `<div class="empty-state">No notes yet. Add one or sync from Apple Notes / OneNote.</div>`;
    return;
  }

  let html = "";
  for (const n of notes) {
    html += `<div class="note-item">
      <div class="note-header">
        <span class="note-title">${escHtml(n.title || "Untitled")}</span>
        <span class="note-source">${escHtml(n.source)}</span>
        <span class="note-date">${fmtDate(n.note_date || n.updated_at)}</span>
      </div>
      <div class="note-content">${escHtml(n.content || "")}</div>
    </div>`;
  }
  el.innerHTML = html;
}

// ── Tabs ──────────────────────────────────────────────────────────────

function activateTab(tabId) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  document.querySelector(`.tab[data-tab="${tabId}"]`)?.classList.add("active");
  document.getElementById(tabId)?.classList.add("active");
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

// ── Add Account Modal ─────────────────────────────────────────────────

document.getElementById("btn-add-account").addEventListener("click", () => {
  openModal("New Account", `
    <div class="form-group">
      <label>Account Name *</label>
      <input type="text" id="new-acct-name" placeholder="e.g. Baptist Hospital">
    </div>
    <div class="form-group">
      <label>Hospital System</label>
      <select id="new-acct-system">
        <option value="">— None —</option>
        ${STATE.systems.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join("")}
      </select>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>City</label>
        <input type="text" id="new-acct-city">
      </div>
      <div class="form-group">
        <label>State</label>
        <input type="text" id="new-acct-state">
      </div>
    </div>
    <div class="form-group">
      <label>Territory</label>
      <input type="text" id="new-acct-territory">
    </div>
    <div class="form-group">
      <label>Aliases (comma-separated)</label>
      <input type="text" id="new-acct-aliases" placeholder="e.g. Baptist Hosp, Baptist Hospital Miami">
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="createAccount()">Create Account</button>
    </div>
  `);
  setTimeout(() => document.getElementById("new-acct-name")?.focus(), 100);
});

async function createAccount() {
  const name = document.getElementById("new-acct-name").value.trim();
  if (!name) { toast("Account name is required", "error"); return; }

  const aliasStr = document.getElementById("new-acct-aliases").value;
  const aliases = aliasStr ? aliasStr.split(",").map(a => a.trim()).filter(Boolean) : [];
  const systemId = document.getElementById("new-acct-system").value;

  try {
    await post("/api/accounts", {
      name,
      system_id: systemId ? parseInt(systemId) : null,
      city: document.getElementById("new-acct-city").value.trim() || null,
      state: document.getElementById("new-acct-state").value.trim() || null,
      territory: document.getElementById("new-acct-territory").value.trim() || null,
      aliases,
    });
    closeModal();
    toast(`Account "${name}" created`, "success");
    await loadDashboard();
  } catch (err) {
    toast("Failed to create account: " + err.message, "error");
  }
}

// ── Add Contact Modal ─────────────────────────────────────────────────

function showAddContact() {
  if (!STATE.currentAccountId) return;
  openModal("Add Contact", `
    <div class="form-group">
      <label>Name *</label>
      <input type="text" id="contact-name" placeholder="Full name">
    </div>
    <div class="form-group">
      <label>Role / Title</label>
      <input type="text" id="contact-role" placeholder="e.g. Perfusionist, OR Director">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Phone</label>
        <input type="tel" id="contact-phone" placeholder="(555) 123-4567">
      </div>
      <div class="form-group">
        <label>Email</label>
        <input type="email" id="contact-email" placeholder="name@hospital.org">
      </div>
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="contact-notes" placeholder="Meeting notes, preferences, etc."></textarea>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="addContact()">Add Contact</button>
    </div>
  `);
  setTimeout(() => document.getElementById("contact-name")?.focus(), 100);
}

async function addContact() {
  const name = document.getElementById("contact-name").value.trim();
  if (!name) { toast("Contact name is required", "error"); return; }

  try {
    await post(`/api/accounts/${STATE.currentAccountId}/contacts`, {
      name,
      role: document.getElementById("contact-role").value.trim() || null,
      phone: document.getElementById("contact-phone").value.trim() || null,
      email: document.getElementById("contact-email").value.trim() || null,
      notes: document.getElementById("contact-notes").value.trim() || null,
    });
    closeModal();
    toast(`Contact "${name}" added`, "success");
    await reloadAccountDetail();
  } catch (err) {
    toast("Failed to add contact: " + err.message, "error");
  }
}

function showEditContact(contactId) {
  const contacts = STATE.currentAccountData?.contacts || [];
  const c = contacts.find(x => x.id === contactId);
  if (!c) return;

  openModal("Edit Contact", `
    <div class="form-group">
      <label>Name *</label>
      <input type="text" id="edit-contact-name" value="${escHtml(c.name)}">
    </div>
    <div class="form-group">
      <label>Role / Title</label>
      <input type="text" id="edit-contact-role" value="${escHtml(c.role || "")}">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Phone</label>
        <input type="tel" id="edit-contact-phone" value="${escHtml(c.phone || "")}">
      </div>
      <div class="form-group">
        <label>Email</label>
        <input type="email" id="edit-contact-email" value="${escHtml(c.email || "")}">
      </div>
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="edit-contact-notes">${escHtml(c.notes || "")}</textarea>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="updateContact(${contactId})">Save</button>
    </div>
  `);
}

async function updateContact(contactId) {
  try {
    await patch(`/api/contacts/${contactId}`, {
      name: document.getElementById("edit-contact-name").value.trim(),
      role: document.getElementById("edit-contact-role").value.trim() || null,
      phone: document.getElementById("edit-contact-phone").value.trim() || null,
      email: document.getElementById("edit-contact-email").value.trim() || null,
      notes: document.getElementById("edit-contact-notes").value.trim() || null,
    });
    closeModal();
    toast("Contact updated", "success");
    await reloadAccountDetail();
  } catch (err) {
    toast("Failed to update contact: " + err.message, "error");
  }
}

async function deleteContact(contactId) {
  if (!confirm("Delete this contact?")) return;
  try {
    await del(`/api/contacts/${contactId}`);
    toast("Contact deleted", "success");
    await reloadAccountDetail();
  } catch (err) {
    toast("Failed to delete contact: " + err.message, "error");
  }
}

// ── Add Note Modal ────────────────────────────────────────────────────

function showAddNote() {
  if (!STATE.currentAccountId) return;
  openModal("Add Note", `
    <div class="form-group">
      <label>Title</label>
      <input type="text" id="note-title" placeholder="e.g. Visit Notes 3/19">
    </div>
    <div class="form-group">
      <label>Content *</label>
      <textarea id="note-content" style="min-height:150px" placeholder="Write your note here..."></textarea>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="addNote()">Save Note</button>
    </div>
  `);
  setTimeout(() => document.getElementById("note-title")?.focus(), 100);
}

async function addNote() {
  const content = document.getElementById("note-content").value.trim();
  if (!content) { toast("Note content is required", "error"); return; }

  try {
    await post(`/api/accounts/${STATE.currentAccountId}/notes`, {
      title: document.getElementById("note-title").value.trim() || null,
      content,
    });
    closeModal();
    toast("Note saved", "success");
    await reloadAccountDetail();
  } catch (err) {
    toast("Failed to save note: " + err.message, "error");
  }
}

// ── Resolve Unmatched ─────────────────────────────────────────────────

function showResolveUnmatched(rawName) {
  const options = STATE.accounts.map(a =>
    `<option value="${a.id}">${escHtml(a.name)}${a.system_name ? ` (${escHtml(a.system_name)})` : ""}</option>`
  ).join("");

  openModal("Resolve: " + rawName, `
    <p style="margin-bottom:14px;color:var(--text-secondary);font-size:0.85rem">
      The name <strong>"${escHtml(rawName)}"</strong> appeared in a report but couldn't be matched
      to an existing account. Select the correct account below, and it will be added as an alias.
    </p>
    <div class="form-group">
      <label>Map to Account</label>
      <select id="resolve-account">${options}</select>
    </div>
    <div class="form-actions">
      <button class="btn" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="resolveUnmatched('${escHtml(rawName)}')">Resolve</button>
    </div>
  `);
}

async function resolveUnmatched(rawName) {
  const accountId = document.getElementById("resolve-account").value;
  if (!accountId) return;

  try {
    await post("/api/unmatched/resolve", { raw_name: rawName, account_id: parseInt(accountId) });
    closeModal();
    toast(`"${rawName}" resolved`, "success");
    await loadDashboard();
  } catch (err) {
    toast("Failed to resolve: " + err.message, "error");
  }
}

// ── Sync actions ──────────────────────────────────────────────────────

async function syncEmail() {
  try {
    const result = await post("/api/sync/email", { days_back: 7 });
    toast(result.message || "Email sync started", "info");
  } catch (err) {
    toast("Sync failed: " + err.message, "error");
  }
}

async function syncNotes() {
  try {
    const result = await post("/api/sync/notes", {});
    toast(result.message || "Notes sync started", "info");
  } catch (err) {
    toast("Sync failed: " + err.message, "error");
  }
}

async function syncSalesforce() {
  try {
    const result = await post("/api/sync/salesforce", {});
    toast(result.message || "Salesforce sync started", "info");
  } catch (err) {
    toast("Sync failed: " + err.message, "error");
  }
}

// ── Keyboard shortcuts ────────────────────────────────────────────────

document.addEventListener("keydown", (e) => {
  // Escape closes modal
  if (e.key === "Escape") {
    closeModal();
  }
  // Ctrl/Cmd+K focuses search
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    document.getElementById("account-search").focus();
  }
});

// ── Boot ──────────────────────────────────────────────────────────────

loadDashboard();
