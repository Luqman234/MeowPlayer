import tempfile
import unittest
from pathlib import Path

from library_watcher import LibraryWatcher


class LibraryWatcherTests(unittest.TestCase):
    def make_watcher(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(
            lambda: __import__("shutil").rmtree(root, ignore_errors=True)
        )
        return LibraryWatcher(
            root,
            {".mp3", ".flac"},
            enabled=False,
            debounce_seconds=0.5,
        )

    def test_audio_file_event_is_recorded(self):
        watcher = self.make_watcher()

        recorded = watcher.record_event(
            [watcher.root / "song.flac"],
            event_type="modified",
            now=10.0,
        )

        self.assertTrue(recorded)
        self.assertIsNone(watcher.poll(now=10.2))

        summary = watcher.poll(now=10.6)
        self.assertEqual(summary["event_types"], ("modified",))
        self.assertEqual(len(summary["paths"]), 1)
        self.assertTrue(summary["paths"][0].endswith("song.flac"))

    def test_irrelevant_extension_is_ignored(self):
        watcher = self.make_watcher()

        recorded = watcher.record_event(
            [watcher.root / "notes.txt"],
            event_type="modified",
            now=1.0,
        )

        self.assertFalse(recorded)
        self.assertIsNone(watcher.poll(now=2.0))

    def test_multiple_events_collapse_into_one_debounced_batch(self):
        watcher = self.make_watcher()

        watcher.record_event(
            [watcher.root / "a.mp3"],
            event_type="created",
            now=1.0,
        )
        watcher.record_event(
            [watcher.root / "a.mp3", watcher.root / "b.flac"],
            event_type="moved",
            now=1.2,
        )

        self.assertIsNone(watcher.poll(now=1.4))
        summary = watcher.poll(now=1.8)

        self.assertEqual(
            set(summary["event_types"]),
            {"created", "moved"},
        )
        self.assertEqual(len(summary["paths"]), 2)

    def test_directory_event_triggers_rescan(self):
        watcher = self.make_watcher()

        recorded = watcher.record_event(
            [watcher.root / "Album"],
            event_type="moved",
            is_directory=True,
            now=5.0,
        )

        self.assertTrue(recorded)
        summary = watcher.poll(now=5.6)
        self.assertIsNotNone(summary)


if __name__ == "__main__":
    unittest.main()
