"""A minimal StatusNotifierItem (the standard Linux tray icon protocol) plus
a DBusMenu, implemented directly over D-Bus with dbus-next — no GTK/
AppIndicator system packages needed. Confirmed on this machine that
Omarchy's Quickshell bar already owns `org.kde.StatusNotifierWatcher`, so a
spec-compliant item just shows up in it.

Menu: Open Configurator, a submenu to switch layers, Reload Config, Quit.
"""
from __future__ import annotations

import logging
from typing import Callable

from dbus_next import PropertyAccess, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property, method, signal

from .spawn import spawn_detached

logger = logging.getLogger("keybow.tray")

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"


class _Item(ServiceInterface):
    def __init__(self, on_activate: Callable[[], None]):
        super().__init__("org.kde.StatusNotifierItem")
        self._on_activate = on_activate
        self._title = "Keybow"

    @method()
    def Activate(self, x: "i", y: "i"):  # noqa: N802, F821
        self._on_activate()

    @method()
    def SecondaryActivate(self, x: "i", y: "i"):  # noqa: N802, F821
        self._on_activate()

    @method()
    def ContextMenu(self, x: "i", y: "i"):  # noqa: N802
        pass

    @method()
    def Scroll(self, delta: "i", orientation: "s"):  # noqa: N802, F821
        pass

    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":  # noqa: N802, F821
        return "ApplicationStatus"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":  # noqa: N802, F821
        return "keybow-daemon"

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":  # noqa: N802, F821
        return self._title

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":  # noqa: N802, F821
        return "Active"

    @dbus_property(access=PropertyAccess.READ)
    def WindowId(self) -> "i":  # noqa: N802, F821
        return 0

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":  # noqa: N802, F821
        return "input-keyboard"

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "s":  # noqa: N802, F821
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":  # noqa: N802, F821
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":  # noqa: N802, F821
        return MENU_PATH

    @signal()
    def NewTitle(self):  # noqa: N802
        pass

    @signal()
    def NewStatus(self) -> "s":  # noqa: N802, F821
        return "Active"

    def set_title(self, title: str) -> None:
        self._title = title
        self.NewTitle()


class _MenuItem:
    """One node in the menu tree. `action`, if set, runs on click."""

    def __init__(self, item_id: int, label: str | None = None, action=None, separator=False, children=None):
        self.id = item_id
        self.label = label
        self.action = action
        self.separator = separator
        self.children: list["_MenuItem"] = children or []

    def props(self) -> dict:
        if self.separator:
            return {"type": Variant("s", "separator")}
        return {
            "label": Variant("s", self.label or ""),
            "enabled": Variant("b", True),
            "visible": Variant("b", True),
            "children-display": Variant("s", "submenu") if self.children else Variant("s", ""),
        }

    def to_layout(self) -> Variant:
        children_variants = [c.to_layout() for c in self.children]
        return Variant("(ia{sv}av)", [self.id, self.props(), children_variants])


