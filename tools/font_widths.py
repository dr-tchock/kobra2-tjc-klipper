#!/usr/bin/env python3
"""Regenerate screen/font_widths.json: character widths per screen font.

The screen program uses it to trim long texts (file names) with "..." so
they fit. Sizes must match the fonts in the .tft (Roboto 16/20/24/32/48).
Usage: font_widths.py   (needs Pillow and tools/fetch_fonts.sh run once)
"""
import json
import os

from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SIZES = [16, 20, 24, 32, 48]
CHARS = [chr(c) for c in range(0x20, 0x7f)] + ["\xb0"]


def main():
    ttf = os.path.join(ROOT, "assets", "fonts", "Roboto-Regular.ttf")
    out = []
    for px in SIZES:
        # TJC font height = full line cell; Roboto glyphs fill ~0.82 of it
        f = ImageFont.truetype(ttf, int(px * 0.82))
        out.append({ch: round(f.getlength(ch), 2) for ch in CHARS})
    path = os.path.join(ROOT, "screen", "font_widths.json")
    with open(path, "w") as fh:
        json.dump(out, fh)
    print("wrote", path)


if __name__ == "__main__":
    main()
