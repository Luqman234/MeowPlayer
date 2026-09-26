import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from google_account import (
    GoogleAccountClient,
    GoogleChannel,
    GooglePlaylist,
    GooglePlaylistTrack,
    GoogleSubscription,
    YOUTUBE_READONLY_SCOPE,
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
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.token_path = Path(self._temp.name) / "google-oauth.json"

    def tearDown(self):
        self._temp.cleanup()

    def client(self, client_id="client-id"):
        return GoogleAccountClient(
            client_id,
            token_path=self.token_path,
        )

    def test_google_account_flag_is_opt_in(self):
        self.assertFalse(parse_args([]).google_account)
        self.assertTrue(parse_args(["--google-account"]).google_account)

    def test_google_client_id_is_separate_from_enable_flag(self):
        args = parse_args(
            [
                "--google-account",
                "--google-client-id",
                "desktop-client.apps.googleusercontent.com",
            ]
        )
        self.assertTrue(args.google_account)
        self.assertEqual(
            args.google_client_id,
            "desktop-client.apps.googleusercontent.com",
        )

    def test_authorization_url_uses_readonly_scope_and_pkce(self):
        client = self.client()
        url = client._authorization_url(
            "http://127.0.0.1:12345/",
            "state-token",
            "challenge-token",
        )
        params = parse_qs(urlsplit(url).query)

        self.assertEqual(params["scope"], [YOUTUBE_READONLY_SCOPE])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["state"], ["state-token"])
        self.assertEqual(params["code_challenge"], ["challenge-token"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["access_type"], ["offline"])

    def test_expired_access_token_without_refresh_is_not_connected(self):
        client = self.client()
        client._token = {
            "client_id": "client-id",
            "access_token": "expired",
            "refresh_token": "",
            "expires_at": 1,
        }

        self.assertFalse(client.connected)

    def test_saved_token_is_restricted_to_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "google-oauth.json"
            client = GoogleAccountClient(
                "client-id",
                token_path=path,
            )
            client._token = {
                "client_id": "client-id",
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": 9999999999,
            }
            client._save_token()

            self.assertTrue(path.exists())
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

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

        self.assertEqual(session.results.get_nowait(), ("track", track))
        self.assertEqual(session.results.get_nowait(), ("done", None))
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

    def test_account_nest_remains_hidden_without_flag(self):
        player = MeowPlayer.__new__(MeowPlayer)
        player.google_account_enabled = False
        player.google_account = None
        statuses = []
        player.set_status = lambda serious, cat: statuses.append((serious, cat))

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
