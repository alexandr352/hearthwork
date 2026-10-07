"""The home: where hearthwork keeps its config, its projects, their tickets and records.

    $HEARTHWORK_HOME (default ~/.hearthwork)
      config.toml                 models, the claude binary, timeouts
      spirit/                     the spirit you talk to (CLAUDE.md, persona.md, memory/)
      worklog.html                the work log, rebuilt after every unit
      projects/<name>/            one per repository; this is also the operator's own directory
        project.toml              the repository and its rules
        CLAUDE.md                 the operator's doctrine (copied from the package)
        knowledge.md              what the operator has learned about the repository
        atlas.md                  the map the executor reads before the tree
        state.json                active ticket, halt
        units.jsonl               one line per unit: phases, models, seconds, cost
        tickets/<ID>/             ticket.md, plan.md, context-full.md, units/NN/...
"""

import json
import os
import re
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

TICKET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

DEFAULT_CONFIG = """\
# hearthwork configuration. Every key is optional; these are the defaults.

[claude]
bin = "claude"                 # the Claude Code CLI

[models]
# Aliases float to the newest model of the family; pin a full model id to hold one.
operator = "opus"              # plans and judges
executor = "opus"              # does the work in your checkout
survey = "sonnet"              # reads the tree when an executor died without a report
spirit = "sonnet"              # the one you talk to (operator chat, operator ui)
atlas = "sonnet"               # drafts a new project's atlas (operator atlas)

[timeouts]                     # seconds
plan = 1800
execute = 3600
judge = 900
survey = 600

[log]
recent_units = 20              # the log page shows this many recent units; older tickets are one
                               # line each, and every ticket has its own page under archive/

[awake]
enabled = true                 # hold off idle sleep while a unit runs or the spirit answers
on_ac = false                  # macOS: also stay awake on mains power (caffeinate -s)

[operator]
warm_minutes = 58             # resume the operator's session if it was used this recently;
                               # older sessions are dropped and it wakes from its files
reconsider = 3                 # tries for a plan or verdict that breaks its contract
"""

DEFAULT_PROJECT = """\
# hearthwork project: {name}

repo = "{repo}"                # the checkout the executor works in
trunk = "{trunk}"              # never committed to by the loop
protected = ["{trunk}", "main", "master", "production"]
branch_prefix = ""             # feature branches are <prefix><TICKET>-<slug>

# Commits carry your own git identity (git config user.name / user.email) and nothing else.
# Set true to let the executor add a "Co-Authored-By: Claude" trailer.
co_author = false

# MCP server tools the executor may call when your MCP servers are switched on
# (operator economy --mcp on). Names as server__tool; a * matches, e.g. "postgres__*".
mcp_allow = []

# Commands the executor may use that reach the network (package installs, a tracker CLI).
# Everything else that reaches the network is refused by the fence.
network_commands = []
"""


def home_dir():
    return Path(os.environ.get("HEARTHWORK_HOME") or Path.home() / ".hearthwork").expanduser()


def doctrine(*parts):
    """Text of a doctrine file shipped in the package."""
    return resources.files("hearthwork").joinpath("doctrine", *parts).read_text(encoding="utf-8")


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(home=None):
    home = home or home_dir()
    cfg = tomllib.loads(DEFAULT_CONFIG)
    p = home / "config.toml"
    if p.exists():
        cfg = _merge(cfg, tomllib.loads(p.read_text(encoding="utf-8")))
    return cfg


@dataclass
class Project:
    name: str
    dir: Path
    repo: Path
    trunk: str
    protected: list = field(default_factory=list)
    branch_prefix: str = ""
    network_commands: list = field(default_factory=list)
    co_author: bool = False
    mcp_allow: list = field(default_factory=list)

    @property
    def tickets(self):
        return self.dir / "tickets"

    @property
    def state_path(self):
        return self.dir / "state.json"

    @property
    def units_log(self):
        return self.dir / "units.jsonl"

    def ticket_dir(self, ticket):
        return self.tickets / ticket

    def read_state(self):
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def write_state(self, state):
        write_atomic(self.state_path, json.dumps(state, indent=2) + "\n")


