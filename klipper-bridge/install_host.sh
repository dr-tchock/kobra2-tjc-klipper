#!/bin/sh
# Link the host module into the live Klipper tree without dirtying its git
# status (same approach as cartographer/idm). Safe to re-run.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIVE=${LIVE:-$HOME/klipper}

ln -sf "$HERE/klippy/extras/serial_bridge.py" "$LIVE/klippy/extras/serial_bridge.py"
grep -qx "klippy/extras/serial_bridge.py" "$LIVE/.git/info/exclude" ||
    echo "klippy/extras/serial_bridge.py" >> "$LIVE/.git/info/exclude"
echo "Linked. Add to printer.cfg (only after flashing the bridge firmware):"
echo
echo "[serial_bridge]"
echo "baud: 115200"
