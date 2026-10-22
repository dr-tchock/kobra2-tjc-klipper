# Development

## Layout

| Path | What |
|---|---|
| `klipper-bridge/` | Klipper extension (MCU C file, host module) and build/install scripts |
| `screen/kobra_screen.py` | The service: panel link, Moonraker, state following, actions |
| `screen/ui.py` | Theme, fonts/icon IDs, page classes (layouts + buttons) |
| `tools/` | Icon generator, mockup renderer, font width table, photo converter |
| `tests/` | Link tests and the UI dry run |
| `assets/`, `tft/` | What goes into the screen firmware |

## Mockups first

`tools/mockup.py` renders every page to PNG with the same `ui.py` code, the
real Roboto fonts and the real icons (needs Pillow and `tools/fetch_fonts.sh`):

```sh
python tools/mockup.py mockups
```

It only uses what the panel can draw (fills, filled circles, stored pictures,
text), so a mockup is what the screen will show, apart from slightly rougher
circle edges.

## Adding a page or button

- Add a `Page` subclass in `ui.py` and register it in `PAGES`.
- Return `Button`s from `draw()`; give each an `enabled` flag:
  - `ui.idle(st)` for anything that would ruin a print (homing, jogging,
    presets, calibrations);
  - `ui.can_gcode(st)` for things that are fine during a print but would only
    queue behind a long running command (Z offset, speed, temperature ±);
  - always enabled for navigation, pause/cancel and emergency stop.
- Handle the button key in `App.do_action()` (or `activate()` for screen-only
  actions). Keys that send G-code belong in `GCODE_KEYS`; keys needing a
  second tap belong in `CONFIRM`.
- If the page shows live values, implement `dyn_key()` and `update()` to
  repaint only those.

## Testing

On the Pi, from `screen/`:

```sh
~/klippy-env/bin/python ../tests/ui_dryrun.py
```

draws every page against the real Moonraker with a fake panel and checks
navigation, confirmations and greyed-out buttons. It sends no G-code.

Link tests (stop the service first: `sudo systemctl stop kobra-screen`):

- `tests/stress.py`: byte-exact round trips through the bridge;
- `tests/noise_test.py`: the same during motor moves (homes, then XY at Z 20).

## Deploying changes

The service runs the files in place, so after editing:

```sh
sudo systemctl restart kobra-screen
tail -f ~/printer_data/logs/kobra_screen.log
```
