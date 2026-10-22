/**
 * TERMINAL BOARD — Core Application & Routing Controller
 * Connects PyWebView desktop bridge with the Dark Neumorphic UI.
 */

// Terminology Sanitization: Replace user-facing "Unknown" with "Cryptic"
function toCryptic(val) {
  if (val === null || val === undefined || val === '') return 'Cryptic';
  const s = String(val);
  if (s.toLowerCase() === 'unknown') return 'Cryptic';
  return s.replace(/\bunknown\b/gi, 'Cryptic');
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Global State
const state = {
  theme: "dark",
  activePage: "dashboard",
  isPaused: false,
  pollTimer: null,
  dashboardData: null,
  toolsData: null,
  licenseData: null,
  selectedLicenseRecord: null,
  activeAlerts: [],
  unreadAlertCount: 0,
  searchQuery: "",
  selectedTool: null,
  pendingAction: null,
  activeSystemHealthTab: "perf",
  driverData: null,
  selectedDriver: null,
  officeActivationData: null,
  windowsActivationData: null,
  licenseExpiryOverview: null,
  manualLicenses: [],
  selectedManualLicense: null
};

// Client API Bridge (PyWebView / HTTP Hybrid)
const api = {
  isPyWebView: () => typeof window.pywebview !== "undefined" && window.pywebview.api,

  async call(method, ...args) {
    if (this.isPyWebView()) {
      return await window.pywebview.api[method](...args);
    }
    // HTTP Fallback
    const endpointMap = {
      get_dashboard_data: "/api/dashboard",
      get_system_health: "/api/system-health",
      get_drive_health: "/api/drive-health",
      get_windows_errors: "/api/windows-errors",
      get_network_diagnostics: "/api/network",
      get_installed_tools: "/api/tools",
      refresh_installed_tools: "/api/tools/refresh",
      get_license_audit: "/api/license-audit",
      update_license_compliance_note: "/api/license-audit/notes",
      get_license_file_preview: "/api/license-audit/preview",
      export_license_audit_data: "/api/license-audit/export",
      get_alerts_history: "/api/alerts",
      acknowledge_alert: (id) => `/api/alerts/${id}/acknowledge`,
      dismiss_alert: (id) => `/api/alerts/${id}/dismiss`,
      get_pending_toasts: "/api/toasts",
      get_diagnostics: "/api/diagnostics",
      execute_safe_action: "/api/diagnostics/execute",
      get_settings: "/api/settings",
      update_setting: "/api/settings",
      clear_history_data: "/api/history/clear",
      pause_monitoring: "/api/monitoring/pause",
      resume_monitoring: "/api/monitoring/resume",
      get_office_activation: (force) => `/api/office-activation?refresh=${force || false}`,
      get_windows_activation: "/api/windows-activation",
      get_license_expiry_overview: "/api/license-expiry",
      get_manual_license_records: "/api/manual-licenses",
      save_manual_license_record: "/api/manual-licenses",
      delete_manual_license_record: (id) => `/api/manual-licenses/${id}`,
      get_driver_inventory: (force) => `/api/drivers?refresh=${force || false}`,
      get_driver_details: (id) => `/api/drivers/details?device_id=${encodeURIComponent(id)}`,
      export_driver_report: (fmt) => `/api/drivers/export/${fmt || 'csv'}`,
      export_license_expiry_report: (fmt) => `/api/license-expiry/export/${fmt || 'csv'}`,
      export_combined_compliance_report: "/api/compliance-report/export",
      get_email_settings: "/api/email/settings",
      update_email_settings: "/api/email/settings",
      test_smtp_connection: "/api/email/test-connection",
      send_test_email: "/api/email/test-email",
      preview_daily_report: "/api/email/preview-report",
      send_daily_report_now: "/api/email/send-report",
      register_report_schedule: "/api/email/scheduler/register",
      remove_report_schedule: "/api/email/scheduler/remove",
      get_email_history: (limit) => `/api/email/history?limit=${limit || 50}`,
      get_email_queue: "/api/email/queue",
      retry_queued_email: (id) => `/api/email/queue/${id}/retry`,
      get_startup_status: "/api/startup/status",
      toggle_startup_status: "/api/startup/toggle"
    };

    const url = endpointMap[method];
    if (!url) throw new Error(`Unrecognized API method: ${method}`);

    if (typeof url === "function") {
      if (method === "acknowledge_alert" || method === "dismiss_alert") {
        const res = await fetch(url(args[0]), { method: "POST" });
        return await res.json();
      }
      if (method === "delete_manual_license_record") {
        const res = await fetch(url(args[0]), { method: "DELETE" });
        return await res.json();
      }
      if (method === "retry_queued_email") {
        const res = await fetch(url(args[0]), { method: "POST" });
        return await res.json();
      }
      const res = await fetch(url(...args));
      return await res.json();
    }

    if (method === "update_email_settings" || method === "test_smtp_connection" || method === "send_test_email" || method === "send_daily_report_now" || method === "register_report_schedule" || method === "remove_report_schedule") {
      let bodyPayload = args[0] || {};
      if (method === "send_test_email" && typeof args[0] === "string") {
        bodyPayload = { recipient: args[0] };
      } else if (method === "send_daily_report_now" && typeof args[0] === "string") {
        bodyPayload = { recipient: args[0] };
      } else if (method === "register_report_schedule") {
        bodyPayload = { time: args[0] || "19:00", consent: args[1] !== false };
      } else if (method === "remove_report_schedule") {
        bodyPayload = { consent: args[0] !== false };
      }
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(bodyPayload)
      });
      return await res.json();
    }


    if (method === "save_manual_license_record") {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(args[0])
      });
      return await res.json();
    }

    if (method === "toggle_startup_status") {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: args[0] })
      });
      return await res.json();
    }

    if (method === "execute_safe_action") {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_id: args[0], params: args[1], user_confirmed: args[2] })
      });
      return await res.json();
    }

    if (method === "update_license_compliance_note") {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: args[0], version: args[1], notes: args[2] })
      });
      return await res.json();
    }

    if (method === "get_license_file_preview") {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: args[0] })
      });
      return await res.json();
    }

    if (method === "update_setting") {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [args[0]]: args[1] })
      });
      return await res.json();
    }

    if (method === "clear_history_data") {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: args[0] })
      });
      return await res.json();
    }

    if (method === "pause_monitoring" || method === "resume_monitoring" || method === "refresh_installed_tools") {
      const res = await fetch(url, { method: "POST" });
      return await res.json();
    }

    const res = await fetch(url);
    return await res.json();
  }
};

// ================= THEME MANAGEMENT ================= //
function initTheme() {
  let savedTheme = localStorage.getItem("terminal_board_theme") || localStorage.getItem("sysfix_theme");
  if (!savedTheme) {
    savedTheme = "dark";
  }
  applyTheme(savedTheme, false);

  // Sync with persistent SQLite setting if available
  api.call("get_settings").then(settings => {
    if (settings && settings.theme && settings.theme !== state.theme) {
      applyTheme(settings.theme, false);
    }
  }).catch(() => {});
}

function applyTheme(theme, save = true) {
  const targetTheme = theme === "light" ? "light" : "dark";
  state.theme = targetTheme;
  document.documentElement.setAttribute("data-theme", targetTheme);

  // Update theme button icon & accessible labels
  const btn = document.getElementById("theme-toggle-btn");
  const iconContainer = document.getElementById("theme-icon-container");
  if (iconContainer) {
    // If dark, show Sun icon (invitation to light). If light, show Moon icon.
    iconContainer.innerHTML = targetTheme === "dark" ? getIcon("sun", 18) : getIcon("moon", 18);
  }
  if (btn) {
    const nextThemeName = targetTheme === "dark" ? "Light Mode" : "Dark Mode";
    btn.title = `Switch to ${nextThemeName}`;
    btn.setAttribute("aria-label", `Switch to ${nextThemeName}`);
  }

  // Update theme select dropdown in settings page if mounted
  const themeSelect = document.getElementById("set-theme");
  if (themeSelect && themeSelect.value !== targetTheme) {
    themeSelect.value = targetTheme;
  }

  if (save) {
    try {
      localStorage.setItem("terminal_board_theme", targetTheme);
      localStorage.setItem("sysfix_theme", targetTheme);
    } catch (e) {}
    api.call("update_setting", "theme", targetTheme).catch(err => {
      console.warn("Could not sync theme setting to backend:", err);
    });
  }

  updateThemeDependentElements();
}

function toggleTheme() {
  const newTheme = state.theme === "dark" ? "light" : "dark";
  document.documentElement.classList.add("theme-transitioning");
  applyTheme(newTheme, true);
  setTimeout(() => {
    document.documentElement.classList.remove("theme-transitioning");
  }, 260);

  showToast(
    "Theme Switched",
    `Active theme changed to ${newTheme === "light" ? "Light Professional" : "Dark Neumorphic"}.`,
    "healthy"
  );
}

function updateThemeDependentElements() {
  if (state.activePage === "dashboard" && state.dashboardData) {
    const cpu = state.dashboardData.metrics?.cpu;
    const cpuSpark = document.getElementById("dash-cpu-sparkline");
    if (cpuSpark && cpu && cpu.history) {
      cpuSpark.innerHTML = createSparkline(
        cpu.history,
        150,
        36,
        cpu.percent > 85 ? "var(--status-critical)" : null
      );
    }
  }
}

function hideSplashScreen() {
  const splash = document.getElementById("splash-screen");
  if (splash && !splash.classList.contains("splash-hidden")) {
    splash.classList.add("splash-hidden");
    setTimeout(() => {
      splash.style.display = "none";
    }, 400);
  }
}

// Application Initialization
window.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  setupNavigation();
  setupSearch();
  setupModals();
  startMonitoringLoop();

  // Safety timer so splash screen never blocks GUI
  const safetyTimer = setTimeout(hideSplashScreen, 3000);

  try {
    await navigate("dashboard");
  } catch (err) {
    console.error("Initial dashboard render error:", err);
  } finally {
    clearTimeout(safetyTimer);
    hideSplashScreen();
  }
});

// Routing & Navigation
function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => {
      const target = item.getAttribute("data-page");
      navigate(target);
    });
  });

  const refreshBtn = document.getElementById("header-refresh-btn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      refreshActivePage();
      showToast("Refreshed", "Live metrics and telemetry updated.", "healthy");
    });
  }

  const themeToggle = document.getElementById("theme-toggle-btn");
  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      toggleTheme();
    });
    themeToggle.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleTheme();
      }
    });
  }

  const pauseToggle = document.getElementById("monitor-toggle-btn");
  if (pauseToggle) {
    pauseToggle.addEventListener("click", async () => {
      if (state.isPaused) {
        await api.call("resume_monitoring");
        state.isPaused = false;
        pauseToggle.textContent = "Pause";
        document.getElementById("pulse-status-dot").classList.remove("paused");
        document.getElementById("pulse-status-text").textContent = "Live Monitoring Active";
        showToast("Monitoring Resumed", "Background polling resumed.", "healthy");
      } else {
        await api.call("pause_monitoring");
        state.isPaused = true;
        pauseToggle.textContent = "Resume";
        document.getElementById("pulse-status-dot").classList.add("paused");
        document.getElementById("pulse-status-text").textContent = "Monitoring Paused";
        showToast("Monitoring Paused", "Background polling temporarily paused.", "warning");
      }
    });
  }
}

