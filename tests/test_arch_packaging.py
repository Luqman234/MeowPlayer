import re
import unittest
from pathlib import Path

import meowplayer


ROOT = Path(__file__).resolve().parents[1]
PKGBUILD = ROOT / "PKGBUILD"


class ArchPackagingTests(unittest.TestCase):
    def text(self):
        return PKGBUILD.read_text(encoding="utf-8")

    def test_pkgbuild_version_matches_runtime(self):
        match = re.search(r"^pkgver=(.+)$", self.text(), re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), meowplayer.__version__)

    def test_pkgbuild_pins_release_source_commit(self):
        match = re.search(
            r"^_commit='([0-9a-f]{40})'$",
            self.text(),
            re.MULTILINE,
        )
        self.assertIsNotNone(match)
        self.assertIn("#commit=$_commit", self.text())

    def test_pkgbuild_exercises_tests_and_installs_wheel(self):
        text = self.text()
        self.assertIn("python -m unittest discover -s tests -v", text)
        self.assertIn("python -m build --wheel --no-isolation", text)
        self.assertIn('python -m installer --destdir="$pkgdir"', text)

    def test_pkgbuild_declares_core_arch_dependencies(self):
        text = self.text()
        for package in (
            "python",
            "mpv",
            "yt-dlp",
            "cava",
            "playerctl",
            "python-mutagen",
            "python-dbus-next",
            "python-pillow",
            "python-watchdog",
        ):
            self.assertIn(f"'{package}'", text)

        self.assertNotIn("optdepends=(", text)


if __name__ == "__main__":
    unittest.main()
