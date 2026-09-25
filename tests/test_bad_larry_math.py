import unittest

from bad_larry import PlaybackSaboteur
from bad_larry_math import (
    MATH_EVENT_CHANCE,
    MATH_ROLL_INTERVAL,
    QUANTUM_EXAM_SECONDS,
    QUANTUM_FINAL_EXAM,
    QUESTION_BANK,
    answer_is_correct,
    select_math_difficulty,
    skip_penalty,
)


class FakeRNG:
    def __init__(self, random_values=None):
        self.random_values = list(random_values or [0.0])

    def random(self):
        if self.random_values:
            return self.random_values.pop(0)
        return 0.0

    def uniform(self, low, high):
        return float(low)

    def randint(self, low, high):
        return int(low)

    def choice(self, values):
        return values[0]


class FakeMPV:
    def __init__(self):
        self.properties = {
            "pause": False,
            "time-pos": 90.0,
            "speed": 1.0,
            "volume": 70,
        }
        self.seeks = []
        self.absolute_seeks = []

    def get_property(self, name):
        return self.properties.get(name)

    def set_property(self, name, value):
        self.properties[name] = value

    def seek(self, seconds):
        self.seeks.append(float(seconds))

    def seek_absolute(self, seconds):
        self.absolute_seeks.append(float(seconds))

    def pause(self):
        self.properties["pause"] = True

    def play(self):
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


class BadLarryMathTests(unittest.TestCase):
    def test_math_roll_is_one_in_five_each_minute(self):
        self.assertEqual(MATH_ROLL_INTERVAL, 60.0)
        self.assertEqual(MATH_EVENT_CHANCE, 0.20)

    def test_difficulty_boundaries_match_requested_distribution(self):
        self.assertEqual(select_math_difficulty(0.00), "easy")
        self.assertEqual(select_math_difficulty(0.499999), "easy")
        self.assertEqual(select_math_difficulty(0.50), "medium")
        self.assertEqual(select_math_difficulty(0.799999), "medium")
        self.assertEqual(select_math_difficulty(0.80), "hard")
        self.assertEqual(select_math_difficulty(0.989999), "hard")
        self.assertEqual(select_math_difficulty(0.99), "stochastic")
        self.assertEqual(select_math_difficulty(0.994999), "stochastic")
        self.assertEqual(select_math_difficulty(0.995), "imo-p6")
        self.assertEqual(select_math_difficulty(0.999999), "imo-p6")

    def test_dangerous_mode_rolls_question_after_one_minute(self):
        player = FakePlayer()
        cat = PlaybackSaboteur(
            "dangerous",
            rng=FakeRNG([0.0, 0.0]),
            now_func=lambda: 0.0,
        )

        self.assertIsNone(cat.pop_math_question())
        cat.tick(player, now=59.9)
        self.assertIsNone(cat.pop_math_question())

        cat.tick(player, now=60.0)
        question = cat.pop_math_question()

        self.assertIsNotNone(question)
        self.assertEqual(question.difficulty, "easy")

    def test_imo_p6_style_boss_has_machine_checkable_answer(self):
        question = QUESTION_BANK["imo-p6"][0]
        self.assertTrue(answer_is_correct(question, "27"))
        self.assertFalse(answer_is_correct(question, "26"))

    def test_skip_penalty_scales_by_difficulty(self):
        easy = skip_penalty("easy", 1)
        medium = skip_penalty("medium", 1)
        hard = skip_penalty("hard", 1)
        stochastic = skip_penalty("stochastic", 1)
        p6 = skip_penalty("imo-p6", 1)
        quantum = skip_penalty("quantum", 1)

        self.assertLess(easy["malice"], medium["malice"])
        self.assertLess(medium["malice"], hard["malice"])
        self.assertLess(hard["malice"], stochastic["malice"])
        self.assertLess(stochastic["malice"], p6["malice"])
        self.assertLess(p6["malice"], quantum["malice"])

    def test_repeated_surrender_increases_penalty_but_caps_multiplier(self):
        self.assertEqual(skip_penalty("hard", 1)["multiplier"], 1.0)
        self.assertEqual(skip_penalty("hard", 2)["multiplier"], 1.15)
        self.assertEqual(skip_penalty("hard", 3)["multiplier"], 1.30)
        self.assertEqual(skip_penalty("hard", 4)["multiplier"], 1.50)
        self.assertEqual(skip_penalty("hard", 99)["multiplier"], 1.50)

    def test_medium_surrender_rewinds_and_temporarily_slows_playback(self):
        player = FakePlayer()
        cat = PlaybackSaboteur(
            "dangerous",
            rng=FakeRNG(),
            now_func=lambda: 0.0,
        )

        penalty = cat.apply_math_skip(player, "medium", now=0.0)

        self.assertEqual(penalty["malice"], 6)
        self.assertEqual(player.mpv.seeks, [-10.0])
        self.assertEqual(player.mpv.properties["speed"], 0.95)

        cat.tick(player, now=10.0)
        self.assertEqual(player.mpv.properties["speed"], 1.0)

    def test_quantum_problem_has_five_minute_limit_and_all_nine_parts(self):
        self.assertEqual(QUANTUM_EXAM_SECONDS, 300.0)
        for number in range(1, 10):
            self.assertIn(f"{number}.", QUANTUM_FINAL_EXAM)
        self.assertIn("Cayley hyperdeterminant", QUANTUM_FINAL_EXAM)
        self.assertIn("GHZ", QUANTUM_FINAL_EXAM)
        self.assertIn("W-class", QUANTUM_FINAL_EXAM)
        self.assertIn("tau_3", QUANTUM_FINAL_EXAM)


if __name__ == "__main__":
    unittest.main()
