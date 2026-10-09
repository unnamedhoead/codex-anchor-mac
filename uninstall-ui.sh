#!/bin/bash
# Remove the control panel. Leaves the warmup job itself untouched.
set -uo pipefail
LABEL="com.hoead.codex-warmup-ui"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || echo "(was not loaded)"
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" && echo "removed LaunchAgent"
if [ -f /etc/sudoers.d/codex-warmup ]; then
  echo "sudoers rule still installed; remove it with:"
  echo "  sudo rm /etc/sudoers.d/codex-warmup"
fi
