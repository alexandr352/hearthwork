"""One unit of work: PLAN (operator) -> EXECUTE (executor) -> JUDGE (operator).

Every step leaves a record before the next begins, so a unit cut short anywhere is
picked up by the next run from what is on disk:

  resume.json         the executor stopped on a usage limit: the next run resumes
                      that same executor session and lets it finish
  judge-pending.json  the report exists but the operator could not judge it: the next
                      run judges it before planning anything new
  chain.json          a chain is open: every unit belongs to it until it commits

When the executor dies without a report (a timeout, a crash), a read-only SURVEY asks
what the tree holds, and the operator judges on that instead of on a one-line failure.
"""

import json
import time
import uuid
from dataclasses import dataclass, field

from . import claude, contract, fence, gitinfo
from .home import doctrine
from .records import Lock, Ticket, meter, now_iso, write_unit_file

RESUME_PROMPT = (
    "Your session was interrupted by a usage limit, which has since reset. Continue the unit "
    "exactly where you stopped. Do not re-derive settled ground. Finish the remaining scope and "
    "produce the complete report in the original return format."
)

SURVEY_PROMPT = (
    "STATE SURVEY — READ-ONLY. The previous session in this checkout ended WITHOUT returning a "
    "report. The working tree may hold most of a finished change, or a broken half-edit, and the "
    "operator cannot look for itself. Report what is actually there.\n\n"
    "DO NOT edit, create, delete, stage, commit, revert, or run tests, builds or linters. Read only.\n\n"
    "Report, in this order:\n"
    "1. The current branch, the HEAD sha, and `git status --porcelain` verbatim.\n"
    "2. `git diff --stat` for tracked modifications.\n"
    "3. For each modified file: what the change appears to do, in one or two sentences read from the diff.\n"
    "4. Whether each change looks COMPLETE or MID-EDIT (syntax that cannot parse, unbalanced blocks, "
    "stray debug lines, half-renamed symbols), quoting the evidence.\n"
    "5. Any untracked path, and whether it looks like a stranded scratch file.\n\n"
    "Do not judge whether the work is right or worth keeping; that is the operator's decision. "
    "Report only what is on disk, and say plainly when you cannot tell."
)

OPERATOR_TOOLS = ["Read", "Grep", "Glob", "Edit", "Write", "Skill", "TodoWrite"]
EXECUTOR_TOOLS = ["Bash", "Read", "Grep", "Glob", "Edit", "Write", "Agent", "Skill", "TodoWrite"]
RESUME_ATTEMPTS = 3
FAILURES_BEFORE_HALT = 3


@dataclass
class Outcome:
    status: str            # continue | ticket-ready | halted | walled | busy | idle | failed
    message: str
    ticket: str | None = None
    unit: int | None = None
    cost_usd: float = 0.0
    details: dict = field(default_factory=dict)

    @property
    def keep_going(self):
        return self.status == "continue"


