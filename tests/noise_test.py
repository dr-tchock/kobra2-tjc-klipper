#!/usr/bin/env python3
"""Does motor activity corrupt the screen link?

Runs the byte-exact screen round-trip test in three phases and counts bad
replies plus the bridge's framing-error reports (klippy.log "line errors"):
  A) motors off   B) motors on, standing still   C) motors moving
Moves are XY only, at Z=20 mm, inside the middle of the bed. No heating.
The kobra-screen service must be stopped (this test needs the pty alone).
Usage: ~/klippy-env/bin/python noise_test.py [seconds_per_phase]
"""
import json
import os
import sys
import threading
import time
import urllib.request

import serial

END = b"\xff\xff\xff"
PTY = os.path.expanduser("~/printer_data/comms/screen")
LOG = os.path.expanduser("~/printer_data/logs/klippy.log")
MOONRAKER = "http://127.0.0.1:7125"
TESTS = [("get dim", b"\x71\x64\x00\x00\x00" + END),
         ('get "ABCDEFGHIJ0123456789"', b"\x70ABCDEFGHIJ0123456789" + END),
         ('get "' + "x" * 40 + '"', b"\x70" + b"x" * 40 + END)]


def gcode(script, timeout=300):
    req = urllib.request.Request(MOONRAKER + "/printer/gcode/script",
                                 data=json.dumps({"script": script}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def frame_errors():
    with open(LOG, errors="replace") as f:
        return sum(1 for line in f if "serial_bridge: line errors" in line)


def roundtrips(port, seconds):
    ok = bad = 0
    end = time.time() + seconds
    while time.time() < end:
        for cmd, expected in TESTS:
            port.write(cmd.encode() + END)
            buf, t = b"", time.time() + 0.5
            while time.time() < t and len(buf) < len(expected):
                buf += port.read(256)
                time.sleep(0.003)
            if buf == expected:
                ok += 1
            else:
                bad += 1
                time.sleep(0.2)
                port.read(4096)
    return ok, bad


def phase(port, name, seconds):
    fe0 = frame_errors()
    ok, bad = roundtrips(port, seconds)
    time.sleep(3)  # let klippy.log catch up
    fe = frame_errors() - fe0
    print("%-28s ok %5d  bad %4d  framing-error reports %4d" % (name, ok, bad, fe),
          flush=True)


def mover(stop):
    while not stop.is_set():
        gcode("G1 X60 Y60 F9000\nG1 X170 Y170 F9000\nG1 X60 Y170 F9000\n"
              "G1 X170 Y60 F9000\nM400")


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    port = serial.Serial(PTY, 115200, timeout=0)
    port.write(b"bkcmd=0" + END)
    time.sleep(0.3)
    port.read(4096)
    gcode("M84")
    phase(port, "A motors off", seconds)
    print("homing...", flush=True)
    gcode("G28\nG90\nG1 Z20 F600\nG1 X115 Y115 F6000\nM400")
    phase(port, "B motors on, still", seconds)
    stop = threading.Event()
    t = threading.Thread(target=mover, args=(stop,), daemon=True)
    t.start()
    phase(port, "C motors moving (XY)", seconds)
    stop.set()
    t.join(timeout=60)
    gcode("M400\nM84")
    print("done, motors off", flush=True)


if __name__ == "__main__":
    main()
