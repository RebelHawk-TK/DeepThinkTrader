"""Minimal image generator that bypasses the buggy gemini CLI.

Calls the Generative Language REST API directly with gemini-2.5-flash-image
and writes every inline PNG part to disk. Invoked as:

    python gen.py <output_prefix> <prompt...>

Key comes from gcloud secret GEMINI_API_KEY on the travelforge-app project.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

MODEL = "gemini-2.5-flash-image"


def api_key() -> str:
    out = subprocess.check_output([
        "gcloud", "secrets", "versions", "access", "latest",
        "--secret=GEMINI_API_KEY", "--project=travelforge-app",
    ])
    return out.decode().strip()


def generate(prefix: str, prompt: str, out_dir: Path) -> list[Path]:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODEL}:generateContent?key={api_key()}"
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for cand in data.get("candidates", []):
        for i, part in enumerate(cand.get("content", {}).get("parts", [])):
            inline = part.get("inlineData")
            if not inline:
                continue
            mime = inline.get("mimeType", "image/png")
            ext = mime.split("/")[-1]
            path = out_dir / f"{prefix}-{len(written) + 1}.{ext}"
            path.write_bytes(base64.b64decode(inline["data"]))
            written.append(path)
    return written


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    prefix = sys.argv[1]
    prompt = " ".join(sys.argv[2:])
    out_dir = Path(__file__).parent
    paths = generate(prefix, prompt, out_dir)
    for p in paths:
        print(p)
    if not paths:
        print("no images in response", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
