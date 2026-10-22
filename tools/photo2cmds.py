#!/usr/bin/env python3
"""Turn a photo into TJC fill commands for live drawing over the bridge.

Quantises to a small palette, encodes each row as runs of one colour and
merges identical runs stacked vertically into taller rectangles. The most
common colour becomes the cls background and is not drawn.

Usage: photo2cmds.py photo.jpg out_prefix [colors]
Writes out_prefix.txt (one command per line) and out_prefix_preview.png.
"""
import collections
import sys

from PIL import Image

W, H = 272, 480


def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def from565(c):
    r, g, b = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def convert(path, colors):
    im = Image.open(path).convert("RGB")
    # Crop to the screen's aspect ratio, then scale
    sw, sh = im.size
    if sw * H > sh * W:
        nw = sh * W // H
        im = im.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
    else:
        nh = sw * H // W
        im = im.crop((0, (sh - nh) // 2, sw, (sh - nh) // 2 + nh))
    im = im.resize((W, H), Image.LANCZOS)
    q = im.quantize(colors=colors, method=Image.MEDIANCUT,
                    dither=Image.Dither.NONE).convert("RGB")
    px = q.load()
    grid = [[rgb565(*px[x, y]) for x in range(W)] for y in range(H)]
    bg = collections.Counter(c for row in grid for c in row).most_common(1)[0][0]

    rects = []
    open_runs = {}  # (x, w, color) -> rect index, for runs ending on prev row
    for y in range(H):
        row = grid[y]
        runs = []
        x = 0
        while x < W:
            c = row[x]
            x2 = x
            while x2 < W and row[x2] == c:
                x2 += 1
            runs.append((x, x2 - x, c))
            x = x2
        next_open = {}
        for run in runs:
            if run[2] == bg:
                continue
            idx = open_runs.get(run)
            if idx is not None:
                rects[idx][3] += 1  # grow downwards
            else:
                idx = len(rects)
                rects.append([run[0], y, run[1], 1, run[2]])
            next_open[run] = idx
        open_runs = next_open

    cmds = ["cls %d" % bg] + ["fill %d,%d,%d,%d,%d" % tuple(r) for r in rects]

    # Preview of exactly what the screen will show
    prev = Image.new("RGB", (W, H), from565(bg))
    pp = prev.load()
    for x, y, w, h, c in rects:
        col = from565(c)
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                pp[xx, yy] = col
    return cmds, prev


def main():
    path, prefix = sys.argv[1], sys.argv[2]
    colors = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    cmds, prev = convert(path, colors)
    size = sum(len(c) + 3 for c in cmds)
    with open(prefix + ".txt", "w") as f:
        f.write("\n".join(cmds) + "\n")
    prev.save(prefix + "_preview.png")
    # Effective rate through the bridge is a bit under 11.5 KB/s
    print("%d colors: %d rects, %.0f KB, ~%.0f s to draw"
          % (colors, len(cmds) - 1, size / 1024, size / 10000))


if __name__ == "__main__":
    main()
