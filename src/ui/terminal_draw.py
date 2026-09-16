"""
Blender Agent Terminal — GPU + BLF Draw Handler

Renders the terminal screen buffer directly into the TEXT_EDITOR area's
WINDOW region using Blender's GPU and BLF (font) APIs.

Architecture:
  - draw_terminal() is registered via SpaceTextEditor.draw_handler_add
    with draw_type='POST_PIXEL'.
  - POST_PIXEL means coordinates are in screen pixels, (0,0) = bottom-left.
  - We draw: background rect → character grid → cursor → status bar → input bar.

Performance notes:
  - The pyte screen buffer is read as a snapshot each frame.
  - Character batching: consecutive chars of the same color are batched
    into a single blf.draw() call for performance.
  - Background rectangles use gpu_extras.batch for GPU-accelerated drawing.
  - Font and shader objects are cached at module level; never created per-frame.
"""

import math
import os
import time
from pathlib import Path
from typing import List, Optional, Tuple

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from ..core.log import get_logger
from ..terminal.screen import RenderedChar, RenderedLine, _DEFAULT_FG, _DEFAULT_BG

log = get_logger("ui.terminal_draw")

# ─── Module-level state ───────────────────────────────────────────────────────

_draw_handler = None          # handle returned by draw_handler_add
_font_id: int = 0             # blf font id (0 = default, or loaded monospace)
_font_loaded: bool = False    # whether we loaded our custom font
_shader = None                # GPU uniform-color shader (cached)
_char_w: float = 8.0          # character cell width in pixels
_char_h: float = 16.0         # character cell height in pixels

# Terminal padding (pixels)
_FONT_H_FACTOR = 1.6
_PAD_X = 12
_PAD_Y = 12

# Cursor blink period in seconds
_CURSOR_BLINK_PERIOD = 1.0

# ─── Theme definitions ────────────────────────────────────────────────────────

_THEMES = {
    "DARK": {
        "bg":          (0.08, 0.08, 0.08, 1.0),
        "statusbar_bg": (0.14, 0.14, 0.14, 1.0),
        "statusbar_fg": (0.60, 0.60, 0.60, 1.0),
        "cursor":      (0.95, 0.95, 0.95, 0.85),
        "selection":   (0.20, 0.40, 0.75, 0.40),
        "inputbar_bg": (0.12, 0.12, 0.12, 1.0),
        "inputbar_fg": (0.90, 0.90, 0.90, 1.0),
        "prompt":      (0.40, 0.90, 0.40, 1.0),
    },
    "DRACULA": {
        "bg":          (0.157, 0.165, 0.212, 1.0),
        "statusbar_bg": (0.102, 0.106, 0.137, 1.0),
        "statusbar_fg": (0.627, 0.627, 0.627, 1.0),
        "cursor":      (0.973, 0.973, 0.949, 0.9),
        "selection":   (0.267, 0.275, 0.357, 0.7),
        "inputbar_bg": (0.118, 0.122, 0.157, 1.0),
        "inputbar_fg": (0.973, 0.973, 0.949, 1.0),
        "prompt":      (0.314, 0.980, 0.482, 1.0),
    },
    "SOLARIZED": {
        "bg":          (0.0, 0.168, 0.212, 1.0),
        "statusbar_bg": (0.0, 0.129, 0.165, 1.0),
        "statusbar_fg": (0.514, 0.580, 0.588, 1.0),
        "cursor":      (0.933, 0.910, 0.835, 0.9),
        "selection":   (0.071, 0.259, 0.322, 0.7),
        "inputbar_bg": (0.0, 0.145, 0.188, 1.0),
        "inputbar_fg": (0.933, 0.910, 0.835, 1.0),
        "prompt":      (0.522, 0.600, 0.000, 1.0),
    },
    "LIGHT": {
        "bg":          (0.97, 0.97, 0.97, 1.0),
        "statusbar_bg": (0.88, 0.88, 0.88, 1.0),
        "statusbar_fg": (0.30, 0.30, 0.30, 1.0),
        "cursor":      (0.10, 0.10, 0.10, 0.85),
        "selection":   (0.70, 0.85, 1.00, 0.50),
        "inputbar_bg": (0.93, 0.93, 0.93, 1.0),
        "inputbar_fg": (0.10, 0.10, 0.10, 1.0),
        "prompt":      (0.10, 0.55, 0.10, 1.0),
    },
}


def _get_blender_theme(context: bpy.types.Context) -> dict:
    try:
        theme = context.preferences.themes[0]
        te = theme.text_editor
        
        def rgba(col, alpha=1.0):
            c = list(col)
            if len(c) == 3: c.append(alpha)
            return tuple(c)
            
        bg = rgba(te.space.back)
        fg = rgba(te.space.text)
        cursor = rgba(te.cursor, 0.85)
        statusbar_bg = rgba(te.space.header)
        selection = rgba(te.space.text_selection, 0.4)
        
        return {
            "bg": bg,
            "statusbar_bg": statusbar_bg,
            "statusbar_fg": fg,
            "cursor": cursor,
            "selection": selection,
            "inputbar_bg": bg,
            "inputbar_fg": fg,
            "prompt": (0.4, 0.9, 0.4, 1.0)
        }
    except Exception:
        return _THEMES["DARK"]


