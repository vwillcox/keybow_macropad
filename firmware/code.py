"""
Keybow 2040 firmware — deliberately dumb.

All 16 physical keys always report the same fixed, otherwise-unused HID
keycode on press/release. It never knows about layers, macros, or apps —
that logic lives entirely in the host daemon (see daemon/), which is what
lets the whole thing be reconfigured live from the web UI without ever
reflashing this device.

The only other thing this firmware does is listen on the second USB CDC
serial (enabled in boot.py) for simple "LED,<index>,<r>,<g>,<b>\n" lines
from the host and set the corresponding key's RGB LED.
"""

import usb_cdc
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode

from pmk import PMK
from pmk.platform.keybow2040 import Keybow2040 as Hardware

keybow = PMK(Hardware())
keys = keybow.keys
keyboard = Keyboard(usb_hid.devices)

# 16 keycodes that are essentially never bound to anything by default, so
# the pad is harmless even if the daemon isn't running to grab it.
KEYCODES = [
    Keycode.F13, Keycode.F14, Keycode.F15, Keycode.F16,
    Keycode.F17, Keycode.F18, Keycode.F19, Keycode.F20,
    Keycode.F21, Keycode.F22, Keycode.F23, Keycode.F24,
    Keycode.APPLICATION, Keycode.PAUSE, Keycode.SCROLL_LOCK, Keycode.PRINT_SCREEN,
]


def make_press_handler(index):
    def handler(key):
        keyboard.press(KEYCODES[index])
    return handler


def make_release_handler(index):
    def handler(key):
        keyboard.release(KEYCODES[index])
    return handler


for index, key in enumerate(keys):
    keybow.on_press(key)(make_press_handler(index))
    keybow.on_release(key)(make_release_handler(index))

serial = usb_cdc.data
led_buf = b""


def process_led_serial():
    global led_buf
    if serial is None or serial.in_waiting == 0:
        return
    led_buf += serial.read(serial.in_waiting)
    while b"\n" in led_buf:
        line, _, led_buf = led_buf.partition(b"\n")
        try:
            parts = line.decode().strip().split(",")
            if len(parts) == 5 and parts[0] == "LED":
                idx, r, g, b = (int(p) for p in parts[1:])
                if 0 <= idx < len(keys):
                    keys[idx].set_led(r, g, b)
        except Exception:
            # Malformed line on the wire — ignore and keep going, never crash
            # the input loop over a bad LED command.
            pass


while True:
    keybow.update()
    process_led_serial()
