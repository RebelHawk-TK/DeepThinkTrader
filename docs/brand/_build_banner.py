"""Compose the DeepThinkTrader banner — dark atmospheric background + wordmark.

Fully deterministic: no image-gen dependency. Produces banner.png at 1600x400.
"""

from __future__ import annotations

import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from _build_brand import (
    BG_DARK, BG_HI, GREEN, RED, OFFWHITE, DIM,
    FONT_DISPLAY, FONT_SANS, FONT_MONO,
    make_mark_tile_png, make_wordmark,
)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo", "banner.png")
AI_BG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo", "banner-bg.png")
W, H = 1600, 400


def _ai_background() -> Image.Image | None:
    """Load the AI-generated background if present; crop-fit to W x H."""
    if not os.path.exists(AI_BG):
        return None
    raw = Image.open(AI_BG).convert("RGB")
    # Scale so shorter side matches then center-crop to W x H
    sw, sh = raw.size
    scale = max(W / sw, H / sh)
    new = raw.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
    nw, nh = new.size
    left = (nw - W) // 2
    top = (nh - H) // 2
    cropped = new.crop((left, top, left + W, top + H))

    # Darken the left third slightly so the white wordmark has contrast
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for x in range(int(W * 0.55)):
        t = 1 - x / (W * 0.55)
        a = int(110 * t)
        odraw.line([(x, 0), (x, H)], fill=(0, 0, 0, a))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=40))
    cropped = Image.alpha_composite(cropped.convert("RGBA"), overlay).convert("RGB")
    return cropped


def _background() -> Image.Image:
    """Dark base with a soft radial glow + faint horizontal grid lines."""
    img = Image.new("RGB", (W, H), BG_DARK)
    # Vertical gradient (top slightly lighter, bottom darker)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        color = (
            int(BG_HI[0] * (1 - t) + BG_DARK[0] * t * 0.7),
            int(BG_HI[1] * (1 - t) + BG_DARK[1] * t * 0.7),
            int(BG_HI[2] * (1 - t) + BG_DARK[2] * t * 0.7),
        )
        draw.line([(0, y), (W, y)], fill=color)

    # Soft green glow rising from bottom-left (drawn on a separate layer + blur)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for r in range(700, 0, -20):
        a = int(max(0, 30 - r / 30))
        gdraw.ellipse([-200 - r, H - 120 - r // 2, -200 + r, H + r // 2],
                      fill=(0, int(60 * a / 30), int(40 * a / 30)))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=70))
    img = Image.blend(img, Image.alpha_composite(
        img.convert("RGBA"),
        Image.merge("RGBA", (*glow.split(), Image.new("L", glow.size, 70)))
    ).convert("RGB"), alpha=0.55)

    # Faint horizontal chart lines
    draw = ImageDraw.Draw(img, "RGBA")
    for y in (H // 4, H // 2, 3 * H // 4):
        draw.line([(0, y), (W, y)], fill=(125, 133, 144, 22), width=1)

    # Scattered candle silhouettes across the right two-thirds, very low opacity
    rnd = random.Random(7)  # stable across runs
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for _ in range(28):
        cx = rnd.randint(int(W * 0.42), W - 40)
        body_h = rnd.randint(18, 90)
        body_w = rnd.randint(6, 16)
        cy = rnd.randint(60, H - 60)
        wick_extra = rnd.randint(6, 26)
        up = rnd.random() < 0.55
        base = GREEN if up else RED
        alpha = rnd.randint(18, 55)
        color = (*base, alpha)
        # wick
        odraw.rectangle(
            [cx - 1, cy - body_h // 2 - wick_extra, cx + 1, cy + body_h // 2 + wick_extra],
            fill=color,
        )
        # body
        odraw.rounded_rectangle(
            [cx - body_w // 2, cy - body_h // 2,
             cx + body_w // 2, cy + body_h // 2],
            radius=max(2, body_w // 3),
            fill=color,
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=2))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    return img


def _overlay_wordmark(bg: Image.Image) -> Image.Image:
    """Place the wordmark on the left, with a muted tagline underneath."""
    wm_height = 180
    wm = make_wordmark(wm_height, on_dark=True)

    canvas = bg.copy().convert("RGBA")
    margin_x = 80
    margin_y = (H - wm_height) // 2 - 16  # shifted up to leave room for tagline
    canvas.alpha_composite(wm, (margin_x, margin_y))

    # Tagline
    try:
        f = ImageFont.truetype(FONT_MONO, 20)
    except Exception:
        f = ImageFont.load_default()
    d = ImageDraw.Draw(canvas)
    tagline = "ai-assisted paper trading · shared strategy, separate accounts"
    d.text(
        (margin_x + 4, margin_y + wm_height + 14),
        tagline,
        font=f,
        fill=(125, 133, 144, 255),
    )

    return canvas.convert("RGB")


def main():
    bg = _ai_background() or _background()
    source = "AI (banner-bg.png)" if _ai_background() else "procedural"
    final = _overlay_wordmark(bg)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    final.save(OUT)
    print(f"wrote {OUT} — background: {source}")


if __name__ == "__main__":
    main()
