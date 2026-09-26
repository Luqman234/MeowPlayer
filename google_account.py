import json
import logging
import os
import queue
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOGGER = logging.getLogger("meowplayer.google")
YOUTUBE_API_ROOT = "https://www.googleapis.com/youtube/v3"
DEFAULT_GOOGLE_AUTH_COMMAND = "meowplayer-google-auth"


class GoogleAccountError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleChannel:
    channel_id: str
    title: str
    uploads_playlist_id: str = ""
    likes_playlist_id: str = ""


@dataclass(frozen=True)
class GooglePlaylist:
    playlist_id: str
    title: str
    item_count: int = 0
    privacy_status: str = ""


@dataclass(frozen=True)
class GoogleSubscription:
    channel_id: str
    title: str


@dataclass(frozen=True)
class GooglePlaylistTrack:
    video_id: str
    title: str
    artist: str
    channel_id: str = ""


class GoogleAuthHelper:
    """Thin subprocess adapter for a NeoMutt-style OAuth helper."""

    def __init__(
        self,
        command=DEFAULT_GOOGLE_AUTH_COMMAND,
        *,
        timeout=35,
        login_timeout=240,
        runner=None,
    ):
        if isinstance(command, (list, tuple)):
            argv = [str(part) for part in command if str(part)]
        else:
            argv = shlex.split(str(command or "").strip())

        self.argv = argv or [DEFAULT_GOOGLE_AUTH_COMMAND]
        self.timeout = max(1, int(timeout))
        self.login_timeout = max(self.timeout, int(login_timeout))
        self.runner = runner or subprocess.run

    @property
    def configured(self):
        executable = self.argv[0]
        if os.sep in executable:
            path = Path(executable).expanduser()
            return path.is_file() and os.access(path, os.X_OK)
        return shutil.which(executable) is not None

    def _invoke(self, action, *, timeout=None):
        if not self.configured:
            raise GoogleAccountError(
                "Google auth helper is unavailable. "
                "Install meowplayer-google-auth or configure "
                "--google-auth-command."
            )

        try:
            return self.runner(
                [*self.argv, action],
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GoogleAccountError(
                f"Google auth helper timed out during {action}."
            ) from exc
        except OSError as exc:
            raise GoogleAccountError(
                f"Could not run Google auth helper: {exc}"
            ) from exc

    @staticmethod
    def _failure_message(result, action):
        detail = str(result.stderr or result.stdout or "").strip()
        if detail:
            return f"Google auth helper {action} failed: {detail[:220]}"
        return (
            f"Google auth helper {action} failed "
            f"with exit code {result.returncode}."
        )

    @property
    def connected(self):
        if not self.configured:
            return False
        try:
            result = self._invoke("status")
        except GoogleAccountError:
            return False
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        LOGGER.debug(
            "Google auth helper status failed rc=%s stderr=%r",
            result.returncode,
            str(result.stderr or "")[:160],
        )
        return False

    def login(self):
        result = self._invoke("login", timeout=self.login_timeout)
        if result.returncode != 0:
            raise GoogleAccountError(
                self._failure_message(result, "login")
            )
        return True

    def token(self):
        result = self._invoke("token")
        if result.returncode != 0:
            raise GoogleAccountError(
                self._failure_message(result, "token")
            )
        token = str(result.stdout or "").strip()
        if not token or any(char.isspace() for char in token):
            raise GoogleAccountError(
                "Google auth helper returned an invalid access token."
            )
        return token

    def logout(self):
        result = self._invoke("logout")
        if result.returncode != 0:
            raise GoogleAccountError(
                self._failure_message(result, "logout")
            )
        return True


class GoogleAccountClient:
    """YouTube account API client; authentication comes from an external helper."""

    def __init__(
        self,
        auth_command=DEFAULT_GOOGLE_AUTH_COMMAND,
        *,
        auth_helper=None,
        request_opener=None,
    ):
        self.auth = auth_helper or GoogleAuthHelper(auth_command)
        self.request_opener = request_opener or urlopen

    @property
    def configured(self):
        return self.auth.configured

    @property
    def connected(self):
        return self.auth.connected

    def authorize(self):
        return self.auth.login()

    def access_token(self):
        return self.auth.token()

    def disconnect(self, revoke=True):
        # Revocation policy belongs to the helper. The argument remains for
        # compatibility with the Account Nest session API.
        return self.auth.logout()

    def _api_get(self, resource, params):
        query = urlencode(params)
        request = Request(
            f"{YOUTUBE_API_ROOT}/{resource}?{query}",
            headers={"Authorization": f"Bearer {self.access_token()}"},
        )
        try:
            with self.request_opener(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GoogleAccountError(
                f"YouTube Data API failed ({exc.code}): {detail[:180]}"
            ) from exc
        except (URLError, OSError) as exc:
            raise GoogleAccountError(
                f"YouTube Data API network error: {exc}"
            ) from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise GoogleAccountError(
                "YouTube Data API returned invalid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise GoogleAccountError(
                "YouTube Data API returned an invalid response."
            )
        return payload

    def channel(self):
        payload = self._api_get(
            "channels",
            {
                "part": "snippet,contentDetails",
                "mine": "true",
                "maxResults": 1,
            },
        )
        items = payload.get("items") or []
        if not items:
            raise GoogleAccountError(
                "This Google Account does not expose a YouTube channel."
            )
        item = items[0]
        snippet = item.get("snippet") or {}
        related = (
            (item.get("contentDetails") or {})
            .get("relatedPlaylists")
            or {}
        )
        return GoogleChannel(
            channel_id=str(item.get("id") or ""),
            title=str(snippet.get("title") or "YouTube Account"),
            uploads_playlist_id=str(related.get("uploads") or ""),
            likes_playlist_id=str(related.get("likes") or ""),
        )

    def playlists(self):
        results = []
        page_token = ""
        while True:
            params = {
                "part": "snippet,contentDetails,status",
                "mine": "true",
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._api_get("playlists", params)
            for item in payload.get("items") or []:
                snippet = item.get("snippet") or {}
                details = item.get("contentDetails") or {}
                status = item.get("status") or {}
                playlist_id = str(item.get("id") or "").strip()
                title = str(snippet.get("title") or "").strip()
                if playlist_id and title:
                    results.append(
                        GooglePlaylist(
                            playlist_id=playlist_id,
                            title=title,
                            item_count=int(details.get("itemCount") or 0),
                            privacy_status=str(
                                status.get("privacyStatus") or ""
                            ),
                        )
                    )
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return results

    def playlist_items(self, playlist_id):
        results = []
        page_token = ""
        while True:
            params = {
                "part": "snippet,contentDetails,status",
                "playlistId": str(playlist_id),
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._api_get("playlistItems", params)
            for item in payload.get("items") or []:
                snippet = item.get("snippet") or {}
                resource = snippet.get("resourceId") or {}
                details = item.get("contentDetails") or {}
                video_id = str(
                    resource.get("videoId")
                    or details.get("videoId")
                    or ""
                ).strip()
                title = str(snippet.get("title") or "").strip()
                artist = str(
                    snippet.get("videoOwnerChannelTitle")
                    or snippet.get("channelTitle")
                    or "YouTube"
                ).strip()
                channel_id = str(
                    snippet.get("videoOwnerChannelId") or ""
                ).strip()
                if (
                    video_id
                    and title
                    and title not in {"Deleted video", "Private video"}
                ):
                    results.append(
                        GooglePlaylistTrack(
                            video_id=video_id,
                            title=title,
                            artist=artist,
                            channel_id=channel_id,
                        )
                    )
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return results

    def subscriptions(self):
        results = []
        page_token = ""
        while True:
            params = {
                "part": "snippet,contentDetails",
                "mine": "true",
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._api_get("subscriptions", params)
            for item in payload.get("items") or []:
                snippet = item.get("snippet") or {}
                resource = snippet.get("resourceId") or {}
                channel_id = str(
                    resource.get("channelId") or ""
                ).strip()
                title = str(snippet.get("title") or "").strip()
                if channel_id and title:
                    results.append(
                        GoogleSubscription(
                            channel_id=channel_id,
                            title=title,
                        )
                    )
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                break
        return results


class GoogleAccountSession:
    MODES = {
        "authorize",
        "playlists",
        "playlist",
        "likes",
        "subscriptions",
        "channel",
        "disconnect",
    }

    def __init__(self, client, mode, *, playlist_id=""):
        if mode not in self.MODES:
            raise ValueError(
                f"Unsupported Google Account session mode: {mode}"
            )
        self.client = client
        self.mode = mode
        self.playlist_id = str(playlist_id or "")
        self.results = queue.SimpleQueue()
        self.thread = threading.Thread(
            target=self._run,
            name=f"google-account-{mode}",
            daemon=True,
        )
        self.thread.start()

    def _run(self):
        try:
            if self.mode == "authorize":
                self.client.authorize()
                self.results.put(("authorized", True))
            elif self.mode == "playlists":
                for item in self.client.playlists():
                    self.results.put(("playlist", item))
                self.results.put(("done", None))
            elif self.mode == "playlist":
                for item in self.client.playlist_items(self.playlist_id):
                    self.results.put(("track", item))
                self.results.put(("done", None))
            elif self.mode == "likes":
                channel = self.client.channel()
                if not channel.likes_playlist_id:
                    raise GoogleAccountError(
                        "YouTube did not expose a Liked Videos playlist "
                        "for this account."
                    )
                for item in self.client.playlist_items(
                    channel.likes_playlist_id
                ):
                    self.results.put(("track", item))
                self.results.put(("done", None))
            elif self.mode == "subscriptions":
                for item in self.client.subscriptions():
                    self.results.put(("subscription", item))
                self.results.put(("done", None))
            elif self.mode == "channel":
                self.results.put(("channel", self.client.channel()))
                self.results.put(("done", None))
            elif self.mode == "disconnect":
                self.client.disconnect(revoke=True)
                self.results.put(("disconnected", True))
        except GoogleAccountError as exc:
            self.results.put(("error", str(exc)))
        except Exception:
            LOGGER.exception(
                "Unexpected Google Account session failure mode=%s",
                self.mode,
            )
            self.results.put(
                (
                    "error",
                    "Google Account operation failed unexpectedly.",
                )
            )

    def close(self):
        self.thread.join(timeout=0.2)
