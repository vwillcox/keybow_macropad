"""Local-only (127.0.0.1) REST API + static file server for the web
configurator. This is the only thing the "Open Configurator" tray menu
item points a browser at.

Binding to loopback alone isn't a security boundary: any local user can
connect, and a web page can reach it via DNS rebinding (its own hostname
re-resolved to 127.0.0.1, making the page same-origin with us). Since the
API can run arbitrary shell commands, two checks guard it:

- TrustedHostMiddleware rejects any Host header that isn't 127.0.0.1 /
  localhost, which is what a rebinding attack necessarily carries.
- Every /api/ request must present the per-user token from
  $XDG_RUNTIME_DIR/keybow/token (mode 0600), via the X-Keybow-Token header
  or, for EventSource which can't set headers, a ?token= query parameter.
  The tray hands it to the web UI in the URL fragment, which the browser
  never sends to any server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import apps as app_discovery
from .actions import ActionContext, dispatch_actions
from .config import Action, Config, ConfigStore
from .layers import LayerController

logger = logging.getLogger("keybow.server")

WEBUI_DIR = Path(__file__).resolve().parent.parent.parent / "webui"
TOKEN_HEADER = "X-Keybow-Token"


def _token_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime_dir) / "keybow" / "token"


def load_or_create_token() -> str:
    """Reuses the token across daemon restarts (the service restarts on every
    replug, and an open configurator tab shouldn't be locked out by that);
    $XDG_RUNTIME_DIR is wiped at logout, so it still rotates per session."""
    path = _token_path()
    try:
        token = path.read_text().strip()
        if token:
            return token
    except FileNotFoundError:
        pass
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    return token


def create_app(config_store: ConfigStore, layers: LayerController, token: str) -> FastAPI:
    app = FastAPI(title="Keybow Configurator", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            presented = request.headers.get(TOKEN_HEADER) or request.query_params.get("token") or ""
            if not secrets.compare_digest(presented.encode(), token.encode()):
                return JSONResponse({"detail": "missing or invalid token"}, status_code=401)
        return await call_next(request)

    # Added last so it runs first, before anything else sees the request.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

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
            try:
                while True:
                    data = await queue.get()
                    yield f"data: {json.dumps(data)}\n\n"
            finally:
                # Runs when the client disconnects; without it every closed
                # tab would leave its callbacks (and queue) behind forever.
                layers.off_change(on_layer_change)
                config_store.off_change(on_config_change)

        return StreamingResponse(stream(), media_type="text/event-stream")

    if WEBUI_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEBUI_DIR), html=True), name="webui")
    else:
        logger.warning("webui directory not found at %s", WEBUI_DIR)

    return app
