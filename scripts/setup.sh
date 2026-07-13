#!/bin/zsh
# AutoLyricMac one-shot setup: Homebrew deps + Python venv + build + tests.
# Safe to re-run; paths are relative to the repo, not any developer machine.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Checking Homebrew dependencies (ffmpeg, yt-dlp, python@3.12)…"
for pkg in ffmpeg yt-dlp python@3.12; do
    if ! brew list --versions "$pkg" >/dev/null 2>&1; then
        echo "    installing $pkg…"
        brew install "$pkg"
    fi
done

PYTHON="$(brew --prefix python@3.12)/bin/python3.12"

if [ ! -x Engine/.venv/bin/python ]; then
    echo "==> Creating Python venv…"
    "$PYTHON" -m venv Engine/.venv
fi
echo "==> Installing engine dependencies…"
Engine/.venv/bin/pip install -q --upgrade pip
Engine/.venv/bin/pip install -q -r Engine/requirements.txt

echo "==> Running engine tests…"
Engine/.venv/bin/python -m unittest discover -s Engine/tests

echo "==> Building the app (release)…"
cd MacApp && swift build -c release && swift test && cd ..

echo ""
echo "Setup complete. Start the app with:  cd MacApp && swift run"
echo "First alignment downloads the Whisper model (~150 MB) after your"
echo "approval in the app. Stock/publishing credentials are optional and"
echo "always stay in your Keychain."
