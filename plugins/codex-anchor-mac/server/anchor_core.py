#!/usr/bin/env python3
"""Schedule state for the Codex anchor job.

Pure logic plus launchctl and pmset calls, with no transport of its own, so
the MCP server and the tests can both drive it.
"""
from __future__ import annotations

import json
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones

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

# pmset must wake the Mac slightly before launchd fires, or a battery night
# misses the trigger entirely.
WAKE_LEAD_MINUTES = 3
PLUGIN_VERSION = "0.1.0"
VERSION_FILE = HOME_DIR / ".version"


# Set by the tests so they cannot reach launchctl, pmset or osascript. The
# suite runs on the same Mac the tool schedules, and pmset is system-global:
# a temporary HOME isolates files but not the power schedule.
DRY_RUN = os.environ.get("ANCHOR_DRY_RUN") == "1"


def _mutates(cmd: list[str]) -> bool:
    """Reads must still reach the system under DRY_RUN, or state detection
    lies: a faked launchctl print would report the job loaded when it is not.
    """
    if cmd[0] in ("sudo", "osascript"):
        return True
    if cmd[0] == "launchctl":
        return cmd[1] not in ("print", "list")
    if cmd[0] == "pmset":
        return cmd[1] != "-g"
    return True


def run(cmd: list[str]) -> tuple[int, str]:
    if DRY_RUN and cmd and _mutates(cmd):
        return 0, f"dry-run: {' '.join(cmd)}"
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
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
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


def last_run() -> dict | None:
    """From the log, not launchctl: its counters reset on every re-bootstrap,
    which made the panel claim 'never run yet' after a successful night."""
    for line in reversed(recent_runs(50)):
        m = re.match(r"(\S+ \S+ \S+)\s+(OK|FAIL|WARN|SKIP)\b", line)
        if m and m.group(2) != "SKIP":
            return {"at": m.group(1), "status": m.group(2)}
    return None


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
        "lastRun": last_run(),
        "pmsetWake": pmset_wake(),
        "expectedWake": f"{wh:02d}:{wm:02d}" if wh is not None else None,
        "runs": recent_runs(),
        "home": home_health(),
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




def installed_version() -> str | None:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def home_health(home: pathlib.Path | None = None,
                script: pathlib.Path | None = None,
                installed_version_override: str | None = None) -> dict:
    """What is on disk, as opposed to what the plist believes.

    The schedule rots in two silent ways: the copied script is deleted, or a
    plugin upgrade leaves the copy behind. Neither surfaces at 04:30.
    """
    home = HOME_DIR if home is None else home
    script = (home / "anchor.sh") if script is None else script
    have = (installed_version_override if installed_version_override is not None
            else installed_version())
    drift = bool(have) and have != PLUGIN_VERSION
    parts = []
    if not home.is_dir():
        parts.append(f"{home} does not exist yet")
    if not script.is_file():
        parts.append(f"anchor.sh is missing from {script.parent}")
    if drift:
        parts.append(f"copied from plugin {have}, running {PLUGIN_VERSION}")
    return {"homePresent": home.is_dir(),
            "scriptPresent": script.is_file(),
            "installedVersion": have,
            "pluginVersion": PLUGIN_VERSION,
            "versionDrift": drift,
            "summary": "; ".join(parts) or "healthy"}


def install_home() -> dict:
    """Create the job's home, install the LaunchAgent, offer the wake.

    Each stage reports separately: a declined admin dialog must not look like
    a failed install, because the job itself needs no privileges at all.
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
        shell = f"/usr/bin/pmset repeat wake MTWRFSU {wh:02d}:{wm:02d}:00"
        rc, out = run(["osascript", "-e",
                       f'do shell script "{shell}" with administrator '
                       f'privileges with prompt "codex-anchor-mac needs to '
                       f'schedule a daily wake"'])
    step("schedule the daily wake", rc == 0,
         f"{wh:02d}:{wm:02d}" if rc == 0
         else "declined; the job still runs, it is just late on battery nights")
    return {"steps": steps, "status": status()}


def uninstall() -> dict:
    steps: list[dict] = []
    _, out = run(["launchctl", "bootout", SERVICE])
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
