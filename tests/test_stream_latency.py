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
from dataclasses import replace
from unittest import mock

from meowplayer import MPVController, MeowPlayer
from youtube_online import (YouTubeCatalog, YouTubeSearchSession, YouTubeStreamResolver,
                            YouTubeTrack, ResolvedStream, StreamResolutionError,
                            network_subprocess_env, parse_stream, resolver_command)

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
        self.play_calls = 0

    def stop(self):
        self.playback_events.clear()
        self.properties.update({"idle-active": True, "time-pos": None})

    def play(self):
        self.play_calls += 1
        self.properties["pause"] = False

    def set_property(self, name, value):
        self.properties[name] = value

    def load(self, url):
        self.loaded.append(url)
        self.playback_events.clear()
        self.properties["path"] = url

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
        self.assertIn("%(.{url,http_headers,format_id,available_at})j", command)
        result = parse_stream(track(), json.dumps({"url": "https://media.example/a",
                              "http_headers": {"Cookie": "required", "Origin": "https://youtube.com"},
                              "format_id": "251"}))
        self.assertEqual(result.headers["Cookie"], "required")
        self.assertEqual(result.format_id, "251")
        self.assertTrue(result.valid())

    def test_network_subprocess_env_preserves_existing_glibc_options(self):
        with mock.patch.dict(os.environ, {"RES_OPTIONS": "timeout:2 attempts:3"}, clear=False):
            with mock.patch("youtube_online.platform.libc_ver", return_value=("glibc", "2.40")):
                env = network_subprocess_env(PYTHONUNBUFFERED=1)
        self.assertEqual(
            env["RES_OPTIONS"],
            "timeout:2 attempts:3 single-request-reopen",
        )
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")

    def test_network_subprocess_env_does_not_duplicate_workaround(self):
        with mock.patch.dict(
            os.environ,
            {"RES_OPTIONS": "single-request-reopen timeout:1"},
            clear=False,
        ):
            with mock.patch("youtube_online.platform.libc_ver", return_value=("glibc", "2.40")):
                env = network_subprocess_env()
        self.assertEqual(
            env["RES_OPTIONS"].split().count("single-request-reopen"),
            1,
        )

    def test_network_subprocess_env_leaves_non_glibc_resolver_unchanged(self):
        with mock.patch.dict(os.environ, {"RES_OPTIONS": "timeout:2"}, clear=False):
            with mock.patch("youtube_online.platform.libc_ver", return_value=("musl", "1.2")):
                env = network_subprocess_env()
        self.assertEqual(env["RES_OPTIONS"], "timeout:2")

    def test_mpv_gets_resolver_workaround_only_when_requested(self):
        fake_env = {"RES_OPTIONS": "single-request-reopen"}
        with mock.patch("meowplayer.network_subprocess_env", return_value=fake_env) as make_env:
            with mock.patch("meowplayer.subprocess.Popen") as popen:
                popen.return_value.pid = 123
                with mock.patch("meowplayer.os.path.exists", return_value=True):
                    MPVController(network_resolver_workaround=True)
        make_env.assert_called_once_with(resolver_workaround=True)
        self.assertIs(popen.call_args.kwargs["env"], fake_env)

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
            # Unexpected early open failure gets one asynchronous same-URL
            # retry before the existing fresh-resolution/fallback sequence.
            player.mpv.playback_events.update({"end-file": time.monotonic(), "end-reason": "error"})
            player.refresh_online_playback_state()
            self.assertEqual(player.online_load_state, "waiting")
            clock = [player._online_wait_until]
            with mock.patch("meowplayer.time.monotonic", side_effect=lambda: clock[0]):
                player.refresh_online_playback_state()
                for attempt in range(2):
                    clock[0] += .05
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

    def test_resolver_subprocess_receives_glibc_workaround(self):
        executable = self.fake_executable(
            'import json,os\n'
            'assert "single-request-reopen" in os.environ.get("RES_OPTIONS","").split()\n'
            'print(json.dumps({"url":"https://media.example/audio","http_headers":{},"format_id":"251"}))\n'
        )
        with mock.patch("youtube_online.platform.libc_ver", return_value=("glibc", "2.40")):
            resolver = YouTubeStreamResolver(executable)
            self.addCleanup(resolver.close)
            self.assertEqual(resolver.resolve(track()).format_id, "251")

    def test_search_subprocess_receives_glibc_workaround(self):
        executable = self.fake_executable(
            'import json,os\n'
            'value=os.environ.get("RES_OPTIONS","")\n'
            'print(json.dumps({"id":"first","title":value}),flush=True)\n'
        )
        with mock.patch("youtube_online.platform.libc_ver", return_value=("glibc", "2.40")):
            session = YouTubeSearchSession(
                YouTubeCatalog(enabled=True, executable=executable),
                "cat",
            )
            self.addCleanup(session.close)
            kind, value = session.results.get(timeout=1)
        self.assertEqual(kind, "track")
        self.assertIn("single-request-reopen", value.title.split())

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


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ScriptedResolver:
    """No threads or sleeps; uses the same expiry/identity contract as resolver."""
    def __init__(self, clock):
        self.clock = clock
        self.cache = {}
        self.requests = []
        self.invalidated = []
        self.extractions = 0
        self.pending = None
        self.delay = 0

    def cached(self, t):
        value = self.cache.get((t.provider, t.video_id))
        return value if value and value.valid() else None

    def request(self, t, *, prefetch=False, debounce=0):
        self.requests.append((t.video_id, prefetch))
        if self.pending is not None:
            return self.pending
        value = self.cached(t)
        if value is None:
            self.extractions += 1
            now = self.clock()
            value = replace(stream(t.video_id), ready_at=now + self.delay)
            self.cache[(t.provider, t.video_id)] = value
        result = Future()
        result.set_result(value)
        return result

    def invalidate(self, t):
        self.invalidated.append(t.video_id)
        self.cache.pop((t.provider, t.video_id), None)


class ReadinessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        patcher = mock.patch("meowplayer.time.monotonic", side_effect=self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.resolver = ScriptedResolver(self.clock)
        self.mpv = FakePlayerMPV()
        self.player = player_for(self.mpv, self.resolver)

    def fail(self, error="loading failed"):
        self.clock.advance(.05)
        self.mpv.playback_events.update({"end-file": self.clock(), "end-reason": "error", "end-error": error})
        return self.player.refresh_online_playback_state()

    def progress(self):
        self.clock.advance(.05)
        self.mpv.playback_events.update({name: self.clock() for name in
            ("start-file", "file-loaded", "playback-restart", "first-nonzero-time-pos")})
        self.mpv.properties.update({"time-pos": .25, "idle-active": False})
        return self.player.refresh_online_playback_state()

    def pending_retry(self):
        self.player.play_online(track())
        self.fail()
        self.assertEqual(self.player.online_load_state, "waiting")

    def test_ready_fresh_url_has_no_delay(self):
        with mock.patch("meowplayer.time.sleep", side_effect=AssertionError("blocking sleep")):
            self.player.play_online(track())
            self.assertEqual(len(self.mpv.loaded), 1)
            self.assertEqual(self.clock(), 1000)
            self.assertTrue(self.progress())
            self.assertEqual(self.player.online_load_state, "streaming")
            self.assertEqual(self.resolver.extractions, 1)

    def test_available_at_converted_to_monotonic_and_expiry_preserved(self):
        with mock.patch("youtube_online.time.time", return_value=10000):
            value = parse_stream(track(), json.dumps({"url": "https://x/a?expire=10090", "available_at": 10004.25}))
        self.assertEqual(value.ready_at, 1004.25)
        self.assertEqual(value.expires_at, 1060)
        self.resolver.cache[("youtube", "cat")] = value
        self.player.play_online(track())
        self.assertEqual(self.player.online_load_state, "waiting")
        self.assertEqual(self.mpv.loaded, [])
        self.assertFalse(self.player.play_online(track()))
        with mock.patch("youtube_online.time.time", return_value=9999999):
            self.clock.advance(4.24)
            self.player.refresh_online_playback_state()
            self.assertEqual(self.mpv.loaded, [])
            self.clock.advance(.01)
            self.player.refresh_online_playback_state()
        self.assertEqual(self.mpv.loaded, [value])

    def test_missing_or_past_availability_is_immediate(self):
        for availability in (None, 9999):
            with self.subTest(availability=availability), mock.patch("youtube_online.time.time", return_value=10000):
                value = parse_stream(track(), json.dumps({"url": "https://x/a", "available_at": availability}))
                self.assertEqual(value.ready_at, self.clock())

    def test_invalid_availability_and_expiry_rejected(self):
        for data in ({"available_at": "nan"}, {"available_at": float("inf")},
                     {"available_at": "invalid"}, {"url": "https://x/a?expire=nan"},
                     {"available_at": 999999999999}):
            with self.subTest(data=data), self.assertRaises(StreamResolutionError):
                parse_stream(track(), json.dumps({"url": "https://x/a", **data}))

    def test_prefetched_ready_stream_starts_immediately(self):
        self.resolver.delay = 4
        value = self.resolver.request(track(), prefetch=True).result()
        self.clock.advance(5)
        self.player.play_online(track())
        self.assertEqual(self.mpv.loaded, [value])
        self.assertEqual(self.player._online_path, "cache")
        self.assertEqual(self.resolver.extractions, 1)

    def test_prefetched_not_ready_waits_only_remaining_time(self):
        self.resolver.delay = 4
        value = self.resolver.request(track(), prefetch=True).result()
        self.clock.advance(3)
        self.player.play_online(track())
        self.assertEqual(self.mpv.loaded, [])
        self.clock.advance(1)
        self.player.refresh_online_playback_state()
        self.assertEqual(self.mpv.loaded, [value])
        self.assertEqual(self.resolver.extractions, 1)

    def test_early_open_failure_retries_exact_url_once_without_extraction(self):
        self.pending_retry()
        value = self.mpv.loaded[0]
        self.clock.advance(.99)
        self.player.refresh_online_playback_state()
        self.assertEqual(len(self.mpv.loaded), 1)
        self.clock.advance(.01)
        self.player.refresh_online_playback_state()
        self.assertIs(self.mpv.loaded[1], value)
        self.assertTrue(self.progress())
        self.assertEqual(self.player.online_load_state, "streaming")
        self.assertEqual(self.resolver.extractions, 1)
        self.assertEqual(self.resolver.invalidated, [])

    def test_repeated_failures_stop_after_same_url_fresh_and_fallback(self):
        self.pending_retry()
        self.clock.advance(1)
        self.player.refresh_online_playback_state()
        self.fail()
        self.assertEqual(self.player.online_load_state, "resolving")
        self.player.refresh_online_playback_state()
        self.fail()
        self.assertEqual(self.player._online_path, "mpv-fallback")
        self.fail()
        self.assertEqual(self.player.online_load_state, "failed")
        self.assertEqual(len(self.mpv.loaded), 4)
        self.assertEqual(self.resolver.extractions, 2)
        self.clock.advance(100)
        self.assertFalse(self.player.refresh_online_playback_state())
        self.assertEqual(len(self.mpv.loaded), 4)

    def test_expiry_before_retry_requires_new_url(self):
        self.resolver.cache[("youtube", "cat")] = replace(stream(), expires_at=self.clock() + .5)
        self.player.play_online(track())
        old = self.mpv.loaded[0]
        self.fail()
        self.assertEqual(self.player.online_load_state, "resolving")
        self.player.refresh_online_playback_state()
        self.assertIsNot(self.mpv.loaded[-1], old)
        self.assertEqual(self.resolver.invalidated, ["cat"])

    def test_expiry_while_waiting_requires_resolution(self):
        self.resolver.delay = 4
        self.player.play_online(track())
        self.clock.advance(61)
        self.player.refresh_online_playback_state()
        self.assertEqual(self.player.online_load_state, "resolving")
        self.assertEqual(self.mpv.loaded, [])
        self.player.refresh_online_playback_state()
        self.clock.advance(4)
        self.player.refresh_online_playback_state()
        self.assertEqual(len(self.mpv.loaded), 1)
        self.assertEqual(self.resolver.extractions, 2)

    def test_switch_track_revokes_pending_retry(self):
        self.pending_retry()
        self.player.play_online(track("other"))
        self.clock.advance(10)
        self.player.refresh_online_playback_state()
        self.assertEqual([s.video_id for s in self.mpv.loaded], ["cat", "other"])

    def test_old_resolution_cannot_replace_new_selection(self):
        old = self.resolver.pending = Future()
        self.player.play_online(track())
        new = self.resolver.pending = Future()
        self.player.play_online(track("other"))
        old.set_result(stream())
        self.assertFalse(self.player.refresh_online_playback_state())
        new.set_result(stream("other"))
        self.player.refresh_online_playback_state()
        self.assertEqual([s.video_id for s in self.mpv.loaded], ["other"])

    def test_stop_cancels_retry_and_explicit_play_can_resume(self):
        self.pending_retry()
        self.player.external_actions = queue.SimpleQueue()
        self.player.external_actions.put(("stop", ()))
        self.player.process_external_actions()
        self.clock.advance(10)
        self.assertFalse(self.player.refresh_online_playback_state())
        self.assertIsNone(self.player._online_stream)
        self.assertEqual(len(self.mpv.loaded), 1)
        self.player.play_online(track())
        self.assertEqual(len(self.mpv.loaded), 2)

    def test_local_selection_cancels_pending_retry(self):
        from test_audio import AudioEngineTests
        player = AudioEngineTests().make_player()
        player.stream_resolver = self.resolver
        player.mpv.load_stream = mock.Mock(return_value={"error": "success"})
        player.mpv.playback_events = {}
        player.play_online(track())
        self.clock.advance(.05)
        player.mpv.playback_events.update({"end-file": self.clock(), "end-reason": "error"})
        player.refresh_online_playback_state()
        self.assertEqual(player.online_load_state, "waiting")
        player.play(1)
        self.clock.advance(10)
        self.assertFalse(player.refresh_online_playback_state())
        self.assertIsNone(player._online_stream)
        self.assertEqual(player.mpv.loaded, [player.songs[1]])
        self.assertEqual(player.mpv.load_stream.call_count, 1)

    def test_shutdown_cancels_retry(self):
        self.pending_retry()
        self.player.persist_state = mock.Mock()
        self.player.playback_saboteur = mock.Mock()
        self.player.youtube_search_session = None
        self.player.youtube_download_session = None
        self.player.creator_session = None
        self.player.catalog = None
        for name in ("youtube", "stream_resolver", "online_metadata", "mpris", "library_watcher", "album_art", "visualizer"):
            setattr(self.player, name, mock.Mock())
        self.mpv.quit = mock.Mock()
        self.player.shutdown()
        self.clock.advance(10)
        self.assertFalse(self.player.refresh_online_playback_state())
        self.assertFalse(self.player._start_online_stream())
        self.assertFalse(self.player.play_online(track("other")))
        self.assertIsNone(self.player._online_stream)
        self.assertEqual(len(self.mpv.loaded), 1)
        self.player.stream_resolver.close.assert_called_once()

    def test_non_open_errors_and_timeout_skip_same_url_retry(self):
        for error in ("audio output initialization failed", "unrecognized file format", "timeout"):
            with self.subTest(error=error):
                self.player.online_current = None
                self.player.play_online(track())
                if error == "timeout":
                    self.clock.advance(31)
                    self.player.refresh_online_playback_state()
                else:
                    self.fail(error)
                self.assertEqual(self.player.online_load_state, "resolving")
                self.assertEqual(self.player._online_same_url_retry, 0)

    def test_error_after_progress_does_not_restart_track(self):
        self.player.play_online(track())
        self.mpv.playback_events["first-nonzero-time-pos"] = self.clock()
        self.fail()
        self.assertEqual(self.player.online_load_state, "failed")
        self.assertEqual(len(self.mpv.loaded), 1)

    def test_normal_eof_before_first_refresh_does_not_retry(self):
        self.player.play_online(track())
        self.clock.advance(.1)
        self.mpv.playback_events.update({"end-file": self.clock(), "end-reason": "eof"})
        self.player.refresh_online_playback_state()
        self.assertEqual(self.player.online_load_state, "idle")
        self.clock.advance(31)
        self.assertFalse(self.player.refresh_online_playback_state())
        self.assertEqual(len(self.mpv.loaded), 1)
        self.assertEqual(self.resolver.extractions, 1)

    def test_short_playlist_track_advances_without_startup_retry(self):
        self.player.play_online(track(), playlist_tracks=[track(), track("next")], playlist_index=0)
        self.clock.advance(.1)
        self.mpv.playback_events.update({"end-file": self.clock(), "end-reason": "eof"})
        self.player.refresh_online_playback_state()
        self.assertEqual(self.player.online_playlist_index, 1)
        self.assertEqual(self.mpv.loaded[-1].video_id, "next")
        self.assertEqual(self.player._online_retry, 0)

    def test_pause_during_availability_wait_is_preserved(self):
        self.resolver.delay = 4
        self.player.play_online(track())
        self.player.set_playback_paused(True)
        self.clock.advance(4)
        self.player.refresh_online_playback_state()
        self.assertTrue(self.mpv.properties["pause"])
        self.clock.advance(31)
        self.player.refresh_online_playback_state()
        self.assertEqual(self.player.online_load_state, "loading")
        self.player.set_playback_paused(False)
        self.assertTrue(self.progress())

    def test_external_pause_toggle_and_play_during_wait(self):
        self.resolver.delay = 4
        self.player.play_online(track())
        self.player.external_actions = queue.SimpleQueue()
        for action, expected in (("pause", True), ("play_pause", False), ("play_pause", True), ("play", False)):
            with self.subTest(action=action):
                self.player.external_actions.put((action, ()))
                self.player.process_external_actions()
                self.assertEqual(self.mpv.properties["pause"], expected)
                self.assertEqual(self.player._online_start_paused, expected)
                self.assertEqual(self.mpv.loaded, [])

    def test_playlist_prefetch_and_eof_advance_after_recovery(self):
        self.player.play_online(track(), playlist_tracks=[track(), track("next")], playlist_index=0)
        self.fail()
        self.clock.advance(1)
        self.player.refresh_online_playback_state()
        self.progress()
        self.player.refresh_online_playback_state()
        self.assertIn(("next", True), self.resolver.requests)
        self.clock.advance(.1)
        self.mpv.playback_events.update({"end-file": self.clock(), "end-reason": "eof"})
        self.player.refresh_online_playback_state()
        self.assertEqual(self.player.online_playlist_index, 1)
        self.assertEqual(self.mpv.loaded[-1].video_id, "next")
        self.assertEqual(self.player._online_path, "cache")
        self.assertEqual(self.player._online_attempt, 1)
        self.assertEqual(self.player._online_same_url_retry, 0)

    def test_diagnostics_exclude_signed_urls_and_headers(self):
        self.resolver.delay = 1
        with self.assertLogs("meowplayer", level="DEBUG") as logged:
            self.player.play_online(track())
            self.clock.advance(1)
            self.player.refresh_online_playback_state()
            self.fail()
        output = "\n".join(logged.output)
        self.assertIn("stream_age_ms=", output)
        self.assertIn("retry_delay_ms=", output)
        self.assertIn("playback_attempt=", output)
        self.assertNotIn("secret=hidden", output)
        self.assertNotIn("media.example", output)
        self.assertNotIn("User-Agent", output)


class IPCConcurrencyTests(unittest.TestCase):
    def test_error_ownership_across_same_url_retry_and_next_entry(self):
        controller = MPVController.__new__(MPVController)
        controller._init_ipc()
        controller._close_ipc = mock.Mock()
        def events(*messages):
            sock = mock.Mock()
            sock.recv.side_effect = [b"".join(json.dumps(m).encode() + b"\n" for m in messages), b""]
            controller._ipc_socket = sock
            controller._read_ipc(sock)
        events({"event": "start-file", "playlist_entry_id": 10},
               {"event": "end-file", "playlist_entry_id": 10, "reason": "error", "file_error": "loading failed"})
        self.assertEqual(controller.playback_events["end-error"], "loading failed")
        self.assertFalse(controller._load_pending)
        for entry in (11, 12):
            controller.begin_load()
            events({"event": "start-file", "playlist_entry_id": entry},
                   {"event": "end-file", "playlist_entry_id": entry - 1, "reason": "error", "file_error": "loading failed"},
                   {"event": "file-loaded"}, {"event": "playback-restart"})
            self.assertNotIn("end-file", controller.playback_events)
            self.assertNotIn("end-error", controller.playback_events)
            self.assertEqual(controller.playback_events["entry-id"], entry)
        events({"event": "end-file", "playlist_entry_id": 12, "reason": "eof"})
        self.assertEqual(controller.playback_events["end-reason"], "eof")

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
