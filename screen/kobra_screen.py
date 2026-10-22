#!/usr/bin/env python3
"""Kobra 2 TJC screen service: draws the UI and turns touches into Moonraker calls.

The screen is reached through Klipper's serial_bridge pty. The .tft holds the
boot animation, Roboto fonts and icons; pages are drawn with TJC commands
(portrait 272x480, layouts in ui.py) and touches arrive as sendxy events.

The screen follows the printer: every poll re-reads Klipper's state and
redraws what changed, so actions taken elsewhere (Mainsail, macros) show up
here too. When a print starts the Print tab is shown; the user can still
navigate, and controls that make no sense during a print are greyed out.
"""
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import serial

import ui

PTY = os.path.expanduser("~/printer_data/comms/screen")
# Written to the panel's sys2 after drawing; the panel resets it to 0 on boot.
# Finding it on connect means the panel kept running through a Klipper
# restart, so we reboot it ourselves to replay the boot animation.
UI_MARKER = 1234
LAST_REST_FILE = "/tmp/kobra_screen_last_rest"
MIN_REST_INTERVAL = 60.
MOONRAKER = "http://127.0.0.1:7125"
END = b"\xff\xff\xff"
POLL_INTERVAL = 1.5
FILES_REFRESH = 15.     # re-read the file list this often while it's shown
CONFIRM_TIME = 4.       # seconds a "tap again to confirm" stays armed
MESSAGE_TIME = 4.       # seconds a card-header message stays up
ACTIVE_JOB = ("printing", "paused")

# Buttons needing a second tap
CONFIRM = ("cancel", "z_save", "save_config", "estop", "fw_restart",
           "host_restart")
# Buttons that send G-code; only one may run at a time. Everything else
# (navigation, pause/cancel, emergency stop, restarts) is never blocked.
GCODE_KEYS = ("quick", "jog", "heat_ext", "heat_bed", "fan", "speed", "flow",
              "preset", "filament", "z_adjust", "z_reset", "z_save",
              "mesh_cal", "mesh_clear", "level", "save_config", "start")
JOG_FEED = {"x": 6000, "y": 6000, "z": 600}
# Long commands started anywhere (Mainsail, console, macros) -> page to show.
# Checked in this order, so "G28 + BED_MESH_CALIBRATE" shows the mesh page.
ACTIVITIES = [
    ("BED_MESH_CALIBRATE", "mesh", "Calibrating mesh..."),
    ("SCREWS_TILT_CALCULATE", "level", "Measuring screws..."),
    ("PROBE_CALIBRATE", "zoffset", "Probe calibration..."),
    ("PID_CALIBRATE", "temp", "PID calibration..."),
    ("LOAD_FILAMENT", "filament", "Loading filament..."),
    ("UNLOAD_FILAMENT", "filament", "Unloading filament..."),
    ("M600", "filament", "Filament change..."),
    ("G28", "move", "Homing..."),
]


def rgb565(hexcolor):
    v = int(hexcolor.lstrip("#"), 16)
    r, g, b = v >> 16, (v >> 8) & 0xFF, v & 0xFF
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # no packet is sent for UDP connect
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


class Moonraker:
    QUERY = ("/printer/objects/query?webhooks&print_stats&"
             "display_status=progress&"
             "gcode_move=gcode_position,homing_origin,speed_factor,extrude_factor&"
             "toolhead=position,homed_axes&"
             "extruder=temperature,target&heater_bed=temperature,target&"
             "fan=speed&screws_tilt_adjust&"
             "bed_mesh=profile_name,probed_matrix&"
             "filament_switch_sensor%20runout=filament_detected&"
             "idle_timeout=state")

    def _request(self, method, path, body=None, timeout=10):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(MOONRAKER + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)["result"]

    def info(self):
        """(state, state_message) of Klipper as Moonraker sees it."""
        res = self._request("GET", "/printer/info", timeout=5)
        return res["state"], res.get("state_message", "")

    def status(self):
        return self._request("GET", self.QUERY, timeout=5)["status"]

    def files(self):
        """G-code files, newest first."""
        res = self._request("GET", "/server/files/list?root=gcodes", timeout=10)
        return sorted(res, key=lambda f: -f["modified"])

    def metadata(self, path):
        q = urllib.parse.quote(path)
        return self._request("GET", "/server/files/metadata?filename=" + q,
                             timeout=10)

    def print_start(self, path):
        q = urllib.parse.quote(path)
        self._request("POST", "/printer/print/start?filename=" + q, timeout=10)

    def print_cmd(self, cmd):
        """pause, resume or cancel"""
        self._request("POST", "/printer/print/" + cmd, timeout=10)

    def gcode_store(self, count=30):
        return self._request("GET", "/server/gcode_store?count=%d" % count,
                             timeout=5)["gcode_store"]

    def firmware_restart(self):
        self._request("POST", "/printer/firmware_restart", timeout=10)

    def host_restart(self):
        self._request("POST", "/printer/restart", timeout=10)

    def emergency_stop(self):
        self._request("POST", "/printer/emergency_stop", timeout=10)

    def gcode(self, script, timeout=600):
        self._request("POST", "/printer/gcode/script", {"script": script},
                      timeout=timeout)


