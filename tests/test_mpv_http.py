"""Opt-in real mpv/HTTP integration; only loopback traffic, never YouTube."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import wave
from unittest import mock

from meowplayer import MPVController, build_mpv_command
from youtube_online import ResolvedStream


@unittest.skipUnless(os.environ.get("MEOW_REAL_MPV") == "1", "opt-in real mpv integration")
class MPVHTTPTests(unittest.TestCase):
    def test_direct_stream_headers_events_and_local_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "tone.wav"
            with wave.open(str(audio), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b"\0\0" * 8000 * 3)
            requests = []
            class Handler(SimpleHTTPRequestHandler):
                def do_GET(self):
                    requests.append(dict(self.headers))
                    super().do_GET()
                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=directory))
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            with mock.patch("meowplayer.build_mpv_command", side_effect=lambda *a, **k:
                            build_mpv_command(*a, **k) + ["--no-config", "--ao=null"]):
                controller = MPVController()
            try:
                url = f"http://127.0.0.1:{server.server_port}/tone.wav"
                now = time.monotonic()
                stream = ResolvedStream("local-http", url, {"X-Meow": "a,b", "Cookie": "per-file"}, None, now, now + 60)
                response = controller.load_stream(stream)
                self.assertEqual(response["error"], "success", response)
                controller.play()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if (controller.get_property("time-pos") or 0) > 0:
                        break
                    time.sleep(.01)
                self.assertGreater(controller.get_property("time-pos") or 0, 0)
                self.assertIn("file-loaded", controller.playback_events)
                self.assertIn("playback-restart", controller.playback_events)
                self.assertEqual(requests[0].get("X-Meow"), "a,b")
                self.assertEqual(requests[0].get("Cookie"), "per-file")
                count = controller._commands
                for _ in range(100):
                    controller.get_property("time-pos")
                    controller.get_property("duration")
                    controller.get_property("pause")
                self.assertEqual(controller._commands, count)
                controller.load(url)
                deadline = time.monotonic() + 5
                while len(requests) < 2 and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertGreaterEqual(len(requests), 2)
                self.assertNotIn("Cookie", requests[-1])
                self.assertNotIn("X-Meow", requests[-1])
            finally:
                controller.quit()
                server.shutdown()
                server.server_close()
                worker.join(1)
            self.assertTrue(all(not r.is_alive() for r in controller._readers))
