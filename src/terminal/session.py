"""
Blender Interactive Terminal — Terminal Session

A TerminalSession ties together:
  - A platform-appropriate TerminalBackend (PTY/ConPTY)
  - A TerminalScreen (pyte emulator + scrollback)
  - An OutputQueue (thread-safe byte buffer)
  - Session state (status, command, cwd, history)

Sessions are owned by TerminalManager and referenced by ID.
"""

import os
import sys
import uuid
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional

from ..core.events import OutputQueue
from ..core.log import get_logger
from ..process.discovery import get_default_shell, get_user_env
from .screen import TerminalScreen

log = get_logger("terminal.session")


class SessionStatus(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPED = auto()
    ERROR = auto()


class TerminalSession:
    """
    Encapsulates a single terminal session: one PTY process + one screen.

    Usage:
        session = TerminalSession(cols=120, rows=40)
        session.start(["bash"])
        session.send_input("echo hello\n")
        session.kill()
    """

    def __init__(
        self,
        cols: int = 220,
        rows: int = 50,
        max_scrollback: int = 2000,
        cwd: Optional[str] = None,
    ) -> None:
        self.session_id: str = str(uuid.uuid4())[:8]
        self.status: SessionStatus = SessionStatus.IDLE
        self.cmd: List[str] = []
        self.cwd: str = cwd or str(Path.home())
        self.history: List[str] = []   # command history
        self._hist_idx: int = -1

        # Terminal emulator screen
        self.screen = TerminalScreen(cols=cols, rows=rows, max_scrollback=max_scrollback)

        # Thread-safe output queue (reader thread → main thread)
        self.output_queue = OutputQueue()

        # Backend — created at start() time
        self._backend = None

        log.debug("Session %s created (%d×%d)", self.session_id, cols, rows)

    # ─── Public API ───────────────────────────────────────────────────────

    def start(self, cmd: Optional[List[str]] = None) -> bool:
        """
        Start a process. If cmd is None, starts the user's default shell.
        Returns True on success.
        """
        if cmd is None:
            cmd = [get_default_shell()]

        self.cmd = cmd
        self.status = SessionStatus.RUNNING

        try:
            backend = self._create_backend()
        except Exception as exc:
            log.error("Backend creation failed: %s", exc)
            self.status = SessionStatus.ERROR
            # Inject error message into the screen so the user sees it
            self._inject_error(str(exc))
            return False

        env = get_user_env()
        env["COLUMNS"] = str(self.screen.cols)
        env["LINES"] = str(self.screen.rows)

        ok = backend.start(
            cmd=cmd,
            cols=self.screen.cols,
            rows=self.screen.rows,
            env=env,
            cwd=self.cwd,
        )

        if ok:
            self._backend = backend
            log.info("Session %s started: %s", self.session_id, cmd)
        else:
            self.status = SessionStatus.ERROR
            self._inject_error(f"Failed to start: {' '.join(cmd)}")

        return ok

    def send_input(self, data: bytes) -> None:
        """Write raw bytes to the PTY (keystrokes, commands)."""
        if self._backend and self._backend.is_alive():
            self._backend.write(data)
        else:
            log.debug("send_input: no live backend")

    def send_line(self, text: str) -> None:
        """Convenience: send a text line followed by newline."""
        self.send_input((text + "\n").encode("utf-8"))
        # Track in history
        if text.strip():
            self.history.append(text)
            self._hist_idx = len(self.history)

    def history_prev(self) -> Optional[str]:
        """Navigate command history upward."""
        if not self.history:
            return None
        self._hist_idx = max(0, self._hist_idx - 1)
        return self.history[self._hist_idx]

    def history_next(self) -> Optional[str]:
        """Navigate command history downward."""
        if not self.history:
            return None
        self._hist_idx = min(len(self.history), self._hist_idx + 1)
        if self._hist_idx >= len(self.history):
            return ""
        return self.history[self._hist_idx]

    def resize(self, cols: int, rows: int) -> None:
        """Resize both the pyte screen and the PTY."""
        self.screen.resize(cols, rows)
        if self._backend:
            self._backend.resize(cols, rows)

    def kill(self) -> None:
        """Kill the running process."""
        if self._backend:
            self._backend.kill()
            self.status = SessionStatus.STOPPED
            log.info("Session %s killed", self.session_id)
        self._backend = None

    def is_alive(self) -> bool:
        """Return True if the underlying process is still running."""
        if self._backend is None:
            return False
        alive = self._backend.is_alive()
        if not alive and self.status == SessionStatus.RUNNING:
            self.status = SessionStatus.STOPPED
        return alive

    @property
    def pid(self) -> Optional[int]:
        return self._backend.pid if self._backend else None

    @property
    def status_label(self) -> str:
        if self.status == SessionStatus.RUNNING and self.is_alive():
            return f"Running (pid {self.pid})"
        if self.status == SessionStatus.STOPPED:
            return "Stopped"
        if self.status == SessionStatus.ERROR:
            return "Error"
        return "Idle"

    # ─── Private helpers ──────────────────────────────────────────────────

    def _create_backend(self):
        """Instantiate the correct backend for the current platform."""
        if sys.platform == "win32":
            from .windows_pty import WindowsPTYBackend
            return WindowsPTYBackend(on_output=self.output_queue.put)
        else:
            from .unix_pty import UnixPTYBackend
            return UnixPTYBackend(on_output=self.output_queue.put)

    def _inject_error(self, message: str) -> None:
        """Write an error message directly into the pyte screen."""
        error_bytes = f"\r\n\033[31m[BAT Error] {message}\033[0m\r\n".encode()
        self.screen.feed(error_bytes)

    def __repr__(self) -> str:
        return (
            f"<TerminalSession id={self.session_id} "
            f"cmd={self.cmd} status={self.status.name}>"
        )
