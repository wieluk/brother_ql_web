// storage.js — localStorage, undo history, IndexedDB image cache, and diff utilities

const LS_KEY = 'labeldesigner_settings_v1';
const LS_HISTORY_KEY = 'labeldesigner_settings_history_v1';
const MAX_HISTORY = 40;

var current_restoring = false;

// ---------------------------------------------------------------------------
// Data URL helpers
// ---------------------------------------------------------------------------

function parseDataUrl(dataUrl) {
    const comma = dataUrl.indexOf(',');
    if (comma === -1) return { mime: null, b64: null };
    const header = dataUrl.substring(5, comma);
    const mime = header.split(';')[0];
    const b64 = dataUrl.substring(comma + 1);
    return { mime, b64 };
}

// FNV-1a 64-bit hash (via BigInt) — used to deduplicate images in IndexedDB
const generateHash = (string) => {
    const FNV_OFFSET_BASIS = 14695981039346656037n;
    const FNV_PRIME = 1099511628211n;
    let hash = FNV_OFFSET_BASIS;
    for (let i = 0; i < string.length; i++) {
        hash ^= BigInt(string.charCodeAt(i));
        hash *= FNV_PRIME;
        hash &= (1n << 64n) - 1n;
    }
    return hash.toString(36);
};

// ---------------------------------------------------------------------------
// IndexedDB helpers
// ---------------------------------------------------------------------------

function _openImageDB() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('brother_ql_images', 1);
        req.onupgradeneeded = (e) => {
            const db = e.target.result;
            if (!db.objectStoreNames.contains('images')) db.createObjectStore('images');
        };
        req.onsuccess = (e) => resolve(e.target.result);
        req.onerror = (e) => reject(e.target.error);
    });
}

function _saveImageToDB(id, mime, b64) {
    return _openImageDB().then(db => new Promise((resolve, reject) => {
        const tx = db.transaction('images', 'readwrite');
        const store = tx.objectStore('images');
        const req = store.add({ mime, b64 }, id);
        req.onsuccess = () => { db.close(); resolve(true); };
        req.onerror = (e) => {
            const err = e && e.target && e.target.error;
            if (err && err.name === 'ConstraintError') {
                db.close(); resolve(false);
            } else {
                db.close(); reject(err);
            }
        };
    })).catch(() => null);
}

function _getImageFromDB(id) {
    return _openImageDB().then(db => new Promise((resolve, reject) => {
        const tx = db.transaction('images', 'readonly');
        const store = tx.objectStore('images');
        const req = store.get(id);
        req.onsuccess = (e) => { db.close(); resolve(e.target.result || null); };
        req.onerror = (e) => { db.close(); reject(e.target.error); };
    })).catch(() => null);
}

// ---------------------------------------------------------------------------
// Settings persistence
// ---------------------------------------------------------------------------

function saveAllSettingsToLocalStorage() {
    const data = {};
    $('input, select, textarea').each(function () {
        if (this.id === 'lineSelect') return;
        const key = this.type === 'radio' && this.name.length > 0 ? this.name : this.id;
        if (key.length === 0) return;
        if (this.type === 'checkbox') {
            data[key] = $(this).is(':checked');
        } else if (this.type === 'radio') {
            if ($(this).is(':checked') || $(this).parent().hasClass('active')) {
                data[key] = $(this).val();
            }
        } else {
            data[key] = $(this).val();
        }
    });
    if (window.fontSettingsPerLine) {
        data['fontSettingsPerLine'] = JSON.stringify(window.fontSettingsPerLine);
    }
    try {
        if (imageDropZone && imageDropZone.files && imageDropZone.files.length > 0) {
            const f = imageDropZone.files[0];
            const dataUrl = imageDropZone.files[0].dataURL;
            const parsed = parseDataUrl(dataUrl);
            if (parsed.b64) {
                const imageHash = generateHash(parsed.b64);
                _saveImageToDB(imageHash, parsed.mime, parsed.b64).catch(e => console.debug('Failed saving image to IndexedDB', e));
                data['image_ref'] = imageHash;
                data['image_mime'] = parsed.mime;
                data['image_name'] = f.name || 'image';
            }
        }
    } catch (e) {
        console.debug('No image to save to localStorage', e);
    }
    const this_settings = JSON.stringify(data);
    localStorage.setItem(LS_KEY, this_settings);

    let history = [];
    try {
        history = JSON.parse(localStorage.getItem(LS_HISTORY_KEY)) || [];
    } catch { history = []; }
    if (history.length === 0 || JSON.stringify(history[history.length - 1]) !== this_settings) {
        console.debug(compareObjects(history[history.length - 1], data));
        history.push(data);
        if (history.length > MAX_HISTORY) history = history.slice(history.length - MAX_HISTORY);
        localStorage.setItem(LS_HISTORY_KEY, JSON.stringify(history));
    }
    updateUndoButton();
}

