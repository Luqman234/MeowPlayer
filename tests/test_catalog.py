import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meow_catalog import LibraryCatalog, SCHEMA_VERSION


def fake_metadata(path):
    return SimpleNamespace(
        title=path.stem,
        artist="Test Cat",
        album="Nine Lives",
        album_artist="Test Cat",
        track_number=1,
        track_text="1/9",
        year="2026",
        genre="Dream Pop",
        duration=243.5,
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

    def cache_song(self, song):
        self.catalog.put(
            song,
            song.stat(),
            fake_metadata(song),
        )
        self.catalog.commit()

    def test_cached_metadata_round_trip(self):
        song = self.make_song()
        stat_result = song.stat()
        self.cache_song(song)

        cached = self.catalog.get(song, stat_result)

        self.assertIsNotNone(cached)
        self.assertEqual(cached["title"], "song")
        self.assertEqual(cached["artist"], "Test Cat")
        self.assertEqual(cached["album"], "Nine Lives")
        self.assertEqual(cached["track_number"], 1)
        self.assertEqual(cached["genre"], "Dream Pop")
        self.assertAlmostEqual(cached["duration"], 243.5)
        self.assertTrue(cached["tagged"])

    def test_online_metadata_enrichment_is_cached_with_provenance(self):
        song = self.make_song()
        stat_result = song.stat()
        self.cache_song(song)

        enriched = fake_metadata(song)
        enriched.artist = "Remote Cat"
        enriched.album = "Remote Album"
        enriched.year = "2024"
        enriched.genre = "Dream Pop"

        self.assertTrue(
            self.catalog.store_online_metadata_result(
                song,
                enriched,
                status="found",
                source="musicbrainz",
                source_id="mbid-123",
                query='recording:"song"',
                fetched_at_ns=123456,
            )
        )
        self.catalog.commit()

        cached = self.catalog.get(song, stat_result)
        state = self.catalog.online_metadata_state(song)

        self.assertEqual(cached["artist"], "Remote Cat")
        self.assertEqual(cached["album"], "Remote Album")
        self.assertEqual(cached["year"], "2024")
        self.assertEqual(cached["genre"], "Dream Pop")
        self.assertEqual(state["status"], "found")
        self.assertEqual(state["source"], "musicbrainz")
        self.assertEqual(state["source_id"], "mbid-123")
        self.assertEqual(state["fetched_at_ns"], 123456)

    def test_file_change_resets_online_metadata_lookup_state(self):
        song = self.make_song(data=b"first")
        self.cache_song(song)
        enriched = fake_metadata(song)

        self.catalog.store_online_metadata_result(
            song,
            enriched,
            status="not-found",
            query="old query",
            fetched_at_ns=123,
        )
        self.catalog.commit()

        song.write_bytes(b"a changed song body")
        self.catalog.put(song, song.stat(), fake_metadata(song))
        self.catalog.commit()

        state = self.catalog.online_metadata_state(song)

        self.assertEqual(state["status"], "")
        self.assertEqual(state["query"], "")
        self.assertEqual(state["fetched_at_ns"], 0)

    def test_changed_file_invalidates_cache_entry(self):
        song = self.make_song(data=b"first")
        original_stat = song.stat()
        self.cache_song(song)

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

        self.cache_song(first)
        self.cache_song(second)

        second.unlink()
        removed = self.catalog.prune([first])
        self.catalog.commit()

        self.assertEqual(removed, 1)
        self.assertEqual(self.catalog.count(), 1)

    def test_pawmark_toggle_persists(self):
        song = self.make_song()
        self.cache_song(song)

        self.assertFalse(self.catalog.is_favorite(song))
        self.assertTrue(self.catalog.toggle_favorite(song))
        self.assertTrue(self.catalog.is_favorite(song))

        stats = self.catalog.play_stats()
        self.assertTrue(stats[str(song.resolve())]["favorite"])

        self.assertFalse(self.catalog.toggle_favorite(song))
        self.assertFalse(self.catalog.is_favorite(song))

    def test_rating_persists_and_is_clamped_to_five_stars(self):
        song = self.make_song()
        self.cache_song(song)

        self.assertEqual(self.catalog.rating(song), 0)
        self.assertEqual(self.catalog.set_rating(song, 4), 4)
        self.assertEqual(self.catalog.rating(song), 4)

        stats = self.catalog.play_stats()[str(song.resolve())]
        self.assertEqual(stats["rating"], 4)

        self.assertEqual(self.catalog.set_rating(song, 99), 5)
        self.assertEqual(self.catalog.rating(song), 5)

        self.assertEqual(self.catalog.set_rating(song, -3), 0)
        self.assertEqual(self.catalog.rating(song), 0)

    def test_record_play_updates_stats_and_history(self):
        song = self.make_song()
        self.cache_song(song)

        self.assertTrue(self.catalog.record_play(song, played_at_ns=100))
        self.assertTrue(self.catalog.record_play(song, played_at_ns=200))

        stats = self.catalog.play_stats()[str(song.resolve())]
        self.assertEqual(stats["play_count"], 2)
        self.assertEqual(stats["last_played_ns"], 200)

        history = self.catalog.recent_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["played_at_ns"], 200)
        self.assertEqual(history[1]["played_at_ns"], 100)

    def test_invalidate_root_preserves_personal_library_data(self):
        song = self.make_song()
        original_stat = song.stat()
        self.cache_song(song)
        self.catalog.toggle_favorite(song)
        self.catalog.set_rating(song, 5)
        self.catalog.record_play(song, played_at_ns=123)

        touched = self.catalog.invalidate_root()
        self.catalog.commit()

        self.assertEqual(touched, 1)
        self.assertIsNone(self.catalog.get(song, original_stat))

        stats = self.catalog.play_stats()[str(song.resolve())]
        self.assertTrue(stats["favorite"])
        self.assertEqual(stats["rating"], 5)
        self.assertEqual(stats["play_count"], 1)
        self.assertEqual(stats["last_played_ns"], 123)

    def test_v1_database_migrates_without_losing_track(self):
        self.catalog.close()

        legacy = sqlite3.connect(self.database)
        legacy.execute("DROP TABLE tracks")
        legacy.execute(
            """
            CREATE TABLE tracks (
                path TEXT PRIMARY KEY,
                root TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT NOT NULL,
                album_artist TEXT NOT NULL,
                track_number INTEGER NOT NULL,
                track_text TEXT NOT NULL,
                year TEXT NOT NULL,
                folder TEXT NOT NULL,
                filename TEXT NOT NULL,
                tagged INTEGER NOT NULL,
                last_scanned_ns INTEGER NOT NULL
            )
            """
        )

        song = self.make_song()
        stat_result = song.stat()
        legacy.execute(
            """
            INSERT INTO tracks VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                str(song.resolve()),
                str(self.music.resolve()),
                stat_result.st_size,
                stat_result.st_mtime_ns,
                "Legacy Song",
                "Legacy Cat",
                "Old Box",
                "Legacy Cat",
                1,
                "1",
                "2025",
                "Album",
                song.name,
                1,
                1,
            ),
        )
        legacy.execute("PRAGMA user_version = 1")
        legacy.commit()
        legacy.close()

        self.catalog = LibraryCatalog(
            self.music,
            path=self.database,
        )

        version = self.catalog.connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        stats = self.catalog.play_stats()

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIn(str(song.resolve()), stats)
        self.assertFalse(stats[str(song.resolve())]["favorite"])
        self.assertEqual(stats[str(song.resolve())]["rating"], 0)
        self.assertEqual(stats[str(song.resolve())]["play_count"], 0)

    def test_v2_migration_preserves_stats_and_invalidates_metadata(self):
        song = self.make_song()
        original_stat = song.stat()
        self.cache_song(song)
        self.catalog.toggle_favorite(song)
        self.catalog.record_play(song, played_at_ns=321)
        self.catalog.close()

        legacy = sqlite3.connect(self.database)
        legacy.execute("PRAGMA user_version = 2")
        legacy.commit()
        legacy.close()

        self.catalog = LibraryCatalog(
            self.music,
            path=self.database,
        )

        self.assertIsNone(self.catalog.get(song, original_stat))
        stats = self.catalog.play_stats()[str(song.resolve())]
        self.assertTrue(stats["favorite"])
        self.assertEqual(stats["play_count"], 1)
        self.assertEqual(stats["last_played_ns"], 321)

    def test_legacy_cache_database_moves_to_xdg_data(self):
        self.catalog.close()

        cache_home = self.base / "cache"
        data_home = self.base / "data"
        legacy_path = cache_home / "meowplayer" / "library.sqlite3"
        legacy_path.parent.mkdir(parents=True)

        legacy_catalog = LibraryCatalog(
            self.music,
            path=legacy_path,
        )
        song = self.make_song()
        legacy_catalog.put(
            song,
            song.stat(),
            fake_metadata(song),
        )
        legacy_catalog.commit()
        legacy_catalog.close()

        with patch.dict(
            os.environ,
            {
                "XDG_CACHE_HOME": str(cache_home),
                "XDG_DATA_HOME": str(data_home),
            },
            clear=False,
        ):
            self.catalog = LibraryCatalog(self.music)

        expected = data_home / "meowplayer" / "library.sqlite3"
        self.assertEqual(self.catalog.path, expected)
        self.assertTrue(expected.exists())
        self.assertFalse(legacy_path.exists())
        self.assertEqual(self.catalog.count(), 1)

    def test_clear_root_compatibility_helper(self):
        song = self.make_song()
        self.cache_song(song)

        removed = self.catalog.clear_root()
        self.catalog.commit()

        self.assertEqual(removed, 1)
        self.assertEqual(self.catalog.count(), 0)


if __name__ == "__main__":
    unittest.main()
