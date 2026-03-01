// main.js — application entry point

// ---------------------------------------------------------------------------
// Dark mode (uses [data-theme="dark"] on <html>)
// ---------------------------------------------------------------------------

(function () {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');

    function _applyTheme(mode) {
        document.documentElement.setAttribute('data-theme', mode);
        const icon = document.getElementById('darkModeIcon');
        if (icon) {
            icon.innerHTML = mode === 'dark'
                ? '<span class="fas fa-moon"></span>'
                : '<span class="fas fa-sun"></span>';
        }
    }

    function _getPreferredMode() {
        return localStorage.getItem('themeMode') || (prefersDark.matches ? 'dark' : 'light');
    }

    function toggleDarkMode() {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        _applyTheme(next);
        localStorage.setItem('themeMode', next);
    }

    // Apply stored / preferred theme before first paint to avoid flash
    _applyTheme(_getPreferredMode());

    prefersDark.addEventListener('change', function (e) {
        if (!localStorage.getItem('themeMode')) _applyTheme(e.matches ? 'dark' : 'light');
    });

    document.addEventListener('DOMContentLoaded', function () {
        const toggle = document.getElementById('darkModeToggle');
        if (toggle) toggle.onclick = toggleDarkMode;
        // Re-apply in case icon element wasn't ready earlier
        _applyTheme(_getPreferredMode());
    });
})();

// ---------------------------------------------------------------------------
// Default input values
// ---------------------------------------------------------------------------

function set_all_inputs_default(force = false) {
    $('input[data-default], select[data-default], textarea[data-default]').each(function () {
        if (this.type === 'checkbox' || this.type === 'radio') {
            $(this).prop('checked', $(this).data('default') == 1 || $(this).data('default') == true);
        } else if (this.type === 'select-one' || this.type === 'number') {
            $(this).val($(this).data('default'));
        } else if (!$(this).val() || force) {
            $(this).val($(this).data('default'));
        }
    });
}

function resetSettings() {
    if (confirm('Really reset all label settings to default?')) {
        localStorage.removeItem(LS_KEY);
        window.fontSettingsPerLine = [];
        set_all_inputs_default(true);
        saveAllSettingsToLocalStorage();
        location.reload();
    }
}

// ---------------------------------------------------------------------------
// Bootstrap — called once barcode types are loaded (see label.js get_barcode_types)
// ---------------------------------------------------------------------------

function init2() {
    set_all_inputs_default();
    restoreAllSettingsFromLocalStorage();

    $(document).on('change input', 'input, select, textarea', function () {
        if ($(this).is('#lineSelect')) return;
        setFontSettingsPerLine();
        saveAllSettingsToLocalStorage();
    });

    $('input.btn-check[type="radio"]').off('change.btnCheckActive').on('change.btnCheckActive', function () {
        const name = $(this).attr('name');
        $(`input[name="${name}"]`).each(function () {
            $(`label[for="${this.id}"]`).removeClass('active');
        });
        $(`label[for="${this.id}"]`).addClass('active');
    });

    $('#resetSettings').on('click', resetSettings);
    $('#undoSettingsBtn').on('click', undoSettings);
    updateUndoButton();

    // Sync margin: when any margin input changes, mirror to all others if sync is on
    $('#margin_top, #margin_bottom, #margin_left, #margin_right').on('change input', function () {
        if ($('#sync_margin').is(':checked')) {
            var val = $(this).val();
            $('#margin_top, #margin_bottom, #margin_left, #margin_right').not(this).val(val);
        }
    });
    // When sync is enabled, immediately equalise all sides to the top value
    $('#sync_margin').on('change', function () {
        if ($(this).is(':checked')) {
            var val = $('#margin_top').val();
            $('#margin_bottom, #margin_left, #margin_right').val(val);
            preview();
        }
    });

    preview();
}

// ---------------------------------------------------------------------------
// Page load
// ---------------------------------------------------------------------------

window.onload = async function () {
    get_barcode_types();  // triggers init2() after barcodes are fetched

    getPrinterStatus();
    startNormalPrinterPolling();

    const rescanBtn = document.getElementById('printerRescanBtn');
    if (rescanBtn) rescanBtn.addEventListener('click', rescanPrinters);
    const debugRescanBtn = document.getElementById('printerDebugRescanBtn');
    if (debugRescanBtn) debugRescanBtn.addEventListener('click', rescanPrinters);
};
