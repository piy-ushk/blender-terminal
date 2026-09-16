"""
Blender Agent Terminal — IPC Server Bridge

Provides a local HTTP server that allows external CLI tools (like `bpy-exec` used by agents)
to send Python code to be executed safely on Blender's main thread.
"""

import io
import json
import os
import queue
import stat
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import bpy

from .log import get_logger

log = get_logger("core.ipc")


class ExecRequest:
    def __init__(self, code: str):
        self.code = code
        self.error: Optional[str] = None
        self.output: str = ""
        self.event = threading.Event()


_exec_queue: queue.Queue = queue.Queue()


def _process_queue() -> float:
    """Timer callback: pops code execution requests and runs them safely on the main thread."""
    while not _exec_queue.empty():
        req: ExecRequest = _exec_queue.get_nowait()

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = sys.stderr = buf = io.StringIO()

        try:
            # Execute with persistent globals so agents can chain commands across multiple script calls
            if not hasattr(bpy, "_bat_ipc_globals"):
                bpy._bat_ipc_globals = {"bpy": bpy}  # type: ignore

            exec(req.code, bpy._bat_ipc_globals)  # type: ignore
        except Exception:
            req.error = traceback.format_exc()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            req.output = buf.getvalue()
            req.event.set()

    return 0.05  # Run every 50ms


class IPCHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/exec":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            data = json.loads(body)
            code = data.get("code", "")

            req = ExecRequest(code)
            _exec_queue.put(req)
            req.event.wait()  # Block HTTP thread until Blender main thread finishes execution

            res = {"output": req.output, "error": req.error}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default HTTP logging to avoid spamming the console
        pass


_server: Optional[HTTPServer] = None
_server_thread: Optional[threading.Thread] = None
_ipc_port: int = 0


def start_ipc_server() -> int:
    global _server, _server_thread, _ipc_port
    if _server is not None:
        return _ipc_port

    _server = HTTPServer(("127.0.0.1", 0), IPCHandler)
    _ipc_port = _server.server_port

    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()

    if not bpy.app.timers.is_registered(_process_queue):
        bpy.app.timers.register(_process_queue, first_interval=0.1)

    log.info("IPC Server started on port %d", _ipc_port)
    return _ipc_port


def stop_ipc_server() -> None:
    global _server, _ipc_port
    if _server:
        _server.shutdown()
        _server.server_close()
        _server = None
        _ipc_port = 0
    if bpy.app.timers.is_registered(_process_queue):
        bpy.app.timers.unregister(_process_queue)
    log.info("IPC Server stopped")


def generate_bpy_exec(port: int) -> str:
    """
    Generates the CLI bridge script `bpy-exec` and returns the directory 
    it is stored in, so it can be added to the PATH.
    """
    bin_dir = "/tmp/bat_ipc_bin"
    os.makedirs(bin_dir, exist_ok=True)
    path = os.path.join(bin_dir, "bpy-exec")
    
    script = f"""#!/usr/bin/env python3
import sys, urllib.request, json

if len(sys.argv) > 1:
    code = " ".join(sys.argv[1:])
else:
    code = sys.stdin.read()

req = urllib.request.Request(
    "http://127.0.0.1:{port}/exec",
    data=json.dumps({{"code": code}}).encode("utf-8"),
    headers={{"Content-Type": "application/json"}},
    method="POST"
)
try:
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode())
        if res.get("output"):
            print(res["output"], end="")
        if res.get("error"):
            print(res["error"], file=sys.stderr)
            sys.exit(1)
except Exception as e:
    print(f"Blender IPC Error: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
    with open(path, "w") as f:
        f.write(script)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    
    # Windows compatibility wrapper
    cmd_path = os.path.join(bin_dir, "bpy-exec.cmd")
    with open(cmd_path, "w") as f:
        f.write('@echo off\r\npython "%~dp0\\bpy-exec" %*\r\n')
    
    return bin_dir