function restoreAllSettingsFromLocalStorage() {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return;
    let data;
    try { data = JSON.parse(raw); } catch { return; }
    current_restoring = true;
    $('input, select, textarea').each(function () {
        const key = this.type === 'radio' && this.name.length > 0 ? this.name : this.id;
        if (!(key in data)) return;
        if (this.type === 'checkbox') {
            $(this).prop('checked', !!data[key]);
        } else if (this.type === 'radio') {
            if ($(this).val() == data[key]) {
                this.checked = true;
                $(`label[for="${this.id}"]`).addClass('active');
            } else {
                this.checked = false;
                $(`label[for="${this.id}"]`).removeClass('active');
            }
        } else {
            this.value = data[key];
            console.log(key + ': ' + data[key]);
        }
    });
    if (data['fontSettingsPerLine'] && window.fontSettingsPerLine !== undefined) {
        try {
            window.fontSettingsPerLine = JSON.parse(data['fontSettingsPerLine']);
            console.log(window.fontSettingsPerLine);
            $('#lineSelect').val(0);
            preview();
        } catch { }
    }
    let imageRestorePromise = Promise.resolve();
    try {
        if (data.image_ref) {
            imageRestorePromise = _getImageFromDB(data.image_ref).then(record => {
                if (record && record.b64) {
                    const dataUrl = 'data:' + (record.mime || 'image/png') + ';base64,' + record.b64;
                    return fetch(dataUrl)
                        .then(res => res.blob())
                        .then(blob => {
                            const file = new File([blob], data.image_name || 'image', { type: record.mime || 'image/png' });
                            try { imageDropZone.removeAllFiles(true); } catch (e) { }
                            try { imageDropZone.addFile(file); } catch (e) { }
                        }).catch(e => console.debug('Failed to fetch blob from IndexedDB dataUrl', e));
                }
            }).catch(e => console.debug('Failed to read image from IndexedDB', e));
        }
    } catch (e) {
        console.debug('No image to restore from storage', e);
    }
    imageRestorePromise.finally(() => {
        preview();
        current_restoring = false;
    });
}

function undoSettings() {
    let history = [];
    try {
        history = JSON.parse(localStorage.getItem(LS_HISTORY_KEY)) || [];
    } catch { history = []; }
    if (history.length < 2) return;
    console.debug(compareObjects(history[history.length - 1], history[history.length - 2]));
    history.pop();
    const prev = history[history.length - 1];
    localStorage.setItem(LS_HISTORY_KEY, JSON.stringify(history));
    localStorage.setItem(LS_KEY, JSON.stringify(prev));
    restoreAllSettingsFromLocalStorage();
    updateUndoButton();
}

function updateUndoButton() {
    let history = [];
    try {
        history = JSON.parse(localStorage.getItem(LS_HISTORY_KEY)) || [];
    } catch { history = []; }
    const steps = Math.max(0, history.length - 1);
    $('#undoCounter').text(steps);
    $('#undoSettingsBtn').prop('disabled', steps === 0);
}

// ---------------------------------------------------------------------------
// Diff utilities (used for debug logging in history)
// ---------------------------------------------------------------------------

function flattenObject(obj) {
    if (obj === undefined) return {};
    const object = Object.create(null);
    const path = [];
    const isObject = (value) => Object(value) === value;
    function dig(obj) {
        for (let [key, value] of Object.entries(obj)) {
            if (typeof value === 'string' &&
                ((value.startsWith('{') && value.endsWith('}')) ||
                 (value.startsWith('[') && value.endsWith(']')))) {
                try { value = JSON.parse(value); } catch (e) { }
            }
            path.push(key);
            if (isObject(value)) dig(value);
            else object[path.join('.')] = value;
            path.pop();
        }
    }
    dig(obj);
    return object;
}

function diffFlatten(before, after) {
    const added = Object.assign({}, after);
    const changed = Object.assign({}, after);
    const removed = Object.assign({}, before);
    for (let key in after) {
        if (after[key] === before[key]) {
            delete added[key]; delete changed[key]; delete removed[key];
        } else if (key in before) {
            delete added[key];
            changed[key] = { from: before[key], to: after[key] };
            delete removed[key];
        } else {
            delete changed[key]; delete removed[key];
        }
    }
    return [added, changed, removed];
}

function compareObjects(before, after) {
    const [added, changed, removed] = diffFlatten(flattenObject(before), flattenObject(after));
    return { added, changed, removed };
}
