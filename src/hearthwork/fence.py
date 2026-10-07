#!/usr/bin/env python3
"""The fence: a PreToolUse hook that every tool call of a hearthwork session passes.

Default-deny. A call is allowed only when its mode's rules allow it, and any error
inside the fence denies. It is a GUARD RAIL, not a sandbox: it keeps an honest
session inside its lane and stops the common accidents (a push, a write outside the
checkout, a read of ~/.ssh, a background job), but a determined process with a shell
can find a way past any pattern check. For unattended runs, use a separate OS user.

Modes (HEARTHWORK_FENCE_POLICY carries the policy as JSON):
  executor   works in the repository: edits inside it, a shell with git rules
  operator   plans and judges: reads and writes its own directory only, no shell
  spirit     talks with you: reads the home and the repositories, writes its memory,
             runs `operator <command>` and read-only git
"""

import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

POLICY = {}
HOME = str(Path.home())
# Scratch space, by its real path: on macOS /tmp is a link to /private/tmp, and each user also
# has a private temporary folder under /var/folders that tools use through $TMPDIR.
TMP = sorted({os.path.realpath(p) for p in ("/tmp", tempfile.gettempdir(), os.environ.get("TMPDIR") or "/tmp")})

SECRET_NAMES = re.compile(
    r"(^|/)(\.ssh|\.gnupg|\.aws|\.azure|\.kube|\.docker|\.netrc|\.pgpass|\.npmrc|\.pypirc|"
    r"\.git-credentials|\.config/gh|\.config/gcloud|\.claude/\.credentials\.json|\.claude\.json|"
    r"id_rsa|id_ed25519|id_ecdsa)(/|$)")
# Caches a build may touch under the home directory; nothing else under it is allowed.
HOME_CACHES = (".cache", ".npm", ".nvm", ".volta", ".cargo/registry", ".rustup", ".gradle",
               ".m2", ".pnpm-store", ".local/share/pnpm", ".yarn", ".bun", ".deno", "go/pkg")

ALWAYS_OK = {"TodoWrite", "ExitPlanMode", "EnterPlanMode", "StructuredOutput"}
NETWORK_CMDS = {"curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "sftp", "rsync", "telnet", "ftp", "socat"}
PRIVILEGE_CMDS = {"sudo", "su", "doas", "pkexec", "setpriv", "chroot"}
DETACH_CMDS = {"nohup", "disown", "setsid", "systemd-run", "crontab", "at", "batch", "screen", "tmux"}
SHELL_CMDS = {"eval", "exec", "sh", "bash", "zsh", "dash", "ksh", "fish"}
WRAPPERS = {"timeout", "env", "time", "nice", "ionice", "xargs", "command", "builtin", "stdbuf"}
PACKAGE_NET = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|i|add|ci|update|upgrade)\b|\bpip3?\s+install\b|"
                         r"\buv\s+(pip\s+install|add|sync)\b|\bcargo\s+(install|add|update)\b|\bgo\s+(get|install)\b")
GIT_DENY = {"push", "config", "remote", "reset", "rebase", "filter-branch", "filter-repo", "update-ref",
            "symbolic-ref", "credential", "submodule", "gc", "prune", "daemon", "fetch", "pull", "clone",
            "merge", "send-email", "request-pull", "worktree", "replace", "notes"}
READ_ONLY_DENY = {"rm", "mv", "cp", "touch", "mkdir", "rmdir", "ln", "chmod", "chown", "tee", "truncate", "dd",
                  "install", "patch", "make", "npm", "pnpm", "yarn", "bun", "npx", "cargo", "go", "mvn", "gradle",
                  "pip", "pip3", "uv", "poetry", "bundle", "gem", "composer", "docker", "podman"}
# Taking work out of the tree by hand is how a fix gets stranded: the one road to a baseline
# is `operator lab ab`, which saves the work first and proves the restore.
GIT_BASELINE = {"stash", "restore"}
LAB_SERVER_VERBS = {"up", "down", "restart", "build"}
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|specs?|e2e)/|(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go|rb|exs?)|"
                       r"[^/]*\.(test|spec)\.[A-Za-z0-9]+|[^/]*_spec\.rb|[^/]*Tests?\.(java|kt|cs|swift))$")
GIT_READ = {"status", "diff", "log", "show", "blame", "ls-files", "rev-parse", "merge-base", "rev-list",
            "describe", "shortlog", "reflog", "cat-file", "ls-tree", "name-rev", "for-each-ref", "grep", "branch"}


