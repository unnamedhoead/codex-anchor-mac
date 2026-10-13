#!/bin/bash
# Smoke tests. Everything runs against a stub codex binary in a throwaway
# directory, so no real request is ever sent and no quota window is opened.
#
#   ./test.sh
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$DIR/plugins/codex-anchor-mac"
PASS=0; FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ok()   { PASS=$((PASS+1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
no()   { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; [ $# -gt 1 ] && printf '       %s\n' "$2"; }
is()   { [ "$2" = "$3" ] && ok "$1" || no "$1" "expected [$3], got [$2]"; }
has()  { case "$2" in *"$3"*) ok "$1";; *) no "$1" "[$2] does not contain [$3]";; esac; }

# --- anchor.sh, against a stub -------------------------------------------
setup_sandbox() {
  rm -rf "$TMP/box"; mkdir -p "$TMP/box"
  cp "$PLUGIN_DIR/anchor.sh" "$TMP/box/"
  echo "# README for the stub to read" > "$TMP/box/README.md"
}
stub() { printf '#!/bin/bash\n%s\n' "$1" > "$TMP/box/stub"; chmod +x "$TMP/box/stub"; }
run_anchor() { ( cd "$TMP/box" && env CODEX_BIN="$TMP/box/stub" "$@" ./anchor.sh >/dev/null 2>&1; echo $? ); }
last_log() { tail -1 "$TMP/box/anchor.log" 2>/dev/null; }

echo "anchor.sh"

setup_sandbox; stub 'echo "stub replied"; exit 0'
is "exits 0 on success" "$(run_anchor)" "0"
has "logs OK" "$(last_log)" "OK"

setup_sandbox; stub 'exit 0'
is "treats empty output as failure" "$(run_anchor)" "1"
has "logs WARN for empty output" "$(last_log)" "WARN"

setup_sandbox; stub 'echo "boom: auth expired" >&2; exit 42'
is "propagates the exit code" "$(run_anchor)" "42"
has "captures stderr on failure" "$(cat "$TMP/box/anchor.log")" "auth expired"

setup_sandbox; stub 'sleep 30'
START=$(date +%s)
RC=$(run_anchor ANCHOR_TIMEOUT_SECS=3)
ELAPSED=$(( $(date +%s) - START ))
# Lower bound matters: an instant failure would otherwise look like a pass.
if [ "$ELAPSED" -ge 2 ] && [ "$ELAPSED" -lt 15 ]; then
  ok "watchdog kills a hung run (${ELAPSED}s, stub sleeps 30s)"
else
  no "watchdog kills a hung run" "took ${ELAPSED}s, expected 2-15s"
fi
is "hung run reports SIGTERM" "$RC" "143"

setup_sandbox
is "fails cleanly with no codex binary" \
   "$( cd "$TMP/box" && CODEX_BIN="$TMP/nope" PATH=/usr/bin:/bin ./anchor.sh >/dev/null 2>&1; echo $? )" "1"
has "says the binary is missing" "$(last_log)" "codex binary not found"

setup_sandbox; stub 'echo hi; exit 0'
mkdir -p "$TMP/box/.anchor.lock"
is "skips when another run holds the lock" "$(run_anchor)" "0"
has "logs SKIP" "$(last_log)" "SKIP"
rmdir "$TMP/box/.anchor.lock"

setup_sandbox; stub 'echo hi; exit 0'
run_anchor >/dev/null
[ -d "$TMP/box/.anchor.lock" ] && no "releases the lock on exit" || ok "releases the lock on exit"

# Truncating by bytes splits a multi-byte character; the log must stay valid.
setup_sandbox
printf '#!/bin/bash\n/usr/bin/python3 -c "print(\x27锚定窗口测试\x27*40,end=\x27\x27)"\nexit 0\n' > "$TMP/box/stub"
chmod +x "$TMP/box/stub"
run_anchor >/dev/null
if /usr/bin/python3 -c "import sys;open('$TMP/box/anchor.log','rb').read().decode('utf-8');sys.exit(0)" 2>/dev/null
then ok "log stays valid UTF-8 with CJK output"
else no "log stays valid UTF-8 with CJK output"; fi

# --- server.py ------------------------------------------------------------
echo
echo "server.py"

is "compiles" "$( /usr/bin/python3 -m py_compile "$DIR/server.py" >/dev/null 2>&1; echo $? )" "0"

TZOUT=$(/usr/bin/python3 - "$DIR" <<'PY'
import sys, pathlib
src = pathlib.Path(sys.argv[1], "server.py").read_text(encoding="utf-8")
ns = {"__name__": "test", "__file__": str(pathlib.Path(sys.argv[1], "server.py"))}
exec(compile(src, "server.py", "exec"), ns)
# A zone that equals the system zone must round-trip unchanged.
h, m = ns["to_local"](4, 30, ns["system_timezone"]())
print(f"{h:02d}:{m:02d}")
# An unknown zone must not raise.
print("%02d:%02d" % ns["to_local"](4, 30, "Nowhere/Nothing"))
# The wake lead must wrap past midnight rather than go negative.
print("%02d:%02d" % ns["wake_time"](0, 1))
PY
)
is "to_local is identity for the system zone" "$(echo "$TZOUT" | sed -n 1p)" "04:30"
is "to_local tolerates an unknown zone"       "$(echo "$TZOUT" | sed -n 2p)" "04:30"
is "wake_time wraps past midnight"            "$(echo "$TZOUT" | sed -n 3p)" "23:58"

# --- guards ---------------------------------------------------------------
echo
echo "guards"

cp -R "$DIR" "$HOME/Documents/.anchor-tcc-probe" 2>/dev/null
OUT=$( cd "$HOME/Documents/.anchor-tcc-probe" && ./setup.sh --no-wake --no-panel 2>&1 | head -1 )
rm -rf "$HOME/Documents/.anchor-tcc-probe"
has "setup.sh refuses a TCC-protected folder" "$OUT" "TCC-protected"

# The UI plist is still at the root until Task 7 retires it.
for f in "$PLUGIN_DIR"/io.github.codex-anchor-mac*.plist "$DIR"/io.github.codex-anchor-mac*.plist; do
  if /usr/bin/python3 -c "import plistlib,sys;plistlib.load(open(sys.argv[1],'rb'))" "$f" 2>/dev/null
  then ok "$(basename "$f") parses as strict XML"
  else no "$(basename "$f") parses as strict XML" "plutil is lenient; plistlib is not"; fi
done

MKT="$DIR/.agents/plugins/marketplace.json"
if /usr/bin/python3 -c "
import json,pathlib
d=json.load(open('$MKT'))
p=d['plugins'][0]
assert p['source']['path']=='plugins/codex-anchor-mac', p['source']['path']
assert pathlib.Path('$DIR', p['source']['path']).is_dir()
" 2>/dev/null
then ok "marketplace manifest points at a real plugin directory"
else no "marketplace manifest points at a real plugin directory"; fi

if visudo -c -f <(sed "s|__USER__|$(id -un)|g" "$PLUGIN_DIR/sudoers.codex-anchor-mac.template") >/dev/null 2>&1
then ok "sudoers template is valid"; else no "sudoers template is valid"; fi

for s in "$DIR"/*.sh "$PLUGIN_DIR"/*.sh; do
  bash -n "$s" 2>/dev/null && ok "$(basename "$s") parses" || no "$(basename "$s") parses"
done

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
