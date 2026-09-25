import json
import unittest
from types import SimpleNamespace
from unittest import mock

from meowplayer import MeowPlayer, build_mpv_command, parse_args
from youtube_online import (
    YouTubeCatalog,
    YouTubeTrack,
    YouTubeUnavailable,
)


class FakeMPV:
    def __init__(self):
        self.loaded = []
        self.play_calls = 0
        self.properties = {
            "idle-active": False,
            "pause": False,
            "time-pos": 12.5,
            "duration": 200.0,
        }

    def load(self, value):
        self.loaded.append(str(value))

    def play(self):
        self.play_calls += 1

    def get_property(self, name):
        return self.properties.get(name)


class YouTubeOnlineTests(unittest.TestCase):
    def test_catalog_parses_flat_yt_dlp_results(self):
        payload = {
            "entries": [
                {
                    "id": "abc123",
                    "title": "Internet Song",
                    "channel": "Terminal Cat",
                    "duration": 245,
                    "thumbnail": "https://img.example/cover.jpg",
                },
                {
                    "id": "def456",
                    "title": "Second Song",
                    "uploader": "Other Cat",
                    "duration": None,
                },
            ]
        }

        tracks = YouTubeCatalog._tracks_from_payload(payload, limit=12)

        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0].video_id, "abc123")
        self.assertEqual(tracks[0].artist, "Terminal Cat")
        self.assertEqual(tracks[0].duration_label, "4:05")
        self.assertEqual(
            tracks[0].url,
            "https://www.youtube.com/watch?v=abc123",
        )
        self.assertEqual(tracks[1].duration_label, "--:--")

    def test_search_uses_keyless_ytsearch_without_downloading(self):
        payload = {
            "entries": [
                {
                    "id": "cat001",
                    "title": "Search Result",
                    "uploader": "Meow Channel",
                    "duration": 120,
                }
            ]
        }
        completed = SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )
        catalog = YouTubeCatalog(
            enabled=True,
            executable="/usr/bin/yt-dlp",
        )

        with mock.patch(
            "youtube_online.subprocess.run",
            return_value=completed,
        ) as run:
            tracks = catalog.search("porter robinson shelter", limit=5)

        self.assertEqual(len(tracks), 1)
        command = run.call_args.args[0]
        self.assertIn("--flat-playlist", command)
        self.assertIn("--skip-download", command)
        self.assertIn("ytsearch5:porter robinson shelter", command)

    def test_search_fails_soft_when_yt_dlp_is_missing(self):
        catalog = YouTubeCatalog(enabled=True, executable=None)
        catalog.executable = None

        with self.assertRaises(YouTubeUnavailable):
            catalog.search("cat music")

    def test_mpv_command_explicitly_enables_ytdl_audio(self):
        command = build_mpv_command("/tmp/meow-youtube.sock")

        self.assertIn("--ytdl=yes", command)
        self.assertIn("--ytdl-format=bestaudio/best", command)
        self.assertIn("--no-video", command)

    def test_cli_youtube_flag_is_opt_in(self):
        self.assertFalse(parse_args([]).youtube)
        self.assertTrue(parse_args(["--youtube"]).youtube)

    def test_play_online_clears_local_playback_state(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.current = 3
        player.online_current = None
        player.online_load_state = "idle"
        player.online_load_started_at = 0.0
        player.current_lyrics = object()
        player.lyrics_track_index = 3
        player.gapless_next_index = 4
        player._awaiting_mpv_path = True
        player.mpv = FakeMPV()
        player.sync_mpris = lambda force=False: None
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        track = YouTubeTrack(
            video_id="xyz987",
            title="Online Track",
            artist="Internet Artist",
            duration=180,
            url="https://www.youtube.com/watch?v=xyz987",
        )

        self.assertTrue(player.play_online(track))

        self.assertIsNone(player.current)
        self.assertIs(player.online_current, track)
        self.assertIsNone(player.current_lyrics)
        self.assertIsNone(player.gapless_next_index)
        self.assertFalse(player._awaiting_mpv_path)
        self.assertEqual(player.mpv.loaded, [track.url])
        self.assertEqual(player.mpv.play_calls, 1)
        self.assertIn("Resolving YouTube stream", statuses[-1][0])

    def test_repeated_enter_does_not_restart_same_online_stream(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.current = None
        player.online_current = None
        player.online_load_state = "idle"
        player.online_load_started_at = 0.0
        player.current_lyrics = None
        player.lyrics_track_index = None
        player.gapless_next_index = None
        player._awaiting_mpv_path = False
        player.mpv = FakeMPV()
        player.sync_mpris = lambda force=False: None
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        track = YouTubeTrack(
            video_id="same123",
            title="Same Track",
            artist="Internet Cat",
            duration=180,
            url="https://www.youtube.com/watch?v=same123",
        )

        self.assertTrue(player.play_online(track, now=100.0))
        self.assertFalse(player.play_online(track, now=100.2))
        self.assertFalse(player.play_online(track, now=101.0))

        self.assertEqual(player.mpv.loaded, [track.url])
        self.assertEqual(player.mpv.play_calls, 1)
        self.assertIn("Repeated Enter ignored", statuses[-1][0])

    def test_failed_online_stream_can_retry_after_guard_window(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.current = None
        player.online_current = None
        player.online_load_state = "idle"
        player.online_load_started_at = 0.0
        player.current_lyrics = None
        player.lyrics_track_index = None
        player.gapless_next_index = None
        player._awaiting_mpv_path = False
        player.mpv = FakeMPV()
        player.sync_mpris = lambda force=False: None
        player.set_status = lambda *args, **kwargs: None

        track = YouTubeTrack(
            video_id="retry123",
            title="Retry Track",
            artist="Internet Cat",
            duration=180,
            url="https://www.youtube.com/watch?v=retry123",
        )

        self.assertTrue(player.play_online(track, now=10.0))

        player.mpv.properties["idle-active"] = True
        player.mpv.properties["time-pos"] = None
        player.mpv.properties["duration"] = None

        self.assertTrue(player.refresh_online_playback_state(now=18.1))
        self.assertEqual(player.online_load_state, "failed")

        self.assertTrue(player.play_online(track, now=18.2))
        self.assertEqual(player.mpv.loaded, [track.url, track.url])
        self.assertEqual(player.mpv.play_calls, 2)
        self.assertEqual(player.online_load_state, "resolving")

    def test_online_stream_transitions_from_resolving_to_streaming(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.current = None
        player.online_current = None
        player.online_load_state = "idle"
        player.online_load_started_at = 0.0
        player.current_lyrics = None
        player.lyrics_track_index = None
        player.gapless_next_index = None
        player._awaiting_mpv_path = False
        player.mpv = FakeMPV()
        player.sync_mpris = lambda force=False: None
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        track = YouTubeTrack(
            video_id="ready123",
            title="Ready Track",
            artist="Internet Cat",
            duration=180,
            url="https://www.youtube.com/watch?v=ready123",
        )

        player.mpv.properties["time-pos"] = None
        player.mpv.properties["duration"] = None
        self.assertTrue(player.play_online(track, now=20.0))

        player.mpv.properties["time-pos"] = 0.0
        player.mpv.properties["duration"] = 180.0
        self.assertTrue(player.refresh_online_playback_state(now=21.0))

        self.assertEqual(player.online_load_state, "streaming")
        self.assertIn("Streaming from YouTube", statuses[-1][0])

    def test_mpris_snapshot_reports_online_track(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.current = None
        player.online_current = YouTubeTrack(
            video_id="a-b_c",
            title="Remote Song",
            artist="Remote Artist",
            duration=201,
            url="https://www.youtube.com/watch?v=a-b_c",
            thumbnail_url="https://img.example/thumb.jpg",
        )
        player.mpv = FakeMPV()
        player.repeat = False
        player.shuffle = False
        player.volume = 70
        player.songs = []
        player.youtube_results = [player.online_current]
        player.youtube = SimpleNamespace(enabled=True)

        snapshot = player.mpris_snapshot()

        self.assertEqual(snapshot["playback_status"], "Playing")
        self.assertTrue(snapshot["has_track"])
        self.assertTrue(snapshot["has_tracks"])
        self.assertEqual(snapshot["metadata"]["title"], "Remote Song")
        self.assertEqual(snapshot["metadata"]["artist"], "Remote Artist")
        self.assertEqual(
            snapshot["metadata"]["url"],
            "https://www.youtube.com/watch?v=a-b_c",
        )
        self.assertIn("youtube_a_b_c", snapshot["metadata"]["track_id"])


if __name__ == "__main__":
    unittest.main()
