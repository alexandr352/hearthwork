#!/usr/bin/env python3
"""A stand-in for the Claude Code CLI: answers each phase from the prompt it is given."""
import json, os, re, subprocess, sys, uuid
from pathlib import Path

argv = sys.argv[1:]
prompt = sys.stdin.read()
state = Path(os.environ["FAKE_STATE"])
state.mkdir(parents=True, exist_ok=True)
calls = state / "calls.jsonl"
resume = argv[argv.index("--resume") + 1] if "--resume" in argv else None
sid = resume or str(uuid.uuid4())
totals = json.loads((state / "totals.json").read_text()) if (state / "totals.json").exists() else {}
totals[sid] = round(totals.get(sid, 0) + 0.10, 4)
(state / "totals.json").write_text(json.dumps(totals))
with open(calls, "a") as f:
    f.write(json.dumps({"cwd": os.getcwd(), "resume": resume, "prompt": prompt[:200], "argv": argv}) + "\n")

def envelope(result, is_error=False, code=0):
    print(json.dumps({"type": "result", "result": result, "is_error": is_error, "session_id": sid,
                      "total_cost_usd": totals[sid], "usage": {"input_tokens": 10, "cache_read_input_tokens": 90,
                      "cache_creation_input_tokens": 0, "output_tokens": 5}, "modelUsage": {"fake-model": {}}}))
    sys.exit(code)

def flag(name):
    p = state / name
    if p.exists():
        p.unlink()
        return True
    return False

if prompt.startswith("PHASE: PLAN") or prompt.startswith("DEVIATION") and "PLAN" in prompt:
    if flag("plan-bad-once"):
        envelope('{"action": "execute", "unit": 1}')
    if flag("plan-halt"):
        envelope(json.dumps({"action": "halt", "reason": "Which currency should totals use?"}))
    m = re.search(r"UNIT: (\d+)", prompt)
    n = int(m.group(1)) if m else int((state / "last-unit").read_text()) if (state / "last-unit").exists() else 1
    (state / "last-unit").write_text(str(n))
    if n == 1:
        plan = {"action": "execute", "unit": 1, "kind": "investigation", "title": "find the total function",
                "budget": "LOW", "commit_expected": False, "chain": "total", "chain_phase": 1, "chain_total": 2,
                "prompt": "SCOPE CONSTRAINT: Read at most 2 files. Read at most 150 lines per file. Do not exceed these limits regardless of what you find. If the question cannot be answered within these limits, stop and report what you found and what remains unread.\nQUESTIONS: where is total computed?\nRETURN FORMAT: [N] File: <path> | Line: <line> | Finding: <fact> | Confidence: <high>",
                "notes": "first look"}
    else:
        plan = {"action": "execute", "unit": n, "kind": "execution", "title": "fix the total and commit",
                "budget": "NONE", "commit_expected": True, "chain": "total", "chain_phase": 2, "chain_total": 2,
                "prompt": "The total now includes tax.\nTARGET FILES: total.txt\nINVARIANTS: nothing else changes\nCOMMIT: yes, on branch T-1-total",
                "notes": "the fix"}
    envelope(json.dumps(plan))
if prompt.startswith("PHASE: JUDGE"):
    n = int(re.search(r"UNIT: (\d+)", prompt).group(1))
    action = "ticket-ready" if n >= 2 else "continue"
    envelope(json.dumps({"action": action, "unit_done": True, "units_done": n, "units_planned": 2,
                         "next": "unit 2: the fix" if n < 2 else "review and merge", "reason": f"unit {n} did what it said"}))
if prompt.startswith("STATE SURVEY"):
    envelope("SURVEY: branch T-1-total, tree has total.txt modified, change looks complete")
if prompt.startswith("Your session was interrupted"):
    envelope("STATUS: success\nFILES CHANGED:\ntotal.txt\n(resumed and finished)")
# the executor
if flag("exec-wall"):
    envelope("You've hit your session limit · resets 3pm", is_error=True, code=1)
if flag("exec-crash"):
    Path("total.txt").write_text("half an edit\n")
    sys.exit(3)
if "TARGET FILES" in prompt:
    subprocess.run(["git", "checkout", "-q", "-b", "T-1-total"], capture_output=True)
    Path("total.txt").write_text("total = price + tax\n")
    subprocess.run(["git", "add", "total.txt"], check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Totals include tax"], check=True)
    envelope("STATUS: success\nFILES CHANGED:\ntotal.txt\nGATES: none named")
envelope("[1] File: total.txt | Line: 1 | Finding: total = price | Confidence: high\nOPEN QUESTIONS: none")
