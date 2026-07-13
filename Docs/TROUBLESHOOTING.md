# Troubleshooting

**Engine badge stays red / "Engine Failed"** — run `scripts/setup.sh`; it
recreates `Engine/.venv` and installs dependencies. Details are in
`Logs/engine.log`. The engine binds 127.0.0.1:8765 only; if another process
holds the port, quit it (`lsof -iTCP:8765`).

**"Python venv missing"** — `scripts/setup.sh` (or manually:
`python3.12 -m venv Engine/.venv && Engine/.venv/bin/pip install -r
Engine/requirements.txt`).

**Download fails** — the URL must be a normal YouTube video you are
authorized to use; age-restricted/private/region-locked sources are
rejected with a clear message. The authorization checkbox is required.

**Alignment is slow or wrong** — first run downloads
`mlx-community/whisper-base-mlx` (~150 MB). Instrumental tracks match few
words: lines show low confidence and the app warns instead of guessing.
After editing a lyric line, run **Align Words** again so word stickers use
the corrected text.

**No lyrics found** — put a `.lrc`/`.txt` file into `Cache/lyrics_local/`
(name it `Artist - Title.lrc`) and fetch again; local files win.

**Media fetch fails** — add a Pexels key (free, pexels.com/api) under
Stock Media API Keys; provider failures fall back and are listed in the
job message. Excluded images never return; Regenerate Media always picks
fresh ones.

**Publishing** — YouTube needs your Google OAuth client (Desktop app type,
YouTube Data API v3 enabled); tokens live in the Keychain, revoke at
myaccount.google.com. Instagram needs an eligible professional account,
a Meta app token and S3-compatible temp storage (object is deleted right
after publishing). The app never asks for passwords.

**Disk space** — Clean Up Caches (History section) removes orphaned job
data and old previews; rendered videos in `Output/videos` are never
touched.
