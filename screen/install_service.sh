#!/bin/sh
# Install the screen program as a systemd service (kobra-screen) that starts
# with the Pi, restarts on failure and logs to ~/printer_data/logs.
# Also lets Moonraker/Mainsail start/stop/restart it. Safe to re-run.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
PYTHON=${PYTHON:-$HOME/klippy-env/bin/python}
LOG=$HOME/printer_data/logs/kobra_screen.log
UNIT=/etc/systemd/system/kobra-screen.service

"$PYTHON" -c "import serial" || {
    echo "pyserial missing in $PYTHON" >&2; exit 1; }

sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Kobra 2 TJC screen (draws the UI through Klipper's serial_bridge)
After=klipper.service moonraker.service
Wants=moonraker.service

[Service]
Type=simple
User=$(id -un)
ExecStart=$PYTHON $HERE/kobra_screen.py
Restart=always
RestartSec=5
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now kobra-screen.service

ASVC=$HOME/printer_data/moonraker.asvc
if [ -f "$ASVC" ] && ! grep -qx kobra-screen "$ASVC"; then
    echo kobra-screen >> "$ASVC"
    echo "Added kobra-screen to $ASVC (takes effect after a Moonraker restart)"
fi
systemctl --no-pager --lines=0 status kobra-screen.service
