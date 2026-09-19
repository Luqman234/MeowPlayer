import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace

from meowplayer import MPVController, MeowPlayer, build_mpv_command


class FakeMPV:
    def __init__(self, current_path=None):
        self.path = current_path
        self.primed = []
        self.trimmed = 0
        self.cleared = 0

    def current_path(self):
        return self.path

    def trim_playlist_before_current(self):
        self.trimmed += 1

    def prime_next(self, filename):
        self.primed.append(Path(filename))

    def clear_future_playlist(self):
        self.cleared += 1


class AudioEngineTests(unittest.TestCase):
    def make_player(self, count=4, current=0):
        player = MeowPlayer.__new__(MeowPlayer)
        player.songs = [Path(f"/music/{i}.flac") for i in range(count)]
        player.song_lookup = {
            path.resolve(): index
            for index, path in enumerate(player.songs)
        }
        player.current = current
        player.repeat = False
        player.shuffle = False
        player.shuffle_bag = []
        player.catnip_stash = []
        player.stash_selected = 0
        player.history = []
        player.playback_sequence = []
        player.gapless_mode = "weak"
        player.gapless_next_index = None
        player._awaiting_mpv_path = False
        player.catalog = None
        player.lyrics = SimpleNamespace(
            load=lambda path: None,
            poll=lambda path: None,
        )
        player.current_lyrics = None
        player.lyrics_track_index = None
        player.lyrics_follow = True
        player.lyrics_scroll = 0
        player.mpv = FakeMPV(
            str(player.songs[current])
            if current is not None
            else None
        )
        player.ordered_library_indices = lambda: list(range(count))
        player.set_status = lambda *args, **kwargs: None
        player.sync_mpris = lambda *args, **kwargs: None
        player.meta = lambda index: SimpleNamespace(
            artist_title=f"Track {index}"
        )
        return player

    def test_meowplayer_constructor_accepts_online_lyrics_flag(self):
        parameters = inspect.signature(MeowPlayer.__init__).parameters

        self.assertIn("lyrics_online_enabled", parameters)

    def test_mpv_controller_does_not_own_ui_feature_flags(self):
        parameters = inspect.signature(MPVController.__init__).parameters

        self.assertNotIn("lyrics_online_enabled", parameters)
        self.assertNotIn("visualizer_enabled", parameters)
        self.assertNotIn("filesystem_watch_enabled", parameters)

    def test_mpv_command_enables_native_audio_features(self):
        command = build_mpv_command(
            "/tmp/meow.sock",
            gapless_mode="weak",
            replaygain_mode="album",
            replaygain_preamp=-1.5,
        )

        self.assertIn("--gapless-audio=weak", command)
        self.assertIn("--replaygain=album", command)
        self.assertIn("--replaygain-preamp=-1.5", command)
        self.assertIn("--replaygain-clip=no", command)

    def test_invalid_audio_modes_fall_back_safely(self):
        command = build_mpv_command(
            "/tmp/meow.sock",
            gapless_mode="wat",
            replaygain_mode="loud",
            replaygain_preamp="bad",
        )

        self.assertIn("--gapless-audio=weak", command)
        self.assertIn("--replaygain=track", command)
        self.assertIn("--replaygain-preamp=0.0", command)

    def test_queue_has_gapless_priority(self):
        player = self.make_player()
        player.catnip_stash = [3]
        player.playback_sequence = [0, 1, 2]

        self.assertEqual(player.peek_next_index(), 3)

    def test_shuffle_peek_does_not_consume_bag(self):
        player = self.make_player()
        player.shuffle = True
        player.shuffle_bag = [2, 3]

        next_index = player.peek_next_index()

        self.assertEqual(next_index, 3)
        self.assertEqual(player.shuffle_bag, [2, 3])

    def test_smart_sequence_is_used_when_not_shuffling(self):
        player = self.make_player(current=2)
        player.playback_sequence = [0, 2, 3]

        self.assertEqual(player.peek_next_index(), 3)

    def test_gapless_priming_waits_for_manual_load_confirmation(self):
        player = self.make_player(current=1)
        player.playback_sequence = [1, 2, 3]
        player._awaiting_mpv_path = True

        player.prime_gapless_next()

        self.assertEqual(player.gapless_next_index, 2)
        self.assertEqual(player.mpv.primed, [])

        player.mpv.path = str(player.songs[1])
        changed = player.sync_gapless_transition()

        self.assertFalse(changed)
        self.assertFalse(player._awaiting_mpv_path)
        self.assertEqual(
            player.mpv.primed,
            [Path("/music/2.flac")],
        )

    def test_playlist_cleanup_never_removes_entries_while_mpv_position_is_minus_one(self):
        controller = MPVController.__new__(MPVController)
        commands = []

        def fake_get_property(name):
            if name == "playlist-current-pos":
                return -1
            if name == "playlist-count":
                return 3
            return None

        controller.get_property = fake_get_property
        controller.command = lambda *args: commands.append(args)

        controller.clear_future_playlist()
        controller.trim_playlist_before_current()

        self.assertEqual(commands, [])

    def test_prime_gapless_appends_reserved_next_track(self):
        player = self.make_player(current=1)
        player.playback_sequence = [1, 2, 3]

        player.prime_gapless_next()

        self.assertEqual(player.gapless_next_index, 2)
        self.assertEqual(player.mpv.primed, [Path("/music/2.flac")])

    def test_repeat_clears_future_gapless_track(self):
        player = self.make_player(current=1)
        player.repeat = True

        player.prime_gapless_next()

        self.assertIsNone(player.gapless_next_index)
        self.assertEqual(player.mpv.cleared, 1)

    def test_natural_transition_commits_reserved_queue_item(self):
        player = self.make_player(current=0)
        player.catnip_stash = [1, 2]
        player.gapless_next_index = 1
        player.mpv.path = str(player.songs[1])

        changed = player.sync_gapless_transition()

        self.assertTrue(changed)
        self.assertEqual(player.current, 1)
        self.assertEqual(player.catnip_stash, [2])
        self.assertEqual(player.history, [0])
        self.assertEqual(player.gapless_next_index, 2)
        self.assertEqual(player.mpv.primed[-1], Path("/music/2.flac"))

    def test_awaiting_manual_load_does_not_fake_transition(self):
        player = self.make_player(current=2)
        player._awaiting_mpv_path = True
        player.mpv.path = str(player.songs[1])

        changed = player.sync_gapless_transition()

        self.assertFalse(changed)
        self.assertEqual(player.current, 2)
        self.assertTrue(player._awaiting_mpv_path)

        player.mpv.path = str(player.songs[2])
        player.sync_gapless_transition()

        self.assertFalse(player._awaiting_mpv_path)


if __name__ == "__main__":
    unittest.main()
