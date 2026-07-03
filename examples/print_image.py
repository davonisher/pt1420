#!/usr/bin/env python3
"""
Example: print an image file (photo, logo, QR code) on the PT-1420.

Shows the raster side of the driver: any image is scaled to the 384px print
width and Floyd-Steinberg dithered to 1-bit. Optionally stack a text caption
underneath to demonstrate composing images.

    python3 examples/print_image.py picture.jpg
    python3 examples/print_image.py logo.png --caption "Hello from my desktop!"
    python3 examples/print_image.py photo.png --no-dither
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pt1420
from PIL import Image


def stack(top: Image.Image, bottom: Image.Image) -> Image.Image:
    """Stack two WIDTH-wide 1-bit images vertically (white background)."""
    canvas = Image.new("1", (pt1420.WIDTH, top.height + bottom.height), 1)
    canvas.paste(top, (0, 0))
    canvas.paste(bottom, (0, top.height))
    return canvas


def main() -> int:
    ap = argparse.ArgumentParser(description="Print an image file on the PT-1420.")
    ap.add_argument("path", help="Path to the image (PNG/JPG/...).")
    ap.add_argument("--caption", help="Optional text printed beneath the image.")
    ap.add_argument("--no-dither", action="store_true",
                    help="Use a hard black/white threshold instead of dithering.")
    args = ap.parse_args()

    img = pt1420.image_from_file(args.path, dither=not args.no_dither)
    if args.caption:
        img = stack(img, pt1420.text_to_image(args.caption))

    asyncio.run(pt1420.print_image(img))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
