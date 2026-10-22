"""The contracts the operator's answers must keep, checked by the program.

A broken answer is never silently retried or repaired here: the deviation is named
and handed back to the same session for reconsideration.
"""

import re

BUDGETS = {"LOW": (2, 150), "MEDIUM": (5, 300), "HIGH": (10, 600)}
FINDINGS_MARK = "| Finding:"
SCOPE_MARK = "SCOPE CONSTRAINT:"
PROMPT_MAX = 24000
MODES = ("VISUAL", "FAMILY", "STABILIZATION", "FEATURE", "REFACTOR", "CONFIGURATION", "MIGRATION", "AUDIT")
FAMILY_ROLES = ("census", "probe", "site-fix", "blast-radius", "guard")
VISUAL_ROLES = ("look", "fix", "guard")
SIGHTING = re.compile(r"(?im)^\s*SIGHTING:\s*(still drawn|gone|cannot show)\b([^\n]*)")


def sightings(report):
    """Every SIGHTING: line of a report, one per released finding: [(what, confidence, the line)]."""
    out = []
    for what, rest in SIGHTING.findall(report or ""):
        m = re.search(r"confidence\s*:?\s*(high|medium|low)", rest, re.I)
        out.append((what.lower(), m.group(1).lower() if m else None, f"SIGHTING: {what}{rest}".strip()))
    return out


def sighting(report):
    """What the chain may do, from all the report's SIGHTING: lines: still drawn at high confidence
    when any finding is (a fix may follow, for those); gone when every finding is; else the
    weakest word seen. (None, None) when there is no line."""
    s = sightings(report)
    if not s:
        return None, None
    if any(w == "still drawn" and c == "high" for w, c, _ in s):
        return "still drawn", "high"
    if all(w == "gone" for w, _, _ in s):
        return "gone", s[-1][1]
    w, c, _ = next((x for x in s if x[0] == "still drawn"), None) or next(x for x in s if x[0] != "gone")
    return w, c


def _check_visual(plan, chain_state, released, dev):
    """The VISUAL shape: one released test file, looked at first, fixed only on a sighting of
    the defect still drawn at high confidence, and guarded by a test that can see it."""
    kind, role, prompt = plan.get("kind"), plan.get("role"), plan.get("prompt") or ""
    phase, total = plan.get("chain_phase"), plan.get("chain_total")
    if not released:
        dev.append("VISUAL opens only on a ticket released from the inspector (operator release); "
                   "this ticket carries no release")
        return
    if not plan.get("chain"):
        dev.append("a VISUAL is a chain: look, fix, guard")
        return
    if role not in VISUAL_ROLES:
        dev.append(f'a VISUAL phase\'s "role" is one of {", ".join(VISUAL_ROLES)}; a probe or a blast radius is an '
                   "insert (a read-only investigation outside the chain)")
    opening = not chain_state or chain_state.get("chain") != plan.get("chain")
    if opening:
        if phase != 1 or role != "look" or kind != "investigation":
            dev.append("a VISUAL opens with its look: phase 1, role look, an investigation")
        if total != 3:
            dev.append('a VISUAL is three phases: "chain_total": 3 (look, fix, guard)')
        if plan.get("released_file") not in released:
            dev.append(f'a VISUAL names the one released test file it answers: "released_file" is one of '
                       f'{", ".join(released)}')
        if "still drawn" not in prompt or "defect" not in prompt.lower():
            dev.append('the look prompt defines the SIGHTING words as the state of the DEFECT ("still drawn" = '
                       'the user still meets it; "gone" = it no longer shows), never of the thing missing')
        for block in ("SIGHTING:", "CANDIDATES:", "operator lab frames"):
            if block not in prompt:
                dev.append(f"the look prompt carries {block}" + (" (the pictures it takes this unit)"
                                                                if block == "operator lab frames" else " by name"))
        return
    if isinstance(total, int) and total != chain_state.get("total"):
        dev.append(f"a VISUAL keeps its three phases; it is {chain_state.get('total')}")
    if role == "fix":
        what, conf = chain_state.get("sighting"), chain_state.get("sighting_confidence")
        if what != "still drawn" or conf != "high":
            dev.append(f"a VISUAL fix needs the defect seen STILL DRAWN at high confidence; the program read "
                       f"{what or 'no sighting'}{f' at {conf} confidence' if conf else ''}"
                       + (": void the chain" if what == "gone" else
                          ": insert a probe that pictures it, or void the chain" if what else
                          ": the look's report has no SIGHTING: line"))
    if role in ("fix", "guard") and "SIGHTING:" not in prompt:
        dev.append(f"the {role} prompt carries the look's SIGHTING: line verbatim")
    if role == "guard" and "operator lab frames" not in prompt:
        dev.append("the VISUAL guard pictures the fixed page (operator lab frames <the test file>) and makes the "
                   "test assert what the picture shows, so it would have caught the defect")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
