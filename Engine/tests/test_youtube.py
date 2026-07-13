"""Unit tests for YouTube publishing: PKCE, redirect parsing, token refresh,
metadata, resumable upload with retry — all offline via injected transport."""

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from publish.youtube import (Keychain, PublishError, YouTubeConnector,
                             build_auth_url, build_video_metadata,
                             exchange_code, make_pkce, parse_redirect,
                             refresh_access_token, start_resumable_session,
                             upload_file)


class FakeResponse:
    def __init__(self, body=b"{}", status=200, headers=None):
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(code, headers=None, body=b"{}"):
    return urllib.error.HTTPError("u", code, "err", headers or {},
                                  io.BytesIO(body))


class TestOAuthHelpers(unittest.TestCase):
    def test_pkce_shape(self):
        verifier, challenge = make_pkce()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertNotIn("=", verifier + challenge)
        self.assertNotEqual(verifier, challenge)

    def test_auth_url_contains_required_params(self):
        url = build_auth_url("CID", "CHAL", "STATE")
        for fragment in ("client_id=CID", "code_challenge=CHAL",
                         "state=STATE", "code_challenge_method=S256",
                         "redirect_uri=http%3A%2F%2F127.0.0.1%3A8767",
                         "youtube.upload"):
            self.assertIn(fragment, url)

    def test_parse_redirect_happy_and_sad(self):
        self.assertEqual(parse_redirect("/?state=S&code=C", "S"), "C")
        with self.assertRaises(PublishError):
            parse_redirect("/?state=WRONG&code=C", "S")
        with self.assertRaises(PublishError):
            parse_redirect("/?state=S&error=access_denied", "S")
        with self.assertRaises(PublishError):
            parse_redirect("/?state=S", "S")

    def test_exchange_and_refresh(self):
        seen = {}

        def opener(req):
            seen["url"] = req.full_url
            seen["body"] = req.data.decode()
            return FakeResponse(json.dumps(
                {"access_token": "AT", "refresh_token": "RT"}).encode())

        tokens = exchange_code("CID", "SEC", "CODE", "VER", opener=opener)
        self.assertEqual(tokens["refresh_token"], "RT")
        self.assertIn("code_verifier=VER", seen["body"])

        token = refresh_access_token("CID", "SEC", "RT", opener=opener)
        self.assertEqual(token, "AT")
        self.assertIn("grant_type=refresh_token", seen["body"])

    def test_refresh_maps_http_error(self):
        def opener(req):
            raise http_error(400, body=json.dumps(
                {"error_description": "Token has been revoked."}).encode())
        with self.assertRaises(PublishError) as ctx:
            refresh_access_token("CID", "SEC", "RT", opener=opener)
        self.assertIn("revoked", str(ctx.exception))


class TestMetadataAndUpload(unittest.TestCase):
    def test_metadata_limits_and_privacy(self):
        meta = build_video_metadata("T" * 300, "D", ["a", " ", "b"], "unlisted")
        self.assertEqual(len(meta["snippet"]["title"]), 100)
        self.assertEqual(meta["snippet"]["tags"], ["a", "b"])
        self.assertEqual(meta["status"]["privacyStatus"], "unlisted")
        with self.assertRaises(PublishError):
            build_video_metadata("T", "", [], "everyone")

    def test_resumable_session_returns_location(self):
        opener = lambda req: FakeResponse(headers={"Location": "https://up/1"})
        self.assertEqual(
            start_resumable_session("AT", {}, 10, opener=opener),
            "https://up/1")

    def test_session_auth_failure_is_human(self):
        def opener(req):
            raise http_error(401)
        with self.assertRaises(PublishError) as ctx:
            start_resumable_session("AT", {}, 10, opener=opener)
        self.assertIn("reconnect", str(ctx.exception))

    def make_file(self, size):
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(b"v" * size)
        tmp.close()
        return tmp.name

    def test_upload_single_chunk_success(self):
        path = self.make_file(100)
        calls = []

        def opener(req):
            calls.append(req.headers.get("Content-range"))
            return FakeResponse(json.dumps({"id": "vid123"}).encode())

        video_id = upload_file("https://up/1", path, 100, opener=opener)
        self.assertEqual(video_id, "vid123")
        self.assertEqual(calls, ["bytes 0-99/100"])

    def test_upload_retries_on_503_then_succeeds(self):
        path = self.make_file(50)
        attempts = {"n": 0}
        naps = []

        def opener(req):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise http_error(503)
            return FakeResponse(json.dumps({"id": "vid9"}).encode())

        video_id = upload_file("https://up/1", path, 50, opener=opener,
                               sleeper=naps.append)
        self.assertEqual(video_id, "vid9")
        self.assertEqual(len(naps), 1)

    def test_upload_gives_up_after_max_retries(self):
        path = self.make_file(50)

        def opener(req):
            raise http_error(503)

        with self.assertRaises(PublishError):
            upload_file("https://up/1", path, 50, opener=opener,
                        sleeper=lambda s: None, max_retries=2)


class FakeKeychain:
    def __init__(self):
        self.data = {}

    def set(self, account, value):
        self.data[account] = value

    def get(self, account):
        return self.data.get(account)

    def delete(self, account):
        self.data.pop(account, None)


class TestConnector(unittest.TestCase):
    def test_connect_disconnect_cycle(self):
        kc = FakeKeychain()
        conn = YouTubeConnector(keychain=kc)
        self.assertFalse(conn.is_connected())
        conn.store_connection("CID", "SEC", "RT")
        self.assertTrue(conn.is_connected())
        conn.disconnect()
        self.assertFalse(conn.is_connected())
        with self.assertRaises(PublishError):
            conn.access_token()

    def test_publish_end_to_end_mocked(self):
        kc = FakeKeychain()
        stage = {"n": 0}

        def opener(req):
            stage["n"] += 1
            if "oauth2.googleapis.com" in req.full_url:
                return FakeResponse(json.dumps({"access_token": "AT"}).encode())
            if "uploadType=resumable" in req.full_url:
                self.assertEqual(req.headers.get("Authorization"),
                                 "Bearer AT")
                return FakeResponse(headers={"Location": "https://up/s"})
            return FakeResponse(json.dumps({"id": "final7"}).encode())

        conn = YouTubeConnector(keychain=kc, opener=opener)
        conn.store_connection("CID", "SEC", "RT")
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"mp4" * 100)
        url = conn.publish(tmp.name, title="Test", privacy="private")
        self.assertEqual(url, "https://www.youtube.com/watch?v=final7")

    def test_keychain_cli_shapes(self):
        commands = []

        def runner(cmd, **kw):
            commands.append(cmd)
            class R:
                returncode = 0
                stdout = "secret\n"
            return R()

        kc = Keychain(runner=runner)
        kc.set("acct", "v")
        self.assertEqual(kc.get("acct"), "secret")
        kc.delete("acct")
        self.assertIn("add-generic-password", commands[0])
        self.assertIn("find-generic-password", commands[1])
        self.assertIn("delete-generic-password", commands[2])


if __name__ == "__main__":
    unittest.main()
