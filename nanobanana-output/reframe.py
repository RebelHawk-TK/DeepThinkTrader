"""Crop the square Gemini output to 3:1 banner shape (1500x500) and save as
banner-final.png so overlay.py picks it up as the base."""
from __future__ import annotations

from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
SRC = HERE / "banner-wide-1.png"
DST = HERE / "banner-final.png"

TARGET_W, TARGET_H = 1500, 500


def main() -> None:
    im = Image.open(SRC).convert("RGB")
    w, h = im.size  # 1024x1024
    # Panels sit roughly in vertical middle; crop a horizontal strip
    # tall enough to catch the full panel height.
    strip_h = int(w / 3)  # 3:1 aspect ratio, so crop height = width/3
    top = (h - strip_h) // 2
    cropped = im.crop((0, top, w, top + strip_h))
    out = cropped.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    out.save(DST, optimize=True)
    print(f"wrote {DST} ({TARGET_W}x{TARGET_H})")


if __name__ == "__main__":
    main()
