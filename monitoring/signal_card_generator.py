"""
NEXUS BET - Signal Card Generator
Generates premium dark-themed signal card images using Pillow.
Style: dark bg #0A0A0A, white text, gold accent #B8963E
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("nexus.signal_card")

# Color palette
BG_COLOR = "#0A0A0A"
CARD_COLOR = "#111111"
GOLD = "#B8963E"
GOLD_LIGHT = "#D4AF6A"
WHITE = "#FFFFFF"
GRAY = "#888888"
GREEN = "#2ECC71"
RED = "#E74C3C"
BLUE_ACCENT = "#1A1A2E"

# Card dimensions
CARD_W = 900
CARD_H = 480


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore


def _is_pillow_available() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def generate_signal_card(signal: dict[str, Any]) -> bytes | None:
    """
    Generate a PNG signal card image for a given signal dict.
    Returns PNG bytes or None if Pillow is not installed.

    Signal dict keys: question, edge_pct, kelly_fraction, confidence,
                      polymarket_price, signal_strength, side, market_type
    """
    if not _is_pillow_available():
        log.warning("Pillow not installed — cannot generate signal card. Run: pip install Pillow")
        return None

    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (CARD_W, CARD_H), color=_hex_to_rgb(BG_COLOR))
        draw = ImageDraw.Draw(img)

        # ── Load fonts (fall back to default if not found) ──
        def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
            try:
                # Try system fonts
                for name in (
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf" if bold else
                    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
                ):
                    if os.path.exists(name):
                        return ImageFont.truetype(name, size)
            except Exception:
                pass
            return ImageFont.load_default()

        font_title = _font(28, bold=True)
        font_question = _font(20)
        font_label = _font(16)
        font_value = _font(24, bold=True)
        font_small = _font(14)
        font_badge = _font(15, bold=True)

        # ── Card background panel ──
        margin = 24
        draw.rounded_rectangle(
            [margin, margin, CARD_W - margin, CARD_H - margin],
            radius=16,
            fill=_hex_to_rgb(CARD_COLOR),
        )

        # ── Gold top border bar ──
        draw.rounded_rectangle(
            [margin, margin, CARD_W - margin, margin + 6],
            radius=3,
            fill=_hex_to_rgb(GOLD),
        )

        # ── Header: NEXUS BET logo + signal strength badge ──
        y = margin + 24
        draw.text((margin + 20, y), "⚡ NEXUS BET", font=font_title, fill=_hex_to_rgb(GOLD))

        strength = str(signal.get("signal_strength", "BUY")).upper()
        badge_color = _hex_to_rgb(GOLD) if strength == "STRONG_BUY" else _hex_to_rgb(GREEN)
        badge_text = f"  {strength}  "
        badge_w = 140 if strength == "STRONG_BUY" else 80
        badge_x = CARD_W - margin - badge_w - 20
        draw.rounded_rectangle(
            [badge_x, y, badge_x + badge_w, y + 34],
            radius=8,
            fill=badge_color,
        )
        draw.text((badge_x + 10, y + 6), strength, font=font_badge, fill=_hex_to_rgb(BG_COLOR))

        # ── Divider line (gold) ──
        y += 50
        draw.line([(margin + 16, y), (CARD_W - margin - 16, y)], fill=_hex_to_rgb(GOLD), width=1)
        y += 16

        # ── Market question ──
        question = str(signal.get("question") or "Unknown Market")
        # Word-wrap to ~60 chars per line
        words = question.split()
        lines = []
        cur = ""
        for w in words:
            if len(cur) + len(w) + 1 > 62:
                if cur:
                    lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            lines.append(cur)
        lines = lines[:2]  # max 2 lines

        for line in lines:
            draw.text((margin + 20, y), line, font=font_question, fill=_hex_to_rgb(WHITE))
            y += 28
        y += 10

        # ── Metrics grid ──
        edge_pct = float(signal.get("edge_pct", 0))
        kelly = float(signal.get("kelly_fraction", 0)) * 100
        confidence = float(signal.get("confidence", 0)) * 100
        price = float(signal.get("polymarket_price", 0.5))
        side = str(signal.get("side") or signal.get("recommended_outcome") or "YES")
        mkt_type = str(signal.get("market_type", "binary")).upper()

        metrics = [
            ("EV / EDGE", f"{edge_pct:.1f}%", GOLD_LIGHT),
            ("KELLY", f"{kelly:.1f}%", WHITE),
            ("CONFIANCE", f"{confidence:.0f}%", WHITE),
            ("PRIX POLY", f"{price:.3f}", WHITE),
        ]

        col_w = (CARD_W - 2 * margin - 40) // 4
        x_start = margin + 20
        for i, (label, value, val_color) in enumerate(metrics):
            x = x_start + i * col_w
            # Metric box
            draw.rounded_rectangle(
                [x, y, x + col_w - 12, y + 72],
                radius=8,
                fill=_hex_to_rgb(BLUE_ACCENT),
            )
            draw.text((x + 10, y + 8), label, font=font_small, fill=_hex_to_rgb(GRAY))
            draw.text((x + 10, y + 30), value, font=font_value, fill=_hex_to_rgb(val_color))

        y += 88

        # ── Bottom: Side + Type + timestamp ──
        side_color = _hex_to_rgb(GREEN) if side.upper() in ("YES", "BUY") else _hex_to_rgb(RED)
        draw.rounded_rectangle([margin + 20, y, margin + 90, y + 28], radius=6, fill=side_color)
        draw.text((margin + 30, y + 4), side[:8], font=font_badge, fill=_hex_to_rgb(BG_COLOR))

        draw.rounded_rectangle([margin + 100, y, margin + 180, y + 28], radius=6, fill=_hex_to_rgb(GRAY))
        draw.text((margin + 110, y + 4), mkt_type[:8], font=font_badge, fill=_hex_to_rgb(BG_COLOR))

        import time
        ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        draw.text((CARD_W - margin - 220, y + 6), ts, font=font_small, fill=_hex_to_rgb(GRAY))

        # ── Bottom gold bar ──
        draw.rounded_rectangle(
            [margin, CARD_H - margin - 6, CARD_W - margin, CARD_H - margin],
            radius=3,
            fill=_hex_to_rgb(GOLD),
        )

        # ── Export to bytes ──
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        log.error("Signal card generation failed: %s", e)
        return None


async def send_signal_card(signal: dict[str, Any], bot_token: str, chat_id: str) -> bool:
    """
    Generate and send a signal card image via Telegram sendPhoto.
    Returns True on success.
    """
    try:
        img_bytes = generate_signal_card(signal)
        if not img_bytes:
            return False

        import httpx
        caption = (
            f"⚡ <b>NEXUS SIGNAL</b>\n"
            f"Edge: <b>{float(signal.get('edge_pct', 0)):.1f}%</b>  │  "
            f"Kelly: <b>{float(signal.get('kelly_fraction', 0)) * 100:.1f}%</b>  │  "
            f"Conf: <b>{float(signal.get('confidence', 0)) * 100:.0f}%</b>"
        )
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("signal_card.png", img_bytes, "image/png")},
            )
            if r.status_code == 200:
                log.info("Signal card sent to chat %s", chat_id)
                return True
            log.warning("sendPhoto failed: %s %s", r.status_code, r.text[:200])
            return False
    except Exception as e:
        log.error("send_signal_card error: %s", e)
        return False
