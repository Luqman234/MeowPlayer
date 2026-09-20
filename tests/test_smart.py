import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from meow_smart import (
    SmartRuleError,
    build_smart_playlists,
    compile_rule,
    load_custom_mix_definitions,
    rule_matches,
)


def meta(
    index,
    *,
    artist="Artist",
    album="Album",
    genre="",
    track_number=1,
    year="2020",
    duration=240.0,
    tagged=True,
):
    return SimpleNamespace(
        path=Path(f"/music/{index}.flac"),
        title=f"Track {index}",
        artist=artist,
        album=album,
        genre=genre,
        track_number=track_number,
        year=year,
        duration=duration,
        tagged=tagged,
        album_artist=artist,
        filename=f"{index}.flac",
        folder="Music",
    )


class SmartPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.metadata = [
            meta(0, artist="Alpha", genre="Dream Pop"),
            meta(1, artist="Beta", genre="Rock"),
            meta(2, artist="Alpha", genre="Dream Pop"),
            meta(3, artist="Gamma", genre=""),
        ]
        self.stats = {
            str(Path("/music/0.flac").resolve()): {
                "favorite": True,
                "rating": 5,
                "play_count": 5,
                "last_played_ns": 400,
                "added_at_ns": 10,
            },
            str(Path("/music/1.flac").resolve()): {
                "favorite": False,
                "rating": 3,
                "play_count": 1,
                "last_played_ns": 300,
                "added_at_ns": 40,
            },
            str(Path("/music/2.flac").resolve()): {
                "favorite": True,
                "rating": 4,
                "play_count": 9,
                "last_played_ns": 200,
                "added_at_ns": 30,
            },
            str(Path("/music/3.flac").resolve()): {
                "favorite": False,
                "rating": 0,
                "play_count": 0,
                "last_played_ns": None,
                "added_at_ns": 20,
            },
        }

    def playlists(self):
        return {
            playlist.key: playlist
            for playlist in build_smart_playlists(
                self.metadata,
                self.stats,
            )
        }

    def test_core_smart_playlists_are_generated(self):
        playlists = self.playlists()

        self.assertEqual(playlists["pawmarked"].indices, (0, 2))
        self.assertEqual(playlists["recent"].indices, (0, 1, 2))
        self.assertEqual(playlists["most-played"].indices, (2, 0, 1))
        self.assertEqual(playlists["unplayed"].indices, (3,))
        self.assertEqual(playlists["top-rated"].indices, (0, 2, 1))

    def test_rule_engine_supports_rating_as_numeric_field(self):
        expression = compile_rule(
            "rating >= 4 and play_count >= 5"
        )

        self.assertTrue(
            rule_matches(expression, self.metadata, self.stats, 0)
        )
        self.assertFalse(
            rule_matches(expression, self.metadata, self.stats, 1)
        )
        self.assertTrue(
            rule_matches(expression, self.metadata, self.stats, 2)
        )
        self.assertFalse(
            rule_matches(expression, self.metadata, self.stats, 3)
        )

    def test_fresh_finds_are_sorted_by_added_time(self):
        playlists = self.playlists()

        self.assertEqual(
            playlists["fresh"].indices,
            (1, 2, 3, 0),
        )

    def test_rule_engine_supports_text_numeric_boolean_and_parentheses(self):
        expression = compile_rule(
            '(genre ~ "dream" and favorite = true) '
            'or play_count >= 9'
        )

        self.assertTrue(
            rule_matches(expression, self.metadata, self.stats, 0)
        )
        self.assertFalse(
            rule_matches(expression, self.metadata, self.stats, 1)
        )
        self.assertTrue(
            rule_matches(expression, self.metadata, self.stats, 2)
        )

    def test_rule_engine_supports_not_and_aliases(self):
        expression = compile_rule(
            'not pawmarked = true and plays = 0'
        )

        self.assertTrue(
            rule_matches(expression, self.metadata, self.stats, 3)
        )
        self.assertFalse(
            rule_matches(expression, self.metadata, self.stats, 0)
        )

    def test_invalid_field_is_rejected(self):
        with self.assertRaises(SmartRuleError):
            compile_rule('mood = "sleepy"')

    def test_custom_mix_file_builds_sorted_limited_playlist(self):
        payload = {
            "mixes": [
                {
                    "name": "Dream Favorites",
                    "rule": 'genre ~ "Dream" and favorite = true and rating >= 4',
                    "sort": "-rating",
                    "limit": 1,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smart-mixes.json"
            path.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            definitions, errors = load_custom_mix_definitions(path)

        self.assertEqual(errors, [])
        playlists = {
            playlist.key: playlist
            for playlist in build_smart_playlists(
                self.metadata,
                self.stats,
                definitions,
            )
        }

        custom = next(
            playlist
            for key, playlist in playlists.items()
            if key.startswith("custom:dream-favorites")
        )
        self.assertEqual(custom.indices, (2,))

    def test_bad_custom_rule_does_not_break_other_mixes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smart-mixes.json"
            path.write_text(
                json.dumps([
                    {
                        "name": "Broken",
                        "rule": "genre ??? rock",
                    }
                ]),
                encoding="utf-8",
            )
            definitions, errors = load_custom_mix_definitions(path)

        self.assertEqual(definitions, [])
        self.assertEqual(len(errors), 1)

    def test_genre_mixes_are_created_from_real_library_genres(self):
        playlists = self.playlists()

        self.assertIn("genre:Dream Pop", playlists)
        self.assertIn("genre:Rock", playlists)
        self.assertEqual(
            playlists["genre:Dream Pop"].indices,
            (0, 2),
        )
        self.assertNotIn("genre:", playlists)


if __name__ == "__main__":
    unittest.main()