def write_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_project(pdir):
    pdir = Path(pdir)
    data = tomllib.loads((pdir / "project.toml").read_text(encoding="utf-8"))
    return Project(
        name=pdir.name,
        dir=pdir,
        repo=Path(data["repo"]).expanduser(),
        trunk=data.get("trunk", "main"),
        protected=list(data.get("protected") or [data.get("trunk", "main")]),
        branch_prefix=data.get("branch_prefix", ""),
        network_commands=list(data.get("network_commands") or []),
        co_author=bool(data.get("co_author", False)),
        mcp_allow=list(data.get("mcp_allow") or []),
    )


def projects(home=None):
    root = (home or home_dir()) / "projects"
    if not root.is_dir():
        return []
    return [load_project(p) for p in sorted(root.iterdir()) if (p / "project.toml").exists()]


class HomeError(Exception):
    pass


def resolve_project(name=None, cwd=None, home=None):
    """The project named, else the one whose repository holds cwd, else the only one."""
    all_ = projects(home)
    if name:
        for p in all_:
            if p.name == name:
                return p
        raise HomeError(f"no project named {name!r} (see `operator project list`)")
    cwd = Path(cwd or os.getcwd()).resolve()
    for p in all_:
        try:
            cwd.relative_to(p.repo.resolve())
            return p
        except ValueError:
            continue
    if len(all_) == 1:
        return all_[0]
    if not all_:
        raise HomeError("no project yet: `operator project add <name> --repo <path>`")
    raise HomeError("several projects: name one with --project, or run from inside its repository")


def init_home(home=None):
    """Create the home and the spirit. Never overwrites a file that exists."""
    home = home or home_dir()
    created = []
    for d in (home, home / "projects", home / "spirit" / "memory"):
        d.mkdir(parents=True, exist_ok=True)
    seeds = {
        home / "config.toml": DEFAULT_CONFIG,
        home / "spirit" / "CLAUDE.md": doctrine("spirit", "CLAUDE.md"),
        home / "spirit" / "persona.md": doctrine("spirit", "persona.md"),
        home / "spirit" / "memory" / "README.md": doctrine("spirit", "memory-readme.md"),
    }
    for path, text in seeds.items():
        if not path.exists():
            path.write_text(text, encoding="utf-8")
            created.append(path)
    return home, created


def add_project(name, repo, trunk=None, home=None):
    home = home or home_dir()
    if not PROJECT_NAME.match(name):
        raise HomeError("a project name is lowercase letters, digits, '.', '_' or '-'")
    repo = Path(repo).expanduser().resolve()
    if not (repo / ".git").exists():
        raise HomeError(f"{repo} is not a git checkout")
    pdir = home / "projects" / name
    if (pdir / "project.toml").exists():
        raise HomeError(f"project {name!r} already exists at {pdir}")
    if trunk is None:
        from . import gitinfo
        trunk = gitinfo.default_branch(repo)
    (pdir / "tickets").mkdir(parents=True, exist_ok=True)
    (pdir / "project.toml").write_text(DEFAULT_PROJECT.format(name=name, repo=repo, trunk=trunk), encoding="utf-8")
    refresh_doctrine(pdir)
    for fname, src in (("knowledge.md", "knowledge-seed.md"), ("atlas.md", "atlas-seed.md")):
        if not (pdir / fname).exists():
            (pdir / fname).write_text(doctrine("operator", src), encoding="utf-8")
    return load_project(pdir)


def refresh_doctrine(pdir):
    """The operator's doctrine travels with the package; a project holds a copy."""
    pdir = Path(pdir)
    (pdir / "CLAUDE.md").write_text(doctrine("operator", "CLAUDE.md"), encoding="utf-8")
    skills = pdir / ".claude" / "skills"
    for skill in ("plan-format", "knowledge-contract"):
        d = skills / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(doctrine("operator", f"skill-{skill}.md"), encoding="utf-8")
