"""
Blender Agent Terminal — Unit Tests

Tests run outside Blender (no bpy) to verify core logic.
Run with: python3 -m pytest tests/ -v

conftest.py installs a bpy mock so src.blender.* can be imported.
"""

import sys
import os
import threading
import time
import unittest

# Ensure the project root is on sys.path so `import src.*` works
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class TestOutputQueue(unittest.TestCase):
    """Test thread-safe OutputQueue."""

    def test_put_and_drain(self):
        from src.core.events import OutputQueue
        q = OutputQueue()
        q.put(b"hello ")
        q.put(b"world")
        result = q.drain()
        self.assertEqual(result, b"hello world")

    def test_drain_empty(self):
        from src.core.events import OutputQueue
        q = OutputQueue()
        self.assertEqual(q.drain(), b"")

    def test_is_empty(self):
        from src.core.events import OutputQueue
        q = OutputQueue()
        self.assertTrue(q.is_empty())
        q.put(b"x")
        self.assertFalse(q.is_empty())
        q.drain()
        self.assertTrue(q.is_empty())

    def test_thread_safety(self):
        """Multiple writers + one reader — no deadlock, no data loss."""
        from src.core.events import OutputQueue
        q = OutputQueue(maxlen=100000)
        received = []
        stop = threading.Event()

        def writer(chunk):
            for _ in range(200):
                q.put(chunk)
                time.sleep(0)

        def reader():
            while not stop.is_set():
                data = q.drain()
                if data:
                    received.append(data)
                time.sleep(0.001)

        threads = [
            threading.Thread(target=writer, args=(b"A",)),
            threading.Thread(target=writer, args=(b"B",)),
            threading.Thread(target=writer, args=(b"C",)),
        ]
        reader_t = threading.Thread(target=reader, daemon=True)
        reader_t.start()

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stop.set()
        reader_t.join(timeout=2)

        total = b"".join(received) + q.drain()
        # 3 writers × 200 iterations × 1 byte each = 600 bytes
        self.assertEqual(len(total), 600)


class TestProcessDiscovery(unittest.TestCase):

    def test_find_python(self):
        from src.process.discovery import find_executable
        # python3 should always be available in the test environment
        result = find_executable("python3") or find_executable("python")
        self.assertIsNotNone(result)

    def test_find_nonexistent(self):
        from src.process.discovery import find_executable
        result = find_executable("THIS_DOES_NOT_EXIST_12345")
        self.assertIsNone(result)

    def test_get_user_env(self):
        from src.process.discovery import get_user_env
        env = get_user_env()
        self.assertIn("TERM", env)
        self.assertEqual(env["TERM"], "xterm-256color")
        # Blender internals should not leak
        self.assertNotIn("PYTHONHOME", env)

    def test_get_default_shell(self):
        from src.process.discovery import get_default_shell
        shell = get_default_shell()
        self.assertTrue(len(shell) > 0)
        # On macOS/Linux it should be an actual file
        if sys.platform != "win32":
            self.assertTrue(os.path.isfile(shell), f"Shell not found: {shell}")


class TestTerminalScreen(unittest.TestCase):

    def setUp(self):
        # pyte must be available (install with: pip install pyte wcwidth)
        try:
            import pyte  # noqa
        except ImportError:
            self.skipTest("pyte not installed — install wheels first")

    def test_basic_feed(self):
        from src.terminal.screen import TerminalScreen
        screen = TerminalScreen(cols=80, rows=24)
        screen.feed(b"Hello, World!")
        lines = screen.get_display_lines()
        self.assertEqual(len(lines), 24)
        # First line should contain "Hello, World!"
        first_line_text = "".join(c.char for c in lines[0])
        self.assertIn("Hello", first_line_text)

    def test_ansi_color(self):
        from src.terminal.screen import TerminalScreen, _DEFAULT_FG
        screen = TerminalScreen(cols=80, rows=24)
        # Green text
        screen.feed(b"\x1b[32mGREEN\x1b[0m")
        lines = screen.get_display_lines()
        first_line = lines[0]
        # The 'G' character should have a green foreground
        g_char = first_line[0]
        self.assertEqual(g_char.char, "G")
        # Green should have higher G channel than R
        self.assertGreater(g_char.fg[1], g_char.fg[0])

    def test_clear(self):
        from src.terminal.screen import TerminalScreen
        screen = TerminalScreen(cols=80, rows=24)
        screen.feed(b"Some text here")
        screen.clear()
        lines = screen.get_display_lines()
        all_text = "".join("".join(c.char for c in line) for line in lines)
        self.assertEqual(all_text.strip(), "")

    def test_scroll(self):
        from src.terminal.screen import TerminalScreen
        screen = TerminalScreen(cols=80, rows=5)
        screen.scroll_up(3)
        self.assertEqual(screen._scroll_offset, 0)  # no scrollback yet
        screen.scroll_down(1)
        self.assertEqual(screen._scroll_offset, 0)

    def test_resize(self):
        from src.terminal.screen import TerminalScreen
        screen = TerminalScreen(cols=80, rows=24)
        screen.resize(120, 40)
        self.assertEqual(screen.cols, 120)
        self.assertEqual(screen.rows, 40)


class TestUnixPTYBackend(unittest.TestCase):

    def setUp(self):
        if sys.platform == "win32":
            self.skipTest("UnixPTYBackend not available on Windows")

    def test_echo_command(self):
        """Start 'echo hello' in a PTY and verify we receive the output."""
        from src.core.events import OutputQueue
        from src.terminal.unix_pty import UnixPTYBackend

        output = []
        q = OutputQueue()

        def collector(data):
            if data:
                output.append(data)

        backend = UnixPTYBackend(on_output=collector)
        ok = backend.start(["echo", "hello from pty"], cols=80, rows=24)
        self.assertTrue(ok)
        self.assertTrue(backend.pid is not None)

        # Wait for output (reader thread)
        time.sleep(0.5)

        combined = b"".join(output)
        self.assertIn(b"hello from pty", combined)

    def test_is_alive_after_exit(self):
        """Process should not be alive after it exits."""
        from src.terminal.unix_pty import UnixPTYBackend

        backend = UnixPTYBackend(on_output=lambda d: None)
        backend.start(["true"], cols=80, rows=24)  # 'true' exits immediately
        time.sleep(0.3)
        self.assertFalse(backend.is_alive())

    def test_kill(self):
        """kill() should terminate a running process."""
        from src.terminal.unix_pty import UnixPTYBackend

        backend = UnixPTYBackend(on_output=lambda d: None)
        backend.start(["sleep", "60"], cols=80, rows=24)
        self.assertTrue(backend.is_alive())
        backend.kill()
        time.sleep(0.3)
        self.assertFalse(backend.is_alive())


class TestTerminalManager(unittest.TestCase):

    def setUp(self):
        # Reset the singleton between tests
        import src.terminal.manager as mgr_module
        mgr_module._manager_instance = None

    def test_create_and_get_active(self):
        from src.terminal.manager import ensure_manager
        manager = ensure_manager()
        session = manager.create_session(cols=80, rows=24)
        self.assertIsNotNone(session)
        self.assertIs(manager.get_active(), session)

    def test_destroy_all(self):
        from src.terminal.manager import ensure_manager, destroy_manager
        manager = ensure_manager()
        manager.create_session()
        manager.create_session()
        self.assertEqual(manager.session_count, 2)
        destroy_manager()
        # After destroy, get_manager() returns None
        from src.terminal.manager import get_manager
        self.assertIsNone(get_manager())


if __name__ == "__main__":
    unittest.main()
