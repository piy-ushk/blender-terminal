"""
Blender Agent Terminal — Unix PTY Backend (macOS + Linux)

Uses the Python stdlib `pty` module to open a master/slave pseudo-terminal
pair, spawns the child process attached to the slave end, and reads output
from the master end in a daemon thread.

This module must NOT be imported on Windows. The session factory checks
sys.platform before instantiating.
"""

import fcntl
import os
import signal
import struct
import subprocess
import sys
import termios
import threading
from typing import Callable, Dict, List, Optional

from .backend import TerminalBackend
from ..core.log import get_logger

log = get_logger("terminal.unix_pty")

# Read chunk size from PTY master fd
_READ_CHUNK = 4096


class UnixPTYBackend(TerminalBackend):
    """
    macOS / Linux PTY-based terminal backend.

    Creates a master/slave PTY pair. The child process runs with
    its stdin/stdout/stderr connected to the slave fd, so it behaves
    exactly as if running in a real terminal. We communicate via
    the master fd.
    """

    def __init__(self, on_output: Callable[[bytes], None]) -> None:
        super().__init__(on_output)
        self._master_fd: Optional[int] = None
        self._slave_fd: Optional[int] = None
        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ─── TerminalBackend interface ─────────────────────────────────────────

    def start(
        self,
        cmd: List[str],
        cols: int,
        rows: int,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> bool:
        import pty  # Unix only

        try:
            self._master_fd, self._slave_fd = pty.openpty()

            # Set initial terminal size on the slave side
            self._set_winsize(self._slave_fd, cols, rows)

            self._proc = subprocess.Popen(
                cmd,
                stdin=self._slave_fd,
                stdout=self._slave_fd,
                stderr=self._slave_fd,
                env=env,
                cwd=cwd,
                close_fds=True,
                start_new_session=True,  # new process group → Ctrl+C works
            )

            # The slave fd is now owned by the child process; close our copy
            # so EOF is signalled when the child exits.
            os.close(self._slave_fd)
            self._slave_fd = None

            # Start daemon reader thread
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"BAT-reader-{self._proc.pid}",
                daemon=True,
            )
            self._reader_thread.start()

            log.info("Started process %s (pid=%d)", cmd, self._proc.pid)
            return True

        except Exception as exc:
            log.error("Failed to start process %s: %s", cmd, exc)
            self._cleanup()
            return False

    def write(self, data: bytes) -> None:
        if self._master_fd is None:
            return
        try:
            os.write(self._master_fd, data)
        except OSError as exc:
            log.debug("PTY write error: %s", exc)

    def resize(self, cols: int, rows: int) -> None:
        if self._master_fd is None:
            return
        try:
            self._set_winsize(self._master_fd, cols, rows)
            log.debug("PTY resized to %d×%d", cols, rows)
        except OSError as exc:
            log.debug("PTY resize error: %s", exc)

    def kill(self) -> None:
        if self._proc is None:
            return
        try:
            # Kill the entire process group so child subprocesses also die
            os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                self._proc.kill()
            except OSError:
                pass
        self._cleanup()

    def is_alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    # ─── Private helpers ───────────────────────────────────────────────────

    def _reader_loop(self) -> None:
        """
        Runs in a daemon thread. Continuously reads raw bytes from
        the PTY master fd and delivers them to the output callback.
        Thread exits when the fd closes (process exited).
        """
        fd = self._master_fd
        log.debug("Reader thread started (fd=%d)", fd)
        while True:
            try:
                data = os.read(fd, _READ_CHUNK)
                if not data:
                    break
                self._on_output(data)
            except OSError:
                # fd closed — process exited
                break
        log.debug("Reader thread exiting")
        # Signal that the process ended by sending a sentinel
        self._on_output(b"")

    def _set_winsize(self, fd: int, cols: int, rows: int) -> None:
        """Set terminal window size via TIOCSWINSZ ioctl."""
        # struct winsize: rows, cols, xpixel, ypixel (all unsigned short)
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    def _cleanup(self) -> None:
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
            self._slave_fd = None
