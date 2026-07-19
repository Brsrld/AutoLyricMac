"""Instagram Reels publishing via the official Meta Graph API (Phase 9).

Requirements honored from the spec: eligible professional account +
user-created Meta app only; no passwords, no browser automation, no private
endpoints. The Graph API needs a public HTTPS video URL, so the rendered
file is uploaded temporarily to a user-configured S3-compatible bucket
(e.g. Cloudflare R2), published, confirmed, and the object is deleted.

All credentials live in the macOS Keychain. Network transport is injectable
so the whole flow is unit-testable offline.
"""

import datetime
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .youtube import Keychain, PublishError

GRAPH = "https://graph.facebook.com/v21.0"
GRAPH_IG = "https://graph.instagram.com/v21.0"


def _base_for(token):
    """New Instagram-Login tokens (IGAA...) live on graph.instagram.com;
    classic Page-linked tokens use graph.facebook.com."""
    return GRAPH_IG if str(token).startswith("IG") else GRAPH
POLL_INTERVAL = 5
POLL_TIMEOUT = 600

ACC_TOKEN = "instagram_access_token"
ACC_USER_ID = "instagram_user_id"
ACC_S3_CONFIG = "instagram_s3_config"      # JSON: endpoint/bucket/keys/public


# ---------------------------------------------------------------------------
# Minimal AWS SigV4 for S3-compatible PUT/DELETE (stdlib only)
# ---------------------------------------------------------------------------