GROUP = re.compile(r"^\d+(\s*,\s*\d+)*$")


def family_sites(report):
    """(sites, groups) counted from a census report's SITES block: one row per site,
    `[n] File | Line | measured state | deviation | group`. The group is a row's last field
    when it has five; a row without one is a group of its own. (0, 0) when there is no block."""
    m = re.search(r"(?ims)^\s*SITES:(.*?)(?=^\s*[A-Z][A-Z ]+:|\Z)", report or "")
    if not m:
        return 0, 0
    rows = [ln for ln in m.group(1).splitlines() if re.match(r"^\s*\[\d+\]", ln)]
    groups = set()
    for i, ln in enumerate(rows):
        f = [x.strip() for x in ln.split("|")]
        groups.add(f[-1].lower() if len(f) >= 5 and f[-1] else f"site {i + 1}")
    return len(rows), len(groups)


def _check_family(plan, chain_state, sha_known, dev):
    """The FAMILY shape: it opens on a shipped pattern with a census, fixes one group of like
    sites per phase, re-declares its length once, and ends in one guard over every site."""
    kind, role, prompt = plan.get("kind"), plan.get("role"), plan.get("prompt") or ""
    phase, total = plan.get("chain_phase"), plan.get("chain_total")
    if not plan.get("chain"):
        dev.append("a FAMILY is a chain: census, one site-fix per group of like sites, guard")
        return
    if role not in FAMILY_ROLES:
        dev.append(f'a FAMILY step\'s "role" is one of {", ".join(FAMILY_ROLES)}')
    opening = not chain_state or chain_state.get("chain") != plan.get("chain")
    if opening:
        if phase != 1 or role != "census" or kind != "investigation":
            dev.append("a FAMILY opens with its census: phase 1, role census, an investigation")
        if total != 3:
            dev.append('a FAMILY opens with "chain_total": 3 (census, site-fix, guard); the first site-fix '
                       "re-declares it to the number of groups + 2")
        sha = str(plan.get("pattern_commit") or "").strip().lower()
        if not SHA.match(sha):
            dev.append('a FAMILY names the shipped fix it repeats: "pattern_commit" is that commit\'s sha. '
                       "Without a shipped pattern the first site is a defect of its own (STABILIZATION)")
        elif sha_known and not sha_known(sha):
            dev.append(f'"pattern_commit" {sha} is not a commit of this repository: a FAMILY repeats a fix '
                       "that shipped here; without one the first site is a defect of its own (STABILIZATION)")
        for block in ("PATTERN:", "SITES:"):
            if block not in prompt:
                dev.append(f"the census prompt asks for the {block} block by name")
        return
    groups = int(chain_state.get("groups") or 0)
    if isinstance(total, int) and total != chain_state.get("total"):
        if not (role == "site-fix" and phase == 2 and groups and total == groups + 2
                and not chain_state.get("grown")):
            dev.append(f"a FAMILY changes its length once, at its first site-fix, to groups + 2"
                       f"{f' = {groups + 2}' if groups else ''}; it is {chain_state.get('total')}")
    if role == "site-fix":
        if not groups:
            dev.append("the census left no SITES rows the program could count: insert a probe that "
                       "measures the sites, or void the chain")
        sg = str(plan.get("site_group") or "").strip()
        if not GROUP.match(sg):
            dev.append('a site-fix names its group: "site_group" is the SITES row numbers it fixes, e.g. "1,2,4"')
        elif chain_state.get("sites") and any(not 1 <= int(x) <= chain_state["sites"] for x in sg.split(",")):
            dev.append(f'"site_group" names a row the census does not have (it has {chain_state["sites"]})')
        if kind != "execution" or plan.get("commit_expected"):
            dev.append("a site-fix is an execution that does not commit")
        for block in ("PATTERN:", "SITES:", "DOES NOT FIT:"):
            if block not in prompt:
                dev.append(f"a site-fix prompt carries {block}" + (
                    " (the census's block, verbatim)" if block != "DOES NOT FIT:" else
                    " (every site it leaves untouched, or none)"))
    if role == "guard" and "SITES:" not in prompt:
        dev.append("the FAMILY guard prompt carries the SITES: block: one test over every site")


