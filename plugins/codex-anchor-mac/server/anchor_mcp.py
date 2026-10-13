#!/usr/bin/env python3
"""MCP server for codex-anchor-mac.

Speaks JSON-RPC 2.0 over stdio with no SDK, so the plugin needs no pip
install on a user's machine.
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
# blocks localhost even when it is declared (openai/codex#45913); needing
# nothing sidesteps that bug entirely rather than working around it.
PANEL_META = {
    "ui": {"csp": {"connectDomains": [], "resourceDomains": []},
           "prefersBorder": False},
    "openai/ui": {"availableDisplayModes": ["inline", "fullscreen"],
                  "preferredDisplayMode": "inline"},
}

_UI = {"ui": {"resourceUri": PANEL_URI}}

TOOLS = [
    {"name": "anchor_status",
     "description": "Show the anchor schedule, timezone, pmset wake and recent "
                    "runs, and open the control panel.",
     "inputSchema": {"type": "object", "properties": {}},
     "_meta": {"ui": {"resourceUri": PANEL_URI},
               "openai/ui": {"entrypoints": [{"type": "thread"}]}}},
    {"name": "anchor_set_time",
     "description": "Set the daily anchor time. hour and minute are wall clock "
                    "in the given IANA timezone; the launchd trigger and the "
                    "pmset wake are both updated.",
     "inputSchema": {"type": "object",
                     "properties": {"hour": {"type": "integer"},
                                    "minute": {"type": "integer"},
                                    "timezone": {"type": "string"}},
                     "required": ["hour", "minute"]},
     "_meta": _UI},
    {"name": "anchor_toggle",
     "description": "Enable or disable the daily anchor job.",
     "inputSchema": {"type": "object",
                     "properties": {"enable": {"type": "boolean"}},
                     "required": ["enable"]},
     "_meta": _UI},
    {"name": "anchor_run_now",
     "description": "Send one anchor request immediately. This opens a 5-hour "
                    "quota window starting now, so do not call it during the "
                    "working day unless asked to.",
     "inputSchema": {"type": "object", "properties": {}},
     "_meta": _UI},
    {"name": "anchor_install",
     "description": "Create ~/.codex-anchor, install the launchd job and offer "
                    "to schedule the daily wake. Also the refresh path after a "
                    "plugin upgrade.",
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
        if args.get("enable"):
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


def handle(req: dict):
    method = req.get("method")
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
                     "error": {"code": -32603,
                               "message": f"{type(exc).__name__}: {exc}"}}
        else:
            if result is None or rid is None:
                continue
            reply = {"jsonrpc": "2.0", "id": rid, "result": result}
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
