"""
Blender Interactive Terminal — Terminal Manager (Singleton)

Owns all active TerminalSession instances and provides the single
authoritative reference point for the Blender operator/UI layer.

Design: module-level singleton (safe for Blender's single-process model).
"""

from typing import Dict, Iterator, List, Optional

from .session import TerminalSession
from ..core.log import get_logger

log = get_logger("terminal.manager")

# ─── Module-level singleton ───────────────────────────────────────────────────

_manager_instance: Optional["TerminalManager"] = None


def get_manager() -> Optional["TerminalManager"]:
    """Return the active TerminalManager, or None if not initialised."""
    return _manager_instance


def ensure_manager() -> "TerminalManager":
    """Return (creating if needed) the TerminalManager singleton."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = TerminalManager()
        log.debug("TerminalManager created")
    return _manager_instance


def destroy_manager() -> None:
    """Kill all sessions and destroy the manager (called on unregister)."""
    global _manager_instance
    if _manager_instance is not None:
        _manager_instance.destroy_all()
        _manager_instance = None
        log.debug("TerminalManager destroyed")


# ─── TerminalManager ──────────────────────────────────────────────────────────

class TerminalManager:
    """
    Manages a collection of TerminalSession instances.

    In MVP #1 only one session is active at a time.
    The architecture supports multiple sessions (tabs) for MVP #2.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, TerminalSession] = {}
        self._active_id: Optional[str] = None

    # ─── Session lifecycle ────────────────────────────────────────────────

    def create_session(
        self,
        cols: int = 220,
        rows: int = 50,
        cwd: Optional[str] = None,
        max_scrollback: int = 2000,
    ) -> TerminalSession:
        """Create a new session and make it active."""
        session = TerminalSession(cols=cols, rows=rows, cwd=cwd, max_scrollback=max_scrollback)
        self._sessions[session.session_id] = session
        self._active_id = session.session_id
        log.debug("Created session %s (total: %d)", session.session_id, len(self._sessions))
        return session

    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        return self._sessions.get(session_id)

    def get_active(self) -> Optional[TerminalSession]:
        if self._active_id is None:
            return None
        return self._sessions.get(self._active_id)

    def set_active(self, session_id: str) -> bool:
        if session_id in self._sessions:
            self._active_id = session_id
            return True
        return False

    def destroy_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            session.kill()
            log.debug("Destroyed session %s", session_id)
        if self._active_id == session_id:
            # Activate the last remaining session, if any
            self._active_id = next(iter(self._sessions), None)

    def destroy_all(self) -> None:
        """Kill and remove all sessions."""
        for session in list(self._sessions.values()):
            try:
                session.kill()
            except Exception:
                pass
        self._sessions.clear()
        self._active_id = None
        log.debug("All sessions destroyed")

    # ─── Iteration ────────────────────────────────────────────────────────

    def iter_sessions(self) -> Iterator[TerminalSession]:
        """Iterate over all active sessions (used by timer pump)."""
        yield from self._sessions.values()

    @property
    def has_active(self) -> bool:
        return self._active_id is not None and self._active_id in self._sessions

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    @property
    def active_id(self) -> Optional[str]:
        return self._active_id

    def __repr__(self) -> str:
        return f"<TerminalManager sessions={len(self._sessions)} active={self._active_id}>"
