#!/usr/bin/env python3
"""Draw a test card on the portrait 272x480 screen through the bridge."""
import os
import sys
import time

import serial

END = b"\xff\xff\xff"
BLUE, WHITE, RED, GREEN, BLACK = 31, 65535, 63488, 2016, 0

dev = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/printer_data/comms/screen")
port = serial.Serial(dev, 115200, timeout=0)


def cmd(c):
    port.write(c.encode() + END)


cmd("bkcmd=0")
cmd("sendxy=1")
cmd("cls %d" % WHITE)
cmd("fill 0,0,272,60,%d" % BLUE)
cmd('xstr 0,0,272,60,0,%d,%d,1,1,1,"Hello from Klipper"' % (WHITE, BLUE))
cmd("cirs 136,200,60,%d" % GREEN)
cmd('xstr 0,185,272,30,0,%d,%d,1,1,0,"bridge OK"' % (WHITE, GREEN))
cmd('xstr 0,300,272,30,0,%d,%d,1,1,1,"2400/2400 round trips"' % (BLACK, WHITE))
cmd('xstr 0,330,272,30,0,%d,%d,1,1,1,"0 errors"' % (BLACK, WHITE))
cmd("fill 0,420,272,60,%d" % RED)
cmd('xstr 0,420,272,60,0,%d,%d,1,1,1,"Touch anywhere"' % (WHITE, RED))
time.sleep(0.5)
print("drawn")
