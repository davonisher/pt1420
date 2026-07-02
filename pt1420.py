#!/usr/bin/env python3
"""
pt1420.py  -  Print op de Powertech PT-1420 (mini thermische "cat printer")
via Bluetooth LE.

De PT-1420 adverteert als 'X6h-0000' en spreekt het klassieke cat-printer
protocol (service AE30, schrijf-characteristic AE01). De USB-C poort laadt
alleen op - printen gaat uitsluitend over BLE.

Gebruik als module:
    import asyncio, pt1420
    asyncio.run(pt1420.print_text("Γεια σου!\\nHallo!"))

Gebruik vanaf de command line:
    python3 pt1420.py "Γεια σου!"          # tekst printen
    echo "hallo" | python3 pt1420.py -     # vanaf stdin
    python3 pt1420.py --file brief.txt      # een bestand
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from PIL import Image, ImageDraw, ImageFont
from bleak import BleakScanner, BleakClient

# --- BLE identiteit ---------------------------------------------------------
# De PT-1420 adverteert als 'X6h-...'. Het BLE-adres verschilt per Mac/toestel,
# dus standaard zoeken we op naam. Zet PT1420_ADDRESS in de omgeving om een
# specifiek adres (macOS CoreBluetooth-UUID) af te dwingen.
NAME_HINT = os.environ.get("PT1420_NAME", "X6h")
ADDRESS = os.environ.get("PT1420_ADDRESS", "")
CHAR_WRITE = "0000ae01-0000-1000-8000-00805f9b34fb"   # write-without-response
CHAR_NOTIFY = "0000ae02-0000-1000-8000-00805f9b34fb"  # status notify

# --- print-parameters -------------------------------------------------------
WIDTH = 384              # 58mm kop = 384 dots
MARGIN = 6
MSB_FIRST = False        # bit-volgorde: LSB-first is correct voor dit toestel
BLACK_THRESHOLD = 128
ENERGY = 0x3FFF          # donkerheid; hoger = donkerder

# Monospace font met Griekse glyphs. Overschrijf met PT1420_FONT.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",                        # macOS
    "/Library/Fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",    # Linux
]


def find_font() -> str:
    override = os.environ.get("PT1420_FONT")
    if override and os.path.exists(override):
        return override
    # matplotlib bundelt DejaVu Sans Mono (met Grieks) en is vaak aanwezig.
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
    raise FileNotFoundError("Geen monospace-font met Grieks gevonden. Zet PT1420_FONT.")


# --- protocol ---------------------------------------------------------------
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
_MODE_IMG  = _cmd(0xBE, b"\x00")                 # 0 = beeld, 1 = tekst
_ENERGY    = _cmd(0xAF, bytes([ENERGY & 0xFF, (ENERGY >> 8) & 0xFF]))
_LAT_ON    = _cmd(0xA6, bytes([0xAA,0x55,0x17,0x38,0x44,0x5F,0x5F,0x5F,0x44,0x38,0x2C]))
_LAT_OFF   = _cmd(0xA6, bytes([0xAA,0x55,0x17,0x00,0x00,0x00,0x00,0x00,0x00,0x17,0x11]))
_FEED      = _cmd(0xA1, bytes([0x30, 0x00]))


# --- tekst -> 1-bit afbeelding ----------------------------------------------
def fit_font(font_path: str, longest_chars: int) -> ImageFont.FreeTypeFont:
    """Kies de grootste monospace-fontgrootte zodat `longest_chars` past."""
    usable = WIDTH - 2 * MARGIN
    probe = ImageFont.truetype(font_path, 40)
    w40 = probe.getlength("0" * max(1, longest_chars))
    size = max(8, int(40 * usable / w40))
    return ImageFont.truetype(font_path, size)


def text_to_image(text: str, font_path: str | None = None) -> Image.Image:
    """Render meerregelige tekst naar een 1-bit afbeelding van WIDTH px breed."""
    font_path = font_path or find_font()
    lines = text.replace("\t", "    ").split("\n")
    longest = max((len(l) for l in lines), default=1)
    font = fit_font(font_path, longest)

    asc, desc = font.getmetrics()
    line_h = asc + desc + 2
    H = MARGIN + line_h * len(lines) + MARGIN + 72   # extra witruimte om af te scheuren

    img = Image.new("L", (WIDTH, H), 255)
    d = ImageDraw.Draw(img)
    y = MARGIN
    for ln in lines:
        d.text((MARGIN, y), ln, font=font, fill=0)
        y += line_h
    return img.point(lambda p: 0 if p < BLACK_THRESHOLD else 255, mode="1")


def image_to_stream(img: Image.Image) -> bytes:
    px = img.load()
    W, H = img.size
    out = bytearray()
    out += _GET_STATE + _QUALITY + _MODE_IMG + _ENERGY + _LAT_ON
    for y in range(H):
        row = bytearray(WIDTH // 8)
        for x in range(WIDTH):
            if x < W and px[x, y] == 0:            # mode '1': 0 == zwart
                if MSB_FIRST:
                    row[x >> 3] |= 0x80 >> (x & 7)
                else:
                    row[x >> 3] |= 1 << (x & 7)
        out += _cmd(0xA2, bytes(row))
    out += _LAT_OFF + _FEED + _GET_STATE
    return bytes(out)


# --- BLE-verzending ---------------------------------------------------------
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
        print(f"Afbeelding {img.size[0]}x{img.size[1]} -> {len(stream)} bytes.")
    dev = await _find_device()
    if dev is None:
        raise RuntimeError("Printer niet gevonden. Staat hij aan en vrij (niet op een telefoon)?")
    if verbose:
        print(f"Verbinden met {dev.name or '(geen naam)'} ...")
    async with BleakClient(dev) as client:
        if verbose:
            print("Verbonden:", client.is_connected)
        try:
            await client.start_notify(CHAR_NOTIFY,
                                      lambda _, d: verbose and print("  <-", d.hex()))
        except Exception:
            pass
        for i in range(0, len(stream), 120):
            await client.write_gatt_char(CHAR_WRITE, stream[i:i + 120], response=False)
            await asyncio.sleep(0.02)
        await asyncio.sleep(4)     # laten leegdraaien voor het verbreken
    if verbose:
        print("Klaar.")


async def print_text(text: str, font_path: str | None = None, verbose: bool = True) -> None:
    await print_image(text_to_image(text, font_path), verbose=verbose)


# --- command line -----------------------------------------------------------
def _read_input(args) -> str:
    if args.file:
        return open(args.file, encoding="utf-8").read()
    if args.text == ["-"] or (not args.text and not sys.stdin.isatty()):
        return sys.stdin.read()
    if args.text:
        return " ".join(args.text)
    raise SystemExit("Niets om te printen. Geef tekst, --file of pipe via stdin.")


def main() -> int:
    p = argparse.ArgumentParser(description="Print tekst op de Powertech PT-1420 (BLE).")
    p.add_argument("text", nargs="*", help="Tekst om te printen (of '-' voor stdin).")
    p.add_argument("--file", help="Print de inhoud van dit bestand.")
    args = p.parse_args()
    asyncio.run(print_text(_read_input(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
