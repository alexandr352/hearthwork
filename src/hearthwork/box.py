"""The box: what the inspector found, one report per test file, until you release it.

The box holds, for every UI test file the inspector has judged, the findings of its
LATEST look, and a new look REPLACES them. A finding is never matched to an earlier
one: the latest look is the truth, so a defect worded differently on a retest cannot
become a second item.

States of a report:
    clean       the latest look found nothing
    open        the latest look has findings, not released
    released    you released it (operator release) into a ticket
    still-seen  released, and a look at a NEWER commit still finds something to fix
    fixed       released, and a look at a newer commit finds nothing to fix

ONE CONTROL, ONE PROBLEM. The judge names each finding's element ("Checkout page ·
Pay button"). When a report lands, each of its findings is matched against the own
findings of every other report in play (open, released, still-seen): the same
criterion and the same element. A match marks the new finding `dup_of` the first and
lists this file under the first's `also_in`; counts, ranks and releases read own
findings only. A finding stays in its file's report either way.

Pure file state under a short lock; nothing here spends.
"""

import fcntl
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path

from .home import write_atomic

STATES = ("clean", "open", "released", "still-seen", "fixed")
IN_PLAY = ("open", "released", "still-seen")
RELEASABLE = ("open", "still-seen")
TO_FIX = ("fails", "measure")
JUDGEMENTS = ("fails", "measure", "other")
RANK = {"fails": 0, "measure": 1, "other": 2}
LEVEL = {"high": 0, "medium": 1, "low": 2}
ELEMENT_MATCH = 0.6
_DROP = {"the", "a", "an", "its", "this", "that", "of", "on", "in", "at", "to", "and", "with"}


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def idir(p):
    return Path(p.dir) / "inspect"


def _path(p):
    return idir(p) / "box.json"


