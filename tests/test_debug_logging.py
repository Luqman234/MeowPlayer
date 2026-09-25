import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from meow_logging import (
    configure_debug_logging,
    default_debug_log_path,
    mpv_debug_log_path,
    shutdown_debug_logging,
)
from meowplayer import build_mpv_command, parse_args


class DebugLoggingTests(unittest.TestCase):
    def tearDown(self):
        shutdown_debug_logging()

    def test_default_debug_log_uses_xdg_state_home(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(
                os.environ,
                {"XDG_STATE_HOME": temp},
                clear=False,
            ):
                expected = Path(temp) / "meowplayer" / "debug.log"
                self.assertEqual(default_debug_log_path(), expected)

    def test_debug_mode_creates_file_and_records_child_loggers(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict(
                os.environ,
                {"XDG_STATE_HOME": temp},
                clear=False,
            ):
                path = configure_debug_logging(enabled=True)
                logging.getLogger("meowplayer.youtube").info(
                    "internet cat diagnostic"
                )
                shutdown_debug_logging()

                self.assertTrue(path.is_file())
                text = path.read_text(encoding="utf-8")
                self.assertIn("Debug logging initialized", text)
                self.assertIn("internet cat diagnostic", text)

    def test_log_file_implies_debug_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "custom-debug.log"
            configured = configure_debug_logging(
                enabled=False,
                log_file=path,
            )
            logging.getLogger("meowplayer").debug("custom path works")
            shutdown_debug_logging()

            self.assertEqual(configured, path.resolve())
            self.assertIn(
                "custom path works",
                path.read_text(encoding="utf-8"),
            )

    def test_mpv_log_is_sibling_of_main_log(self):
        self.assertEqual(
            mpv_debug_log_path("/tmp/meowplayer-debug.log"),
            Path("/tmp/meowplayer-debug.mpv.log"),
        )
        self.assertEqual(
            mpv_debug_log_path("/tmp/meow-debug"),
            Path("/tmp/meow-debug.mpv.log"),
        )

    def test_mpv_command_enables_verbose_file_log_only_when_requested(self):
        normal = build_mpv_command("/tmp/meow-normal.sock")
        debug = build_mpv_command(
            "/tmp/meow-debug.sock",
            debug_log_path="/tmp/mpv-debug.log",
        )

        self.assertFalse(
            any(item.startswith("--log-file=") for item in normal)
        )
        self.assertNotIn("--msg-level=all=v", normal)
        self.assertIn("--log-file=/tmp/mpv-debug.log", debug)
        self.assertIn("--msg-level=all=v", debug)

    def test_debug_cli_flags(self):
        normal = parse_args([])
        debug = parse_args(["--debug"])
        custom = parse_args(["--log-file", "/tmp/meow.log"])

        self.assertFalse(normal.debug)
        self.assertIsNone(normal.log_file)
        self.assertTrue(debug.debug)
        self.assertEqual(custom.log_file, "/tmp/meow.log")


if __name__ == "__main__":
    unittest.main()
