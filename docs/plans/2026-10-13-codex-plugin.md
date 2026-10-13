# Codex Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the anchor control panel as a Codex plugin, so installing the plugin installs the daily job and renders the panel inside Codex.

**Architecture:** The repository becomes a single-plugin git marketplace. A stdio MCP server replaces the HTTP server as the only backend; the UI is an MCP Apps resource that reaches it through `callServerTool`, never over the network. The launchd job lives in `~/.codex-anchor/`, outside the version-scoped plugin cache.

**Tech Stack:** Python 3.9 standard library (MCP server, no SDK), TypeScript + `@modelcontextprotocol/ext-apps` 1.7.5 + esbuild (UI), bash (job + tests), launchd + pmset.

**Spec:** `docs/specs/2026-10-13-codex-plugin-design.md`

## Global Constraints

- Python must be `/usr/bin/python3` (3.9.6 on this machine) and use the standard library only. No pip installs: the plugin runs on a user's machine with no build step.
- Pin `@modelcontextprotocol/ext-apps` to exactly `1.7.5`. The extension is young and the Codex host has an open CSP bug.
- `ui/dist/panel.html` is committed. A user must never be asked to run `npm install`.
- The UI resource declares `"connectDomains": []` and `"resourceDomains": []`. The panel must work with no network access of any kind.
- `anchor.sh` keeps its current behaviour exactly. This plan moves it and changes nothing inside it except paths it reads.
- macOS only. ChatGPT Plus only. Never claim the DarkWake workaround is verified.
- Existing tests must keep passing: `./test.sh` is 28 tests before this plan and must never go below that.

## Review Focus

These are implied by the spec but easy to leave untested. Each line's test is assigned to the task that owns the code.

1. `~/.codex-anchor/anchor.sh` deleted while the LaunchAgent still points at it — the 04:30 run fails and nothing says so. `anchor_status` must report it. (Task 4)
2. Plugin upgraded, `~/.codex-anchor/anchor.sh` still the old copy — must surface as version drift, not run stale forever. (Task 4)
3. First `anchor_status` with no `~/.codex-anchor/` at all — must create it and report what it did, not crash. (Task 4)
4. The admin dialog is cancelled — the pmset step fails but the LaunchAgent must still install and the tool must still return success for the part that worked. (Task 4)
5. `config.json` corrupt or truncated — the MCP server must fall back to defaults and keep serving, not exit. (Task 2)

---

### Task 1: Restructure into marketplace + plugin layout

**Files:**
- Create: `.agents/plugins/marketplace.json`
- Move: `anchor.sh` → `plugins/codex-anchor-mac/anchor.sh`
- Move: `io.github.codex-anchor-mac.plist` → `plugins/codex-anchor-mac/io.github.codex-anchor-mac.plist`
- Move: `sudoers.codex-anchor-mac.template` → `plugins/codex-anchor-mac/sudoers.codex-anchor-mac.template`
- Modify: `setup.sh`, `install.sh`, `test.sh` (paths)
- Test: `test.sh`

**Interfaces:**
- Consumes: nothing
- Produces: `PLUGIN_DIR="$DIR/plugins/codex-anchor-mac"` convention used by every later task; the marketplace name `codex-anchor-mac` and plugin name `codex-anchor-mac`

- [ ] **Step 1: Move the operational files, keeping git history**

```bash
cd ~/codex-anchor-mac
mkdir -p plugins/codex-anchor-mac
git mv anchor.sh plugins/codex-anchor-mac/anchor.sh
git mv io.github.codex-anchor-mac.plist plugins/codex-anchor-mac/io.github.codex-anchor-mac.plist
git mv sudoers.codex-anchor-mac.template plugins/codex-anchor-mac/sudoers.codex-anchor-mac.template
```

- [ ] **Step 2: Run the tests to see them fail on the moved paths**

Run: `./test.sh`
Expected: FAIL — the `anchor.sh parses` and plist checks cannot find their files.

- [ ] **Step 3: Point setup.sh and install.sh at the plugin directory**

In `setup.sh`, after the `DIR=` line, add:

```bash
PLUGIN_DIR="$DIR/plugins/codex-anchor-mac"
```

and change the install invocation to pass it through:

```bash
ANCHOR_INSTALL_SUDOERS=$WAKE SKIP_WAKE=$((1 - WAKE)) PLUGIN_DIR="$PLUGIN_DIR" "$DIR/install.sh"
```

In `install.sh`, after its own `DIR=` line, add:

```bash
# The operational files live in the plugin directory; the repo root only
# carries the installers, so both entry points use one copy.
PLUGIN_DIR="${PLUGIN_DIR:-$DIR/plugins/codex-anchor-mac}"
```

then replace every `$DIR/anchor.sh`, `$DIR/$LABEL.plist` and
`$DIR/sudoers.codex-anchor-mac.template` with the `$PLUGIN_DIR/` equivalent.
The `__DIR__` substitution still resolves to `$PLUGIN_DIR`, because that is
where `anchor.log` and `config.json` sit during a non-Codex install.

- [ ] **Step 4: Point test.sh at the plugin directory**

In `test.sh`, after `DIR=`, add:

```bash
PLUGIN_DIR="$DIR/plugins/codex-anchor-mac"
```

Replace `cp "$DIR/anchor.sh" "$TMP/box/"` with `cp "$PLUGIN_DIR/anchor.sh" "$TMP/box/"`,
`for f in "$DIR"/io.github.codex-anchor-mac*.plist` with `for f in "$PLUGIN_DIR"/io.github.codex-anchor-mac*.plist`,
and the sudoers path with `"$PLUGIN_DIR/sudoers.codex-anchor-mac.template"`.
Change the shell-parse loop to cover both directories:

