"""
Blender Agent Terminal — Sidebar Panel

Renders the control panel in the TEXT_EDITOR N-panel sidebar.
This is the user's primary interface for opening/closing the terminal,
launching agents, and adjusting settings.
"""

import bpy
from bpy.types import Panel

from ..core.log import get_logger
from ..process.discovery import detect_agents, get_agent_label

log = get_logger("ui.terminal_panel")

# Cache agent detection (re-probe every 60s via a simple counter)
_agent_cache: dict = {}
_agent_cache_frame: int = -9999
_AGENT_CACHE_FRAMES = 300  # ~10 seconds at 30fps pumps


def _get_agents(context: bpy.types.Context) -> dict:
    global _agent_cache, _agent_cache_frame
    current = context.scene.frame_current if context.scene else 0
    if abs(current - _agent_cache_frame) > _AGENT_CACHE_FRAMES or not _agent_cache:
        _agent_cache = detect_agents()
        _agent_cache_frame = current
    return _agent_cache


class BAT_PT_TerminalPanel(Panel):
    """Blender Agent Terminal — sidebar control panel."""

    bl_label = "Agent Terminal"
    bl_idname = "BAT_PT_terminal_panel"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Terminal"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        wm = context.window_manager
        active = getattr(wm, "bat_terminal_active", False)

        # ── Main open/close button ─────────────────────────────────────────
        if not active:
            row = layout.row()
            row.scale_y = 1.6
            row.operator(
                "bat.open_terminal",
                text="▶  Open Terminal",
                icon="CONSOLE",
            )
        else:
            # Controls while terminal is open
            col = layout.column(align=True)
            row = col.row(align=True)
            row.scale_y = 1.2
            row.operator("bat.kill_process",    text="Kill",    icon="X")
            row.operator("bat.restart_session", text="Restart", icon="FILE_REFRESH")
            row.operator("bat.clear_terminal",  text="Clear",   icon="TRASH")
            row.operator("bat.close_terminal",  text="Close",   icon="PANEL_CLOSE")

            # Session status
            from ..terminal.manager import get_manager
            manager = get_manager()
            if manager:
                session = manager.get_active()
                if session:
                    layout.separator(factor=0.5)
                    box = layout.box()
                    col2 = box.column(align=True)
                    col2.scale_y = 0.8
                    col2.label(text=f"Status: {session.status_label}", icon="INFO")
                    col2.label(text=f"Cmd: {' '.join(session.cmd)}", icon="RIGHTARROW_THIN")
                    col2.label(text=f"CWD: {_short_path(session.cwd)}", icon="FILE_FOLDER")

        layout.separator()

        # ── Quick-launch agent buttons ─────────────────────────────────────
        layout.label(text="Quick Launch:", icon="TOOL_SETTINGS")
        agents = _get_agents(context)

        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for agent_key, agent_path in agents.items():
            btn = grid.column()
            btn.enabled = bool(agent_path)
            op = btn.operator(
                "bat.launch_agent",
                text=agent_key,
                icon="CONSOLE" if agent_path else "ERROR",
            )
            op.agent = agent_key

        layout.separator()

        # ── Settings shortcut ─────────────────────────────────────────────
        layout.label(text="Settings:", icon="PREFERENCES")
        try:
            from ..blender.preferences import get_prefs
            prefs = get_prefs(context)
            if prefs:
                col = layout.column(align=True)
                col.prop(prefs, "font_size")
                col.prop(prefs, "theme")
            else:
                layout.label(text="(Preferences not loaded)", icon="ERROR")
        except Exception as exc:
            layout.label(text=f"(Error: {exc})", icon="INFO")
            
        layout.separator()
        layout.operator("bat.update_extension", icon="FILE_REFRESH")


def _short_path(path: str, max_len: int = 28) -> str:
    if len(path) <= max_len:
        return path
    return "…" + path[-(max_len - 1):]


class BAT_PT_TerminalHelpPanel(Panel):
    """Help / usage instructions sub-panel."""

    bl_label = "Usage"
    bl_idname = "BAT_PT_terminal_help"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "Terminal"
    bl_options = {"DEFAULT_CLOSED"}
    bl_parent_id = "BAT_PT_terminal_panel"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.scale_y = 0.85

        col = layout.column(align=True)
        col.label(text="1. Switch an area to Text Editor", icon="RIGHTARROW_THIN")
        col.label(text="2. Open the N-panel sidebar (N key)", icon="RIGHTARROW_THIN")
        col.label(text="3. Click 'Open Terminal'", icon="RIGHTARROW_THIN")
        col.separator(factor=0.5)
        col.label(text="Keyboard shortcuts (in terminal area):")
        col.label(text="  Ctrl+C — interrupt process")
        col.label(text="  Ctrl+D — send EOF")
        col.label(text="  Ctrl+L — clear screen")
        col.label(text="  ↑ / ↓  — command history")
        col.label(text="  Scroll wheel — scrollback")
        col.label(text="  ESC — send escape to process")


CLASSES = [BAT_PT_TerminalPanel, BAT_PT_TerminalHelpPanel]
