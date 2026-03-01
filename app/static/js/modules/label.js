// label.js — label generation, preview, print, Dropzone, status display

var lastPreviewData = null;
var imageDropZone = null;
var dropZoneMode = 'preview';

// Global printer status (updated by printer.js)
var printer_status = {
    errors: [],
    model: 'Unknown',
    media_width: 62,
    media_length: 0,
    phase_type: 'Unknown',
    red_support: false
};

// ---------------------------------------------------------------------------
// Form data collection
// ---------------------------------------------------------------------------

function formData(cut_once = false) {
    var data = {
        text: JSON.stringify(fontSettingsPerLine),
        label_size: $('#label_size').val(),
        orientation: $('input[name=orientation]:checked').val(),
        margin_top: parseInt($('#margin_top').val(), 10) || 0,
        margin_bottom: parseInt($('#margin_bottom').val(), 10) || 0,
        margin_left: parseInt($('#margin_left').val(), 10) || 0,
        margin_right: parseInt($('#margin_right').val(), 10) || 0,
        print_type: $('input[name=print_type]:checked').val(),
        barcode_type: $('#barcode_type').val() || 'QR',
        qrcode_size: parseInt($('#qrcode_size').val(), 10) || 0,
        qrcode_correction: $('#qrcode_correction option:selected').val(),
        image_bw_threshold: parseInt($('#image_bw_threshold').val(), 10) || 0,
        image_mode: $('input[name=image_mode]:checked').val(),
        image_fit: $('#image_fit').is(':checked') ? 1 : 0,
        print_count: parseInt($('#print_count').val(), 10) || 0,
        log_level: $('#log_level').val(),
        cut_once: cut_once ? 1 : 0,
        border_thickness: parseInt($('#border_thickness').val(), 10) || 0,
        border_roundness: parseInt($('#border_roundness').val(), 10) || 0,
        border_distance_x: parseInt($('#border_distance_x').val(), 10) || 0,
        border_distance_y: parseInt($('#border_distance_y').val(), 10) || 0,
        high_res: $('#high_res').is(':checked') ? 1 : 0,
        image_scaling_factor: parseInt($('#image_scaling_factor').val(), 10) || 0,
        image_rotation: parseInt($('#image_rotation').val(), 10) || 0,
        sync_font_settings: $('#sync_font_settings').is(':checked') ? 1 : 0
    };

    if (printer_status['red_support']) {
        data['print_color'] = $('input[name=print_color]:checked').val();
        data['border_color'] = $('input[name=border_color]:checked').val();
    }
    data['code_text'] = $('#code_text').val() || '';

    data['ship_sender_name']      = $('#ship_sender_name').val()      || '';
    data['ship_sender_street']    = $('#ship_sender_street').val()    || '';
    data['ship_sender_zip_city']  = $('#ship_sender_zip_city').val()  || '';
    data['ship_sender_country']   = $('#ship_sender_country').val()   || '';
    data['ship_recip_company']    = $('#ship_recip_company').val()    || '';
    data['ship_recip_name']       = $('#ship_recip_name').val()       || '';
    data['ship_recip_street']     = $('#ship_recip_street').val()     || '';
    data['ship_recip_zip_city']   = $('#ship_recip_zip_city').val()   || '';
    data['ship_recip_country']    = $('#ship_recip_country').val()    || '';
    data['ship_tracking']         = $('#ship_tracking').val()         || '';
    data['ship_section_spacing']  = parseInt($('#ship_section_spacing').val(), 10)  || 0;
    data['ship_barcode_scale']    = parseInt($('#ship_barcode_scale').val(), 10)    || 0;
    data['ship_barcode_show_text']= $('#ship_barcode_show_text').is(':checked') ? 1 : 0;
    data['ship_from_label']       = $('#ship_from_label').val()       || '';
    data['ship_to_label']         = $('#ship_to_label').val()         || '';
    data['ship_recip_border']     = $('#ship_recip_border').is(':checked') ? 1 : 0;

    const printerSelect = document.getElementById('printer');
    if (printerSelect && printerSelect.value) {
        data['printer'] = printerSelect.value;
    }

    const modelFromPrinter = (() => {
        if (printerSelect && printerSelect.value && window.available_printers) {
            const p = window.available_printers.find(p => p.path === printerSelect.value);
            if (p && p.model && p.model !== 'Unknown') return p.model;
        }
        if (printer_status && printer_status.model && printer_status.model !== 'Unknown') {
            return printer_status.model;
        }
        return null;
    })();
    if (modelFromPrinter) data['model'] = modelFromPrinter;

    return data;
}