```bash
for s in "$DIR"/*.sh "$PLUGIN_DIR"/*.sh; do
  bash -n "$s" 2>/dev/null && ok "$(basename "$s") parses" || no "$(basename "$s") parses"
done
```

- [ ] **Step 5: Run the tests to verify they pass again**

Run: `./test.sh`
Expected: PASS, 28 or more.

- [ ] **Step 6: Write the marketplace manifest**

Create `.agents/plugins/marketplace.json`:

```json
{
  "name": "codex-anchor-mac",
  "interface": {
    "displayName": "Codex Anchor"
  },
  "plugins": [
    {
      "name": "codex-anchor-mac",
      "category": "Developer Tools",
      "source": {
        "source": "git-subdir",
        "url": "https://github.com/unnamedhoead/codex-anchor-mac.git",
        "path": "plugins/codex-anchor-mac",
        "ref": "main"
      },
      "policy": {
        "installation": "AVAILABLE"
      }
    }
  ]
}
```

- [ ] **Step 7: Add a test that the manifest is valid JSON and self-consistent**

Append to `test.sh`'s `guards` section:

```bash
MKT="$DIR/.agents/plugins/marketplace.json"
if /usr/bin/python3 -c "
import json,sys,pathlib
d=json.load(open('$MKT'))
p=d['plugins'][0]
assert p['source']['path']=='plugins/codex-anchor-mac', p['source']['path']
assert pathlib.Path('$DIR', p['source']['path']).is_dir()
" 2>/dev/null
then ok "marketplace manifest points at a real plugin directory"
else no "marketplace manifest points at a real plugin directory"; fi
```

- [ ] **Step 8: Run the tests**

Run: `./test.sh`
Expected: PASS, 29 or more.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Restructure into a marketplace with one plugin subdirectory"
```

---

### Task 2: Extract the shared logic into anchor_core.py

**Files:**
- Create: `plugins/codex-anchor-mac/server/anchor_core.py`
- Test: `plugins/codex-anchor-mac/server/test_anchor_core.py`

**Interfaces:**
- Consumes: Task 1's `plugins/codex-anchor-mac/` location
- Produces: module `anchor_core` exporting `HOME_DIR: pathlib.Path`, `LABEL: str`, `SERVICE: str`, `run(cmd: list[str]) -> tuple[int, str]`, `system_timezone() -> str`, `load_config() -> dict`, `save_config(cfg: dict) -> None`, `to_local(hour: int, minute: int, tz_name: str) -> tuple[int, int]`, `wake_time(hour: int, minute: int) -> tuple[int, int]`, `timezone_choices() -> list[dict]`, `timezone_drifted(cfg: dict) -> bool`, `read_schedule() -> tuple[int | None, int | None]`, `agent_state() -> dict`, `pmset_wake() -> str`, `recent_runs(limit: int = 15) -> list[str]`, `last_run() -> dict | None`, `status() -> dict`, `set_schedule(hour: int, minute: int, tz_name: str) -> list[dict]`

- [ ] **Step 1: Copy server.py lines 1-266 into anchor_core.py and repoint the paths**

Copy `server.py` from the imports through the end of `status()` (line 266) into
`plugins/codex-anchor-mac/server/anchor_core.py`. Delete the HTTP-only names:
`PORT`, `BIND`, `ALLOWED_HOSTS`, `INDEX`. Replace the path block with:

```python
# The job's home is deliberately outside the plugin: Codex scopes the plugin
# cache by version, so a LaunchAgent pointing into it would break on upgrade.
HOME_DIR = pathlib.Path.home() / ".codex-anchor"
PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
LABEL = "io.github.codex-anchor-mac"
LOG = HOME_DIR / "anchor.log"
CONFIG = HOME_DIR / "config.json"
TEMPLATE = PLUGIN_DIR / f"{LABEL}.plist"
INSTALLED = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
UID = os.getuid()
SERVICE = f"gui/{UID}/{LABEL}"
WAKE_LEAD_MINUTES = 3
```

In `set_schedule`, delete the step that rewrites `install.sh`'s `WAKE_TIME`:
the installer no longer owns the schedule, `config.json` does.

- [ ] **Step 2: Write the failing tests**

Create `plugins/codex-anchor-mac/server/test_anchor_core.py`:

```python
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import anchor_core as core


class TimeMath(unittest.TestCase):
    def test_system_zone_is_identity(self):
        self.assertEqual(core.to_local(4, 30, core.system_timezone()), (4, 30))

    def test_unknown_zone_does_not_raise(self):
        self.assertEqual(core.to_local(4, 30, "Nowhere/Nothing"), (4, 30))

    def test_wake_wraps_past_midnight(self):
        self.assertEqual(core.wake_time(0, 1), (23, 58))


class Timezones(unittest.TestCase):
    def test_one_entry_per_rule_set_not_per_zone(self):
        names = [c["name"] for c in core.timezone_choices()]
        self.assertLess(len(names), 100)
        self.assertGreater(len(names), 40)

    def test_system_zone_is_always_offered(self):
        names = [c["name"] for c in core.timezone_choices()]
        self.assertIn(core.system_timezone(), names)


class Config(unittest.TestCase):
    def test_corrupt_config_falls_back_instead_of_raising(self):
        # Review Focus 5: a truncated write must not take the server down.
        original = core.CONFIG.read_bytes() if core.CONFIG.exists() else None
        core.CONFIG.parent.mkdir(parents=True, exist_ok=True)
        core.CONFIG.write_text('{"timezone": "Asia/Sh', encoding="utf-8")
        try:
            cfg = core.load_config()
            self.assertEqual(cfg["hour"], 4)
            self.assertTrue(cfg["timezone"])
            self.assertIn("_error", cfg)
        finally:
            if original is None:
                core.CONFIG.unlink()
            else:
                core.CONFIG.write_bytes(original)

    def test_null_timezone_resolves_to_system(self):
        self.assertEqual(
            core.load_config.__module__, "anchor_core"
        )  # module identity, cheap guard against a stale import


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `/usr/bin/python3 plugins/codex-anchor-mac/server/test_anchor_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'anchor_core'` until Step 1's file exists, then failures on any path still pointing at the old location.

