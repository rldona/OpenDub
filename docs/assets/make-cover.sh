#!/usr/bin/env bash
# Regenerates docs/assets/cover.png (the repository cover / GitHub social preview, 1280x640).
#
#   1. uv run opendub web --no-browser   (with a few dubbed videos in the library)
#   2. docs/assets/make-cover.sh [http://localhost:8000]
#
# It screenshots the real app (library, English, dark) with headless Chrome and lays it out in cover.html.
set -euo pipefail

base="${1:-http://localhost:8000}"
here="$(cd "$(dirname "$0")" && pwd)"
chrome="$(command -v google-chrome || command -v chromium || command -v chromium-browser)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

shoot() {  # url, WxH, output
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-dark-mode --lang=en-US \
    --user-data-dir="$tmp/profile" --virtual-time-budget=5000 \
    --window-size="$2" --screenshot="$3" "$1" >/dev/null 2>&1
}

shoot "$base/#/" 1280,800 "$tmp/app.png"
cp "$here/cover.html" "$tmp/cover.html"
shoot "file://$tmp/cover.html" 1280,640 "$here/cover.png"
echo "wrote docs/assets/cover.png ($(( $(stat -c %s "$here/cover.png") / 1024 )) KB, 1280x640)"
