#!/usr/bin/env python3
"""Local control panel for the Codex quota warmup job.

Binds 127.0.0.1 only. Lets you change the daily trigger time (keeping the
launchd job and the pmset wake in sync), watch recent runs, disable the job
and fire a manual run.
"""
from __future__ import annotations

import json
import os
import pathlib
import plistlib
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 7788
BIND = "127.0.0.1"
LABEL = "com.hoead.codex-warmup"
DIR = pathlib.Path(__file__).resolve().parent
TEMPLATE = DIR / f"{LABEL}.plist"
INSTALL_SH = DIR / "install.sh"
LOG = DIR / "warmup.log"
INSTALLED = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
INDEX = DIR / "index.html"
UID = os.getuid()
SERVICE = f"gui/{UID}/{LABEL}"

# pmset must wake the Mac slightly before launchd fires, or a battery night
# misses the trigger entirely.
WAKE_LEAD_MINUTES = 3

# A browser can be tricked into resolving an attacker domain to 127.0.0.1, so
# only answer requests that actually addressed us by our own name.
ALLOWED_HOSTS = {f"{BIND}:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"}


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI verbatim
        return 1, f"{type(exc).__name__}: {exc}"
    return p.returncode, (p.stdout + p.stderr).strip()


def read_schedule() -> tuple[int | None, int | None]:
    try:
        with INSTALLED.open("rb") as fh:
            cal = plistlib.load(fh).get("StartCalendarInterval") or {}
        return int(cal["Hour"]), int(cal["Minute"])
    except Exception:
        return None, None


def wake_time(hour: int, minute: int) -> tuple[int, int]:
    total = (hour * 60 + minute - WAKE_LEAD_MINUTES) % (24 * 60)
    return divmod(total, 60)


def agent_loaded() -> tuple[bool, str]:
    rc, out = run(["launchctl", "print", SERVICE])
    if rc != 0:
        return False, "未加载"
    state = "运行中" if "state = running" in out else "已加载，待触发"
    for line in out.splitlines():
        if "last exit code" in line:
            state += f"（上次退出码 {line.split('=')[-1].strip()}）"
            break
    return True, state


def pmset_wake() -> str:
    _, out = run(["pmset", "-g", "sched"])
    m = re.search(r"wake at (\S+ ?\S*) every day", out)
    return m.group(1) if m else "未设置"


def recent_runs(limit: int = 15) -> list[str]:
    try:
        text = LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # Skip the indented continuation lines a FAIL entry dumps; only the
    # timestamped lines are actual runs.
    runs = [ln for ln in text.splitlines() if re.match(r"\d{4}-\d{2}-\d{2} ", ln)]
    return runs[-limit:]


def status() -> dict:
    hour, minute = read_schedule()
    loaded, state = agent_loaded()
    wh, wm = wake_time(hour, minute) if hour is not None else (None, None)
    return {
        "hour": hour,
        "minute": minute,
        "time": f"{hour:02d}:{minute:02d}" if hour is not None else None,
        "loaded": loaded,
        "state": state,
        "pmsetWake": pmset_wake(),
        "expectedWake": f"{wh:02d}:{wm:02d}" if wh is not None else None,
        "runs": recent_runs(),
    }


def set_schedule(hour: int, minute: int) -> list[dict]:
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": name, "ok": ok, "detail": detail})

    try:
        with INSTALLED.open("rb") as fh:
            data = plistlib.load(fh)
        data["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
        with INSTALLED.open("wb") as fh:
            plistlib.dump(data, fh)
        step("更新已安装的 plist", True, str(INSTALLED))
    except Exception as exc:  # noqa: BLE001
        step("更新已安装的 plist", False, str(exc))
        return steps

    # Keep the template and installer in sync so re-running install.sh does not
    # silently revert the time.
    try:
        src = TEMPLATE.read_text(encoding="utf-8")
        src = re.sub(r"(<key>Hour</key>\s*<integer>)\d+(</integer>)",
                     rf"\g<1>{hour}\g<2>", src, count=1)
        src = re.sub(r"(<key>Minute</key>\s*<integer>)\d+(</integer>)",
                     rf"\g<1>{minute}\g<2>", src, count=1)
        TEMPLATE.write_text(src, encoding="utf-8")
        step("同步 plist 模板", True)
    except Exception as exc:  # noqa: BLE001
        step("同步 plist 模板", False, str(exc))

    wh, wm = wake_time(hour, minute)
    try:
        sh = INSTALL_SH.read_text(encoding="utf-8")
        sh = re.sub(r'WAKE_TIME="\d{2}:\d{2}:\d{2}"',
                    f'WAKE_TIME="{wh:02d}:{wm:02d}:00"', sh, count=1)
        INSTALL_SH.write_text(sh, encoding="utf-8")
        step("同步 install.sh 的 WAKE_TIME", True, f"{wh:02d}:{wm:02d}:00")
    except Exception as exc:  # noqa: BLE001
        step("同步 install.sh 的 WAKE_TIME", False, str(exc))

    run(["launchctl", "bootout", SERVICE])
    rc, out = run(["launchctl", "bootstrap", f"gui/{UID}", str(INSTALLED)])
    step("重新加载 launchd", rc == 0, out)
    run(["launchctl", "enable", SERVICE])

    # -n so a missing sudoers rule fails loudly instead of hanging on a prompt.
    rc, out = run(["sudo", "-n", "pmset", "repeat", "wake", "MTWRFSU",
                   f"{wh:02d}:{wm:02d}:00"])
    step("更新 pmset 唤醒", rc == 0,
         out or (f"已设为 {wh:02d}:{wm:02d}" if rc == 0 else "需要 sudoers 规则"))
    return steps


class Handler(BaseHTTPRequestHandler):
    server_version = "codex-warmup-ui"

    def log_message(self, fmt, *args):  # quieter launchd logs
        pass

    def _guard(self) -> bool:
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self.send_error(421, "unexpected Host header")
            return False
        return True

    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if not self._guard():
            return
        if self.path in ("/", "/index.html"):
            try:
                body = INDEX.read_bytes()
            except OSError:
                self.send_error(500, "index.html missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            self._json(status())
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        if not self._guard():
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "bad json"}, 400)
            return

        if self.path == "/api/time":
            try:
                hour = int(payload["hour"])
                minute = int(payload["minute"])
            except (KeyError, TypeError, ValueError):
                self._json({"error": "hour/minute 必须是整数"}, 400)
                return
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                self._json({"error": "hour 需在 0-23，minute 需在 0-59"}, 400)
                return
            self._json({"steps": set_schedule(hour, minute), "status": status()})

        elif self.path == "/api/toggle":
            enable = bool(payload.get("enable"))
            if enable:
                run(["launchctl", "enable", SERVICE])
                rc, out = run(["launchctl", "bootstrap", f"gui/{UID}",
                               str(INSTALLED)])
            else:
                run(["launchctl", "disable", SERVICE])
                rc, out = run(["launchctl", "bootout", SERVICE])
            self._json({"ok": rc == 0, "detail": out, "status": status()})

        elif self.path == "/api/run":
            rc, out = run(["launchctl", "kickstart", "-k", SERVICE])
            self._json({"ok": rc == 0, "detail": out})

        else:
            self.send_error(404)


def main() -> None:
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"codex-warmup control panel on http://{BIND}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
