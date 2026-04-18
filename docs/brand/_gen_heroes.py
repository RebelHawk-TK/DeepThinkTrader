"""Generate three hero illustrations for empty/pending states via gpt-image-1.

Outputs into docs/brand/logo/:
- hero-pending.png   — account pending approval screen
- hero-no-keys.png   — Settings page, no API keys saved yet
- hero-no-trades.png — dashboard, no trades executed yet
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from urllib import request, error

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo")

PROMPTS = {
    "hero-pending.png": (
        "A minimalist editorial illustration for a 'waiting for approval' screen on "
        "a dark fintech dashboard. Extremely dark navy background (#0B0E14). "
        "Soft abstract geometric composition: a single thin vertical candlestick-like "
        "shape in muted green, paused mid-motion, with a faint concentric ring pulsing "
        "around it suggesting 'standing by'. Subtle atmospheric glow. No text, no "
        "people, no logos. Flat graphic design, Stripe/Linear aesthetic, suitable "
        "for a 600x400 hero image. Ultra-minimal, elegant, premium."
    ),
    "hero-no-keys.png": (
        "A minimalist editorial illustration for a 'connect your broker' onboarding "
        "step. Extremely dark navy background (#0B0E14). A stylized flat graphic "
        "showing two abstract rectangular 'key card' shapes gently tilting toward "
        "each other about to click together, muted green accent on one side. Very "
        "soft, understated, implying a handshake or connection. No text, no realistic "
        "keys, no hands, no people. Flat graphic design, Stripe/Linear aesthetic, "
        "600x400 hero composition."
    ),
    "hero-no-trades.png": (
        "A minimalist editorial illustration for an empty dashboard state, 'no "
        "trades yet'. Extremely dark navy background (#0B0E14). A single very faint "
        "dotted horizontal line across the middle of the frame, with a lone small "
        "green candlestick about to appear on the left side, as if waiting to draw "
        "a chart. Immense empty space, understated, expectant mood. No text. Flat "
        "graphic design, Stripe/Linear aesthetic, 600x400 composition."
    ),
}


def _key() -> str:
    env = os.getenv("OPENAI_API_KEY")
    if env:
        return env
    return subprocess.run(
        ["security", "find-generic-password", "-s", "openai-api-key", "-w"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _gen(prompt: str) -> bytes:
    body = json.dumps({
        "model": "gpt-image-1",
        "prompt": prompt,
        "size": "1536x1024",
        "quality": "medium",
        "n": 1,
    }).encode()
    req = request.Request(
        "https://api.openai.com/v1/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
    except error.HTTPError as e:
        raise RuntimeError(f"OpenAI {e.code}: {e.read().decode()[:400]}")
    return base64.b64decode(data["data"][0]["b64_json"])


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, prompt in PROMPTS.items():
        path = os.path.join(OUT_DIR, name)
        if os.path.exists(path) and os.getenv("FORCE") != "1":
            print(f"skip (exists): {name} — set FORCE=1 to overwrite")
            continue
        print(f"generating {name}…")
        data = _gen(prompt)
        with open(path, "wb") as f:
            f.write(data)
        print(f"  wrote {len(data)//1024}KB")


if __name__ == "__main__":
    main()
