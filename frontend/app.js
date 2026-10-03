// Base URL for backend API.
// Empty string means same origin (when served via FastAPI StaticFiles).
// Set to "http://localhost:8000" if opening the HTML file directly in a browser via file:// or another port.
const API_BASE = "";

// Global UI State
let state = {
  alerts: [],
  apiStatuses: [],
  selectedSeverity: "all",
  searchQuery: "",
  showResolved: false,
  autoRefreshTimer: null,
};

// DOM Element References
const elements = {
  connectionBadge: document.getElementById("connectionBadge"),
  updatedAtText: document.getElementById("updatedAtText"),
  autoRefreshToggle: document.getElementById("autoRefreshToggle"),
  refreshBtn: document.getElementById("refreshBtn"),
  customInputBtn: document.getElementById("customInputBtn"),
  runSampleBtn: document.getElementById("runSampleBtn"),
  statTotal: document.getElementById("statTotal"),
  statHealthy: document.getElementById("statHealthy"),
  statCritical: document.getElementById("statCritical"),
  statWarning: document.getElementById("statWarning"),
  apiStatusGrid: document.getElementById("apiStatusGrid"),
  apiStatusCount: document.getElementById("apiStatusCount"),
  filterAll: document.getElementById("filterAll"),
  filterCritical: document.getElementById("filterCritical"),
  filterWarning: document.getElementById("filterWarning"),
  searchInput: document.getElementById("searchInput"),
  showResolvedToggle: document.getElementById("showResolvedToggle"),
  alertsCountText: document.getElementById("alertsCountText"),
  resolveAllBtn: document.getElementById("resolveAllBtn"),
  alertsList: document.getElementById("alertsList"),
  emptyState: document.getElementById("emptyState"),
  errorState: document.getElementById("errorState"),
  errorMessageText: document.getElementById("errorMessageText"),
  retryBtn: document.getElementById("retryBtn"),
  loadingState: document.getElementById("loadingState"),
  customInputModal: document.getElementById("customInputModal"),
  closeModalBtn: document.getElementById("closeModalBtn"),
  cancelModalBtn: document.getElementById("cancelModalBtn"),
  submitCustomJsonBtn: document.getElementById("submitCustomJsonBtn"),
  customJsonTextarea: document.getElementById("customJsonTextarea"),
  modalError: document.getElementById("modalError"),
  actionBanner: document.getElementById("actionBanner"),
  actionBannerContent: document.getElementById("actionBannerContent"),
  closeBannerBtn: document.getElementById("closeBannerBtn"),
  quickCriticalBtn: document.getElementById("quickCriticalBtn"),
  quickWarningBtn: document.getElementById("quickWarningBtn"),
  quickHealthyBtn: document.getElementById("quickHealthyBtn"),
};

// Displays an action status banner above the summary cards
function showBanner(message, type = "info") {
  if (!elements.actionBanner || !elements.actionBannerContent) return;
  elements.actionBannerContent.textContent = message;
  elements.actionBanner.className =
    "p-3.5 rounded-xl border text-xs font-medium flex items-center justify-between transition-all shadow-sm";

  if (type === "success") {
    elements.actionBanner.classList.add("bg-emerald-50", "border-emerald-200", "text-emerald-800");
  } else if (type === "warning") {
    elements.actionBanner.classList.add("bg-amber-50", "border-amber-200", "text-amber-800");
  } else if (type === "error") {
    elements.actionBanner.classList.add("bg-red-50", "border-red-200", "text-red-800");
  } else {
    elements.actionBanner.classList.add("bg-blue-50", "border-blue-200", "text-blue-800");
  }
}