def log(decision, tool, reason, detail=""):
    path = POLICY.get("log")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\t%s\t%.300s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    POLICY.get("mode", "?"), decision, tool, reason, str(detail).replace("\n", " ")))
    except OSError:
        pass


def decide(decision, tool, reason, detail=""):
    log(decision, tool, reason, detail)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def allow(tool, reason="", detail=""):
    decide("allow", tool, reason or "allowed", detail)


def deny(tool, reason, detail=""):
    decide("deny", tool, "hearthwork fence: " + reason, detail)


def norm(path, cwd):
    p = os.path.expanduser(os.path.expandvars(str(path)))
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.realpath(p)


def under(path, roots):
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def secret(path):
    return bool(SECRET_NAMES.search(path)) or re.search(r"(^|/)\.env(\.[\w.-]+)?$", path) is not None and not under(path, POLICY.get("env_ok", []))


def home_cache(path):
    return under(path, [os.path.join(HOME, c) for c in HOME_CACHES])


def roots(key):
    return [os.path.realpath(os.path.expanduser(r)) for r in POLICY.get(key, [])]


# --- shell -------------------------------------------------------------------

def strip_heredocs(cmd):
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", lines[i])
        out.append(lines[i])
        i += 1
        if m:
            while i < len(lines) and lines[i].strip() != m.group(1):
                i += 1
            i += 1
    return "\n".join(out)


def path_mentions(cmd):
    """Every path-like string in the command, quoted or not. Quotes do not hide a path:
    the scan reads the raw text, so `cat "$HOME/.ssh/id_ed25519"` is seen whole."""
    text = cmd.replace("${HOME}", HOME).replace("$HOME", HOME)
    text = re.sub(r"(^|[\s='\"(:])~(?=/|\s|$|['\"])", lambda m: m.group(1) + HOME, text)
    return [m.group(0) for m in re.finditer(r"/[^\s'\"`;&|<>(){}$]*", text)]


def segments(body):
    """The simple commands of a shell line, each as argv with wrappers peeled off
    (`timeout 60 git push` is a git push). Splits on ; && || | & newlines, $( and backticks."""
    out = []
    for seg in re.split(r"&&|\|\||;|\||&|\n|\$\(|`|\(|\)", body):
        seg = seg.strip()
        if not seg:
            continue
        try:
            argv = shlex.split(seg)
        except ValueError:
            argv = seg.split()
        while argv and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]) or argv[0] in WRAPPERS):
            head = argv.pop(0)
            if head == "timeout":
                while argv and (argv[0].startswith("-") or re.match(r"^\d+[smhd]?$", argv[0])):
                    argv.pop(0)
            elif head in ("env", "nice", "ionice", "stdbuf", "xargs"):
                while argv and argv[0].startswith("-"):
                    argv.pop(0)
        if argv:
            out.append(argv)
    return out


def git_verb(argv):
    args = argv[1:]
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else args[1:]
    return (args[0], args[1:]) if args else (None, [])


def protected_target(verb, rest):
    """The protected branch a checkout/switch/branch would move to or change, if any.
    Creating a new branch FROM a protected one (`checkout -b T-1-fix main`) is fine:
    that is how a ticket's branch is cut from the trunk."""
    protected = POLICY.get("protected", [])
    args = [a for a in rest if a != "--"]
    if verb in ("checkout", "switch") and any(a in ("-b", "-B", "-c", "-C", "--create", "--force-create") for a in args):
        i = next(i for i, a in enumerate(args) if a in ("-b", "-B", "-c", "-C", "--create", "--force-create"))
        new = args[i + 1] if i + 1 < len(args) else None
        return new if new in protected else None
    if verb == "branch":
        flags = [a for a in args if a.startswith("-")]
        names = [a for a in args if not a.startswith("-")]
        if not flags or flags == ["--list"] or "--show-current" in flags:
            return names[0] if names and names[0] in protected and len(names) > 1 else None
        if any(f in ("-d", "-D", "-m", "-M", "-f", "--force", "--delete", "--move", "-c", "-C") for f in flags):
            return next((n for n in names if n in protected), None)
        return None
    names = [a for a in args if not a.startswith("-")]
    return names[0] if names and names[0] in protected else None