def _sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def sigv4_headers(method, url, region, access_key, secret_key,
                  payload_hash, now=None):
    """Authorization headers for one S3 request (virtual-host or path style)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    parsed = urllib.parse.urlparse(url)
    canonical_uri = urllib.parse.quote(parsed.path or "/")
    host = parsed.netloc

    canonical_headers = (f"host:{host}\nx-amz-content-sha256:{payload_hash}\n"
                         f"x-amz-date:{amz_date}\n")
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([method, canonical_uri, "",
                                   canonical_headers, signed_headers,
                                   payload_hash])
    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest()])
    signing_key = _sign(_sign(_sign(_sign(
        ("AWS4" + secret_key).encode(), datestamp), region), "s3"),
        "aws4_request")
    signature = hmac.new(signing_key, string_to_sign.encode(),
                         hashlib.sha256).hexdigest()
    return {
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope},"
                          f" SignedHeaders={signed_headers},"
                          f" Signature={signature}"),
    }


class TempObjectStore:
    """S3-compatible temporary storage: upload, public URL, delete.

    config: {"endpoint": "https://<account>.r2.cloudflarestorage.com",
             "bucket": "...", "region": "auto", "access_key": "...",
             "secret_key": "...", "public_base": "https://pub-....r2.dev"}
    """

    def __init__(self, config, opener=urllib.request.urlopen):
        for field in ("endpoint", "bucket", "access_key", "secret_key",
                      "public_base"):
            if not config.get(field):
                raise PublishError(f"Object storage config is missing "
                                   f"'{field}'.")
        self.config = config
        self.opener = opener

    def _object_url(self, key):
        return (f"{self.config['endpoint'].rstrip('/')}/"
                f"{self.config['bucket']}/{key}")

    def _request(self, method, key, data=None, payload_hash=None):
        url = self._object_url(key)
        headers = sigv4_headers(method, url,
                                self.config.get("region", "auto"),
                                self.config["access_key"],
                                self.config["secret_key"],
                                payload_hash or hashlib.sha256(
                                    data or b"").hexdigest())
        if data is not None:
            headers["Content-Type"] = "video/mp4"
        if self.opener is urllib.request.urlopen:
            # system curl trusts the local TLS chain (AV interception etc.)
            return self._request_curl(method, url, headers, data)
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with self.opener(req) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            raise PublishError(f"Object storage {method} failed "
                               f"(HTTP {exc.code}).") from exc
        except urllib.error.URLError as exc:
            raise PublishError(f"Could not reach object storage: "
                               f"{exc.reason}") from exc

    def _request_curl(self, method, url, headers, data, attempts=3):
        import os
        import subprocess
        import tempfile
        import time
        base = ["/usr/bin/curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                "-X", method,
                "--connect-timeout", "30",   # fail fast on a dead connection
                "--max-time", "900"]         # allow big reels on a slow uplink
        for name, value in headers.items():
            base += ["-H", f"{name}: {value}"]
        tmp = None
        if data is not None:
            tmp = tempfile.NamedTemporaryFile(delete=False)
            tmp.write(data)
            tmp.close()
            base += ["--data-binary", f"@{tmp.name}"]
        base.append(url)
        try:
            last_rc = None
            for attempt in range(attempts):
                result = subprocess.run(base, capture_output=True, text=True,
                                        timeout=960)
                if result.returncode == 0:
                    code = int(result.stdout.strip() or 0)
                    if code >= 300:
                        raise PublishError(f"Object storage {method} failed "
                                           f"(HTTP {code}).")
                    return code
                last_rc = result.returncode          # 28 = timeout, etc.
                if attempt < attempts - 1:
                    time.sleep(2 * (attempt + 1))
        finally:
            if tmp is not None:
                os.unlink(tmp.name)
        hint = (" (zaman aşımı — internet/R2 bağlantısını kontrol et; büyük "
                "video yavaş yüklenebilir)" if last_rc == 28 else "")
        raise PublishError(f"Could not reach object storage "
                           f"(curl {last_rc}){hint}.")

    def upload(self, file_path, key):
        data = open(file_path, "rb").read()
        self._request("PUT", key, data=data)
        return f"{self.config['public_base'].rstrip('/')}/{key}"

    def delete(self, key):
        try:
            self._request("DELETE", key)
        except PublishError:
            pass  # best effort; a stale temp object is not fatal

    def public_head(self, url):
        """(http_code, content_type) for the public URL Instagram will fetch."""
        import subprocess
        try:
            r = subprocess.run(
                ["/usr/bin/curl", "-sI", "-L", "-o", "/dev/null",
                 "-w", "%{http_code} %{content_type}",
                 "--connect-timeout", "20", "--max-time", "40", url],
                capture_output=True, text=True, timeout=50)
        except Exception:
            return 0, ""
        parts = (r.stdout or "").split()
        code = int(parts[0]) if parts and parts[0].isdigit() else 0
        return code, (parts[1] if len(parts) > 1 else "")


# ---------------------------------------------------------------------------
# Graph API flow
# ---------------------------------------------------------------------------

def _graph(method, path, params, opener):
    query = urllib.parse.urlencode(params)
    url = f"{_base_for(params.get('access_token', ''))}{path}"
    data = None
    if method == "POST":
        data = query.encode()
    else:
        url = f"{url}?{query}"
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with opener(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail, code = "", None
        try:
            err = json.loads(exc.read().decode()).get("error", {})
            detail = err.get("message", "")
            code = err.get("code")
        except Exception:
            pass
        # Meta app-level rate limit (codes 4/17/32/613 or 'request limit')
        if code in (4, 17, 32, 613) or "request limit" in detail.lower() \
                or "rate limit" in detail.lower():
            raise PublishError(
                "Instagram uygulaması istek limitine takıldı. Bu Meta'nın "
                "saatlik kotası — biraz bekleyip (genelde ~1 saat) tekrar "
                "dene. Peş peşe denemek limiti daha da uzatır.") from exc
        raise PublishError(f"Instagram API error (HTTP {exc.code}). "
                           f"{detail}".strip()) from exc
    except urllib.error.URLError as exc:
        raise PublishError(f"Could not reach the Instagram API: "
                           f"{exc.reason}") from exc


def verify_account(access_token, ig_user_id, opener=urllib.request.urlopen):
    """Confirm the token can see the professional IG account; return name."""
    payload = _graph("GET", f"/{ig_user_id}",
                     {"fields": "username", "access_token": access_token},
                     opener)
    username = payload.get("username")
    if not username:
        raise PublishError("The token cannot access this Instagram account. "
                           "Check the account is professional and linked.")
    return username


def publish_reel(access_token, ig_user_id, video_url, caption, audio_name="",
                 opener=urllib.request.urlopen, sleeper=time.sleep,
                 progress=None):
    """Container create -> poll FINISHED -> publish -> permalink.

    `audio_name` sets the Reel's original-audio title (what shows at the top
    of the reel and lets people find other videos using that sound). It can
    be set only once; we set it to the song name.
    """
    params = {
        "media_type": "REELS", "video_url": video_url,
        "caption": caption[:2200], "share_to_feed": "true",
        "access_token": access_token}
    if audio_name.strip():
        params["audio_name"] = audio_name.strip()[:100]
    created = _graph("POST", f"/{ig_user_id}/media", params, opener)
    container = created.get("id")
    if not container:
        raise PublishError("Instagram did not return a media container id.")

    waited = 0
    interval = POLL_INTERVAL
    while waited < POLL_TIMEOUT:
        info = _graph("GET", f"/{container}",
                      {"fields": "status_code,status",
                       "access_token": access_token}, opener)
        status = info.get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            # surface Instagram's own reason (e.g. bad codec / duration / URL)
            detail = str(info.get("status") or "").strip()
            raise PublishError(
                "Instagram could not process the video"
                + (f": {detail}" if detail else " (container status ERROR)")
                + ".")
        if progress:
            progress(min(0.9, waited / 120))
        sleeper(interval)
        waited += interval
        interval = min(20, interval + 3)   # back off to spare the API quota
    else:
        raise PublishError("Instagram processing timed out.")

    published = _graph("POST", f"/{ig_user_id}/media_publish",
                       {"creation_id": container,
                        "access_token": access_token}, opener)
    media_id = published.get("id")
    if not media_id:
        raise PublishError("Publishing returned no media id.")
    permalink = _graph("GET", f"/{media_id}",
                       {"fields": "permalink",
                        "access_token": access_token}, opener).get("permalink")
    return permalink or f"instagram media id {media_id}"


class InstagramConnector:
    def __init__(self, keychain=None, opener=urllib.request.urlopen):
        self.keychain = keychain or Keychain()
        self.opener = opener

    def is_connected(self):
        return bool(self.keychain.get(ACC_TOKEN)
                    and self.keychain.get(ACC_USER_ID)
                    and self.keychain.get(ACC_S3_CONFIG))

    def store_connection(self, access_token, ig_user_id, s3_config):
        username = verify_account(access_token, ig_user_id,
                                  opener=self.opener)
        TempObjectStore(s3_config, opener=self.opener)  # validates fields
        self.keychain.set(ACC_TOKEN, access_token)
        self.keychain.set(ACC_USER_ID, ig_user_id)
        self.keychain.set(ACC_S3_CONFIG, json.dumps(s3_config))
        return username

    def disconnect(self):
        for account in (ACC_TOKEN, ACC_USER_ID, ACC_S3_CONFIG):
            self.keychain.delete(account)

    def publish(self, file_path, caption, progress=None, sleeper=time.sleep,
                audio_name=""):
        from pathlib import Path
        path = Path(file_path)
        if not path.is_file():
            raise PublishError("The rendered video file no longer exists.")
        token = self.keychain.get(ACC_TOKEN)
        user_id = self.keychain.get(ACC_USER_ID)
        raw_config = self.keychain.get(ACC_S3_CONFIG)
        if not (token and user_id and raw_config):
            raise PublishError("Instagram is not connected yet.")
        store = TempObjectStore(json.loads(raw_config), opener=self.opener)
        key = f"autolyric_tmp/{int(time.time())}_{path.name}"
        if progress:
            progress(0.05)
        video_url = store.upload(path, key)
        # Sanity-check the public URL, but only ABORT on a definitive
        # not-public/missing (403/404). A local connect failure (HTTP 0 —
        # e.g. antivirus TLS interception on this machine) is NOT proof:
        # Instagram fetches the URL from its own servers, so we proceed.
        if self.opener is urllib.request.urlopen:
            code, _ctype = store.public_head(video_url)
            if code in (401, 403, 404):
                store.delete(key)
                raise PublishError(
                    f"Yüklenen video herkese açık URL'den okunamıyor "
                    f"(HTTP {code}). R2 bucket'ı public mi ve 'public_base' "
                    f"doğru mu kontrol et:\n{video_url}")
        if progress:
            progress(0.1)
        try:
            permalink = publish_reel(token, user_id, video_url, caption,
                                     audio_name=audio_name,
                                     opener=self.opener, sleeper=sleeper,
                                     progress=progress)
        finally:
            store.delete(key)  # temp object never outlives the publish
        return permalink
