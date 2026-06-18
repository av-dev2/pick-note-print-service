/**
 * Pick Note Print Service — Dashboard JavaScript
 *
 * Handles all client-side logic: config loading/saving, connection testing,
 * printer enumeration, service start/stop, log polling, and toast notifications.
 *
 * Uses modern ES6+ (const/let, async/await, fetch API). No external dependencies.
 */

"use strict";

// ==========================================================================
//  DOM References
// ==========================================================================
const $id = (id) => document.getElementById(id);

const DOM = {
    // Connection
    frappeUrl:        $id("frappe-url"),
    apiToken:         $id("api-token"),
    btnTestConn:      $id("btn-test-connection"),
    connResult:       $id("connection-result"),

    // Layout
    paperWidth:       $id("paper-width"),
    pollInterval:     $id("poll-interval"),
    feedLines:        $id("feed-lines"),
    autoCut:          $id("auto-cut"),

    // Printer
    printerType:      $id("printer-type"),
    printerName:      $id("printer-name"),
    printerNameGroup: $id("printer-name-group"),
    printerAddress:   $id("printer-address"),
    printerAddrGroup: $id("printer-address-group"),
    btnRefreshPrint:  $id("btn-refresh-printers"),
    btnTestPrint:     $id("btn-test-print"),

    // Controls
    btnSaveConfig:    $id("btn-save-config"),
    btnToggleService: $id("btn-toggle-service"),

    // Status
    statusDot:        $id("status-dot"),
    statusText:       $id("status-text"),
    statLastPoll:     $id("stat-last-poll"),
    statJobsProc:     $id("stat-jobs-processed"),
    statLastError:    $id("stat-last-error"),

    // Log
    logTableBody:     $id("log-table-body"),
    logCount:         $id("log-count"),

    // Toast
    toastContainer:   $id("toast-container"),
};


// ==========================================================================
//  State
// ==========================================================================
let isServiceRunning = false;
let refreshInterval  = null;


// ==========================================================================
//  Toast notifications
// ==========================================================================

/**
 * Show a toast notification.
 * @param {string} message - The message to display.
 * @param {"success"|"error"|"info"} type - Toast type.
 * @param {number} duration - Auto-dismiss in milliseconds.
 */
function showToast(message, type = "info", duration = 4000) {
    const icons = {
        success: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
        error:   `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
        info:    `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    };

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `${icons[type] || icons.info}<span>${escapeHtml(message)}</span>`;

    DOM.toastContainer.appendChild(toast);

    // Auto-dismiss
    setTimeout(() => {
        toast.classList.add("removing");
        toast.addEventListener("animationend", () => toast.remove());
    }, duration);
}


// ==========================================================================
//  Utility helpers
// ==========================================================================

/** Escape HTML entities for safe insertion. */
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

/** Set a button into loading state. */
function setLoading(btn, loading) {
    if (loading) {
        btn.classList.add("loading");
        btn.disabled = true;
    } else {
        btn.classList.remove("loading");
        btn.disabled = false;
    }
}

/** Generic JSON fetch wrapper with error handling. */
async function apiFetch(url, options = {}) {
    const resp = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
        throw new Error(data.error || `HTTP ${resp.status}`);
    }
    return data;
}

/** Format an ISO timestamp to a human-friendly local string. */
function formatTimestamp(iso) {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        return d.toLocaleString();
    } catch {
        return iso;
    }
}


// ==========================================================================
//  Config: Load & Save
// ==========================================================================

/** Load config from the server and populate form fields. */
async function loadConfig() {
    try {
        const data = await apiFetch("/api/config");

        DOM.frappeUrl.value    = data.frappe_url || "";
        DOM.apiToken.value     = data.api_token || "";
        DOM.pollInterval.value = data.poll_interval_seconds || 30;

        // Layout settings
        DOM.paperWidth.value = data.paper_width || 42;
        DOM.feedLines.value  = data.feed_lines ?? 3;
        DOM.autoCut.checked  = data.auto_cut !== false;  // Default true

        // Printer type
        DOM.printerType.value  = data.printer_type || "windows";
        DOM.printerAddress.value = data.printer_address || "";
        updatePrinterUI();



        // Printer name — set a temporary option if stored
        if (data.printer_name) {
            const opt = document.createElement("option");
            opt.value = data.printer_name;
            opt.textContent = data.printer_name;
            opt.selected = true;
            // Prepend but keep the existing options
            DOM.printerName.innerHTML = "";
            DOM.printerName.appendChild(opt);
        }

    } catch (err) {
        console.warn("Failed to load config:", err);
    }
}

