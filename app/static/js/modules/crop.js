// crop.js — visual crop tool (renders inside a Bootstrap modal)

var cropTool = (function () {
    'use strict';

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    var _originalFile = null;
    var _sourceImage  = null;   // HTMLImageElement or HTMLCanvasElement
    var _scale        = 1;      // canvas-px / source-px
    var _sel          = { x: 0, y: 0, w: 0, h: 0 };
    var _drag         = { active: false, mode: null,
                          startMX: 0, startMY: 0,
                          startX: 0, startY: 0, startW: 0, startH: 0 };
    var _cropApplied  = false;
    var _addingResult = false;  // true while we are programmatically swapping the dropzone file
    var _modalReady   = false;  // one-time hidden.bs.modal listener attached
    var HANDLE = 10;

    // -----------------------------------------------------------------------
    // DOM / source helpers
    // -----------------------------------------------------------------------
    function el(id) { return document.getElementById(id); }
    function srcW(s) { return s.naturalWidth  || s.width;  }
    function srcH(s) { return s.naturalHeight || s.height; }

    // -----------------------------------------------------------------------
    // Geometry
    // -----------------------------------------------------------------------
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    function normSel() {
        var s = _sel;
        return {
            x: s.w >= 0 ? s.x : s.x + s.w,
            y: s.h >= 0 ? s.y : s.y + s.h,
            w: Math.abs(s.w),
            h: Math.abs(s.h)
        };
    }

    function hitMode(mx, my) {
        var s = normSel();
        var corners = [
            { name: 'tl', x: s.x,       y: s.y       },
            { name: 'tr', x: s.x + s.w, y: s.y       },
            { name: 'bl', x: s.x,       y: s.y + s.h },
            { name: 'br', x: s.x + s.w, y: s.y + s.h },
        ];
        for (var i = 0; i < corners.length; i++) {
            var c = corners[i];
            if (Math.abs(mx - c.x) <= HANDLE && Math.abs(my - c.y) <= HANDLE)
                return 'resize-' + c.name;
        }
        if (mx >= s.x && mx <= s.x + s.w && my >= s.y && my <= s.y + s.h)
            return 'move';
        return 'new';
    }

    function getMousePos(e) {
        var canvas = el('cropCanvas');
        var rect   = canvas.getBoundingClientRect();
        var sx = canvas.width  / rect.width;
        var sy = canvas.height / rect.height;
        var clientX = e.touches ? e.touches[0].clientX : e.clientX;
        var clientY = e.touches ? e.touches[0].clientY : e.clientY;
        return { x: (clientX - rect.left) * sx, y: (clientY - rect.top) * sy };
    }

    // -----------------------------------------------------------------------
    // Drawing
    // -----------------------------------------------------------------------
    function draw() {
        var canvas = el('cropCanvas');
        if (!canvas || !_sourceImage) return;
        var ctx = canvas.getContext('2d');
        var s   = normSel();

        ctx.drawImage(_sourceImage, 0, 0, canvas.width, canvas.height);

        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        if (s.w > 1 && s.h > 1) {
            ctx.drawImage(
                _sourceImage,
                s.x / _scale, s.y / _scale, s.w / _scale, s.h / _scale,
                s.x, s.y, s.w, s.h
            );

            ctx.save();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth   = 1.5;
            ctx.setLineDash([5, 3]);
            ctx.strokeRect(s.x + 0.5, s.y + 0.5, s.w - 1, s.h - 1);
            ctx.restore();

            // Rule-of-thirds grid
            ctx.save();
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth   = 0.5;
            ctx.beginPath();
            for (var t = 1; t <= 2; t++) {
                var gx = s.x + s.w * t / 3;
                var gy = s.y + s.h * t / 3;
                ctx.moveTo(gx, s.y); ctx.lineTo(gx, s.y + s.h);
                ctx.moveTo(s.x, gy); ctx.lineTo(s.x + s.w, gy);
            }
            ctx.stroke();
            ctx.restore();

            // Corner handles
            [[s.x, s.y], [s.x + s.w, s.y], [s.x, s.y + s.h], [s.x + s.w, s.y + s.h]]
                .forEach(function (pt) {
                    ctx.fillStyle   = '#fff';
                    ctx.strokeStyle = '#444';
                    ctx.lineWidth   = 1;
                    ctx.fillRect  (pt[0] - HANDLE/2, pt[1] - HANDLE/2, HANDLE, HANDLE);
                    ctx.strokeRect(pt[0] - HANDLE/2, pt[1] - HANDLE/2, HANDLE, HANDLE);
                });
        }
    }

    // -----------------------------------------------------------------------
    // Mouse / touch
    // -----------------------------------------------------------------------
    function onDown(e) {
        e.preventDefault();
        var pos  = getMousePos(e);
        var mode = hitMode(pos.x, pos.y);
        var s    = normSel();
        _drag = { active: true, mode: mode,
                  startMX: pos.x, startMY: pos.y,
                  startX: s.x, startY: s.y, startW: s.w, startH: s.h };
        if (mode === 'new') _sel = { x: pos.x, y: pos.y, w: 0, h: 0 };
    }

    function onMove(e) {
        if (!_drag.active) return;
        e.preventDefault();
        var canvas = el('cropCanvas');
        var W = canvas.width, H = canvas.height;
        var pos = getMousePos(e);
        var dx  = pos.x - _drag.startMX;
        var dy  = pos.y - _drag.startMY;
        var d   = _drag;

        if (d.mode === 'new') {
            _sel.w = clamp(pos.x, 0, W) - _sel.x;
            _sel.h = clamp(pos.y, 0, H) - _sel.y;
        } else if (d.mode === 'move') {
            _sel.x = clamp(d.startX + dx, 0, W - d.startW);
            _sel.y = clamp(d.startY + dy, 0, H - d.startH);
            _sel.w = d.startW; _sel.h = d.startH;
        } else if (d.mode === 'resize-br') {
            _sel.x = d.startX; _sel.y = d.startY;
            _sel.w = clamp(d.startW + dx, 10, W - d.startX);
            _sel.h = clamp(d.startH + dy, 10, H - d.startY);
        } else if (d.mode === 'resize-tl') {
            var nx = clamp(d.startX + dx, 0, d.startX + d.startW - 10);
            var ny = clamp(d.startY + dy, 0, d.startY + d.startH - 10);
            _sel.w = d.startX + d.startW - nx; _sel.h = d.startY + d.startH - ny;
            _sel.x = nx; _sel.y = ny;
        } else if (d.mode === 'resize-tr') {
            var ny2 = clamp(d.startY + dy, 0, d.startY + d.startH - 10);
            _sel.x = d.startX;
            _sel.w = clamp(d.startW + dx, 10, W - d.startX);
            _sel.h = d.startY + d.startH - ny2; _sel.y = ny2;
        } else if (d.mode === 'resize-bl') {
            var nx2 = clamp(d.startX + dx, 0, d.startX + d.startW - 10);
            _sel.y = d.startY;
            _sel.w = d.startX + d.startW - nx2;
            _sel.h = clamp(d.startH + dy, 10, H - d.startY);
            _sel.x = nx2;
        }
        draw();
    }

    function onUp() {
        if (!_drag.active) return;
        _drag.active = false;
        var s = normSel();
        _sel = { x: s.x, y: s.y, w: s.w, h: s.h };
        draw();
    }

    function attachCanvasEvents() {
        var c = el('cropCanvas');
        if (!c) return;
        c.addEventListener('mousedown',  onDown);
        c.addEventListener('mousemove',  onMove);
        c.addEventListener('mouseup',    onUp);
        c.addEventListener('mouseleave', onUp);
        c.addEventListener('touchstart', onDown, { passive: false });
        c.addEventListener('touchmove',  onMove, { passive: false });
        c.addEventListener('touchend',   onUp);
    }

    function detachCanvasEvents() {
        var c = el('cropCanvas');
        if (!c) return;
        c.removeEventListener('mousedown',  onDown);
        c.removeEventListener('mousemove',  onMove);
        c.removeEventListener('mouseup',    onUp);
        c.removeEventListener('mouseleave', onUp);
        c.removeEventListener('touchstart', onDown);
        c.removeEventListener('touchmove',  onMove);
        c.removeEventListener('touchend',   onUp);
    }

    // -----------------------------------------------------------------------
    // PDF rendering via PDF.js
    // -----------------------------------------------------------------------
    function renderPDFToCanvas(arrayBuffer, onDone, onError) {
        if (typeof pdfjsLib === 'undefined') { onError('PDF.js not loaded'); return; }
        pdfjsLib.GlobalWorkerOptions.workerSrc =
            'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

        pdfjsLib.getDocument({ data: arrayBuffer }).promise.then(function (pdf) {
            var n = pdf.numPages, scale = 2.0;
            var pages = new Array(n);
            var pending = n;

            function renderPage(i) {
                pdf.getPage(i).then(function (page) {
                    var vp  = page.getViewport({ scale: scale });
                    var pc  = document.createElement('canvas');
                    pc.width  = Math.round(vp.width);
                    pc.height = Math.round(vp.height);
                    page.render({ canvasContext: pc.getContext('2d'), viewport: vp })
                        .promise.then(function () {
                            pages[i - 1] = pc;
                            if (--pending === 0) {
                                var totalH = pages.reduce(function (s, c) { return s + c.height; }, 0);
                                var maxW   = pages.reduce(function (s, c) { return Math.max(s, c.width); }, 0);
                                var out = document.createElement('canvas');
                                out.width = maxW; out.height = totalH;
                                var ctx = out.getContext('2d'), y = 0;
                                pages.forEach(function (c) { ctx.drawImage(c, 0, y); y += c.height; });
                                onDone(out);
                            }
                        });
                });
            }
            for (var i = 1; i <= n; i++) renderPage(i);
        }, onError);
    }

    // -----------------------------------------------------------------------
    // Modal open / close
    // -----------------------------------------------------------------------
    function _ensureModalListener() {
        if (_modalReady) return;
        _modalReady = true;
        var modalEl = el('cropModal');
        if (!modalEl) return;
        // Always detach canvas events when modal fully closes (any trigger)
        modalEl.addEventListener('hidden.bs.modal', function () {
            detachCanvasEvents();
        });
    }

    function open() {
        if (!_sourceImage) return;
        _ensureModalListener();
        var modalEl = el('cropModal');
        if (!modalEl) return;

        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);

        // Size canvas once the modal is fully visible and has a real layout
        modalEl.addEventListener('shown.bs.modal', function () {
            var body  = el('cropModalBody');
            var maxW  = Math.max(300, body.clientWidth - 4);
            // Also fit vertically so the full image is visible without scrolling
            var maxH  = Math.round(window.innerHeight * 0.72);
            _scale = Math.min(1, maxW / srcW(_sourceImage), maxH / srcH(_sourceImage));

            var canvas    = el('cropCanvas');
            canvas.width  = Math.round(srcW(_sourceImage) * _scale);
            canvas.height = Math.round(srcH(_sourceImage) * _scale);

            _sel  = { x: 0, y: 0, w: canvas.width, h: canvas.height };
            _drag = { active: false };
            attachCanvasEvents();
            draw();
        }, { once: true });

        modal.show();
    }

    function close() {
        var modalEl = el('cropModal');
        if (modalEl) {
            var m = bootstrap.Modal.getInstance(modalEl);
            if (m) { m.hide(); return; }
        }
        detachCanvasEvents();
    }

    // -----------------------------------------------------------------------
    // Apply / reset
    // -----------------------------------------------------------------------
    function applyTool() {
        if (!_sourceImage) return;
        var s  = normSel();
        var ox = Math.round(s.x / _scale);
        var oy = Math.round(s.y / _scale);
        var ow = Math.max(1, Math.round(s.w / _scale));
        var oh = Math.max(1, Math.round(s.h / _scale));

        var out = document.createElement('canvas');
        out.width = ow; out.height = oh;
        out.getContext('2d').drawImage(_sourceImage, ox, oy, ow, oh, 0, 0, ow, oh);

        out.toBlob(function (blob) {
            var cropped = new File([blob], 'cropped.png', { type: 'image/png' });
            _cropApplied  = true;
            _addingResult = true;
            close();
            try { imageDropZone.removeAllFiles(true); } catch (e) {}
            try { imageDropZone.addFile(cropped); }    catch (e) {}
            var rb = el('resetCropBtn');
            if (rb) rb.style.display = '';
        }, 'image/png');
    }

    function resetCrop() {
        if (!_originalFile) return;
        _cropApplied  = false;
        _addingResult = true;
        close();
        try { imageDropZone.removeAllFiles(true); } catch (e) {}
        try { imageDropZone.addFile(_originalFile); } catch (e) {}
        var rb = el('resetCropBtn');
        if (rb) rb.style.display = 'none';
    }

    // -----------------------------------------------------------------------
    // Dropzone hooks
    // -----------------------------------------------------------------------
    function onFileAdded(file) {
        if (_addingResult) {
            _addingResult = false;
            var panel = el('cropPanel');
            if (panel) panel.style.display = '';
            return;
        }

        _originalFile = file;
        _cropApplied  = false;

        var rb = el('resetCropBtn');
        if (rb) rb.style.display = 'none';

        var loading = el('cropLoadingNote');
        var tools   = el('cropImageTools');
        var isPDF   = (file.name || '').toLowerCase().endsWith('.pdf')
                      || file.type === 'application/pdf';

        if (isPDF) {
            if (loading) loading.style.display = '';
            if (tools)   tools.style.display   = 'none';

            var reader = new FileReader();
            reader.onload = function (ev) {
                renderPDFToCanvas(ev.target.result, function (canvas) {
                    _sourceImage = canvas;
                    if (loading) loading.style.display = 'none';
                    if (tools)   tools.style.display   = '';
                }, function () {
                    if (loading) loading.style.display = 'none';
                });
            };
            reader.readAsArrayBuffer(file);
        } else {
            if (loading) loading.style.display = 'none';
            if (tools)   tools.style.display   = '';

            var reader2 = new FileReader();
            reader2.onload = function (ev) {
                var img = new Image();
                img.onload = function () { _sourceImage = img; };
                img.src = ev.target.result;
            };
            reader2.readAsDataURL(file);
        }

        var panel = el('cropPanel');
        if (panel) panel.style.display = '';
    }

    function onFileRemoved() {
        if (_addingResult) return;
        _originalFile = null;
        _sourceImage  = null;
        _cropApplied  = false;
        var panel = el('cropPanel');
        if (panel) panel.style.display = 'none';
        var rb = el('resetCropBtn');
        if (rb) rb.style.display = 'none';
    }

    return {
        open:          open,
        close:         close,
        applyTool:     applyTool,
        resetCrop:     resetCrop,
        onFileAdded:   onFileAdded,
        onFileRemoved: onFileRemoved,
    };
})();
