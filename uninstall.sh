#!/bin/bash
# Remove everything install.sh created, including the pmset wake schedule.
set -uo pipefail

LABEL="com.hoead.codex-warmup"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> unloading the LaunchAgent"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || echo "    (was not loaded)"
rm -f "$TARGET" && echo "    removed $TARGET"

echo "==> cancelling the repeating wake (needs sudo)"
sudo pmset repeat cancel

echo "==> done. logs are left in place; delete this folder to remove them."
pmset -g sched
