"""Config schema (pydantic models) + a thread-safe store with hot-reload.

This is the single source of truth for what a "key" can do. Both the REST
API (server.py) and the input dispatcher (input.py) work against these same
models, so anything the web UI can save is automatically something the
pad can run.
"""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator

NUM_KEYS = 16
DEFAULT_PORT = 8642
DEFAULT_HOLD_MS = 400

CONFIG_DIR = Path.home() / ".config" / "keybow"
CONFIG_PATH = CONFIG_DIR / "config.json"
SEED_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.config.json"


# ---- Actions -----------------------------------------------------------

class OpenUrlAction(BaseModel):
    type: Literal["open_url"] = "open_url"
    url: str


class LaunchAppAction(BaseModel):
    type: Literal["launch_app"] = "launch_app"
    desktop_id: str
    name: str = ""


class ExecAction(BaseModel):
    type: Literal["exec"] = "exec"
    command: str


class TextStep(BaseModel):
    kind: Literal["text"] = "text"
    value: str


class HotkeyStep(BaseModel):
    kind: Literal["hotkey"] = "hotkey"
    keys: list[str] = Field(default_factory=list)


class DelayStep(BaseModel):
    kind: Literal["delay"] = "delay"
    ms: int = 100


KeySequenceStep = Annotated[
    Union[TextStep, HotkeyStep, DelayStep], Field(discriminator="kind")
]


class KeySequenceAction(BaseModel):
    type: Literal["key_sequence"] = "key_sequence"
    steps: list[KeySequenceStep] = Field(default_factory=list)


class LayerSwitchAction(BaseModel):
    type: Literal["layer_switch"] = "layer_switch"
    target: str
    mode: Literal["toggle", "momentary"] = "toggle"


class MacroAction(BaseModel):
    type: Literal["macro"] = "macro"
    id: str


Action = Annotated[
    Union[
        OpenUrlAction,
        LaunchAppAction,
        ExecAction,
        KeySequenceAction,
        LayerSwitchAction,
        MacroAction,
    ],
    Field(discriminator="type"),
]


# ---- Layers / keys -------------------------------------------------------

class KeyConfig(BaseModel):
    label: str = ""
    color: str = "#222222"
    tap: list[Action] = Field(default_factory=list)
    hold: list[Action] = Field(default_factory=list)


class Layer(BaseModel):
    id: str
    name: str
    color: str = "#2b6cb0"
    keys: list[KeyConfig] = Field(default_factory=lambda: [KeyConfig() for _ in range(NUM_KEYS)])

    @field_validator("keys")
    @classmethod
    def _exactly_16(cls, v: list[KeyConfig]) -> list[KeyConfig]:
        if len(v) != NUM_KEYS:
            raise ValueError(f"a layer must have exactly {NUM_KEYS} keys, got {len(v)}")
        return v


class Macro(BaseModel):
    id: str
    name: str
    steps: list[Action] = Field(default_factory=list)


class Config(BaseModel):
    port: int = DEFAULT_PORT
    hold_ms: int = DEFAULT_HOLD_MS
    # Lets you physically rotate the pad (e.g. to move the USB-C port from
    # one edge to another) without having to redo your layout: logical key
    # 0 stays "the same key" from your perspective, whichever physical key
    # now occupies that corner. See rotation.py.
    rotation: Literal[0, 90, 180, 270] = 0
    active_layer: str
    layers: list[Layer]
    macros: dict[str, Macro] = Field(default_factory=dict)

    @field_validator("layers")
    @classmethod
    def _at_least_one_layer(cls, v: list[Layer]) -> list[Layer]:
        if not v:
            raise ValueError("config must have at least one layer")
        return v

    def layer_ids(self) -> set[str]:
        return {layer.id for layer in self.layers}

    def get_layer(self, layer_id: str) -> Layer | None:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        return None


class ConfigError(Exception):
    pass


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if SEED_CONFIG_PATH.exists():
            shutil.copy(SEED_CONFIG_PATH, path)
        else:
            raise ConfigError(f"no config at {path} and no seed config to copy from")
    raw = json.loads(path.read_text())
    config = Config.model_validate(raw)
    if config.active_layer not in config.layer_ids():
        raise ConfigError(f"active_layer {config.active_layer!r} is not one of the defined layers")
    return config


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(config.model_dump_json(indent=2))
    tmp.replace(path)


class ConfigStore:
    """Thread-safe holder for the live Config, with file hot-reload.

    A bad edit to config.json (or a bad PUT from the web UI) never replaces
    the last-known-good config — callers get a ConfigError back and the
    daemon keeps running on what it already had.
    """

    def __init__(self, path: Path = CONFIG_PATH):
        self._path = path
        self._lock = threading.RLock()
        self._config = load_config(path)
        self._mtime = path.stat().st_mtime
        self._listeners: list = []

    def get(self) -> Config:
        with self._lock:
            return self._config

    def on_change(self, callback) -> None:
        self._listeners.append(callback)

    def off_change(self, callback) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb(self._config)

    def replace(self, new_config: Config) -> None:
        with self._lock:
            save_config(new_config, self._path)
            self._config = new_config
            self._mtime = self._path.stat().st_mtime
        self._notify()

    def poll_for_external_changes(self) -> bool:
        """Call periodically; reloads from disk if the file changed under us
        (e.g. hand-edited). Returns True if a reload happened."""
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return False
        with self._lock:
            if mtime == self._mtime:
                return False
            try:
                new_config = load_config(self._path)
            except (ConfigError, Exception):
                return False
            self._config = new_config
            self._mtime = mtime
        self._notify()
        return True
