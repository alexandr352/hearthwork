"""Token economy: what every Claude call carries, and the three things you may switch.

Fixed, never switched: no background tasks, each role's own tool list (the fence would
refuse anything more, so more tools would only cost tokens), and the fence itself.

Switchable, in ~/.hearthwork/settings.json (the page's economy panel, or `operator economy`):

  mcp        off  the executor gets no MCP server            (default)
             on   the executor gets your MCP servers; the fence lets it call only the
                  server tools a project names in mcp_allow. Reading sessions never do.
  claude_md  off  the executor carries only hearthwork's doctrine and the repository's own
                  CLAUDE.md                                    (default)
             on   your ~/.claude/CLAUDE.md is added to the executor's instructions
  cache      policy  operator and spirit write the 1-hour prompt cache (they resume after
                  long gaps); executor, survey and atlas the 5-minute one (cheaper writes,
                  their turns are seconds apart)              (default)
             auto    the Claude Code CLI decides

A setting is read when a unit starts and applies to the whole unit.
"""

import json
from pathlib import Path

from . import home

DEFAULTS = {"mcp": False, "claude_md": False, "cache": "policy"}
TTL = {"operator": "1h", "spirit": "1h", "executor": "5m", "survey": "5m", "atlas": "5m"}
CACHES = ("policy", "auto")


def path(h=None):
    return (h or home.home_dir()) / "settings.json"


def load(h=None):
    try:
        data = json.loads(path(h).read_text(encoding="utf-8")).get("economy") or {}
    except (OSError, ValueError, AttributeError):
        data = {}
    out = dict(DEFAULTS)
    if isinstance(data.get("mcp"), bool):
        out["mcp"] = data["mcp"]
    if isinstance(data.get("claude_md"), bool):
        out["claude_md"] = data["claude_md"]
    if data.get("cache") in CACHES:
        out["cache"] = data["cache"]
    return out


def save(values, h=None):
    """Merge `values` into the economy settings; unknown keys and values are refused."""
    cur = load(h)
    for k, v in values.items():
        if k in ("mcp", "claude_md"):
            if not isinstance(v, bool):
                raise ValueError(f"{k} is true or false")
        elif k == "cache":
            if v not in CACHES:
                raise ValueError(f"cache is one of {', '.join(CACHES)}")
        else:
            raise ValueError(f"unknown economy setting {k!r}")
        cur[k] = v
    p = path(h)
    try:
        whole = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(whole, dict):
            whole = {}
    except (OSError, ValueError):
        whole = {}
    whole["economy"] = cur
    home.write_atomic(p, json.dumps(whole, indent=2) + "\n")
    return cur


def ttl(role, eco):
    """The cache TTL a role's calls set, or None to leave the CLI to decide."""
    return TTL.get(role) if eco.get("cache") == "policy" else None


def ttl_env(role, eco):
    t = ttl(role, eco)
    return {"CLAUDE_CODE_PROMPT_CACHE_TTL": t} if t else {}


def label(eco):
    return "full" if eco == DEFAULTS else "custom"


def personal_claude_md():
    """The person's own global instructions, when they keep them."""
    p = Path.home() / ".claude" / "CLAUDE.md"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""
