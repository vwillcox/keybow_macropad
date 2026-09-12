"""Local-only (127.0.0.1) REST API + static file server for the web
configurator. This is the only thing the "Open Configurator" tray menu
item points a browser at.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import apps as app_discovery
from .actions import ActionContext, dispatch_actions
from .config import Action, Config, ConfigStore
from .layers import LayerController

logger = logging.getLogger("keybow.server")

WEBUI_DIR = Path(__file__).resolve().parent.parent.parent / "webui"


def create_app(config_store: ConfigStore, layers: LayerController) -> FastAPI:
    app = FastAPI(title="Keybow Configurator")

    @app.get("/api/config")
    def get_config() -> Config:
        return config_store.get()

    @app.put("/api/config")
    def put_config(config: Config):
        if config.active_layer not in config.layer_ids():
            raise HTTPException(status_code=400, detail=f"active_layer {config.active_layer!r} is not a defined layer")
        config_store.replace(config)
        return config

    @app.get("/api/apps")
    def get_apps():
        return [
            {"desktop_id": a.desktop_id, "name": a.name, "icon": a.icon}
            for a in app_discovery.list_apps()
        ]

    @app.get("/api/status")
    def get_status():
        config = config_store.get()
        return {
            "active_layer": layers.current_id(),
            "layers": [{"id": layer.id, "name": layer.name, "color": layer.color} for layer in config.layers],
        }

    @app.post("/api/layer/{layer_id}/activate")
    def activate_layer(layer_id: str):
        if layer_id not in config_store.get().layer_ids():
            raise HTTPException(status_code=404, detail=f"no layer {layer_id!r}")
        layers.set_current(layer_id)
        return {"active_layer": layers.current_id()}

    @app.post("/api/test-action")
    def test_action(action_list: list[Action]):
        # Lets the web UI's "Test" button fire a key's actions immediately,
        # without needing the physical key — same dispatch path a real
        # press uses, just with no key index behind it.
        ctx = ActionContext(config_store, layers, key_index=-1)
        dispatch_actions(action_list, ctx)
        return {"ok": True}

    @app.get("/api/events")
    async def events():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def on_layer_change(layer_id: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, {"active_layer": layer_id})

        def on_config_change(_config) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, {"config_changed": True})

        layers.on_change(on_layer_change)
        config_store.on_change(on_config_change)

        async def stream():
            while True:
                data = await queue.get()
                yield f"data: {json.dumps(data)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    if WEBUI_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEBUI_DIR), html=True), name="webui")
    else:
        logger.warning("webui directory not found at %s", WEBUI_DIR)

    return app
