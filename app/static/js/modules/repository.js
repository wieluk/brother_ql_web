// repository.js — label repository CRUD operations

function openRepositoryModal() {
    const modalEl = document.getElementById('repoModal');
    if (!modalEl) return;
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
    loadRepositoryList();
}

function loadRepositoryList() {
    const body = $('#repoListBody');
    body.html('<p class="text-muted">Loading...</p>');
    fetch(url_for_repo_list)
        .then(r => r.json())
        .then(data => { renderRepoList(data.files || []); })
        .catch(e => {
            body.html('<div class="text-danger">Failed to load repository list.</div>');
            console.error(e);
        });
}

function renderRepoList(files) {
    const body = $('#repoListBody');
    if (!files || files.length === 0) {
        body.html('<p class="text-muted">No labels in repository.</p>');
        return;
    }
    const table = $('<div class="list-group"></div>');
    files.forEach(f => {
        const item = $(`
            <div class="list-group-item d-flex justify-content-between align-items-center">
                <div class="d-flex gap-3 align-items-center">
                    <img class="repo-thumb" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAAAQCAYAAAB49c9kAAAAE0lEQVR42mNgGAWjYBSMglEwCQAAP1gF8bQqT9kAAAAASUVORK5CYII=" />
                    <div>
                        <strong class="repo-name">${f.name}</strong><br/>
                        <small class="text-muted">${new Date(f.mtime * 1000).toLocaleString()} — ${f.size} bytes</small><br/>
                        <small class="text-muted">Label size: ${f.label_size ? f.label_size : 'unknown'}</small>
                    </div>
                </div>
                <div class="btn-group">
                    <button class="btn btn-sm btn-outline-success repo-load" data-name="${f.name}">Load</button>
                    <button class="btn btn-sm btn-outline-primary repo-print" data-name="${f.name}">Print</button>
                    <button class="btn btn-sm btn-outline-danger repo-delete" data-name="${f.name}">Delete</button>
                </div>
            </div>`);
        table.append(item);
        const img = item.find('.repo-thumb')[0];
        if (img) repoFetchThumbnail(f.name, img);
    });
    body.html(table);

    $('.repo-load').off('click').on('click', function () { repoLoad($(this).data('name')); });
    $('.repo-delete').off('click').on('click', function () {
        const name = $(this).data('name');
        if (!confirm('Delete ' + name + '?')) return;
        repoDelete(name);
    });
    $('.repo-print').off('click').on('click', function () { repoPrint($(this).data('name')); });
}

function repoSaveCurrent() {
    const name = $('#repoSaveName').val();
    if (!name) { alert('Please provide a name to save.'); return; }
    try { saveAllSettingsToLocalStorage(); } catch (e) { }
    let payload = {};
    try { payload = JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch (e) { payload = {}; }
    payload['name'] = name;

    function sendJsonPayload(p) {
        fetch(url_for_repo_save, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(p)
        }).then(r => r.json())
            .then(resp => {
                if (resp && (resp.success || resp.name)) {
                    try { $('#repoSaveName').val(''); } catch (e) { }
                    loadRepositoryList();
                } else {
                    alert('Save failed: ' + (resp && resp.message ? resp.message : 'Unknown'));
                }
            }).catch(e => { console.error(e); alert('Save failed'); });
    }

    try {
        if (imageDropZone && imageDropZone.files && imageDropZone.files.length > 0) {
            const f = imageDropZone.files[0];
            const reader = new FileReader();
            reader.onload = function (e) {
                try {
                    const dataUrl = e.target.result;
                    const parsed = parseDataUrl(dataUrl);
                    if (parsed.b64) {
                        payload['image_data'] = parsed.b64;
                        payload['image_mime'] = parsed.mime;
                        payload['image_name'] = f.name || 'image';
                    }
                } catch (err) {
                    console.warn('Failed to extract base64 from FileReader result', err);
                }
                sendJsonPayload(payload);
            };
            reader.onerror = function () { sendJsonPayload(payload); };
            reader.readAsDataURL(f);
            return;
        }
    } catch (e) { console.warn('No image to attach to repo save', e); }

    sendJsonPayload(payload);
}

