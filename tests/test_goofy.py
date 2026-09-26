import unittest
from unittest import mock

from meowplayer import CAT_INCIDENTS, MeowPlayer


class FakeMPV:
    def __init__(self, paused=False):
        self.paused = paused
        self.properties = {}

    def get_property(self, name):
        if name == "pause":
            return self.paused
        return self.properties.get(name)

    def set_property(self, name, value):
        self.properties[name] = value


class GoofyCatTests(unittest.TestCase):
    def make_player(
        self,
        *,
        serious=False,
        current=0,
        volume=70,
        paused=False,
    ):
        player = MeowPlayer.__new__(MeowPlayer)
        player.serious_mode = serious
        player.maximum_meow = False
        player.current = current
        player.volume = volume
        player.repeat = False
        player.shuffle = False
        player.catnip_stash = []
        player.mpv = FakeMPV(paused=paused)

        player.scritches = 0
        player.cat_incident = None
        player.cat_incident_until = 0.0
        player.next_cat_incident_at = 100.0
        player.quote = "Ordinary cat quote."
        player.status_message = ""

        return player

    def test_high_volume_cat_screams(self):
        player = self.make_player(volume=95)
        self.assertEqual(player.cat_mood(), "Screaming")

    def test_low_volume_cat_whispers(self):
        player = self.make_player(volume=5)
        self.assertEqual(player.cat_mood(), "Whispering")

    def test_pause_still_overrides_volume_moods(self):
        player = self.make_player(volume=100, paused=True)
        self.assertEqual(player.cat_mood(), "Loafing")

    def test_pet_cat_increments_scritches_and_creates_footer_incident(self):
        player = self.make_player()

        with mock.patch(
            "meowplayer.random.choice",
            return_value="made a tiny mrrp.",
        ):
            self.assertTrue(player.pet_cat())

        self.assertEqual(player.scritches, 1)
        self.assertIn("Scritch #1", player.status_message)
        self.assertIn("SCRITCH #1", player.cat_footer_message())

    def test_tenth_scritch_has_milestone_message(self):
        player = self.make_player()
        player.scritches = 9

        player.pet_cat()

        self.assertEqual(player.scritches, 10)
        self.assertIn("MILESTONE 10", player.cat_incident)

    def test_serious_mode_suppresses_cat_incidents(self):
        player = self.make_player(serious=True)

        self.assertFalse(
            player.trigger_cat_incident(
                "this should not happen",
                now=10.0,
            )
        )
        self.assertIsNone(player.cat_incident)
        self.assertEqual(player.cat_footer_message(now=10.0), "")

    def test_due_random_incident_appears_then_expires(self):
        player = self.make_player()
        player.next_cat_incident_at = 5.0

        with mock.patch(
            "meowplayer.random.choice",
            return_value=CAT_INCIDENTS[0],
        ), mock.patch(
            "meowplayer.random.uniform",
            return_value=60.0,
        ):
            self.assertTrue(player.maybe_trigger_cat_incident(now=5.0))

        self.assertIn("CAT INCIDENT", player.cat_footer_message(now=6.0))
        self.assertIn(CAT_INCIDENTS[0], player.cat_footer_message(now=6.0))

        footer = player.cat_footer_message(now=20.0)
        self.assertTrue(footer.startswith("🐱 "))
        self.assertIn("Ordinary cat quote.", footer)
        self.assertIn("cat", footer.casefold())
        self.assertIsNone(player.cat_incident)

    def test_incident_does_not_retrigger_while_active(self):
        player = self.make_player()
        player.cat_incident = "active chaos"
        player.cat_incident_until = 20.0
        player.next_cat_incident_at = 0.0

        self.assertFalse(player.maybe_trigger_cat_incident(now=10.0))
        self.assertEqual(player.cat_incident, "active chaos")


if __name__ == "__main__":
    unittest.main()
