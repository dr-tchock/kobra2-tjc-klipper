"""Page layouts for the Kobra 2 screen, drawn through a small canvas API.

Two canvases implement the same primitives: TjcCanvas (real panel, in
kobra_screen.py) and PilCanvas (PNG mockups, tools/mockup.py). Pages only use
what the panel can do: fills, filled circles, stored pictures and Roboto text.

Every page is a Page object: draw() paints it and returns its Buttons,
dyn_key() describes the live values on it, update() repaints just those.
A Button knows its area, how to paint itself (normal/pressed/disabled) and
whether it is enabled right now (e.g. greyed out during a print).

st = printer state (built by the app from Moonraker), u = screen-side state
(selected step sizes, armed confirmations, file list page, ...).
"""
import json
import os
import time

W, H = 272, 480

# Theme (Mainsail-like dark). CARD/SURFACE/SURFACE_DOWN must match the
# backgrounds the icons were rendered on (tools/make_icons.py).
BG = "#121212"
CARD = "#1e1e1e"
SURFACE = "#2a2a2a"
SURFACE_DOWN = "#1565c0"
TRACK = "#333333"
DISABLED = "#232323"
DISABLED_TEXT = "#5f5f5f"
TEXT = "#ffffff"
MUTED = "#9e9e9e"
PRIMARY = "#2196f3"
OK = "#4caf50"
WARN = "#ffa726"
ERR = "#f44336"
HOT = "#ff5252"     # extruder accent
BED = "#ffa726"     # bed accent

# Fonts in the .tft (Roboto, ASCII + degree sign), by size
F16, F20, F24, F32, F48 = range(5)
FONT_PX = [16, 20, 24, 32, 48]

# Pictures in the .tft, in tools/make_icons.py import order:
# button icon i = normal 2*i, pressed 2*i + 1; small icons after them.
_BUTTON_ICONS = ["home", "nozzle", "bed", "fan", "play", "pause", "stop",
                 "estop", "up", "down", "left", "right", "plus", "minus",
                 "check", "close", "files", "move", "temp", "cool",
                 "motors_off", "filament", "load", "unload", "settings",
                 "mesh", "level", "restart", "z_offset", "z_up", "z_down",
                 "save"]
ICON = {name: 2 * i for i, name in enumerate(_BUTTON_ICONS)}
SMALL = {"nozzle": 64, "bed": 65, "fan": 66}
ICON_PX = 48

# State chip: klipper/print state -> (label, colour, chip background)
CHIPS = {
    "ready": ("Ready", OK, "#1b3a1d"),
    "printing": ("Printing", PRIMARY, "#0d2c45"),
    "paused": ("Paused", WARN, "#3d2a0c"),
    "startup": ("Starting", WARN, "#3d2a0c"),
    "error": ("Error", ERR, "#3d1513"),
    "shutdown": ("Shutdown", ERR, "#3d1513"),
    "offline": ("Offline", MUTED, "#2a2a2a"),
    "busy": ("Busy", PRIMARY, "#0d2c45"),
}


def can_gcode(st):
    """Klipper can take commands now (not stuck behind a long one)."""
    return st["klippy"] == "ready" and not st.get("busy")


def idle(st):
    """Safe for actions that would ruin a print."""
    return can_gcode(st) and not st["printing"]

APPBAR_H = 44
NAV_Y = 404
NAV_TABS = [("home", "home", "Home"), ("print", "files", "Print"),
            ("move", "move", "Move"), ("more", "settings", "More")]
NAV_W = W // len(NAV_TABS)
TILE_W, TILE_H = 116, 80
COL = (16, 140)          # x of the two tile columns inside a card

MOVE_STEPS = [0.1, 1, 10, 50]
Z_STEPS = [0.005, 0.01, 0.025, 0.05]
PRESETS = {"PLA": (190, 60), "PETG": (235, 80)}
TEMP_STEP, FAN_STEP, SPEED_STEP, FLOW_STEP = 5, 10, 10, 5
FILE_ROWS = 4


# --- Helpers -----------------------------------------------------------------
_WIDTHS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "font_widths.json")))


def text_width(s, font):
    w = _WIDTHS[font]
    return sum(w.get(ch, w["M"]) for ch in s)


def fit(s, font, max_w):
    """Trim s with '...' so it fits max_w px (5% safety for panel rendering)."""
    max_w *= 0.95
    if text_width(s, font) <= max_w:
        return s
    while s and text_width(s + "...", font) > max_w:
        s = s[:-1]
    return s + "..."


def duration(sec):
    sec = int(sec or 0)
    h, m = sec // 3600, (sec % 3600) // 60
    return "%dh %02dm" % (h, m) if h else "%dm" % m


