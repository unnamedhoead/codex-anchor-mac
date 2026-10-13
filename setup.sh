#!/bin/bash
# One command to install everything. Safe to re-run; it re-applies the same
# state rather than stacking up duplicates.
#
#   ./setup.sh                 job + control panel + daily wake
#   ./setup.sh --no-panel      just the anchor job
#   ./setup.sh --no-wake       skip the admin prompt entirely
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$DIR/plugins/codex-anchor-mac"
PANEL=1; WAKE=1
for a in "$@"; do
  case "$a" in
    --no-panel) PANEL=0 ;;
    --no-wake)  WAKE=0 ;;
    -h|--help)  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 1 ;;
  esac
done

# launchd gets no access to TCC-protected folders, and the failure is silent
# until the job misses its time at 4am. Refuse rather than let that happen.
case "$DIR/" in
  "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Downloads/"*|\
  "$HOME/Movies/"*|"$HOME/Music/"*|"$HOME/Pictures/"*)
    echo "ERROR: $DIR sits in a macOS TCC-protected folder." >&2
    echo "       launchd cannot run scripts there. Move this folder to e.g." >&2
    echo "       ~/codex-anchor-mac and run ./setup.sh again." >&2
    exit 1 ;;
esac

echo "==> 1/3  anchor job"
ANCHOR_INSTALL_SUDOERS=$WAKE SKIP_WAKE=$((1 - WAKE)) PLUGIN_DIR="$PLUGIN_DIR" "$DIR/install.sh"

if [ "$PANEL" = "1" ]; then
  echo
  echo "==> 2/3  control panel"
  "$DIR/install-ui.sh"
  echo
  echo "==> 3/3  opening http://127.0.0.1:7788"
  open "http://127.0.0.1:7788" 2>/dev/null || true
else
  echo
  echo "==> panel skipped"
fi

echo
echo "Done. Check tomorrow's run with:"
echo "  tail -3 $HOME/.codex-anchor/anchor.log"
