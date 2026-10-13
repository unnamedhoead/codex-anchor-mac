#!/bin/bash
# One command to install everything. Safe to re-run; it re-applies the same
# state rather than stacking up duplicates.
#
#   ./setup.sh                 the job, the daily wake, and how to get the panel
#   ./setup.sh --no-panel      skip the panel instructions
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

echo "==> 1/2  anchor job"
ANCHOR_INSTALL_SUDOERS=$WAKE SKIP_WAKE=$((1 - WAKE)) PLUGIN_DIR="$PLUGIN_DIR" "$DIR/install.sh"

echo
if [ "$PANEL" = "1" ]; then
  echo "==> 2/2  control panel"
  echo "    The panel is a Codex plugin now, not a local web page. Install it"
  echo "    from inside Codex:"
  echo
  echo "      codex plugin marketplace add https://github.com/unnamedhoead/codex-anchor-mac.git"
  echo "      codex plugin add codex-anchor-mac@codex-anchor-mac"
  echo
  echo "    Then ask Codex to open the anchor panel."
else
  echo "==> panel skipped"
fi

echo
echo "Done. Check tomorrow's run with:"
echo "  tail -3 $HOME/.codex-anchor/anchor.log"
