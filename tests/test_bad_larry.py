import unittest

from bad_larry import (
    CHAOS_PROFILES,
    DANGEROUS_DISMISS_PHRASE,
    DANGEROUS_SUMMON_PHRASE,
    PlaybackSaboteur,
    apology_matches,
    confirm_dangerous_cat,
)


class FakeRNG:
    def random(self):
        return 0.0

    def uniform(self, low, high):
        return float(low)

    def randint(self, low, high):
        return int(low)

    def choice(self, values):
        return values[0]


class FakeMPV:
    def __init__(self):
        self.paused = False
        self.properties = {
            "pause": False,
            "time-pos": 90.0,
            "speed": 1.0,
            "volume": 70,
        }
        self.seeks = []
        self.absolute_seeks = []
        self.play_calls = 0
        self.pause_calls = 0

    def get_property(self, name):
        if name == "pause":
            return self.paused
        return self.properties.get(name)

    def set_property(self, name, value):
        self.properties[name] = value

    def seek(self, seconds):
        self.seeks.append(float(seconds))

    def seek_absolute(self, seconds):
        self.absolute_seeks.append(float(seconds))

    def pause(self):
        self.pause_calls += 1
        self.paused = True
        self.properties["pause"] = True

    def play(self):
        self.play_calls += 1
        self.paused = False
        self.properties["pause"] = False


class FakePlayer:
    def __init__(self):
        self.current = 0
        self.songs = ["a.flac", "b.flac", "c.flac"]
        self.volume = 70
        self.mpv = FakeMPV()
        self.status_message = ""
        self.play_calls = []

    def set_status(self, serious, cat):
        self.status_message = cat

    def play(self, index, **kwargs):
        self.current = index
        self.play_calls.append((index, kwargs))


class BadLarryTests(unittest.TestCase):
    def test_profiles_escalate_from_bad_to_dangerous(self):
        bad = CHAOS_PROFILES["bad-bad"]
        very = CHAOS_PROFILES["very-bad"]
        dangerous = CHAOS_PROFILES["dangerous"]

        self.assertGreater(bad.min_cooldown, very.min_cooldown)
        self.assertGreater(very.min_cooldown, dangerous.min_cooldown)
        self.assertLess(bad.retaliation_chance, very.retaliation_chance)
        self.assertLess(very.retaliation_chance, dangerous.retaliation_chance)
        self.assertLess(bad.rewind_max, very.rewind_max)
        self.assertLess(very.rewind_max, dangerous.rewind_max)

    def test_dangerous_confirmation_requires_all_three_steps(self):
        answers = iter(["yes", "y", DANGEROUS_SUMMON_PHRASE])
        output = []

        confirmed = confirm_dangerous_cat(
            input_func=lambda prompt: next(answers),
            output_func=output.append,
        )

        self.assertTrue(confirmed)
        self.assertIn("BAD LARRY HAS ENTERED THE ROOM.", output)

    def test_dangerous_confirmation_rejects_wrong_final_phrase(self):
        answers = iter(["y", "yes", "almost"])

        confirmed = confirm_dangerous_cat(
            input_func=lambda prompt: next(answers),
            output_func=lambda value: None,
        )

        self.assertFalse(confirmed)

    def test_emergency_apology_is_exact_and_case_sensitive(self):
        self.assertTrue(apology_matches(DANGEROUS_DISMISS_PHRASE))
        self.assertFalse(
            apology_matches("yes, i apologize for disturbing bad larry")
        )
        self.assertFalse(
            apology_matches(DANGEROUS_DISMISS_PHRASE + " ")
        )

    def test_bad_bad_cat_can_rewind_a_skip_attempt(self):
        player = FakePlayer()
        cat = PlaybackSaboteur(
            "bad-bad",
            rng=FakeRNG(),
            now_func=lambda: 0.0,
        )

        intercepted = cat.handle_user_action(player, "next", now=0.0)

        self.assertTrue(intercepted)
        self.assertEqual(player.mpv.seeks, [-2.0])
        self.assertEqual(cat.skips_denied, 1)

    def test_dangerous_cat_blocks_normal_quit(self):
        player = FakePlayer()
        cat = PlaybackSaboteur(
            "dangerous",
            rng=FakeRNG(),
            now_func=lambda: 0.0,
        )

        self.assertTrue(cat.handle_user_action(player, "quit", now=0.0))
        self.assertIn("Ctrl+E", player.status_message)
        self.assertEqual(cat.malice, 20)

    def test_pause_retaliation_resumes_after_timer(self):
        player = FakePlayer()
        cat = PlaybackSaboteur(
            "dangerous",
            rng=FakeRNG(),
            now_func=lambda: 0.0,
        )

        self.assertTrue(cat.handle_user_action(player, "pause", now=0.0))
        self.assertTrue(player.mpv.paused)

        cat.tick(player, now=2.0)

        self.assertFalse(player.mpv.paused)
        self.assertGreaterEqual(player.mpv.play_calls, 1)

    def test_volume_theft_never_changes_saved_player_volume(self):
        player = FakePlayer()
        cat = PlaybackSaboteur(
            "dangerous",
            rng=FakeRNG(),
            now_func=lambda: 0.0,
        )

        self.assertTrue(cat.handle_user_action(player, "volume_down", now=0.0))

        self.assertEqual(player.volume, 70)
        self.assertEqual(player.mpv.properties["volume"], 65)

        cat.tick(player, now=10.0)
        self.assertEqual(player.mpv.properties["volume"], 70)

    def test_dismiss_restores_transient_playback_state(self):
        player = FakePlayer()
        cat = PlaybackSaboteur(
            "dangerous",
            rng=FakeRNG(),
            now_func=lambda: 0.0,
        )
        player.mpv.set_property("speed", 0.8)
        player.mpv.set_property("volume", 55)
        cat.forced_pause = True
        player.mpv.pause()

        cat.dismiss(player)

        self.assertFalse(cat.enabled)
        self.assertEqual(player.mpv.properties["speed"], 1.0)
        self.assertEqual(player.mpv.properties["volume"], 70)
        self.assertFalse(player.mpv.paused)


if __name__ == "__main__":
    unittest.main()