// Converts ISO timestamp to human-friendly relative time
function getRelativeTime(timestamp) {
  if (!timestamp) return "just now";
  const now = new Date();
  const date = new Date(timestamp.endsWith("Z") ? timestamp : timestamp + "Z");
  const diffSec = Math.floor((now - date) / 1000);

  if (diffSec < 10) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${Math.floor(diffHours / 24)}d ago`;
}

// Sets connection status UI
function setConnectionStatus(connected, message = null) {
  elements.connectionBadge.textContent = "";
  const dot = document.createElement("span");
  dot.className = connected
    ? "w-2 h-2 rounded-full bg-emerald-500 inline-block animate-pulse mr-1"
    : "w-2 h-2 rounded-full bg-red-500 inline-block mr-1";
  elements.connectionBadge.appendChild(dot);

  const textNode = document.createTextNode(connected ? "Connected" : (message || "Offline"));
  elements.connectionBadge.appendChild(textNode);
  elements.connectionBadge.className = `inline-flex items-center text-xs font-semibold ml-1 ${
    connected ? "text-emerald-600" : "text-red-600"
  }`;
}

// Fetches top summary card statistics
async function fetchSummary() {
  try {
    const res = await fetch(`${API_BASE}/alerts/summary`);
    if (!res.ok) throw new Error(`Summary error: ${res.statusText}`);
    const data = await res.json();

    elements.statTotal.textContent = String(data.total);
    elements.statHealthy.textContent = String(data.healthy);
    elements.statCritical.textContent = String(data.critical);
    elements.statWarning.textContent = String(data.warning);

    setConnectionStatus(true);
  } catch (err) {
    console.error("Failed to load summary stats:", err);
    setConnectionStatus(false);
  }
}

// Fetches live status for all monitored APIs
async function fetchApiStatus() {
  if (!elements.apiStatusGrid) return;
  try {
    const res = await fetch(`${API_BASE}/apis/status`);
    if (!res.ok) throw new Error(`Status error: ${res.statusText}`);
    const data = await res.json();
    state.apiStatuses = data.items || [];
    renderApiStatuses();
  } catch (err) {
    console.error("Failed to load API statuses:", err);
  }
}

// Renders compact monitored API cards
function renderApiStatuses() {
  if (!elements.apiStatusGrid) return;
  elements.apiStatusGrid.textContent = "";

  if (elements.apiStatusCount) {
    const healthyCount = state.apiStatuses.filter(s => s.is_healthy).length;
    elements.apiStatusCount.textContent = `${healthyCount}/${state.apiStatuses.length} healthy`;
  }

  state.apiStatuses.forEach(api => {
    const card = document.createElement("div");
    const isHealthy = api.is_healthy;
    card.className = `p-2.5 rounded-lg border text-xs transition shadow-sm ${
      isHealthy
        ? "bg-slate-50/80 border-slate-200 hover:border-emerald-300"
        : "bg-red-50/60 border-red-200 hover:border-red-300"
    }`;

    // Row 1: Name and Health Dot
    const headerRow = document.createElement("div");
    headerRow.className = "flex items-center justify-between gap-1 mb-1.5";

    const nameSpan = document.createElement("span");
    nameSpan.className = "font-bold text-slate-900 truncate";
    nameSpan.title = api.api_name;
    nameSpan.textContent = api.api_name;

    const dot = document.createElement("span");
    dot.className = `w-2 h-2 rounded-full flex-shrink-0 ${
      isHealthy ? "bg-emerald-500 animate-pulse" : "bg-red-500"
    }`;

    headerRow.appendChild(nameSpan);
    headerRow.appendChild(dot);
    card.appendChild(headerRow);

    // Row 2: Status Code & Latency
    const metricRow = document.createElement("div");
    metricRow.className = "flex items-center justify-between text-[11px] text-slate-500 mb-1";

    const statusBadge = document.createElement("span");
    statusBadge.className = `font-mono font-semibold px-1 py-0.2 rounded text-[10px] ${
      isHealthy
        ? "bg-emerald-100 text-emerald-800"
        : "bg-red-100 text-red-800"
    }`;
    statusBadge.textContent = api.status_code === 0 ? "CONN ERR" : `${api.status_code}`;

    const latencySpan = document.createElement("span");
    latencySpan.className = "font-mono font-medium text-slate-600";
    latencySpan.textContent = `${api.response_time_ms}ms`;

    metricRow.appendChild(statusBadge);
    metricRow.appendChild(latencySpan);
    card.appendChild(metricRow);

    // Row 3: 1h Uptime
    const uptimeRow = document.createElement("div");
    uptimeRow.className = "flex items-center justify-between text-[10px] text-slate-400 font-medium";

    const uptimeText = document.createElement("span");
    uptimeText.textContent = `${api.uptime_percentage}% 1h uptime`;

    uptimeRow.appendChild(uptimeText);
    card.appendChild(uptimeRow);

    elements.apiStatusGrid.appendChild(card);
  });
}

// Fetches alerts list from the backend
async function fetchAlerts(showLoader = false) {
  if (showLoader) {
    elements.loadingState.classList.remove("hidden");
    elements.errorState.classList.add("hidden");
  }

  try {
    const statusParam = state.showResolved ? "all" : "active";
    const res = await fetch(`${API_BASE}/alerts?status=${statusParam}`);
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    const data = await res.json();

    state.alerts = data.items || [];
    renderAlerts();
    elements.updatedAtText.textContent = "Updated just now";
    elements.errorState.classList.add("hidden");
    setConnectionStatus(true);
  } catch (err) {
    console.error("Failed to fetch alerts:", err);
    elements.errorState.classList.remove("hidden");
    elements.errorMessageText.textContent = "Backend unreachable: " + err.message;
    setConnectionStatus(false);
  } finally {
    elements.loadingState.classList.add("hidden");
  }
}

// Safely creates an alert card element using DOM methods (zero innerHTML injection)
function createAlertCard(alert) {
  const card = document.createElement("div");
  const isCritical = alert.severity === "critical";
  const borderLeftClass = isCritical ? "border-l-4 border-l-red-500" : "border-l-4 border-l-amber-500";
  card.className = `bg-white rounded-xl border border-slate-200 p-4 md:p-5 shadow-sm transition hover:shadow-md ${borderLeftClass}`;

  // Top Row: Title, Severity Pill, Occurrence Pill, Source Pill, and Resolve Button
  const topRow = document.createElement("div");
  topRow.className = "flex items-start justify-between gap-2";

  const leftMeta = document.createElement("div");
  leftMeta.className = "flex flex-wrap items-center gap-2";

  // API Name
  const apiName = document.createElement("h3");
  apiName.className = "text-base font-bold text-slate-900";
  apiName.textContent = alert.api_name || "Unknown API";
  leftMeta.appendChild(apiName);

  // Severity Badge
  const severityBadge = document.createElement("span");
  severityBadge.className = isCritical
    ? "bg-red-100 text-red-700 text-xs font-semibold px-2 py-0.5 rounded-full"
    : "bg-amber-100 text-amber-800 text-xs font-semibold px-2 py-0.5 rounded-full";
  severityBadge.textContent = alert.severity || "warning";
  leftMeta.appendChild(severityBadge);

  // Occurrence Badge ("occurred N times")
  const occurrences = alert.occurrence_count || 1;
  const occurrenceBadge = document.createElement("span");
  occurrenceBadge.className = "bg-purple-50 text-purple-700 border border-purple-200 text-xs font-semibold px-2 py-0.5 rounded-full";
  occurrenceBadge.textContent = `Occurred ${occurrences} time${occurrences > 1 ? "s" : ""}`;
  leftMeta.appendChild(occurrenceBadge);

  // Message Source Badge (AI or Template)
  const sourceBadge = document.createElement("span");
  sourceBadge.className = "bg-blue-50 text-blue-600 border border-blue-200 text-xs font-medium px-2 py-0.5 rounded-full";
  sourceBadge.textContent = alert.message_source === "ai" ? "AI" : "Template";
  leftMeta.appendChild(sourceBadge);

  topRow.appendChild(leftMeta);

  // Action Button (Resolve / Resolved)
  if (alert.status === "active") {
    const resolveBtn = document.createElement("button");
    resolveBtn.className = "flex items-center gap-1.5 px-3 py-1 bg-white text-slate-700 border border-slate-200 rounded-lg text-xs font-semibold hover:bg-slate-50 transition shadow-sm";
    
    // Checkmark SVG
    const checkSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    checkSvg.setAttribute("class", "w-3.5 h-3.5 text-slate-500");
    checkSvg.setAttribute("fill", "none");
    checkSvg.setAttribute("stroke", "currentColor");
    checkSvg.setAttribute("stroke-width", "2.5");
    checkSvg.setAttribute("viewBox", "0 0 24 24");
    const checkPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    checkPath.setAttribute("stroke-linecap", "round");
    checkPath.setAttribute("stroke-linejoin", "round");
    checkPath.setAttribute("d", "M5 13l4 4L19 7");
    checkSvg.appendChild(checkPath);
    resolveBtn.appendChild(checkSvg);

    const btnText = document.createTextNode("Resolve");
    resolveBtn.appendChild(btnText);

    resolveBtn.addEventListener("click", () => handleResolveAlert(alert.id));
    topRow.appendChild(resolveBtn);
  } else {
    const resolvedBadge = document.createElement("span");
    resolvedBadge.className = "text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 rounded-lg";
    resolvedBadge.textContent = "Resolved";
    topRow.appendChild(resolvedBadge);
  }

  card.appendChild(topRow);

  // Message Text
  const messageP = document.createElement("p");
  messageP.className = "text-sm text-slate-800 mt-2 font-medium leading-relaxed";
  messageP.textContent = alert.message || "";
  card.appendChild(messageP);

  // Anomaly Tag Badges
  if (Array.isArray(alert.anomaly_types) && alert.anomaly_types.length > 0) {
    const tagsContainer = document.createElement("div");
    tagsContainer.className = "flex flex-wrap gap-1.5 mt-2.5";
    alert.anomaly_types.forEach((tag) => {
      const pill = document.createElement("span");
      pill.className = "bg-slate-50 border border-slate-200 text-slate-600 text-[11px] font-mono font-medium px-2 py-0.5 rounded";
      pill.textContent = tag;
      tagsContainer.appendChild(pill);
    });
    card.appendChild(tagsContainer);
  }

  // Telemetry Metrics Row
  const raw = alert.raw_data || {};
  const metaRow = document.createElement("div");
  metaRow.className = "text-xs text-slate-500 mt-3 flex flex-wrap items-center gap-3";

  // Status
  const statusSpan = document.createElement("span");
  statusSpan.textContent = "Status ";
  const statusVal = document.createElement("strong");
  statusVal.className = "text-slate-800 font-semibold";
  statusVal.textContent = raw.status_code !== undefined ? String(raw.status_code) : "N/A";
  statusSpan.appendChild(statusVal);
  metaRow.appendChild(statusSpan);

  // Response Time
  const responseSpan = document.createElement("span");
  responseSpan.textContent = "Response ";
  const responseVal = document.createElement("strong");
  responseVal.className = "text-slate-800 font-semibold";
  responseVal.textContent = raw.response_time_ms !== undefined ? `${raw.response_time_ms} ms` : "N/A";
  responseSpan.appendChild(responseVal);
  metaRow.appendChild(responseSpan);

  // Records
  const recordsSpan = document.createElement("span");
  recordsSpan.textContent = "Records ";
  const recordsVal = document.createElement("strong");
  recordsVal.className = "text-slate-800 font-semibold";
  recordsVal.textContent = raw.records_returned !== undefined ? String(raw.records_returned) : "N/A";
  recordsSpan.appendChild(recordsVal);
  metaRow.appendChild(recordsSpan);

  // Last Seen
  const lastSeenSpan = document.createElement("span");
  lastSeenSpan.className = "text-slate-500";
  lastSeenSpan.textContent = "Last seen ";
  const lastSeenVal = document.createElement("strong");
  lastSeenVal.className = "text-slate-700 font-medium";
  lastSeenVal.textContent = getRelativeTime(alert.last_seen_at || alert.created_at);
  lastSeenSpan.appendChild(lastSeenVal);
  metaRow.appendChild(lastSeenSpan);

  // First Detected Timestamp
  const timeSpan = document.createElement("span");
  timeSpan.className = "text-slate-400";
  timeSpan.textContent = `(First: ${getRelativeTime(alert.created_at)})`;
  metaRow.appendChild(timeSpan);

  card.appendChild(metaRow);

  // Raw Response Accordion Toggle
  const toggleBtn = document.createElement("button");
  toggleBtn.className = "text-xs font-semibold text-blue-600 hover:text-blue-700 flex items-center gap-1 mt-2.5 focus:outline-none";
  toggleBtn.textContent = "▶ Raw response";

  const rawContainer = document.createElement("pre");
  rawContainer.className = "hidden bg-slate-900 text-emerald-400 p-3 rounded-lg text-xs mt-2 overflow-x-auto font-mono";
  rawContainer.textContent = JSON.stringify(alert.raw_data, null, 2);

  toggleBtn.addEventListener("click", () => {
    const isHidden = rawContainer.classList.contains("hidden");
    if (isHidden) {
      rawContainer.classList.remove("hidden");
      toggleBtn.textContent = "▼ Raw response";
    } else {
      rawContainer.classList.add("hidden");
      toggleBtn.textContent = "▶ Raw response";
    }
  });

  card.appendChild(toggleBtn);
  card.appendChild(rawContainer);

  return card;
}

// Filters and renders alerts based on search and selected severity
function renderAlerts() {
  const query = state.searchQuery.trim().toLowerCase();

  // Compute counts for tab labels
  const totalCount = state.alerts.length;
  const criticalCount = state.alerts.filter((a) => a.severity === "critical").length;
  const warningCount = state.alerts.filter((a) => a.severity === "warning").length;

  elements.filterAll.textContent = `All (${totalCount})`;
  elements.filterCritical.textContent = `Critical (${criticalCount})`;
  elements.filterWarning.textContent = `Warning (${warningCount})`;

  // Filter alerts according to current view
  const filtered = state.alerts.filter((alert) => {
    const matchesSeverity =
      state.selectedSeverity === "all" || alert.severity === state.selectedSeverity;
    const matchesSearch =
      !query || (alert.api_name && alert.api_name.toLowerCase().includes(query));
    return matchesSeverity && matchesSearch;
  });

  elements.alertsCountText.textContent = `${filtered.length} alerts shown`;

  // Clear existing cards
  elements.alertsList.textContent = "";

  if (filtered.length === 0) {
    elements.emptyState.classList.remove("hidden");
  } else {
    elements.emptyState.classList.add("hidden");
    filtered.forEach((alert) => {
      elements.alertsList.appendChild(createAlertCard(alert));
    });
  }
}

// Updates filter tab button styling
function updateFilterTabs(activeSeverity) {
  state.selectedSeverity = activeSeverity;
  const buttons = [
    { el: elements.filterAll, sev: "all" },
    { el: elements.filterCritical, sev: "critical" },
    { el: elements.filterWarning, sev: "warning" },
  ];

  buttons.forEach(({ el, sev }) => {
    if (sev === activeSeverity) {
      el.className = "px-3.5 py-1.5 rounded-lg text-sm font-medium bg-blue-600 text-white shadow-sm transition";
    } else {
      el.className = "px-3.5 py-1.5 rounded-lg text-sm font-medium bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 transition";
    }
  });

  renderAlerts();
}

// Marks a single alert as resolved
async function handleResolveAlert(alertId) {
  try {
    const res = await fetch(`${API_BASE}/alerts/${alertId}/resolve`, {
      method: "PATCH",
    });
    if (!res.ok) throw new Error("Failed to resolve alert.");

    await fetchAlerts(false);
    await fetchSummary();
    await fetchApiStatus();
  } catch (err) {
    alert("Error resolving alert: " + err.message);
  }
}

// Resolves all currently filtered and visible active alerts
async function handleResolveAllShown() {
  const query = state.searchQuery.trim().toLowerCase();
  const visibleActiveAlerts = state.alerts.filter((alert) => {
    if (alert.status !== "active") return false;
    const matchesSeverity =
      state.selectedSeverity === "all" || alert.severity === state.selectedSeverity;
    const matchesSearch =
      !query || (alert.api_name && alert.api_name.toLowerCase().includes(query));
    return matchesSeverity && matchesSearch;
  });

  if (visibleActiveAlerts.length === 0) return;

  try {
    elements.resolveAllBtn.disabled = true;
    for (const alert of visibleActiveAlerts) {
      await fetch(`${API_BASE}/alerts/${alert.id}/resolve`, { method: "PATCH" });
    }
    await fetchAlerts(false);
    await fetchSummary();
    await fetchApiStatus();
  } catch (err) {
    alert("Error resolving all alerts: " + err.message);
  } finally {
    elements.resolveAllBtn.disabled = false;
  }
}

// Runs sample data from backend/data/sample_input.json
async function handleRunSample() {
  elements.runSampleBtn.disabled = true;
  elements.loadingState.classList.remove("hidden");

  try {
    const res = await fetch(`${API_BASE}/monitor/sample`, { method: "POST" });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.error || `HTTP ${res.status}`);
    }

    const result = await res.json();
    await fetchAlerts(false);
    await fetchSummary();
    await fetchApiStatus();

    showBanner(
      `Sample batch processed: ${result.total} APIs evaluated (${result.healthy} healthy, ${result.anomalies} anomalies detected).`,
      "info"
    );
  } catch (err) {
    alert("Failed to run sample data: " + err.message);
  } finally {
    elements.runSampleBtn.disabled = false;
    elements.loadingState.classList.add("hidden");
  }
}

// Submits custom JSON (array or single object) to POST /monitor
async function handleSubmitCustomJson() {
  elements.modalError.classList.add("hidden");
  const rawText = elements.customJsonTextarea.value.trim();

  let parsed;
  try {
    parsed = JSON.parse(rawText);
    // If a single object {...} is provided, automatically wrap into an array
    if (!Array.isArray(parsed)) {
      if (typeof parsed === "object" && parsed !== null) {
        parsed = [parsed];
      } else {
        throw new Error("Input must be a valid JSON object {...} or array of objects [{...}].");
      }
    }
    if (parsed.length === 0) {
      throw new Error("Input batch cannot be empty.");
    }
  } catch (err) {
    elements.modalError.textContent = err.message;
    elements.modalError.classList.remove("hidden");
    return;
  }

  elements.submitCustomJsonBtn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/monitor`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || errData.error || `HTTP ${res.status}`);
    }

    const result = await res.json();

    // Close modal and refresh
    elements.customInputModal.classList.add("hidden");
    await fetchAlerts(false);
    await fetchSummary();
    await fetchApiStatus();

    if (result.anomalies > 0) {
      showBanner(
        `⚠️ Batch analyzed: Found ${result.anomalies} anomaly/anomalies (${result.critical} Critical, ${result.warning} Warning). Added to the alert board below.`,
        "warning"
      );
    } else {
      showBanner(
        `✅ Batch analyzed: All ${result.total} API(s) are Healthy! (Note: The board lists Alerts for issues. Because this API is operating normally, no alert was created, but the 'Healthy' counter above has been updated).`,
        "success"
      );
    }
  } catch (err) {
    elements.modalError.textContent = err.message;
    elements.modalError.classList.remove("hidden");
  } finally {
    elements.submitCustomJsonBtn.disabled = false;
  }
}

