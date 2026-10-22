#!/usr/bin/env python3
"""Render screen pages to PNG using the same layout code as the panel.

PilCanvas implements the canvas primitives of screen/ui.py with Pillow,
using the real Roboto fonts and the icon PNGs that are in the .tft.
Usage: mockup.py out_dir
"""
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "screen"))
import ui  # noqa: E402

ICON_DIR = os.path.join(ROOT, "assets", "icons")


class PilCanvas:
    def __init__(self):
        self.im = Image.new("RGB", (ui.W, ui.H), ui.BG)
        self.d = ImageDraw.Draw(self.im)
        self.fonts = [ImageFont.truetype(
            os.path.join(ROOT, "assets", "fonts", "Roboto-Regular.ttf"),
            int(px * 0.82)) for px in ui.FONT_PX]
        self.icons = {int(f[:2]): f for f in os.listdir(ICON_DIR)
                      if f[:2].isdigit()}

    def clear(self, color):
        self.d.rectangle((0, 0, ui.W, ui.H), fill=color)

    def fill(self, x, y, w, h, color):
        if w > 0 and h > 0:
            self.d.rectangle((x, y, x + w - 1, y + h - 1), fill=color)

    def circle(self, cx, cy, r, color):
        self.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)

    def pic(self, x, y, pid):
        self.im.paste(Image.open(os.path.join(ICON_DIR, self.icons[pid])),
                      (x, y))

    def text(self, x, y, w, h, s, fg, bg, font, align=1):
        self.fill(x, y, w, h, bg)
        ax = {0: x, 1: x + w // 2, 2: x + w}[align]
        anchor = {0: "lm", 1: "mm", 2: "rm"}[align]
        self.d.text((ax, y + h // 2), s, font=self.fonts[font], fill=fg,
                    anchor=anchor)


def sample_state(printing=False):
    now = time.time()
    files = [  # invented examples
        dict(name="spool_holder_PLA_0.2_1h52m.gcode", modified=now - 3 * 3600,
             estimated_time=6720, filament_weight_total=24.6, layer_height=0.2,
             first_layer_extr_temp=200, first_layer_bed_temp=60),
        dict(name="cable_clip_PLA_0.2_14m.gcode", modified=now - 26 * 3600,
             estimated_time=840, filament_weight_total=3.2),
        dict(name="desk_hook_PLA_0.2_31m.gcode", modified=now - 3 * 86400,
             estimated_time=1860, filament_weight_total=9.5),
        dict(name="gear_demo_PETG_0.2_48m.gcode", modified=now - 9 * 86400,
             estimated_time=2880, filament_weight_total=14.1),
    ]
    st = dict(
        chip="printing" if printing else "ready", klippy="ready",
        klippy_msg="Printer is ready", printing=printing,
        job_state="printing" if printing else "standby",
        temps=[(200, 200), (60, 60)] if printing else [(21, 0), (24, 0)],
        job=dict(state="printing", filename=files[0]["name"], progress=0.42,
                 remaining=3900, elapsed=2820, layer=34, layers=120, z=6.8),
        pos=[110.0, 110.0, 6.8], homed="xyz" if printing else "",
        z_offset=-0.025, speed=1.0, flow=1.0, fan=1.0 if printing else 0.,
        runout=True, ip="192.168.1.50",
        screws={"screw1": dict(name="front left", is_base=True, adjust="00:00",
                               sign="CW"),
                "screw2": dict(name="front right", is_base=False, adjust="00:03",
                               sign="CW"),
                "screw3": dict(name="rear right", is_base=False, adjust="00:18",
                               sign="CCW"),
                "screw4": dict(name="rear left", is_base=False, adjust="00:09",
                               sign="CW")},
        mesh=dict(profile="default", matrix=[
            [-0.05, -0.02, 0.01, 0.03, 0.02],
            [-0.03, 0.00, 0.02, 0.05, 0.04],
            [-0.02, 0.01, 0.03, 0.06, 0.07],
            [-0.04, 0.00, 0.02, 0.04, 0.05],
            [-0.07, -0.03, 0.00, 0.02, 0.03]]),
    )
    u = dict(file_page=0, file_pages=70, page_files=files, detail=files[0],
             armed=None, move_step=10, z_step=0.025)
    return st, u


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for printing in (False, True):
        st, u = sample_state(printing)
        for name, page in ui.PAGES.items():
            if name == "job" and not printing:
                continue
            c = PilCanvas()
            page.draw(c, st, u)
            c.im.save(os.path.join(out, "%s%s.png" % (name, "_printing"
                                                      if printing else "")))
    print("mockups written to", out)


if __name__ == "__main__":
    main()
