"""Shared utilities and constants for label rendering."""

from PIL import ImageFont
from typing import Dict, Tuple

# Shared font cache to avoid reloading fonts on every render
FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}

# Text length above which a warning is logged
WARNING_TEXT_LENGTH = 500
# Default length for {{random}} template output
DEFAULT_RANDOM_LENGTH = 64
# Default font size fallback
DEFAULT_FONT_SIZE = 12


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
