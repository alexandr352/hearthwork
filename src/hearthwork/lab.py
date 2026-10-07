"""The lab: one instrument for a checkout's runtime, and the one sanctioned baseline.

    operator lab status | up | down | restart | build [--force] | logs [n]
    operator lab gate <file...>          run the named test files once, under a clock
    operator lab lint [file...]
    operator lab ab <file...> [--dry-run] [--last]
        THE CARRIED A/B: the named tests run on your uncommitted work (CARRIED) and on
        clean HEAD with the named files kept (BASE). It answers the question a guard test
        exists for: does it fail without the change and pass with it?
            GUARDS                 red on BASE, green on CARRIED: the test guards the change
            PASSES-WITHOUT-CHANGE  green on both: the test does not prove the change
            BROKEN-BY-CHANGE       green on BASE, red on CARRIED: the change broke it
            RED-AT-BOTH            red on both: the test fails for another reason
    operator lab config [--from-atlas | <key> <value>]

The commands come from the [lab] table of the project's project.toml:

    [lab]
    test = "pytest -q {files}"      # {files}: the named files; required for gate and ab
    lint = "ruff check {files}"     # {files} optional
    build = "npm run build"         # optional
    up = "npm run serve"            # optional: a server the tests need, run in its own process group
    health = ""                     # optional: the URL up waits for; left empty, up finds it (what the
                                    #   server prints, else the port it opens) and saves it here
    down = ""                       # optional: run before the process group is stopped
    scratch = ".hearthwork-scratch" # git-excluded folder for disposable probes
    ab = "worktree"                 # worktree: BASE runs in a throwaway git worktree, your checkout
                                    #   is never touched; in-place: BASE swaps the files in the
                                    #   checkout (for tests that run against the lab's server), and
                                    #   your work is saved under a git ref first and restored verified
    share = ["node_modules", ".venv"]   # worktree: linked into the throwaway worktree
    gate_timeout = 540              # seconds per gate run
    up_timeout = 120

Everything the lab starts runs in its own process group recorded in its state, so nothing
leaks; an A/B runs detached, so a caller killed mid-run never strands your work, and every
acting verb first recovers what an A/B that died left behind.
"""

import fcntl
import re
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .home import write_atomic

DEFAULTS = {"test": "", "lint": "", "build": "", "up": "", "health": "", "down": "",
            "scratch": ".hearthwork-scratch", "ab": "worktree", "share": None,
            "gate_timeout": 540, "up_timeout": 120, "build_timeout": 900}
SHARE_GUESS = ("node_modules", ".venv", "venv", "env", "vendor")
KEYS = ("test", "lint", "build", "up", "health", "down", "scratch", "ab")
VERDICTS = ("GUARDS", "PASSES-WITHOUT-CHANGE", "BROKEN-BY-CHANGE", "RED-AT-BOTH")
REF_PREFIX = "refs/hearthwork/lab/carried-"


