"""
Business logic for label and printer creation.

Extracted from routes.py so that HTTP handlers stay thin and
application logic stays testable outside a request context.
"""

import os
import logging

from PIL import Image
from flask import current_app, json
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from brother_ql.labels import ALL_LABELS, FormFactor

from .printer import PrinterQueue
from .label import SimpleLabel, ShippingLabel, LabelContent, LabelOrientation, LabelType
from app.utils import (
    convert_image_to_bw,
    convert_image_to_grayscale,
    convert_image_to_red_and_black,
    pdffile_to_image,
    pdffile_to_images,
    imgfile_to_image,
)

DEFAULT_DPI = 300


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------

def get_repo_dir() -> str:
    """Return (and create if necessary) the label repository directory."""
    repo = current_app.config.get('LABEL_REPOSITORY_DIR')
    if not repo:
        repo = os.path.join(current_app.root_path, 'labels')
    os.makedirs(repo, exist_ok=True)
    return repo


def load_repo_json(name: str) -> dict:
    """Load a repository JSON file by name. Raises FileNotFoundError if absent."""
    filename = secure_filename(name)
    repo = get_repo_dir()
    path = os.path.join(repo, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(name)
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
        data['text'] = json.dumps(data.get('text', []))
        return data


# ---------------------------------------------------------------------------
# Label dimensions
# ---------------------------------------------------------------------------

def get_label_dimensions(label_size: str, high_res: bool = False):
    """Return (width, height) in printer dots for the given label identifier."""
    dimensions = next(
        (label.dots_printable for label in ALL_LABELS if label.identifier == label_size),
        None,
    )
    if dimensions is None:
        raise LookupError("Unknown label_size")
    if high_res:
        return [2 * dimensions[0], 2 * dimensions[1]]
    return list(dimensions)


# ---------------------------------------------------------------------------
# Printer factory
# ---------------------------------------------------------------------------

def create_printer_from_request(values: dict) -> PrinterQueue:
    """
    Build a PrinterQueue from a flat dict of request values
    (e.g. ``request.values.to_dict(flat=True)``).
    """
    label_size = values.get('label_size', '62')
    device = values.get('printer') or current_app.config['PRINTER_PRINTER']
    model = values.get('model') or current_app.config['PRINTER_MODEL']
    if device == '?' and current_app.config.get('PRINTER_SIMULATION', False):
        device = 'simulation'
    return PrinterQueue(model=model, device_specifier=device, label_size=label_size)


# ---------------------------------------------------------------------------
# Label factory
# ---------------------------------------------------------------------------

def create_label_from_request(d: dict = {}, files: dict = {}, counter: int = 0):
    """
    Build a SimpleLabel or ShippingLabel from a flat dict ``d`` and an
    optional ``files`` dict (mapping field name → FileStorage).
    """
    from app import FONTS  # deferred to avoid circular import at module load

    label_size = d.get('label_size', "62")
    kind = next((label.form_factor for label in ALL_LABELS if label.identifier == label_size), None)
    if kind is None:
        raise LookupError("Unknown label_size")

    context = {
        'label_size': label_size,
        'print_type': d.get('print_type', 'text'),
        'label_orientation': d.get('orientation', 'standard'),
        'kind': kind,
        'margin_top': int(d.get('margin_top', 12)),
        'margin_bottom': int(d.get('margin_bottom', 12)),
        'margin_left': int(d.get('margin_left', 20)),
        'margin_right': int(d.get('margin_right', 20)),
        'border_thickness': int(d.get('border_thickness', 1)),
        'border_roundness': int(d.get('border_roundness', 0)),
        'border_distanceX': int(d.get('border_distance_x', 0)),
        'border_distanceY': int(d.get('border_distance_y', 0)),
        'border_color': d.get('border_color', 'black'),
        'text': json.loads(d.get('text', '[]')),
        'barcode_type': d.get('barcode_type') or 'QR',
        'qrcode_size': int(d.get('qrcode_size', 10)),
        'qrcode_correction': d.get('qrcode_correction', 'L'),
        'image_mode': d.get('image_mode', "grayscale"),
        'image_bw_threshold': int(d.get('image_bw_threshold', 70)),
        'image_fit': int(d.get('image_fit', 1)) > 0,
        'image_scaling_factor': float(d.get('image_scaling_factor', 100.0)),
        'image_rotation': int(d.get('image_rotation', 0)),
        'print_color': d.get('print_color', 'black'),
        'timestamp': int(d.get('timestamp', 0)),
        'high_res': int(d.get('high_res', 0)) != 0,
        'code_text': d.get('code_text', '').strip(),
    }

    def _get_uploaded_image(image: FileStorage) -> Image.Image:
        name, ext = os.path.splitext(image.filename)
        ext = ext.lower()
        if ext == '.pdf':
            img = pdffile_to_image(image, DEFAULT_DPI)
            if context['image_mode'] == 'grayscale':
                return convert_image_to_grayscale(img)
            return convert_image_to_bw(img, context['image_bw_threshold'])
        exts = Image.registered_extensions()
        supported_extensions = {ex for ex, f in exts.items() if f in Image.OPEN}
        if ext in supported_extensions:
            img = imgfile_to_image(image)
            if context['image_mode'] == 'grayscale':
                return convert_image_to_grayscale(img)
            elif context['image_mode'] == 'red_and_black':
                return convert_image_to_red_and_black(img)
            elif context['image_mode'] == 'colored':
                return img
            return convert_image_to_bw(img, context['image_bw_threshold'])
        raise ValueError("Unsupported file type")

    # Resolve label content type
    print_type = context['print_type']
    image_mode = context['image_mode']
    if print_type == 'text':
        label_content = LabelContent.TEXT_ONLY
    elif print_type == 'qrcode':
        label_content = LabelContent.QRCODE_ONLY
    elif print_type == 'qrcode_text':
        label_content = LabelContent.TEXT_QRCODE
    elif image_mode == 'grayscale':
        label_content = LabelContent.IMAGE_GRAYSCALE
    elif image_mode == 'red_black':
        label_content = LabelContent.IMAGE_RED_BLACK
    elif image_mode == 'colored':
        label_content = LabelContent.IMAGE_COLORED
    else:
        label_content = LabelContent.IMAGE_BW

    label_orientation = (LabelOrientation.ROTATED
                         if context['label_orientation'] == 'rotated'
                         else LabelOrientation.STANDARD)
    if context['kind'] == FormFactor.ENDLESS:
        label_type = LabelType.ENDLESS_LABEL
    elif context['kind'] == FormFactor.DIE_CUT:
        label_type = LabelType.DIE_CUT_LABEL
    else:
        label_type = LabelType.ROUND_DIE_CUT_LABEL

    width, height = get_label_dimensions(context['label_size'], context['high_res'])
    if height > width:
        width, height = height, width
    if label_orientation == LabelOrientation.ROTATED:
        height, width = width, height

    # Resolve font paths for text lines
    for line in context['text']:
        if 'size' not in line or not str(line['size']).isdigit():
            current_app.logger.error(line)
            raise ValueError("Font size is required")
        if int(line['size']) < 1:
            raise ValueError("Font size must be at least 1")
        line['path'] = FONTS.get_path(line.get('font', ''))
        if len(line.get('text', '')) > 10_000:
            raise ValueError("Text is too long")

    fore_color = (255, 0, 0) if context['print_color'] == 'red' else (0, 0, 0)
    border_color = (255, 0, 0) if context['border_color'] == 'red' else (0, 0, 0)

    # Resolve image
    uploaded = files.get('image', None)
    image = None
    if uploaded is not None:
        image = _get_uploaded_image(uploaded)
    else:
        image_ref = d.get('image')
        if isinstance(image_ref, str) and len(image_ref) > 0:
            try:
                repo = get_repo_dir()
                image_path = os.path.join(repo, secure_filename(image_ref))
                if os.path.exists(image_path):
                    with open(image_path, 'rb') as fh:
                        pil_img = imgfile_to_image(fh)
                    if context['image_mode'] == 'grayscale':
                        image = convert_image_to_grayscale(pil_img)
                    elif context['image_mode'] == 'red_and_black':
                        image = convert_image_to_red_and_black(pil_img)
                    elif context['image_mode'] == 'colored':
                        image = pil_img
                    else:
                        image = convert_image_to_bw(pil_img, context['image_bw_threshold'])
            except Exception:
                current_app.logger.exception('Failed to load repository image')

    # Build shipping label
    if print_type == 'shipping':
        default_family, default_style = FONTS.get_default_font()
        default_font_path = FONTS.get_path(f"{default_family},{default_style}")
        sender_font_path = context['text'][0].get('path', default_font_path) if context['text'] else default_font_path
        recipient_font_path = context['text'][1].get('path', sender_font_path) if len(context['text']) > 1 else sender_font_path
        sender_font_size = int(context['text'][0].get('size', 0)) if context['text'] else 0
        recipient_font_size = int(context['text'][1].get('size', sender_font_size)) if len(context['text']) > 1 else sender_font_size
        sender_line_spacing = int(context['text'][0].get('line_spacing', 100)) if context['text'] else 100
        recipient_line_spacing = int(context['text'][1].get('line_spacing', sender_line_spacing)) if len(context['text']) > 1 else sender_line_spacing
        if label_type == LabelType.ENDLESS_LABEL and width > height:
            label_orientation = LabelOrientation.ROTATED
            width, height = height, width

        ml = int(context['margin_left'])
        mr = int(context['margin_right'])
        mt = int(context['margin_top'])
        mb = int(context['margin_bottom'])

        return ShippingLabel(
            width=width,
            height=height,
            label_type=label_type,
            label_orientation=label_orientation,
            sender={
                'name':     d.get('ship_sender_name', '').strip(),
                'street':   d.get('ship_sender_street', '').strip(),
                'zip_city': d.get('ship_sender_zip_city', '').strip(),
                'country':  d.get('ship_sender_country', '').strip(),
            },
            recipient={
                'company':  d.get('ship_recip_company', '').strip(),
                'name':     d.get('ship_recip_name', '').strip(),
                'street':   d.get('ship_recip_street', '').strip(),
                'zip_city': d.get('ship_recip_zip_city', '').strip(),
                'country':  d.get('ship_recip_country', '').strip(),
            },
            tracking_number=d.get('ship_tracking', '').strip(),
            font_path=recipient_font_path,
            sender_font_path=sender_font_path,
            tracking_barcode_type=context['barcode_type'],
            sender_font_size=sender_font_size,
            recipient_font_size=recipient_font_size,
            margin=(ml, mr, mt, mb),
            section_spacing=int(d.get('ship_section_spacing', 0) or 0),
            barcode_scale=int(d.get('ship_barcode_scale', 0) or 0),
            barcode_show_text=bool(int(d.get('ship_barcode_show_text', 0) or 0)),
            from_label=d.get('ship_from_label', '').strip(),
            to_label=d.get('ship_to_label', '').strip(),
            recipient_border=bool(int(d.get('ship_recip_border', 0) or 0)),
            border_thickness=context['border_thickness'],
            border_roundness=context['border_roundness'],
            border_distance=(context['border_distanceX'], context['border_distanceY']),
            sender_line_spacing=sender_line_spacing,
            recipient_line_spacing=recipient_line_spacing,
        )

    # Build simple label (non-split types)
    return SimpleLabel(
        width=width,
        height=height,
        label_content=label_content,
        label_orientation=label_orientation,
        label_type=label_type,
        label_margin=(
            int(context['margin_left']),
            int(context['margin_right']),
            int(context['margin_top']),
            int(context['margin_bottom'])
        ),
        fore_color=fore_color,
        text=context['text'],
        barcode_type=context['barcode_type'],
        qr_size=context['qrcode_size'],
        qr_correction=context['qrcode_correction'],
        image=image,
        image_fit=context['image_fit'],
        image_scaling_factor=context['image_scaling_factor'],
        image_rotation=context['image_rotation'],
        border_thickness=context['border_thickness'],
        border_roundness=context['border_roundness'],
        border_distance=(context['border_distanceX'], context['border_distanceY']),
        border_color=border_color,
        timestamp=context['timestamp'],
        counter=counter,
        code_text=context['code_text']
    )


# ---------------------------------------------------------------------------
# Split label factory
# ---------------------------------------------------------------------------


def _img_white(mode: str):
    """Return a white fill value for the given PIL image mode."""
    if mode in ('L', 'P', '1'):
        return 255
    if mode in ('RGBA', 'LA'):
        return (255, 255, 255, 255)
    return (255, 255, 255)  # RGB and everything else


def _apply_crop(img: Image.Image, top_pct: float, right_pct: float,
                bottom_pct: float, left_pct: float) -> Image.Image:
    """Trim edges by percentage. Each value is 0–49."""
    iw, ih = img.size
    x0 = int(iw * left_pct / 100)
    y0 = int(ih * top_pct / 100)
    x1 = int(iw * (1 - right_pct / 100))
    y1 = int(ih * (1 - bottom_pct / 100))
    if x1 > x0 and y1 > y0:
        return img.crop((x0, y0, x1, y1))
    return img


def _make_strip_label(strip, width, label_content, margin_left, margin_right,
                      margin_top, margin_bottom):
    return SimpleLabel(
        width=width,
        height=0,
        label_content=label_content,
        label_orientation=LabelOrientation.STANDARD,
        label_type=LabelType.ENDLESS_LABEL,
        label_margin=(margin_left, margin_right, margin_top, margin_bottom),
        text=[],
        image=strip,
        image_fit=False,
        image_scaling_factor=100.0,
    )


def create_split_labels_from_request(d: dict = {}, files: dict = {}):
    """
    Split an image/PDF into multiple endless-tape labels.

    Two modes (split_axis):
      'horizontal' — scales the image to N× the tape width and cuts it into
                     N vertical strips.  Place labels side by side (left→right)
                     to see the full image at N× the normal size.  Use this to
                     make a shipping label or document readable.
      'vertical'   — scales the image to fit the tape width and cuts it into
                     N equal horizontal slices.  Place labels end to end
                     (top→bottom) to read a long document in sequence.

    An optional crop (trim %) is applied before scaling/splitting.

    Returns (labels, split_axis).
    """
    label_size = d.get('label_size', '62')
    kind = next((label.form_factor for label in ALL_LABELS if label.identifier == label_size), None)
    if kind is None:
        raise LookupError("Unknown label_size")

    high_res = int(d.get('high_res', 0)) != 0
    dpi = DEFAULT_DPI * 2 if high_res else DEFAULT_DPI

    image_mode = d.get('image_mode', 'grayscale')
    image_bw_threshold = int(d.get('image_bw_threshold', 70))

    margin_left = int(d.get('margin_left', 20))
    margin_right = int(d.get('margin_right', 20))
    margin_top = int(d.get('margin_top', 12))
    margin_bottom = int(d.get('margin_bottom', 12))

    num_labels = max(1, min(6, int(d.get('split_num_labels', 1) or 1)))
    split_axis = d.get('split_axis', 'horizontal')

    crop_top    = max(0.0, min(49.0, float(d.get('crop_top_pct',    0) or 0)))
    crop_right  = max(0.0, min(49.0, float(d.get('crop_right_pct',  0) or 0)))
    crop_bottom = max(0.0, min(49.0, float(d.get('crop_bottom_pct', 0) or 0)))
    crop_left   = max(0.0, min(49.0, float(d.get('crop_left_pct',   0) or 0)))

    width, height = get_label_dimensions(label_size, high_res)
    if height > width:
        width, height = height, width

    uploaded = files.get('image', None)
    if uploaded is None:
        raise ValueError("No image uploaded for Split mode")

    _, ext = os.path.splitext(uploaded.filename or '')
    ext = ext.lower()

    if ext == '.pdf':
        pages = pdffile_to_images(uploaded, dpi)
        if not pages:
            raise ValueError("PDF produced no pages")
        total_h = sum(p.height for p in pages)
        max_w = max(p.width for p in pages)
        raw_img = Image.new('RGB', (max_w, total_h), 'white')
        y_off = 0
        for page in pages:
            raw_img.paste(page, (0, y_off))
            y_off += page.height
    else:
        raw_img = imgfile_to_image(uploaded)

    # Convert colour mode
    if image_mode == 'grayscale':
        img = convert_image_to_grayscale(raw_img)
        label_content = LabelContent.IMAGE_GRAYSCALE
    elif image_mode == 'red_and_black':
        img = convert_image_to_red_and_black(raw_img)
        label_content = LabelContent.IMAGE_RED_BLACK
    elif image_mode == 'colored':
        img = raw_img.convert('RGB')
        label_content = LabelContent.IMAGE_COLORED
    else:
        img = convert_image_to_bw(raw_img, image_bw_threshold)
        label_content = LabelContent.IMAGE_BW

    # Crop before scaling
    img = _apply_crop(img, crop_top, crop_right, crop_bottom, crop_left)

    # B&W images must use NEAREST to preserve bar widths; anti-aliasing distorts barcodes
    resample = Image.Resampling.NEAREST if image_mode == 'bw' else Image.Resampling.LANCZOS

    content_width = max(width - margin_left - margin_right, 1)

    labels = []

    if split_axis == 'horizontal':
        # Scale image so the full combined strip (minus outer margins) fills
        # num_labels tape widths.  Build one wide canvas, paste, then slice —
        # this way only the outermost edges carry a margin; inner seams are
        # seamless.
        outer_w = max(num_labels * width - margin_left - margin_right, 1)
        iw, ih = img.size
        img_scaled = img.resize(
            (outer_w, max(int(ih * outer_w / iw), 1)),
            resample,
        )
        canvas_w = num_labels * width
        canvas = Image.new(img_scaled.mode, (canvas_w, img_scaled.height),
                           _img_white(img_scaled.mode))
        canvas.paste(img_scaled, (margin_left, 0))
        for i in range(num_labels):
            strip = canvas.crop((i * width, 0, (i + 1) * width, canvas.height))
            if strip.width > 0 and strip.height > 0:
                labels.append(_make_strip_label(
                    strip, width, label_content,
                    0, 0, margin_top, margin_bottom))  # left/right baked into canvas
    else:
        # vertical: scale to fit content_width → N horizontal slices end to end.
        # Remove margins on interior edges so strips join without gaps.
        iw, ih = img.size
        img = img.resize((content_width, max(int(ih * content_width / iw), 1)),
                         resample)
        iw, ih = img.size
        slice_h = max(ih // num_labels, 1)
        for i in range(num_labels):
            y0 = i * slice_h
            y1 = ih if i == num_labels - 1 else y0 + slice_h
            strip = img.crop((0, y0, iw, y1))
            if strip.width > 0 and strip.height > 0:
                mt = margin_top    if i == 0               else 0
                mb = margin_bottom if i == num_labels - 1  else 0
                labels.append(_make_strip_label(
                    strip, width, label_content,
                    margin_left, margin_right, mt, mb))

    if not labels:
        raise ValueError("Split produced no labels")

    return labels, split_axis


def create_split_preview(labels, split_axis='horizontal'):
    """
    Render a preview showing all split labels in order with clear separators.
    Each section is a separate physical label.
    For 'horizontal' axis: place labels side by side (←→).
    For 'vertical' axis: place labels end to end (↑↓).
    """
    from PIL import ImageDraw, ImageFont
    SEP_H = 20   # pixels between strips in the preview
    BORDER = 3   # border around each strip
    num = len(labels)
    imgs = [lbl.generate(rotate=True) for lbl in labels]

    max_w = max(im.width for im in imgs)
    strip_w = max_w + 2 * BORDER
    total_h = sum(im.height + 2 * BORDER for im in imgs) + SEP_H * (num - 1)
    composite = Image.new('RGB', (strip_w, total_h), (230, 230, 230))
    draw = ImageDraw.Draw(composite)

    try:
        font = ImageFont.load_default(size=14)
    except Exception:
        font = ImageFont.load_default()

    arrow = '←→' if split_axis == 'horizontal' else '↑↓'

    y = 0
    for i, im in enumerate(imgs):
        # White card background for this label
        card_top = y
        card_bottom = y + im.height + 2 * BORDER
        draw.rectangle([0, card_top, strip_w - 1, card_bottom - 1],
                       fill='white', outline=(100, 100, 100), width=BORDER)
        composite.paste(im, (BORDER, y + BORDER))

        # Badge: "Label 1 of 2 ←→"
        badge = f" Label {i + 1} of {num} {arrow} "
        bb = draw.textbbox((0, 0), badge, font=font)
        bw, bh = bb[2] - bb[0], bb[3] - bb[1]
        bx = strip_w - bw - BORDER - 2
        by = y + BORDER + 2
        draw.rectangle([bx - 2, by - 1, bx + bw + 2, by + bh + 1], fill=(50, 50, 50))
        draw.text((bx, by), badge, fill='white', font=font)

        y = card_bottom + SEP_H

    return composite
