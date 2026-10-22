"""The inspector: it runs your UI tests, looks at what they draw, and keeps what it finds.

    operator inspect [--file <test file>] [--units N] [--at <ref>] [--dry-run] [--detach]
    operator inspect config [<key> <value>]
    operator box [--json]
    operator release <N | file...> --ticket <ID>

Your UI tests pass on what they check: the page's structure, its computed styles. Nobody
has LOOKED at what they draw. One inspector unit takes one test file, runs it under
Playwright with tracing on, cuts the frames a user would see after each step from the
trace, and hands them to one judge call that reads the pictures against your rubric
(rubric.md in the project's inspect/ folder; WCAG 2.2 A and AA unless you change it).
What it finds goes to THE BOX (box.py), one report per test file, and stays there until
you release it into a ticket. Nothing reaches the loop unless you do.

ITS OWN GROUND: a git worktree of its own (inspect/work, detached at the commit it looks
at, the checkout's HEAD by default), and, when the tests need a server, a server of its
own on its own port. Your checkout is never touched. The [inspect] table of project.toml:

    [inspect]
    tests = "tests/e2e/**/*.spec.ts"   # the UI test files to look at (a glob from the repo root); required
    port_env = "PORT"                  # the variable your app and your Playwright config read the port from
    port = 4180                        # the inspector's port: never the one your own server uses
    command = "npx playwright test"    # how Playwright runs, from `cwd`
    cwd = ""                           # where Playwright runs from (default: the config's folder, or the root)
    config = ""                        # the Playwright config (default: playwright.config.* in cwd)
    up = ""                            # a server to start first, if Playwright's webServer does not
    build = ""                         # a build to run first, if the server needs one
    share = []                         # folders linked from your checkout (default: every node_modules)
    relook_hours = 24                  # look again at an unchanged test file this long after, if the code moved

Playwright only: the frames come from Playwright's trace. Every look is recorded under
inspect/: units.jsonl (one line per unit, its cost), captures/<commit>/uNNNN/ (frames,
the judge's prompt and answers), roster.json (what each file's latest look said).
"""

import fcntl
import glob as globmod
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import zipfile
from dataclasses import replace
from pathlib import Path

from . import box, claude, economy, fence, gitinfo, lab
from .home import doctrine, write_atomic

DEFAULTS = {"tests": "", "port_env": "", "port": 0, "command": "npx playwright test", "cwd": "", "config": "",
            "up": "", "health": "", "build": "", "share": None, "relook_hours": 24, "timeout": 1200}
KEYS = ("tests", "port_env", "port", "command", "cwd", "config", "up", "health", "build", "relook_hours")
FRAMES_PER_CALL = 40          # a judge call sees at most this many pictures; a group is split by test, never cut
MAX_FRAMES_PER_TEST = 40      # a test with more is not judged, and named
SOURCE_MAX = 60000            # a test's source over this is not judged, and named
RECONSIDER = 3                # a judgement that breaks its contract three times is a failed judgement
JUDGE_TIMEOUT = 1500
CAPTURES_KEEP_DAYS = 14
EARLY_MS, SETTLE_MS, TRANSIENT_MS = 100, 350, 150
ACTION = re.compile(r"^(press|click|dblclick|double click|hover|fill|type|focus|check|uncheck|select|selectoption|"
                    r"navigate|goto|go back|goback|drag|tap|set input files|setinputfiles|scroll|keyboard)", re.I)
VERDICTS = ("seen-ok", "findings", "not-visual", "cannot-judge")
LEVELS = ("high", "medium", "low")


class InspectError(Exception):
    """Refused or failed; the message says why. code 2 = refused (setup), 1 = failed."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- where it lives ---------------------------------------------------------------

def idir(p):
    d = box.idir(p)
    d.mkdir(parents=True, exist_ok=True)
    return d


def worktree(p):
    return idir(p) / "work"


def conf(p):
    c = dict(DEFAULTS)
    c.update({k: v for k, v in (getattr(p, "inspect", None) or {}).items() if v is not None})
    return c


def check_conf(p):
    """The setup's gaps, as plain lines; empty when the inspector can run."""
    c, gaps = conf(p), []
    if not c["tests"]:
        gaps.append('which UI test files to look at: operator inspect config tests "<glob, e.g. tests/e2e/**/*.spec.ts>"')
    if not c["port_env"] or not c["port"]:
        gaps.append("a port of its own, so it never meets your own server: operator inspect config port_env PORT "
                    "and operator inspect config port <a free port> (your app and your Playwright config must read "
                    "the port from that variable)")
    return gaps


