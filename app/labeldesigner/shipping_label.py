"""ShippingLabel — structured sender/recipient label renderer."""

import logging
from typing import Any, List, Tuple

from PIL import Image, ImageDraw, ImageFont
from qrcode import QRCode, constants
import barcode
from barcode.writer import ImageWriter

from .enums import LabelContent, LabelType, LabelOrientation
from .label_utils import FONT_CACHE, _draw_dashed_line

logger = logging.getLogger(__name__)


class ShippingLabel:
    """
    Renders a structured shipping label with sender, recipient address blocks
    and an optional tracking-number barcode/QR code.
    """

    def __init__(
        self,
        width: int,
        height: int,
        label_type: LabelType,
        label_orientation: LabelOrientation,
        sender: dict,
        recipient: dict,
        tracking_number: str = '',
        font_path: str = '',
        sender_font_path: str = '',
        tracking_barcode_type: str = 'code128',
        sender_font_size: int = 0,
        recipient_font_size: int = 0,
        margin: Tuple[int, int, int, int] = (20, 20, 15, 15),
        section_spacing: int = 0,
        barcode_scale: int = 0,
        barcode_show_text: bool = False,
        from_label: str = '',
        to_label: str = '',
        recipient_border: bool = False,
        border_thickness: int = 0,
        border_roundness: int = 0,
        border_distance: Tuple[int, int] = (0, 0),
        sender_line_spacing: int = 100,
        recipient_line_spacing: int = 100,
    ):
        self._width = width
        self._height = height
        self._label_type = label_type
        self._label_orientation = label_orientation
        self.sender = sender
        self.recipient = recipient
        self.tracking_number = tracking_number
        self._font_path = font_path
        self._sender_font_path = sender_font_path or font_path
        self._tracking_barcode_type = (tracking_barcode_type or 'code128').strip().lower()
        self._sender_font_size = max(sender_font_size or 0, 0)
        self._recipient_font_size = max(recipient_font_size or 0, 0)
        self._margin = margin
        self._section_spacing = max(section_spacing or 0, 0)
        self._barcode_scale = max(barcode_scale or 0, 0)
        self._barcode_show_text = bool(barcode_show_text)
        self._from_label = (from_label or '').strip() or 'From:'
        self._to_label = (to_label or '').strip() or 'To:'
        self._recipient_border = bool(recipient_border)
        self._border_thickness = max(int(border_thickness or 0), 0)
        self._border_roundness = max(int(border_roundness or 0), 0)
        self._border_distance = tuple(border_distance) if border_distance else (0, 0)
        self._sender_line_spacing = max(sender_line_spacing or 100, 100)
        self._recipient_line_spacing = max(recipient_line_spacing or 100, 100)

    @property
    def label_type(self):
        return self._label_type

    @property
    def label_orientation(self):
        return self._label_orientation

    @property
    def label_content(self):
        return LabelContent.TEXT_ONLY

    def _get_font(self, size: int, font_path: str = '') -> ImageFont.FreeTypeFont:
        path = font_path or self._font_path
        if not path:
            return ImageFont.load_default()
        key = (path, size)
        if key in FONT_CACHE:
            return FONT_CACHE[key]
        try:
            font = ImageFont.truetype(path, size)
            FONT_CACHE[key] = font
            return font
        except Exception as e:
            logger.error(f"ShippingLabel: failed to load font '{path}' size {size}: {e}")
            return ImageFont.load_default()

    def _generate_tracking_image(self, write_text: bool = False) -> Optional[Image.Image]:
        """Generate a tracking-number barcode or QR image."""
        if not self.tracking_number:
            return None
        bc_type = self._tracking_barcode_type
        if bc_type == 'qr':
            qr = QRCode(
                version=1,
                error_correction=constants.ERROR_CORRECT_L,
                box_size=10,
                border=1,
            )
            qr.add_data(self.tracking_number)
            qr.make(fit=True)
            return qr.make_image(fill_color='black', back_color='white').convert('RGB')
        else:
            try:
                bc_class = barcode.get_barcode_class(bc_type)
            except Exception:
                bc_class = barcode.get_barcode_class('code128')
            bc_obj = bc_class(self.tracking_number, writer=ImageWriter())
            return bc_obj.render(writer_options={'write_text': write_text, 'quiet_zone': 2}).convert('RGB')

    def generate(self, rotate: bool = False) -> Image.Image:
        if self._label_type == LabelType.ENDLESS_LABEL:
            return self._generate_landscape()
        return self._generate_portrait()

    def _generate_landscape(self) -> Image.Image:
        """
        Landscape layout for endless tape. The tape's dimension becomes the image HEIGHT;
        width grows to fit content. Sender is left, recipient right, optional code at far right.

        Font sizes: when sender/recipient_font_size > 0, those values are used directly as the
        primary font size; when 0, sizes are auto-computed proportionally from the canvas height.
        A single-pass scale-down is applied if text blocks would overflow the available height.
        """
        ml, mr, mt, mb = self._margin
        canvas_h = max(self._height, 1)
        usable_h = max(canvas_h - mt - mb, 1)

        COLOR_GRAY = (130, 130, 130)
        COLOR_BLACK = (0, 0, 0)
        DIVIDER_GAP = (self._section_spacing if self._section_spacing > 0
                       else max(int(usable_h * 0.04), 24))
        CODE_GAP = max(int(usable_h * 0.03), 20)

        n_recip = sum(1 for k in ('company', 'name', 'street', 'zip_city', 'country')
                      if self.recipient.get(k))
        n_recip = max(1, min(5, n_recip))
        line_h = usable_h / (n_recip + 0.5)

        sfp = self._sender_font_path

        # Dummy canvas for text measurement
        dummy = Image.new('RGB', (16000, canvas_h), 'white')
        draw_m = ImageDraw.Draw(dummy)

        def _compute_sizes(scale: float = 1.0):
            """
            Compute all font sizes proportionally from canvas height.
            font_size inputs act as scale multipliers (relative to 48) so the
            visual hierarchy (recipient larger than sender) is always preserved.
            """
            r_scale = (self._recipient_font_size / 48.0) if self._recipient_font_size > 0 else 1.0
            s_scale = (self._sender_font_size / 48.0) if self._sender_font_size > 0 else 1.0
            sz_rname = max(int(line_h * 1.15 * r_scale * scale), 8)
            sz_rdetail = max(int(line_h * 0.92 * r_scale * scale), 7)
            sz_to = max(int(line_h * 0.52 * r_scale * scale), 5)
            sz_sender = max(int(line_h * 0.28 * s_scale * scale), 5)
            sz_from = max(int(line_h * 0.16 * s_scale * scale), 4)
            sz_tracking = max(int(line_h * 0.14 * scale), 5)
            return sz_rname, sz_rdetail, sz_to, sz_sender, sz_from, sz_tracking

        def _load_fonts(sizes):
            sz_rname, sz_rdetail, sz_to, sz_sender, sz_from, sz_tracking = sizes
            return (
                self._get_font(sz_rname),
                self._get_font(sz_rdetail),
                self._get_font(sz_to),
                self._get_font(sz_sender, sfp),
                self._get_font(sz_from, sfp),
                self._get_font(sz_tracking),
            )

        def _build_lines(font_from, font_sender, font_to, font_rname, font_rdetail):
            _sender: List[Tuple[str, Any, Tuple, int]] = [
                (self._from_label, font_from, COLOR_GRAY, 0),
            ]
            for field, base_pad in [
                (self.sender.get('name', ''), 4),
                (self.sender.get('street', ''), 0),
            ]:
                if field:
                    _sender.append((field, font_sender, COLOR_BLACK, base_pad))
            addr_parts = [p for p in [self.sender.get('zip_city'), self.sender.get('country')] if p]
            if addr_parts:
                _sender.append((' \u00b7 '.join(addr_parts), font_sender, COLOR_BLACK, 0))

            _recip: List[Tuple[str, Any, Tuple, int]] = [
                (self._to_label, font_to, COLOR_GRAY, 0),
            ]
            if self.recipient.get('company'):
                _recip.append((self.recipient['company'], font_rdetail, COLOR_BLACK, 6))
            if self.recipient.get('name'):
                _recip.append((self.recipient['name'], font_rname, COLOR_BLACK, 6))
            if self.recipient.get('street'):
                _recip.append((self.recipient['street'], font_rdetail, COLOR_BLACK, 6))
            if self.recipient.get('zip_city'):
                _recip.append((self.recipient['zip_city'], font_rdetail, COLOR_BLACK, 0))
            if self.recipient.get('country'):
                _recip.append((self.recipient['country'], font_rdetail, COLOR_BLACK, 0))
            return _sender, _recip

        def _block_height(lines_list, ls_px=0) -> int:
            total = 0
            for text, font, _, extra_top in lines_list:
                if not text:
                    continue
                bb = draw_m.textbbox((0, 0), text or ' ', font=font, anchor='lt')
                total += extra_top + (bb[3] - bb[1]) + ls_px
            return total

        # --- Initial sizing ---
        sizes = _compute_sizes(1.0)
        sz_rname, sz_rdetail, sz_to, sz_sender, sz_from, sz_tracking = sizes
        font_rname, font_rdetail, font_to, font_sender, font_from, font_tracking = _load_fonts(sizes)

        sender_ls_px = max(0, int(sz_sender * (self._sender_line_spacing - 100) / 100))
        recip_ls_px = max(0, int(sz_rdetail * (self._recipient_line_spacing - 100) / 100))

        sender_lines, recip_lines = _build_lines(font_from, font_sender, font_to, font_rname, font_rdetail)

        # --- Auto-scale down if blocks overflow available height ---
        max_block_h = max(_block_height(sender_lines, sender_ls_px),
                          _block_height(recip_lines, recip_ls_px))
        if max_block_h > usable_h:
            scale = (usable_h / max_block_h) * 0.94
            sizes = _compute_sizes(scale)
            sz_rname, sz_rdetail, sz_to, sz_sender, sz_from, sz_tracking = sizes
            font_rname, font_rdetail, font_to, font_sender, font_from, font_tracking = _load_fonts(sizes)
            sender_ls_px = max(0, int(sz_sender * (self._sender_line_spacing - 100) / 100))
            recip_ls_px = max(0, int(sz_rdetail * (self._recipient_line_spacing - 100) / 100))
            sender_lines, recip_lines = _build_lines(font_from, font_sender, font_to, font_rname, font_rdetail)

        # --- Column widths ---
        def col_width(lines_list, min_w: int) -> int:
            max_w = min_w
            for text, font, _, _ in lines_list:
                if not text:
                    continue
                bb = draw_m.textbbox((0, 0), text, font=font, anchor='lt')
                max_w = max(max_w, bb[2] - bb[0])
            return max_w

        sender_col_w = col_width(sender_lines, 100)
        recip_col_w = col_width(recip_lines, 300)

        # --- Tracking barcode ---
        code_img = None
        code_col_w = 0
        tracking_tw = 0
        tracking_th = 0

        if self.tracking_number:
            raw_code = self._generate_tracking_image(write_text=self._barcode_show_text)
            if raw_code is not None:
                _bscale = (self._barcode_scale / 100.0) if self._barcode_scale > 0 else 1.0
                if self._tracking_barcode_type == 'qr':
                    side = max(int(usable_h * 0.85 * _bscale), 8)
                    code_img = raw_code.resize((side, side), Image.Resampling.LANCZOS)
                else:
                    rotated = raw_code.rotate(90, expand=True)
                    target_h = max(int(usable_h * _bscale), 8)
                    sc = target_h / rotated.height
                    new_w = max(int(rotated.width * sc), 1)
                    code_img = rotated.resize((new_w, target_h), Image.Resampling.LANCZOS)

                tb = draw_m.textbbox((0, 0), self.tracking_number, font=font_tracking, anchor='lt')
                tracking_tw = tb[2] - tb[0]
                tracking_th = tb[3] - tb[1]
                code_col_w = CODE_GAP + max(code_img.width, tracking_tw)

        # --- Build final canvas ---
        canvas_w = (ml + sender_col_w + DIVIDER_GAP + 1 + DIVIDER_GAP
                    + recip_col_w + code_col_w + mr)
        img = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(img)

        # Draw sender (centered vertically)
        sender_block_h = _block_height(sender_lines, sender_ls_px)
        y = mt + max((usable_h - sender_block_h) // 2, 0)
        for text, font, color, extra_top in sender_lines:
            if not text:
                continue
            y += extra_top
            draw.text((ml, y), text, fill=color, font=font, anchor='lt')
            bb = draw.textbbox((ml, y), text, font=font, anchor='lt')
            y += bb[3] - bb[1] + sender_ls_px

        # Divider line
        div_x = ml + sender_col_w + DIVIDER_GAP
        _draw_dashed_line(draw, div_x, mt, div_x, canvas_h - mb,
                          fill=(180, 180, 180), width=2, dash_len=10, gap_len=6)

        # Draw recipient
        rx = div_x + 1 + DIVIDER_GAP
        y = mt
        recip_block_y_start = y
        for text, font, color, extra_top in recip_lines:
            if not text:
                continue
            y += extra_top
            draw.text((rx, y), text, fill=color, font=font, anchor='lt')
            bb = draw.textbbox((rx, y), text, font=font, anchor='lt')
            y += bb[3] - bb[1] + recip_ls_px
        recip_block_y_end = y

        if self._recipient_border and self._border_thickness > 0:
            bw = self._border_thickness
            bdx, bdy = self._border_distance
            br = self._border_roundness
            default_pad = max(int(usable_h * 0.03), 6)
            pad_x = default_pad + bdx
            pad_y = default_pad + bdy
            rect = [rx - pad_x, recip_block_y_start - pad_y,
                    rx + recip_col_w + pad_x, recip_block_y_end + pad_y]
            if br > 0:
                draw.rounded_rectangle(rect, radius=br, outline=COLOR_BLACK, width=bw)
            else:
                draw.rectangle(rect, outline=COLOR_BLACK, width=bw)

        # Draw tracking barcode
        if code_img:
            code_x = rx + recip_col_w + CODE_GAP
            code_y = mt + max((usable_h - code_img.height) // 2, 0)
            img.paste(code_img, (code_x, code_y))
            if self._barcode_show_text and self._tracking_barcode_type == 'qr' and tracking_th:
                ty = code_y + code_img.height + 6
                if ty + tracking_th <= canvas_h - mb:
                    draw.text((code_x, ty), self.tracking_number,
                              fill=COLOR_BLACK, font=font_tracking, anchor='lt')

        return img

    def _generate_portrait(self) -> Image.Image:
        """
        Portrait layout for die-cut labels (fixed width × height).

        Font sizes are proportional to the user's scale factor (size / 48).
        Text is wrapped to fit the usable width. If the total content height exceeds
        the fixed canvas height, all fonts are scaled down proportionally.
        """
        ml, mr, mt, mb = self._margin
        usable_width = max(self._width - ml - mr, 1)

        sfp = self._sender_font_path
        S_SCALE = (self._sender_font_size / 48.0) if self._sender_font_size > 0 else 1.0
        R_SCALE = (self._recipient_font_size / 48.0) if self._recipient_font_size > 0 else 1.0

        COLOR_GRAY = (130, 130, 130)
        COLOR_BLACK = (0, 0, 0)
        DIVIDER_H = (self._section_spacing if self._section_spacing > 0
                     else max(int(usable_width * 0.04), 18))

        def _build_portrait_fonts(scale: float = 1.0):
            _font_section = self._get_font(max(int(13 * max(S_SCALE, R_SCALE) * scale), 5))
            _font_sender = self._get_font(max(int(16 * S_SCALE * scale), 6), sfp)
            _font_rname = self._get_font(max(int(38 * R_SCALE * scale), 9))
            _font_rdetail = self._get_font(max(int(30 * R_SCALE * scale), 8))
            return _font_section, _font_sender, _font_rname, _font_rdetail

        font_section, font_sender, font_rname, font_rdetail = _build_portrait_fonts(1.0)

        dummy = Image.new('RGB', (max(self._width, 1), 20), 'white')
        draw_m = ImageDraw.Draw(dummy)

        def build_lines(font_section, font_sender, font_rname, font_rdetail):
            _sender: List[Tuple[str, Any, Tuple, int]] = [
                (self._from_label, font_section, COLOR_GRAY, 0),
            ]
            for field, pad in [(self.sender.get('name', ''), 3),
                               (self.sender.get('street', ''), 0)]:
                if field:
                    _sender.append((field, font_sender, COLOR_BLACK, pad))
            addr_parts = [p for p in [self.sender.get('zip_city'), self.sender.get('country')] if p]
            if addr_parts:
                _sender.append((' \u00b7 '.join(addr_parts), font_sender, COLOR_BLACK, 0))

            _recip: List[Tuple[str, Any, Tuple, int]] = [
                (self._to_label, font_section, COLOR_GRAY, 0),
            ]
            for field, font, pad in [
                (self.recipient.get('company', ''), font_rdetail, 5),
                (self.recipient.get('name', ''), font_rname, 5),
                (self.recipient.get('street', ''), font_rdetail, 5),
                (self.recipient.get('zip_city', ''), font_rdetail, 0),
                (self.recipient.get('country', ''), font_rdetail, 0),
            ]:
                if field:
                    _recip.append((field, font, COLOR_BLACK, pad))
            return _sender, _recip

        sender_ls_px = max(0, int(font_sender.size * (self._sender_line_spacing - 100) / 100))
        recip_ls_px = max(0, int(font_rdetail.size * (self._recipient_line_spacing - 100) / 100))

        sender_lines, recip_lines = build_lines(font_section, font_sender, font_rname, font_rdetail)

        def measure_h(lines_list, ls_px=0):
            total = 0
            for text, font, _, extra in lines_list:
                bb = draw_m.textbbox((0, 0), text or ' ', font=font, anchor='lt')
                total += extra + (bb[3] - bb[1]) + ls_px
            return total

        sender_h = measure_h(sender_lines, sender_ls_px)
        recip_h = measure_h(recip_lines, recip_ls_px)

        # --- Tracking barcode ---
        code_img = None
        code_h = 0
        tracking_text_h = 0
        font_tracking = self._get_font(14)

        if self.tracking_number:
            raw_code = self._generate_tracking_image(write_text=self._barcode_show_text)
            if raw_code is not None:
                _bscale = (self._barcode_scale / 100.0) if self._barcode_scale > 0 else 1.0
                if self._tracking_barcode_type == 'qr':
                    side = max(min(int(usable_width * 0.28 * _bscale), 110), 8)
                    code_img = raw_code.resize((side, side), Image.Resampling.NEAREST)
                else:
                    target_w = max(int(usable_width * _bscale), 8)
                    sc = target_w / raw_code.width
                    new_h = max(int(raw_code.height * sc), 1)
                    code_img = raw_code.resize((target_w, new_h), Image.Resampling.LANCZOS)
                code_h = code_img.height
                tb = draw_m.textbbox((0, 0), self.tracking_number, font=font_tracking, anchor='lt')
                tracking_text_h = tb[3] - tb[1]

        code_row_h = (
            (code_h + (8 + tracking_text_h if self._tracking_barcode_type != 'qr' else 0) + 14)
            if code_img else 0
        )
        if self._tracking_barcode_type == 'qr' and code_img:
            code_row_h = max(code_img.height, tracking_text_h) + 14

        total_h = mt + sender_h + DIVIDER_H * 2 + 1 + recip_h + code_row_h + mb

        canvas_h = max(self._height, 1) if self._height else max(int(total_h), 1)
        canvas_w = max(self._width, 1)

        # --- Auto-scale if content overflows a fixed-height canvas ---
        if self._height > 0 and total_h > self._height:
            scale = (self._height / total_h) * 0.94
            font_section, font_sender, font_rname, font_rdetail = _build_portrait_fonts(scale)
            sender_ls_px = max(0, int(font_sender.size * (self._sender_line_spacing - 100) / 100))
            recip_ls_px = max(0, int(font_rdetail.size * (self._recipient_line_spacing - 100) / 100))
            sender_lines, recip_lines = build_lines(font_section, font_sender, font_rname, font_rdetail)
            sender_h = measure_h(sender_lines, sender_ls_px)
            recip_h = measure_h(recip_lines, recip_ls_px)

        img = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(img)
        y = mt

        def draw_lines(lines_list, ls_px=0):
            nonlocal y
            for text, font, color, extra_top in lines_list:
                if not text:
                    continue
                y += extra_top
                draw.text((ml, y), text, fill=color, font=font, anchor='lt')
                bb = draw.textbbox((ml, y), text, font=font, anchor='lt')
                y += bb[3] - bb[1] + ls_px

        draw_lines(sender_lines, sender_ls_px)

        y += DIVIDER_H
        _draw_dashed_line(draw, ml, y, canvas_w - mr, y,
                          fill=(170, 170, 170), width=2, dash_len=10, gap_len=6)
        y += 1 + DIVIDER_H

        recip_y_start = y
        draw_lines(recip_lines, recip_ls_px)
        recip_y_end = y

        if self._recipient_border and self._border_thickness > 0:
            bw = self._border_thickness
            bdx, bdy = self._border_distance
            br = self._border_roundness
            default_pad = max(int(usable_width * 0.02), 4)
            pad_x = default_pad + bdx
            pad_y = default_pad + bdy
            rect = [ml - pad_x, recip_y_start - pad_y,
                    canvas_w - mr + pad_x, recip_y_end + pad_y]
            if br > 0:
                draw.rounded_rectangle(rect, radius=br, outline=COLOR_BLACK, width=bw)
            else:
                draw.rectangle(rect, outline=COLOR_BLACK, width=bw)

        if code_img:
            y += 14
            if self._tracking_barcode_type == 'qr':
                img.paste(code_img, (ml, y))
                if self._barcode_show_text and tracking_text_h:
                    tx = ml + code_img.width + 12
                    ty = y + max((code_img.height - tracking_text_h) // 2, 0)
                    if tx + 20 <= canvas_w - mr:
                        draw.text((tx, ty), self.tracking_number,
                                  fill=COLOR_BLACK, font=font_tracking, anchor='lt')
            else:
                img.paste(code_img, (ml, y))

        return img