class Loop:
    def __init__(self, project, cfg, log=print):
        self.p = project
        self.cfg = cfg
        self.log = log
        self.costs = claude.CostLedger(project.dir / "session-cost.json")
        self.bin = cfg["claude"]["bin"]
        self.models = cfg["models"]
        self.timeouts = cfg["timeouts"]

    # --- the two seats -------------------------------------------------------

    def _settings(self, cwd):
        s = fence.settings_for()
        s["claudeMdExcludes"] = claude.doctrine_excludes(cwd)
        return s

    def _policy_env(self, policy):
        policy = dict(policy, log=str(self.p.dir / "fence.log"))
        return {"HEARTHWORK_FENCE_POLICY": json.dumps(policy)}

    def operator_call(self, prompt, label, resume):
        return claude.run(
            claude_bin=self.bin, cwd=self.p.dir, prompt=prompt, model=self.models["operator"],
            timeout=self.timeouts["judge" if label.startswith("judge") else "plan"], label=label,
            costs=self.costs, resume=resume, tools=OPERATOR_TOOLS, setting_sources=["project"],
            settings=self._settings(self.p.dir),
            env_extra=self._policy_env({"mode": "operator", "own_dir": str(self.p.dir)}))

    def executor_call(self, prompt, label, model, timeout, resume=None, read_only=False):
        atlas = ""
        try:
            atlas = (self.p.dir / "atlas.md").read_text(encoding="utf-8")
        except OSError:
            pass
        system = doctrine("executor", "EXECUTOR.md") + "\n\n# ATLAS\n\n" + atlas
        policy = {"mode": "executor", "repo": str(self.p.repo), "protected": self.p.protected,
                  "network_commands": self.p.network_commands, "read_only": read_only}
        return claude.run(
            claude_bin=self.bin, cwd=self.p.repo, prompt=prompt, model=model, timeout=timeout,
            label=label, costs=self.costs, resume=resume, tools=EXECUTOR_TOOLS,
            setting_sources=["project", "local"], settings=self._settings(self.p.repo),
            append_system_prompt=system, env_extra=self._policy_env(policy))

    # --- the operator's session ----------------------------------------------

    def _session_for(self, t):
        sid = t.session()
        if not sid:
            return None
        age = claude.session_age_minutes(self.p.dir, sid)
        warm = float(self.cfg["operator"]["warm_minutes"])
        if age is not None and age > warm:
            self.log(f"operator session idle {age:.0f} min: waking cold from the files")
            t.drop_session()
            return None
        return sid

    def _ask_operator(self, t, prompt, label, check, phase, rec):
        """Ask, validate, and hand a broken answer back to the same session with its
        deviation. Returns (answer, None) or (None, Outcome)."""
        sid = self._session_for(t)
        tries = int(self.cfg["operator"]["reconsider"])
        devs = []
        for attempt in range(1, tries + 1):
            res = self.operator_call(prompt, f"{label}-{attempt}" if attempt > 1 else label, sid)
            if not res.ok and sid and not res.walled:
                self.log(f"{label}: resuming the operator session failed ({res.error}); trying a fresh one")
                t.drop_session()
                sid = None
                res = self.operator_call(prompt, label, None)
            rec["phases"].setdefault(phase, []).append(res.record())
            if not res.ok:
                if res.walled:
                    return None, Outcome("walled", f"{label}: the operator hit a usage limit; the next run continues",
                                         t.id, rec["unit"])
                return None, self._failed(t, rec, f"{label}: the operator call failed: {res.error}")
            sid = res.session_id or sid
            t.set_session(sid)
            answer = claude.extract_json(res.text)
            devs = check(answer)
            if not devs:
                return answer, None
            self.log(f"{label}: contract broken ({'; '.join(devs)}); returned for reconsideration")
            prompt = contract.deviation_message(devs, phase.upper())
        return None, self._halt(t, rec, f"the operator broke its {phase} contract {tries} times: {'; '.join(devs)}")

    # --- outcomes ------------------------------------------------------------

    def _halt(self, t, rec, reason):
        st = self.p.read_state()
        st["halted"] = {"reason": reason, "ticket": t.id, "unit": rec.get("unit"), "at": now_iso()}
        self.p.write_state(st)
        rec["outcome"] = "halted"
        return Outcome("halted", reason, t.id, rec.get("unit"))

    def _failed(self, t, rec, reason):
        st = self.p.read_state()
        st["failures"] = int(st.get("failures") or 0) + 1
        self.p.write_state(st)
        rec["outcome"] = "failed"
        if st["failures"] >= FAILURES_BEFORE_HALT:
            return self._halt(t, rec, f"{reason} ({st['failures']} failures in a row)")
        return Outcome("failed", reason, t.id, rec.get("unit"))

    # --- one unit ------------------------------------------------------------

    def run_unit(self):
        """One whole unit with a headless executor (`operator run`)."""
        return self._wrapped(self._unit)

    def _wrapped(self, body, *args):
        st = self.p.read_state()
        if st.get("halted"):
            h = st["halted"]
            return Outcome("halted", f"halted: {h.get('reason')}", h.get("ticket"), h.get("unit"))
        tid = st.get("active_ticket")
        if not tid:
            return Outcome("idle", "no active ticket: `operator ticket new` or `operator ticket use`")
        t = Ticket(self.p, tid)
        if not t.exists():
            return Outcome("failed", f"ticket {tid} has no ticket.md", tid)
        lock = Lock(self.p)
        if not lock.acquire():
            return Outcome("busy", "another run is working on this project", tid)
        rec = {"ts": now_iso(), "project": self.p.name, "ticket": tid, "unit": None, "phases": {}}
        t0 = time.time()
        try:
            out = body(t, rec, *args)
        finally:
            lock.release()
        rec["seconds"] = round(time.time() - t0, 1)
        rec["cost_usd"] = round(sum(c.get("cost_usd") or 0 for calls in rec["phases"].values() for c in calls), 6)
        rec.setdefault("outcome", out.status)
        out.cost_usd = rec["cost_usd"]
        if rec["phases"] and not rec.get("no_meter"):
            meter(self.p, rec)
        try:
            from . import worklog
            worklog.build()
        except Exception as e:  # the log page never stops the loop
            self.log(f"work log not rebuilt: {e}")
        return out

    # --- MCP: the person's own Claude Code session is the executor -------------

    def lease_plan(self):
        """Plan the next unit and open a lease on it for the person's session; or return
        the lease already open. A pending judgement is made first."""
        return self._wrapped(self._lease_plan)

    def lease_submit(self, lease_id, report):
        """Take the session's report for the open lease, read git, and judge."""
        return self._wrapped(self._lease_submit, lease_id, report)

    def _lease_plan(self, t, rec):
        lease = t.read("lease.json")
        if lease:
            rec["no_meter"] = True
            plan = json.loads((t.unit_dir(lease["unit"]) / "plan.json").read_text())
            return Outcome("lease", f"unit {lease['unit']} is open in your session", t.id, lease["unit"],
                           details={"lease": lease, "plan": plan})
        if t.read("judge-pending.json") or t.read("resume.json"):
            return self._unit(t, rec, recover_only=True)
        n, plan, stop = self._plan(t, rec)
        if stop:
            return stop
        lease = {"lease": uuid.uuid4().hex[:12], "unit": n, "before": gitinfo.snapshot(self.p.repo),
                 "opened": now_iso(), "opened_epoch": time.time()}
        t.write("lease.json", lease)
        rec["no_meter"] = True   # the unit is metered once, when it is judged
        t.write("lease-rec.json", rec)
        return Outcome("lease", f"unit {n} planned: {plan['title']}", t.id, n, details={"lease": lease, "plan": plan})

    def _lease_submit(self, t, rec, lease_id, report):
        lease = t.read("lease.json")
        if not lease:
            rec["no_meter"] = True
            return Outcome("failed", "no unit is open: call next first", t.id)
        if lease["lease"] != lease_id:
            rec["no_meter"] = True
            return Outcome("failed", f"lease {lease_id} is not the open one ({lease['lease']}, unit {lease['unit']})",
                           t.id, lease["unit"])
        planned = t.read("lease-rec.json") or {}
        rec.update({k: planned[k] for k in ("ts", "unit", "kind", "title") if k in planned})
        rec["phases"] = planned.get("phases") or {}
        rec["phases"]["execute"] = [{"label": "execute", "model": "your session", "seconds":
                                     round(time.time() - lease.get("opened_epoch", time.time()), 1),
                                     "cost_usd": None, "cost_basis": "not metered (your own session)"}]
        rec["executor"] = "mcp"
        n = lease["unit"]
        plan = json.loads((t.unit_dir(n) / "plan.json").read_text())
        t.clear("lease.json")
        t.clear("lease-rec.json")
        return self._after_execute(t, rec, n, plan, None, lease["before"], died=None,
                                   report_text=report)

    def _unit(self, t, rec, recover_only=False):
        if t.read("lease.json") and not recover_only:
            rec["no_meter"] = True
            return Outcome("busy", "a unit is open in a Claude Code session (MCP): submit it there, "
                                   "or `operator abandon` to drop it", t.id)
        pending = t.read("judge-pending.json")
        if pending:
            rec["unit"] = n = pending["unit"]
            rec["recovered"] = "judge-pending"
            self.log(f"{t.id} unit {n}: judging the report a previous run could not")
            return self._judge(t, rec, n, pending)

        resume = t.read("resume.json")
        if resume:
            n = resume["unit"]
            rec["unit"] = n
            plan = json.loads((t.unit_dir(n) / "plan.json").read_text())
            rec["kind"] = plan.get("kind")
            rec["title"] = plan.get("title")
            if int(resume.get("attempts") or 0) < RESUME_ATTEMPTS:
                rec["recovered"] = "resume"
                self.log(f"{t.id} unit {n}: resuming the executor session after a usage limit")
                return self._execute(t, rec, n, plan, resume=resume)
            self.log(f"{t.id} unit {n}: resumed {RESUME_ATTEMPTS} times without finishing; surveying the tree")
            t.clear("resume.json")
            return self._after_execute(t, rec, n, plan, None, resume["before"], died="resume attempts exhausted")

        n, plan, stop = self._plan(t, rec)
        if stop:
            return stop
        return self._execute(t, rec, n, plan)

    def _plan(self, t, rec):
        """(unit, plan, None) for an approved plan, or (None, None, Outcome) when it stops."""
        n = t.next_unit()
        rec["unit"] = n
        chain = t.read("chain.json")
        prompt = f"PHASE: PLAN\nTICKET: {t.id}\nUNIT: {n}\n"
        if chain:
            prompt += f"OPEN CHAIN: {chain['chain']} (phase {chain['phase']} of {chain['total']} done)\n"
        rulings = t.path("rulings.md")
        if rulings.exists():
            prompt += "RULINGS: tickets/%s/rulings.md holds the person's answers; read it.\n" % t.id
        try:
            prompt += "\n" + gitinfo.plan_facts(self.p.repo, self.p.trunk) + "\n"
        except Exception as e:  # facts are evidence, never a gate
            prompt += f"\nREPOSITORY FACTS AT PLAN: unreadable ({e})\n"
        self.log(f"{t.id} unit {n}: planning")
        plan, stop = self._ask_operator(
            t, prompt, "plan", lambda a: contract.check_plan(a, n, chain and chain["chain"]), "plan", rec)
        if stop:
            return None, None, stop
        write_unit_file(t, n, "plan.json", json.dumps(plan, indent=2))
        if plan["action"] == "halt":
            return None, None, self._halt(t, rec, plan["reason"])
        write_unit_file(t, n, "prompt.md", plan["prompt"])
        rec["kind"], rec["title"] = plan["kind"], plan["title"]
        if plan.get("chain"):
            t.write("chain.json", {"chain": plan["chain"], "phase": plan["chain_phase"] - 1,
                                   "total": plan["chain_total"], "unit": n})
        return n, plan, None

    def _execute(self, t, rec, n, plan, resume=None):
        before = resume["before"] if resume else gitinfo.snapshot(self.p.repo)
        self.log(f"{t.id} unit {n}: executing — {plan['title']}")
        if resume:
            res = self.executor_call(RESUME_PROMPT, "execute-resume", self.models["executor"],
                                     self.timeouts["execute"], resume=resume["session_id"])
        else:
            res = self.executor_call(plan["prompt"], "execute", self.models["executor"], self.timeouts["execute"])
        rec["phases"].setdefault("execute", []).append(res.record())
        if not res.ok and res.walled:
            sid = res.session_id or (resume or {}).get("session_id")
            if sid:
                t.write("resume.json", {"unit": n, "session_id": sid, "before": before,
                                        "attempts": int((resume or {}).get("attempts") or 0) + 1})
                rec["outcome"] = "walled"
                return Outcome("walled", f"unit {n}: the executor hit a usage limit; the next run resumes it", t.id, n)
        t.clear("resume.json")
        return self._after_execute(t, rec, n, plan, res, before, died=None if res.ok else res.error)

    def _after_execute(self, t, rec, n, plan, res, before, died, report_text=None):
        report = report_text if report_text is not None else (res.text if res and res.ok else None)
        survey_path = None
        if report is None:
            self.log(f"{t.id} unit {n}: the executor returned no report ({died}); surveying the tree")
            sv = self.executor_call(SURVEY_PROMPT, "survey", self.models["survey"], self.timeouts["survey"],
                                    read_only=True)
            rec["phases"].setdefault("survey", []).append(sv.record())
            if sv.ok:
                survey_path = write_unit_file(t, n, "survey.md", sv.text)
            report = f"EXECUTOR FAILED: {died}\n"
        write_unit_file(t, n, "report.md", report)
        diff = gitinfo.compare(self.p.repo, before, gitinfo.snapshot(self.p.repo))
        facts = gitinfo.facts_block(diff, self.p.repo, self.p.trunk)
        if died:
            facts += f"\nexecutor: FAILED ({died})"
        write_unit_file(t, n, "facts.md", facts)
        rec["git"] = {"commits": len(diff["commits"]), "files": len(diff["files_touched"]), "clean": diff["tree_clean"]}
        pending = {"unit": n, "survey": bool(survey_path), "commits": len(diff["commits"]),
                   "tree_clean": diff["tree_clean"], "exec_failed": bool(died)}
        t.write("judge-pending.json", pending)
        return self._judge(t, rec, n, pending)

    def _judge(self, t, rec, n, pending):
        rel = f"tickets/{t.id}/units/{n:02d}"
        facts = (t.unit_dir(n) / "facts.md").read_text(encoding="utf-8")
        prompt = (f"PHASE: JUDGE\nTICKET: {t.id}\nUNIT: {n}\nREPORT: {rel}/report.md\n"
                  + (f"SURVEY: {rel}/survey.md\n" if pending.get("survey") else "")
                  + "\n" + facts + "\n")
        self.log(f"{t.id} unit {n}: judging")
        verdict, stop = self._ask_operator(t, prompt, "judge", contract.check_verdict, "judge", rec)
        if stop:
            return stop
        write_unit_file(t, n, "verdict.json", json.dumps(verdict, indent=2))
        t.clear("judge-pending.json")
        rec["verdict"] = {k: verdict.get(k) for k in ("action", "unit_done", "units_done", "units_planned", "next", "reason")}
        st = self.p.read_state()
        st["failures"] = 0
        self.p.write_state(st)

        chain = t.read("chain.json")
        if chain and chain.get("unit") is not None:
            plan = json.loads((t.unit_dir(n) / "plan.json").read_text())
            if plan.get("chain") == chain["chain"] and verdict["unit_done"]:
                chain["phase"] = max(chain["phase"], plan.get("chain_phase") or 0)
                t.write("chain.json", chain)
        committed_clean = pending.get("commits", 0) > 0 and pending.get("tree_clean")
        if chain and committed_clean and chain["phase"] >= chain["total"]:
            t.clear("chain.json")
        if committed_clean or verdict["action"] != "continue":
            # The work crossed a commit (or stopped): the next unit starts from the files.
            t.drop_session()

        if verdict["action"] == "halt":
            return self._halt(t, rec, verdict["reason"])
        if verdict["action"] == "ticket-ready":
            st = self.p.read_state()
            st.setdefault("ready", [])
            if t.id not in st["ready"]:
                st["ready"].append(t.id)
            st["active_ticket"] = None
            self.p.write_state(st)
            rec["outcome"] = "ticket-ready"
            return Outcome("ticket-ready", f"{t.id} is ready: {verdict['reason']}", t.id, n)
        rec["outcome"] = "continue"
        return Outcome("continue", f"unit {n} judged: {verdict['reason']} — next: {verdict['next']}", t.id, n)
