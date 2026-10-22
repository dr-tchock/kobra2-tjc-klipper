# Screen firmware (`kobra2.tft`)

Ready-to-flash firmware for the Kobra 2's stock touchscreen. It is mostly an
empty shell: everything you see is drawn live by `screen/kobra_screen.py`
on the Pi. The `.tft` only stores what has to live inside the screen.

| Item | Details |
|---|---|
| Display | TJC4827X243_011 (X2 series, 4.3", 480×272, resistive) |
| Orientation | 90° (portrait, 272×480) |
| Editor | TJC USART HMI 1.68.1 |
| Page 0 pre-init | `baud=115200` |
| Boot animation | component `gm0`, `loop` = no, `en` = 1, from `assets/boot/boot.gif` |
| Fonts 0–4 | Roboto 16 / 20 / 24 / 32 / 48 px, ASCII + `°` (sources in `fonts/`) |
| Pictures 0–66 | `assets/icons/*.png`, imported in file-name order |

The screen program relies on these numbers. If you rebuild the `.tft`, keep
the font order and import the icons in file-name order (ID = file prefix).
See [docs/editing-the-tft.md](../docs/editing-the-tft.md).

## Flashing

1. Copy `kobra2.tft` to a FAT32 SD card. It must be the only file on it.
2. Printer off, card into the slot **under the touchscreen** (not the mainboard slot).
3. Power on. The screen shows a progress bar; wait for "Update Successed!" (2–3 min).
4. Power off, remove the card, power on.

To go back to the stock interface, flash Anycubic's original `.tft` the same
way (it comes with Anycubic's Kobra 2 firmware download).
