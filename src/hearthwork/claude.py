"""One headless Claude Code call, and what it cost.

Everything here leans on the Claude Code CLI: `--print --output-format json`, its
envelope fields, and its transcript folder under ~/.claude/projects/. The last of
these is not a documented interface; it is read only to notice a usage-limit stop
and to keep a session warm, and every reader fails toward the safe answer.
"""

import fcntl
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

LIMIT_RE = re.compile(r"hit your (session|usage|weekly) limit|(session|usage|weekly) limit (reached|exceeded)", re.I)


@dataclass
class CallResult:
    text: str | None
    label: str
    model: str
    seconds: float = 0.0
    cost_usd: float | None = None
    cost_basis: str = "none"
    cli_total_cost_usd: float | None = None
    usage: dict | None = None
    session_id: str | None = None
    resumed: bool = False
    models_used: list = field(default_factory=list)
    cache_ttl: str = "auto"
    mcp: bool = False
    error: str | None = None
    walled: bool = False

    @property
    def ok(self):
        return self.text is not None

    def record(self):
        return {k: v for k, v in self.__dict__.items() if k != "text"}


def transcript_dir(cwd):
    """Claude Code keeps a project's transcripts under a folder named after its path."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))


def transcript(cwd, session_id):
    return transcript_dir(cwd) / f"{session_id}.jsonl"


def session_age_minutes(cwd, session_id):
    """Minutes since a session's transcript was written, or None when it cannot be read."""
    try:
        return (time.time() - transcript(cwd, session_id).stat().st_mtime) / 60.0
    except OSError:
        return None


def _tail_walled(path, since):
    try:
        if path.stat().st_mtime < since - 5:
            return False
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            return LIMIT_RE.search(f.read().decode("utf-8", "replace")) is not None
    except OSError:
        return False


def walled(cwd, session_id, error, since):
    """Did this call stop on a usage limit? The error text counts; so does the tail of a
    transcript this call wrote (a fresh session that walls returns no session id at all,
    so the newest transcript touched since the call began is read instead)."""
    if LIMIT_RE.search(error or ""):
        return True
    if session_id and _tail_walled(transcript(cwd, session_id), since):
        return True
    try:
        newest = max((p for p in transcript_dir(cwd).glob("*.jsonl")), key=lambda p: p.stat().st_mtime)
        return _tail_walled(newest, since)
    except (OSError, ValueError):
        return False


def doctrine_excludes(cwd):
    """Every CLAUDE.md Claude Code would load for `cwd` that is not cwd's own: the user's
    global file and every parent directory's. A call made by hearthwork carries its own
    doctrine and none of the person's other instructions."""
    cwd = Path(cwd).resolve()
    out = []
    for name in ("CLAUDE.md", "CLAUDE.local.md"):
        p = Path.home() / ".claude" / name
        if p.exists():
            out.append(str(p))
    for d in cwd.parents:
        for name in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
            p = d / name
            if p.exists():
                out.append(str(p))
    return out


class CostLedger:
    """With --resume, the CLI's total_cost_usd is the SESSION'S running total, not the
    call's. The call's cost is the increment over the last figure seen for that session.
    `cost_basis` says which figure a record holds:
        whole       a new session; the figure is the call's
        increment   a resume over a known figure
        dropped     a resume whose figure fell below the last one (the CLI began again)
        unknown     a resume of a session never seen; the running total as it came
    """

    KEEP = 400

    def __init__(self, path):
        self.path = Path(path)

    def cost(self, session_id, cli_total, resumed):
        if not isinstance(cli_total, (int, float)) or isinstance(cli_total, bool):
            return None, "none"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                seen = json.loads(self.path.read_text())
                if not isinstance(seen, dict):
                    seen = {}
            except (OSError, ValueError):
                seen = {}
            prev = (seen.get(session_id) or {}).get("total") if session_id else None
            if not resumed:
                cost, basis = cli_total, "whole"
            elif not isinstance(prev, (int, float)):
                cost, basis = cli_total, "unknown"
            elif cli_total + 1e-9 >= prev:
                cost, basis = cli_total - prev, "increment"
            else:
                cost, basis = cli_total, "dropped"
            if session_id:
                seen[session_id] = {"total": cli_total, "ts": time.time()}
                for k in sorted(seen, key=lambda k: seen[k].get("ts", 0))[: max(0, len(seen) - self.KEEP)]:
                    seen.pop(k, None)
                tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
                tmp.write_text(json.dumps(seen))
                os.replace(tmp, self.path)
        return round(cost, 6), basis


def run(*, claude_bin, cwd, prompt, model, timeout, label, costs, resume=None, tools=None,
        settings=None, setting_sources=None, append_system_prompt=None, add_dirs=(), env_extra=None,
        strict_mcp=True):
    """One `claude --print` call. Never raises for a failed call: the result says why."""
    cmd = [claude_bin, "--print", "--model", model, "--output-format", "json",
           "--dangerously-skip-permissions"]
    if strict_mcp:
        cmd += ["--strict-mcp-config"]
    if tools is not None:
        cmd += ["--tools", ",".join(tools)]
    if setting_sources is not None:
        cmd += ["--setting-sources", ",".join(setting_sources)]
    if settings is not None:
        cmd += ["--settings", json.dumps(settings)]
    if append_system_prompt:
        cmd += ["--append-system-prompt", append_system_prompt]
    for d in add_dirs:
        cmd += ["--add-dir", str(d)]
    if resume:
        cmd += ["--resume", resume]
    env = dict(os.environ)
    # --print returns the final turn only: a session that backgrounds a task and ends its
    # turn "waiting" has returned nothing. Background tasks are off for every call.
    env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    env.update(env_extra or {})
    res = CallResult(text=None, label=label, model=model, resumed=bool(resume),
                     cache_ttl=env.get("CLAUDE_CODE_PROMPT_CACHE_TTL") or "auto",
                     mcp=not strict_mcp)
    t0 = time.time()
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=str(cwd),
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        res.seconds = round(time.time() - t0, 1)
        res.error = f"timeout after {timeout}s"
        res.walled = walled(cwd, resume, res.error, t0)
        return res
    except FileNotFoundError:
        res.error = f"the Claude Code CLI was not found: {claude_bin}"
        return res
    res.seconds = round(time.time() - t0, 1)
    raw = p.stdout
    brace = raw.find("{")
    try:
        out = json.loads(raw[brace:] if brace >= 0 else raw)
    except ValueError:
        out = None
    if not isinstance(out, dict):
        res.error = f"exit {p.returncode}: {(p.stderr or raw).strip()[:400] or 'no output'}"
        res.walled = walled(cwd, resume, res.error, t0)
        return res
    res.session_id = out.get("session_id")
    res.usage = out.get("usage")
    res.cli_total_cost_usd = out.get("total_cost_usd")
    res.cost_usd, res.cost_basis = costs.cost(res.session_id, res.cli_total_cost_usd, bool(resume))
    if isinstance(out.get("modelUsage"), dict):
        res.models_used = sorted(out["modelUsage"])
    if p.returncode != 0 or out.get("is_error"):
        res.error = f"session error: {str(out.get('result'))[:400]}"
        res.walled = walled(cwd, res.session_id or resume, res.error, t0)
        return res
    res.text = out.get("result") or ""
    return res


def extract_json(text):
    """A phase's answer is one JSON object; tolerate a code fence or text around it."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    start = t.find("{")
    if start < 0:
        return None
    dec = json.JSONDecoder()
    for i in range(start, len(t)):
        if t[i] != "{":
            continue
        try:
            obj, _ = dec.raw_decode(t[i:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