def age(ts, now=None):
    d = (now or time.time()) - ts
    if d < 3600:
        return "%dm ago" % max(1, d // 60)
    if d < 86400:
        return "%dh ago" % (d // 3600)
    if d < 86400 * 60:
        return "%dd ago" % (d // 86400)
    return time.strftime("%d %b %Y", time.localtime(ts))


def display_name(path):
    name = path.rsplit("/", 1)[-1]
    return name[:-6] if name.lower().endswith(".gcode") else name


def step_label(v):
    return ("%g" % v)


def hit(rect, x, y):
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def rrect(c, x, y, w, h, r, color):
    """Rounded rectangle from two fills and four filled circles.

    A circle of radius r is 2r+1 px wide, so r is capped to keep the corner
    circles inside the box (otherwise thin bars leak a pixel row).
    """
    r = max(0, min(r, (w - 1) // 2, (h - 1) // 2))
    if w > 2 * r:
        c.fill(x + r, y, w - 2 * r, h, color)
    if h > 2 * r:
        c.fill(x, y + r, w, h - 2 * r, color)
    for cx, cy in ((x + r, y + r), (x + w - r - 1, y + r),
                   (x + r, y + h - r - 1), (x + w - r - 1, y + h - r - 1)):
        c.circle(cx, cy, r, color)


def card(c, y, h, title=None, right=None):
    rrect(c, 8, y, 256, h, 10, CARD)
    if title:
        card_header(c, y, title, right)


def card_header(c, y, title, right=None, color=MUTED):
    c.text(18, y + 4, 236 if not right else 150, 22, title, color, CARD, F16,
           align=0)
    if right:
        c.text(168, y + 4, 86, 22, right, MUTED, CARD, F16, align=2)


def card_message(c, y, text, color):
    """Temporary feedback in place of a card header."""
    c.text(18, y + 4, 236, 22, fit(text, F16, 236), color, CARD, F16, align=0)


def bar(c, x, y, w, h, frac, color):
    c.fill(x - 2, y - 2, w + 4, h + 4, CARD)  # wipe old bar completely
    rrect(c, x, y, w, h, h // 2, TRACK)
    filled = int(w * max(0., min(frac, 1.)))
    if filled >= h:
        rrect(c, x, y, filled, h, h // 2, color)


# --- Buttons ------------------------------------------------------------------
class Button:
    def __init__(self, key, rect, paint, enabled=True, arg=None):
        self.key, self.rect, self.paint = key, rect, paint
        self.enabled, self.arg = enabled, arg

    def draw(self, c, pressed=False):
        self.paint(c, self.rect, pressed, self.enabled)


def tile(icon, label=None, primary=False, armed=None, fallback=None):
    """Painter for an icon tile; label below the icon if given.

    primary: blue at rest. armed: callable -> label shown while a
    confirmation is armed (tile turns blue). fallback: text shown instead of
    the icon when disabled (no grey icons in the .tft yet).
    """
    def paint(c, rect, pressed, enabled):
        x, y, w, h = rect
        if not enabled:
            rrect(c, x, y, w, h, 8, DISABLED)
            txt = fallback or label or ""
            c.text(x + 2, y + (h - 24) // 2, w - 4, 24, txt, DISABLED_TEXT,
                   DISABLED, F20 if fallback and not label else F16, align=1)
            return
        armed_label = armed() if armed else None
        blue = pressed != primary or bool(armed_label)
        face = SURFACE_DOWN if blue else SURFACE
        rrect(c, x, y, w, h, 8, face)
        lab = armed_label or label
        iy = y + (h - ICON_PX) // 2 if not lab else y + max(2, (h - 70) // 2)
        c.pic(x + (w - ICON_PX) // 2, iy, ICON[icon] + (1 if blue else 0))
        if lab:
            c.text(x + 2, iy + ICON_PX, w - 4, 20, fit(lab, F16, w - 4), TEXT,
                   face, F16, align=1)
    return paint


def text_btn(label, selected=False):
    def paint(c, rect, pressed, enabled):
        x, y, w, h = rect
        if not enabled:
            face, fg = DISABLED, DISABLED_TEXT
        else:
            blue = pressed or selected
            face, fg = (SURFACE_DOWN if blue else SURFACE), TEXT
        rrect(c, x, y, w, h, 8, face)
        c.text(x + 2, y + (h - 26) // 2, w - 4, 26, label, fg, face, F20, align=1)
    return paint


def segmented(key, values, selected, y, enabled=True, x0=16, w_total=240):
    """Row of text buttons for picking a step size."""
    n = len(values)
    gap = 6
    w = (w_total - gap * (n - 1)) // n
    out = []
    for i, v in enumerate(values):
        out.append(Button(key, (x0 + i * (w + gap), y, w, 40),
                          text_btn(step_label(v), v == selected), enabled, v))
    return out


# --- Shared chrome --------------------------------------------------------------
def draw_appbar(c, chip, title=None):
    """App bar; with a title it becomes '< title' and returns a back button."""
    c.fill(0, 0, W, APPBAR_H, CARD)
    out = []
    if title:
        c.text(8, 0, 160, APPBAR_H, "< " + title, TEXT, CARD, F24, align=0)
        out.append(Button("back", (0, 0, 170, APPBAR_H), lambda *a: None))
    else:
        c.text(12, 0, 150, APPBAR_H, "Kobra 2", TEXT, CARD, F24, align=0)
    draw_chip(c, chip)
    return out


def draw_chip(c, chip):
    label, fg, bg = CHIPS.get(chip, CHIPS["offline"])
    c.fill(170, 6, 102, 32, CARD)
    rrect(c, 180, 11, 84, 22, 11, bg)
    c.circle(193, 22, 4, fg)
    c.text(201, 12, 60, 20, label, fg, bg, F16, align=0)


def nav_paint(i, active):
    def paint(c, rect, pressed, enabled):
        key, icon, label = NAV_TABS[i]
        tx, ty, tw, th = rect
        c.fill(tx, ty, tw, th, CARD)
        if active:
            c.fill(tx + 8, ty, tw - 16, 3, PRIMARY)
        blue = active or pressed
        rrect(c, tx + 6, ty + 7, tw - 12, 52, 8, SURFACE_DOWN if blue else SURFACE)
        c.pic(tx + (tw - ICON_PX) // 2, ty + 9, ICON[icon] + (1 if blue else 0))
        c.text(tx, ty + 60, tw, 16, label, PRIMARY if active else MUTED, CARD,
               F16, align=1)
    return paint


def draw_nav(c, active):
    c.fill(0, NAV_Y, W, H - NAV_Y, CARD)
    out = []
    for i, (key, _, _) in enumerate(NAV_TABS):
        b = Button("nav", (i * NAV_W, NAV_Y, NAV_W, H - NAV_Y),
                   nav_paint(i, key == active), True, key)
        b.draw(c)
        out.append(b)
    return out


def finish(c, buttons):
    for b in buttons:
        b.draw(c)
    return buttons


def pm_row(c, key, y, label, value, enabled=True, label_icon=None):
    """'label  [-]  value  [+]' row; returns the two buttons."""
    x = 18
    if label_icon:
        c.pic(18, y + 14, SMALL[label_icon])
        x = 46
    c.text(x, y, 92 - x + 18, 52, label, TEXT, CARD, F20, align=0)
    pm_value(c, y, value)
    return [Button(key, (92, y, 52, 52), tile("minus", fallback="-"), enabled, -1),
            Button(key, (208, y, 52, 52), tile("plus", fallback="+"), enabled, +1)]


def pm_value(c, y, value):
    c.text(146, y, 60, 52, value, TEXT, CARD, F24, align=1)


# --- Pages ---------------------------------------------------------------------
class Page:
    tab = None          # nav tab to highlight
    parent = None       # page "< back" goes to (sub-pages only)
    title = None        # sub-page title in the app bar
    msg_y = 50          # card whose header shows feedback messages
    header = ""         # that card's normal header text

    def draw(self, c, st, u):
        raise NotImplementedError

    def restore_header(self, c, st, u):
        card_header(c, self.msg_y, self.header)

    def dyn_key(self, st, u):
        return None

    def update(self, c, st, u):
        pass

    def chrome(self, c, st):
        c.clear(BG)
        return draw_appbar(c, st["chip"], self.title)


# Home ---------------------------------------------------------------------------
TEMP_ROWS = [("nozzle", "Extruder", HOT, 80), ("bed", "Bed", BED, 130)]
ACT_TILES = [("home", "home", "Home all", 16, 222),
             ("preheat", "temp", "Preheat PLA", 140, 222),
             ("cool", "cool", "Cool down", 16, 308),
             ("motors_off", "motors_off", "Motors off", 140, 308)]


def draw_temp_values(c, temps):
    for (icon, name, accent, ry), (act, tgt) in zip(TEMP_ROWS, temps):
        c.text(140, ry - 4, 76, 40, "%d\xb0" % round(act), TEXT, CARD, F32, align=2)
        c.text(216, ry + 6, 40, 24, "/%d" % round(tgt), MUTED, CARD, F16, align=2)
        bar(c, 18, ry + 38, 236, 6, act / tgt if tgt > 0 else 0., accent)


class HomePage(Page):
    tab = "home"
    msg_y = 190
    msg_y = 190
    header = "QUICK ACTIONS"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 134, "TEMPERATURES")
        for icon, name, _, ry in TEMP_ROWS:
            c.pic(18, ry + 4, SMALL[icon])
            c.text(48, ry, 90, 32, name, TEXT, CARD, F20, align=0)
        draw_temp_values(c, st["temps"])
        card(c, 190, 208, "QUICK ACTIONS")
        for key, icon, label, x, y in ACT_TILES:
            btns.append(Button("quick", (x, y, TILE_W, TILE_H),
                               tile(icon, label), idle(st), key))
        return finish(c, btns) + draw_nav(c, self.tab)

    def dyn_key(self, st, u):
        return [(round(a), round(t)) for a, t in st["temps"]]

    def update(self, c, st, u):
        draw_temp_values(c, st["temps"])


# Print: file list -----------------------------------------------------------------
class FilesPage(Page):
    tab = "print"
    header = "FILES"

    def restore_header(self, c, st, u):
        card_header(c, 50, "FILES", "%d / %d" % (u["file_page"] + 1,
                                                u["file_pages"]))

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        page, pages = u["file_page"], u["file_pages"]
        card(c, 50, 348, "FILES", "%d / %d" % (page + 1, pages))
        files = u["page_files"]
        for i in range(FILE_ROWS):
            rect = (16, 80 + i * 66, 240, 60)
            if i < len(files):
                btns.append(Button("file", rect, file_row(files[i]), True, i))
        if page > 0:
            btns.append(Button("pager", (16, 344, 116, 50), tile("up"), True, -1))
        if page < pages - 1:
            btns.append(Button("pager", (140, 344, 116, 50), tile("down"), True, 1))
        return finish(c, btns) + draw_nav(c, self.tab)


def file_row(f, now=None):
    def paint(c, rect, pressed, enabled):
        x, y, w, h = rect
        face = SURFACE_DOWN if pressed else SURFACE
        rrect(c, x, y, w, h, 8, face)
        c.text(x + 10, y + 4, w - 20, 28, fit(display_name(f["name"]), F20, w - 20),
               TEXT, face, F20, align=0)
        bits = []
        if f.get("estimated_time"):
            bits.append(duration(f["estimated_time"]))
        if f.get("filament_weight_total"):
            bits.append("%.0f g" % f["filament_weight_total"])
        bits.append(age(f["modified"], now))
        c.text(x + 10, y + 32, w - 20, 22, "  |  ".join(bits),
               TEXT if pressed else MUTED, face, F16, align=0)
    return paint


# Print: start confirmation ---------------------------------------------------------
class DetailPage(Page):
    tab = "print"
    header = "START PRINT?"

    def draw(self, c, st, u):
        f = u["detail"]
        btns = self.chrome(c, st)
        card(c, 50, 246, "START PRINT?")
        name = display_name(f["name"])
        first = fit(name, F24, 236)
        if first.endswith("...") and len(name) > len(first) - 3:
            line1 = first[:-3]
            line2 = fit(name[len(line1):], F24, 236)
        else:
            line1, line2 = name, ""
        c.text(18, 80, 236, 30, line1, TEXT, CARD, F24, align=0)
        if line2:
            c.text(18, 110, 236, 30, line2, TEXT, CARD, F24, align=0)
        stats = [
            ("Print time", duration(f["estimated_time"])
             if f.get("estimated_time") else "-"),
            ("Filament", "%.1f g" % f["filament_weight_total"]
             if f.get("filament_weight_total") else "-"),
            ("Layer height", "%.2f mm" % f["layer_height"]
             if f.get("layer_height") else "-"),
            ("Nozzle / bed", "%d\xb0 / %d\xb0" % (f.get("first_layer_extr_temp") or 0,
                                                 f.get("first_layer_bed_temp") or 0)),
        ]
        for i, (label, value) in enumerate(stats):
            sx, sy = 18 + (i % 2) * 122, 150 + (i // 2) * 70
            c.text(sx, sy, 116, 22, label, MUTED, CARD, F16, align=0)
            c.text(sx, sy + 22, 116, 30, value, TEXT, CARD, F24, align=0)
        btns.append(Button("detail_back", (16, 308, TILE_W, TILE_H),
                           tile("close", "Back")))
        btns.append(Button("start", (140, 308, TILE_W, TILE_H),
                           tile("play", "Print", primary=True),
                           idle(st)))
        return finish(c, btns) + draw_nav(c, self.tab)


# Print: job status -------------------------------------------------------------------
def draw_job_values(c, job, temps):
    prog = job["progress"]
    c.text(18, 110, 120, 60, "%d%%" % int(prog * 100), TEXT, CARD, F48, align=0)
    left = job.get("remaining")
    c.text(138, 112, 118, 28, (duration(left) + " left") if left else "", TEXT,
           CARD, F20, align=2)
    eta = time.strftime("ETA %H:%M", time.localtime(time.time() + left)) \
        if left else ""
    c.text(138, 140, 118, 24, eta, MUTED, CARD, F16, align=2)
    bar(c, 18, 176, 236, 8, prog, PRIMARY)
    stats = [("Layer", "%s / %s" % (job.get("layer") or "-",
                                     job.get("layers") or "-")),
             ("Height", "%.2f mm" % job.get("z", 0.)),
             ("Elapsed", duration(job.get("elapsed")))]
    for i, (label, value) in enumerate(stats):
        sx = 18 + i * 80
        c.text(sx, 196, 76, 20, label, MUTED, CARD, F16, align=0)
        c.text(sx, 216, 76, 26, value, TEXT, CARD, F20, align=0)
    for i, (icon, (act, tgt)) in enumerate(zip(("nozzle", "bed"), temps)):
        tx = 18 + i * 122
        c.pic(tx, 262, SMALL[icon])
        c.text(tx + 30, 258, 90, 32, "%d / %d\xb0" % (round(act), round(tgt)),
               TEXT, CARD, F20, align=0)


def job_header(c, state):
    card_header(c, 50, "PAUSED" if state == "paused" else "PRINTING",
                color=WARN if state == "paused" else MUTED)


class JobPage(Page):
    tab = "print"

    def restore_header(self, c, st, u):
        job_header(c, st["job"]["state"] if st["job"] else "printing")

    def draw(self, c, st, u):
        job = st["job"]
        btns = self.chrome(c, st)
        card(c, 50, 260)
        job_header(c, job["state"])
        c.text(18, 78, 236, 28, fit(display_name(job["filename"]), F20, 236),
               TEXT, CARD, F20, align=0)
        draw_job_values(c, job, st["temps"])
        paused = job["state"] == "paused"
        btns.append(Button("pause", (16, 318, 76, 80),
                           tile("play" if paused else "pause",
                                "Resume" if paused else "Pause")))
        btns.append(Button("goto", (98, 318, 76, 80), tile("settings", "Tune"),
                           True, "tune"))
        btns.append(Button("cancel", (180, 318, 76, 80),
                           tile("stop", "Cancel", armed=lambda: "Confirm?"
                                if u["armed"] == "cancel" else None)))
        return finish(c, btns) + draw_nav(c, self.tab)

    def dyn_key(self, st, u):
        j = st["job"] or {}
        return (int(j.get("progress", 0) * 100), int(j.get("remaining") or 0) // 60,
                j.get("layer"), j.get("layers"), round(j.get("z", 0), 2),
                int(j.get("elapsed") or 0) // 60,
                tuple((round(a), round(t)) for a, t in st["temps"]),
                time.strftime("%H:%M"))

    def update(self, c, st, u):
        draw_job_values(c, st["job"], st["temps"])


# Print: tune ------------------------------------------------------------------------
class TunePage(Page):
    tab = "print"
    parent = "job"
    title = "Tune"
    header = "TUNE PRINT"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 330, "TUNE PRINT")
        btns.append(Button("goto", (16, 80, 240, 52), self.zrow(st), True,
                           "zoffset"))
        for key, label, y in (("speed", "Speed", 142), ("flow", "Flow", 202),
                              ("fan", "Fan", 262)):
            btns += pm_row(c, key, y, label, self.value(st, key),
                           can_gcode(st))
        c.text(18, 326, 236, 44, "Speed / flow / fan apply instantly",
               MUTED, CARD, F16, align=0)
        return finish(c, btns) + draw_nav(c, self.tab)

    @staticmethod
    def zrow(st):
        def paint(c, rect, pressed, enabled):
            x, y, w, h = rect
            face = SURFACE_DOWN if pressed else SURFACE
            rrect(c, x, y, w, h, 8, face)
            c.text(x + 10, y, 110, h, "Z offset", TEXT, face, F20, align=0)
            c.text(x + 110, y, 120, h, "%+.3f mm  >" % st["z_offset"], TEXT, face,
                   F20, align=2)
        return paint

    @staticmethod
    def value(st, key):
        return {"speed": "%d%%" % round(st["speed"] * 100),
                "flow": "%d%%" % round(st["flow"] * 100),
                "fan": "%d%%" % round(st["fan"] * 100)}[key]

    def dyn_key(self, st, u):
        return (round(st["z_offset"], 3), self.value(st, "speed"),
                self.value(st, "flow"), self.value(st, "fan"))

    def update(self, c, st, u):
        self.zrow(st)(c, (16, 80, 240, 52), False, True)
        for key, y in (("speed", 142), ("flow", 202), ("fan", 262)):
            pm_value(c, y, self.value(st, key))


# Move ---------------------------------------------------------------------------
def draw_position(c, st):
    for i, axis in enumerate("xyz"):
        homed = axis in st["homed"]
        val = ("%.2f" if axis == "z" else "%.1f") % st["pos"][i]
        x = 18 + i * 80
        c.text(x, 76, 24, 28, axis.upper(), OK if homed else WARN, CARD, F20, align=0)
        c.text(x + 22, 76, 56, 28, val if homed else "?", TEXT, CARD, F20, align=0)


class MovePage(Page):
    tab = "move"
    header = "POSITION"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 62, "POSITION")
        draw_position(c, st)
        card(c, 118, 280, "JOG")
        ok = idle(st)
        pad = [("y", +1, "up", "Y+", 76, 146), ("x", -1, "left", "X-", 16, 206),
               ("x", +1, "right", "X+", 136, 206), ("y", -1, "down", "Y-", 76, 266)]
        for axis, sign, icon, fb, x, y in pad:
            btns.append(Button("jog", (x, y, 56, 56), tile(icon, fallback=fb), ok,
                               (axis, sign)))
        btns.append(Button("quick", (76, 206, 56, 56), tile("home", fallback="H"),
                           ok, "home"))
        btns.append(Button("jog", (200, 146, 56, 56), tile("z_up", fallback="Z+"),
                           ok, ("z", +1)))
        c.text(200, 206, 56, 56, "Z", MUTED, CARD, F24, align=1)
        btns.append(Button("jog", (200, 266, 56, 56), tile("z_down", fallback="Z-"),
                           ok, ("z", -1)))
        c.text(18, 326, 236, 20, "Step (mm)", MUTED, CARD, F16, align=0)
        btns += segmented("move_step", MOVE_STEPS, u["move_step"], 354, ok)
        return finish(c, btns) + draw_nav(c, self.tab)

    def dyn_key(self, st, u):
        return (tuple(round(p, 2) for p in st["pos"]), st["homed"])

    def update(self, c, st, u):
        draw_position(c, st)


# More ------------------------------------------------------------------------------
MORE_TILES = [("temp", "temp", "Temperature"), ("filament", "filament", "Filament"),
              ("zoffset", "z_offset", "Z offset"), ("mesh", "mesh", "Bed mesh"),
              ("level", "level", "Bed level"), ("system", "settings", "System")]
NOT_DURING_PRINT = ("mesh", "level")


class MorePage(Page):
    tab = "more"
    header = "MORE"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 348, "MORE")
        for i, (key, icon, label) in enumerate(MORE_TILES):
            rect = (COL[i % 2], 78 + (i // 2) * 106, TILE_W, 100)
            ok = not (st["printing"] and key in NOT_DURING_PRINT)
            btns.append(Button("goto", rect, tile(icon, label), ok, key))
        return finish(c, btns) + draw_nav(c, self.tab)


class TempPage(Page):
    tab = "more"
    parent = "more"
    title = "Temperature"
    header = "TARGETS"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 348, "TARGETS")
        btns += pm_row(c, "heat_ext", 80, "", self.val(st, 0), can_gcode(st), label_icon="nozzle")
        btns += pm_row(c, "heat_bed", 148, "", self.val(st, 1), can_gcode(st), label_icon="bed")
        btns += pm_row(c, "fan", 216, "", "%d%%" % round(st["fan"] * 100),
                       can_gcode(st), label_icon="fan")
        self.actuals(c, st)
        c.text(18, 296, 236, 22, "Presets", MUTED, CARD, F16, align=0)
        ok = idle(st)
        for i, name in enumerate(("PLA", "PETG", "Off")):
            btns.append(Button("preset", (16 + i * 82, 324, 76, 52), text_btn(name),
                               ok, name))
        return finish(c, btns) + draw_nav(c, self.tab)

    @staticmethod
    def val(st, i):
        return "%d\xb0" % round(st["temps"][i][1])

    @staticmethod
    def actuals(c, st):
        for i, y in ((0, 80), (1, 148)):
            c.text(18, y + 40, 72, 20, "%d\xb0 now" % round(st["temps"][i][0]),
                   MUTED, CARD, F16, align=0)

    def dyn_key(self, st, u):
        return ([(round(a), round(t)) for a, t in st["temps"]], round(st["fan"], 2))

    def update(self, c, st, u):
        pm_value(c, 80, self.val(st, 0))
        pm_value(c, 148, self.val(st, 1))
        pm_value(c, 216, "%d%%" % round(st["fan"] * 100))
        self.actuals(c, st)


class FilamentPage(Page):
    tab = "more"
    parent = "more"
    title = "Filament"
    msg_y = 140
    header = "FILAMENT"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 84, "STATUS")
        self.status(c, st)
        card(c, 140, 258, "FILAMENT")
        ok = idle(st)
        for i, (key, icon, label) in enumerate((
                ("load", "load", "Load"), ("unload", "unload", "Unload"),
                ("extrude", "down", "Extrude 10"), ("retract", "up", "Retract 1"))):
            rect = (COL[i % 2], 166 + (i // 2) * 86, TILE_W, TILE_H)
            btns.append(Button("filament", rect, tile(icon, label), ok, key))
        btns.append(Button("filament", (16, 338, 240, 56),
                           text_btn("Change filament (M600)"),
                           st["printing"] and can_gcode(st), "m600"))
        return finish(c, btns) + draw_nav(c, self.tab)

    @staticmethod
    def status(c, st):
        runout = st["runout"]
        txt, col = {True: ("Filament detected", OK),
                    False: ("No filament detected", WARN)}.get(runout,
                                                            ("Sensor unknown", MUTED))
        c.text(18, 74, 236, 26, txt, col, CARD, F20, align=0)
        a, t = st["temps"][0]
        c.pic(18, 104, SMALL["nozzle"])
        c.text(48, 100, 206, 30, "%d / %d\xb0" % (round(a), round(t)), TEXT, CARD,
               F20, align=0)

    def dyn_key(self, st, u):
        return (st["runout"], round(st["temps"][0][0]), round(st["temps"][0][1]))

    def update(self, c, st, u):
        self.status(c, st)


class ZOffsetPage(Page):
    tab = "more"
    parent = "more"
    title = "Z offset"
    header = "Z OFFSET"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 348, "Z OFFSET")
        self.value(c, st)
        btns.append(Button("z_adjust", (16, 138, TILE_W, TILE_H),
                           tile("z_down", "Lower nozzle"), can_gcode(st), -1))
        btns.append(Button("z_adjust", (140, 138, TILE_W, TILE_H),
                           tile("z_up", "Raise nozzle"), can_gcode(st), +1))
        c.text(18, 226, 236, 20, "Step (mm)", MUTED, CARD, F16, align=0)
        btns += segmented("z_step", Z_STEPS, u["z_step"], 250)
        ok = idle(st)
        btns.append(Button("z_reset", (16, 304, TILE_W, TILE_H),
                           tile("restart", "Reset"), ok))
        btns.append(Button("z_save", (140, 304, TILE_W, TILE_H),
                           tile("save", "Save", armed=lambda: "Confirm save?"
                                if u["armed"] == "z_save" else None), ok))
        return finish(c, btns) + draw_nav(c, self.tab)

    @staticmethod
    def value(c, st):
        c.text(18, 74, 236, 60, "%+.3f mm" % st["z_offset"], TEXT, CARD, F48,
               align=1)

    def dyn_key(self, st, u):
        return round(st["z_offset"], 4)

    def update(self, c, st, u):
        self.value(c, st)


def mesh_color(t):
    """0..1 -> blue -> green -> red."""
    if t < 0.5:
        k = t / 0.5
        r, g, b = 0x21, int(0x96 + (0xaf - 0x96) * k), int(0xf3 + (0x50 - 0xf3) * k)
    else:
        k = (t - 0.5) / 0.5
        r, g, b = int(0x4c + (0xf4 - 0x4c) * k), int(0xaf + (0x43 - 0xaf) * k), 0x36
    return "#%02x%02x%02x" % (r, g, b)


class MeshPage(Page):
    tab = "more"
    parent = "more"
    title = "Bed mesh"
    header = "BED MESH"

    def restore_header(self, c, st, u):
        card_header(c, 50, "BED MESH", st["mesh"]["profile"] or "none")

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        m = st["mesh"]
        card(c, 50, 250, "BED MESH", m["profile"] or "none")
        matrix = m["matrix"]
        if matrix and matrix[0]:
            lo = min(min(r) for r in matrix)
            hi = max(max(r) for r in matrix)
            rows, cols = len(matrix), len(matrix[0])
            cw, ch = 236 // cols, 160 // rows
            ox, oy = 18 + (236 - cw * cols) // 2, 80
            for j, row in enumerate(matrix):          # row 0 = front (Y min)
                for i, v in enumerate(row):
                    t = (v - lo) / (hi - lo) if hi > lo else 0.5
                    c.fill(ox + i * cw, oy + (rows - 1 - j) * ch, cw - 2, ch - 2,
                           mesh_color(t))
            c.text(18, 246, 118, 22, "min %+.3f" % lo, MUTED, CARD, F16, align=0)
            c.text(138, 246, 118, 22, "max %+.3f" % hi, MUTED, CARD, F16, align=2)
            c.text(18, 268, 236, 26, "Range %.3f mm" % (hi - lo), TEXT, CARD, F20,
                   align=0)
        else:
            c.text(18, 120, 236, 60, "No mesh loaded", MUTED, CARD, F24, align=1)
        ok = idle(st)
        btns.append(Button("mesh_cal", (16, 306, 76, 92),
                           tile("mesh", "Calibrate"), ok))
        btns.append(Button("mesh_clear", (98, 306, 76, 92),
                           tile("close", "Clear"), ok))
        btns.append(Button("save_config", (180, 306, 76, 92),
                           tile("save", "Save", armed=lambda: "Confirm?"
                                if u["armed"] == "save_config" else None), ok))
        return finish(c, btns) + draw_nav(c, self.tab)

    def dyn_key(self, st, u):
        return json.dumps(st["mesh"], sort_keys=True)

    def update(self, c, st, u):
        return "redraw"


class LevelPage(Page):
    tab = "more"
    parent = "more"
    title = "Bed level"
    header = "SCREW ADJUSTMENTS"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 248, "SCREW ADJUSTMENTS")
        res = st["screws"]
        if res:
            for i, (name, r) in enumerate(sorted(res.items())[:5]):
                y = 78 + i * 42
                label = r.get("name") or name
                c.text(18, y, 130, 36, fit(label, F20, 130), TEXT, CARD, F20, align=0)
                if r.get("is_base"):
                    txt, col = "base", MUTED
                else:
                    adj = r.get("adjust", "00:00")
                    mins = int(adj[:2]) * 60 + int(adj[3:]) if ":" in adj else 0
                    txt = "%s %s" % (r.get("sign", ""), adj)
                    col = OK if mins <= 5 else WARN
                c.text(150, y, 104, 36, txt, col, CARD, F20, align=2)
        else:
            c.text(18, 100, 236, 60, "Not measured yet", MUTED, CARD, F24, align=1)
            c.text(18, 160, 236, 60, "Tap Measure to probe the screws", MUTED, CARD,
                   F16, align=1)
        c.text(18, 304 - 22, 236, 18, "CW = clockwise, 01:00 = one turn", MUTED,
               CARD, F16, align=0)
        ok = idle(st)
        btns.append(Button("level", (16, 306, 240, 92), tile("level", "Measure"),
                           ok))
        return finish(c, btns) + draw_nav(c, self.tab)

    def dyn_key(self, st, u):
        return json.dumps(st["screws"], sort_keys=True)

    def update(self, c, st, u):
        return "redraw"


class SystemPage(Page):
    tab = "more"
    parent = "more"
    title = "System"
    msg_y = 160
    header = "ACTIONS"

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 104, "STATUS")
        self.status(c, st)
        card(c, 160, 238, "ACTIONS")
        idle = not st["printing"]

        def armed(key, text):
            return lambda: text if u["armed"] == key else None
        btns.append(Button("estop", (16, 188, TILE_W, TILE_H),
                           tile("estop", "Emergency stop",
                                armed=armed("estop", "Tap to STOP"))))
        btns.append(Button("fw_restart", (140, 188, TILE_W, TILE_H),
                           tile("restart", "Firmware restart",
                                armed=armed("fw_restart", "Confirm?")), idle))
        btns.append(Button("host_restart", (16, 274, TILE_W, TILE_H),
                           tile("restart", "Restart Klipper",
                                armed=armed("host_restart", "Confirm?")), idle))
        btns.append(Button("save_config", (140, 274, TILE_W, TILE_H),
                           tile("save", "Save config",
                                armed=armed("save_config", "Confirm?")), idle))
        return finish(c, btns) + draw_nav(c, self.tab)

    @staticmethod
    def status(c, st):
        col = OK if st["klippy"] == "ready" else ERR
        c.text(18, 76, 236, 26, "Klipper: %s" % st["klippy"], col, CARD, F20,
               align=0)
        msg = (st["klippy_msg"] or "").strip().split("\n")[0]
        c.text(18, 102, 236, 22, fit(msg, F16, 236) if st["klippy"] != "ready"
               else "", MUTED, CARD, F16, align=0)
        c.text(18, 124, 236, 24, "IP  %s" % (st["ip"] or "?"), TEXT, CARD, F20,
               align=0)

    def dyn_key(self, st, u):
        return (st["klippy"], st["klippy_msg"], st["ip"])

    def update(self, c, st, u):
        self.status(c, st)


class PlaceholderPage(Page):
    def __init__(self, tab):
        self.tab = tab

    def draw(self, c, st, u):
        btns = self.chrome(c, st)
        card(c, 50, 120)
        c.text(18, 70, 236, 40, self.tab.title(), TEXT, CARD, F32, align=1)
        c.text(18, 115, 236, 30, "Coming soon", MUTED, CARD, F20, align=1)
        return finish(c, btns) + draw_nav(c, self.tab)


PAGES = {
    "home": HomePage(), "files": FilesPage(), "detail": DetailPage(),
    "job": JobPage(), "tune": TunePage(), "move": MovePage(), "more": MorePage(),
    "temp": TempPage(), "filament": FilamentPage(), "zoffset": ZOffsetPage(),
    "mesh": MeshPage(), "level": LevelPage(), "system": SystemPage(),
}
