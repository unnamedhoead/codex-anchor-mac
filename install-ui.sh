#!/bin/bash
# Install the localhost control panel. Separate from install.sh on purpose:
# the warmup job must keep working even if the panel is broken or removed.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="io.github.codex-anchor-mac.ui"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT=7788

case "$DIR/" in
  "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Downloads/"*)
    echo "ERROR: $DIR is TCC-protected; launchd cannot run from there." >&2
    exit 1 ;;
esac

if lsof -nP -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo "WARNING: port $PORT is already in use:" >&2
  lsof -nP -iTCP:$PORT -sTCP:LISTEN >&2
  echo "         (that is fine if it is this panel restarting)" >&2
fi

echo "==> writing $TARGET"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s|__DIR__|$DIR|g" "$DIR/$LABEL.plist" >"$TARGET"
plutil -lint "$TARGET"

echo "==> (re)loading"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$TARGET"
launchctl enable "gui/$UID/$LABEL"

echo
echo "==> sudoers rule (lets the panel keep pmset in sync)"
RENDERED="$DIR/.sudoers.rendered"
sed "s|__USER__|$(id -un)|g" "$DIR/sudoers.codex-anchor-mac.template" >"$RENDERED"
chmod 0600 "$RENDERED"
if sudo -n pmset repeat wake MTWRFSU 04:27:00 2>/dev/null; then
  echo "    already installed"
  rm -f "$RENDERED"
else
  echo "    not installed yet. Run this to enable password-free pmset sync:"
  echo
  echo "      sudo install -m 0440 -o root -g wheel \\"
  echo "        $RENDERED /etc/sudoers.d/codex-anchor-mac"
  echo
  echo "    Without it the panel still changes the launchd time; it just cannot"
  echo "    move the pmset wake, so you must run that one command yourself."
fi

echo
sleep 1
echo "==> http://127.0.0.1:$PORT"
curl -fsS -m 3 "http://127.0.0.1:$PORT/api/status" >/dev/null \
  && echo "    responding" || echo "    NOT responding -- check $DIR/ui.err.log"
