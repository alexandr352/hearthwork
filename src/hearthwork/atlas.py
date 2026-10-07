"""`operator atlas`: the first map of a new project, drafted by one read-only session.

The executor reads the repository (README, manifests, the repository's own CLAUDE.md, CI,
test configuration) and returns the atlas as markdown, every fact with its source and
the questions only the person can answer at the end. The program writes it into the
project's atlas.md; the person reviews and edits it. An edited atlas is never overwritten
without --force, and then the old one is kept beside it.
"""

import json
import re
import time

from .home import doctrine, write_atomic
from .loop import Loop
from .records import Lock, now_iso

HEADINGS = ["## What this is", "## How to run things", "## Where things are", "## Conventions",
            "## Traps", "## Questions for the person"]


class AtlasError(Exception):
    pass


def is_seed(text):
    return text.strip() == doctrine("operator", "atlas-seed.md").strip()


def extract(text):
    """The atlas markdown from a report, or None when its shape is broken."""
    i = (text or "").find("# Atlas")
    if i < 0:
        return None
    body = text[i:].strip()
    body = re.sub(r"\n```\s*$", "", body)
    pos = [body.find(h) for h in HEADINGS]
    if any(p < 0 for p in pos) or pos != sorted(pos):
        return None
    return body + "\n"


def questions(atlas_text):
    i = atlas_text.find("## Questions for the person")
    return atlas_text[i + len("## Questions for the person"):].strip() if i >= 0 else ""


QUESTION = re.compile(r"^(\d+)\.\s+(.*)$")
ANSWER = re.compile(r"^\s+Answer:\s*(.*)$")


def _split(text):
    """(before, question lines, after) around the questions section."""
    i = text.find("## Questions for the person")
    if i < 0:
        return text, [], ""
    j = text.find("\n## ", i + 5)
    body = text[i:] if j < 0 else text[i:j]
    rest = "" if j < 0 else text[j:]
    return text[:i], body.splitlines(), rest


def question_list(project):
    """[(number, question, answer or None)] from the project's atlas."""
    try:
        text = (project.dir / "atlas.md").read_text(encoding="utf-8")
    except OSError:
        return []
    _, lines, _ = _split(text)
    out = []
    for line in lines:
        m = QUESTION.match(line)
        if m:
            out.append([int(m.group(1)), m.group(2).strip(), None])
            continue
        a = ANSWER.match(line)
        if a and out:
            out[-1][2] = a.group(1).strip()
        elif out and line.strip() and out[-1][2] is None and line.startswith("   "):
            out[-1][1] += " " + line.strip()
    return [tuple(q) for q in out]


def answer(project, number, text):
    """Write the person's answer under question `number`, replacing an earlier answer."""
    text = " ".join(str(text).split())
    if not text:
        raise AtlasError("the answer is empty")
    path = project.dir / "atlas.md"
    try:
        whole = path.read_text(encoding="utf-8")
    except OSError:
        raise AtlasError("this project has no atlas yet: `operator atlas` drafts one")
    before, lines, rest = _split(whole)
    if not lines:
        raise AtlasError("the atlas has no questions section")
    out, found, pending = [], False, False
    for line in lines:
        m = QUESTION.match(line)
        if pending:
            if ANSWER.match(line):
                continue  # the earlier answer is replaced
            if line.startswith("   ") and not m and line.strip():
                out.append(line)  # the question wraps onto this line
                continue
            out.append(f"   Answer: {text}")
            pending = False
        out.append(line)
        if m and int(m.group(1)) == number:
            found, pending = True, True
    if pending:
        out.append(f"   Answer: {text}")
    if not found:
        raise AtlasError(f"there is no question {number} (see `operator atlas questions`)")
    write_atomic(path, before + "\n".join(out) + ("\n" if not rest else "") + rest)
    return text


def build(project, cfg, force=False, log=print):
    path = project.dir / "atlas.md"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current and not is_seed(current) and not force:
        raise AtlasError(f"{path} already has content; use --force to draft it again (the old one is kept)")
    lock = Lock(project)
    if not lock.acquire():
        raise AtlasError("a unit is running on this project; try again when it ends")
    try:
        loop = Loop(project, cfg, log=log)
        model = cfg["models"].get("atlas") or cfg["models"]["survey"]
        timeout = max(int(cfg["timeouts"]["survey"]), 900)
        log(f"drafting the atlas of {project.repo} (read-only, {model})")
        calls = []
        res = loop.executor_call(doctrine("executor", "ATLAS-BUILD.md"), "atlas", model, timeout, read_only=True,
                                 with_atlas=False)
        calls.append(res.record())
        draft = extract(res.text) if res.ok else None
        if res.ok and draft is None and res.session_id:
            log("the draft broke its format; asking the same session to fix it")
            res = loop.executor_call(
                "DEVIATION: return the atlas again as EXACTLY the markdown the task gave: it starts with "
                "'# Atlas' and has these headings in this order: " + ", ".join(HEADINGS) + ". Nothing before "
                "or after it.", "atlas-fix", model, timeout, resume=res.session_id, read_only=True, with_atlas=False)
            calls.append(res.record())
            draft = extract(res.text) if res.ok else None
        cost = round(sum(c.get("cost_usd") or 0 for c in calls), 6)
        with open(project.dir / "atlas-runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now_iso(), "calls": calls, "cost_usd": cost, "ok": draft is not None}) + "\n")
        if draft is None:
            why = res.error if not res.ok else "the draft never kept its format"
            raise AtlasError(f"no atlas was written: {why} (cost ${cost:.2f}); atlas.md is unchanged")
        if current and not is_seed(current):
            backup = path.with_name(f"atlas.{time.strftime('%Y%m%d-%H%M%S')}.md")
            write_atomic(backup, current)
            log(f"the previous atlas is kept as {backup.name}")
        header = (f"<!-- drafted by hearthwork on {now_iso()} from the repository; review it, fix what is "
                  "wrong, answer the questions at the end, and delete this line -->\n\n")
        write_atomic(path, header + draft)
        return path, questions(draft), cost
    finally:
        lock.release()
