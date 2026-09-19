import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from meowplayer import MeowPlayer


def metadata_for(path):
    return SimpleNamespace(
        path=path,
        title=path.stem,
        artist="Artist",
        album="Album",
        album_artist="Artist",
        track_number=1,
        track_text="1",
        year="2026",
        genre="Test",
        duration=60.0,
        folder="Music",
        filename=path.name,
        tagged=True,
    )


class FakeMPV:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class RescanTests(unittest.TestCase):
    def make_player(self, old_songs, new_songs):
        player = MeowPlayer.__new__(MeowPlayer)
        player.songs = list(old_songs)
        player.metadata = [metadata_for(path) for path in old_songs]
        player.song_lookup = {
            path.resolve(): index
            for index, path in enumerate(old_songs)
        }

        player.current = 1 if len(old_songs) > 1 else 0
        player.catnip_stash = [0]
        player.history = [player.current, 0]
        player.shuffle_bag = [0]
        player.playback_sequence = [player.current, 0]

        player.selected = 0
        player.stash_selected = 0
        player.shuffle = False
        player.library_stats = {}
        player.catalog = None
        player.catalog_error = None
        player.catalog_hits = 0
        player.catalog_refreshed = 0
        player.catalog_pruned = 0

        player.current_lyrics = None
        player.lyrics_track_index = None
        player.gapless_next_index = None

        player.mpv = FakeMPV()

        player.find_songs = lambda: list(new_songs)

        def load_metadata(rebuild=False):
            return [metadata_for(path) for path in new_songs]

        player.load_library_metadata = load_metadata
        player.selected_library_song = lambda: 0
        player.ordered_library_indices = lambda: list(range(len(player.songs)))
        player.load_current_lyrics = lambda index: None
        player.prime_gapless_next = lambda: None
        player.sync_mpris = lambda force=False: None
        player.set_status = lambda *args, **kwargs: None

        return player

    def test_rescan_remaps_state_by_path_not_old_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            b = root / "b.flac"
            c = root / "c.flac"
            a = root / "a.flac"
            for path in (a, b, c):
                path.write_bytes(b"x")

            player = self.make_player(
                [b, c],
                [a, b, c],
            )

            player.rescan_library(
                {"paths": (str(a),), "event_types": ("created",)}
            )

            self.assertEqual(player.songs[player.current], c)
            self.assertEqual(
                [player.songs[i] for i in player.catnip_stash],
                [b],
            )
            self.assertEqual(
                [player.songs[i] for i in player.history],
                [c, b],
            )
            self.assertEqual(
                [player.songs[i] for i in player.playback_sequence],
                [c, b],
            )

    def test_deleted_current_track_is_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            b = root / "b.flac"
            c = root / "c.flac"
            b.write_bytes(b"x")
            c.write_bytes(b"x")

            player = self.make_player(
                [b, c],
                [b],
            )

            player.rescan_library(
                {"paths": (str(c),), "event_types": ("deleted",)}
            )

            self.assertIsNone(player.current)
            self.assertTrue(player.mpv.stopped)


if __name__ == "__main__":
    unittest.main()
