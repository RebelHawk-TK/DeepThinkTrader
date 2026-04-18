"""Paths to the DeepThinkTrader brand assets baked into the container.

Canonical sources live under docs/brand/logo/; the subset needed at runtime
is copied into static/brand/ during the build so this module's paths resolve
both locally and inside the Cloud Run image.
"""

from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "static", "brand")

ICON_PATH = os.path.join(_DIR, "mark-tile-192.png")
BANNER_PATH = os.path.join(_DIR, "banner.png")
FAVICON_PATH = os.path.join(_DIR, "favicon.ico")