function get_dpi() {
    return $('#high_res').is(':checked') ? 600 : 300;
}

// ---------------------------------------------------------------------------
// Preview image
// ---------------------------------------------------------------------------

function updatePreview(data) {
    $('#previewImg').attr('src', 'data:image/png;base64,' + data);
    var img = $('#previewImg')[0];
    img.onload = function () {
        $('#labelWidth').html((img.naturalWidth / get_dpi() * 2.54).toFixed(1));
        $('#labelHeight').html((img.naturalHeight / get_dpi() * 2.54).toFixed(1));
    };
}

// ---------------------------------------------------------------------------
// Label generation
// ---------------------------------------------------------------------------

function updateAccordionAvailability(printType) {
    // Full-section disable rules
    const sectionRules = {
        accordionFontSettings:  printType === 'qrcode' || printType === 'image',
        accordionCodeSettings:  printType === 'text'   || printType === 'image',
        accordionImageSettings: printType !== 'image',
    };
    for (const [id, disabled] of Object.entries(sectionRules)) {
        const el = document.getElementById(id);
        if (!el) continue;
        const item = el.closest('.accordion-item');
        if (!item) continue;
        item.classList.toggle('section-disabled', disabled);
        if (disabled && el.classList.contains('show')) {
            (bootstrap.Collapse.getInstance(el) ||
             new bootstrap.Collapse(el, { toggle: false })).hide();
        }
    }
    // Shipping-specific sub-group restrictions
    const shippingMode = printType === 'shipping';
    ['fontAlignmentGroup', 'additionalFontOptions', 'codeContentGroup'].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('controls-disabled', shippingMode);
    });

    // Auto-open the primary section for the current print type
    const primarySection = {
        text:         'accordionFontSettings',
        qrcode:       'accordionCodeSettings',
        qrcode_text:  'accordionFontSettings',
        image:        'accordionImageSettings',
        shipping:     'accordionFontSettings',
    }[printType];
    if (primarySection) {
        const openEl = document.getElementById(primarySection);
        if (openEl && !openEl.classList.contains('show')) {
            (bootstrap.Collapse.getInstance(openEl) || new bootstrap.Collapse(openEl)).show();
        }
    }
}

function gen_label(isPreview = true, cut_once = false) {
    updatePrinterStatus();
    setFontSettingsPerLine();

    if (isPreview) {
        if ($('#label_size option:selected').data('round') == 'True') {
            $('img#previewImg').addClass('roundPreviewImage');
        } else {
            $('img#previewImg').removeClass('roundPreviewImage');
        }
    }

    const printType = $('input[name=print_type]:checked').val();
    if (printType === 'image') {
        $('#groupLabelImage').show();
    } else {
        $('#groupLabelImage').hide();
    }
    if (printType === 'shipping') {
        $('#groupShipping').show();
        $('#groupLabelText').hide();
    } else {
        $('#groupShipping').hide();
        if (printType !== 'image') {
            $('#groupLabelText').show();
        } else {
            $('#groupLabelText').hide();
        }
    }

    updateAccordionAvailability(printType);

    let type = isPreview ? 'preview' : 'printing';
    setStatus({ type: type, status: 'pending' });

    if ($('input[name=print_type]:checked').val() == 'image') {
        dropZoneMode = isPreview ? 'preview' : 'printing';
        imageDropZone.processQueue();
        return;
    }

    const data = formData(cut_once);
    const dataJson = JSON.stringify(data);
    if (isPreview && dataJson === lastPreviewData) {
        console.debug('No changes detected, not generating new preview.');
        return;
    }
    lastPreviewData = dataJson;

    const url = isPreview ? (url_for_preview + '?return_format=base64') : url_for_print;
    $.ajax({
        type: 'POST',
        url: url,
        contentType: 'application/x-www-form-urlencoded; charset=UTF-8',
        data: formData(cut_once),
        success: function (data) {
            const status = typeof data === 'object' && data !== null && 'success' in data && data.success === false
                ? 'error' : 'success';
            setStatus({ type: type, status: status });
            updatePreview(data);
        },
        error: function (xhr, _status, error) {
            const message = xhr.responseJSON ? xhr.responseJSON.message : error;
            const text = isPreview ? 'Preview generation failed' : 'Printing failed';
            setStatus({ type: type, status: 'error', message: message }, text);
        }
    });
}

