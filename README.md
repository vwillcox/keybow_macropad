# Keybow 2040 macro pad

Turns a [Pimoroni Keybow 2040](https://shop.pimoroni.com/products/keybow-2040)
into a fully configurable Linux macro pad: a tray icon, a local web UI with
layers and per-key actions (open a URL, launch any installed app, run a
shell command, type text / send hotkeys, switch layers), all editable live
with no reflashing.

Confirmed working on this machine: device `16d0:08c6`, Omarchy/Quickshell
bar (tray via standard StatusNotifierItem), Hyprland (`wtype` for synthetic
keystrokes).

## How it's split up

- **`firmware/`** — CircuitPython. Deliberately dumb: reports which of the
  16 keys is pressed (as fixed, otherwise-unused HID keycodes) and displays
  LED colors the host tells it to. No app logic lives here.
- **`daemon/`** — Python service. Grabs the pad's input exclusively, tracks
  layers/tap/hold timing, runs actions, serves the web UI + REST API on
  `127.0.0.1:8642`, and registers the tray icon.
- **`webui/`** — the configurator itself (vanilla HTML/CSS/JS, no build
  step) — served by the daemon, opened from the tray menu.
- **`install/`** — udev rule, systemd `--user` unit, and `install.sh` to
  wire it all up.
- **`config/default.config.json`** — seed config copied to
  `~/.config/keybow/config.json` on first run: 4 example layers, one key
  that opens ProtonMail webmail, one hold-for-momentary-layer key, one
  toggle-layer key.

## 1. Flash the firmware

The Keybow ships with CircuitPython, but needs two libraries added and our
two files copied over.

1. Double-tap the reset button (or hold BOOTSEL while plugging in) to drop
   it into bootloader mode if needed, then let it boot normally — it should
   already show up as a `CIRCUITPY` USB drive when running CircuitPython.
2. From the [Adafruit CircuitPython bundle](https://circuitpython.org/libraries)
   matching your CircuitPython version, copy `adafruit_hid/` into
   `CIRCUITPY/lib/`. From [Pimoroni's PMK library](https://github.com/pimoroni/pmk-circuitpython),
   copy the `pmk/` folder into `CIRCUITPY/lib/` too.
3. Copy `firmware/boot.py` and `firmware/code.py` onto `CIRCUITPY/` (this
   repo's `firmware/code.py` replaces whatever demo `code.py` is there).
4. Power-cycle the board (unplug/replug, or reset button). `boot.py` only
   takes effect after a real reset.
5. You should now see **two** serial devices show up
   (`/dev/ttyACM0` and `/dev/ttyACM1` — console and the LED data channel),
   and the keys, while nothing is grabbing them, produce F13–F24 plus
   Menu/Pause/ScrollLock/PrintScreen — harmless until the daemon runs.

## 2. Install the daemon

```sh
./install/install.sh
```

This does four things, in order:
1. Installs `install/99-keybow2040.rules` to `/etc/udev/rules.d/` (**one
   `sudo` prompt**) so the pad's input device is usable without being in
   the `input` group, and reloads udev.
2. Creates a venv at `~/.local/share/keybow/venv` and installs the daemon
   into it.
3. Seeds `~/.config/keybow/config.json` from `config/default.config.json`
   if you don't already have one (never overwrites an existing config).
4. Installs and enables `keybow-daemon.service` as a systemd `--user` unit,
   so it starts automatically on login.

Check it's running:

```sh
systemctl --user status keybow-daemon
journalctl --user -u keybow-daemon -f
```

## 3. Configure

Click the keyboard icon in the bar → **Open Configurator** (or open
`http://127.0.0.1:8642` yourself). Pick a layer tab, click a key, add
actions to its **Tap** (fires on quick press+release) and/or **Hold**
(fires once you've held it past the threshold) lists, set a label/LED
color, hit **Save to device** — it applies immediately, no restart needed.

**Layers**: a key whose *only* Hold action is "Switch Layer → momentary"
with an empty Tap list becomes an instant modifier — the layer is active
exactly while you hold that key down (like a shift key). A key whose only
Tap action is "Switch Layer → toggle" with an empty Hold list switches
layers immediately on press, and switches back if you press it again.
Mix a layer-switch into a longer action list on the same key and it'll
still run, but only the two "dedicated key" patterns above get the
instant (no hold-delay) behavior.

**Macros** are named, reusable action lists you can invoke from any key
via a "Run Macro" action — edit them in the Macros section at the bottom
of the left column.

**Device rotation** (footer dropdown): if you physically rotate the pad —
e.g. to move the USB-C port from one edge to another — set this instead of
redoing your layout. It remaps which physical key produces which logical
key number (config, web UI grid, and LEDs all stay in "logical" space), so
whatever you'd built stays in the same relative position after the turn.
The four options are just the four 90°-apart physical orientations; if the
one you pick doesn't match after rotating, try the adjacent one — there's
no way to know which is which without seeing the device rotate.

## Troubleshooting

- **Tray icon doesn't appear**: `systemctl --user status keybow-daemon` —
  check for errors around `tray icon registered`. `busctl --user list |
  grep StatusNotifierItem` should show the daemon's bus name once it's up.
- **Keys do nothing**: `ls /dev/input/by-id/ | grep -i keybow` should list
  the pad; if `test -r` on that event device fails, the udev rule didn't
  apply — run `sudo udevadm control --reload-rules && sudo udevadm trigger
  --action=add` (a plain `trigger` sends a "change" event, which some
  permission-granting udev logic ignores — `--action=add` forces the event
  type that reliably re-applies rules to an already-connected device).
- **LEDs don't update**: needs both firmware files (`boot.py` *and*
  `code.py`) and a power-cycle after copying `boot.py` — the daemon logs a
  warning and keeps working without LEDs if it can't find the second
  serial port.
- **Hotkeys/text don't get typed**: the daemon shells out to `wtype`
  (already installed on this system) — it only affects the currently
  focused Wayland window, same as if you'd typed it yourself.