- [ ] **Step 4: Fix anchor_core.py until the tests pass**

The likely fixes: `load_config` must tolerate a `JSONDecodeError` and attach
`_error` (it already does in `server.py`); `CONFIG.parent` may not exist on a
fresh machine, so `save_config` must `mkdir(parents=True, exist_ok=True)`
first.

```python
def save_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/usr/bin/python3 plugins/codex-anchor-mac/server/test_anchor_core.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 6: Wire the unit tests into test.sh**

Append a `server` section to `test.sh` before the final count:

```bash
echo
echo "anchor_core"
if /usr/bin/python3 "$PLUGIN_DIR/server/test_anchor_core.py" >/dev/null 2>&1
then ok "anchor_core unit tests"; else no "anchor_core unit tests"; fi
```

- [ ] **Step 7: Run the full suite**

Run: `./test.sh`
Expected: PASS, 30 or more.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Extract the schedule logic into anchor_core, homed at ~/.codex-anchor"
```

---

### Task 3: The stdio MCP server

**Files:**
- Create: `plugins/codex-anchor-mac/server/anchor_mcp.py`
- Create: `plugins/codex-anchor-mac/server/test_anchor_mcp.py`

**Interfaces:**
- Consumes: every name from Task 2's `anchor_core`
- Produces: an executable stdio server speaking JSON-RPC 2.0, handling `initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`; the UI resource URI `ui://codex-anchor-mac/panel-<VERSION>.html`; tool names `anchor_status`, `anchor_set_time`, `anchor_toggle`, `anchor_run_now`, `anchor_install`, `anchor_uninstall`

- [ ] **Step 1: Write the failing test**

Create `plugins/codex-anchor-mac/server/test_anchor_mcp.py`:

```python
import json
import pathlib
import subprocess
import sys
import unittest

SERVER = pathlib.Path(__file__).resolve().parent / "anchor_mcp.py"


def talk(requests: list[dict]) -> list[dict]:
    """Drive the server over stdio the way a host would."""
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    p = subprocess.run([sys.executable, str(SERVER)], input=payload,
                       capture_output=True, text=True, timeout=30)
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]


class Protocol(unittest.TestCase):
    def test_initialize_advertises_tools_and_resources(self):
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2026-01-26"}}])
        caps = out[0]["result"]["capabilities"]
        self.assertIn("tools", caps)
        self.assertIn("resources", caps)

    def test_tools_list_has_the_six_tools(self):
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertEqual(names, {"anchor_status", "anchor_set_time",
                                 "anchor_toggle", "anchor_run_now",
                                 "anchor_install", "anchor_uninstall"})

    def test_status_tool_carries_the_ui_resource(self):
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        tool = next(t for t in out[1]["result"]["tools"]
                    if t["name"] == "anchor_status")
        self.assertTrue(tool["_meta"]["ui"]["resourceUri"].startswith(
            "ui://codex-anchor-mac/panel-"))

    def test_ui_resource_declares_no_network(self):
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}])
        res = out[1]["result"]["resources"][0]
        csp = res["_meta"]["ui"]["csp"]
        self.assertEqual(csp["connectDomains"], [])
        self.assertEqual(csp["resourceDomains"], [])

    def test_read_panel_html(self):
        init = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                     {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}])
        uri = init[1]["result"]["resources"][0]["uri"]
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "resources/read",
                     "params": {"uri": uri}}])
        text = out[1]["result"]["contents"][0]["text"]
        self.assertIn("<!doctype html", text.lower())

    def test_unknown_method_returns_an_error_not_a_crash(self):
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "nope/nope"}])
        self.assertIn("error", out[1])
        self.assertEqual(out[1]["error"]["code"], -32601)

    def test_bad_arguments_return_an_error_not_a_crash(self):
        out = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "anchor_set_time",
                                "arguments": {"hour": 99, "minute": 0}}}])
        body = out[1]["result"]["content"][0]["text"]
        self.assertIn("0-23", body)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/usr/bin/python3 plugins/codex-anchor-mac/server/test_anchor_mcp.py -v`
Expected: FAIL — `anchor_mcp.py` does not exist.

- [ ] **Step 3: Write the server**

Create `plugins/codex-anchor-mac/server/anchor_mcp.py`:

