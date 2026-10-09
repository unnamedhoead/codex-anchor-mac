#!/bin/bash
# Install the daily warmup: a LaunchAgent at 04:58 plus a pmset wake at 04:55
# so the Mac is actually awake when the agent fires.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.hoead.codex-warmup"
TEMPLATE="$DIR/$LABEL.plist"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
WAKE_TIME="04:27:00"

[ -f "$TEMPLATE" ] || { echo "missing $TEMPLATE" >&2; exit 1; }

# launchd-spawned processes have no access to TCC-protected folders, so a script
# living in one fails with "Operation not permitted" (exit 126) at 04:58 with no
# warning at install time. Refuse to install from there rather than fail nightly.
case "$DIR/" in
  "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Downloads/"*|\
  "$HOME/Movies/"*|"$HOME/Music/"*|"$HOME/Pictures/"*)
    echo "ERROR: $DIR is inside a macOS TCC-protected folder." >&2
    echo "       launchd cannot execute scripts there -- move this folder to" >&2
    echo "       somewhere like ~/codex-quota-warmup and run ./install.sh again." >&2
    exit 1
    ;;
esac

echo "==> writing $TARGET"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__WARMUP_SH__|$DIR/warmup.sh|g" -e "s|__DIR__|$DIR|g" "$TEMPLATE" >"$TARGET"
plutil -lint "$TARGET"

echo "==> (re)loading the LaunchAgent"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$TARGET"
launchctl enable "gui/$UID/$LABEL"

echo
echo "==> scheduling a daily wake at $WAKE_TIME (needs sudo)"
# pmset holds exactly one repeating schedule, so show what is there first.
if pmset -g sched | grep -qi 'Repeating power events'; then
  echo "    WARNING: a repeating power event already exists and will be replaced:"
  pmset -g sched | sed -n '/Repeating power events/,$p' | sed 's/^/    /'
  read -r -p "    Continue? [y/N] " ans
  [ "$ans" = "y" ] || { echo "    skipped pmset; the agent will only fire if the Mac is already awake."; exit 0; }
fi
sudo pmset repeat wake MTWRFSU "$WAKE_TIME"

echo
echo "==> done. current state:"
launchctl print "gui/$UID/$LABEL" | grep -E '^\s+(state|path|runs|last exit code)' || true
pmset -g sched