class Screen:
    def __init__(self, path):
        self.port = serial.Serial(path, 115200, timeout=0)
        self.path = path
        self.dev = os.path.realpath(path)
        self.buf = b""
        self.lock = threading.Lock()

    def cmd(self, *cmds):
        with self.lock:
            self.port.write(b"".join(c.encode() + END for c in cmds))

    def query_int(self, cmd, timeout=0.5):
        """Send a 'get' for a number; returns it, or None on error/no reply."""
        with self.lock:
            self.port.read(4096)
            self.port.write(b"bkcmd=0" + END + cmd.encode() + END)
            buf = b""
            end = time.time() + timeout
            while time.time() < end:
                buf += self.port.read(64)
                i = buf.find(b"\x71")
                if i >= 0 and len(buf) >= i + 8 and buf[i + 5:i + 8] == END:
                    return int.from_bytes(buf[i + 1:i + 5], "little")
                time.sleep(0.01)
        return None

    def events(self):
        """Yield complete frames received from the panel."""
        with self.lock:
            self.buf += self.port.read(256)
        while True:
            if self.buf[:1] == b"\x67":
                # Touch: 67 xH xL yH yL state FF FF FF (coords may contain 0xFF)
                if len(self.buf) < 9:
                    return
                frame, self.buf = self.buf[:9], self.buf[9:]
                yield frame
                continue
            idx = self.buf.find(END)
            if idx < 0:
                return
            frame, self.buf = self.buf[:idx + 3], self.buf[idx + 3:]
            yield frame

    def stale(self):
        """True once Klipper restarted and re-created the pty."""
        try:
            return os.path.realpath(self.path) != self.dev
        except OSError:
            return True


class TjcCanvas:
    """ui.py canvas primitives as TJC drawing commands."""
    def __init__(self, screen):
        self.s = screen

    def clear(self, color):
        self.s.cmd("cls %d" % rgb565(color))

    def fill(self, x, y, w, h, color):
        if w > 0 and h > 0:
            self.s.cmd("fill %d,%d,%d,%d,%d" % (x, y, w, h, rgb565(color)))

    def circle(self, cx, cy, r, color):
        self.s.cmd("cirs %d,%d,%d,%d" % (cx, cy, r, rgb565(color)))

    def pic(self, x, y, pid):
        self.s.cmd("pic %d,%d,%d" % (x, y, pid))

    def text(self, x, y, w, h, s, fg, bg, font, align=1):
        s = s.replace('"', "'")
        self.s.cmd('xstr %d,%d,%d,%d,%d,%d,%d,%d,1,1,"%s"'
                   % (x, y, w, h, font, rgb565(fg), rgb565(bg), align, s))


