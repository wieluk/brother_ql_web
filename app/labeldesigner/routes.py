"""HTTP route handlers for the label designer blueprint."""

import base64
import logging
import os

import barcode
from flask import current_app, json, jsonify, make_response, render_template, request
from werkzeug.utils import secure_filename
from brother_ql.labels import ALL_LABELS, FormFactor

from . import bp
from app import FONTS
from app.utils import fill_first_line_fields, image_to_png_bytes
from .printer import PrinterQueue, get_ptr_status, reset_printer_cache
from .services import (
    create_label_from_request,
    create_printer_from_request,
    get_repo_dir,
    load_repo_json,
)

LINE_SPACINGS = (100, 150, 200, 250, 300)
HIGH_RES_DPI = 600


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@bp.errorhandler(ValueError)
def handle_value_error(e):
    return jsonify({"error": str(e)}), 400


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@bp.route('/')
def index():
    label_sizes = [
        (label.identifier, label.name, label.form_factor == FormFactor.ROUND_DIE_CUT, label.tape_size)
        for label in ALL_LABELS
    ]
    return render_template(
        'labeldesigner.html',
        fonts=FONTS.fontlist(),
        label_sizes=label_sizes,
        default_label_size=current_app.config['LABEL_DEFAULT_SIZE'],
        default_font_size=current_app.config['LABEL_DEFAULT_FONT_SIZE'],
        default_orientation=current_app.config['LABEL_DEFAULT_ORIENTATION'],
        default_qr_size=current_app.config['LABEL_DEFAULT_QR_SIZE'],
        default_image_mode=current_app.config['IMAGE_DEFAULT_MODE'],
        default_bw_threshold=current_app.config['IMAGE_DEFAULT_BW_THRESHOLD'],
        default_font_family=FONTS.get_default_font()[0],
        default_font_style=FONTS.get_default_font()[1],
        line_spacings=LINE_SPACINGS,
        default_line_spacing=current_app.config['LABEL_DEFAULT_LINE_SPACING'],
        default_dpi=HIGH_RES_DPI,
        default_margin_top=current_app.config['LABEL_DEFAULT_MARGIN_TOP'],
        default_margin_bottom=current_app.config['LABEL_DEFAULT_MARGIN_BOTTOM'],
        default_margin_left=current_app.config['LABEL_DEFAULT_MARGIN_LEFT'],
        default_margin_right=current_app.config['LABEL_DEFAULT_MARGIN_RIGHT']
    )


# ---------------------------------------------------------------------------
# Preview / print
# ---------------------------------------------------------------------------

def _image_response(im, return_format: str):
    """Return a Flask response with PNG bytes or base64-encoded text."""
    data = image_to_png_bytes(im)
    if return_format == 'base64':
        data = base64.b64encode(data)
        content_type = 'text/plain'
    else:
        content_type = 'image/png'
    resp = make_response(data)
    resp.headers.set('Content-type', content_type)
    return resp


@bp.route('/api/preview', methods=['POST'])
def preview_from_image():
    log_level = request.values.get('log_level')
    if log_level:
        level = getattr(logging, log_level.upper(), None)
        if isinstance(level, int):
            current_app.logger.setLevel(level)
    try:
        values = request.values.to_dict(flat=True)
        files = request.files.to_dict(flat=True)
        label = create_label_from_request(values, files)
        im = label.generate(rotate=True)
    except Exception as e:
        current_app.logger.exception(e)
        error = 413 if "too long" in str(e) else 400
        return make_response(jsonify({'message': str(e)}), error)
    return _image_response(im, request.values.get('return_format', 'png'))


@bp.route('/api/print', methods=['POST', 'GET'])
def print_label():
    return_dict = {'success': False}
    try:
        log_level = request.values.get('log_level')
        if log_level:
            level = getattr(logging, log_level.upper(), None)
            if isinstance(level, int):
                current_app.logger.setLevel(level)
        printer = create_printer_from_request(request.values.to_dict(flat=True))
        print_count = int(request.values.get('print_count', 1))
        if print_count < 1:
            raise ValueError("print_count must be greater than 0")
        cut_once = int(request.values.get('cut_once', 0)) == 1
        high_res = int(request.values.get('high_res', 0)) != 0
    except Exception as e:
        return_dict['message'] = str(e)
        current_app.logger.exception(e)
        return make_response(jsonify(return_dict), 400)

    status = ""
    try:
        for i in range(print_count):
            values = request.values.to_dict(flat=True)
            files = request.files.to_dict(flat=True)
            label = create_label_from_request(values, files, i)
            cut = not cut_once or (cut_once and i == print_count - 1)
            printer.add_label_to_queue(label, cut, high_res)
        status = printer.process_queue()
    except Exception as e:
        return_dict['message'] = str(e)
        current_app.logger.exception(e)
        return make_response(jsonify(return_dict), 400)

    return_dict['success'] = len(status) == 0
    if len(status) > 0:
        return_dict['message'] = status
        return make_response(jsonify(return_dict), 400)
    return return_dict


