import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from google_auth_helper import (
    GoogleAuthError,
    GoogleOAuthHelper,
    YOUTUBE_READONLY_SCOPE,
    main,
)


class GoogleAuthHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token_path = Path(self.temp.name) / "google-oauth.json"

    def tearDown(self):
        self.temp.cleanup()

    def helper(self, client_id="client-id"):
        return GoogleOAuthHelper(
            client_id,
            token_path=self.token_path,
        )

    def test_authorization_url_uses_readonly_scope_and_pkce(self):
        helper = self.helper()
        url = helper.authorization_url(
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

    def test_saved_token_is_owner_only_on_posix(self):
        helper = self.helper()
        helper._token = {
            "client_id": "client-id",
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": time.time() + 3600,
        }
        helper._save_token()

        self.assertTrue(self.token_path.exists())
        if os.name == "posix":
            self.assertEqual(
                self.token_path.stat().st_mode & 0o777,
                0o600,
            )

    def test_saved_client_id_can_configure_later_invocations(self):
        helper = self.helper()
        helper._token = {
            "client_id": "saved-client",
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": time.time() + 3600,
        }
        helper._save_token()

        loaded = GoogleOAuthHelper(
            "",
            token_path=self.token_path,
        )

        self.assertTrue(loaded.configured)
        self.assertEqual(loaded.client_id, "saved-client")

    def test_expired_access_without_refresh_is_disconnected(self):
        helper = self.helper()
        helper._token = {
            "client_id": "client-id",
            "access_token": "expired",
            "refresh_token": "",
            "expires_at": 1,
        }

        self.assertFalse(helper.connected)

    def test_valid_access_token_is_returned_without_refresh(self):
        helper = self.helper()
        helper._token = {
            "client_id": "client-id",
            "access_token": "still-valid",
            "refresh_token": "refresh",
            "expires_at": time.time() + 3600,
        }
        helper._refresh = mock.Mock(
            side_effect=AssertionError("refresh should not run")
        )

        self.assertEqual(helper.access_token(), "still-valid")

    def test_expired_access_token_is_refreshed(self):
        helper = self.helper()
        helper._token = {
            "client_id": "client-id",
            "access_token": "expired",
            "refresh_token": "refresh",
            "expires_at": 1,
        }
        helper._post_form = mock.Mock(
            return_value={
                "access_token": "fresh-token",
                "expires_in": 3600,
                "scope": YOUTUBE_READONLY_SCOPE,
            }
        )

        token = helper.access_token()

        self.assertEqual(token, "fresh-token")
        self.assertEqual(
            helper._token["access_token"],
            "fresh-token",
        )
        self.assertTrue(self.token_path.exists())

    def test_token_cli_writes_only_token_to_stdout(self):
        with mock.patch(
            "google_auth_helper.GoogleOAuthHelper"
        ) as helper_type:
            helper = helper_type.return_value
            helper.access_token.return_value = "machine-token"

            with mock.patch("builtins.print") as output:
                rc = main(
                    [
                        "--client-id",
                        "client-id",
                        "--token-file",
                        str(self.token_path),
                        "token",
                    ]
                )

        self.assertEqual(rc, 0)
        output.assert_called_once_with("machine-token")

    def test_status_exit_codes_are_machine_friendly(self):
        with mock.patch(
            "google_auth_helper.GoogleOAuthHelper"
        ) as helper_type:
            helper_type.return_value.connected = True
            with mock.patch("builtins.print") as output:
                self.assertEqual(main(["status"]), 0)
                output.assert_called_once_with("connected")

        with mock.patch(
            "google_auth_helper.GoogleOAuthHelper"
        ) as helper_type:
            helper_type.return_value.connected = False
            with mock.patch("builtins.print") as output:
                self.assertEqual(main(["status"]), 1)
                output.assert_called_once_with("disconnected")

    def test_missing_client_id_is_rejected_for_login(self):
        helper = GoogleOAuthHelper(
            "",
            token_path=self.token_path,
        )
        with self.assertRaises(GoogleAuthError):
            helper.authorization_url(
                "http://127.0.0.1:12345/",
                "state",
                "challenge",
            )


if __name__ == "__main__":
    unittest.main()
