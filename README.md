# hearthwork

A plan → execute → judge loop for [Claude Code](https://claude.com/claude-code), with a
home, a work log, and a spirit you can talk to.

You give it a ticket. An **operator** plans the work in small units and writes a prompt
for each. An **executor** does the unit in your checkout, behind a fence. The operator
judges the report against what git actually shows, updates the plan, and writes down what
it learned. A ticket moves unit by unit until the operator judges it ready, or stops to
ask you a question.

```
            ┌─────────── operator (plans, judges, remembers) ───────────┐
ticket ──►  │ PLAN: one bounded prompt   JUDGE: report + git facts → verdict │ ──► ready
            └──────────────┬──────────────────────────▲──────────────────┘
                           ▼                          │
                executor in your checkout ──► report ─┘   (fenced, cold, 45 min)
```

It is extracted from a system that has carried hundreds of units of real ticket work
unattended. What made that work was not prompting. It was structure:

- **The judge never sees the code.** The operator cannot read your repository; it reasons
  from the executor's report and from facts the program reads from git (commits, files
  touched, a clean or dirty tree). When a report claims something git does not show, the
  facts win.
- **Every answer has a contract, checked by code.** A plan without its scope line, or an
  execution without target files, never runs. A broken answer goes back to the *same*
  session with the deviation named, up to three times; then the loop halts and asks you.
- **Investigation before execution.** No change is written on a hypothesis. Work that ends
  in one commit is a *chain*: the investigations it needs, the changes, and one last unit
  that runs the gates and commits.
- **Nothing is lost when a session dies.** A usage limit mid-unit resumes the same executor
  session on the next run. A report the operator could not judge is judged first next time.
  An executor that crashed gets a read-only survey of the tree, and the operator judges
  that instead of a one-line failure.
- **Cold starts are cheap.** After each verdict the operator rewrites a short handover file,
  so a fresh session picks up where the last one stopped without re-reading everything.
- **Every call is metered.** Seconds, model and dollar cost per phase, per unit, per ticket.

## Install

Requires Python 3.11+, git, and the Claude Code CLI (`claude`) logged in.

```sh
pipx install git+https://github.com/alexandr352/hearthwork
# or: pip install --user git+https://github.com/alexandr352/hearthwork
operator doctor
```

## Use

```sh
operator init
operator project add shop --repo ~/code/shop
operator ticket new T-12 --title "Totals include tax" --file ticket.md
operator run                # one unit; see what it did
operator run -n 0           # keep going until it is ready or needs you
operator status
operator log                # prints the path of the work log page
```

When the operator needs you, it halts with a question. Answer it:

```sh
operator rule "Use the store's currency, never the browser's."
operator run
```

The ruling is kept with the ticket and binds every later unit.

### Unattended

`operator run` takes one unit and exits, so a scheduler is just cron:

```cron
*/20 8-18 * * 1-5  operator run -p shop --max-cost 5 >> ~/.hearthwork/cron.log 2>&1
```

A second run while one is working exits quietly. A usage limit ends the run; the next one
resumes the unit.

## The home

```
~/.hearthwork/                    (or $HEARTHWORK_HOME)
  config.toml                     models, timeouts, the claude binary
  worklog.html                    the work log, rebuilt after every unit
  spirit/                         the spirit (see below)
  projects/<name>/                the operator's own directory for one repository
    project.toml                  repository, trunk, protected branches, network commands
    knowledge.md                  what it has learned about the repository, with sources
    atlas.md                      the short map the executor reads first: edit it freely
    units.jsonl                   one line per unit: phases, models, seconds, cost
    tickets/<ID>/
      ticket.md  rulings.md  plan.md  context-full.md
      units/NN/  plan.json  prompt.md  report.md  facts.md  verdict.json
```

Everything is plain files. Read them, grep them, keep them in git if you like.

## The work log

`worklog.html` is a single self-contained page: every ticket as a strip of units (green,
amber when something was retried or recovered, red when it halted), each unit's prompt,
report, git facts and verdict one click away, and what it all cost today, this week and in
total. It is built by code from the records, never written by the model, and it refreshes
itself while open.

## The spirit

```sh
operator chat
```

opens Claude Code in the home, as the spirit that lives beside the loop. It knows where
the records are and how to read them: ask why unit 7 halted, what the ticket has cost,
what the operator believes about your auth module and where it learned it. It acts only
through `operator` commands (it will record your ruling on a halt, add a ticket, run a
unit when you say so), reads anything in the home and your repositories, and writes only
its own memory. Its voice is `spirit/persona.md`: replace it with whatever you like.

## The fence

Every tool call of every session passes a PreToolUse hook (`fence.py`), default-deny:

| | may | may not |
|---|---|---|
| executor | edit inside the checkout and /tmp; shell; git add/commit/branch on the ticket's branch; sub-agents in the foreground | push, fetch, reset, rebase, amend, skip hooks; touch protected branches; read or write elsewhere in your home; read secrets (~/.ssh, ~/.aws, .env, ...); network; sudo; background jobs |
| operator | read and write its own directory | anything else, including your repository |
| spirit | read the home and the repositories; write its memory; `operator ...`; read-only git | everything else |

Calls carry no MCP servers and only the tools their role needs, and none of your personal
CLAUDE.md files: each session gets its own doctrine and nothing else. `operator doctor`
warns if your settings disable hooks.

**It is a guard rail, not a sandbox.** It stops an honest session from wandering and the
common accidents; a determined process with a shell can get past any pattern check. For
unattended runs, use a separate OS user that owns only the checkout.

## Cost

Each unit is three or more Claude calls: a plan, the execution, a judgement. A small
investigation costs cents; a large change on a big codebase can cost a few dollars.
`--max-cost` stops a run once the spend reaches the limit, and `units.jsonl` holds every
call's cost. With `--resume`, the CLI reports a session's running total; hearthwork records
each call's own increment.

## Status

0.1: the loop, recovery, the fence, the work log and the spirit. Planned: an MCP mode
where your own interactive Claude Code session is the executor and you watch each edit,
a local server for the work log with the spirit's chat beside it, and ticket sources
beyond markdown files (GitHub Issues, Jira).

## License

MIT
