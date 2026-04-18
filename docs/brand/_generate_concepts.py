"""Generate three logo concepts as PNG tiles + a contact sheet for review."""

from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BG = (11, 14, 20)          # deep near-black
BG_HILIGHT = (22, 28, 40)
GREEN = (0, 208, 132)
GREEN_DIM = (0, 168, 107)
RED = (255, 76, 76)
YELLOW = (255, 204, 61)
OFFWHITE = (230, 237, 243)
DIM = (125, 133, 144)

SIZE = 512
OUT = os.path.dirname(os.path.abspath(__file__))
CONCEPTS = os.path.join(OUT, "concepts")

FONT_DISPLAY = "/System/Library/Fonts/SFNSRounded.ttf"
FONT_MONO = "/System/Library/Fonts/SFNSMono.ttf"
FONT_SANS = "/System/Library/Fonts/SFNS.ttf"


def _tile_bg(size: int = SIZE) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)
    # subtle diagonal highlight — top-left brighter, bottom-right darker
    for i in range(size):
        alpha = max(0, 60 - int(i * 60 / size))
        draw.line([(0, i), (i, 0)], fill=(22, 28, 40), width=1)
    return img


def _rounded_tile(size: int, radius_frac: float = 0.22) -> Image.Image:
    """Dark rounded-square tile, iOS app-icon style."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = int(size * radius_frac)
    # gradient fill by drawing many rounded rectangles — cheap gradient
    for i in range(size):
        t = i / size
        color = (
            int(11 + 14 * (1 - t)),
            int(14 + 18 * (1 - t)),
            int(20 + 26 * (1 - t)),
            255,
        )
        draw.line([(0, i), (size, i)], fill=color)
    # mask to rounded rect
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=r, fill=255
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def concept_a_dt_sparkline() -> Image.Image:
    """'DT' monogram where the T's bar is a rising sparkline."""
    size = SIZE
    tile = _rounded_tile(size)
    draw = ImageDraw.Draw(tile)

    # Big "D" in bold rounded
    try:
        fD = ImageFont.truetype(FONT_DISPLAY, int(size * 0.58))
    except Exception:
        fD = ImageFont.load_default()

    # Layout: "D" on left, "T" on right with reshaped bar
    dt_y = int(size * 0.18)
    d_x = int(size * 0.14)
    draw.text((d_x, dt_y), "D", font=fD, fill=OFFWHITE)

    # "T" vertical stem only (we'll draw its bar as a sparkline)
    t_x = int(size * 0.52)
    # Vertical bar of T
    stem_w = int(size * 0.08)
    stem_top = int(size * 0.32)
    stem_bot = int(size * 0.78)
    draw.rounded_rectangle(
        [t_x + int(size * 0.11), stem_top,
         t_x + int(size * 0.11) + stem_w, stem_bot],
        radius=stem_w // 2,
        fill=OFFWHITE,
    )

    # Sparkline replacing the T's horizontal bar
    spark_y_base = int(size * 0.33)
    spark_left = t_x + int(size * 0.02)
    spark_right = t_x + int(size * 0.36)
    points = [
        (spark_left, spark_y_base + int(size * 0.04)),
        (spark_left + (spark_right - spark_left) // 4, spark_y_base + int(size * 0.06)),
        (spark_left + (spark_right - spark_left) // 2, spark_y_base - int(size * 0.01)),
        (spark_left + 3 * (spark_right - spark_left) // 4, spark_y_base + int(size * 0.02)),
        (spark_right, spark_y_base - int(size * 0.05)),
    ]
    draw.line(points, fill=GREEN, width=int(size * 0.035), joint="curve")
    # Glow dot at the end
    r = int(size * 0.035)
    draw.ellipse(
        [spark_right - r, points[-1][1] - r, spark_right + r, points[-1][1] + r],
        fill=GREEN,
    )

    return tile


def concept_b_candle_stack() -> Image.Image:
    """Three candlesticks in a rising pattern — red, red, green — stylized D."""
    size = SIZE
    tile = _rounded_tile(size)
    draw = ImageDraw.Draw(tile)

    # Candles centered
    n = 3
    candle_w = int(size * 0.11)
    gap = int(size * 0.055)
    total_w = n * candle_w + (n - 1) * gap
    start_x = (size - total_w) // 2
    cy = int(size * 0.50)

    # Candle specs: (body_top_frac, body_bot_frac, wick_top_frac, wick_bot_frac, color)
    specs = [
        (0.42, 0.64, 0.34, 0.70, RED),
        (0.34, 0.58, 0.28, 0.66, RED),
        (0.18, 0.48, 0.12, 0.54, GREEN),
    ]

    wick_w = max(2, int(size * 0.010))
    for i, (bt, bb, wt, wb, color) in enumerate(specs):
        x = start_x + i * (candle_w + gap)
        cx = x + candle_w // 2
        # wick
        draw.rectangle(
            [cx - wick_w // 2, int(size * wt), cx + wick_w // 2, int(size * wb)],
            fill=color,
        )
        # body
        draw.rounded_rectangle(
            [x, int(size * bt), x + candle_w, int(size * bb)],
            radius=int(candle_w * 0.18),
            fill=color,
        )

    # subtle trend arrow under candles
    arr_y = int(size * 0.82)
    draw.line(
        [(int(size * 0.18), arr_y + int(size * 0.02)),
         (int(size * 0.50), arr_y - int(size * 0.01)),
         (int(size * 0.82), arr_y - int(size * 0.06))],
        fill=GREEN_DIM,
        width=int(size * 0.012),
        joint="curve",
    )
    return tile


def concept_c_chevron_prism() -> Image.Image:
    """Upward chevron refracting into red/yellow/green rays — prism of signals."""
    size = SIZE
    tile = _rounded_tile(size)
    draw = ImageDraw.Draw(tile)

    cx = size // 2
    apex_y = int(size * 0.28)
    base_y = int(size * 0.60)
    half_w = int(size * 0.22)
    thick = int(size * 0.075)

    # Chevron ^ shape (two thick lines)
    draw.line(
        [(cx - half_w, base_y), (cx, apex_y)],
        fill=OFFWHITE,
        width=thick,
        joint="curve",
    )
    draw.line(
        [(cx, apex_y), (cx + half_w, base_y)],
        fill=OFFWHITE,
        width=thick,
        joint="curve",
    )

    # Three rays emerging downward below the chevron
    rays_top = int(size * 0.64)
    rays_bot = int(size * 0.86)
    spread = int(size * 0.16)
    ray_w = int(size * 0.024)

    for dx, color in [(-spread, RED), (0, YELLOW), (spread, GREEN)]:
        draw.line(
            [(cx, rays_top), (cx + dx, rays_bot)],
            fill=color,
            width=ray_w,
        )
        # dot at ray end
        r = ray_w
        draw.ellipse(
            [cx + dx - r, rays_bot - r, cx + dx + r, rays_bot + r],
            fill=color,
        )
    return tile


def add_caption(tile: Image.Image, label: str) -> Image.Image:
    """Add a thin caption under a tile, returning a taller image."""
    w, h = tile.size
    pad = 28
    new = Image.new("RGB", (w, h + 70), BG)
    new.paste(tile, (0, 0), tile if tile.mode == "RGBA" else None)
    draw = ImageDraw.Draw(new)
    try:
        f = ImageFont.truetype(FONT_MONO, 22)
    except Exception:
        f = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=f)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, h + 20), label, font=f, fill=DIM)
    return new


def main():
    os.makedirs(CONCEPTS, exist_ok=True)

    tiles = {
        "A_dt_sparkline": concept_a_dt_sparkline(),
        "B_candle_stack": concept_b_candle_stack(),
        "C_chevron_prism": concept_c_chevron_prism(),
    }

    for name, tile in tiles.items():
        tile.save(os.path.join(CONCEPTS, f"{name}.png"))

    # Contact sheet — horizontal strip of all 3, labeled
    labeled = [add_caption(t, f"Concept {n.split('_')[0]} — {' '.join(n.split('_')[1:])}")
               for n, t in tiles.items()]
    sheet_w = SIZE * 3 + 80
    sheet_h = labeled[0].size[1] + 60
    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype(FONT_SANS, 28)
    except Exception:
        f = ImageFont.load_default()
    draw.text((24, 16), "DeepThinkTrader — Logo Concepts", font=f, fill=OFFWHITE)
    for i, img in enumerate(labeled):
        x = 20 + i * (SIZE + 20)
        sheet.paste(img, (x, 60))
    sheet.save(os.path.join(OUT, "concepts_review.png"))
    print(f"wrote {os.path.join(OUT, 'concepts_review.png')}")


if __name__ == "__main__":
    main()
