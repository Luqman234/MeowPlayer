import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from lyrics_support import LyricsManager, parse_lrc, parse_plain_lyrics


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
                "lyrics_support._fetch_lrclib",
                return_value="[00:01.00]Downloaded line\n",
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

    def test_sidecar_still_beats_downloaded_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "song.flac"
            track.write_bytes(b"not-real-audio")
            cache_dir = root / "cache"

            with mock.patch(
                "lyrics_support._fetch_lrclib",
                return_value="[00:01.00]Remote lyric\n",
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