def check_plan(plan, unit, open_chain=None, lab_ready=False, chain_state=None, sha_known=None, released=()):
    """A list of deviations; empty when the plan keeps its contract. chain_state is the open
    chain's record (chain.json); sha_known tells whether a commit is in the repository."""
    if not isinstance(plan, dict):
        return ["the answer is not one JSON object"]
    action = plan.get("action")
    if action == "halt":
        return [] if str(plan.get("reason") or "").strip() else ['"halt" needs a "reason"']
    if action != "execute":
        return [f'"action" must be "execute" or "halt", not {action!r}']
    dev = []
    if plan.get("unit") != unit:
        dev.append(f'"unit" must be {unit}, the unit being planned (got {plan.get("unit")!r})')
    kind = plan.get("kind")
    if kind not in ("investigation", "execution"):
        dev.append('"kind" must be "investigation" or "execution"')
    if not str(plan.get("title") or "").strip():
        dev.append('"title" is missing')
    prompt = plan.get("prompt")
    if not isinstance(prompt, str) or len(prompt.strip()) < 40:
        dev.append('"prompt" must carry the executor prompt as one string')
        prompt = ""
    if len(prompt) > PROMPT_MAX:
        dev.append(f'"prompt" is {len(prompt)} characters; keep it under {PROMPT_MAX}')
    if "```" in prompt:
        dev.append('"prompt" contains a fenced code block; use labelled plain text instead')
    budget = plan.get("budget")
    commit = plan.get("commit_expected")
    if not isinstance(commit, bool):
        dev.append('"commit_expected" must be true or false')
    if kind == "investigation":
        if budget not in BUDGETS:
            dev.append('an investigation carries "budget" LOW, MEDIUM or HIGH')
        elif SCOPE_MARK not in prompt:
            files, lines = BUDGETS[budget]
            dev.append(f"an investigation prompt opens with the verbatim line: SCOPE CONSTRAINT: Read at most "
                       f"{files} files. Read at most {lines} lines per file. ...")
        if FINDINGS_MARK not in prompt:
            dev.append("an investigation prompt asks for findings in the grammar "
                       "[N] File: <path> | Line: <line> | Finding: <fact> | Confidence: <level>")
        if commit:
            dev.append("an investigation never commits")
    if kind == "execution":
        if budget not in (None, "NONE"):
            dev.append('an execution carries "budget": "NONE"; its scope is TARGET FILES')
        if "TARGET FILES:" not in prompt:
            dev.append("an execution prompt names TARGET FILES:")
        if "INVARIANTS:" not in prompt:
            dev.append("an execution prompt names INVARIANTS:")
        if SCOPE_MARK in prompt:
            dev.append("an execution prompt carries no SCOPE CONSTRAINT")
    mode = plan.get("mode")
    if mode is not None and mode not in MODES:
        dev.append(f'"mode" is one of {", ".join(MODES)}')
    role = plan.get("role")
    if role is not None and not (isinstance(role, str) and 0 < len(role) <= 24 and role == role.lower()):
        dev.append('"role" is one short lowercase word for this step (e.g. reproduce, fix, guard)')
    steps = plan.get("chain_steps")
    chain = plan.get("chain")
    if steps is not None:
        if not (isinstance(steps, list) and all(isinstance(x, str) and 0 < len(x) <= 24 for x in steps)):
            dev.append('"chain_steps" is a list of short step names, one per phase')
        elif chain and isinstance(plan.get("chain_total"), int) and len(steps) != plan["chain_total"]:
            dev.append(f'"chain_steps" names {len(steps)} steps but "chain_total" is {plan["chain_total"]}')
    if chain:
        phase, total = plan.get("chain_phase"), plan.get("chain_total")
        if not (isinstance(phase, int) and isinstance(total, int) and 1 <= phase <= total and total >= 2):
            dev.append('a chain unit carries "chain_phase" and "chain_total" with 1 <= phase <= total and total >= 2')
        elif commit and phase != total:
            dev.append("only the last phase of a chain commits")
        elif phase == total and kind != "execution":
            dev.append("the last phase of a chain is the committing execution")
    if "lab" in plan and not isinstance(plan.get("lab"), bool):
        dev.append('"lab" is true when the unit needs the lab\'s server up, else false or absent')
    cs = chain_state or {}
    in_family = mode == "FAMILY" or (cs.get("mode") == "FAMILY" and bool(chain) and chain == cs.get("chain"))
    if in_family:
        if mode not in (None, "FAMILY"):
            dev.append(f'chain "{chain}" is a FAMILY: its steps carry "mode": "FAMILY"')
        _check_family(plan, chain_state, sha_known, dev)
    in_visual = mode == "VISUAL" or (cs.get("mode") == "VISUAL" and bool(chain) and chain == cs.get("chain"))
    if in_visual:
        if mode not in (None, "VISUAL"):
            dev.append(f'chain "{chain}" is a VISUAL: its phases carry "mode": "VISUAL"')
        _check_visual(plan, chain_state, list(released or ()), dev)
    shape = "FAMILY" if in_family else "VISUAL" if in_visual else "STABILIZATION"
    if lab_ready and (mode in ("STABILIZATION", "FAMILY", "VISUAL") or in_family or in_visual) and kind == "execution" \
            and commit is True and "operator lab ab" not in prompt:
        dev.append(f"a {shape} commit proves its guard first: the prompt orders "
                   "`operator lab ab <the guard test files>` and asks for its AB VERDICT line verbatim; "
                   "it commits only on GUARDS")
    if open_chain and chain and chain != open_chain:
        dev.append(f'chain "{open_chain}" is open: finish it (or insert a read-only investigation) before another')
    if open_chain and not chain and kind == "execution":
        dev.append(f'chain "{open_chain}" is open: an execution must belong to it')
    return dev


