"""The next step: one answer to "what do I do now?", read the same way by `operator next`,
the page's banner and the spirit."""

import os
import subprocess
import time
from pathlib import Path

from . import home
from .records import Ticket

SEARCH = ("code", "projects", "work", "src", "dev", "repos", "git", "Developer", "Documents", "workspace")


def next_step(project_name=None, h=None):
    """A dict: key, title (what to do), why (one line), command (to do it directly),
    ask (what to tell the spirit to have it done), project (when one is meant)."""
    h = h or home.home_dir()
    projects = home.projects(h)
    if project_name:
        projects = [p for p in projects if p.name == project_name] or projects
    if not projects:
        return {"key": "project", "title": "Add a project",
                "why": "hearthwork works on a git repository on this machine; tell it which one.",
                "command": "operator project add <name> --repo <path>   (operator repos lists the ones it can find)",
                "ask": "I want to add a project. Which repositories can you find on this machine?",
                "project": None}
    from . import atlas
    from .records import running
    for p in projects:
        r = running(p)
        if r:
            mins = (time.time() - (r.get("started") or time.time())) / 60
            return {"key": "running", "title": f"Unit {r['unit']} of {r['ticket']} is running: {r.get('phase')}",
                    "why": f"{r.get('title') or 'the operator is planning it'} · {mins:.0f} min so far. "
                           "The page updates as it goes; nothing to do until it is judged.",
                    "command": f"operator status -p {p.name}",
                    "ask": "What is the running unit doing?", "project": p.name}
    for p in projects:
        st = p.read_state()
        if st.get("halted"):
            hl = st["halted"]
            return {"key": "halt", "title": f"Answer {p.name}'s question",
                    "why": f"the work stopped on {hl.get('ticket')}: {hl.get('reason')}",
                    "command": 'operator rule "<your decision>"   (or operator resume)',
                    "ask": "The work halted. What is the question, and what are my options?", "project": p.name}
    for p in projects:
        try:
            seed = atlas.is_seed((p.dir / "atlas.md").read_text(encoding="utf-8"))
        except OSError:
            seed = True
        if seed:
            return {"key": "atlas", "title": f"Draft {p.name}'s atlas",
                    "why": "the short map every session reads before the code; one read-only session drafts it.",
                    "command": f"operator atlas -p {p.name}",
                    "ask": "Let's draft the atlas for this project. What will it do and cost?", "project": p.name}
        open_q = [n for n, _, a in atlas.question_list(p) if not a]
        if open_q:
            return {"key": "questions", "title": f"Answer {len(open_q)} atlas question{'s' if len(open_q) != 1 else ''} for {p.name}",
                    "why": "facts the draft could not find in the repository; every unit reads your answers.",
                    "command": f'operator atlas answer <n> "<your answer>" -p {p.name}   (operator atlas questions lists them)',
                    "ask": "Let's go through the open atlas questions, one at a time.", "project": p.name}
    for p in projects:
        st = p.read_state()
        tid = st.get("active_ticket")
        if tid:
            t = Ticket(p, tid)
            if t.read("lease.json"):
                return {"key": "lease", "title": f"Finish {tid}'s open unit in your Claude Code session",
                        "why": "a unit was handed to your own session (MCP mode) and is not submitted yet.",
                        "command": f"operator abandon -p {p.name}   (to drop it instead)",
                        "ask": f"{tid} has a unit open in my Claude Code session. What should I do with it?",
                        "project": p.name}
            return {"key": "run", "title": f"Run the next unit of {tid}",
                    "why": "one unit: the operator plans it, the executor does it, the operator judges it.",
                    "command": f"operator run -p {p.name}   (operator run -n 0 --max-cost 5 to go on until it is ready)",
                    "ask": f"Run the next unit of {tid}.", "project": p.name}
    p = projects[0]
    ready = p.read_state().get("ready") or []
    return {"key": "ticket", "title": "Create a ticket",
            "why": ("ready for your review: " + ", ".join(ready) + ". " if ready else "")
                   + "Paste a ticket's text and the work begins.",
            "command": f'operator ticket new <ID> --title "..." --file <ticket.md> -p {p.name}',
            "ask": "I want to create a ticket. I'll paste its text.", "project": p.name}


def find_repos(roots=None, depth=3, limit=40):
    """Git repositories under the usual folders of the home directory: [(path, branch)]."""
    base = Path.home()
    roots = roots or [base / d for d in SEARCH] + [base]
    seen, out = set(), []
    for root in roots:
        if not root.is_dir():
            continue
        start_depth = len(root.parts)
        for dirpath, dirnames, _ in os.walk(root):
            d = Path(dirpath)
            if (d / ".git").exists():
                real = d.resolve()
                if real not in seen:
                    seen.add(real)
                    try:
                        br = subprocess.run(["git", "-C", str(d), "rev-parse", "--abbrev-ref", "HEAD"],
                                            capture_output=True, text=True, timeout=5).stdout.strip()
                    except (OSError, subprocess.TimeoutExpired):
                        br = ""
                    out.append((str(d), br))
                if d != base:  # a home folder kept in git (dotfiles) is listed and still searched
                    dirnames[:] = []
                    continue
            if len(d.parts) - start_depth >= depth:
                dirnames[:] = []
                continue
            dirnames[:] = [x for x in dirnames if not x.startswith(".") and x not in
                           ("node_modules", "Library", "Applications", "venv", ".venv", "__pycache__")
                           and not (d == base and root == base and x in SEARCH)]
            if len(out) >= limit:
                return out
    return out