def shell_check(cmd, cwd, write_roots):
    body = strip_heredocs(cmd)
    netcmds = POLICY.get("network_commands", [])
    allowed_net = bool(netcmds) and any(body.strip().startswith(c) for c in netcmds)
    if re.search(r"&\s*$|&\s*\n|&\s*[;)]", body.replace("&&", "")):
        return "background jobs are not allowed: run in the foreground and wait"
    for argv in segments(body):
        name = os.path.basename(argv[0])
        if name in PRIVILEGE_CMDS:
            return "privilege escalation is not allowed"
        if name in DETACH_CMDS:
            return "background and detached jobs are not allowed: run in the foreground and wait"
        if name in SHELL_CMDS:
            return "eval, exec and nested shells (sh -c) are not allowed: run the command directly"
        if name in NETWORK_CMDS and not allowed_net:
            return "network commands are not allowed (add a command prefix to network_commands in project.toml)"
        if name == "operator" or (name.startswith("python") and argv[1:3] == ["-m", "hearthwork"]):
            words = argv[1:] if name == "operator" else argv[3:]
            words = [w for i, w in enumerate(words) if not (w in ("-p", "--project") or (i and words[i - 1] in ("-p", "--project")))]
            if not words or words[0] != "lab":
                return "the executor runs `operator lab ...` and no other operator command"
            verb = words[1] if len(words) > 1 else "status"
            if verb == "_ab-body":
                return "the A/B body is started by `operator lab ab`, never by hand"
            if POLICY.get("kind") == "investigation" and verb in LAB_SERVER_VERBS:
                return (f"an investigation does not operate the lab (`operator lab {verb}`): it reads and probes "
                        "with lab status, gate, ab and logs; the loop brings the lab up for a unit that needs it")
            continue
        if name == "git":
            verb, rest = git_verb(argv)
            if verb in GIT_DENY:
                return f"git {verb} is not the loop's: the loop ends at committed local work"
            if verb in GIT_BASELINE or (verb == "checkout" and "--" in rest):
                return (f"git {verb} takes work out of the tree by hand: the one baseline is "
                        "`operator lab ab <test files>`, which saves your work first and proves the restore")
            if verb == "commit":
                if any(a in ("--no-verify", "-n", "--amend") for a in rest):
                    return "commits never skip hooks and never amend"
                if not POLICY.get("co_author") and re.search(r"co-authored-by\s*:", cmd, re.I):
                    return ("no Co-Authored-By trailer: the commit carries the person's own git identity "
                            "and nothing else; commit again without it")
                if POLICY.get("_branch") in POLICY.get("protected", []):
                    return f"the checkout is on {POLICY['_branch']}, which is protected: create the ticket's branch first"
            if verb in ("checkout", "switch", "branch"):
                bad = protected_target(verb, rest)
                if bad:
                    return f"{bad} is protected: work happens on the ticket's branch"
    if PACKAGE_NET.search(body) and not allowed_net:
        return "package installs reach the network and are not allowed (add the prefix to network_commands)"
    for raw in path_mentions(body):
        p = os.path.realpath(raw)
        if secret(p):
            return f"{raw} holds secrets and is out of bounds"
        if p == HOME or under(p, [HOME]):
            readable = write_roots + [os.path.realpath(POLICY["repo"])] + roots("read_roots")
            if not (under(p, readable) or home_cache(p)):
                return f"{raw} is outside the repository"
    for m in re.finditer(r"(?:^|[^<>&0-9])>>?\s*['\"]?([^\s'\";&|]+)", body):
        tgt = m.group(1)
        if tgt.startswith("/dev/"):
            continue
        t = norm(tgt, cwd)
        if POLICY.get("kind") == "investigation" and under(t, [os.path.realpath(POLICY["repo"])]) \
                and not under(t, [os.path.realpath(POLICY.get("scratch") or "/nonexistent")]):
            return f"an investigation changes nothing in the repository: {tgt} is not the scratch folder"
        if not under(t, write_roots + TMP):
            return f"writing to {tgt} is outside the repository"
    if re.search(r"(?:^|[\s;&|])rm\s+(-\w*[rf]\w*\s+)+(/|~|\$HOME|\*)(\s|$)", body):
        return "rm on / or the home directory is not allowed"
    return None


# --- modes -------------------------------------------------------------------

def file_tool_path(ti):
    return ti.get("file_path") or ti.get("notebook_path") or ti.get("path")