@contextmanager
def locked(p):
    d = idir(p)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "box.lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def load(p):
    try:
        b = json.loads(_path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        b = {}
    b.setdefault("reports", {})
    return b


def save(p, box):
    write_atomic(_path(p), json.dumps(box, indent=1, sort_keys=True) + "\n")


def name_of(rel):
    """A report is named by its file without the test suffix: tests/a11y/checkout.spec.ts -> checkout."""
    base = rel.rsplit("/", 1)[-1]
    return re.sub(r"\.(spec|test|e2e)\.[A-Za-z0-9]+$|\.[A-Za-z0-9]+$", "", base)


def own(r):
    return [f for f in r.get("findings") or [] if not f.get("dup_of")]


def to_fix(r):
    return [f for f in own(r) if f.get("judgement") in TO_FIX]


def finding_rank(f):
    return (RANK.get(f.get("judgement"), 3), LEVEL.get(f.get("severity"), 3), LEVEL.get(f.get("confidence"), 3))


def report_rank(r):
    fs = own(r)
    return (min((finding_rank(f) for f in fs), default=(9, 9, 9)), -len(to_fix(r)), -len(fs), r.get("name", ""))


def _tokens(s):
    return frozenset(w for w in re.findall(r"[a-z0-9]+", str(s or "").lower()) if w not in _DROP)


def element_match(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return ta == tb or len(ta & tb) / len(ta | tb) >= ELEMENT_MATCH


def _dedupe_into(box, rel, fs):
    others = [(o, r) for o, r in box["reports"].items() if o != rel and r.get("state") in IN_PLAY]
    n = 0
    for f in fs:
        if f.get("carried") or not f.get("element"):
            continue
        for orel, r in others:
            hit = next((o for o in own(r) if o.get("element") and o.get("criterion") == f.get("criterion")
                        and element_match(o["element"], f["element"])), None)
            if hit:
                f["dup_of"] = {"file": orel, "n": hit.get("n")}
                hit["also_in"] = [x for x in hit.get("also_in") or [] if x.get("file") != rel] + [
                    {"file": rel, "test": f.get("test"), "frame": f.get("frame")}]
                n += 1
                break
    return n


def _unlink(box, rel):
    """Before rel's report is replaced: it leaves every also_in, and findings that pointed at it
    become own findings again."""
    for orel, r in box["reports"].items():
        if orel == rel:
            continue
        for o in r.get("findings") or []:
            if o.get("also_in"):
                o["also_in"] = [x for x in o["also_in"] if x.get("file") != rel]
                if not o["also_in"]:
                    o.pop("also_in")
            if (o.get("dup_of") or {}).get("file") == rel:
                o.pop("dup_of")
                o["was_dup_of"] = rel   # its first was looked at again: this file is due a look too


def replace_report(p, rel, head, findings, carried=()):
    """The look at `head` is the truth for `rel`. `carried` are the previous findings on tests
    this look could not judge: kept and marked, because an unjudged test is not a clean one.
    Returns (previous state | None, new state, number of findings)."""
    with locked(p):
        box = load(p)
        prev = box["reports"].get(rel)
        prev_state = prev.get("state") if prev else None
        _unlink(box, rel)
        fs = [{k: v for k, v in f.items() if k not in ("carried", "dup_of", "also_in", "was_dup_of")} for f in findings]
        fs += [dict({k: v for k, v in f.items() if k not in ("dup_of", "also_in", "was_dup_of")}, carried=True)
               for f in carried]
        fs.sort(key=finding_rank)
        for i, f in enumerate(fs, 1):
            f["n"] = i
        _dedupe_into(box, rel, fs)
        r = dict(prev) if prev else {"history": []}
        r.update(file=rel, name=name_of(rel), findings=fs, audited_commit=head, audited_at=now_iso())
        if prev_state in ("released", "still-seen") and r.get("released_commit") not in (None, head):
            state = "still-seen" if [f for f in fs if f.get("judgement") in TO_FIX] else "fixed"
        elif prev_state == "released":
            state = "released"      # looked at again at the release commit: nothing to decide yet
        else:
            state = "open" if fs else "clean"
        r["state"] = state
        r.setdefault("history", []).append([now_iso(), "looked:" + state, head, len(fs)])
        box["reports"][rel] = r
        save(p, box)
    return prev_state, state, len(fs)


def shared_moved(p, head):
    """Files with findings that were copies of another file's, whose first has since been
    looked at again: what that file shows now may have changed here too."""
    return {rel for rel, r in load(p)["reports"].items()
            if r.get("state") in RELEASABLE and r.get("audited_commit") != head
            and any(f.get("was_dup_of") for f in r.get("findings") or [])}


def findings_of(p, rel):
    r = load(p)["reports"].get(rel)
    return list(r.get("findings") or []) if r else []


def released_files(p, head):
    """Released files last looked at before `head`: a newer look decides fixed or still seen."""
    return {rel for rel, r in load(p)["reports"].items()
            if r.get("state") == "released" and r.get("audited_commit") != head}


def cited_captures(p):
    keep = set()
    for r in load(p)["reports"].values():
        if r.get("state") in ("clean", "fixed"):
            continue
        for f in (r.get("findings") or []) + (r.get("released_findings") or []):
            if f.get("frame"):
                keep.add(str(Path(f["frame"]).parent.parent))
    return keep


def counts(box):
    c = {s: 0 for s in STATES}
    for r in box["reports"].values():
        c[r["state"]] = c.get(r["state"], 0) + 1
    return c


def judgement_line(r):
    c = {}
    for f in own(r):
        c[f.get("judgement")] = c.get(f.get("judgement"), 0) + 1
    words = {"fails": "failing", "measure": "to measure", "other": "other"}
    line = ", ".join(f"{c[k]} {words[k]}" for k in JUDGEMENTS if c.get(k))
    dups = len(r.get("findings") or []) - len(own(r))
    return line + (f"{', ' if line else ''}{dups} also seen elsewhere" if dups else "")


def numbers(p, roster=None, n_files=None):
    """The box in two plain lines."""
    box = load(p)
    roster = roster if roster is not None else {}
    seen = [s for s in roster.values() if s.get("audited_commit")]
    by = {}
    for s in seen:
        by[s.get("verdict")] = by.get(s.get("verdict"), 0) + 1
    c = counts(box)
    open_ = [r for r in box["reports"].values() if r["state"] == "open"]
    parts = [f"{by.get('seen-ok', 0)} clean", f"{by.get('findings', 0)} with problems"]
    if by.get("not-visual"):
        parts.append(f"{by['not-visual']} nothing to see")
    if by.get("cannot-judge"):
        parts.append(f"{by['cannot-judge']} no usable picture")
    total = n_files if n_files is not None else len(roster)
    return (f"Files looked at: {len(seen)} of {total} — {', '.join(parts)}\n"
            f"In the box: {c['open']} waiting for you ({sum(len(own(r)) for r in open_)} problems, "
            f"{sum(len([f for f in own(r) if f.get('judgement') == 'fails']) for r in open_)} failing) · "
            f"{c['released']} released · {c['fixed']} fixed"
            + (f" · {c['still-seen']} released but still seen" if c["still-seen"] else ""))


def render(p, roster=None, n_files=None, top=10):
    box = load(p)
    lines = numbers(p, roster, n_files).splitlines()
    waiting = sorted((r for r in box["reports"].values() if r["state"] in RELEASABLE), key=report_rank)
    if waiting:
        lines += ["", "Waiting for you, failures first (operator release <N> --ticket <ID> releases the top N "
                      "with something to fix; or name the files):"]
        for r in waiting[:top]:
            fs = own(r) or r["findings"]
            mark = " (released, still seen)" if r["state"] == "still-seen" else ""
            lines.append(f"  {r['name']:<32} {judgement_line(r)}{mark} — {fs[0].get('finding', '')[:110]}")
        if len(waiting) > top:
            lines.append(f"  … and {len(waiting) - top} more")
    return "\n".join(lines)


def _resolve(box, tok):
    t = name_of(tok.strip()) if "/" in tok or "." in tok else tok.strip()
    hits = [rel for rel, r in box["reports"].items() if r.get("name") == t or rel == tok.strip()]
    return hits[0] if len(hits) == 1 else None


class BoxError(Exception):
    pass


def release(p, tokens, head, ticket):
    """Release the top N waiting files, or the named ones, into `ticket`. Returns (text of the
    release, the files released). The text is what the ticket carries."""
    with locked(p):
        box = load(p)
        reps = box["reports"]
        if len(tokens) == 1 and tokens[0].isdigit():
            n = int(tokens[0])
            if n < 1:
                raise BoxError("N is 1 or more")
            chosen = sorted((r for r in reps.values() if r["state"] in RELEASABLE and to_fix(r)), key=report_rank)[:n]
        else:
            chosen = []
            for tok in tokens:
                rel = _resolve(box, tok)
                if not rel:
                    raise BoxError(f"'{tok}' is neither a count nor a file in the box (operator box lists them)")
                r = reps[rel]
                if r["state"] not in RELEASABLE:
                    raise BoxError(f"{r['name']} is {r['state']}, not waiting")
                if not to_fix(r):
                    raise BoxError(f"{r['name']} holds nothing to fix (only findings judged other)")
                if r not in chosen:
                    chosen.append(r)
        if not chosen:
            raise BoxError("no waiting file has something to fix")
        body = [f"Released from the inspector on {now_iso()}. The inspector ran these UI tests, looked at what",
                "they draw, and found what the tests do not catch. One section per test file: its findings at",
                "its latest look. Look again at the current commit before acting (the look may trail it).",
                "Fix what is judged FAILS, and MEASURE (measure first; fix only if it fails). A fix to a defect",
                "a passing test missed also STRENGTHENS THAT TEST so it would catch it. A finding ALSO SEEN in",
                "other files is one control: fix it once, and strengthen every test named. Findings judged",
                "OTHER are listed last for information.", ""]
        for r in chosen:
            body += [f"## {r['name']}  ({judgement_line(r)} · looked at {(r.get('audited_commit') or '')[:10]})",
                     f"- test file: {r['file']}", ""]
            info = [f for f in own(r) if f.get("judgement") not in TO_FIX]
            for f in to_fix(r) + info:
                if info and f is info[0]:
                    body += ["#### For information (judged other)", ""]
                body += [f"### {f['n']}. {f.get('judgement', '').upper()} · {f.get('criterion') or 'no criterion'}"
                         f" · severity {f.get('severity')} · confidence {f.get('confidence')}"
                         + (" (carried: its test was not judged at the latest look)" if f.get("carried") else ""),
                         f"- test: {f.get('test')}", f"- element: {f.get('element')}",
                         f"- finding: {f.get('finding')}", f"- frame: {f.get('frame')}"]
                if f.get("also_in"):
                    body.append(f"- ALSO SEEN in: " + "; ".join(
                        f"{name_of(x['file'])} ({x.get('test')})" for x in f["also_in"]))
                body.append("")
        for r in chosen:
            r.update(state="released", released_at=now_iso(), released_commit=head, released_to=ticket,
                     released_findings=[dict(f) for f in r["findings"]])
            r.setdefault("history", []).append([now_iso(), "released:" + ticket, head, len(r["findings"])])
        save(p, box)
    return "\n".join(body), [r["file"] for r in chosen]
