"""Offline resolver/state tests; live YouTube is never a CI dependency."""
import json
import os
from pathlib import Path
import queue
import socket
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from unittest import mock

from meowplayer import MPVController, MeowPlayer
from youtube_online import (YouTubeCatalog, YouTubeSearchSession, YouTubeStreamResolver,
                            YouTubeTrack, ResolvedStream, StreamResolutionError,
                            parse_stream, resolver_command)

def player_for(mpv, resolver):
    player = MeowPlayer.__new__(MeowPlayer)
    player.mpv = mpv
    player.stream_resolver = resolver
    player.online_current = None
    player.online_load_state = "idle"
    player.online_load_started_at = 0
    player.sync_mpris = lambda **kw: None
    player.set_status = lambda *args: None
    return player



def track(video_id="cat"):
    return YouTubeTrack(video_id, "Cat", "Artist", 10, f"https://www.youtube.com/watch?v={video_id}")


def stream(video_id="cat"):
    now = time.monotonic()
    return ResolvedStream(video_id, "https://media.example/audio?secret=hidden",
                          {"User-Agent": "Cat", "Referer": "https://www.youtube.com/"}, "251", now, now + 60)


class FakePlayerMPV:
    def __init__(self):
        self.loaded = []
        self.playback_events = {}
        self.properties = {"idle-active": True, "time-pos": None}

    def stop(self):
        pass

    def play(self):
        pass

    def load(self, url):
        self.loaded.append(url)

    def load_stream(self, result):
        self.loaded.append(result)
        self.properties["path"] = result.url
        self.playback_events.clear()
        return {"error": "success"}

    def get_property(self, name):
        return self.properties.get(name)


