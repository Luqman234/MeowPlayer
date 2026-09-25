import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from lyrics_support import (
    LyricsFetchResult,
    LyricsManager,
    _fetch_lrclib_result,
    parse_lrc,
    parse_plain_lyrics,
)


class LyricsTests(unittest.TestCase):
    def test_lrc_parser_handles_multiple_timestamps(self):
        document = parse_lrc(
            "[00:01.00][00:03.50]Hello cat\n"
            "[00:05.00]Second line"
        )

        self.assertIsNotNone(document)
        self.assertTrue(document.synced)
        self.assertEqual(
            [round(line.time, 2) for line in document.lines],
            [1.0, 3.5, 5.0],
        )
        self.assertEqual(
            [line.text for line in document.lines],
            ["Hello cat", "Hello cat", "Second line"],
        )

    def test_lrc_offset_is_applied(self):
        document = parse_lrc(
            "[offset:500]\n"
            "[00:01.00]Shifted"
        )

        self.assertAlmostEqual(document.lines[0].time, 1.5)

    def test_current_line_follows_playback_position(self):
        document = parse_lrc(
            "[00:01.00]One\n"
            "[00:04.00]Two\n"
            "[00:08.00]Three"
        )

        self.assertEqual(document.current_line(0.0), "")
        self.assertEqual(document.current_line(1.0), "One")
        self.assertEqual(document.current_line(4.5), "Two")
        self.assertEqual(document.current_line(99.0), "Three")

    def test_plain_lyrics_are_unsynchronized(self):
        document = parse_plain_lyrics("first\n\nsecond")

        self.assertFalse(document.synced)
        self.assertEqual(
            [line.text for line in document.lines],
            ["first", "second"],
        )

    def test_sidecar_added_later_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "song.flac"
            track.write_bytes(b"not-real-audio")

            manager = LyricsManager(enabled=True, online_enabled=False)
            self.assertIsNone(manager.load(track))

            (root / "song.lrc").write_text(
                "[00:01.00]Arrived later\n",
                encoding="utf-8",
            )
            document = manager.load(track)

            self.assertIsNotNone(document)
            self.assertEqual(document.current_line(2.0), "Arrived later")

    def test_sidecar_lrc_has_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "song.flac"
            track.write_bytes(b"not-real-audio")
            (root / "song.lrc").write_text(
                "[00:01.00]Sidecar lyric\n",
                encoding="utf-8",
            )
            (root / "song.txt").write_text(
                "Plain fallback",
                encoding="utf-8",
            )

            manager = LyricsManager(enabled=True, online_enabled=False)
            document = manager.load(track)

            self.assertIsNotNone(document)
            self.assertTrue(document.synced)
            self.assertEqual(document.current_line(2.0), "Sidecar lyric")
            self.assertIn("song.lrc", document.source)


    def test_downloaded_lrc_is_cached_and_reused_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "Artist - Song.flac"
            track.write_bytes(b"not-real-audio")
            cache_dir = root / "cache"

            with mock.patch(
                "lyrics_support._fetch_lrclib_result",
                return_value=LyricsFetchResult(
                    "[00:01.00]Downloaded line\n",
                    "found",
                    "Artist Song",
                ),
            ) as fetch:
                manager = LyricsManager(
                    enabled=True,
                    online_enabled=True,
                    cache_dir=cache_dir,
                    request_timeout=0.25,
                )
                self.assertIsNone(manager.load(track))
                document = None
                for _ in range(100):
                    document = manager.poll(track)
                    if document is not None:
                        break
                    time.sleep(0.01)

            self.assertIsNotNone(document)
            self.assertTrue(document.synced)
            self.assertEqual(document.current_line(2.0), "Downloaded line")
            self.assertEqual(document.source, "LRCLIB · downloaded")
            fetch.assert_called_once()
            self.assertEqual(len(list(cache_dir.glob("*.lrc"))), 1)

            offline = LyricsManager(
                enabled=True,
                online_enabled=False,
                cache_dir=cache_dir,
            )
            cached = offline.load(track)

            self.assertIsNotNone(cached)
            self.assertTrue(cached.synced)
            self.assertEqual(cached.current_line(2.0), "Downloaded line")
            self.assertEqual(cached.source, "LRCLIB cache")

    def test_transient_lrclib_lyrics_are_session_only_and_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "cache"

            with mock.patch(
                "lyrics_support._fetch_lrclib_result",
                return_value=LyricsFetchResult(
                    "[00:01.00]Internet line\n",
                    "found",
                    "Internet Artist Online Track",
                ),
            ) as fetch:
                manager = LyricsManager(
                    enabled=True,
                    online_enabled=True,
                    cache_dir=cache_dir,
                    request_timeout=0.25,
                )
                self.assertIsNone(
                    manager.load_transient(
                        "video-123",
                        title="Online Track",
                        artist="Internet Artist",
                        duration=180,
                    )
                )

                document = None
                for _ in range(100):
                    document = manager.poll_transient("video-123")
                    if document is not None:
                        break
                    time.sleep(0.01)

            self.assertIsNotNone(document)
            self.assertTrue(document.synced)
            self.assertEqual(document.current_line(2.0), "Internet line")
            self.assertEqual(document.source, "LRCLIB · Internet Nest")
            self.assertEqual(
                manager.transient_status("video-123")["status"],
                "found",
            )
            fetch.assert_called_once()
            self.assertFalse(cache_dir.exists())

    def test_online_status_reports_searching_then_found(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "Artist - Song.flac"
            track.write_bytes(b"not-real-audio")

            release = mock.Mock()

            def delayed_fetch(metadata, timeout):
                release()
                time.sleep(0.03)
                return LyricsFetchResult(
                    "[00:01.00]Found online\n",
                    "found",
                    "Artist Song",
                )

            with mock.patch(
                "lyrics_support._fetch_lrclib_result",
                side_effect=delayed_fetch,
            ):
                manager = LyricsManager(
                    enabled=True,
                    online_enabled=True,
                    cache_dir=root / "cache",
                    request_timeout=0.25,
                )
                self.assertIsNone(manager.load(track))

                state = manager.online_status(track)
                self.assertEqual(state["status"], "searching")

                document = None
                for _ in range(100):
                    document = manager.poll(track)
                    if document is not None:
                        break
                    time.sleep(0.01)

            self.assertIsNotNone(document)
            self.assertEqual(manager.online_status(track)["status"], "found")

    def test_transient_network_failure_is_retried_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "Artist - Song.flac"
            track.write_bytes(b"not-real-audio")

            with mock.patch(
                "lyrics_support._fetch_lrclib_result",
                side_effect=[
                    LyricsFetchResult("", "network-error", "Artist Song"),
                    LyricsFetchResult(
                        "[00:01.00]Retry worked\n",
                        "found",
                        "Artist Song",
                    ),
                ],
            ) as fetch:
                manager = LyricsManager(
                    enabled=True,
                    online_enabled=True,
                    cache_dir=root / "cache",
                    request_timeout=0.25,
                )
                self.assertIsNone(manager.load(track))

                document = None
                for _ in range(100):
                    document = manager.poll(track)
                    if document is not None:
                        break
                    time.sleep(0.01)

            self.assertIsNotNone(document)
            self.assertEqual(document.current_line(2.0), "Retry worked")
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(manager.online_status(track)["attempts"], 2)

    def test_failed_lookup_does_not_cache_none_forever(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "Artist - Song.flac"
            track.write_bytes(b"not-real-audio")

            first = LyricsFetchResult("", "not-found", "Artist Song")
            second = LyricsFetchResult(
                "[00:01.00]Second lookup worked\n",
                "found",
                "Artist Song",
            )

            with mock.patch(
                "lyrics_support._fetch_lrclib_result",
                side_effect=[first, second],
            ) as fetch:
                manager = LyricsManager(
                    enabled=True,
                    online_enabled=True,
                    cache_dir=root / "cache",
                    request_timeout=0.25,
                )
                self.assertIsNone(manager.load(track))

                for _ in range(100):
                    manager.poll(track)
                    if manager.online_status(track)["status"] == "not-found":
                        break
                    time.sleep(0.01)

                self.assertEqual(
                    manager.online_status(track)["status"],
                    "not-found",
                )

                self.assertIsNone(manager.load(track))
                document = None
                for _ in range(100):
                    document = manager.poll(track)
                    if document is not None:
                        break
                    time.sleep(0.01)

            self.assertEqual(fetch.call_count, 2)
            self.assertIsNotNone(document)
            self.assertEqual(
                document.current_line(2.0),
                "Second lookup worked",
            )

    def test_lrclib_search_falls_back_to_filename_stem(self):
        metadata = {
            "title": "Wrong Tagged Title",
            "artist": "Wrong Tagged Artist",
            "album": "",
            "duration": 0.0,
            "filename_stem": "Correct Artist - Correct Song",
        }
        calls = []

        def fake_request(path, params, timeout):
            calls.append((path, dict(params)))
            if path == "/api/get":
                return None, "not-found"
            if params.get("q") == "Correct Artist - Correct Song":
                return [
                    {
                        "syncedLyrics": "[00:01.00]Correct result",
                    }
                ], "ok"
            return [], "ok"

        with mock.patch(
            "lyrics_support._lrclib_request",
            side_effect=fake_request,
        ):
            result = _fetch_lrclib_result(metadata, timeout=0.25)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.query, "Correct Artist - Correct Song")
        self.assertIn(
            (
                "/api/search",
                {"q": "Correct Artist - Correct Song"},
            ),
            calls,
        )

    def test_lrclib_rejects_wildly_wrong_duration(self):
        metadata = {
            "title": "Song",
            "artist": "Artist",
            "album": "",
            "duration": 258.0,
            "filename_stem": "Artist - Song",
        }

        def fake_request(path, params, timeout):
            if path == "/api/get":
                return None, "not-found"
            return [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "duration": 62.0,
                    "syncedLyrics": "[00:01.00]WRONG",
                },
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "duration": 258.0,
                    "syncedLyrics": "[00:01.00]CORRECT",
                },
            ], "ok"

        with mock.patch(
            "lyrics_support._lrclib_request",
            side_effect=fake_request,
        ):
            result = _fetch_lrclib_result(metadata, timeout=0.25)

        self.assertEqual(result.status, "found")
        self.assertIn("CORRECT", result.text)
        self.assertNotIn("WRONG", result.text)

    def test_lrclib_rejects_conflicting_title_and_artist(self):
        metadata = {
            "title": "Wanted Song",
            "artist": "Wanted Artist",
            "album": "",
            "duration": 240.0,
            "filename_stem": "Wanted Artist - Wanted Song",
        }

        def fake_request(path, params, timeout):
            if path == "/api/get":
                return None, "not-found"
            return [
                {
                    "trackName": "Different Song",
                    "artistName": "Different Artist",
                    "duration": 240.0,
                    "syncedLyrics": "[00:01.00]WRONG",
                },
                {
                    "trackName": "Wanted Song",
                    "artistName": "Wanted Artist",
                    "duration": 241.0,
                    "syncedLyrics": "[00:01.00]CORRECT",
                },
            ], "ok"

        with mock.patch(
            "lyrics_support._lrclib_request",
            side_effect=fake_request,
        ):
            result = _fetch_lrclib_result(metadata, timeout=0.25)

        self.assertEqual(result.status, "found")
        self.assertIn("CORRECT", result.text)

    def test_lrclib_plain_lyrics_are_returned_when_unsynchronized(self):
        metadata = {
            "title": "Song",
            "artist": "Artist",
            "album": "",
            "duration": 258.0,
            "filename_stem": "Artist - Song",
        }

        def fake_request(path, params, timeout):
            return {
                "trackName": "Song",
                "artistName": "Artist",
                "duration": 258.0,
                "syncedLyrics": None,
                "plainLyrics": "First line\nSecond line",
            }, "ok"

        with mock.patch(
            "lyrics_support._lrclib_request",
            side_effect=fake_request,
        ):
            result = _fetch_lrclib_result(metadata, timeout=0.25)

        self.assertEqual(result.status, "found")
        self.assertFalse(result.synced)
        self.assertEqual(result.text, "First line\nSecond line")

    def test_lrclib_prefers_synced_over_plain_search_result(self):
        metadata = {
            "title": "Song",
            "artist": "Artist",
            "album": "",
            "duration": 258.0,
            "filename_stem": "Artist - Song",
        }

        def fake_request(path, params, timeout):
            if path == "/api/get":
                return None, "not-found"
            return [
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "duration": 258.0,
                    "plainLyrics": "PLAIN",
                },
                {
                    "trackName": "Song",
                    "artistName": "Artist",
                    "duration": 258.0,
                    "syncedLyrics": "[00:01.00]SYNCED",
                },
            ], "ok"

        with mock.patch(
            "lyrics_support._lrclib_request",
            side_effect=fake_request,
        ):
            result = _fetch_lrclib_result(metadata, timeout=0.25)

        self.assertTrue(result.synced)
        self.assertIn("SYNCED", result.text)

    def test_downloaded_plain_lrclib_lyrics_show_and_cache_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "Artist - Song.flac"
            track.write_bytes(b"not-real-audio")
            cache_dir = root / "cache"

            with mock.patch(
                "lyrics_support._fetch_lrclib_result",
                return_value=LyricsFetchResult(
                    "First line\nSecond line",
                    "found",
                    "Artist Song",
                    synced=False,
                ),
            ):
                manager = LyricsManager(
                    enabled=True,
                    online_enabled=True,
                    cache_dir=cache_dir,
                    request_timeout=0.25,
                )
                self.assertIsNone(manager.load(track))

                document = None
                for _ in range(100):
                    document = manager.poll(track)
                    if document is not None:
                        break
                    time.sleep(0.01)

            self.assertIsNotNone(document)
            self.assertFalse(document.synced)
            self.assertEqual(
                [line.text for line in document.lines],
                ["First line", "Second line"],
            )
            self.assertIn("unsynchronized", document.source)
            self.assertEqual(len(list(cache_dir.glob("*.txt"))), 1)

            offline = LyricsManager(
                enabled=True,
                online_enabled=False,
                cache_dir=cache_dir,
            )
            cached = offline.load(track)

            self.assertIsNotNone(cached)
            self.assertFalse(cached.synced)
            self.assertEqual(
                [line.text for line in cached.lines],
                ["First line", "Second line"],
            )
            self.assertIn("LRCLIB cache", cached.source)

    def test_sidecar_still_beats_downloaded_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "song.flac"
            track.write_bytes(b"not-real-audio")
            cache_dir = root / "cache"

            with mock.patch(
                "lyrics_support._fetch_lrclib_result",
                return_value=LyricsFetchResult(
                    "[00:01.00]Remote lyric\n",
                    "found",
                    "song",
                ),
            ):
                online = LyricsManager(
                    enabled=True,
                    online_enabled=True,
                    cache_dir=cache_dir,
                )
                self.assertIsNone(online.load(track))
                remote = None
                for _ in range(100):
                    remote = online.poll(track)
                    if remote is not None:
                        break
                    time.sleep(0.01)
                self.assertIsNotNone(remote)
                self.assertEqual(remote.current_line(2.0), "Remote lyric")

            (root / "song.lrc").write_text(
                "[00:01.00]Local lyric\n",
                encoding="utf-8",
            )
            fresh = LyricsManager(
                enabled=True,
                online_enabled=True,
                cache_dir=cache_dir,
            )
            document = fresh.load(track)

            self.assertEqual(document.current_line(2.0), "Local lyric")
            self.assertIn("song.lrc", document.source)


if __name__ == "__main__":
    unittest.main()
