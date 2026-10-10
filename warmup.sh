#!/bin/bash
# Fire one tiny Codex request to anchor the start of a 5-hour usage window.
# Designed to run unattended from launchd at ~04:58 so that the window
# boundaries land inside the working day instead of after it.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$DIR/warmup.log"
LOCK="$DIR/.warmup.lock"   # a directory: mkdir is the atomic test-and-set
TIMEOUT_SECS="${WARMUP_TIMEOUT_SECS:-240}"

# Codex ships several ways on macOS: bundled inside ChatGPT.app, as a
# standalone app, or installed by npm/brew onto PATH. Try each in turn.
find_codex() {
  [ -n "${CODEX_BIN:-}" ] && { printf '%s' "$CODEX_BIN"; return; }
  local c
  for c in \
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex" \
    "/Applications/Codex.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex" \
    "/Applications/Codex.app/Contents/MacOS/codex" \
    "/opt/homebrew/bin/codex" \
    "/usr/local/bin/codex" \
    "$HOME/.local/bin/codex"
  do
    [ -x "$c" ] && { printf '%s' "$c"; return; }
  done
  command -v codex 2>/dev/null || true
}
CODEX="$(find_codex)"

export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$PATH"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*" >>"$LOG"; }

# Keep the log from growing without bound.
if [ -f "$LOG" ] && [ "$(wc -l <"$LOG")" -gt 2000 ]; then
  tail -n 1000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# Never let a manual run and the scheduled run overlap.
if ! mkdir "$LOCK" 2>/dev/null; then
  log "SKIP  another warmup run is already in progress"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if [ -z "$CODEX" ] || [ ! -x "$CODEX" ]; then
  log "FAIL  codex binary not found (set CODEX_BIN to override)"
  exit 1
fi

PROMPT='Read README.md in the current directory and print only its first 100 characters. Do nothing else.'

OUT="$(mktemp -t codex-warmup)"
START_EPOCH=$(date +%s)

# A pmset wake lands the Mac in DarkWake, where it honours "Sleep Service Back
# to Sleep" over an idle assertion and freezes us mid-request for hours. -u is
# the only flag that forces a real wake (-s is AC-only, see caffeinate(1)), so
# declare user activity to escape DarkWake, then blank the display again right
# away -- nobody wants a laptop lighting up at 04:30.
/usr/bin/caffeinate -u -t 1 2>/dev/null
/usr/bin/pmset displaysleepnow 2>/dev/null

/usr/bin/caffeinate -i -s "$CODEX" exec \
  --ephemeral \
  --skip-git-repo-check \
  -C "$DIR" \
  -s read-only \
  -c approval_policy="never" \
  -c model_reasoning_effort="low" \
  -c notify="[]" \
  "$PROMPT" >"$OUT" 2>&1 &
CODEX_PID=$!

( sleep "$TIMEOUT_SECS"
  kill -TERM "$CODEX_PID" 2>/dev/null && sleep 10 && kill -KILL "$CODEX_PID" 2>/dev/null
) >/dev/null 2>&1 &
WATCHER_PID=$!

RC=0
wait "$CODEX_PID" || RC=$?
kill -TERM "$WATCHER_PID" 2>/dev/null
wait "$WATCHER_PID" 2>/dev/null || true

ELAPSED=$(( $(date +%s) - START_EPOCH ))

if [ "$RC" -eq 0 ] && [ -s "$OUT" ]; then
  # One line of evidence that the model actually answered, not just that the
  # process exited cleanly.
  # tail -c cuts bytes, which splits multi-byte characters; iconv -c drops the
  # resulting partial character instead of logging mojibake.
  REPLY="$(tr '\n' ' ' <"$OUT" | tail -c 160 | iconv -f UTF-8 -t UTF-8 -c)"
  # The watchdog counts awake seconds (correct for detecting a hung request),
  # but ELAPSED is wall-clock, so the two diverge when the Mac slept mid-run.
  SLEPT=""
  [ "$ELAPSED" -gt 120 ] && SLEPT=" [machine slept mid-run; anchor landed late]"
  log "OK    exit=0 ${ELAPSED}s tz=$(date +%Z%z)${SLEPT}  tail: ${REPLY}"
elif [ "$RC" -eq 0 ]; then
  # Exit 0 with no output means no turn happened -- e.g. auth silently lapsed.
  # That would not anchor a window, so do not report it as success.
  log "WARN  exit=0 but produced no output ${ELAPSED}s -- window probably NOT anchored"
  RC=1
else
  log "FAIL  exit=$RC ${ELAPSED}s"
  sed 's/^/          | /' "$OUT" | tail -n 20 >>"$LOG"
fi

rm -f "$OUT"
exit "$RC"
