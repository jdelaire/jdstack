#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
. scripts/lib/flow-stamp.sh

playwright=playwright@1.64.1
[ $# -gt 0 ] || set -- $(flow_skills worktree)

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for skill in "$@"; do
  html=docs/flows/$skill.html
  [ -f "$html" ] || { echo "Missing $html" >&2; exit 1; }
  [ -d "skills/$skill" ] || { echo "Missing skills/$skill" >&2; exit 1; }
  for scheme in light dark; do
    npx -y "$playwright" screenshot --device="Desktop Chrome HiDPI" --viewport-size=900,800 \
      --color-scheme="$scheme" --full-page "file://$PWD/$html" "$tmp/$skill-$scheme.png" >/dev/null
  done
  mv "$tmp/$skill-light.png" "$tmp/$skill-dark.png" docs/flows/
  flow_stamp "$skill" worktree > "$tmp/$skill.stamp"
  mv "$tmp/$skill.stamp" "docs/flows/$skill.stamp"
  echo "Rendered docs/flows/$skill-light.png and docs/flows/$skill-dark.png"
done
