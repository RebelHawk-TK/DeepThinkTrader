"""Build the DeepThinkTrader brand set — vector mark, raster family, favicon, wordmark.

Concept B: three rising candlesticks (red, red, green). Clean, trading-native,
scales to 16px.

Outputs in docs/brand/logo/:
- mark.svg              (candles only, transparent bg)
- mark-tile.svg         (candles in rounded dark tile)
- mark-tile-{N}.png     (N=16, 32, 48, 128, 192, 256, 512, 1024)
- favicon.ico           (multi-res)
- wordmark-light.png    (horizontal lockup for dark backgrounds)
- wordmark-dark.png     (horizontal lockup for light backgrounds)
"""

from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

# ── Brand palette ─────────────────────────────────────────────────
BG_DARK = (11, 14, 20)        # #0B0E14
BG_HI = (22, 28, 40)           # highlight end of gradient
GREEN = (0, 208, 132)          # #00D084
RED = (255, 76, 76)            # #FF4C4C
OFFWHITE = (230, 237, 243)     # #E6EDF3
CHARCOAL = (35, 42, 55)        # for light-bg wordmark
DIM = (125, 133, 144)

FONT_DISPLAY = "/System/Library/Fonts/SFNSRounded.ttf"
FONT_SANS = "/System/Library/Fonts/SFNS.ttf"
FONT_MONO = "/System/Library/Fonts/SFNSMono.ttf"

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo")


# ── SVG helpers ───────────────────────────────────────────────────

def svg_mark_only() -> str:
    """Just the three candles, 512x512 viewBox, transparent background."""
    # Candle geometry (percentages of 512)
    candles = [
        # (wick_top%, wick_bot%, body_top%, body_bot%, color)
        (34, 70, 42, 64, "#FF4C4C"),
        (28, 66, 34, 58, "#FF4C4C"),
        (12, 54, 18, 48, "#00D084"),
    ]
    size = 512
    n = 3
    body_w = int(size * 0.11)
    gap = int(size * 0.055)
    total = n * body_w + (n - 1) * gap
    start_x = (size - total) // 2
    wick_w = max(2, int(size * 0.010))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">']
    for i, (wt, wb, bt, bb, color) in enumerate(candles):
        x = start_x + i * (body_w + gap)
        cx = x + body_w // 2
        parts.append(
            f'<rect x="{cx - wick_w//2}" y="{size*wt//100}" '
            f'width="{wick_w}" height="{size*(wb-wt)//100}" fill="{color}" />'
        )
        parts.append(
            f'<rect x="{x}" y="{size*bt//100}" width="{body_w}" '
            f'height="{size*(bb-bt)//100}" rx="{int(body_w*0.18)}" ry="{int(body_w*0.18)}" fill="{color}" />'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def svg_mark_tile() -> str:
    """Candles inside a rounded dark tile, 512x512."""
    size = 512
    inner = svg_mark_only()
    # strip the outer <svg> wrapper from inner so we can nest
    inner_body = inner.split(">", 1)[1].rsplit("</svg>", 1)[0]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">
  <defs>
    <linearGradient id="tileBg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#161C28"/>
      <stop offset="100%" stop-color="#0B0E14"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="{int(size*0.22)}" ry="{int(size*0.22)}" fill="url(#tileBg)"/>
  {inner_body}
</svg>"""


# ── PIL helpers ───────────────────────────────────────────────────

def _rounded_tile(size: int, radius_frac: float = 0.22) -> Image.Image:
    """Dark rounded-square tile with subtle vertical gradient."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGB", (size, size), BG_DARK)
    draw = ImageDraw.Draw(grad)
    for i in range(size):
        t = i / size
        color = (
            int(BG_HI[0] * (1 - t) + BG_DARK[0] * t),
            int(BG_HI[1] * (1 - t) + BG_DARK[1] * t),
            int(BG_HI[2] * (1 - t) + BG_DARK[2] * t),
        )
        draw.line([(0, i), (size, i)], fill=color)
    mask = Image.new("L", (size, size), 0)
    r = int(size * radius_frac)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=r, fill=255
    )
    img.paste(grad, (0, 0), mask)
    return img


