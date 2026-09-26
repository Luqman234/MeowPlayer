import unittest

from cat_presence import CatPresence, CatPresenceSnapshot


class CatPresenceTests(unittest.TestCase):
    def test_crossfade_turns_cat_into_dj_with_highest_priority(self):
        snapshot = CatPresenceSnapshot(
            active=True,
            paused=True,
            volume=100,
            shuffle=True,
            repeat=True,
            stash_count=4,
            crossfade_active=True,
            online=True,
            online_state="loading",
            rating=1,
            visualizer_visible=True,
        )

        self.assertEqual(CatPresence.mood(snapshot), "DJ")
        self.assertIn("[DJ]", CatPresence.frame(snapshot, now=0.0)[0])

    def test_internet_cat_hunts_then_wears_headphones(self):
        hunting = CatPresenceSnapshot(
            active=True,
            online=True,
            online_state="resolving",
        )
        streaming = CatPresenceSnapshot(
            active=True,
            online=True,
            online_state="idle",
        )

        self.assertEqual(CatPresence.mood(hunting), "Hunting")
        self.assertEqual(CatPresence.mood(streaming), "Headphones")
        self.assertIn("packet", CatPresence.caption(hunting).lower())
        self.assertIn("headphones", CatPresence.caption(streaming).lower())

    def test_failed_stream_returns_empty_pawed_cat(self):
        snapshot = CatPresenceSnapshot(
            active=True,
            online=True,
            online_state="failed",
        )

        self.assertEqual(CatPresence.mood(snapshot), "Empty-Pawed")
        self.assertIn("nothing", CatPresence.caption(snapshot).lower())

    def test_local_state_priority_remains_deterministic(self):
        self.assertEqual(
            CatPresence.mood(
                CatPresenceSnapshot(active=True, paused=True, volume=100)
            ),
            "Loafing",
        )
        self.assertEqual(
            CatPresence.mood(
                CatPresenceSnapshot(active=True, volume=95, shuffle=True)
            ),
            "Screaming",
        )
        self.assertEqual(
            CatPresence.mood(
                CatPresenceSnapshot(active=True, shuffle=True, stash_count=2)
            ),
            "Zoomies",
        )
        self.assertEqual(
            CatPresence.mood(
                CatPresenceSnapshot(active=True, stash_count=2)
            ),
            "Guarding Catnip",
        )

    def test_visualizer_and_ratings_get_cat_reactions(self):
        self.assertEqual(
            CatPresence.mood(
                CatPresenceSnapshot(active=True, visualizer_visible=True)
            ),
            "Dancing",
        )
        self.assertEqual(
            CatPresence.mood(
                CatPresenceSnapshot(active=True, rating=1)
            ),
            "Judging",
        )
        self.assertEqual(
            CatPresence.mood(
                CatPresenceSnapshot(active=True, rating=5)
            ),
            "Adoring",
        )

    def test_frames_animate_without_mutating_snapshot(self):
        snapshot = CatPresenceSnapshot(active=True)
        first = CatPresence.frame(snapshot, now=0.0)
        second = CatPresence.frame(
            snapshot,
            now=CatPresence.FRAME_SECONDS + 0.01,
        )

        self.assertNotEqual(first, second)
        self.assertEqual(snapshot, CatPresenceSnapshot(active=True))

    def test_maximum_meow_adds_garnish_not_new_state(self):
        snapshot = CatPresenceSnapshot(
            active=True,
            crossfade_active=True,
        )

        normal = CatPresence.frame(snapshot, now=0.0)
        maximum = CatPresence.frame(
            snapshot,
            now=0.0,
            maximum_meow=True,
        )

        self.assertEqual(CatPresence.mood(snapshot), "DJ")
        self.assertNotEqual(normal, maximum)
        self.assertTrue(all("♪" in line or "♫" in line for line in maximum))

    def test_scritches_are_reported_in_context_caption(self):
        snapshot = CatPresenceSnapshot(active=True, scritches=12)

        caption = CatPresence.caption(snapshot)

        self.assertIn("Scritches logged: 12", caption)


if __name__ == "__main__":
    unittest.main()
