#!/usr/bin/env bash
# usage: tools/publish_media.sh posts/<folder>   (run from the repo root)
# Commits the finished post folder, pushes, and prints public URLs that Metricool can download.
set -euo pipefail
dir="${1%/}"
git add "$dir" log.json 2>/dev/null || git add "$dir"
git commit -qm "post $(basename "$dir")" && git push -q
remote=$(git remote get-url origin); slug=$(echo "$remote" | sed -E 's#(https://|git@)github.com[:/]##; s#\.git$##')
sha=$(git rev-parse HEAD)
for f in "$dir"/*.{png,jpg,mp4}; do
  [ -e "$f" ] || continue
  raw="https://raw.githubusercontent.com/$slug/$sha/$f"
  code=$(curl -s -o /dev/null -w '%{http_code}' -I "$raw")
  echo "$code $raw"
done
