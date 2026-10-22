#!/usr/bin/env python3
"""Dry run of the screen app against the real Moonraker, with a fake panel.

Draws every page and exercises navigation, step selectors, confirmations and
greyed-out buttons. No G-code is sent: do_action is replaced by a recorder.
Run on the Pi from the screen/ folder of this repo:
    ~/klippy-env/bin/python ../tests/ui_dryrun.py
"""
import sys
import time

sys.path.insert(0, ".")
import kobra_screen as k  # noqa: E402
import ui  # noqa: E402


class FakePanel:
    def __init__(self):
        self.n = self.bytes = 0

    def cmd(self, *c):
        self.n += len(c)
        self.bytes += sum(len(x) + 3 for x in c)


def main():
    panel = FakePanel()
    a = k.App()
    a.screen, a.canvas = panel, k.TjcCanvas(panel)
    actions = []
    a.do_action = lambda b: actions.append((b.key, b.arg))
    a.refresh_state(draw=False)
    a.ui_ready = True
    print("klippy=%s printing=%s homed=%r z_offset=%.3f mesh=%s screws=%d runout=%s ip=%s"
          % (a.st["klippy"], a.st["printing"], a.st["homed"], a.st["z_offset"],
             a.st["mesh"]["profile"], len(a.st["screws"]), a.st["runout"], a.st["ip"]))

    def tap(b):
        x, y, w, h = b.rect
        a.on_touch(x + w // 2, y + h // 2, True)
        a.on_touch(x + w // 2, y + h // 2, False)

    def find(key, arg=None):
        for b in a.buttons:
            if b.key == key and (arg is None or b.arg == arg):
                return b
        raise KeyError((key, arg, a.page))

    # Every page draws without errors
    for name in ui.PAGES:
        if name == "detail":
            a.show("files")
            tap(find("file", 0))
        else:
            a.show(name)
        panel.n = panel.bytes = 0
        a.show(a.page)
        print("  %-9s -> drew %-8s %4d cmds %5d bytes (~%.2fs)  buttons=%d"
              % (name, a.page, panel.n, panel.bytes, panel.bytes / 10000.,
                 len(a.buttons)))

    # Navigation
    a.show("more")
    tap(find("goto", "zoffset"))
    assert a.page == "zoffset"
    tap(find("back"))
    assert a.page == "more", a.page
    # Step selector
    a.show("zoffset")
    tap(find("z_step", 0.05))
    assert a.u["z_step"] == 0.05
    # Confirmation: first tap arms, second confirms
    actions.clear()
    tap(find("z_save"))
    assert a.u["armed"] == "z_save" and not actions
    tap(find("z_save"))
    assert actions == [("z_save", None)], actions
    # Armed state times out
    tap(find("z_save"))
    a.armed_until = time.time() - 1
    a.update_page()
    assert a.u["armed"] is None
    # Plain action
    actions.clear()
    tap(find("z_adjust", -1))
    assert actions == [("z_adjust", -1)]

    # Simulated print: greyed buttons must refuse
    a.st = dict(a.st, printing=True, job_state="printing", chip="printing",
                job=dict(state="printing", filename="x.gcode", progress=0.3,
                         remaining=600, elapsed=300, layer=3, layers=10, z=0.6))
    for page, key, arg in (("home", "quick", "home"), ("move", "jog", ("x", 1)),
                           ("more", "goto", "mesh"), ("temp", "preset", "PLA"),
                           ("zoffset", "z_save", None)):
        a.show(page)
        actions.clear()
        b = find(key, arg)
        assert not b.enabled, (page, key)
        tap(b)
        assert not actions and a.page == page, (page, key, actions)
    # ...while print-time controls still work
    a.show("zoffset")
    actions.clear()
    tap(find("z_adjust", 1))
    assert actions == [("z_adjust", 1)]
    a.show("tune")
    actions.clear()
    tap(find("speed", 1))
    assert actions == [("speed", 1)]
    a.show("system")
    actions.clear()
    tap(find("estop"))
    tap(find("estop"))
    assert actions == [("estop", None)]
    # Activity started elsewhere: jump to its page, grey out G-code buttons
    a.st = dict(a.st, printing=False, job_state="standby", chip="ready", job=None)
    a.show("home")
    real_status, real_store = a.mr.status, a.mr.gcode_store
    fake = {"busy": False, "store": [{"time": 1.0, "type": "command",
                                      "message": "G28"}]}

    def status():
        s = real_status()
        s["print_stats"]["state"] = "standby"
        s["idle_timeout"] = {"state": "Printing" if fake["busy"] else "Ready"}
        return s
    a.mr.status = status
    a.mr.gcode_store = lambda count=30: fake["store"]
    a.gstore_t = None
    a.refresh_state()                      # first look only learns history
    assert a.page == "home"
    fake["busy"] = True
    fake["store"].append({"time": 2.0, "type": "command",
                          "message": "G28\nBED_MESH_CALIBRATE"})
    a.refresh_state()
    assert a.page == "mesh", a.page
    assert a.msg and a.msg[1] == "Calibrating mesh..." and a.msg[3] is None
    assert a.st["chip"] == "busy"
    assert not find("mesh_cal").enabled
    a.show("system")                       # user can still navigate...
    assert find("estop").enabled           # ...and e-stop always works
    a.show("mesh")
    fake["busy"] = False
    a.refresh_state()
    assert a.msg and a.msg[1] == "Done" and find("mesh_cal").enabled
    # Commands sent by the screen itself don't cause a jump
    a.show("home")
    a.sent.append((time.time(), "SCREWS_TILT_CALCULATE"))
    fake["store"].append({"time": 3.0, "type": "command",
                          "message": "SCREWS_TILT_CALCULATE"})
    a.refresh_state()
    assert a.page == "home", a.page
    print("all checks passed")


if __name__ == "__main__":
    main()
