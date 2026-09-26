#!/usr/bin/env python3

import argparse
import base64
import hashlib
import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"


class GoogleAuthError(RuntimeError):
    pass


def default_token_path():
    override = os.environ.get("MEOWPLAYER_GOOGLE_TOKEN_FILE")
    if override:
        return Path(override).expanduser()
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
    verifier = secrets.token_urlsafe(64).rstrip("=")[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    result_queue = None

    def do_GET(self):
        params = parse_qs(urlsplit(self.path).query)
        payload = {
            "code": (params.get("code") or [""])[0],
            "state": (params.get("state") or [""])[0],
            "error": (params.get("error") or [""])[0],
        }
        if self.result_queue is not None:
            self.result_queue.put(payload)

        body = (
            b"<!doctype html><html><body>"
            b"<h2>MeowPlayer authorization received.</h2>"
            b"<p>You can close this tab and return to MeowPlayer.</p>"
            b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class GoogleOAuthHelper:
    def __init__(
        self,
        client_id="",
        *,
        token_path=None,
        request_opener=None,
        browser_open=None,
    ):
        self.token_path = Path(token_path or default_token_path()).expanduser()
        self.request_opener = request_opener or urlopen
        self.browser_open = browser_open or _open_browser
        self._token = self._load_token()
        self.client_id = (
            str(client_id or "").strip()
            or str(self._token.get("client_id") or "").strip()
        )

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
        request = Request(
            url,
            data=urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.request_opener(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GoogleAuthError(
                f"Google OAuth request failed ({exc.code}): {detail[:180]}"
            ) from exc
        except (URLError, OSError) as exc:
            raise GoogleAuthError(f"Google OAuth network error: {exc}") from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise GoogleAuthError("Google OAuth returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise GoogleAuthError("Google OAuth returned an invalid response.")
        return data

    def authorization_url(self, redirect_uri, state, challenge):
        if not self.configured:
            raise GoogleAuthError(
                "Google OAuth client ID is not configured. "
                "Use --client-id or MEOWPLAYER_GOOGLE_CLIENT_ID."
            )
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

    def login(self, timeout=180):
        if not self.configured:
            raise GoogleAuthError(
                "Google OAuth client ID is not configured. "
                "Use --client-id or MEOWPLAYER_GOOGLE_CLIENT_ID."
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
            raise GoogleAuthError(
                f"Could not start local OAuth callback server: {exc}"
            ) from exc

        server.timeout = 0.5
        redirect_uri = f"http://127.0.0.1:{server.server_port}/"
        auth_url = self.authorization_url(redirect_uri, state, challenge)

        if not self.browser_open(auth_url):
            server.server_close()
            raise GoogleAuthError(
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
            raise GoogleAuthError("Google authorization timed out.")
        if payload.get("error"):
            raise GoogleAuthError(
                f"Google authorization was denied: {payload['error']}"
            )
        if payload.get("state") != state:
            raise GoogleAuthError("Google authorization state mismatch.")

        code = str(payload.get("code") or "").strip()
        if not code:
            raise GoogleAuthError("Google authorization returned no code.")

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
            raise GoogleAuthError("Google did not return an access token.")

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
            raise GoogleAuthError("Google Account is not connected.")
        if not self.configured:
            raise GoogleAuthError("Google OAuth client ID is unavailable.")

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
            raise GoogleAuthError(
                "Google token refresh returned no access token."
            )

        expires_in = int(token.get("expires_in") or 3600)
        self._token["access_token"] = access_token
        self._token["expires_at"] = time.time() + max(60, expires_in)
        self._token["scope"] = str(
            token.get("scope")
            or self._token.get("scope")
            or YOUTUBE_READONLY_SCOPE
        )
        self._save_token()
        return access_token

    def access_token(self):
        if not self.connected:
            raise GoogleAuthError("Google Account is not connected.")

        token = str(self._token.get("access_token") or "").strip()
        try:
            expires_at = float(self._token.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0

        if token and expires_at - time.time() > 60:
            return token
        return self._refresh()

    def logout(self, revoke=True):
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
                pass

        self._token = {}
        try:
            self.token_path.unlink(missing_ok=True)
        except OSError:
            pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="meowplayer-google-auth",
        description=(
            "External Google OAuth helper for MeowPlayer. "
            "The token command writes only the access token to stdout."
        ),
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("MEOWPLAYER_GOOGLE_CLIENT_ID", ""),
        help=(
            "Google Desktop OAuth client ID. Defaults to "
            "MEOWPLAYER_GOOGLE_CLIENT_ID or the client ID saved with the token."
        ),
    )
    parser.add_argument(
        "--token-file",
        default=None,
        help=(
            "override OAuth token file; defaults to "
            "MEOWPLAYER_GOOGLE_TOKEN_FILE or XDG config storage"
        ),
    )
    parser.add_argument(
        "action",
        choices=("login", "token", "status", "logout"),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    helper = GoogleOAuthHelper(
        args.client_id,
        token_path=args.token_file,
    )

    try:
        if args.action == "status":
            if helper.connected:
                print("connected")
                return 0
            print("disconnected")
            return 1

        if args.action == "login":
            helper.login()
            print("connected")
            return 0

        if args.action == "token":
            # stdout is intentionally machine-readable: token only.
            print(helper.access_token())
            return 0

        helper.logout(revoke=True)
        print("disconnected")
        return 0
    except GoogleAuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