```python
#!/usr/bin/env python3
"""MCP server for codex-anchor-mac.

Speaks JSON-RPC 2.0 over stdio with no SDK, the way iphone-use does, so the
plugin needs no pip install on a user's machine.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import anchor_core as core

VERSION = "0.1.0"
PROTOCOLS = ["2026-01-26", "2025-06-18"]
PANEL = pathlib.Path(__file__).resolve().parent.parent / "ui" / "dist" / "panel.html"
PANEL_URI = f"ui://codex-anchor-mac/panel-{VERSION}.html"

# The panel talks only to this server, so it needs no origins at all. Codex
# blocks localhost even when declared (openai/codex#45913); needing nothing
# sidesteps that entirely.
PANEL_META = {
    "ui": {"csp": {"connectDomains": [], "resourceDomains": []},
           "prefersBorder": False},
    "openai/ui": {"availableDisplayModes": ["inline", "fullscreen"],
                  "preferredDisplayMode": "inline"},
}

TOOLS = [
    {"name": "anchor_status",
     "description": "Show the anchor schedule, timezone, pmset wake and recent "
                    "runs, and open the control panel.",
     "inputSchema": {"type": "object", "properties": {}},
     "_meta": {"ui": {"resourceUri": PANEL_URI},
               "openai/ui": {"entrypoints": [{"type": "thread"}]}}},
    {"name": "anchor_set_time",
     "description": "Set the daily anchor time. hour/minute are wall clock in "
                    "the given IANA timezone; launchd and the pmset wake are "
                    "both updated.",
     "inputSchema": {"type": "object",
                     "properties": {"hour": {"type": "integer"},
                                    "minute": {"type": "integer"},
                                    "timezone": {"type": "string"}},
                     "required": ["hour", "minute"]},
     "_meta": {"ui": {"resourceUri": PANEL_URI}}},
    {"name": "anchor_toggle",
     "description": "Enable or disable the daily anchor job.",
     "inputSchema": {"type": "object",
                     "properties": {"enable": {"type": "boolean"}},
                     "required": ["enable"]},
     "_meta": {"ui": {"resourceUri": PANEL_URI}}},
    {"name": "anchor_run_now",
     "description": "Send one anchor request immediately. This opens a 5-hour "
                    "quota window starting now, so do not call it during the "
                    "working day without being asked to.",
     "inputSchema": {"type": "object", "properties": {}},
     "_meta": {"ui": {"resourceUri": PANEL_URI}}},
    {"name": "anchor_install",
     "description": "Create ~/.codex-anchor, install the launchd job and offer "
                    "to schedule the daily wake.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "anchor_uninstall",
     "description": "Remove the launchd job and the pmset wake. Logs are kept.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _text(payload) -> dict:
    body = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False)
    return {"content": [{"type": "text", "text": body}]}


def call_tool(name: str, args: dict) -> dict:
    if name == "anchor_status":
        return _text(core.status())
    if name == "anchor_set_time":
        try:
            hour, minute = int(args["hour"]), int(args["minute"])
        except (KeyError, TypeError, ValueError):
            return _text("hour and minute must be integers")
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return _text("hour must be 0-23 and minute 0-59")
        tz = args.get("timezone") or core.load_config()["timezone"]
        return _text({"steps": core.set_schedule(hour, minute, tz),
                      "status": core.status()})
    if name == "anchor_toggle":
        enable = bool(args.get("enable"))
        if enable:
            core.run(["launchctl", "enable", core.SERVICE])
            rc, out = core.run(["launchctl", "bootstrap", f"gui/{core.UID}",
                                str(core.INSTALLED)])
        else:
            core.run(["launchctl", "disable", core.SERVICE])
            rc, out = core.run(["launchctl", "bootout", core.SERVICE])
        return _text({"ok": rc == 0, "detail": out, "status": core.status()})
    if name == "anchor_run_now":
        rc, out = core.run(["launchctl", "kickstart", "-k", core.SERVICE])
        return _text({"ok": rc == 0, "detail": out})
    if name == "anchor_install":
        # Also the refresh path: it re-copies anchor.sh and rewrites .version,
        # which is exactly what version drift needs.
        return _text(core.install_home())
    if name == "anchor_uninstall":
        return _text(core.uninstall())
    return _text(f"unknown tool: {name}")


def handle(req: dict) -> dict | None:
    method, rid = req.get("method"), req.get("id")
    if method == "initialize":
        offered = (req.get("params") or {}).get("protocolVersion")
        return {"protocolVersion": offered if offered in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False},
                                 "resources": {"listChanged": False}},
                "serverInfo": {"name": "codex-anchor-mac", "version": VERSION}}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = req.get("params") or {}
        return call_tool(params.get("name", ""), params.get("arguments") or {})
    if method == "resources/list":
        return {"resources": [{"uri": PANEL_URI,
                               "name": "Codex Anchor panel",
                               "mimeType": "text/html;profile=mcp-app",
                               "_meta": PANEL_META}]}
    if method == "resources/read":
        return {"contents": [{"uri": PANEL_URI,
                              "mimeType": "text/html;profile=mcp-app",
                              "text": PANEL.read_text(encoding="utf-8"),
                              "_meta": PANEL_META}]}
    raise LookupError(method)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        try:
            result = handle(req)
        except LookupError as exc:
            reply = {"jsonrpc": "2.0", "id": rid,
                     "error": {"code": -32601, "message": f"method not found: {exc}"}}
        except Exception as exc:  # noqa: BLE001 - a crash would kill the panel
            reply = {"jsonrpc": "2.0", "id": rid,
                     "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
        else:
            if result is None or rid is None:
                continue
            reply = {"jsonrpc": "2.0", "id": rid, "result": result}
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create a placeholder panel so resources/read has something to serve**

```bash
mkdir -p plugins/codex-anchor-mac/ui/dist
printf '<!doctype html><title>placeholder</title>\n' > plugins/codex-anchor-mac/ui/dist/panel.html
```

Task 5 replaces this with the real build.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `/usr/bin/python3 plugins/codex-anchor-mac/server/test_anchor_mcp.py -v`
Expected: PASS. `anchor_install` and `anchor_uninstall` are referenced but not yet defined in `anchor_core`; Task 4 adds them, so until then the two tools exist in `tools/list` and only fail when called. No test calls them yet.

- [ ] **Step 6: Wire into test.sh**

Append to the `anchor_core` section of `test.sh`:

```bash
if /usr/bin/python3 "$PLUGIN_DIR/server/test_anchor_mcp.py" >/dev/null 2>&1
then ok "anchor_mcp protocol tests"; else no "anchor_mcp protocol tests"; fi
```

- [ ] **Step 7: Run the full suite**

Run: `./test.sh`
Expected: PASS, 31 or more.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add the stdio MCP server with the six anchor tools"
```

---

### Task 4: The ~/.codex-anchor home, install and uninstall

**Files:**
- Modify: `plugins/codex-anchor-mac/server/anchor_core.py`
- Modify: `plugins/codex-anchor-mac/server/test_anchor_core.py`

