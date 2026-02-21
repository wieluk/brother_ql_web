from .enums import LabelContent, LabelOrientation, LabelType
import os
import uuid
from qrcode import QRCode, constants
from PIL import Image, ImageDraw, ImageFont
import logging
import barcode
from barcode.writer import ImageWriter
import datetime
import re
import random
import string
import copy
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def _draw_dashed_line(draw, x0, y0, x1, y1, fill=(190, 190, 190), width=1, dash_len=8, gap_len=5):
    """Draw a dashed line from (x0, y0) to (x1, y1)."""
    dx, dy = x1 - x0, y1 - y0
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return
    nx, ny = dx / length, dy / length
    pos = 0.0
    drawing = True
    while pos < length:
        seg = dash_len if drawing else gap_len
        end_pos = min(pos + seg, length)
        if drawing:
            draw.line(
                [(x0 + nx * pos, y0 + ny * pos), (x0 + nx * end_pos, y0 + ny * end_pos)],
                fill=fill, width=width
            )
        pos = end_pos
        drawing = not drawing


# Constants
WARNING_TEXT_LENGTH = 500
DEFAULT_RANDOM_LENGTH = 64
DEFAULT_FONT_SIZE = 12
FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


class SimpleLabel:
    """
    Represents a label with text, image, barcode, and QR code support.
    Handles rendering, template processing, and layout.
    """
    QR_CORRECTION_MAPPING = {
        'M': constants.ERROR_CORRECT_M,
        'L': constants.ERROR_CORRECT_L,
        'H': constants.ERROR_CORRECT_H,
        'Q': constants.ERROR_CORRECT_Q
    }

    def __init__(
        self,
        width: int = 0,
        height: int = 0,
        label_content: LabelContent = LabelContent.TEXT_ONLY,
        label_orientation: LabelOrientation = LabelOrientation.STANDARD,
        label_type: LabelType = LabelType.ENDLESS_LABEL,
        barcode_type: str = "QR",
        label_margin: Tuple[int, int, int, int] = (0, 0, 0, 0),
        fore_color: Tuple[int, int, int] = (0, 0, 0),
        text: Optional[List[Dict[str, Any]]] = None,
        qr_size: int = 10,
        qr_correction: str = 'L',
        image_fit: bool = False,
        image_scaling_factor: float = 100.0,
        image_rotation: int = 0,
        image: Optional[Union[Image.Image, None]] = None,
        border_thickness: int = 0,
        border_roundness: int = 0,
        border_distance: Tuple[int, int] = (0, 0),
        border_color: Tuple[int, int, int] = (0, 0, 0),
        timestamp: int = 0,
        counter: int = 0,
        red_support: bool = False,
        code_text: str = '',
    ):
        """Initialize a SimpleLabel object."""
        # Input validation
        if width < 0 or height < 0:
            raise ValueError("Width and height must be non-negative.")
        if border_thickness < 0:
            raise ValueError("Border thickness must be non-negative.")
        if qr_size < 1:
            raise ValueError("QR size must be positive.")
        if image_scaling_factor <= 0:
            raise ValueError("Image scaling factor must be > 0.")
        if image_rotation < 0 or image_rotation > 360:
            raise ValueError("Image rotation must be between 0 and 360 inclusive.")
        self._width = width
        self._height = height
        self.label_content = label_content
        self.label_orientation = label_orientation
        self.label_type = label_type
        self.barcode_type = barcode_type
        self._label_margin = label_margin
        self._fore_color = fore_color
        self.text = None
        self.input_text = text
        self._qr_size = qr_size
        self.qr_correction = qr_correction
        self._image = image
        self._image_fit = image_fit
        self._image_scaling_factor = image_scaling_factor
        self._image_rotation = image_rotation
        self._border_thickness = border_thickness
        self._border_roundness = border_roundness
        self._border_distance = border_distance
        self._border_color = border_color
        self._counter = counter
        self._timestamp = timestamp
        self._red_support = red_support
        self._code_text = code_text

    @property
    def label_content(self):
        return self._label_content

    @label_content.setter
    def label_content(self, value):
        self._label_content = value

    def want_text(self, img: Optional[Image.Image]) -> bool:
        """Determine if text should be drawn on the label."""

        # If we are not drawing an image, we need to draw text or the label will
        # vanish
        if img is None:
            return True

        # If we want to draw only a code, suppress any text
        if self._label_content in (LabelContent.QRCODE_ONLY,):
            return False

        # If we are drawing an image, we want to draw text as well if there is
        # at least one line of text with non-empty content
        logger.debug(f"Text content: {self.text}")
        if self.text and any(line.get('text', '').strip() != '' for line in self.text):
            return True

        # Don't draw any text
        return False

    @property
    def need_image_text_distance(self):
        return self._label_content in (LabelContent.TEXT_QRCODE,
                                       LabelContent.IMAGE_BW,
                                       LabelContent.IMAGE_GRAYSCALE,
                                       LabelContent.IMAGE_RED_BLACK,
                                       LabelContent.IMAGE_COLORED)

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value

    @property
    def qr_correction(self):
        for key, val in self.QR_CORRECTION_MAPPING.items():
            if val == self._qr_correction:
                return key
        return 'L'

    @qr_correction.setter
    def qr_correction(self, value):
        self._qr_correction = self.QR_CORRECTION_MAPPING.get(value, constants.ERROR_CORRECT_L)

    @property
    def label_orientation(self):
        return self._label_orientation

    @label_orientation.setter
    def label_orientation(self, value):
        self._label_orientation = value

    @property
    def label_type(self):
        return self._label_type

    @label_type.setter
    def label_type(self, value):
        self._label_type = value

    def process_templates(self) -> None:
        """Process and replace templates in the text lines."""
        self.text = copy.deepcopy(self.input_text)
        for line in self.text:
            text_val = line.get('text', '')
            if len(text_val) > WARNING_TEXT_LENGTH:
                logger.warning(
                    f"Text line is very long (> {WARNING_TEXT_LENGTH} characters), "
                    "this may lead to long processing times.")

            # Replace {{counter[:<start>]}} with current label counter (<start> is
            # an optional offset defaulting to 1)
            def counter_replacer(match):
                offset = int(match.group(1)) if match.group(1) else 1
                return str(self._counter + offset)
            text_val = re.sub(r"\{\{counter(?:\:(\d+))?\}\}", counter_replacer, text_val)

            # Replace {{datetime:<format>}} with current datetime formatted as <format>
            def datetime_replacer(match):
                fmt = match.group(1)
                now = datetime.datetime.fromtimestamp(self._timestamp) if self._timestamp > 0 else datetime.datetime.now()
                return now.strftime(fmt)
            text_val = re.sub(r"\{\{datetime:([^}]+)\}\}", datetime_replacer, text_val)

            # Replace {{uuid}} with a new UUID
            if "{{uuid}}" in text_val:
                ui = uuid.UUID(int=random.getrandbits(128))
                text_val = text_val.replace("{{uuid}}", str(ui))

            # Replace {{short-uuid}} with a shortened UUID
            if "{{short-uuid}}" in text_val:
                ui = uuid.UUID(int=random.getrandbits(128))
                text_val = text_val.replace("{{short-uuid}}", str(ui)[:8])

            # Replace {{env:<var>}} with the value of the environment variable var
            def env_replacer(match):
                var_name = match.group(1)
                return os.getenv(var_name, "")
            text_val = re.sub(r"\{\{env:([^}]+)\}\}", env_replacer, text_val)

            # Replace {{random[:<len>][:shift]}} with random string of optional
            # length <len> and shifting instruction. ":s" is accepted as
            # shorthand for ":shift"
            def random_replacer(match):
                length = int(match.group(1)) if match.group(1) else DEFAULT_RANDOM_LENGTH
                if match.group(2):
                    line['shift'] = True
                return ''.join(random.choices(string.ascii_letters + string.digits + string.punctuation, k=length))
            text_val = re.sub(r"\{\{random(?:\:(\d+))?(?:\:(s(hift)?))?\}\}", random_replacer, text_val)

            line['text'] = text_val

    def generate(self, rotate: bool = False):
        # Process possible templates in the text
        self.process_templates()

        # Generate codes or load images if requested
        if self._label_content in (LabelContent.QRCODE_ONLY, LabelContent.TEXT_QRCODE):
            if self.barcode_type == "QR":
                img = self._generate_qr()
            else:
                img = self._generate_barcode()
        elif self._label_content in (LabelContent.IMAGE_BW, LabelContent.IMAGE_GRAYSCALE, LabelContent.IMAGE_RED_BLACK, LabelContent.IMAGE_COLORED):
            img = self._image
        else:
            img = None

        # Initialize dimensions
        width, height = self._width, self._height
        margin_left, margin_right, margin_top, margin_bottom = self._label_margin

        # Resize image to fit if image_fit is True
        if img is not None:
            # First rotate the image if requested
            if self._image_rotation != 0 and self._image_rotation != 360:
                img = img.rotate(-self._image_rotation, expand=True, fillcolor="white")
            # Resize image to fit if image_fit is True
            if self._image_fit:
                # Calculate the maximum allowed dimensions
                max_width = max(width - margin_left - margin_right, 1)
                max_height = max(height - margin_top - margin_bottom, 1)

                # Get image dimensions
                img_width, img_height = img.size

                # Print the original image size
                logger.debug(f"Maximal allowed dimensions: {max_width}x{max_height} mm")
                logger.debug(f"Original image size: {img_width}x{img_height} px")

                # Resize the image to fit within the maximum dimensions
                scale = 1.0
                if self._label_orientation == LabelOrientation.STANDARD:
                    if self._label_type in (LabelType.ENDLESS_LABEL,):
                        # Only width is considered for endless label without rotation
                        scale = max_width / img_width
                    else:
                        # Both dimensions are considered for standard label
                        scale = min(max_width / img_width, max_height / img_height)
                else:
                    if self._label_type in (LabelType.ENDLESS_LABEL,):
                        # Only height is considered for endless label without rotation
                        scale = max_height / img_height
                    else:
                        # Both dimensions are considered for standard label
                        scale = min(max_width / img_width, max_height / img_height)
                logger.debug(f"Scaling image by factor: {scale}")
                new_size = (int(img_width * scale), int(img_height * scale))
                logger.debug(f"Resized image size: {new_size} px")
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                # Update image dimensions
                img_width, img_height = img.size
            else:
                # Use image_scaling_factor if provided
                img_width, img_height = img.size
                scale = self._image_scaling_factor / 100.0
                logger.debug(f"Manual image scaling factor: {scale}")
                new_size = (int(img_width * scale), int(img_height * scale))
                logger.debug(f"Resized image size: {new_size} px")
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                img_width, img_height = img.size
        else:
            img_width, img_height = (0, 0)

        if self.want_text(img):
            bboxes = self._draw_text(None, [])
            textsize = self._compute_bbox(bboxes)
        else:
            bboxes = []
            textsize = (0, 0, 0, 0)

        # Adjust label size for endless label
        if self._label_orientation == LabelOrientation.STANDARD:
            if self._label_type in (LabelType.ENDLESS_LABEL,):
                height = img_height + textsize[3] - textsize[1] + margin_top + margin_bottom
        elif self._label_orientation == LabelOrientation.ROTATED:
            if self._label_type in (LabelType.ENDLESS_LABEL,):
                width = img_width + textsize[2] + margin_left + margin_right

        if self._label_orientation == LabelOrientation.STANDARD:
            if self._label_type in (LabelType.DIE_CUT_LABEL, LabelType.ROUND_DIE_CUT_LABEL):
                vertical_offset_text = (height - img_height - textsize[3])//2
                vertical_offset_text += (margin_top - margin_bottom)//2
            else:
                vertical_offset_text = margin_top
                if self.need_image_text_distance:
                    # Slightly increase the margin to get some distance from the
                    # QR code
                    vertical_offset_text *= 1.25

            vertical_offset_text += img_height
            horizontal_offset_text = max((width - textsize[2])//2, 0)
            horizontal_offset_image = (width - img_width)//2
            vertical_offset_image = margin_top

        elif self._label_orientation == LabelOrientation.ROTATED:
            vertical_offset_text = (height - textsize[3])//2
            vertical_offset_text += (margin_top - margin_bottom)//2
            if self._label_type in (LabelType.DIE_CUT_LABEL, LabelType.ROUND_DIE_CUT_LABEL):
                horizontal_offset_text = max((width - img_width - textsize[2])//2, 0)
            else:
                horizontal_offset_text = margin_left
                if self.need_image_text_distance:
                    # Slightly increase the margin to get some distance from the
                    # QR code
                    horizontal_offset_text *= 1.25

            horizontal_offset_text += img_width
            horizontal_offset_image = margin_left
            vertical_offset_image = (height - img_height)//2

        text_offset = horizontal_offset_text, vertical_offset_text
        image_offset = horizontal_offset_image, vertical_offset_image

        # Ensure height and width are at least 1 to avoid generating valishing
        # preview images for empty inputs. PIL cannot store images with 0
        # width/height dimensions
        width = max(int(width), 1)
        height = max(int(height), 1)

        logger.debug(f"Image resolution: {int(width)} x {int(height)} px")
        imgResult = Image.new('RGB', (int(width), int(height)), 'white')

        if img is not None:
            imgResult.paste(img, image_offset)

        if self.want_text(img):
            self._draw_text(imgResult, bboxes, text_offset)

        # Check if the image needs rotation (only applied when generating
        # preview images)
        preview_needs_rotation = (
            self._label_orientation == LabelOrientation.ROTATED and self._label_type not in (LabelType.DIE_CUT_LABEL, LabelType.ROUND_DIE_CUT_LABEL) or \
            self._label_orientation == LabelOrientation.STANDARD and self._label_type in (LabelType.DIE_CUT_LABEL, LabelType.ROUND_DIE_CUT_LABEL)
        )
        if rotate and preview_needs_rotation:
            imgResult = imgResult.rotate(-90, expand=True)

        # Draw border if thickness > 0
        if self._border_thickness > 0:
            draw = ImageDraw.Draw(imgResult)
            # Calculate border rectangle (inside the image, respecting thickness)
            rect = [self._border_distance[0],
                    self._border_distance[1],
                    imgResult.width - self._border_distance[0] - 1,
                    imgResult.height - self._border_distance[1] - 1]
            # Validity checks on rect:
            # - x1 >= x0
            # - y1 >= y0
            if rect[2] < rect[0] or rect[3] < rect[1]:
                raise ValueError("Invalid border rectangle")

            # Draw (rounded) rectangle
            draw.rounded_rectangle(rect, radius=self._border_roundness, outline=self._border_color, width=self._border_thickness)
        return imgResult

    def _generate_barcode(self):
        barcode_generator = barcode.get_barcode_class(self.barcode_type)
        if len(self._code_text) > 0:
            value = self._code_text
        else:
            # Take value from the first line of text
            value = self.text[0].get('text', '') if self.text and self.text[0].get('text', '') else ''
        my_barcode = barcode_generator(value, writer=ImageWriter())
        return my_barcode.render()

    def _generate_qr(self):
        qr = QRCode(
            version=1,
            error_correction=self._qr_correction,
            box_size=self._qr_size,
            border=0,
        )
        if len(self._code_text) > 0:
            text = self._code_text
        else:
            # Combine texts from all lines for QR code
            text = "\n".join(line.get('text', '') for line in self.text)
        qr.add_data(text.encode("utf-8-sig"))
        qr.make(fit=True)
        fill_color = 'red' if self._fore_color == (255, 0, 0) else 'black'
        qr_img = qr.make_image(fill_color=fill_color, back_color="white")
        return qr_img

    def _draw_text(self, img = None, bboxes = [], text_offset = (0, 0)):
        """
        Returns a list of bounding boxes for each line, so each line can use a different font.
        """
        do_draw = img is not None
        if not do_draw:
            img = Image.new('L', (20, 20), 'white')
        draw = ImageDraw.Draw(img)
        y = 0

        # Iterate over lines of text
        for i, line in enumerate(self.text):
            # Calculate spacing
            spacing = int(int(line['size'])*((int(line['line_spacing']) - 100) / 100)) if 'line_spacing' in line else 0

            # Get font
            font = self._get_font(line['path'], line['size'])

            # Determine anchors
            anchor = None
            align = line.get('align', 'center')

            # Left aligned text
            if align == "left":
                anchor = "lt"
            # Center aligned text
            elif align == "center":
                anchor = "mt"
            # Right aligned text
            elif align == "right":
                anchor = "rt"
            # else: error
            else:
                raise ValueError(f"Unsupported alignment: {align}")

            red_font = 'color' in line and line['color'] == 'red'
#            if red_font and not self._red_support:
#                raise ValueError("Red font is not supported on this label")
            color = (255, 0, 0) if red_font else (0, 0, 0)

            # Draw checkbox if needed
            checkbox = line.get('checkbox', False)

            INVERT_LINE = 'inverted' in line and line['inverted']
            if do_draw and INVERT_LINE:
                # Draw a filled rectangle
                center_x = 0
                if anchor == "lt":
                    min_bbox_x = text_offset[0] + min(bbox[0][0] for bbox in bboxes)
                    max_bbox_x = text_offset[0] + bboxes[i][0][2] # max(bbox[0][2] for bbox in bboxes)
                elif anchor == "mt":
                    min_bbox_x = min(bbox[0][0] for bbox in bboxes)
                    max_bbox_x = max(bbox[0][2] for bbox in bboxes)
                    center_x = (min_bbox_x + max_bbox_x) // 2
                    min_bbox_x = text_offset[0] + center_x - (bboxes[i][0][2] - bboxes[i][0][0]) // 2
                    max_bbox_x = text_offset[0] + center_x + (bboxes[i][0][2] - bboxes[i][0][0]) // 2
                elif anchor == "rt":
                    max_bbox_x = text_offset[0] + max(bbox[0][2] for bbox in bboxes)
                    min_bbox_x = max_bbox_x - (bboxes[i][0][2] - bboxes[i][0][0])
                shift = 0.1 * int(line['size'])
                y_min = bboxes[i][0][1] + text_offset[1] - shift
                y_max = bboxes[i][0][3] + text_offset[1] - shift
                draw.rectangle((min_bbox_x, y_min, max_bbox_x, y_max), fill=color)
                # Overwrite font color with white on colored background
                color = (255, 255, 255)

            # Either calculate bbox or actually draw
            if not do_draw:
                # Get bbox of the text
                bbox = draw.textbbox((0, y), line['text'], font=font, align=align, anchor="lt")

                # Ensure consistent line heights for each line except the last
                # one (where it is not needed). We still need this when
                # inverting text to ensure the inversion box is large enough to
                # hold the entire text
                IS_LAST_LINE = i == len(self.text) - 1
                if not IS_LAST_LINE or INVERT_LINE:
                    # Some characters may need special height
                    all_characters = ''.join(string.ascii_letters + string.digits + string.punctuation)
                    Ag = draw.textbbox((0, y), all_characters, font, anchor="lt")
                    # Get bbox with width of text and dummy height
                    bbox = (bbox[0], Ag[1], bbox[2], Ag[3])
                bboxes.append((bbox, y))
                y += bbox[3] - bbox[1] + (spacing if i < len(self.text)-1 else 0)
            else:
                bbox = bboxes[i][0]
                y = bboxes[i][1] + text_offset[1]
                # Left aligned text
                if align == "left":
                    min_bbox_x = min(bbox[0][0] for bbox in bboxes) if len(bboxes) > 0 else 0
                    x = min_bbox_x + text_offset[0]
                # Center aligned text
                elif align == "center":
                    min_bbox_x = min(bbox[0][0] for bbox in bboxes) if len(bboxes) > 0 else 0
                    max_bbox_x = max(bbox[0][2] for bbox in bboxes) if len(bboxes) > 0 else 0
                    x = (max_bbox_x - min_bbox_x) // 2 + min_bbox_x + text_offset[0]
                # Right aligned text
                elif align == "right":
                    max_bbox_x = max(bbox[0][2] for bbox in bboxes) if len(bboxes) > 0 else 0
                    x = max_bbox_x + text_offset[0]

                # Draw checkbox if needed
                if checkbox:
                    checkbox_box_dimensions = 8 * int(line['size']) // 10
                    bbox = draw.textbbox((x - 1.2 * checkbox_box_dimensions, y), line['text'], font=font, align=align, anchor=anchor)
                    box_dimensions = bbox[0], y, bbox[0] + checkbox_box_dimensions, y + checkbox_box_dimensions
                    draw.rounded_rectangle(box_dimensions, radius=5, outline=color, width=max(1, checkbox_box_dimensions//10), fill=(255,255,255))

                draw.text((x, y), line['text'], color, font=font, anchor=anchor, align=align, spacing=spacing)

                # Shift text around if requested
                if "shift" in line:
                    def get_shift_amount():
                        return 0.03 * random.randint(5, 10) * int(line['size'])
                    for x_shift in [-get_shift_amount(), get_shift_amount()]:
                        for y_shift in [-get_shift_amount(), get_shift_amount()]:
                            new_random_text = ''.join(random.choices(string.ascii_letters + string.digits + string.punctuation, k=len(line['text'])))
                            draw.text((x + x_shift, y + y_shift), new_random_text, color, font=font, anchor=anchor, align=align, spacing=spacing)

        # Return total bbox
        # each in form (x0, y0, x1, y1)
        return bboxes

    def _compute_bbox(self, bboxes):
        # Edge case: No text
        if not bboxes:
            return (0, 0, 0, 0)
        # Iterate over right margins of multiple text lines and find the maximum
        # width needed to fit all lines of text
        max_width = max(bbox[0][2] for bbox in bboxes)
        return (bboxes[0][0][0], bboxes[0][0][1], max_width, bboxes[-1][0][3])

    def _get_font(self, font_path: str, size: int) -> ImageFont.FreeTypeFont:
        """Get a font object, using cache for performance."""
        key = (font_path, size)
        if key in FONT_CACHE:
            return FONT_CACHE[key]
        try:
            font = ImageFont.truetype(font_path, int(size))
            FONT_CACHE[key] = font
            return font
        except Exception as e:
            logger.error(f"Failed to load font '{font_path}' with size {size}: {e}")
            return ImageFont.load_default()


class ShippingLabel:
    """
    Renders a structured shipping label with sender, recipient address blocks
    and an optional tracking-number QR code. Designed for continuous tape
    (e.g. DK-22205 62 mm). Works with fixed-size die-cut labels too (content
    is clipped to the canvas).

    German field names are used on the label ("Von:" / "An:").
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
        sender_line_spacing: int = 100,
        recipient_line_spacing: int = 100,
    ):
        """
        :param sender:               dict with keys: name, street, zip_city, country
        :param recipient:            dict with keys: company (optional), name, street,
                                     zip_city, country
        :param font_path:            font for recipient section (and fallback)
        :param sender_font_path:     font for sender section (defaults to font_path)
        :param tracking_barcode_type: barcode type for tracking number ('code128', 'qr', etc.)
        :param sender_font_size:     base font size for sender section (0 = auto)
        :param recipient_font_size:  base font size for recipient section (0 = auto)
        :param margin:               (left, right, top, bottom) in pixels
        :param section_spacing:       extra gap (px) at the From/To divider; 0 = auto
        :param barcode_scale:         tracking barcode scale as percentage of default; 0 = auto
        :param barcode_show_text:     embed tracking number text inside the barcode image
        :param from_label:            override the "From:" section header (empty = default)
        :param to_label:              override the "To:" section header (empty = default)
        :param recipient_border:      draw a rectangle border around the recipient block
        :param sender_line_spacing:   line spacing % for sender section (100 = normal)
        :param recipient_line_spacing: line spacing % for recipient section (100 = normal)
        """
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
        # Shipping labels are always rendered as structured text (not an image)
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
        """Generate a tracking-number barcode or QR image (no text embedded)."""
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

    def _build_line_lists(self, font_section, font_sender, font_rname, font_rdetail,
                          sender_pad: int, recip_pad: int):
        """Build (text, font, color, extra_top_padding) tuples for sender and recipient."""
        COLOR_GRAY  = (130, 130, 130)
        COLOR_BLACK = (0, 0, 0)

        sender_lines: List[Tuple[str, Any, Tuple, int]] = [
            (self._from_label, font_section, COLOR_GRAY, 0),
        ]
        if self.sender.get('name'):
            sender_lines.append((self.sender['name'], font_sender, COLOR_BLACK, sender_pad))
        if self.sender.get('street'):
            sender_lines.append((self.sender['street'], font_sender, COLOR_BLACK, 0))
        addr_parts = [p for p in [self.sender.get('zip_city'), self.sender.get('country')] if p]
        if addr_parts:
            sender_lines.append((" \u00b7 ".join(addr_parts), font_sender, COLOR_BLACK, 0))

        recip_lines: List[Tuple[str, Any, Tuple, int]] = [
            (self._to_label, font_section, COLOR_GRAY, 0),
        ]
        if self.recipient.get('company'):
            recip_lines.append((self.recipient['company'], font_rdetail, COLOR_BLACK, recip_pad))
        if self.recipient.get('name'):
            recip_lines.append((self.recipient['name'], font_rname, COLOR_BLACK, recip_pad))
        if self.recipient.get('street'):
            recip_lines.append((self.recipient['street'], font_rdetail, COLOR_BLACK, recip_pad))
        if self.recipient.get('zip_city'):
            recip_lines.append((self.recipient['zip_city'], font_rdetail, COLOR_BLACK, 0))
        if self.recipient.get('country'):
            recip_lines.append((self.recipient['country'], font_rdetail, COLOR_BLACK, 0))

        return sender_lines, recip_lines

    def _generate_landscape(self) -> Image.Image:
        """
        Landscape layout for endless tape.  The tape's 62 mm dimension becomes
        the image HEIGHT; width grows to fit content.  Sender is on the left,
        recipient on the right, optional code column at the far right.

        All font sizes are derived dynamically from the number of visible
        recipient fields so that the content fills the full tape height
        (rather than occupying only the top quarter at fixed small sizes).
        """
        ml, mr, mt, mb = self._margin
        canvas_h  = max(self._height, 1)
        usable_h  = max(canvas_h - mt - mb, 1)

        COLOR_GRAY  = (130, 130, 130)
        COLOR_BLACK = (0, 0, 0)
        # Scale gaps with tape height so they stay proportional at 600dpi
        DIVIDER_GAP = (self._section_spacing if self._section_spacing > 0
                       else max(int(usable_h * 0.04), 24))
        CODE_GAP    = max(int(usable_h * 0.03), 20)

        # ── 1. Dynamic font sizing ────────────────────────────────────────────
        # Count visible recipient content lines (excluding the "To:" header).
        n_recip = sum(1 for k in ('company', 'name', 'street', 'zip_city', 'country')
                      if self.recipient.get(k))
        n_recip = max(1, min(5, n_recip))

        # Budget per recipient line (0.5 extra slot allocated for the header).
        line_h = usable_h / (n_recip + 0.5)

        # Per-section font size overrides (0 = use dynamic default)
        # Reference base size = 48 (app default).  Scale factor relative to that.
        S_SCALE = (self._sender_font_size / 48.0) if self._sender_font_size > 0 else 1.0
        R_SCALE = (self._recipient_font_size / 48.0) if self._recipient_font_size > 0 else 1.0

        # Recipient sizes: dynamic with per-role minimum, then optionally boosted by R_SCALE
        sz_rname    = max(int(line_h * 1.00), max(int(110 * R_SCALE), 40))
        sz_rdetail  = max(int(line_h * 0.82), max(int( 90 * R_SCALE), 32))
        sz_to       = max(int(line_h * 0.48), max(int( 52 * R_SCALE), 20))
        # Sender sizes: dynamic with per-role minimum, then optionally boosted by S_SCALE
        sz_sender   = max(int(line_h * 0.46), max(int( 48 * S_SCALE), 18))
        sz_from     = max(int(line_h * 0.26), max(int( 30 * S_SCALE), 12))
        sz_tracking = max(int(line_h * 0.14), 22)

        sfp = self._sender_font_path   # sender font path (may differ from recipient)
        font_rname    = self._get_font(sz_rname)
        font_rdetail  = self._get_font(sz_rdetail)
        font_to       = self._get_font(sz_to)
        font_sender   = self._get_font(sz_sender, sfp)
        font_from     = self._get_font(sz_from,   sfp)
        font_tracking = self._get_font(sz_tracking)

        # ── 2. Measurement canvas ─────────────────────────────────────────────
        dummy  = Image.new('RGB', (16000, canvas_h), 'white')
        draw_m = ImageDraw.Draw(dummy)

        # ── 3. Text-wrap helper ───────────────────────────────────────────────
        def wrap_text(text: str, font, max_px: int) -> List[str]:
            """Break text at word boundaries; char-level fallback for long words."""
            if not text:
                return []
            words = text.split()
            lines: List[str] = []
            current = ''
            for word in words:
                candidate = (current + ' ' + word).strip()
                bb = draw_m.textbbox((0, 0), candidate, font=font, anchor='lt')
                if bb[2] - bb[0] <= max_px:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    bb_w = draw_m.textbbox((0, 0), word, font=font, anchor='lt')
                    if bb_w[2] - bb_w[0] <= max_px:
                        current = word
                    else:
                        # Character-level fallback (rare: very long compound words)
                        current = ''
                        for ch in word:
                            trial = current + ch
                            bb_c = draw_m.textbbox((0, 0), trial, font=font, anchor='lt')
                            if bb_c[2] - bb_c[0] <= max_px:
                                current = trial
                            else:
                                lines.append(current)
                                current = ch
            if current:
                lines.append(current)
            return lines or ['']

        # ── 4. Build sender line list (with wrapping) ─────────────────────────
        SENDER_WRAP_PX = int(usable_h * 1.8)   # generous budget for sender column

        sender_lines: List[Tuple[str, Any, Tuple, int]] = [
            (self._from_label, font_from, COLOR_GRAY, 0),
        ]
        for field, base_pad in [
            (self.sender.get('name',   ''), 4),
            (self.sender.get('street', ''), 0),
        ]:
            if field:
                for i, row in enumerate(wrap_text(field, font_sender, SENDER_WRAP_PX)):
                    sender_lines.append((row, font_sender, COLOR_BLACK, base_pad if i == 0 else 2))

        addr_parts = [p for p in [self.sender.get('zip_city'), self.sender.get('country')] if p]
        if addr_parts:
            combined = ' \u00b7 '.join(addr_parts)
            for i, row in enumerate(wrap_text(combined, font_sender, SENDER_WRAP_PX)):
                sender_lines.append((row, font_sender, COLOR_BLACK, 0 if i == 0 else 2))

        # ── 5. Build recipient line list (with wrapping) ──────────────────────
        RECIP_WRAP_PX = int(usable_h * 3.0)   # wide budget; wraps only very long lines

        recip_lines: List[Tuple[str, Any, Tuple, int]] = [
            (self._to_label, font_to, COLOR_GRAY, 0),
        ]
        recip_fields = []
        if self.recipient.get('company'):
            recip_fields.append((self.recipient['company'], font_rdetail, 6))
        if self.recipient.get('name'):
            recip_fields.append((self.recipient['name'],    font_rname,   6))
        if self.recipient.get('street'):
            recip_fields.append((self.recipient['street'],  font_rdetail, 6))
        if self.recipient.get('zip_city'):
            recip_fields.append((self.recipient['zip_city'], font_rdetail, 0))
        if self.recipient.get('country'):
            recip_fields.append((self.recipient['country'],  font_rdetail, 0))

        for field_text, font_obj, base_pad in recip_fields:
            for i, row in enumerate(wrap_text(field_text, font_obj, RECIP_WRAP_PX)):
                recip_lines.append((row, font_obj, COLOR_BLACK, base_pad if i == 0 else 2))

        # ── 6. Measure column widths from actual (post-wrap) text ─────────────
        def col_width(lines_list, min_w: int) -> int:
            max_w = min_w
            for text, font, _, _ in lines_list:
                if not text:
                    continue
                bb = draw_m.textbbox((0, 0), text, font=font, anchor='lt')
                max_w = max(max_w, bb[2] - bb[0])
            return max_w

        sender_col_w = col_width(sender_lines, 200)
        recip_col_w  = col_width(recip_lines,  300)

        # ── 7. Tracking code — scaled to fill tape height, rotated for 1D ─────
        code_img    = None
        code_col_w  = 0
        tracking_tw = 0
        tracking_th = 0

        if self.tracking_number:
            raw_code = self._generate_tracking_image(write_text=self._barcode_show_text)
            if raw_code is not None:
                _bscale = (self._barcode_scale / 100.0) if self._barcode_scale > 0 else 1.0
                if self._tracking_barcode_type == 'qr':
                    # QR: scale to ~85% of tape height (adjusted by barcode_scale), square
                    side = max(int(usable_h * 0.85 * _bscale), 8)
                    code_img = raw_code.resize((side, side), Image.Resampling.LANCZOS)
                else:
                    # 1D barcode: rotate 90° so it runs vertically along the tape
                    rotated = raw_code.rotate(90, expand=True)
                    target_h = max(int(usable_h * _bscale), 8)
                    scale    = target_h / rotated.height
                    new_w    = max(int(rotated.width * scale), 1)
                    code_img = rotated.resize((new_w, target_h), Image.Resampling.LANCZOS)

                tb = draw_m.textbbox((0, 0), self.tracking_number, font=font_tracking, anchor='lt')
                tracking_tw = tb[2] - tb[0]
                tracking_th = tb[3] - tb[1]

                code_col_w = CODE_GAP + max(code_img.width, tracking_tw)

        # ── 8. Compose canvas ─────────────────────────────────────────────────
        canvas_w = (ml + sender_col_w + DIVIDER_GAP + 1 + DIVIDER_GAP
                    + recip_col_w + code_col_w + mr)
        img  = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(img)

        # ── 9. Sender column — vertically centered ────────────────────────────
        sender_ls_px = max(0, int(sz_sender * (self._sender_line_spacing - 100) / 100))
        recip_ls_px  = max(0, int(sz_rdetail * (self._recipient_line_spacing - 100) / 100))

        def block_height(lines_list, ls_px=0) -> int:
            total = 0
            for text, font, _, extra_top in lines_list:
                if not text:
                    continue
                bb = draw_m.textbbox((0, 0), text or ' ', font=font, anchor='lt')
                total += extra_top + (bb[3] - bb[1]) + ls_px
            return total

        sender_block_h = block_height(sender_lines, sender_ls_px)
        y = mt + max((usable_h - sender_block_h) // 2, 0)

        for text, font, color, extra_top in sender_lines:
            if not text:
                continue
            y += extra_top
            draw.text((ml, y), text, fill=color, font=font, anchor='lt')
            bb = draw.textbbox((ml, y), text, font=font, anchor='lt')
            y += bb[3] - bb[1] + sender_ls_px

        # ── 10. Dashed vertical divider ───────────────────────────────────────
        div_x = ml + sender_col_w + DIVIDER_GAP
        _draw_dashed_line(draw, div_x, mt, div_x, canvas_h - mb,
                          fill=(180, 180, 180), width=2, dash_len=10, gap_len=6)

        # ── 11. Recipient column — top-aligned ────────────────────────────────
        rx = div_x + 1 + DIVIDER_GAP
        y  = mt
        recip_block_y_start = y
        for text, font, color, extra_top in recip_lines:
            if not text:
                continue
            y += extra_top
            draw.text((rx, y), text, fill=color, font=font, anchor='lt')
            bb = draw.textbbox((rx, y), text, font=font, anchor='lt')
            y += bb[3] - bb[1] + recip_ls_px
        recip_block_y_end = y

        if self._recipient_border:
            PAD = max(int(usable_h * 0.03), 6)
            draw.rectangle(
                [rx - PAD, recip_block_y_start - PAD,
                 rx + recip_col_w + PAD, recip_block_y_end + PAD],
                outline=COLOR_BLACK, width=2,
            )

        # ── 12. Tracking code — vertically centered in code column ────────────
        if code_img:
            code_x = rx + recip_col_w + CODE_GAP
            code_y = mt + max((usable_h - code_img.height) // 2, 0)
            img.paste(code_img, (code_x, code_y))
            # QR codes can't embed text; draw it below the image when requested
            if self._barcode_show_text and self._tracking_barcode_type == 'qr' and tracking_th:
                ty = code_y + code_img.height + 6
                if ty + tracking_th <= canvas_h - mb:
                    draw.text((code_x, ty), self.tracking_number,
                              fill=COLOR_BLACK, font=font_tracking, anchor='lt')

        return img

    def _generate_portrait(self) -> Image.Image:
        """
        Portrait layout for die-cut labels (fixed width × height).
        Stacks sender and recipient vertically with a dashed horizontal divider.
        """
        ml, mr, mt, mb = self._margin
        usable_width = max(self._width - ml - mr, 1)

        sfp = self._sender_font_path

        # Scale factor relative to reference size 48 (app default font_size).
        S_SCALE = (self._sender_font_size / 48.0) if self._sender_font_size > 0 else 1.0
        R_SCALE = (self._recipient_font_size / 48.0) if self._recipient_font_size > 0 else 1.0

        font_section = self._get_font(max(int(16 * max(S_SCALE, R_SCALE)), 10))
        font_sender  = self._get_font(max(int(20 * S_SCALE), 10), sfp)
        font_rname   = self._get_font(max(int(28 * R_SCALE), 12))
        font_rdetail = self._get_font(max(int(22 * R_SCALE), 10))

        COLOR_GRAY  = (130, 130, 130)
        COLOR_BLACK = (0, 0, 0)
        # Scale DIVIDER_H with usable_width so it stays proportional at any DPI
        DIVIDER_H   = (self._section_spacing if self._section_spacing > 0
                       else max(int(usable_width * 0.04), 18))

        sender_lines, recip_lines = self._build_line_lists(
            font_section, font_sender, font_rname, font_rdetail,
            sender_pad=3, recip_pad=5,
        )

        dummy  = Image.new('RGB', (usable_width, 20), 'white')
        draw_m = ImageDraw.Draw(dummy)

        sender_ls_px = max(0, int(font_sender.size * (self._sender_line_spacing - 100) / 100))
        recip_ls_px  = max(0, int(font_rdetail.size * (self._recipient_line_spacing - 100) / 100))

        def measure_h(lines_list, ls_px=0):
            total = 0
            for text, font, _, extra in lines_list:
                bb = draw_m.textbbox((0, 0), text or " ", font=font, anchor="lt")
                total += extra + (bb[3] - bb[1]) + ls_px
            return total

        sender_h = measure_h(sender_lines, sender_ls_px)
        recip_h  = measure_h(recip_lines, recip_ls_px)

        # ── Tracking code (full-width barcode or QR) ──────────────────────────
        code_img        = None
        code_h          = 0
        tracking_text_h = 0
        font_tracking   = self._get_font(14)

        if self.tracking_number:
            raw_code = self._generate_tracking_image(write_text=self._barcode_show_text)
            if raw_code is not None:
                _bscale = (self._barcode_scale / 100.0) if self._barcode_scale > 0 else 1.0
                if self._tracking_barcode_type == 'qr':
                    # QR: fixed square, ~28% of label width (adjusted by barcode_scale)
                    side     = max(min(int(usable_width * 0.28 * _bscale), 110), 8)
                    code_img = raw_code.resize((side, side), Image.Resampling.NEAREST)
                else:
                    # 1D barcode: scale to full usable width (adjusted by barcode_scale)
                    target_w = max(int(usable_width * _bscale), 8)
                    scale    = target_w / raw_code.width
                    new_h    = max(int(raw_code.height * scale), 1)
                    code_img = raw_code.resize((target_w, new_h), Image.Resampling.LANCZOS)
                code_h = code_img.height
                tb = draw_m.textbbox((0, 0), self.tracking_number, font=font_tracking, anchor="lt")
                tracking_text_h = tb[3] - tb[1]

        code_row_h = (code_h + (8 + tracking_text_h if self._tracking_barcode_type != 'qr' else 0) + 14) if code_img else 0
        if self._tracking_barcode_type == 'qr' and code_img:
            code_row_h = max(code_img.height, tracking_text_h) + 14

        total_h = mt + sender_h + DIVIDER_H * 2 + 1 + recip_h + code_row_h + mb

        canvas_h = max(self._height, 1) if self._height else max(int(total_h), 1)
        canvas_w = max(self._width, 1)

        img  = Image.new('RGB', (canvas_w, canvas_h), 'white')
        draw = ImageDraw.Draw(img)

        y = mt

        def draw_lines(lines_list, ls_px=0):
            nonlocal y
            for text, font, color, extra_top in lines_list:
                if not text:
                    continue
                y += extra_top
                draw.text((ml, y), text, fill=color, font=font, anchor="lt")
                bb = draw.textbbox((ml, y), text, font=font, anchor="lt")
                y += bb[3] - bb[1] + ls_px

        draw_lines(sender_lines, sender_ls_px)

        y += DIVIDER_H
        _draw_dashed_line(draw, ml, y, canvas_w - mr, y,
                          fill=(170, 170, 170), width=2, dash_len=10, gap_len=6)
        y += 1 + DIVIDER_H

        recip_y_start = y
        draw_lines(recip_lines, recip_ls_px)
        recip_y_end = y

        if self._recipient_border:
            PAD = max(int(usable_width * 0.02), 4)
            draw.rectangle(
                [ml - PAD, recip_y_start - PAD,
                 canvas_w - mr + PAD, recip_y_end + PAD],
                outline=COLOR_BLACK, width=2,
            )

        if code_img:
            y += 14
            if self._tracking_barcode_type == 'qr':
                # QR: paste at left; draw tracking number to the right when requested
                img.paste(code_img, (ml, y))
                if self._barcode_show_text and tracking_text_h:
                    tx = ml + code_img.width + 12
                    ty = y + max((code_img.height - tracking_text_h) // 2, 0)
                    if tx + 20 <= canvas_w - mr:
                        draw.text((tx, ty), self.tracking_number,
                                  fill=COLOR_BLACK, font=font_tracking, anchor="lt")
            else:
                # 1D barcode: full-width; text is embedded in the image via write_text
                img.paste(code_img, (ml, y))

        return img