/** Save the current form values to the server. */
async function saveConfig() {
    setLoading(DOM.btnSaveConfig, true);
    try {
        const body = {
            frappe_url:           DOM.frappeUrl.value.trim(),
            api_token:            DOM.apiToken.value.trim(),
            paper_width:          parseInt(DOM.paperWidth.value, 10) || 42,
            feed_lines:           parseInt(DOM.feedLines.value, 10) || 3,
            auto_cut:             DOM.autoCut.checked,
            poll_interval_seconds: parseInt(DOM.pollInterval.value, 10) || 30,
            printer_type:         DOM.printerType.value,
            printer_name:         DOM.printerName.value,
            printer_address:      DOM.printerAddress.value.trim(),
        };

        // Validate required fields
        if (!body.frappe_url) {
            showToast("Frappe URL is required.", "error");
            return;
        }
        if (!body.api_token) {
            showToast("API Token is required.", "error");
            return;
        }

        await apiFetch("/api/config", { method: "POST", body: JSON.stringify(body) });
        showToast("Configuration saved successfully.", "success");
    } catch (err) {
        showToast(`Save failed: ${err.message}`, "error");
    } finally {
        setLoading(DOM.btnSaveConfig, false);
    }
}


// ==========================================================================
//  Connection test
// ==========================================================================

async function testConnection() {
    setLoading(DOM.btnTestConn, true);
    DOM.connResult.textContent = "";
    DOM.connResult.className = "result-text";

    try {
        const body = {
            frappe_url:  DOM.frappeUrl.value.trim(),
            api_token:   DOM.apiToken.value.trim(),
        };

        if (!body.frappe_url || !body.api_token) {
            showToast("Please enter the Frappe URL and API Token.", "error");
            return;
        }

        const data = await apiFetch("/api/test-connection", {
            method: "POST",
            body: JSON.stringify(body),
        });

        DOM.connResult.textContent = `✓ Connected as ${data.user || "unknown"}`;
        DOM.connResult.className = "result-text success";
        showToast(`Connected as ${data.user}`, "success");

    } catch (err) {
        DOM.connResult.textContent = `✗ ${err.message}`;
        DOM.connResult.className = "result-text error";
        showToast(`Connection failed: ${err.message}`, "error");
    } finally {
        setLoading(DOM.btnTestConn, false);
    }
}



// ==========================================================================
//  Printers
// ==========================================================================

async function fetchPrinters() {
    setLoading(DOM.btnRefreshPrint, true);
    try {
        const data = await apiFetch("/api/printers");
        const printers = data.printers || [];
        const currentPrinter = DOM.printerName.value;

        DOM.printerName.innerHTML = "";

        if (printers.length === 0) {
            const opt = document.createElement("option");
            opt.value = "";
            opt.textContent = "— No printers found —";
            DOM.printerName.appendChild(opt);
            showToast("No printers found on this system.", "info");
            return;
        }

        for (const p of printers) {
            const opt = document.createElement("option");
            opt.value = p.name;
            opt.textContent = `${p.name} (${p.type})`;
            if (p.name === currentPrinter) opt.selected = true;
            DOM.printerName.appendChild(opt);
        }

        showToast(`Found ${printers.length} printer(s).`, "success");
    } catch (err) {
        showToast(`Failed to list printers: ${err.message}`, "error");
    } finally {
        setLoading(DOM.btnRefreshPrint, false);
    }
}


/** Show/hide printer fields based on the selected printer type. */
function updatePrinterUI() {
    const ptype = DOM.printerType.value;

    // Show address input for network and serial types
    if (ptype === "network" || ptype === "serial") {
        DOM.printerAddrGroup.style.display = "block";
        DOM.printerAddress.placeholder = ptype === "network"
            ? "192.168.1.100:9100"
            : "/dev/ttyUSB0 or COM3";
    } else {
        DOM.printerAddrGroup.style.display = "none";
    }

    // Show printer name dropdown for windows and cups types
    if (ptype === "windows" || ptype === "cups") {
        DOM.printerNameGroup.style.display = "block";
    } else if (ptype === "network") {
        DOM.printerNameGroup.style.display = "none";
    } else {
        DOM.printerNameGroup.style.display = "block";
    }
}


