#!/usr/bin/env python3
"""Local control panel for the Codex quota anchor job.

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
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo, available_timezones

PORT = 7788
BIND = "127.0.0.1"
LABEL = "io.github.codex-anchor-mac"
DIR = pathlib.Path(__file__).resolve().parent
TEMPLATE = DIR / f"{LABEL}.plist"
INSTALL_SH = DIR / "install.sh"
LOG = DIR / "anchor.log"
INSTALLED = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
INDEX = DIR / "index.html"
CONFIG = DIR / "config.json"
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


def system_timezone() -> str:
    """The IANA name macOS is currently using, e.g. Asia/Shanghai."""
    try:
        link = os.readlink("/etc/localtime")
    except OSError:
        return "UTC"
    # /var/db/timezone/zoneinfo/Asia/Shanghai -> Asia/Shanghai
    parts = link.split("zoneinfo/", 1)
    return parts[1] if len(parts) == 2 else "UTC"


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        cfg = {}
    except (json.JSONDecodeError, OSError) as exc:
        # Fall back to defaults rather than 500, but keep the reason visible.
        cfg = {"_error": f"config.json could not be read ({exc}); using defaults"}
    # A null timezone means "whatever this Mac is set to" -- the right default
    # for anyone who clones this, rather than inheriting the author's zone.
    if not cfg.get("timezone"):
        cfg["timezone"] = system_timezone()
    cfg.setdefault("hour", 4)
    cfg.setdefault("minute", 30)
    cfg.setdefault("computedUnderSystemTimezone", cfg["timezone"])
    if not CONFIG.exists():
        save_config(cfg)
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def to_local(hour: int, minute: int, tz_name: str) -> tuple[int, int]:
    """Convert a wall-clock time in tz_name into the system's local clock.

    launchd only understands the system's local time, so a user who picks a
    timezone other than their system's needs the conversion done here. Anchored
    on the next occurrence rather than today so a DST shift resolves the way
    the next run actually will.
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return hour, minute
    local_now = datetime.now().astimezone()
    candidate = datetime.now(tz).replace(hour=hour, minute=minute,
                                         second=0, microsecond=0)
    if candidate <= datetime.now(tz):
        candidate += timedelta(days=1)
    local = candidate.astimezone(local_now.tzinfo)
    return local.hour, local.minute


# 598 IANA zones is an unusable dropdown. Collapsing by *current* offset would
# be wrong, though: Europe/London and Africa/Abidjan agree in January and
# differ in July. Group by the (January, July) offset pair instead, so each
# entry stands for one real set of rules, DST included.
_PREFERRED = (
    "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul", "Asia/Singapore", "Asia/Kolkata",
    "Asia/Dubai", "Asia/Bangkok", "Asia/Jakarta", "Asia/Karachi", "Asia/Tehran",
    "Asia/Jerusalem", "Asia/Kathmandu", "Asia/Yangon", "Asia/Kabul",
    "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Moscow",
    "Europe/Lisbon", "Europe/Athens", "Europe/Dublin",
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "America/Sao_Paulo",
    "America/Mexico_City", "America/Bogota", "America/Halifax", "America/St_Johns",
    "Pacific/Auckland", "Pacific/Honolulu", "Pacific/Fiji", "Pacific/Chatham",
    "Australia/Sydney", "Australia/Brisbane", "Australia/Adelaide",
    "Australia/Perth", "Australia/Darwin", "Australia/Lord_Howe",
    "Africa/Cairo", "Africa/Lagos", "Africa/Johannesburg", "Africa/Nairobi",
    "Africa/Abidjan", "Atlantic/Azores", "UTC",
    # Slots with no obvious big city; pick the most recognisable inhabited place
    # rather than letting an Etc/GMT* or legacy US/* name win on length.
    "Pacific/Pago_Pago", "America/Adak", "Pacific/Gambier", "Pacific/Pitcairn",
    "America/Caracas", "Atlantic/South_Georgia", "Atlantic/Cape_Verde",
    "Asia/Dhaka", "Pacific/Guadalcanal", "Pacific/Tongatapu",
    "Pacific/Kiritimati", "Pacific/Marquesas",
)


