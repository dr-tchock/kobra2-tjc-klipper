#!/usr/bin/env python3
"""Render Material Design Icons (as used by Mainsail) into PNGs for the .tft.

Pictures on the panel are opaque, so each icon is rendered onto the exact
background colour it will sit on (plus a darker "pressed" variant).

Usage: make_icons.py out_dir
Writes out_dir/NN_name_variant.png (NN = import order = picture id) and
out_dir/_sheet.png for a quick visual check.
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "..", "assets", "fonts")

# Theme (Mainsail-like dark)
BG = "#121212"          # page background
SURFACE = "#2a2a2a"     # button face
SURFACE_DOWN = "#1565c0"  # button face while pressed
FG = "#ffffff"

SIZE = 48  # icon square in px (button icons)

# Starter set: (name in our UI, mdi icon name)
ICONS = [
    ("home", "home"),
    ("nozzle", "printer-3d-nozzle"),
    ("bed", "radiator"),
    ("fan", "fan"),
    ("play", "play"),
    ("pause", "pause"),
    ("stop", "stop"),
    ("estop", "alert-octagon"),
    ("up", "arrow-up-bold"),
    ("down", "arrow-down-bold"),
    ("left", "arrow-left-bold"),
    ("right", "arrow-right-bold"),
    ("plus", "plus"),
    ("minus", "minus"),
    ("check", "check"),
    ("close", "close"),
    ("files", "file-document-multiple"),
    ("move", "arrow-all"),
    ("temp", "thermometer"),
    ("cool", "snowflake"),
    ("motors_off", "engine-off"),
    ("filament", "printer-3d-nozzle-heat"),
    ("load", "download"),
    ("unload", "upload"),
    ("settings", "cog"),
    ("mesh", "grid"),
    ("level", "screw-machine-flat-top"),
    ("restart", "restart"),
    # Z offset (same icons as Mainsail's Z-offset panel)
    ("z_offset", "arrow-collapse-vertical"),
    ("z_up", "arrow-expand-up"),
    ("z_down", "arrow-collapse-down"),
    ("save", "content-save"),
]
VARIANTS = [("n", SURFACE), ("p", SURFACE_DOWN)]

# Small icons for the top status bar (one variant, not pressable)
BAR = "#1e1e1e"
SMALL_SIZE = 24
SMALL_ICONS = [
    ("s_nozzle", "printer-3d-nozzle"),
    ("s_bed", "radiator"),
    ("s_fan", "fan"),
]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    meta = json.load(open(os.path.join(FONTS, "mdi-meta.json"), encoding="utf-8"))
    code = {m["name"]: int(m["codepoint"], 16) for m in meta}
    font = ImageFont.truetype(os.path.join(FONTS, "materialdesignicons-webfont.ttf"),
                              SIZE - 8)
    small_font = ImageFont.truetype(
        os.path.join(FONTS, "materialdesignicons-webfont.ttf"), SMALL_SIZE - 2)
    missing = [mdi for _, mdi in ICONS + SMALL_ICONS if mdi not in code]
    if missing:
        sys.exit("unknown mdi icons: %s" % missing)
    pid = 0
    tiles = []

    def render(name, mdi, vname, bg, size, fnt):
        nonlocal pid
        im = Image.new("RGB", (size, size), bg)
        d = ImageDraw.Draw(im)
        d.text((size / 2, size / 2), chr(code[mdi]), font=fnt, fill=FG,
               anchor="mm")
        im.save(os.path.join(out, "%02d_%s_%s.png" % (pid, name, vname)))
        # Show small icons on a 48px tile in the sheet
        tile = Image.new("RGB", (SIZE, SIZE), bg)
        tile.paste(im, ((SIZE - size) // 2, (SIZE - size) // 2))
        tiles.append((pid, name, vname, tile))
        pid += 1

    for name, mdi in ICONS:
        for vname, bg in VARIANTS:
            render(name, mdi, vname, bg, SIZE, font)
    for name, mdi in SMALL_ICONS:
        render(name, mdi, "s", BAR, SMALL_SIZE, small_font)
    # Contact sheet
    cols = 8
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 70, rows * 74), BG)
    d = ImageDraw.Draw(sheet)
    for i, (p, name, vname, im) in enumerate(tiles):
        x, y = (i % cols) * 70 + 11, (i // cols) * 74 + 4
        sheet.paste(im, (x, y))
        d.text((x + 24, y + 58), "%d %s" % (p, name[:8]), fill="#9e9e9e",
               anchor="mt")
    sheet.save(os.path.join(out, "_sheet.png"))
    print("%d pictures (%d icons x %d variants + %d small) in %s"
          % (len(tiles), len(ICONS), len(VARIANTS), len(SMALL_ICONS), out))


if __name__ == "__main__":
    main()
