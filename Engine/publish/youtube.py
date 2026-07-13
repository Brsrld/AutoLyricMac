"""YouTube publishing via official OAuth 2.0 + Data API v3 (Phase 8).

Installed-app authorization code flow with PKCE and a loopback redirect —
no passwords, no browser automation, no cookies. The refresh token and the
user's OAuth client credentials live in the macOS Keychain (via the
`security` CLI, injectable for tests). Uploads use the official resumable
protocol with retry/backoff; everything network-shaped is injectable so the
logic is fully unit-testable offline.
"""

import base64
import hashlib
import json
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
UPLOAD_ENDPOINT = ("https://www.googleapis.com/upload/youtube/v3/videos"
                   "?uploadType=resumable&part=snippet,status")
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
REDIRECT_PORT = 8767
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}"
CHUNK_SIZE = 8 * 1024 * 1024
KEYCHAIN_SERVICE = "AutoLyricMac"
PRIVACY_LEVELS = ("private", "unlisted", "public")


class PublishError(Exception):
    """Human-readable publishing failure."""


# ---------------------------------------------------------------------------
# Keychain (subprocess `security`, injectable)
# ---------------------------------------------------------------------------

class Keychain:
    def __init__(self, runner=subprocess.run):
        self._run = runner

    def set(self, account, value):
        self._run(["security", "add-generic-password", "-U",
                   "-s", KEYCHAIN_SERVICE, "-a", account, "-w", value],
                  capture_output=True, check=True)

    def get(self, account):
        result = self._run(["security", "find-generic-password",
                            "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                           capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def delete(self, account):
        self._run(["security", "delete-generic-password",
                   "-s", KEYCHAIN_SERVICE, "-a", account],
                  capture_output=True)


# ---------------------------------------------------------------------------
# Pure OAuth helpers
# ---------------------------------------------------------------------------

def make_pkce():
    """(verifier, challenge) per RFC 7636 S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)) \
        .rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_auth_url(client_id, challenge, state):
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    })
    return f"{AUTH_ENDPOINT}?{params}"


def parse_redirect(path, expected_state):
    """Extract the auth code from the loopback redirect path (pure)."""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
    if query.get("error"):
        raise PublishError(f"Authorization was denied: {query['error'][0]}")
    if query.get("state", [None])[0] != expected_state:
        raise PublishError("OAuth state mismatch — possible interception; "
                           "please try connecting again.")
    code = query.get("code", [None])[0]
    if not code:
        raise PublishError("No authorization code in the redirect.")
    return code


def _post_form(url, fields, opener):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode()).get(
                "error_description", "")
        except Exception:
            pass
        raise PublishError(f"Token request failed (HTTP {exc.code}). "
                           f"{detail}".strip()) from exc
    except urllib.error.URLError as exc:
        raise PublishError(f"Could not reach Google: {exc.reason}") from exc


def exchange_code(client_id, client_secret, code, verifier,
                  opener=urllib.request.urlopen):
    return _post_form(TOKEN_ENDPOINT, {
        "client_id": client_id, "client_secret": client_secret,
        "code": code, "code_verifier": verifier,
        "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI,
    }, opener)


def refresh_access_token(client_id, client_secret, refresh_token,
                         opener=urllib.request.urlopen):
    payload = _post_form(TOKEN_ENDPOINT, {
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }, opener)
    token = payload.get("access_token")
    if not token:
        raise PublishError("Google returned no access token; reconnect "
                           "your YouTube account.")
    return token


# ---------------------------------------------------------------------------
# Upload (resumable, injectable transport)
# ---------------------------------------------------------------------------

def build_video_metadata(title, description, tags, privacy):
    if privacy not in PRIVACY_LEVELS:
        raise PublishError(f"Privacy must be one of {PRIVACY_LEVELS}.")
    return {
        "snippet": {
            "title": (title or "Untitled")[:100],
            "description": (description or "")[:4900],
            "tags": [t.strip() for t in (tags or []) if t.strip()][:30],
            "categoryId": "10",   # Music
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }


def start_resumable_session(access_token, metadata, total_bytes,
                            opener=urllib.request.urlopen):
    req = urllib.request.Request(
        UPLOAD_ENDPOINT, data=json.dumps(metadata).encode(),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(total_bytes),
            "X-Upload-Content-Type": "video/mp4",
        }, method="POST")
    try:
        with opener(req) as resp:
            location = resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PublishError("YouTube rejected the credentials; reconnect "
                               "your account.") from exc
        raise PublishError(f"Could not start the upload (HTTP {exc.code})."
                           ) from exc
    if not location:
        raise PublishError("YouTube did not return an upload session URL.")
    return location


def upload_file(session_url, file_path, total_bytes,
                opener=urllib.request.urlopen, progress=None,
                max_retries=4, sleeper=time.sleep):
    """Chunked resumable upload with backoff. Returns the video id."""
    sent = 0
    retries = 0
    with open(file_path, "rb") as fh:
        while sent < total_bytes:
            fh.seek(sent)
            chunk = fh.read(CHUNK_SIZE)
            end = sent + len(chunk) - 1
            req = urllib.request.Request(session_url, data=chunk, headers={
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {sent}-{end}/{total_bytes}",
            }, method="PUT")
            try:
                with opener(req) as resp:
                    body = resp.read().decode() or "{}"
                    sent = end + 1
                    retries = 0
                    if progress:
                        progress(sent / total_bytes)
                    if resp.status in (200, 201):
                        video_id = json.loads(body).get("id")
                        if not video_id:
                            raise PublishError("Upload finished but YouTube "
                                               "returned no video id.")
                        return video_id
            except urllib.error.HTTPError as exc:
                if exc.code == 308:            # chunk accepted, keep going
                    rng = exc.headers.get("Range", "")
                    if rng.startswith("bytes=0-"):
                        sent = int(rng.split("-")[1]) + 1
                    else:
                        sent = end + 1
                    retries = 0
                    if progress:
                        progress(sent / total_bytes)
                    continue
                if exc.code in (500, 502, 503, 504) and retries < max_retries:
                    retries += 1
                    sleeper(min(2 ** retries, 30))
                    continue
                raise PublishError(f"Upload failed (HTTP {exc.code})."
                                   ) from exc
            except urllib.error.URLError as exc:
                if retries < max_retries:
                    retries += 1
                    sleeper(min(2 ** retries, 30))
                    continue
                raise PublishError(f"Network error during upload: "
                                   f"{exc.reason}") from exc
    raise PublishError("Upload ended without a completion response.")


# ---------------------------------------------------------------------------
# High-level connector
# ---------------------------------------------------------------------------

ACC_CLIENT_ID = "youtube_client_id"
ACC_CLIENT_SECRET = "youtube_client_secret"
ACC_REFRESH_TOKEN = "youtube_refresh_token"


class YouTubeConnector:
    def __init__(self, keychain=None, opener=urllib.request.urlopen):
        self.keychain = keychain or Keychain()
        self.opener = opener

    def is_connected(self):
        return bool(self.keychain.get(ACC_REFRESH_TOKEN)
                    and self.keychain.get(ACC_CLIENT_ID))

    def store_connection(self, client_id, client_secret, refresh_token):
        self.keychain.set(ACC_CLIENT_ID, client_id)
        self.keychain.set(ACC_CLIENT_SECRET, client_secret)
        self.keychain.set(ACC_REFRESH_TOKEN, refresh_token)

    def disconnect(self):
        for account in (ACC_REFRESH_TOKEN, ACC_CLIENT_ID, ACC_CLIENT_SECRET):
            self.keychain.delete(account)

    def access_token(self):
        client_id = self.keychain.get(ACC_CLIENT_ID)
        client_secret = self.keychain.get(ACC_CLIENT_SECRET)
        refresh = self.keychain.get(ACC_REFRESH_TOKEN)
        if not (client_id and client_secret and refresh):
            raise PublishError("YouTube is not connected yet.")
        return refresh_access_token(client_id, client_secret, refresh,
                                    opener=self.opener)

    def publish(self, file_path, title, description="", tags=(),
                privacy="private", progress=None):
        from pathlib import Path
        path = Path(file_path)
        if not path.is_file():
            raise PublishError("The rendered video file no longer exists.")
        total = path.stat().st_size
        token = self.access_token()
        metadata = build_video_metadata(title, description, list(tags),
                                        privacy)
        session = start_resumable_session(token, metadata, total,
                                          opener=self.opener)
        video_id = upload_file(session, path, total, opener=self.opener,
                               progress=progress)
        return f"https://www.youtube.com/watch?v={video_id}"
