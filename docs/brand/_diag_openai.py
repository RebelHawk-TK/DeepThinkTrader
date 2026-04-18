"""Diagnostic: test the Keychain OpenAI key against /v1/models (cheap) and
report length + prefix + failure reason. Never prints the key value."""

from __future__ import annotations

import json
import subprocess
from urllib import request, error


def get_key() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "openai-api-key", "-w"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def main():
    k = get_key()
    print(f"key length     : {len(k)}")
    print(f"key prefix     : {k[:8]}…")
    print(f"key suffix     : …{k[-4:]}")
    print(f"expected prefix: sk-proj- (project) or sk- (user)")
    print()

    req = request.Request(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {k}"},
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        models = [m["id"] for m in data.get("data", [])]
        print(f"/v1/models OK — {len(models)} models visible")
        image_models = [m for m in models if "image" in m or "dall" in m or "gpt-image" in m]
        print(f"image-capable models: {image_models or '(none visible — check project scope)'}")
    except error.HTTPError as e:
        body = e.read().decode()[:400]
        print(f"HTTP {e.code} — {e.reason}")
        print(body)
    except Exception as exc:
        print(f"network error: {exc}")


if __name__ == "__main__":
    main()
