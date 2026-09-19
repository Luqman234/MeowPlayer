import unittest
from pathlib import Path

from meowplayer import MeowPlayer


class ShuffleBagTests(unittest.TestCase):
    def make_player(self, count=5, current=0):
        player = MeowPlayer.__new__(MeowPlayer)
        player.songs = [Path(f"/music/{i}.flac") for i in range(count)]
        player.current = current
        player.shuffle = True
        player.shuffle_bag = []
        player.catnip_stash = []
        player.history = []
        player.playback_sequence = []
        player.played = []

        def fake_play(index, **kwargs):
            player.played.append(index)
            player.current = index

        player.play = fake_play
        player.set_status = lambda *args, **kwargs: None
        return player

    def test_shuffle_cycle_visits_every_other_track_once(self):
        player = self.make_player(count=5, current=0)

        for _ in range(4):
            player.next_song(automatic=True)

        self.assertEqual(len(player.played), 4)
        self.assertEqual(len(set(player.played)), 4)
        self.assertEqual(set(player.played), {1, 2, 3, 4})
        self.assertEqual(player.shuffle_bag, [])

    def test_refill_never_contains_current_track(self):
        player = self.make_player(count=5, current=3)
        player.refill_shuffle_bag()

        self.assertEqual(len(player.shuffle_bag), 4)
        self.assertNotIn(3, player.shuffle_bag)
        self.assertEqual(set(player.shuffle_bag), {0, 1, 2, 4})

    def test_sanitize_removes_current_duplicates_and_bad_indices(self):
        player = self.make_player(count=4, current=1)
        player.shuffle_bag = [0, 1, 2, 2, -1, 99, 3]

        player.sanitize_shuffle_bag()

        self.assertEqual(player.shuffle_bag, [0, 2, 3])

    def test_previous_then_next_returns_departed_track(self):
        player = self.make_player(count=5, current=2)
        player.history = [0, 1]
        player.shuffle_bag = [3, 4]

        player.previous_song()

        self.assertEqual(player.current, 1)
        self.assertEqual(player.shuffle_bag[-1], 2)

        player.next_song(automatic=True)

        self.assertEqual(player.current, 2)

    def test_shuffle_bag_is_scoped_to_active_playback_sequence(self):
        player = self.make_player(count=6, current=1)
        player.playback_sequence = [1, 3, 5]

        player.refill_shuffle_bag()

        self.assertEqual(set(player.shuffle_bag), {3, 5})
        self.assertNotIn(0, player.shuffle_bag)
        self.assertNotIn(2, player.shuffle_bag)
        self.assertNotIn(4, player.shuffle_bag)

    def test_single_track_smart_sequence_is_stable(self):
        player = self.make_player(count=5, current=3)
        player.playback_sequence = [3]

        player.next_song(automatic=True)

        self.assertEqual(player.current, 3)
        self.assertEqual(player.played, [3])

    def test_single_track_shuffle_is_stable(self):
        player = self.make_player(count=1, current=0)

        player.next_song(automatic=True)

        self.assertEqual(player.current, 0)
        self.assertEqual(player.played, [0])


if __name__ == "__main__":
    unittest.main()
