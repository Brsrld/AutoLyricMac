"""Offline unit tests for Instagram publishing (mocked transport)."""

import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from publish.instagram import (InstagramConnector, PublishError,
                               TempObjectStore, publish_reel, sigv4_headers,
                               verify_account)


class FakeResponse:
    def __init__(self, body=b"{}", status=200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def graph_opener(script):
    """Route requests to canned JSON responses by URL substring."""
    calls = []

    def opener(req):
        calls.append(req)
        for fragment, payload in script:
            if fragment in req.full_url:
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(json.dumps(payload).encode())
        raise AssertionError(f"unexpected request {req.full_url}")
    opener.calls = calls
    return opener


S3_CONFIG = {"endpoint": "https://acc.r2.cloudflarestorage.com",
             "bucket": "temp", "region": "auto", "access_key": "AK",
             "secret_key": "SK", "public_base": "https://pub-x.r2.dev"}


class TestSigV4(unittest.TestCase):
    def test_header_shape_and_determinism(self):
        import datetime
        now = datetime.datetime(2026, 7, 13, 12, 0,
                                tzinfo=datetime.timezone.utc)
        h1 = sigv4_headers("PUT", "https://acc.r2.cloudflarestorage.com/temp/k",
                           "auto", "AK", "SK", "abc", now=now)
        h2 = sigv4_headers("PUT", "https://acc.r2.cloudflarestorage.com/temp/k",
                           "auto", "AK", "SK", "abc", now=now)
        self.assertEqual(h1, h2)
        self.assertIn("Credential=AK/20260713/auto/s3/aws4_request",
                      h1["Authorization"])
        self.assertIn("Signature=", h1["Authorization"])
        self.assertEqual(h1["x-amz-date"], "20260713T120000Z")


class TestTempObjectStore(unittest.TestCase):
    def test_missing_config_field(self):
        with self.assertRaises(PublishError):
            TempObjectStore({"endpoint": "x"})

    def test_upload_returns_public_url_and_delete_best_effort(self):
        seen = []

        def opener(req):
            seen.append((req.get_method(), req.full_url))
            if req.get_method() == "DELETE":
                raise urllib.error.HTTPError("u", 500, "boom", {},
                                             io.BytesIO(b"{}"))
            return FakeResponse()

        store = TempObjectStore(S3_CONFIG, opener=opener)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"vid")
        url = store.upload(tmp.name, "autolyric_tmp/x.mp4")
        self.assertEqual(url, "https://pub-x.r2.dev/autolyric_tmp/x.mp4")
        store.delete("autolyric_tmp/x.mp4")   # 500 swallowed
        self.assertEqual([m for m, _ in seen], ["PUT", "DELETE"])


class TestGraphFlow(unittest.TestCase):
    def test_verify_account(self):
        opener = graph_opener([("/17841400", {"username": "demo.music"})])
        self.assertEqual(verify_account("T", "17841400", opener=opener),
                         "demo.music")
        with self.assertRaises(PublishError):
            verify_account("T", "17841400",
                           opener=graph_opener([("/17841400", {})]))

    def test_publish_reel_polls_until_finished(self):
        states = iter(["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
        naps = []

        def opener(req):
            url = req.full_url
            if url.endswith("/media") or "/media?" in url:
                return FakeResponse(b'{"id": "C1"}')
            if "/C1" in url:
                return FakeResponse(json.dumps(
                    {"status_code": next(states)}).encode())
            if "media_publish" in url:
                return FakeResponse(b'{"id": "M9"}')
            if "/M9" in url:
                return FakeResponse(b'{"permalink": "https://instagr.am/p/x"}')
            raise AssertionError(url)

        link = publish_reel("T", "U", "https://pub/vid.mp4", "caption",
                            opener=opener, sleeper=naps.append)
        self.assertEqual(link, "https://instagr.am/p/x")
        self.assertEqual(len(naps), 2)  # sleeps only between IN_PROGRESS polls

    def test_publish_reel_container_error(self):
        def opener(req):
            if req.full_url.endswith("/media"):
                return FakeResponse(b'{"id": "C1"}')
            return FakeResponse(b'{"status_code": "ERROR"}')
        with self.assertRaises(PublishError):
            publish_reel("T", "U", "https://pub/v.mp4", "c", opener=opener,
                         sleeper=lambda s: None)

    def test_graph_error_message_surfaced(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(
            json.dumps({"error": {"message": "Invalid OAuth token"}}).encode()))
        with self.assertRaises(PublishError) as ctx:
            verify_account("T", "17841",
                           opener=graph_opener([("/17841", err)]))
        self.assertIn("Invalid OAuth token", str(ctx.exception))


class FakeKeychain:
    def __init__(self):
        self.data = {}

    def set(self, a, v):
        self.data[a] = v

    def get(self, a):
        return self.data.get(a)

    def delete(self, a):
        self.data.pop(a, None)


class TestConnector(unittest.TestCase):
    def test_full_publish_flow_with_temp_cleanup(self):
        kc = FakeKeychain()
        deletes = []

        def opener(req):
            url = req.full_url
            if "r2.cloudflarestorage" in url:
                if req.get_method() == "DELETE":
                    deletes.append(url)
                return FakeResponse()
            if "fields=username" in url:
                return FakeResponse(b'{"username": "demo"}')
            if url.endswith("/media"):
                return FakeResponse(b'{"id": "C1"}')
            if "/C1" in url:
                return FakeResponse(b'{"status_code": "FINISHED"}')
            if "media_publish" in url:
                return FakeResponse(b'{"id": "M1"}')
            if "/M1" in url:
                return FakeResponse(b'{"permalink": "https://instagr.am/p/z"}')
            raise AssertionError(url)

        conn = InstagramConnector(keychain=kc, opener=opener)
        self.assertEqual(conn.store_connection("TOK", "17841", S3_CONFIG),
                         "demo")
        self.assertTrue(conn.is_connected())
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"vid")
        link = conn.publish(tmp.name, "hello", sleeper=lambda s: None)
        self.assertEqual(link, "https://instagr.am/p/z")
        self.assertEqual(len(deletes), 1, "temp object must be deleted")
        conn.disconnect()
        self.assertFalse(conn.is_connected())

    def test_publish_requires_connection(self):
        conn = InstagramConnector(keychain=FakeKeychain())
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"v")
        with self.assertRaises(PublishError):
            conn.publish(tmp.name, "c")


class TestRateLimitMessage(unittest.TestCase):
    def test_403_request_limit_gives_clear_message(self):
        import urllib.error
        from publish.instagram import _graph, PublishError

        def opener(req):
            body = json.dumps({"error": {"message": "Application request "
                                         "limit reached", "code": 4}}).encode()
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                         io.BytesIO(body))
        with self.assertRaises(PublishError) as cm:
            _graph("GET", "/me", {"access_token": "x"}, opener)
        self.assertIn("istek limitine", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
