# hearthwork

A plan → execute → judge loop for [Claude Code](https://claude.com/claude-code), with a
home, a work log, and a spirit you can talk to.

![The work log with the spirit's chat: a ticket's chain of units, what each one did and cost, your limits, and the spirit answering from the records](docs/screenshot.png)

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

- **The judge never sees the code.** The operator reasons from the executor's report and from
  facts the program reads from git; when the two disagree, the facts win.
- **Every answer has a contract, checked by code.** A broken answer goes back to the same
  session with the deviation named; three in a row halt the loop and ask you.
- **Investigation before execution.** No change is written on a hypothesis. Work that ends in
  one commit is a chain: what it needs to learn, the changes, and one committing unit.
- **Nothing is lost when something stops.** A usage limit, a crash, a closed laptop: the next
  run resumes, or surveys the tree and judges what is there.
- **You see everything.** A live page with every unit's prompt, report, git facts, verdict and
  cost; your 5-hour session and week; and a chat with a spirit that reads the records.

## Install

Python 3.10+, git, and the Claude Code CLI (`claude`), logged in.

```sh
python3 -m venv ~/.hearthwork-venv
~/.hearthwork-venv/bin/pip install git+https://github.com/alexandr352/hearthwork
echo 'export PATH="$HOME/.hearthwork-venv/bin:$PATH"' >> ~/.zshrc   # ~/.bashrc on bash
source ~/.zshrc
operator doctor
```

To update: `~/.hearthwork-venv/bin/pip install --force-reinstall --no-deps git+https://github.com/alexandr352/hearthwork`,
then `operator upgrade`. What changed: [CHANGELOG.md](CHANGELOG.md).

## Start

Two ways, and they meet in the middle.

**Talk to the spirit.** `operator ui` opens the work log with a chat beside it, and a banner
that always names the next step. Say hi: the spirit lists your repositories, registers the one
you pick, drafts its map, works through the questions only you can answer, creates a ticket
from text you paste, and runs each unit when you say go. It shows every command it runs.

**Or run the commands yourself:**

```sh
operator init
operator project add shop --repo ~/code/shop
operator atlas                 # one read-only session drafts the project's map
operator atlas questions       # what only you know; answer with: operator atlas answer 1 "..."
operator ticket new T-12 --title "Totals include tax" --file ticket.md
operator run                   # one unit; read what it did
operator run -n 0 --max-cost 5 # keep going until ready, a question, or $5
```

When the operator needs you, it halts with a question; answer with
`operator rule "your decision"`, which binds every later unit. Not sure what to do:
`operator next`.

A ticket ends as a local commit on its own branch, with your git identity. Nothing is pushed:
review it and push it yourself.

**From your own Claude Code session:** `claude mcp add hearthwork -- operator mcp`, then
"work the next unit with hearthwork"; you approve each edit. See [docs/mcp.md](docs/mcp.md).

**Unattended:** `operator run` takes one unit and exits, so a schedule is just cron:
`*/20 8-18 * * 1-5  operator run -p shop --max-cost 5`.

## Documentation

- [docs/commands.md](docs/commands.md): every command.
- [docs/how-it-works.md](docs/how-it-works.md): units, chains, contracts, recovery, memory,
  the records.
- [docs/safety.md](docs/safety.md): the fence, repository hooks, commits, token economy, your
  limits, sleep, the page.
- [docs/mcp.md](docs/mcp.md): working from your own Claude Code session.
- [examples/atlas-hearthwork.md](examples/atlas-hearthwork.md): the unedited atlas
  `operator atlas` drafted of this repository.

## Status

0.2: the loop and its recovery, the fence, the work log with archive and stats, the spirit,
MCP mode, the atlas, token economy, your limits. Planned: ticket sources beyond text (GitHub
Issues, Jira).

Security: see [SECURITY.md](SECURITY.md). License: MIT.
