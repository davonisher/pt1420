#!/usr/bin/env python3
"""
Example: print a generated text document on the PT-1420.

This prints a daily Greek lesson produced by a separate project, "greek-tutor"
(https://github.com/davonisher/greek-tutor is the author's personal project and
is NOT part of this repo). It runs `learn_greek.py --dry-run` with a temporary
config that narrows the layout to fit the 58mm roll, then prints the output.

It is included to show the general pattern: generate text somewhere, then hand
it to `pt1420.print_text(...)`. Swap in any command that emits text.

    python3 examples/greek_lesson.py                 # today's lesson
    python3 examples/greek_lesson.py --day 1          # preview a specific day
    python3 examples/greek_lesson.py --cols 40        # smaller font (more cols)
    python3 examples/greek_lesson.py --dry-run        # show text, don't print

Set GREEK_TUTOR_DIR to point at your greek-tutor checkout (default ~/greek-tutor).
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pt1420

TUTOR_DIR = Path(os.environ.get("GREEK_TUTOR_DIR", str(Path.home() / "greek-tutor")))
TUTOR_SCRIPT = TUTOR_DIR / "learn_greek.py"
TUTOR_CONFIG = TUTOR_DIR / "config.toml"


def lesson_text(cols: int, day: int | None) -> str:
    """Run learn_greek.py --dry-run with an overridden column width."""
    if not TUTOR_SCRIPT.exists():
        raise SystemExit(f"greek-tutor not found at {TUTOR_DIR}. Set GREEK_TUTOR_DIR.")

    # Copy the config and override only line_width so the lesson is laid out
    # for `cols` columns instead of 48.
    cfg = TUTOR_CONFIG.read_text(encoding="utf-8")
    cfg = re.sub(r"(?m)^(\s*line_width\s*=\s*)\d+", rf"\g<1>{cols}", cfg)
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False,
                                     encoding="utf-8") as tmp:
        tmp.write(cfg)
        tmp_path = tmp.name

    cmd = [sys.executable, str(TUTOR_SCRIPT), "--dry-run", "--config", tmp_path]
    if day is not None:
        cmd += ["--day", str(day)]

    print(f"Fetching lesson from greek-tutor ({cols} columns)...")
    proc = subprocess.run(cmd, cwd=str(TUTOR_DIR), capture_output=True,
                          text=True, timeout=180)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"greek-tutor failed (exit {proc.returncode}).")
    return proc.stdout.rstrip("\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Print the daily Greek lesson on the PT-1420.")
    p.add_argument("--cols", type=int, default=32,
                   help="Lesson column width (default 32; fewer = larger font).")
    p.add_argument("--day", type=int, default=None, help="Force a lesson-day index (preview).")
    p.add_argument("--dry-run", action="store_true", help="Print the text to stdout, not the printer.")
    args = p.parse_args()

    text = lesson_text(args.cols, args.day)
    if args.dry_run:
        print(text)
        return 0
    asyncio.run(pt1420.print_text(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
