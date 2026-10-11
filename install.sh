#!/bin/bash
# Install the daily anchor: a LaunchAgent at the configured time, plus a
# pmset wake three minutes earlier
# so the Mac is actually awake when the agent fires.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="io.github.codex-anchor-mac"
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
    echo "       somewhere like ~/codex-anchor-mac and run ./install.sh again." >&2
    exit 1
    ;;
esac

echo "==> writing $TARGET"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__ANCHOR_SH__|$DIR/anchor.sh|g" -e "s|__DIR__|$DIR|g" "$TEMPLATE" >"$TARGET"
plutil -lint "$TARGET"

echo "==> (re)loading the LaunchAgent"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$TARGET"
launchctl enable "gui/$UID/$LABEL"

echo
if [ "${SKIP_WAKE:-0}" = "1" ]; then
  echo "==> daily wake skipped (--no-wake)"
  echo
  echo "==> done."
  exit 0
fi

echo "==> optional: daily wake at $WAKE_TIME"
echo "    launchd cannot wake a sleeping Mac, so without this the job is late"
echo "    (or skipped) on nights the Mac is not plugged in. Plugged-in users"
echo "    with sleep disabled on AC do not need it."
echo

# Authorization Services rather than sudo: works without a terminal, shows the
# standard macOS prompt, and supports Touch ID. One prompt covers both changes.
ADMIN_SCRIPT="/usr/bin/pmset repeat wake MTWRFSU $WAKE_TIME"
if [ "${ANCHOR_INSTALL_SUDOERS:-1}" = "1" ]; then
  RENDERED="$DIR/.sudoers.rendered"
  sed "s|__USER__|$(id -un)|g" "$DIR/sudoers.codex-anchor-mac.template" >"$RENDERED"
  chmod 0600 "$RENDERED"
  # Letting the panel change the wake time later needs a narrow NOPASSWD rule.
  ADMIN_SCRIPT="$ADMIN_SCRIPT && /usr/bin/install -m 0440 -o root -g wheel '$RENDERED' /etc/sudoers.d/codex-anchor-mac"
fi

if sudo -n pmset repeat wake MTWRFSU "$WAKE_TIME" 2>/dev/null; then
  echo "    done (sudoers rule already in place)"
elif osascript -e "do shell script \"$ADMIN_SCRIPT\" with administrator privileges with prompt \"codex-anchor-mac needs to schedule a daily wake\"" >/dev/null 2>&1; then
  echo "    done"
else
  echo "    SKIPPED (cancelled or failed). The anchor still runs; it will just"
  echo "    be late on battery nights. To enable it later, re-run ./install.sh"
fi
rm -f "$DIR/.sudoers.rendered"

echo
echo "==> done. current state:"
launchctl print "gui/$UID/$LABEL" | grep -E '^\s+(state|path|runs|last exit code)' || true
pmset -g sched