def set_keys(p, keys):
    """Write keys into the [inspect] table of project.toml, keeping the rest of the file."""
    path = Path(p.dir) / "project.toml"
    text = path.read_text(encoding="utf-8")
    if not re.search(r"(?m)^\[inspect\]\s*$", text):
        text = text.rstrip("\n") + "\n\n[inspect]\n"
    head, _, rest = text.partition("[inspect]")
    m = re.search(r"(?m)^\[", rest)
    table, tail = (rest[:m.start()], rest[m.start():]) if m else (rest, "")
    for k, v in keys.items():
        if k not in KEYS:
            raise InspectError(f"unknown key {k!r}; the keys are {', '.join(KEYS)}", 2)
        if k in ("port", "relook_hours"):
            try:
                v = int(v)
            except ValueError:
                raise InspectError(f"{k} is a number", 2)
        line = f"{k} = {json.dumps(v)}"
        if re.search(rf"(?m)^{k}\s*=", table):
            table = re.sub(rf"(?m)^{k}\s*=.*$", lambda _m: line, table)
        else:
            table = table.rstrip("\n") + "\n" + line + "\n"
    write_atomic(path, head + "[inspect]" + table + ("\n" if tail and not table.endswith("\n\n") else "") + tail)
    p.inspect = dict(getattr(p, "inspect", None) or {}, **keys)


def rubric_path(p):
    path = idir(p) / "rubric.md"
    if not path.exists():
        write_atomic(path, doctrine("inspector", "rubric-wcag.md"))
    return path


def criteria(rubric_text):
    """The ids a "fails" or "measure" may cite: the first word of each line under '## Criteria'.
    An empty set means the rubric lists none, and any named criterion is accepted."""
    m = re.search(r"(?ims)^##\s*Criteria\s*$(.*?)(?=^##\s|\Z)", rubric_text or "")
    if not m:
        return set()
    return {ln.split()[1].rstrip(":") for ln in m.group(1).splitlines() if re.match(r"^\s*[-*]\s+\S", ln)}


# --- the worktree ------------------------------------------------------------------

