#!/bin/sh
# Rebuild the Kobra 2 mainboard firmware with the serial bridge, at the same
# Klipper version as the live ~/klipper. Output: ../firmware/firmware.bin
# (copy to the root of an SD card and power-cycle the printer to flash).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
LIVE=${LIVE:-$HOME/klipper}
TREE=${TREE:-$HOME/kobra_builds/klipper-bridge}
OUTDIR=$HERE/../firmware

[ -d "$TREE" ] || git clone -q "$LIVE" "$TREE"
cd "$TREE"
# Undo the previous patch, then move to the live tree's commit
git checkout -q -- src/hc32f460/Kconfig src/hc32f460/Makefile src/hc32f460/serial.c
git fetch -q "$LIVE" HEAD
git checkout -q --detach FETCH_HEAD
echo "Klipper version: $(git describe --tags --always)"

sh "$HERE/apply.sh" "$TREE"
cp "$HERE/mcu.config" .config
make olddefconfig >/dev/null
grep -q "^CONFIG_HC32F460_SERIAL_BRIDGE=y" .config || {
    echo "bridge option lost in menuconfig - check Kconfig patch" >&2; exit 1; }
make clean >/dev/null
make -j4 >/dev/null

python3 - out/klipper.dict <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert 'config_serial_bridge oid=%c baud=%u' in d['commands'], "bridge missing"
print("Firmware version:", d['version'])
EOF
mkdir -p "$OUTDIR"
cp out/klipper.bin "$OUTDIR/firmware.bin"
echo "Ready: $OUTDIR/firmware.bin ($(stat -c %s out/klipper.bin) bytes)"
