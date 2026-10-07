"""The executor's kit: the sub-agents (reader, prober, reviewer) and the skills (probe,
census, self-review) every executor call carries. Nothing is written into the person's
repository: the agents travel as --agents JSON, the skills as a plugin built in the home."""

import json
import re
from importlib import resources

from . import __version__
from .home import home_dir, write_atomic

AGENTS = ("hw-investigator", "hw-prober", "hw-reviewer")
SKILLS = ("hw-probe", "hw-census", "hw-self-review")


def _front(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if v:
            meta[k.strip()] = v.strip()
    return meta, m.group(2).strip() + "\n"


def agents(model="sonnet"):
    """The --agents JSON: each agent's description, prompt, tools, and the reader model."""
    out = {}
    root = resources.files("hearthwork").joinpath("doctrine", "agents")
    for name in AGENTS:
        meta, body = _front(root.joinpath(f"{name}.md").read_text(encoding="utf-8"))
        out[name] = {"description": meta.get("description", name), "prompt": body,
                     "tools": [t.strip() for t in meta.get("tools", "Read,Grep,Glob").split(",") if t.strip()],
                     "model": model}
    return out


def plugin_dir(h=None):
    """The skills as a Claude Code plugin named "hearthwork" (skills load as
    hearthwork:hw-probe ...), rebuilt in the home whenever the version changes."""
    d = (h or home_dir()) / "plugin" / __version__
    manifest = d / ".claude-plugin" / "plugin.json"
    if not manifest.exists():
        root = resources.files("hearthwork").joinpath("doctrine", "skills")
        for name in SKILLS:
            write_atomic(d / "skills" / name / "SKILL.md", root.joinpath(name, "SKILL.md").read_text(encoding="utf-8"))
        write_atomic(manifest, json.dumps({"name": "hearthwork", "version": __version__,
                                           "description": "the hearthwork executor's skills"}, indent=2) + "\n")
    return d
