"""Renaming a ticket and changing its title, with everything that carries its id."""

import json
import re
import subprocess

from . import home
from .records import Lock, Ticket, running


class TicketError(Exception):
    pass


def _word(old):
    """The id as a whole word: T-12 never matches inside T-123."""
    return re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(old)}(?![A-Za-z0-9_])")


def set_title(project, tid, title):
    t = Ticket(project, tid)
    if not t.exists():
        raise TicketError(f"no ticket {tid}")
    title = " ".join(str(title).split())
    if not title:
        raise TicketError("the title is empty")
    meta = t.read("meta.json") or {"id": tid}
    meta["title"] = title
    t.write("meta.json", meta)
    lines = t.path("ticket.md").read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("# "):
        lines[0] = f"# {tid} — {title}"
        home.write_atomic(t.path("ticket.md"), "\n".join(lines) + "\n")
    return title


def rename(project, old, new):
    """Rename ticket `old` to `new`. Returns a list of what was done, for the person to read."""
    if not home.TICKET_ID.match(new):
        raise TicketError("a ticket id is letters, digits, '.', '_' or '-' (e.g. T-12, PROJ-123)")
    src, dst = Ticket(project, old), Ticket(project, new)
    if not src.exists():
        raise TicketError(f"no ticket {old}")
    if dst.dir.exists():
        raise TicketError(f"ticket {new} already exists")
    if running(project):
        raise TicketError("a unit is running on this project; rename the ticket when it is done")
    if src.read("lease.json"):
        raise TicketError(f"{old} has a unit open in a Claude Code session; submit it or `operator abandon` first")
    lock = Lock(project)
    if not lock.acquire():
        raise TicketError("another run is working on this project")
    done = []
    try:
        word = _word(old)
        src.dir.rename(dst.dir)
        done.append(f"folder tickets/{old} -> tickets/{new}")
        for name in ("ticket.md", "plan.md", "context-full.md", "rulings.md"):
            f = dst.path(name)
            if f.exists():
                text = f.read_text(encoding="utf-8")
                fixed = word.sub(new, text)
                if fixed != text:
                    home.write_atomic(f, fixed)
                    done.append(f"{name}: the id replaced")
        meta = dst.read("meta.json") or {}
        meta["id"] = new
        meta.setdefault("renamed_from", []).append(old)
        dst.write("meta.json", meta)

        st = project.read_state()
        if st.get("active_ticket") == old:
            st["active_ticket"] = new
        if old in (st.get("ready") or []):
            st["ready"] = [new if x == old else x for x in st["ready"]]
        if (st.get("halted") or {}).get("ticket") == old:
            st["halted"]["ticket"] = new
        project.write_state(st)

        if project.units_log.exists():
            rows, changed = [], 0
            for line in project.units_log.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    rows.append(line)
                    continue
                if r.get("ticket") == old:
                    r["ticket"] = new
                    changed += 1
                rows.append(json.dumps(r, separators=(",", ":")))
            if changed:
                home.write_atomic(project.units_log, "\n".join(rows) + "\n")
                done.append(f"{changed} unit record(s) now carry {new}")

        done += _rename_branches(project, old, new)

        kfile = project.dir / "knowledge.md"
        if kfile.exists():
            text = kfile.read_text(encoding="utf-8")
            fixed = text.replace(f"[{old}]", f"[{new}]")
            if fixed != text:
                home.write_atomic(kfile, fixed)
                done.append("knowledge.md: the ticket's tags")

        arch = project.dir.parent.parent / "archive" / project.name / f"{old}.html"
        if arch.exists():
            arch.unlink()
            done.append("the old archive page removed (the next rebuild writes the new one)")
    finally:
        lock.release()
    return done


def _rename_branches(project, old, new):
    """Local branches named for the ticket follow it, unless they were ever pushed."""
    out = []
    try:
        names = subprocess.run(["git", "-C", str(project.repo), "for-each-ref", "--format=%(refname:short)",
                                "refs/heads/"], capture_output=True, text=True, timeout=20).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return ["git branches: could not be read; rename any yourself"]
    prefix = project.branch_prefix + old
    for b in names:
        if b != prefix and not b.startswith(prefix + "-"):
            continue
        nb = project.branch_prefix + new + b[len(prefix):]
        remote = subprocess.run(["git", "-C", str(project.repo), "for-each-ref", "--format=%(refname)",
                                 f"refs/remotes/*/{b}"], capture_output=True, text=True).stdout.strip()
        upstream = subprocess.run(["git", "-C", str(project.repo), "rev-parse", "--abbrev-ref", f"{b}@{{upstream}}"],
                                  capture_output=True, text=True).returncode == 0
        if remote or upstream:
            out.append(f"branch {b} was pushed, so it was left as it is (rename it yourself if you want: "
                       f"git branch -m {b} {nb}, then push the new name)")
            continue
        p = subprocess.run(["git", "-C", str(project.repo), "branch", "-m", b, nb], capture_output=True, text=True)
        out.append(f"branch {b} -> {nb}" if p.returncode == 0 else f"branch {b}: not renamed ({p.stderr.strip()[:120]})")
        # the operator's knowledge of the branch follows it
        kfile = project.dir / "knowledge.md"
        if p.returncode == 0 and kfile.exists():
            text = kfile.read_text(encoding="utf-8")
            if f"[on {b}]" in text:
                home.write_atomic(kfile, text.replace(f"[on {b}]", f"[on {nb}]"))
    return out
