"""
NEXUS BET - Signal Card Generator
Generates premium dark signal cards as PNG images for Telegram send_photo().
Style: dark bg #0A0A0A, white text, gold accent #B8963E
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any

log = logging.getLogger("nexus.signal_card")

# ── Design constants ──
BG_COLOR = (10, 10, 10)          # #0A0A0A
CARD_COLOR = (18, 18, 18)        # #121212
GOLD = (184, 150, 62)            # #B8963E
GOLD_LIGHT = (220, 190, 100)     # lighter gold for values
WHITE = (240, 240, 240)          # #F0F0F0
GRAY = (120, 120, 120)           # #787878
GREEN = (76, 175, 80)            # #4CAF50 BUY
RED = (244, 67, 54)              # #F44336 SELL
STRONG_BUY_COLOR = (255, 193, 7) # #FFC107 STRONG_BUY

CARD_W = 600
CARD_H = 320
PADDING = 28
CORNER_R = 16


def _get_fonts(font_size_title: int = 22, font_size_label: int = 13, font_size_value: int = 16):
    """Load fonts with graceful fallback to default."""
    try:
        from PIL import ImageFont
        # Try system fonts
        for path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]:
            try:
                font_title = ImageFont.truetype(path, font_size_title)
                font_label = ImageFont.truetype(path, font_size_label)
                font_value = ImageFont.truetype(path, font_size_value)
                return font_title, font_label, font_value
            except (IOError, OSError):
                continue
        # Fallback to default
        font_default = ImageFont.load_default()
        return font_default, font_default, font_default
    except ImportError:
        return None, None, None


def _draw_rounded_rect(draw, xy, radius: int, fill, outline=None, width: int = 1):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.ellipse([x0, y0, x0 + 2 * radius, y0 + 2 * radius], fill=fill)
    draw.ellipse([x1 - 2 * radius, y0, x1, y0 + 2 * radius], fill=fill)
    draw.ellipse([x0, y1 - 2 * radius, x0 + 2 * radius, y1], fill=fill)
    draw.ellipse([x1 - 2 * radius, y1 - 2 * radius, x1, y1], fill=fill)
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    if outline:
        draw.arc([x0, y0, x0 + 2 * radius, y0 + 2 * radius], 180, 270, fill=outline, width=width)
        draw.arc([x1 - 2 * radius, y0, x1, y0 + 2 * radius], 270, 360, fill=outline, width=width)
        draw.arc([x0, y1 - 2 * radius, x0 + 2 * radius, y1], 90, 180, fill=outline, width=width)
        draw.arc([x1 - 2 * radius, y1 - 2 * radius, x1, y1], 0, 90, fill=outline, width=width)
        draw.line([x0 + radius, y0, x1 - radius, y0], fill=outline, width=width)
        draw.line([x0 + radius, y1, x1 - radius, y1], fill=outline, width=width)
        draw.line([x0, y0 + radius, x0, y1 - radius], fill=outline, width=width)
        draw.line([x1, y0 + radius, x1, y1 - radius], fill=outline, width=width)


def _draw_bar(draw, x: int, y: int, w: int, h: int, value: float, max_val: float = 1.0, color=GOLD):
    """Draw a progress bar."""
    pct = min(1.0, max(0.0, value / max_val)) if max_val > 0 else 0
    draw.rectangle([x, y, x + w, y + h], fill=(30, 30, 30))
    if pct > 0:
        draw.rectangle([x, y, x + int(w * pct), y + h], fill=color)


def generate_signal_card(signal: dict[str, Any]) -> bytes:
    """
    Generate a premium signal card PNG for Telegram.
    Returns PNG bytes.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        log.warning("Pillow not installed — cannot generate signal card")
        raise RuntimeError("Pillow not installed")

    img = Image.new("RGB", (CARD_W, CARD_H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    font_title, font_label, font_value = _get_fonts(22, 12, 15)

    # ── Card background ──
    _draw_rounded_rect(draw, [4, 4, CARD_W - 4, CARD_H - 4], CORNER_R, CARD_COLOR, GOLD, 1)

    # ── Gold top accent bar ──
    draw.rectangle([PADDING, PADDING, CARD_W - PADDING, PADDING + 3], fill=GOLD)

    # ── Header: NEXUS CAPITAL + signal type ──
    y = PADDING + 12
    strength = signal.get("signal_strength", "BUY")
    strength_color = STRONG_BUY_COLOR if strength == "STRONG_BUY" else GREEN
    strength_label = "⚡ STRONG BUY" if strength == "STRONG_BUY" else "▲ BUY SIGNAL"

    if font_title:
        draw.text((PADDING, y), "NEXUS CAPITAL", font=font_title, fill=GOLD)
        # Signal strength badge (right aligned)
        badge_text = strength_label
        try:
            bbox = draw.textbbox((0, 0), badge_text, font=font_label)
            badge_w = bbox[2] - bbox[0] + 16
        except Exception:
            badge_w = 100
        badge_x = CARD_W - PADDING - badge_w
        _draw_rounded_rect(draw, [badge_x, y + 2, badge_x + badge_w, y + 20], 4, strength_color)
        draw.text((badge_x + 8, y + 4), badge_text, font=font_label, fill=BG_COLOR)

    # ── Market question ──
    y += 36
    question = (signal.get("question") or signal.get("market_id", "Unknown market"))[:70]
    if len(question) >= 70:
        question = question[:67] + "..."
    if font_value:
        draw.text((PADDING, y), question, font=font_value, fill=WHITE)

    # ── Divider ──
    y += 28
    draw.line([PADDING, y, CARD_W - PADDING, y], fill=(40, 40, 40), width=1)

    # ── Metrics row ──
    y += 14
    edge_pct = float(signal.get("edge_pct", 0))
    kelly = float(signal.get("kelly_fraction", 0))
    confidence = float(signal.get("confidence", 0))
    price = float(signal.get("polymarket_price", 0.5))
    market_type = (signal.get("market_type") or "binary").upper()[:5]
    rec = signal.get("recommended_outcome") or signal.get("side", "?")

    metrics = [
        ("MARKET", market_type),
        ("OUTCOME", str(rec)[:8]),
        ("PRICE", f"${price:.3f}"),
        ("EV%", f"{edge_pct:.1f}%"),
    ]
    col_w = (CARD_W - 2 * PADDING) // len(metrics)
    for i, (label, value) in enumerate(metrics):
        cx = PADDING + i * col_w + col_w // 2
        if font_label:
            try:
                bbox = draw.textbbox((0, 0), label, font=font_label)
                lw = bbox[2] - bbox[0]
            except Exception:
                lw = 40
            draw.text((cx - lw // 2, y), label, font=font_label, fill=GRAY)
        if font_value:
            try:
                bbox = draw.textbbox((0, 0), value, font=font_value)
                vw = bbox[2] - bbox[0]
            except Exception:
                vw = 50
            val_color = GOLD_LIGHT if label == "EV%" else WHITE
            draw.text((cx - vw // 2, y + 18), value, font=font_value, fill=val_color)

    # ── Progress bars: Kelly + Confidence ──
    y += 52
    bar_section_w = (CARD_W - 2 * PADDING - 20) // 2

    # Kelly
    if font_label:
        draw.text((PADDING, y), "KELLY FRACTION", font=font_label, fill=GRAY)
        draw.text((PADDING + bar_section_w - 40, y), f"{kelly:.1%}", font=font_label, fill=GOLD_LIGHT)
    _draw_bar(draw, PADDING, y + 16, bar_section_w - 44, 8, kelly, 0.5, GOLD)

    # Confidence
    cx2 = PADDING + bar_section_w + 20
    if font_label:
        draw.text((cx2, y), "CONFIDENCE", font=font_label, fill=GRAY)
        draw.text((cx2 + bar_section_w - 40, y), f"{confidence:.0%}", font=font_label, fill=GOLD_LIGHT)
    conf_color = GREEN if confidence >= 0.7 else GOLD
    _draw_bar(draw, cx2, y + 16, bar_section_w - 44, 8, confidence, 1.0, conf_color)

    # ── Bottom divider + footer ──
    y += 42
    draw.line([PADDING, y, CARD_W - PADDING, y], fill=(40, 40, 40), width=1)
    y += 8
    if font_label:
        draw.text((PADDING, y), "NEXUS BET · Autonomous Polymarket Intelligence", font=font_label, fill=(50, 50, 50))

    # ── Export PNG bytes ──
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


def generate_signal_card_safe(signal: dict[str, Any]) -> bytes | None:
    """Returns PNG bytes or None on failure."""
    try:
        return generate_signal_card(signal)
    except Exception as e:
        log.warning("Signal card generation failed: %s", e)
        return None
