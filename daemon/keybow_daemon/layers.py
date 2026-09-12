"""Tracks which layer is currently active, independent of the persisted
config's `active_layer` (that's just the layer you boot into). Handles both
toggle (press to switch, press again to switch back) and momentary
(active only while a key is held) layer changes, and pushes LED updates +
notifies listeners (SSE clients, the tray icon) whenever the active layer
changes.
"""
from __future__ import annotations

import logging

from . import rotation
from .config import ConfigStore
from .led import LedLink

logger = logging.getLogger("keybow.layers")


class LayerController:
    def __init__(self, config_store: ConfigStore, led_link: LedLink):
        self._config_store = config_store
        self._led = led_link
        self._current = config_store.get().active_layer
        self._previous = self._current
        # key_index -> layer id that was active before this key's momentary
        # switch began, so nested/overlapping momentary keys revert cleanly.
        self._momentary_stack: dict[int, str] = {}
        self._listeners: list = []
        config_store.on_change(self._on_config_reloaded)
        self._sync_leds()

    def on_change(self, callback) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb(self._current)
        self._sync_leds()

    def _on_config_reloaded(self, config) -> None:
        if config.get_layer(self._current) is None:
            # the layer we were on got deleted/renamed out from under us
            self._current = config.active_layer
        self._sync_leds()

    def current_id(self) -> str:
        return self._current

    def refresh_leds(self) -> None:
        """Repaint every LED for the current layer. Callers use this after
        the LED link reconnects, since the firmware forgets all LED state
        across a power cycle."""
        self._sync_leds()

    def _sync_leds(self) -> None:
        config = self._config_store.get()
        layer = config.get_layer(self._current)
        if layer is None:
            return
        for logical_i, key in enumerate(layer.keys):
            physical_i = rotation.logical_to_physical(config.rotation, logical_i)
            self._led.set_led(physical_i, key.color)

    def set_current(self, target: str) -> None:
        """Unconditional switch (used by the web UI / tray menu)."""
        if target not in self._config_store.get().layer_ids():
            logger.warning("layer_switch target %r does not exist", target)
            return
        if target == self._current:
            return
        self._previous = self._current
        self._current = target
        self._notify()

    def toggle(self, target: str) -> None:
        """Switch to `target`, or back to whatever was active before if
        `target` is already active (used by hardware toggle keys)."""
        if self._current == target:
            self.set_current(self._previous)
        else:
            self.set_current(target)

    def begin_momentary(self, key_index: int, target: str) -> None:
        if target not in self._config_store.get().layer_ids():
            logger.warning("layer_switch target %r does not exist", target)
            return
        self._momentary_stack[key_index] = self._current
        self._current = target
        self._notify()

    def end_momentary(self, key_index: int) -> None:
        previous = self._momentary_stack.pop(key_index, None)
        if previous is None:
            return
        self._current = previous
        self._notify()
