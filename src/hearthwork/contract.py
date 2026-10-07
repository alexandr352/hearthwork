"""The contracts the operator's answers must keep, checked by the program.

A broken answer is never silently retried or repaired here: the deviation is named
and handed back to the same session for reconsideration.
"""

BUDGETS = {"LOW": (2, 150), "MEDIUM": (5, 300), "HIGH": (10, 600)}
FINDINGS_MARK = "| Finding:"
SCOPE_MARK = "SCOPE CONSTRAINT:"
PROMPT_MAX = 24000


def check_plan(plan, unit, open_chain=None):
    """A list of deviations; empty when the plan keeps its contract."""
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
    chain = plan.get("chain")
    if chain:
        phase, total = plan.get("chain_phase"), plan.get("chain_total")
        if not (isinstance(phase, int) and isinstance(total, int) and 1 <= phase <= total and total >= 2):
            dev.append('a chain unit carries "chain_phase" and "chain_total" with 1 <= phase <= total and total >= 2')
        elif commit and phase != total:
            dev.append("only the last phase of a chain commits")
        elif phase == total and kind != "execution":
            dev.append("the last phase of a chain is the committing execution")
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
    return dev


def deviation_message(devs, phase):
    lines = [f"DEVIATION: your {phase} answer broke its contract. Fix exactly this and answer again "
             "with ONE JSON object:"]
    lines += [f"- {d}" for d in devs]
    return "\n".join(lines)
