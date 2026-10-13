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

# --- anchor_core -----------------------------------------------------------
echo
echo "anchor_core"
# Report each unittest case rather than the file, so the headline count
# reflects what is actually covered instead of hiding it behind one line.
run_unittests() {
  local file="$1" label="$2" out
  out="$(/usr/bin/python3 "$file" -v 2>&1)"
  while IFS= read -r line; do
    case "$line" in
      *" ... ok")   ok "$label: ${line%% (*}" ;;
      *" ... FAIL"|*" ... ERROR") no "$label: ${line%% (*}" ;;
    esac
  done <<<"$out"
}

run_unittests "$PLUGIN_DIR/server/test_anchor_core.py" "core"
run_unittests "$PLUGIN_DIR/server/test_anchor_mcp.py" "mcp"

# --- guards ---------------------------------------------------------------
echo
echo "guards"

cp -R "$DIR" "$HOME/Documents/.anchor-tcc-probe" 2>/dev/null
OUT=$( cd "$HOME/Documents/.anchor-tcc-probe" && ./setup.sh --no-wake --no-panel 2>&1 | head -1 )
rm -rf "$HOME/Documents/.anchor-tcc-probe"
has "setup.sh refuses a TCC-protected folder" "$OUT" "TCC-protected"

for f in "$PLUGIN_DIR"/io.github.codex-anchor-mac*.plist; do
  if /usr/bin/python3 -c "import plistlib,sys;plistlib.load(open(sys.argv[1],'rb'))" "$f" 2>/dev/null
  then ok "$(basename "$f") parses as strict XML"
  else no "$(basename "$f") parses as strict XML" "plutil is lenient; plistlib is not"; fi
done

if /usr/bin/python3 -c "
import json, pathlib
root = pathlib.Path('$PLUGIN_DIR')
a = json.load(open(root/'plugin.json'))
b = json.load(open(root/'.codex-plugin'/'plugin.json'))
assert a['name'] == b['name'] == 'codex-anchor-mac'
assert a['version'] == b['version']
assert b['mcpServers'] == './.mcp.json'
m = json.load(open(root/'.mcp.json'))
args = m['mcpServers']['codex_anchor']['args'][0]
assert args.endswith('server/anchor_mcp.py'), args
assert (root/'server'/'anchor_mcp.py').is_file()
assert (root/a['extensions']['com.openai']['interface']['logo'][2:]).is_file()
" 2>/dev/null
then ok "plugin manifests agree and point at real files"
else no "plugin manifests agree and point at real files"; fi

PANEL="$PLUGIN_DIR/ui/dist/panel.html"
if [ -s "$PANEL" ] && ! grep -qE 'src="http|href="http|fetch\(' "$PANEL"
then ok "built panel references no external origin"
else no "built panel references no external origin"; fi

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
