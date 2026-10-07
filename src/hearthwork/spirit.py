"""How a spirit session is started: the same fence and doctrine for the terminal chat
(`operator chat`) and the chat on the work log page (`operator ui`)."""

import json
import os
import shutil
import sys
from pathlib import Path

from . import claude, fence, home

TOOLS = ["Read", "Grep", "Glob", "Bash", "Edit", "Write", "Skill", "TodoWrite"]


def spirit_dir(h=None):
    return (h or home.home_dir()) / "spirit"


def operator_bin_dir():
    """The folder holding the `operator` command, so the spirit can run it."""
    found = shutil.which("operator")
    return str(Path(found).parent) if found else str(Path(sys.argv[0]).resolve().parent)


def launch(h=None):
    """(argv tail, env) for a spirit session: fenced, with only its own doctrine."""
    h = h or home.home_dir()
    sdir = spirit_dir(h)
    settings = fence.settings_for()
    settings["claudeMdExcludes"] = claude.doctrine_excludes(sdir)
    repos = [str(p.repo) for p in home.projects(h)]
    policy = {"mode": "spirit", "home": str(h), "repos": repos, "log": str(sdir / "fence.log")}
    env = dict(os.environ, HEARTHWORK_FENCE_POLICY=json.dumps(policy), HEARTHWORK_HOME=str(h))
    env["PATH"] = operator_bin_dir() + os.pathsep + env.get("PATH", "")
    env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    args = ["--settings", json.dumps(settings), "--setting-sources", "project", "--strict-mcp-config",
            "--tools", ",".join(TOOLS), "--add-dir", str(h)]
    for r in repos:
        args += ["--add-dir", r]
    return args, env