// Starts auto-refresh timer (every 10s)
function startAutoRefresh() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
  }
  state.autoRefreshTimer = setInterval(() => {
    fetchAlerts(false);
    fetchSummary();
    fetchApiStatus();
  }, 10000);
}

// Stops auto-refresh timer
function stopAutoRefresh() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
}

// Event Listeners setup
function initializeEventListeners() {
  // Filter tabs
  elements.filterAll.addEventListener("click", () => updateFilterTabs("all"));
  elements.filterCritical.addEventListener("click", () => updateFilterTabs("critical"));
  elements.filterWarning.addEventListener("click", () => updateFilterTabs("warning"));

  // Search input
  elements.searchInput.addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    renderAlerts();
  });

  // Show resolved toggle
  elements.showResolvedToggle.addEventListener("change", (e) => {
    state.showResolved = e.target.checked;
    fetchAlerts(true);
  });

  // Action buttons
  elements.refreshBtn.addEventListener("click", () => {
    fetchAlerts(true);
    fetchSummary();
    fetchApiStatus();
  });

  elements.runSampleBtn.addEventListener("click", handleRunSample);
  elements.resolveAllBtn.addEventListener("click", handleResolveAllShown);
  elements.retryBtn.addEventListener("click", () => {
    fetchAlerts(true);
    fetchSummary();
    fetchApiStatus();
  });

  // Custom Input Modal
  elements.customInputBtn.addEventListener("click", () => {
    elements.modalError.classList.add("hidden");
    elements.customInputModal.classList.remove("hidden");
  });

  elements.closeModalBtn.addEventListener("click", () => {
    elements.customInputModal.classList.add("hidden");
  });

  elements.cancelModalBtn.addEventListener("click", () => {
    elements.customInputModal.classList.add("hidden");
  });

  elements.submitCustomJsonBtn.addEventListener("click", handleSubmitCustomJson);

  // Close status banner
  if (elements.closeBannerBtn) {
    elements.closeBannerBtn.addEventListener("click", () => {
      elements.actionBanner.classList.add("hidden");
    });
  }

  // Quick fill template buttons in modal
  if (elements.quickCriticalBtn) {
    elements.quickCriticalBtn.addEventListener("click", () => {
      elements.customJsonTextarea.value = JSON.stringify(
        [
          {
            api_name: "PaymentGatewayAPI",
            status_code: 500,
            response_time_ms: 5200,
            records_returned: 0,
          },
        ],
        null,
        2
      );
      elements.modalError.classList.add("hidden");
    });
  }

  if (elements.quickWarningBtn) {
    elements.quickWarningBtn.addEventListener("click", () => {
      elements.customJsonTextarea.value = JSON.stringify(
        [
          {
            api_name: "AnalyticsAPI",
            status_code: 200,
            response_time_ms: 3800,
            records_returned: 50,
          },
        ],
        null,
        2
      );
      elements.modalError.classList.add("hidden");
    });
  }

  if (elements.quickHealthyBtn) {
    elements.quickHealthyBtn.addEventListener("click", () => {
      elements.customJsonTextarea.value = JSON.stringify(
        [
          {
            api_name: "UserAccountAPI",
            status_code: 200,
            response_time_ms: 220,
            records_returned: 25,
          },
        ],
        null,
        2
      );
      elements.modalError.classList.add("hidden");
    });
  }

  // Auto-refresh interval toggle
  if (elements.autoRefreshToggle) {
    elements.autoRefreshToggle.addEventListener("change", (e) => {
      if (e.target.checked) {
        startAutoRefresh();
      } else {
        stopAutoRefresh();
      }
    });
  }
}

// Initialization on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  initializeEventListeners();
  fetchSummary();
  fetchAlerts(true);
  fetchApiStatus();

  // Enable auto-refresh by default
  if (elements.autoRefreshToggle && elements.autoRefreshToggle.checked) {
    startAutoRefresh();
  }
});

