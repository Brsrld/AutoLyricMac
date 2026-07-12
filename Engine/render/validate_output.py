#!/usr/bin/env python3
"""Validate a rendered video against the AutoLyricMac output contract:
1080x1920, 30 fps, H.264 yuv420p, AAC audio, fast-start, fully decodable.

Usage: python validate_output.py <video.mp4> [expected_duration]
Exits non-zero on any failure.
"""

import json
import subprocess
import sys

from proto_common import FFMPEG, FFPROBE


def probe(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def validate(path, expected_duration=None):
    checks = []
    info = probe(path)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")

    check("video stream present", video is not None)
    if video:
        check("codec h264", video["codec_name"] == "h264", video["codec_name"])
        check("1080x1920", (video["width"], video["height"]) == (1080, 1920),
              f'{video["width"]}x{video["height"]}')
        check("30 fps", video["r_frame_rate"] == "30/1", video["r_frame_rate"])
        check("yuv420p", video["pix_fmt"] == "yuv420p", video["pix_fmt"])
    check("audio stream present (aac)", audio is not None
          and audio["codec_name"] == "aac",
          audio["codec_name"] if audio else "none")
    duration = float(info["format"]["duration"])
    if expected_duration is not None:
        check("duration", abs(duration - expected_duration) < 0.25,
              f"{duration:.2f}s vs {expected_duration}s")
    # fast-start: moov atom must precede mdat
    with open(path, "rb") as fh:
        head = fh.read(64 * 1024)
    moov, mdat = head.find(b"moov"), head.find(b"mdat")
    check("fast-start (moov first)", 0 <= moov < mdat if mdat != -1 else moov >= 0)
    # full decode (playability)
    rc = subprocess.run([FFMPEG, "-v", "error", "-i", str(path),
                         "-f", "null", "-"], capture_output=True, text=True)
    check("decodes fully", rc.returncode == 0 and not rc.stderr.strip(),
          (rc.stderr.strip()[:120] or ""))
    return all(checks)


def main():
    path = sys.argv[1]
    expected = float(sys.argv[2]) if len(sys.argv) > 2 else None
    print(f"Validating {path}")
    ok = validate(path, expected)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
