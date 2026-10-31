#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
. scripts/lib/flow-stamp.sh

case ${1:-} in
  "") source=worktree ;;
  --staged) source=index ;;
  *) source=$(git rev-parse --verify --quiet "$1^{commit}") || { echo "Unknown revision: $1" >&2; exit 2; } ;;
esac

stale=()
skills=$(flow_skills "$source")
for skill in $skills; do
  actual=$(flow_stamp "$skill" "$source")
  if [ "$actual" != "$(flow_read "$skill" "$source")" ]; then
    stale+=("$skill")
  fi
done

if [ ${#stale[@]} -gt 0 ]; then
  for skill in "${stale[@]}"; do
    echo "Flow diagram out of date: docs/flows/$skill ($source)" >&2
  done
  echo "Update docs/flows/<skill>.html to match the skill, run scripts/render-flows.sh <skill>, check both PNGs, then stage docs/flows/ with the skill change." >&2
  exit 1
fi