class AutoRecover(threading.Thread):
    """Firmware-restart Klipper after the mainboard was power cycled.

    Only reacts to "the board went away" states. Real faults (heater,
    ADC, timer errors) are left alone so they stay stopped until checked.
    Retries back off from 30 s to 5 min while the board stays off.
    """
    BOARD_GONE = ("Lost communication with MCU", "spontaneous restart",
                  "Unable to connect")

    def __init__(self, mr):
        super().__init__(daemon=True)
        self.mr = mr
        self.backoff = 30.
        self.next_try = 0.

    def run(self):
        while True:
            time.sleep(5)
            try:
                state, msg = self.mr.info()
            except Exception:
                continue  # Moonraker/Klipper restarting
            if state == "ready":
                self.backoff, self.next_try = 30., 0.
                continue
            if state not in ("shutdown", "error"):
                continue  # startup in progress
            if not any(m in msg for m in self.BOARD_GONE):
                continue
            now = time.time()
            if now < self.next_try:
                continue
            logging.info("auto-recover: %r -> FIRMWARE_RESTART (next retry in %ds)",
                         msg.strip().split("\n")[0], self.backoff)
            try:
                self.mr.firmware_restart()
            except Exception as e:
                logging.warning("auto-recover: restart failed: %s", e)
            # Klipper itself waits up to 90 s for the board after a restart
            self.next_try = now + 90. + self.backoff
            self.backoff = min(self.backoff * 2, 300.)


