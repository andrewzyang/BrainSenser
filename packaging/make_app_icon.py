#!/usr/bin/env python3
"""Generate the BrainSenser macOS app icon: the brain contour mark on a fully
transparent background (no tile, plate, or rim).

Trims the preserved line-art mark, scales it large within the 1024x1024 canvas
with a small transparent margin, centers it, and writes the master PNG plus the
multi-size .icns. The background is pure alpha-0 — the icon free-floats.

Usage:
    python packaging/make_app_icon.py
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
BRAIN_SRC = ASSETS / "brain_mark_source.png"   # transparent line-art (preserved)
OUT_PNG = ASSETS / "brainsenser_app_icon.png"
OUT_ICNS = ASSETS / "brainsenser_app_icon.icns"

OUT = 1024            # master size
MARK_FRAC = 0.90      # mark's longest side as fraction of canvas (small margin)


def build() -> Image.Image:
    mark = Image.open(BRAIN_SRC).convert("RGBA")
    mark = mark.crop(mark.getbbox())             # trim transparent border

    longest = max(mark.width, mark.height)
    scale = (OUT * MARK_FRAC) / longest
    w, h = round(mark.width * scale), round(mark.height * scale)
    mark = mark.resize((w, h), Image.LANCZOS)

    canvas = Image.new("RGBA", (OUT, OUT), (0, 0, 0, 0))   # perfect transparency
    canvas.alpha_composite(mark, ((OUT - w) // 2, (OUT - h) // 2))
    return canvas


def write_icns(png: Image.Image) -> None:
    sizes = [16, 32, 128, 256, 512]
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "icon.iconset"
        iconset.mkdir()
        for s in sizes:
            png.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            png.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT_ICNS)],
                       check=True)


if __name__ == "__main__":
    icon = build()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT_PNG)
    write_icns(icon)
    print(f"wrote {OUT_PNG} and {OUT_ICNS}")
