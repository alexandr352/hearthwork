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
operator atlas              # one read-only session drafts the project's map; review it
operator ticket new T-12 --title "Totals include tax" --file ticket.md
operator run                # one unit; see what it did
operator run -n 0           # keep going until it is ready or needs you
operator status
operator log                # prints the path of the work log page
operator ui                 # the work log, live, with the spirit's chat beside it
```

`operator ui` serves on 127.0.0.1 only and prints a link carrying a one-time key.

When the operator needs you, it halts with a question. Answer it:

```sh
operator rule "Use the store's currency, never the browser's."
operator run
```

The ruling is kept with the ticket and binds every later unit.

### With your own Claude Code session (MCP)

Register hearthwork once in the repository, then work the ticket from your usual session:

```sh
claude mcp add hearthwork -- operator mcp
claude
> work the next unit with hearthwork
```

Your session calls `next`, gets the unit and the executor's rules, does the work in front of
you (you approve each edit as usual), and calls `submit` with its report. The operator still
plans and judges in its own fenced session, and the program still reads git itself, so the
judge stays independent of whoever did the work. Planning and judging take minutes; the tools
say "still planning, call again" rather than hang. `operator run` will not touch a unit that
is open in your session; `operator abandon` drops one you walked away from.

### Unattended

`operator run` takes one unit and exits, so a scheduler is just cron:

```cron
*/20 8-18 * * 1-5  operator run -p shop --max-cost 5 >> ~/.hearthwork/cron.log 2>&1
```

A second run while one is working exits quietly. A usage limit ends the run; the next one
resumes the unit.

### Laptops and sleep

While a unit runs or the spirit answers, hearthwork holds the system's own sleep guard
(`caffeinate -i` on macOS, `systemd-inhibit` on Linux), tied to its process: the machine
stays awake for exactly as long as work is in flight, and the screen may still lock. A
closed lid still sleeps a laptop. If it does sleep mid-unit, nothing is lost: the unit is
surveyed and judged, or resumed. `[awake] on_ac = true` in config.toml also keeps a Mac
awake on mains power, and the page's "screen on" button keeps the display lit while the
tab is in front. `operator doctor` says whether the guard works on your machine.

## The home

```
~/.hearthwork/                    (or $HEARTHWORK_HOME)
  config.toml                     models, timeouts, the claude binary
  worklog.html                    the work log, rebuilt after every unit
  spirit/                         the spirit (see below)
  projects/<name>/                the operator's own directory for one repository
    project.toml                  repository, trunk, protected branches, network commands
    knowledge.md                  what it has learned about the repository, with sources
    atlas.md                      the short map the executor reads first: drafted by
                                  `operator atlas` from the repository, then yours to edit
    units.jsonl                   one line per unit: phases, models, seconds, cost
    tickets/<ID>/
      ticket.md  rulings.md  plan.md  context-full.md
      units/NN/  plan.json  prompt.md  report.md  facts.md  verdict.json
```

Everything is plain files. Read them, grep them, keep them in git if you like.

## The atlas

Every session reads the atlas before the tree, so nobody re-learns the project. On a new
project, `operator atlas` hands one read-only session (Sonnet, about $0.10 on a small
repository) a fixed brief: read the README, the manifests, the repository's own CLAUDE.md,
CI and test configuration, and return the map: how to install, build, test one file, lint;
where changes land; conventions; traps; and, at the end, the questions only you can answer.
Every fact names its source; nothing is guessed. You review it, answer the questions in the
file, and from then on the operator keeps it current from what units learn.
[examples/atlas-hearthwork.md](examples/atlas-hearthwork.md) is the unedited draft it made
of this repository. An atlas you
have edited is only redrafted with `--force`, and the old one is kept.

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

0.1: the loop, recovery, the fence, the work log with the spirit's chat (`operator ui`),
and MCP mode. Planned: ticket sources beyond markdown files (GitHub Issues, Jira).

## License

MIT