class App:
    def __init__(self):
        self.mr = Moonraker()
        self.screen = None
        self.canvas = None
        self.ui_ready = False
        self.draw_lock = threading.RLock()
        self.page = "home"
        self.buttons = []
        self.pressed = None
        self.busy = False
        self.back_override = {}      # page -> page "< back" returns to
        self.shown_key = None
        self.msg = None              # (page, text, color, until or None)
        self.armed_until = 0.
        self.files = []
        self.files_time = 0.
        self.meta = {}
        self.ip, self.ip_time = None, 0.
        self.activity = None         # (page, label) of a long command running
        self.sent = []               # (time, script) sent by the screen
        self.gstore_t = None         # newest gcode_store entry already seen
        self.shown_mode = None
        self.st = dict(chip="offline", klippy="offline", klippy_msg="",
                       job_state="standby", printing=False,
                       temps=[(0., 0.), (0., 0.)], job=None, pos=[0., 0., 0.],
                       homed="", z_offset=0., speed=1., flow=1., fan=0.,
                       screws={}, mesh=dict(profile=None, matrix=None),
                       runout=None, ip=None, busy=False)
        self.u = dict(file_page=0, file_pages=1, page_files=[], detail=None,
                      armed=None, move_step=10, z_step=0.025)

    # --- Panel link -------------------------------------------------------
    def wait_link(self):
        """Block until the panel answers through the bridge.

        The pty exists before Klipper is ready, and the bridge drops writes
        until then, so anything drawn earlier would silently vanish.
        Returns False if the pty went stale meanwhile.
        """
        while not self.screen.stale():
            if self.screen.query_int("get dim") is not None:
                return True
            time.sleep(1)
        return False

    def maybe_reboot_screen(self):
        """Replay the boot animation after a Klipper/firmware restart."""
        if self.screen.query_int("get sys2") != UI_MARKER:
            return True  # panel booted fresh, animation already played
        try:
            last = os.path.getmtime(LAST_REST_FILE)
        except OSError:
            last = 0.
        if time.time() - last < MIN_REST_INTERVAL:
            logging.info("screen reboot skipped (last one %.0fs ago)",
                         time.time() - last)
            return True
        with open(LAST_REST_FILE, "w"):
            pass
        logging.info("rebooting screen to replay the boot animation")
        self.screen.cmd("rest")
        time.sleep(1.)
        return self.wait_link()

    def wait_boot_animation(self, timeout=15.):
        """Don't interrupt the boot animation: wait until gm0 played to the end.

        A lost or garbled reply must not count as "finished", or the UI gets
        drawn while frames are still being painted. Only several failed
        queries in a row mean "this .tft has no animation".
        """
        s = self.screen
        start = time.time()
        failures = 0
        while time.time() - start < timeout:
            tim = s.query_int("get gm0.tim")
            stim = s.query_int("get gm0.stim")
            if tim is None or stim is None or stim == 0:
                failures += 1
                if failures >= 6:
                    logging.info("no boot animation answer, drawing UI")
                    return
            else:
                failures = 0
                if tim >= stim:
                    logging.info("boot animation done (%.1fs)", time.time() - start)
                    return
            time.sleep(0.25)
        logging.info("boot animation wait timed out")

    def first_draw(self):
        self.wait_boot_animation()
        # Stop and hide the boot animation (gm0 in the .tft), and give the
        # panel a moment so no frame in flight lands on top of the UI
        self.screen.cmd("bkcmd=0", "gm0.en=0", "vis gm0,0", "sendxy=1")
        time.sleep(0.3)
        self.refresh_state(draw=False)
        with self.draw_lock:
            if self.st["printing"]:
                self.page = "job"
            self.show(self.page)
            self.ui_ready = True
        self.screen.cmd("sys2=%d" % UI_MARKER)

    # --- Pages ------------------------------------------------------------
    def show(self, page):
        """Draw a whole page for the current state."""
        with self.draw_lock:
            if page == "job" and not self.st["printing"]:
                page = "files"
            if page in ("tune",) and not self.st["printing"]:
                page = "files"
            if page == "detail" and not self.u["detail"]:
                page = "files"
            if page == "files":
                self.prepare_files()
            self.page = page
            self.pressed = None
            self.u["armed"] = None
            p = ui.PAGES[page]
            self.buttons = p.draw(self.canvas, self.st, self.u)
            self.shown_key = p.dyn_key(self.st, self.u)
            self.shown_mode = self.mode()
            # Keep a still-valid message (e.g. "Calibrating mesh...") on top
            if self.msg and self.msg[0] == page and \
                    (self.msg[3] is None or self.msg[3] > time.time()):
                ui.card_message(self.canvas, p.msg_y, self.msg[1], self.msg[2])

    def mode(self):
        """What decides which buttons are enabled; a change means redraw."""
        st = self.st
        return (st["printing"], st["busy"], st["klippy"])

    def message(self, text, color, persistent=False):
        """Feedback in a card header of the current page.

        Normal messages fade after a few seconds; persistent ones stay
        until replaced (used for "what is running" while busy).
        """
        with self.draw_lock:
            self.msg = (self.page, text, color,
                        None if persistent else time.time() + MESSAGE_TIME)
            if self.ui_ready:
                ui.card_message(self.canvas, ui.PAGES[self.page].msg_y, text,
                                color)

    def redraw_buttons(self, key):
        for b in self.buttons:
            if b.key == key:
                b.draw(self.canvas)

    # --- Files ---------------------------------------------------------------
    def load_files(self, force=False):
        if not force and time.time() - self.files_time < 2.:
            return False
        try:
            files = self.mr.files()
        except Exception as e:
            logging.warning("file list failed: %s", e)
            return False
        changed = [(f["path"], f["modified"]) for f in files] != \
            [(f["path"], f["modified"]) for f in self.files]
        self.files, self.files_time = files, time.time()
        return changed

    def prepare_files(self):
        self.load_files()
        u = self.u
        u["file_pages"] = max(1, (len(self.files) + ui.FILE_ROWS - 1) // ui.FILE_ROWS)
        u["file_page"] = max(0, min(u["file_page"], u["file_pages"] - 1))
        start = u["file_page"] * ui.FILE_ROWS
        u["page_files"] = [self.file_info(f)
                           for f in self.files[start:start + ui.FILE_ROWS]]

    def file_info(self, f):
        """File entry merged with (cached) slicer metadata."""
        key = (f["path"], f["modified"])
        if key not in self.meta:
            try:
                self.meta[key] = self.mr.metadata(f["path"])
            except Exception:
                self.meta[key] = {}
        info = dict(self.meta[key])
        info.update(name=f["path"], path=f["path"], modified=f["modified"])
        return info

    def slicer_estimate(self, path):
        for (p, _), m in self.meta.items():
            if p == path and m.get("estimated_time"):
                return m["estimated_time"]
        try:
            m = self.mr.metadata(path)
        except Exception:
            return None
        self.meta[(path, m.get("modified"))] = m
        return m.get("estimated_time")

    # --- Live data ---------------------------------------------------------
    def build_job(self, s):
        ps = s["print_stats"]
        progress = s["display_status"]["progress"] or 0.
        printing = ps.get("print_duration") or 0.
        est = self.slicer_estimate(ps["filename"]) if ps.get("filename") else None
        # Remaining: file-progress estimate once it's meaningful, averaged
        # with the slicer estimate when we have one (Mainsail does similar)
        guesses = []
        if progress > 0.02 and printing > 0:
            guesses.append(printing / progress - printing)
        if est:
            guesses.append(max(0., est - printing))
        info = ps.get("info") or {}
        return dict(state=ps["state"], filename=ps.get("filename") or "",
                    progress=min(max(progress, 0.), 1.),
                    remaining=sum(guesses) / len(guesses) if guesses else None,
                    elapsed=ps.get("total_duration") or 0.,
                    layer=info.get("current_layer"), layers=info.get("total_layer"),
                    z=(s["gcode_move"]["gcode_position"] or [0, 0, 0])[2])

    def read_state(self):
        st = dict(self.st)
        if time.time() - self.ip_time > 60:
            self.ip, self.ip_time = local_ip(), time.time()
        st["ip"] = self.ip
        try:
            s = self.mr.status()
        except Exception:
            try:
                klippy, msg = self.mr.info()
            except Exception:
                klippy, msg = "offline", "Moonraker not reachable"
            st.update(klippy=klippy, klippy_msg=msg, chip=klippy)
            return st
        wh = s.get("webhooks", {})
        st["klippy"] = wh.get("state", "offline")
        st["klippy_msg"] = wh.get("state_message", "")
        st["job_state"] = s["print_stats"]["state"]
        st["printing"] = st["klippy"] == "ready" and st["job_state"] in ACTIVE_JOB
        # Klipper reports "Printing" while it runs any command (G28, mesh...)
        st["busy"] = (st["klippy"] == "ready" and not st["printing"] and
                      (s.get("idle_timeout") or {}).get("state") == "Printing")
        st["chip"] = st["job_state"] if st["printing"] else (
            "busy" if st["busy"] else st["klippy"])
        st["temps"] = [(s["extruder"]["temperature"], s["extruder"]["target"]),
                       (s["heater_bed"]["temperature"], s["heater_bed"]["target"])]
        st["job"] = self.build_job(s) if st["printing"] else None
        th, gm = s.get("toolhead", {}), s.get("gcode_move", {})
        st["pos"] = (th.get("position") or [0, 0, 0, 0])[:3]
        st["homed"] = th.get("homed_axes") or ""
        st["z_offset"] = (gm.get("homing_origin") or [0, 0, 0])[2]
        st["speed"] = gm.get("speed_factor", 1.)
        st["flow"] = gm.get("extrude_factor", 1.)
        st["fan"] = s.get("fan", {}).get("speed", 0.)
        st["screws"] = (s.get("screws_tilt_adjust") or {}).get("results") or {}
        bm = s.get("bed_mesh") or {}
        # Show the probed points (the real measurements, 6x6 here); the
        # interpolated mesh has ~250 cells and takes ~1 s to draw
        st["mesh"] = dict(profile=bm.get("profile_name") or None,
                          matrix=bm.get("probed_matrix") or None)
        st["runout"] = (s.get("filament_switch_sensor runout") or {}).get(
            "filament_detected")
        return st

    def detect_activity(self):
        """A long command started elsewhere -> (page, label), else None.

        Uses Moonraker's command history, which includes commands typed or
        clicked in Mainsail. Commands this screen sent are ignored (the user
        is already on the right page for those).
        """
        try:
            entries = self.mr.gcode_store(30)
        except Exception:
            return None
        if not entries:
            return None
        newest = max(e["time"] for e in entries)
        if self.gstore_t is None:      # first look: ignore history
            self.gstore_t = newest
            return None
        new = [e for e in entries if e["time"] > self.gstore_t and
               e["type"] == "command"]
        self.gstore_t = max(self.gstore_t, newest)
        now = time.time()
        self.sent = [(t, sc) for t, sc in self.sent if now - t < 120]
        mine = [sc for _, sc in self.sent]
        found = None
        for e in new:
            if e["message"] in mine:
                continue
            words = [ln.strip().split(" ")[0].upper()
                     for ln in e["message"].split("\n") if ln.strip()]
            for cmd, page, label in ACTIVITIES:
                if cmd in words:
                    found = (page, label)
                    break
        return found

    def refresh_state(self, draw=True):
        st = self.read_state()
        act = self.detect_activity() if draw else None
        with self.draw_lock:
            old = self.st
            self.st = st
            if not (draw and self.ui_ready):
                return
            c = self.canvas
            if st["chip"] != old["chip"]:
                ui.draw_chip(c, st["chip"])
            if st["printing"] and not old["printing"]:
                # A print started (from here or anywhere else): always show
                # it. The user can still navigate afterwards.
                logging.info("print started: %s", st["job"]["filename"])
                self.activity = None
                self.show("job")
                return
            if old["printing"] and not st["printing"]:
                logging.info("print ended: %s", st["job_state"])
                if self.page in ("job", "tune"):
                    self.show("files")
                    self.message("Print %s" % st["job_state"],
                                 ui.OK if st["job_state"] == "complete" else ui.WARN)
                else:
                    self.show(self.page)  # re-enable greyed controls
                return
            if act and not st["printing"]:
                # Something long started elsewhere: show its page (the user
                # can navigate away again)
                logging.info("activity from elsewhere: %s", act[1])
                self.activity = act
                self.show(act[0])
                self.message(act[1], ui.PRIMARY, persistent=True)
                return
            if self.activity and old["busy"] and not st["busy"]:
                page, label = self.activity
                self.activity = None
                self.show(self.page)   # re-enable buttons
                if self.page == page:
                    self.message("Done", ui.OK)
                return
            if self.mode() != self.shown_mode:
                self.show(self.page)
                return
            self.update_page()

    def update_page(self):
        """Refresh the changing parts of the current page."""
        c, now = self.canvas, time.time()
        p = ui.PAGES[self.page]
        if self.msg and self.msg[3] is not None and now > self.msg[3]:
            self.msg = None
            p.restore_header(c, self.st, self.u)
        if self.u["armed"] and now > self.armed_until:
            key, self.u["armed"] = self.u["armed"], None
            self.redraw_buttons(key)
        if self.page == "files" and now - self.files_time > FILES_REFRESH \
                and self.load_files():
            self.show("files")
            return
        key = p.dyn_key(self.st, self.u)
        if key != self.shown_key:
            self.shown_key = key
            if p.update(c, self.st, self.u) == "redraw":
                self.show(self.page)

    def poll_loop(self):
        while True:
            time.sleep(POLL_INTERVAL)
            try:
                self.refresh_state()
            except (OSError, serial.SerialException):
                pass
            except Exception:
                logging.exception("poll failed")

    # --- Actions -----------------------------------------------------------
    QUICK = {
        "home": ("Homing...", "Homed", "G28"),
        "preheat": ("Preheating PLA...", "Heating to %d/%d" % ui.PRESETS["PLA"],
                    "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=%d\n"
                    "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=%d"
                    % ui.PRESETS["PLA"]),
        "cool": ("Cooling down...", "Heaters off", "TURN_OFF_HEATERS"),
        "motors_off": ("Motors off...", "Motors off", "M84"),
    }

    def run_bg(self, fn, *args, gcode=True):
        if gcode:
            self.busy = True

        def wrapper():
            try:
                fn(*args)
            except urllib.error.HTTPError as e:
                try:
                    msg = json.load(e)["error"]["message"]
                except Exception:
                    msg = str(e)
                logging.warning("action failed: %s", msg)
                self.message(msg.strip().split("\n")[0], ui.ERR)
            except Exception as e:
                logging.warning("action failed: %s", e)
                self.message("Moonraker error", ui.ERR)
            finally:
                if gcode:
                    self.busy = False
        threading.Thread(target=wrapper, daemon=True).start()

    def gcode(self, script, busy_msg=None, done_msg=None):
        self.sent.append((time.time(), script))
        if busy_msg:
            self.activity = (self.page, busy_msg)
            self.message(busy_msg, ui.PRIMARY, persistent=True)
        try:
            self.mr.gcode(script)
        finally:
            self.activity = None
        if done_msg:
            self.message(done_msg, ui.OK)
        elif busy_msg:
            self.message("Done", ui.OK)

    def needs_home(self, axes="xyz"):
        return "G28\n" if any(a not in self.st["homed"] for a in axes) else ""

    def do_action(self, b):
        key, arg, st, u = b.key, b.arg, self.st, self.u
        if key == "quick":
            busy, done, script = self.QUICK[arg]
            self.run_bg(self.gcode, script, busy, done)
        elif key == "start":
            self.run_bg(self.start_print, u["detail"])
        elif key == "pause":
            cmd = "resume" if st["job_state"] == "paused" else "pause"
            self.run_bg(self.job_cmd, cmd, gcode=False)
        elif key == "cancel":
            self.run_bg(self.job_cmd, "cancel", gcode=False)
        elif key in ("speed", "flow"):
            cur = round(st[key] * 100)
            step = ui.SPEED_STEP if key == "speed" else ui.FLOW_STEP
            new = max(10, min(300, cur + arg * step))
            self.run_bg(self.gcode, "%s S%d" % ("M220" if key == "speed" else "M221",
                                                new))
        elif key == "fan":
            new = max(0, min(100, round(st["fan"] * 100) + arg * ui.FAN_STEP))
            self.run_bg(self.gcode, "M106 S%d" % round(new * 255 / 100))
        elif key in ("heat_ext", "heat_bed"):
            i = 0 if key == "heat_ext" else 1
            new = max(0, round(st["temps"][i][1]) + arg * ui.TEMP_STEP)
            heater = "extruder" if i == 0 else "heater_bed"
            self.run_bg(self.gcode, "SET_HEATER_TEMPERATURE HEATER=%s TARGET=%d"
                        % (heater, new))
        elif key == "preset":
            if arg == "Off":
                self.run_bg(self.gcode, "TURN_OFF_HEATERS", None, "Heaters off")
            else:
                e, bd = ui.PRESETS[arg]
                self.run_bg(self.gcode,
                            "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=%d\n"
                            "SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=%d"
                            % (e, bd), None, "%s: %d/%d" % (arg, e, bd))
        elif key == "jog":
            axis, sign = arg
            d = sign * (u["move_step"] if axis != "z" else min(u["move_step"], 10))
            self.run_bg(self.gcode, "G91\nG1 %s%g F%d\nG90"
                        % (axis.upper(), d, JOG_FEED[axis]))
        elif key == "filament":
            script, busy, done = {
                "load": ("LOAD_FILAMENT", "Loading...", "Loaded"),
                "unload": ("UNLOAD_FILAMENT", "Unloading...", "Unloaded"),
                "extrude": ("M83\nG1 E10 F300", "Extruding...", "Extruded 10 mm"),
                "retract": ("M83\nG1 E-1 F1800", "Retracting...", "Retracted 1 mm"),
                "m600": ("M600", "Filament change...", "Change started"),
            }[arg]
            self.run_bg(self.gcode, script, busy, done)
        elif key == "z_adjust":
            move = " MOVE=1" if "z" in st["homed"] else ""
            self.run_bg(self.gcode, "SET_GCODE_OFFSET Z_ADJUST=%.3f%s"
                        % (arg * u["z_step"], move))
        elif key == "z_reset":
            move = " MOVE=1" if "z" in st["homed"] else ""
            self.run_bg(self.gcode, "SET_GCODE_OFFSET Z=0%s" % move, None,
                        "Offset reset")
        elif key == "z_save":
            self.run_bg(self.gcode, "Z_OFFSET_APPLY_PROBE\nSAVE_CONFIG",
                        "Saving, Klipper restarts...")
        elif key == "mesh_cal":
            self.run_bg(self.gcode, self.needs_home() + "BED_MESH_CALIBRATE",
                        "Calibrating mesh...", "Mesh done (not saved)")
        elif key == "mesh_clear":
            self.run_bg(self.gcode, "BED_MESH_CLEAR", None, "Mesh cleared")
        elif key == "level":
            self.run_bg(self.gcode, self.needs_home() + "SCREWS_TILT_CALCULATE",
                        "Measuring screws...", "Measured")
        elif key == "save_config":
            self.run_bg(self.gcode, "SAVE_CONFIG", "Saving, Klipper restarts...")
        elif key == "estop":
            logging.warning("EMERGENCY STOP from screen")
            self.run_bg(self.mr.emergency_stop, gcode=False)
        elif key == "fw_restart":
            self.run_bg(self.mr.firmware_restart, gcode=False)
        elif key == "host_restart":
            self.run_bg(self.mr.host_restart, gcode=False)

    def start_print(self, f):
        self.message("Starting print...", ui.PRIMARY)
        self.mr.print_start(f["path"])
        # The poll loop switches to the job view once Klipper reports it

    def job_cmd(self, cmd):
        self.message({"pause": "Pausing...", "resume": "Resuming...",
                      "cancel": "Cancelling..."}[cmd], ui.PRIMARY)
        self.mr.print_cmd(cmd)

    # --- Touch ---------------------------------------------------------------
    def target_at(self, x, y):
        for b in self.buttons:
            if ui.hit(b.rect, x, y):
                return b
        return None

    def on_touch(self, x, y, down):
        if not self.ui_ready:
            return
        with self.draw_lock:
            b = self.target_at(x, y)
            if down:
                if b and b.enabled and not (self.busy and b.key in GCODE_KEYS):
                    self.pressed = b
                    b.draw(self.canvas, True)
                elif b and not b.enabled:
                    self.pressed = b   # remember, to explain on release
                elif b and self.busy:
                    self.message("Busy, please wait...", ui.WARN)
                return
            pressed, self.pressed = self.pressed, None
            if pressed is None:
                return
            if not pressed.enabled:
                if b is pressed:
                    self.message("Not available %s" % (
                        "while printing" if self.st["printing"] else "right now"),
                        ui.WARN)
                return
            if b is not pressed:
                pressed.draw(self.canvas)
                return  # finger slid off: cancel
            self.activate(pressed)

    def activate(self, b):
        u = self.u
        if b.key == "nav":
            self.show({"home": "home", "print": "job" if self.st["printing"]
                       else "files", "move": "move", "more": "more"}[b.arg])
        elif b.key == "back":
            parent = self.back_override.pop(self.page, None) or \
                ui.PAGES[self.page].parent
            self.show(parent)
        elif b.key == "goto":
            if b.arg == "zoffset" and self.page == "tune":
                self.back_override["zoffset"] = "tune"
            else:
                self.back_override.pop(b.arg, None)
            self.show(b.arg)
        elif b.key == "file":
            u["detail"] = u["page_files"][b.arg]
            self.show("detail")
        elif b.key == "pager":
            u["file_page"] += b.arg
            self.show("files")
        elif b.key == "detail_back":
            self.show("files")
        elif b.key in ("move_step", "z_step"):
            u[b.key] = b.arg
            self.buttons = [x for x in self.buttons if x.key != b.key]
            y = b.rect[1]
            values = ui.MOVE_STEPS if b.key == "move_step" else ui.Z_STEPS
            new = ui.segmented(b.key, values, b.arg, y, b.enabled)
            self.buttons += ui.finish(self.canvas, new)
        elif b.key in CONFIRM and u["armed"] != b.key:
            # First tap only arms it; a second tap within a few s confirms
            prev, u["armed"] = u["armed"], b.key
            self.armed_until = time.time() + CONFIRM_TIME
            if prev:
                self.redraw_buttons(prev)
            b.draw(self.canvas)
        else:
            if b.key in CONFIRM:
                u["armed"] = None
            b.draw(self.canvas)
            if self.busy and b.key in GCODE_KEYS:
                self.message("Busy, please wait...", ui.WARN)
                return
            self.do_action(b)

    def on_frame(self, f):
        if f[0] == 0x67 and len(f) == 9:
            x, y, state = (f[1] << 8) | f[2], (f[3] << 8) | f[4], f[5]
            self.on_touch(x, y, state == 1)
        elif f[:1] in (b"\x88", b"\x00"):
            # Panel (re)booted - it forgot sendxy and our drawing
            logging.info("screen restarted, redrawing")
            self.ui_ready = False
            time.sleep(0.3)
            self.first_draw()

    # --- Main loop ---------------------------------------------------------
    def run(self):
        AutoRecover(self.mr).start()
        threading.Thread(target=self.poll_loop, daemon=True).start()
        while True:
            self.ui_ready = False
            if self.screen is not None:
                try:
                    self.screen.port.close()
                except Exception:
                    pass
                self.screen = None
            try:
                self.screen = Screen(PTY)
                self.canvas = TjcCanvas(self.screen)
                logging.info("connected to %s", self.screen.dev)
                if not self.wait_link() or not self.maybe_reboot_screen():
                    continue
                logging.info("screen answering, drawing UI")
                self.first_draw()
                while not self.screen.stale():
                    for frame in self.screen.events():
                        self.on_frame(frame)
                    time.sleep(0.02)
                logging.info("pty changed (Klipper restart?), reconnecting")
            except (OSError, serial.SerialException) as e:
                logging.info("screen not available (%s), retrying", e)
            time.sleep(2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    App().run()