# ---------------------------------------------------------------------------
# Printer status
# ---------------------------------------------------------------------------

@bp.route('/api/barcodes', methods=['GET'])
def get_barcodes():
    barcodes = [code.upper() for code in barcode.PROVIDED_BARCODES]
    for pin in ('QR', 'CODE128'):
        if pin in barcodes:
            barcodes.remove(pin)
        barcodes.insert(0, pin)
    return {'barcodes': barcodes}


@bp.route('/api/printer_status', methods=['GET'])
def get_printer_status():
    return get_ptr_status(current_app.config)


@bp.route('/api/printer_rescan', methods=['POST'])
def rescan_printers():
    reset_printer_cache()
    return get_ptr_status(current_app.config)


# ---------------------------------------------------------------------------
# Label repository
# ---------------------------------------------------------------------------

@bp.route('/api/repository/list', methods=['GET'])
def repo_list():
    repo = get_repo_dir()
    files = []
    for name in sorted(os.listdir(repo)):
        if not name.lower().endswith('.json'):
            continue
        path = os.path.join(repo, name)
        stat = os.stat(path)
        entry = {'name': name, 'mtime': int(stat.st_mtime), 'size': stat.st_size}
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        label_size = data.get('label_size') or data.get('labelSize')
        if label_size:
            label_size_human = next(
                (label.name for label in ALL_LABELS if label.identifier == label_size), None
            )
            if label_size_human:
                label_size = f"{label_size_human}"
            entry['label_size'] = str(label_size)
        else:
            entry['label_size'] = None
        files.append(entry)
    return {'files': files}


@bp.route('/api/repository/save', methods=['POST'])
def repo_save():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return make_response(jsonify({'success': False, 'message': 'No JSON payload provided'}), 400)
    name = data.get('name') or request.values.get('name') or None
    if not name:
        return make_response(jsonify({'success': False, 'message': 'No name provided'}), 400)
    filename = secure_filename(name)
    if not filename.lower().endswith('.json'):
        filename = filename + '.json'
    repo = get_repo_dir()
    path = os.path.join(repo, filename)
    try:
        text = data.get('fontSettingsPerLine', [])
        if isinstance(text, str):
            data['text'] = json.loads(text)

        try:
            img_b64 = data.get('image_data')
            if isinstance(img_b64, str) and len(img_b64) > 0:
                img_mime = data.get('image_mime', 'image/png')
                ext = {
                    'image/png': '.png',
                    'image/jpeg': '.jpg',
                    'image/jpg': '.jpg',
                    'image/gif': '.gif',
                    'application/pdf': '.pdf'
                }.get(img_mime, '.png')
                base_name = os.path.splitext(filename)[0]
                image_name = secure_filename(data.get('image_name') or (base_name + '_image' + ext))
                image_path = os.path.join(repo, image_name)
                import base64 as _b64
                with open(image_path, 'wb') as imgfh:
                    imgfh.write(_b64.b64decode(img_b64))
                data['image'] = image_name
        except Exception:
            current_app.logger.exception('Failed to store base64 image from JSON')

        if 'image_data' in data:
            del data['image_data']

        for key in ['font_size', 'font_inverted', 'font', 'font_align', 'font_checkbox',
                    'font_color', 'line_spacing', 'fontSettingsPerLine']:
            if key in data:
                del data[key]

        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': 'Failed to save file'}), 500)
    return {'success': True, 'name': filename}