class StreamTests(unittest.TestCase):
    def resolver(self, **kwargs):
        resolver = YouTubeStreamResolver("fake", **kwargs)
        self.addCleanup(resolver.close)
        return resolver

    def test_command_and_required_headers(self):
        command = resolver_command("yt-dlp", track())
        self.assertIn("--ignore-config", command)
        self.assertIn("--skip-download", command)
        self.assertIn("--no-playlist", command)
        self.assertIn("%(.{url,http_headers,format_id})j", command)
        result = parse_stream(track(), json.dumps({"url": "https://media.example/a",
                              "http_headers": {"Cookie": "required", "Origin": "https://youtube.com"},
                              "format_id": "251"}))
        self.assertEqual(result.headers["Cookie"], "required")
        self.assertEqual(result.format_id, "251")
        self.assertTrue(result.valid())

    def test_expiry_and_invalid_output(self):
        result = parse_stream(track(), json.dumps({"url": f"https://m.example/a?expire={time.time()+40}"}))
        self.assertLessEqual(result.expires_at - result.resolved_at, 10)
        self.assertFalse(result.valid(result.expires_at))
        for output in ['{}', 'bad json', '{"url":"file:///etc/passwd"}',
                       '{"url":"https://m.example/a?expire=1"}',
                       '{"url":"https://m.example/a","http_headers":{"X":"a\\nb"}}']:
            with self.assertRaises(StreamResolutionError):
                parse_stream(track(), output)

    def test_deduplication_cache_expiration_and_lru(self):
        resolver = self.resolver(capacity=1)
        entered, release = threading.Event(), threading.Event()
        def extract(t, cancel):
            entered.set()
            release.wait(1)
            return stream(t.video_id)
        with mock.patch.object(resolver, "_extract", side_effect=extract) as extract_mock:
            first = resolver.request(track(), prefetch=True)
            self.assertTrue(entered.wait(1))
            self.assertIs(resolver.request(track()), first)
            release.set()
            value = first.result(1)
            self.assertIs(resolver.resolve(track()), value)
            self.assertEqual(extract_mock.call_count, 1)
            resolver.resolve(track("second"))
            self.assertIsNone(resolver.cached(track()))
            resolver._cache[("youtube", "old")] = ResolvedStream("old", "https://x", {}, None, 0, 0)
            self.assertIsNone(resolver.cached(track("old")))
            resolver.invalidate(track("second"))
            self.assertIsNone(resolver.cached(track("second")))

    def test_rapid_selection_debounce_only_resolves_last(self):
        resolver = self.resolver()
        with mock.patch.object(resolver, "_extract", side_effect=lambda t, c: stream(t.video_id)) as extract:
            futures = [resolver.request(track(str(i)), prefetch=True, debounce=.15) for i in range(4)]
            self.assertEqual(futures[-1].result(1).video_id, "3")
            self.assertTrue(all(f.cancelled() for f in futures[:-1]))
            self.assertEqual(extract.call_count, 1)

    def test_enter_removes_debounce_and_shares_prefetch(self):
        resolver = self.resolver()
        with mock.patch.object(resolver, "_extract", return_value=stream()):
            future = resolver.request(track(), prefetch=True, debounce=60)
            self.assertIs(future, resolver.request(track()))
            self.assertEqual(future.result(1).video_id, "cat")

    def test_enter_during_prefetch_and_duplicate_enter(self):
        resolver = self.resolver()
        entered, release = threading.Event(), threading.Event()
        def extract(t, cancel):
            entered.set()
            release.wait(1)
            return stream()
        with mock.patch.object(resolver, "_extract", side_effect=extract) as extract_mock:
            future = resolver.request(track(), prefetch=True)
            self.assertTrue(entered.wait(1))
            player = player_for(FakePlayerMPV(), resolver)
            self.assertTrue(player.play_online(track()))
            self.assertFalse(player.play_online(track()))
            self.assertEqual(player.mpv.loaded, [])
            release.set()
            future.result(1)
            player.refresh_online_playback_state()
            self.assertEqual(len(player.mpv.loaded), 1)
            self.assertEqual(player.online_load_state, "loading")
            self.assertEqual(extract_mock.call_count, 1)
            self.assertFalse(player.play_online(track()))

    def test_cached_enter_loads_direct_and_requires_playback_evidence(self):
        resolver = self.resolver()
        with mock.patch.object(resolver, "_extract", return_value=stream()) as extract:
            resolver.resolve(track())
            player = player_for(FakePlayerMPV(), resolver)
            player.play_online(track())
            self.assertEqual(player._online_path, "cache")
            self.assertIsInstance(player.mpv.loaded[0], ResolvedStream)
            self.assertEqual(extract.call_count, 1)
            now = time.monotonic()
            player.mpv.playback_events = {"start-file": now, "file-loaded": now}
            player.mpv.properties.update({"time-pos": 0, "idle-active": False, "duration": 50})
            self.assertFalse(player.refresh_online_playback_state())
            player.mpv.playback_events["playback-restart"] = now
            player.mpv.properties["time-pos"] = .1
            player.mpv.properties["path"] = "https://old.example/previous"
            self.assertFalse(player.refresh_online_playback_state())
            player.mpv.properties["path"] = stream().url
            self.assertTrue(player.refresh_online_playback_state())
            self.assertEqual(player.online_load_state, "streaming")

    def test_failure_falls_back(self):
        resolver = self.resolver()
        with mock.patch.object(resolver, "_extract", side_effect=StreamResolutionError("offline")):
            player = player_for(FakePlayerMPV(), resolver)
            player.play_online(track())
            try:
                player._online_future.result(1)
            except StreamResolutionError:
                pass
            player.refresh_online_playback_state()
            self.assertEqual(player.mpv.loaded, [track().url])
            self.assertEqual(player._online_path, "mpv-fallback")

    def test_rejected_stream_resolves_once_then_fallback(self):
        resolver = self.resolver()
        with mock.patch.object(resolver, "_extract", return_value=stream()) as extract:
            resolver.resolve(track())
            player = player_for(FakePlayerMPV(), resolver)
            player.play_online(track())
            for attempt in range(2):
                player.mpv.playback_events.update({"end-file": time.monotonic(), "end-reason": "error"})
                player.refresh_online_playback_state()
                if attempt == 0:
                    player._online_future.result(1)
                    player.refresh_online_playback_state()
            self.assertEqual(extract.call_count, 2)
            self.assertEqual(player._online_path, "mpv-fallback")
            self.assertEqual(player.mpv.loaded[-1], track().url)

    def test_returning_to_cached_selection_cancels_stale_queue(self):
        resolver = self.resolver()
        with mock.patch.object(resolver, "_extract", return_value=stream()):
            resolver.resolve(track())
            pending = resolver.request(track("other"), prefetch=True, debounce=60)
            self.assertEqual(resolver.request(track(), prefetch=True).result().video_id, "cat")
            self.assertTrue(pending.cancelled())
            self.assertIsNone(resolver._next)

    def test_enter_queued_selection_cancels_unrelated_active_prefetch(self):
        resolver = self.resolver()
        entered = threading.Event()
        def extract(t, cancel):
            if t.video_id == "first":
                entered.set()
                self.assertTrue(cancel.wait(1))
                raise StreamResolutionError("superseded")
            return stream(t.video_id)
        with mock.patch.object(resolver, "_extract", side_effect=extract):
            resolver.request(track("first"), prefetch=True)
            self.assertTrue(entered.wait(1))
            pending = resolver.request(track("second"), prefetch=True, debounce=60)
            self.assertIs(resolver.request(track("second")), pending)
            self.assertEqual(pending.result(1).video_id, "second")

    def test_local_switch_does_not_apply_late_resolve(self):
        resolver = self.resolver()
        player = player_for(FakePlayerMPV(), resolver)
        future = Future()
        player.online_current = track()
        player.online_load_state = "resolving"
        player._online_future = future
        player.online_current = None  # local play clears online identity
        future.set_result(stream())
        self.assertFalse(player.refresh_online_playback_state())
        self.assertEqual(player.mpv.loaded, [])

    def test_close_cancels_worker_and_queued_job(self):
        resolver = self.resolver()
        entered = threading.Event()
        def extract(t, cancel):
            entered.set()
            cancel.wait(2)
            raise StreamResolutionError("cancelled")
        with mock.patch.object(resolver, "_extract", side_effect=extract):
            active = resolver.request(track())
            self.assertTrue(entered.wait(1))
            pending = resolver.request(track("next"), prefetch=True)
            resolver.close()
            self.assertFalse(resolver._thread.is_alive())
            self.assertTrue(pending.cancelled())
            self.assertTrue(active.done())

    def fake_executable(self, script):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "yt-dlp"
        path.write_text(f"#!{sys.executable}\n" + script)
        path.chmod(0o755)
        return str(path)

    def test_real_subprocess_timeout(self):
        resolver = YouTubeStreamResolver(self.fake_executable("import time\ntime.sleep(30)\n"), timeout=.15)
        self.addCleanup(resolver.close)
        with self.assertRaises(StreamResolutionError):
            resolver.resolve(track())
        resolver.close()
        self.assertFalse(resolver._thread.is_alive())

    def test_background_search_delivers_before_process_exits(self):
        executable = self.fake_executable(
            'import json,time\nprint(json.dumps({"id":"first","title":"First"}),flush=True)\n'
            'time.sleep(.3)\nprint(json.dumps({"id":"second","title":"Second"}),flush=True)\n')
        session = YouTubeSearchSession(YouTubeCatalog(enabled=True, executable=executable), "cat")
        self.addCleanup(session.close)
        kind, value = session.results.get(timeout=1)
        self.assertEqual((kind, value.video_id), ("track", "first"))
        self.assertTrue(session.thread.is_alive())
        self.assertEqual(session.results.get(timeout=1)[1].video_id, "second")
        self.assertEqual(session.results.get(timeout=1)[0], "done")


