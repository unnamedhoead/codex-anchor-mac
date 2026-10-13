#!/usr/bin/env python3
"""Register this plugin's MCP server with Codex.

Codex installs the plugin and marks it enabled, but it does not read mcp.json
and start the server: config.toml gets a [plugins."..."] entry and no
[mcp_servers.*] one, so the tools never reach a session. iphone-use solves
this the same way, with its own registration step.

The cache path carries the version, so a registration made for 0.1.0 points
at a directory that an upgrade replaces. Re-run this after upgrading; it
retires its own previous entry first.

    python3 register_mcp.py            register the newest installed version
    ANCHOR_REGISTER_DRY_RUN=1 ...      print the commands without running them
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

SERVER_NAME = "codex_anchor"
DRY_RUN = os.environ.get("ANCHOR_REGISTER_DRY_RUN") == "1"


def codex_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CODEX_HOME", str(pathlib.Path.home() / ".codex")))


def _version_key(path: pathlib.Path) -> tuple:
    """Sort 0.10.0 above 0.9.0, which a plain string sort gets backwards."""
    parts = re.findall(r"\d+", path.name)
    return tuple(int(n) for n in parts) if parts else (0,)


def newest_install() -> pathlib.Path | None:
    root = codex_home() / "plugins" / "cache"
    candidates = [d for d in root.glob("*/codex-anchor-mac/*")
                  if (d / "server" / "anchor_mcp.py").is_file()]
    return max(candidates, key=_version_key) if candidates else None


def run(cmd: list[str]) -> int:
    print("  " + " ".join(cmd))
    if DRY_RUN:
        return 0
    return subprocess.run(cmd, capture_output=True, text=True).returncode


def main() -> int:
    plugin = newest_install()
    if plugin is None:
        print("codex-anchor-mac is not installed. Install it first:\n"
              "  codex plugin marketplace add "
              "https://github.com/unnamedhoead/codex-anchor-mac.git\n"
              "  codex plugin add codex-anchor-mac@codex-anchor-mac",
              file=sys.stderr)
        return 1

    server = plugin / "server" / "anchor_mcp.py"
    print(f"Registering {SERVER_NAME} -> {server}")

    # Remove first: `mcp add` will not overwrite an existing name, so skipping
    # this makes the whole script a no-op after an upgrade.
    run(["codex", "mcp", "remove", SERVER_NAME])
    rc = run(["codex", "mcp", "add", SERVER_NAME, "--", "/usr/bin/python3", str(server)])
    if rc != 0:
        print("registration failed; is `codex` on your PATH?", file=sys.stderr)
        return rc

    print("\nDone. Open a NEW Codex session -- MCP servers are started when a\n"
          "session begins, so an already-open one will not see it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