@bp.route('/api/repository/load', methods=['GET'])
def repo_load():
    name = request.values.get('name')
    if not name:
        return make_response(jsonify({'success': False, 'message': 'No name specified'}), 400)
    filename = secure_filename(name)
    repo = get_repo_dir()
    path = os.path.join(repo, filename)
    if not os.path.exists(path):
        return make_response(jsonify({'success': False, 'message': 'Not found'}), 404)
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        text = data.get('text', [])
        data['text'] = json.dumps(text)
        data = fill_first_line_fields(text, data)
        try:
            image_ref = data.get('image')
            if isinstance(image_ref, str) and len(image_ref) > 0:
                image_path = os.path.join(repo, secure_filename(image_ref))
                if os.path.exists(image_path):
                    import base64 as _b64
                    with open(image_path, 'rb') as imgfh:
                        b = imgfh.read()
                    _, ext = os.path.splitext(image_path)
                    ext = ext.lower()
                    mime = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.gif': 'image/gif',
                        '.pdf': 'application/pdf'
                    }.get(ext, 'application/octet-stream')
                    data['image_name'] = image_ref
                    data['image_mime'] = mime
                    data['image_data'] = _b64.b64encode(b).decode('ascii')
        except Exception:
            current_app.logger.exception('Failed to include repository image in load response')
        return data
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': 'Failed to load file'}), 500)


@bp.route('/api/repository/delete', methods=['POST'])
def repo_delete():
    jdata = request.get_json(force=True, silent=True) or {}
    name = jdata.get('name') or request.values.get('name')
    if not name:
        return make_response(jsonify({'success': False, 'message': 'No name specified'}), 400)
    filename = secure_filename(name)
    repo = get_repo_dir()
    path = os.path.join(repo, filename)
    if not os.path.exists(path):
        return make_response(jsonify({'success': False, 'message': 'Not found'}), 404)
    try:
        os.remove(path)
        try:
            base_name = os.path.splitext(filename)[0]
            for f in os.listdir(repo):
                if f.startswith(base_name + '_image'):
                    try:
                        os.remove(os.path.join(repo, f))
                    except Exception:
                        current_app.logger.exception(f'Failed to remove associated image {f}')
        except Exception:
            current_app.logger.exception('Failed to cleanup associated images')
        return {'success': True}
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': 'Failed to delete file'}), 500)


@bp.route('/api/repository/preview', methods=['GET', 'POST'])
def repo_preview():
    name = request.values.get('name')
    if not name:
        return make_response(jsonify({'success': False, 'message': 'No name specified'}), 400)
    try:
        data = load_repo_json(name)
    except FileNotFoundError:
        return make_response(jsonify({'success': False, 'message': 'Not found'}), 404)
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': 'Failed to preview file'}), 500)

    if request.values.get('printer'):
        data['printer'] = request.values.get('printer')

    try:
        label = create_label_from_request(data)
        im = label.generate(rotate=True)
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 400)

    return _image_response(im, request.values.get('return_format', 'png'))


@bp.route('/api/repository/print', methods=['POST'])
def repo_print():
    jdata = request.get_json(force=True, silent=True) or {}
    name = jdata.get('name') or request.values.get('name')
    if not name:
        return make_response(jsonify({'success': False, 'message': 'No name specified'}), 400)
    try:
        data = load_repo_json(name)
    except FileNotFoundError:
        return make_response(jsonify({'success': False, 'message': 'Not found'}), 404)
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': 'Failed to load file'}), 500)

    if request.values.get('printer'):
        data['printer'] = request.values.get('printer')

    try:
        device = request.values.get('printer') or current_app.config['PRINTER_PRINTER']
        model = request.values.get('model') or current_app.config['PRINTER_MODEL']
        label_size = data.get('label_size') or current_app.config['LABEL_DEFAULT_SIZE']
        if device == '?' and current_app.config.get('PRINTER_SIMULATION', False):
            device = 'simulation'
        printer = PrinterQueue(model=model, device_specifier=device, label_size=label_size)
        print_count = int(request.values.get('print_count') or data.get('print_count') or 1)
        if print_count < 1:
            raise ValueError("print_count must be greater than 0")
        cut_once = int(request.values.get('cut_once') or data.get('cut_once') or 0) == 1
        high_res = int(request.values.get('high_res') or data.get('high_res') or 0) != 0
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': str(e)}), 400)

    status = ""
    try:
        for i in range(print_count):
            label = create_label_from_request(data, {}, i)
            cut = not cut_once or (cut_once and i == print_count - 1)
            printer.add_label_to_queue(label, cut, high_res)
        status = printer.process_queue()
    except Exception as e:
        current_app.logger.exception(e)
        return make_response(jsonify({'success': False, 'message': str(e)}), 400)

    result = {'success': len(status) == 0}
    if len(status) > 0:
        result['message'] = status
        return make_response(jsonify(result), 400)
    return result