def _get_theme(context: bpy.types.Context) -> dict:
    try:
        from ..blender.preferences import get_prefs
        prefs = get_prefs(context)
        if prefs and prefs.theme == "BLENDER":
            return _get_blender_theme(context)
        return _THEMES.get(prefs.theme if prefs else "DARK", _THEMES["DARK"])
    except Exception:
        return _THEMES["DARK"]


def _get_font_size(context: bpy.types.Context) -> int:
    try:
        from ..blender.preferences import get_prefs
        prefs = get_prefs(context)
        return prefs.font_size if prefs else 13
    except Exception:
        return 13


def _get_ui_scale(context: bpy.types.Context) -> float:
    try:
        scale = context.preferences.view.ui_scale
        # pixel_size is 2.0 on Mac Retina displays
        pixel_size = context.preferences.system.pixel_size
        return float(scale * pixel_size)
    except Exception:
        return 1.0


# ─── Font loading ─────────────────────────────────────────────────────────────

def _load_font() -> None:
    global _font_id, _font_loaded
    if _font_loaded:
        return
    # Path to the bundled JetBrains Mono font, relative to this file
    font_path = Path(__file__).parent.parent.parent / "fonts" / "JetBrainsMono-Regular.ttf"
    if font_path.is_file():
        loaded_id = blf.load(str(font_path))
        if loaded_id >= 0:
            _font_id = loaded_id
            _font_loaded = True
            log.info("Loaded JetBrains Mono font (id=%d)", _font_id)
            return
    # Fallback to Blender default font (font_id 0)
    _font_id = 0
    _font_loaded = True
    log.warning("JetBrains Mono not found, using default font (grid may not align)")


def _measure_char(font_size: int, ui_scale: float = 1.0) -> Tuple[float, float]:
    """Measure a representative monospace character cell."""
    _load_font()
    scaled_size = int(font_size * ui_scale)
    blf.size(_font_id, scaled_size)
    w, h = blf.dimensions(_font_id, "M")
    if w <= 0:
        w = scaled_size * 0.6
    if h <= 0:
        h = scaled_size * 1.4
    return w, h


# ─── GPU helpers ──────────────────────────────────────────────────────────────

def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _shader


def _draw_rect(x: float, y: float, w: float, h: float, color: Tuple) -> None:
    """Draw a filled rectangle at (x, y) with size (w, h)."""
    shader = _get_shader()
    vertices = [
        (x,     y    ),
        (x + w, y    ),
        (x + w, y + h),
        (x,     y + h),
    ]
    batch = batch_for_shader(shader, "TRIS", {"pos": [
        vertices[0], vertices[1], vertices[2],
        vertices[0], vertices[2], vertices[3],
    ]})
    shader.bind()
    shader.uniform_float("color", color)
    gpu.state.blend_set("ALPHA")
    batch.draw(shader)
    gpu.state.blend_set("NONE")


# ─── Main draw callback ───────────────────────────────────────────────────────

def draw_terminal() -> None:
    try:
        _draw_terminal_impl()
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        log.error("DRAW ERROR: %s\n%s", e, err)
        with open("/tmp/bat_draw_error.txt", "w") as f:
            f.write(err)