function navigate(pageId) {
  if (pageId === "drivers" || pageId === "hardware_drivers") {
    navigate("system_health");
    switchSystemHealthTab("drivers");
    return;
  }

  state.activePage = pageId;

  // Update sidebar active class
  document.querySelectorAll(".nav-item").forEach(item => {
    item.classList.toggle("active", item.getAttribute("data-page") === pageId);
  });

  // Update page visibility
  document.querySelectorAll(".page-view").forEach(view => {
    view.classList.toggle("active", view.id === `page-${pageId}`);
  });

  // Update Header Title
  const titles = {
    dashboard: "System Overview Dashboard",
    system_health: "Hardware & Process Health",
    drive_health: "Storage Devices & Drive Reliability",
    windows_errors: "Windows Error Logs & Crash Events",
    network_monitor: "Network Diagnostics & Connectivity",
    installed_tools: "Installed Software & Tool Inventory",
    license_audit: "Software License Audit & Verification",
    alerts_history: "System Alerts & Anomaly History",
    diagnostics: "Diagnostics & Safe Fixes",
    settings: "Monitoring Preferences & Thresholds"
  };
  const subtitles = {
    dashboard: "Real-time telemetry and monitored developer tool inspection",
    system_health: "CPU cores, memory distribution, battery, and top process consumers",
    drive_health: "HDD, SATA SSD, and NVMe health, SMART status, and wear metrics",
    windows_errors: "System and application event monitoring with diagnostic advice",
    network_monitor: "Latency, DNS resolution, default gateway, and local dev ports",
    installed_tools: "Full registry inventory and verified development tool paths",
    license_audit: "Declared licenses, package manifests, and compliance verification",
    alerts_history: "Configurable threshold alerts, suppression, and recovery log",
    diagnostics: "Evidence-based problem diagnosis and user-confirmed safe repairs",
    settings: "Intervals, alert limits, data retention, and notifications"
  };

  const titleEl = document.getElementById("header-page-title");
  const subEl = document.getElementById("header-page-subtitle");
  if (titleEl) titleEl.textContent = titles[pageId] || "TERMINAL BOARD";
  if (subEl) subEl.textContent = subtitles[pageId] || "Detect Problems. Understand Causes. Fix Smarter.";

  refreshActivePage();
}

async function refreshActivePage() {
  try {
    switch (state.activePage) {
      case "dashboard":
        await renderDashboard();
        break;
      case "system_health":
        await renderSystemHealth();
        break;
      case "drive_health":
        await renderDriveHealth();
        break;
      case "windows_errors":
        await renderWindowsErrors();
        break;
      case "network_monitor":
        await renderNetworkMonitor();
        break;
      case "installed_tools":
        await renderInstalledTools();
        break;
      case "license_audit":
        await renderLicenseAudit();
        break;
      case "alerts_history":
        await renderAlertsHistory();
        break;
      case "diagnostics":
        await renderDiagnostics();
        break;
      case "settings":
        await renderSettings();
        break;
    }
    await checkToasts();
  } catch (err) {
    console.error(`Error loading page ${state.activePage}:`, err);
  }
}

// Background Polling Loop (3 seconds)
function startMonitoringLoop() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    if (state.isPaused) return;
    try {
      if (state.activePage === "dashboard") {
        await renderDashboard(true);
      } else if (state.activePage === "system_health") {
        await renderSystemHealth(true);
      }
      await checkToasts();
    } catch (e) {
      console.warn("Polling tick error:", e);
    }
  }, 3000);
}

// Toasts Checker
async function checkToasts() {
  try {
    const toasts = await api.call("get_pending_toasts");
    if (toasts && toasts.length > 0) {
      toasts.forEach(t => showToast(t.title, t.message, t.severity));
    }
  } catch (e) {}
}

function showToast(title, message, severity = "healthy") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const el = document.createElement("div");
  el.className = `toast ${severity}`;
  el.innerHTML = `
    <div class="toast-header">
      <span>${title}</span>
      <span style="font-size: 10px; color: var(--text-muted); cursor: pointer;" onclick="this.parentElement.parentElement.remove()">✕</span>
    </div>
    <div class="toast-msg">${message}</div>
  `;

  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateX(50px)";
    el.style.transition = "all 0.3s ease";
    setTimeout(() => el.remove(), 300);
  }, 4500);
}

// ================= PAGE RENDERERS ================= //

