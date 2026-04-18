"""Generate banner background via OpenAI Images (gpt-image-1).

Reads the API key from macOS Keychain (service 'openai-api-key'). Writes the
PNG to docs/brand/logo/banner-bg.png.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from urllib import request

OUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "logo", "banner-bg.png"
)

PROMPT = (
    "A wide cinematic abstract background for a fintech dashboard hero banner. "
    "Extremely dark navy near-black base color (#0B0E14). Subtle, elegant, "
    "minimalist composition with faint translucent green and soft red candlestick "
    "silhouettes fading in and out across the frame, very low contrast, like an "
    "out-of-focus trading terminal in the background. Soft atmospheric glow "
    "rising from the bottom. No text, no logos, no people. Editorial, premium, "
    "Stripe/Linear/Bloomberg Terminal design aesthetic. Ultra-wide 16:9 "
    "composition, suitable for overlaying white text and a small green accent "
    "logo on top. Very flat, vector-like, graphic design style, not photographic."
)


def get_api_key() -> str:
    env = os.getenv("OPENAI_API_KEY")
    if env:
        return env
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "openai-api-key", "-w"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def generate() -> bytes:
    key = get_api_key()
    body = json.dumps({
        "model": "gpt-image-1",
        "prompt": PROMPT,
        "size": "1536x1024",
        "quality": "high",
        "n": 1,
    }).encode()
    req = request.Request(
        "https://api.openai.com/v1/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        err_body = ""
        if hasattr(exc, "read"):
            try:
                err_body = exc.read().decode()[:500]  # type: ignore[attr-defined]
            except Exception:
                pass
        raise RuntimeError(f"OpenAI image gen failed: {exc} body={err_body}")

    b64 = data["data"][0]["b64_json"]
    return base64.b64decode(b64)


def main():
    png = generate()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        f.write(png)
    print(f"wrote {OUT_PATH} ({len(png)//1024}KB)")


if __name__ == "__main__":
    sys.exit(main())
