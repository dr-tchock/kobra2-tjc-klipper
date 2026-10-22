#!/usr/bin/env python3
"""Smoke test for the TJC panel link: sets t0.txt and prints anything the panel sends.

Usage: python3 hello_serial.py /dev/ttyAMA0 115200
Requires pyserial (pip install pyserial).
"""
import sys
import time

import serial

END = b"\xff\xff\xff"


def send(port, cmd):
    port.write(cmd.encode("utf-8") + END)


def main():
    dev = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyAMA0"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
    with serial.Serial(dev, baud, timeout=0.2) as port:
        send(port, "bkcmd=3")  # ask the panel to acknowledge every command
        send(port, 't0.txt="Hello from Klipper host"')
        print(f"Sent text on {dev} @ {baud}. Touch the screen; Ctrl+C to quit.")
        buf = b""
        while True:
            buf += port.read(64)
            while END in buf:
                frame, buf = buf.split(END, 1)
                # 0x01 = command OK, 0x65 = touch event (page, id, press/release)
                print(" ".join(f"{b:02x}" for b in frame))
            time.sleep(0.05)


if __name__ == "__main__":
    main()