class IPCConcurrencyTests(unittest.TestCase):
    def test_interleaved_replies_partial_frames_and_observations(self):
        client, server = socket.socketpair()
        controller = MPVController.__new__(MPVController)
        controller._init_ipc()
        controller._ipc_socket = client
        reader = threading.Thread(target=controller._read_ipc, args=(client,))
        reader.start()
        def serve():
            with server.makefile("rb") as incoming:
                requests = [json.loads(incoming.readline()) for _ in range(2)]
                payload = b'{"event":"property-change","name":"time-pos","data":0.5}\n'
                for request in reversed(requests):
                    payload += json.dumps({"request_id": request["request_id"], "data": request["command"][1]}).encode() + b"\n"
                server.sendall(payload[:17])
                server.sendall(payload[17:])
        worker = threading.Thread(target=serve)
        worker.start()
        try:
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(controller.command, "get_property", "first")
                second = pool.submit(controller.command, "get_property", "second")
                self.assertEqual(first.result(2)["data"], "first")
                self.assertEqual(second.result(2)["data"], "second")
            self.assertEqual(controller.get_property("time-pos"), .5)
            self.assertEqual(controller._commands, 2)
        finally:
            controller._closing = True
            controller._close_ipc()
            server.close()
            reader.join(1)
            worker.join(1)
        self.assertFalse(reader.is_alive())

    def test_socket_reconnect_resubscribes_without_replaying_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            server = socket.socket(socket.AF_UNIX)
            path = str(Path(directory) / "mpv.sock")
            server.bind(path)
            server.listen()
            seen = []
            def serve():
                for _ in range(2):
                    conn, _ = server.accept()
                    with conn, conn.makefile("rb") as incoming:
                        for line in incoming:
                            request = json.loads(line)
                            seen.append(request["command"][0])
                            if request["command"][0] != "observe_property":
                                conn.sendall(json.dumps({"request_id": request["request_id"], "error": "success"}).encode() + b"\n")
                                break
            worker = threading.Thread(target=serve)
            worker.start()
            controller = MPVController.__new__(MPVController)
            controller.socket_path = path
            controller._init_ipc()
            try:
                self.assertEqual(controller.command("stop")["error"], "success")
                controller._close_ipc()
                self.assertEqual(controller.command("stop")["error"], "success")
                self.assertEqual(seen.count("stop"), 2)
                self.assertEqual(seen.count("observe_property"), 2 * len(controller.OBSERVED_PROPERTIES))
            finally:
                controller._closing = True
                controller._close_ipc()
                for reader in controller._readers:
                    reader.join(1)
                server.close()
                worker.join(1)


if __name__ == "__main__":
    unittest.main()
