import tempfile
import unittest
from pathlib import Path

from album_art import AlbumArtManager


class AlbumArtTests(unittest.TestCase):
    def test_folder_cover_lookup_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            track = root / "song.flac"
            cover = root / "Cover.JPG"
            track.write_bytes(b"audio")
            cover.write_bytes(b"image")

            manager = AlbumArtManager(enabled=False)

            self.assertEqual(
                manager._folder_cover(track),
                cover,
            )

    def test_kitty_renderer_transmits_png_and_reuses_image(self):
        manager = AlbumArtManager(enabled=False)
        manager.supported = True
        writes = []
        manager._write = writes.append

        image = Path("/tmp/meowplayer-test-cover.png")

        manager.render(
            image,
            row=1,
            column=70,
            columns=20,
            rows=9,
        )
        manager.render(
            image,
            row=1,
            column=70,
            columns=20,
            rows=9,
        )

        combined = "".join(writes)

        self.assertEqual(
            combined.count("a=t,t=f,f=100"),
            1,
        )
        self.assertEqual(
            combined.count("a=p,i="),
            2,
        )
        self.assertIn("c=20,r=9,C=1", combined)

    def test_clear_can_soft_delete_without_forgetting_transmission(self):
        manager = AlbumArtManager(enabled=False)
        manager.supported = True
        manager._transmitted = "/tmp/cover.png"
        writes = []
        manager._write = writes.append

        manager.clear(free_data=False)

        self.assertEqual(
            manager._transmitted,
            "/tmp/cover.png",
        )
        self.assertIn("a=d,d=i", writes[0])


if __name__ == "__main__":
    unittest.main()
