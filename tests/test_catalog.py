import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from meow_catalog import LibraryCatalog


def fake_metadata(path):
    return SimpleNamespace(
        title=path.stem,
        artist="Test Cat",
        album="Nine Lives",
        album_artist="Test Cat",
        track_number=1,
        track_text="1/9",
        year="2026",
        folder="Album",
        filename=path.name,
        tagged=True,
    )


class LibraryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.music = self.base / "Music"
        self.music.mkdir()
        self.database = self.base / "catalog.sqlite3"
        self.catalog = LibraryCatalog(
            self.music,
            path=self.database,
        )

    def tearDown(self):
        self.catalog.close()
        self.temp.cleanup()

    def make_song(self, name="song.mp3", data=b"meow"):
        path = self.music / name
        path.write_bytes(data)
        return path

    def test_cached_metadata_round_trip(self):
        song = self.make_song()
        stat_result = song.stat()
        self.catalog.put(
            song,
            stat_result,
            fake_metadata(song),
        )
        self.catalog.commit()

        cached = self.catalog.get(song, stat_result)

        self.assertIsNotNone(cached)
        self.assertEqual(cached["title"], "song")
        self.assertEqual(cached["artist"], "Test Cat")
        self.assertEqual(cached["album"], "Nine Lives")
        self.assertEqual(cached["track_number"], 1)
        self.assertTrue(cached["tagged"])

    def test_changed_file_invalidates_cache_entry(self):
        song = self.make_song(data=b"first")
        original_stat = song.stat()
        self.catalog.put(
            song,
            original_stat,
            fake_metadata(song),
        )
        self.catalog.commit()

        song.write_bytes(b"a much larger second version")
        changed_stat = song.stat()

        self.assertIsNotNone(
            self.catalog.get(song, original_stat)
        )
        self.assertIsNone(
            self.catalog.get(song, changed_stat)
        )

    def test_prune_removes_deleted_tracks(self):
        first = self.make_song("first.mp3")
        second = self.make_song("second.mp3")

        for song in (first, second):
            self.catalog.put(
                song,
                song.stat(),
                fake_metadata(song),
            )
        self.catalog.commit()

        second.unlink()
        removed = self.catalog.prune([first])
        self.catalog.commit()

        self.assertEqual(removed, 1)
        self.assertEqual(self.catalog.count(), 1)

    def test_clear_root_rebuilds_only_current_library(self):
        song = self.make_song()
        self.catalog.put(
            song,
            song.stat(),
            fake_metadata(song),
        )
        self.catalog.commit()

        removed = self.catalog.clear_root()
        self.catalog.commit()

        self.assertEqual(removed, 1)
        self.assertEqual(self.catalog.count(), 0)


if __name__ == "__main__":
    unittest.main()
