import unittest
from pathlib import Path
from types import SimpleNamespace

from meow_smart import build_smart_playlists


def meta(
    index,
    *,
    artist="Artist",
    album="Album",
    genre="",
    track_number=1,
):
    return SimpleNamespace(
        path=Path(f"/music/{index}.flac"),
        title=f"Track {index}",
        artist=artist,
        album=album,
        genre=genre,
        track_number=track_number,
    )


class SmartPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.metadata = [
            meta(0, artist="Alpha", genre="Dream Pop"),
            meta(1, artist="Beta", genre="Rock"),
            meta(2, artist="Alpha", genre="Dream Pop"),
            meta(3, artist="Gamma", genre=""),
        ]
        self.stats = {
            str(Path("/music/0.flac").resolve()): {
                "favorite": True,
                "play_count": 5,
                "last_played_ns": 400,
                "added_at_ns": 10,
            },
            str(Path("/music/1.flac").resolve()): {
                "favorite": False,
                "play_count": 1,
                "last_played_ns": 300,
                "added_at_ns": 40,
            },
            str(Path("/music/2.flac").resolve()): {
                "favorite": True,
                "play_count": 9,
                "last_played_ns": 200,
                "added_at_ns": 30,
            },
            str(Path("/music/3.flac").resolve()): {
                "favorite": False,
                "play_count": 0,
                "last_played_ns": None,
                "added_at_ns": 20,
            },
        }

    def playlists(self):
        return {
            playlist.key: playlist
            for playlist in build_smart_playlists(
                self.metadata,
                self.stats,
            )
        }

    def test_core_smart_playlists_are_generated(self):
        playlists = self.playlists()

        self.assertEqual(playlists["pawmarked"].indices, (0, 2))
        self.assertEqual(playlists["recent"].indices, (0, 1, 2))
        self.assertEqual(playlists["most-played"].indices, (2, 0, 1))
        self.assertEqual(playlists["unplayed"].indices, (3,))

    def test_fresh_finds_are_sorted_by_added_time(self):
        playlists = self.playlists()

        self.assertEqual(
            playlists["fresh"].indices,
            (1, 2, 3, 0),
        )

    def test_genre_mixes_are_created_from_real_library_genres(self):
        playlists = self.playlists()

        self.assertIn("genre:Dream Pop", playlists)
        self.assertIn("genre:Rock", playlists)
        self.assertEqual(
            playlists["genre:Dream Pop"].indices,
            (0, 2),
        )
        self.assertNotIn("genre:", playlists)


if __name__ == "__main__":
    unittest.main()