class _Menu(ServiceInterface):
    def __init__(self):
        super().__init__("com.canonical.dbusmenu")
        self._revision = 1
        self._next_id = 1
        self._by_id: dict[int, _MenuItem] = {}
        self._root = self._add(_MenuItem(0))

    def _add(self, item: _MenuItem) -> _MenuItem:
        self._by_id[item.id] = item
        return item

    def new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def rebuild(self, items: list[_MenuItem]) -> None:
        self._by_id = {0: self._root}
        self._root.children = items
        for item in items:
            self._register(item)
        self._revision += 1
        self.LayoutUpdated(self._revision, 0)

    def _register(self, item: _MenuItem) -> None:
        self._by_id[item.id] = item
        for child in item.children:
            self._register(child)

    @method()
    def GetLayout(self, parent_id: "i", recursion_depth: "i", property_names: "as") -> "u(ia{sv}av)":  # noqa: N802, F821
        node = self._by_id.get(parent_id, self._root)
        return [self._revision, node.to_layout().value]

    @method()
    def GetGroupProperties(self, ids: "ai", property_names: "as") -> "a(ia{sv})":  # noqa: N802, F821
        return [[i, self._by_id[i].props()] for i in ids if i in self._by_id]

    @method()
    def GetProperty(self, id: "i", name: "s") -> "v":  # noqa: N802, F821
        item = self._by_id.get(id)
        if item is None:
            return Variant("s", "")
        return item.props().get(name, Variant("s", ""))

    @method()
    def Event(self, id: "i", event_id: "s", data: "v", timestamp: "u"):  # noqa: N802, F821
        if event_id != "clicked":
            return
        item = self._by_id.get(id)
        if item and item.action:
            try:
                item.action()
            except Exception:
                logger.exception("menu action for item %d failed", id)

    @method()
    def AboutToShow(self, id: "i") -> "b":  # noqa: N802, F821
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> "u":  # noqa: N802, F821
        return 3

    @dbus_property(access=PropertyAccess.READ)
    def TextDirection(self) -> "s":  # noqa: N802, F821
        return "ltr"

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":  # noqa: N802, F821
        return "normal"

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "as":  # noqa: N802, F821
        return []

    @signal()
    def LayoutUpdated(self, revision: "u", parent: "i"):  # noqa: N802, F821
        pass

    @signal()
    def ItemsPropertiesUpdated(self):  # noqa: N802
        pass


class TrayIcon:
    def __init__(self, config_store, layer_controller, web_url: str):
        self._config_store = config_store
        self._layers = layer_controller
        self._web_url = web_url
        self._bus: MessageBus | None = None
        self._item: _Item | None = None
        self._menu: _Menu | None = None
        self._quit_requested = False

    async def start(self) -> None:
        self._bus = await MessageBus().connect()
        self._item = _Item(self._open_configurator)
        self._menu = _Menu()
        self._bus.export(ITEM_PATH, self._item)
        self._bus.export(MENU_PATH, self._menu)

        bus_name = f"org.kde.StatusNotifierItem-{__import__('os').getpid()}-1"
        await self._bus.request_name(bus_name)

        self._rebuild_menu()
        self._layers.on_change(lambda _layer_id: self._rebuild_menu())
        self._config_store.on_change(lambda _cfg: self._rebuild_menu())

        watcher = self._bus.get_proxy_object(
            "org.kde.StatusNotifierWatcher",
            "/StatusNotifierWatcher",
            await self._bus.introspect("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher"),
        ).get_interface("org.kde.StatusNotifierWatcher")
        await watcher.call_register_status_notifier_item(bus_name)
        logger.info("tray icon registered as %s", bus_name)

    def _open_configurator(self) -> None:
        spawn_detached(["xdg-open", self._web_url])

    def _rebuild_menu(self) -> None:
        if self._menu is None:
            return
        config = self._config_store.get()
        current = self._layers.current_id()

        layer_items = []
        for layer in config.layers:
            marker = "✓ " if layer.id == current else "   "
            layer_items.append(
                _MenuItem(self._menu.new_id(), f"{marker}{layer.name}", action=self._make_switch(layer.id))
            )

        items = [
            _MenuItem(self._menu.new_id(), "Open Configurator", action=self._open_configurator),
            _MenuItem(self._menu.new_id(), separator=True),
            _MenuItem(self._menu.new_id(), "Layer", children=layer_items),
            _MenuItem(self._menu.new_id(), separator=True),
            _MenuItem(self._menu.new_id(), "Reload Config", action=self._reload),
            _MenuItem(self._menu.new_id(), "Quit", action=self._quit),
        ]
        self._menu.rebuild(items)
        if self._item is not None:
            self._item.set_title(f"Keybow — {config.get_layer(current).name if config.get_layer(current) else current}")

    def _make_switch(self, layer_id: str):
        return lambda: self._layers.set_current(layer_id)

    def _reload(self) -> None:
        self._config_store.poll_for_external_changes()

    def _quit(self) -> None:
        self._quit_requested = True
        import signal as _signal
        import os
        os.kill(os.getpid(), _signal.SIGTERM)

    @property
    def quit_requested(self) -> bool:
        return self._quit_requested
