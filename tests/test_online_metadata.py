import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from online_metadata import (
    MusicBrainzClient,
    OnlineMetadataManager,
    OnlineMetadataResult,
    filename_artist_title,
    merge_missing_metadata,
    metadata_lookup_due,
    missing_metadata_fields,
    needs_online_metadata,
)


def metadata(**overrides):
    values = {
        "path": Path("/music/01 - Beach House - Space Song.flac"),
        "title": "01 - Beach House - Space Song",
        "artist": "Unknown Artist",
        "album": "Unknown Album",
        "album_artist": "Unknown Artist",
        "track_number": 0,
        "track_text": "",
        "year": "",
        "genre": "",
        "duration": 320.0,
        "folder": "Music Root",
        "filename": "01 - Beach House - Space Song.flac",
        "tagged": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class OnlineMetadataTests(unittest.TestCase):
    def test_missing_fields_detect_fallback_metadata(self):
        item = metadata()

        fields = missing_metadata_fields(item)

        self.assertIn("title", fields)
        self.assertIn("artist", fields)
        self.assertIn("album", fields)
        self.assertIn("year", fields)
        self.assertIn("genre", fields)
        self.assertTrue(needs_online_metadata(item))

    def test_tagged_title_matching_filename_is_preserved(self):
        item = metadata(
            path=Path("/music/Space Song.flac"),
            filename="Space Song.flac",
            title="Space Song",
            artist="Beach House",
            album="Unknown Album",
            album_artist="Beach House",
            year="",
            genre="",
            tagged=True,
        )

        self.assertNotIn("title", missing_metadata_fields(item))

    def test_complete_local_tags_do_not_need_web_lookup(self):
        item = metadata(
            title="Space Song",
            artist="Beach House",
            album="Depression Cherry",
            album_artist="Beach House",
            year="2015",
            genre="Dream Pop",
            tagged=True,
        )

        self.assertFalse(needs_online_metadata(item))

    def test_remote_metadata_only_fills_missing_fields(self):
        item = metadata(
            title="Space Song",
            artist="Beach House",
            album="Unknown Album",
            album_artist="Beach House",
            year="",
            genre="",
            tagged=True,
        )
        result = OnlineMetadataResult(
            path=str(item.path),
            status="found",
            query="recording query",
            title="WRONG REMOTE TITLE",
            artist="WRONG REMOTE ARTIST",
            album="Depression Cherry",
            album_artist="WRONG ALBUM ARTIST",
            year="2015",
            genre="Dream Pop",
        )

        merged = merge_missing_metadata(item, result)

        self.assertEqual(merged["title"], "Space Song")
        self.assertEqual(merged["artist"], "Beach House")
        self.assertEqual(merged["album_artist"], "Beach House")
        self.assertEqual(merged["album"], "Depression Cherry")
        self.assertEqual(merged["year"], "2015")
        self.assertEqual(merged["genre"], "Dream Pop")

    def test_filename_parser_handles_track_prefix(self):
        artist, title = filename_artist_title(
            Path("/music/01 - Beach House - Space Song.flac")
        )

        self.assertEqual(artist, "Beach House")
        self.assertEqual(title, "Space Song")

    def test_musicbrainz_result_extracts_metadata_and_genre(self):
        client = MusicBrainzClient()
        responses = [
            (
                {
                    "recordings": [
                        {
                            "id": "recording-id",
                            "score": 100,
                            "title": "Space Song",
                            "length": 320000,
                            "artist-credit": [
                                {
                                    "name": "Beach House",
                                }
                            ],
                            "first-release-date": "2015-08-28",
                            "releases": [
                                {
                                    "title": "Depression Cherry",
                                    "status": "Official",
                                    "date": "2015-08-28",
                                }
                            ],
                        }
                    ]
                },
                "ok",
            ),
            (
                {
                    "genres": [
                        {"name": "dream pop", "count": 8},
                        {"name": "indie pop", "count": 3},
                    ]
                },
                "ok",
            ),
        ]
        calls = []

        def fake_request(path, params=None):
            calls.append((path, dict(params or {})))
            return responses.pop(0)

        client._request_json = fake_request
        item = metadata(
            title="Space Song",
            artist="Beach House",
            duration=320.0,
        )
        snapshot = {
            "path": str(item.path),
            "title": item.title,
            "artist": item.artist,
            "album": item.album,
            "duration": item.duration,
            "missing": missing_metadata_fields(item),
        }

        result = client.fetch(snapshot)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.title, "Space Song")
        self.assertEqual(result.artist, "Beach House")
        self.assertEqual(result.album, "Depression Cherry")
        self.assertEqual(result.year, "2015")
        self.assertEqual(result.genre, "dream pop")
        self.assertEqual(result.source_id, "recording-id")
        self.assertEqual(calls[1][0], "/recording/recording-id")

    def test_large_duration_mismatch_rejects_false_match(self):
        client = MusicBrainzClient()
        client._request_json = lambda path, params=None: (
            {
                "recordings": [
                    {
                        "id": "wrong",
                        "score": 100,
                        "title": "Space Song",
                        "length": 120000,
                        "artist-credit": [{"name": "Beach House"}],
                    }
                ]
            },
            "ok",
        )
        item = metadata(
            title="Space Song",
            artist="Beach House",
            duration=320.0,
        )
        snapshot = {
            "path": str(item.path),
            "title": item.title,
            "artist": item.artist,
            "album": item.album,
            "duration": item.duration,
            "missing": missing_metadata_fields(item),
        }

        result = client.fetch(snapshot)

        self.assertEqual(result.status, "not-found")

    def test_cache_ttls_prevent_constant_requeries(self):
        now = 10_000_000_000_000_000

        self.assertFalse(
            metadata_lookup_due(
                {
                    "status": "found",
                    "fetched_at_ns": now - 60_000_000_000,
                },
                now_ns=now,
            )
        )
        self.assertFalse(
            metadata_lookup_due(
                {
                    "status": "not-found",
                    "fetched_at_ns": now - 60_000_000_000,
                },
                now_ns=now,
            )
        )
        self.assertTrue(
            metadata_lookup_due(
                {
                    "status": "network-error",
                    "fetched_at_ns": now - 16 * 60 * 1_000_000_000,
                },
                now_ns=now,
            )
        )

    def test_manager_deduplicates_pending_track(self):
        class FakeClient:
            def fetch(self, snapshot):
                return OnlineMetadataResult(
                    path=snapshot["path"],
                    status="found",
                    query="test",
                    title="Space Song",
                )

        manager = OnlineMetadataManager(
            enabled=True,
            client=FakeClient(),
        )
        item = metadata()

        self.assertTrue(manager.enqueue(item))
        self.assertFalse(manager.enqueue(item))

        result = None
        for _ in range(100):
            polled = manager.poll()
            if polled:
                result = polled[0]
                break
            time.sleep(0.005)

        manager.stop()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "found")


if __name__ == "__main__":
    unittest.main()
