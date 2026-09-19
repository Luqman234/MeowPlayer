import unittest

from visualizer import AudioVisualizer


class VisualizerTests(unittest.TestCase):
    def test_config_uses_raw_ascii_output(self):
        visualizer = AudioVisualizer(enabled=False, bars=24)
        config = visualizer._config()

        self.assertIn("bars = 24", config)
        self.assertIn("method = raw", config)
        self.assertIn("data_format = ascii", config)
        self.assertIn("raw_target = /dev/stdout", config)
        self.assertIn("channels = mono", config)

    def test_render_maps_values_to_unicode_bars(self):
        visualizer = AudioVisualizer(enabled=False, bars=8)
        visualizer.visible = True
        visualizer._latest = [0, 125, 250, 375, 500, 625, 750, 1000]

        rendered = visualizer.render(80)

        self.assertEqual(len(rendered), 8)
        self.assertEqual(rendered[0], "▁")
        self.assertEqual(rendered[-1], "█")

    def test_render_reduces_bar_count_to_width(self):
        visualizer = AudioVisualizer(enabled=False, bars=8)
        visualizer.visible = True
        visualizer._latest = [100] * 8

        rendered = visualizer.render(4)

        self.assertEqual(len(rendered), 4)

    def test_hidden_visualizer_renders_nothing(self):
        visualizer = AudioVisualizer(enabled=False)
        visualizer._latest = [1000] * 8

        self.assertEqual(visualizer.render(20), "")


if __name__ == "__main__":
    unittest.main()
