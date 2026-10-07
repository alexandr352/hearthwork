"""The records: the per-unit folder, the meter, the open chain, the recovery notes."""

import fcntl
import json
import os
import time
from pathlib import Path

from .home import write_atomic


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Ticket:
    """One ticket's folder in the operator's directory."""

    def __init__(self, project, ticket_id):
        self.project = project
        self.id = ticket_id
        self.dir = project.ticket_dir(ticket_id)

    def path(self, *parts):
        return self.dir.joinpath(*parts)

    def exists(self):
        return self.path("ticket.md").exists()

    def unit_dir(self, n):
        return self.path("units", f"{n:02d}")

    def units(self):
        d = self.path("units")
        if not d.is_dir():
            return []
        return sorted(int(p.name) for p in d.iterdir() if p.name.isdigit())

    def next_unit(self):
        done = [n for n in self.units() if (self.unit_dir(n) / "verdict.json").exists()
                or (self.unit_dir(n) / "plan.json").exists()]
        return (max(done) + 1) if done else 1

    # --- JSON side files ------------------------------------------------------

    def read(self, name):
        try:
            return json.loads(self.path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write(self, name, obj):
        write_atomic(self.path(name), json.dumps(obj, indent=2) + "\n")

    def clear(self, name):
        try:
            self.path(name).unlink()
        except FileNotFoundError:
            pass

    # --- the operator's session for this ticket -------------------------------

    def session(self):
        try:
            return self.path("session").read_text().strip() or None
        except OSError:
            return None

    def set_session(self, sid):
        if sid:
            write_atomic(self.path("session"), sid + "\n")

    def drop_session(self):
        self.clear("session")


def write_unit_file(ticket, n, name, text):
    d = ticket.unit_dir(n)
    d.mkdir(parents=True, exist_ok=True)
    write_atomic(d / name, text if text.endswith("\n") else text + "\n")
    return d / name


def meter(project, rec):
    """One JSON line per unit, appended under a lock."""
    project.units_log.parent.mkdir(parents=True, exist_ok=True)
    with open(project.units_log, "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def read_meter(project):
    out = []
    try:
        with open(project.units_log, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


class Lock:
    """One loop per project at a time. Non-blocking: a second run exits quietly."""

    def __init__(self, project):
        self.path = Path(project.dir) / ".lock"
        self.fh = None

    def acquire(self):
        self.fh = open(self.path, "a+")
        try:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.fh.close()
            self.fh = None
            return False
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(f"{os.getpid()} {now_iso()}\n")
        self.fh.flush()
        return True

    def release(self):
        if self.fh:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None
