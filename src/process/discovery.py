"""
Blender Agent Terminal — Process Discovery & Environment

Provides:
  find_executable(name)   — cross-platform shutil.which wrapper
  get_user_env()          — a clean copy of os.environ for subprocess use
  detect_agents()         — probes for known AI CLIs and common tools
"""

import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional

from ..core.log import get_logger

log = get_logger("process.discovery")

# ─── Known agent / tool names to probe ───────────────────────────────────────

_KNOWN_AGENTS: Dict[str, str] = {
    "claude":  "Claude Code (Anthropic)",
    "codex":   "OpenAI Codex CLI",
    "gemini":  "Gemini CLI (Google)",
    "aider":   "Aider",
    "continue": "Continue",
}

_KNOWN_TOOLS: Dict[str, str] = {
    "node":    "Node.js",
    "npm":     "npm",
    "npx":     "npx",
    "git":     "Git",
    "python3": "Python 3",
    "python":  "Python",
    "bash":    "Bash",
    "zsh":     "Zsh",
    "sh":      "POSIX shell",
}


def find_executable(name: str) -> Optional[str]:
    """
    Return the full path to *name* if it exists on PATH, else None.
    Uses shutil.which which handles PATH lookup correctly on all platforms.
    """
    path = shutil.which(name)
    if path:
        log.debug("Found executable %r → %s", name, path)
    else:
        log.debug("Executable %r not found on PATH", name)
    return path


def get_default_shell() -> str:
    """
    Return the user's preferred interactive shell.
    Falls back to /bin/sh on Unix, cmd.exe on Windows.
    """
    if sys.platform == "win32":
        return os.environ.get("COMSPEC", "cmd.exe")

    # On macOS/Linux prefer SHELL env variable
    shell = os.environ.get("SHELL", "")
    if shell and Path(shell).is_file():
        return shell

    # Probe common shells in order of preference
    for candidate in ("zsh", "bash", "sh"):
        found = shutil.which(candidate)
        if found:
            return found

    return "/bin/sh"


def get_user_env() -> Dict[str, str]:
    """
    Return a clean copy of os.environ suitable for subprocess use.
    Adds TERM=xterm-256color so that CLI tools behave correctly inside
    our PTY (enables color output, proper readline, etc.).
    Does NOT propagate any Blender-internal paths that could cause
    subprocess Python version conflicts.
    """
    env = os.environ.copy()

    # Ensure a useful TERM value
    env.setdefault("TERM", "xterm-256color")
    env["COLORTERM"] = "truecolor"

    # Prevent Blender's embedded Python from being picked up by subprocesses
    # that resolve 'python' via PYTHONHOME/PYTHONPATH.
    for key in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)

    return env


def detect_agents() -> Dict[str, Optional[str]]:
    """
    Probe for known AI CLI agents.
    Returns dict: agent_key → full_path_or_None
    """
    result: Dict[str, Optional[str]] = {}
    for name in _KNOWN_AGENTS:
        result[name] = find_executable(name)
    return result


def detect_tools() -> Dict[str, Optional[str]]:
    """
    Probe for common developer tools.
    Returns dict: tool_key → full_path_or_None
    """
    result: Dict[str, Optional[str]] = {}
    for name in _KNOWN_TOOLS:
        result[name] = find_executable(name)
    return result


def detect_all() -> Dict[str, Dict[str, Optional[str]]]:
    """Return combined detection results."""
    return {
        "agents": detect_agents(),
        "tools": detect_tools(),
    }


def get_agent_label(key: str) -> str:
    """Human-readable label for an agent key."""
    return _KNOWN_AGENTS.get(key, key)


def get_tool_label(key: str) -> str:
    """Human-readable label for a tool key."""
    return _KNOWN_TOOLS.get(key, key)
