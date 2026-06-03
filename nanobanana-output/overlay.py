"""Composite bold DeepThink Trader wordmark onto banner-final.png.

Base (banner-final.png) is the Gemini-generated 3-panel glass design with
the chart flowing across all three panels. This script adds only the
wordmark — no new chart line.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
SRC = HERE / "banner-final.png"
OUT = HERE / "banner.png"
FONT_PATH = "/System/Library/Fonts/HelveticaNeue.ttc"


def load_font(size: int, index: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size, index=index)


def draw_wordmark(banner: Image.Image) -> Image.Image:
    w, h = banner.size
    heavy = load_font(112, 8)
    try:
        heavy = load_font(112, 8)
    except Exception:
        heavy = load_font(112, 2)

    part1 = "DeepThink"
    part2 = " Trader"

    tmp_draw = ImageDraw.Draw(banner)
    bbox1 = tmp_draw.textbbox((0, 0), part1, font=heavy)
    bbox2 = tmp_draw.textbbox((0, 0), part2, font=heavy)
    w1 = bbox1[2] - bbox1[0]
    w2 = bbox2[2] - bbox2[0]
    total_w = w1 + w2
    text_h = max(bbox1[3] - bbox1[1], bbox2[3] - bbox2[1])

    x = (w - total_w) // 2
    y = (h - text_h) // 2 - 28

    RED = (255, 77, 109)
    GREEN = (0, 245, 160)
    out = banner.convert("RGBA")

    aura = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    adraw = ImageDraw.Draw(aura)
    adraw.text((x, y), part1, font=heavy, fill=(*RED, 180))
    adraw.text((x + w1, y), part2, font=heavy, fill=(*GREEN, 200))
    aura = aura.filter(ImageFilter.GaussianBlur(radius=22))
    out = Image.alpha_composite(out, aura)

    edge = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    edraw = ImageDraw.Draw(edge)
    edraw.text((x, y), part1, font=heavy, fill=(*RED, 255))
    edraw.text((x + w1, y), part2, font=heavy, fill=(*GREEN, 255))
    edge = edge.filter(ImageFilter.GaussianBlur(radius=4))
    out = Image.alpha_composite(out, edge)

    shadow = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.text((x + 2, y + 4), part1, font=heavy, fill=(0, 0, 0, 180))
    sdraw.text((x + w1 + 2, y + 4), part2, font=heavy, fill=(0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=6))
    out = Image.alpha_composite(out, shadow)

    body = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(body)
    bdraw.text((x, y), part1, font=heavy, fill=(*RED, 255))
    bdraw.text((x + w1, y), part2, font=heavy, fill=(*GREEN, 255))
    out = Image.alpha_composite(out, body)

    mask = Image.new("L", banner.size, 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.text((x, y), part1, font=heavy, fill=255)
    mdraw.text((x + w1, y), part2, font=heavy, fill=255)

    gloss = Image.new("RGBA", banner.size, (0, 0, 0, 0))
    gpx = gloss.load()
    band_top = y
    band_bot = y + text_h
    band_h = max(1, band_bot - band_top)
    for yy in range(band_top, min(band_bot + 1, h)):
        t = (yy - band_top) / band_h
        a = int(180 * (1 - t / 0.45) ** 1.6) if t < 0.45 else 0
        if a <= 0:
            continue
        for xx in range(w):
            gpx[xx, yy] = (255, 255, 255, a)

    gloss_masked = Image.composite(
        gloss, Image.new("RGBA", banner.size, (0, 0, 0, 0)), mask
    )
    out = Image.alpha_composite(out, gloss_masked)

    return out


def main() -> None:
    banner = Image.open(SRC).convert("RGBA")
    out = draw_wordmark(banner)
    out.convert("RGB").save(OUT, optimize=True)
    print(f"wrote {OUT} ({out.size[0]}x{out.size[1]})")


if __name__ == "__main__":
    main()