function print(cut_once = false) { gen_label(false, cut_once); }
function preview() { gen_label(true); }

// ---------------------------------------------------------------------------
// Status display
// ---------------------------------------------------------------------------

function setStatus(data, what = null) {
    let type = data.type || '';
    let status = data.status || '';
    let message = data.message || '';
    let errors = data?.errors || [];
    let extra_info = message ? ':<br />' + message : '';
    if (errors.length > 0) extra_info += '<br />' + errors.join('<br />');

    let html = '';
    let iconClass = '';

    if (type === 'preview' || type === 'printing') {
        if (status === 'pending') {
            let action = type === 'printing' ? 'Printing' : 'Generating preview';
            html = `<div id="statusBox" class="alert alert-info" role="alert">
                        <i class="fas fa-hourglass-half"></i>
                        <span>${action}...</span>
                    </div>`;
            iconClass = 'float-end fas fa-hourglass-half text-muted';
        } else if (status === 'success') {
            if (type === 'preview') {
                html = `<div id="statusBox" class="alert alert-info" role="alert">
                            <i class="fas fa-eye"></i>
                            <span>Preview generated successfully.</span>
                        </div>`;
                iconClass = 'float-end fas fa-check text-success';
            } else {
                html = `<div id="statusBox" class="alert alert-success" role="alert">
                            <i class="fas fa-check"></i>
                            <span>Printing was successful.</span>
                        </div>`;
                iconClass = 'float-end fas fa-print text-success';
            }
        } else if (status === 'error') {
            let action = type === 'preview' ? 'Preview generation failed' : 'Printing failed';
            html = `<div id="statusBox" class="alert alert-warning" role="alert">
                        <i class="fas fa-exclamation-triangle"></i>
                        <span>${action}${extra_info}</span>
                    </div>`;
            iconClass = 'float-end fas fa-exclamation-triangle text-danger';
        }
    } else if (type === 'status') {
        if (status === 'error') {
            html = `<div id="statusBox" class="alert alert-warning" role="alert">
                        <i class="fas fa-exclamation-triangle"></i>
                        <span>Error${extra_info}</span>
                    </div>`;
            iconClass = 'float-end fas fa-exclamation-triangle text-danger';
        }
    }

    let elem = type === 'status' ? $('#printerStatusPanel') : $('#statusPanel');
    elem.html(html);
    if (html.length > 0) elem.show(); else elem.hide();

    $('#statusIcon').removeClass().addClass(iconClass);
    $('#printButton').prop('disabled', false);
    $('#dropdownPrintButton').prop('disabled', false);
}

// ---------------------------------------------------------------------------
// Printer status UI
// ---------------------------------------------------------------------------

