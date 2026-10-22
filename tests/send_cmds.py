#!/usr/bin/env python3
"""Stream a file of TJC commands (one per line) to the screen, paced.

The bridge keeps at most ~8 KB queued on the host, so we stay below the
115200 baud screen rate instead of dumping everything at once.
Usage: send_cmds.py cmds.txt [bytes_per_sec]
"""
import os
import sys
import time

import serial

END = b"\xff\xff\xff"
PTY = os.path.expanduser("~/printer_data/comms/screen")


def main():
    rate = float(sys.argv[2]) if len(sys.argv) > 2 else 10000.
    cmds = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    data = b"".join(c.encode() + END for c in ["bkcmd=0"] + cmds)
    port = serial.Serial(PTY, 115200, timeout=0)
    block = 512
    t0 = time.time()
    for i in range(0, len(data), block):
        port.write(data[i:i + block])
        port.read(4096)  # discard anything the panel sends meanwhile
        # Sleep until the paced schedule catches up
        due = t0 + (i + block) / rate
        delay = due - time.time()
        if delay > 0:
            time.sleep(delay)
        if i % (block * 40) == 0:
            print("%3d%%" % (100 * i // len(data)), flush=True)
    print("done: %d commands, %.0f KB in %.1f s"
          % (len(cmds), len(data) / 1024, time.time() - t0))


if __name__ == "__main__":
    main()
