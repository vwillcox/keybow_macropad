"""Talks the tiny "LED,<index>,<r>,<g>,<b>\\n" protocol to the firmware's
second USB CDC ("data") serial port (see firmware/boot.py + code.py).

LED feedback is a nice-to-have, never a hard dependency: if the serial link
can't be found or drops, everything here degrades to a no-op rather than
taking the rest of the daemon down with it.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import serial
from serial.tools import list_ports

logger = logging.getLogger("keybow.led")

VENDOR_ID = 0x16D0
PRODUCT_ID = 0x08C6


def _candidate_ports() -> list[str]:
    matches = [
        p.device
        for p in list_ports.comports()
        if p.vid == VENDOR_ID and p.pid == PRODUCT_ID
    ]
    # CircuitPython enables the console CDC port before the data CDC port,
    # so on Linux the data port is reliably the higher-numbered ttyACMn.
    return sorted(matches)


class LedLink:
    def __init__(self):
        # Reentrant: _write() calls connect() while already holding the lock
        # when it needs to reconnect, which would deadlock a plain Lock.
        self._lock = threading.RLock()
        self._serial: serial.Serial | None = None
        self._on_reconnect: Callable[[], None] | None = None
        self.connect()

    def on_reconnect(self, callback: Callable[[], None]) -> None:
        """Register a callback fired after the link re-establishes following
        a drop (the pad got unplugged and replugged, or briefly lost power).
        The firmware has no memory of LED state across a power cycle, so a
        freshly reconnected link is dark until someone repaints it — this is
        the hook callers use to do that (see LayerController.refresh_leds)."""
        self._on_reconnect = callback

    def connect(self) -> bool:
        with self._lock:
            if self._serial is not None:
                return True
            ports = _candidate_ports()
            if len(ports) < 2:
                logger.warning(
                    "could not find the Keybow's LED data serial port (found %s); "
                    "LED feedback disabled until it appears",
                    ports,
                )
                return False
            data_port = ports[-1]
            try:
                self._serial = serial.Serial(data_port, baudrate=115200, timeout=0)
            except serial.SerialException as exc:
                logger.warning("could not open %s for LED feedback: %s", data_port, exc)
                self._serial = None
                return False
            logger.info("LED link connected on %s", data_port)
            if self._on_reconnect is not None:
                self._on_reconnect()
            return True

    def set_led(self, index: int, rgb_hex: str) -> None:
        r, g, b = _hex_to_rgb(rgb_hex)
        self._write(f"LED,{index},{r},{g},{b}\n")

    def set_all(self, rgb_hex: str) -> None:
        r, g, b = _hex_to_rgb(rgb_hex)
        for i in range(16):
            self._write(f"LED,{i},{r},{g},{b}\n")

    def _write(self, line: str) -> None:
        with self._lock:
            if self._serial is None and not self.connect():
                return
            try:
                self._serial.write(line.encode())
            except serial.SerialException as exc:
                logger.warning("LED link write failed, will retry to reconnect: %s", exc)
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
