"""`operator mcp`: hearthwork as an MCP server for your own Claude Code session.

Register it once in a repository:

    claude mcp add hearthwork -- operator mcp

Your interactive session then becomes the executor: it calls `next` for a unit, does
the work in front of you, and calls `submit` with its report. The operator still plans
and judges in its own fenced, headless session, so the judge stays independent of the
one doing the work, and the program still reads git for itself.

Planning and judging take minutes. A tool call waits up to WAIT seconds, then answers
"still working, call again"; the work continues in this process, and the next call
picks it up where it stands.
"""

import json
import sys
import threading
import time

from . import __version__, home, lab
from .home import doctrine
from .loop import Loop

WAIT = 50
PROTOCOL = "2025-06-18"

TOOLS = [
    {
        "name": "next",
        "description": (
            "Get the next unit of hearthwork ticket work for this repository. Returns the unit's prompt and "
            "the rules for doing it. Do exactly that unit, in this checkout, then call `submit` with your full "
            "report. If it says the operator is still planning, call `next` again. If a unit is already open, "
            "it returns that unit again."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "submit",
        "description": (
            "Hand in the report for the open unit. The program reads git itself and the operator judges the "
            "report against it. If it says the operator is still judging, call `submit` again with the same "
            "lease and an empty report to collect the verdict."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lease": {"type": "string", "description": "the lease id `next` gave"},
                "report": {"type": "string", "description": "the full report, in the return format the unit asked for"},
            },
            "required": ["lease", "report"],
            "additionalProperties": False,
        },
    },
    {
        "name": "status",
        "description": "Where the work stands: the active ticket, the last verdict, any halt, and the cost so far.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "rule",
        "description": (
            "Record the person's answer to a halt, in their own words, and lift the halt. Use only with "
            "the person's decision, never your own."),
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
                        "additionalProperties": False},
    },
]


class Job:
    """A plan or a judgement running in this process while tool calls come and go."""

    def __init__(self, kind, fn, *args):
        self.kind, self.result, self.error = kind, None, None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(fn, *args), daemon=True)
        self.thread.start()

    def _run(self, fn, *args):
        try:
            self.result = fn(*args)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.done.set()


class Server:
    def __init__(self, project_name=None):
        self.project_name = project_name
        self.job = None
        self.lock = threading.Lock()
        self.logs = []

    def project(self):
        return home.resolve_project(self.project_name)

    def loop(self):
        return Loop(self.project(), home.load_config(), log=lambda m: self.logs.append(m))

    # --- tools -----------------------------------------------------------------

    def wait(self, kind, start):
        with self.lock:
            if self.job is None or self.job.done.is_set() and self.job.kind != kind:
                self.job = Job(kind, start)
            job = self.job
        if job.kind != kind:
            return None, f"the operator is still busy with a {job.kind}; call that tool again first"
        if not job.done.wait(WAIT):
            return None, f"STILL {('PLANNING' if kind == 'plan' else 'JUDGING')}: the operator is working. Call `{'next' if kind == 'plan' else 'submit'}` again to wait for it."
        with self.lock:
            self.job = None
        if job.error:
            return None, f"hearthwork failed: {job.error}"
        return job.result, None

    def tool_next(self, args):
        loop = self.loop()
        out, msg = self.wait("plan", loop.lease_plan)
        if msg:
            return msg, False
        if out.status != "lease":
            return self.describe(out), out.status in ("failed",)
        lease, plan = out.details["lease"], out.details["plan"]
        p = self.project()
        try:
            atlas = (p.dir / "atlas.md").read_text(encoding="utf-8")
        except OSError:
            atlas = ""
        commit = "COMMIT when done, as the unit says." if plan.get("commit_expected") else \
            "DO NOT COMMIT in this unit: leave the work in the tree."
        text = (f"HEARTHWORK UNIT {out.unit} of ticket {out.ticket} — {plan['title']}\n"
                f"lease: {lease['lease']}   kind: {plan['kind']}   {commit}\n\n"
                "Do exactly this unit in this checkout, following the rules below, then call `submit` with "
                "this lease and your full report. Show the person what you change as you go.\n\n"
                "=== THE UNIT ===\n" + plan["prompt"] + "\n\n"
                "=== HOW TO DO IT (the executor's rules) ===\n" + doctrine("executor", "EXECUTOR.md") +
                "\n\n=== ATLAS (the project's map) ===\n" + atlas +
                "\n\n=== " + lab.brief(p).lstrip("# ") +
                "\n\n=== IN YOUR SESSION ===\nThe hw-investigator, hw-prober and hw-reviewer sub-agents and the "
                "hearthwork:hw-* skills ride only on hearthwork's own executor. Here, do their work yourself under the "
                "same rules: probes only in the scratch folder, run once through `operator lab gate`; the guard "
                "proven by `operator lab ab`; one review of the whole diff before a commit.")
        return text, False

    def tool_submit(self, args):
        lease_id = str(args.get("lease") or "")
        report = str(args.get("report") or "")
        loop = self.loop()
        with self.lock:
            running = self.job is not None and self.job.kind == "judge"
        if not running and not report.strip():
            return "the report is empty: submit the full report of the unit", True
        out, msg = self.wait("judge", lambda: loop.lease_submit(lease_id, report))
        if msg:
            return msg, False
        return self.describe(out), out.status == "failed"

    def describe(self, out):
        cost = f" (operator ${out.cost_usd:.2f})" if out.cost_usd else ""
        if out.status == "continue":
            return f"{out.message}{cost}\nCall `next` for the next unit when the person is ready."
        if out.status == "ticket-ready":
            return f"{out.message}{cost}\nThe ticket is ready for the person's review. Nothing is pushed."
        if out.status == "halted":
            return (f"HALTED: {out.message}{cost}\nAsk the person. When they decide, record their words "
                    "with `rule`, then call `next`.")
        return f"{out.status}: {out.message}{cost}"

    def tool_status(self, args):
        import contextlib
        import io
        from . import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["status", "-p", self.project().name])
        return buf.getvalue(), False

    def tool_rule(self, args):
        import contextlib
        import io
        from . import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["rule", "-p", self.project().name, str(args.get("text") or "")])
        return buf.getvalue() or "not recorded", code != 0

    # --- JSON-RPC over stdio ---------------------------------------------------

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": ver, "capabilities": {"tools": {}},
                "serverInfo": {"name": "hearthwork", "version": __version__},
                "instructions": ("hearthwork runs ticket work unit by unit. Call `next` to get a unit, do it, "
                                 "and `submit` the report. Never invent a ruling: `rule` records the person's words.")}}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": mid, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
        if method == "tools/call":
            params = msg.get("params") or {}
            name, args = params.get("name"), params.get("arguments") or {}
            fn = getattr(self, f"tool_{name}", None)
            if fn is None:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
            try:
                text, is_error = fn(args)
            except home.HomeError as e:
                text, is_error = str(e), True
            except Exception as e:
                text, is_error = f"hearthwork error: {type(e).__name__}: {e}", True
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}],
                                                             "isError": bool(is_error)}}
        if mid is None:
            return None  # a notification
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve(project_name=None, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    server = Server(project_name)
    out_lock = threading.Lock()

    def reply(obj):
        if obj is None:
            return
        with out_lock:
            stdout.write(json.dumps(obj) + "\n")
            stdout.flush()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        if msg.get("method") == "tools/call":
            # A long tool call must not block pings and other calls.
            threading.Thread(target=lambda m=msg: reply(server.handle(m)), daemon=True).start()
        else:
            reply(server.handle(msg))
    time.sleep(0.1)
    return 0