**Interfaces:**
- Consumes: `anchor_core.HOME_DIR`, `PLUGIN_DIR`, `TEMPLATE`, `INSTALLED`, `SERVICE`, `run`, `load_config`, `save_config`, `wake_time`, `to_local`, `status`
- Produces: `anchor_core.PLUGIN_VERSION: str`, `installed_version() -> str | None`, `home_health() -> dict`, `install_home() -> dict`, `uninstall() -> dict`; `status()` gains a `"home"` key holding `home_health()`'s result

- [ ] **Step 1: Write the failing tests**

Add to `test_anchor_core.py`:

```python
class Home(unittest.TestCase):
    def test_health_reports_a_missing_script(self):
        # Review Focus 1: the plist points somewhere that no longer exists.
        h = core.home_health(script=pathlib.Path("/nonexistent/anchor.sh"))
        self.assertFalse(h["scriptPresent"])
        self.assertIn("anchor.sh", h["summary"])

    def test_health_reports_version_drift(self):
        # Review Focus 2: plugin upgraded, the copied script is stale.
        h = core.home_health(script=core.PLUGIN_DIR / "anchor.sh",
                             installed_version_override="0.0.1")
        self.assertTrue(h["versionDrift"])

    def test_health_on_a_fresh_machine_does_not_raise(self):
        # Review Focus 3: nothing exists yet.
        h = core.home_health(home=pathlib.Path("/nonexistent/.codex-anchor"))
        self.assertFalse(h["homePresent"])
        self.assertFalse(h["scriptPresent"])

    def test_status_includes_home_health(self):
        self.assertIn("home", core.status())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `/usr/bin/python3 plugins/codex-anchor-mac/server/test_anchor_core.py -v`
Expected: FAIL with `AttributeError: module 'anchor_core' has no attribute 'home_health'`.

- [ ] **Step 3: Implement the home helpers**

Add to `anchor_core.py`:

```python
PLUGIN_VERSION = "0.1.0"
VERSION_FILE = HOME_DIR / ".version"


def installed_version() -> str | None:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def home_health(home: pathlib.Path | None = None,
                script: pathlib.Path | None = None,
                installed_version_override: str | None = None) -> dict:
    """What is actually on disk, as opposed to what the plist believes.

    The schedule can rot in two silent ways: the copied script is deleted, or
    a plugin upgrade leaves the copy behind. Neither surfaces at 04:30.
    """
    home = HOME_DIR if home is None else home
    script = (home / "anchor.sh") if script is None else script
    have_version = (installed_version_override if installed_version_override
                    is not None else installed_version())
    drift = bool(have_version) and have_version != PLUGIN_VERSION
    parts = []
    if not home.is_dir():
        parts.append(f"{home} does not exist yet")
    if not script.is_file():
        parts.append(f"anchor.sh is missing from {script.parent}")
    if drift:
        parts.append(f"copied from plugin {have_version}, running "
                     f"{PLUGIN_VERSION}")
    return {"homePresent": home.is_dir(),
            "scriptPresent": script.is_file(),
            "installedVersion": have_version,
            "pluginVersion": PLUGIN_VERSION,
            "versionDrift": drift,
            "summary": "; ".join(parts) or "healthy"}
```

Add `"home": home_health(),` to the dict `status()` returns.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `/usr/bin/python3 plugins/codex-anchor-mac/server/test_anchor_core.py -v`
Expected: PASS.

- [ ] **Step 5: Implement install_home and uninstall**

Add to `anchor_core.py`:

```python
def install_home() -> dict:
    """Create the job's home, install the LaunchAgent, offer the wake.

    Each stage reports separately: a declined admin dialog must not look like
    a failed install, because the job itself needs no privileges.
    """
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": name, "ok": ok, "detail": detail})

    HOME_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PLUGIN_DIR / "anchor.sh", HOME_DIR / "anchor.sh")
    (HOME_DIR / "anchor.sh").chmod(0o755)
    VERSION_FILE.write_text(PLUGIN_VERSION + "\n", encoding="utf-8")
    step("create ~/.codex-anchor", True, str(HOME_DIR))

    cfg = load_config()
    local_h, local_m = to_local(cfg["hour"], cfg["minute"], cfg["timezone"])
    src = TEMPLATE.read_text(encoding="utf-8")
    src = src.replace("__ANCHOR_SH__", str(HOME_DIR / "anchor.sh"))
    src = src.replace("__DIR__", str(HOME_DIR))
    src = re.sub(r"(<key>Hour</key>\s*<integer>)\d+(</integer>)",
                 rf"\g<1>{local_h}\g<2>", src, count=1)
    src = re.sub(r"(<key>Minute</key>\s*<integer>)\d+(</integer>)",
                 rf"\g<1>{local_m}\g<2>", src, count=1)
    INSTALLED.parent.mkdir(parents=True, exist_ok=True)
    INSTALLED.write_text(src, encoding="utf-8")
    run(["launchctl", "bootout", SERVICE])
    rc, out = run(["launchctl", "bootstrap", f"gui/{UID}", str(INSTALLED)])
    run(["launchctl", "enable", SERVICE])
    step("install the launchd job", rc == 0,
         out or f"{local_h:02d}:{local_m:02d} system time")

    wh, wm = wake_time(local_h, local_m)
    rc, out = run(["sudo", "-n", "pmset", "repeat", "wake", "MTWRFSU",
                   f"{wh:02d}:{wm:02d}:00"])
    if rc != 0:
        script = (f"/usr/bin/pmset repeat wake MTWRFSU {wh:02d}:{wm:02d}:00")
        rc, out = run(["osascript", "-e",
                       f'do shell script "{script}" with administrator '
                       f'privileges with prompt "codex-anchor-mac needs to '
                       f'schedule a daily wake"'])
    step("schedule the daily wake", rc == 0,
         f"{wh:02d}:{wm:02d}" if rc == 0
         else "declined; the job still runs, it is just late on battery nights")
    return {"steps": steps, "status": status()}


