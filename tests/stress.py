#!/usr/bin/env python3
"""Byte-exact round-trip test of the screen link through the serial bridge.

Sends TJC queries with known replies and counts intact vs damaged answers.
Usage: python3 stress.py [rounds] [pty]
"""
import collections
import os
import sys
import time

import serial

END = b"\xff\xff\xff"
TESTS = [
    ("get dim", b"\x71\x64\x00\x00\x00" + END),
    ("get baud", b"\x71\x00\xc2\x01\x00" + END),
    ('get "ABCDEFGHIJ"', b"\x70ABCDEFGHIJ" + END),
    ('get "dddddddddd"', b"\x70dddddddddd" + END),
    ('get "0123456789"', b"\x700123456789" + END),
    ('get "' + "x" * 40 + '"', b"\x70" + b"x" * 40 + END),
]


def read_reply(port, expected, timeout=0.5):
    buf = b""
    end = time.time() + timeout
    while time.time() < end and len(buf) < len(expected):
        buf += port.read(256)
        time.sleep(0.003)
    return buf


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    dev = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/printer_data/comms/screen")
    port = serial.Serial(dev, 115200, timeout=0)
    port.write(b"bkcmd=0" + END)
    time.sleep(0.3)
    port.read(4096)
    stats = collections.Counter()
    samples = collections.defaultdict(list)
    t0 = time.time()
    for _ in range(rounds):
        for cmd, expected in TESTS:
            port.write(cmd.encode() + END)
            reply = read_reply(port, expected)
            if reply == expected:
                stats[cmd, "ok"] += 1
            else:
                stats[cmd, "bad"] += 1
                if len(samples[cmd]) < 2:
                    samples[cmd].append(reply.hex(" "))
                time.sleep(0.2)
                port.read(4096)  # resync
    port.write(b"bkcmd=3" + END)
    total_ok = sum(v for (c, s), v in stats.items() if s == "ok")
    total = rounds * len(TESTS)
    for cmd, _ in TESTS:
        print("%-20s ok %3d  bad %3d  %s" % (cmd[:20], stats[cmd, "ok"],
                                             stats[cmd, "bad"], samples[cmd]))
    print("TOTAL %d/%d intact in %.1fs" % (total_ok, total, time.time() - t0))


if __name__ == "__main__":
    main()
