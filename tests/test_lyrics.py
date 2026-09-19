import tempfile
import unittest
from pathlib import Path

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

        self.assertEqual(document.current_line(0.0), "One")
        self.assertEqual(document.current_line(4.5), "Two")
        self.assertEqual(document.current_line(99.0), "Three")

    def test_plain_lyrics_are_unsynchronized(self):
        document = parse_plain_lyrics("first\n\nsecond")

        self.assertFalse(document.synced)
        self.assertEqual(
            [line.text for line in document.lines],
            ["first", "second"],
        )

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

            manager = LyricsManager(enabled=True)
            document = manager.load(track)

            self.assertIsNotNone(document)
            self.assertTrue(document.synced)
            self.assertEqual(document.current_line(2.0), "Sidecar lyric")
            self.assertIn("song.lrc", document.source)


if __name__ == "__main__":
    unittest.main()