def _offset_label(delta) -> str:
    total = int(delta.total_seconds()) // 60
    sign = "+" if total >= 0 else "-"
    return f"UTC{sign}{abs(total) // 60:02d}:{abs(total) % 60:02d}"


def timezone_choices() -> list[dict]:
    """One entry per distinct set of rules, sorted by offset, plus this Mac's."""
    rank = {name: i for i, name in enumerate(_PREFERRED)}
    groups: dict[tuple, list[str]] = {}
    for name in available_timezones():
        try:
            tz = ZoneInfo(name)
            jan = datetime(2026, 1, 15, 12, tzinfo=tz).utcoffset()
            jul = datetime(2026, 7, 15, 12, tzinfo=tz).utcoffset()
        except Exception:
            continue
        groups.setdefault((jan, jul), []).append(name)

    out = []
    for (jan, jul), names in groups.items():
        # Prefer a city people recognise; fall back to the shortest name.
        pick = min(names, key=lambda n: (rank.get(n, 10_000), len(n), n))
        label = _offset_label(jan)
        if jan != jul:
            label += f" / {_offset_label(jul)} DST"
        out.append({"name": pick, "label": f"{label}  {pick}", "sort": jan})

    sys_tz = system_timezone()
    if sys_tz not in {c["name"] for c in out}:
        try:
            off = datetime(2026, 1, 15, 12, tzinfo=ZoneInfo(sys_tz)).utcoffset()
        except Exception:
            off = None
        out.append({"name": sys_tz, "label": f"{sys_tz} (this Mac)",
                    "sort": off or jan})

    out.sort(key=lambda c: (c["sort"], c["name"]))
    for c in out:
        del c["sort"]
    return out


def timezone_drifted(cfg: dict) -> bool:
    return cfg.get("computedUnderSystemTimezone") != system_timezone()


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


def agent_state() -> dict:
    """Structured, not prose: the UI renders it in whichever language is on."""
    rc, out = run(["launchctl", "print", SERVICE])
    if rc != 0:
        return {"loaded": False, "running": False, "lastExit": None}
    exit_code = None
    for line in out.splitlines():
        if "last exit code" in line:
            raw = line.split("=")[-1].strip()
            if raw.lstrip("-").isdigit():
                exit_code = int(raw)
            break
    return {"loaded": True,
            "running": "state = running" in out,
            "lastExit": exit_code}


def pmset_wake() -> str:
    _, out = run(["pmset", "-g", "sched"])
    m = re.search(r"wake at (\S+ ?\S*) every day", out)
    return m.group(1) if m else "not set"


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
    cfg = load_config()
    local_hour, local_minute = read_schedule()
    agent = agent_state()
    wh, wm = wake_time(local_hour, local_minute) if local_hour is not None else (None, None)
    sys_tz = system_timezone()
    return {
        "timezone": cfg["timezone"],
        "systemTimezone": sys_tz,
        "hour": cfg["hour"],
        "minute": cfg["minute"],
        # What the user asked for, in their chosen timezone.
        "time": f"{cfg['hour']:02d}:{cfg['minute']:02d}",
        # What launchd will actually honour, on the system clock.
        "localTime": (f"{local_hour:02d}:{local_minute:02d}"
                      if local_hour is not None else None),
        "sameClock": cfg["timezone"] == sys_tz,
        "drifted": timezone_drifted(cfg),
        "loaded": agent["loaded"],
        "running": agent["running"],
        "lastExit": agent["lastExit"],
        "pmsetWake": pmset_wake(),
        "expectedWake": f"{wh:02d}:{wm:02d}" if wh is not None else None,
        "runs": recent_runs(),
        "timezones": timezone_choices(),
    }


