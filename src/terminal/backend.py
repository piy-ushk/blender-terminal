"""
Blender Agent Terminal — Terminal Backend Abstract Base Class

All platform-specific backends implement this interface.
The session layer only talks to TerminalBackend — it never
knows whether it's using a Unix PTY or Windows ConPTY.
"""

import abc
from typing import Callable, Dict, List, Optional


class TerminalBackend(abc.ABC):
    """
    Abstract terminal backend.

    Lifecycle:
      backend = UnixPTYBackend(on_output=queue.put)
      backend.start(["bash"], cols=80, rows=24, env={...}, cwd="/tmp")
      backend.write(b"echo hello\n")
      backend.resize(120, 40)
      backend.kill()
    """

    def __init__(self, on_output: Callable[[bytes], None]) -> None:
        """
        :param on_output: Callback invoked from the READER THREAD when new
                          bytes arrive from the process. Must be thread-safe.
                          Typically this is OutputQueue.put.
        """
        self._on_output = on_output

    @abc.abstractmethod
    def start(
        self,
        cmd: List[str],
        cols: int,
        rows: int,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> bool:
        """
        Start the process inside a PTY.

        :param cmd:  Command + args list, e.g. ["bash"] or ["claude"].
        :param cols: Initial terminal width in columns.
        :param rows: Initial terminal height in rows.
        :param env:  Environment dict (None = inherit).
        :param cwd:  Working directory (None = inherit).
        :return:     True if process started successfully.
        """

    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """Write bytes to the process stdin (PTY master write side)."""

    @abc.abstractmethod
    def resize(self, cols: int, rows: int) -> None:
        """Inform the PTY of a terminal size change (SIGWINCH equivalent)."""

    @abc.abstractmethod
    def kill(self) -> None:
        """Terminate the process (SIGKILL / TerminateProcess)."""

    @abc.abstractmethod
    def is_alive(self) -> bool:
        """Return True if the process is still running."""

    @property
    @abc.abstractmethod
    def pid(self) -> Optional[int]:
        """Return the process ID, or None if not started."""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} pid={self.pid} alive={self.is_alive()}>"
