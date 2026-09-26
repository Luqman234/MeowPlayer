import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from google_account import (
    GoogleAccountClient,
    GoogleAuthHelper,
    GoogleChannel,
    GooglePlaylist,
    GooglePlaylistTrack,
    GoogleSubscription,
)
from meowplayer import MeowPlayer, parse_args


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class GoogleAccountTests(unittest.TestCase):
    def auth(self, **overrides):
        values = {
            "configured": True,
            "connected": True,
            "login": mock.Mock(return_value=True),
            "token": mock.Mock(return_value="access-token"),
            "logout": mock.Mock(return_value=True),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def client(self, **auth_overrides):
        return GoogleAccountClient(
            auth_helper=self.auth(**auth_overrides)
        )

    def test_google_account_flag_is_opt_in(self):
        self.assertFalse(parse_args([]).google_account)
        self.assertTrue(parse_args(["--google-account"]).google_account)

    def test_google_auth_command_is_configurable(self):
        args = parse_args(
            [
                "--google-account",
                "--google-auth-command",
                "/tmp/custom-google-helper",
            ]
        )
        self.assertTrue(args.google_account)
        self.assertEqual(
            args.google_auth_command,
            "/tmp/custom-google-helper",
        )

    def test_helper_status_defines_connected_state(self):
        runner = mock.Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout="connected\n",
                stderr="",
            )
        )
        helper = GoogleAuthHelper(sys.executable, runner=runner)

        self.assertTrue(helper.connected)
        runner.assert_called_once()
        self.assertEqual(
            runner.call_args.args[0],
            [sys.executable, "status"],
        )

    def test_helper_status_exit_one_means_disconnected(self):
        runner = mock.Mock(
            return_value=SimpleNamespace(
                returncode=1,
                stdout="disconnected\n",
                stderr="",
            )
        )
        helper = GoogleAuthHelper(sys.executable, runner=runner)

        self.assertFalse(helper.connected)

    def test_helper_token_is_machine_readable_contract(self):
        runner = mock.Mock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout="token-value\n",
                stderr="",
            )
        )
        helper = GoogleAuthHelper(sys.executable, runner=runner)

        self.assertEqual(helper.token(), "token-value")
        self.assertEqual(
            runner.call_args.args[0],
            [sys.executable, "token"],
        )

    def test_client_authorization_is_delegated_to_helper(self):
        auth = self.auth(connected=False)
        client = GoogleAccountClient(auth_helper=auth)

        self.assertTrue(client.authorize())
        auth.login.assert_called_once_with()

    def test_client_disconnect_is_delegated_to_helper(self):
        auth = self.auth()
        client = GoogleAccountClient(auth_helper=auth)

        self.assertTrue(client.disconnect())
        auth.logout.assert_called_once_with()

    def test_api_request_gets_bearer_token_from_helper(self):
        seen = {}

        def opener(request, timeout):
            seen["authorization"] = request.headers.get("Authorization")
            seen["timeout"] = timeout
            return _Response({"items": []})

        client = GoogleAccountClient(
            auth_helper=self.auth(),
            request_opener=opener,
        )
        client._api_get(
            "playlists",
            {"part": "snippet", "mine": "true"},
        )

        self.assertEqual(
            seen["authorization"],
            "Bearer access-token",
        )
        self.assertEqual(seen["timeout"], 30)

    def test_channel_parser_uses_authenticated_mine_response(self):
        client = self.client()
        client._api_get = mock.Mock(
            return_value={
                "items": [
                    {
                        "id": "UCmine",
                        "snippet": {"title": "My Channel"},
                        "contentDetails": {
                            "relatedPlaylists": {
                                "uploads": "UUUP",
                                "likes": "LLIKES",
                            }
                        },
                    }
                ]
            }
        )

        channel = client.channel()

        self.assertEqual(
            channel,
            GoogleChannel(
                channel_id="UCmine",
                title="My Channel",
                uploads_playlist_id="UUUP",
                likes_playlist_id="LLIKES",
            ),
        )
        params = client._api_get.call_args.args[1]
        self.assertEqual(params["mine"], "true")

    def test_playlist_parser_reads_owned_playlists(self):
        client = self.client()
        client._api_get = mock.Mock(
            return_value={
                "items": [
                    {
                        "id": "PL123",
                        "snippet": {"title": "Night Music"},
                        "contentDetails": {"itemCount": 3},
                        "status": {"privacyStatus": "private"},
                    }
                ]
            }
        )

        playlists = client.playlists()

        self.assertEqual(
            playlists,
            [
                GooglePlaylist(
                    playlist_id="PL123",
                    title="Night Music",
                    item_count=3,
                    privacy_status="private",
                )
            ],
        )

    def test_playlist_items_become_streamable_track_identifiers(self):
        client = self.client()
        client._api_get = mock.Mock(
            return_value={
                "items": [
                    {
                        "snippet": {
                            "title": "Song",
                            "channelTitle": "Playlist Owner",
                            "videoOwnerChannelTitle": "Artist Channel",
                            "videoOwnerChannelId": "UCartist",
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": "video123",
                            },
                        },
                        "contentDetails": {"videoId": "video123"},
                    }
                ]
            }
        )

        tracks = client.playlist_items("PL123")

        self.assertEqual(
            tracks,
            [
                GooglePlaylistTrack(
                    video_id="video123",
                    title="Song",
                    artist="Artist Channel",
                    channel_id="UCartist",
                )
            ],
        )

    def test_liked_videos_uses_authenticated_likes_playlist(self):
        client = self.client()
        client.channel = mock.Mock(
            return_value=GoogleChannel(
                channel_id="UCmine",
                title="My Channel",
                likes_playlist_id="LLIKES",
            )
        )
        track = GooglePlaylistTrack(
            video_id="liked123",
            title="Liked Song",
            artist="Artist",
        )
        client.playlist_items = mock.Mock(return_value=[track])

        from google_account import GoogleAccountSession

        session = GoogleAccountSession.__new__(GoogleAccountSession)
        session.client = client
        session.mode = "likes"
        session.playlist_id = ""
        import queue as _queue
        session.results = _queue.SimpleQueue()
        session._run()

        self.assertEqual(
            session.results.get_nowait(),
            ("track", track),
        )
        self.assertEqual(
            session.results.get_nowait(),
            ("done", None),
        )
        client.playlist_items.assert_called_once_with("LLIKES")

    def test_subscriptions_become_creator_nest_targets(self):
        client = self.client()
        client._api_get = mock.Mock(
            return_value={
                "items": [
                    {
                        "snippet": {
                            "title": "Producer Channel",
                            "resourceId": {
                                "kind": "youtube#channel",
                                "channelId": "UCproducer",
                            },
                        }
                    }
                ]
            }
        )

        subscriptions = client.subscriptions()

        self.assertEqual(
            subscriptions,
            [
                GoogleSubscription(
                    channel_id="UCproducer",
                    title="Producer Channel",
                )
            ],
        )

    def test_authorize_session_does_not_require_playlist(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.google_account = object()
        player.account_session = None
        player.account_level = "menu"
        player.account_items = []
        player.account_selected = 0
        player.account_playlist = None
        player.account_parent_items = []
        player.account_parent_selected = 0
        player.set_status = mock.Mock()

        with mock.patch("meowplayer.GoogleAccountSession") as session_type:
            session_type.return_value = SimpleNamespace()

            self.assertTrue(
                player.start_account_session("authorize")
            )

        session_type.assert_called_once_with(
            player.google_account,
            "authorize",
            playlist_id="",
        )
        player.set_status.assert_called_once_with(
            "Waiting for Google authorization...",
            "Waiting for Google to inspect the pawprint...",
        )

    def test_account_nest_remains_hidden_without_flag(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.google_account_enabled = False
        player.google_account = None
        statuses = []
        player.set_status = (
            lambda serious, cat: statuses.append((serious, cat))
        )

        self.assertFalse(player.open_account_nest())
        self.assertIn("--google-account", statuses[-1][0])

    def test_playlist_track_reuses_existing_online_playback_path(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.google_account_enabled = True
        player.google_account = SimpleNamespace()
        player.account_level = "playlist"
        player.account_items = [
            GooglePlaylistTrack(
                video_id="video123",
                title="Song",
                artist="Artist Channel",
                channel_id="UCartist",
            )
        ]
        player.account_selected = 0
        player.play_online = mock.Mock(return_value=True)

        self.assertTrue(player.activate_account_selection())

        track = player.play_online.call_args.args[0]
        self.assertEqual(track.video_id, "video123")
        self.assertEqual(
            track.url,
            "https://www.youtube.com/watch?v=video123",
        )
        self.assertEqual(
            track.channel_url,
            "https://www.youtube.com/channel/UCartist",
        )


if __name__ == "__main__":
    unittest.main()