def _draw_candles(img: Image.Image, cx: int, cy: int, scale: float = 1.0) -> None:
    """Draw three rising candles centered at (cx, cy). scale=1.0 → ~62% of min dim."""
    draw = ImageDraw.Draw(img)
    area = int(min(img.size) * 0.62 * scale)
    n = 3
    body_w = int(area * 0.18)
    gap = int(area * 0.09)
    total_w = n * body_w + (n - 1) * gap
    left = cx - total_w // 2
    top = cy - area // 2

    specs = [
        # (wick_top_f, wick_bot_f, body_top_f, body_bot_f, color) - fractions of area
        (0.05, 0.70, 0.15, 0.58, RED),
        (0.15, 0.80, 0.25, 0.68, RED),
        (0.00, 0.55, 0.08, 0.45, GREEN),
    ]
    wick_w = max(2, int(area * 0.017))
    for i, (wt, wb, bt, bb, color) in enumerate(specs):
        x = left + i * (body_w + gap)
        ccx = x + body_w // 2
        draw.rectangle(
            [ccx - wick_w // 2, top + int(area * wt),
             ccx + wick_w // 2, top + int(area * wb)],
            fill=color,
        )
        draw.rounded_rectangle(
            [x, top + int(area * bt), x + body_w, top + int(area * bb)],
            radius=int(body_w * 0.22),
            fill=color,
        )


def make_mark_tile_png(size: int) -> Image.Image:
    tile = _rounded_tile(size)
    _draw_candles(tile, size // 2, size // 2)
    return tile


def make_mark_only_png(size: int) -> Image.Image:
    """Candles only, transparent bg."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _draw_candles(img, size // 2, size // 2)
    return img


def make_wordmark(height: int = 240, on_dark: bool = True) -> Image.Image:
    """Horizontal lockup: tile + 'DeepThink' + 'Trader'. Canvas auto-sized to fit."""
    text_color = OFFWHITE if on_dark else CHARCOAL
    accent_color = GREEN

    # Measure text first
    type_size = int(height * 0.52)
    try:
        f = ImageFont.truetype(FONT_DISPLAY, type_size)
    except Exception:
        f = ImageFont.load_default()

    probe = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(probe)
    b1 = d.textbbox((0, 0), "DeepThink", font=f)
    b2 = d.textbbox((0, 0), "Trader", font=f)
    w_deep = b1[2] - b1[0]
    w_trade = b2[2] - b2[0]
    ascent = max(b1[3], b2[3])

    tile_size = height
    left_pad = 0
    tile_to_text = int(height * 0.22)
    word_gap = int(height * 0.12)
    right_pad = int(height * 0.12)

    width = (
        left_pad
        + tile_size
        + tile_to_text
        + w_deep
        + word_gap
        + w_trade
        + right_pad
    )

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tile = make_mark_tile_png(tile_size)
    img.paste(tile, (left_pad, 0), tile)

    draw = ImageDraw.Draw(img)
    # Center text vertically relative to tile's visual center
    text_y = (height - ascent) // 2 - int(height * 0.05)
    text_x = left_pad + tile_size + tile_to_text
    draw.text((text_x, text_y), "DeepThink", font=f, fill=text_color)
    draw.text((text_x + w_deep + word_gap, text_y), "Trader", font=f, fill=accent_color)
    return img


def make_favicon_ico() -> None:
    """Multi-resolution .ico file."""
    sizes = [16, 32, 48, 64]
    imgs = [make_mark_tile_png(s) for s in sizes]
    imgs[0].save(
        os.path.join(OUT, "favicon.ico"),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=imgs[1:],
    )


# ── Build ─────────────────────────────────────────────────────────

def main():
    os.makedirs(OUT, exist_ok=True)

    # SVG masters
    with open(os.path.join(OUT, "mark.svg"), "w") as f:
        f.write(svg_mark_only())
    with open(os.path.join(OUT, "mark-tile.svg"), "w") as f:
        f.write(svg_mark_tile())

    # Raster tile family (used for favicon, OG, app icon, etc.)
    for s in (16, 32, 48, 128, 192, 256, 512, 1024):
        make_mark_tile_png(s).save(os.path.join(OUT, f"mark-tile-{s}.png"))

    # Mark-only transparent versions
    for s in (256, 512):
        make_mark_only_png(s).save(os.path.join(OUT, f"mark-{s}.png"))

    # Wordmark lockups
    make_wordmark(1600, on_dark=True).save(os.path.join(OUT, "wordmark-light.png"))
    make_wordmark(1600, on_dark=False).save(os.path.join(OUT, "wordmark-dark.png"))

    # Favicon .ico
    make_favicon_ico()

    print("Wrote brand assets to", OUT)
    for f in sorted(os.listdir(OUT)):
        print(" ", f)


if __name__ == "__main__":
    main()