// 1. DASHBOARD
async function renderDashboard(isSilent = false) {
  const data = await api.call("get_dashboard_data");
  state.dashboardData = data;

  // Header overall health badge
  const badge = document.getElementById("header-health-badge");
  if (badge) {
    const healthLower = (data.overall_health || "healthy").toLowerCase();
    badge.className = `health-badge badge-${healthLower}`;
    badge.innerHTML = `<span style="width: 8px; height: 8px; border-radius: 50%; background: var(--status-${healthLower});"></span> ${data.overall_health} Health`;
  }

  // RAM Card
  const ram = data.metrics.ram;
  document.getElementById("dash-ram-percent").textContent = `${ram.percent}%`;
  document.getElementById("dash-ram-details").textContent = `${ram.used_formatted} / ${ram.total_formatted}`;
  document.getElementById("dash-ram-avail").textContent = `Available: ${ram.available_formatted}`;
  const ramBar = document.getElementById("dash-ram-bar");
  ramBar.style.width = `${ram.percent}%`;
  ramBar.className = `progress-fill ${ram.percent > 85 ? 'critical' : (ram.percent > 70 ? 'warning' : 'healthy')}`;

  // CPU Card
  const cpu = data.metrics.cpu;
  document.getElementById("dash-cpu-percent").textContent = `${cpu.percent}%`;
  document.getElementById("dash-cpu-cores").textContent = `${cpu.logical_cores} Cores (${cpu.physical_cores} Physical)`;
  document.getElementById("dash-cpu-freq").textContent = cpu.frequency ? `${cpu.frequency.current_mhz} MHz` : "Standard Clock";
  const cpuSpark = document.getElementById("dash-cpu-sparkline");
  if (cpuSpark) cpuSpark.innerHTML = createSparkline(cpu.history, 150, 36, cpu.percent > 85 ? 'var(--status-critical)' : null);

  // DISK Card
  const disks = data.metrics.disks;
  const primaryDisk = disks && disks.length > 0 ? disks[0] : null;
  if (primaryDisk) {
    document.getElementById("dash-disk-percent").textContent = `${primaryDisk.percent_used}%`;
    document.getElementById("dash-disk-details").textContent = `${primaryDisk.free_formatted} Free of ${primaryDisk.total_formatted}`;
    document.getElementById("dash-disk-mount").textContent = `Volume ${primaryDisk.mountpoint} (${primaryDisk.fstype})`;
    const diskBar = document.getElementById("dash-disk-bar");
    diskBar.style.width = `${primaryDisk.percent_used}%`;
    diskBar.className = `progress-fill ${primaryDisk.percent_used > 90 ? 'critical' : (primaryDisk.percent_used > 80 ? 'warning' : 'healthy')}`;
  } else {
    document.getElementById("dash-disk-percent").textContent = "N/A";
    document.getElementById("dash-disk-details").textContent = "No disk partitions detected";
  }

  // BATTERY Card
  const bat = data.metrics.battery;
  if (bat.has_battery) {
    document.getElementById("dash-bat-percent").textContent = `${bat.percent}%`;
    document.getElementById("dash-bat-status").textContent = bat.status;
    document.getElementById("dash-bat-time").textContent = bat.time_remaining;
    const batBar = document.getElementById("dash-bat-bar");
    batBar.style.width = `${bat.percent}%`;
    batBar.className = `progress-fill ${bat.percent < 20 ? 'critical' : (bat.percent < 40 ? 'warning' : 'healthy')}`;
  } else {
    document.getElementById("dash-bat-percent").textContent = "AC";
    document.getElementById("dash-bat-status").textContent = bat.status;
    document.getElementById("dash-bat-time").textContent = bat.time_remaining;
    const batBar = document.getElementById("dash-bat-bar");
    batBar.style.width = "100%";
    batBar.className = "progress-fill healthy";
  }

  // Installed Tools Quick Cards Grid
  const toolsGrid = document.getElementById("dash-tools-grid");
  if (toolsGrid && data.curated_tools) {
    toolsGrid.innerHTML = data.curated_tools.map(tool => `
      <div class="tool-card ${tool.installed ? '' : 'tool-uninstalled'}" onclick="openToolDetailModal('${tool.id}')">
        <div class="tool-header">
          <div class="tool-icon">${getIcon(tool.icon || 'package', 18)}</div>
          <div style="flex: 1; min-width: 0;">
            <div class="tool-title" title="${tool.name}">${tool.name}</div>
            <div class="tool-version">${tool.installed ? tool.version : 'Not Installed'}</div>
          </div>
        </div>
        <div class="tool-card-footer">
          <span class="badge ${tool.installed ? 'badge-healthy' : 'badge-cryptic'}" title="${tool.category || 'Tool'}">${tool.category || 'Tool'}</span>
          <span style="font-size: 11px; color: var(--accent-primary); font-weight: 500; white-space: nowrap;">Details →</span>
        </div>
      </div>
    `).join("");
  }

  // Dashboard Active Alerts Banner
  const alertBanner = document.getElementById("dash-alerts-banner");
  if (alertBanner) {
    if (data.active_alerts && data.active_alerts.length > 0) {
      alertBanner.style.display = "block";
      alertBanner.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
          <span style="font-weight: 600; color: var(--status-critical); display: flex; align-items: center; gap: 6px;">
            ${getIcon('alert-triangle', 16)} Active Attention Required (${data.active_alerts.length})
          </span>
          <button class="btn" style="padding: 4px 10px; font-size: 11px;" onclick="navigate('alerts_history')">View All Alerts</button>
        </div>
        <div style="display: flex; flex-direction: column; gap: 6px;">
          ${data.active_alerts.slice(0, 2).map(a => `
            <div style="background: var(--bg-surface); padding: 10px 14px; border-radius: 8px; border-left: 3px solid ${a.severity === 'critical' ? 'var(--status-critical)' : 'var(--status-warning)'}; display: flex; justify-content: space-between; align-items: center;">
              <div>
                <strong style="color: var(--text-primary); font-size: 12px;">${a.title}</strong>
                <p style="color: var(--text-secondary); font-size: 11px; margin-top: 2px;">${a.message}</p>
              </div>
              <button class="btn" style="padding: 3px 8px; font-size: 11px;" onclick="dismissAlert(${a.id})">Dismiss</button>
            </div>
          `).join("")}
        </div>
      `;
    } else {
      alertBanner.style.display = "none";
    }
  }
}

// 2. SYSTEM HEALTH
async function renderSystemHealth(isSilent = false) {
  const data = await api.call("get_system_health");
  const metrics = data.metrics;

  // Uptime
  const uptimeEl = document.getElementById("sys-uptime-text");
  if (uptimeEl) uptimeEl.textContent = metrics.uptime.uptime_formatted;
  const bootEl = document.getElementById("sys-boot-time");
  if (bootEl) bootEl.textContent = `Booted at: ${metrics.uptime.boot_time}`;

  // CPU Cores Breakdown
  const coresContainer = document.getElementById("sys-cpu-cores-list");
  if (coresContainer && metrics.cpu.per_cpu) {
    coresContainer.innerHTML = metrics.cpu.per_cpu.map((val, idx) => `
      <div style="display: flex; flex-direction: column; gap: 4px;">
        <div style="display: flex; justify-content: space-between; font-size: 11px;">
          <span style="color: var(--text-secondary);">Core ${idx}</span>
          <span style="font-weight: 600;">${val}%</span>
        </div>
        <div class="progress-track" style="height: 6px;">
          <div class="progress-fill ${val > 85 ? 'critical' : (val > 70 ? 'warning' : 'healthy')}" style="width: ${val}%;"></div>
        </div>
      </div>
    `).join("");
  }

  // Memory Distribution Breakdown
  const ram = metrics.ram;
  document.getElementById("sys-ram-used-text").textContent = ram.used_formatted;
  document.getElementById("sys-ram-avail-text").textContent = ram.available_formatted;
  document.getElementById("sys-swap-used-text").textContent = `${ram.swap_used_formatted} / ${ram.swap_total_formatted}`;

  // Sensor notice
  const tempMsg = document.getElementById("sys-sensor-notice");
  if (tempMsg) {
    tempMsg.textContent = metrics.temperatures.message;
  }

  // Top Processes Table
  const procTable = document.getElementById("sys-processes-table-body");
  if (procTable && data.processes) {
    procTable.innerHTML = data.processes.map(p => `
      <tr>
        <td style="font-weight: 600;">${p.name}</td>
        <td><code>${p.pid}</code></td>
        <td>${p.cpu_percent}%</td>
        <td>${p.memory_formatted} (${p.memory_percent}%)</td>
        <td><span class="badge badge-healthy">${p.status}</span></td>
        <td>${p.username}</td>
        <td>
          <button class="btn btn-danger" style="padding: 2px 8px; font-size: 10px;" onclick="confirmKillProcess(${p.pid}, '${p.name}')">End Task</button>
        </td>
      </tr>
    `).join("");
  }

  // If currently in drivers tab, refresh drivers
  if (state.activeSystemHealthTab === "drivers") {
    renderDriverInventory(isSilent);
  }
}

// System Health Sub-tab switcher
function switchSystemHealthTab(tab) {
  state.activeSystemHealthTab = tab;
  const btnPerf = document.getElementById("tab-btn-perf");
  const btnDrivers = document.getElementById("tab-btn-drivers");
  const tabPerf = document.getElementById("tab-sys-perf");
  const tabDrivers = document.getElementById("tab-sys-drivers");

  if (tab === "drivers") {
    if (btnPerf) btnPerf.classList.remove("active");
    if (btnDrivers) btnDrivers.classList.add("active");
    if (tabPerf) tabPerf.style.display = "none";
    if (tabDrivers) tabDrivers.style.display = "block";
    renderDriverInventory();
  } else {
    if (btnPerf) btnPerf.classList.add("active");
    if (btnDrivers) btnDrivers.classList.remove("active");
    if (tabPerf) tabPerf.style.display = "block";
    if (tabDrivers) tabDrivers.style.display = "none";
  }
}

// Hardware Devices & Drivers Diagnostics
async function renderDriverInventory(isSilent = false) {
  const tbody = document.getElementById("drivers-table-body");
  const subEl = document.getElementById("drivers-subtitle");

  try {
    if (!state.driverData && !isSilent) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 32px;"><div class="loading-dots" style="margin-bottom: 8px;"><span></span><span></span><span></span></div>Scanning Windows PnP devices and driver packages...</td></tr>`;
      }
      if (subEl) {
        subEl.textContent = "Scanning Windows PnP devices and driver packages...";
      }
    }

    if (!state.driverData || !isSilent) {
      state.driverData = await api.call("get_driver_inventory");
    }
    const data = state.driverData;
    if (!data) return;

    if (data.success === false) {
      throw new Error(data.error || "Failed to retrieve Windows hardware inventory.");
    }

    // Metric Summary Cards
    const totalEl = document.getElementById("drv-stat-total");
    const healthyEl = document.getElementById("drv-stat-healthy");
    const warnEl = document.getElementById("drv-stat-warning");
    const critEl = document.getElementById("drv-stat-critical");
    const unavailEl = document.getElementById("drv-stat-unavailable");

    if (totalEl) totalEl.textContent = data.total_count !== undefined ? String(data.total_count) : "0";
    if (healthyEl) healthyEl.textContent = data.healthy_count !== undefined ? String(data.healthy_count) : "0";
    if (warnEl) warnEl.textContent = data.warning_count !== undefined ? String(data.warning_count) : "0";
    if (critEl) critEl.textContent = data.critical_count !== undefined ? String(data.critical_count) : "0";
    if (unavailEl) unavailEl.textContent = data.not_available_count !== undefined ? String(data.not_available_count) : "0";

    if (subEl) subEl.textContent = `${data.total_count || 0} hardware devices and drivers registered (Updated: ${data.last_checked || 'Live'})`;

    // Populate class filter dynamically if empty
    const classFilter = document.getElementById("drv-class-filter");
    if (classFilter && classFilter.options.length <= 1) {
      const classes = Array.from(new Set((data.drivers || []).map(d => d.device_class).filter(Boolean))).sort();
      classes.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c;
        classFilter.appendChild(opt);
      });
    }

    filterDriversTable();
  } catch (err) {
    console.error("Error loading driver inventory:", err);
    const totalEl = document.getElementById("drv-stat-total");
    const healthyEl = document.getElementById("drv-stat-healthy");
    const warnEl = document.getElementById("drv-stat-warning");
    const critEl = document.getElementById("drv-stat-critical");
    const unavailEl = document.getElementById("drv-stat-unavailable");

    if (totalEl && totalEl.textContent === "--") totalEl.textContent = "0";
    if (healthyEl && healthyEl.textContent === "--") healthyEl.textContent = "0";
    if (warnEl && warnEl.textContent === "--") warnEl.textContent = "0";
    if (critEl && critEl.textContent === "--") critEl.textContent = "0";
    if (unavailEl && unavailEl.textContent === "--") unavailEl.textContent = "0";

    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--status-critical); padding: 28px;">
        <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px;">Hardware Scan Notice</div>
        <div style="color: var(--text-secondary); font-size: 12px; margin-bottom: 12px;">${escapeHtml(err.message || String(err))}</div>
        <button class="btn btn-primary" onclick="refreshDriverInventoryData()">Retry Scan</button>
      </td></tr>`;
    }
    if (subEl) {
      subEl.textContent = "Hardware discovery failed or restricted. Click Retry Scan.";
    }
    showToast("Discovery Notice", "Hardware scan reported error or restriction: " + (err.message || String(err)), "critical");
  }
}

async function refreshDriverInventoryData() {
  const tbody = document.getElementById("drivers-table-body");
  const subEl = document.getElementById("drivers-subtitle");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-secondary); padding: 32px;"><div class="loading-dots" style="margin-bottom: 8px;"><span></span><span></span><span></span></div>Rescanning hardware devices and driver packages...</td></tr>`;
  }
  if (subEl) {
    subEl.textContent = "Inspecting Windows PnP catalog & live driver packages...";
  }
  showToast("Scanning Hardware", "Inspecting system PnP device catalog & driver packages...", "healthy");

  try {
    const freshData = await api.call("get_driver_inventory", true);
    state.driverData = freshData;
    await renderDriverInventory(true);
    showToast("Drivers Updated", `Refreshed ${state.driverData?.total_count || 0} hardware device profiles.`, "healthy");
  } catch (err) {
    console.error("Error refreshing driver inventory:", err);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--status-critical); padding: 28px;">
        <div style="font-size: 13px; font-weight: 600; margin-bottom: 6px;">Hardware Rescan Failed</div>
        <div style="color: var(--text-secondary); font-size: 12px; margin-bottom: 12px;">${escapeHtml(err.message || String(err))}</div>
        <button class="btn btn-primary" onclick="refreshDriverInventoryData()">Retry Scan</button>
      </td></tr>`;
    }
    showToast("Scan Failed", "Failed to refresh hardware device profiles.", "critical");
  }
}

function filterDriversTable() {
  const data = state.driverData;
  const tbody = document.getElementById("drivers-table-body");
  if (!tbody || !data || !data.drivers) return;

  const q = (document.getElementById("drv-search-input")?.value || "").toLowerCase().trim();
  const classFilter = document.getElementById("drv-class-filter")?.value || "all";
  const healthFilter = document.getElementById("drv-health-filter")?.value || "all";

  const filtered = data.drivers.filter(d => {
    if (q) {
      const matchName = (d.device_name || "").toLowerCase().includes(q);
      const matchMfr = (d.manufacturer || "").toLowerCase().includes(q);
      const matchProv = (d.driver_provider || d.provider || "").toLowerCase().includes(q);
      const matchVer = (d.driver_version || "").toLowerCase().includes(q);
      const matchId = (d.device_id || d.device_instance_id || "").toLowerCase().includes(q);
      if (!matchName && !matchMfr && !matchProv && !matchVer && !matchId) return false;
    }
    if (classFilter !== "all" && d.device_class !== classFilter) return false;
    if (healthFilter !== "all") {
      const hClass = (d.health_classification || "NOT AVAILABLE").toUpperCase();
      if (healthFilter === "HEALTHY" && hClass !== "HEALTHY") return false;
      if (healthFilter === "WARNING" && hClass !== "WARNING") return false;
      if (healthFilter === "CRITICAL" && hClass !== "CRITICAL") return false;
      if (healthFilter === "NOT AVAILABLE" && !["NOT AVAILABLE", "SCAN ERROR"].includes(hClass)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 24px;">No matching drivers or hardware devices found.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(d => {
    const healthClass = (d.health_classification || "NOT AVAILABLE").toUpperCase();
    const badgeHealth = healthClass === "HEALTHY" ? "badge-healthy" : (healthClass === "WARNING" ? "badge-warning" : (healthClass === "CRITICAL" ? "badge-critical" : "badge-cryptic"));
    const safeId = (d.device_id || d.device_instance_id || "").replace(/"/g, '&quot;');
    const devName = escapeHtml(d.device_name || 'Not Available');
    const devId = escapeHtml(d.device_id || d.device_instance_id || 'Not Available');
    const devClass = escapeHtml(d.device_class || 'Not Available');
    const mfr = escapeHtml(d.manufacturer || 'Not Available');
    const prov = escapeHtml(d.driver_provider || d.provider || 'Not Available');
    const ver = escapeHtml(d.driver_version || 'Not Available');
    const dt = escapeHtml(d.driver_date || 'Not Available');
    const reason = escapeHtml(d.health_reason || d.diagnostic_reason || 'Operating Normally');

    return `
      <tr>
        <td style="font-weight: 600;">
          <div style="color: var(--text-primary); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${devName}">${devName}</div>
          <div style="font-size: 10px; color: var(--text-muted); font-family: monospace; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${devId}">${devId}</div>
        </td>
        <td><span class="badge badge-cryptic">${devClass}</span></td>
        <td style="font-size: 12px; max-width: 180px;">
          <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${mfr}">${mfr}</div>
          <div style="font-size: 10px; color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${prov}">${prov}</div>
        </td>
        <td style="font-size: 12px; font-family: monospace; max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${ver}">${ver}</td>
        <td style="font-size: 11px; color: var(--text-secondary);">${dt}</td>
        <td><span class="badge ${badgeHealth}">${healthClass}</span></td>
        <td style="font-size: 11px; max-width: 200px;">
          <div style="color: var(--text-primary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;" title="${reason}">${reason}</div>
          ${d.problem_code && d.problem_code !== 0 && d.problem_code !== "0" ? `<div style="font-size: 10px; color: var(--status-warning);">Code ${escapeHtml(String(d.problem_code))}: ${escapeHtml(d.problem_description || '')}</div>` : ''}
        </td>
        <td>
          <button class="btn" style="padding: 3px 10px; font-size: 11px;" onclick="openDriverDetailModal('${safeId}')">Inspect</button>
        </td>
      </tr>
    `;
  }).join("");
}

async function openDriverDetailModal(deviceId) {
  const drivers = state.driverData?.drivers || [];
  let d = drivers.find(item => item.device_id === deviceId || item.device_instance_id === deviceId);
  if (!d) {
    try {
      const res = await api.call("get_driver_details", deviceId);
      d = res.driver;
    } catch (e) {}
  }
  if (!d) return;

  state.selectedDriver = d;
  document.getElementById("driver-modal-name").textContent = d.device_name || "Not Available";
  document.getElementById("driver-modal-class").textContent = `Class: ${d.device_class || 'Not Available'} | Manufacturer: ${d.manufacturer || 'Not Available'}`;

  const healthClass = (d.health_classification || "NOT AVAILABLE").toUpperCase();
  const badgeHealth = healthClass === "HEALTHY" ? "badge-healthy" : (healthClass === "WARNING" ? "badge-warning" : (healthClass === "CRITICAL" ? "badge-critical" : "badge-cryptic"));
  const hBadge = document.getElementById("driver-modal-health-badge");
  if (hBadge) {
    hBadge.className = `badge ${badgeHealth}`;
    hBadge.textContent = `Status: ${healthClass}`;
  }

  const pBadge = document.getElementById("driver-modal-problem-badge");
  if (pBadge) {
    if (d.problem_code && d.problem_code !== 0 && d.problem_code !== "0") {
      pBadge.className = "badge badge-warning";
      pBadge.textContent = `PnP Code ${d.problem_code}: ${d.problem_description || 'Issue Detected'}`;
      pBadge.style.display = "inline-block";
    } else {
      pBadge.className = "badge badge-healthy";
      pBadge.textContent = "CM_PROB_NONE (Code 0)";
      pBadge.style.display = "inline-block";
    }
  }

  document.getElementById("driver-modal-provider").textContent = d.driver_provider || d.provider || "Not Available";
  document.getElementById("driver-modal-version").textContent = d.driver_version || "Not Available";
  document.getElementById("driver-modal-date").textContent = d.driver_date || "Not Available";
  document.getElementById("driver-modal-inf").textContent = d.inf_name || d.inf_path || "Not Available";
  document.getElementById("driver-modal-instance-id").textContent = d.device_id || d.device_instance_id || "Not Available";
  document.getElementById("driver-modal-reason").textContent = d.health_reason || d.diagnostic_reason || "Device is working properly according to Windows Plug-and-Play manager.";
  document.getElementById("driver-modal-remediation").textContent = d.remediation_step || "No repair action needed. Hardware is communicating with operating system.";
  document.getElementById("driver-modal-updated").textContent = `Last scanned: ${d.last_scanned || d.scanned_at || 'Recent'}`;

  const modal = document.getElementById("driver-detail-modal");
  if (modal) modal.classList.add("active");
}

function closeDriverDetailModal() {
  const modal = document.getElementById("driver-detail-modal");
  if (modal) modal.classList.remove("active");
  state.selectedDriver = null;
}

async function exportDriverReport(fmt) {
  try {
    const res = await api.call("export_driver_report", fmt);
    const blob = new Blob([res.content], { type: fmt === 'html' ? 'text/html' : 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = res.filename;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Export Ready", `Exported hardware driver inventory as ${res.filename}`, "healthy");
  } catch (e) {
    showToast("Export Failed", String(e), "critical");
  }
}

// 3. DRIVE HEALTH
async function renderDriveHealth() {
  const data = await api.call("get_drive_health");
  const drivesContainer = document.getElementById("drive-health-cards-container");
  if (!drivesContainer) return;

  if (!data.drives || data.drives.length === 0) {
    drivesContainer.innerHTML = `<div class="card"><p style="color: var(--text-muted);">No physical storage drives discovered.</p></div>`;
    return;
  }

  drivesContainer.innerHTML = data.drives.map(drive => `
    <div class="card" style="display: flex; flex-direction: column; gap: 16px;">
      <div style="display: flex; align-items: flex-start; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 14px;">
          <div style="width: 44px; height: 44px; border-radius: 12px; background: var(--bg-surface); box-shadow: var(--shadow-inset); display: flex; align-items: center; justify-content: center; color: var(--accent-primary);">
            ${getIcon('hard-drive', 24)}
          </div>
          <div>
            <h3 style="font-size: 16px; font-weight: 700; color: var(--text-primary);">${drive.model}</h3>
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">
              Disk ID: ${drive.device_id} | Type: ${drive.media_type} (${drive.bus_type}) | Capacity: ${drive.capacity_formatted}
            </p>
          </div>
        </div>
        <span class="badge ${drive.badge_class}" style="font-size: 13px; padding: 6px 12px;">${drive.risk_level}</span>
      </div>

      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; background: var(--bg-surface); padding: 14px; border-radius: 10px;">
        <div>
          <span style="font-size: 11px; color: var(--text-secondary);">Operational Status</span>
          <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); margin-top: 2px;">${drive.operational_status}</div>
        </div>
        <div>
          <span style="font-size: 11px; color: var(--text-secondary);">SMART / Health</span>
          <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); margin-top: 2px;">${drive.smart_status}</div>
        </div>
        <div>
          <span style="font-size: 11px; color: var(--text-secondary);">Reported Wear</span>
          <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); margin-top: 2px;">${drive.wear_indicator}</div>
        </div>
        <div>
          <span style="font-size: 11px; color: var(--text-secondary);">Temperature</span>
          <div style="font-weight: 600; font-size: 13px; color: var(--text-primary); margin-top: 2px;">${drive.temperature}</div>
        </div>
      </div>

      <div style="background: var(--code-bg); padding: 12px 16px; border-radius: 8px; border-left: 3px solid ${drive.risk_level === 'Critical' ? 'var(--status-critical)' : (drive.risk_level === 'Warning' ? 'var(--status-warning)' : 'var(--accent-primary)')};">
        <div style="font-size: 12px; font-weight: 600; color: var(--text-primary);">Diagnosis Summary</div>
        <p style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">${drive.summary}</p>
        <div style="font-size: 12px; font-weight: 600; color: var(--accent-primary); margin-top: 6px;">Recommended Action:</div>
        <p style="font-size: 12px; color: var(--text-primary);">${drive.recommendation}</p>
      </div>

      <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-muted);">
        <span>Telemetry note: ${drive.telemetry_note}</span>
        <span>Last checked: ${drive.last_checked}</span>
      </div>
    </div>
  `).join("");
}

// 4. WINDOWS ERRORS
async function renderWindowsErrors() {
  const logSelect = document.getElementById("win-log-filter")?.value || "All";
  const sevSelect = document.getElementById("win-sev-filter")?.value || "All";

  const data = await api.call("get_windows_errors", logSelect, sevSelect);
  const tableBody = document.getElementById("win-errors-table-body");
  if (!tableBody) return;

  if (!data.events || data.events.length === 0) {
    tableBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 24px;">No matching error or warning events recorded in this log range.</td></tr>`;
    return;
  }

  tableBody.innerHTML = data.events.map(ev => `
    <tr style="cursor: pointer;" onclick="openEventDetailModal(${JSON.stringify(ev).replace(/"/g, '&quot;')})">
      <td><span class="badge badge-${ev.level.toLowerCase()}">${ev.level}</span></td>
      <td style="font-size: 12px; color: var(--text-secondary);">${ev.timestamp}</td>
      <td><strong>${ev.provider}</strong></td>
      <td><code>${ev.event_id}</code></td>
      <td><span class="badge badge-unknown">${ev.category}</span></td>
      <td style="max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text-secondary);" title="${ev.message}">${ev.message}</td>
    </tr>
  `).join("");
}

