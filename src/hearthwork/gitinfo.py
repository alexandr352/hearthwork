"""What the repository says, read by the program — never taken from a report.

The executor writes a report; the judge must not take that report's word for what
changed. These readers give the judge the repository's own account: the head before
and after, the commits made, the files touched, and whether the tree is clean.
"""

import subprocess


def git(repo, *args, timeout=60):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def default_branch(repo):
    try:
        ref = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        return ref.split("/", 1)[1]
    except (RuntimeError, IndexError):
        pass
    for name in ("main", "master"):
        try:
            git(repo, "rev-parse", "--verify", "--quiet", name)
            return name
        except RuntimeError:
            continue
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() or "main"


def head(repo):
    try:
        return git(repo, "rev-parse", "HEAD").strip()
    except RuntimeError:
        return None


def branch(repo):
    try:
        return git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except RuntimeError:
        return None


def porcelain(repo):
    return git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()


def snapshot(repo):
    """The state of the checkout at one moment."""
    return {"head": head(repo), "branch": branch(repo), "status": porcelain(repo)}


def compare(repo, before, after):
    """What happened between two snapshots: commits, files touched, tree state."""
    commits, committed_files = [], []
    if before.get("head") and after.get("head") and before["head"] != after["head"]:
        try:
            log = git(repo, "log", "--format=%H %s", f"{before['head']}..{after['head']}")
            commits = [line.split(" ", 1) for line in log.splitlines() if line]
            committed_files = git(repo, "diff", "--name-only", before["head"], after["head"]).splitlines()
        except RuntimeError:
            commits = [[after["head"], "(history rewritten or unreadable)"]]
    dirty = [line[3:] for line in after.get("status") or []]
    touched = sorted(set(committed_files) | set(dirty))
    return {
        "head_before": before.get("head"),
        "head_after": after.get("head"),
        "branch_before": before.get("branch"),
        "branch_after": after.get("branch"),
        "commits": [{"sha": c[0], "subject": c[1] if len(c) > 1 else ""} for c in commits],
        "files_touched": touched,
        "tree_clean": not after.get("status"),
        "uncommitted": after.get("status") or [],
    }


def facts_block(diff):
    """The repository's account, as the judge reads it."""
    lines = [
        "REPOSITORY FACTS (read by the program from git, not from the report):",
        f"branch: {diff['branch_before']} -> {diff['branch_after']}",
        f"head: {(diff['head_before'] or 'none')[:12]} -> {(diff['head_after'] or 'none')[:12]}",
    ]
    if diff["commits"]:
        lines.append("commits made:")
        lines += [f"  {c['sha'][:12]} {c['subject']}" for c in diff["commits"]]
    else:
        lines.append("commits made: none")
    lines.append("tree: clean" if diff["tree_clean"] else "tree: NOT clean")
    if diff["uncommitted"]:
        lines.append("uncommitted (git status --porcelain):")
        lines += [f"  {s}" for s in diff["uncommitted"][:200]]
        if len(diff["uncommitted"]) > 200:
            lines.append(f"  ... and {len(diff['uncommitted']) - 200} more")
    return "\n".join(lines)
