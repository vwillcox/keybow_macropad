"""Discovers installed .desktop entries for the web UI's "launch app" picker,
and launches them. Reuses the standard XDG desktop-entry format rather than
inventing a separate app list.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .spawn import spawn_detached

APP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
]

# Desktop-entry "field codes" (%f, %F, %u, %U, %i, %c, %k, ...) are filled in
# by the launcher that invoked the app with a document/file; we're launching
# with no target, so they're simply dropped.
_FIELD_CODE_RE = re.compile(r"%[fFuUick%]")


@dataclass
class AppEntry:
    desktop_id: str
    name: str
    exec_cmd: str
    icon: str = ""


def _parse_desktop_file(path: Path) -> AppEntry | None:
    name = ""
    exec_cmd = ""
    icon = ""
    no_display = False
    hidden = False
    is_application = False
    try:
        in_desktop_entry_section = False
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                in_desktop_entry_section = line == "[Desktop Entry]"
                continue
            if not in_desktop_entry_section or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "Name" and not name:
                name = value
            elif key == "Exec":
                exec_cmd = value
            elif key == "Icon":
                icon = value
            elif key == "NoDisplay":
                no_display = value.lower() == "true"
            elif key == "Hidden":
                hidden = value.lower() == "true"
            elif key == "Type":
                is_application = value == "Application"
    except OSError:
        return None

    if not is_application or no_display or hidden or not exec_cmd or not name:
        return None
    return AppEntry(desktop_id=path.name, name=name, exec_cmd=exec_cmd, icon=icon)


def list_apps() -> list[AppEntry]:
    seen_ids: set[str] = set()
    apps: list[AppEntry] = []
    for app_dir in APP_DIRS:
        if not app_dir.is_dir():
            continue
        for desktop_file in sorted(app_dir.glob("*.desktop")):
            if desktop_file.name in seen_ids:
                continue
            entry = _parse_desktop_file(desktop_file)
            if entry is None:
                continue
            seen_ids.add(desktop_file.name)
            apps.append(entry)
    apps.sort(key=lambda a: a.name.lower())
    return apps


def find_app(desktop_id: str) -> AppEntry | None:
    for app_dir in APP_DIRS:
        candidate = app_dir / desktop_id
        if candidate.is_file():
            return _parse_desktop_file(candidate)
    return None


def launch_app(desktop_id: str) -> None:
    app = find_app(desktop_id)
    if app is None:
        raise FileNotFoundError(f"no installed app with desktop id {desktop_id!r}")
    cmd = _FIELD_CODE_RE.sub("", app.exec_cmd)
    args = shlex.split(cmd)
    if not args:
        raise ValueError(f"{desktop_id} has an empty Exec= line")
    spawn_detached(args)
