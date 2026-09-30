"""Executes the action lists attached to a key. Every action type here is a
small, self-contained side effect — open a URL, launch an app, run a shell
command, or synthesize keystrokes into whatever window has focus (via
`wtype`, which is already Wayland/Hyprland-native on this system).
"""
from __future__ import annotations

import logging
import subprocess
import time

from . import apps
from .config import (
    Action,
    ConfigStore,
    DelayStep,
    ExecAction,
    HotkeyStep,
    KeySequenceAction,
    LaunchAppAction,
    LayerSwitchAction,
    MacroAction,
    OpenUrlAction,
    TextStep,
)
from .layers import LayerController
from .spawn import spawn_detached

logger = logging.getLogger("keybow.actions")

_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "super": "logo",
    "meta": "logo",
    "win": "logo",
    "logo": "logo",
}

_KEYNAME_ALIASES = {
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": "space",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "delete": "Delete",
    "del": "Delete",
    "backspace": "BackSpace",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
}


class ActionContext:
    def __init__(self, config_store: ConfigStore, layers: LayerController, key_index: int):
        self.config_store = config_store
        self.layers = layers
        self.key_index = key_index


def dispatch_actions(action_list: list[Action], ctx: ActionContext, _macro_guard: frozenset[str] = frozenset()) -> None:
    for action in action_list:
        try:
            _execute_one(action, ctx, _macro_guard)
        except Exception:
            logger.exception("action %r failed", action)


def _execute_one(action: Action, ctx: ActionContext, macro_guard: frozenset[str]) -> None:
    if isinstance(action, OpenUrlAction):
        spawn_detached(["xdg-open", action.url])
    elif isinstance(action, LaunchAppAction):
        apps.launch_app(action.desktop_id)
    elif isinstance(action, ExecAction):
        spawn_detached(["/bin/sh", "-c", action.command])
    elif isinstance(action, KeySequenceAction):
        _run_key_sequence(action)
    elif isinstance(action, LayerSwitchAction):
        if action.mode == "toggle":
            ctx.layers.toggle(action.target)
        else:
            # Momentary needs a press/release pair, not a single fire-and-
            # forget action, so input.py handles it directly when a key's
            # `hold` list is *only* this action. Mixed into a longer list
            # like this it can't be given a matching release, so it's a no-op.
            logger.warning(
                "layer_switch mode=momentary only works as the sole action "
                "in a key's `hold` list; ignoring it here (key %d)",
                ctx.key_index,
            )
    elif isinstance(action, MacroAction):
        if action.id in macro_guard:
            logger.warning("macro %r references itself, skipping to avoid infinite loop", action.id)
            return
        macro = ctx.config_store.get().macros.get(action.id)
        if macro is None:
            logger.warning("macro %r not found", action.id)
            return
        dispatch_actions(macro.steps, ctx, macro_guard | {action.id})
    else:
        logger.warning("unknown action type: %r", action)


def _run_key_sequence(action: KeySequenceAction) -> None:
    for step in action.steps:
        if isinstance(step, TextStep):
            subprocess.run(["wtype", step.value], check=False)
        elif isinstance(step, DelayStep):
            time.sleep(max(0, step.ms) / 1000)
        elif isinstance(step, HotkeyStep):
            _wtype_hotkey(step.keys)


def _wtype_hotkey(keys: list[str]) -> None:
    if not keys:
        return
    *modifiers, main_key = keys
    mods = [_MODIFIER_ALIASES.get(m.lower(), m.lower()) for m in modifiers]
    key = _KEYNAME_ALIASES.get(main_key.lower(), main_key)
    args: list[str] = ["wtype"]
    for m in mods:
        args += ["-M", m]
    args += ["-k", key]
    for m in reversed(mods):
        args += ["-m", m]
    subprocess.run(args, check=False)
