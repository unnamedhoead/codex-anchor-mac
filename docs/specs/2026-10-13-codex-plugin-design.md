# Ship the control panel as a Codex plugin

Status: implemented 2026-10-13

What the implementation did differently: the copy range for anchor_core ran to
line 333 rather than 266, because set_schedule sits past the end of status();
install.sh reads the schedule from config.json instead of holding a WAKE_TIME
constant, and installs into ~/.codex-anchor, so the CLI and plugin routes share
one home rather than silently keeping two; and test.sh reports each unittest
case rather than each file, which took the headline count from 28 to 48 without
adding coverage it did not already have.
Date: 2026-10-13

## Intent

Someone with a ChatGPT Plus subscription should be able to install this tool
from inside Codex and see the anchor panel in Codex's own UI, without cloning
a repository, running a shell script, or knowing that a localhost port exists.

Success looks like:

```
codex plugin marketplace add https://github.com/unnamedhoead/codex-anchor-mac.git
codex plugin add codex-anchor-mac@codex-anchor-mac
```

then asking Codex to open the panel, and getting a working panel that can
change the schedule — with the daily job installed as part of that, not as a
separate step.

Non-goals: Windows or Linux support, ChatGPT Pro (no 5-hour window to anchor),
and any change to what the anchor request itself does.

## What the probes established

Two assumptions were tested before committing to this design.

