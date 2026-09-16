"""
Blender Agent Terminal — Extension Entry Point
==============================================
An integrated, interactive terminal inside Blender's UI.

Launch Claude Code, Gemini CLI, Codex, npm, git, bash and any other
CLI tool in a terminal panel embedded right inside Blender — while your
3D viewport stays fully responsive.

SPDX-License-Identifier: GPL-3.0-or-later
"""

# ─── Module reload support ─────────────────────────────────────────────────────
# Blender may hot-reload addon modules. We detect this and reload sub-modules
# so that code changes take effect without a Blender restart during development.

import importlib
import sys


def _pkg_name() -> str:
    return __name__


_SUBMODULE_ORDER = [
    "src",
    "src.core",
    "src.core.log",
    "src.core.events",
    "src.core.ipc",
    "src.process",
    "src.process.discovery",
    "src.terminal",
    "src.terminal.backend",
    "src.terminal.screen",
    "src.terminal.unix_pty",
    "src.terminal.windows_pty",
    "src.terminal.session",
    "src.terminal.manager",
    "src.blender",
    "src.blender.props",
    "src.blender.preferences",
    "src.blender.operators",
    "src.ui",
    "src.ui.terminal_draw",
    "src.ui.terminal_panel",
]


def _reload_all() -> None:
    pkg = _pkg_name()
    for rel in _SUBMODULE_ORDER:
        full = f"{pkg}.{rel}"
        if full in sys.modules:
            try:
                importlib.reload(sys.modules[full])
            except Exception as exc:
                print(f"[BAT] reload warning {full}: {exc}")


# First import vs. reload detection
if "src" in sys.modules.get(_pkg_name() + ".src", object).__dict__ if _pkg_name() + ".src" in sys.modules else {}:
    _reload_all()


# ─── Keymaps & Menus ──────────────────────────────────────────────────────────

import bpy

_addon_keymaps = []

def draw_window_menu(self, context):
    layout = self.layout
    layout.separator()
    layout.operator("bat.toggle_terminal_window", icon='CONSOLE')
    layout.operator("bat.create_workspace", icon='WORKSPACE')

def register_keymaps():
    wm = bpy.context.window_manager
    if wm.keyconfigs.addon:
        km = wm.keyconfigs.addon.keymaps.new(name='Window', space_type='EMPTY')
        # Default hotkey: Cmd+T (Mac) / Win+T (Windows)
        kmi = km.keymap_items.new('bat.toggle_terminal_window', 'T', 'PRESS', oskey=True)
        _addon_keymaps.append((km, kmi))

def unregister_keymaps():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()


def register() -> None:
    # Import here so reloads work correctly
    from .src.core.log import get_logger
    log = get_logger("__init__")

    from .src.blender.props import register_props
    from .src.blender.preferences import CLASSES as PREF_CLASSES
    from .src.blender.operators import CLASSES as OP_CLASSES
    from .src.ui.terminal_panel import CLASSES as PANEL_CLASSES
    from .src.core.events import register_pump_timer

    all_classes = PREF_CLASSES + OP_CLASSES + PANEL_CLASSES

    log.info("Registering Blender Agent Terminal")

    for cls in all_classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            # Already registered (hot-reload) — unregister first
            try:
                bpy.utils.unregister_class(cls)
                bpy.utils.register_class(cls)
            except Exception as inner:
                log.error("Could not register %s: %s", cls.__name__, inner)

    register_props()
    register_pump_timer()
    register_keymaps()
    bpy.types.TOPBAR_MT_window.append(draw_window_menu)

    log.info("Blender Agent Terminal ready")


def unregister() -> None:
    from .src.core.log import get_logger
    log = get_logger("__init__")

    from .src.blender.preferences import CLASSES as PREF_CLASSES
    from .src.blender.operators import CLASSES as OP_CLASSES
    from .src.ui.terminal_panel import CLASSES as PANEL_CLASSES
    from .src.core.events import unregister_pump_timer
    from .src.ui.terminal_draw import unregister_draw_handler
    from .src.terminal.manager import destroy_manager
    from .src.blender.props import unregister_props
    from .src.core.ipc import stop_ipc_server

    log.info("Unregistering Blender Agent Terminal")

    unregister_pump_timer()
    unregister_draw_handler()
    destroy_manager()
    stop_ipc_server()
    unregister_props()
    unregister_keymaps()
    bpy.types.TOPBAR_MT_window.remove(draw_window_menu)

    all_classes = PREF_CLASSES + OP_CLASSES + PANEL_CLASSES
    for cls in reversed(all_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            log.debug("Unregister %s: %s", cls.__name__, exc)

    log.info("Blender Agent Terminal unregistered")