def set_schedule(hour: int, minute: int, tz_name: str) -> list[dict]:
    """hour/minute are wall-clock in tz_name; launchd gets the local equivalent."""
    steps: list[dict] = []
    local_hour, local_minute = to_local(hour, minute, tz_name)

    def step(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": name, "ok": ok, "detail": detail})

    try:
        with INSTALLED.open("rb") as fh:
            data = plistlib.load(fh)
        data["StartCalendarInterval"] = {"Hour": local_hour, "Minute": local_minute}
        with INSTALLED.open("wb") as fh:
            plistlib.dump(data, fh)
        step("update installed plist", True,
             f"{hour:02d}:{minute:02d} {tz_name} = {local_hour:02d}:{local_minute:02d} system time")
    except FileNotFoundError:
        step("update installed plist", False,
             "the LaunchAgent is not installed -- run ./setup.sh first")
        return steps
    except Exception as exc:  # noqa: BLE001
        step("update installed plist", False, str(exc))
        return steps

    # Keep the template and installer in sync so re-running install.sh does not
    # silently revert the time.
    try:
        src = TEMPLATE.read_text(encoding="utf-8")
        src = re.sub(r"(<key>Hour</key>\s*<integer>)\d+(</integer>)",
                     rf"\g<1>{local_hour}\g<2>", src, count=1)
        src = re.sub(r"(<key>Minute</key>\s*<integer>)\d+(</integer>)",
                     rf"\g<1>{local_minute}\g<2>", src, count=1)
        TEMPLATE.write_text(src, encoding="utf-8")
        step("sync plist template", True)
    except Exception as exc:  # noqa: BLE001
        step("sync plist template", False, str(exc))

    cfg = load_config()
    cfg.update({"timezone": tz_name, "hour": hour, "minute": minute,
                "computedUnderSystemTimezone": system_timezone()})
    save_config(cfg)
    step("write config.json", True, f"timezone={tz_name}")

    wh, wm = wake_time(local_hour, local_minute)
    try:
        sh = INSTALL_SH.read_text(encoding="utf-8")
        sh = re.sub(r'WAKE_TIME="\d{2}:\d{2}:\d{2}"',
                    f'WAKE_TIME="{wh:02d}:{wm:02d}:00"', sh, count=1)
        INSTALL_SH.write_text(sh, encoding="utf-8")
        step("sync install.sh WAKE_TIME", True, f"{wh:02d}:{wm:02d}:00")
    except Exception as exc:  # noqa: BLE001
        step("sync install.sh WAKE_TIME", False, str(exc))

    run(["launchctl", "bootout", SERVICE])
    rc, out = run(["launchctl", "bootstrap", f"gui/{UID}", str(INSTALLED)])
    step("reload launchd", rc == 0, out)
    run(["launchctl", "enable", SERVICE])

    # -n so a missing sudoers rule fails loudly instead of hanging on a prompt.
    rc, out = run(["sudo", "-n", "pmset", "repeat", "wake", "MTWRFSU",
                   f"{wh:02d}:{wm:02d}:00"])
    step("update pmset wake", rc == 0,
         out or (f"set to {wh:02d}:{wm:02d}" if rc == 0 else "needs the sudoers rule -- re-run ./setup.sh"))
    return steps


class Handler(BaseHTTPRequestHandler):
    server_version = "codex-anchor-mac"

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
                self._json({"error": "hour and minute must be integers"}, 400)
                return
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                self._json({"error": "hour must be 0-23 and minute 0-59"}, 400)
                return
            tz_name = payload.get("timezone") or load_config()["timezone"]
            if tz_name not in available_timezones():
                self._json({"error": f"unknown timezone: {tz_name}"}, 400)
                return
            self._json({"steps": set_schedule(hour, minute, tz_name),
                        "status": status()})

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
    print(f"codex-anchor-mac control panel on http://{BIND}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
