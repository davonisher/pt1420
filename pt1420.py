#!/usr/bin/env python3
"""
pt1420.py  -  Drive the Powertech PT-1420 mini thermal printer from a
laptop/desktop over Bluetooth LE.

The PT-1420 is a rebranded "cat printer" module: its USB-C port only charges,
and all printing happens over Bluetooth LE. It advertises as 'X6h-...' and
speaks the classic cat-printer protocol (service AE30, write characteristic
AE01). This module renders text or images to a 384px-wide 1-bit raster and
sends it to the printer.

As a library:

    import asyncio, pt1420
    asyncio.run(pt1420.print_text("Hello!\\nΓεια σου!"))
    asyncio.run(pt1420.print_image(pt1420.image_from_file("logo.png")))

As a command-line tool:

    python3 pt1420.py "Hello, world!"      # print text
    echo "hi" | python3 pt1420.py -        # print from stdin
    python3 pt1420.py --file notes.txt     # print a text file
    python3 pt1420.py --image photo.png    # print an image (dithered)

Requirements: `pip install bleak pillow`. Tested on macOS; works anywhere
`bleak` supports (Linux/Windows) since it only talks BLE.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from PIL import Image, ImageDraw, ImageFont
from bleak import BleakScanner, BleakClient

# --- BLE identity -----------------------------------------------------------
# The PT-1420 advertises as 'X6h-...'. Its BLE address differs per host/device,
# so by default we discover it by name. Set PT1420_ADDRESS to force a specific
# address (a macOS CoreBluetooth UUID, or a MAC on Linux/Windows).
NAME_HINT = os.environ.get("PT1420_NAME", "X6h")
ADDRESS = os.environ.get("PT1420_ADDRESS", "")
CHAR_WRITE = "0000ae01-0000-1000-8000-00805f9b34fb"   # write-without-response
CHAR_NOTIFY = "0000ae02-0000-1000-8000-00805f9b34fb"  # status notifications

# --- print parameters -------------------------------------------------------
WIDTH = 384              # 58mm print head = 384 dots
MARGIN = 6
MSB_FIRST = False        # bit order within a byte; LSB-first is correct here
BLACK_THRESHOLD = 128
ENERGY = 0x3FFF          # darkness; higher = darker

# Monospace font with Greek/Latin glyphs. Override with PT1420_FONT.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",                        # macOS
    "/Library/Fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",    # Linux
]


def find_font() -> str:
    override = os.environ.get("PT1420_FONT")
    if override and os.path.exists(override):
        return override
    # matplotlib bundles DejaVu Sans Mono (wide glyph coverage) and is common.
    try:
        import matplotlib.font_manager as fm
        path = fm.findfont("DejaVu Sans Mono", fallback_to_default=False)
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("No monospace font found. Set PT1420_FONT to a .ttf path.")


# --- cat-printer protocol ---------------------------------------------------
def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def _cmd(command: int, payload: bytes) -> bytes:
    n = len(payload)
    return (bytes([0x51, 0x78, command, 0x00, n & 0xFF, (n >> 8) & 0xFF])
            + payload + bytes([crc8(payload), 0xFF]))


_GET_STATE = _cmd(0xA3, b"\x00")
_QUALITY   = _cmd(0xA4, b"\x32")                 # 200 dpi
_MODE_IMG  = _cmd(0xBE, b"\x00")                 # 0 = image, 1 = text
_ENERGY    = _cmd(0xAF, bytes([ENERGY & 0xFF, (ENERGY >> 8) & 0xFF]))
_LAT_ON    = _cmd(0xA6, bytes([0xAA,0x55,0x17,0x38,0x44,0x5F,0x5F,0x5F,0x44,0x38,0x2C]))
_LAT_OFF   = _cmd(0xA6, bytes([0xAA,0x55,0x17,0x00,0x00,0x00,0x00,0x00,0x00,0x17,0x11]))
_FEED      = _cmd(0xA1, bytes([0x30, 0x00]))


# --- content -> 1-bit image -------------------------------------------------
def fit_font(font_path: str, longest_chars: int) -> ImageFont.FreeTypeFont:
    """Pick the largest monospace size so `longest_chars` fit the print width."""
    usable = WIDTH - 2 * MARGIN
    probe = ImageFont.truetype(font_path, 40)
    w40 = probe.getlength("0" * max(1, longest_chars))
    size = max(8, int(40 * usable / w40))
    return ImageFont.truetype(font_path, size)


def text_to_image(text: str, font_path: str | None = None) -> Image.Image:
    """Render multi-line text to a 1-bit image WIDTH px wide (auto-fit font)."""
    font_path = font_path or find_font()
    lines = text.replace("\t", "    ").split("\n")
    longest = max((len(l) for l in lines), default=1)
    font = fit_font(font_path, longest)

    asc, desc = font.getmetrics()
    line_h = asc + desc + 2
    height = MARGIN + line_h * len(lines) + MARGIN + 72   # trailing feed room

    img = Image.new("L", (WIDTH, height), 255)
    draw = ImageDraw.Draw(img)
    y = MARGIN
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=0)
        y += line_h
    return img.point(lambda p: 0 if p < BLACK_THRESHOLD else 255, mode="1")


def image_from_file(path: str, dither: bool = True) -> Image.Image:
    """Load any image, scale to the print width, and reduce to 1-bit."""
    src = Image.open(path).convert("L")
    if src.width != WIDTH:
        h = max(1, round(src.height * WIDTH / src.width))
        src = src.resize((WIDTH, h), Image.LANCZOS)
    mono = src.convert("1") if dither else src.point(
        lambda p: 0 if p < BLACK_THRESHOLD else 255, mode="1")
    # add a little white tail so the last rows clear the tear bar
    out = Image.new("1", (WIDTH, mono.height + 64), 1)
    out.paste(mono, (0, 0))
    return out


def image_to_stream(img: Image.Image) -> bytes:
    """Encode a 1-bit image as a full cat-printer command stream."""
    px = img.load()
    W, H = img.size
    out = bytearray()
    out += _GET_STATE + _QUALITY + _MODE_IMG + _ENERGY + _LAT_ON
    for y in range(H):
        row = bytearray(WIDTH // 8)
        for x in range(WIDTH):
            if x < W and px[x, y] == 0:            # mode '1': 0 == black
                if MSB_FIRST:
                    row[x >> 3] |= 0x80 >> (x & 7)
                else:
                    row[x >> 3] |= 1 << (x & 7)
        out += _cmd(0xA2, bytes(row))
    out += _LAT_OFF + _FEED + _GET_STATE
    return bytes(out)


# --- BLE transport ----------------------------------------------------------
async def _find_device():
    if ADDRESS:
        dev = await BleakScanner.find_device_by_address(ADDRESS, timeout=15)
        if dev is not None:
            return dev
    return await BleakScanner.find_device_by_filter(
        lambda d, adv: (adv.local_name or d.name or "").startswith(NAME_HINT),
        timeout=15)


async def print_image(img: Image.Image, verbose: bool = True) -> None:
    stream = image_to_stream(img)
    if verbose:
        print(f"Image {img.size[0]}x{img.size[1]} -> {len(stream)} bytes.")
    dev = await _find_device()
    if dev is None:
        raise RuntimeError("Printer not found. Is it ON and free (not on a phone)?")
    if verbose:
        print(f"Connecting to {dev.name or '(no name)'} ...")
    async with BleakClient(dev) as client:
        if verbose:
            print("Connected:", client.is_connected)
        try:
            await client.start_notify(CHAR_NOTIFY,
                                      lambda _, d: verbose and print("  <-", d.hex()))
        except Exception:
            pass
        for i in range(0, len(stream), 120):     # write-without-response, paced
            await client.write_gatt_char(CHAR_WRITE, stream[i:i + 120], response=False)
            await asyncio.sleep(0.02)
        await asyncio.sleep(4)                    # let it flush before disconnect
    if verbose:
        print("Done.")


async def print_text(text: str, font_path: str | None = None, verbose: bool = True) -> None:
    await print_image(text_to_image(text, font_path), verbose=verbose)


# --- command line -----------------------------------------------------------
def _read_text(args) -> str:
    if args.file:
        return open(args.file, encoding="utf-8").read()
    if args.text == ["-"] or (not args.text and not sys.stdin.isatty()):
        return sys.stdin.read()
    if args.text:
        return " ".join(args.text)
    raise SystemExit("Nothing to print. Give text, --file, --image, or pipe stdin.")


def main() -> int:
    p = argparse.ArgumentParser(description="Print text or an image on the Powertech PT-1420 (BLE).")
    p.add_argument("text", nargs="*", help="Text to print (or '-' for stdin).")
    p.add_argument("--file", help="Print the contents of this text file.")
    p.add_argument("--image", help="Print this image file (scaled + dithered).")
    args = p.parse_args()

    if args.image:
        asyncio.run(print_image(image_from_file(args.image)))
    else:
        asyncio.run(print_text(_read_text(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
