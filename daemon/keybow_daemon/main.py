"""Entrypoint: wires up config, LED link, layer state, HID input handling,
the local web server, and the tray icon, then runs them all on one asyncio
event loop.
"""
from __future__ import annotations

import asyncio
import logging

import uvicorn

from .config import ConfigStore
from .input import InputHandler
from .layers import LayerController
from .led import LedLink
from .server import create_app, load_or_create_token
from .tray import TrayIcon

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-14s %(levelname)-7s %(message)s")
logger = logging.getLogger("keybow.main")


async def _poll_config_changes(config_store: ConfigStore) -> None:
    while True:
        await asyncio.sleep(2)
        if config_store.poll_for_external_changes():
            logger.info("config.json changed on disk, reloaded")


async def _tray_with_retry(tray: TrayIcon) -> None:
    # A one-shot attempt at boot can lose a race against the bar's own
    # startup (its StatusNotifierWatcher isn't registered yet), with no way
    # to recover for the rest of the process's life. Retry with backoff
    # instead, capped low enough to notice the bar coming up within a
    # minute but without hammering D-Bus if it never does.
    delay = 2.0
    while True:
        try:
            await tray.start()
            return
        except Exception:
            logger.warning("tray icon failed to start; retrying in %.0fs", delay, exc_info=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


async def async_main() -> None:
    config_store = ConfigStore()
    config = config_store.get()

    led = LedLink()
    layers = LayerController(config_store, led)
    led.on_reconnect(layers.refresh_leds)
    input_handler = InputHandler(config_store, layers)

    token = load_or_create_token()
    app = create_app(config_store, layers, token)
    web_url = f"http://127.0.0.1:{config.port}"
    # The fragment never leaves the browser (not sent in requests, Referer,
    # or server logs); the web UI reads the token from it.
    tray = TrayIcon(config_store, layers, f"{web_url}/#token={token}")

    # Without this, uvicorn's graceful shutdown waits indefinitely for any
    # open connection to close on its own — including the /api/events SSE
    # stream, which is designed to stay open forever. That turned a plain
    # `systemctl restart` into a multi-minute hang while the web UI was open.
    uvicorn_config = uvicorn.Config(
        app, host="127.0.0.1", port=config.port, log_level="warning", timeout_graceful_shutdown=3
    )
    server = uvicorn.Server(uvicorn_config)

    logger.info("Keybow daemon running — configurator at %s (open it from the tray icon)", web_url)

    tasks = [
        asyncio.create_task(_tray_with_retry(tray), name="tray"),
        asyncio.create_task(input_handler.run(), name="input"),
        asyncio.create_task(server.serve(), name="web-server"),
        asyncio.create_task(_poll_config_changes(config_store), name="config-poll"),
    ]
    await asyncio.gather(*tasks)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