function repoLoad(name) {
    fetch(url_for_repo_load + '?name=' + encodeURIComponent(name))
        .then(r => { if (!r.ok) throw new Error('Load failed'); return r.json(); })
        .then(data => {
            try {
                data['fontSettingsPerLine'] = data['text'] || '[]';
                localStorage.setItem(LS_KEY, JSON.stringify(data));
            } catch (e) { }
            restoreAllSettingsFromLocalStorage();
            try {
                const img_b64 = data.image_data;
                const img_mime = data.image_mime || 'image/png';
                const img_name = data.image_name || data.image || 'image';
                if (img_b64) {
                    const dataUrl = 'data:' + img_mime + ';base64,' + img_b64;
                    fetch(dataUrl)
                        .then(res => res.blob())
                        .then(blob => {
                            const file = new File([blob], img_name, { type: img_mime });
                            try { imageDropZone.removeAllFiles(true); } catch (e) { }
                            try { imageDropZone.addFile(file); } catch (e) {
                                console.warn('Failed to populate Dropzone with repository image', e);
                            }
                            preview();
                        }).catch(e => console.warn('Failed to load image blob', e));
                }
            } catch (e) { console.warn(e); }
            const modalEl = document.getElementById('repoModal');
            bootstrap.Modal.getInstance(modalEl).hide();
        }).catch(e => { console.error(e); alert('Failed to load label'); });
}

function repoDelete(name) {
    fetch(url_for_repo_delete + '?name=' + encodeURIComponent(name), { method: 'POST' })
        .then(r => r.json())
        .then(resp => {
            if (resp && resp.success) {
                loadRepositoryList();
            } else {
                alert('Delete failed: ' + (resp && resp.message ? resp.message : 'Unknown'));
            }
        }).catch(e => { console.error(e); alert('Delete failed'); });
}

function repoPrint(name) {
    const printerSelect = document.getElementById('printer');
    const body = new URLSearchParams();
    body.append('name', name);
    if (printerSelect && printerSelect.value) body.append('printer', printerSelect.value);
    const modelVal = (() => {
        if (printerSelect && printerSelect.value && window.available_printers) {
            const p = window.available_printers.find(p => p.path === printerSelect.value);
            if (p && p.model && p.model !== 'Unknown') return p.model;
        }
        if (printer_status && printer_status.model && printer_status.model !== 'Unknown') {
            return printer_status.model;
        }
        return null;
    })();
    if (modelVal) body.append('model', modelVal);

    fetch(url_for_repo_print, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
        body: body
    }).then(r => r.json())
        .then(resp => {
            if (resp && resp.success) {
                setStatus({ type: 'printing', status: 'success' });
            } else {
                const msg = resp && resp.message ? resp.message : 'Print failed';
                setStatus({ type: 'printing', status: 'error', message: msg });
                console.error(msg);
            }
        }).catch(e => { console.error(e); console.error('Print failed'); });
}

function repoFetchThumbnail(name, imgEl) {
    const printerSelect = document.getElementById('printer');
    const printer = printerSelect && printerSelect.value ? printerSelect.value : null;
    let url = url_for_repo_preview + '?name=' + encodeURIComponent(name) + '&return_format=base64';
    if (printer) url += '&printer=' + encodeURIComponent(printer);
    fetch(url)
        .then(r => { if (!r.ok) throw new Error('Preview fetch failed'); return r.text(); })
        .then(b64 => { imgEl.src = 'data:image/png;base64,' + b64; })
        .catch(e => { console.debug('Thumbnail fetch failed for', name, e); imgEl.style.opacity = 0.4; });
}

// Wire modal buttons once DOM is ready
$(document).ready(function () {
    $('#openRepoBtn').off('click').on('click', openRepositoryModal);
    $('#repoSaveBtn').off('click').on('click', repoSaveCurrent);
});
