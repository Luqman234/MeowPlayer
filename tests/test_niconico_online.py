import unittest
from types import SimpleNamespace
from unittest import mock

from meowplayer import MeowPlayer
from youtube_online import (
    YouTubeCatalog,
    YouTubeTrack,
    niconico_search_target,
    online_provider_label,
    online_track_key,
    youtube_download_command,
)


class NicoNicoOnlineTests(unittest.TestCase):
    def test_niconico_search_target_requests_all_results(self):
        self.assertEqual(
            niconico_search_target("初音ミク"),
            "nicosearchall:初音ミク",
        )

    def test_niconico_search_target_supports_bounded_results(self):
        self.assertEqual(
            niconico_search_target("vocaloid", limit=12),
            "nicosearch12:vocaloid",
        )

    def test_niconico_artist_prefix_uses_same_search_surface(self):
        self.assertEqual(
            niconico_search_target("artist:椎名もた"),
            "nicosearchall:椎名もた",
        )

    def test_niconico_payload_becomes_provider_aware_track(self):
        tracks = YouTubeCatalog._tracks_from_payload(
            {
                "entries": [
                    {
                        "id": "sm9",
                        "title": "Nico Song",
                        "uploader": "Nico Creator",
                        "uploader_id": "419948",
                        "duration": 185,
                    }
                ]
            },
            provider="niconico",
        )

        self.assertEqual(len(tracks), 1)
        track = tracks[0]
        self.assertEqual(track.video_id, "sm9")
        self.assertEqual(track.provider, "niconico")
        self.assertEqual(track.provider_label, "NicoNico")
        self.assertEqual(
            track.url,
            "https://www.nicovideo.jp/watch/sm9",
        )
        self.assertEqual(
            track.channel_url,
            "https://www.nicovideo.jp/user/419948",
        )
        self.assertIn("NicoNico", track.queue_label)

    def test_niconico_payload_preserves_extractor_webpage_url(self):
        track = YouTubeCatalog._tracks_from_payload(
            {
                "entries": [
                    {
                        "id": "sm123",
                        "title": "Extractor URL",
                        "uploader": "Creator",
                        "webpage_url": "https://www.nicovideo.jp/watch/sm123",
                    }
                ]
            },
            provider="niconico",
        )[0]

        self.assertEqual(
            track.url,
            "https://www.nicovideo.jp/watch/sm123",
        )

    def test_provider_identity_separates_same_remote_id(self):
        youtube = YouTubeTrack(
            "same-id",
            "YouTube Song",
            "Creator",
            60,
            "https://www.youtube.com/watch?v=same-id",
        )
        niconico = YouTubeTrack(
            "same-id",
            "Nico Song",
            "Creator",
            60,
            "https://www.nicovideo.jp/watch/same-id",
            provider="niconico",
        )

        self.assertNotEqual(
            online_track_key(youtube),
            online_track_key(niconico),
        )
        self.assertEqual(online_provider_label("niconico"), "NicoNico")

    def test_open_niconico_search_uses_niconico_session(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.youtube = SimpleNamespace(enabled=True, available=True)
        player.youtube_search_session = None
        player.youtube_query = ""
        player.youtube_search_mode = "all"
        player.online_provider = "youtube"
        player.youtube_results = []
        player.youtube_selected = 0
        player._prefetch_selection = None
        player.view = "library"
        player.text = lambda serious, cat: serious
        player.prompt_text = lambda _screen, _prompt: "初音ミク"
        player.set_status = lambda *_args: None

        with mock.patch("meowplayer.NicoNicoSearchSession") as session:
            self.assertTrue(player.open_niconico_search(object()))

        session.assert_called_once_with(
            player.youtube,
            "初音ミク",
            search_mode="all",
        )
        self.assertEqual(player.online_provider, "niconico")
        self.assertEqual(player.youtube_query, "初音ミク")
        self.assertEqual(player.view, "online")

    def test_niconico_result_does_not_enter_youtube_creator_nest(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.youtube_results = [
            YouTubeTrack(
                "sm9",
                "Nico Song",
                "Nico Creator",
                120,
                "https://www.nicovideo.jp/watch/sm9",
                provider="niconico",
            )
        ]
        player.youtube_selected = 0
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        self.assertFalse(player.open_selected_youtube_creator())
        self.assertIn("YouTube results only", statuses[-1][0])

    def test_download_command_accepts_niconico_track_url(self):
        track = YouTubeTrack(
            "sm9",
            "Nico Song",
            "Nico Creator",
            120,
            "https://www.nicovideo.jp/watch/sm9",
            provider="niconico",
        )

        command = youtube_download_command(
            "/usr/bin/yt-dlp",
            track,
            "/music/Internet Nest",
            ffmpeg_executable="/usr/bin/ffmpeg",
        )

        self.assertEqual(command[-1], track.url)


if __name__ == "__main__":
    unittest.main()
