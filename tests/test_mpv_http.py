"""Opt-in real mpv/HTTP integration; only loopback traffic, never YouTube."""
import functools
from concurrent.futures import Future
from dataclasses import replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import wave
from unittest import mock

from meowplayer import MPVController, build_mpv_command
from youtube_online import ResolvedStream
from test_stream_latency import player_for, track


@unittest.skipUnless(os.environ.get("MEOW_REAL_MPV") == "1", "opt-in real mpv integration")
class MPVHTTPTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required for local format integration")
    def test_local_formats_gapless_pause_seek_stop_and_replaygain(self):
        with tempfile.TemporaryDirectory() as directory:
            files = [Path(directory) / f"tone.{ext}" for ext in ("flac", "mp3", "opus")]
            for path in files:
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                                "anullsrc=r=48000:cl=stereo", "-t", "3", str(path)],
                               check=True, capture_output=True, timeout=10)
            with mock.patch("meowplayer.build_mpv_command", side_effect=lambda *a, **k:
                            build_mpv_command(*a, **k) + ["--no-config", "--ao=null"]):
                controller = MPVController()
            def wait_for(condition):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if condition():
                        return
                    time.sleep(.01)
                self.fail("mpv did not reach expected local playback state")
            try:
                for index, path in enumerate(files):
                    if index == 0:
                        controller.load(path)
                        controller.play()
                    wait_for(lambda: controller.get_property("path") == str(path)
                             and (controller.get_property("time-pos") or 0) > 0)
                    self.assertEqual(controller.get_property("replaygain"), "track")
                    controller.pause()
                    wait_for(lambda: controller.get_property("pause") is True)
                    controller.seek_absolute(.5)
                    wait_for(lambda: (controller.get_property("time-pos") or 0) >= .4)
                    controller.play()
                    wait_for(lambda: controller.get_property("pause") is False)
                    if index + 1 < len(files):
                        self.assertTrue(controller.prime_next(files[index + 1]))
                        controller.seek_absolute(2.8)
                        # Real EOF handoff to the reserved native playlist entry.
                controller.stop()
                wait_for(lambda: controller.get_property("idle-active") is True)
                self.assertEqual(controller.playback_snapshot(), {})
            finally:
                controller.quit()

    def test_real_403_readiness_recovery_and_bounded_failure(self):
        for mode in ("available_at", "early_403", "always_403"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                audio = Path(directory) / "tone.wav"
                with wave.open(str(audio), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(8000)
                    output.writeframes(b"\0\0" * 8000 * 3)
                requests = []
                ready_at = time.monotonic() + .5
                class Handler(SimpleHTTPRequestHandler):
                    def do_GET(self):
                        now = time.monotonic()
                        rejected = mode == "always_403" or now < ready_at
                        requests.append((now, rejected, dict(self.headers)))
                        if rejected:
                            self.send_error(403)
                        else:
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
                    # Start availability relative to the completed mpv launch,
                    # keeping slow hosts deterministic enough for integration.
                    ready_at = now + .3
                    value = ResolvedStream("cat", url, {"X-Meow": "per-file"}, "wav", now, now + 60,
                                           ready_at if mode == "available_at" else 0)
                    class Resolver:
                        extractions = 0
                        cached_value = None
                        def cached(self, t):
                            return self.cached_value
                        def request(self, t, **kw):
                            if self.cached_value is None:
                                self.extractions += 1
                                self.cached_value = replace(value, resolved_at=time.monotonic())
                            future = Future()
                            future.set_result(self.cached_value)
                            return future
                        def invalidate(self, t):
                            self.cached_value = None
                    resolver = Resolver()
                    player = player_for(controller, resolver)
                    if mode == "always_403":
                        # Watch-URL fallback also goes to the loopback server.
                        selected = replace(track(), url=url)
                    else:
                        selected = track()
                    player.play_online(selected)
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        player.refresh_online_playback_state()
                        if player.online_load_state in {"streaming", "failed"}:
                            break
                        time.sleep(.01)
                    if mode == "always_403":
                        self.assertEqual(player.online_load_state, "failed")
                        self.assertEqual(player._online_path, "mpv-fallback")
                        self.assertEqual(player._online_attempt, 4)
                        self.assertEqual(resolver.extractions, 2)
                        self.assertTrue(all(rejected for _, rejected, _ in requests))
                    else:
                        self.assertEqual(player.online_load_state, "streaming")
                        self.assertGreater(controller.get_property("time-pos"), 0)
                        self.assertEqual(resolver.extractions, 1)
                        self.assertEqual(requests[-1][2].get("X-Meow"), "per-file")
                        if mode == "available_at":
                            self.assertGreaterEqual(requests[0][0], ready_at)
                            self.assertFalse(any(rejected for _, rejected, _ in requests))
                            self.assertEqual(player._online_attempt, 1)
                        else:
                            self.assertTrue(requests[0][1])
                            self.assertFalse(requests[-1][1])
                            self.assertEqual(player._online_attempt, 2)
                finally:
                    controller.quit()
                    server.shutdown()
                    server.server_close()
                    worker.join(1)
                self.assertTrue(all(not r.is_alive() for r in controller._readers))

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
