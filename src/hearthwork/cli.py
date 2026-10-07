"""`operator` — the command line of hearthwork."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, home
from .records import Ticket, now_iso, read_meter


def out(msg=""):
    print(msg, flush=True)


def fail(msg):
    print(f"operator: {msg}", file=sys.stderr)
    return 2


def project_of(args):
    return home.resolve_project(getattr(args, "project", None))


# --- init and projects -----------------------------------------------------------

def cmd_init(args):
    h, created = home.init_home()
    out(f"home: {h}")
    for p in created:
        out(f"  created {p.relative_to(h)}")
    if not created:
        out("  (already set up)")
    out("\nnext: operator project add <name> --repo <path to a git checkout>")
    return 0


def cmd_project_add(args):
    home.init_home()
    p = home.add_project(args.name, args.repo, args.trunk)
    out(f"project {p.name}: {p.repo} (trunk {p.trunk})")
    out(f"  its records: {p.dir}")
    out(f"  edit {p.dir / 'project.toml'} to adjust protected branches and network commands")
    out("\nnext: operator atlas      drafts the map every session reads first, from the repository itself")
    out("                          (one read-only session; you review the result and answer its questions)")
    out("then: operator ticket new <ID> --title \"...\" --file <ticket.md>")
    return 0


def cmd_project_list(args):
    ps = home.projects()
    if not ps:
        out("no projects yet: operator project add <name> --repo <path>")
    for p in ps:
        st = p.read_state()
        out(f"{p.name:20} {p.repo}  active={st.get('active_ticket') or '-'}"
            + (f"  HALTED" if st.get("halted") else ""))
    return 0


def cmd_upgrade(args):
    for p in home.projects():
        home.refresh_doctrine(p.dir)
        out(f"{p.name}: operator doctrine refreshed")
    sp = home.home_dir() / "spirit" / "CLAUDE.md"
    if sp.parent.is_dir():
        sp.write_text(home.doctrine("spirit", "CLAUDE.md"), encoding="utf-8")
        out("spirit: doctrine refreshed (your persona and its memory are untouched)")
    return 0


# --- tickets ---------------------------------------------------------------------

def cmd_ticket_new(args):
    p = project_of(args)
    if not home.TICKET_ID.match(args.id):
        return fail("a ticket id is letters, digits, '.', '_' or '-' (e.g. T-12, bug-checkout)")
    t = Ticket(p, args.id)
    if t.exists():
        return fail(f"ticket {args.id} already exists")
    if args.file:
        body = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        body = args.text
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        return fail("give the ticket text with --file, --text, or on stdin")
    title = args.title or body.strip().splitlines()[0].lstrip("# ").strip()[:120]
    t.dir.mkdir(parents=True, exist_ok=True)
    home.write_atomic(t.path("ticket.md"), f"# {args.id} — {title}\n\n{body.strip()}\n")
    t.write("meta.json", {"id": args.id, "title": title, "created": now_iso()})
    st = p.read_state()
    if not st.get("active_ticket") or args.use:
        st["active_ticket"] = args.id
        p.write_state(st)
        out(f"ticket {args.id} created and active")
    else:
        out(f"ticket {args.id} created (active stays {st['active_ticket']}; `operator ticket use {args.id}` to switch)")
    return 0


def cmd_ticket_list(args):
    p = project_of(args)
    st = p.read_state()
    if not p.tickets.is_dir():
        return 0
    for d in sorted(p.tickets.iterdir()):
        t = Ticket(p, d.name)
        if not t.exists():
            continue
        meta = t.read("meta.json") or {}
        mark = "*" if st.get("active_ticket") == d.name else " "
        ready = " ready" if d.name in (st.get("ready") or []) else ""
        out(f"{mark} {d.name:16} units={len(t.units()):3}{ready}  {meta.get('title', '')}")
    return 0


def cmd_ticket_use(args):
    p = project_of(args)
    if not Ticket(p, args.id).exists():
        return fail(f"no ticket {args.id}")
    st = p.read_state()
    if st.get("halted") and st["halted"].get("ticket") != args.id:
        out(f"note: the project is halted on {st['halted'].get('ticket')}; `operator resume` lifts it")
    st["active_ticket"] = args.id
    st["ready"] = [x for x in (st.get("ready") or []) if x != args.id]
    p.write_state(st)
    out(f"active ticket: {args.id}")
    return 0


# --- the loop --------------------------------------------------------------------

def cmd_run(args):
    from .loop import Loop
    p = project_of(args)
    cfg = home.load_config()
    loop = Loop(p, cfg, log=lambda m: out(f"[{now_iso()}] {m}"))
    from .awake import from_config
    with from_config(cfg, why=f"hearthwork is running units on {p.name}"):
        return run_loop(loop, args)


def run_loop(loop, args):
    spent, units = 0.0, 0
    while True:
        o = loop.run_unit()
        spent += o.cost_usd or 0.0
        if o.unit is not None:
            units += 1
        out(f"[{now_iso()}] {o.status}: {o.message}  (${o.cost_usd:.2f})")
        if not o.keep_going:
            break
        if args.units and units >= args.units:
            break
        if args.max_cost and spent >= args.max_cost:
            out(f"stopping: ${spent:.2f} spent, the limit is ${args.max_cost:.2f}")
            break
    out(f"spent ${spent:.2f} over {units} unit(s)")
    return 0 if o.status in ("continue", "ticket-ready", "idle", "busy", "walled") else 1


def cmd_status(args):
    ps = [project_of(args)] if args.project else home.projects()
    if not ps:
        out("no projects yet: operator init, then operator project add")
        return 0
    for p in ps:
        st = p.read_state()
        meter = read_meter(p)
        spent = sum(r.get("cost_usd") or 0 for r in meter)
        out(f"{p.name} — {p.repo}")
        from . import atlas as _atlas
        _qs = _atlas.question_list(p)
        _seed = _atlas.is_seed((p.dir / "atlas.md").read_text(encoding="utf-8")) if (p.dir / "atlas.md").exists() else True
        if _seed:
            out("  atlas: not drafted yet (operator atlas)")
        elif _qs:
            _open = [n for n, _, a in _qs if not a]
            out(f"  atlas: {len(_qs) - len(_open)} of {len(_qs)} questions answered"
                + (f"; open: {', '.join(map(str, _open))} (operator atlas questions)" if _open else ""))
        if st.get("halted"):
            h = st["halted"]
            out(f"  HALTED on {h.get('ticket')} unit {h.get('unit')}: {h.get('reason')}")
            out("  answer with: operator rule \"<your decision>\"   (or: operator resume)")
        active = st.get("active_ticket")
        out(f"  active ticket: {active or '-'}")
        if active:
            t = Ticket(p, active)
            last = None
            for n in reversed(t.units()):
                v = t.unit_dir(n) / "verdict.json"
                if v.exists():
                    last = (n, json.loads(v.read_text()))
                    break
            if last:
                n, v = last
                out(f"  unit {n}: {v.get('action')} — {v.get('reason')}")
                out(f"  progress: {v.get('units_done')} of {v.get('units_planned')} units done; next: {v.get('next')}")
            for name, what in (("resume.json", "an executor session waits to be resumed"),
                               ("judge-pending.json", "a report waits to be judged"),
                               ("chain.json", "a chain is open")):
                if t.path(name).exists():
                    out(f"  pending: {what}")
            tick = [r for r in meter if r.get("ticket") == active]
            out(f"  this ticket: {len(tick)} units, ${sum(r.get('cost_usd') or 0 for r in tick):.2f}")
        if st.get("ready"):
            out(f"  ready for you: {', '.join(st['ready'])}")
        out(f"  all units: {len(meter)}, ${spent:.2f}")
    return 0


def cmd_halt(args):
    p = project_of(args)
    st = p.read_state()
    st["halted"] = {"reason": args.reason, "ticket": st.get("active_ticket"), "unit": None, "at": now_iso(), "by": "you"}
    p.write_state(st)
    out("halted")
    return 0


def cmd_resume(args):
    p = project_of(args)
    st = p.read_state()
    if not st.pop("halted", None):
        out("not halted")
        return 0
    st["failures"] = 0
    p.write_state(st)
    out("resumed: the next run continues")
    return 0


def cmd_rule(args):
    p = project_of(args)
    st = p.read_state()
    tid = (st.get("halted") or {}).get("ticket") or st.get("active_ticket")
    if not tid:
        return fail("no ticket to rule on")
    t = Ticket(p, tid)
    halt = st.get("halted") or {}
    entry = f"\n## {now_iso()}\n"
    if halt.get("reason"):
        entry += f"Question: {halt['reason']}\n"
    entry += f"Ruling: {args.text.strip()}\n"
    with open(t.path("rulings.md"), "a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write(f"# Rulings on {tid}\n\nThe person's answers. Each binds every later unit.\n")
        f.write(entry)
    st.pop("halted", None)
    st["failures"] = 0
    p.write_state(st)
    out(f"ruling recorded on {tid}; the halt is lifted")
    return 0


# --- the page, the spirit, the doctor -------------------------------------------

def cmd_log(args):
    from . import worklog
    path = worklog.build()
    out(str(path))
    return 0


def cmd_chat(args):
    from . import spirit
    h, _ = home.init_home()
    cfg = home.load_config()
    claude = shutil.which(cfg["claude"]["bin"]) or cfg["claude"]["bin"]
    tail, env = spirit.launch(h)
    argv = [claude, *tail, "--model", args.model or cfg["models"]["spirit"]]
    os.chdir(spirit.spirit_dir(h))
    os.execvpe(claude, argv, env)


def cmd_atlas(args):
    from . import atlas
    p = project_of(args)
    if args.action == "questions":
        qs = atlas.question_list(p)
        if not qs:
            out("no questions: the atlas is not drafted yet, or it asked none")
        for n, q, a in qs:
            out(f"{n}. {q}")
            out(f"   Answer: {a}" if a else "   (not answered yet)")
        return 0
    if args.action == "answer":
        if len(args.rest) < 2 or not args.rest[0].isdigit():
            return fail('say which question and the answer: operator atlas answer 3 "bug fixes only"')
        try:
            atlas.answer(p, int(args.rest[0]), " ".join(args.rest[1:]))
        except atlas.AtlasError as e:
            return fail(str(e))
        left = sum(1 for _, _, a in atlas.question_list(p) if not a)
        out(f"answer {args.rest[0]} recorded in the atlas; {left} question(s) left")
        return 0
    try:
        path, qs, cost = atlas.build(p, home.load_config(), force=args.force, log=lambda m: out(m))
    except atlas.AtlasError as e:
        return fail(str(e))
    out(f"\natlas written: {path}  (${cost:.2f})")
    if qs:
        out("\nIt could not find these in the repository; only you know them:\n")
        out(qs)
        out("\nAnswer them, one at a time with the spirit's help:")
        out("  operator ui     then \"answer them with the spirit\" on the page")
        out("or here:  operator atlas answer <n> \"your answer\"   (operator atlas questions lists them)")
    return 0


def onoff(v):
    if v is None:
        return None
    if v in ("on", "off"):
        return v == "on"
    raise home.HomeError("say on or off")


def cmd_economy(args):
    from . import economy
    changes = {}
    if args.mcp is not None:
        changes["mcp"] = onoff(args.mcp)
    if args.claude_md is not None:
        changes["claude_md"] = onoff(args.claude_md)
    if args.cache is not None:
        changes["cache"] = args.cache
    if args.reset:
        changes = dict(economy.DEFAULTS)
    eco = economy.save(changes) if changes else economy.load()
    out(f"token economy: {economy.label(eco)}   (the first option of each row saves tokens and is the default)")
    out(f"  MCP servers        {'yours' if eco['mcp'] else 'none':16} none | yours"
        + ("   (the executor may call only the tools a project lists in mcp_allow)" if eco["mcp"] else ""))
    out(f"  your CLAUDE.md     {'included' if eco['claude_md'] else 'left out':16} left out | included")
    out(f"  prompt cache       {'tuned per role' if eco['cache'] == 'policy' else 'CLI default':16} tuned per role | CLI default"
        + ("   (operator and spirit 1 h, executor 5 min)" if eco["cache"] == "policy" else ""))
    if eco["mcp"]:
        for p in home.projects():
            out(f"  {p.name}: mcp_allow = {p.mcp_allow or '[] (nothing may be called yet)'}")
    out("  fixed: each role's own tools, no background tasks, the fence")
    return 0


def cmd_mcp(args):
    from . import mcp
    return mcp.serve(args.project)


def cmd_abandon(args):
    p = project_of(args)
    st = p.read_state()
    tid = st.get("active_ticket")
    if not tid:
        return fail("no active ticket")
    t = Ticket(p, tid)
    lease = t.read("lease.json")
    if not lease:
        out("no unit is open")
        return 0
    t.clear("lease.json")
    t.clear("lease-rec.json")
    with open(t.path("rulings.md"), "a", encoding="utf-8") as f:
        if f.tell() == 0:
            f.write(f"# Rulings on {tid}\n\nThe person's answers. Each binds every later unit.\n")
        f.write(f"\n## {now_iso()}\nRuling: unit {lease['unit']} was abandoned before it was done; its work, "
                "if any, is whatever the tree now shows. Plan from the tree as it stands.\n")
    out(f"unit {lease['unit']} abandoned; the next plan is told so")
    return 0


def cmd_ui(args):
    from . import server
    home.init_home()
    return server.serve(port=args.port, open_browser=not args.no_browser)


def cmd_doctor(args):
    ok = True
    cfg = home.load_config()
    exe = shutil.which(cfg["claude"]["bin"])
    out(f"claude: {exe or 'NOT FOUND'}")
    if exe:
        v = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()
        out(f"  version: {v}")
    else:
        ok = False
    out(f"git: {shutil.which('git') or 'NOT FOUND'}")
    ok = ok and bool(shutil.which("git"))
    h = home.home_dir()
    out(f"home: {h} {'(ok)' if (h / 'config.toml').exists() else '(not set up: operator init)'}")
    settings = Path.home() / ".claude" / "settings.json"
    try:
        if json.loads(settings.read_text()).get("disableAllHooks"):
            out("WARNING: ~/.claude/settings.json sets disableAllHooks: the fence would not run. Remove it.")
            ok = False
    except (OSError, ValueError):
        pass
    from .awake import from_config
    import time
    a = from_config(cfg)
    if not a.enabled:
        out("sleep guard: off (config [awake] enabled = false, or HEARTHWORK_NO_AWAKE)")
    elif not a.command():
        out("sleep guard: unavailable here (needs caffeinate on macOS or systemd-inhibit on Linux)")
    else:
        with a:
            time.sleep(1)
            works = a.holding
        out(f"sleep guard: {a.command()[0]} " + ("works" if works else
            "was refused (normal over SSH; a desktop session allows it)"))
    for p in home.projects():
        out(f"project {p.name}: {'ok' if (p.repo / '.git').exists() else 'REPOSITORY MISSING'} {p.repo}")
    return 0 if ok else 1


# --- parser ----------------------------------------------------------------------

def parser():
    ap = argparse.ArgumentParser(prog="operator", description="hearthwork: plan -> execute -> judge, for Claude Code")
    ap.add_argument("--version", action="version", version=f"hearthwork {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_project(sp):
        sp.add_argument("--project", "-p", help="the project (default: the one holding the current directory)")
        return sp

    sub.add_parser("init", help="create the home").set_defaults(fn=cmd_init)

    pj = sub.add_parser("project", help="add or list projects").add_subparsers(dest="sub", required=True)
    sp = pj.add_parser("add", help="register a git checkout")
    sp.add_argument("name")
    sp.add_argument("--repo", required=True)
    sp.add_argument("--trunk")
    sp.set_defaults(fn=cmd_project_add)
    pj.add_parser("list").set_defaults(fn=cmd_project_list)

    tk = sub.add_parser("ticket", help="add, list or switch tickets").add_subparsers(dest="sub", required=True)
    sp = with_project(tk.add_parser("new", help="add a ticket"))
    sp.add_argument("id")
    sp.add_argument("--title")
    sp.add_argument("--file")
    sp.add_argument("--text")
    sp.add_argument("--use", action="store_true", help="make it the active ticket")
    sp.set_defaults(fn=cmd_ticket_new)
    with_project(tk.add_parser("list")).set_defaults(fn=cmd_ticket_list)
    sp = with_project(tk.add_parser("use", help="make a ticket active"))
    sp.add_argument("id")
    sp.set_defaults(fn=cmd_ticket_use)

    sp = with_project(sub.add_parser("run", help="run units on the active ticket"))
    sp.add_argument("--units", "-n", type=int, default=1, help="stop after this many units (default 1; 0 = until it stops)")
    sp.add_argument("--max-cost", type=float, help="stop once this many dollars are spent")
    sp.set_defaults(fn=cmd_run)

    sp = with_project(sub.add_parser("status", help="where the work stands"))
    sp.set_defaults(fn=cmd_status)
    sp = with_project(sub.add_parser("halt", help="stop the loop with a reason"))
    sp.add_argument("reason")
    sp.set_defaults(fn=cmd_halt)
    with_project(sub.add_parser("resume", help="lift a halt")).set_defaults(fn=cmd_resume)
    sp = with_project(sub.add_parser("rule", help="answer a halt; the operator reads it on the next unit"))
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_rule)

    sub.add_parser("log", help="rebuild the work log page and print its path").set_defaults(fn=cmd_log)
    sp = sub.add_parser("chat", help="talk to the spirit")
    sp.add_argument("--model")
    sp.set_defaults(fn=cmd_chat)
    sp = sub.add_parser("economy", help="show or switch what Claude calls carry: MCP servers, your CLAUDE.md, the cache policy")
    sp.add_argument("--mcp", choices=["on", "off"])
    sp.add_argument("--claude-md", dest="claude_md", choices=["on", "off"])
    sp.add_argument("--cache", choices=["policy", "auto"])
    sp.add_argument("--reset", action="store_true", help="back to full economy")
    sp.set_defaults(fn=cmd_economy)
    sp = with_project(sub.add_parser("atlas", help="draft the project's atlas (one read-only session), list its questions, or answer one",
                                     description="operator atlas                draft the map from the repository\n"
                                                 "operator atlas questions      the questions it asked you, and which are answered\n"
                                                 "operator atlas answer 3 TEXT  record your answer to question 3",
                                     formatter_class=argparse.RawDescriptionHelpFormatter))
    sp.add_argument("action", nargs="?", default="draft", choices=["draft", "questions", "answer"])
    sp.add_argument("rest", nargs="*", help="for answer: the question number, then the answer")
    sp.add_argument("--force", action="store_true", help="draft again over an edited atlas (the old one is kept)")
    sp.set_defaults(fn=cmd_atlas)
    sp = with_project(sub.add_parser("mcp", help="serve hearthwork to your Claude Code session (claude mcp add hearthwork -- operator mcp)"))
    sp.set_defaults(fn=cmd_mcp)
    sp = with_project(sub.add_parser("abandon", help="drop a unit left open by an MCP session"))
    sp.set_defaults(fn=cmd_abandon)
    sp = sub.add_parser("ui", help="serve the work log with the spirit's chat on this machine")
    sp.add_argument("--port", type=int, default=0, help="default: a free port")
    sp.add_argument("--no-browser", action="store_true")
    sp.set_defaults(fn=cmd_ui)
    sub.add_parser("doctor", help="check the setup").set_defaults(fn=cmd_doctor)
    sub.add_parser("upgrade", help="refresh every project's operator doctrine from this version").set_defaults(fn=cmd_upgrade)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except home.HomeError as e:
        return fail(str(e))
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # the reader went away (`operator status | head`): stop quietly, as a pipe expects
        import os as _os
        _os.dup2(_os.open(_os.devnull, _os.O_WRONLY), sys.stdout.fileno())
        return 0
