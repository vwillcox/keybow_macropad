"""Finds the Keybow 2040's HID input device, grabs it exclusively (so its
keycodes never leak into whatever window has focus), and turns press/hold/
release timing into action dispatch.

Key press/hold model, per key:
  - a *pure momentary modifier* (hold = [layer_switch momentary], tap empty)
    switches layers the instant it's pressed and reverts the instant it's
    released — no delay, so it feels like a real modifier key.
  - a *layer-tap* key (hold = [layer_switch momentary], tap = something else)
    waits `hold_ms`: released before that fires the tap action, held past it
    engages the layer (reverting on release) — like QMK's LT().
  - a *dedicated toggle* key (tap = [layer_switch toggle], hold empty) fires
    immediately on press, no delay.
  - any other key waits `hold_ms`: if released first, fires `tap`; if held
    past the threshold, fires `hold` once (whatever it contains).
"""
from __future__ import annotations

import asyncio
import logging

import evdev
from evdev import ecodes

from . import rotation
from .actions import ActionContext, dispatch_actions
from .config import ConfigStore, LayerSwitchAction
from .layers import LayerController

logger = logging.getLogger("keybow.input")

VENDOR_ID = 0x16D0
PRODUCT_ID = 0x08C6

# Order must exactly match firmware/code.py's KEYCODES list.
_KEY_NAMES = [
    "KEY_F13", "KEY_F14", "KEY_F15", "KEY_F16",
    "KEY_F17", "KEY_F18", "KEY_F19", "KEY_F20",
    "KEY_F21", "KEY_F22", "KEY_F23", "KEY_F24",
    "KEY_COMPOSE", "KEY_PAUSE", "KEY_SCROLLLOCK", "KEY_SYSRQ",
]


def _build_keycode_map() -> dict[int, int]:
    mapping = {}
    for slot, name in enumerate(_KEY_NAMES):
        code = ecodes.ecodes.get(name)
        if code is None:
            logger.warning("evdev has no keycode named %s; slot %d unreachable", name, slot)
            continue
        mapping[code] = slot
    return mapping


KEYCODE_TO_SLOT = _build_keycode_map()


def find_device() -> evdev.InputDevice | None:
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        if dev.info.vendor == VENDOR_ID and dev.info.product == PRODUCT_ID:
            caps = dev.capabilities().get(ecodes.EV_KEY, [])
            if any(code in KEYCODE_TO_SLOT for code in caps):
                return dev
        dev.close()
    return None


def _dedicated_layer_action(action_list) -> LayerSwitchAction | None:
    if len(action_list) == 1 and isinstance(action_list[0], LayerSwitchAction):
        return action_list[0]
    return None


class KeyState:
    __slots__ = ("hold_task", "hold_fired", "momentary_active")

    def __init__(self):
        self.hold_task: asyncio.Task | None = None
        self.hold_fired = False
        self.momentary_active = False


class InputHandler:
    def __init__(self, config_store: ConfigStore, layer_controller: LayerController):
        self.config_store = config_store
        self.layers = layer_controller
        self._states = {i: KeyState() for i in range(16)}
        self._device: evdev.InputDevice | None = None

    async def run(self) -> None:
        while True:
            if self._device is None:
                self._device = find_device()
                if self._device is None:
                    logger.info("Keybow 2040 not found, retrying...")
                    await asyncio.sleep(2)
                    continue
                try:
                    self._device.grab()
                except OSError as exc:
                    logger.warning("could not grab Keybow input device: %s", exc)
                logger.info("Keybow 2040 input grabbed: %s", self._device.path)
            try:
                async for event in self._device.async_read_loop():
                    if event.type == ecodes.EV_KEY:
                        self._handle_key_event(event)
            except OSError:
                logger.warning("Keybow input device disappeared, will rescan")
                self._device = None
                await asyncio.sleep(1)

    def _handle_key_event(self, event) -> None:
        physical_slot = KEYCODE_TO_SLOT.get(event.code)
        if physical_slot is None:
            return
        degrees = self.config_store.get().rotation
        slot = rotation.physical_to_logical(degrees, physical_slot)
        if event.value == 1:
            self._on_press(slot)
        elif event.value == 0:
            self._on_release(slot)

    def _config_key(self, slot: int):
        layer = self.config_store.get().get_layer(self.layers.current_id())
        if layer is None:
            return None
        return layer.keys[slot]

    def _on_press(self, slot: int) -> None:
        key = self._config_key(slot)
        state = self._states[slot]
        state.hold_fired = False
        state.momentary_active = False
        if key is None:
            return

        dedicated_hold = _dedicated_layer_action(key.hold)
        if dedicated_hold is not None and dedicated_hold.mode == "momentary" and not key.tap:
            state.momentary_active = True
            state.hold_fired = True
            self.layers.begin_momentary(slot, dedicated_hold.target)
            return

        dedicated_tap = _dedicated_layer_action(key.tap)
        if dedicated_tap is not None and dedicated_tap.mode == "toggle" and not key.hold:
            state.hold_fired = True  # suppress the normal tap firing on release
            ctx = ActionContext(self.config_store, self.layers, slot)
            dispatch_actions(key.tap, ctx)
            return

        hold_ms = self.config_store.get().hold_ms
        loop = asyncio.get_event_loop()
        state.hold_task = loop.create_task(self._fire_hold_after_delay(slot, hold_ms / 1000))

    async def _fire_hold_after_delay(self, slot: int, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
        key = self._config_key(slot)
        state = self._states[slot]
        state.hold_fired = True
        if key is None:
            return
        dedicated_hold = _dedicated_layer_action(key.hold)
        if dedicated_hold is not None and dedicated_hold.mode == "momentary":
            state.momentary_active = True
            self.layers.begin_momentary(slot, dedicated_hold.target)
            return
        if key.hold:
            ctx = ActionContext(self.config_store, self.layers, slot)
            dispatch_actions(key.hold, ctx)

    def _on_release(self, slot: int) -> None:
        state = self._states[slot]
        if state.hold_task is not None and not state.hold_task.done():
            state.hold_task.cancel()
        if state.momentary_active:
            state.momentary_active = False
            self.layers.end_momentary(slot)
            return
        if not state.hold_fired:
            key = self._config_key(slot)
            if key and key.tap:
                ctx = ActionContext(self.config_store, self.layers, slot)
                dispatch_actions(key.tap, ctx)
        state.hold_fired = False
