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
import subprocess
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


# ─── PATH Resolution ──────────────────────────────────────────────────────────

_CACHED_PATH = None

def _get_interactive_path() -> str:
    """
    On macOS GUI apps, os.environ["PATH"] is heavily restricted to /usr/bin.
    This fetches the true PATH from the user's interactive shell.
    """
    global _CACHED_PATH
    if _CACHED_PATH is not None:
        return _CACHED_PATH
    
    _CACHED_PATH = os.environ.get("PATH", "")
    if sys.platform != "darwin":
        return _CACHED_PATH

    try:
        shell = os.environ.get("SHELL", "/bin/zsh")
        result = subprocess.run(
            [shell, "-ilc", "env"],
            capture_output=True,
            text=True,
            timeout=2.0
        )
        for line in result.stdout.splitlines():
            if line.startswith("PATH="):
                _CACHED_PATH = line[5:]
                break
    except Exception as e:
        log.warning("Failed to fetch interactive PATH: %s", e)
        
    return _CACHED_PATH

# Inject true PATH into Blender's environment on module load
if sys.platform == "darwin":
    os.environ["PATH"] = _get_interactive_path()


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

    # ─── Start IPC Server & Inject bridge ───
    try:
        from ..core.ipc import start_ipc_server, generate_bpy_exec
        port = start_ipc_server()
        bin_dir = generate_bpy_exec(port)
        
        env["BLENDER_IPC_PORT"] = str(port)
        
        # Inject agent wrappers to force system prompts
        import bpy
        import stat
        blend_file = bpy.data.filepath
        blend_dir = os.path.dirname(blend_file) if blend_file else "The current Blender file is not saved yet."
        
        prompt = (
            "You are an AI assistant running inside a terminal directly embedded in Blender. "
            "You have FULL access to Blender's Python API via the 'bpy-exec' command line tool. "
            "Your primary goal is to help the user manipulate the 3D scene, UI, and objects. "
            "Instead of telling the user how to do things, DO IT YOURSELF by running python scripts or 'bpy-exec \"...\"'. "
            f"Restrict your workspace to this directory: {blend_dir}."
        )
        prompt_esc = prompt.replace('"', '\\"')
        
        claude_path = shutil.which("claude")
        if claude_path and not claude_path.startswith(bin_dir):
            wrap_path = os.path.join(bin_dir, "claude")
            with open(wrap_path, "w") as f:
                f.write(f'#!/bin/sh\nexec "{claude_path}" --system-prompt "{prompt_esc}" "$@"\n')
            os.chmod(wrap_path, os.stat(wrap_path).st_mode | stat.S_IEXEC)
        
        # Prepend our bin_dir to PATH so bpy-exec and wrappers are immediately available
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    except Exception as e:
        log.error("Failed to start IPC server: %s", e)

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
