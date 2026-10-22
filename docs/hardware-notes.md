# Hardware notes and findings

## Display

Decoded from the header of Anycubic's stock screen firmware
(`Anycubic_20230529T_newui.tft`), using the format documented by
[UNUF/nxt-doc](https://github.com/UNUF/nxt-doc/blob/main/File%20Formats/TFT.md)
and [TFTTool](https://github.com/UNUF/TFTTool):

| Field | Value |
|---|---|
| Vendor | TJC (Nextion editor and files don't work on it) |
| Model | TJC4827X243_011, found by matching the model-name CRC at offset 0x2E |
| Panel | 480×272, used at 90° (portrait) |
| Stock editor | USART HMI 1.65.3 |
| Flash | 8 MB (TJC spec). Pictures are stored compressed (~20–40 KB per full-screen picture). |

The stock UI speaks DWIN DGUS framing (`5A A5 …`), which is why Anycubic's
Marlin uses `ANYCUBIC_LCD_DGUS`. With our `.tft` the screen accepts normal
TJC instructions.

The screen's saved default baud (`bauds`) was 9600. Our `.tft` switches to
115200 at page load; setting `bauds=115200` once makes it the boot default.

## Screen wiring on the mainboard

From Anycubic's published Kobra 2 source
([ANYCUBIC-3D/Kobra2](https://github.com/ANYCUBIC-3D/Kobra2)):
`LCD_SERIAL_PORT 4`, `board/bsp_init.h` → **USART4, TX = PB10, RX = PH2**.
The host link stays on USART1 (PA15/PA9, CH340) at 250000 baud.

## Klipper's HC32F460 serial driver bug

With the bridge sending many small messages, Klipper's link to the Pi
started corrupting frames (`bytes_invalid` rising fast). Cause: a race in
`src/hc32f460/serial.c`. A transmit-complete interrupt could switch the
transmitter off while a freshly queued message was going out.

It can't simply keep the transmitter on: **HC32F460 errata 2.6.1** says the
TX-empty interrupt only fires when TE and TXEIE are set together while
TE = 0. Keeping TE on stalls the link. The fix (applied by `apply.sh`):

- `serial_enable_tx_irq` starts the transmitter only from TE = 0;
- if a message is queued while the previous one is still finishing, it sets
  a flag and the TX-complete interrupt restarts the transmitter properly.

Result: 2400/2400 byte-exact screen round trips, `bytes_invalid` = 0.
The bug also exists without the bridge (it shows up as occasional
retransmits); the bridge just triggers it much more often.

Source: [HC32F460 errata sheet](https://m.huazhoucn.com/downloads/xshc/ES_HC32F460_A460_F451_F452%E7%B3%BB%E5%88%97%E5%8B%98%E8%AF%AF%E8%A1%A8_Rev1.0.pdf), item 2.6.1.

## Framing errors in klippy.log

`serial_bridge: line errors (flags=4, ...)` appears in bursts of about 12 per
screen reboot. During a reset the panel holds its TX line low, which the UART
reads as broken bytes. `tests/noise_test.py` showed 0 errors in ~5300 round
trips with motors off, powered, and moving, so stepper noise is not a
problem. The bursts are harmless.

## Z safety

Unrelated to the screen, but worth knowing: some Kobra 2 Klipper configs use
`position_min: -15` for `[stepper_z]`, which lets any Z move go 15 mm below
the bed. With an inductive probe, `position_min: -1` is enough (mesh
compensation stays well within it) and turns accidental moves into
"Move out of range" errors instead of crashes.
