// font-settings.js — per-line font settings management

const DEFAULT_FONT = 'Droid Serif,Regular';
const SHIPPING_LINE_NAMES = ['Sender section', 'Recipient section'];

// Global array: one entry per label text line, each holds font properties
var fontSettingsPerLine = [];
window.fontSettingsPerLine = fontSettingsPerLine;

// ---------------------------------------------------------------------------
// Core logic
// ---------------------------------------------------------------------------

function setFontSettingsPerLine() {
    var currentFont = {
        font: $('#font option:selected').val() || DEFAULT_FONT,
        size: $('#font_size').val(),
        inverted: $('#font_inverted').is(':checked'),
        checkbox: $('#font_checkbox').is(':checked'),
        align: $('input[name=font_align]:checked').val() || 'center',
        line_spacing: $('input[name=line_spacing]:checked').val() || '100',
        color: $('input[name=print_color]:checked').val() || 'black'
    };

    const printType = $('input[name=print_type]:checked').val();
    if (printType === 'shipping') {
        _setShippingFontSettings(currentFont);
        return;
    }

    var text = $('#label_text').val() || '';
    var lines = text.split(/\r?\n/);
    if (lines.length === 0) lines = [''];

    var lineSelect = $('#lineSelect');
    var selectedLine = lineSelect.val();
    lineSelect.empty();
    $.each(lines, function (index, line) {
        lineSelect.append($('<option></option>')
            .attr('value', index).text(lines[index] || '(line ' + (index + 1) + ' is empty)'));
    });
    if (selectedLine !== null) {
        lineSelect.val(selectedLine);
    } else {
        lineSelect.val(0);
    }

    const isSynced = $('#sync_font_settings').is(':checked');
    if (isSynced) {
        fontSettingsPerLine = [];
        for (var i = 0; i < lines.length; i++) {
            fontSettingsPerLine[i] = Object.assign({}, currentFont);
            fontSettingsPerLine[i]['text'] = lines[i];
        }
        window.fontSettingsPerLine = fontSettingsPerLine;
        return;
    }

    if (fontSettingsPerLine.length < lines.length) {
        for (var i = fontSettingsPerLine.length; i < lines.length; i++) {
            if (i === selectedLine || selectedLine === null) {
                fontSettingsPerLine.push(Object.assign({}, currentFont));
            } else {
                fontSettingsPerLine.push(Object.assign({}, fontSettingsPerLine[i - 1]));
            }
        }
    }
    while (fontSettingsPerLine.length > lines.length) {
        fontSettingsPerLine.pop();
    }
    if (fontSettingsPerLine[selectedLine]) {
        fontSettingsPerLine[selectedLine] = Object.assign({}, currentFont);
    }
    for (var i = 0; i < lines.length; i++) {
        fontSettingsPerLine[i]['text'] = lines[i];
    }
    window.fontSettingsPerLine = fontSettingsPerLine;
}

function _setShippingFontSettings(currentFont) {
    var lineSelect = $('#lineSelect');
    var selectedLine = parseInt(lineSelect.val()) || 0;
    if (selectedLine >= SHIPPING_LINE_NAMES.length) selectedLine = 0;

    lineSelect.empty();
    SHIPPING_LINE_NAMES.forEach(function (name, idx) {
        lineSelect.append($('<option></option>').attr('value', idx).text(name));
    });
    lineSelect.val(selectedLine);

    while (fontSettingsPerLine.length < SHIPPING_LINE_NAMES.length) {
        var prev = fontSettingsPerLine.length > 0
            ? fontSettingsPerLine[fontSettingsPerLine.length - 1]
            : Object.assign({}, currentFont);
        fontSettingsPerLine.push(Object.assign({}, prev));
    }
    fontSettingsPerLine = fontSettingsPerLine.slice(0, SHIPPING_LINE_NAMES.length);

    const isSynced = $('#sync_font_settings').is(':checked');
    if (isSynced) {
        SHIPPING_LINE_NAMES.forEach(function (_, idx) {
            fontSettingsPerLine[idx] = Object.assign({}, currentFont);
        });
    } else {
        fontSettingsPerLine[selectedLine] = Object.assign({}, currentFont);
    }
    SHIPPING_LINE_NAMES.forEach(function (name, idx) {
        fontSettingsPerLine[idx]['text'] = name;
    });
    window.fontSettingsPerLine = fontSettingsPerLine;
}

// ---------------------------------------------------------------------------
// UI sync — update font controls when a line is selected
// ---------------------------------------------------------------------------

$(document).ready(function () {
    $('#lineSelect').on('change', function () {
        var idx = parseInt($(this).val(), 10);
        if (isNaN(idx) || !fontSettingsPerLine || !fontSettingsPerLine[idx]) return;
        var fs = fontSettingsPerLine[idx];
        $('#font').val(fs.font || DEFAULT_FONT);
        $('#font_size').val(fs.size);
        $('input[name=font_align]').prop('checked', false);
        $('input[name=font_align][value="' + fs.align + '"]').prop('checked', true).trigger('change');
        $('input[name=line_spacing]').prop('checked', false);
        $('input[name=line_spacing][value="' + fs.line_spacing + '"]').prop('checked', true).trigger('change');
        $('#font_inverted').prop('checked', fs.inverted);
        $('input[name=print_color]').prop('checked', false);
        $('input[name=print_color][value="' + fs.color + '"]').prop('checked', true).trigger('change');
        $('#font_checkbox').prop('checked', fs.checkbox);
    });

    // Sync line selector with textarea caret position
    $('#label_text').on('click keyup', function () {
        var textarea = this;
        var caret = textarea.selectionStart;
        var lines = textarea.value.split(/\r?\n/);
        var charCount = 0;
        var lineIdx = 0;
        for (var i = 0; i < lines.length; i++) {
            var nextCount = charCount + (lines[i] ? lines[i].length : 0) + 1;
            if (caret < nextCount) { lineIdx = i; break; }
            charCount = nextCount;
        }
        $('#lineSelect').val(lineIdx).trigger('change');
    });
});