def sync(p, ref="HEAD"):
    """The worktree, detached at `ref` of the checkout, with the shared folders linked.
    Returns the commit it stands at."""
    try:
        head = gitinfo.git(p.repo, "rev-parse", f"{ref}^{{commit}}").strip()
    except RuntimeError as e:
        raise InspectError(f"cannot find {ref} in the checkout: {e}", 2)
    wt = worktree(p)
    if not (wt / ".git").exists():
        if wt.exists():
            shutil.rmtree(wt)
        subprocess.run(["git", "-C", str(p.repo), "worktree", "prune"], capture_output=True)
        r = subprocess.run(["git", "-C", str(p.repo), "worktree", "add", "--detach", str(wt), head],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise InspectError(f"git worktree add failed: {r.stderr.strip()[:300]}")
    else:
        r = subprocess.run(["git", "-C", str(wt), "checkout", "-q", "--detach", "--force", head],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise InspectError(f"the inspector's worktree would not move to {head[:10]}: {r.stderr.strip()[:300]}")
    _link_shared(p, wt)
    return head


def _link_shared(p, wt):
    c = conf(p)
    share = c["share"]
    if share is None:
        share = []
        for nm in Path(p.repo).glob("**/node_modules"):
            rel = nm.relative_to(p.repo)
            if "node_modules" in rel.parts[:-1] or any(part.startswith(".") for part in rel.parts):
                continue
            share.append(str(rel))
    for s in share:
        src, dst = Path(p.repo) / s, wt / s
        if src.is_dir() and not dst.exists() and not dst.is_symlink():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src, dst)


def test_files(p):
    c = conf(p)
    wt = worktree(p)
    root = wt if wt.exists() else Path(p.repo)
    try:
        tracked = set(gitinfo.git(root, "ls-files").splitlines())
    except RuntimeError:
        tracked = set()
    hits = {str(Path(x).relative_to(root)) for x in globmod.glob(str(root / c["tests"]), recursive=True)}
    return sorted(h for h in hits if h in tracked)


def blob(p, rel, commit):
    try:
        return gitinfo.git(worktree(p), "rev-parse", f"{commit}:{rel}").strip()
    except RuntimeError:
        return None


# --- the roster: what each file's latest look said ---------------------------------

def load_roster(p):
    try:
        return json.loads((idir(p) / "roster.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mark(p, rel, head, **kw):
    with box.locked(p):
        r = load_roster(p)
        r[rel] = dict(kw, audited_commit=head, audited_at=now_iso(), blob=blob(p, rel, head))
        write_atomic(idir(p) / "roster.json", json.dumps(r, indent=1, sort_keys=True) + "\n")


def _epoch(iso):
    try:
        return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (TypeError, ValueError):
        return 0.0


def queue(p, head):
    """The files due a look, each with its reason: never looked at first, then released files
    to verify, then a file that changed, then an old look whose code has moved since."""
    roster, released, shared = load_roster(p), box.released_files(p, head), box.shared_moved(p, head)
    hours = float(conf(p)["relook_hours"] or 24)
    q = []
    for rel in test_files(p):
        r = roster.get(rel) or {}
        if not r.get("audited_commit"):
            q.append((0, "", rel, "never looked at"))
        elif rel in released:
            q.append((1, r["audited_at"], rel, "released: is it fixed?"))
        elif rel in shared:
            q.append((1, r["audited_at"], rel, "a control it shares was looked at again"))
        elif r.get("blob") != blob(p, rel, head):
            q.append((2, r["audited_at"], rel, "the test file changed"))
        elif r["audited_commit"] != head and time.time() - _epoch(r.get("audited_at")) > hours * 3600:
            try:
                subprocess.run(["git", "-C", str(worktree(p)), "diff", "--quiet", r["audited_commit"], head],
                               check=True, capture_output=True)
            except subprocess.CalledProcessError:
                q.append((3, r["audited_at"], rel, "the code moved since the last look"))
    q.sort()
    return [(rel, why) for _, _, rel, why in q]


# --- capture: the test drives the page, the trace keeps the pictures ----------------

def _cwd_and_config(p, root=None):
    c, wt = conf(p), Path(root or worktree(p))
    if c["config"]:
        cfg = wt / c["config"]
        cwd = wt / c["cwd"] if c["cwd"] else cfg.parent
    else:
        cwd = wt / c["cwd"] if c["cwd"] else wt
        found = sorted(cwd.glob("playwright.config.*"))
        if not found:
            raise InspectError(f"no playwright.config.* in {cwd.relative_to(wt) if cwd != wt else 'the repository root'}: "
                               "name it with operator inspect config config <path>", 2)
        cfg = found[0]
    if not cfg.exists():
        raise InspectError(f"the Playwright config {cfg.relative_to(wt)} is not in the repository at this commit", 2)
    return cwd, cfg


def wrapper_config(cwd, cfg):
    """An untracked config beside yours, the same in all but one thing: a trace and a
    screenshot at the end of every test."""
    ts = cfg.suffix in (".ts", ".mts", ".cts")
    name = "hearthwork.inspect.config." + ("ts" if ts else "mjs")
    rel = os.path.relpath(cfg, cwd)
    imp = ("./" + rel) if not rel.startswith(".") else rel
    if ts:
        imp = re.sub(r"\.(c|m)?ts$", "", imp)
    body = ("// Written by hearthwork's inspector; untracked, never committed. Your config, with a\n"
            "// trace and a screenshot at the end of every test.\n"
            f"import base from '{imp}';\n"
            "const look = (u) => ({ ...(u || {}), trace: 'on', screenshot: 'on' });\n"
            "export default { ...base, use: look(base.use),\n"
            "  projects: (base.projects || []).map((p) => ({ ...p, use: look(p.use) })) };\n")
    path = cwd / name
    if not path.exists() or path.read_text(encoding="utf-8") != body:
        path.write_text(body, encoding="utf-8")
    return path


def _exclude(repo, path):
    """Keep a file the inspector writes into your checkout out of git (.git/info/exclude)."""
    try:
        exclude = Path(repo) / gitinfo.git(repo, "rev-parse", "--git-path", "info/exclude").strip()
        line = "/" + str(Path(path).resolve().relative_to(Path(repo).resolve()))
        have = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if line not in have:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with open(exclude, "a", encoding="utf-8") as f:
                f.write(("" if not have or have[-1] == "" else "\n") + f"# hearthwork inspector\n{line}\n")
    except (RuntimeError, OSError, ValueError):
        pass


def port_env(p):
    c = conf(p)
    return {str(c["port_env"]): str(c["port"])}


def capture(p, rel, capdir, root=None):
    """Run one test file. Returns (tests, output, seconds); tests is None when Playwright gave
    no report. It runs through the wrapper config beside yours, which adds the trace and the end
    screenshot; in your checkout (root given) the wrapper is git-excluded and removed after."""
    c, wt = conf(p), Path(root or worktree(p))
    cwd, cfg = _cwd_and_config(p, wt)
    wrap = wrapper_config(cwd, cfg)
    if root is not None:
        _exclude(wt, wrap)
    capdir.mkdir(parents=True, exist_ok=True)
    report = capdir / "report.json"
    cmd = shlex.split(c["command"]) + [os.path.relpath(wt / rel, cwd), f"--config={os.path.relpath(wrap, cwd)}",
                                       "--trace=on", "--workers=1", f"--output={capdir / 'results'}",
                                       "--reporter=json"]
    env = dict(os.environ, PLAYWRIGHT_JSON_OUTPUT_NAME=str(report), FORCE_COLOR="0", **port_env(p))
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=env, timeout=int(c["timeout"]))
        said = (r.stdout or "")[-4000:] + (r.stderr or "")[-4000:]
    except subprocess.TimeoutExpired:
        return None, f"Playwright ran past {c['timeout']}s", round(time.time() - t0, 1)
    except FileNotFoundError as e:
        return None, f"cannot run {c['command']}: {e}", round(time.time() - t0, 1)
    finally:
        if root is not None:
            wrap.unlink(missing_ok=True)
    try:
        rep = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, said, round(time.time() - t0, 1)
    tests = []

    def walk(suite, titles):
        for sp in suite.get("specs") or []:
            for t in sp.get("tests") or []:
                res = (t.get("results") or [{}])[-1]
                att = res.get("attachments") or []
                tests.append({
                    "title": " › ".join(x for x in titles + [sp.get("title")] if x),
                    "project": t.get("projectName"), "status": res.get("status"),
                    "trace": next((a.get("path") for a in att if a.get("name") == "trace"), None),
                    "end_shot": next((a.get("path") for a in att if a.get("name") == "screenshot" and a.get("path")), None),
                    "error": ((res.get("error") or {}).get("message") or "")[:400]})
        for s in suite.get("suites") or []:
            t = s.get("title") or ""
            walk(s, titles + ([t] if t and not re.search(r"\.(spec|test)\.[a-z]+$|\.[mc]?[jt]sx?$", t) else []))
    for s in rep.get("suites") or []:
        walk(s, [])
    return tests, said, round(time.time() - t0, 1)


def _events(z, name):
    out = []
    for line in z.read(name).decode("utf-8", "replace").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def key_frames(trace_path, frames_dir, prefix):
    """The frames a user would see: the state after every action (the last frame before the
    next action begins) and the picture at every assertion. Every frame carries its timing
    and a flag when it cannot prove an absence (EARLY, SETTLING, TRANSIENT, STALE)."""
    z = zipfile.ZipFile(trace_path)
    names = set(z.namelist())
    steps = _events(z, "test.trace") if "test.trace" in names else []
    frames = []
    for n in names:
        if n.endswith(".trace") and n != "test.trace":
            for e in _events(z, n):
                if e.get("type") == "screencast-frame" and e.get("sha1"):
                    frames.append((e.get("timestamp") or 0, e["sha1"]))
    frames.sort()
    ends = {e.get("callId"): e.get("endTime") for e in steps if e.get("type") == "after"}
    moments = []
    for e in steps:
        if e.get("type") != "before" or e.get("parentId"):
            continue
        title, cat = e.get("title") or "", e.get("category") or e.get("method") or ""
        end = ends.get(e.get("callId")) or e.get("startTime")
        if cat == "expect" or title.lower().startswith("expect"):
            moments.append(("claim", e.get("startTime"), end, title))
        elif cat == "pw:api" and ACTION.match(title):
            moments.append(("action", e.get("startTime"), end, title))
    moments = [m for m in moments if m[1] is not None]
    moments.sort(key=lambda m: m[1])
    picked, last_action_end = [], None
    for i, (kind, st, en, title) in enumerate(moments):
        nxt = next((m[1] for m in moments[i + 1:] if m[0] == "action"), None)
        flags = []
        if kind == "action":
            window = [f for f in frames if f[0] >= en and (nxt is None or f[0] <= nxt)]
            if window:
                cand = window[-1]
            else:
                before = [f for f in frames if f[0] <= en]
                cand = before[-1] if before else None
                flags.append("STALE")
            ref = last_action_end = en
        else:
            before = [f for f in frames if f[0] <= en + 5]
            cand = before[-1] if before else None
            ref = last_action_end if last_action_end is not None else st
            if cand is not None and last_action_end is not None and cand[0] < last_action_end:
                flags.append("STALE")
        if cand is None:
            continue
        after_ms = int(round(cand[0] - ref))
        lasted = int(round(nxt - ref)) if nxt is not None else None
        if "STALE" not in flags:
            if after_ms < EARLY_MS:
                flags.append("EARLY")
            elif after_ms < SETTLE_MS:
                flags.append("SETTLING")
        if lasted is not None and lasted < TRANSIENT_MS:
            flags.append("TRANSIENT")
        note = f"{after_ms:+d} ms after the step" + (f"; the state lasted {lasted} ms" if lasted is not None else "") \
            + (f"; {' '.join(flags)}" if flags else "")
        if picked and picked[-1]["sha1"] == cand[1]:
            picked[-1]["after"].append(title)
            picked[-1]["flags"] = sorted(set(picked[-1]["flags"]) | set(flags))
            continue
        picked.append({"sha1": cand[1], "after": [title], "timing": note, "flags": flags})
    frames_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, pk in enumerate(picked, 1):
        src = "resources/" + pk["sha1"]
        if src not in names:
            continue
        ext = ".png" if z.read(src)[:4] == b"\x89PNG" else ".jpeg"
        fn = f"{prefix}-{i:03d}{ext}"
        (frames_dir / fn).write_bytes(z.read(src))
        out.append({"frame": fn, "after": pk["after"][:12], "timing": pk["timing"], "flags": pk["flags"]})
    return out


TEST_DECL = re.compile(r"""^\s*(?:test|it)(?:\.(?:only|skip|fixme|fail))?\(\s*(['"`])(.*?)\1""", re.M)


def test_sources(src):
    """{test title: its source block}, and the file's head under ''."""
    decls = [(m.start(), m.group(2)) for m in TEST_DECL.finditer(src)]
    out = {"": src[:decls[0][0]] if decls else src}
    for i, (pos, title) in enumerate(decls):
        out[title] = src[pos:decls[i + 1][0] if i + 1 < len(decls) else len(src)]
    return out


# --- the judge -------------------------------------------------------------------------

def validate(obj, frame_names, titles, crit):
    """The deviation, named; None when the answer keeps its contract. Normalises in place."""
    if not isinstance(obj, dict):
        return "the answer is not one JSON object"
    if obj.get("verdict") not in VERDICTS:
        return f"verdict is one of {', '.join(VERDICTS)}, not {obj.get('verdict')!r}"
    fs = obj.get("findings", [])
    if not isinstance(fs, list):
        return "findings is a list"
    for n in fs:
        if not isinstance(n, dict):
            return "each finding is an object"
        for k in ("test", "frame", "finding", "element", "judgement", "criterion", "severity", "confidence"):
            if not isinstance(n.get(k), str) or not n[k].strip():
                return f"a finding is missing {k!r}"
        if n["judgement"] not in box.JUDGEMENTS:
            return f"judgement is one of {', '.join(box.JUDGEMENTS)}, not {n['judgement']!r}"
        cid = n["criterion"].strip().split()[0].rstrip(":,;")
        if n["judgement"] in box.TO_FIX:
            if crit and cid not in crit:
                return (f"a {n['judgement']} finding cites one of the rubric's criteria ({', '.join(sorted(crit))}), "
                        f"not {n['criterion']!r}; anything else is judged other with criterion \"none\"")
            n["criterion"] = cid
        else:
            n["criterion"] = "none"
        if n["frame"] not in frame_names:
            return f"a finding cites frame {n['frame']!r}, which is not in the frame list"
        if n["test"] not in titles:
            hits = [t for t in titles if t.split(" › ")[-1] == n["test"].split(" › ")[-1]]
            if len(hits) != 1:
                return f"a finding names test {n['test'][:80]!r}, which is not in the test list"
            n["test"] = hits[0]
        if n["severity"] not in LEVELS or n["confidence"] not in LEVELS:
            return "severity and confidence are high, medium or low"
    if obj["verdict"] in ("seen-ok", "not-visual") and fs:
        return f"verdict {obj['verdict']} contradicts the findings: a visible defect makes it findings"
    if obj["verdict"] == "findings" and not fs:
        return "verdict findings with no finding"
    return None


class Judge:
    def __init__(self, p, cfg, costs):
        self.p, self.cfg, self.costs = p, cfg, costs
        self.model = cfg["models"].get("inspector") or "opus"
        self.eco = economy.load()

    def call(self, prompt, capdir, resume=None):
        policy = {"mode": "inspector", "read_root": str(capdir), "log": str(Path(self.p.dir) / "fence.log")}
        settings = fence.settings_for()
        settings["claudeMdExcludes"] = claude.doctrine_excludes(capdir)
        return claude.run(claude_bin=self.cfg["claude"]["bin"], cwd=capdir, prompt=prompt, model=self.model,
                          timeout=JUDGE_TIMEOUT, label="inspect", costs=self.costs, resume=resume, tools=["Read"],
                          setting_sources=[], settings=settings, strict_mcp=True,
                          env_extra={"HEARTHWORK_FENCE_POLICY": json.dumps(policy),
                                     **economy.ttl_env("inspector", self.eco)})

    def judge(self, rel, group, frames_by_test, blocks, capdir, rubric, crit, found, records):
        """One judgement over a group of tests; a broken answer goes back to the same session
        with the deviation named. Returns (answer | None, [calls], error | None)."""
        names, lines, srcs = set(), [], []
        for t in group:
            lines.append(f"TEST: {t['title']}   [status {t['status']}"
                         + (f"; error: {t['error'][:200]}" if t.get("error") else "") + "]")
            for f in frames_by_test[t["title"]]:
                names.add(f["frame"])
                lines.append(f"  FRAME {capdir / 'frames' / f['frame']}  after: {' | '.join(f['after'])}  [{f['timing']}]")
            s = blocks.get(t["title"].split(" › ")[-1])
            srcs.append(f"// ---- {t['title']}\n{s if s is not None else '(its source block was not found by title)'}")
        prompt = (doctrine("inspector", "JUDGE.md") + "\n=== THE RUBRIC ===\n" + rubric
                  + f"\n=== THE TEST FILE {rel} ===\n--- ITS HEAD (imports, helpers) ---\n{blocks.get('', '')[:SOURCE_MAX // 2]}"
                  + "\n--- THE TESTS YOU JUDGE ---\n" + "\n".join(srcs) + "\n\n=== FRAMES ===\n" + "\n".join(lines) + "\n")
        if found:
            prompt += ("\n=== ALREADY FOUND IN THIS LOOK (other tests of this file) ===\n"
                       + "\n".join(f"  - [{f['judgement']} {f['criterion']}] {f['element']}: {f['finding'][:200]}" for f in found)
                       + "\nDo not report these again; report only what is new.\n")
        titles = {t["title"] for t in group}
        records.append(f"### PROMPT ({len(prompt)} characters, {len(names)} frames)\n\n{prompt}")
        calls = []
        res = self.call(prompt, capdir)
        calls.append(res)
        for attempt in range(RECONSIDER):
            if not res.ok:
                return None, calls, f"the judge call failed: {res.error}"
            records.append(f"### ANSWER (try {attempt + 1})\n\n{res.text}")
            obj = claude.extract_json(res.text)
            dev = validate(obj, names, titles, crit) if obj is not None else "there is no JSON object in the answer"
            if dev is None:
                return obj, calls, None
            records.append(f"### DEVIATION\n\n{dev}")
            if attempt + 1 >= RECONSIDER:
                return None, calls, f"the answer broke its contract three times; the last: {dev}"
            res = self.call(f"DEVIATION: your answer broke its contract: {dev}\nAnswer again with the corrected "
                            "JSON object only, the same shape.", capdir, resume=res.session_id)
            calls.append(res)
        return None, calls, "unreachable"


# --- one unit ------------------------------------------------------------------------

def _proxy(p):
    """The project as the lab sees it when the inspector raises a server: its worktree for
    the checkout, the inspector's folder for the lab's state."""
    c, d = conf(p), idir(p)
    if not (d / "project.toml").exists():
        write_atomic(d / "project.toml", "# the inspector's own lab state; written by hearthwork\n[lab]\n")
    return replace(p, dir=d, repo=worktree(p),
                   lab={"up": c["up"], "build": c["build"], "health": c["health"] or None, "test": ""})


class Locked:
    def __init__(self, p):
        self.path = idir(p) / "inspect.lock"

    def __enter__(self):
        self.f = open(self.path, "w")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            raise InspectError("another inspector unit is running on this project", 2)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def next_unit(p):
    path = idir(p) / "counter"
    try:
        n = int(path.read_text().strip() or 0) + 1
    except (OSError, ValueError):
        n = 1
    path.write_text(str(n))
    return n


def prune(p, keep_days=CAPTURES_KEEP_DAYS):
    root = idir(p) / "captures"
    if not root.exists():
        return 0
    cited, cut, n = box.cited_captures(p), time.time() - keep_days * 86400, 0
    for d in root.glob("*/u*"):
        if str(d) not in cited and d.stat().st_mtime < cut:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def groups_of(judged, frames_by_test, blocks, refused):
    out, cur, nf, nc = [], [], 0, 0
    for t in judged:
        f = len(frames_by_test[t["title"]])
        c = len(blocks.get(t["title"].split(" › ")[-1]) or "")
        if c > SOURCE_MAX:
            refused.append(f"{t['title']} (its source is {c} characters)")
            continue
        if cur and (nf + f > FRAMES_PER_CALL or nc + c > SOURCE_MAX):
            out.append(cur)
            cur, nf, nc = [], 0, 0
        cur.append(t)
        nf, nc = nf + f, nc + c
    if cur:
        out.append(cur)
    return out


def run_unit(p, cfg, only=None, ref="HEAD", dry=False, log=print):
    """One look at one test file. Returns the unit's record (outcome: judged, judged-partly,
    nothing-due, or the failure) — or the queue on a dry run."""
    gaps = check_conf(p)
    if gaps:
        raise InspectError("the inspector is not set up:\n  " + "\n  ".join(gaps), 2)
    with Locked(p):
        head = sync(p, ref)
        if only:
            files = test_files(p)
            hit = [f for f in files if f == only or box.name_of(f) == box.name_of(only)]
            if not hit:
                raise InspectError(f"{only} is not one of the inspector's test files at {head[:10]}", 2)
            q = [(hit[0], "named by you")]
        else:
            q = queue(p, head)
        if dry:
            return {"outcome": "dry-run", "head": head, "queue": q}
        if not q:
            return {"outcome": "nothing-due", "head": head, "message": f"every test file is current at {head[:10]}"}
        rel, reason = q[0]
        prune(p)
        n = next_unit(p)
        capdir = idir(p) / "captures" / head[:10] / f"u{n:04d}"
        capdir.mkdir(parents=True, exist_ok=True)
        rec = {"ts": now_iso(), "unit": n, "file": rel, "reason": reason, "head": head, "phases": {}, "outcome": None}
        records, t0 = [], time.time()
        log(f"inspect unit {n}: {rel} ({reason}) at {head[:10]}")
        try:
            return _look(p, cfg, rec, rel, head, capdir, records, t0, log)
        finally:
            write_atomic(capdir / "judge.md", "\n\n".join(records) + "\n")
            rec["seconds"] = round(time.time() - t0, 1)
            with open(idir(p) / "units.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _look(p, cfg, rec, rel, head, capdir, records, t0, log):
    c = conf(p)
    raised = False
    if c["build"] or c["up"]:
        px = _proxy(p)
        saved = {k: os.environ.get(k) for k in port_env(p)}
        os.environ.update(port_env(p))
        try:
            with lab.Locked(px):
                lab.recover(px, echo=lambda *_: None)
                if c["build"]:
                    rc, msg = lab.build(px, echo=False)
                    if rc != 0:
                        rec["outcome"] = "build-failed"
                        records.append(f"### BUILD\n\n{lab.logs(px, 60)}")
                        return rec
                if c["up"] and lab.status(px)["state"] != "up":
                    log(lab.up(px, echo=False, owner=os.getpid()))
                    raised = True
        except lab.LabError as e:
            rec["outcome"] = "server-failed"
            rec["error"] = str(e)[:400]
            records.append(f"### SERVER\n\n{e}")
            return rec
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    try:
        tests, said, secs = capture(p, rel, capdir)
    finally:
        if raised:
            try:
                with lab.Locked(_proxy(p)):
                    lab.down(_proxy(p))
            except lab.LabError as e:
                log(f"the inspector's server did not go down: {e}")
    rec["phases"]["capture"] = {"seconds": secs, "tests": len(tests or [])}
    records.append(f"### CAPTURE ({secs}s)\n\n{said.strip()[-3000:]}")
    if not tests:
        rec["outcome"] = "capture-empty"
        rec["error"] = (said.strip().splitlines() or ["Playwright gave no report"])[-1][:300]
        mark(p, rel, head, verdict="cannot-judge", summary="Playwright gave no report: " + rec["error"], cost_usd=0)
        return rec
    frames_dir, frames_by_test, refused = capdir / "frames", {}, []
    for i, t in enumerate(tests, 1):
        fr = []
        if t.get("trace") and os.path.exists(t["trace"]):
            try:
                fr = key_frames(t["trace"], frames_dir, f"t{i:02d}")
            except (zipfile.BadZipFile, KeyError, OSError) as e:
                refused.append(f"{t['title']} (its trace could not be read: {e})")
        if t.get("end_shot") and os.path.exists(t["end_shot"]):
            fn = f"t{i:02d}-end.png"
            frames_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(t["end_shot"], frames_dir / fn)
            fr.append({"frame": fn, "after": ["END OF TEST — the settled page"],
                       "timing": "taken at the end of the test, full resolution", "flags": []})
        if len(fr) > MAX_FRAMES_PER_TEST:
            refused.append(f"{t['title']} ({len(fr)} frames, over {MAX_FRAMES_PER_TEST})")
        elif fr:
            frames_by_test[t["title"]] = fr
    write_atomic(capdir / "manifest.json", json.dumps({"file": rel, "commit": head, "tests": tests,
                                                       "frames": frames_by_test, "refused": refused}, indent=1) + "\n")
    n_frames = sum(len(v) for v in frames_by_test.values())
    rec["phases"]["capture"]["frames"] = n_frames
    shutil.rmtree(capdir / "results", ignore_errors=True)   # the traces: the frames are cut, the test makes them again
    judged = [t for t in tests if frames_by_test.get(t["title"])]
    if not judged:
        rec["outcome"] = "no-frames"
        mark(p, rel, head, verdict="cannot-judge", summary="no frames" + (": " + "; ".join(refused) if refused else ""),
             cost_usd=0)
        return rec
    src = (worktree(p) / rel).read_text(encoding="utf-8", errors="replace")
    blocks = test_sources(src)
    rubric = rubric_path(p).read_text(encoding="utf-8")
    crit = criteria(rubric)
    judge = Judge(p, cfg, claude.CostLedger(idir(p) / "session-cost.json"))
    results, calls, errors, judged_titles = [], [], [], set()
    for g in groups_of(judged, frames_by_test, blocks, refused):
        obj, cs, err = judge.judge(rel, g, frames_by_test, blocks, capdir, rubric, crit,
                                   [f for r in results for f in r.get("findings", [])], records)
        calls += cs
        if err:
            errors.append(err)
        else:
            results.append(obj)
            judged_titles |= {t["title"] for t in g}
    cost = round(sum(c.cost_usd or 0 for c in calls), 4)
    rec["phases"]["judge"] = {"model": judge.model, "calls": [c.record() for c in calls], "cost_usd": cost,
                              "errors": errors}
    rec["cost_usd"] = cost
    if not results:
        rec["outcome"] = "judge-failed"
        return rec
    fs = [{"test": n["test"], "frame": str(capdir / "frames" / n["frame"]), "finding": n["finding"].strip(),
           "element": n["element"].strip(), "judgement": n["judgement"], "criterion": n["criterion"],
           "severity": n["severity"], "confidence": n["confidence"], "seen_commit": head}
          for r in results for n in r.get("findings", [])]
    unjudged = {t["title"] for t in tests} - judged_titles
    carried = [f for f in box.findings_of(p, rel) if f.get("test") in unjudged]
    prev, state, n_found = box.replace_report(p, rel, head, fs, carried)
    vs = [r["verdict"] for r in results]
    v = ("findings" if "findings" in vs else "cannot-judge" if ("cannot-judge" in vs or errors or refused)
         else "seen-ok" if "seen-ok" in vs else "not-visual")
    summary = " / ".join(r.get("summary", "")[:200] for r in results)
    if refused:
        summary += " · not judged: " + "; ".join(refused)
    mark(p, rel, head, verdict=v, summary=summary[:1500], cost_usd=cost, tests=len(tests), frames=n_frames,
         error="; ".join(errors) or None, capture=str(capdir))
    rec.update(outcome="judged" if not errors else "judged-partly", verdict=v, findings=n_found,
               carried=len(carried), state=state, prev_state=prev)
    return rec


def frames_here(p, rel, echo=print):
    """`operator lab frames <test file>`: run one UI test file in YOUR CHECKOUT, uncommitted work
    and all, on the inspector's port, and cut the frames a user sees after each step into the
    scratch folder. No judge, nothing spent: the unit reads the pictures itself. Returns the exit code."""
    gaps = check_conf(p)
    if gaps:
        raise InspectError("the inspector is not set up, so its port is unknown:\n  " + "\n  ".join(gaps), 2)
    repo = Path(p.repo)
    full = (repo / rel).resolve()
    try:
        rel = str(full.relative_to(repo.resolve()))
    except ValueError:
        raise InspectError(f"{rel} is not in the checkout", 2)
    if not full.exists():
        raise InspectError(f"{rel} does not exist", 2)
    out = lab.scratch_path(p) / "frames" / box.name_of(rel)
    shutil.rmtree(out, ignore_errors=True)
    with Locked(p):
        tests, said, secs = capture(p, rel, out, root=repo)
    if not tests:
        echo(f"operator lab frames: Playwright gave no report ({secs}s). Its last lines:")
        echo("\n".join(said.strip().splitlines()[-25:]))
        return 1
    echo(f"FRAMES of {rel} at the checkout as it stands (uncommitted work included), {secs}s.")
    echo("Read each picture with the Read tool. A flagged frame (EARLY, SETTLING, TRANSIENT, STALE) never proves")
    echo("that something is missing.")
    for i, t in enumerate(tests, 1):
        echo(f"TEST: {t['title']}   [status {t['status']}]" + (f" error: {t['error'][:200]}" if t.get("error") else ""))
        fr = []
        if t.get("trace") and os.path.exists(t["trace"]):
            try:
                fr = key_frames(t["trace"], out, f"t{i:02d}")
            except (zipfile.BadZipFile, KeyError, OSError) as e:
                echo(f"  its trace could not be read: {e}")
        if t.get("end_shot") and os.path.exists(t["end_shot"]):
            fn = f"t{i:02d}-end.png"
            shutil.copyfile(t["end_shot"], out / fn)
            fr.append({"frame": fn, "after": ["END OF TEST — the settled page"],
                       "timing": "taken at the end of the test, full resolution, never flagged"})
        for f in fr:
            echo(f"  FRAME {os.path.relpath(out / f['frame'], repo)}  after: {' | '.join(f['after'])}  [{f['timing']}]")
        if not fr:
            echo("  no frames")
    shutil.rmtree(out / "results", ignore_errors=True)
    return 0


def describe(rec):
    """One line for a person: what this unit found."""
    o = rec.get("outcome")
    if o == "dry-run":
        q = rec["queue"]
        return (f"{len(q)} file(s) due at {rec['head'][:10]}" + "".join(f"\n  {r}  ({w})" for r, w in q[:10])
                + (f"\n  … and {len(q) - 10} more" if len(q) > 10 else ""))
    if o == "nothing-due":
        return rec["message"]
    name = box.name_of(rec.get("file", ""))
    if o in ("judged", "judged-partly"):
        what = {"findings": f"{rec['findings']} problem(s)", "seen-ok": "clean",
                "not-visual": "nothing visual to check: the passing test stands",
                "cannot-judge": "no usable picture: not checked"}[rec["verdict"]]
        extra = {"fixed": " · the released fix is confirmed", "still-seen": " · RELEASED BUT STILL SEEN"}.get(rec.get("state"), "")
        return f"{name}: {what}{extra}{' (partly judged)' if o == 'judged-partly' else ''} · ${rec.get('cost_usd', 0):.2f}"
    return f"{name}: {o}" + (f" — {rec['error']}" if rec.get("error") else "")