**A sandboxed MCP Apps UI cannot reach localhost in Codex.**
[openai/codex#45913](https://github.com/openai/codex/issues/45913), open since
2026-09-16, reproduces exactly this: a UI resource that declares
`http://127.0.0.1:<port>` in `_meta.ui.csp` still has its `fetch` and `<img>`
blocked. The MCP Apps spec says the declaration should work; Codex's
implementation does not honour it yet.

This rules out keeping `server.py` and pointing the plugin UI at it. The UI
must reach its backend through `callServerTool`, which means the MCP server
becomes the only backend and the HTTP server goes away.

**An MCP server can spawn privileged helpers.** `iphone_use.py:241` spawns
`/usr/bin/osascript` from inside its stdio MCP server, so MCP servers are not
sandboxed away from system binaries. `osascript … with administrator
privileges` is the same binary with different arguments, and it already works
from this machine's shell.

Not fully verified: the admin dialog has not been exercised from inside a real
Codex MCP context. If it fails, only the `pmset` wake is affected; the launchd
job needs no privileges at all, so the fallback is to print the one command for
the user to run.

## Architecture

The repository becomes its own marketplace containing one plugin. A git
marketplace needs a manifest and the plugin committed in a subdirectory —
`iPhone-use` appears to need neither only because it registers as a *local*
marketplace whose `dist/` is gitignored, which cannot be distributed over git
at all.

```
codex-anchor-mac/
├── .agents/plugins/marketplace.json   NEW  marketplace manifest
├── plugins/codex-anchor-mac/          NEW  the plugin, committed
│   ├── plugin.json                         metadata + interface
│   ├── .codex-plugin/plugin.json           points at .mcp.json
│   ├── .mcp.json                           one stdio MCP server
│   ├── server/anchor_mcp.py                JSON-RPC over stdio, stdlib only
│   ├── anchor.sh                           moved here; the canonical copy
│   ├── io.github.codex-anchor-mac.plist    moved here
│   └── ui/
│       ├── src/app.ts                      @modelcontextprotocol/ext-apps
│       ├── build.mjs                       esbuild → one HTML file
│       └── dist/panel.html                 committed build output
├── setup.sh, test.sh, README*         stay at the root, call into plugins/
├── docs/
└── REMOVED: server.py, index.html, install-ui.sh, the UI LaunchAgent
```

The operational files move into the plugin directory rather than being
duplicated. `setup.sh` at the root keeps working for people who do not use
Codex; it just installs from `plugins/codex-anchor-mac/` instead of from `.`.

The marketplace manifest describes the plugin as a subdirectory of this same
repository:

```json
{
  "name": "codex-anchor-mac",
  "interface": { "displayName": "Codex Anchor" },
  "plugins": [{
    "name": "codex-anchor-mac",
    "category": "Developer Tools",
    "source": {
      "source": "git-subdir",
      "url": "https://github.com/unnamedhoead/codex-anchor-mac.git",
      "path": "plugins/codex-anchor-mac",
      "ref": "main"
    },
    "policy": { "installation": "AVAILABLE" }
  }]
}
```

`git-subdir` is used rather than a relative `local` path because every
verified git marketplace uses it; relative paths appear only in local
marketplaces.

`server.py`'s logic is not rewritten, it is moved: `to_local`,
`timezone_choices`, `wake_time`, `set_schedule`, `last_run`, `system_timezone`
and `agent_state` carry over unchanged. Only the transport differs — JSON-RPC
over stdio instead of HTTP.

## The version-path problem

Codex caches plugins at `cache/<marketplace>/<plugin>/<version>/`. The path
contains the version, so it changes on every upgrade. A LaunchAgent pointing
into the plugin cache would break each time the plugin updated, silently, at
04:30.

The job therefore lives outside the plugin:

```
~/.codex-anchor/
├── anchor.sh      copied from the plugin on install
├── config.json    schedule and timezone
├── anchor.log
└── .version       which plugin version wrote this copy
```

The LaunchAgent points at `~/.codex-anchor/anchor.sh`. On every
`anchor_status`, the server compares `.version` against its own and reports a
mismatch so the panel can offer to refresh the copy. An upgrade that nobody
accepts leaves a working, if older, job rather than a broken one.

This also settles uninstall: the job's home is not the plugin's, so
`codex plugin remove` takes away the panel and leaves the anchor running. The
panel documents `anchor_uninstall` as the way to remove the job itself.

## Tool surface

| Tool | Purpose |
|---|---|
| `anchor_status` | Schedule, timezone, pmset wake, last runs, version drift. Carries `_meta.ui.resourceUri`, so calling it opens the panel |
| `anchor_set_time` | hour, minute, timezone; converts to system-local, rewrites the plist, reloads launchd, syncs pmset |
| `anchor_toggle` | enable / disable the LaunchAgent |
| `anchor_run_now` | fire one real request; the tool description states that this opens a 5-hour window immediately |
| `anchor_install` | create `~/.codex-anchor/`, install the LaunchAgent, offer the pmset wake |
| `anchor_uninstall` | remove the LaunchAgent and the pmset wake; leave logs |

The first `anchor_status` after installing the plugin finds no LaunchAgent and
runs `anchor_install` itself, which is what makes "install the plugin" equal
"install the tool". It is not silent: the panel's first screen states that it
created `~/.codex-anchor/`, installed the job at the default time, and whether
the pmset wake was accepted or declined.

The UI resource is `ui://codex-anchor-mac/panel-<version>.html` with
`_meta.ui.csp` set to empty `connectDomains` and `resourceDomains`: everything
the panel needs arrives through `callServerTool`, so it needs no network at all.
That turns the CSP restriction from an obstacle into a property worth having.

## UI

`index.html`'s markup, CSS and bilingual string table carry over. Two changes:

- `fetch('/api/…')` becomes `app.callServerTool({ name: 'anchor_status' })`
- theme follows `app.onhostcontextchanged(ctx => applyTheme(ctx.theme))`
  instead of `prefers-color-scheme`, so the panel matches Codex

The language toggle stays; it is per-viewer state in `localStorage`, which
works the same inside the iframe.

## Testing

`test.sh` grows a third section that exercises `anchor_mcp.py` over stdio with
no Codex present: feed it `initialize`, `tools/list`, `resources/read` and an
`anchor_status` call, and assert the shapes. The existing 28 tests are
unaffected, since `anchor.sh` does not change.

CI gains a step that rebuilds `ui/dist/panel.html` and fails if the result
differs from the committed file, so a source edit cannot ship without its
build.

## Risks

- The admin dialog from an MCP context is unverified. Fallback: the launchd job
  works without it and the panel prints the `pmset` command.
- `@modelcontextprotocol/ext-apps` is young (1.7.5) and the Codex host has at
  least one open CSP bug. Pinning the exact version is deliberate.
- Codex's plugin schema is `agent-plugins.org/schemas/1.0.0` and may change.
  The plugin is small enough that tracking it is cheap.
- The marketplace manifest's `git-subdir` source pins `ref: main`. A tag per
  release would be safer but adds release ceremony; revisit if the plugin
  gains users.
- Deleting `server.py` removes the only UI that works without Codex. This was
  accepted on the grounds that the tool's audience is Codex users by
  definition; `setup.sh` and `anchor.log` remain for everyone else.