VERDICTS = ("continue", "ticket-ready", "halt")


def check_verdict(verdict):
    if not isinstance(verdict, dict):
        return ["the answer is not one JSON object"]
    dev = []
    if verdict.get("action") not in VERDICTS:
        dev.append(f'"action" must be one of {", ".join(VERDICTS)}')
    if not isinstance(verdict.get("unit_done"), bool):
        dev.append('"unit_done" must be true or false')
    for k in ("units_done", "units_planned"):
        if not isinstance(verdict.get(k), int) or verdict.get(k) < 0:
            dev.append(f'"{k}" must be a whole number read from plan.md')
    if isinstance(verdict.get("units_done"), int) and isinstance(verdict.get("units_planned"), int) \
            and verdict["units_done"] > verdict["units_planned"]:
        dev.append('"units_done" cannot exceed "units_planned"')
    for k in ("next", "reason"):
        if not str(verdict.get(k) or "").strip():
            dev.append(f'"{k}" is missing')
    if "chain_void" in verdict and not isinstance(verdict["chain_void"], bool):
        dev.append('"chain_void" is true when the chain\'s first phase shows its premise false, else absent')
    summary = verdict.get("summary")
    if summary is not None and not (isinstance(summary, str) and 0 < len(summary) <= 400):
        dev.append('"summary" is one plain sentence of at most 400 characters')
    return dev


def deviation_message(devs, phase):
    lines = [f"DEVIATION: your {phase} answer broke its contract. Fix exactly this and answer again "
             "with ONE JSON object:"]
    lines += [f"- {d}" for d in devs]
    return "\n".join(lines)