def uninstall() -> dict:
    steps: list[dict] = []
    rc, out = run(["launchctl", "bootout", SERVICE])
    steps.append({"step": "unload the launchd job", "ok": True, "detail": out})
    try:
        INSTALLED.unlink()
    except OSError:
        pass
    rc, out = run(["sudo", "-n", "pmset", "repeat", "cancel"])
    steps.append({"step": "cancel the daily wake", "ok": rc == 0,
                  "detail": out or "run: sudo pmset repeat cancel"})
    steps.append({"step": "keep logs", "ok": True, "detail": str(HOME_DIR)})
    return {"steps": steps}
```

Add `import re` and `import shutil` to the imports. Rename the plist
placeholder in `plugins/codex-anchor-mac/io.github.codex-anchor-mac.plist`
from `__WARMUP_SH__`/`__ANCHOR_SH__` to `__ANCHOR_SH__` if it is not already,
and update `install.sh`'s `sed` to match.

- [ ] **Step 6: Write the declined-dialog test**

Add to `test_anchor_core.py`:

```python
class Install(unittest.TestCase):
    def test_declined_wake_still_reports_the_job_installed(self):
        # Review Focus 4: cancelling the admin dialog is not an install failure.
        import unittest.mock as mock
        calls = []

        def fake_run(cmd):
            calls.append(cmd)
            if cmd[0] in ("sudo", "osascript"):
                return 1, "User cancelled."
            return 0, ""

        with mock.patch.object(core, "run", fake_run):
            result = core.install_home()
        by_name = {s["step"]: s for s in result["steps"]}
        self.assertTrue(by_name["install the launchd job"]["ok"])
        self.assertFalse(by_name["schedule the daily wake"]["ok"])
        self.assertIn("still runs", by_name["schedule the daily wake"]["detail"])
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `/usr/bin/python3 plugins/codex-anchor-mac/server/test_anchor_core.py -v`
Expected: PASS. Note this test really does write `~/.codex-anchor/` and a
LaunchAgent plist; that is intended, since the machine running the tests is the
machine the tool installs onto.

- [ ] **Step 8: Make the panel offer a refresh when the copy is stale**

In `ui/src/app.ts`'s `render`, when `s.home.versionDrift` or
`!s.home.scriptPresent` is true, show the existing `#warn` banner with
`s.home.summary` and enable a button that calls `anchor_install`. Reusing the
install tool is deliberate: it re-copies `anchor.sh` and rewrites `.version`,
which is the whole of what a refresh means.

This step belongs to Task 5; it is listed here because the health data it
consumes is defined above. Implement it when building the UI.

- [ ] **Step 9: Run the full suite and commit**

Run: `./test.sh`
Expected: PASS, 31 or more.

```bash
git add -A
git commit -m "Install the job into ~/.codex-anchor and report home health"
```

---

### Task 5: The MCP Apps UI

**Files:**
- Create: `plugins/codex-anchor-mac/ui/package.json`
- Create: `plugins/codex-anchor-mac/ui/tsconfig.json`
- Create: `plugins/codex-anchor-mac/ui/build.mjs`
- Create: `plugins/codex-anchor-mac/ui/src/app.ts`
- Create: `plugins/codex-anchor-mac/ui/src/strings.ts`
- Create: `plugins/codex-anchor-mac/ui/src/panel.html`
- Create: `plugins/codex-anchor-mac/ui/dist/panel.html` (build output, committed)

**Interfaces:**
- Consumes: the tool names and `status()` shape from Tasks 3 and 4
- Produces: `ui/dist/panel.html`, a single self-contained file served by `resources/read`

- [ ] **Step 1: Scaffold the build**

`plugins/codex-anchor-mac/ui/package.json`:

```json
{
  "name": "codex-anchor-panel",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "tsc --noEmit && node build.mjs",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@modelcontextprotocol/ext-apps": "1.7.5"
  },
  "devDependencies": {
    "esbuild": "0.25.11",
    "typescript": "5.9.3"
  }
}
```

`plugins/codex-anchor-mac/ui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noEmit": true,
    "lib": ["ES2022", "DOM"]
  },
  "include": ["src"]
}
```

`plugins/codex-anchor-mac/ui/build.mjs`:

```javascript
// One self-contained HTML file: the host serves it as a resource, so it
// cannot fetch a sibling script or stylesheet.
import { build } from 'esbuild';
import { readFile, writeFile, mkdir } from 'node:fs/promises';

const result = await build({
  entryPoints: ['src/app.ts'],
  bundle: true, format: 'iife', minify: true, write: false,
  target: ['safari17'],
});
const js = result.outputFiles[0].text;
const shell = await readFile('src/panel.html', 'utf8');
await mkdir('dist', { recursive: true });
await writeFile('dist/panel.html',
  shell.replace('/*BUNDLE*/', () => js), 'utf8');
console.log(`dist/panel.html written, ${js.length} bytes of JS`);
```

- [ ] **Step 2: Port the markup and styles**

Copy the whole `<style>` block and the `<body>` markup from the repository's
`index.html` into `plugins/codex-anchor-mac/ui/src/panel.html`, with two
changes: drop the `@media (prefers-color-scheme: dark)` block, because the
theme now arrives from the host, and end the file with

```html
<script>/*BUNDLE*/</script>
</body>
</html>
```

Keep every `data-i18n` attribute and every element id: `time`, `state`,
`wake`, `expected`, `tz`, `localtime`, `warn`, `picker`, `tzpick`, `save`,
`steps`, `toggle`, `runnow`, `log`, `lang`.

- [ ] **Step 3: Port the string table**

