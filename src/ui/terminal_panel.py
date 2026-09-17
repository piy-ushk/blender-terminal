"""
Blender Interactive Terminal — Sidebar Panel

Renders the control panel in the TEXT_EDITOR N-panel sidebar.
This is the user's primary interface for opening/closing the terminal,
launching tools, and adjusting settings.
"""

import bpy
from bpy.types import Menu, Panel

from ..core.log import get_logger

log = get_logger("ui.terminal_menu")


class BAT_MT_terminal_menu(Menu):
    bl_label = "Interactive Terminal"
    bl_idname = "BAT_MT_terminal_menu"

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        wm = context.window_manager
        active = getattr(wm, "bat_terminal_active", False)

        if not active:
            layout.operator("bat.open_terminal", text="Open Terminal", icon="CONSOLE")
        else:
            layout.operator("bat.close_terminal", text="Close Terminal", icon="PANEL_CLOSE")
            layout.operator("bat.toggle_fullscreen", text="Toggle Fullscreen", icon="FULLSCREEN_ENTER")
            layout.separator()
            layout.operator("bat.restart_session", text="Restart Process", icon="FILE_REFRESH")
            layout.operator("bat.clear_terminal", text="Clear Screen", icon="TRASH")
            layout.operator("bat.kill_process", text="Kill Process", icon="X")
        
        layout.separator()
        layout.operator("bat.update_extension", text="Sync Updates", icon="FILE_REFRESH")
        
        layout.separator()
        layout.menu("BAT_MT_terminal_usage", text="Usage", icon="QUESTION")
        layout.popover("BAT_PT_terminal_settings", text="Settings")


class BAT_MT_terminal_usage(Menu):
    bl_label = "Terminal Usage"
    bl_idname = "BAT_MT_terminal_usage"

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        layout.label(text="Click inside the terminal to focus and type.", icon="MOUSE_LMB")
        layout.separator()
        layout.label(text="Cmd+T / Ctrl+T — Toggle floating window")
        layout.label(text="Ctrl+C — Interrupt process")
        layout.label(text="Ctrl+D — Send EOF")
        layout.label(text="Ctrl+L — Clear screen")
        layout.label(text="↑ / ↓ — Command history")
        layout.label(text="Scroll — View scrollback")


class BAT_PT_terminal_settings(Panel):
    bl_label = "Terminal Settings"
    bl_idname = "BAT_PT_terminal_settings"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "HEADER"

    def draw(self, context: bpy.types.Context):
        layout = self.layout
        try:
            from ..blender.preferences import get_prefs
            prefs = get_prefs(context)
            if prefs:
                col = layout.column(align=True)
                col.prop(prefs, "font_size")
                col.prop(prefs, "theme")
                
                # Expose Keymap
                kc = context.window_manager.keyconfigs.user
                if kc:
                    km = kc.keymaps.get("Window")
                    if km:
                        kmi = km.keymap_items.get("bat.toggle_terminal_window")
                        if kmi:
                            col.separator()
                            col.context_pointer_set("keymap", km)
                            col.prop(kmi, "type", text="Hotkey", full_event=True)
            else:
                layout.label(text="(Preferences not loaded)", icon="ERROR")
        except Exception as exc:
            layout.label(text=f"(Error: {exc})", icon="INFO")


def draw_header_menu(self, context: bpy.types.Context):
    # Appended to TEXT_HT_header
    self.layout.separator()
    self.layout.menu("BAT_MT_terminal_menu", text="Interactive Terminal", icon="CONSOLE")


CLASSES = [BAT_MT_terminal_menu, BAT_MT_terminal_usage, BAT_PT_terminal_settings]