class LabError(Exception):
    """Refused or failed; the message says why. code 2 = refused, 1 = failed, 3 = down."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def conf(p):
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (getattr(p, "lab", None) or {}).items() if v is not None})
    return c


def lab_dir(p):
    d = Path(p.dir) / "lab"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, obj):
    write_atomic(path, json.dumps(obj, indent=2) + "\n")


def _alive(pid):
    """A process that still runs. A zombie (dead, not yet reaped by its parent) is dead."""
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        pass
    try:
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5).stdout
        return bool(st.strip()) and not st.strip().startswith("Z")
    except (OSError, subprocess.SubprocessError):
        return True


def _git(repo, *args, env=None, check=True, text=True):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=text,
                       env={**os.environ, **(env or {})}, timeout=300)
    if check and p.returncode != 0:
        raise LabError(f"git {' '.join(args[:3])}: {(p.stderr or p.stdout).strip()[:300]}")
    return p.stdout.strip() if text else p.stdout


def scratch_path(p):
    return (Path(p.repo) / conf(p)["scratch"]).resolve()


def ensure_scratch(p):
    """The scratch folder is excluded from git in this checkout only (.git/info/exclude):
    nothing is added to the repository, and a probe in it never shows as a change."""
    try:
        rel = check_scratch(p, conf(p)["scratch"])
    except LabError:
        return
    try:
        exclude = Path(p.repo) / _git(p.repo, "rev-parse", "--git-path", "info/exclude")
    except (LabError, OSError, subprocess.SubprocessError):
        return
    line = f"/{rel}/"
    try:
        have = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    except OSError:
        return
    if line not in have:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as f:
            f.write(("" if not have or have[-1] == "" else "\n") + f"# hearthwork probes\n{line}\n")


class Locked:
    """The lab's lock, taken once per verb at the top (never again inside: a fresh fd is
    not re-entrant)."""

    def __init__(self, p, wait=1200):
        self.path = lab_dir(p) / ".lock"
        self.wait = wait
        self.f = None

    def __enter__(self):
        self.f = open(self.path, "a+")
        t0 = time.time()
        while True:
            try:
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() - t0 > self.wait:
                    raise LabError("the lab is busy (another lab verb holds it)", 2)
                time.sleep(0.5)

    def __exit__(self, *exc):
        fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        self.f.close()


def _tag(p):
    """The ticket and unit in flight, so a result is filed with the unit that made it."""
    rec = _read(Path(p.dir) / "running.json") or {}
    if rec.get("ticket"):
        return {"ticket": rec.get("ticket"), "unit": rec.get("unit")}
    st = _read(Path(p.dir) / "state.json") or {}
    tid = st.get("active_ticket")
    if tid:
        lease = _read(Path(p.dir) / "tickets" / tid / "lease.json") or {}
        return {"ticket": tid, "unit": lease.get("unit")}
    return {}


def _files(p, files, cwd=None):
    """The named files, relative to the checkout. Every one must exist."""
    if not files:
        raise LabError("name the test files: a gate never runs a whole suite", 2)
    repo = Path(p.repo).resolve()
    out = []
    for f in files:
        cand = [Path(f)] if os.path.isabs(f) else [Path(cwd or os.getcwd()) / f, repo / f]
        path = next((c.resolve() for c in cand if c.exists()), None)
        if path is None:
            raise LabError(f"{f}: no such file", 2)
        try:
            out.append(str(path.relative_to(repo)))
        except ValueError:
            raise LabError(f"{f} is outside the checkout", 2)
    return out


def _cmd(template, files):
    joined = " ".join(shlex.quote(f) for f in files)
    if "{files}" in template:
        return template.replace("{files}", joined)
    return f"{template} {joined}".strip()


def _run_logged(cmd, cwd, log, timeout, echo=True):
    """Run a shell command in its own process group, output to the log (and the terminal).
    Returns (rc, seconds, tail). A timeout kills the group: rc 124."""
    t0 = time.time()
    with open(log, "a", encoding="utf-8") as lf:
        lf.write(f"\n$ {cmd}    [{time.strftime('%H:%M:%S')}, in {cwd}]\n")
        lf.flush()
        proc = subprocess.Popen(cmd, shell=True, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, start_new_session=True,
                                env={**os.environ, "CI": os.environ.get("CI", "1")})
        lines = []
        deadline = t0 + timeout
        try:
            for line in proc.stdout:
                lf.write(line)
                lines.append(line)
                if len(lines) > 400:
                    lines = lines[-300:]
                if echo:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                if time.time() > deadline:
                    raise subprocess.TimeoutExpired(cmd, timeout)
            rc = proc.wait(timeout=max(1, deadline - time.time()))
        except subprocess.TimeoutExpired:
            _killpg(proc.pid)
            rc = 124
            lf.write(f"\n[killed after {timeout}s]\n")
            if echo:
                print(f"\n[killed after {timeout}s]")
    return rc, round(time.time() - t0, 1), "".join(lines[-60:])


def _killpg(pid, grace=10):
    try:
        pg = os.getpgid(int(pid))
    except (OSError, TypeError, ValueError):
        return
    try:
        os.killpg(pg, signal.SIGTERM)
    except OSError:
        return
    t0 = time.time()
    while time.time() - t0 < grace:
        try:
            os.killpg(pg, 0)
        except OSError:
            return
        time.sleep(0.25)
    try:
        os.killpg(pg, signal.SIGKILL)
    except OSError:
        pass


# --- state ------------------------------------------------------------------

def _healthy(c, timeout=3):
    url = c.get("health")
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def health_probe(c, timeout=3):
    """(answered, what it said) for the health URL; (None, "") when none is set."""
    url = c.get("health")
    if not url:
        return None, ""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"no answer ({getattr(e, 'reason', None) or e.__class__.__name__})"


def status(p, probe_health=True):
    """{"state": none|down|up|starting|unhealthy|ab|held, ...} with what the page and the
    spirit show. Never changes anything."""
    c = conf(p)
    d = Path(p.dir) / "lab"
    st = _read(d / "state.json") or {}
    out = {"configured": bool(c["test"] or c["up"]), "server": bool(c["up"]), "test": bool(c["test"]),
           "gate_last": _read(d / "gate-last.json"), "ab_last": _last_ab(p)}
    inflight = _read(d / "ab-inflight.json")
    if inflight:
        out["ab_inflight"] = inflight
        if not _alive(inflight.get("pid")) and inflight.get("method") == "in-place":
            out["state"] = "held"
            out["detail"] = f"an A/B died with your work saved under {inflight.get('ref')}; `operator lab restore` (or any acting lab verb) puts it back"
            return out
    pid = st.get("pid")
    if c["up"] and pid and _alive(pid):
        h = _healthy(c) if probe_health else None
        out.update(pid=pid, since=st.get("started"))
        if h is False:
            out["state"] = "starting" if time.time() - (st.get("started") or 0) < c["up_timeout"] else "unhealthy"
        else:
            out["state"] = "up"
    elif c["up"]:
        out["state"] = "down"
    else:
        out["state"] = "none" if not c["test"] else "ready"
    gating = _read(d / "gate-inflight.json")
    if inflight and _alive(inflight.get("pid")):
        out["state_server"] = out["state"]
        out["state"] = "ab"
    elif gating and _alive(gating.get("pid")):
        out["state_server"] = out["state"]
        out["state"] = "gate"
        out["gating"] = gating
    return out


def _last_ab(p):
    path = Path(p.dir) / "lab" / "ab.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def ab_results(p, ticket, unit):
    """Every A/B filed under this ticket's unit, oldest first."""
    out = []
    try:
        lines = (Path(p.dir) / "lab" / "ab.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("ticket") == ticket and r.get("unit") == unit:
            out.append(r)
    return out


def gate_results(p, ticket, unit):
    out = []
    try:
        lines = (Path(p.dir) / "lab" / "gates.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("ticket") == ticket and r.get("unit") == unit:
            out.append(r)
    return out


def _append(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


# --- verbs -------------------------------------------------------------------

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOCAL_URL = re.compile(r"(https?)://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]|\[::\])(?::(\d{2,5}))?(/[^\s'\"<>)]*)?", re.I)
PORT_LINE = re.compile(r"(?i)\b(?:port|listening on|listening at|running on)\b\D{0,12}?(\d{4,5})\b")


def url_from_output(text):
    """The local address a server printed as it started (`Local: http://localhost:5173/`,
    `listening on port 3355`), or None."""
    text = ANSI.sub("", text or "")
    m = LOCAL_URL.search(text)
    if m:
        scheme, _host, port, path = m.groups()
        return f"{scheme.lower()}://localhost{':' + port if port else ''}{path or '/'}"
    m = PORT_LINE.search(text)
    if m:
        return f"http://localhost:{m.group(1)}/"
    return None


def _group_pids(pgid):
    out = set()
    try:
        r = subprocess.run(["ps", "-A", "-o", "pid=,pgid="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for line in r.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == str(pgid):
            out.add(int(parts[0]))
    return out


def listening_ports(pgid):
    """TCP ports the server's process group listens on: lsof (macOS, most Linux), else ss."""
    ports = []
    if shutil.which("lsof"):
        try:
            r = subprocess.run(["lsof", "-nP", "-a", "-iTCP", "-sTCP:LISTEN", "-g", str(pgid), "-Fn"],
                               capture_output=True, text=True, timeout=10).stdout
            ports = [int(x.rsplit(":", 1)[1]) for x in r.splitlines() if x.startswith("n") and ":" in x
                     and x.rsplit(":", 1)[1].isdigit()]
        except (OSError, subprocess.SubprocessError):
            ports = []
    if not ports and shutil.which("ss"):
        pids = _group_pids(pgid)
        try:
            r = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            r = ""
        for line in r.splitlines():
            found = {int(x) for x in re.findall(r"pid=(\d+)", line)}
            cols = line.split()
            if found & pids and len(cols) >= 4 and cols[3].rsplit(":", 1)[-1].isdigit():
                ports.append(int(cols[3].rsplit(":", 1)[1]))
    return sorted(set(ports))


def up(p, echo=True, owner=None):
    """Start the server and wait until it answers. With no health URL set, the address is
    found: in what the server prints as it starts, else in the port it listens on; the
    address found is saved as `health` so status and later runs ask it."""
    c = conf(p)
    if not c["up"]:
        return "no server is configured ([lab] up in project.toml): nothing to bring up"
    d = lab_dir(p)
    st = _read(d / "state.json") or {}
    if st.get("pid") and _alive(st["pid"]):
        if _healthy(c) is not False:
            return f"the lab is already up (pid {st['pid']})"
        _killpg(st["pid"])
    log = d / "server.log"
    lf = open(log, "a", encoding="utf-8")
    lf.write(f"\n=== up {time.strftime('%Y-%m-%d %H:%M:%S')}: {c['up']}\n")
    lf.flush()
    offset = lf.tell()
    proc = subprocess.Popen(c["up"], shell=True, cwd=str(p.repo), stdout=lf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True,
                            env={**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0"})
    lf.close()
    state = {"pid": proc.pid, "started": time.time(), "cmd": c["up"], "owner": owner}
    _write(d / "state.json", state)
    t0, url, source, said = time.time(), c["health"] or None, "set" if c["health"] else None, ""
    while time.time() - t0 < c["up_timeout"]:
        if proc.poll() is not None:
            _write(d / "state.json", {})
            raise LabError(f"the server exited (rc {proc.returncode}) before it was up; "
                           f"the last lines of {log}:\n{_tail(log, 30)}")
        if not url:
            try:
                with open(log, encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    url = url_from_output(f.read())
                source = "found in the server's output" if url else None
            except OSError:
                pass
        if not url and time.time() - t0 > 3:
            ports = listening_ports(proc.pid)
            if ports:
                url, source = f"http://localhost:{ports[0]}/", f"found from the port it listens on ({ports[0]})"
        if url:
            ok, said = health_probe({"health": url}, timeout=2)
            if ok:
                if source != "set":
                    set_keys(p, {"health": url})
                    p.lab = dict(p.lab or {}, health=url)
                state.update(health=url, health_source=source)
                _write(d / "state.json", state)
                return (f"the lab is up (pid {proc.pid}, {time.time() - t0:.0f}s): {url} answers {said}"
                        + ("" if source == "set" else f" ({source}; saved as health)"))
        time.sleep(1)
    _killpg(proc.pid)
    _write(d / "state.json", {})
    where = (f"{url} did not answer ({said})" if url else
             "it printed no local address and listens on no TCP port")
    raise LabError(f"the server was not up within {c['up_timeout']}s: {where}. Set the address yourself with "
                   f"operator lab config health \"<url>\" if it is unusual; the last lines of {log}:\n{_tail(log, 30)}")


def restart(p):
    down(p)
    return up(p)


def down(p):
    c = conf(p)
    d = lab_dir(p)
    st = _read(d / "state.json") or {}
    if c["down"]:
        subprocess.run(c["down"], shell=True, cwd=str(p.repo), capture_output=True, timeout=120)
    if st.get("pid"):
        _killpg(st["pid"])
    _write(d / "state.json", {})
    return "the lab is down"


def _tree_stamp(repo):
    """A name for the working tree as it stands: tracked and untracked (not ignored) files."""
    idx = Path(repo) / _git(repo, "rev-parse", "--git-path", "hearthwork-stamp-index")
    env = {"GIT_INDEX_FILE": str(idx)}
    try:
        _git(repo, "read-tree", "HEAD", env=env)
        _git(repo, "add", "-A", env=env)
        return _git(repo, "write-tree", env=env)
    finally:
        try:
            idx.unlink()
        except OSError:
            pass


def build(p, force=False, cwd=None, echo=True):
    c = conf(p)
    if not c["build"]:
        return 0, "no build is configured"
    d = lab_dir(p)
    where = Path(cwd or p.repo)
    stamp = None
    if cwd is None:
        try:
            stamp = _tree_stamp(p.repo)
        except LabError:
            stamp = None
        last = _read(d / "build.json") or {}
        if not force and stamp and last.get("stamp") == stamp and last.get("rc") == 0:
            return 0, "the build is fresh for this tree (operator lab build --force rebuilds)"
    rc, secs, _ = _run_logged(c["build"], where, d / "build.log", c["build_timeout"], echo=echo)
    if cwd is None:
        _write(d / "build.json", {"stamp": stamp, "rc": rc, "at": time.time(), "seconds": secs})
    return rc, f"build rc {rc} in {secs}s"


def gate(p, files, cwd=None, echo=True):
    c = conf(p)
    if not c["test"]:
        raise LabError("no test command is configured: operator lab config test \"<command with {files}>\"", 2)
    rel = _files(p, files, cwd)
    d = lab_dir(p)
    _write(d / "gate-inflight.json", {"pid": os.getpid(), "files": rel, "at": time.time()})
    try:
        rc, secs, tail = _run_logged(_cmd(c["test"], rel), p.repo, d / "gate.log", c["gate_timeout"], echo=echo)
    finally:
        try:
            (d / "gate-inflight.json").unlink()
        except OSError:
            pass
    rec = {"at": time.time(), "files": rel, "rc": rc, "seconds": secs, **_tag(p)}
    _write(d / "gate-last.json", rec)
    _append(d / "gates.jsonl", rec)
    return rc


def lint(p, files=(), echo=True):
    c = conf(p)
    if not c["lint"]:
        raise LabError("no lint command is configured: operator lab config lint \"<command>\"", 2)
    rel = _files(p, files) if files else []
    cmd = _cmd(c["lint"], rel) if rel else c["lint"].replace("{files}", "").strip()
    rc, _, _ = _run_logged(cmd, p.repo, lab_dir(p) / "lint.log", c["gate_timeout"], echo=echo)
    return rc


def _tail(path, n):
    try:
        return "".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines(True)[-n:])
    except OSError:
        return ""


def logs(p, n=60):
    d = lab_dir(p)
    parts = []
    for name in ("server.log", "build.log", "gate.log", "ab.log"):
        t = _tail(d / name, n)
        if t:
            parts.append(f"=== {name}\n{t}")
    return "\n".join(parts) or "no lab logs yet"


# --- the carried A/B ---------------------------------------------------------

def _snapshot(repo):
    """Save the working tree (tracked changes and new files) as a commit under a ref, the
    real index aside. Returns the marker fields."""
    tree = _tree_stamp(repo)
    head_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    if tree == head_tree:
        raise LabError("the tree is clean: there is no uncommitted work to compare with HEAD", 2)
    commit = _git(repo, "commit-tree", tree, "-p", "HEAD", "-m", "hearthwork lab: the carried work")
    ref = REF_PREFIX + time.strftime("%Y%m%dT%H%M%S")
    _git(repo, "update-ref", ref, commit)
    return {"ref": ref, "tree": tree, "commit": commit}


def _changed(repo, tree):
    """(status, path) for every path the carried tree changes against HEAD."""
    out = []
    raw = _git(repo, "diff-tree", "-r", "--no-renames", "--name-status", "-z", "HEAD^{tree}", tree, text=True)
    parts = [x for x in raw.split("\0") if x]
    for i in range(0, len(parts) - 1, 2):
        out.append((parts[i][0], parts[i + 1]))
    return out


def _to_base(repo, changed, held):
    for status_, path in changed:
        if path in held:
            continue
        full = Path(repo) / path
        if status_ == "A":
            if full.exists() or full.is_symlink():
                full.unlink()
        else:
            _git(repo, "restore", "--source=HEAD", "--worktree", "--", path)


def _restore(repo, marker):
    """Put the carried work back from its ref and the real index from its copy, then prove it."""
    commit, tree = marker["commit"], marker["tree"]
    for status_, path in _changed(repo, tree):
        full = Path(repo) / path
        if status_ == "D":
            if full.exists() or full.is_symlink():
                full.unlink()
        else:
            _git(repo, "restore", f"--source={commit}", "--worktree", "--", path)
    idx = marker.get("index_copy")
    if idx and Path(idx).exists():
        real = Path(repo) / _git(repo, "rev-parse", "--git-path", "index")
        shutil.copy2(idx, real)
    now = _tree_stamp(repo)
    if now != tree:
        raise LabError(f"RESTORE: NOT VERIFIED. Your work is safe under the git ref {marker['ref']} "
                       f"(git restore --source={marker['ref']} --worktree -- . puts it back). Stop and report.", 1)
    _git(repo, "update-ref", "-d", marker["ref"])
    if idx:
        try:
            Path(idx).unlink()
        except OSError:
            pass
    return "RESTORE: VERIFIED"


def reap_orphan_server(p, echo=print):
    """A server a loop run raised and never took down (the run died) is taken down."""
    st = _read(Path(p.dir) / "lab" / "state.json") or {}
    if st.get("owner") and not _alive(st["owner"]) and st.get("pid") and _alive(st["pid"]):
        down(p)
        if echo:
            echo(f"the lab's server (pid {st['pid']}) was left up by a run that ended; it is down now")
        return True
    return False


def recover(p, echo=print):
    """An A/B that died (the caller killed, the machine restarted) is finished here: an
    in-place one gets your work back and proven; a worktree one gets its worktree removed."""
    d = Path(p.dir) / "lab"
    marker = _read(d / "ab-inflight.json")
    if not marker or _alive(marker.get("pid")):
        return None
    msg = "the throwaway worktree of an A/B that died was removed"
    if marker.get("method") == "in-place" and marker.get("ref"):
        msg = "an A/B died mid-run; your work was restored from " + marker["ref"] + ": " + _restore(p.repo, marker)
    _drop_worktree(p)
    try:
        (d / "ab-inflight.json").unlink()
    except OSError:
        pass
    if echo:
        echo(msg)
    return msg


def _wt_path(p):
    return Path(p.dir) / "lab" / "ab-worktree"


def _drop_worktree(p):
    wt = _wt_path(p)
    if wt.exists():
        subprocess.run(["git", "-C", str(p.repo), "worktree", "remove", "--force", str(wt)], capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)
    subprocess.run(["git", "-C", str(p.repo), "worktree", "prune"], capture_output=True)


def _verdict(carried_rc, base_rc):
    if carried_rc == 0 and base_rc != 0:
        return "GUARDS"
    if carried_rc == 0 and base_rc == 0:
        return "PASSES-WITHOUT-CHANGE"
    if carried_rc != 0 and base_rc == 0:
        return "BROKEN-BY-CHANGE"
    return "RED-AT-BOTH"


VERDICT_LINE = {
    "GUARDS": "red without the change, green with it: the test guards the change",
    "PASSES-WITHOUT-CHANGE": "green with and without the change: the test does not prove the change",
    "BROKEN-BY-CHANGE": "green at HEAD, red with the change: the change broke it",
    "RED-AT-BOTH": "red with and without the change: it fails for another reason",
}


def ab_plan(p, files):
    """What an A/B would do, without doing it."""
    c = conf(p)
    if not c["test"]:
        raise LabError("no test command is configured: operator lab config test \"<command with {files}>\"", 2)
    rel = _files(p, files)
    tree = _tree_stamp(p.repo)
    if tree == _git(p.repo, "rev-parse", "HEAD^{tree}"):
        raise LabError("the tree is clean: there is no uncommitted work to compare with HEAD", 2)
    changed = _changed(p.repo, tree)
    swapped = [f"{s} {x}" for s, x in changed if x not in rel]
    lines = [f"method: {c['ab']}", f"test: {_cmd(c['test'], rel)}",
             f"kept in both arms: {', '.join(rel)}",
             f"taken back to HEAD for BASE ({len(swapped)}): " + (", ".join(swapped) or "nothing"),
             ]
    if not swapped:
        lines.append("REFUSED: nothing but the named files changed, so BASE would equal CARRIED")
    return "\n".join(lines)


def ab_body(p, files):
    """Run in its own session; never by a person. Prints as it goes; writes the result."""
    c = conf(p)
    d = lab_dir(p)
    rel = _files(p, files)
    tag = _tag(p)
    marker = {"pid": os.getpid(), "files": rel, "method": c["ab"], "at": time.time(), **tag}
    tree = _tree_stamp(p.repo)
    if tree == _git(p.repo, "rev-parse", "HEAD^{tree}"):
        raise LabError("the tree is clean: there is no uncommitted work to compare with HEAD", 2)
    changed = _changed(p.repo, tree)
    if not [x for _, x in changed if x not in rel]:
        raise LabError("nothing but the named files changed: BASE would equal CARRIED", 2)
    result = {"at": time.time(), "files": rel, "method": c["ab"], **tag}
    log = d / "ab.log"
    print(f"CARRIED: the named tests on your uncommitted work", flush=True)
    if c["ab"] == "in-place":
        snap = _snapshot(p.repo)
        idx_copy = d / "ab-index"
        real_idx = Path(p.repo) / _git(p.repo, "rev-parse", "--git-path", "index")
        if real_idx.exists():
            shutil.copy2(real_idx, idx_copy)
        marker.update(snap, index_copy=str(idx_copy) if real_idx.exists() else None)
        _write(d / "ab-inflight.json", marker)
        server_up = status(p, probe_health=False)["state"] in ("up", "starting", "unhealthy")
        try:
            if server_up and c["build"]:
                build(p)
                restart(p)
            rc_c, s_c, _ = _run_logged(_cmd(c["test"], rel), p.repo, log, c["gate_timeout"])
            print(f"\nBASE: HEAD with the named files kept", flush=True)
            _to_base(p.repo, changed, set(rel))
            if server_up:
                if c["build"]:
                    build(p, force=True)
                restart(p)
            rc_b, s_b, _ = _run_logged(_cmd(c["test"], rel), p.repo, log, c["gate_timeout"])
        finally:
            restored = _restore(p.repo, marker)
            print(restored, flush=True)
            try:
                (d / "ab-inflight.json").unlink()
            except OSError:
                pass
            if server_up:
                if c["build"]:
                    build(p, force=True)
                restart(p)
        result["restore"] = "verified"
    else:
        _write(d / "ab-inflight.json", marker)
        try:
            rc_c, s_c, _ = _run_logged(_cmd(c["test"], rel), p.repo, log, c["gate_timeout"])
            print(f"\nBASE: HEAD in a throwaway worktree, the named files kept", flush=True)
            _drop_worktree(p)
            wt = _wt_path(p)
            _git(p.repo, "worktree", "add", "--detach", str(wt), "HEAD")
            for f in rel:
                dst = wt / f
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(p.repo) / f, dst)
            share = c["share"] if c["share"] is not None else [s for s in SHARE_GUESS if (Path(p.repo) / s).is_dir()]
            for s in share:
                src, dst = Path(p.repo) / s, wt / s
                if src.exists() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.symlink(src, dst)
            if c["build"]:
                rcb, _ = build(p, cwd=wt)
                if rcb != 0:
                    print("BASE: the build failed in the worktree; BASE counts as red", flush=True)
            rc_b, s_b, _ = _run_logged(_cmd(c["test"], rel), wt, log, c["gate_timeout"])
        finally:
            _drop_worktree(p)
            try:
                (d / "ab-inflight.json").unlink()
            except OSError:
                pass
    v = _verdict(rc_c, rc_b)
    result.update(carried={"rc": rc_c, "seconds": s_c}, base={"rc": rc_b, "seconds": s_b}, verdict=v)
    _append(d / "ab.jsonl", result)
    print(f"\nAB VERDICT: {v} — {VERDICT_LINE[v]} (CARRIED rc {rc_c}, BASE rc {rc_b})", flush=True)
    return 0


def ab(p, files, wait=1200):
    """Start the A/B detached and follow its log. The caller may die; the A/B finishes."""
    d = lab_dir(p)
    marker = _read(d / "ab-inflight.json")
    if marker and _alive(marker.get("pid")):
        print(f"an A/B is already running (pid {marker['pid']}); following it")
        return follow(p, wait)
    _files(p, files)  # refuse before starting anything
    run_id = time.strftime("%Y%m%dT%H%M%S")
    old = sorted(d.glob("ab-*.out"))
    for o in old[:-9]:
        for x in (o, o.with_suffix(".rc")):
            try:
                x.unlink()
            except OSError:
                pass
    out = d / f"ab-{run_id}.out"
    cmd = [sys.executable, "-m", "hearthwork", "lab", "-p", p.name, "_ab-body", "--", *files]
    with open(out, "w") as f:
        proc = subprocess.Popen(cmd, cwd=str(p.repo), stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True, env={**os.environ, "HEARTHWORK_AB_OUT": str(out)})
    _write(d / "ab-current.json", {"out": str(out), "pid": proc.pid, "files": list(files), "at": time.time()})
    rc = follow(p, wait)
    proc.poll()
    return rc


def follow(p, wait=1200):
    """Print the running (or last) A/B's output as it comes, and its exit code."""
    d = lab_dir(p)
    cur = _read(d / "ab-current.json")
    if not cur:
        print("no A/B has run yet")
        return 2
    out = Path(cur["out"])
    rcfile = out.with_suffix(".rc")
    pos, t0 = 0, time.time()
    while True:
        try:
            with open(out, encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
        except OSError:
            pass
        if rcfile.exists():
            try:
                return int(rcfile.read_text().strip() or 1)
            except ValueError:
                return 1
        if not _alive(cur["pid"]):
            time.sleep(0.5)
            if rcfile.exists():
                continue
            print("\nthe A/B process ended without an exit code; operator lab status says what it left")
            return 1
        if time.time() - t0 > wait:
            print(f"\nstill running after {wait}s; `operator lab ab --last` follows it again")
            return 1
        time.sleep(0.5)


# --- configuration -------------------------------------------------------------

NOT_A_VALUE = ("unknown", "not needed", "none", "n/a", "no ", "-", "not applicable", "nothing")


def _value(raw, key):
    """The command an atlas line proposes: its first `code span`, else the text before its
    source bracket or first clause; nothing when the line says there is none."""
    import re
    raw = raw.strip()
    m = re.search(r"`([^`]+)`", raw)
    val = m.group(1).strip() if m else re.split(r"\s+\[|[,;]\s|\.\s|\s+\(", raw, maxsplit=1)[0].strip().rstrip(".")
    if key == "ab":
        val = val.split()[0].strip(",.") if val else ""
        return val if val in ("worktree", "in-place") else ""
    if not val or val.lower().startswith(NOT_A_VALUE):
        return ""
    return val


def from_atlas(atlas_text):
    """The [lab] keys an atlas proposes, from lines like `- lab test: pytest -q {files}`
    under its "## The lab" section."""
    import re
    out, inside = {}, False
    for line in atlas_text.splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == "## the lab"
            continue
        if not inside:
            continue
        m = re.match(r"^\s*[-*]\s*lab\s+([a-z_]+)\s*:\s*(.*)$", line)
        if m and m.group(1) in KEYS:
            val = _value(m.group(2), m.group(1))
            if val:
                out[m.group(1)] = val
    if "test" not in out:
        test = test_from_run_line(atlas_text)
        if test:
            out["test"] = test
    return out


def has_lab_section(atlas_text):
    return any(line.strip().lower() == "## the lab" for line in atlas_text.splitlines())


TEST_PATH = re.compile(r"^[\w./@:-]*[/.][\w./@:-]*$")


def test_from_run_line(atlas_text):
    """An atlas drafted before it had a lab section still names how to run one test file
    ("- Run one test file: npx vitest run src/cart.spec.ts [package.json]"). Its example
    path becomes {files}: `npx vitest run {files}`. None when no such line, or no path in it."""
    m = re.search(r"(?im)^\s*[-*]\s*run one test file\s*:\s*(.+)$", atlas_text)
    if not m:
        return None
    cmd = _value(m.group(1), "test")
    if not cmd:
        return None
    words = cmd.split()
    for i in range(len(words) - 1, 0, -1):
        w = words[i].strip("'\"")
        if not w.startswith("-") and TEST_PATH.match(w) and not re.match(r"^\d+(\.\d+)*$", w):
            words[i] = "{files}"
            return " ".join(words)
    return None


def check_scratch(p, rel):
    """The scratch folder is git-excluded whole: it must not hold anything git tracks."""
    rel = rel.strip().strip("/")
    if not rel or rel in (".", "..") or rel.startswith("../") or os.path.isabs(rel):
        raise LabError(f"scratch must be a folder inside the checkout, not {rel!r}", 2)
    tracked = _git(p.repo, "ls-files", "--", rel, check=False)
    if tracked:
        raise LabError(f"{rel}/ holds files git tracks ({tracked.splitlines()[0]}, ...): the scratch folder is "
                       "excluded from git whole, so it must be a new folder, e.g. tests/_scratch", 2)
    return rel


def set_keys(p, keys):
    """Write keys into the [lab] table of project.toml, keeping the rest of the file."""
    import re
    if "scratch" in keys:
        keys = dict(keys, scratch=check_scratch(p, keys["scratch"]))
    path = Path(p.dir) / "project.toml"
    text = path.read_text(encoding="utf-8")
    if not re.search(r"(?m)^\[lab\]\s*$", text):
        text = text.rstrip("\n") + "\n\n[lab]\n"
    head, _, rest = text.partition("[lab]")
    m = re.search(r"(?m)^\[", rest)
    table, tail = (rest[:m.start()], rest[m.start():]) if m else (rest, "")
    for k, v in keys.items():
        line = f"{k} = {json.dumps(v)}"
        if re.search(rf"(?m)^{k}\s*=", table):
            table = re.sub(rf"(?m)^{k}\s*=.*$", lambda _m: line, table)
        else:
            table = table.rstrip("\n") + "\n" + line + "\n"
    write_atomic(path, head + "[lab]" + table + ("\n" if tail and not table.endswith("\n\n") else "") + tail)


def summary(p):
    """One line for the page and `operator status`."""
    s = status(p)
    state = s["state"]
    label = {"none": "—", "ready": "READY", "down": "DOWN", "up": "UP", "starting": "STARTING",
             "unhealthy": "UNHEALTHY", "ab": "A/B", "gate": "GATE", "held": "RESTORE HELD"}[state]
    return label, s


def brief(p):
    """The lab as this checkout has it, for whoever does a unit: what is configured, its state."""
    c = conf(p)
    label, _ = summary(p)
    lines = ["# THE LAB OF THIS CHECKOUT", f"state: {label}",
             f"scratch folder (git-excluded, for probes): {c['scratch']}/"]
    for k in ("test", "lint", "build", "up", "health"):
        if c[k]:
            lines.append(f"{k}: {c[k]}")
    if not c["test"]:
        lines.append("NO TEST COMMAND IS CONFIGURED: `operator lab gate` and `operator lab ab` refuse. "
                     "Run named tests with the atlas's form, under a timeout, and say in the report that "
                     "the lab is not set up.")
    return "\n".join(lines)
