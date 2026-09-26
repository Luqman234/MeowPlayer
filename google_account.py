import base64
import hashlib
import json
import logging
import os
import queue
import secrets
import shutil
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


LOGGER = logging.getLogger("meowplayer.google")

YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
YOUTUBE_API_ROOT = "https://www.googleapis.com/youtube/v3"


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


def google_token_path():
    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".config"
    return base / "meowplayer" / "google-oauth.json"


def _open_browser(url):
    termux_open = shutil.which("termux-open-url")
    if termux_open:
        try:
            subprocess.Popen(
                [termux_open, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except OSError:
            pass
    try:
        return bool(webbrowser.open(url, new=1))
    except Exception:
        return False


def _pkce_pair():
    verifier = secrets.token_urlsafe(64).rstrip("=")
    verifier = verifier[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    result_queue = None

    def do_GET(self):
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        payload = {
            "code": (params.get("code") or [""])[0],
            "state": (params.get("state") or [""])[0],
            "error": (params.get("error") or [""])[0],
        }
        if self.result_queue is not None:
            self.result_queue.put(payload)

        body = (
            b"<!doctype html><html><body><h2>MeowPlayer authorization received.</h2>"
            b"<p>You can close this tab and return to MeowPlayer.</p></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class GoogleAccountClient:
    def __init__(
        self,
        client_id="",
        *,
        token_path=None,
        request_opener=None,
        browser_open=None,
    ):
        self.client_id = str(client_id or "").strip()
        self.token_path = Path(token_path or google_token_path()).expanduser()
        self.request_opener = request_opener or urlopen
        self.browser_open = browser_open or _open_browser
        self._token = self._load_token()

    @property
    def configured(self):
        return bool(self.client_id)

    @property
    def connected(self):
        if not self._token or self._token.get("client_id") != self.client_id:
            return False
        if self._token.get("refresh_token"):
            return True
        access_token = str(self._token.get("access_token") or "").strip()
        try:
            expires_at = float(self._token.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        return bool(access_token and expires_at - time.time() > 60)

    def _load_token(self):
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_token(self):
        if not self._token:
            return
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_path.with_name(self.token_path.name + ".tmp")
        temporary.write_text(
            json.dumps(self._token, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.token_path)
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass

    def _post_form(self, url, payload):
        encoded = urlencode(payload).encode("utf-8")
        request = Request(
            url,
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.request_opener(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GoogleAccountError(
                f"Google OAuth request failed ({exc.code}): {detail[:180]}"
            ) from exc
        except (URLError, OSError) as exc:
            raise GoogleAccountError(f"Google OAuth network error: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise GoogleAccountError("Google OAuth returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise GoogleAccountError("Google OAuth returned an invalid response.")
        return data

    def _authorization_url(self, redirect_uri, state, challenge):
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": YOUTUBE_READONLY_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    def authorize(self, timeout=180):
        if not self.configured:
            raise GoogleAccountError(
                "Google OAuth client ID is not configured. "
                "Use --google-client-id or MEOWPLAYER_GOOGLE_CLIENT_ID."
            )

        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        result_queue = queue.SimpleQueue()

        class Handler(_OAuthCallbackHandler):
            pass

        Handler.result_queue = result_queue
        try:
            server = HTTPServer(("127.0.0.1", 0), Handler)
        except OSError as exc:
            raise GoogleAccountError(
                f"Could not start local OAuth callback server: {exc}"
            ) from exc

        server.timeout = 0.5
        redirect_uri = f"http://127.0.0.1:{server.server_port}/"
        auth_url = self._authorization_url(redirect_uri, state, challenge)

        LOGGER.info("Opening Google OAuth authorization page")
        if not self.browser_open(auth_url):
            server.server_close()
            raise GoogleAccountError(
                "Could not open the browser for Google authorization."
            )

        deadline = time.monotonic() + max(30, int(timeout))
        payload = None
        try:
            while time.monotonic() < deadline:
                server.handle_request()
                try:
                    payload = result_queue.get_nowait()
                    break
                except queue.Empty:
                    continue
        finally:
            server.server_close()

        if payload is None:
            raise GoogleAccountError("Google authorization timed out.")
        if payload.get("error"):
            raise GoogleAccountError(
                f"Google authorization was denied: {payload['error']}"
            )
        if payload.get("state") != state:
            raise GoogleAccountError("Google authorization state mismatch.")
        code = str(payload.get("code") or "").strip()
        if not code:
            raise GoogleAccountError("Google authorization returned no code.")

        token = self._post_form(
            TOKEN_ENDPOINT,
            {
                "client_id": self.client_id,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        access_token = str(token.get("access_token") or "").strip()
        if not access_token:
            raise GoogleAccountError("Google did not return an access token.")

        refresh_token = str(token.get("refresh_token") or "").strip()
        previous_refresh = str(self._token.get("refresh_token") or "").strip()
        expires_in = int(token.get("expires_in") or 3600)
        self._token = {
            "client_id": self.client_id,
            "access_token": access_token,
            "refresh_token": refresh_token or previous_refresh,
            "expires_at": time.time() + max(60, expires_in),
            "scope": str(token.get("scope") or YOUTUBE_READONLY_SCOPE),
            "token_type": str(token.get("token_type") or "Bearer"),
        }
        self._save_token()
        return True

    def _refresh(self):
        refresh_token = str(self._token.get("refresh_token") or "").strip()
        if not refresh_token:
            raise GoogleAccountError("Google Account is not connected.")

        token = self._post_form(
            TOKEN_ENDPOINT,
            {
                "client_id": self.client_id,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        access_token = str(token.get("access_token") or "").strip()
        if not access_token:
            raise GoogleAccountError("Google token refresh returned no access token.")

        expires_in = int(token.get("expires_in") or 3600)
        self._token["access_token"] = access_token
        self._token["expires_at"] = time.time() + max(60, expires_in)
        self._token["scope"] = str(
            token.get("scope") or self._token.get("scope") or YOUTUBE_READONLY_SCOPE
        )
        self._save_token()
        return access_token

    def access_token(self):
        if not self.connected:
            raise GoogleAccountError("Google Account is not connected.")
        token = str(self._token.get("access_token") or "").strip()
        expires_at = float(self._token.get("expires_at") or 0)
        if token and expires_at - time.time() > 60:
            return token
        return self._refresh()

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
            raise GoogleAccountError(f"YouTube Data API network error: {exc}") from exc

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise GoogleAccountError("YouTube Data API returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise GoogleAccountError("YouTube Data API returned an invalid response.")
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
        related = (item.get("contentDetails") or {}).get("relatedPlaylists") or {}
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
                            privacy_status=str(status.get("privacyStatus") or ""),
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
                    resource.get("videoId") or details.get("videoId") or ""
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
                if video_id and title and title not in {"Deleted video", "Private video"}:
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
                channel_id = str(resource.get("channelId") or "").strip()
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

    def disconnect(self, revoke=True):
        token = str(
            self._token.get("refresh_token")
            or self._token.get("access_token")
            or ""
        ).strip()
        if revoke and token:
            try:
                request = Request(
                    REVOKE_ENDPOINT,
                    data=urlencode({"token": token}).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with self.request_opener(request, timeout=15):
                    pass
            except Exception:
                LOGGER.warning("Google token revocation failed; clearing local token anyway")
        self._token = {}
        try:
            self.token_path.unlink(missing_ok=True)
        except OSError:
            pass


class GoogleAccountSession:
    MODES = {"authorize", "playlists", "playlist", "subscriptions", "channel", "disconnect"}

    def __init__(self, client, mode, *, playlist_id=""):
        if mode not in self.MODES:
            raise ValueError(f"Unsupported Google Account session mode: {mode}")
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
            LOGGER.exception("Unexpected Google Account session failure mode=%s", self.mode)
            self.results.put(("error", "Google Account operation failed unexpectedly."))

    def close(self):
        self.thread.join(timeout=0.2)
