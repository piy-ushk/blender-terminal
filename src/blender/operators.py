"""
Blender Interactive Terminal — Operators

All Blender operators for the terminal. Operators are the only
safe way to interact with bpy from user-initiated actions.

Operators defined here:
  BAT_OT_open_terminal    — create session, register draw handler
  BAT_OT_close_terminal   — destroy session, unregister draw handler
  BAT_OT_kill_process     — send SIGKILL to active process
  BAT_OT_clear_terminal   — clear screen + scrollback
  BAT_OT_restart_session  — kill + start fresh session
  BAT_OT_input_modal      — modal operator: captures all keystrokes


THREADING RULES:
  - All bpy access is in the main thread (operators, modal, timer).
  - Background threads only touch OutputQueue and terminal backend.
  - Never call bpy from unix_pty.py or windows_pty.py reader threads.
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Set

import bpy
from bpy.props import StringProperty

from ..core.log import get_logger
from ..process.discovery import find_executable, get_default_shell

log = get_logger("blender.operators")

# ─── Key → bytes translation table ───────────────────────────────────────────
# Maps Blender event.type strings to the byte sequences sent to the PTY.

_KEY_TO_BYTES = {
    # Navigation / control
    "RET":           b"\r",
    "NUMPAD_ENTER":  b"\r",
    "TAB":           b"\t",
    "BACK_SPACE":    b"\x7f",
    "DEL":           b"\x1b[3~",
    "ESC":           b"\x1b",
    # Arrows
    "UP_ARROW":      b"\x1b[A",
    "DOWN_ARROW":    b"\x1b[B",
    "RIGHT_ARROW":   b"\x1b[C",
    "LEFT_ARROW":    b"\x1b[D",
    # Home / End / Page
    "HOME":          b"\x1b[H",
    "END":           b"\x1b[F",
    "PAGE_UP":       b"\x1b[5~",
    "PAGE_DOWN":     b"\x1b[6~",
}

# Keys that should trigger scroll (not sent to PTY)
_SCROLL_UP_KEYS: Set[str] = {"WHEELUPMOUSE", "TRACKPADPAN"}
_SCROLL_DOWN_KEYS: Set[str] = {"WHEELDOWNMOUSE"}


def _event_to_bytes(event) -> Optional[bytes]:
    """
    Convert a Blender keyboard event to the bytes to write to the PTY.
    Returns None if the event should be ignored.
    """
    key = event.type

    # Ctrl+C → SIGINT (Check explicitly for Ctrl, not Cmd/OSKey on Mac)
    if key == "C" and event.ctrl and not event.shift and not event.alt and not event.oskey:
        return b"\x03"
    # Ctrl+D → EOF
    if key == "D" and event.ctrl and not event.shift and not event.alt and not event.oskey:
        return b"\x04"
    # Ctrl+L → clear screen
    if key == "L" and event.ctrl and not event.shift and not event.alt and not event.oskey:
        return b"\x0c"
    # Ctrl+Z → suspend
    if key == "Z" and event.ctrl and not event.shift and not event.alt and not event.oskey:
        return b"\x1a"
    # Ctrl+A → beginning of line
    if key == "A" and event.ctrl and not event.shift and not event.alt:
        return b"\x01"
    # Ctrl+E → end of line
    if key == "E" and event.ctrl and not event.shift and not event.alt:
        return b"\x05"
    # Ctrl+K → kill to end of line
    if key == "K" and event.ctrl and not event.shift and not event.alt:
        return b"\x0b"
    # Ctrl+U → kill to beginning of line
    if key == "U" and event.ctrl and not event.shift and not event.alt:
        return b"\x15"

    if key in _KEY_TO_BYTES:
        return _KEY_TO_BYTES[key]

    # Printable character via event.unicode
    if event.unicode and not event.ctrl and not event.alt and not event.oskey:
        char = event.unicode
        if char:
            return char.encode("utf-8")

    return None


# ─── BAT_OT_open_terminal ─────────────────────────────────────────────────────

class BAT_OT_open_terminal(bpy.types.Operator):
    """Open the Blender Interactive Terminal in this area"""
    bl_idname = "bat.open_terminal"
    bl_label = "Open Terminal"
    bl_description = "Open an interactive terminal panel in this Text Editor area"

    initial_cmd: StringProperty(
        name="Initial Command",
        description="Command to run automatically on open (blank = default shell)",
        default="",
    )  # type: ignore

    def invoke(self, context: bpy.types.Context, event):
        return self.execute(context)

    def execute(self, context: bpy.types.Context):
        from ..terminal.manager import ensure_manager
        from ..core.events import register_pump_timer
        from ..ui.terminal_draw import register_draw_handler

        wm = context.window_manager

        # If already open, just focus
        if wm.bat_terminal_active and wm.bat_session_id:
            self.report({"INFO"}, "Terminal already open")
            return {"FINISHED"}

        # Determine terminal dimensions from the current area
        cols, rows = _estimate_term_size(context)

        # Create session
        manager = ensure_manager()
        cwd = _get_blend_dir(context)
        session = manager.create_session(cols=cols, rows=rows, cwd=cwd)

        # Determine command to launch
        cmd_str = self.initial_cmd.strip()
        if cmd_str:
            cmd = cmd_str.split()
        else:
            shell = get_default_shell()
            cmd = [shell]

        ok = session.start(cmd)

        # Register draw handler + timer
        register_draw_handler()
        register_pump_timer()

        wm.bat_terminal_active = True
        wm.bat_session_id = session.session_id
        wm.bat_input_line = ""

        # Launch the modal input operator
        bpy.ops.bat.input_modal("INVOKE_DEFAULT")

        if ok:
            self.report({"INFO"}, f"Terminal opened: {' '.join(cmd)}")
        else:
            self.report({"WARNING"}, "Terminal opened but process failed to start")

        context.area.tag_redraw()
        return {"FINISHED"}


# ─── BAT_OT_close_terminal ────────────────────────────────────────────────────

class BAT_OT_close_terminal(bpy.types.Operator):
    """Close the terminal and kill the running process"""
    bl_idname = "bat.close_terminal"
    bl_label = "Close Terminal"
    bl_description = "Close the terminal and terminate the running process"

    def execute(self, context: bpy.types.Context):
        from ..terminal.manager import get_manager, destroy_manager
        from ..core.events import unregister_pump_timer
        from ..ui.terminal_draw import unregister_draw_handler

        wm = context.window_manager
        manager = get_manager()
        if manager:
            manager.destroy_all()

        unregister_draw_handler()
        # Keep the pump timer alive — it handles "no sessions" gracefully.
        # unregister only on full addon disable.

        wm.bat_terminal_active = False
        wm.bat_session_id = ""
        wm.bat_input_active = False
        wm.bat_input_line = ""

        context.area.tag_redraw()
        self.report({"INFO"}, "Terminal closed")
        return {"FINISHED"}


# ─── BAT_OT_kill_process ─────────────────────────────────────────────────────

class BAT_OT_kill_process(bpy.types.Operator):
    """Send SIGKILL to the running process"""
    bl_idname = "bat.kill_process"
    bl_label = "Kill Process"
    bl_description = "Forcefully terminate the currently running process (SIGKILL)"

    def execute(self, context: bpy.types.Context):
        from ..terminal.manager import get_manager
        manager = get_manager()
        if manager:
            session = manager.get_active()
            if session:
                session.kill()
                context.area.tag_redraw()
                self.report({"INFO"}, "Process killed")
                return {"FINISHED"}
        self.report({"WARNING"}, "No active process to kill")
        return {"CANCELLED"}


# ─── BAT_OT_clear_terminal ────────────────────────────────────────────────────

class BAT_OT_clear_terminal(bpy.types.Operator):
    """Clear the terminal screen and scrollback buffer"""
    bl_idname = "bat.clear_terminal"
    bl_label = "Clear Terminal"
    bl_description = "Clear the terminal screen and all scrollback history"

    def execute(self, context: bpy.types.Context):
        from ..terminal.manager import get_manager
        manager = get_manager()
        if manager:
            session = manager.get_active()
            if session:
                session.screen.clear()
                context.area.tag_redraw()
                return {"FINISHED"}
        return {"CANCELLED"}


# ─── BAT_OT_restart_session ───────────────────────────────────────────────────

class BAT_OT_restart_session(bpy.types.Operator):
    """Restart the terminal session with the same command"""
    bl_idname = "bat.restart_session"
    bl_label = "Restart Session"
    bl_description = "Kill the current process and start a new session"

    def execute(self, context: bpy.types.Context):
        from ..terminal.manager import get_manager
        manager = get_manager()
        if not manager:
            return {"CANCELLED"}
        session = manager.get_active()
        if session:
            cmd = list(session.cmd)
            cwd = session.cwd
            session.kill()
            session.screen.clear()
            ok = session.start(cmd if cmd else None)
            context.area.tag_redraw()
            if ok:
                self.report({"INFO"}, f"Session restarted: {' '.join(cmd)}")
            else:
                self.report({"WARNING"}, "Restart failed")
        return {"FINISHED"}


# ─── BAT_OT_input_modal ──────────────────────────────────────────────────────

class BAT_OT_input_modal(bpy.types.Operator):
    """
    Modal operator that captures keyboard input and routes it to the PTY.

    Lifecycle:
      - Invoked by BAT_OT_open_terminal.
      - Runs while bat_terminal_active is True.
      - Terminated when terminal is closed or ESC is pressed (with confirm).
      - Captures ALL key events in TEXT_EDITOR areas; passes through otherwise.
    """
    bl_idname = "bat.input_modal"
    bl_label = "Terminal Input Modal"
    bl_options = {"INTERNAL"}

    _is_selecting: bool = False

    def invoke(self, context: bpy.types.Context, event):
        # Flag it as active and focused
        context.window_manager.bat_input_active = True
        context.window_manager.bat_terminal_active = True
        context.window_manager.bat_terminal_focused = True
        self._is_selecting = False
        context.window_manager.modal_handler_add(self)
        log.debug("Input modal started")
        return {"RUNNING_MODAL"}

    def modal(self, context: bpy.types.Context, event):
        wm = context.window_manager
        if not getattr(wm, "bat_terminal_active", False):
            return {"FINISHED"}

        # Track terminal focus globally based on mouse clicks
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            is_over_term = bool(context.area and context.area.type == "TEXT_EDITOR")
            wm.bat_terminal_focused = is_over_term

        # Only capture input when the cursor is over a TEXT_EDITOR area
        if not context.area or context.area.type != "TEXT_EDITOR":
            return {"PASS_THROUGH"}

        from ..terminal.manager import get_manager
        manager = get_manager()
        if not manager:
            return {"PASS_THROUGH"}
        session = manager.get_active()
        if not session:
            return {"PASS_THROUGH"}

        # ── Mouse Interaction (Scrolling & Selection) ─────────────────────
        if context.region and context.region.type == "WINDOW":
            if event.type in _SCROLL_UP_KEYS:
                if event.type == "TRACKPADPAN":
                    delta = event.mouse_y - event.mouse_prev_y
                    session.screen.trackpad_scroll(delta)
                else:
                    session.screen.scroll_up(3)
                context.area.tag_redraw()
                return {"PASS_THROUGH"}

            if event.type in _SCROLL_DOWN_KEYS:
                session.screen.scroll_down(3)
                context.area.tag_redraw()
                return {"PASS_THROUGH"}

            # Text selection
            if event.type == "LEFTMOUSE":
                if event.value == "PRESS":
                    self._is_selecting = True
                    col, row = _mouse_to_col_row(context, event, session)
                    session.screen.selection_start = (col, row)
                    session.screen.selection_end = (col, row)
                    context.area.tag_redraw()
                    return {"PASS_THROUGH"}
                elif event.value == "RELEASE":
                    if self._is_selecting:
                        self._is_selecting = False
                        col, row = _mouse_to_col_row(context, event, session)
                        session.screen.selection_end = (col, row)
                        context.area.tag_redraw()
                    return {"PASS_THROUGH"}

            if event.type == "MOUSEMOVE" and self._is_selecting:
                col, row = _mouse_to_col_row(context, event, session)
                session.screen.selection_end = (col, row)
                context.area.tag_redraw()
                return {"PASS_THROUGH"}

        # Only act on PRESS events for keyboard keys
        if event.value not in {"PRESS"}:
            return {"PASS_THROUGH"}

        # ── Copy / Paste ──────────────────────────────────────────────────
        is_mac = sys.platform == "darwin"
        
        # COPY: Cmd+C (Mac) or Ctrl+Shift+C (Win/Linux)
        is_copy = (event.type == "C" and 
                   ((is_mac and event.oskey) or 
                    (not is_mac and event.ctrl and event.shift)))
        if is_copy:
            text = session.screen.get_selection_text()
            if text:
                context.window_manager.clipboard = text
                self.report({"INFO"}, "Terminal selection copied to clipboard")
            else:
                # Fallback MVP: Copy the entire visible screen to clipboard
                lines = session.screen.get_display_lines()
                text = "\n".join("".join(char.char for char in line).rstrip() for line in lines)
                text = text.rstrip() + "\n"
                context.window_manager.clipboard = text
                self.report({"INFO"}, "Terminal screen copied to clipboard")
            return {"RUNNING_MODAL"}

        # PASTE: Cmd+V (Mac) or Ctrl+Shift+V (Win/Linux)
        is_paste = (event.type == "V" and 
                    ((is_mac and event.oskey) or 
                     (not is_mac and event.ctrl and event.shift)))
        if is_paste:
            text = context.window_manager.clipboard
            if text:
                # Send text directly, converting newlines to \r
                session.send_input(text.replace("\n", "\r").encode("utf-8"))
            return {"RUNNING_MODAL"}

        # ── ESC — confirm close (don't accidentally close with ESC) ───────
        if event.type == "ESC" and not event.ctrl:
            # Send ESC to the process (e.g., vim needs it)
            session.send_input(b"\x1b")
            return {"RUNNING_MODAL"}

        # ── Regular key → PTY (Replaces local history) ─────────────────────
        if getattr(wm, "bat_terminal_focused", True):
            data = _event_to_bytes(event)
            if data is not None:
                session.send_input(data)
                # Scroll back to bottom on any input
                session.screen.scroll_to_bottom()
                return {"RUNNING_MODAL"}

        # Unknown key or not focused — pass through to Blender
        return {"PASS_THROUGH"}

    def cancel(self, context: bpy.types.Context):
        self._finish(context)

    def _finish(self, context: bpy.types.Context):
        context.window_manager.bat_input_active = False
        log.debug("Input modal finished")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mouse_to_col_row(context, event, session):
    """Convert absolute screen coordinates to terminal (col, row)."""
    try:
        prefs = context.preferences.addons[__package__.split(".")[0]].preferences
        font_size = prefs.font_size
    except Exception:
        font_size = 13
        
    char_w = font_size * 0.60
    char_h = font_size * 1.40
    
    pad_x = 10
    pad_y = 10
    
    x = event.mouse_region_x
    y = event.mouse_region_y
    region_h = context.region.height
    
    row = int((region_h - pad_y - y) / char_h)
    col = int((x - pad_x) / char_w)
    
    # Include scroll offset so the selection maps to the visible line
    row = max(0, min(row, session.screen.rows - 1))
    col = max(0, min(col, session.screen.cols - 1))
    
    return col, row


def _estimate_term_size(context: bpy.types.Context):
    """
    Estimate a reasonable cols×rows from the current area pixel size.
    Uses a monospace character cell approximation.
    """
    try:
        prefs = context.preferences.addons[
            __package__.split(".")[0]
        ].preferences
        font_size = prefs.font_size
    except Exception:
        font_size = 13

    char_w = font_size * 0.60   # approximate monospace cell width
    char_h = font_size * 1.40   # approximate line height

    area = context.area
    if area:
        # Find the WINDOW region
        for region in area.regions:
            if region.type == "WINDOW":
                cols = max(40, int(region.width / char_w))
                rows = max(10, int(region.height / char_h))
                return cols, rows

    return 120, 40


def _get_blend_dir(context: bpy.types.Context) -> str:
    """Return the directory of the current .blend file, or home dir."""
    blend_path = bpy.data.filepath
    if blend_path:
        return str(Path(blend_path).parent)
    return str(Path.home())


# ─── BAT_OT_update_extension ──────────────────────────────────────────────────

class BAT_OT_update_extension(bpy.types.Operator):
    """Update Blender Interactive Terminal from GitHub"""
    bl_idname = "bat.update_extension"
    bl_label = "Update Terminal"
    bl_description = "Download and install the latest OTA update from GitHub"

    def execute(self, context: bpy.types.Context):
        import urllib.request
        import zipfile
        import tempfile
        import shutil

        url = "https://github.com/piy-ushk/blender-terminal/archive/refs/heads/main.zip"
        pkg_path = Path(__file__).parent.parent.parent

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = Path(tmpdir) / "update.zip"
                urllib.request.urlretrieve(url, zip_path)
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(tmpdir)
                    
                src_dir = Path(tmpdir) / "blender-terminal-main"
                
                # Copy files over, overwriting existing ones
                for root, _, files in os.walk(src_dir):
                    rel_path = os.path.relpath(root, src_dir)
                    dst_dir = pkg_path / rel_path
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    for f in files:
                        shutil.copy2(os.path.join(root, f), dst_dir / f)

            self.report({"INFO"}, "Update complete! Please RESTART Blender.")
            
        except Exception as e:
            log.error("Update failed: %s", e)
            self.report({"ERROR"}, f"Update failed: {e}")
            
        return {"FINISHED"}


# ─── BAT_OT_toggle_terminal_window ────────────────────────────────────────────

class BAT_OT_toggle_terminal_window(bpy.types.Operator):
    """Open Interactive Terminal in a new floating window"""
    bl_idname = "bat.toggle_terminal_window"
    bl_label = "Interactive Terminal Window"
    
    def invoke(self, context: bpy.types.Context, event):
        return self.execute(context)

    def execute(self, context: bpy.types.Context):
        old_windows = set(context.window_manager.windows)
        
        # Create a new default window safely
        bpy.ops.wm.window_new('INVOKE_DEFAULT')
        
        # Find the new window
        new_windows = set(context.window_manager.windows) - old_windows
        if not new_windows:
            self.report({"WARNING"}, "Failed to create new window")
            return {"CANCELLED"}
            
        win = new_windows.pop()
        
        # Change area to TEXT_EDITOR
        area = win.screen.areas[0]
        area.type = "TEXT_EDITOR"
        
        # Open terminal in that area
        with context.temp_override(window=win, screen=win.screen, area=area, region=area.regions[0]):
            bpy.ops.bat.open_terminal('INVOKE_DEFAULT')
        
        return {"FINISHED"}

# ─── BAT_OT_create_workspace ──────────────────────────────────────────────────

class BAT_OT_create_workspace(bpy.types.Operator):
    """Create or switch to the Interactive Terminal workspace"""
    bl_idname = "bat.create_workspace"
    bl_label = "Interactive Terminal Workspace"
    
    def execute(self, context: bpy.types.Context):
        ws_name = "Interactive Terminal"
        if ws_name not in bpy.data.workspaces:
            # Create a new workspace by duplicating the current one
            bpy.ops.workspace.add()
            ws = context.window.workspace
            ws.name = ws_name
            
            # Find the largest area and make it a TEXT_EDITOR
            screen = ws.screens[0]
            if screen.areas:
                largest = max(screen.areas, key=lambda a: a.width * a.height)
                largest.type = "TEXT_EDITOR"
                
                # We can't safely call open_terminal on a background screen if it expects to draw immediately,
                # but since we just switched to it, we can use the current context's new area.
                # Actually, the workspace switch might be deferred. 
                # Let's tag the area to open a terminal.
                with context.temp_override(window=context.window, screen=screen, area=largest, region=largest.regions[0]):
                    bpy.ops.bat.open_terminal('INVOKE_DEFAULT')
        else:
            # Just switch to it
            context.window.workspace = bpy.data.workspaces[ws_name]
            
        return {"FINISHED"}


class BAT_OT_toggle_fullscreen(bpy.types.Operator):
    """Toggle fullscreen view for the terminal"""
    bl_idname = "bat.toggle_fullscreen"
    bl_label = "Toggle Fullscreen"

    def execute(self, context: bpy.types.Context):
        # screen_full_area toggles the maximization of the area in the context
        bpy.ops.screen.screen_full_area()
        return {"FINISHED"}


# ─── Registration ─────────────────────────────────────────────────────────────

CLASSES = [
    BAT_OT_open_terminal,
    BAT_OT_close_terminal,
    BAT_OT_kill_process,
    BAT_OT_clear_terminal,
    BAT_OT_restart_session,

    BAT_OT_update_extension,
    BAT_OT_input_modal,
    BAT_OT_toggle_terminal_window,
    BAT_OT_create_workspace,
    BAT_OT_toggle_fullscreen,
]