async function testPrint() {
    setLoading(DOM.btnTestPrint, true);
    try {
        await apiFetch("/api/test-print", { method: "POST" });
        showToast("Test print sent successfully!", "success");
    } catch (err) {
        showToast(`Test print failed: ${err.message}`, "error");
    } finally {
        setLoading(DOM.btnTestPrint, false);
    }
}


// ==========================================================================
//  Service control
// ==========================================================================

async function toggleService() {
    setLoading(DOM.btnToggleService, true);
    try {
        if (isServiceRunning) {
            await apiFetch("/api/service/stop", { method: "POST" });
            showToast("Print service stopped.", "info");
        } else {
            await apiFetch("/api/service/start", { method: "POST" });
            showToast("Print service started!", "success");
        }
        // Immediately refresh status
        await refreshStatus();
    } catch (err) {
        showToast(`Service action failed: ${err.message}`, "error");
    } finally {
        setLoading(DOM.btnToggleService, false);
    }
}


// ==========================================================================
//  Status & Logs polling
// ==========================================================================

async function refreshStatus() {
    try {
        const data = await apiFetch("/api/status");
        isServiceRunning = data.running;

        // Update header badge
        DOM.statusDot.className  = `status-dot${data.running ? " running" : ""}`;
        DOM.statusText.textContent = data.running ? "Running" : "Stopped";

        // Update toggle button
        const btnText = DOM.btnToggleService.querySelector(".btn-text");
        if (data.running) {
            btnText.textContent = "Stop Service";
            DOM.btnToggleService.className = "btn btn-danger btn-lg";
        } else {
            btnText.textContent = "Start Service";
            DOM.btnToggleService.className = "btn btn-success btn-lg";
        }

        // Update stats
        DOM.statLastPoll.textContent     = formatTimestamp(data.last_poll);
        DOM.statJobsProc.textContent     = data.jobs_processed ?? 0;
        DOM.statLastError.textContent    = data.last_error || "None";
        DOM.statLastError.className      = `stat-value${data.last_error ? " stat-error" : ""}`;

    } catch (err) {
        console.warn("Status refresh failed:", err);
    }
}

async function refreshLogs() {
    try {
        const data = await apiFetch("/api/logs");
        const logs = data.logs || [];

        DOM.logCount.textContent = `${logs.length} entr${logs.length === 1 ? "y" : "ies"}`;

        if (logs.length === 0) {
            DOM.logTableBody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="4">No print jobs yet. Start the service to begin polling.</td>
                </tr>`;
            return;
        }

        // Render rows in reverse order (newest first)
        const rows = [...logs].reverse().map((log) => {
            const statusClass = log.status || "info";
            return `
                <tr>
                    <td>${escapeHtml(formatTimestamp(log.timestamp))}</td>
                    <td>${escapeHtml(log.pick_note || "—")}</td>
                    <td><span class="log-status ${statusClass}">${escapeHtml(log.status || "—")}</span></td>
                    <td>${escapeHtml(log.message || "—")}</td>
                </tr>`;
        }).join("");

        DOM.logTableBody.innerHTML = rows;

    } catch (err) {
        console.warn("Log refresh failed:", err);
    }
}


// ==========================================================================
//  Initialisation
// ==========================================================================

document.addEventListener("DOMContentLoaded", async () => {
    // Load config and populate the form
    await loadConfig();

    // Fetch initial status
    await refreshStatus();
    await refreshLogs();

    // Try to load printers on init
    fetchPrinters();

    // ------- Event listeners -------

    // Connection
    DOM.btnTestConn.addEventListener("click", testConnection);

    // Printer
    DOM.printerType.addEventListener("change", updatePrinterUI);
    DOM.btnRefreshPrint.addEventListener("click", fetchPrinters);
    DOM.btnTestPrint.addEventListener("click", testPrint);

    // Config
    DOM.btnSaveConfig.addEventListener("click", saveConfig);

    // Service
    DOM.btnToggleService.addEventListener("click", toggleService);

    // ------- Auto-refresh -------
    refreshInterval = setInterval(async () => {
        await refreshStatus();
        await refreshLogs();
    }, 10_000);
});
