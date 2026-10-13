#!/bin/bash
# Fire one tiny Codex request to anchor the start of a 5-hour usage window.
# Designed to run unattended from launchd at ~04:58 so that the window
# boundaries land inside the working day instead of after it.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$DIR/anchor.log"
LOCK="$DIR/.anchor.lock"   # a directory: mkdir is the atomic test-and-set
TIMEOUT_SECS="${ANCHOR_TIMEOUT_SECS:-240}"
LABEL="io.github.codex-anchor-mac"
# Overridable so the tests can observe these without touching the real display.
PMSET="${PMSET:-/usr/bin/pmset}"
CAFFEINATE="${CAFFEINATE:-/usr/bin/caffeinate}"

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

# launchd appends to this file forever, so a failure from weeks ago keeps
# looking like the current state. Reset it; this run owns its contents.
: > "$DIR/launchd.err.log" 2>/dev/null || true

# Keep the log from growing without bound.
if [ -f "$LOG" ] && [ "$(wc -l <"$LOG")" -gt 2000 ]; then
  tail -n 1000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# Never let a manual run and the scheduled run overlap.
if ! mkdir "$LOCK" 2>/dev/null; then
  log "SKIP  another anchor run is already in progress"
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if [ -z "$CODEX" ] || [ ! -x "$CODEX" ]; then
  log "FAIL  codex binary not found (set CODEX_BIN to override)"
  exit 1
fi

# Two things can silently desynchronise between runs, and both would otherwise
# only show up as a schedule that quietly fires at the wrong time.
self_check() {
  local cfg="$DIR/config.json" plist="$HOME/Library/LaunchAgents/$LABEL.plist"
  [ -f "$cfg" ] || return 0
  /usr/bin/python3 - "$cfg" "$plist" <<'PYCHK'
import json, os, plistlib, sys

cfg_path, plist_path = sys.argv[1], sys.argv[2]
try:
    cfg = json.load(open(cfg_path, encoding="utf-8"))
except Exception as exc:
    print(f"config.json unreadable ({exc})")
    raise SystemExit(0)

try:
    link = os.readlink("/etc/localtime").split("zoneinfo/", 1)
    system_tz = link[1] if len(link) == 2 else "UTC"
except OSError:
    system_tz = "UTC"

computed_under = cfg.get("computedUnderSystemTimezone")
if computed_under and computed_under != system_tz:
    print(f"system timezone is {system_tz} but the schedule was computed for "
          f"{computed_under}; re-save it in the panel")

try:
    with open(plist_path, "rb") as fh:
        cal = plistlib.load(fh).get("StartCalendarInterval") or {}
except Exception:
    raise SystemExit(0)

# When the chosen zone IS the system zone, the plist should hold exactly the
# configured time. Any other pairing is a conversion we cannot re-verify here.
if cfg.get("timezone") == system_tz:
    want = (cfg.get("hour"), cfg.get("minute"))
    got = (cal.get("Hour"), cal.get("Minute"))
    if None not in want and want != got:
        print(f"config says {want[0]:02d}:{want[1]:02d} but launchd is set to "
              f"{got[0]:02d}:{got[1]:02d}; re-save it in the panel")
PYCHK
}

while IFS= read -r issue; do
  [ -n "$issue" ] && log "WARN  $issue"
done < <(self_check 2>/dev/null)

PROMPT='Read README.md in the current directory and print only its first 100 characters. Do nothing else.'

OUT="$(mktemp -t codex-anchor)"
START_EPOCH=$(date +%s)

# A pmset wake lands the Mac in DarkWake, where it honours "Sleep Service Back
# to Sleep" over an idle assertion and freezes us mid-request for hours. -u is
# the only flag that forces a real wake (-s is AC-only, see caffeinate(1)), so
# declare user activity to escape DarkWake, then blank the display again right
# away -- nobody wants a laptop lighting up at 04:30.
# ...but only when nobody is at the keyboard. Forcing a wake flashes the
# display, and this script also runs from the test suite, which would strobe
# the screen of whoever is working on it.
if ! "$PMSET" -g assertions 2>/dev/null | grep -qE '^[[:space:]]*UserIsActive[[:space:]]+1'; then
  "$CAFFEINATE" -u -t 1 2>/dev/null
  "$PMSET" displaysleepnow 2>/dev/null
fi

"$CAFFEINATE" -i -s "$CODEX" exec \
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