// 5. NETWORK MONITOR
async function renderNetworkMonitor() {
  const data = await api.call("get_network_diagnostics");
  const net = data.network;

  // Status Banner
  const statusBanner = document.getElementById("net-status-banner");
  if (statusBanner) {
    statusBanner.className = `card ${net.health_status.toLowerCase()}`;
    statusBanner.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 14px;">
          <div style="width: 40px; height: 40px; border-radius: 10px; background: var(--bg-surface); display: flex; align-items: center; justify-content: center; color: var(--accent-primary);">
            ${getIcon('wifi', 22)}
          </div>
          <div>
            <h3 style="font-size: 16px; font-weight: 700; color: var(--text-primary);">${net.root_cause}</h3>
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">${net.recommendation}</p>
          </div>
        </div>
        <span class="badge badge-${net.health_status.toLowerCase()}" style="font-size: 13px; padding: 6px 14px;">${net.health_status}</span>
      </div>
    `;
  }

  // Key Metrics
  document.getElementById("net-gateway-ip").textContent = net.gateway_ip;
  document.getElementById("net-gateway-status").textContent = net.gateway_reachable ? "Reachable" : "Unreachable";
  document.getElementById("net-dns-status").textContent = net.dns_resolution.success ? `${net.dns_resolution.latency_ms} ms (${net.dns_resolution.resolved_ip})` : "Resolution Failed";
  document.getElementById("net-ping-avg").textContent = typeof net.internet_ping.avg_latency_ms === "number" ? `${net.internet_ping.avg_latency_ms} ms` : net.internet_ping.avg_latency_ms;
  document.getElementById("net-packet-loss").textContent = `${net.internet_ping.packet_loss_percent}%`;

  // Adapters List
  const adaptList = document.getElementById("net-adapters-list");
  if (adaptList && net.adapters) {
    adaptList.innerHTML = net.adapters.map(a => `
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: var(--bg-surface); border-radius: 8px;">
        <div>
          <strong style="color: var(--text-primary); font-size: 13px;">${a.name}</strong>
          <div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">IPv4: ${a.ipv4} | MAC: ${a.mac}</div>
        </div>
        <span class="badge ${a.is_up ? 'badge-healthy' : 'badge-unknown'}">${a.status}</span>
      </div>
    `).join("");
  }

  // Local Dev Ports Table
  const devPortsTable = document.getElementById("net-dev-ports-body");
  if (devPortsTable && net.dev_ports) {
    devPortsTable.innerHTML = net.dev_ports.map(p => `
      <tr>
        <td><strong>:${p.port}</strong></td>
        <td>${p.service}</td>
        <td><span class="badge ${p.is_active ? 'badge-healthy' : 'badge-unknown'}">${p.status}</span></td>
      </tr>
    `).join("");
  }
}

// 6. INSTALLED TOOLS
async function renderInstalledTools() {
  const data = await api.call("get_installed_tools");
  state.toolsData = data;

  const countEl = document.getElementById("tools-total-count");
  if (countEl) countEl.textContent = `${data.total_detected} Tools & Applications Detected`;

  filterAndRenderToolsGrid();
}

function filterAndRenderToolsGrid() {
  const data = state.toolsData;
  if (!data) return;

  const q = state.searchQuery.toLowerCase().trim();
  const allSoftware = [...data.curated_tools, ...data.all_registry_software];

  const filtered = allSoftware.filter(s => {
    if (!q) return true;
    return (s.name && s.name.toLowerCase().includes(q)) ||
           (s.publisher && s.publisher.toLowerCase().includes(q)) ||
           (s.category && s.category.toLowerCase().includes(q));
  });

  const grid = document.getElementById("tools-full-grid");
  if (!grid) return;

  grid.innerHTML = filtered.map(tool => `
    <div class="tool-card ${tool.installed ? '' : 'tool-uninstalled'}" onclick="openToolDetailModal('${tool.id || tool.name}')">
      <div class="tool-header">
        <div class="tool-icon">${getIcon(tool.icon || 'package', 18)}</div>
        <div style="flex: 1; min-width: 0;">
          <div class="tool-title" title="${tool.name}">${tool.name}</div>
          <div class="tool-version">${tool.installed ? tool.version : 'Not Installed'}</div>
        </div>
      </div>
      <div class="tool-card-footer">
        <span class="badge ${tool.installed ? 'badge-healthy' : 'badge-cryptic'}" title="${tool.category || 'App'}">${tool.category || 'App'}</span>
        <span style="font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 110px;" title="${tool.source || 'Registry'}">${tool.source || 'Registry'}</span>
      </div>
    </div>
  `).join("");
}

// 7. LICENSE AUDIT
async function renderLicenseAudit() {
  try {
    // Parallel fetch of license audit, Office activation, Windows activation, and expiry overview
    const [auditData, officeData, winData, expiryData] = await Promise.all([
      api.call("get_license_audit"),
      api.call("get_office_activation").catch(() => null),
      api.call("get_windows_activation").catch(() => null),
      api.call("get_license_expiry_overview").catch(() => null)
    ]);

    state.licenseData = auditData;
    state.officeActivationData = officeData;
    state.windowsActivationData = winData;
    state.licenseExpiryOverview = expiryData;

    const countEl = document.getElementById("license-total-count");
    if (countEl) countEl.textContent = `${auditData.total} Software Packages Audited (Registry & Manifests)`;

    // Update Windows Activation Hero Card
    if (winData && winData.windows_activation) {
      const w = winData.windows_activation;
      const wBadge = document.getElementById("win-act-badge");
      const wProd = document.getElementById("win-act-product");
      const wChan = document.getElementById("win-act-channel");

      if (wBadge) {
        const isLic = w.is_activated;
        wBadge.className = `badge ${isLic ? 'badge-healthy' : 'badge-warning'}`;
        wBadge.textContent = w.status_label || (isLic ? "Licensed" : "Not Licensed");
      }
      if (wProd) wProd.textContent = w.product_name || "Windows Operating System";
      if (wChan) wChan.textContent = w.channel || w.description || "Windows Retail / OEM Channel";
    }

    // Update Microsoft Office Activation Hero Card
    if (officeData) {
      const oBadge = document.getElementById("office-act-badge");
      const oProd = document.getElementById("office-act-product");
      const oChan = document.getElementById("office-act-channel");
      const oDiag = document.getElementById("office-act-diagnostic");

      if (oBadge) {
        oBadge.className = `badge ${officeData.badge_class || 'badge-unknown'}`;
        oBadge.textContent = toCryptic(officeData.activation_status) || "Cryptic";
      }
      if (oProd) {
        oProd.textContent = officeData.installed_edition || (officeData.detected ? "Microsoft Office" : "No Supported Office Detected");
        oProd.title = officeData.installed_edition || "";
      }
      if (oChan) {
        const keyText = officeData.partial_product_key ? `Suffix: ${officeData.partial_product_key}` : "No Key Suffix";
        oChan.textContent = `${officeData.license_channel || 'Channel N/A'} (${keyText})`;
      }
      if (oDiag) {
        oDiag.textContent = officeData.status_message || (officeData.ospp_path ? `Script: ${officeData.ospp_path}` : "OSPP.VBS not found");
        oDiag.title = officeData.status_message || "";
      }
    }

    // Expiry Metrics Cards
    const records = auditData.records || [];
    const verifiedCount = records.filter(r => r.verification_status === "Verified license information").length;
    const activeCount = expiryData?.summary?.active_count ?? records.filter(r => r.expiry_state === "ACTIVE").length;
    const expiringCount = expiryData?.summary?.expiring_soon_count ?? records.filter(r => r.expiry_state === "EXPIRING_SOON").length;
    const reviewCount = records.filter(r => r.expiry_state === "EXPIRED" || r.verification_status === "Review required" || r.verification_status === "Potential licensing concern").length;

    const totalEl = document.getElementById("lic-stat-total");
    const verEl = document.getElementById("lic-stat-verified");
    const actEl = document.getElementById("lic-stat-active");
    const expEl = document.getElementById("lic-stat-expiring");
    const revEl = document.getElementById("lic-stat-review");

    if (totalEl) totalEl.textContent = records.length;
    if (verEl) verEl.textContent = verifiedCount;
    if (actEl) actEl.textContent = activeCount;
    if (expEl) expEl.textContent = expiringCount;
    if (revEl) revEl.textContent = reviewCount;

    filterLicenseAuditTable();
  } catch (err) {
    console.error("Error loading license audit:", err);
  }
}

function filterLicenseAuditTable() {
  const data = state.licenseData;
  const tbody = document.getElementById("license-audit-table-body");
  if (!tbody || !data || !data.records) return;

  const q = (document.getElementById("lic-search-input")?.value || "").toLowerCase().trim();
  const catFilter = document.getElementById("lic-category-filter")?.value || "all";
  const statFilter = document.getElementById("lic-status-filter")?.value || "all";
  const expFilter = document.getElementById("lic-expiry-filter")?.value || "all";
  const srcFilter = document.getElementById("lic-source-filter")?.value || "all";

  const filtered = data.records.filter(r => {
    // Search query match
    if (q) {
      const matchName = (r.name || "").toLowerCase().includes(q);
      const matchPub = (r.publisher || "").toLowerCase().includes(q);
      const matchLic = (r.license_identifier || "").toLowerCase().includes(q);
      const matchCat = (r.category || "").toLowerCase().includes(q);
      if (!matchName && !matchPub && !matchLic && !matchCat) return false;
    }
    // Category match
    if (catFilter !== "all" && r.license_category !== catFilter) return false;
    // Status match
    if (statFilter !== "all" && r.verification_status !== statFilter) return false;
    // Expiry match
    if (expFilter !== "all" && r.expiry_state !== expFilter) return false;
    // Evidence source match
    if (srcFilter !== "all") {
      const evSrc = (r.evidence_source || "").toLowerCase();
      if (!evSrc.includes(srcFilter.toLowerCase())) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 28px;">No matching software license records found.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map((r) => {
    const origIdx = data.records.indexOf(r);
    const catClass = `badge-lic-${(r.license_category || 'cryptic').toLowerCase().replace(/[^a-z0-9]/g, '')}`;
    const userNoteDot = r.compliance_notes ? `<span title="Manual compliance record attached" style="display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--status-healthy); margin-left: 6px;"></span>` : "";

    // Expiry badge class
    const expState = r.expiry_state || "CRYPTIC";
    const expBadgeClass = `badge-exp-${expState.toLowerCase().replace(/_/g, '-')}`;
    const expDateText = r.expiry_date ? `<div style="font-size: 10px; color: var(--text-secondary); margin-top: 2px;">Exp: ${r.expiry_date}</div>` : "";

    // Activation display
    const act = toCryptic(r.activation_status) || "Unavailable";
    const actColor = act.includes("Licensed") || act.includes("ACTIVATED") ? "var(--status-healthy)" : (act.includes("Notification") || act.includes("Grace") ? "var(--status-warning)" : "var(--text-muted)");

    return `
      <tr>
        <td style="font-weight: 600;">
          <div style="display: flex; align-items: center;">
            <span style="color: var(--text-primary); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${r.name}">${r.name}</span>
            ${userNoteDot}
          </div>
          <div style="font-size: 11px; color: var(--text-secondary); margin-top: 2px;">${r.publisher || 'Cryptic Publisher'}</div>
        </td>
        <td style="font-size: 12px;">${r.version || 'Cryptic'}</td>
        <td><span class="badge ${catClass}">${toCryptic(r.license_category) || 'Cryptic'}</span></td>
        <td><code>${r.license_identifier || 'Not Documented'}</code></td>
        <td style="font-size: 12px; font-weight: 500; color: ${actColor};">${act}</td>
        <td>
          <span class="badge ${expBadgeClass}">${toCryptic(expState).replace(/_/g, ' ')}</span>
          ${expDateText}
        </td>
        <td>
          <div style="font-size: 11px; color: var(--text-primary); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${r.evidence_source}">${toCryptic(r.evidence_source) || 'Inconclusive'}</div>
          <div style="font-size: 10px; color: var(--text-muted);">${r.verification_method || 'Heuristic'}</div>
        </td>
        <td>
          <button class="btn" style="padding: 3px 10px; font-size: 11px;" onclick="openLicenseDetailModalByIndex(${origIdx})">
            Details
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

function openLicenseDetailModalByIndex(idx) {
  if (!state.licenseData || !state.licenseData.records || !state.licenseData.records[idx]) return;
  const record = state.licenseData.records[idx];
  state.selectedLicenseRecord = record;

  document.getElementById("lic-modal-title").textContent = record.name;
  document.getElementById("lic-modal-subtitle").textContent = `Version: ${record.version || 'Cryptic'} | Publisher: ${record.publisher || 'Cryptic Vendor'}`;

  // Category Badge
  const catBadge = document.getElementById("lic-modal-cat-badge");
  const catClass = `badge-lic-${(record.license_category || 'cryptic').toLowerCase().replace(/[^a-z0-9]/g, '')}`;
  catBadge.className = `badge ${catClass}`;
  catBadge.textContent = toCryptic(record.license_category) || "Cryptic";

  // Status Badge
  const statusBadge = document.getElementById("lic-modal-status-badge");
  statusBadge.className = `badge ${record.badge_class || 'badge-unknown'}`;
  statusBadge.textContent = toCryptic(record.verification_status) || "Cryptic";

  // Activation Badge
  const actBadge = document.getElementById("lic-modal-activation-badge");
  const act = toCryptic(record.activation_status) || "Activation Data Unavailable";
  if (act.includes("Licensed") || act.includes("Permanent") || act.includes("ACTIVATED")) {
    actBadge.className = "badge badge-healthy";
  } else if (act.includes("Notification") || act.includes("Grace")) {
    actBadge.className = "badge badge-warning";
  } else {
    actBadge.className = "badge badge-unknown";
  }
  actBadge.textContent = `Activation: ${act}`;

  // Fields
  document.getElementById("lic-modal-identifier").textContent = record.license_identifier || "Not Documented";
  document.getElementById("lic-modal-category").textContent = record.category || "Application";
  document.getElementById("lic-modal-evidence").textContent = toCryptic(record.evidence_source) || "Cryptic";
  document.getElementById("lic-modal-method").textContent = record.verification_method || "Inconclusive Heuristic";
  document.getElementById("lic-modal-location").textContent = record.install_path || "Registry Managed / System Default";
  document.getElementById("lic-modal-file").textContent = record.license_file || "No local LICENSE or EULA file detected";
  document.getElementById("lic-modal-reason").textContent = record.status_reason || record.notes || "No analysis provided.";
  document.getElementById("lic-modal-time").textContent = `Last verified: ${record.last_audited || 'Recent'}`;


  // Notes
  const notesInput = document.getElementById("lic-modal-notes-input");
  if (notesInput) notesInput.value = record.compliance_notes || "";

  // Preview snippet
  const previewContainer = document.getElementById("lic-modal-preview-container");
  const previewText = document.getElementById("lic-modal-preview-text");
  if (record.license_file) {
    previewContainer.style.display = "block";
    previewText.textContent = "Loading file snippet...";
    api.call("get_license_file_preview", record.license_file).then(res => {
      previewText.textContent = res.snippet || "Unable to read license file contents.";
    }).catch(() => {
      previewText.textContent = "Error loading local file snippet.";
    });
  } else {
    previewContainer.style.display = "none";
  }

  const modal = document.getElementById("license-detail-modal");
  if (modal) modal.classList.add("active");
}

function closeLicenseDetailModal() {
  const modal = document.getElementById("license-detail-modal");
  if (modal) modal.classList.remove("active");
  state.selectedLicenseRecord = null;
}

async function saveCurrentComplianceNote() {
  if (!state.selectedLicenseRecord) return;
  const notes = document.getElementById("lic-modal-notes-input").value.trim();
  const rec = state.selectedLicenseRecord;

  try {
    await api.call("update_license_compliance_note", rec.name, rec.version, notes);
    rec.compliance_notes = notes;
    if (notes) {
      rec.evidence_source = "User-provided compliance records";
    }
    showToast("Compliance Record Saved", `Updated compliance notes for ${rec.name}.`, "healthy");
    filterLicenseAuditTable();
  } catch (err) {
    showToast("Save Error", String(err), "critical");
  }
}

async function refreshLicenseAuditData() {
  showToast("Scanning Software", "Rescanning registry software, Office activation, and license manifests...", "healthy");
  await api.call("refresh_installed_tools");
  await renderLicenseAudit();
  showToast("Audit Refreshed", "Software license audit updated successfully.", "healthy");
}

async function exportLicenseAudit(fmt) {
  try {
    const res = await api.call("export_license_audit_data", fmt);
    const blob = new Blob([res.content], { type: fmt === 'html' ? 'text/html' : 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = res.filename;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Export Ready", `Exported license audit as ${res.filename}`, "healthy");
  } catch (e) {
    showToast("Export Failed", String(e), "critical");
  }
}

// Manual Subscription and License Records Modal Handlers
function openManualLicenseModal(rec = null) {
  state.selectedManualLicense = rec;
  const modal = document.getElementById("manual-license-modal");
  const title = document.getElementById("manual-lic-modal-title");
  const delBtn = document.getElementById("manual-lic-del-btn");

  if (rec) {
    if (title) title.textContent = "Edit Subscription / License Record";
    if (delBtn) delBtn.style.display = "block";
    document.getElementById("manual-lic-id").value = rec.id || "";
    document.getElementById("manual-lic-name").value = rec.app_name || rec.name || "";
    document.getElementById("manual-lic-publisher").value = rec.publisher || "";
    document.getElementById("manual-lic-category").value = rec.category || "Subscription";
    document.getElementById("manual-lic-expiry").value = rec.expiry_date || "";
    document.getElementById("manual-lic-reminder").value = String(rec.reminder_days_before ?? 30);
    document.getElementById("manual-lic-ref").value = rec.license_reference || "";
    document.getElementById("manual-lic-notes").value = rec.compliance_notes || rec.notes || "";
  } else {
    if (title) title.textContent = "Add Manual Subscription or License Record";
    if (delBtn) delBtn.style.display = "none";
    document.getElementById("manual-lic-id").value = "";
    document.getElementById("manual-lic-name").value = "";
    document.getElementById("manual-lic-publisher").value = "";
    document.getElementById("manual-lic-category").value = "Subscription";
    document.getElementById("manual-lic-expiry").value = "";
    document.getElementById("manual-lic-reminder").value = "30";
    document.getElementById("manual-lic-ref").value = "";
    document.getElementById("manual-lic-notes").value = "";
  }

  if (modal) modal.classList.add("active");
}

function closeManualLicenseModal() {
  const modal = document.getElementById("manual-license-modal");
  if (modal) modal.classList.remove("active");
  state.selectedManualLicense = null;
}

async function saveManualLicenseRecord() {
  const name = document.getElementById("manual-lic-name").value.trim();
  if (!name) {
    showToast("Validation Error", "Application / Service name is required.", "warning");
    return;
  }

  const idVal = document.getElementById("manual-lic-id").value.trim();
  const payload = {
    id: idVal ? parseInt(idVal, 10) : null,
    app_name: name,
    publisher: document.getElementById("manual-lic-publisher").value.trim(),
    category: document.getElementById("manual-lic-category").value,
    expiry_date: document.getElementById("manual-lic-expiry").value || null,
    reminder_days_before: parseInt(document.getElementById("manual-lic-reminder").value, 10) || 30,
    license_reference: document.getElementById("manual-lic-ref").value.trim(),
    compliance_notes: document.getElementById("manual-lic-notes").value.trim()
  };

  try {
    const res = await api.call("save_manual_license_record", payload);
    if (res.success) {
      showToast("Subscription Saved", `Saved manual record for ${name}.`, "healthy");
      closeManualLicenseModal();
      await renderLicenseAudit();
    } else {
      showToast("Save Error", "Unable to save manual license record.", "critical");
    }
  } catch (e) {
    showToast("Save Error", String(e), "critical");
  }
}

async function deleteCurrentManualLicense() {
  const idVal = document.getElementById("manual-lic-id").value;
  if (!idVal) return;
  if (!confirm("Are you sure you want to delete this subscription / license record?")) return;

  try {
    const res = await api.call("delete_manual_license_record", parseInt(idVal, 10));
    if (res.success) {
      showToast("Deleted", "Manual license record removed.", "healthy");
      closeManualLicenseModal();
      await renderLicenseAudit();
    }
  } catch (e) {
    showToast("Delete Error", String(e), "critical");
  }
}

async function exportCombinedComplianceReport() {
  try {
    showToast("Generating Audit", "Compiling complete software compliance & driver diagnostics report...", "healthy");
    const res = await api.call("export_combined_compliance_report");
    const blob = new Blob([res.content], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = res.filename;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Report Ready", `Saved compliance audit report as ${res.filename}`, "healthy");
  } catch (e) {
    showToast("Report Error", String(e), "critical");
  }
}

async function exportLicenseExpiryReport(fmt) {
  try {
    const res = await api.call("export_license_expiry_report", fmt);
    const blob = new Blob([res.content], { type: fmt === 'html' ? 'text/html' : 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = res.filename;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Export Ready", `Saved expiry report as ${res.filename}`, "healthy");
  } catch (e) {
    showToast("Report Error", String(e), "critical");
  }
}

// 8. ALERTS & HISTORY
async function renderAlertsHistory() {
  const filter = document.getElementById("alerts-status-filter")?.value || "all";
  const statusParam = filter === "all" ? null : filter;
  const alerts = await api.call("get_alerts_history", statusParam);

  const container = document.getElementById("alerts-list-container");
  if (!container) return;

  if (!alerts || alerts.length === 0) {
    container.innerHTML = `<div class="card"><p style="color: var(--text-muted); text-align: center; padding: 24px;">No alert history found for this filter.</p></div>`;
    return;
  }

  container.innerHTML = alerts.map(a => `
    <div class="card" style="display: flex; flex-direction: column; gap: 10px; border-left: 4px solid ${a.severity === 'critical' ? 'var(--status-critical)' : 'var(--status-warning)'};">
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="badge badge-${a.severity}">${a.severity.toUpperCase()}</span>
          <h4 style="font-size: 14px; font-weight: 600; color: var(--text-primary);">${a.title}</h4>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="font-size: 11px; color: var(--text-muted);">${a.timestamp}</span>
          ${a.status === 'active' ? `
            <button class="btn" style="padding: 3px 8px; font-size: 10px;" onclick="acknowledgeAlert(${a.id})">Acknowledge</button>
            <button class="btn btn-danger" style="padding: 3px 8px; font-size: 10px;" onclick="dismissAlert(${a.id})">Dismiss</button>
          ` : `<span class="badge badge-unknown">${a.status}</span>`}
        </div>
      </div>
      <p style="font-size: 12px; color: var(--text-secondary);">${a.message}</p>
      ${a.evidence ? `<div style="font-size: 11px; color: var(--text-muted);"><strong>Evidence:</strong> ${a.evidence}</div>` : ''}
      ${a.recommended_steps ? `<div style="font-size: 11px; color: var(--accent-primary);"><strong>Next Steps:</strong> ${a.recommended_steps}</div>` : ''}
    </div>
  `).join("");
}

async function acknowledgeAlert(id) {
  await api.call("acknowledge_alert", id);
  showToast("Acknowledged", "Alert marked as acknowledged.", "healthy");
  renderAlertsHistory();
}

async function dismissAlert(id) {
  await api.call("dismiss_alert", id);
  showToast("Dismissed", "Alert dismissed.", "healthy");
  renderAlertsHistory();
  if (state.activePage === "dashboard") renderDashboard();
}

// 9. DIAGNOSTICS & SAFE FIXES
async function renderDiagnostics() {
  const findings = await api.call("get_diagnostics");
  const container = document.getElementById("diagnostics-cards-container");
  if (!container) return;

  container.innerHTML = findings.map(f => `
    <div class="card" style="display: flex; flex-direction: column; gap: 14px;">
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <h3 style="font-size: 15px; font-weight: 700; color: var(--text-primary);">${f.title}</h3>
        </div>
        <span class="badge ${f.badge_class}">${f.severity}</span>
      </div>

      <div style="display: flex; flex-direction: column; gap: 6px; font-size: 13px;">
        <div><strong style="color: var(--text-secondary);">What Happened:</strong> <span style="color: var(--text-primary);">${f.what_happened}</span></div>
        <div><strong style="color: var(--text-secondary);">Supporting Evidence:</strong> <span style="color: var(--text-muted);">${f.supporting_evidence}</span></div>
        <div><strong style="color: var(--text-secondary);">Suspected Cause:</strong> <span style="color: var(--text-muted);">${f.possible_causes}</span></div>
        <div><strong style="color: var(--accent-primary);">Recommended Step:</strong> <span style="color: var(--text-primary);">${f.recommended_steps}</span></div>
      </div>

      <div style="display: flex; align-items: center; justify-content: space-between; padding-top: 10px; border-top: 1px solid var(--border-subtle);">
        <span style="font-size: 11px; color: var(--text-muted);">${f.confidence}</span>
        ${f.safe_action ? `
          <button class="btn btn-primary" onclick="promptSafeActionConfirmation('${f.safe_action.action_id}', '${f.safe_action.name}', '${f.safe_action.description}')">
            ${getIcon('wrench', 14)} ${f.safe_action.name}
          </button>
        ` : ''}
      </div>
    </div>
  `).join("");
}

// 10. SETTINGS
async function renderSettings() {
  try {
    const settings = await api.call("get_settings") || {};
    
    const toastEl = document.getElementById("set-desktop-toast");
    if (toastEl) toastEl.value = settings.enable_desktop_notifications !== undefined ? String(settings.enable_desktop_notifications) : "1";
    
    const retEl = document.getElementById("set-retention");
    if (retEl) retEl.value = settings.retention_days || "30";
    
    const themeEl = document.getElementById("set-theme");
    if (themeEl) {
      themeEl.value = settings.theme || state.theme || "dark";
    }

    // Load email and startup automation settings
    await loadEmailSettings();
    await loadStartupSettings();
  } catch (err) {
    console.error("Error loading settings:", err);
  }
}

// Windows User Startup Integration
async function loadStartupSettings() {
  const badge = document.getElementById("startup-status-badge");
  const toggle = document.getElementById("set-windows-startup-toggle");
  const desc = document.getElementById("startup-status-desc");
  if (!badge || !toggle) return;

  try {
    const res = await api.call("get_startup_status");
    if (res && res.enabled) {
      badge.className = "badge badge-healthy";
      badge.textContent = "Enabled in Windows Startup";
      toggle.checked = true;
      if (desc) desc.textContent = `Auto-launch configured in HKCU Run registry: ${res.command || 'TERMINAL_BOARD'}`;
    } else {
      badge.className = "badge badge-cryptic";
      badge.textContent = "Disabled";
      toggle.checked = false;
      if (desc) desc.textContent = "Configures standard Current User Run key (HKCU). Safe, fully reversible, no administrator rights required.";
    }
  } catch (e) {
    console.warn("Could not check Windows startup status:", e);
    badge.className = "badge badge-cryptic";
    badge.textContent = "Status Cryptic";
  }
}

async function toggleWindowsStartup(enabled) {
  try {
    const res = await api.call("toggle_startup_status", enabled);
    if (res && res.success) {
      showToast(
        enabled ? "Windows Startup Enabled" : "Windows Startup Disabled",
        res.message || (enabled ? "TERMINAL BOARD will launch upon Windows sign-in." : "Removed from Windows startup."),
        enabled ? "healthy" : "warning"
      );
    } else {
      showToast("Startup Configuration Error", (res && res.error) || "Failed to modify Windows startup entry.", "critical");
    }
    await loadStartupSettings();
  } catch (e) {
    showToast("Error", "Could not communicate with Windows startup bridge: " + e, "critical");
    await loadStartupSettings();
  }
}

async function saveSettings() {
  const fb = document.getElementById("settings-feedback");
  const themeEl = document.getElementById("set-theme");
  const themeVal = themeEl ? themeEl.value : state.theme;
  const toastEl = document.getElementById("set-desktop-toast");
  const toastVal = toastEl ? toastEl.value : "1";
  const retEl = document.getElementById("set-retention");
  const retVal = retEl ? parseInt(retEl.value, 10) : 30;

  // Validation
  if (isNaN(retVal) || retVal < 1 || retVal > 365) {
    if (fb) {
      fb.style.display = "block";
      fb.style.background = "var(--badge-critical-bg)";
      fb.style.color = "var(--status-critical)";
      fb.style.border = "1px solid var(--badge-critical-border)";
      fb.textContent = "Validation Error: Data retention period must be an integer between 1 and 365 days.";
    }
    showToast("Invalid Setting", "Data retention must be between 1 and 365 days.", "critical");
    return;
  }

  const payload = {
    enable_desktop_notifications: toastVal,
    retention_days: String(retVal),
    theme: themeVal
  };

  try {
    for (const [k, v] of Object.entries(payload)) {
      const ok = await api.call("update_setting", k, v);
      if (ok === false) {
        throw new Error(`Failed to persist setting '${k}'`);
      }
    }

    if (themeVal && themeVal !== state.theme) {
      applyTheme(themeVal, false);
    }

    if (fb) {
      fb.style.display = "block";
      fb.style.background = "var(--badge-healthy-bg)";
      fb.style.color = "var(--status-healthy)";
      fb.style.border = "1px solid var(--badge-healthy-border)";
      fb.textContent = "Application configuration saved and persisted successfully.";
    }

    showToast("Settings Saved", "Application configuration updated successfully.", "healthy");
  } catch (err) {
    console.error("Save settings error:", err);
    if (fb) {
      fb.style.display = "block";
      fb.style.background = "var(--badge-critical-bg)";
      fb.style.color = "var(--status-critical)";
      fb.style.border = "1px solid var(--badge-critical-border)";
      fb.textContent = `Save Failed: ${escapeHtml(err.message || String(err))}`;
    }
    showToast("Save Failed", String(err.message || err), "critical");
  }
}

async function clearHistory(type) {
  if (!confirm(`Are you sure you want to clear ${type} history? This action cannot be undone.`)) return;
  await api.call("clear_history_data", type);
  showToast("History Cleared", `Successfully purged ${type} local storage data.`, "healthy");
  refreshActivePage();
}

// Search Handler
function setupSearch() {
  const input = document.getElementById("global-search-input");
  if (!input) return;

  input.addEventListener("input", (e) => {
    state.searchQuery = e.target.value;
    if (state.activePage === "installed_tools") {
      filterAndRenderToolsGrid();
    }
  });
}

// Modals Handling
function setupModals() {
  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) {
        overlay.classList.remove("active");
      }
    });
  });
}

function openToolDetailModal(toolId) {
  const all = [...(state.toolsData?.curated_tools || []), ...(state.toolsData?.all_registry_software || [])];
  const tool = all.find(t => (t.id && t.id === toolId) || t.name === toolId);
  if (!tool) return;

  document.getElementById("tool-modal-title").textContent = tool.name;
  document.getElementById("tool-modal-version").textContent = tool.version;
  document.getElementById("tool-modal-publisher").textContent = tool.publisher;
  document.getElementById("tool-modal-category").textContent = tool.category || "General Software";
  document.getElementById("tool-modal-path").textContent = tool.install_location || "N/A";
  document.getElementById("tool-modal-exe").textContent = tool.exe_path || "N/A";
  document.getElementById("tool-modal-license-file").textContent = tool.license_file || "None Detected in Install Directory";
  document.getElementById("tool-modal-source").textContent = tool.source || "Windows Registry";

  // Match against license records if available
  const licRecord = state.licenseData?.records?.find(r => r.name.toLowerCase() === tool.name.toLowerCase());
  const licCatEl = document.getElementById("tool-modal-license-category");
  const licActEl = document.getElementById("tool-modal-activation");
  const licEvEl = document.getElementById("tool-modal-evidence-source");
  const licMetEl = document.getElementById("tool-modal-verification-method");

  if (licRecord) {
    if (licCatEl) licCatEl.textContent = toCryptic(licRecord.license_category) || "Cryptic";
    if (licActEl) licActEl.textContent = toCryptic(licRecord.activation_status) || "Activation Data Unavailable";
    if (licEvEl) licEvEl.textContent = toCryptic(licRecord.evidence_source) || "Cryptic or inconclusive";
    if (licMetEl) licMetEl.textContent = toCryptic(licRecord.verification_method) || "Inconclusive Heuristic";
  } else {
    if (licCatEl) licCatEl.textContent = "Cryptic (Audit Pending)";
    if (licActEl) licActEl.textContent = "Activation Data Unavailable";
    if (licEvEl) licEvEl.textContent = "Cryptic or inconclusive evidence";
    if (licMetEl) licMetEl.textContent = "Inconclusive Heuristic";
  }


  const modal = document.getElementById("tool-detail-modal");
  if (modal) modal.classList.add("active");
}

function closeToolDetailModal() {
  const modal = document.getElementById("tool-detail-modal");
  if (modal) modal.classList.remove("active");
}

function openEventDetailModal(ev) {
  document.getElementById("event-modal-title").textContent = `Event ID ${ev.event_id} — ${ev.provider}`;
  document.getElementById("event-modal-severity").textContent = ev.level;
  document.getElementById("event-modal-severity").className = `badge badge-${ev.level.toLowerCase()}`;
  document.getElementById("event-modal-time").textContent = ev.timestamp;
  document.getElementById("event-modal-category").textContent = ev.category;
  document.getElementById("event-modal-msg").textContent = ev.message;
  document.getElementById("event-modal-cause").textContent = ev.possible_cause;
  document.getElementById("event-modal-steps").textContent = ev.suggested_steps;

  const modal = document.getElementById("event-detail-modal");
  if (modal) modal.classList.add("active");
}

function closeEventDetailModal() {
  const modal = document.getElementById("event-detail-modal");
  if (modal) modal.classList.remove("active");
}

function promptSafeActionConfirmation(actionId, title, desc, params = {}) {
  state.pendingAction = { actionId, params };
  document.getElementById("confirm-action-title").textContent = `Confirm Safe Action: ${title}`;
  document.getElementById("confirm-action-desc").textContent = desc;

  const modal = document.getElementById("confirm-action-modal");
  if (modal) modal.classList.add("active");
}

function closeConfirmActionModal() {
  state.pendingAction = null;
  const modal = document.getElementById("confirm-action-modal");
  if (modal) modal.classList.remove("active");
}

async function executeConfirmedAction() {
  if (!state.pendingAction) return;
  const { actionId, params } = state.pendingAction;
  closeConfirmActionModal();

  try {
    const res = await api.call("execute_safe_action", actionId, params, true);
    if (res.success) {
      showToast("Action Succeeded", res.message, "healthy");
    } else {
      showToast("Action Notice", res.message, "warning");
    }
    refreshActivePage();
  } catch (err) {
    showToast("Action Error", String(err), "critical");
  }
}

function confirmKillProcess(pid, name) {
  promptSafeActionConfirmation(
    "kill_process",
    `End Task (${name})`,
    `Are you sure you want to terminate process '${name}' (PID: ${pid})? Unsaved progress in this application will be lost.`,
    { pid: pid }
  );
}

// =========================================================================
// EMAIL AUTOMATION, FAULTY DRIVER ALERTS & REPORT CONTROLLERS
// =========================================================================

async function loadEmailSettings() {
  try {
    const s = await api.call("get_email_settings");
    if (!s) return;

    const recipientInput = document.getElementById("set-email-recipient");
    if (recipientInput) recipientInput.value = s.recipient_email || "karthikeyansa369@gmail.com";

    const dailyToggle = document.getElementById("set-email-daily-enable");
    if (dailyToggle) dailyToggle.checked = Boolean(s.daily_report_enabled !== 0 && s.daily_report_enabled !== false);

    const dailyTime = document.getElementById("set-email-daily-time");
    if (dailyTime) dailyTime.value = s.daily_report_time || "19:00";

    const driverToggle = document.getElementById("set-email-driver-enable");
    if (driverToggle) driverToggle.checked = Boolean(s.driver_alerts_enabled !== 0 && s.driver_alerts_enabled !== false);

    const recToggle = document.getElementById("set-email-recovery-enable");
    if (recToggle) recToggle.checked = Boolean(s.driver_recovery_enabled !== 0 && s.driver_recovery_enabled !== false);

    const cooldownInput = document.getElementById("set-email-cooldown");
    if (cooldownInput) cooldownInput.value = s.alert_cooldown_min || 60;

    const hostInput = document.getElementById("set-smtp-host");
    if (hostInput) hostInput.value = s.smtp_host || "smtp.gmail.com";

    const portInput = document.getElementById("set-smtp-port");
    if (portInput) portInput.value = s.smtp_port || 587;

    const secSelect = document.getElementById("set-smtp-security");
    if (secSelect) {
      if (s.smtp_use_ssl) secSelect.value = "ssl";
      else if (s.smtp_use_tls) secSelect.value = "tls";
      else secSelect.value = "none";
    }

    const senderInput = document.getElementById("set-smtp-sender");
    if (senderInput) senderInput.value = s.smtp_sender || "";

    const userInput = document.getElementById("set-smtp-username");
    if (userInput) userInput.value = s.smtp_username || "";

    const pwdStatus = document.getElementById("smtp-pwd-status");
    const pwdInput = document.getElementById("set-smtp-password");
    if (s.has_password) {
      if (pwdStatus) {
        pwdStatus.textContent = "Saved in DPAPI Vault";
        pwdStatus.style.color = "var(--status-healthy)";
      }
      if (pwdInput && !pwdInput.value) pwdInput.placeholder = "•••••••• (Saved in DPAPI)";
    } else {
      if (pwdStatus) {
        pwdStatus.textContent = "No credentials saved";
        pwdStatus.style.color = "var(--status-warning)";
      }
      if (pwdInput && !pwdInput.value) pwdInput.placeholder = "Enter 16-character Google App Password";
    }

    // Windows Task Scheduler Status
    const taskStatusEl = document.getElementById("email-task-scheduler-status");
    const taskBtn = document.getElementById("btn-register-scheduler");
    const nextRunEl = document.getElementById("email-next-run-text");

    if (s.task_scheduler && s.task_scheduler.is_registered) {
      if (taskStatusEl) {
        taskStatusEl.textContent = `Active: Registered for ${s.daily_report_time || '19:00'} Daily`;
        taskStatusEl.style.color = "var(--status-healthy)";
      }
      if (taskBtn) taskBtn.textContent = "Update Windows Task";
    } else {
      if (taskStatusEl) {
        taskStatusEl.textContent = "Not registered in Windows Task Scheduler";
        taskStatusEl.style.color = "var(--text-muted)";
      }
      if (taskBtn) taskBtn.textContent = "Register Windows Task";
    }

    if (nextRunEl) {
      nextRunEl.textContent = s.next_scheduled_run ? s.next_scheduled_run : `Daily at ${s.daily_report_time || '19:00'}`;
    }

  } catch (err) {
    console.error("Error loading email settings:", err);
  }
}

async function saveEmailSettings() {
  const recipient = document.getElementById("set-email-recipient")?.value.trim() || "karthikeyansa369@gmail.com";
  const dailyEnabled = document.getElementById("set-email-daily-enable")?.checked ?? true;
  const dailyTime = document.getElementById("set-email-daily-time")?.value || "19:00";
  const driverEnabled = document.getElementById("set-email-driver-enable")?.checked ?? true;
  const recEnabled = document.getElementById("set-email-recovery-enable")?.checked ?? true;
  const cooldown = parseInt(document.getElementById("set-email-cooldown")?.value || "60", 10);
  const host = document.getElementById("set-smtp-host")?.value.trim() || "smtp.gmail.com";
  const port = parseInt(document.getElementById("set-smtp-port")?.value || "587", 10);
  const sec = document.getElementById("set-smtp-security")?.value || "tls";
  const sender = document.getElementById("set-smtp-sender")?.value.trim() || "";
  const username = document.getElementById("set-smtp-username")?.value.trim() || "";
  const password = document.getElementById("set-smtp-password")?.value || "";

  const payload = {
    recipient_email: recipient,
    daily_report_enabled: dailyEnabled ? 1 : 0,
    daily_report_time: dailyTime,
    driver_alerts_enabled: driverEnabled ? 1 : 0,
    driver_recovery_enabled: recEnabled ? 1 : 0,
    alert_cooldown_min: cooldown,
    smtp_host: host,
    smtp_port: port,
    smtp_use_tls: sec === "tls" ? 1 : 0,
    smtp_use_ssl: sec === "ssl" ? 1 : 0,
    smtp_sender: sender,
    smtp_username: username
  };

  // Only pass password if user entered a non-placeholder value
  if (password && !password.includes("••••")) {
    payload.smtp_password = password;
  }

  try {
    const res = await api.call("update_email_settings", payload);
    if (res.success) {
      showToast("Email Settings Saved", "Configuration and DPAPI credentials updated successfully.", "healthy");
      loadEmailSettings();
    } else {
      showToast("Save Failed", res.message || "Failed to update email settings.", "critical");
    }
  } catch (err) {
    showToast("Error", String(err), "critical");
  }
}

async function testSmtpConnection() {
  const host = document.getElementById("set-smtp-host")?.value.trim() || "smtp.gmail.com";
  const port = parseInt(document.getElementById("set-smtp-port")?.value || "587", 10);
  const sec = document.getElementById("set-smtp-security")?.value || "tls";
  const username = document.getElementById("set-smtp-username")?.value.trim() || "";
  const password = document.getElementById("set-smtp-password")?.value || "";

  const fb = document.getElementById("email-action-feedback");
  if (fb) {
    fb.style.display = "block";
    fb.style.background = "var(--bg-surface-alt)";
    fb.style.color = "var(--text-primary)";
    fb.textContent = `Testing connection to ${host}:${port} (${sec.toUpperCase()})...`;
  }

  showToast("Testing SMTP", `Connecting to ${host}:${port}...`, "healthy");

  const payload = {
    smtp_host: host,
    smtp_port: port,
    smtp_use_tls: sec === "tls",
    smtp_use_ssl: sec === "ssl",
    smtp_username: username
  };
  if (password && !password.includes("••••")) {
    payload.smtp_password = password;
  }

  try {
    const res = await api.call("test_smtp_connection", payload);
    if (fb) {
      if (res.success) {
        fb.style.background = "rgba(69, 214, 163, 0.15)";
        fb.style.color = "var(--status-healthy)";
        fb.textContent = `✓ ${res.message}`;
      } else {
        fb.style.background = "rgba(255, 100, 124, 0.15)";
        fb.style.color = "var(--status-critical)";
        fb.textContent = `✗ ${res.message}`;
      }
    }
    showToast(res.success ? "Connection Successful" : "Connection Failed", res.message, res.success ? "healthy" : "critical");
  } catch (err) {
    if (fb) {
      fb.style.background = "rgba(255, 100, 124, 0.15)";
      fb.style.color = "var(--status-critical)";
      fb.textContent = `✗ Error: ${String(err)}`;
    }
    showToast("SMTP Test Error", String(err), "critical");
  }
}

async function sendTestEmailNow() {
  const recipient = document.getElementById("set-email-recipient")?.value.trim() || "karthikeyansa369@gmail.com";
  const fb = document.getElementById("email-action-feedback");
  if (fb) {
    fb.style.display = "block";
    fb.style.background = "var(--bg-surface-alt)";
    fb.style.color = "var(--text-primary)";
    fb.textContent = `Dispatching test email to ${recipient}...`;
  }

  showToast("Sending Test Email", `Dispatching to ${recipient}...`, "healthy");

  try {
    const res = await api.call("send_test_email", recipient);
    if (fb) {
      if (res.success) {
        fb.style.background = "rgba(69, 214, 163, 0.15)";
        fb.style.color = "var(--status-healthy)";
        fb.textContent = `✓ ${res.message}`;
      } else {
        fb.style.background = "rgba(255, 100, 124, 0.15)";
        fb.style.color = "var(--status-critical)";
        fb.textContent = `✗ ${res.message}`;
      }
    }
    showToast(res.success ? "Test Email Sent" : "Delivery Failed", res.message, res.success ? "healthy" : "critical");
  } catch (err) {
    if (fb) {
      fb.style.background = "rgba(255, 100, 124, 0.15)";
      fb.style.color = "var(--status-critical)";
      fb.textContent = `✗ Error: ${String(err)}`;
    }
    showToast("Test Email Error", String(err), "critical");
  }
}

async function openEmailReportPreview() {
  showToast("Generating Preview", "Compiling full-system diagnostic snapshot...", "healthy");
  try {
    const data = await api.call("preview_daily_report");
    if (!data) return;

    document.getElementById("email-preview-subject").textContent = data.subject || "TERMINAL BOARD Daily Diagnostic Report";
    const recipient = document.getElementById("set-email-recipient")?.value.trim() || "karthikeyansa369@gmail.com";
    document.getElementById("email-preview-recipient-label").textContent = recipient;

    const attachContainer = document.getElementById("email-preview-attachments");
    if (attachContainer) {
      attachContainer.innerHTML = (data.attachment_names || []).map(name => `
        <span class="badge badge-cryptic" style="font-family: monospace; font-size: 11px;">📎 ${name}</span>
      `).join("") || `<span style="color: var(--text-muted); font-size: 11px;">None</span>`;
    }

    const iframe = document.getElementById("email-preview-iframe");
    if (iframe) {
      iframe.srcdoc = data.html || "<p style='color: white; padding: 20px;'>Report generation empty.</p>";
    }

    const modal = document.getElementById("email-preview-modal");
    if (modal) modal.classList.add("active");
  } catch (err) {
    showToast("Preview Error", String(err), "critical");
  }
}

function closeEmailPreviewModal() {
  const modal = document.getElementById("email-preview-modal");
  if (modal) modal.classList.remove("active");
}

async function sendDailyReportNow() {
  closeEmailPreviewModal();
  const recipient = document.getElementById("set-email-recipient")?.value.trim() || "karthikeyansa369@gmail.com";
  showToast("Dispatching Report", `Generating and sending full-system report to ${recipient}...`, "healthy");

  try {
    const res = await api.call("send_daily_report_now", recipient);
    showToast(res.success ? "Report Sent" : "Report Failed", res.message, res.success ? "healthy" : "critical");
  } catch (err) {
    showToast("Dispatch Error", String(err), "critical");
  }
}

async function registerSchedulerJob() {
  const timeStr = document.getElementById("set-email-daily-time")?.value || "19:00";
  const ok = confirm(`Do you consent to registering a scheduled daily task in Windows Task Scheduler for ${timeStr} to dispatch TERMINAL BOARD system reports automatically?`);
  if (!ok) return;

  showToast("Task Scheduler", "Registering Windows scheduled task...", "healthy");
  try {
    const res = await api.call("register_report_schedule", timeStr, true);
    showToast(res.success ? "Task Registered" : "Registration Failed", res.message, res.success ? "healthy" : "critical");
    loadEmailSettings();
  } catch (err) {
    showToast("Task Scheduler Error", String(err), "critical");
  }
}

async function removeSchedulerJob() {
  const ok = confirm("Remove the scheduled daily report task from Windows Task Scheduler?");
  if (!ok) return;

  try {
    const res = await api.call("remove_report_schedule", true);
    showToast(res.success ? "Task Removed" : "Removal Failed", res.message, res.success ? "healthy" : "warning");
    loadEmailSettings();
  } catch (err) {
    showToast("Error", String(err), "critical");
  }
}

function togglePasswordVisibility(elemId) {
  const el = document.getElementById(elemId);
  if (!el) return;
  el.type = el.type === "password" ? "text" : "password";
}

