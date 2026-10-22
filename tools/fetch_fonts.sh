#!/bin/sh
# Download the fonts used to make the icons and the screen fonts.
# Only needed to regenerate icons (make_icons.py), mockups (mockup.py) or
# the width table (font_widths.py); the screen itself doesn't need them.
set -e
DIR=$(cd "$(dirname "$0")/../assets/fonts" && pwd)
MDI=https://cdn.jsdelivr.net/npm
ROBOTO=https://raw.githubusercontent.com/googlefonts/roboto/main/src/hinted

curl -sSLf -o "$DIR/materialdesignicons-webfont.ttf" \
    "$MDI/@mdi/font@7.4.47/fonts/materialdesignicons-webfont.ttf"
curl -sSLf -o "$DIR/mdi-meta.json" "$MDI/@mdi/svg@7.4.47/meta.json"
for w in Regular Medium Bold; do
    curl -sSLf -o "$DIR/Roboto-$w.ttf" "$ROBOTO/Roboto-$w.ttf"
done
ls -l "$DIR"