def read_only_shell(cmd, cwd):
    """A reading session may look and list, never change: no writing tools, no builds,
    only read-only git, no edits in place, and no redirect into the repository (even one
    that lives under /tmp)."""
    body = strip_heredocs(cmd)
    repo = os.path.realpath(POLICY["repo"])
    for m in re.finditer(r"(?:^|[^<>&0-9])>>?\s*['\"]?([^\s'\";&|]+)", body):
        tgt = m.group(1)
        if not tgt.startswith("/dev/") and (under(norm(tgt, cwd), [repo]) or not under(norm(tgt, cwd), TMP)):
            return f"this session is read-only: it does not write {tgt}"
    if re.search(r"(?:^|\s)(sed|perl)\s+(-\w*i|--in-place)", body):
        return "this session is read-only: no edits in place"
    for argv in segments(body):
        name = os.path.basename(argv[0])
        if name in READ_ONLY_DENY and not any(a in ("--version", "-v", "--help", "-h") for a in argv[1:2]):
            return f"this session is read-only: {name} is not run here"
        if name == "git":
            verb, rest = git_verb(argv)
            if verb not in GIT_READ or (verb == "branch" and any(a.startswith("-") and a not in ("-a", "-r", "--list", "-v", "-vv", "--show-current") for a in rest)):
                return f"this session is read-only: git {verb} changes the repository"
    return None


def step_write(p, repo):
    """The unit's step narrows where it may write: an investigation writes only probes in the
    scratch folder; a fix writes no test outside it (the guard step writes the real test)."""
    scratch = POLICY.get("scratch")
    in_scratch = bool(scratch) and under(p, [os.path.realpath(scratch)])
    if POLICY.get("kind") == "investigation" and not in_scratch and under(p, [repo]):
        return ("an investigation changes nothing in the repository: a disposable probe goes in "
                f"{os.path.relpath(scratch, repo) if scratch else 'the scratch folder'}/")
    if POLICY.get("role") == "fix" and not in_scratch and under(p, [repo]) and TEST_FILE.search(os.path.relpath(p, repo)):
        return ("a fix step writes no test: a probe goes in the scratch folder, and the guard step "
                "writes the test that proves the fix")
    return None


def check_executor(tool, ti, cwd):
    repo = os.path.realpath(POLICY["repo"])
    read_only = bool(POLICY.get("read_only"))
    write_roots = list(TMP) if read_only else [repo] + TMP
    if POLICY.get("kind") == "investigation" and POLICY.get("scratch") and not read_only:
        write_roots = [os.path.realpath(POLICY["scratch"])] + TMP
    if tool in ("Read", "Grep", "Glob", "LS"):
        p = file_tool_path(ti)
        if not p:
            allow(tool, "search from the working directory")
        p = norm(p, cwd)
        if secret(p):
            deny(tool, f"{p} holds secrets and is out of bounds")
        if under(p, [HOME]) and not (under(p, [repo]) or under(p, roots("read_roots")) or home_cache(p)):
            deny(tool, f"{p} is outside the repository")
        allow(tool, "read")
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        if read_only:
            deny(tool, "this session is read-only: report what you found, change nothing")
        p = file_tool_path(ti)
        if not p:
            deny(tool, "a write without a path")
        p = norm(p, cwd)
        why = step_write(p, repo)
        if why:
            deny(tool, why, p)
        if not under(p, write_roots):
            deny(tool, f"{p} is outside the repository")
        if under(p, [os.path.join(repo, ".git")]):
            deny(tool, "the repository's .git directory is not edited by hand")
        if secret(p):
            deny(tool, f"{p} holds secrets")
        allow(tool, "write inside the repository")
    if tool == "Bash":
        reason = (read_only_shell(ti.get("command", ""), cwd) if read_only else None) or \
            shell_check(ti.get("command", ""), cwd, write_roots)
        if reason:
            deny(tool, reason, ti.get("command", ""))
        allow(tool, "shell", ti.get("command", ""))
    if tool.startswith("mcp__"):
        allowed = POLICY.get("mcp_allow") or []
        import fnmatch
        name = tool[len("mcp__"):]
        if allowed and any(fnmatch.fnmatchcase(name, pat) for pat in allowed):
            allow(tool, "an MCP tool the project allows")
        deny(tool, f"MCP tool {name} is not allowed: switch your MCP servers on (operator economy --mcp on) "
                   "and name it in mcp_allow in project.toml" if not allowed else
                   f"MCP tool {name} is not in this project's mcp_allow")
    if tool in ("Agent", "Task", "Skill"):
        if ti.get("run_in_background"):
            deny(tool, "sub-agents run in the foreground: this turn is the only one you get")
        allow(tool, "sub-agent or skill")
    deny(tool, f"{tool} is not available to the executor")