function updatePrinterStatus() {
    if ($('#label_size option:selected').val().includes('red')) {
        $('.red-support').show();
    } else {
        $('#print_color_black').prop('active', true);
        $('.red-support').hide();
    }

    const labelSizeX = document.getElementById('label-width');
    const labelSizeY = document.getElementById('label-height');
    if (labelSizeX && labelSizeY) {
        labelSizeX.textContent = (printer_status.media_width ?? '???') + ' mm';
        if (printer_status.media_length > 0) {
            labelSizeY.textContent = printer_status.media_length + ' mm';
        } else if (printer_status.media_type === 'Continuous length tape') {
            labelSizeY.textContent = 'endless';
        } else {
            labelSizeY.textContent = '???';
        }
    }

    const labelSizeSelect = document.getElementById('label_size');
    const labelMismatch = document.getElementById('labelMismatch');
    const labelMismatchIcon = document.getElementById('labelMismatchIcon');
    if (labelSizeSelect && labelMismatch && labelMismatchIcon) {
        const selectedOption = labelSizeSelect.options[labelSizeSelect.selectedIndex];
        const dataX = selectedOption.getAttribute('data-x');
        const dataY = selectedOption.getAttribute('data-y');
        if (printer_status.media_width !== null &&
            (printer_status.media_width !== parseInt(dataX) || printer_status.media_length !== parseInt(dataY))) {
            labelMismatch.style.display = '';
            labelMismatchIcon.style.display = '';
        } else {
            labelMismatch.style.display = 'none';
            labelMismatchIcon.style.display = 'none';
        }
    }

    if (printer_status.errors && printer_status.errors.length > 0) {
        setStatus({ type: 'status', status: 'error', errors: printer_status.errors });
    } else {
        setStatus({ type: 'status', status: 'success' });
    }
}

// ---------------------------------------------------------------------------
// Barcode type selector
// ---------------------------------------------------------------------------

function toggleQrSettings() {
    var barcodeType = document.getElementById('barcode_type');
    var qrCodeSize = document.getElementById('qrCodeSizeContainer');
    var qrCodeCorrection = document.getElementById('qrCodeCorrectionContainer');
    if (barcodeType) {
        qrCodeSize.style.display = (barcodeType.value === 'QR') ? '' : 'none';
        qrCodeCorrection.style.display = (barcodeType.value === 'QR') ? '' : 'none';
    }
}

function get_barcode_types() {
    fetch(url_for_get_barcodes)
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById('barcode_type');
            var barcodes = data['barcodes'];
            if (select && Array.isArray(barcodes) && barcodes.length > 0) {
                barcodes.forEach((barcode, idx) => {
                    const opt = document.createElement('option');
                    opt.value = barcode;
                    opt.textContent = barcode;
                    if (idx === 0) {
                        opt.selected = true;
                        opt.setAttribute('data-default', '1');
                    }
                    select.appendChild(opt);
                });
                toggleQrSettings();
                select.addEventListener('change', toggleQrSettings);
                init2();
            }
        });
}

// ---------------------------------------------------------------------------
// Dropzone initialization (runs once DOM is ready)
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', function () {
    if (typeof Dropzone === 'undefined' || !document.getElementById('image-dropzone')) return;

    Dropzone.autoDiscover = false;
    imageDropZone = new Dropzone('#image-dropzone', {
        url: function () {
            return dropZoneMode === 'preview'
                ? url_for_preview + '?return_format=base64'
                : url_for_print;
        },
        paramName: 'image',
        acceptedFiles: 'image/*,application/pdf',
        maxFiles: 1,
        addRemoveLinks: true,
        autoProcessQueue: false,
        thumbnailMethod: 'contain',
        init: function () {
            this.on('addedfile', function () {
                if (this.files[1] != null) this.removeFile(this.files[0]);
            });
        },
        sending: function (file, xhr, formDataObj) {
            let fd = formData(false);
            $.each(fd, function (key, value) { formDataObj.append(key, value); });
        },
        success: function (file, response) {
            const status = typeof response === 'object' && response !== null && 'success' in response && response.success === false
                ? 'error' : 'success';
            setStatus({ type: dropZoneMode, status: status });
            if (dropZoneMode === 'preview') updatePreview(response);
            file.status = Dropzone.QUEUED;
        },
        accept: function (file, done) {
            done();
            preview();
        },
        removedfile: function (file) {
            file.previewElement.remove();
            preview();
            updatePreview('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=');
        }
    });
});

// init2 is defined in main.js (loaded after this file) and called once barcodes are fetched
