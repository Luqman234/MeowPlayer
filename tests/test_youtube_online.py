import queue
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from meowplayer import (
    MeowPlayer,
    _prompt_input_window,
    build_mpv_command,
    parse_args,
)
from youtube_online import (
    YouTubeCatalog,
    YouTubePlaylist,
    YouTubeTrack,
    YouTubeUnavailable,
    normalize_youtube_search,
    youtube_creator_browse_targets,
    youtube_creator_section_url,
    youtube_music_album_search_url,
    youtube_download_command,
    youtube_search_target,
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


class _PromptScreen:
    def __init__(self, keys, width=24, height=12):
        self.keys = list(keys)
        self.width = width
        self.height = height
        self.rendered = []

    def getmaxyx(self):
        return self.height, self.width

    def nodelay(self, value):
        pass

    def timeout(self, value):
        pass

    def move(self, y, x):
        pass

    def clrtoeol(self):
        pass

    def addstr(self, y, x, value, *args):
        self.rendered.append((y, x, value))

    def refresh(self):
        pass

    def get_wch(self):
        if not self.keys:
            return "\n"
        return self.keys.pop(0)


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

    def test_prompt_input_window_scrolls_without_truncating_buffer(self):
        query = "a very long song title that cannot fit on a phone screen"

        visible = _prompt_input_window(query, 12)

        self.assertEqual(len(visible), 12)
        self.assertTrue(visible.startswith("<"))
        self.assertTrue(query.endswith(visible[1:]))

    def test_prompt_text_accepts_query_longer_than_terminal_width(self):
        query = "this title is much longer than twenty four columns"
        screen = _PromptScreen([*query, "\n"], width=24)
        player = MeowPlayer.__new__(MeowPlayer)

        with mock.patch("meowplayer.curses.curs_set"):
            value = player.prompt_text(screen, "Internet Nest search")

        self.assertEqual(value, query)
        self.assertGreater(len(value), screen.width)

    def test_prompt_text_backspace_operates_on_full_hidden_buffer(self):
        query = "abcdefghijklmnopqrstuvwxyz"
        screen = _PromptScreen(
            [*query, "\b", "\b", "Y", "Z", "\n"],
            width=16,
        )
        player = MeowPlayer.__new__(MeowPlayer)

        with mock.patch("meowplayer.curses.curs_set"):
            value = player.prompt_text(screen, "YouTube search")

        self.assertEqual(value, "abcdefghijklmnopqrstuvwxYZ")

    def test_search_aggregates_background_results(self):
        import queue
        results = queue.SimpleQueue()
        track = YouTubeTrack("cat001", "Search Result", "Meow Channel", 120, "https://youtube.com/watch?v=cat001")
        results.put(("track", track))
        results.put(("done", None))
        catalog = YouTubeCatalog(enabled=True, executable="/usr/bin/yt-dlp")
        with mock.patch("youtube_online.YouTubeSearchSession") as session:
            session.return_value.results = results
            self.assertEqual(catalog.search("shelter", limit=5), [track])
            session.assert_called_once_with(catalog, "shelter", limit=5, search_mode="all")
            session.return_value.close.assert_called_once()

    def test_search_payload_preserves_channel_identity(self):
        payload = {
            "entries": [
                {
                    "id": "creator001",
                    "title": "Creator Song",
                    "channel": "Creator Cat",
                    "channel_id": "UCcreator",
                    "channel_url": "https://www.youtube.com/@creatorcat",
                    "duration": 123,
                }
            ]
        }

        tracks = YouTubeCatalog._tracks_from_payload(payload)

        self.assertEqual(tracks[0].channel_id, "UCcreator")
        self.assertEqual(
            tracks[0].channel_url,
            "https://www.youtube.com/@creatorcat",
        )

    def test_topic_channel_uploads_fall_back_to_channel_root(self):
        targets = youtube_creator_browse_targets(
            "https://www.youtube.com/channel/UCtopic",
            "uploads",
        )

        self.assertEqual(
            targets,
            (
                "https://www.youtube.com/channel/UCtopic/videos",
                "https://www.youtube.com/channel/UCtopic",
            ),
        )

    def test_youtube_music_album_search_targets_album_section(self):
        self.assertEqual(
            youtube_music_album_search_url("Creator Cat"),
            "https://music.youtube.com/search?q=Creator+Cat#albums",
        )

    def test_topic_suffix_is_removed_from_music_album_search(self):
        self.assertEqual(
            youtube_music_album_search_url("Creator Cat - Topic"),
            "https://music.youtube.com/search?q=Creator+Cat#albums",
        )

    def test_topic_playlists_fall_back_to_music_album_search(self):
        targets = youtube_creator_browse_targets(
            "https://www.youtube.com/channel/UCtopic",
            "playlists",
            "Creator Cat",
        )

        self.assertEqual(
            targets,
            (
                "https://www.youtube.com/channel/UCtopic/playlists",
                "https://www.youtube.com/channel/UCtopic/releases",
                "https://music.youtube.com/search?q=Creator+Cat#albums",
            ),
        )

    def test_release_url_without_explicit_id_is_kept_as_playlist(self):
        playlist = YouTubeCatalog._playlist_from_entry(
            {
                "url": (
                    "https://www.youtube.com/playlist"
                    "?list=OLAK5uy_release123"
                ),
                "album": "Release Album",
                "artist": "Creator Cat",
            }
        )

        self.assertIsInstance(playlist, YouTubePlaylist)
        self.assertEqual(
            playlist.playlist_id,
            "OLAK5uy_release123",
        )
        self.assertEqual(playlist.title, "Release Album")

    def test_creator_playlists_fall_back_to_releases(self):
        targets = youtube_creator_browse_targets(
            "https://www.youtube.com/@creatorcat",
            "playlists",
        )

        self.assertEqual(
            targets,
            (
                "https://www.youtube.com/@creatorcat/playlists",
                "https://www.youtube.com/@creatorcat/releases",
            ),
        )

    def test_creator_section_url_normalizes_releases_to_channel_root(self):
        self.assertEqual(
            youtube_creator_section_url(
                "https://www.youtube.com/@creatorcat/releases",
                "videos",
            ),
            "https://www.youtube.com/@creatorcat/videos",
        )

    def test_creator_section_urls_are_built_from_channel_root(self):
        self.assertEqual(
            youtube_creator_section_url(
                "https://www.youtube.com/@creatorcat/videos",
                "playlists",
            ),
            "https://www.youtube.com/@creatorcat/playlists",
        )
        self.assertEqual(
            youtube_creator_section_url(
                "https://www.youtube.com/channel/UCcreator",
                "videos",
            ),
            "https://www.youtube.com/channel/UCcreator/videos",
        )

    def test_playlist_payload_becomes_creator_playlist(self):
        playlist = YouTubeCatalog._playlist_from_entry(
            {
                "id": "PLcat",
                "title": "Cat Songs",
                "channel": "Creator Cat",
                "playlist_count": 12,
            }
        )

        self.assertIsInstance(playlist, YouTubePlaylist)
        self.assertEqual(playlist.playlist_id, "PLcat")
        self.assertEqual(playlist.count_label, "12 tracks")
        self.assertEqual(
            playlist.url,
            "https://www.youtube.com/playlist?list=PLcat",
        )

    def test_open_selected_creator_uses_channel_url_not_artist_research(self):
        player = MeowPlayer.__new__(MeowPlayer)
        track = YouTubeTrack(
            "creator002",
            "Direct Channel Track",
            "Creator Cat",
            120,
            "https://www.youtube.com/watch?v=creator002",
            channel_id="UCcreator",
            channel_url="https://www.youtube.com/@creatorcat",
        )
        player.youtube_results = [track]
        player.youtube_selected = 0
        player.creator_session = None
        player.view = "online"
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        self.assertTrue(player.open_selected_youtube_creator())

        self.assertEqual(player.view, "creator")
        self.assertEqual(player.creator_name, "Creator Cat")
        self.assertEqual(
            player.creator_channel_url,
            "https://www.youtube.com/@creatorcat",
        )
        self.assertEqual(player.creator_level, "menu")
        self.assertIn("Opened creator channel", statuses[-1][0])

    def test_creator_menu_opens_uploads_and_playlists(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.creator_name = "Creator Cat"
        player.creator_channel_url = "https://www.youtube.com/@creatorcat"
        player.creator_session = None
        player.creator_items = []
        player.creator_selected = 0
        player.creator_level = "menu"
        player.creator_playlist = None
        player.youtube = SimpleNamespace(timeout=20)
        player.set_status = lambda *args: None

        with mock.patch("meowplayer.YouTubeBrowseSession") as session:
            self.assertTrue(player.activate_creator_selection())

        session.assert_called_once_with(
            player.youtube,
            "https://www.youtube.com/@creatorcat",
            "uploads",
            creator_name="Creator Cat",
        )

    def test_artist_prefix_selects_artist_search_mode(self):
        query, mode = normalize_youtube_search("artist:Porter Robinson")
        self.assertEqual(query, "Porter Robinson")
        self.assertEqual(mode, "artist")

    def test_default_search_target_requests_all_results(self):
        self.assertEqual(
            youtube_search_target("porter robinson shelter"),
            "ytsearchall:porter robinson shelter",
        )

    def test_default_artist_search_target_requests_all_results(self):
        self.assertEqual(
            youtube_search_target(
                "Porter Robinson",
                search_mode="artist",
            ),
            'ytsearchall:"Porter Robinson" music',
        )

    def test_catalog_defaults_to_unbounded_search_results(self):
        catalog = YouTubeCatalog(
            enabled=True,
            executable="/usr/bin/yt-dlp",
        )
        self.assertIsNone(catalog.default_limit)

    def test_payload_parser_has_no_default_twelve_result_cap(self):
        entries = [
            {
                "id": f"video-{index}",
                "title": f"Song {index}",
                "channel": "Many Cats",
                "duration": 120,
            }
            for index in range(20)
        ]

        tracks = YouTubeCatalog._tracks_from_payload(
            {"entries": entries}
        )

        self.assertEqual(len(tracks), 20)

    def test_artist_search_target_biases_youtube_search_toward_artist(self):
        target = youtube_search_target("Porter Robinson", 12, "artist")
        self.assertEqual(target, 'ytsearch12:"Porter Robinson" music')

    def test_artist_search_target_sanitizes_embedded_quotes(self):
        target = youtube_search_target('A "Quoted" Artist', 12, "artist")
        self.assertEqual(target, 'ytsearch12:"A Quoted Artist" music')

    def test_internet_nest_artist_search_tracks_mode_and_query(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.youtube = SimpleNamespace(enabled=True, available=True)
        player.youtube_search_session = None
        player.youtube_results = [object()]
        player.youtube_selected = 4
        player._prefetch_selection = "old"
        player.view = "library"
        player.text = lambda serious, cat: serious
        player.prompt_text = mock.Mock(return_value="Porter Robinson")
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        with mock.patch("meowplayer.YouTubeSearchSession") as session:
            self.assertTrue(player.open_youtube_search(object(), search_mode="artist"))

        self.assertEqual(player.youtube_query, "Porter Robinson")
        self.assertEqual(player.youtube_search_mode, "artist")
        self.assertEqual(player.youtube_results, [])
        self.assertEqual(player.youtube_selected, 0)
        self.assertIsNone(player._prefetch_selection)
        self.assertEqual(player.view, "online")
        session.assert_called_once_with(
            player.youtube,
            "Porter Robinson",
            search_mode="artist",
        )
        self.assertIn("artist: Porter Robinson", statuses[-1][0])
    def test_search_fails_soft_when_yt_dlp_is_missing(self):
        catalog = YouTubeCatalog(enabled=True, executable=None)
        catalog.executable = None

        with self.assertRaises(YouTubeUnavailable):
            catalog.search("cat music")

    def test_download_command_saves_opus_into_requested_library_folder(self):
        track = YouTubeTrack(
            video_id="adopt123",
            title="Adopt Me",
            artist="Internet Cat",
            duration=180,
            url="https://www.youtube.com/watch?v=adopt123",
        )

        command = youtube_download_command(
            "/usr/bin/yt-dlp",
            track,
            Path("/music/Internet Nest"),
            ffmpeg_executable="/usr/bin/ffmpeg",
        )

        self.assertEqual(command[0], "/usr/bin/yt-dlp")
        self.assertIn("--no-playlist", command)
        self.assertIn("--no-overwrites", command)
        self.assertIn("--extract-audio", command)
        self.assertIn("--embed-metadata", command)
        self.assertIn("opus", command)
        self.assertIn("/usr/bin/ffmpeg", command)
        self.assertIn(
            "/music/Internet Nest/%(title)s [%(id)s].%(ext)s",
            command,
        )
        self.assertEqual(command[-1], track.url)

    def test_internet_nest_download_targets_library_subfolder(self):
        player = MeowPlayer.__new__(MeowPlayer)
        track = YouTubeTrack(
            video_id="adopt456",
            title="Take Me Home",
            artist="Internet Cat",
            duration=181,
            url="https://www.youtube.com/watch?v=adopt456",
        )
        player.youtube_results = [track]
        player.youtube_selected = 0
        player.youtube_download_session = None
        player.youtube_download_track = None
        player.youtube = SimpleNamespace(executable="/usr/bin/yt-dlp")
        player.music_dir = Path("/music")
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        with mock.patch("meowplayer.YouTubeDownloadSession") as session:
            self.assertTrue(player.download_selected_youtube_result())

        session.assert_called_once_with(
            "/usr/bin/yt-dlp",
            track,
            Path("/music/Internet Nest"),
        )
        self.assertIs(player.youtube_download_track, track)
        self.assertIn("Downloading to library", statuses[-1][0])

    def test_internet_nest_download_rejects_second_concurrent_adoption(self):
        player = MeowPlayer.__new__(MeowPlayer)
        track = YouTubeTrack(
            video_id="busy123",
            title="Already Going",
            artist="Internet Cat",
            duration=182,
            url="https://www.youtube.com/watch?v=busy123",
        )
        player.youtube_results = [track]
        player.youtube_selected = 0
        player.youtube_download_track = track
        player.youtube_download_session = object()
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        self.assertFalse(player.download_selected_youtube_result())
        self.assertIn("already in progress", statuses[-1][0])

    def test_completed_internet_nest_download_rescans_library(self):
        player = MeowPlayer.__new__(MeowPlayer)
        track = YouTubeTrack(
            video_id="done123",
            title="Home Now",
            artist="Internet Cat",
            duration=183,
            url="https://www.youtube.com/watch?v=done123",
        )
        results = queue.SimpleQueue()
        downloaded = Path("/music/Internet Nest/Home Now [done123].opus")
        results.put(("done", downloaded))
        session = SimpleNamespace(
            results=results,
            close=mock.Mock(),
        )
        player.youtube_download_session = session
        player.youtube_download_track = track
        player.rescan_library = mock.Mock()
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        self.assertTrue(player.process_youtube_download())

        session.close.assert_called_once()
        player.rescan_library.assert_called_once_with(
            {"paths": (str(downloaded),)}
        )
        self.assertIsNone(player.youtube_download_session)
        self.assertIsNone(player.youtube_download_track)
        self.assertIn("Downloaded to library", statuses[-1][0])

    def test_failed_internet_nest_download_clears_busy_state(self):
        player = MeowPlayer.__new__(MeowPlayer)
        results = queue.SimpleQueue()
        results.put(("error", "ffmpeg is required"))
        session = SimpleNamespace(
            results=results,
            close=mock.Mock(),
        )
        player.youtube_download_session = session
        player.youtube_download_track = None
        player.rescan_library = mock.Mock()
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

        self.assertTrue(player.process_youtube_download())

        session.close.assert_called_once()
        player.rescan_library.assert_not_called()
        self.assertIsNone(player.youtube_download_session)
        self.assertIn("Download failed", statuses[-1][0])

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
        player.lyrics = SimpleNamespace(
            load_transient=mock.Mock(),
        )
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
        player.lyrics.load_transient.assert_called_once_with(
            "xyz987",
            title="Online Track",
            artist="Internet Artist",
            duration=180,
        )
        self.assertIsNone(player.gapless_next_index)
        self.assertFalse(player._awaiting_mpv_path)
        self.assertEqual(player.mpv.loaded, [track.url])
        self.assertEqual(player.mpv.play_calls, 1)
        self.assertIn("Loading YouTube stream", statuses[-1][0])

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

        self.assertTrue(player.refresh_online_playback_state(now=player._online_load_sent + 31))
        self.assertEqual(player.online_load_state, "failed")

        self.assertTrue(player.play_online(track, now=18.2))
        self.assertEqual(player.mpv.loaded, [track.url, track.url])
        self.assertEqual(player.mpv.play_calls, 2)
        self.assertEqual(player.online_load_state, "loading")

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

        player.mpv.playback_events = {name: player._online_load_sent + 0.1
                                      for name in ("start-file", "file-loaded", "playback-restart")}
        player.mpv.properties["time-pos"] = 0.1
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
