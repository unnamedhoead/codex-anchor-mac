#!/bin/bash
# Remove everything setup.sh installed. Logs and config.json are left behind;
# delete the folder to get rid of those too.
set -uo pipefail

JOB="io.github.codex-anchor-mac"

for label in "$JOB"; do
  if launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID/$label" 2>/dev/null && echo "unloaded $label"
  fi
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done

echo "cancelling the repeating wake (needs admin)"
osascript -e 'do shell script "/usr/bin/pmset repeat cancel" with administrator privileges with prompt "codex-anchor-mac is removing its daily wake"' \
  >/dev/null 2>&1 && echo "  cancelled" || echo "  SKIPPED -- run: sudo pmset repeat cancel"

if [ -f /etc/sudoers.d/codex-anchor-mac ]; then
  echo "removing the sudoers rule (needs admin)"
  osascript -e 'do shell script "/bin/rm -f /etc/sudoers.d/codex-anchor-mac" with administrator privileges with prompt "codex-anchor-mac is removing its sudoers rule"' \
    >/dev/null 2>&1 && echo "  removed" || echo "  SKIPPED -- run: sudo rm /etc/sudoers.d/codex-anchor-mac"
fi

echo
echo "The Codex plugin is removed separately:"
echo "  codex plugin remove codex-anchor-mac"
echo
echo "Done. Logs and config.json are still in $HOME/.codex-anchor"
