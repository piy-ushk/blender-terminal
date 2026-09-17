"""
Blender Interactive Terminal — Event / Output Queue & Timer Pump

Architecture:
  Reader thread  →  OutputQueue (deque + lock)
  bpy.app.timers → pump_output() on MAIN THREAD
  pump_output()  → feeds pyte screen → triggers redraw

CRITICAL: No bpy calls from background threads. Only the timer callback
(running on Blender's main thread) accesses bpy.
"""

import threading
import collections
from typing import Optional

from .log import get_logger

log = get_logger("events")

# ─── Per-session output queue ─────────────────────────────────────────────────

class OutputQueue:
    """Thread-safe byte queue for PTY → pyte data flow."""

    def __init__(self, maxlen: int = 65536) -> None:
        self._lock = threading.Lock()
        self._buf = collections.deque(maxlen=maxlen)

    def put(self, data: bytes) -> None:
        """Called from reader thread."""
        with self._lock:
            self._buf.append(data)

    def drain(self) -> bytes:
        """Called from main thread timer. Returns all pending bytes."""
        with self._lock:
            if not self._buf:
                return b""
            chunks = list(self._buf)
            self._buf.clear()
        return b"".join(chunks)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._buf) == 0


# ─── Global timer state ───────────────────────────────────────────────────────

_TIMER_INTERVAL = 0.033  # ~30 fps pump rate
_timer_registered = False


def register_pump_timer() -> None:
    """Register the bpy.app.timer that pumps all active sessions.
    Safe to call multiple times — idempotent.
    """
    global _timer_registered
    import bpy

    if _timer_registered:
        return

    # Check if already registered (module reload safety)
    # bpy.app.timers has no way to query by function, so we track ourselves.
    bpy.app.timers.register(_timer_callback, first_interval=_TIMER_INTERVAL, persistent=True)
    _timer_registered = True
    log.debug("Output pump timer registered (%.3fs interval)", _TIMER_INTERVAL)


def unregister_pump_timer() -> None:
    """Unregister the pump timer on extension disable."""
    global _timer_registered
    import bpy

    if not _timer_registered:
        return

    try:
        bpy.app.timers.unregister(_timer_callback)
    except ValueError:
        pass  # already unregistered
    _timer_registered = False
    log.debug("Output pump timer unregistered")


def _timer_callback() -> Optional[float]:
    """
    Called by Blender on the main thread at _TIMER_INTERVAL seconds.
    Drains each active session's output queue, feeds pyte, and triggers
    a UI redraw if any new data arrived.

    Returns the next interval (float) to keep the timer running,
    or None to stop it (we never stop it while registered).
    """
    from ..terminal.manager import get_manager  # late import avoids circular

    manager = get_manager()
    if manager is None:
        return _TIMER_INTERVAL

    had_output = False
    for session in manager.iter_sessions():
        data = session.output_queue.drain()
        if data:
            session.screen.feed(data)
            had_output = True

    if had_output:
        _request_terminal_redraw()

    return _TIMER_INTERVAL


def _request_terminal_redraw() -> None:
    """Tag all visible TEXT_EDITOR areas for redraw."""
    try:
        import bpy
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "TEXT_EDITOR":
                    area.tag_redraw()
    except Exception as exc:
        log.debug("Redraw tag failed: %s", exc)