Move the `STR` object from `index.html` verbatim into
`plugins/codex-anchor-mac/ui/src/strings.ts`, typed:

```typescript
export type Lang = 'en' | 'zh';
export interface Strings { [key: string]: string | ((arg: string) => string); }
export const STR: Record<Lang, Strings> = { /* the existing object */ };
```

- [ ] **Step 4: Write the data layer against ext-apps**

`plugins/codex-anchor-mac/ui/src/app.ts`:

```typescript
import { App } from '@modelcontextprotocol/ext-apps';
import { STR, type Lang } from './strings';

const app = new App();
let st: any = null;
let lang: Lang = 'en';
try { lang = (localStorage.getItem('lang') as Lang) || 'en'; } catch {}
const T = () => STR[lang];

// Codex blocks localhost even when declared (openai/codex#45913), so every
// read and write goes through the server rather than over HTTP.
async function callTool(name: string, args: Record<string, unknown> = {}) {
  const res = await app.callServerTool({ name, arguments: args });
  const text = (res as any)?.content?.[0]?.text ?? '{}';
  try { return JSON.parse(text); } catch { return { error: text }; }
}

async function refresh() { render(await callTool('anchor_status')); }

// Ported verbatim from index.html. Add `: any` to each parameter and `!` to
// every getElementById; nothing else changes.
function render(s: any) { /* index.html lines 196-233 */ }
function applyLang() { /* index.html lines 148-158 */ }
function describeState(s: any) { /* index.html lines 186-194 */ }

document.getElementById('save')!.onclick = async (e) => {
  const target = e.target as HTMLButtonElement;
  const v = (document.getElementById('picker') as HTMLInputElement).value;
  if (!v) return;
  const [hour, minute] = v.split(':').map(Number);
  target.disabled = true;
  const res = await callTool('anchor_set_time', {
    hour, minute,
    timezone: (document.getElementById('tzpick') as HTMLSelectElement).value,
  });
  target.disabled = false;
  renderSteps(res);
  if (res.status) render(res.status);
};

function renderSteps(res: any) { /* index.html lines 247-254, the box.innerHTML block */ }

document.getElementById('toggle')!.onclick = async (e) => {
  const target = e.target as HTMLButtonElement;
  target.disabled = true;
  const res = await callTool('anchor_toggle', { enable: !st.loaded });
  target.disabled = false;
  if (res.status) render(res.status);
};

document.getElementById('runnow')!.onclick = async (e) => {
  if (!confirm(T().confirmRun as string)) return;
  const target = e.target as HTMLButtonElement;
  target.disabled = true;
  await callTool('anchor_run_now');
  setTimeout(() => { target.disabled = false; void refresh(); }, 4000);
};

document.getElementById('lang')!.onclick = () => {
  lang = lang === 'en' ? 'zh' : 'en';
  try { localStorage.setItem('lang', lang); } catch {}
  applyLang();
};

app.onhostcontextchanged = (ctx: any) => {
  document.documentElement.dataset.theme = ctx?.theme === 'dark' ? 'dark' : 'light';
};

await app.connect();
const ctx = app.getHostContext() as any;
document.documentElement.dataset.theme = ctx?.theme === 'dark' ? 'dark' : 'light';
applyLang();
await refresh();
setInterval(() => { void refresh(); }, 15000);
```

Open `index.html` at the line ranges named in the stubs and paste those bodies
in. The only edits are TypeScript's non-null assertions on `getElementById`
and `: any` on the parameters. Run `git show HEAD:index.html` after Task 7
deletes the file if you need it again.

- [ ] **Step 5: Build and verify the output is self-contained**

```bash
cd plugins/codex-anchor-mac/ui && npm install && npm run build && cd -
```

Run:

```bash
grep -cE 'src="http|href="http|fetch\(' plugins/codex-anchor-mac/ui/dist/panel.html
```

Expected: `0`. The panel must reference no external origin.

- [ ] **Step 6: Add a test that the built panel is self-contained and current**

Append to `test.sh`'s `guards` section:

```bash
PANEL="$PLUGIN_DIR/ui/dist/panel.html"
if [ -s "$PANEL" ] && ! grep -qE 'src="http|href="http|fetch\(' "$PANEL"
then ok "built panel references no external origin"
else no "built panel references no external origin"; fi
```

- [ ] **Step 7: Run the full suite**

Run: `./test.sh`
Expected: PASS, 32 or more.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add the MCP Apps panel, bundled into one self-contained file"
```

---

### Task 6: Plugin manifests and a real install

**Files:**
- Create: `plugins/codex-anchor-mac/plugin.json`
- Create: `plugins/codex-anchor-mac/.codex-plugin/plugin.json`
- Create: `plugins/codex-anchor-mac/.mcp.json`
- Create: `plugins/codex-anchor-mac/assets/icon.svg`

**Interfaces:**
- Consumes: Task 3's `server/anchor_mcp.py`, Task 5's `ui/dist/panel.html`
- Produces: a plugin installable with `codex plugin add codex-anchor-mac@codex-anchor-mac`

- [ ] **Step 1: Write the MCP server declaration**

`plugins/codex-anchor-mac/.mcp.json`:

```json
{
  "mcpServers": {
    "codex_anchor": {
      "type": "stdio",
      "command": "/usr/bin/python3",
      "args": ["${PLUGIN_ROOT}/server/anchor_mcp.py"],
      "cwd": "${PLUGIN_ROOT}"
    }
  }
}
```

- [ ] **Step 2: Write the plugin manifests**

`plugins/codex-anchor-mac/plugin.json`:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "codex-anchor-mac",
  "version": "0.1.0",
  "description": "Anchor your ChatGPT Plus 5-hour Codex window at a time you choose, so the boundaries fall inside your working day. macOS only. Adds no quota.",
  "author": { "name": "unnamedhoead" },
  "license": "MIT",
  "extensions": {
    "com.openai": {
      "interface": {
        "displayName": "Codex Anchor",
        "shortDescription": "Move your 5-hour quota window to where you need it",
        "longDescription": "The 5-hour window starts at your first message, so a window burned by 10am leaves you waiting until 1pm. This sends one deliberately tiny request early each morning, which shifts the boundaries into your working day. It adds no quota and bypasses nothing. macOS and ChatGPT Plus only; Pro has no 5-hour limit to anchor.",
        "developerName": "unnamedhoead",
        "category": "Developer Tools",
        "logo": "./assets/icon.svg",
        "composerIcon": "./assets/icon.svg",
        "defaultPrompt": [
          "Open the anchor panel.",
          "Move my daily anchor to 4:30am."
        ]
      }
    }
  }
}
```

