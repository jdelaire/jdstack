#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
label=com.jdelaire.temp-sweeper
dest="$HOME/Library/LaunchAgents/$label.plist"
cp "$here/$label.plist" "$dest"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$dest"
launchctl print "gui/$(id -u)/$label" | grep -E 'state|path ='
