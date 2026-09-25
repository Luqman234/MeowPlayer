import unittest
from unittest import mock

from meowplayer import MeowPlayer
from meow_persistence import DEFAULT_CONFIG
from settings_nest import (
    SETTINGS_SPECS,
    adjust_setting_value,
    format_setting_value,
    setting_spec,
)


class SettingsNestTests(unittest.TestCase):
    def test_every_setting_maps_to_persistent_config(self):
        missing = [
            spec.key
            for spec in SETTINGS_SPECS
            if spec.key not in DEFAULT_CONFIG
        ]
        self.assertEqual(missing, [])

    def test_boolean_setting_toggles(self):
        spec = setting_spec("lyrics_enabled")
        self.assertFalse(adjust_setting_value(spec, True, 1))
        self.assertTrue(adjust_setting_value(spec, False, -1))

    def test_choice_setting_cycles_both_directions(self):
        spec = setting_spec("gapless_mode")
        self.assertEqual(adjust_setting_value(spec, "weak", 1), "yes")
        self.assertEqual(adjust_setting_value(spec, "weak", -1), "no")
        self.assertEqual(adjust_setting_value(spec, "yes", 1), "no")

    def test_float_setting_respects_step_and_bounds(self):
        spec = setting_spec("replaygain_preamp")
        self.assertEqual(adjust_setting_value(spec, 0.0, 1), 0.5)
        self.assertEqual(adjust_setting_value(spec, 0.0, -1), -0.5)
        self.assertEqual(adjust_setting_value(spec, 20.0, 1), 20.0)
        self.assertEqual(adjust_setting_value(spec, -20.0, -1), -20.0)
        self.assertEqual(format_setting_value(spec, -1.5), "-1.5 dB")

    def test_gapless_setting_applies_live_and_persists(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.serious_mode = True
        player.app_config = {"gapless_mode": "weak"}
        player.settings_selected = next(
            i for i, spec in enumerate(SETTINGS_SPECS)
            if spec.key == "gapless_mode"
        )
        player.gapless_mode = "weak"
        player.mpv = mock.Mock()
        player.prime_gapless_next = mock.Mock()
        player.status_message = ""

        with mock.patch("meowplayer.save_config", return_value=True) as save:
            changed = player.change_selected_setting(direction=1)

        self.assertTrue(changed)
        self.assertEqual(player.app_config["gapless_mode"], "yes")
        self.assertEqual(player.gapless_mode, "yes")
        player.mpv.set_property.assert_called_once_with("gapless-audio", "yes")
        player.prime_gapless_next.assert_called_once()
        save.assert_called_once()
        self.assertIn("(live)", player.status_message)

    def test_next_launch_setting_is_saved_but_not_applied_live(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.serious_mode = True
        player.app_config = {"mpris_enabled": True}
        player.settings_selected = next(
            i for i, spec in enumerate(SETTINGS_SPECS)
            if spec.key == "mpris_enabled"
        )
        player.status_message = ""

        with mock.patch("meowplayer.save_config", return_value=True):
            with mock.patch.object(
                player,
                "_apply_live_setting",
                wraps=player._apply_live_setting,
            ) as apply_live:
                changed = player.change_selected_setting(direction=1)

        self.assertTrue(changed)
        self.assertFalse(player.app_config["mpris_enabled"])
        apply_live.assert_called_once()
        self.assertIn("next launch", player.status_message)

    def test_settings_nest_returns_to_previous_view(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.serious_mode = False
        player.view = "online"
        player.settings_return_view = "library"
        player.settings_selected = 0
        player.status_message = ""

        player.open_settings_nest()
        self.assertEqual(player.view, "settings")
        self.assertEqual(player.settings_return_view, "online")

        player.close_settings_nest()
        self.assertEqual(player.view, "online")
        self.assertIn("Settings Nest closed", player.status_message)

    def test_lyrics_setting_applies_live(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.serious_mode = True
        player.app_config = {"lyrics_enabled": True}
        player.settings_selected = next(
            i for i, spec in enumerate(SETTINGS_SPECS)
            if spec.key == "lyrics_enabled"
        )
        player.lyrics = mock.Mock()
        player.lyrics.enabled = True
        player.current_lyrics = object()
        player.status_message = ""

        with mock.patch("meowplayer.save_config", return_value=True):
            player.change_selected_setting(direction=1)

        self.assertFalse(player.lyrics.enabled)
        self.assertIsNone(player.current_lyrics)


if __name__ == "__main__":
    unittest.main()