def _draw_terminal_impl() -> None:
    """
    Called by Blender every frame for every TEXT_EDITOR area.
    We skip areas that don't have an active terminal session.
    """
    context = bpy.context

    if not context or not context.area:
        return
    if context.area.type != "TEXT_EDITOR":
        return

    wm = context.window_manager
    if not wm.bat_terminal_active:
        return

    from ..terminal.manager import get_manager
    manager = get_manager()
    if not manager:
        return
    session = manager.get_active()
    if not session:
        return

    # Find the WINDOW region dimensions
    region = None
    for r in context.area.regions:
        if r.type == "WINDOW":
            region = r
            break
    if region is None:
        return

    rw = region.width
    rh = region.height

    # ── Font + sizing ──────────────────────────────────────────────────────
    _load_font()
    font_size = _get_font_size(context)
    ui_scale = _get_ui_scale(context)
    char_w, char_h = _measure_char(font_size, ui_scale)
    scaled_font_size = int(font_size * ui_scale)

    # Update session terminal size if area has changed significantly
    cols = max(10, int((rw - _PAD_X * 2) / char_w))
    rows = max(5, int((rh - _PAD_Y * 2 - char_h) / char_h))
    if cols != session.screen.cols or rows != session.screen.rows:
        session.resize(cols, rows)

    # ── Theme ──────────────────────────────────────────────────────────────
    theme = _get_theme(context)

    # ── Draw background ────────────────────────────────────────────────────
    _draw_rect(0, 0, rw, rh, theme["bg"])

    # ── Draw terminal screen buffer ────────────────────────────────────────
    term_area_y = 0
    term_area_h = rh

    lines = session.screen.get_display_lines()

    # Render from top of terminal area downward
    # Blender's y=0 is at bottom; lines[0] is top of screen.
    # So we render lines starting from (rh - char_h) and going down.
    start_y = rh - char_h - _PAD_Y

    for row_idx, line in enumerate(lines):
        y = start_y - row_idx * char_h

        # Skip rows below the visible area
        if y < term_area_y:
            break

        # Render this line: batch same-color consecutive chars
        _render_line(line, y, char_w, char_h, scaled_font_size, _PAD_X)

    # ── Draw text selection ────────────────────────────────────────────────
    if session.screen.selection_start and session.screen.selection_end:
        c1, r1 = session.screen.selection_start
        c2, r2 = session.screen.selection_end
        if r1 > r2 or (r1 == r2 and c1 > c2):
            c1, r1, c2, r2 = c2, r2, c1, r1
            
        r1 = max(0, min(r1, len(lines) - 1))
        r2 = max(0, min(r2, len(lines) - 1))
        
        selection_color = (0.2, 0.5, 0.9, 0.4)  # Semi-transparent blue
        
        for r in range(r1, r2 + 1):
            line = lines[r]
            start_col = c1 if r == r1 else 0
            end_col = c2 + 1 if r == r2 else len(line)
            
            start_col = max(0, min(start_col, len(line)))
            end_col = max(0, min(end_col, len(line)))
            
            if end_col > start_col:
                sx = _PAD_X + start_col * char_w
                sy = start_y - r * char_h
                sw = (end_col - start_col) * char_w
                _draw_rect(sx, sy, sw, char_h, selection_color)

    # ── Draw PTY cursor ────────────────────────────────────────────────────
    t = time.monotonic()
    cursor_on = (int(t / (_CURSOR_BLINK_PERIOD / 2)) % 2) == 0
    if cursor_on and session.is_alive() and wm.bat_input_active:
        cur_row = session.screen.cursor_row
        cur_col = session.screen.cursor_col
        cx = _PAD_X + cur_col * char_w
        cy = start_y - cur_row * char_h
        if cy >= term_area_y:
            # Draw semi-transparent block cursor so text beneath is slightly visible
            cursor_color = list(theme["cursor"])
            if len(cursor_color) == 3:
                cursor_color.append(0.6)
            elif len(cursor_color) == 4:
                cursor_color[3] = 0.6
            _draw_rect(cx, cy, char_w, char_h, tuple(cursor_color))


def _render_line(
    line: RenderedLine,
    y: float,
    char_w: float,
    char_h: float,
    scaled_font_size: int,
    pad_x: float,
) -> None:
    """
    Render a single RenderedLine using blf.
    Consecutive characters with the same fg color are batched into
    one blf.draw() call for performance.
    """
    if not line:
        return

    blf.size(_font_id, scaled_font_size)

    # Group consecutive chars by color
    batch_start = 0
    batch_fg = line[0].fg
    batch_chars = []

    def flush_batch(end_col: int):
        if not batch_chars:
            return
        text = "".join(batch_chars)
        x = pad_x + batch_start * char_w
        blf.color(_font_id, *batch_fg)
        blf.position(_font_id, x, y, 0)
        blf.draw(_font_id, text)

    for col_idx, rchar in enumerate(line):
        if rchar.fg != batch_fg:
            flush_batch(col_idx)
            batch_start = col_idx
            batch_fg = rchar.fg
            batch_chars = [rchar.char]
        else:
            batch_chars.append(rchar.char)

    flush_batch(len(line))


def _truncate_path(path: str, max_len: int = 40) -> str:
    """Shorten a path for display in the status bar."""
    if len(path) <= max_len:
        return path
    parts = Path(path).parts
    if len(parts) <= 2:
        return path
    return "…/" + str(Path(*parts[-2:]))


# ─── Handler registration ─────────────────────────────────────────────────────

def register_draw_handler() -> None:
    global _draw_handler
    if _draw_handler is not None:
        return  # Already registered
    _draw_handler = bpy.types.SpaceTextEditor.draw_handler_add(
        draw_terminal, (), "WINDOW", "POST_PIXEL"
    )
    log.debug("Draw handler registered on SpaceTextEditor")


def unregister_draw_handler() -> None:
    global _draw_handler
    if _draw_handler is None:
        return
    try:
        bpy.types.SpaceTextEditor.draw_handler_remove(_draw_handler, "WINDOW")
    except Exception as exc:
        log.debug("Draw handler removal: %s", exc)
    _draw_handler = None
    log.debug("Draw handler unregistered")
