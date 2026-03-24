"""
NEXUS BET - Signal Card Image Generator
Generates premium dark signal cards using Pillow.
Dark bg #0A0A0A, white text, gold #B8963E — screenshot-worthy for affiliates.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Optional

log = logging.getLogger("nexus.signal_card")


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# Color palette
BG = _hex_to_rgb("#0A0A0A")
BG_CARD = _hex_to_rgb("#111111")
BG_CODE = _hex_to_rgb("#161616")
GOLD = _hex_to_rgb("#B8963E")
GREEN = _hex_to_rgb("#00C853")
BLUE = _hex_to_rgb("#2979FF")
WHITE = _hex_to_rgb("#FFFFFF")
GRAY = _hex_to_rgb("#888888")
BORDER = _hex_to_rgb("#2A2A2A")


def _get_fonts(size_title: int = 28, size_body: int = 18, size_small: int = 14):
    """Load fonts with fallback to default PIL font."""
    try:
        from PIL import ImageFont
        # Try system monospace fonts
        for font_path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
            "/System/Library/Fonts/Menlo.ttc",
        ]:
            try:
                ft = ImageFont.truetype(font_path, size_title)
                fb = ImageFont.truetype(font_path, size_body)
                fs = ImageFont.truetype(font_path, size_small)
                return ft, fb, fs
            except (IOError, OSError):
                continue
        # Ultimate fallback
        ft = ImageFont.load_default()
        return ft, ft, ft
    except ImportError:
        return None, None, None


def generate_signal_card(
    question: str,
    signal_strength: str,
    category: str,
    edge_pct: float,
    ev_pct: float,
    kelly_fraction: float,
    polymarket_price: float,
    fair_price: float,
    confidence: float,
    capital: float = 1000.0,
    side: str = "YES",
) -> Optional[bytes]:
    """
    Generate a premium signal card image.
    Returns PNG bytes or None if Pillow not available.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        log.debug("Pillow not installed — skipping signal card generation")
        return None

    W, H = 800, 420
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    ft, fb, fs = _get_fonts(28, 18, 14)

    is_strong = signal_strength == "STRONG_BUY"
    accent = GOLD if is_strong else BLUE
    strength_label = "⚡ STRONG BUY" if is_strong else "▲ BUY"

    # Background card with subtle border
    draw.rounded_rectangle([16, 16, W - 16, H - 16], radius=16, fill=BG_CARD, outline=BORDER, width=1)

    # Top accent bar
    draw.rounded_rectangle([16, 16, W - 16, 52], radius=16, fill=accent)
    draw.rectangle([16, 38, W - 16, 52], fill=accent)  # Square bottom of top bar

    # Header text: signal strength + category
    header = f"{strength_label}  ·  {category}"
    draw.text((36, 22), header, font=ft, fill=BG_CARD)

    # Separator
    SEP_Y = 64
    draw.line([(36, SEP_Y), (W - 36, SEP_Y)], fill=BORDER, width=1)

    # Question (truncated, wrapped)
    q = question[:80]
    if len(question) > 80:
        q = question[:77] + "..."
    draw.text((36, 78), q, font=fb, fill=WHITE)

    # Metrics grid
    GRID_Y = 148
    stake = round(capital * min(kelly_fraction, 0.05), 2)
    conf_pct = int(confidence * 100) if confidence <= 1 else int(confidence)
    conf_label = "HIGH" if conf_pct >= 80 else "MED" if conf_pct >= 60 else "LOW"

    metrics = [
        ("EV", f"+{ev_pct:.1f}%"),
        ("EDGE", f"{edge_pct:.1f}pts"),
        ("MISE", f"${stake:.2f}"),
        ("CONF", conf_label),
    ]

    col_w = (W - 72) // 4
    for i, (label, value) in enumerate(metrics):
        x = 36 + i * col_w
        # Metric box
        draw.rounded_rectangle([x, GRID_Y, x + col_w - 8, GRID_Y + 80], radius=8, fill=BG_CODE, outline=BORDER, width=1)
        # Label
        draw.text((x + 12, GRID_Y + 10), label, font=fs, fill=GRAY)
        # Value
        val_color = GREEN if "+" in value else GOLD
        draw.text((x + 12, GRID_Y + 34), value, font=fb, fill=val_color)

    # Bottom separator
    BOT_Y = GRID_Y + 100
    draw.line([(36, BOT_Y), (W - 36, BOT_Y)], fill=BORDER, width=1)

    # Footer: prices + branding
    poly_pct = round(polymarket_price * 100)
    fair_pct = round(fair_price * 100)
    footer = f"POLY: {poly_pct}%   FAIR: {fair_pct}%"
    draw.text((36, BOT_Y + 12), footer, font=fs, fill=GRAY)

    branding = "NEXUS BET"
    draw.text((W - 120, BOT_Y + 12), branding, font=fs, fill=GOLD)

    # Watermark dot
    dot_r = 5
    dot_x, dot_y = W - 140, BOT_Y + 19
    dot_fill = GREEN if is_strong else BLUE
    draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r], fill=dot_fill)

    # Export to bytes
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()
