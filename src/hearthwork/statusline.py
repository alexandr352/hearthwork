"""`operator statusline`: Claude Code's status line, and a documented source of your limits.

Claude Code runs a status line command after each reply in an interactive session and gives
it a JSON snapshot on stdin; on subscription plans it carries `rate_limits` (the 5-hour and
7-day windows, used percentage and reset time). This command keeps that as hearthwork's
newest usage reading, and prints one short line. It never fails: a status line that errors
shows nothing, so every problem degrades to a shorter line.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import home


def note_from_statusline(data):
    """Keep the status line's rate_limits as the usage reading; True when there were any."""
    rl = (data or {}).get("rate_limits") or {}
    keep = {}
    for name in ("five_hour", "seven_day"):
        w = rl.get(name) or {}
        pct = w.get("used_percentage")
        if isinstance(pct, (int, float)) and not isinstance(pct, bool):
            keep[name] = {"used": float(pct) / 100.0, "resets_at": w.get("resets_at")}
    if not keep:
        return False
    keep["seen"] = time.time()
    keep["source"] = "statusline"
    from .claude import usage_path
    try:
        path = usage_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".usage.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(keep))
        os.replace(tmp, path)
    except OSError:
        pass
    return True


def line(data):
    """The one line shown at the bottom of Claude Code."""
    parts = []
    from .claude import read_usage
    u = read_usage() or {}
    for key, label, fmt in (("five_hour", "5h", "%H:%M"), ("seven_day", "week", "%a %H:%M")):
        w = u.get(key)
        if w:
            r = f" ↻{time.strftime(fmt, time.localtime(w['resets_at']))}" if w.get("resets_at") else ""
            parts.append(f"{label} {w['used'] * 100:.0f}%{r}")
    cwd = ((data or {}).get("workspace") or {}).get("current_dir") or (data or {}).get("cwd")
    try:
        p = home.resolve_project(cwd=cwd) if cwd else None
    except home.HomeError:
        p = None
    if p:
        from .records import running
        r = running(p)
        st = p.read_state()
        if r:
            parts.append(f"{p.name}: {r.get('ticket')} running ({r.get('phase')})")
        elif st.get("halted"):
            parts.append(f"{p.name}: halted, needs you")
        elif st.get("active_ticket"):
            parts.append(f"{p.name}: {st['active_ticket']}")
    return "hearthwork · " + " · ".join(parts) if parts else "hearthwork"


def run(stdin=None):
    try:
        raw = (stdin or sys.stdin).read()
        data = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        data = {}
    try:
        note_from_statusline(data)
        text = line(data)
    except Exception:
        text = "hearthwork"
    print(text, flush=True)
    return 0


def settings_path():
    return Path.home() / ".claude" / "settings.json"


def install():
    """Add this command as Claude Code's status line. Returns (ok, message)."""
    beside = Path(sys.executable).parent / "operator"   # where pip put the command
    exe = str(beside) if beside.exists() else shutil.which("operator")
    if not exe:
        return False, "cannot find the operator command to install; is hearthwork installed?"
    command = f"{exe} statusline"
    path = settings_path()
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(settings, dict):
            return False, f"{path} is not a JSON object; nothing was changed"
    except ValueError:
        return False, f"{path} is not valid JSON; nothing was changed"
    current = settings.get("statusLine")
    if current:
        cmd = current.get("command", "") if isinstance(current, dict) else ""
        if cmd.endswith(" statusline") and "operator" in cmd:
            if cmd == command:
                return True, f"already installed in {path}"
        else:
            return False, (f"{path} already has a status line ({cmd or current}); it was left alone. To keep yours "
                           f"and still feed hearthwork, have it pipe its input to `{command}` too.")
    if path.exists():
        backup = path.with_name(f"settings.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(path.read_text())
    settings["statusLine"] = {"type": "command", "command": command}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".settings.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n")
    os.replace(tmp, path)
    return True, f"installed in {path}; a new Claude Code session shows it after its first reply"
