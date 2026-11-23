#!/usr/bin/env bash
# usage: tools/fetch_images.sh URL [URL...]   (run from the repo root)
# Mirrors store images into media-in/ via the GitHub Action, waits, prints local paths.
set -euo pipefail
mkdir -p fetch
printf '%s\n' "$@" > fetch/requests.txt
git add fetch/requests.txt
git commit -qm "fetch $(date +%F-%H%M)" && git push -q
want=()
for u in "$@"; do
  n=$(printf '%s' "$u" | sha1sum | cut -c1-12); want+=("$n")
done
for i in $(seq 1 36); do            # up to ~6 minutes
  sleep 10; git pull -q --rebase
  missing=0; for n in "${want[@]}"; do ls media-in/"$n".* >/dev/null 2>&1 || missing=1; done
  [ $missing -eq 0 ] && { for n in "${want[@]}"; do ls media-in/"$n".*; done; exit 0; }
done
echo "TIMEOUT: images not mirrored (check the Actions tab on GitHub)" >&2; exit 1