def check_operator(tool, ti, cwd):
    own = [os.path.realpath(POLICY["own_dir"])]
    if tool in ("Read", "Grep", "Glob", "LS", "Edit", "Write", "MultiEdit"):
        p = file_tool_path(ti)
        p = norm(p, cwd) if p else os.path.realpath(cwd)
        if not under(p, own):
            deny(tool, "the operator reads and writes only its own directory; the repository is the executor's")
        allow(tool, "own directory")
    if tool == "Skill":
        allow(tool, "skill")
    deny(tool, f"{tool} is not available to the operator")


def unquoted_newline(cmd):
    """True when a newline stands outside quotes, where the shell reads it as a new command."""
    quote, escape = None, False
    for ch in cmd:
        if escape:
            escape = False
        elif ch == "\\" and quote != "'":
            escape = True
        elif quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            return True
    return False


def check_spirit(tool, ti, cwd):
    home = os.path.realpath(POLICY["home"])
    readable = [home] + roots("repos")
    memory = [os.path.join(home, "spirit", "memory")]
    if tool in ("Read", "Grep", "Glob", "LS"):
        p = file_tool_path(ti)
        p = norm(p, cwd) if p else os.path.realpath(cwd)
        if secret(p):
            deny(tool, f"{p} holds secrets")
        if not under(p, readable):
            deny(tool, "the spirit reads the home and the project repositories only")
        allow(tool, "read")
    if tool in ("Edit", "Write", "MultiEdit"):
        p = norm(file_tool_path(ti) or "", cwd)
        if not under(p, memory):
            deny(tool, "the spirit writes only its memory; the loop's records change through `operator` commands")
        allow(tool, "memory")
    if tool == "Bash":
        cmd = ti.get("command", "").strip()
        # Substitution runs even inside double quotes, so it is refused anywhere. Operators
        # (; & | < >) are refused only where the shell would act on them: outside quotes.
        if "`" in cmd or "$(" in cmd:
            deny(tool, "no command substitution, not even inside quotes", cmd)
        if unquoted_newline(cmd):
            deny(tool, "one command at a time: a newline outside quotes starts another", cmd)
        try:
            lex = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>()")
            lex.whitespace_split = True
            words = list(lex)
        except ValueError:
            deny(tool, "the command does not parse", cmd)
        if any(w and set(w) <= set(";&|<>()") for w in words):
            deny(tool, "one command at a time, no pipes, redirects or chains", cmd)
        try:
            argv = shlex.split(cmd)
        except ValueError:
            deny(tool, "the command does not parse", cmd)
        if argv and os.path.basename(argv[0]) == "operator" and len(argv) > 1 and argv[1] not in ("chat", "ui", "mcp"):
            allow(tool, "operator command", cmd)
        if len(argv) >= 2 and argv[0] == "git":
            args = argv[1:]
            if args[:1] == ["-C"] and len(args) >= 3:
                if not under(norm(args[1], cwd), readable):
                    deny(tool, "git -C outside the project repositories", cmd)
                args = args[2:]
            if args and args[0] in GIT_READ and not (args[0] == "branch" and any(a in ("-d", "-D", "-m", "-M", "--delete", "--move", "-f", "--force") for a in args[1:])):
                allow(tool, "read-only git", cmd)
        deny(tool, "the spirit runs `operator <command>` and read-only git, nothing else", cmd)
    if tool == "Skill":
        allow(tool, "skill")
    deny(tool, f"{tool} is not available to the spirit")


def main():
    global POLICY
    raw = os.environ.get("HEARTHWORK_FENCE_POLICY")
    if not raw:
        POLICY = {}
        decide("deny", "?", "hearthwork fence: no policy was given, so nothing is allowed")
    POLICY = json.loads(raw)
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = str(data.get("cwd") or os.getcwd())
    if tool in ALWAYS_OK:
        allow(tool, "harness-internal")
    mode = POLICY.get("mode")
    if mode == "executor":
        try:
            import subprocess
            POLICY["_branch"] = subprocess.run(["git", "-C", POLICY["repo"], "rev-parse", "--abbrev-ref", "HEAD"],
                                               capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            POLICY["_branch"] = None
        check_executor(tool, ti, cwd)
    elif mode == "operator":
        check_operator(tool, ti, cwd)
    elif mode == "spirit":
        check_spirit(tool, ti, cwd)
    deny(tool, f"unknown fence mode {mode!r}")


def settings_for(policy_log=None):
    """The --settings JSON that attaches this fence to every tool call."""
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(os.path.abspath(__file__))}"
    return {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]},
            "disableAllHooks": False}


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log("deny", "?", f"fence internal error: {e.__class__.__name__}: {e}")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": "hearthwork fence: internal error, denied"}}))
        sys.exit(0)
