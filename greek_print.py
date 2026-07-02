#!/usr/bin/env python3
"""
greek_print.py  -  Print de dagelijkse Griekse les op de Powertech PT-1420
(via Bluetooth LE, op deze Mac).

Haalt de les op uit het bestaande greek-tutor project (`learn_greek.py`) met
`--dry-run`, maar geformatteerd op smallere kolommen zodat hij netjes op de
58mm rol past, en print hem dan via pt1420.py.

    python3 greek_print.py                # les van vandaag
    python3 greek_print.py --day 1        # voorbeeld van lesdag 2
    python3 greek_print.py --cols 40      # meer kolommen = kleiner lettertype
    python3 greek_print.py --dry-run      # toon alleen de tekst, print niet

Let op: dit gebruikt --dry-run, dus greek-tutor slaat de voortgang
(spaced-repetition "seen") niet op. Draai het echte project als je dat wilt.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pt1420

# Pad naar het greek-tutor project (apart, persoonlijk project). Overschrijf
# met de omgevingsvariabele GREEK_TUTOR_DIR.
TUTOR_DIR = Path(os.environ.get("GREEK_TUTOR_DIR", str(Path.home() / "greek-tutor")))
TUTOR_SCRIPT = TUTOR_DIR / "learn_greek.py"
TUTOR_CONFIG = TUTOR_DIR / "config.toml"


def lesson_text(cols: int, day: int | None) -> str:
    """Draai learn_greek.py --dry-run met een aangepaste kolombreedte."""
    # Config kopieren en alleen line_width overschrijven (de les wordt dan
    # op `cols` kolommen opgemaakt i.p.v. 48).
    cfg = TUTOR_CONFIG.read_text(encoding="utf-8")
    cfg = re.sub(r"(?m)^(\s*line_width\s*=\s*)\d+", rf"\g<1>{cols}", cfg)

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False,
                                     encoding="utf-8") as tmp:
        tmp.write(cfg)
        tmp_path = tmp.name

    cmd = [sys.executable, str(TUTOR_SCRIPT), "--dry-run", "--config", tmp_path]
    if day is not None:
        cmd += ["--day", str(day)]

    print(f"Les ophalen uit greek-tutor ({cols} kolommen)...")
    proc = subprocess.run(cmd, cwd=str(TUTOR_DIR), capture_output=True,
                          text=True, timeout=180)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"greek-tutor faalde (exit {proc.returncode}).")
    return proc.stdout.rstrip("\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Print de dagelijkse Griekse les op de PT-1420.")
    p.add_argument("--cols", type=int, default=32,
                   help="Kolombreedte van de les (default 32; minder = groter lettertype).")
    p.add_argument("--day", type=int, default=None,
                   help="Forceer een lesdag-index (voorbeeld).")
    p.add_argument("--dry-run", action="store_true",
                   help="Toon de les-tekst en print niet.")
    args = p.parse_args()

    text = lesson_text(args.cols, args.day)

    if args.dry_run:
        print(text)
        return 0

    asyncio.run(pt1420.print_text(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