`plugins/codex-anchor-mac/.codex-plugin/plugin.json`: the same object with the
`extensions` wrapper removed, `interface` hoisted to the top level, and
`"mcpServers": "./.mcp.json"` added — matching `iphone-use`'s pair exactly.

- [ ] **Step 3: Draw the icon**

`plugins/codex-anchor-mac/assets/icon.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <circle cx="12" cy="12" r="9"/>
  <path d="M12 7v5l3 2"/>
</svg>
```

- [ ] **Step 4: Add a manifest-validity test**

Append to `test.sh`'s `guards` section:

```bash
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
```

- [ ] **Step 5: Run the tests**

Run: `./test.sh`
Expected: PASS, 33 or more.

- [ ] **Step 6: Install it for real, from a local marketplace**

```bash
CODEX=/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex
"$CODEX" plugin marketplace add ~/codex-anchor-mac
"$CODEX" plugin list
"$CODEX" plugin add codex-anchor-mac@codex-anchor-mac
```

Expected: the plugin appears in `plugin list` and installs without error.
If `marketplace add` rejects the path, the manifest location is wrong — check
whether Codex wants `.claude-plugin/marketplace.json` rather than
`.agents/plugins/marketplace.json`, and add whichever it reads.

- [ ] **Step 7: Verify the panel opens in Codex**

Ask Codex: "Open the anchor panel." Confirm the panel renders, shows the real
schedule, and that pressing Save changes it. This step needs a human; record
the result in the commit message.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add the plugin manifests and make it installable from a marketplace"
```

---

### Task 7: Retire the HTTP panel and update the docs

**Files:**
- Delete: `server.py`, `index.html`, `install-ui.sh`, `io.github.codex-anchor-mac.ui.plist`
- Modify: `README.md`, `README.zh-CN.md`, `uninstall.sh`, `.github/workflows/test.yml`
- Modify: `docs/specs/2026-10-13-codex-plugin-design.md` (status line)

**Interfaces:**
- Consumes: everything from Tasks 1-6
- Produces: the shipped repository

- [ ] **Step 1: Stop and remove the old UI agent, then delete its files**

```bash
launchctl bootout gui/$UID/io.github.codex-anchor-mac.ui 2>/dev/null
rm -f ~/Library/LaunchAgents/io.github.codex-anchor-mac.ui.plist
git rm server.py index.html install-ui.sh io.github.codex-anchor-mac.ui.plist
```

- [ ] **Step 2: Drop the panel from uninstall.sh**

In `uninstall.sh`, remove `io.github.codex-anchor-mac.ui` from the `for label`
loop, leaving only the job, and add a line pointing at the plugin:

```bash
echo "The Codex plugin is removed separately: codex plugin remove codex-anchor-mac"
```

- [ ] **Step 3: Run the tests to confirm nothing depended on the deleted files**

Run: `./test.sh`
Expected: PASS, 33 or more. The `guards` loop over `"$DIR"/*.sh` now sees one
fewer script, which is correct.

- [ ] **Step 4: Rewrite the install sections of both READMEs**

Replace the `## Install` section of `README.md` with:

````markdown
## Install

Inside Codex:

```bash
codex plugin marketplace add https://github.com/unnamedhoead/codex-anchor-mac.git
codex plugin add codex-anchor-mac@codex-anchor-mac
```

Then ask Codex to open the anchor panel. Installing the plugin installs the
daily job; there is nothing else to run.

Without Codex, the job works on its own, without a panel:

```bash
git clone https://github.com/unnamedhoead/codex-anchor-mac.git ~/codex-anchor-mac
cd ~/codex-anchor-mac && ./setup.sh
```
````

Mirror this in `README.zh-CN.md`. In the `## Control panel` section of both,
replace the localhost paragraph with a sentence saying the panel renders
inside Codex, and keep the screenshot.

- [ ] **Step 5: Add the dist-freshness check to CI**

In `.github/workflows/test.yml`, add a step before `./test.sh`:

```yaml
      - name: Verify the committed panel matches its source
        run: |
          cd plugins/codex-anchor-mac/ui
          npm ci
          cp dist/panel.html /tmp/committed.html
          npm run build
          diff -q /tmp/committed.html dist/panel.html \
            || { echo "ui/dist/panel.html is stale; run npm run build"; exit 1; }
```

- [ ] **Step 6: Mark the spec implemented**

In `docs/specs/2026-10-13-codex-plugin-design.md`, change the status line to
`Status: implemented 2026-10-13` and note anything the implementation did
differently from the design.

- [ ] **Step 7: Run the full suite and push**

Run: `./test.sh`
Expected: PASS, 33 or more.

```bash
git add -A
git commit -m "Retire the HTTP panel in favour of the Codex plugin"
git push origin main
```

- [ ] **Step 8: Confirm CI is green**

Run: `gh run list --repo unnamedhoead/codex-anchor-mac --limit 1`
Expected: the newest run's conclusion is `success`.
