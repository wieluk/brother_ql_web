// printer.js — printer status polling, rescan, Home Assistant power control

const HA_POLL_INTERVAL  = 10000;  // HA status poll: 10s
const SCAN_NORMAL_INTERVAL = 30000;  // normal printer scan: 30s
const SCAN_FAST_INTERVAL   = 2000;   // fast scan after power-on: 2s
const SCAN_FAST_DURATION   = 60000;  // stay in fast mode for 60s

let _printerScanTimer = null;

function startNormalPrinterPolling() {
    if (_printerScanTimer) clearInterval(_printerScanTimer);
    _printerScanTimer = setInterval(getPrinterStatus, SCAN_NORMAL_INTERVAL);
}

function startFastPrinterPolling() {
    if (_printerScanTimer) clearInterval(_printerScanTimer);
    _printerScanTimer = setInterval(getPrinterStatus, SCAN_FAST_INTERVAL);
    setTimeout(startNormalPrinterPolling, SCAN_FAST_DURATION);
}

// ---------------------------------------------------------------------------
// Printer status fetch
// ---------------------------------------------------------------------------

async function getPrinterStatus() {
    const response = await fetch(url_for_get_printer_status);
    const data = await response.json();
    if (data && Array.isArray(data.printers)) {
        const select = document.getElementById('printer');
        if (select) {
            const cur = select.value;
            select.innerHTML = '';
            data.printers.forEach((p) => {
                const opt = document.createElement('option');
                opt.value = p.path || '';
                const displayPath = p.path ? p.path.replace(/file:\/\//g, '') : '';
                opt.textContent = (p.model || 'Unknown') + ' @ ' + displayPath;
                select.appendChild(opt);
            });
            if (cur && Array.from(select.options).some(o => o.value === cur)) {
                select.value = cur;
            } else if (data.selected) {
                select.value = data.selected;
            } else if (data.printers[0]) {
                select.value = data.printers[0].path;
            }
        }
        const chosenPath = (document.getElementById('printer') || {}).value || (data.selected || (data.printers[0] && data.printers[0].path));
        let chosen = data.printers.find(p => p.path === chosenPath) || data.printers[0] || {};
        printer_status = chosen;
        window.available_printers = data.printers;
    } else {
        printer_status = data;
    }
    updatePrinterStatus();
    updatePrinterDebugPanel(data);
}

async function rescanPrinters() {
    const btn = document.getElementById('printerRescanBtn');
    const icon = document.getElementById('printerRescanIcon');
    if (btn) btn.disabled = true;
    if (icon) icon.classList.add('fa-spin');
    try {
        const response = await fetch(url_for_printer_rescan, { method: 'POST' });
        const data = await response.json();
        if (data && Array.isArray(data.printers)) {
            const select = document.getElementById('printer');
            if (select) {
                const cur = select.value;
                select.innerHTML = '';
                data.printers.forEach((p) => {
                    const opt = document.createElement('option');
                    opt.value = p.path || '';
                    const displayPath = p.path ? p.path.replace(/file:\/\//g, '') : '';
                    opt.textContent = (p.model || 'Unknown') + ' @ ' + displayPath;
                    select.appendChild(opt);
                });
                if (cur && Array.from(select.options).some(o => o.value === cur)) {
                    select.value = cur;
                } else if (data.selected) {
                    select.value = data.selected;
                } else if (data.printers[0]) {
                    select.value = data.printers[0].path;
                }
            }
            const chosenPath = (document.getElementById('printer') || {}).value || (data.selected || (data.printers[0] && data.printers[0].path));
            printer_status = data.printers.find(p => p.path === chosenPath) || data.printers[0] || {};
            window.available_printers = data.printers;
        } else {
            printer_status = data;
        }
        updatePrinterStatus();
        updatePrinterDebugPanel(data);
    } catch (e) {
        console.error('Rescan failed:', e);
    } finally {
        if (icon) icon.classList.remove('fa-spin');
        if (btn) btn.disabled = false;
    }
}

// ---------------------------------------------------------------------------
// Printer debug panel
// ---------------------------------------------------------------------------

function updatePrinterDebugPanel(data) {
    const content = document.getElementById('printerDebugContent');
    if (!content) return;

    const printers = (data && Array.isArray(data.printers)) ? data.printers : [];
    const scanLog  = (data && Array.isArray(data.scan_log)) ? data.scan_log : [];

    let html = '<h6>Detected Printers (' + printers.length + ')</h6>';
    if (printers.length === 0) {
        html += '<div class="alert alert-warning py-2">No printers found.</div>';
    } else {
        html += '<ul class="list-group mb-3">';
        printers.forEach(p => {
            const isOk = !p.errors || p.errors.length === 0;
            html += '<li class="list-group-item list-group-item-' + (isOk ? 'success' : 'danger') + ' py-2">';
            html += '<strong>' + (p.model || 'Unknown') + '</strong>';
            html += ' &mdash; <code>' + (p.path || '') + '</code>';
            html += ' <span class="badge bg-secondary ms-1">' + (p.status_type || '') + '</span>';
            if (p.media_width) html += ' <span class="text-muted small ms-1">' + p.media_width + 'mm</span>';
            if (p.errors && p.errors.length > 0) {
                html += '<br><small class="text-danger">' + p.errors.join(', ') + '</small>';
            }
            html += '</li>';
        });
        html += '</ul>';
    }

    if (scanLog.length > 0) {
        html += '<h6>Last USB Scan Log</h6><ul class="list-group mb-2">';
        scanLog.forEach(entry => {
            const cls = entry.found ? 'success' : 'danger';
            html += '<li class="list-group-item list-group-item-' + cls + ' py-1 small">';
            html += '<code>' + entry.device + '</code>';
            if (entry.found) {
                html += ' <span class="badge bg-success ms-1">Found: ' + (entry.model || '?') + '</span>';
            } else {
                html += ' <span class="badge bg-danger ms-1">Failed</span>';
                if (entry.error) html += '<br><span class="text-danger">' + entry.error + '</span>';
            }
            html += '</li>';
        });
        html += '</ul>';
    } else if (data && data.path && data.path !== '?') {
        html += '<p class="text-muted small">Using fixed device: <code>' + data.path + '</code></p>';
    }

    content.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Home Assistant power button
// ---------------------------------------------------------------------------

function updatePrinterPowerStatus() {
    fetch('/api/printer_power/status')
        .then(r => r.json())
        .then(data => {
            const btn = document.getElementById('printerPowerBtn');
            const icon = document.getElementById('printerPowerIcon');
            const status = document.getElementById('printerPowerStatus');
            if (!btn) return;
            if (data.state === 'on') {
                icon.classList.remove('fa-plug', 'text-danger');
                icon.classList.add('fa-bolt', 'text-success');
                status.textContent = 'On';
                btn.classList.remove('btn-outline-info');
                btn.classList.add('btn-success');
            } else if (data.state === 'off') {
                icon.classList.remove('fa-bolt', 'text-success');
                icon.classList.add('fa-plug', 'text-danger');
                status.textContent = 'Off';
                btn.classList.remove('btn-success');
                btn.classList.add('btn-outline-info');
            } else {
                icon.classList.remove('fa-bolt', 'fa-plug', 'text-success', 'text-danger');
                status.textContent = 'Unknown';
                btn.classList.remove('btn-success');
                btn.classList.add('btn-outline-info');
            }
        })
        .catch(() => { /* network error — leave button as-is */ });
}

function togglePrinterPower() {
    fetch('/api/printer_power/toggle', { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            setTimeout(updatePrinterPowerStatus, 1000);
            getPrinterStatus();
            startFastPrinterPolling();
        });
}

document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('printerPowerBtn');
    if (btn) {
        btn.addEventListener('click', togglePrinterPower);
        updatePrinterPowerStatus();
        setInterval(updatePrinterPowerStatus, HA_POLL_INTERVAL);
    }
});
