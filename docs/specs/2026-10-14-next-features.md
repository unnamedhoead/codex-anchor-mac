# Next features

Status: recorded, not implemented
Date: 2026-10-14
Source: user feedback after the panel rendered successfully in Codex

What the panel rendering confirmed, so these are no longer open risks: the
MCP Apps UI renders inside Codex, and `anchor_set_time` completes all six
steps including the pmset wake through `sudo -n` with no admin dialog.

## 1. The panel does not follow Codex's theme

Codex is in dark mode; the panel renders light.

Not a missing feature — the code is already there. `panel.html` carries a
`:root[data-theme="dark"]` block and `app.ts` sets
`document.documentElement.dataset.theme` from `app.getHostContext()?.theme`
and from `onhostcontextchanged`. So either the host context does not carry a
theme at all, or it carries it under a different key, or the callback never
fires.

Investigate before changing anything: log what `getHostContext()` actually
returns in a running panel. A plausible fallback, if the host genuinely does
not expose a theme, is to restore the `prefers-color-scheme` media query that
was removed when the host-driven path was added — the iframe should still
inherit the system appearance.

## 2. Nobody can see what the anchor request actually says

The prompt is invisible: it lives in `anchor.sh` as a constant, and neither
the user nor a reader of the repository can tell what gets sent. For a tool
whose whole claim is "one deliberately tiny request", the request being
unreadable is the wrong default.

The panel should show the exact prompt it will send, and let it be changed.

## 3. Default to "hi", and allow a custom prompt pinned to a session

**Default.** Replace the current prompt — "Read README.md in the current
directory and print only its first 100 characters" — with `hi`. It was chosen
to double as a health check, but it is ambiguous about what the tool does and
costs more tokens than the job needs. `hi` is unambiguous: it exists only to
start the clock.

Dropping the README read loses the health check that the log tail provided.
Decide what replaces it: the exit code and the token count in the log may be
enough.

**Custom.** The panel gets a prompt field and a session selector, so a user
can choose what to send and which session or folder to send it in. The stated
use case is a scheduled task that does real work at the anchor time, instead
of a throwaway ping.

Open question, and the hard part: `anchor.sh` runs `codex exec --ephemeral`,
which deliberately leaves no session behind. Pinning the request to a named
session means either dropping `--ephemeral` and using `codex exec resume
<id>`, or giving the plugin a way to enumerate sessions and address one.
Neither is designed yet. `codex exec resume --last` and the session index at
`~/.codex/session_index.jsonl` are the places to start.

## Explicitly out of scope

Multiple anchors per day. One scheduled run, changed by hand when needed, is
enough for the stated use. Do not build a schedule list.
